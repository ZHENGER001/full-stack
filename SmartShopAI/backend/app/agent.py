from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any, Iterable

from fastapi import HTTPException, UploadFile

from .agent_tools import SearchProductsInput, call_search_products_tool
from .config import get_settings
from .llm_client import LLMGenerationError, LLMGenerationResult, generate_agent_reply_with_status
from .query_parser import parse_user_filters
from .schemas import ProductCard


logger = logging.getLogger(__name__)

ACTION_LABELS = {
    "go_detail": "查看详情",
    "add_to_cart": "加入购物车",
    "open_cart": "打开购物车",
    "search_more": "查看更多",
}
PRODUCT_ACTION_TYPES = {"go_detail", "add_to_cart"}
ALLOWED_ACTION_TYPES = set(ACTION_LABELS)


def sse_event(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def mock_detect_from_hint(user_hint: str | None, filename: str | None = None) -> dict[str, str]:
    # TODO: replace mock image detection with real vision encoder.
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


def stream_chat(
    conn,
    session_id: str,
    message: str,
    image_id: str | None,
    current_product_id: str | None = None,
    cart_context: list[dict] | None = None,
) -> Iterable[str]:
    try:
        yield from _stream_chat(conn, session_id, message, image_id, current_product_id, cart_context or [])
    except Exception:
        yield sse_event("error", {"message": "AI 导购暂时遇到问题，请稍后再试。"})
        yield sse_event("delta", {"text": "AI 导购暂时遇到问题，请稍后再试。"})
        yield sse_event("done", {"session_id": session_id})


def _stream_chat(
    conn,
    session_id: str,
    message: str,
    image_id: str | None,
    current_product_id: str | None,
    cart_context: list[dict],
) -> Iterable[str]:
    ensure_session(conn, session_id)
    if current_product_id and product_exists(conn, current_product_id):
        update_session_state(conn, session_id, current_product_id=current_product_id)
    conn.execute(
        "INSERT INTO chat_messages(id, session_id, role, content, image_id) VALUES (?, ?, ?, ?, ?)",
        (f"msg_{uuid.uuid4().hex[:12]}", session_id, "user", message, image_id),
    )

    cart_product_id = resolve_cart_product_id(conn, session_id, message, current_product_id, cart_context)
    if cart_product_id:
        cart_product = add_product_to_cart(conn, cart_product_id)
        if cart_product:
            actions = normalize_actions(conn, [{"type": "open_cart", "label": "打开购物车", "product_id": None}])
            assistant_content = f"已把 {cart_product['title']} 加入购物车。"
            yield sse_event("delta", {"text": assistant_content})
            yield sse_event("actions", {"actions": actions})
            store_assistant_message(conn, session_id, assistant_content, image_id)
            update_session_state(
                conn,
                session_id,
                last_query=message,
                current_product_id=cart_product_id,
                last_actions=actions,
            )
            yield sse_event("done", {"session_id": session_id})
            return

    image_query = None
    if image_id:
        detected, image_query = analyze_image(conn, image_id, message)
        yield sse_event(
            "delta",
            {
                "text": (
                    f"我识别到图片里像是{detected['color']}{detected['style']}风格的{detected['object_type']}，"
                    f"材质特征偏{detected['material']}，场景更接近{detected['scene']}。"
                )
            },
        )

    final_user_query = build_final_user_query(conn, message, image_query, current_product_id, session_id)
    parsed_filters = parse_user_filters(final_user_query, load_known_brands(conn))
    logger.info("agent_final_user_query=%s parsed_filters=%s", final_user_query, parsed_filters)
    yield sse_event(
        "retrieval_status",
        {
            "final_user_query": final_user_query,
            "parsed_filters": parsed_filters,
            "pipeline": ["query_router", "dense_milvus", "bm25", "keyword", "rrf", "sqlite_hydrate", "verifier"],
            "sources": ["dense_milvus", "bm25", "keyword"],
            "fusion": "rrf",
            "vector_backend": "milvus",
        },
    )
    search_result = call_search_products_tool(conn, SearchProductsInput(query=final_user_query, top_k=3))
    products = search_result.products
    yield sse_event("retrieval_diagnostics", search_result.diagnostics)
    grounded_products = build_grounded_products(conn, products)
    faq_context = load_faq_context(conn, [product["id"] for product in grounded_products])
    chat_history = load_chat_history(conn, session_id)
    actions = build_actions(conn, grounded_products)
    if grounded_products:
        yield sse_event("llm_status", {"mode": "calling", "provider": "poe"})
    answer, llm_status = generate_grounded_answer(message, grounded_products, faq_context, chat_history)

    yield sse_event("llm_status", llm_status)
    yield sse_event("delta", {"text": answer})
    if grounded_products:
        yield sse_event("products", {"products": grounded_products})
    if actions:
        yield sse_event("actions", {"actions": actions})

    assistant_content = append_recommendation_marker(answer, grounded_products)
    store_assistant_message(conn, session_id, assistant_content, image_id)
    update_session_state(
        conn,
        session_id,
        last_query=message,
        last_recommended_product_ids=[product["id"] for product in grounded_products],
        current_product_id=grounded_products[0]["id"] if grounded_products else current_product_id,
        last_actions=actions,
    )
    yield sse_event("done", {"session_id": session_id})


def ensure_session(conn, session_id: str) -> None:
    conn.execute("INSERT OR IGNORE INTO chat_sessions(id) VALUES (?)", (session_id,))


def load_known_brands(conn) -> list[str]:
    return [row["brand"] for row in conn.execute("SELECT DISTINCT brand FROM products").fetchall() if row["brand"]]


def build_final_user_query(
    conn,
    message: str,
    image_query: str | None,
    current_product_id: str | None,
    session_id: str,
) -> str:
    parts = [message.strip()]
    if image_query:
        parts.append(image_query)
    anchor_product_id = current_product_id
    if not anchor_product_id and any(word in message for word in ["这个", "这款", "刚刚", "刚才", "类似", "同款"]):
        row = conn.execute("SELECT current_product_id FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
        anchor_product_id = row["current_product_id"] if row else None
    if anchor_product_id and product_exists(conn, anchor_product_id):
        product = conn.execute(
            "SELECT title, brand, category, subcategory, marketing_description FROM products WHERE id = ?",
            (anchor_product_id,),
        ).fetchone()
        if product:
            parts.extend(
                [
                    product["title"],
                    product["brand"],
                    product["category"],
                    product["subcategory"],
                    str(product["marketing_description"])[:160],
                ]
            )
    return " ".join(part for part in parts if part)


def product_exists(conn, product_id: str | None) -> bool:
    if not product_id:
        return False
    row = conn.execute("SELECT id FROM products WHERE id = ?", (product_id,)).fetchone()
    return row is not None


def normalize_actions(conn, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for action in actions:
        action_type = str(action.get("type", "")).strip()
        if action_type not in ALLOWED_ACTION_TYPES:
            continue
        product_id = action.get("product_id")
        if product_id is not None:
            product_id = str(product_id).strip() or None
        if action_type in PRODUCT_ACTION_TYPES and not product_exists(conn, product_id):
            continue
        label = str(action.get("label") or ACTION_LABELS[action_type])
        normalized.append({"type": action_type, "label": label, "product_id": product_id})
    return normalized


def build_actions(conn, products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not products:
        return normalize_actions(
            conn,
            [{"type": "search_more", "label": "换个关键词再搜", "product_id": None}],
        )
    actions: list[dict[str, Any]] = []
    for index, product in enumerate(products[:2], start=1):
        product_id = product["id"]
        prefix = "第一款" if index == 1 else "第二款"
        actions.extend(
            [
                {"type": "go_detail", "label": f"查看{prefix}详情", "product_id": product_id},
                {"type": "add_to_cart", "label": f"加入{prefix}购物车", "product_id": product_id},
            ]
        )
    actions.append({"type": "search_more", "label": "换一批", "product_id": None})
    return normalize_actions(
        conn,
        actions,
    )


def build_grounded_products(conn, products: list[ProductCard]) -> list[dict[str, Any]]:
    grounded: list[dict[str, Any]] = []
    for product in products:
        data = product.model_dump()
        row = conn.execute(
            """
            SELECT
                COUNT(s.id) AS sku_count,
                COALESCE(SUM(s.stock), 0) AS stock,
                GROUP_CONCAT(s.sku_name, '；') AS sku_summary,
                p.marketing_description AS marketing_description
            FROM products p
            LEFT JOIN product_skus s ON s.product_id = p.id
            WHERE p.id = ?
            GROUP BY p.id
            """,
            (product.id,),
        ).fetchone()
        if row:
            data.update(
                {
                    "marketing_description": row["marketing_description"],
                    "sku_count": int(row["sku_count"] or 0),
                    "stock": int(row["stock"] or 0),
                    "sku_summary": row["sku_summary"],
                }
            )
        data["faq_summary"] = [
            f"{item['question']}：{item['answer']}"
            for item in conn.execute(
                "SELECT question, answer FROM product_faqs WHERE product_id = ? LIMIT 2",
                (product.id,),
            ).fetchall()
        ]
        data["review_summary"] = [
            item["content"]
            for item in conn.execute(
                "SELECT content FROM product_reviews WHERE product_id = ? ORDER BY rating DESC LIMIT 2",
                (product.id,),
            ).fetchall()
        ]
        data["review_count"] = int(
            conn.execute("SELECT COUNT(*) AS total FROM product_reviews WHERE product_id = ?", (product.id,)).fetchone()[
                "total"
            ]
        )
        data["faq_count"] = int(
            conn.execute("SELECT COUNT(*) AS total FROM product_faqs WHERE product_id = ?", (product.id,)).fetchone()[
                "total"
            ]
        )
        grounded.append(data)
    return grounded


def load_faq_context(conn, product_ids: list[str]) -> list[dict[str, str]]:
    if not product_ids:
        return []
    placeholders = ",".join("?" for _ in product_ids)
    rows = conn.execute(
        f"""
        SELECT product_id, question, answer
        FROM product_faqs
        WHERE product_id IN ({placeholders})
        LIMIT 12
        """,
        product_ids,
    ).fetchall()
    return [
        {"product_id": row["product_id"], "question": row["question"], "answer": row["answer"]}
        for row in rows
    ]


def load_chat_history(conn, session_id: str, limit: int = 6) -> list[dict[str, str]]:
    rows = conn.execute(
        """
        SELECT role, content
        FROM chat_messages
        WHERE session_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (session_id, limit),
    ).fetchall()
    return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]


def generate_grounded_answer(
    message: str,
    grounded_products: list[dict[str, Any]],
    faq_context: list[dict[str, str]],
    chat_history: list[dict[str, str]],
) -> tuple[str, dict[str, str]]:
    if not grounded_products:
        return build_template_answer(grounded_products, message), {"mode": "fallback", "reason": "no_retrieved_products"}
    try:
        result = run_async_blocking(generate_agent_reply_with_status(message, grounded_products, faq_context, chat_history))
        return sanitize_llm_answer(result.content, grounded_products), {
            "mode": "llm",
            "provider": result.provider,
            "model": result.model,
        }
    except LLMGenerationError as exc:
        return build_template_answer(grounded_products, message), {"mode": "fallback", "reason": str(exc)}
    except Exception as exc:
        return build_template_answer(grounded_products, message), {"mode": "fallback", "reason": exc.__class__.__name__}


def run_async_blocking(coro) -> LLMGenerationResult:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except Exception as exc:
            result["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result["value"]


def sanitize_llm_answer(answer: str, products: list[dict[str, Any]]) -> str:
    cleaned = " ".join(answer.split()).strip()
    if not cleaned:
        return build_template_answer(products)
    if len(cleaned) > 160:
        return build_template_answer(products)
    return cleaned


def build_template_answer(products: list[dict[str, Any]], query: str = "") -> str:
    if not products:
        max_price_match = re.search(r"(\d+(?:\.\d+)?)\s*元?\s*(?:以下|以内|内|之内)", query)
        if "耳机" in query and max_price_match:
            return f"当前商品库没有找到 {max_price_match.group(1)} 元以内的蓝牙耳机，可以尝试放宽预算、品牌或品类条件。"
        return "当前商品库没有找到完全匹配的商品，可以尝试放宽价格、品牌或品类条件。"
    first = products[0]
    return (
        f"找到 {len(products)} 款匹配商品，优先看 {first['title']}。"
        "已按品类、预算、库存和评价排序，详细信息见下方商品卡片。"
    )


def append_recommendation_marker(answer: str, products: list[dict[str, Any]]) -> str:
    if not products:
        return answer
    return f"{answer}\n推荐商品: {','.join(product['id'] for product in products)}"


def store_assistant_message(conn, session_id: str, content: str, image_id: str | None) -> None:
    conn.execute(
        "INSERT INTO chat_messages(id, session_id, role, content, image_id) VALUES (?, ?, ?, ?, ?)",
        (f"msg_{uuid.uuid4().hex[:12]}", session_id, "assistant", content, image_id),
    )


def update_session_state(
    conn,
    session_id: str,
    last_query: str | None = None,
    last_recommended_product_ids: list[str] | None = None,
    current_product_id: str | None = None,
    last_actions: list[dict[str, Any]] | None = None,
) -> None:
    conn.execute(
        """
        UPDATE chat_sessions
        SET
            last_query = COALESCE(?, last_query),
            last_recommended_product_ids = COALESCE(?, last_recommended_product_ids),
            current_product_id = COALESCE(?, current_product_id),
            last_actions = COALESCE(?, last_actions)
        WHERE id = ?
        """,
        (
            last_query,
            json.dumps(last_recommended_product_ids, ensure_ascii=False) if last_recommended_product_ids is not None else None,
            current_product_id,
            json.dumps(last_actions, ensure_ascii=False) if last_actions is not None else None,
            session_id,
        ),
    )


def resolve_cart_product_id(
    conn,
    session_id: str,
    message: str,
    current_product_id: str | None = None,
    cart_context: list[dict] | None = None,
) -> str | None:
    normalized = message.strip()
    explicit = parse_explicit_product_id(normalized)
    if explicit:
        return explicit if product_exists(conn, explicit) else None
    if not is_cart_intent(normalized):
        return None

    session_row = conn.execute(
        "SELECT last_recommended_product_ids, current_product_id FROM chat_sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    recent_ids = parse_product_id_list(session_row["last_recommended_product_ids"] if session_row else None)
    if current_product_id and product_exists(conn, current_product_id):
        recent_ids = [current_product_id, *[pid for pid in recent_ids if pid != current_product_id]]
    if session_row and session_row["current_product_id"] and product_exists(conn, session_row["current_product_id"]):
        recent_ids = [
            session_row["current_product_id"],
            *[pid for pid in recent_ids if pid != session_row["current_product_id"]],
        ]
    if cart_context:
        recent_ids.extend(
            str(item.get("product_id") or item.get("productId"))
            for item in cart_context
            if item.get("product_id") or item.get("productId")
        )

    selected_index = parse_ordinal_index(normalized)
    if selected_index is not None and 0 <= selected_index < len(recent_ids):
        return recent_ids[selected_index]
    if any(word in normalized for word in ["刚刚", "刚才", "上一个", "那个", "这款", "这个"]) and recent_ids:
        return recent_ids[0]
    if recent_ids:
        return recent_ids[0]
    return resolve_from_assistant_marker(conn, session_id)


def parse_explicit_product_id(message: str) -> str | None:
    for prefix in ["加入购物车:", "加入购物车：", "加购:", "加购："]:
        if message.startswith(prefix):
            return message.split(prefix, 1)[1].strip() or None
    return None


def is_cart_intent(message: str) -> bool:
    return any(word in message for word in ["加入购物车", "加购物车", "加购", "放购物车", "购物车"])


def parse_product_id_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if item]


def parse_ordinal_index(message: str) -> int | None:
    number_map = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5}
    match = re.search(r"第?\s*([一二两三四五\d]+)\s*个", message)
    if not match:
        return None
    token = match.group(1)
    value = int(token) if token.isdigit() else number_map.get(token)
    return value - 1 if value else None


def resolve_from_assistant_marker(conn, session_id: str) -> str | None:
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
    first_id = product_ids[0].strip() if product_ids else None
    return first_id if product_exists(conn, first_id) else None


def add_product_to_cart(conn, product_id: str) -> dict[str, Any] | None:
    product = conn.execute("SELECT id, title FROM products WHERE id = ?", (product_id,)).fetchone()
    if not product:
        return None
    sku = conn.execute(
        "SELECT id FROM product_skus WHERE product_id = ? ORDER BY price ASC LIMIT 1",
        (product_id,),
    ).fetchone()
    conn.execute(
        "INSERT INTO cart_items(id, product_id, sku_id, quantity, selected) VALUES (?, ?, ?, 1, 1)",
        (f"cart_{uuid.uuid4().hex[:10]}", product_id, sku["id"] if sku else None),
    )
    return product
