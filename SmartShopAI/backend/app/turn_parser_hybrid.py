from __future__ import annotations

import logging
import re
from typing import Any

from .llm_client import LLMGenerationError
from .catalog_grounder import default_catalog_summary as grounded_catalog_summary
from .scene_slot_generator import generate_scene_slots_with_llm
from .scene_slots import is_scene_bundle_request
from .search_contract_compiler import candidate_from_parsed_turn, compile_executable_turn, compile_search_contract
from .safety_profile import build_safety_clarification_question
from .turn_parser_llm import parse_turn_with_llm
from .turn_schema import ParsedTurn, ParsedTurnCandidate, ProductReference, RetrievalPolicyHint, TurnConstraints


logger = logging.getLogger(__name__)

UNKNOWN_EXACT_MAX_CHARS = 8
ATTRIBUTE_ONLY_TERMS = {"蓝牙", "防水", "轻薄", "降噪", "续航", "便携"}
PRICE_COMPARE_TERMS = {"便宜", "价格", "更便宜"}
STOCK_TERMS = {"有货", "库存", "现货"}
DETAIL_TERMS = {"参数", "规格", "价格", "库存", "有货", "怎么样"}
GREETINGS = {"你好", "您好", "hi", "hello"}
NEGATION_TERMS = ["不要", "排除", "不想要", "别要", "不考虑", "别推荐", "不要推荐", "不是"]
BRAND_ALIAS_GROUPS = [
    ["Nike", "耐克"],
    ["Apple", "苹果"],
    ["HUAWEI", "华为"],
    ["Xiaomi", "小米"],
]

CATALOG_TERMS: list[dict[str, Any]] = [
    {"terms": ["拍照手机", "手机"], "categories": ["数码电子"], "subcategories": ["智能手机"], "required_terms": ["手机"]},
    {"terms": ["蓝牙耳机", "降噪耳机", "耳机"], "categories": ["数码电子"], "subcategories": ["真无线耳机"], "required_terms": ["耳机"]},
    {"terms": ["笔记本电脑", "笔记本"], "categories": ["数码电子"], "subcategories": ["笔记本电脑"], "required_terms": ["笔记本"]},
    {"terms": ["平板电脑", "平板"], "categories": ["数码电子"], "subcategories": ["平板电脑"], "required_terms": ["平板"]},
    {"terms": ["篮球鞋"], "categories": ["服饰运动"], "subcategories": ["篮球鞋"], "required_terms": ["篮球鞋"]},
    {"terms": ["跑步鞋"], "categories": ["服饰运动"], "subcategories": ["跑步鞋"], "required_terms": ["跑步鞋"]},
    {"terms": ["卫衣"], "categories": ["服饰运动"], "subcategories": ["卫衣"], "required_terms": ["卫衣"]},
    {"terms": ["帽子", "棒球帽", "鸭舌帽"], "categories": ["服饰运动"], "subcategories": ["帽子"], "required_terms": ["帽"]},
    {"terms": ["背包"], "categories": ["旅行户外", "服饰运动"], "subcategories": ["背包", "户外背包"], "required_terms": ["背包"]},
    {"terms": ["登机箱"], "categories": ["旅行户外"], "subcategories": ["旅行箱包"], "required_terms": ["登机箱"]},
    {"terms": ["行李箱", "拉杆箱"], "categories": ["旅行户外"], "subcategories": ["旅行箱包"], "required_terms": ["行李箱"]},
    {"terms": ["零食", "坚果"], "categories": ["食品饮料"], "subcategories": ["坚果/零食"], "required_terms": ["零食"]},
    {"terms": ["咖啡"], "categories": ["食品饮料"], "subcategories": ["咖啡"], "required_terms": ["咖啡"]},
    {"terms": ["牛奶"], "categories": ["食品饮料"], "subcategories": ["牛奶"], "required_terms": ["牛奶"]},
    {"terms": ["酱油", "生抽", "老抽", "调味品", "调味料"], "categories": ["食品饮料"], "subcategories": [], "required_terms": ["酱油"]},
    {"terms": ["泳衣", "泳裤"], "categories": ["服饰运动"], "subcategories": [], "required_terms": ["泳"]},
    {"terms": ["泳镜"], "categories": ["服饰运动"], "subcategories": [], "required_terms": ["泳镜"]},
    {"terms": ["泳帽"], "categories": ["服饰运动"], "subcategories": [], "required_terms": ["泳帽"]},
    {"terms": ["防水包"], "categories": ["旅行户外"], "subcategories": ["背包", "户外背包"], "required_terms": ["防水包"]},
    {"terms": ["速干毛巾", "浴巾"], "categories": ["家居百货"], "subcategories": [], "required_terms": ["毛巾"]},
    {"terms": ["精华"], "categories": ["美妆护肤"], "subcategories": ["精华"], "required_terms": ["精华"]},
    {"terms": ["面霜"], "categories": ["美妆护肤"], "subcategories": ["面霜"], "required_terms": ["面霜"]},
    {"terms": ["防晒"], "categories": ["美妆护肤"], "subcategories": ["防晒"], "required_terms": ["防晒"]},
    {"terms": ["猫爬架"], "categories": ["宠物用品"], "subcategories": ["猫咪用品"], "required_terms": ["猫爬架"]},
    {"terms": ["猫抓板"], "categories": ["宠物用品"], "subcategories": ["猫咪用品"], "required_terms": ["猫抓板"]},
    {"terms": ["宠物围栏"], "categories": ["宠物用品"], "subcategories": ["宠物围栏"], "required_terms": ["宠物围栏"]},
    {"terms": ["计划本"], "categories": ["办公文具"], "subcategories": ["本册纸品"], "required_terms": ["计划本"]},
    {"terms": ["墨盒"], "categories": ["办公文具"], "subcategories": ["打印耗材"], "required_terms": ["墨盒"]},
    {"terms": ["胶带"], "categories": ["办公文具"], "subcategories": ["胶带耗材"], "required_terms": ["胶带"]},
    {"terms": ["挂钟"], "categories": ["家居百货"], "subcategories": ["挂钟"], "required_terms": ["挂钟"]},
]


