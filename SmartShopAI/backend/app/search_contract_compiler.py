from __future__ import annotations

from .catalog_grounder import CatalogGroundingResult, ground_catalog_terms
from .parser_safety import compact_text, safe_candidate_terms
from .turn_schema import BundleSlotCandidate, ParsedTurn, ParsedTurnCandidate, RetrievalPolicyHint, TurnConstraints


SEARCH_INTENTS = {"product_search", "filter_refinement", "unknown"}
PROTECTED_INTENTS = {
    "cart_add",
    "cart_remove",
    "cart_update_quantity",
    "cart_list",
    "cart_clear",
    "product_compare",
    "product_detail_qa",
    "greeting",
    "capability_question",
    "bundle_recommendation",
}


def compile_executable_turn(candidate: ParsedTurnCandidate) -> ParsedTurn:
    raw = candidate.raw_message or ""
    constraints = TurnConstraints(
        brands_include=list(candidate.brands_include),
        brands_exclude=list(candidate.brands_exclude),
        attributes_include=list(candidate.attributes_include),
        attributes_exclude=list(candidate.attributes_exclude),
        scene_terms=list(candidate.scene_terms),
        price=candidate.price,
        negative_terms=list(candidate.negative_terms),
    )
    normalized_query = _core_query(candidate)

    if candidate.intent_type == "bundle_recommendation":
        return ParsedTurn(
            raw_message=raw,
            normalized_query=normalized_query,
            intent_type="bundle_recommendation",
            route_hint="direct_tool",
            needs_clarification=candidate.needs_clarification,
            clarification_question=candidate.clarification_question,
            constraints=constraints,
            references=list(candidate.references),
            compare_dimensions=list(candidate.compare_dimensions),
            quantity=candidate.quantity,
            bundle_slots=_compile_bundle_slots(candidate),
            source=candidate.source,
            confidence=candidate.confidence,
        )

    parsed = ParsedTurn(
        raw_message=raw,
        normalized_query=normalized_query,
        intent_type=candidate.intent_type,
        constraints=constraints,
        references=list(candidate.references),
        compare_dimensions=list(candidate.compare_dimensions),
        quantity=candidate.quantity,
        needs_clarification=candidate.needs_clarification,
        clarification_question=candidate.clarification_question,
        source=candidate.source,
        confidence=candidate.confidence,
    )

    if parsed.intent_type in PROTECTED_INTENTS or parsed.intent_type not in SEARCH_INTENTS:
        return parsed

    raw = parsed.raw_message or ""
    retrieval = parsed.retrieval_policy_hint.model_copy(deep=True)
    grounding = ground_catalog_terms(raw, _candidate_terms(candidate))

    if grounding.ambiguous_terms and not _has_structured_constraints(constraints):
        return parsed.model_copy(
            update={
                "route_hint": "no_tool",
                "needs_clarification": True,
                "clarification_question": _ambiguity_question(grounding.ambiguous_terms[0]),
                "normalized_query": grounding.core_query or parsed.normalized_query,
                "constraints": constraints,
                "retrieval_policy_hint": retrieval,
            }
        )

    if grounding.matches:
        _apply_grounding(constraints, grounding)
        if constraints.required_terms:
            retrieval = retrieval.model_copy(
                update={
                    "allow_popular_fallback": False,
                    "allow_dense_only": False,
                    "require_lexical_anchor": True,
                }
            )
        return parsed.model_copy(
            update={
                "intent_type": "product_search" if parsed.intent_type == "unknown" else parsed.intent_type,
                "route_hint": "direct_tool",
                "needs_clarification": False,
                "clarification_question": None,
                "normalized_query": grounding.core_query or parsed.normalized_query,
                "constraints": constraints,
                "retrieval_policy_hint": retrieval,
                "is_unknown_short_query": False,
            }
        )

    if (
        grounding.unknown_terms
        and parsed.intent_type in {"product_search", "unknown"}
        and not _has_structured_constraints(constraints)
    ):
        constraints.required_terms = [grounding.unknown_terms[0]]
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
                "normalized_query": grounding.unknown_terms[0],
                "constraints": constraints,
                "retrieval_policy_hint": retrieval,
                "is_unknown_short_query": True,
            }
        )

    constraints.required_terms = safe_candidate_terms(grounding.core_query or raw, constraints.required_terms)
    return parsed.model_copy(
        update={
            "normalized_query": grounding.core_query or parsed.normalized_query,
            "constraints": constraints,
            "retrieval_policy_hint": retrieval,
        }
    )


