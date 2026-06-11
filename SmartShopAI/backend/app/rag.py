from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .query_parser import has_hard_filters, narrow_to_explicit_subcategories
from .query_router import ParsedQuery, parse_query
from .retrieval import hybrid_search_products
from .search_document import build_search_keywords
from .schemas import ProductCard
from .verifier import verify_products


@dataclass(frozen=True)
class QueryIntent:
    max_price: float | None


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
            "content": (
                f"商品名称：{product['title']}\n"
                f"品牌：{product['brand']}\n"
                f"类目：{product['category']} > {product['subcategory']}\n"
                f"价格：{product['price']}\n"
                f"评分：{product['rating']}\n"
                f"搜索关键词：{build_search_keywords(product)}"
            ),
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
    products, _ = search_products_for_agent_with_diagnostics(conn, query, limit)
    return products


def search_products_for_agent_with_diagnostics(
    conn,
    query: str,
    limit: int = 3,
    constraints: dict[str, Any] | None = None,
    retrieval_policy: dict[str, Any] | None = None,
) -> tuple[list[ProductCard], dict[str, Any]]:
    # 商品 RAG 主入口：先解析 query 和工具约束，再做混合召回，最后由 verifier 做硬过滤。
    known_brands = [
        str(row["brand"])
        for row in conn.execute("SELECT DISTINCT brand FROM products").fetchall()
        if row["brand"]
    ]
    parsed_query = parse_query(query, known_brands)
    parsed_query = apply_tool_constraints(parsed_query, constraints or {}, retrieval_policy or {})
    retrieval_result = hybrid_search_products(conn, parsed_query, limit=max(limit * 8, 20))
    # verifier 负责价格、品类、品牌、必含词等硬约束，避免召回结果直接透出。
    verification = verify_products(retrieval_result.candidates, parsed_query.filters, limit)
    selected_products, confidence_diagnostics = apply_confidence_gate(verification.products, parsed_query.filters)
    fallback_used = False
    alternative_cards: list[ProductCard] = []
    confidence_rejected = confidence_diagnostics["status"] == "rejected"

    allow_popular_fallback = parsed_query.filters.get("allow_popular_fallback", True)
    if (
        not selected_products
        and allow_popular_fallback
        and not confidence_rejected
        and not has_hard_filters(parsed_query.filters)
    ):
        # 只有在没有硬过滤条件时才允许热门兜底；强约束查询宁可返回空/替代品。
        fallback_used = True
        cards = fallback_products(conn, QueryIntent(max_price=extract_max_price(query)), limit)
    else:
        cards = [product_dict_to_product_card(product) for product in selected_products]
        if not cards:
            alternative_cards = build_alternative_products(retrieval_result.candidates, parsed_query.filters, limit)

    retrieval_degradation = retrieval_result.diagnostics.get("degradation", {})
    diagnostics = {
        **retrieval_result.diagnostics,
        "verifier": verification.diagnostics,
        "confidence": confidence_diagnostics,
        "fallback": {
            "used": bool(fallback_used or retrieval_degradation.get("used")),
            "popular_fallback_used": fallback_used,
            "retrieval_degraded": bool(retrieval_degradation.get("used")),
            "reason": "popular_products" if fallback_used else retrieval_degradation.get("reason"),
        },
        "alternatives": {
            "used": bool(alternative_cards),
            "reason": "price_relaxed" if alternative_cards else None,
            "products": [product.model_dump(mode="json") for product in alternative_cards],
        },
        "final_product_ids": [product.id for product in cards],
    }
    return cards, diagnostics


