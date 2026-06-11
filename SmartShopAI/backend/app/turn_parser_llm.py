from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import ValidationError

from .concurrency import llm_slot
from .llm_client import LLMGenerationError, _env_value, _extract_content, _timeout_seconds, llm_model_name
from .turn_schema import ParsedTurnCandidate


TURN_PARSER_SYSTEM_PROMPT = """
你是电商导购系统的 turn parser。
你的任务是把用户当前输入解析为结构化 ParsedTurnCandidate JSON。
你不能推荐商品，不能编造商品，不能生成自然语言导购回答。
你只能输出一个 JSON object，字段必须符合 ParsedTurnCandidate schema。

必须遵守：
1. 找商品、推荐商品、筛选商品：intent_type=product_search 或 filter_refinement。
2. 问“第一个/第二个/这个/刚才那个”的价格、库存、参数：intent_type=product_detail_qa，并输出 references。
3. 加入、删除、修改购物车：intent_type=cart_add/cart_remove/cart_update_quantity，并输出 references 和 quantity。
4. 比较两个或多个商品：intent_type=product_compare，并输出 references 和 compare_dimensions。
5. “蓝牙”“防水”“轻薄”等属性孤词且没有上下文：needs_clarification=true，并给出 clarification_question。
6. “配一套/搭配/组合/清单/方案/全家桶”，尤其带“互联/生态/协同/跨屏/同品牌”时，intent_type=bundle_recommendation。
7. 只输出语义候选：intent_type、proposed_tool、core_product_query、product_mentions、query_expansions、品牌、否定、属性、场景、引用、数量、对比维度。
8. 不要输出 required_terms、match_mode、allow_popular_fallback、allow_dense_only、require_lexical_anchor、product_id、cart_item_id。
9. 不要把没有明确出现的品牌、价格、库存、商品功能写进结果。
10. 不要输出商品推荐、价格、库存、商品卡片或 SQL。
11. 如果用户用口语或隐含表达描述商品，在 query_expansions 输出 2-5 个常见商品名/类目同义词。
    例如：“家里打印机没墨水了” -> ["打印机墨水", "墨盒", "打印耗材"]。
"""


async def parse_turn_with_llm(
    message: str,
    chat_history: list[dict] | None,
    conversation_state: dict | None,
    catalog_summary: dict | None,
) -> ParsedTurnCandidate:
    api_key = _env_value("POE_API_KEY")
    if not api_key:
        raise LLMGenerationError("POE_API_KEY is not configured")

    base_url = (_env_value("POE_BASE_URL", "https://api.poe.com/v1") or "https://api.poe.com/v1").rstrip("/")
    model = llm_model_name()
    payload = {
        "message": message,
        "chat_history": chat_history or [],
        "conversation_state": conversation_state or {},
        "catalog_summary": catalog_summary or {},
        "schema": ParsedTurnCandidate.model_json_schema(),
    }
    # turn parser prompt 只输出结构化意图候选，不做商品推荐，也不生成自然语言回答。
    user_prompt = (
        "解析下面输入，只输出 JSON object，不要 markdown，不要解释。\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )

    try:
        async with llm_slot():
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
            parsed = ParsedTurnCandidate.model_validate(data)
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
