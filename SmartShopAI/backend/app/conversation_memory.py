from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from .turn_schema import ParsedTurn, TurnConstraints


STRUCTURED_MEMORY_KEY = "structured_memory"


def empty_structured_memory() -> dict[str, Any]:
    return {
        "current_task": None,
        "last_intent": None,
        "last_query": None,
        "category": None,
        "subcategory": None,
        "budget_min": None,
        "budget_max": None,
        "brands_include": [],
        "brands_exclude": [],
        "attributes_include": [],
        "attributes_exclude": [],
        "scene_terms": [],
        "size_hint": None,
        "last_product_ids": [],
        "current_product_id": None,
        "pending_question": None,
        "cart_item_count": 0,
        "updated_at": None,
    }


def parse_structured_memory(raw: str | None) -> dict[str, Any]:
    memory = empty_structured_memory()
    if not raw:
        return memory
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return memory
    if not isinstance(payload, dict):
        return memory
    memory.update({key: value for key, value in payload.items() if key in memory})
    for key in [
        "brands_include",
        "brands_exclude",
        "attributes_include",
        "attributes_exclude",
        "scene_terms",
        "last_product_ids",
    ]:
        memory[key] = _dedupe_texts(memory.get(key) or [])
    return memory


def dump_structured_memory(memory: dict[str, Any]) -> str:
    normalized = empty_structured_memory()
    normalized.update({key: value for key, value in memory.items() if key in normalized})
    normalized["updated_at"] = datetime.now(timezone.utc).isoformat()
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))


def apply_memory_to_parsed_turn(parsed: ParsedTurn, conversation_state: dict | None) -> ParsedTurn:
    memory = _memory_from_state(conversation_state)
    if not memory or not _should_inherit_memory(parsed):
        return parsed

    constraints = parsed.constraints.model_copy(deep=True)
    inherited = False

    if not constraints.categories and memory.get("category"):
        constraints.categories = [str(memory["category"])]
        inherited = True
    if not constraints.subcategories and memory.get("subcategory"):
        constraints.subcategories = [str(memory["subcategory"])]
        inherited = True
    if constraints.price.min is None and memory.get("budget_min") is not None:
        constraints.price.min = float(memory["budget_min"])
        inherited = True
    if constraints.price.max is None and memory.get("budget_max") is not None:
        constraints.price.max = float(memory["budget_max"])
        inherited = True

    constraints.brands_include = _merge_if_empty_or_refining(
        constraints.brands_include,
        memory.get("brands_include"),
        parsed.intent_type == "filter_refinement",
    )
    constraints.brands_exclude = _merge_lists(constraints.brands_exclude, memory.get("brands_exclude"))
    constraints.attributes_include = _merge_lists(constraints.attributes_include, memory.get("attributes_include"))
    constraints.attributes_exclude = _merge_lists(constraints.attributes_exclude, memory.get("attributes_exclude"))
    constraints.scene_terms = _merge_lists(constraints.scene_terms, memory.get("scene_terms"))

    if constraints != parsed.constraints:
        inherited = True
    if not inherited:
        return parsed

    return parsed.model_copy(
        update={
            "intent_type": "filter_refinement" if parsed.intent_type == "product_search" else parsed.intent_type,
            "constraints": constraints,
        }
    )


def build_updated_structured_memory(
    previous: dict[str, Any] | None,
    *,
    message: str,
    parsed_turn: ParsedTurn | None = None,
    visible_products: list[dict[str, Any]] | None = None,
    current_product_id: str | None = None,
    cart: dict[str, Any] | None = None,
) -> dict[str, Any]:
    memory = empty_structured_memory()
    if previous:
        memory.update({key: value for key, value in previous.items() if key in memory})

    memory["last_query"] = message
    if parsed_turn is not None:
        _merge_turn_into_memory(memory, parsed_turn)
    if visible_products is not None:
        product_ids = [str(item.get("id") or "") for item in visible_products if item.get("id")]
        if product_ids:
            memory["last_product_ids"] = product_ids
            memory["current_product_id"] = current_product_id or product_ids[0]
            _merge_product_context(memory, visible_products[0])
    elif current_product_id:
        memory["current_product_id"] = current_product_id

    if cart is not None:
        items = cart.get("items") if isinstance(cart, dict) else None
        memory["cart_item_count"] = len(items) if isinstance(items, list) else 0

    memory["size_hint"] = _extract_size_hint(message) or memory.get("size_hint")
    return memory


