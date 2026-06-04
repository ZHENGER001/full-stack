from __future__ import annotations

import logging
import re
from typing import Any

from .query_parser import parse_user_filters


logger = logging.getLogger(__name__)


def rerank_products(
    query: str,
    products: list[dict],
    user_filters: dict | None = None,
    session_state: dict | None = None,
    top_k: int = 6,
) -> list[dict]:
    filters = user_filters or parse_user_filters(query)
    try:
        filtered = [product for product in products if passes_hard_filters(product, filters)]
        logger.info(
            "agent_retrieval filters=%s candidates_before=%s candidates_after=%s",
            safe_filters(filters),
            len(products),
            len(filtered),
        )
        ranked = sorted(
            (score_product(query, product, filters, session_state) for product in filtered),
            key=lambda item: item[0],
            reverse=True,
        )
        top_products = []
        for score, product, reasons in ranked[:top_k]:
            enriched = dict(product)
            enriched["rerank_score"] = round(score, 2)
            enriched["rerank_reason"] = "，".join(reasons) if reasons else "基础相关性排序"
            top_products.append(enriched)
        logger.info(
            "agent_top_products=%s",
            [
                {
                    "id": product.get("id"),
                    "title": product.get("title"),
                    "category": product.get("category"),
                    "price": product.get("price"),
                    "rerank_score": product.get("rerank_score"),
                }
                for product in top_products
            ],
        )
        return top_products
    except Exception:
        logger.exception("agent_rerank_failed")
        return [dict(product) for product in products[:top_k]]


def passes_hard_filters(product: dict[str, Any], filters: dict[str, Any]) -> bool:
    if filters.get("max_price") is not None and float(product.get("price") or 0) > float(filters["max_price"]):
        return False
    if float(product.get("stock") or 0) <= 0:
        return False
    target_categories = set(filters.get("target_categories") or [])
    target_subcategories = set(filters.get("target_subcategories") or [])
    if filters.get("explicit_category") and (target_categories or target_subcategories):
        category = product.get("category")
        subcategory = product.get("subcategory")
        search_text = product_text(product)
        category_match = category in target_categories or subcategory in target_subcategories
        text_match = any(term in search_text for term in filters.get("required_terms") or [])
        if not category_match and not text_match:
            return False
    brands = filters.get("brands") or []
    if brands and product.get("brand") not in brands:
        return False
    return True


def score_product(
    query: str,
    product: dict[str, Any],
    filters: dict[str, Any],
    session_state: dict | None,
) -> tuple[float, dict[str, Any], list[str]]:
    score = float(product.get("_retrieval_score") or 0)
    score += float(product.get("_bm25_score") or 0)
    score += float(product.get("_rule_score") or 0)
    reasons: list[str] = []
    search_text = product_text(product)

    if filters.get("explicit_category"):
        if product.get("category") in set(filters.get("target_categories") or []):
            score += 40
            reasons.append("品类匹配")
        if product.get("subcategory") in set(filters.get("target_subcategories") or []):
            score += 55
            reasons.append("子品类匹配")

    for term in query_terms(query):
        if term in str(product.get("title") or "").lower():
            score += 7
        elif term in search_text:
            score += 2

    max_price = filters.get("max_price")
    price = float(product.get("price") or 0)
    if max_price is not None:
        score += max(0.0, 20.0 * (1 - price / max(float(max_price), 1.0)))
        reasons.append("预算内")
    elif filters.get("price_sensitive"):
        score += price_score(price)
        reasons.append("价格友好")

    stock = float(product.get("stock") or 0)
    if stock >= 20:
        score += 8
        reasons.append("库存充足")
    elif stock > 0:
        score += 3
        reasons.append("有库存")

    for scene in filters.get("scene_terms") or []:
        if scene in search_text:
            score += 8
            reasons.append(f"{scene}场景匹配")

    if product.get("review_count"):
        score += min(float(product["review_count"]), 20.0) * 0.2
    if product.get("rating"):
        score += float(product["rating"]) * 1.2
    if float(product.get("_semantic_score") or 0) > 0:
        reasons.append("语义召回匹配")
    if float(product.get("_graph_score") or 0) > 0:
        reasons.append("图关系扩展相关")

    last_ids = (session_state or {}).get("last_recommended_product_ids") or []
    if product.get("id") in last_ids and any(term in query for term in ["刚刚", "刚才", "类似", "更便宜"]):
        score += 10
        reasons.append("多轮上下文相关")

    if "非商业演示" in search_text or "商品目录图片数据" in search_text:
        score -= 20

    return score, product, reasons


def product_text(product: dict[str, Any]) -> str:
    parts = [
        product.get("title"),
        product.get("brand"),
        product.get("category"),
        product.get("subcategory"),
        product.get("marketing_description"),
        product.get("sku_text"),
        product.get("faq_text"),
        product.get("review_text"),
        product.get("chunk_text"),
    ]
    return " ".join(str(part or "") for part in parts).lower()


def query_terms(query: str) -> list[str]:
    lower = (query or "").lower()
    terms = re.findall(r"[a-z0-9]+", lower)
    cjk_chars = [char for char in lower if "\u4e00" <= char <= "\u9fff"]
    terms.extend("".join(cjk_chars[index : index + 2]) for index in range(max(len(cjk_chars) - 1, 0)))
    terms.extend(term for term in ["蓝牙耳机", "耳机", "降噪", "学生党", "通勤", "办公", "游戏", "续航", "拍照"] if term in lower)
    return list(dict.fromkeys(term for term in terms if term))


def price_score(price: float) -> float:
    if price <= 50:
        return 22
    if price <= 100:
        return 19
    if price <= 200:
        return 16
    if price <= 500:
        return 12
    if price <= 1000:
        return 7
    if price <= 2000:
        return 2
    if price <= 3000:
        return -5
    return -14


def safe_filters(filters: dict[str, Any]) -> dict[str, Any]:
    return {
        "target_categories": filters.get("target_categories"),
        "target_subcategories": filters.get("target_subcategories"),
        "max_price": filters.get("max_price"),
        "price_sensitive": filters.get("price_sensitive"),
        "scene_terms": filters.get("scene_terms"),
        "brands": filters.get("brands"),
    }