def compile_search_contract(parsed: ParsedTurn) -> ParsedTurn:
    if parsed.intent_type in PROTECTED_INTENTS or parsed.intent_type not in SEARCH_INTENTS:
        return parsed
    return compile_executable_turn(candidate_from_parsed_turn(parsed))


def candidate_from_parsed_turn(parsed: ParsedTurn) -> ParsedTurnCandidate:
    constraints = parsed.constraints
    return ParsedTurnCandidate(
        raw_message=parsed.raw_message,
        intent_type=parsed.intent_type,
        core_product_query=parsed.normalized_query,
        semantic_query=parsed.normalized_query,
        query_expansions=[],
        product_mentions=list(constraints.required_terms),
        category_mentions=list(constraints.categories),
        subcategory_mentions=list(constraints.subcategories),
        brands_include=list(constraints.brands_include),
        brands_exclude=list(constraints.brands_exclude),
        attributes_include=list(constraints.attributes_include),
        attributes_exclude=list(constraints.attributes_exclude),
        scene_terms=list(constraints.scene_terms),
        price=constraints.price,
        negative_terms=list(constraints.negative_terms),
        references=list(parsed.references),
        compare_dimensions=list(parsed.compare_dimensions),
        bundle_slots=list(parsed.bundle_slots),
        quantity=parsed.quantity,
        needs_clarification=parsed.needs_clarification,
        clarification_question=parsed.clarification_question,
        source=parsed.source,
        confidence=parsed.confidence,
    )


def _candidate_terms(candidate: ParsedTurnCandidate) -> list[str]:
    return [
        candidate.core_product_query or "",
        candidate.semantic_query or "",
        *candidate.product_mentions,
        *candidate.query_expansions,
        *candidate.subcategory_mentions,
    ]


def _apply_grounding(constraints: TurnConstraints, grounding: CatalogGroundingResult) -> None:
    constraints.required_terms = []
    for match in grounding.matches:
        constraints.categories = _merge_unique(constraints.categories, match.categories)
        constraints.subcategories = _merge_unique(constraints.subcategories, match.subcategories)
        constraints.required_terms = _merge_unique(constraints.required_terms, match.required_terms)


def _has_structured_constraints(constraints: TurnConstraints) -> bool:
    return bool(
        constraints.categories
        or constraints.subcategories
        or constraints.brands_include
        or constraints.brands_exclude
        or constraints.attributes_include
        or constraints.attributes_exclude
        or constraints.scene_terms
        or constraints.price.min is not None
        or constraints.price.max is not None
    )


def _ambiguity_question(term: str) -> str:
    compact = compact_text(term)
    if compact == "笔":
        return "你说的是书写用的笔、眉笔，还是笔记本电脑？"
    return f"你说的“{compact}”具体是哪一类商品？"


def _core_query(candidate: ParsedTurnCandidate) -> str | None:
    for value in (candidate.core_product_query, candidate.semantic_query):
        compact = compact_text(value or "")
        if compact:
            return compact
    return None


def _compile_bundle_slots(candidate: ParsedTurnCandidate) -> list[BundleSlotCandidate]:
    raw = candidate.raw_message or ""
    slots = candidate.bundle_slots or _fallback_bundle_slots(raw, candidate)
    compiled: list[BundleSlotCandidate] = []
    for index, slot in enumerate(slots, start=1):
        slot_query = compact_text(slot.query or " ".join(slot.product_mentions) or slot.title)
        grounding = ground_catalog_terms(slot_query, [*slot.product_mentions, slot_query])
        grounded_terms = _grounded_required_terms(grounding)
        compiled.append(
            BundleSlotCandidate(
                key=slot.key or f"slot_{index}",
                title=slot.title or f"搭配项{index}",
                query=grounding.core_query or slot_query,
                reason=slot.reason,
                product_mentions=grounded_terms or safe_candidate_terms(slot_query, slot.product_mentions),
                attributes_include=list(slot.attributes_include),
                scene_terms=_merge_unique(list(candidate.scene_terms), list(slot.scene_terms)),
            )
        )
    return compiled


