from __future__ import annotations

import json
import re
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from .llm_client import LLMGenerationError, _env_value, _extract_content, _timeout_seconds, llm_model_name
from .turn_schema import ProductReference


ReactAction = Literal["cart_add", "checkout", "cart_remove", "cart_update_quantity", "cart_list", "none"]
RULE_BATCH_REFERENCE_REASON = "规则识别批量引用"


class ReactPlanStep(BaseModel):
    action: ReactAction
    product_reference: Literal["current_product", "last_product", "position", "product_id"] | None = None
    position: int | None = Field(default=None, ge=1)
    product_id: str | None = None
    sku_hint: str | None = None
    quantity: int | None = Field(default=None, ge=1)
    use_default_address: bool = False
    confirm_payment: bool = False
    reason: str | None = None


class ReactTransactionPlan(BaseModel):
    should_execute: bool = False
    requires_confirmation: bool = False
    confidence: float = Field(default=0.0, ge=0, le=1)
    steps: list[ReactPlanStep] = Field(default_factory=list)
    question: str | None = None

    def first_step(self, action: ReactAction) -> ReactPlanStep | None:
        for step in self.steps:
            if step.action == action:
                return step
        return None


REACT_PLANNER_SYSTEM_PROMPT = """
你是电商交易 Agent 的 ReAct planner。
你只负责把用户自然语言归一成工具步骤，不执行工具，不推荐商品，不编造商品事实。

允许动作：
- cart_add：加入购物车，需要 product_reference，可带 sku_hint 和 quantity。
- checkout：下单/支付，只能在用户明确表达购买、付款、下单、默认地址、直接买时输出。
- cart_remove/cart_update_quantity/cart_list：购物车 CRUD。
- none：不是交易执行请求。

安全规则：
1. 用户只是咨询、推荐、比较、问价格时，不要输出 checkout。
2. 用户说“直接买/下单吧/按默认地址走/付款/去支付”才允许 checkout.confirm_payment=true。
3. 如果用户说“这双/这款/刚才那款/第一款”，要输出对应 product_reference。
4. 如果用户说“42/42码/黑色/256G”等规格，写入 sku_hint。
5. 只输出 JSON object，不要 markdown，不要解释。
"""


async def plan_react_transaction(
    message: str,
    chat_history: list[dict[str, str]],
    conversation_state: dict[str, Any],
) -> ReactTransactionPlan:
    fallback = plan_react_transaction_with_rules(message, conversation_state)
    if is_rule_resolved_reference_plan(fallback):
        return fallback
    if not should_call_react_llm(message):
        return fallback

    api_key = _env_value("POE_API_KEY")
    if not api_key:
        return fallback

    base_url = (_env_value("POE_BASE_URL", "https://api.poe.com/v1") or "https://api.poe.com/v1").rstrip("/")
    payload = {
        "message": message,
        "recent_chat_history": chat_history[-6:],
        "conversation_state": compact_conversation_state(conversation_state),
        "schema": ReactTransactionPlan.model_json_schema(),
    }
    user_prompt = "把下面输入规划成工具步骤，只输出 JSON object。\n" + json.dumps(payload, ensure_ascii=False)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(_timeout_seconds(), connect=8.0)) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": llm_model_name(),
                    "messages": [
                        {"role": "system", "content": REACT_PLANNER_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0,
                    "max_tokens": 800,
                },
            )
            response.raise_for_status()
            data = json.loads(extract_json_object(_extract_content(response.json())))
            plan = ReactTransactionPlan.model_validate(data)
            if not is_safe_react_plan(message, plan):
                return fallback
            return plan if plan.confidence >= fallback.confidence else fallback
    except (json.JSONDecodeError, ValidationError, httpx.HTTPError, LLMGenerationError):
        return fallback


def should_call_react_llm(message: str) -> bool:
    text = message.strip()
    if not text:
        return False
    return any(term in text for term in TRANSACTION_TERMS) and not any(term in text for term in CONSULT_ONLY_TERMS)


