from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .query_parser import has_hard_filters
from .query_router import parse_query
from .retrieval import hybrid_search_products
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
                f"{product['title']} {product['brand']} {product['category']} "
                f"{product['subcategory']} price {product['price']} rating {product['rating']}"
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
) -> tuple[list[ProductCard], dict[str, Any]]:
    known_brands = [
        str(row["brand"])
        for row in conn.execute("SELECT DISTINCT brand FROM products").fetchall()
        if row["brand"]
    ]
    parsed_query = parse_query(query, known_brands)
    retrieval_result = hybrid_search_products(conn, parsed_query, limit=max(limit * 8, 20))
    verification = verify_products(retrieval_result.candidates, parsed_query.filters, limit)
    selected_products = verification.products
    fallback_used = False

    if not selected_products and not has_hard_filters(parsed_query.filters):
        fallback_used = True
        cards = fallback_products(conn, QueryIntent(max_price=extract_max_price(query)), limit)
    else:
        cards = [product_dict_to_product_card(product) for product in selected_products]

    diagnostics = {
        **retrieval_result.diagnostics,
        "verifier": verification.diagnostics,
        "fallback": {"used": fallback_used},
        "final_product_ids": [product.id for product in cards],
    }
    return cards, diagnostics


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
