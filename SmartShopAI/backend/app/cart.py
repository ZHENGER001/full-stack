import json

from fastapi import HTTPException

from app.database import db_session
from app.models import Cart, CartItemCreate, CartItemUpdate
from app.products import image_url


def _cart_rows(user_id: str) -> list[dict[str, object]]:
    with db_session() as db:
        return db.execute(
            """
            SELECT
                ci.sku_id, ci.quantity, s.product_id, s.properties_json, s.price,
                p.title, p.brand, p.image_path
            FROM cart_items ci
            JOIN skus s ON s.sku_id = ci.sku_id
            JOIN products p ON p.product_id = s.product_id
            WHERE ci.user_id = ?
            ORDER BY ci.created_at, ci.sku_id
            """,
            (user_id,),
        ).fetchall()


def get_cart(user_id: str) -> Cart:
    items = []
    for row in _cart_rows(user_id):
        quantity = int(row["quantity"])
        unit_price = float(row["price"])
        items.append(
            {
                "sku_id": str(row["sku_id"]),
                "product_id": str(row["product_id"]),
                "title": str(row["title"]),
                "brand": str(row["brand"]),
                "image_url": image_url(str(row["image_path"])),
                "properties": json.loads(str(row["properties_json"])),
                "unit_price": unit_price,
                "quantity": quantity,
                "line_total": round(unit_price * quantity, 2),
            }
        )
    return Cart(
        user_id=user_id,
        items=items,
        total_amount=round(sum(item["line_total"] for item in items), 2),
    )


def add_cart_item(user_id: str, payload: CartItemCreate) -> Cart:
    with db_session() as db:
        sku = db.execute("SELECT sku_id FROM skus WHERE sku_id = ?", (payload.sku_id,)).fetchone()
        if not sku:
            raise HTTPException(status_code=404, detail="SKU not found")
        db.execute(
            """
            INSERT INTO cart_items (user_id, sku_id, quantity, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, sku_id) DO UPDATE SET
                quantity = quantity + excluded.quantity,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, payload.sku_id, payload.quantity),
        )
    return get_cart(user_id)


def update_cart_item(user_id: str, sku_id: str, payload: CartItemUpdate) -> Cart:
    with db_session() as db:
        result = db.execute(
            """
            UPDATE cart_items
            SET quantity = ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND sku_id = ?
            """,
            (payload.quantity, user_id, sku_id),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Cart item not found")
    return get_cart(user_id)


def remove_cart_item(user_id: str, sku_id: str) -> Cart:
    with db_session() as db:
        db.execute("DELETE FROM cart_items WHERE user_id = ? AND sku_id = ?", (user_id, sku_id))
    return get_cart(user_id)