def plan_react_transaction_with_rules(message: str, conversation_state: dict[str, Any]) -> ReactTransactionPlan:
    text = message.strip()
    if not should_call_react_llm(text):
        return ReactTransactionPlan()
    wants_checkout = has_checkout_signal(text)
    wants_cart_add = has_cart_add_signal(text) or (wants_checkout and has_product_reference_signal(text, conversation_state))
    if wants_checkout and has_unresolved_product_reference_signal(text):
        wants_cart_add = True
    if not wants_cart_add and not wants_checkout:
        return ReactTransactionPlan()

    steps: list[ReactPlanStep] = []
    if wants_cart_add:
        positions = infer_product_reference_positions(text, conversation_state)
        if positions:
            steps.extend(
                ReactPlanStep(
                    action="cart_add",
                    product_reference="position",
                    position=position,
                    sku_hint=extract_sku_hint(text),
                    quantity=1,
                    reason=RULE_BATCH_REFERENCE_REASON,
                )
                for position in positions
            )
        elif has_structured_multi_product_reference(text):
            return ReactTransactionPlan()
        else:
            ref_type, position = infer_product_reference(text, conversation_state)
            steps.append(
                ReactPlanStep(
                    action="cart_add",
                    product_reference=ref_type,
                    position=position,
                    sku_hint=extract_sku_hint(text),
                    quantity=extract_quantity_hint(text) or 1,
                    reason="自然语言购买意图归一为加购",
                )
            )
    if wants_checkout:
        steps.append(
            ReactPlanStep(
                action="checkout",
                use_default_address=has_default_address_signal(text),
                confirm_payment=has_checkout_signal(text),
                reason="用户明确表达下单/支付",
            )
        )
    return ReactTransactionPlan(
        should_execute=bool(steps),
        requires_confirmation=False,
        confidence=0.68 if wants_cart_add and wants_checkout else 0.55,
        steps=steps,
    )


def is_rule_resolved_reference_plan(plan: ReactTransactionPlan) -> bool:
    return any(step.action == "cart_add" and step.reason == RULE_BATCH_REFERENCE_REASON for step in plan.steps)


def is_safe_react_plan(message: str, plan: ReactTransactionPlan) -> bool:
    if not plan.should_execute:
        return True
    checkout = plan.first_step("checkout")
    if checkout and not has_checkout_signal(message):
        return False
    return True


def compact_conversation_state(conversation_state: dict[str, Any]) -> dict[str, Any]:
    return {
        "last_query": conversation_state.get("last_query"),
        "last_recommended_product_ids": conversation_state.get("last_recommended_product_ids") or [],
        "current_product_id": conversation_state.get("current_product_id"),
        "cart_context": (conversation_state.get("cart_context") or [])[:5],
    }


def product_reference_from_step(step: ReactPlanStep) -> list[ProductReference]:
    reference_type = step.product_reference or "current_product"
    return [
        ProductReference(
            reference_type=reference_type,
            position=step.position,
            product_id=step.product_id,
            raw_text=step.reason or reference_type,
        )
    ]


def message_with_sku_hint(message: str, step: ReactPlanStep) -> str:
    sku_hint = (step.sku_hint or "").strip()
    if not sku_hint or sku_hint in message:
        return message
    return f"{message} {sku_hint}"


def extract_json_object(content: str) -> str:
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


def has_checkout_signal(text: str) -> bool:
    return any(term in text for term in ("直接买", "买了", "下单", "付款", "支付", "去支付", "按默认地址", "默认地址", "地址用默认", "拿下", "走"))


def has_cart_add_signal(text: str) -> bool:
    return any(term in text for term in ("加入购物车", "加购物车", "加购", "放购物车", "加入", "加到购物车", "拿"))


def has_default_address_signal(text: str) -> bool:
    return any(term in text for term in ("默认地址", "按默认地址", "地址用默认", "用默认地址"))


def has_product_reference_signal(text: str, conversation_state: dict[str, Any]) -> bool:
    return bool(conversation_state.get("current_product_id") or conversation_state.get("last_recommended_product_ids")) and any(
        term in text for term in ("这双", "这款", "这个", "刚才", "刚刚", "第一", "第二", "第三")
    )


def has_unresolved_product_reference_signal(text: str) -> bool:
    return any(term in text for term in ("这双", "这款", "这个", "刚才", "刚刚", "第一", "第二", "第三"))


def infer_product_reference_positions(text: str, conversation_state: dict[str, Any]) -> list[int]:
    recent_count = recent_recommendation_count(conversation_state)
    if recent_count <= 0:
        return []

    ordinal_positions = valid_recent_positions(extract_ordinal_positions(text), recent_count)
    if len(ordinal_positions) > 1:
        return ordinal_positions

    number_list_positions = valid_recent_positions(extract_number_list_positions(text), recent_count)
    if number_list_positions:
        return number_list_positions

    range_positions = extract_range_positions(text, recent_count)
    if range_positions:
        return range_positions

    if has_all_recent_reference(text):
        return list(range(1, recent_count + 1))

    return []


