from __future__ import annotations

import re
from typing import Any


CATEGORY_ALIASES = [
    {
        "terms": ["蓝牙耳机", "耳机", "降噪耳机", "真无线耳机"],
        "categories": ["数码电子"],
        "subcategories": ["真无线耳机"],
        "required_terms": ["耳机"],
    },
    {
        "terms": ["手机", "拍照手机"],
        "categories": ["数码电子"],
        "subcategories": ["智能手机"],
        "required_terms": ["手机"],
    },
    {
        "terms": ["平板", "平板电脑"],
        "categories": ["数码电子"],
        "subcategories": ["平板电脑"],
        "required_terms": ["平板"],
    },
    {
        "terms": ["电脑", "笔记本", "笔记本电脑"],
        "categories": ["数码电子"],
        "subcategories": ["笔记本电脑"],
        "required_terms": ["笔记本", "电脑"],
    },
    {
        "terms": ["卫衣"],
        "categories": ["服饰运动"],
        "subcategories": ["卫衣"],
        "required_terms": ["卫衣"],
    },
    {
        "terms": ["鞋", "跑步鞋", "篮球鞋", "徒步鞋"],
        "categories": ["服饰运动"],
        "subcategories": ["跑步鞋", "篮球鞋", "徒步鞋"],
        "required_terms": ["鞋"],
    },
    {
        "terms": ["包", "背包"],
        "categories": ["旅行户外", "服饰运动"],
        "subcategories": ["背包", "户外背包", "旅行箱包"],
        "required_terms": ["包", "背包"],
    },
    {
        "terms": ["键盘", "鼠标", "充电器", "办公用品", "文具"],
        "categories": ["办公文具"],
        "subcategories": ["办公配件", "书写工具", "本册纸品", "桌面整理", "文件管理"],
        "required_terms": [],
    },
]

SCENE_TERMS = ["降噪", "运动", "通勤", "游戏", "续航", "拍照", "办公", "送礼", "学习", "宿舍"]
PRICE_SENSITIVE_TERMS = ["学生党", "便宜", "性价比", "平价", "预算", "入门"]
COLOR_TERMS = ["黑色", "白色", "蓝色", "红色", "灰色", "粉色", "绿色", "棕色"]


NORMALIZED_CATEGORY_ALIASES = [
    {
        "terms": ["\u624b\u8868", "\u667a\u80fd\u624b\u8868", "\u8155\u8868", "\u8fd0\u52a8\u624b\u8868", "watch", "apple watch"],
        "categories": ["\u6570\u7801\u7535\u5b50"],
        "subcategories": ["\u667a\u80fd\u624b\u8868"],
        "required_terms": ["\u624b\u8868", "\u8155\u8868", "watch"],
    },
    {
        "terms": ["\u624b\u673a", "\u62cd\u7167\u624b\u673a"],
        "categories": ["\u6570\u7801\u7535\u5b50"],
        "subcategories": ["\u667a\u80fd\u624b\u673a"],
        "required_terms": ["\u624b\u673a"],
    },
    {
        "terms": ["\u8033\u673a", "\u84dd\u7259\u8033\u673a", "\u964d\u566a\u8033\u673a", "\u771f\u65e0\u7ebf\u8033\u673a"],
        "categories": ["\u6570\u7801\u7535\u5b50"],
        "subcategories": ["\u771f\u65e0\u7ebf\u8033\u673a"],
        "required_terms": ["\u8033\u673a"],
    },
    {
        "terms": ["\u88e4\u5b50", "\u957f\u88e4", "\u77ed\u88e4", "\u8fd0\u52a8\u88e4"],
        "categories": ["\u670d\u9970\u8fd0\u52a8"],
        "subcategories": ["\u6237\u5916\u88e4", "\u745c\u4f3d\u88e4", "\u8fd0\u52a8\u77ed\u88e4", "\u8fd0\u52a8\u957f\u88e4"],
        "required_terms": ["\u88e4"],
    },
]

EVIDENCE_TERMS = [
    "\u8bc4\u8bba",
    "\u8bc4\u4ef7",
    "\u53e3\u7891",
    "\u7528\u6237\u53cd\u9988",
    "\u4f53\u9a8c",
    "\u597d\u4e0d\u597d",
    "\u600e\u4e48\u6837",
    "\u7f3a\u70b9",
    "\u4f18\u7f3a\u70b9",
    "\u552e\u540e",
    "\u95ee\u7b54",
    "faq",
    "\u6d4b\u8bc4",
    "\u5b9e\u6d4b",
]


def parse_user_filters(query: str, known_brands: list[str] | None = None) -> dict[str, Any]:
    text = query or ""
    text_lower = text.lower()
    categories: set[str] = set()
    subcategories: set[str] = set()
    required_terms: set[str] = set()
    explicit_category = False

    for alias in [*NORMALIZED_CATEGORY_ALIASES, *CATEGORY_ALIASES]:
        if any(term in text or term.lower() in text_lower for term in alias["terms"]):
            explicit_category = True
            categories.update(alias["categories"])
            subcategories.update(alias["subcategories"])
            required_terms.update(alias["required_terms"])

    max_price = extract_max_price(text)
    price_sensitive = max_price is not None or any(term in text for term in PRICE_SENSITIVE_TERMS)
    scenes = [term for term in SCENE_TERMS if term in text]
    colors = [term for term in COLOR_TERMS if term in text]
    brands = [
        brand
        for brand in known_brands or []
        if brand and brand.lower() in text.lower()
    ]
    retrieval_scope = "full_evidence" if any(term in text_lower for term in EVIDENCE_TERMS) else "catalog_only"

    return {
        "raw_query": query,
        "target_categories": sorted(categories),
        "target_subcategories": sorted(subcategories),
        "required_terms": sorted(required_terms),
        "explicit_category": explicit_category,
        "max_price": max_price,
        "price_sensitive": price_sensitive,
        "scene_terms": scenes,
        "colors": colors,
        "brands": brands,
        "retrieval_scope": retrieval_scope,
    }


def extract_max_price(text: str) -> float | None:
    patterns = [
        r"(\d+(?:\.\d+)?)\s*元?\s*(?:以下|以内|内|之内)",
        r"预算\s*(\d+(?:\.\d+)?)",
        r"不超过\s*(\d+(?:\.\d+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return float(match.group(1))
    return None


def has_hard_filters(user_filters: dict[str, Any]) -> bool:
    return bool(
        user_filters.get("explicit_category")
        or user_filters.get("max_price") is not None
        or user_filters.get("brands")
    )