async def parse_turn_hybrid(
    message: str,
    chat_history: list[dict] | None,
    conversation_state: dict | None,
) -> ParsedTurn:
    rule_parse = parse_turn_with_rules(message, chat_history, conversation_state)
    rule_candidate = candidate_from_parsed_turn(rule_parse)
    llm_candidate: ParsedTurnCandidate | None = None
    try:
        llm_candidate = _as_candidate(
            await parse_turn_with_llm(message, chat_history, conversation_state, catalog_summary=default_catalog_summary())
        )
    except LLMGenerationError as exc:
        logger.info("turn_parser_llm_failed=%s", exc)
    except Exception as exc:
        logger.info("turn_parser_llm_failed=%s", exc.__class__.__name__)
    merged = merge_rule_and_llm_parse(rule_candidate, llm_candidate)
    if merged.intent_type == "bundle_recommendation" and not merged.bundle_slots:
        try:
            generated_slots = await generate_scene_slots_with_llm(message, catalog_summary=default_catalog_summary())
            if generated_slots:
                merged = merged.model_copy(update={"bundle_slots": generated_slots, "source": "hybrid"})
        except LLMGenerationError as exc:
            logger.info("scene_slot_generator_failed=%s", exc)
        except Exception as exc:
            logger.info("scene_slot_generator_failed=%s", exc.__class__.__name__)
    compiled = compile_executable_turn(merged)
    return post_validate_parsed_turn(compiled, default_catalog_summary(), chat_history, conversation_state)


