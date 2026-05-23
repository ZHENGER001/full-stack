from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Iterable

from fastapi import HTTPException, UploadFile

from .config import get_settings
from .rag import search_products_for_agent


def sse_event(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def mock_detect_from_hint(user_hint: str | None, filename: str | None = None) -> dict[str, str]:
    text = f"{user_hint or ''} {filename or ''}".lower()
    if any(word in text for word in ["鞋", "shoe", "sneaker", "跑步"]):
        return {"object_type": "鞋", "color": "黑色", "style": "运动", "material": "织物", "scene": "跑步通勤"}
    if any(word in text for word in ["耳机", "headphone", "earbud"]):
        return {"object_type": "耳机", "color": "黑色", "style": "简约", "material": "塑料", "scene": "通勤降噪"}
    if any(word in text for word in ["外套", "jacket", "coat", "衣"]):
        return {"object_type": "外套", "color": "黑色", "style": "休闲", "material": "皮革", "scene": "街拍"}
    if any(word in text for word in ["洗面奶", "洁面", "护肤", "beauty"]):
        return {"object_type": "洁面产品", "color": "白色", "style": "护肤", "material": "乳液", "scene": "日常洁面"}
    return {"object_type": "商品", "color": "黑色", "style": "休闲", "material": "未知", "scene": "日常"}


def detected_to_query(detected: dict[str, str], user_hint: str | None) -> str:
    parts = [
        detected["color"],
        detected["style"],
        detected["material"],
        detected["object_type"],
        detected["scene"],
        user_hint or "类似款",
    ]
    return " ".join(part for part in parts if part and part != "未知")


def save_upload(file: UploadFile) -> tuple[str, str, Path]:
    settings = get_settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "upload.jpg").suffix or ".jpg"
    image_id = f"img_{uuid.uuid4().hex[:12]}"
    filename = f"{image_id}{ext}"
    file_path = settings.upload_dir / filename
    with file_path.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    return image_id, f"/uploads/{filename}", file_path


def analyze_image(conn, image_id: str, user_hint: str | None = None) -> tuple[dict[str, str], str]:
    row = conn.execute("SELECT * FROM uploaded_images WHERE image_id = ?", (image_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Image not found")
    if row["detected_json"] and row["query"] and not user_hint:
        return json.loads(row["detected_json"]), row["query"]
    detected = mock_detect_from_hint(user_hint, row["file_path"])
    query = detected_to_query(detected, user_hint)
    conn.execute(
        "UPDATE uploaded_images SET detected_json = ?, query = ? WHERE image_id = ?",
        (json.dumps(detected, ensure_ascii=False), query, image_id),
    )
    return detected, query


def stream_chat(conn, session_id: str, message: str, image_id: str | None) -> Iterable[str]:
    conn.execute(
        "INSERT OR IGNORE INTO chat_sessions(id) VALUES (?)",
        (session_id,),
    )
    conn.execute(
        "INSERT INTO chat_messages(id, session_id, role, content, image_id) VALUES (?, ?, ?, ?, ?)",
        (f"msg_{uuid.uuid4().hex[:12]}", session_id, "user", message, image_id),
    )

    cart_product_id = resolve_cart_product_id(conn, session_id, message)
    if cart_product_id:
        add_product_to_cart(conn, cart_product_id)
        assistant_content = f"已把商品 {cart_product_id} 加入购物车。"
        yield sse_event("delta", {"text": assistant_content})
        yield sse_event("actions", {"actions": [{"type": "open_cart"}]})
        conn.execute(
            "INSERT INTO chat_messages(id, session_id, role, content, image_id) VALUES (?, ?, ?, ?, ?)",
            (f"msg_{uuid.uuid4().hex[:12]}", session_id, "assistant", assistant_content, image_id),
        )
        yield sse_event("done", {"session_id": session_id})
        return

    search_query = message
    if image_id:
        detected, image_query = analyze_image(conn, image_id, message)
        search_query = f"{image_query} {message}"
        yield sse_event(
            "delta",
            {
                "text": (
                    f"我识别到图片里像是{detected['color']}{detected['style']}风格的{detected['object_type']}，"
                    f"材质特征偏{detected['material']}，场景更接近{detected['scene']}。"
                )
            },
        )
        yield sse_event("delta", {"text": "我会把这些视觉特征和你的文字需求合并，用商品库里的真实数据来找相似商品。"})
    else:
        yield sse_event("delta", {"text": "我先根据你的需求在当前商品库里筛选，不会编造商品价格、库存或 SKU。"})

    products = search_products_for_agent(conn, search_query, limit=3)
    if products:
        intro = "下面是基于商品标题、卖点、FAQ、评价和规格筛出的候选："
        yield sse_event("delta", {"text": intro})
        yield sse_event("products", {"products": [product.model_dump() for product in products]})
        yield sse_event(
            "actions",
            {
                "actions": [
                    {"type": "go_detail", "product_id": products[0].id},
                    {"type": "add_to_cart", "product_id": products[0].id},
                ]
            },
        )
        assistant_content = f"{intro} 推荐商品: {','.join(product.id for product in products)}"
    else:
        assistant_content = "当前商品库没有找到足够匹配的商品。当前商品数据未提供更多可用候选。"
        yield sse_event("delta", {"text": assistant_content})

    conn.execute(
        "INSERT INTO chat_messages(id, session_id, role, content, image_id) VALUES (?, ?, ?, ?, ?)",
        (f"msg_{uuid.uuid4().hex[:12]}", session_id, "assistant", assistant_content, image_id),
    )
    yield sse_event("done", {"session_id": session_id})


def resolve_cart_product_id(conn, session_id: str, message: str) -> str | None:
    normalized = message.strip()
    if normalized.startswith("加入购物车:"):
        return normalized.split(":", 1)[1].strip() or None
    if "购物车" not in normalized and "加购" not in normalized:
        return None
    row = conn.execute(
        """
        SELECT content FROM chat_messages
        WHERE session_id = ? AND role = 'assistant' AND content LIKE '%推荐商品:%'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (session_id,),
    ).fetchone()
    if not row:
        return None
    product_ids = row["content"].split("推荐商品:", 1)[1].split(",")
    return product_ids[0].strip() if product_ids else None


def add_product_to_cart(conn, product_id: str) -> None:
    product = conn.execute("SELECT id FROM products WHERE id = ?", (product_id,)).fetchone()
    if not product:
        return
    sku = conn.execute(
        "SELECT id FROM product_skus WHERE product_id = ? ORDER BY price ASC LIMIT 1",
        (product_id,),
    ).fetchone()
    conn.execute(
        "INSERT INTO cart_items(id, product_id, sku_id, quantity, selected) VALUES (?, ?, ?, 1, 1)",
        (f"cart_{uuid.uuid4().hex[:10]}", product_id, sku["id"] if sku else None),
    )