def apply_confidence_gate(
    products: list[dict[str, Any]],
    filters: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not products:
        return products, {"status": "pass", "reason": None}
    if has_hard_filters(filters):
        return products, {"status": "pass", "reason": None}

    weak_products = [
        product
        for product in products
        if _is_dense_only_weak_match(product)
    ]
    if weak_products and len(weak_products) == len(products):
        return [], {
            "status": "rejected",
            "reason": "dense_only_without_lexical_support",
            "product_ids": [product.get("id") for product in weak_products],
        }
    return products, {"status": "pass", "reason": None}


def _is_dense_only_weak_match(product: dict[str, Any]) -> bool:
    sources = set(product.get("_sources") or [])
    if sources != {"dense"}:
        return False
    return float(product.get("_bm25_score") or 0.0) <= 0 and float(product.get("_keyword_score") or 0.0) <= 0


def apply_tool_constraints(
    parsed_query: ParsedQuery,
    constraints: dict[str, Any],
    retrieval_policy: dict[str, Any],
) -> ParsedQuery:
    filters = dict(parsed_query.filters)
    route_notes = list(parsed_query.route_notes)

    categories = _list_value(constraints.get("categories"))
    subcategories = _list_value(constraints.get("subcategories"))
    required_terms = _list_value(constraints.get("required_terms"))
    brands_include = _list_value(constraints.get("brands_include"))
    brands_exclude = _list_value(constraints.get("brands_exclude"))
    attributes_include = _list_value(constraints.get("attributes_include"))
    attributes_exclude = _list_value(constraints.get("attributes_exclude"))
    scene_terms = _list_value(constraints.get("scene_terms"))
    negative_terms = _list_value(constraints.get("negative_terms"))
    price = constraints.get("price") if isinstance(constraints.get("price"), dict) else {}

    if categories:
        filters["target_categories"] = _merge_unique(filters.get("target_categories") or [], categories)
        filters["explicit_category"] = True
        route_notes.append("turn_category")
    if subcategories:
        filters["target_subcategories"] = _merge_unique(filters.get("target_subcategories") or [], subcategories)
        filters["explicit_category"] = True
        route_notes.append("turn_subcategory")
    if required_terms:
        filters["required_terms"] = _merge_unique(filters.get("required_terms") or [], required_terms)
        route_notes.append("turn_required_terms")
    if brands_include:
        filters["brands"] = _merge_unique(filters.get("brands") or [], brands_include)
        route_notes.append("turn_brand")
    if brands_exclude:
        filters["brands_exclude"] = _merge_unique(filters.get("brands_exclude") or [], brands_exclude)
    if filters.get("brands") and filters.get("brands_exclude"):
        excluded_lower = {str(brand).lower() for brand in filters["brands_exclude"]}
        filters["brands"] = [brand for brand in filters["brands"] if str(brand).lower() not in excluded_lower]
    if attributes_include:
        filters["attributes_include"] = _merge_unique(filters.get("attributes_include") or [], attributes_include)
    if attributes_exclude:
        filters["attributes_exclude"] = _merge_unique(filters.get("attributes_exclude") or [], attributes_exclude)
    if scene_terms:
        filters["scene_terms"] = _merge_unique(filters.get("scene_terms") or [], scene_terms)
    if negative_terms:
        filters["negative_terms"] = _merge_unique(filters.get("negative_terms") or [], negative_terms)
    if price.get("max") is not None:
        filters["max_price"] = price["max"]
        filters["price_sensitive"] = True
    if price.get("min") is not None:
        filters["min_price"] = price["min"]

    if retrieval_policy.get("image_wide_match"):
        filters["explicit_category"] = False
        filters["match_mode"] = None
        filters["allow_popular_fallback"] = False
        filters["require_lexical_anchor"] = False
        route_notes.append("image_wide_match")

    for key in ["match_mode", "allow_popular_fallback", "allow_dense_only", "require_lexical_anchor"]:
        if key in retrieval_policy and retrieval_policy[key] is not None:
            filters[key] = retrieval_policy[key]
    if filters.get("match_mode") == "exact_or_none":
        route_notes.append("exact_or_none")

    filters = narrow_to_explicit_subcategories(filters, parsed_query.raw_query)
    expansion_terms = [
        parsed_query.raw_query,
        *(filters.get("target_categories") or []),
        *(filters.get("target_subcategories") or []),
        *(filters.get("required_terms") or []),
        *(filters.get("attributes_include") or []),
        *(filters.get("scene_terms") or []),
    ]
    rewritten_query = " ".join(dict.fromkeys(str(term).strip() for term in expansion_terms if str(term).strip()))
    return ParsedQuery(
        raw_query=parsed_query.raw_query,
        rewritten_query=rewritten_query or parsed_query.rewritten_query,
        filters=filters,
        route_notes=list(dict.fromkeys(route_notes)),
    )


def _list_value(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _merge_unique(first: list[Any], second: list[str]) -> list[str]:
    return list(dict.fromkeys([str(item) for item in first if str(item).strip()] + second))


def extract_max_price(text: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:元|块|rmb|RMB)?\s*(?:以下|以内|内|之内)", text or "")
    if match:
        return float(match.group(1))
    return None


def fallback_products(conn, intent: QueryIntent, limit: int) -> list[ProductCard]:
    rows = conn.execute(
        """
        SELECT p.*, COALESCE(SUM(s.stock), 0) AS stock
        FROM products p
        LEFT JOIN product_skus s ON s.product_id = p.id
        WHERE p.price <= COALESCE(?, p.price)
        GROUP BY p.id
        ORDER BY
            CASE WHEN COALESCE(SUM(s.stock), 0) > 0 THEN 0 ELSE 1 END,
            p.rating DESC,
            p.price ASC
        LIMIT ?
        """,
        (intent.max_price, limit),
    ).fetchall()
    return [
        row_to_product_card_for_agent(row, "Fallback match by stock, rating, and price.")
        for row in rows
    ]


def build_alternative_products(candidates: list[dict[str, Any]], filters: dict[str, Any], limit: int) -> list[ProductCard]:
    if not candidates or (filters.get("max_price") is None and filters.get("min_price") is None):
        return []

    relaxed_filters = dict(filters)
    max_price = relaxed_filters.pop("max_price", None)
    min_price = relaxed_filters.pop("min_price", None)
    relaxed_filters["price_sensitive"] = False

    relaxed = verify_products(candidates, relaxed_filters, limit=len(candidates))
    relaxed_products = [
        product
        for product in relaxed.products
        if _matches_target_catalog(product, filters)
    ]
    alternatives = sorted(
        relaxed_products,
        key=lambda product: (_price_distance(product, max_price, min_price), float(product.get("price") or 0)),
    )[:limit]

    cards: list[ProductCard] = []
    for product in alternatives:
        item = dict(product)
        item["reason"] = "预算条件放宽后的相近选择，品类仍匹配你的需求，但价格可能高于原预算。"
        item["rerank_reason"] = item["reason"]
        cards.append(product_dict_to_product_card(item))
    return cards


def _matches_target_catalog(product: dict[str, Any], filters: dict[str, Any]) -> bool:
    target_subcategories = set(filters.get("target_subcategories") or [])
    if target_subcategories and product.get("subcategory") not in target_subcategories:
        return False
    target_categories = set(filters.get("target_categories") or [])
    if target_categories and product.get("category") not in target_categories:
        return False
    return True


def _price_distance(product: dict[str, Any], max_price: Any, min_price: Any) -> float:
    price = float(product.get("price") or 0)
    if max_price is not None and price > float(max_price):
        return price - float(max_price)
    if min_price is not None and price < float(min_price):
        return float(min_price) - price
    return 0.0


def product_dict_to_product_card(product: dict[str, Any]) -> ProductCard:
    reason = product.get("rerank_reason") or product.get("reason")
    return ProductCard(
        id=product["id"],
        title=product["title"],
        brand=product["brand"],
        category=product.get("category"),
        subcategory=product.get("subcategory"),
        price=float(product["price"]),
        rating=float(product.get("rating") or 0),
        image_path=product.get("image_path") or f"/api/product-thumbnails/{product['id']}.jpg",
        reason=reason,
        marketing_description=product.get("marketing_description"),
        stock=int(product.get("stock") or 0),
        rerank_score=product.get("rerank_score"),
        rerank_reason=product.get("rerank_reason"),
    )


def row_to_product_card_for_agent(row: Any, reason: str | None = None) -> ProductCard:
    return ProductCard(
        id=row["id"],
        title=row["title"],
        brand=row["brand"],
        category=row["category"],
        subcategory=row["subcategory"],
        price=float(row["price"]),
        rating=float(row["rating"]),
        image_path=f"/api/product-thumbnails/{row['id']}.jpg",
        reason=reason,
    )