def parse_turn_with_rules(
    message: str,
    chat_history: list[dict] | None = None,
    conversation_state: dict | None = None,
) -> ParsedTurn:
    raw = (message or "").strip()
    compact = _compact(raw)
    constraints = TurnConstraints()
    references = _extract_references(raw)
    quantity = _extract_quantity(raw)
    compare_dimensions: list[str] = []

    if not raw:
        return ParsedTurn(raw_message=raw, intent_type="unknown", route_hint="no_tool", needs_clarification=True)
    explicit_cart_product_id = _explicit_cart_product_id(raw)
    if explicit_cart_product_id:
        return ParsedTurn(
            raw_message=raw,
            intent_type="cart_add",
            route_hint="bounded_react",
            references=[
                ProductReference(
                    reference_type="product_id",
                    product_id=explicit_cart_product_id,
                    raw_text=explicit_cart_product_id,
                )
            ],
            quantity=quantity or 1,
            source="rule",
        )
    if _looks_like_sku_selection(raw) and (conversation_state or {}).get("current_product_id"):
        return ParsedTurn(
            raw_message=raw,
            intent_type="cart_add",
            route_hint="bounded_react",
            references=[ProductReference(reference_type="current_product", raw_text="当前商品")],
            quantity=quantity or 1,
            source="rule",
        )
    if compact.lower() in GREETINGS:
        return ParsedTurn(raw_message=raw, intent_type="greeting", route_hint="no_tool")
    if any(term in raw for term in ["你能做什么", "你会什么", "怎么用"]):
        return ParsedTurn(raw_message=raw, intent_type="capability_question", route_hint="no_tool")
    if _is_explicit_single_product_replenishment(raw):
        _apply_catalog_terms(raw, constraints)
        _apply_price(raw, constraints)
        _apply_brand_filters(raw, constraints)
        return ParsedTurn(raw_message=raw, intent_type="product_search", route_hint="direct_tool", constraints=constraints, source="rule")
    if _is_bundle_request(raw):
        return ParsedTurn(raw_message=raw, intent_type="bundle_recommendation", route_hint="direct_tool", source="rule")
    if _is_ambiguous_action_request(raw):
        return ParsedTurn(
            raw_message=raw,
            intent_type="unknown",
            route_hint="no_tool",
            needs_clarification=True,
            clarification_question="我需要确认一下，你是想换一批推荐、删除购物车商品，还是加入购物车/直接购买？",
            source="rule",
        )

    _apply_catalog_terms(raw, constraints)
    _apply_price(raw, constraints)
    _apply_brand_filters(raw, constraints)

    has_cart_context = _has_cart_context(conversation_state)
    cart_quantity_terms = ["改", "数量", "件", "增加", "加一", "再加", "多加", "减少", "减一", "少一", "少买"]
    cart_scope = "购物车" in raw or has_cart_context or (bool(references) and any(term in raw for term in cart_quantity_terms))
    cart_remove_terms = ["删除", "移除", "去掉", "拿掉"]

    if any(term in raw for term in ["购物车", "加购", "加入"]) and any(term in raw for term in ["加", "加入", "放入"]):
        return ParsedTurn(
            raw_message=raw,
            intent_type="cart_add",
            route_hint="bounded_react",
            constraints=constraints,
            references=references,
            quantity=quantity or 1,
            source="rule",
        )
    if "购物车" in raw and any(term in raw for term in ["清空", "全部删除", "全删", "清掉", "清除"]):
        return ParsedTurn(raw_message=raw, intent_type="cart_clear", route_hint="bounded_react", source="rule")
    if _is_cart_remove_request(raw, references, has_cart_context, cart_remove_terms):
        return ParsedTurn(raw_message=raw, intent_type="cart_remove", route_hint="bounded_react", references=references, source="rule")
    if cart_scope and any(term in raw for term in cart_quantity_terms):
        return ParsedTurn(
            raw_message=raw,
            intent_type="cart_update_quantity",
            route_hint="bounded_react",
            references=references,
            quantity=quantity,
            source="rule",
        )
    if "购物车" in raw and any(term in raw for term in ["看", "打开", "列表"]):
        return ParsedTurn(raw_message=raw, intent_type="cart_list", route_hint="bounded_react", source="rule")

    if len(references) >= 2 and any(term in raw for term in ["比较", "哪个", "哪款"]):
        if any(term in raw for term in PRICE_COMPARE_TERMS):
            compare_dimensions.append("price")
        return ParsedTurn(
            raw_message=raw,
            intent_type="product_compare",
            route_hint="bounded_react",
            references=references,
            compare_dimensions=compare_dimensions or ["overall"],
            source="rule",
        )
    if references and any(term in raw for term in DETAIL_TERMS):
        dimensions = ["stock"] if any(term in raw for term in STOCK_TERMS) else []
        return ParsedTurn(
            raw_message=raw,
            intent_type="product_detail_qa",
            route_hint="bounded_react",
            references=references,
            compare_dimensions=dimensions,
            source="rule",
        )

    intent = "filter_refinement" if any(term in raw for term in ["再便宜点", "便宜点", "不要", "排除"]) else "product_search"
    return ParsedTurn(raw_message=raw, intent_type=intent, route_hint="direct_tool", constraints=constraints, source="rule")


