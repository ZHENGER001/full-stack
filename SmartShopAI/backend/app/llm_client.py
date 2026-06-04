from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import httpx

from .config import BASE_DIR, _load_env_file


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
    raw_value = _env_value("LLM_TIMEOUT_SECONDS", "25")
    try:
        return max(float(raw_value or "25"), 25.0)
    except ValueError:
        return 25.0


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
    api_key = _env_value("POE_API_KEY")
    if not api_key:
        raise LLMGenerationError("POE_API_KEY is not configured")

    base_url = (_env_value("POE_BASE_URL", "https://api.poe.com/v1") or "https://api.poe.com/v1").rstrip("/")
    model = _env_value("QWEN_MODEL", "qwen3.6-plus") or "qwen3.6-plus"
    products = [_compact_product(product) for product in retrieved_products]
    grounded_context = {
        "user_message": user_message,
        "retrieved_products": products,
        "faq_context": faq_context or [],
        "chat_history": _compact_history(chat_history),
    }
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

    try:
        timeout_seconds = _timeout_seconds()
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds, connect=8.0)) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 180,
                },
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
