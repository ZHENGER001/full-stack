from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx

from .concurrency import llm_slot
from .config import BASE_DIR, _load_env_file
from .timeouts import llm_connect_timeout_seconds, llm_timeout_seconds


class LLMGenerationError(RuntimeError):
    """Raised when the optional Poe/Qwen generation path is unavailable."""


@dataclass(frozen=True)
class LLMGenerationResult:
    content: str
    provider: str
    model: str


def _env_value(name: str, default: str | None = None) -> str | None:
    env_file = _load_env_file(BASE_DIR / ".env")
    return os.getenv(name) or env_file.get(name) or default


def _timeout_seconds() -> float:
    return llm_timeout_seconds()


def llm_model_name() -> str:
    return _env_value("LLM_MODEL") or _env_value("QWEN_MODEL") or "gemini-3.5-flash"


def _compact_product(product: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": product.get("id"),
        "title": product.get("title"),
        "brand": product.get("brand"),
        "category": product.get("category"),
        "subcategory": product.get("subcategory"),
        "price": product.get("price"),
        "rating": product.get("rating"),
        "stock": product.get("stock"),
        "sku_summary": product.get("sku_summary"),
        "faq_summary": product.get("faq_summary"),
        "review_summary": product.get("review_summary"),
        "reason": product.get("reason"),
        "marketing_description": product.get("marketing_description"),
    }


def _compact_history(chat_history: list[dict] | None) -> list[dict[str, str]]:
    if not chat_history:
        return []
    compacted: list[dict[str, str]] = []
    for item in chat_history[-6:]:
        role = str(item.get("role", "user"))
        if role not in {"user", "assistant"}:
            role = "user"
        content = str(item.get("content", ""))[:600]
        if content:
            compacted.append({"role": role, "content": content})
    return compacted


def _extract_content(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMGenerationError("LLM response has no choices")
    message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts).strip()
    raise LLMGenerationError("LLM response content is invalid")


def _extract_stream_delta(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    choice = choices[0] if isinstance(choices[0], dict) else {}
    delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
    content = delta.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    text = choice.get("text")
    return text if isinstance(text, str) else ""


def _build_chat_completion_request(
    user_message: str,
    retrieved_products: list[dict],
    faq_context: list[dict] | None = None,
    chat_history: list[dict] | None = None,
    *,
    stream: bool = False,
) -> tuple[str, dict[str, str], dict[str, Any], str]:
    api_key = _env_value("POE_API_KEY")
    if not api_key:
        raise LLMGenerationError("POE_API_KEY is not configured")

    base_url = (_env_value("POE_BASE_URL", "https://api.poe.com/v1") or "https://api.poe.com/v1").rstrip("/")
    model = llm_model_name()
    products = [_compact_product(product) for product in retrieved_products]
    grounded_context = {
        "user_message": user_message,
        "retrieved_products": products,
        "faq_context": faq_context or [],
        "chat_history": _compact_history(chat_history),
    }
    # 导购回答 prompt 是 grounded writer：只能基于 retrieved_products/faq_context 写话术。
    # 商品集合已经由 RAG 决定，LLM 不允许新增商品、价格、库存或功能事实。
    system_prompt = (
        "你是 SmartShop AI 导购助手。你只能基于系统提供的 retrieved_products 和 faq_context 回答。"
        "严格规则：只能推荐 retrieved_products 中的商品；不能编造商品、价格、库存、SKU、折扣、品牌、评分或功能；"
        "如果 retrieved_products 为空，直接说明没有找到合适商品；用户明确指定品类时，只能推荐该品类或高度相关品类商品；"
        "如果候选商品品类明显不匹配用户需求，不要强行推荐；回复最多 120 个中文字符；"
        "不要在文本中逐条列出完整商品清单，因为前端会展示商品卡片；只输出自然语言导购说明，不要输出 JSON；"
        "不要说“我不会编造价格、库存或 SKU”这类系统说明。推荐理由只总结排序依据，例如价格、库存、评分、功能匹配。"
    )
    user_prompt = (
        "请用两句话回答：第一句说明是否找到匹配商品；第二句简要说明推荐依据。不要逐条列商品。\n"
        f"{json.dumps(grounded_context, ensure_ascii=False)}"
    )
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 180,
    }
    if stream:
        payload["stream"] = True
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    return f"{base_url}/chat/completions", headers, payload, model


async def generate_agent_reply(
    user_message: str,
    retrieved_products: list[dict],
    faq_context: list[dict] | None = None,
    chat_history: list[dict] | None = None,
) -> str | None:
    try:
        result = await generate_agent_reply_with_status(user_message, retrieved_products, faq_context, chat_history)
        return result.content
    except LLMGenerationError:
        return None