def merge_rule_and_llm_parse(rule_parse: ParsedTurnCandidate, llm_parse: ParsedTurnCandidate | None) -> ParsedTurnCandidate:
    if llm_parse is None:
        return rule_parse.model_copy(update={"source": "rule"})

    if rule_parse.intent_type == "bundle_recommendation":
        if llm_parse.intent_type == "bundle_recommendation" and llm_parse.bundle_slots:
            return llm_parse.model_copy(update={"source": "hybrid"})
        return rule_parse.model_copy(update={"source": "rule"})

    if _locks_rule_intent(rule_parse):
        return rule_parse.model_copy(update={"source": "rule"})

    if (
        rule_parse.intent_type == "product_search"
        and _is_explicit_single_product_replenishment(rule_parse.raw_message)
        and rule_parse.product_mentions
    ):
        return rule_parse.model_copy(update={"source": "rule"})

    intent_type = llm_parse.intent_type if llm_parse.intent_type != "unknown" else rule_parse.intent_type
    price = llm_parse.price.model_copy(deep=True)
    if rule_parse.price.min is not None:
        price.min = rule_parse.price.min
    if rule_parse.price.max is not None:
        price.max = rule_parse.price.max

    return llm_parse.model_copy(
        update={
            "raw_message": llm_parse.raw_message or rule_parse.raw_message,
            "intent_type": intent_type,
            "core_product_query": llm_parse.core_product_query or llm_parse.semantic_query or rule_parse.core_product_query,
            "semantic_query": llm_parse.semantic_query or llm_parse.core_product_query or rule_parse.semantic_query,
            "product_mentions": _merge_unique(rule_parse.product_mentions, llm_parse.product_mentions),
            "query_expansions": _merge_unique(rule_parse.query_expansions, llm_parse.query_expansions),
            "category_mentions": _merge_unique(rule_parse.category_mentions, llm_parse.category_mentions),
            "subcategory_mentions": _merge_unique(rule_parse.subcategory_mentions, llm_parse.subcategory_mentions),
            "brands_include": _merge_unique(rule_parse.brands_include, llm_parse.brands_include),
            "brands_exclude": _merge_unique(rule_parse.brands_exclude, llm_parse.brands_exclude),
            "attributes_include": _merge_unique(rule_parse.attributes_include, llm_parse.attributes_include),
            "attributes_exclude": _merge_unique(rule_parse.attributes_exclude, llm_parse.attributes_exclude),
            "scene_terms": _merge_unique(rule_parse.scene_terms, llm_parse.scene_terms),
            "negative_terms": _merge_unique(rule_parse.negative_terms, llm_parse.negative_terms),
            "price": price,
            "references": llm_parse.references or rule_parse.references,
            "quantity": llm_parse.quantity or rule_parse.quantity,
            "compare_dimensions": llm_parse.compare_dimensions or rule_parse.compare_dimensions,
            "bundle_slots": llm_parse.bundle_slots or rule_parse.bundle_slots,
            "source": "hybrid",
        }
    )


