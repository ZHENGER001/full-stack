import json
from uuid import uuid4

from fastapi import HTTPException

from app.cart import _cart_rows
from app.database import db_session
from app.models import MockPayment, MockPaymentCreate, Order


def create_order_from_cart(user_id: str) -> Order:
    rows = _cart_rows(user_id)
    if not rows:
        raise HTTPException(status_code=400, detail="Cart is empty")

    order_id = f"ord_{uuid4().hex[:16]}"
    total = round(sum(float(row["price"]) * int(row["quantity"]) for row in rows), 2)
    with db_session() as db:
        db.execute(
            """
            INSERT INTO orders (order_id, user_id, status, payment_status, total_amount)
            VALUES (?, ?, 'created', 'unpaid', ?)
            """,
            (order_id, user_id, total),
        )
        for row in rows:
            db.execute(
                """
                INSERT INTO order_items (
                    order_id, sku_id, product_id, title, sku_properties_json,
                    unit_price, quantity
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    row["sku_id"],
                    row["product_id"],
                    row["title"],
                    row["properties_json"],
                    float(row["price"]),
                    int(row["quantity"]),
                ),
            )
        db.execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))
    order = get_order(order_id)
    if not order:
        raise HTTPException(status_code=500, detail="Order creation failed")
    return order


def get_order(order_id: str) -> Order | None:
    with db_session() as db:
        order = db.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        if not order:
            return None
        items = db.execute(
            "SELECT * FROM order_items WHERE order_id = ? ORDER BY sku_id",
            (order_id,),
        ).fetchall()

    return Order(
        order_id=str(order["order_id"]),
        user_id=str(order["user_id"]),
        status=order["status"],
        payment_status=order["payment_status"],
        total_amount=float(order["total_amount"]),
        created_at=str(order["created_at"]),
        items=[
            {
                "sku_id": str(item["sku_id"]),
                "product_id": str(item["product_id"]),
                "title": str(item["title"]),
                "properties": json.loads(str(item["sku_properties_json"])),
                "unit_price": float(item["unit_price"]),
                "quantity": int(item["quantity"]),
                "line_total": round(float(item["unit_price"]) * int(item["quantity"]), 2),
            }
            for item in items
        ],
    )


def mock_pay(payload: MockPaymentCreate) -> MockPayment:
    order = get_order(payload.order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    payment_status = "paid" if payload.success else "failed"
    order_status = "paid" if payload.success else "created"
    with db_session() as db:
        db.execute(
            "UPDATE orders SET status = ?, payment_status = ? WHERE order_id = ?",
            (order_status, payment_status, payload.order_id),
        )
    return MockPayment(
        order_id=payload.order_id,
        payment_status=payment_status,
        order_status=order_status,
    )