async def generate_agent_reply_with_status(
    user_message: str,
    retrieved_products: list[dict],
    faq_context: list[dict] | None = None,
    chat_history: list[dict] | None = None,
) -> LLMGenerationResult:
    try:
        url, headers, payload, model = _build_chat_completion_request(
            user_message,
            retrieved_products,
            faq_context,
            chat_history,
        )
        timeout_seconds = _timeout_seconds()
        async with llm_slot():
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds, connect=llm_connect_timeout_seconds())) as client:
                response = await client.post(
                    url,
                    headers=headers,
                    json=payload,
                )
            response.raise_for_status()
            content = _extract_content(response.json())
            if not content:
                raise LLMGenerationError("LLM response is empty")
            return LLMGenerationResult(content=content, provider="poe", model=model)
    except LLMGenerationError:
        raise
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        raise LLMGenerationError(f"LLM HTTP status {status_code}") from exc
    except httpx.TimeoutException as exc:
        raise LLMGenerationError("LLM request timed out") from exc
    except httpx.HTTPError as exc:
        raise LLMGenerationError("LLM network error") from exc
    except Exception as exc:
        raise LLMGenerationError("LLM generation failed") from exc


async def stream_agent_reply_chunks_with_status(
    user_message: str,
    retrieved_products: list[dict],
    faq_context: list[dict] | None = None,
    chat_history: list[dict] | None = None,
) -> AsyncIterator[str]:
    try:
        url, headers, payload, _model = _build_chat_completion_request(
            user_message,
            retrieved_products,
            faq_context,
            chat_history,
            stream=True,
        )
        timeout_seconds = _timeout_seconds()
        async with llm_slot():
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds, connect=llm_connect_timeout_seconds())) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    response.raise_for_status()
                    async for raw_line in response.aiter_lines():
                        line = raw_line.strip()
                        if not line:
                            continue
                        if line.startswith("data:"):
                            data_text = line.removeprefix("data:").strip()
                        elif line.startswith("{"):
                            data_text = line
                        else:
                            continue
                        if data_text == "[DONE]":
                            break
                        data = json.loads(data_text)
                        if line.startswith("{"):
                            content = _extract_content(data)
                        else:
                            content = _extract_stream_delta(data)
                        if content:
                            yield content
    except LLMGenerationError:
        raise
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        raise LLMGenerationError(f"LLM HTTP status {status_code}") from exc
    except httpx.TimeoutException as exc:
        raise LLMGenerationError("LLM request timed out") from exc
    except httpx.HTTPError as exc:
        raise LLMGenerationError("LLM network error") from exc
    except Exception as exc:
        raise LLMGenerationError("LLM streaming failed") from exc


async def generate_product_presentations(
    user_message: str,
    products: list[dict[str, Any]],
) -> dict[str, dict[str, str]]:
    if not products:
        return {}
    api_key = _env_value("POE_API_KEY")
    if not api_key:
        raise LLMGenerationError("POE_API_KEY is not configured")

    base_url = (_env_value("POE_BASE_URL", "https://api.poe.com/v1") or "https://api.poe.com/v1").rstrip("/")
    model = llm_model_name()
    compact_products = [
        {
            "id": item.get("id"),
            "title": item.get("title"),
            "brand": item.get("brand"),
            "category": item.get("category"),
            "subcategory": item.get("subcategory"),
            "price": item.get("price"),
            "rating": item.get("rating"),
            "stock": item.get("stock"),
            "sku_summary": item.get("sku_summary"),
            "reason": item.get("reason"),
            "marketing_description": item.get("marketing_description"),
            "review_summary": item.get("review_summary"),
            "faq_summary": item.get("faq_summary"),
        }
        for item in products[:6]
    ]
    # 商品卡片文案 prompt 只生成展示标签和推荐理由，不影响召回、排序或过滤结果。
    system_prompt = (
        "你是电商导购商品展示文案生成器。只能基于输入商品事实和用户需求生成。"
        "不要编造优惠、销量、库存、功能、品牌、价格或活动。"
        "为每个商品输出 recommendation_title 和 reason。"
        "title 必须是中文短标签，不超过 8 个汉字；reason 不超过 70 个中文字符。"
        "不能输出英文技术词，如 RRF、BM25、retrieval、score。只输出 JSON object。"
    )
    user_prompt = json.dumps(
        {
            "user_message": user_message,
            "products": compact_products,
            "output_schema": {
                "items": [
                    {
                        "id": "商品 id",
                        "recommendation_title": "不超过8字中文标签",
                        "reason": "不超过70字推荐理由",
                    }
                ]
            },
        },
        ensure_ascii=False,
    )
    try:
        async with llm_slot():
            async with httpx.AsyncClient(timeout=httpx.Timeout(_timeout_seconds(), connect=llm_connect_timeout_seconds())) as client:
                response = await client.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.2,
                        "max_tokens": 1000,
                    },
                )
            response.raise_for_status()
            content = _extract_content(response.json())
            data = json.loads(_extract_json_object(content))
            items = data.get("items") if isinstance(data, dict) else None
            if not isinstance(items, list):
                raise LLMGenerationError("presentation JSON has no items")
            result: dict[str, dict[str, str]] = {}
            for item in items:
                if not isinstance(item, dict):
                    continue
                product_id = str(item.get("id") or "").strip()
                title = sanitize_presentation_text(str(item.get("recommendation_title") or ""), 12)
                reason = sanitize_presentation_text(str(item.get("reason") or ""), 90)
                if product_id and title and reason:
                    result[product_id] = {"recommendation_title": title, "reason": reason}
            return result
    except LLMGenerationError:
        raise
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        raise LLMGenerationError(f"presentation HTTP status {status_code}") from exc
    except httpx.TimeoutException as exc:
        raise LLMGenerationError("presentation timed out") from exc
    except httpx.HTTPError as exc:
        raise LLMGenerationError("presentation network error") from exc
    except Exception as exc:
        raise LLMGenerationError("presentation generation failed") from exc