def post_validate_parsed_turn(
    parsed: ParsedTurn,
    catalog_lexicon: dict[str, Any] | None = None,
    chat_history: list[dict] | None = None,
    conversation_state: dict | None = None,
) -> ParsedTurn:
    raw = parsed.raw_message.strip()
    compact = _compact(raw)
    constraints = parsed.constraints.model_copy(deep=True)
    _normalize_brand_constraints(constraints)
    retrieval = parsed.retrieval_policy_hint.model_copy(deep=True)
    has_context = _has_context(chat_history, conversation_state)

    if _is_attribute_only(compact) and not has_context and not constraints.subcategories:
        return parsed.model_copy(
            update={
                "needs_clarification": True,
                "route_hint": "no_tool",
                "clarification_question": f"你想找哪类带{compact}功能的商品？",
                "retrieval_policy_hint": retrieval,
            }
        )

    compiled = compile_search_contract(
        parsed.model_copy(update={"constraints": constraints, "retrieval_policy_hint": retrieval})
    )
    if compiled.route_hint == "no_tool" and compiled.needs_clarification:
        return compiled
    constraints = compiled.constraints.model_copy(deep=True)
    retrieval = compiled.retrieval_policy_hint.model_copy(deep=True)
    parsed = compiled
    if parsed.is_unknown_short_query:
        return parsed

    safety_question = build_safety_clarification_question(parsed, constraints)
    if safety_question:
        return parsed.model_copy(
            update={
                "needs_clarification": True,
                "route_hint": "no_tool",
                "clarification_question": safety_question,
                "retrieval_policy_hint": retrieval,
            }
        )

    if _needs_preference_clarification(parsed, constraints, has_context):
        return parsed.model_copy(
            update={
                "needs_clarification": True,
                "route_hint": "no_tool",
                "clarification_question": build_preference_clarification_question(constraints),
                "retrieval_policy_hint": retrieval,
            }
        )

    known_catalog_hit = _matches_catalog(raw)
    protected_intent = parsed.intent_type in {
        "cart_add",
        "cart_remove",
        "cart_update_quantity",
        "cart_list",
        "cart_clear",
        "product_compare",
        "product_detail_qa",
        "greeting",
        "capability_question",
    }
    if (
        not protected_intent
        and parsed.intent_type in {"product_search", "unknown"}
        and _is_short_query(compact)
        and not known_catalog_hit
        and not _is_attribute_only(compact)
        and constraints.price.min is None
        and constraints.price.max is None
        and not constraints.categories
        and not constraints.subcategories
        and not constraints.brands_include
    ):
        constraints.required_terms = [compact]
        retrieval = RetrievalPolicyHint(
            match_mode="exact_or_none",
            allow_popular_fallback=False,
            allow_dense_only=False,
            require_lexical_anchor=True,
        )
        return parsed.model_copy(
            update={
                "intent_type": "product_search",
                "route_hint": "direct_tool",
                "constraints": constraints,
                "retrieval_policy_hint": retrieval,
                "is_unknown_short_query": True,
            }
        )

    if parsed.intent_type in {"cart_add", "cart_remove", "cart_update_quantity", "cart_list", "cart_clear", "product_compare", "product_detail_qa"}:
        route_hint = "bounded_react"
    elif parsed.intent_type in {"greeting", "capability_question", "unknown"} and parsed.needs_clarification:
        route_hint = "no_tool"
    elif parsed.intent_type in {"greeting", "capability_question"}:
        route_hint = "no_tool"
    else:
        route_hint = "direct_tool"

    return parsed.model_copy(update={"route_hint": route_hint, "constraints": constraints, "retrieval_policy_hint": retrieval})


def default_catalog_summary() -> dict[str, Any]:
    summary = grounded_catalog_summary()
    return {
        "terms": [term for item in CATALOG_TERMS for term in item["terms"]],
        "grounded_terms": summary.get("terms", []),
        "grounded_labels": summary.get("labels", []),
        "attribute_only_terms": sorted(ATTRIBUTE_ONLY_TERMS),
    }


def _apply_catalog_terms(raw: str, constraints: TurnConstraints) -> None:
    for item in CATALOG_TERMS:
        if any(term in raw for term in item["terms"]):
            constraints.categories = _merge_unique(constraints.categories, item["categories"])
            constraints.subcategories = _merge_unique(constraints.subcategories, item["subcategories"])
            constraints.required_terms = _merge_unique(constraints.required_terms, item["required_terms"])
    if "蓝牙" in raw and "耳机" not in raw:
        constraints.attributes_include = _merge_unique(constraints.attributes_include, ["蓝牙"])


def _apply_price(raw: str, constraints: TurnConstraints) -> None:
    max_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:元)?\s*(?:以下|以内|内|之内)", raw)
    if not max_match:
        max_match = re.search(r"(?:不超过|低于|小于|预算)\s*(\d+(?:\.\d+)?)", raw)
    if max_match:
        constraints.price.max = float(max_match.group(1))
    min_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:元)?\s*(?:以上|起)", raw)
    if min_match:
        constraints.price.min = float(min_match.group(1))


