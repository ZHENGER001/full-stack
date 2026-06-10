from __future__ import annotations

import json
import re
from typing import Any

from fastapi import HTTPException

from .catalog_grounder import ground_catalog_terms
from .schemas import (
    AddressResponse,
    CartItem,
    CartResponse,
    CategoryItem,
    OrderItem,
    OrderResponse,
    ProductCard,
    ProductDetail,
)


def row_to_product_card(row: Any, reason: str | None = None) -> ProductCard:
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
        marketing_description=compact_text(row["marketing_description"], 140) if "marketing_description" in row.keys() else None,
        review_count=int(row["review_count"]) if "review_count" in row.keys() and row["review_count"] is not None else 0,
        sku_count=int(row["sku_count"]) if "sku_count" in row.keys() and row["sku_count"] is not None else 0,
        faq_count=int(row["faq_count"]) if "faq_count" in row.keys() and row["faq_count"] is not None else 0,
        stock=int(row["stock"]) if "stock" in row.keys() and row["stock"] is not None else 0,
        sku_summary=compact_text(row["sku_summary"], 80) if "sku_summary" in row.keys() else None,
        faq_summary=split_summary(row["faq_summary"], 60) if "faq_summary" in row.keys() else [],
        review_summary=split_summary(row["review_summary"], 60) if "review_summary" in row.keys() else [],
    )


def list_products(
    conn,
    keyword: str | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    sort: str | None = None,
    limit: int = 500,
) -> tuple[list[ProductCard], int]:
    keyword, min_price, max_price = apply_keyword_price_constraints(keyword, min_price, max_price)
    inferred_subcategories = infer_explicit_subcategories(keyword) if keyword and not subcategory else []
    where = []
    params: list[Any] = []
    if keyword:
        term_clauses = []
        for term in expand_search_terms(keyword):
            term_clauses.append(
                "(title LIKE ? OR brand LIKE ? OR category LIKE ? OR subcategory LIKE ? OR marketing_description LIKE ?)"
            )
            like = f"%{term}%"
            params.extend([like, like, like, like, like])
        where.append(f"({' OR '.join(term_clauses)})")
    if category:
        where.append("category = ?")
        params.append(category)
    if subcategory:
        where.append("subcategory = ?")
        params.append(subcategory)
    elif inferred_subcategories:
        placeholders = ", ".join("?" for _ in inferred_subcategories)
        where.append(f"subcategory IN ({placeholders})")
        params.extend(inferred_subcategories)
    if min_price is not None:
        where.append("price >= ?")
        params.append(min_price)
    if max_price is not None:
        where.append("price <= ?")
        params.append(max_price)

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    order_sql = {
        "price_asc": "ORDER BY price ASC",
        "price_desc": "ORDER BY price DESC",
        "rating": "ORDER BY rating DESC",
    }.get(sort or "", "ORDER BY rating DESC, id ASC")

    total = conn.execute(f"SELECT COUNT(*) AS total FROM products {where_sql}", params).fetchone()["total"]
    query_limit = 1000 if keyword and not sort else limit
    rows = conn.execute(
        f"""
        SELECT p.id, p.title, p.brand, p.category, p.subcategory, p.price, p.rating, p.image_path,
               p.marketing_description,
               COALESCE(rc.review_count, 0) AS review_count,
               COALESCE(sc.sku_count, 0) AS sku_count,
               COALESCE(fc.faq_count, 0) AS faq_count,
               COALESCE(ss.stock, 0) AS stock,
               ss.sku_summary AS sku_summary,
               fs.faq_summary AS faq_summary,
               rs.review_summary AS review_summary
        FROM products p
        LEFT JOIN (
            SELECT product_id, COUNT(*) AS review_count
            FROM product_reviews
            GROUP BY product_id
        ) rc ON rc.product_id = p.id
        LEFT JOIN (
            SELECT product_id, COUNT(*) AS sku_count
            FROM product_skus
            GROUP BY product_id
        ) sc ON sc.product_id = p.id
        LEFT JOIN (
            SELECT product_id, COUNT(*) AS faq_count
            FROM product_faqs
            GROUP BY product_id
        ) fc ON fc.product_id = p.id
        LEFT JOIN (
            SELECT product_id, SUM(stock) AS stock, GROUP_CONCAT(sku_name, ' / ') AS sku_summary
            FROM product_skus
            GROUP BY product_id
        ) ss ON ss.product_id = p.id
        LEFT JOIN (
            SELECT product_id, GROUP_CONCAT(question || char(10) || answer, '|||') AS faq_summary
            FROM (
                SELECT product_id, question, answer,
                       ROW_NUMBER() OVER (PARTITION BY product_id ORDER BY id) AS row_no
                FROM product_faqs
            )
            WHERE row_no <= 1
            GROUP BY product_id
        ) fs ON fs.product_id = p.id
        LEFT JOIN (
            SELECT product_id, GROUP_CONCAT(nickname || '：' || content, '|||') AS review_summary
            FROM (
                SELECT product_id, nickname, content,
                       ROW_NUMBER() OVER (PARTITION BY product_id ORDER BY id) AS row_no
                FROM product_reviews
            )
            WHERE row_no <= 1
            GROUP BY product_id
        ) rs ON rs.product_id = p.id
        {where_sql}
        {order_sql}
        LIMIT ?
        """,
        params + [query_limit],
    ).fetchall()
    if keyword and not sort:
        search_terms = expand_search_terms(keyword)
        rows = sorted(rows, key=lambda row: relevance_score(row, search_terms), reverse=True)
        rows = rows[:limit]
    return [row_to_product_card(row) for row in rows], int(total)


