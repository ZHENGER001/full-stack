from __future__ import annotations

import json
import uuid
from pathlib import Path as FsPath

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from .agent import analyze_image, save_upload, stream_chat
from .catalog import (
    first_sku,
    get_cart,
    get_categories,
    get_order,
    get_product_detail,
    list_products,
    row_to_product_card,
)
from .config import get_settings
from .database import get_db, init_db
from .schemas import (
    CartItemCreate,
    CartItemPatch,
    CartResponse,
    CategoriesResponse,
    ChatStreamRequest,
    AddressCreate,
    AddressListResponse,
    AddressResponse,
    FavoriteCreate,
    FavoriteListResponse,
    FavoriteResponse,
    FootprintCreate,
    FootprintListResponse,
    FootprintResponse,
    ImageAnalyzeRequest,
    ImageAnalyzeResponse,
    ImageUploadResponse,
    MockPaymentRequest,
    MockPaymentResponse,
    OrderCreate,
    OrderListResponse,
    OrderResponse,
    ProfileSummaryResponse,
    ProductDetail,
    ProductListResponse,
)


settings = get_settings()
app = FastAPI(title="SmartShopAI API", version="0.1.0")
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
settings.upload_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")
if settings.dataset_path.exists():
    app.mount("/assets", StaticFiles(directory=settings.dataset_path), name="assets")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def product_list_json(items, total: int) -> JSONResponse:
    return JSONResponse(content=ProductListResponse(items=items, total=total).model_dump())


def address_from_row(row) -> AddressResponse:
    return AddressResponse(
        id=row["id"],
        receiver_name=row["receiver_name"],
        phone=row["phone"],
        province=row["province"],
        city=row["city"],
        district=row["district"],
        detail=row["detail"],
        is_default=bool(row["is_default"]),
    )


def default_address(conn):
    return conn.execute(
        "SELECT * FROM addresses ORDER BY is_default DESC, created_at DESC LIMIT 1"
    ).fetchone()


def product_exists(conn, product_id: str) -> None:
    if not conn.execute("SELECT id FROM products WHERE id = ?", (product_id,)).fetchone():
        raise HTTPException(status_code=404, detail="Product not found")


@app.get("/api/products", response_model=ProductListResponse)
def api_products(
    keyword: str | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    sort: str | None = None,
    limit: int = Query(default=500, ge=1, le=1000),
):
    with get_db() as conn:
        items, total = list_products(conn, keyword, category, subcategory, min_price, max_price, sort, limit)
        return product_list_json(items, total)


@app.get("/products", response_model=ProductListResponse)
def products(
    keyword: str | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    sort: str | None = None,
    limit: int = Query(default=500, ge=1, le=1000),
):
    return api_products(keyword, category, subcategory, min_price, max_price, sort, limit)


@app.get("/api/products/{product_id}", response_model=ProductDetail)
def api_product_detail(product_id: str):
    with get_db() as conn:
        return get_product_detail(conn, product_id)


@app.get("/api/product-images/{product_id}.jpg")
def api_product_image(product_id: str):
    image_path = product_image_path(product_id)
    return FileResponse(
        image_path,
        headers={"Cache-Control": "public, max-age=86400, immutable"},
    )


@app.get("/api/product-thumbnails/{product_id}.jpg")
def api_product_thumbnail(product_id: str):
    image_path = product_image_path(product_id)
    thumb_dir = settings.upload_dir / "product_thumbnails"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    thumb_path = thumb_dir / f"{product_id}.jpg"
    if not thumb_path.exists() or thumb_path.stat().st_mtime < image_path.stat().st_mtime:
        try:
            from PIL import Image

            with Image.open(image_path) as image:
                image.thumbnail((360, 360))
                image.convert("RGB").save(thumb_path, format="JPEG", quality=82, optimize=True)
        except Exception:
            return FileResponse(
                image_path,
                headers={"Cache-Control": "public, max-age=86400, immutable"},
            )
    return FileResponse(
        thumb_path,
        headers={"Cache-Control": "public, max-age=86400, immutable"},
    )