def _apply_brand_filters(raw: str, constraints: TurnConstraints) -> None:
    raw_lower = raw.lower()
    for group in BRAND_ALIAS_GROUPS:
        for alias in group:
            start = raw_lower.find(alias.lower())
            if start < 0 or not _is_negated_brand(raw_lower, start):
                continue
            constraints.brands_exclude = _merge_unique(constraints.brands_exclude, group)
            constraints.negative_terms = _merge_unique(constraints.negative_terms, group)


def _normalize_brand_constraints(constraints: TurnConstraints) -> None:
    excluded = _expand_brand_aliases(constraints.brands_exclude)
    included = _expand_brand_aliases(constraints.brands_include)
    excluded_lower = {brand.lower() for brand in excluded}

    constraints.brands_exclude = excluded
    constraints.brands_include = [brand for brand in included if brand.lower() not in excluded_lower]
    if excluded:
        constraints.negative_terms = _merge_unique(constraints.negative_terms, excluded)


def _expand_brand_aliases(brands: list[str]) -> list[str]:
    expanded: list[str] = []
    for brand in brands:
        expanded = _merge_unique(expanded, _brand_alias_group(brand))
    return expanded


def _brand_alias_group(brand: str) -> list[str]:
    brand_lower = str(brand).lower()
    for group in BRAND_ALIAS_GROUPS:
        if any(alias.lower() == brand_lower for alias in group):
            return group
    return [brand]


def _is_negated_brand(raw_lower: str, start: int) -> bool:
    prefix = raw_lower[max(0, start - 12) : start]
    return any(term.lower() in prefix for term in NEGATION_TERMS)


def _extract_references(raw: str) -> list[ProductReference]:
    refs: list[ProductReference] = []
    for token, position in [("第一个", 1), ("第一款", 1), ("第二个", 2), ("第二款", 2), ("第三个", 3), ("第三款", 3)]:
        if token in raw:
            refs.append(ProductReference(reference_type="position", position=position, raw_text=token))
    if any(token in raw for token in ["这个", "这款", "刚才那个", "刚刚那个"]):
        refs.append(ProductReference(reference_type="current_product", raw_text="这个"))
    return refs


def _has_cart_context(conversation_state: dict | None) -> bool:
    return bool((conversation_state or {}).get("cart_context"))


def _is_cart_remove_request(
    raw: str,
    references: list[ProductReference],
    has_cart_context: bool,
    remove_terms: list[str],
) -> bool:
    if "购物车" in raw and any(term in raw for term in [*remove_terms, "不要"]):
        return True
    if references and any(term in raw for term in remove_terms):
        return True
    if references and has_cart_context and "不要" in raw:
        return True
    return False


def _extract_quantity(raw: str) -> int | None:
    match = re.search(r"(\d+)\s*(?:件|个|份)?", raw)
    if match and any(term in raw for term in ["购物车", "加购", "加入", "数量", "改成", "改为", "改到", "增加", "减少"]):
        return max(int(match.group(1)), 1)
    if any(term in raw for term in ["一件", "一个", "一份"]):
        return 1
    if "两" in raw and any(term in raw for term in ["件", "个", "份", "数量", "改成", "改为"]):
        return 2
    return None


def _looks_like_sku_selection(raw: str) -> bool:
    return bool(re.fullmatch(r"\s*\d{2}(?:\.\d)?\s*(?:码)?\s*", raw)) or (
        "选择" in raw and any(term in raw for term in ["尺码", "规格", "码"])
    )


def _explicit_cart_product_id(raw: str) -> str | None:
    for prefix in ("加入购物车:", "加入购物车：", "加购:", "加购："):
        if raw.startswith(prefix):
            return raw.split(prefix, 1)[1].strip() or None
    return None


def _matches_catalog(raw: str) -> bool:
    return any(term in raw for item in CATALOG_TERMS for term in item["terms"])


def _is_explicit_single_product_replenishment(raw: str) -> bool:
    product_terms = ("酱油", "生抽", "老抽", "调味品", "调味料")
    replenishment_terms = ("没了", "用完", "缺", "补", "买", "推荐", "来一瓶", "来点")
    return any(term in raw for term in product_terms) and any(term in raw for term in replenishment_terms)


