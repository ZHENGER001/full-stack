from __future__ import annotations

import json
import re
from typing import Any

from .schemas import ProductCard


def tokenize(text: str) -> set[str]:
    lower = text.lower()
    ascii_tokens = set(re.findall(r"[a-z0-9]+", lower))
    cjk_tokens = {lower[i : i + 2] for i in range(max(len(lower) - 1, 0)) if "\u4e00" <= lower[i] <= "\u9fff"}
    return ascii_tokens | cjk_tokens


def build_product_chunks(product: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = {
        "product_id": product["id"],
        "title": product["title"],
        "brand": product["brand"],
        "category": product["category"],
        "subcategory": product["subcategory"],
        "price": product["price"],
        "rating": product["rating"],
    }
    chunks = [
        {
            "id": f"{product['id']}:basic_info",
            "product_id": product["id"],
            "chunk_type": "basic_info",
            "content": f"{product['title']} {product['brand']} {product['category']} {product['subcategory']} 价格 {product['price']} 评分 {product['rating']}",
            "metadata_json": json.dumps({**metadata, "chunk_type": "basic_info"}, ensure_ascii=False),
        },
        {
            "id": f"{product['id']}:marketing",
            "product_id": product["id"],
            "chunk_type": "marketing",
            "content": product.get("marketing_description", ""),
            "metadata_json": json.dumps({**metadata, "chunk_type": "marketing"}, ensure_ascii=False),
        },
    ]
    return [chunk for chunk in chunks if chunk["content"]]


def search_products_for_agent(conn, query: str, limit: int = 3) -> list[ProductCard]:
    expanded_query = expand_query(query)
    max_price = extract_max_price(expanded_query)
    strong_terms = required_terms(expanded_query)
    query_tokens = tokenize(expanded_query)
    rows = conn.execute(
        """
        SELECT p.*, GROUP_CONCAT(r.content, ' ') AS review_text
        FROM products p
        LEFT JOIN product_reviews r ON r.product_id = p.id
        GROUP BY p.id
        """
    ).fetchall()
    scored: list[tuple[float, Any, str]] = []
    for row in rows:
        if max_price is not None and float(row["price"]) > max_price:
            continue
        text = " ".join(
            [
                row["title"],
                row["brand"],
                row["category"],
                row["subcategory"],
                row["marketing_description"],
                row["review_text"] or "",
            ]
        )
        if strong_terms and not any(term in text for term in strong_terms):
            continue
        tokens = tokenize(text)
        score = len(query_tokens & tokens)
        for phrase in ["油皮", "控油", "洗面奶", "洁面", "蓝牙", "耳机", "外套", "鞋", "休闲", "黑色"]:
            if phrase in expanded_query and phrase in text:
                score += 3
        if ("洗面奶" in expanded_query or "洁面" in expanded_query) and (
            "洁面" in row["subcategory"] or "洁面" in row["title"] or "洗面奶" in row["title"]
        ):
            score += 12
        if ("洗面奶" in expanded_query or "洁面" in expanded_query) and row["subcategory"] in {"蜜粉", "防晒", "口红", "精华"}:
            score -= 8
        if ("蓝牙" in expanded_query or "耳机" in expanded_query) and (
            "耳机" in row["subcategory"] or "耳机" in row["title"] or "蓝牙" in text
        ):
            score += 12
        if score > 0:
            reason = build_reason(row, expanded_query)
            scored.append((score + float(row["rating"]) / 10, row, reason))
    if not scored and strong_terms:
        return []
    if not scored:
        fallback = conn.execute(
            "SELECT * FROM products WHERE price <= COALESCE(?, price) ORDER BY rating DESC LIMIT ?",
            (max_price, limit),
        ).fetchall()
        return [
            row_to_product_card_for_agent(row, "当前商品数据匹配信息有限，按评分和价格约束给出候选。")
            for row in fallback
        ]
    scored.sort(key=lambda item: item[0], reverse=True)
    return [row_to_product_card_for_agent(row, reason) for _, row, reason in scored[:limit]]


def extract_max_price(text: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*元?\s*(?:以下|以内|内|之内)", text)
    if match:
        return float(match.group(1))
    return None


def expand_query(query: str) -> str:
    additions = []
    if "洗面奶" in query:
        additions.extend(["洁面", "清洁"])
    if "油皮" in query:
        additions.extend(["控油", "清爽"])
    if "同款" in query or "类似" in query:
        additions.append("相似")
    return " ".join([query, *additions])


def required_terms(query: str) -> set[str]:
    terms = set()
    if "蓝牙" in query or "耳机" in query:
        terms.update({"蓝牙", "耳机"})
    if "洗面奶" in query or "洁面" in query:
        terms.update({"洗面奶", "洁面"})
    if "外套" in query:
        terms.update({"外套", "夹克", "卫衣", "上衣"})
    return terms


def build_reason(row: Any, query: str) -> str:
    parts = []
    if row["subcategory"] in query or row["category"] in query:
        parts.append(f"品类匹配{row['subcategory']}")
    if row["brand"] in query:
        parts.append(f"品牌匹配{row['brand']}")
    if "油皮" in query and ("油" in row["marketing_description"] or "洁面" in row["subcategory"]):
        parts.append("适合围绕肤质和清洁需求进一步比较")
    if "蓝牙" in query and ("蓝牙" in row["marketing_description"] or "耳机" in row["title"]):
        parts.append("标题或卖点中包含蓝牙/耳机相关信息")
    if not parts:
        parts.append("与当前需求在标题、分类、描述或评价中有匹配")
    return "，".join(parts) + "。"


def row_to_product_card_for_agent(row: Any, reason: str | None = None) -> ProductCard:
    return ProductCard(
        id=row["id"],
        title=row["title"],
        brand=row["brand"],
        category=row["category"],
        subcategory=row["subcategory"],
        price=float(row["price"]),
        rating=float(row["rating"]),
        image_path=f"/api/product-images/{row['id']}.jpg",
        reason=reason,
    )
