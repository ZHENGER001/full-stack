from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .agent_tools import SearchProductsInput, call_search_products_tool
from .search_contract_compiler import compile_executable_turn
from .scene_slots import bundle_slot_candidates_for_message, scene_name_for_message
from .schemas import ProductCard
from .turn_schema import BundleSlotCandidate, ParsedTurnCandidate


@dataclass(frozen=True)
class BundleSlot:
    key: str
    title: str
    query: str
    reason: str
    constraints: dict[str, Any] = field(default_factory=dict)
    retrieval_policy: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BundleRecommendationResult:
    scene: str
    slots: list[BundleSlot]
    products: list[ProductCard] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)


def build_bundle_slots(message: str, bundle_slots: list[BundleSlotCandidate] | None = None) -> tuple[str, list[BundleSlot]]:
    text = message.strip()
    if bundle_slots:
        slots = [_slot_from_candidate(slot) for slot in bundle_slots]
        return _infer_scene(text), slots

    configured_slots = bundle_slot_candidates_for_message(text)
    if configured_slots:
        return scene_name_for_message(text), [_slot_from_candidate(slot) for slot in configured_slots]

    scene = "组合搭配"
    slots = [
        BundleSlot("core", "核心商品", text, "先匹配你描述里最核心的商品需求。"),
        BundleSlot("accessory", "配套商品", f"{text} 配套 便携", "再补一个更适合一起购买的配套选择。"),
    ]
    return scene, [_compile_slot_contract(slot) for slot in slots]


def retrieve_bundle_recommendations(
    conn,
    message: str,
    top_k_per_slot: int = 1,
    bundle_slots: list[BundleSlotCandidate] | None = None,
) -> BundleRecommendationResult:
    scene, slots = build_bundle_slots(message, bundle_slots=bundle_slots)
    products: list[ProductCard] = []
    diagnostics: dict[str, Any] = {"scene": scene, "slots": []}
    seen_ids: set[str] = set()
    for slot in slots:
        result = call_search_products_tool(
            conn,
            SearchProductsInput(
                query=slot.query,
                top_k=max(top_k_per_slot, 1),
                constraints=slot.constraints,
                retrieval_policy=slot.retrieval_policy,
            ),
        )
        slot_products = []
        for product in result.products:
            if product.id in seen_ids:
                continue
            seen_ids.add(product.id)
            updated = product.model_copy(update={"reason": f"{slot.title}：{slot.reason}"})
            products.append(updated)
            slot_products.append(product.id)
            if len(slot_products) >= top_k_per_slot:
                break
        diagnostics["slots"].append(
            {
                "key": slot.key,
                "title": slot.title,
                "query": slot.query,
                "constraints": slot.constraints,
                "retrieval_policy": slot.retrieval_policy,
                "product_ids": slot_products,
                "status": result.status,
            }
        )
    return BundleRecommendationResult(scene=scene, slots=slots, products=products, diagnostics=diagnostics)


def build_bundle_answer(result: BundleRecommendationResult) -> str:
    if not result.products:
        return "我理解这是组合搭配需求，但当前商品库没有找到足够合适的商品。可以先放宽品类或预算再试。"
    slot_titles = _join_slot_titles([slot.title for slot in result.slots[:5]])
    return (
        f"我按“{result.scene}”把需求拆成：{slot_titles}。"
        "下面每款商品都对应一个搭配位置，你可以按预算、风格和使用场景取舍。"
    )


def _join_slot_titles(titles: list[str]) -> str:
    clean_titles = [title.strip() for title in titles if title.strip()]
    if not clean_titles:
        return "核心商品"
    if len(clean_titles) == 1:
        return clean_titles[0]
    return "、".join(clean_titles[:-1]) + "和" + clean_titles[-1]


def _slot_from_candidate(slot: BundleSlotCandidate) -> BundleSlot:
    return _compile_slot_contract(
        BundleSlot(
            key=slot.key,
            title=slot.title,
            query=slot.query or " ".join(slot.product_mentions),
            reason=slot.reason,
        ),
        product_mentions=slot.product_mentions,
        attributes_include=slot.attributes_include,
        scene_terms=slot.scene_terms,
    )


def _compile_slot_contract(
    slot: BundleSlot,
    product_mentions: list[str] | None = None,
    attributes_include: list[str] | None = None,
    scene_terms: list[str] | None = None,
) -> BundleSlot:
    candidate = ParsedTurnCandidate(
        raw_message=slot.query,
        intent_type="product_search",
        core_product_query=slot.query,
        product_mentions=product_mentions or [],
        attributes_include=attributes_include or [],
        scene_terms=scene_terms or [],
        source="rule",
    )
    compiled = compile_executable_turn(candidate)
    return BundleSlot(
        key=slot.key,
        title=slot.title,
        query=compiled.normalized_query or slot.query,
        reason=slot.reason,
        constraints=compiled.constraints.model_dump(mode="json"),
        retrieval_policy=compiled.retrieval_policy_hint.model_dump(mode="json"),
    )


def _infer_scene(message: str) -> str:
    return scene_name_for_message(message)