async def generate_preference_answer_with_status(
    user_message: str,
    fallback_answer: str,
    conversation_state: dict[str, Any] | None = None,
) -> LLMGenerationResult:
    api_key = _env_value("POE_API_KEY")
    if not api_key:
        raise LLMGenerationError("POE_API_KEY is not configured")
    base_url = (_env_value("POE_BASE_URL", "https://api.poe.com/v1") or "https://api.poe.com/v1").rstrip("/")
    model = llm_model_name()
    memory = (conversation_state or {}).get("structured_memory") or (conversation_state or {}).get("structured_state") or {}
    payload = {
        "user_question": user_message,
        "category": memory.get("category"),
        "subcategory": memory.get("subcategory"),
        "budget_max": memory.get("budget_max"),
        "fallback_answer": fallback_answer,
        "strict_rules": [
            "只解释偏好取舍，不推荐具体商品",
            "不能切换到其他品类",
            "不能编造商品、价格、库存或参数",
            "最后必须追问一个使用场景问题",
            "回答不超过90个中文字符",
        ],
    }
    # 偏好解释 prompt 只回答取舍问题，不推荐具体商品，避免绕过 RAG 商品集合。
    system_prompt = (
        "你是电商导购偏好取舍解释器。只基于输入的品类、问题和 fallback_answer 改写自然语言。"
        "不要输出商品清单、品牌对比、表格、JSON 或 Markdown。"
    )
    try:
        async with llm_slot():
            async with httpx.AsyncClient(timeout=httpx.Timeout(_timeout_seconds(), connect=llm_connect_timeout_seconds())) as client:
                response = await client.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                        ],
                        "temperature": 0.25,
                        "max_tokens": 180,
                    },
                )
            response.raise_for_status()
            content = sanitize_preference_answer(_extract_content(response.json()))
            if not content:
                raise LLMGenerationError("preference answer is empty")
            return LLMGenerationResult(content=content, provider="poe", model=model)
    except LLMGenerationError:
        raise
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        raise LLMGenerationError(f"preference HTTP status {status_code}") from exc
    except httpx.TimeoutException as exc:
        raise LLMGenerationError("preference timed out") from exc
    except httpx.HTTPError as exc:
        raise LLMGenerationError("preference network error") from exc
    except Exception as exc:
        raise LLMGenerationError("preference generation failed") from exc


def sanitize_preference_answer(text: str) -> str:
    cleaned = " ".join((text or "").strip().split())
    forbidden = ("RRF", "BM25", "retrieval", "score", "SQL", "{", "}", "|")
    if not cleaned or any(token.lower() in cleaned.lower() for token in forbidden):
        return ""
    return cleaned[:140].rstrip("，。；; ")


def sanitize_presentation_text(text: str, max_length: int) -> str:
    cleaned = " ".join((text or "").strip().split())
    forbidden = ("RRF", "BM25", "retrieval", "score", "Matched by", "dense", "keyword")
    if not cleaned or any(token.lower() in cleaned.lower() for token in forbidden):
        return ""
    return cleaned[:max_length].rstrip("，,。 ")


def _extract_json_object(content: str) -> str:
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise json.JSONDecodeError("No JSON object found", text, 0)
    return text[start : end + 1]
