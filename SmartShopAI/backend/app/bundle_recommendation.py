from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .agent_tools import SearchProductsInput, call_search_products_tool
from .schemas import ProductCard


@dataclass(frozen=True)
class BundleSlot:
    key: str
    title: str
    query: str
    reason: str


@dataclass(frozen=True)
class BundleRecommendationResult:
    scene: str
    slots: list[BundleSlot]
    products: list[ProductCard] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)


def build_bundle_slots(message: str) -> tuple[str, list[BundleSlot]]:
    text = message.strip()
    if any(term in text for term in ("三亚", "海边", "海岛", "沙滩", "度假")):
        scene = "海边度假"
        slots = [
            BundleSlot("sunscreen", "防晒打底", "SPF50 防水 防晒霜 海边 户外", "海边紫外线强，先用高倍防晒做基础防护。"),
            BundleSlot("sun_protection", "物理防晒", "轻薄 防晒衣 透气 户外", "防晒衣能减少长时间暴晒，也适合坐车和逛街。"),
            BundleSlot("shoes", "鞋履", "沙滩 凉鞋 防滑 轻便", "沙滩和酒店来回走动，需要防滑、轻便、好清洁。"),
            BundleSlot("bag", "随身收纳", "防水包 旅行 背包 轻便", "玩水和出门拍照时，手机证件需要更稳妥地收纳。"),
            BundleSlot("repair", "晒后护理", "晒后修复 补水 舒缓 护肤", "晚上回酒店做晒后舒缓，减少干燥和泛红。"),
        ]
        return scene, slots

    if any(term in text for term in ("通勤", "上班", "上学")) and any(term in text for term in ("搭配", "一套", "方案")):
        scene = "日常通勤"
        slots = [
            BundleSlot("top", "上装", "通勤 轻薄 外套 卫衣", "上装优先选耐穿、好打理、适合室内外温差的款式。"),
            BundleSlot("shoes", "鞋履", "通勤 运动鞋 舒适", "通勤走路时间长，鞋子要兼顾缓震和耐磨。"),
            BundleSlot("bag", "包袋", "通勤 背包 轻便 容量", "背包需要放电脑、水杯和随身物品。"),
        ]
        return scene, slots

    scene = "组合搭配"
    slots = [
        BundleSlot("core", "核心商品", text, "先匹配你描述里最核心的商品需求。"),
        BundleSlot("accessory", "配套商品", f"{text} 配套 便携", "再补一个更适合一起购买的配套选择。"),
    ]
    return scene, slots


def retrieve_bundle_recommendations(conn, message: str, top_k_per_slot: int = 1) -> BundleRecommendationResult:
    scene, slots = build_bundle_slots(message)
    products: list[ProductCard] = []
    diagnostics: dict[str, Any] = {"scene": scene, "slots": []}
    seen_ids: set[str] = set()
    for slot in slots:
        result = call_search_products_tool(
            conn,
            SearchProductsInput(
                query=f"{message} {slot.query}",
                top_k=max(top_k_per_slot, 1),
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
                "product_ids": slot_products,
                "status": result.status,
            }
        )
    return BundleRecommendationResult(scene=scene, slots=slots, products=products, diagnostics=diagnostics)


def build_bundle_answer(result: BundleRecommendationResult) -> str:
    if not result.products:
        return "我理解这是组合搭配需求，但当前商品库没有找到足够合适的商品。可以先放宽品类或预算再试。"
    slot_titles = "、".join(slot.title for slot in result.slots[:5])
    return (
        f"我按“{result.scene}”帮你拆成 {slot_titles} 几个部分。"
        "下面每个商品都对应一个搭配位置，你可以先看是否符合预算和风格。"
    )
