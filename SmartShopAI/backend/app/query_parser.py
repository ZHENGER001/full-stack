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
NEGATION_TERMS = ["不要", "排除", "不想要", "别要", "不考虑", "别推荐", "不要推荐", "不是"]
BRAND_ALIAS_GROUPS = [
    ["Nike", "耐克"],
    ["Apple", "苹果"],
    ["HUAWEI", "华为"],
    ["Xiaomi", "小米"],
]


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

UNKNOWN_EXACT_MAX_CHARS = 8


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
    brands, brands_exclude = extract_brand_filters(text, known_brands or [])
    retrieval_scope = "full_evidence" if any(term in text_lower for term in EVIDENCE_TERMS) else "catalog_only"
    match_mode = None
    if _should_require_exact_term(
        text=text,
        categories=categories,
        subcategories=subcategories,
        max_price=max_price,
        price_sensitive=price_sensitive,
        scenes=scenes,
        colors=colors,
        brands=[*brands, *brands_exclude],
        retrieval_scope=retrieval_scope,
    ):
        match_mode = "exact_or_none"
        required_terms.add(_compact_query(text))

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
        "brands_exclude": brands_exclude,
        "retrieval_scope": retrieval_scope,
        "match_mode": match_mode,
    }


def extract_brand_filters(text: str, known_brands: list[str]) -> tuple[list[str], list[str]]:
    included: list[str] = []
    excluded: list[str] = []
    text_lower = (text or "").lower()

    for mention, aliases in _brand_mentions(known_brands).items():
        start = text_lower.find(mention.lower())
        if start < 0:
            continue
        if _is_negated_brand(text_lower, start):
            excluded = _merge_unique(excluded, aliases)
        else:
            included = _merge_unique(included, aliases)

    excluded_lower = {brand.lower() for brand in excluded}
    included = [brand for brand in included if brand.lower() not in excluded_lower]
    return included, excluded


def _brand_mentions(known_brands: list[str]) -> dict[str, list[str]]:
    mentions: dict[str, list[str]] = {}
    known = [brand.strip() for brand in known_brands if brand and brand.strip()]
    for brand in known:
        mentions[brand] = _merge_unique(mentions.get(brand, []), [brand])
    known_lower = {brand.lower() for brand in known}
    for group in BRAND_ALIAS_GROUPS:
        if not any(alias.lower() in known_lower for alias in group):
            continue
        aliases = _merge_unique([], group)
        for alias in group:
            mentions[alias] = _merge_unique(mentions.get(alias, []), aliases)
    return mentions


def _is_negated_brand(text_lower: str, start: int) -> bool:
    prefix = text_lower[max(0, start - 12) : start]
    return any(term.lower() in prefix for term in NEGATION_TERMS)


def _merge_unique(first: list[str], second: list[str]) -> list[str]:
    return list(dict.fromkeys([*first, *second]))


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
        or user_filters.get("brands_exclude")
        or user_filters.get("required_terms")
        or user_filters.get("allow_popular_fallback") is False
        or user_filters.get("match_mode") == "exact_or_none"
    )


def _should_require_exact_term(
    *,
    text: str,
    categories: set[str],
    subcategories: set[str],
    max_price: float | None,
    price_sensitive: bool,
    scenes: list[str],
    colors: list[str],
    brands: list[str],
    retrieval_scope: str,
) -> bool:
    compact = _compact_query(text)
    if retrieval_scope != "catalog_only" or not compact:
        return False
    if categories or subcategories or max_price is not None or price_sensitive or scenes or colors or brands:
        return False
    if len(compact) > UNKNOWN_EXACT_MAX_CHARS:
        return False
    return bool(re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9]+", compact))


def _compact_query(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip())