def _merge_turn_into_memory(memory: dict[str, Any], parsed_turn: ParsedTurn) -> None:
    constraints = getattr(parsed_turn, "constraints", None) or TurnConstraints()
    intent_type = str(getattr(parsed_turn, "intent_type", "") or "")
    memory["last_intent"] = intent_type or None
    memory["current_task"] = _task_from_intent(intent_type, memory.get("current_task"))
    memory["pending_question"] = (
        getattr(parsed_turn, "clarification_question", None)
        if bool(getattr(parsed_turn, "needs_clarification", False))
        else None
    )

    if constraints.categories:
        memory["category"] = constraints.categories[0]
    if constraints.subcategories:
        memory["subcategory"] = constraints.subcategories[0]
    if constraints.price.min is not None:
        memory["budget_min"] = constraints.price.min
    if constraints.price.max is not None:
        memory["budget_max"] = constraints.price.max

    memory["brands_include"] = _merge_lists(memory.get("brands_include"), constraints.brands_include)
    memory["brands_exclude"] = _merge_lists(memory.get("brands_exclude"), constraints.brands_exclude)
    memory["attributes_include"] = _merge_lists(memory.get("attributes_include"), constraints.attributes_include)
    memory["attributes_exclude"] = _merge_lists(memory.get("attributes_exclude"), constraints.attributes_exclude)
    memory["scene_terms"] = _merge_lists(memory.get("scene_terms"), constraints.scene_terms)


def _merge_product_context(memory: dict[str, Any], product: dict[str, Any]) -> None:
    category = product.get("category")
    subcategory = product.get("subcategory")
    brand = product.get("brand")
    if category:
        memory["category"] = category
    if subcategory:
        memory["subcategory"] = subcategory
    if brand:
        memory["brands_include"] = _merge_lists(memory.get("brands_include"), [brand])


def _memory_from_state(conversation_state: dict | None) -> dict[str, Any]:
    if not conversation_state:
        return {}
    memory = conversation_state.get(STRUCTURED_MEMORY_KEY) or conversation_state.get("structured_state")
    return memory if isinstance(memory, dict) else {}


def _should_inherit_memory(parsed: ParsedTurn) -> bool:
    if parsed.intent_type not in {"product_search", "filter_refinement"}:
        return False
    constraints = parsed.constraints
    if constraints.categories or constraints.subcategories:
        return False
    has_refinement = bool(
        constraints.price.min is not None
        or constraints.price.max is not None
        or constraints.brands_exclude
        or constraints.attributes_include
        or constraints.attributes_exclude
        or constraints.scene_terms
        or constraints.negative_terms
    )
    if parsed.intent_type == "filter_refinement":
        return True
    return has_refinement or _looks_like_refinement(parsed.raw_message)


def _looks_like_refinement(message: str) -> bool:
    text = (message or "").strip()
    if not text:
        return False
    refinement_terms = (
        "再",
        "换",
        "便宜",
        "贵",
        "耐磨",
        "轻",
        "舒服",
        "黑色",
        "白色",
        "不要",
        "除了",
        "排除",
        "大一点",
        "小一点",
    )
    return len(text) <= 18 and any(term in text for term in refinement_terms)


def _task_from_intent(intent: str, fallback: Any) -> str | None:
    if intent in {"product_search", "filter_refinement", "bundle_recommendation"}:
        return "recommendation"
    if intent in {"cart_add", "cart_remove", "cart_update_quantity", "cart_list", "cart_clear"}:
        return "cart"
    if intent in {"product_compare", "product_detail_qa"}:
        return "product_qa"
    return fallback if isinstance(fallback, str) else None


def _extract_size_hint(message: str) -> str | None:
    match = re.search(r"(?<!\d)(\d{2}(?:\.\d)?)(?:\s*码)?(?!\d)", message or "")
    return f"{match.group(1)}码" if match else None


def _merge_if_empty_or_refining(current: Any, remembered: Any, force: bool) -> list[str]:
    current_list = _dedupe_texts(current or [])
    if current_list and not force:
        return current_list
    return _merge_lists(current_list, remembered)


def _merge_lists(first: Any, second: Any) -> list[str]:
    return _dedupe_texts([*(first or []), *(second or [])])


def _dedupe_texts(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
