from __future__ import annotations

import re
from typing import Any


MAX_DESCRIPTION_CHARS = 520
MAX_SKU_CHARS = 260
MAX_FAQ_CHARS = 360
MAX_REVIEW_CHARS = 360
MAX_CHUNK_CHARS = 260


CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "美妆护肤": ["护肤", "油皮", "干皮", "敏感肌", "控油", "保湿", "修护", "抗老", "清爽", "防晒", "洁面"],
    "数码电子": ["蓝牙", "降噪", "续航", "通勤", "办公", "游戏", "拍照", "快充", "便携", "智能"],
    "服饰运动": ["通勤", "运动", "户外", "休闲", "保暖", "透气", "轻便", "百搭", "跑步"],
    "食品生活": ["零食", "早餐", "冲泡", "健康", "即食", "囤货", "低糖", "便携"],
    "家居百货": ["收纳", "清洁", "厨房", "卧室", "客厅", "浴室", "家用", "耐用"],
    "宠物用品": ["猫", "狗", "宠物", "喂食", "清洁", "玩具", "出行", "护理"],
    "办公文具": ["办公", "学习", "书写", "文件", "桌面", "打印", "收纳", "会议"],
    "旅行户外": ["旅行", "出差", "登机", "户外", "收纳", "背包", "行李箱", "轻便", "防水"],
}


SUBCATEGORY_KEYWORDS: dict[str, list[str]] = {
    "洁面": ["洗面奶", "洁面乳", "清洁", "控油", "泡沫", "不紧绷"],
    "防晒": ["防晒霜", "防晒乳", "通勤防晒", "户外防晒", "清爽", "不油腻"],
    "真无线耳机": ["蓝牙耳机", "无线耳机", "降噪耳机", "通勤耳机", "运动耳机"],
    "智能手机": ["手机", "拍照手机", "游戏手机", "快充", "长续航"],
    "智能手表": ["手表", "运动监测", "健康监测", "腕表", "智能穿戴"],
    "双肩包": ["背包", "电脑包", "通勤包", "上班包", "书包", "出差包"],
    "行李箱": ["登机箱", "拉杆箱", "旅行箱", "万向轮", "出差", "旅行"],
}


def build_product_search_document(row: Any, include_evidence: bool = True) -> str:
    """Build a retrieval-oriented product document for embeddings and lexical search."""
    title = _value(row, "title")
    brand = _value(row, "brand")
    category = _value(row, "category")
    subcategory = _value(row, "subcategory")
    price = _value(row, "price")
    rating = _value(row, "rating")
    stock = _value(row, "stock")
    marketing = _compact(_value(row, "marketing_description"), MAX_DESCRIPTION_CHARS)
    sku_text = _compact(_value(row, "sku_text"), MAX_SKU_CHARS)
    keywords = build_search_keywords(row)

    sections = [
        f"商品名称：{title}",
        f"品牌：{brand}",
        f"类目：{category} > {subcategory}",
        f"价格：{price}",
        f"评分：{rating}",
        f"库存：{stock}",
        f"核心描述：{marketing}",
        f"规格属性：{sku_text}",
        f"搜索关键词：{keywords}",
    ]
    if include_evidence:
        sections.extend(
            [
                f"常见问题摘要：{_compact(_value(row, 'faq_text'), MAX_FAQ_CHARS)}",
                f"用户评价摘要：{_compact(_value(row, 'review_text'), MAX_REVIEW_CHARS)}",
                f"补充检索文本：{_compact(_value(row, 'chunk_text'), MAX_CHUNK_CHARS)}",
            ]
        )
    return "\n".join(section for section in sections if not section.endswith("："))


def build_search_keywords(row: Any) -> str:
    category = _value(row, "category")
    subcategory = _value(row, "subcategory")
    title = _value(row, "title")
    brand = _value(row, "brand")
    marketing = _value(row, "marketing_description")
    terms: list[str] = []
    terms.extend([brand, category, subcategory])
    terms.extend(CATEGORY_KEYWORDS.get(category, []))
    terms.extend(SUBCATEGORY_KEYWORDS.get(subcategory, []))
    terms.extend(_extract_high_signal_terms(f"{title} {marketing}"))
    return " ".join(dict.fromkeys(term for term in terms if term))


def _extract_high_signal_terms(text: str) -> list[str]:
    terms: list[str] = []
    phrase_map = {
        "油皮": ["油皮", "控油", "清爽"],
        "敏感肌": ["敏感肌", "舒缓", "修护"],
        "通勤": ["通勤", "上班", "办公"],
        "蓝牙": ["蓝牙", "无线"],
        "降噪": ["降噪", "安静"],
        "旅行": ["旅行", "出差", "便携"],
        "户外": ["户外", "防水", "耐用"],
    }
    for phrase, expanded in phrase_map.items():
        if phrase in text:
            terms.extend(expanded)
    for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9+.-]{1,}", text):
        terms.append(token.lower())
    return terms[:30]


def _compact(text: str, max_chars: int) -> str:
    compacted = " ".join(str(text or "").split())
    return compacted[:max_chars]


def _value(row: Any, key: str) -> str:
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        value = None
    if value is None:
        return ""
    return str(value).strip()