def infer_explicit_subcategories(keyword: str | None) -> list[str]:
    if not keyword:
        return []
    matches = [match for match in ground_catalog_terms(keyword).matches if match.subcategories]
    if not matches:
        return []
    max_term_length = max(len(match.term) for match in matches)
    subcategories: list[str] = []
    for match in matches:
        if len(match.term) == max_term_length:
            subcategories.extend(match.subcategories)
    return list(dict.fromkeys(subcategories))


def expand_search_terms(keyword: str) -> list[str]:
    terms = [keyword]
    if "洗面奶" in keyword:
        terms.extend(["洁面", "洁面乳"])
    if "油皮" in keyword:
        terms.extend(["控油", "清爽"])
    if "蓝牙耳机" in keyword:
        terms.extend(["蓝牙", "耳机"])
    if "手机" in keyword:
        terms.extend(["智能手机", "5G"])
    return list(dict.fromkeys(term for term in terms if term.strip()))


def apply_keyword_price_constraints(
    keyword: str | None,
    min_price: float | None,
    max_price: float | None,
) -> tuple[str | None, float | None, float | None]:
    if not keyword:
        return keyword, min_price, max_price

    if max_price is None:
        under_match = re.search(r"(\d+(?:\.\d+)?)\s*元?\s*(以下|以内|内)", keyword)
        if under_match:
            max_price = float(under_match.group(1))
        else:
            under_match = re.search(r"(低于|不超过|小于|少于)\s*(\d+(?:\.\d+)?)", keyword)
            if under_match:
                max_price = float(under_match.group(2))

    if min_price is None:
        over_match = re.search(r"(\d+(?:\.\d+)?)\s*元?\s*(以上|起)", keyword)
        if over_match:
            min_price = float(over_match.group(1))
        else:
            over_match = re.search(r"(高于|超过|大于)\s*(\d+(?:\.\d+)?)", keyword)
            if over_match:
                min_price = float(over_match.group(2))

    return keyword, min_price, max_price


def relevance_score(row: Any, terms: list[str]) -> float:
    title = row["title"]
    brand = row["brand"]
    category = row["category"]
    subcategory = row["subcategory"]
    marketing = row["marketing_description"]
    score = float(row["rating"]) / 10
    for term in terms:
        if term in title:
            score += 20
        if term in subcategory:
            score += 15
        if term in brand:
            score += 8
        if term in category:
            score += 4
        if term in marketing:
            score += 1
    return score


def compact_text(value: str | None, max_length: int) -> str | None:
    if not value:
        return value
    text = " ".join(str(value).split())
    if len(text) <= max_length:
        return text
    return f"{text[:max_length].rstrip()}..."


def split_summary(value: str | None, max_length: int) -> list[str]:
    if not value:
        return []
    return [
        compact_text(part, max_length) or ""
        for part in str(value).split("|||")
        if part.strip()
    ]