def _grounded_required_terms(grounding: CatalogGroundingResult) -> list[str]:
    terms: list[str] = []
    for match in grounding.matches:
        terms = _merge_unique(terms, match.required_terms or [match.term])
    if not terms and grounding.unknown_terms:
        terms = [grounding.unknown_terms[0]]
    return terms


def _fallback_bundle_slots(raw: str, candidate: ParsedTurnCandidate) -> list[BundleSlotCandidate]:
    text = raw or candidate.core_product_query or ""
    if any(term in text for term in ("三亚", "海边", "海岛", "沙滩", "度假")):
        return [
            BundleSlotCandidate(key="sunscreen", title="防晒打底", query="SPF50 防水 防晒霜 海边 户外", reason="海边紫外线强，先用高倍防晒做基础防护。", product_mentions=["防晒"]),
            BundleSlotCandidate(key="sun_protection", title="物理防晒", query="轻薄 防晒衣 透气 户外", reason="减少长时间暴晒。"),
            BundleSlotCandidate(key="shoes", title="鞋履", query="沙滩 凉鞋 防滑 轻便", reason="沙滩和酒店来回走动需要防滑轻便。", product_mentions=["鞋"]),
            BundleSlotCandidate(key="bag", title="随身收纳", query="防水包 旅行 背包 轻便", reason="收纳手机证件和随身物品。", product_mentions=["背包"]),
            BundleSlotCandidate(key="repair", title="晒后护理", query="晒后修复 补水 舒缓 护肤", reason="晚上做晒后舒缓。"),
        ]
    if _looks_like_digital_ecosystem(text):
        return [
            BundleSlotCandidate(key="phone", title="手机", query="智能手机 互联 生态 协同", reason="作为互联生态的核心设备。", product_mentions=["手机"]),
            BundleSlotCandidate(key="computer", title="电脑或平板", query="笔记本电脑 平板 互联 协同", reason="和手机形成跨设备办公与内容同步。", product_mentions=["笔记本", "平板"]),
            BundleSlotCandidate(key="audio_wearable", title="耳机或手表", query="耳机 手表 互联 生态 配套", reason="补齐通话、音频或随身通知体验。", product_mentions=["耳机", "手表"]),
        ]
    if any(term in text for term in ("通勤", "上班", "上学")):
        return [
            BundleSlotCandidate(key="top", title="上装", query="通勤 轻薄 外套 卫衣", reason="兼顾室内外温差。"),
            BundleSlotCandidate(key="shoes", title="鞋履", query="通勤 运动鞋 舒适", reason="适合长时间走路。", product_mentions=["鞋"]),
            BundleSlotCandidate(key="bag", title="包袋", query="通勤 背包 轻便 容量", reason="收纳电脑和随身物品。", product_mentions=["背包"]),
        ]
    core = candidate.core_product_query or text
    return [
        BundleSlotCandidate(key="core", title="核心商品", query=core, reason="先匹配描述里最核心的商品需求。", product_mentions=list(candidate.product_mentions)),
        BundleSlotCandidate(key="accessory", title="配套商品", query=f"{core} 配套 便携", reason="再补一个适合一起购买的配套选择。"),
    ]


def _looks_like_digital_ecosystem(text: str) -> bool:
    return (
        any(term in text for term in ("一套", "配套", "搭配", "组合", "全家桶"))
        and any(term in text for term in ("互联", "生态", "协同", "跨屏", "同品牌"))
        and any(term in text for term in ("手机", "电脑", "笔记本", "平板", "耳机", "手表"))
    )


def _merge_unique(first: list[str], second: list[str]) -> list[str]:
    return list(dict.fromkeys([*first, *second]))
