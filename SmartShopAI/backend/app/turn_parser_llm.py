from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import ValidationError

from .llm_client import LLMGenerationError, _env_value, _extract_content, _timeout_seconds
from .turn_schema import ParsedTurn


TURN_PARSER_SYSTEM_PROMPT = """
你是电商导购系统的 turn parser。
你的任务是把用户当前输入解析为结构化 JSON。
你不能推荐商品，不能编造商品，不能生成自然语言导购回答。
你只能输出一个 JSON object，字段必须符合 ParsedTurn schema。

必须遵守：
1. 找商品、推荐商品、筛选商品：intent_type=product_search 或 filter_refinement。
2. 问“第一个/第二个/这个/刚才那个”的价格、库存、参数：intent_type=product_detail_qa，并输出 references。
3. 加入、删除、修改购物车：intent_type=cart_add/cart_remove/cart_update_quantity，并输出 references 和 quantity。
4. 比较两个或多个商品：intent_type=product_compare，并输出 references 和 compare_dimensions。
5. “蓝牙”“防水”“轻薄”等属性孤词且没有上下文：needs_clarification=true，route_hint=no_tool。
6. “手柄”“足球”等未知短词不要扩展成相似品类；required_terms=[原词]，match_mode=exact_or_none，allow_popular_fallback=false。
7. 不要把没有明确出现的品牌、价格、库存、商品功能写进结果。
8. 不要输出商品推荐、价格、库存、商品卡片或 SQL。
"""


async def parse_turn_with_llm(
    message: str,
    chat_history: list[dict] | None,
    conversation_state: dict | None,
    catalog_summary: dict | None,
) -> ParsedTurn:
    api_key = _env_value("POE_API_KEY")
    if not api_key:
        raise LLMGenerationError("POE_API_KEY is not configured")

    base_url = (_env_value("POE_BASE_URL", "https://api.poe.com/v1") or "https://api.poe.com/v1").rstrip("/")
    model = _env_value("QWEN_MODEL", "qwen3.6-plus") or "qwen3.6-plus"
    payload = {
        "message": message,
        "chat_history": chat_history or [],
        "conversation_state": conversation_state or {},
        "catalog_summary": catalog_summary or {},
        "schema": ParsedTurn.model_json_schema(),
    }
    user_prompt = (
        "解析下面输入，只输出 JSON object，不要 markdown，不要解释。\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(_timeout_seconds(), connect=8.0)) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": TURN_PARSER_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0,
                    "max_tokens": 900,
                },
            )
            response.raise_for_status()
            content = _extract_content(response.json())
            data = json.loads(_extract_json_object(content))
            parsed = ParsedTurn.model_validate(data)
            return parsed.model_copy(update={"raw_message": parsed.raw_message or message, "source": "llm"})
    except (json.JSONDecodeError, ValidationError) as exc:
        raise LLMGenerationError("turn parser returned invalid JSON") from exc
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        raise LLMGenerationError(f"turn parser HTTP status {status_code}") from exc
    except httpx.TimeoutException as exc:
        raise LLMGenerationError("turn parser timed out") from exc
    except httpx.HTTPError as exc:
        raise LLMGenerationError("turn parser network error") from exc


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
