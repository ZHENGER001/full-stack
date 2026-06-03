from __future__ import annotations

import json
import logging
import shutil
import uuid
from pathlib import Path
from typing import Iterable

from fastapi import HTTPException, UploadFile

from .config import get_settings
from .graph_rag import graph_hybrid_retrieve, graph_rag_retrieve
from .llm_client import get_llm_client
from .post_generation_verifier import PostGenerationVerifier
from .prompts import SYSTEM_PROMPT, format_user_prompt
from .query_router import IntelligentQueryRouter, QueryRoute
from .rag import (
    RetrievalResult,
    hybrid_retrieve,
    load_contexts_for_products,
    load_product_search_rows,
    row_to_product_card_for_agent,
    search_products_for_agent,
)
from .schemas import ProductCard

LOGGER = logging.getLogger(__name__)


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
    conn.commit()
    return detected, query


def stream_chat(
    conn,
    session_id: str,
    message: str,
    image_id: str | None,
    mode: str = "ai_guide",
    current_product_id: str | None = None,
    cart_context: list[dict] | None = None,
) -> Iterable[str]:
    conn.execute("INSERT OR IGNORE INTO chat_sessions(id) VALUES (?)", (session_id,))
    conn.execute(
        "INSERT INTO chat_messages(id, session_id, role, content, image_id) VALUES (?, ?, ?, ?, ?)",
        (f"msg_{uuid.uuid4().hex[:12]}", session_id, "user", message, image_id),
    )
    conn.commit()

    cart_product_id = resolve_cart_product_id(conn, session_id, message)
    if cart_product_id:
        add_product_to_cart(conn, cart_product_id)
        assistant_content = f"已把商品 {cart_product_id} 加入购物车。"
        yield sse_event("assistant_text_delta", {"text": assistant_content})
        yield sse_event("actions", {"actions": [{"type": "open_cart"}]})
        conn.execute(
            "INSERT INTO chat_messages(id, session_id, role, content, image_id) VALUES (?, ?, ?, ?, ?)",
            (f"msg_{uuid.uuid4().hex[:12]}", session_id, "assistant", assistant_content, image_id),
        )
        conn.commit()
        yield sse_event("done", {"session_id": session_id})
        return

    search_query = message
    image_hint: str | None = None
    if image_id:
        detected, image_query = analyze_image(conn, image_id, message)
        image_hint = (
            f"图片识别提示：{detected['color']}{detected['style']}风格的{detected['object_type']}，"
            f"材质特征偏{detected['material']}，场景更接近{detected['scene']}。"
        )
        search_query = f"{image_query} {message}"
        yield sse_event("assistant_text_delta", {"text": image_hint})

    route = IntelligentQueryRouter().route(search_query, image_hint=image_hint, mode=mode)
    yield sse_event("strategy", route.to_dict())

    retrieval, graph_context, retrieval_fallback = retrieve_for_route(conn, search_query, route)
    retrieval = apply_hard_constraint_filter(retrieval, route)
    card_limit = 8 if mode == "user_search" else 3
    candidate_products = retrieval.products[:10]
    selected_products = retrieval.products[:card_limit]
    if not selected_products:
        fallback_products = search_products_for_agent(conn, search_query, limit=10)
        selected_products = filter_products_by_hard_constraints(fallback_products, route)[:card_limit]
        candidate_products = selected_products
        retrieval_fallback = True

    llm_text, llm_fallback, llm_reason = generate_answer(
        user_query=search_query,
        route=route,
        retrieval=retrieval,
        graph_context=graph_context,
        candidate_products=candidate_products,
        mode=mode,
    )
    if llm_fallback:
        llm_text = build_template_answer(search_query, selected_products, mode, llm_reason)

    verified = PostGenerationVerifier().verify(
        user_query=search_query,
        llm_text=llm_text,
        retrieved_contexts=retrieval.context_dicts(),
        candidate_products=candidate_products,
        selected_products=selected_products,
        graph_context=graph_context,
        parsed_constraints=route.parsed_constraints.to_dict(),
    )

    final_products = verified.verified_products
    final_fallback = retrieval_fallback or llm_fallback or verified.verification_result.fallback_used
    if final_products and verified.verification_result.removed_products:
        verified.verified_text = build_template_answer(
            search_query,
            final_products,
            mode,
            "post-generation verifier removed unsupported products",
        )
        verified.verification_result.fallback_used = True
        final_fallback = True

    if not final_products:
        if verified.verification_result.budget_violations and candidate_products:
            final_products = filter_products_by_hard_constraints(candidate_products, route)[:card_limit]
            llm_text = (
                build_budget_alternative_answer(route, final_products)
                if final_products
                else build_no_verified_products_answer(route)
            )
        else:
            fallback_products = search_products_for_agent(conn, search_query, limit=10)
            final_products = filter_products_by_hard_constraints(fallback_products, route)[:card_limit]
            llm_text = (
                build_template_answer(search_query, final_products, mode, "post-generation verifier removed all products")
                if final_products
                else build_no_verified_products_answer(route)
            )
        verified.verification_result.fallback_used = True
        final_fallback = True
        verified.verified_text = llm_text

    for chunk in text_chunks(verified.verified_text):
        yield sse_event("assistant_text_delta", {"text": chunk})

    yield sse_event("products", {"products": [product.model_dump(exclude_none=True) for product in final_products[:card_limit]]})
    if final_products:
        yield sse_event(
            "actions",
            {
                "actions": [
                    {"type": "go_detail", "product_id": final_products[0].id},
                    {"type": "add_to_cart", "product_id": final_products[0].id},
                ]
            },
        )
    yield sse_event("fallback_used", {"fallback_used": final_fallback, "reason": fallback_reason(retrieval, llm_reason, verified.verification_result.reason)})
    yield sse_event("verification_result", verified.verification_result.to_dict())

    assistant_content = f"{verified.verified_text} 推荐商品:{','.join(product.id for product in final_products[:card_limit])}"
    conn.execute(
        "INSERT INTO chat_messages(id, session_id, role, content, image_id) VALUES (?, ?, ?, ?, ?)",
        (f"msg_{uuid.uuid4().hex[:12]}", session_id, "assistant", assistant_content, image_id),
    )
    conn.commit()
    yield sse_event("done", {"session_id": session_id})