def product_image_path(product_id: str) -> FsPath:
    with get_db() as conn:
        row = conn.execute("SELECT image_path FROM products WHERE id = ?", (product_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Product not found")
    image_path = settings.dataset_path / FsPath(row["image_path"])
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Product image not found")
    return image_path


@app.get("/products/{product_id}", response_model=ProductDetail)
def product_detail(product_id: str):
    return api_product_detail(product_id)


@app.get("/api/categories", response_model=CategoriesResponse)
def api_categories():
    with get_db() as conn:
        return CategoriesResponse(categories=get_categories(conn))


@app.get("/categories", response_model=CategoriesResponse)
def categories():
    return api_categories()


@app.get("/api/search", response_model=ProductListResponse)
def api_search(
    q: str = Query(default=""),
    category: str | None = None,
    subcategory: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    sort: str | None = None,
    limit: int = Query(default=500, ge=1, le=1000),
):
    with get_db() as conn:
        items, total = list_products(conn, q, category, subcategory, min_price, max_price, sort, limit)
        return product_list_json(items, total)


@app.get("/search", response_model=ProductListResponse)
def search(
    q: str = Query(default=""),
    category: str | None = None,
    subcategory: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    sort: str | None = None,
    limit: int = Query(default=500, ge=1, le=1000),
):
    return api_search(q, category, subcategory, min_price, max_price, sort, limit)


@app.get("/api/profile/summary", response_model=ProfileSummaryResponse)
def api_profile_summary():
    with get_db() as conn:
        return ProfileSummaryResponse(
            favorite_count=int(conn.execute("SELECT COUNT(*) AS total FROM favorites").fetchone()["total"]),
            footprint_count=int(conn.execute("SELECT COUNT(*) AS total FROM footprints").fetchone()["total"]),
            order_count=int(conn.execute("SELECT COUNT(*) AS total FROM orders").fetchone()["total"]),
            cart_count=int(conn.execute("SELECT COUNT(*) AS total FROM cart_items").fetchone()["total"]),
            address_count=int(conn.execute("SELECT COUNT(*) AS total FROM addresses").fetchone()["total"]),
        )


@app.get("/api/favorites", response_model=FavoriteListResponse)
def api_favorites():
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT f.id AS favorite_id, f.created_at,
                   p.id, p.title, p.brand, p.category, p.subcategory, p.price, p.rating, p.image_path,
                   p.marketing_description,
                   COALESCE(rc.review_count, 0) AS review_count,
                   COALESCE(sc.sku_count, 0) AS sku_count,
                   COALESCE(fc.faq_count, 0) AS faq_count,
                   COALESCE(ss.stock, 0) AS stock,
                   ss.sku_summary AS sku_summary
            FROM favorites f
            JOIN products p ON p.id = f.product_id
            LEFT JOIN (SELECT product_id, COUNT(*) AS review_count FROM product_reviews GROUP BY product_id) rc ON rc.product_id = p.id
            LEFT JOIN (SELECT product_id, COUNT(*) AS sku_count FROM product_skus GROUP BY product_id) sc ON sc.product_id = p.id
            LEFT JOIN (SELECT product_id, COUNT(*) AS faq_count FROM product_faqs GROUP BY product_id) fc ON fc.product_id = p.id
            LEFT JOIN (SELECT product_id, SUM(stock) AS stock, GROUP_CONCAT(sku_name, ' / ') AS sku_summary FROM product_skus GROUP BY product_id) ss ON ss.product_id = p.id
            ORDER BY f.created_at DESC
            """
        ).fetchall()
        items = [
            FavoriteResponse(id=row["favorite_id"], product=row_to_product_card(row), created_at=row["created_at"])
            for row in rows
        ]
        return FavoriteListResponse(items=items, total=len(items))


@app.post("/api/favorites", response_model=FavoriteResponse)
def api_add_favorite(payload: FavoriteCreate):
    with get_db() as conn:
        product_exists(conn, payload.product_id)
        favorite_id = f"fav_{uuid.uuid4().hex[:10]}"
        conn.execute(
            """
            INSERT INTO favorites(id, product_id, created_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(product_id) DO UPDATE SET created_at = CURRENT_TIMESTAMP
            """,
            (favorite_id, payload.product_id),
        )
        row = conn.execute(
            """
            SELECT f.id AS favorite_id, f.created_at,
                   p.id, p.title, p.brand, p.category, p.subcategory, p.price, p.rating, p.image_path,
                   p.marketing_description
            FROM favorites f
            JOIN products p ON p.id = f.product_id
            WHERE f.product_id = ?
            """,
            (payload.product_id,),
        ).fetchone()
        return FavoriteResponse(id=row["favorite_id"], product=row_to_product_card(row), created_at=row["created_at"])


@app.delete("/api/favorites/{product_id}", response_model=ProfileSummaryResponse)
def api_delete_favorite(product_id: str):
    with get_db() as conn:
        conn.execute("DELETE FROM favorites WHERE product_id = ?", (product_id,))
        return ProfileSummaryResponse(
            favorite_count=int(conn.execute("SELECT COUNT(*) AS total FROM favorites").fetchone()["total"]),
            footprint_count=int(conn.execute("SELECT COUNT(*) AS total FROM footprints").fetchone()["total"]),
            order_count=int(conn.execute("SELECT COUNT(*) AS total FROM orders").fetchone()["total"]),
            cart_count=int(conn.execute("SELECT COUNT(*) AS total FROM cart_items").fetchone()["total"]),
            address_count=int(conn.execute("SELECT COUNT(*) AS total FROM addresses").fetchone()["total"]),
        )


@app.get("/api/footprints", response_model=FootprintListResponse)
def api_footprints():
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT fp.id AS footprint_id, fp.viewed_at,
                   p.id, p.title, p.brand, p.category, p.subcategory, p.price, p.rating, p.image_path,
                   p.marketing_description
            FROM footprints fp
            JOIN products p ON p.id = fp.product_id
            ORDER BY fp.viewed_at DESC
            """
        ).fetchall()
        items = [
            FootprintResponse(id=row["footprint_id"], product=row_to_product_card(row), viewed_at=row["viewed_at"])
            for row in rows
        ]
        return FootprintListResponse(items=items, total=len(items))


@app.post("/api/footprints", response_model=FootprintResponse)
def api_add_footprint(payload: FootprintCreate):
    with get_db() as conn:
        product_exists(conn, payload.product_id)
        footprint_id = f"fp_{uuid.uuid4().hex[:10]}"
        conn.execute(
            """
            INSERT INTO footprints(id, product_id, viewed_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(product_id) DO UPDATE SET viewed_at = CURRENT_TIMESTAMP
            """,
            (footprint_id, payload.product_id),
        )
        row = conn.execute(
            """
            SELECT fp.id AS footprint_id, fp.viewed_at,
                   p.id, p.title, p.brand, p.category, p.subcategory, p.price, p.rating, p.image_path,
                   p.marketing_description
            FROM footprints fp
            JOIN products p ON p.id = fp.product_id
            WHERE fp.product_id = ?
            """,
            (payload.product_id,),
        ).fetchone()
        return FootprintResponse(id=row["footprint_id"], product=row_to_product_card(row), viewed_at=row["viewed_at"])


@app.get("/api/addresses", response_model=AddressListResponse)
def api_addresses():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM addresses ORDER BY is_default DESC, created_at DESC").fetchall()
        items = [address_from_row(row) for row in rows]
        return AddressListResponse(items=items, total=len(items))


@app.post("/api/addresses", response_model=AddressResponse)
def api_add_address(payload: AddressCreate):
    with get_db() as conn:
        address_id = f"addr_{uuid.uuid4().hex[:10]}"
        should_default = payload.is_default or not conn.execute("SELECT id FROM addresses LIMIT 1").fetchone()
        if should_default:
            conn.execute("UPDATE addresses SET is_default = 0")
        conn.execute(
            """
            INSERT INTO addresses(id, receiver_name, phone, province, city, district, detail, is_default)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                address_id,
                payload.receiver_name,
                payload.phone,
                payload.province,
                payload.city,
                payload.district,
                payload.detail,
                int(should_default),
            ),
        )
        return address_from_row(conn.execute("SELECT * FROM addresses WHERE id = ?", (address_id,)).fetchone())


@app.get("/api/cart", response_model=CartResponse)
def api_get_cart():
    with get_db() as conn:
        return get_cart(conn)


@app.get("/cart", response_model=CartResponse)
def read_cart():
    return api_get_cart()


@app.post("/api/cart/items", response_model=CartResponse)
def api_add_cart_item(payload: CartItemCreate):
    with get_db() as conn:
        product_exists(conn, payload.product_id)
        sku = first_sku(conn, payload.product_id, payload.sku_id)
        sku_id = sku["id"] if sku else payload.sku_id
        current = conn.execute(
            "SELECT id, quantity FROM cart_items WHERE product_id = ? AND COALESCE(sku_id, '') = COALESCE(?, '')",
            (payload.product_id, sku_id),
        ).fetchone()
        if current:
            conn.execute(
                "UPDATE cart_items SET quantity = ?, selected = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (int(current["quantity"]) + payload.quantity, current["id"]),
            )
        else:
            item_id = f"cart_{uuid.uuid4().hex[:10]}"
            conn.execute(
                "INSERT INTO cart_items(id, product_id, sku_id, quantity, selected) VALUES (?, ?, ?, ?, 1)",
                (item_id, payload.product_id, sku_id, payload.quantity),
            )
        return get_cart(conn)


@app.post("/cart/items", response_model=CartResponse)
def add_item(payload: CartItemCreate):
    return api_add_cart_item(payload)


@app.patch("/api/cart/items/{item_id}", response_model=CartResponse)
def api_patch_cart_item(item_id: str, payload: CartItemPatch):
    with get_db() as conn:
        current = conn.execute("SELECT * FROM cart_items WHERE id = ?", (item_id,)).fetchone()
        if not current:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Cart item not found")
        quantity = payload.quantity if payload.quantity is not None else current["quantity"]
        selected = int(payload.selected) if payload.selected is not None else current["selected"]
        conn.execute(
            "UPDATE cart_items SET quantity = ?, selected = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (quantity, selected, item_id),
        )
        return get_cart(conn)


@app.patch("/cart/items/{item_id}", response_model=CartResponse)
def patch_item(item_id: str, payload: CartItemPatch):
    return api_patch_cart_item(item_id, payload)


@app.delete("/api/cart/items/{item_id}", response_model=CartResponse)
def api_delete_cart_item(item_id: str):
    with get_db() as conn:
        conn.execute("DELETE FROM cart_items WHERE id = ?", (item_id,))
        return get_cart(conn)


@app.delete("/cart/items/{item_id}", response_model=CartResponse)
def delete_item(item_id: str):
    return api_delete_cart_item(item_id)


@app.post("/api/orders", response_model=OrderResponse)
def api_create_order(payload: OrderCreate | None = None):
    payload = payload or OrderCreate()
    with get_db() as conn:
        if payload.product_id:
            product_exists(conn, payload.product_id)
            sku = first_sku(conn, payload.product_id, payload.sku_id)
            product = conn.execute("SELECT * FROM products WHERE id = ?", (payload.product_id,)).fetchone()
            selected_items = [
                type(
                    "OrderSourceItem",
                    (),
                    {
                        "product_id": payload.product_id,
                        "sku_id": sku["id"] if sku else payload.sku_id,
                        "title": product["title"],
                        "brand": product["brand"],
                        "image_path": product["image_path"],
                        "sku_name": sku["sku_name"] if sku else "默认规格",
                        "price": float(sku["price"] if sku else product["price"]),
                        "quantity": payload.quantity,
                    },
                )()
            ]
            cart_item_ids: set[str] = set()
        else:
            cart = get_cart(conn)
            cart_item_ids = set(payload.cart_item_ids or [item.id for item in cart.items if item.selected])
            selected_items = [item for item in cart.items if item.id in cart_item_ids]
        if not selected_items:
            raise HTTPException(status_code=400, detail="No selected cart items")
        address = (
            conn.execute("SELECT * FROM addresses WHERE id = ?", (payload.address_id,)).fetchone()
            if payload.address_id
            else default_address(conn)
        )
        if not address:
            raise HTTPException(status_code=400, detail="Shipping address is required")
        order_id = f"ord_{uuid.uuid4().hex[:10]}"
        total = round(sum(item.price * item.quantity for item in selected_items), 2)
        conn.execute(
            """
            INSERT INTO orders(id, status, total_amount, address_id, address_snapshot)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                order_id,
                "pending_payment",
                total,
                address["id"],
                json.dumps(address, ensure_ascii=False),
            ),
        )
        for item in selected_items:
            conn.execute(
                """
                INSERT INTO order_items(id, order_id, product_id, sku_id, title, brand, image_path, sku_name, price, quantity)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"oi_{uuid.uuid4().hex[:10]}",
                    order_id,
                    item.product_id,
                    item.sku_id,
                    item.title,
                    item.brand,
                    item.image_path,
                    item.sku_name,
                    item.price,
                    item.quantity,
                ),
            )
        if cart_item_ids:
            conn.executemany("DELETE FROM cart_items WHERE id = ?", [(item_id,) for item_id in cart_item_ids])
        return get_order(conn, order_id)


@app.post("/orders", response_model=OrderResponse)
def create_order(payload: OrderCreate | None = None):
    return api_create_order(payload)


@app.get("/api/orders", response_model=OrderListResponse)
def api_list_orders():
    with get_db() as conn:
        rows = conn.execute("SELECT id FROM orders ORDER BY created_at DESC").fetchall()
        items = [get_order(conn, row["id"]) for row in rows]
        return OrderListResponse(items=items, total=len(items))


@app.get("/api/orders/{order_id}", response_model=OrderResponse)
def api_get_order(order_id: str):
    with get_db() as conn:
        return get_order(conn, order_id)


@app.get("/orders/{order_id}", response_model=OrderResponse)
def read_order(order_id: str):
    return api_get_order(order_id)


@app.post("/api/payments/mock", response_model=MockPaymentResponse)
def api_mock_payment(payload: MockPaymentRequest):
    if payload.password != "123456":
        raise HTTPException(status_code=400, detail="Payment password is incorrect")
    with get_db() as conn:
        order = get_order(conn, payload.order_id)
        status = "paid" if payload.success else "failed"
        payment_id = f"pay_{uuid.uuid4().hex[:10]}"
        conn.execute(
            "INSERT INTO payments(id, order_id, status, amount) VALUES (?, ?, ?, ?)",
            (payment_id, payload.order_id, status, order.total_amount),
        )
        conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, payload.order_id))
        return MockPaymentResponse(
            payment_id=payment_id,
            order_id=payload.order_id,
            status=status,
            amount=order.total_amount,
        )


@app.post("/payments/mock", response_model=MockPaymentResponse)
def mock_payment(payload: MockPaymentRequest):
    return api_mock_payment(payload)


@app.post("/api/agent/image/upload", response_model=ImageUploadResponse)
def api_image_upload(file: UploadFile = File(...)):
    image_id, image_url, file_path = save_upload(file)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO uploaded_images(image_id, image_url, file_path) VALUES (?, ?, ?)",
            (image_id, image_url, str(file_path)),
        )
    return ImageUploadResponse(image_id=image_id, image_url=image_url)


@app.post("/api/agent/image/analyze", response_model=ImageAnalyzeResponse)
def api_image_analyze(payload: ImageAnalyzeRequest):
    with get_db() as conn:
        detected, query = analyze_image(conn, payload.image_id, payload.user_hint)
        return ImageAnalyzeResponse(image_id=payload.image_id, detected=detected, query=query)


@app.post("/api/agent/chat/stream")
def api_chat_stream(payload: ChatStreamRequest):
    def generate():
        with get_db() as conn:
            yield from stream_chat(conn, payload.session_id, payload.message, payload.image_id)

    return StreamingResponse(generate(), media_type="text/event-stream")