def has_structured_multi_product_reference(text: str) -> bool:
    if len(extract_ordinal_positions(text)) > 1:
        return True
    if extract_number_list_positions(text):
        return True
    if re.search(r"(?:前|头|最后|后)\s*[一二两三四五六七八九十\d]+\s*(?:款|个|双|台|件)?", text):
        return True
    return has_all_recent_reference(text)


def recent_recommendation_count(conversation_state: dict[str, Any]) -> int:
    recent_ids = conversation_state.get("last_recommended_product_ids") or []
    if not isinstance(recent_ids, (list, tuple)):
        return 0
    return len(recent_ids)


def extract_ordinal_positions(text: str) -> list[int]:
    positions: list[int] = []
    for match in re.finditer(r"第\s*([一二两三四五六七八九十\d]+)\s*(?:款|个|双|台|件)?", text):
        number = parse_reference_number(match.group(1))
        if number is not None:
            positions.append(number)
    return positions


def extract_number_list_positions(text: str) -> list[int]:
    match = re.search(r"(?<![\dA-Za-z])\d{1,2}(?:\s*(?:[,，、]|和|与|及|跟)\s*\d{1,2})+(?![\dA-Za-z])", text)
    if not match:
        return []
    return [int(token) for token in re.findall(r"\d{1,2}", match.group(0))]


def extract_range_positions(text: str, recent_count: int) -> list[int]:
    front_match = re.search(r"(?:前|头)\s*([一二两三四五六七八九十\d]+)\s*(?:款|个|双|台|件)?", text)
    if front_match:
        count = parse_reference_number(front_match.group(1))
        if count and 1 <= count <= recent_count:
            return list(range(1, count + 1))

    back_match = re.search(r"(?:最后|后)\s*([一二两三四五六七八九十\d]+)\s*(?:款|个|双|台|件)?", text)
    if back_match:
        count = parse_reference_number(back_match.group(1))
        if count and 1 <= count <= recent_count:
            return list(range(recent_count - count + 1, recent_count + 1))

    return []


def has_all_recent_reference(text: str) -> bool:
    return any(term in text for term in ("全部", "全都", "所有", "都"))


def valid_recent_positions(positions: list[int], recent_count: int) -> list[int]:
    if not positions:
        return []
    deduped: list[int] = []
    for position in positions:
        if position < 1 or position > recent_count:
            return []
        if position not in deduped:
            deduped.append(position)
    return deduped


def parse_reference_number(token: str) -> int | None:
    token = token.strip()
    if token.isdigit():
        return int(token)

    number_map = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    if token in number_map:
        return number_map[token]
    if token == "十":
        return 10
    if token.startswith("十"):
        return 10 + number_map.get(token[1:], 0)
    if "十" in token:
        left, right = token.split("十", 1)
        tens = number_map.get(left)
        if tens is None:
            return None
        return tens * 10 + (number_map.get(right, 0) if right else 0)
    return None


def infer_product_reference(text: str, conversation_state: dict[str, Any]) -> tuple[Literal["current_product", "last_product", "position", "product_id"], int | None]:
    match = re.search(r"第\s*([一二两三四五\d]+)\s*(款|个|双)", text)
    if match:
        token = match.group(1)
        return "position", parse_reference_number(token) or 1
    if any(term in text for term in ("刚才", "刚刚", "上一", "上一个")):
        return "last_product", None
    if conversation_state.get("current_product_id"):
        return "current_product", None
    return "position", 1


def extract_sku_hint(text: str) -> str | None:
    size_match = re.search(r"(\d{2}(?:\.\d)?)\s*码?", text)
    if size_match:
        return size_match.group(1)
    storage_match = re.search(r"(\d{2,4}\s*(?:g|gb|G|GB|G版|GB版))", text)
    if storage_match:
        return storage_match.group(1).replace(" ", "")
    color_match = re.search(r"(黑色|白色|蓝色|红色|灰色|银色|金色|粉色|绿色)", text)
    if color_match:
        return color_match.group(1)
    return None


def extract_quantity_hint(text: str) -> int | None:
    match = re.search(r"(\d+)\s*(件|个|双|台|份)", text)
    if match:
        return int(match.group(1))
    number_map = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5}
    match = re.search(r"([一二两三四五])\s*(件|个|双|台|份)", text)
    return number_map.get(match.group(1)) if match else None


TRANSACTION_TERMS = {
    "买",
    "下单",
    "付款",
    "支付",
    "购物车",
    "加购",
    "加入",
    "拿下",
    "默认地址",
    "地址用默认",
    "删",
    "删除",
    "数量",
}
CONSULT_ONLY_TERMS = {"推荐", "介绍", "对比", "比较", "看看", "有没有", "怎么选"}