def retrieve_for_route(conn, query: str, route: QueryRoute) -> tuple[RetrievalResult, str, bool]:
    if route.strategy == "hybrid":
        result = hybrid_retrieve(conn, query, top_k=10)
        return result, "", result.fallback_used

    if route.strategy == "graph":
        graph_result = graph_rag_retrieve(route, top_k=10)
        if graph_result.product_ids:
            products = cards_for_product_ids(conn, graph_result.product_ids)
            contexts = load_contexts_for_products(conn, [product.id for product in products], limit_per_product=3)
            return (
                RetrievalResult(
                    products=products,
                    contexts=contexts,
                    candidate_product_ids=[product.id for product in products],
                    strategy="graph",
                    fallback_used=graph_result.fallback_used,
                    reason=graph_result.reason or "Neo4j graph retrieval returned candidates.",
                ),
                graph_result.graph_context,
                graph_result.fallback_used,
            )
        hybrid = hybrid_retrieve(conn, query, top_k=10)
        hybrid.strategy = "graph_to_hybrid"
        hybrid.fallback_used = True
        return hybrid, graph_result.graph_context, True

    graph_result, hybrid_result = graph_hybrid_retrieve(conn, query, route, top_k=10)
    graph_products = cards_for_product_ids(conn, graph_result.product_ids)
    combined = merge_product_cards(graph_products, hybrid_result.products)
    contexts = load_contexts_for_products(conn, [product.id for product in combined], limit_per_product=3)
    contexts = hybrid_result.contexts + contexts
    return (
        RetrievalResult(
            products=combined[:10],
            contexts=contexts,
            candidate_product_ids=[product.id for product in combined[:10]],
            strategy="graph_hybrid",
            fallback_used=graph_result.fallback_used or hybrid_result.fallback_used,
            reason="Combined Neo4j graph candidates with Hybrid RRF retrieval.",
        ),
        graph_result.graph_context,
        graph_result.fallback_used or hybrid_result.fallback_used,
    )


def cards_for_product_ids(conn, product_ids: list[str]) -> list[ProductCard]:
    if not product_ids:
        return []
    rows = load_product_search_rows(conn)
    rows_by_id = {str(row["id"]): row for row in rows}
    return [
        row_to_product_card_for_agent(rows_by_id[product_id], "图谱关系和商品字段共同匹配当前需求。")
        for product_id in product_ids
        if product_id in rows_by_id
    ]


def merge_product_cards(primary: list[ProductCard], secondary: list[ProductCard]) -> list[ProductCard]:
    merged: list[ProductCard] = []
    seen: set[str] = set()
    for product in [*primary, *secondary]:
        if product.id in seen:
            continue
        seen.add(product.id)
        merged.append(product)
    return merged


def apply_hard_constraint_filter(retrieval: RetrievalResult, route: QueryRoute) -> RetrievalResult:
    constraints = route.parsed_constraints
    if constraints.budget_max is None and not constraints.categories:
        return retrieval

    filtered_products = filter_products_by_hard_constraints(retrieval.products, route)
    if not filtered_products:
        retrieval.products = []
        retrieval.contexts = []
        retrieval.candidate_product_ids = []
        retrieval.reason = f"{retrieval.reason} No retrieved products satisfied hard budget/category constraints."
        return retrieval

    allowed_ids = {product.id for product in filtered_products}
    retrieval.products = filtered_products
    retrieval.candidate_product_ids = [product.id for product in filtered_products]
    retrieval.contexts = [context for context in retrieval.contexts if context.product_id in allowed_ids]
    return retrieval