def get_product_detail(conn, product_id: str) -> ProductDetail:
    product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    faqs = [
        {"question": row["question"], "answer": row["answer"]}
        for row in conn.execute(
            "SELECT question, answer FROM product_faqs WHERE product_id = ? ORDER BY id",
            (product_id,),
        ).fetchall()
    ]
    reviews = [
        {"nickname": row["nickname"], "rating": float(row["rating"]), "content": row["content"]}
        for row in conn.execute(
            "SELECT nickname, rating, content FROM product_reviews WHERE product_id = ? ORDER BY id",
            (product_id,),
        ).fetchall()
    ]
    skus = [
        {
            "sku_id": row["id"],
            "sku_name": row["sku_name"],
            "properties": json.loads(row["properties_json"]),
            "price": float(row["price"]),
            "stock": int(row["stock"]),
        }
        for row in conn.execute(
            "SELECT id, sku_name, properties_json, price, stock FROM product_skus WHERE product_id = ? ORDER BY id",
            (product_id,),
        ).fetchall()
    ]
    return ProductDetail(
        id=product["id"],
        title=product["title"],
        brand=product["brand"],
        category=product["category"],
        subcategory=product["subcategory"],
        price=float(product["price"]),
        rating=float(product["rating"]),
        image_path=f"/api/product-images/{product['id']}.jpg",
        reason=None,
        marketing_description=product["marketing_description"],
        official_faq=faqs,
        user_reviews=reviews,
        skus=skus,
    )


def get_categories(conn) -> list[CategoryItem]:
    rows = conn.execute(
        "SELECT category, subcategory FROM products GROUP BY category, subcategory ORDER BY category, subcategory"
    ).fetchall()
    grouped: dict[str, list[str]] = {}
    for row in rows:
        grouped.setdefault(row["category"], [])
        if row["subcategory"] not in grouped[row["category"]]:
            grouped[row["category"]].append(row["subcategory"])
    return [CategoryItem(name=name, subcategories=subs) for name, subs in grouped.items()]


def first_sku(conn, product_id: str, sku_id: str | None = None):
    if sku_id:
        sku = conn.execute(
            "SELECT * FROM product_skus WHERE product_id = ? AND id = ?",
            (product_id, sku_id),
        ).fetchone()
        if sku:
            return sku
    return conn.execute(
        "SELECT * FROM product_skus WHERE product_id = ? ORDER BY price ASC LIMIT 1",
        (product_id,),
    ).fetchone()


def get_cart(conn) -> CartResponse:
    rows = conn.execute(
        """
        SELECT c.id, c.product_id, c.sku_id, c.quantity, c.selected,
               p.title, p.brand, p.image_path, p.price AS product_price,
               s.sku_name, s.price AS sku_price
        FROM cart_items c
        JOIN products p ON p.id = c.product_id
        LEFT JOIN product_skus s ON s.id = c.sku_id
        ORDER BY c.created_at DESC
        """
    ).fetchall()
    items = [
        CartItem(
            id=row["id"],
            product_id=row["product_id"],
            sku_id=row["sku_id"],
            title=row["title"],
            brand=row["brand"],
            image_path=row["image_path"],
            sku_name=row["sku_name"] or "默认规格",
            price=float(row["sku_price"] or row["product_price"]),
            quantity=int(row["quantity"]),
            selected=bool(row["selected"]),
        )
        for row in rows
    ]
    return CartResponse(
        items=items,
        total_amount=round(sum(item.price * item.quantity for item in items if item.selected), 2),
    )


def get_order(conn, order_id: str) -> OrderResponse:
    order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    address = None
    if order.get("address_snapshot"):
        snapshot = json.loads(order["address_snapshot"])
        address = AddressResponse(
            id=snapshot.get("id", order.get("address_id") or ""),
            receiver_name=snapshot.get("receiver_name", ""),
            phone=snapshot.get("phone", ""),
            province=snapshot.get("province", ""),
            city=snapshot.get("city", ""),
            district=snapshot.get("district", ""),
            detail=snapshot.get("detail", ""),
            is_default=bool(snapshot.get("is_default", False)),
        )
    rows = conn.execute(
        "SELECT * FROM order_items WHERE order_id = ? ORDER BY id",
        (order_id,),
    ).fetchall()
    return OrderResponse(
        id=order["id"],
        status=order["status"],
        total_amount=float(order["total_amount"]),
        address=address,
        items=[
            OrderItem(
                id=row["id"],
                product_id=row["product_id"],
                sku_id=row["sku_id"],
                title=row["title"],
                brand=row["brand"],
                image_path=row["image_path"],
                sku_name=row["sku_name"],
                price=float(row["price"]),
                quantity=int(row["quantity"]),
            )
            for row in rows
        ],
    )