def _is_bundle_request(raw: str) -> bool:
    if is_scene_bundle_request(raw):
        return True
    has_bundle_word = any(term in raw for term in ("搭配", "一套", "方案", "组合", "清单", "从", "到"))
    has_scene_word = any(term in raw for term in ("度假", "三亚", "海边", "沙滩", "旅行", "通勤", "上班", "户外", "下水", "游泳", "泳池"))
    has_ecosystem_word = any(term in raw for term in ("互联", "生态", "协同", "跨屏", "同品牌", "全家桶"))
    has_digital_word = any(term in raw for term in ("手机", "电脑", "笔记本", "平板", "耳机", "手表"))
    strong_bundle_word = any(term in raw for term in ("搭配", "一套", "方案", "组合", "清单"))
    return has_bundle_word and (has_scene_word or (has_ecosystem_word and has_digital_word) or strong_bundle_word)


def _is_ambiguous_action_request(raw: str) -> bool:
    if not any(term in raw for term in ("弄一下", "处理一下", "搞一下", "安排", "不要了", "再来一个", "然后买", "买了")):
        return False
    has_reference = bool(_extract_references(raw)) or any(term in raw for term in ("这个", "这款", "这双", "刚才", "刚刚"))
    has_clear_action = any(term in raw for term in ("加入购物车", "加购", "删除购物车", "删掉购物车", "下单吧", "确认下单", "直接买"))
    return has_reference and not has_clear_action


def _needs_preference_clarification(parsed: ParsedTurn, constraints: TurnConstraints, has_context: bool) -> bool:
    if parsed.needs_clarification:
        return False
    if parsed.intent_type not in {"product_search", "filter_refinement", "unknown"}:
        return False
    if len(constraints.subcategories) != 1:
        return False
    if constraints.price.min is not None or constraints.price.max is not None:
        return False
    if constraints.brands_include or constraints.attributes_include or constraints.scene_terms:
        return False
    raw = parsed.raw_message or ""
    if any(term in raw for term in ["推荐", "想买", "我要买", "有没有", "有没"]) and not any(
        term in raw for term in ["怎么选", "哪个", "哪款", "更适合", "对比", "比较"]
    ):
        return False
    broad_subcategories = {"智能手机", "真无线耳机", "笔记本电脑", "篮球鞋", "跑步鞋"}
    return constraints.subcategories[0] in broad_subcategories


def build_preference_clarification_question(constraints: TurnConstraints) -> str:
    subcategory = constraints.subcategories[0] if constraints.subcategories else "商品"
    if subcategory == "智能手机":
        return "请问你更看重拍照、续航、性能还是性价比？预算大概多少？"
    if subcategory == "真无线耳机":
        return "请问你更看重降噪、音质、续航还是佩戴舒适？预算大概多少？"
    if subcategory in {"篮球鞋", "跑步鞋"}:
        return "请问你主要用于实战、跑步、通勤还是日常穿搭？预算大概多少？"
    return f"你更看重{subcategory}的哪些方面？比如价格、品牌、功能或使用场景。"


def _is_attribute_only(compact: str) -> bool:
    return compact in ATTRIBUTE_ONLY_TERMS


def _is_short_query(compact: str) -> bool:
    return bool(compact) and len(compact) <= UNKNOWN_EXACT_MAX_CHARS and bool(re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9]+", compact))


def _has_context(chat_history: list[dict] | None, conversation_state: dict | None) -> bool:
    if conversation_state and (
        conversation_state.get("current_product_id")
        or conversation_state.get("last_recommended_product_ids")
        or conversation_state.get("last_query")
    ):
        return True
    return bool(chat_history)


def _as_candidate(parsed: ParsedTurnCandidate | ParsedTurn) -> ParsedTurnCandidate:
    if isinstance(parsed, ParsedTurnCandidate):
        return parsed
    return candidate_from_parsed_turn(parsed)


def _locks_rule_intent(rule_parse: ParsedTurnCandidate) -> bool:
    return rule_parse.intent_type in {
        "cart_add",
        "cart_remove",
        "cart_update_quantity",
        "cart_list",
        "cart_clear",
        "product_compare",
        "product_detail_qa",
        "bundle_recommendation",
        "greeting",
        "capability_question",
    }


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip())


def _merge_unique(first: list[str], second: list[str]) -> list[str]:
    return list(dict.fromkeys([*first, *second]))