def filter_products_by_hard_constraints(products: list[ProductCard], route: QueryRoute) -> list[ProductCard]:
    return [product for product in products if product_satisfies_hard_constraints(product, route)]


def product_satisfies_hard_constraints(product: ProductCard, route: QueryRoute) -> bool:
    budget = route.parsed_constraints.budget_max
    if budget is not None and float(product.price) > float(budget):
        return False
    categories = route.parsed_constraints.categories
    if categories:
        haystack = f"{product.category or ''} {product.subcategory or ''} {product.title}".lower()
        if not any(category.lower() in haystack for category in categories):
            return False
    return True


def generate_answer(
    user_query: str,
    route: QueryRoute,
    retrieval: RetrievalResult,
    graph_context: str,
    candidate_products: list[ProductCard],
    mode: str,
) -> tuple[str, bool, str | None]:
    if mode == "user_search":
        return build_template_answer(user_query, candidate_products[:8], mode, "user_search mode uses local verified search"), True, "user_search mode"

    prompt = format_user_prompt(
        user_query=user_query,
        retrieval_strategy=route.strategy,
        parsed_constraints=route.parsed_constraints.to_dict(),
        candidate_products=[product_prompt_dict(product) for product in candidate_products[:10]],
        retrieved_contexts=[context.to_dict() for context in retrieval.contexts[:20]],
        graph_context=graph_context,
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    client = get_llm_client()
    stream_chunks = list(client.stream_complete(messages))
    if stream_chunks:
        return "".join(stream_chunks).strip(), False, None
    result = client.complete(messages)
    if result.available:
        return result.text, False, None
    return "", True, result.fallback_reason or "LLM unavailable"


def build_template_answer(query: str, products: list[ProductCard], mode: str, reason: str | None = None) -> str:
    if not products:
        return "当前商品库没有找到足够匹配的商品。我会保留你的条件，建议放宽预算、品类或功能要求后再试。"
    if mode == "user_search":
        intro = "我按你的条件做了结构化检索，优先保留价格、品类和关键词匹配的商品。"
    else:
        intro = "我先基于本地商品库和检索上下文给出可靠推荐。"
    lines = [intro]
    for index, product in enumerate(products[:3], start=1):
        lines.append(
            f"{index}. {product.title}：{product.reason or '与当前需求在标题、分类、描述或评价中有匹配'} "
            f"适合先查看详情页确认 SKU、库存和具体规格。"
        )
    if reason and ("LLM" in reason or "POE" in reason or "AI" in reason or "unavailable" in reason):
        lines.append("外部 AI 或图谱服务不可用时，系统已自动使用本地规则结果兜底。")
    elif reason:
        lines.append("系统已完成事后校验，并移除不满足条件或缺少依据的推荐。")
    lines.append("购买前建议以商品卡片和详情页的价格、库存、SKU 为准。")
    return "\n".join(lines)


def build_budget_alternative_answer(route: QueryRoute, products: list[ProductCard]) -> str:
    budget = route.parsed_constraints.budget_max
    budget_text = f"{budget:.0f} 元以内" if budget is not None else "当前预算"
    lines = [f"当前强匹配商品不满足 {budget_text} 条件，下面只保留预算内且品类匹配的近似选择。"]
    for index, product in enumerate(products[:3], start=1):
        lines.append(
            f"{index}. {product.title}：符合硬性预算和品类条件，建议进入详情页确认 SKU、库存和具体规格。"
        )
    lines.append("如果仍不满意，可以放宽预算、减少功能要求，或切换到用户检索模式继续筛选。")
    return "\n".join(lines)


def build_no_verified_products_answer(route: QueryRoute) -> str:
    parts: list[str] = []
    if route.parsed_constraints.budget_max is not None:
        parts.append(f"{route.parsed_constraints.budget_max:.0f} 元以内")
    if route.parsed_constraints.categories:
        parts.append("、".join(route.parsed_constraints.categories))
    condition = "、".join(parts) if parts else "当前条件"
    return (
        f"当前商品库没有找到同时满足 {condition} 的可靠商品，所以不展示不合格商品卡片。"
        "建议放宽预算、品类或功能要求后再试。"
    )


def product_prompt_dict(product: ProductCard) -> dict:
    return {
        "id": product.id,
        "title": product.title,
        "brand": product.brand,
        "category": product.category,
        "subcategory": product.subcategory,
        "price": product.price,
        "rating": product.rating,
        "stock": product.stock,
        "sku_summary": product.sku_summary,
        "reason": product.reason,
    }


def text_chunks(text: str, size: int = 48) -> Iterable[str]:
    if not text:
        return
    for index in range(0, len(text), size):
        yield text[index : index + size]


def fallback_reason(retrieval: RetrievalResult, llm_reason: str | None, verifier_reason: str) -> str:
    reasons = [retrieval.reason, verifier_reason]
    if llm_reason:
        reasons.append(llm_reason)
    return " | ".join(reason for reason in reasons if reason)


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
