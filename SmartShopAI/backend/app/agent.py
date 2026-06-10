from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Iterable

from fastapi import HTTPException, UploadFile

from .agentic_rag import plan_agentic_turn, retrieve_products_for_turn
from .bounded_agent_tools import BoundedToolResult, execute_bounded_turn
from .bundle_recommendation import build_bundle_answer, retrieve_bundle_recommendations
from .catalog import get_cart
from .config import get_settings
from .llm_client import (
    LLMGenerationError,
    LLMGenerationResult,
    generate_agent_reply_with_status,
    generate_product_presentations,
    llm_model_name,
    stream_agent_reply_chunks_with_status,
)
from .react_planner import has_checkout_signal, message_with_sku_hint, plan_react_transaction, product_reference_from_step
from .schemas import ProductCard
from .turn_schema import ParsedTurn


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


def order_status_event(
    status: str,
    message: str,
    order_id: str | None = None,
    payment_id: str | None = None,
) -> str:
    payload: dict[str, Any] = {"status": status, "message": message}
    if order_id:
        payload["order_id"] = order_id
    if payment_id:
        payload["payment_id"] = payment_id
    return sse_event("order_status", payload)


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
    from .agent_orchestrator import stream_agent_turn
    from .agent_state import AgentTurnRequest

    yield from stream_agent_turn(
        conn,
        AgentTurnRequest(
            session_id=session_id,
            message=message,
            image_id=image_id,
            current_product_id=current_product_id,
            cart_context=cart_context,
        ),
    )


def _stream_chat_legacy(
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
    previous_chat_history = load_chat_history(conn, session_id)
    conn.execute(
        "INSERT INTO chat_messages(id, session_id, role, content, image_id) VALUES (?, ?, ?, ?, ?)",
        (f"msg_{uuid.uuid4().hex[:12]}", session_id, "user", message, image_id),
    )

    chat_history = previous_chat_history
    conversation_state = load_conversation_state(conn, session_id, current_product_id, cart_context)
    if is_order_cancel_intent(message):
        yield from emit_order_cancel_turn(conn, session_id, message, image_id)
        return
    pending_checkout_message = pending_cart_add_checkout_message(message, chat_history)
    if pending_checkout_message:
        yield from emit_cart_add_checkout_turn(
            conn,
            session_id,
            f"{pending_checkout_message} {message}",
            image_id,
            chat_history,
            conversation_state,
        )
        return
    react_plan = run_async_blocking(plan_react_transaction(message, chat_history, conversation_state))
    if react_plan.should_execute and any(step.action in {"cart_add", "checkout"} for step in react_plan.steps):
        yield from emit_react_transaction_turn(conn, session_id, message, image_id, react_plan)
        return
    if is_cart_add_checkout_intent(message):
        yield from emit_cart_add_checkout_turn(conn, session_id, message, image_id, chat_history, conversation_state)
        return
    if is_checkout_intent(message):
        yield from emit_checkout_turn(conn, session_id, message, image_id)
        return
    turn_plan = None
    parsed_turn = None
    try:
        turn_plan = run_async_blocking(plan_agentic_turn(message, chat_history, conversation_state))
        parsed_turn = turn_plan.parsed_turn
        logger.info("agent_parsed_turn=%s", parsed_turn.model_dump(mode="json"))
        if turn_plan.should_run_bounded_tool:
            bounded_result = execute_bounded_turn(conn, parsed_turn, conversation_state)
            yield from emit_bounded_result(conn, session_id, message, image_id, bounded_result)
            return
        if parsed_turn.intent_type == "bundle_recommendation":
            yield from emit_bundle_recommendation_turn(conn, session_id, message, image_id, turn_plan)
            return
        if not turn_plan.should_search_products:
            assistant_content = turn_plan.policy.response_text or "这个操作我正在支持中。"
            actions = build_clarification_actions(conn, parsed_turn.clarification_question or assistant_content)
            yield sse_event("delta", {"text": assistant_content})
            if actions:
                yield sse_event("actions", {"actions": actions})
            store_assistant_message(conn, session_id, assistant_content, image_id)
            update_session_state(conn, session_id, last_query=message, last_actions=actions or None)
            yield sse_event("done", {"session_id": session_id})
            return
    except Exception as exc:
        logger.info("turn_parser_failed=%s", exc.__class__.__name__)

    cart_product_id = resolve_cart_product_id(conn, session_id, message, current_product_id, cart_context)
    if cart_product_id:
        skus = fetch_cart_skus(conn, cart_product_id)
        selected_sku = resolve_sku_from_message(message, skus)
        if len(skus) > 1 and selected_sku is None:
            product = conn.execute("SELECT id, title FROM products WHERE id = ?", (cart_product_id,)).fetchone()
            if product:
                actions = build_sku_selection_actions(skus)
                assistant_content = build_sku_selection_prompt(product["title"], skus)
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
        cart_product = add_product_to_cart(conn, cart_product_id, selected_sku["id"] if selected_sku else None)
        if cart_product:
            actions = normalize_actions(conn, [{"type": "open_cart", "label": "打开购物车", "product_id": None}])
            sku_text = f"（{cart_product['sku_name']}）" if cart_product.get("sku_name") else ""
            cart_payload = get_cart(conn).model_dump(mode="json")
            assistant_content = f"已把 {cart_product['title']}{sku_text} 加入购物车，数量 1。购物车详情如下。"
            yield sse_event("delta", {"text": assistant_content})
            yield sse_event("cart", cart_payload)
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
    retrieval_result = retrieve_products_for_turn(conn, final_user_query, load_known_brands(conn), turn_plan)
    parsed_filters = retrieval_result.parsed_filters
    logger.info("agent_final_user_query=%s parsed_filters=%s", final_user_query, parsed_filters)
    for waiting_text in build_waiting_deltas(message, parsed_filters, image_id, bool(chat_history)):
        yield sse_event("delta", {"text": f"{waiting_text}\n"})
        time.sleep(0.25)
    yield sse_event(
        "retrieval_status",
        {
            "final_user_query": final_user_query,
            "parsed_filters": parsed_filters,
            "pipeline": retrieval_result.pipeline,
            "sources": retrieval_result.sources,
            "fusion": retrieval_result.fusion,
            "vector_backend": retrieval_result.vector_backend,
            "graph_backend": retrieval_result.graph_backend,
            "turn": {
                "intent_type": parsed_turn.intent_type if parsed_turn else "unknown",
                "route_hint": parsed_turn.route_hint if parsed_turn else "direct_tool",
                "needs_clarification": parsed_turn.needs_clarification if parsed_turn else False,
                "graph_backend": turn_plan.graph_backend if turn_plan else "langgraph_fallback",
            },
        },
    )
    search_result = retrieval_result.search_result
    products = search_result.products
    alternatives = search_result.alternatives
    yield sse_event("retrieval_diagnostics", search_result.diagnostics)
    grounded_products = build_grounded_products(conn, products)
    grounded_alternatives = [] if grounded_products else build_grounded_products(conn, alternatives)
    visible_products = grounded_products or grounded_alternatives
    enrich_product_presentations(message, visible_products)
    faq_context = load_faq_context(conn, [product["id"] for product in grounded_products])
    chat_history = load_chat_history(conn, session_id)
    actions = build_actions(conn, visible_products, final_user_query, parsed_filters)
    if grounded_products:
        yield sse_event("products", {"products": grounded_products})
    elif grounded_alternatives:
        yield sse_event("alternatives", {"products": grounded_alternatives, "match_type": "alternatives"})
    if not grounded_products and grounded_alternatives:
        answer = build_alternative_answer(message, grounded_alternatives)
        llm_status = {"mode": "fallback", "reason": "alternatives_available"}
        yield sse_event("llm_status", llm_status)
        yield sse_event("delta", {"text": answer})
    else:
        answer, llm_status = yield from stream_grounded_answer_events(
            message,
            grounded_products,
            faq_context,
            chat_history,
        )
        if grounded_products:
            yield sse_event("llm_status", llm_status)

    if actions:
        yield sse_event("actions", {"actions": actions})

    assistant_content = append_recommendation_marker(answer, visible_products)
    store_assistant_message(conn, session_id, assistant_content, image_id)
    update_session_state(
        conn,
        session_id,
        last_query=message,
        last_recommended_product_ids=[product["id"] for product in visible_products],
        current_product_id=visible_products[0]["id"] if visible_products else current_product_id,
        last_actions=actions,
    )
    yield sse_event("done", {"session_id": session_id})


def emit_bounded_result(
    conn,
    session_id: str,
    message: str,
    image_id: str | None,
    result: BoundedToolResult,
) -> Iterable[str]:
    yield from emit_bounded_events(conn, session_id, message, image_id, result, store=True, done=True)


def emit_bounded_events(
    conn,
    session_id: str,
    message: str,
    image_id: str | None,
    result: BoundedToolResult,
    *,
    store: bool,
    done: bool,
) -> Iterable[str]:
    actions = normalize_actions(conn, result.actions)
    yield sse_event(
        "tool_diagnostics",
        {
            "tool_name": result.tool_name,
            "status": result.status,
            **result.diagnostics,
        },
    )
    yield sse_event("delta", {"text": result.response_text})
    if result.comparison:
        yield sse_event("comparison", result.comparison)
    if result.products:
        yield sse_event("products", {"products": result.products})
    if result.cart is not None:
        yield sse_event("cart", result.cart)
    if result.status == "needs_reference" and not actions:
        actions = build_reference_clarification_actions(conn, result.response_text)
    if actions:
        yield sse_event("actions", {"actions": actions})

    if not store:
        return
    store_assistant_message(conn, session_id, result.response_text, image_id)
    update_session_state(
        conn,
        session_id,
        last_query=message,
        last_recommended_product_ids=result.product_ids or None,
        current_product_id=result.current_product_id,
        last_actions=actions or None,
    )
    if done:
        yield sse_event("done", {"session_id": session_id})


def emit_cart_add_checkout_turn(
    conn,
    session_id: str,
    message: str,
    image_id: str | None,
    chat_history: list[dict[str, str]],
    conversation_state: dict[str, Any],
) -> Iterable[str]:
    try:
        turn_plan = run_async_blocking(plan_agentic_turn(message, chat_history, conversation_state))
        parsed_turn = turn_plan.parsed_turn
    except Exception as exc:
        logger.info("cart_add_checkout_parse_failed=%s", exc.__class__.__name__)
        yield from emit_checkout_turn(conn, session_id, message, image_id)
        return

    if parsed_turn.intent_type != "cart_add":
        yield from emit_checkout_turn(conn, session_id, message, image_id)
        return

    add_result = execute_bounded_turn(conn, parsed_turn, conversation_state)
    yield sse_event(
        "workflow_status",
        {
            "workflow": "cart_add_checkout",
            "step": "cart_add",
            "status": add_result.status,
            "graph_backend": turn_plan.graph_backend,
        },
    )
    yield from emit_bounded_events(conn, session_id, message, image_id, add_result, store=True, done=False)
    if add_result.status != "ok":
        yield sse_event("done", {"session_id": session_id})
        return

    yield sse_event(
        "workflow_status",
        {
            "workflow": "cart_add_checkout",
            "step": "checkout",
            "status": "start",
            "graph_backend": turn_plan.graph_backend,
        },
    )
    checkout_message = "确认下单并支付" if should_auto_confirm_checkout(message) else message
    yield from emit_checkout_turn(conn, session_id, checkout_message, image_id)


def emit_react_transaction_turn(
    conn,
    session_id: str,
    message: str,
    image_id: str | None,
    react_plan,
) -> Iterable[str]:
    yield sse_event(
        "workflow_status",
        {
            "workflow": "react_transaction",
            "step": "planner",
            "status": "ok",
            "confidence": react_plan.confidence,
            "actions": [step.action for step in react_plan.steps],
        },
    )
    completed_any_step = False
    for step in react_plan.steps:
        if step.action == "cart_add":
            parsed_turn = ParsedTurn(
                raw_message=message_with_sku_hint(message, step),
                intent_type="cart_add",
                route_hint="bounded_react",
                references=product_reference_from_step(step),
                quantity=step.quantity or 1,
                source="llm",
            )
            result = execute_bounded_turn(conn, parsed_turn, load_conversation_state(conn, session_id, None, None))
            yield sse_event(
                "workflow_status",
                {
                    "workflow": "react_transaction",
                    "step": "cart_add",
                    "status": result.status,
                },
            )
            yield from emit_bounded_events(conn, session_id, message, image_id, result, store=True, done=False)
            if result.status != "ok":
                yield sse_event("done", {"session_id": session_id})
                return
            completed_any_step = True
            continue
        if step.action == "checkout":
            if not completed_any_step and not get_cart(conn).items:
                assistant_content = "我还不知道你想买哪一款商品。请先告诉我具体商品，或先让我推荐几款再说“第一款 42 码直接买”。"
                actions = normalize_actions(
                    conn,
                    [
                        {"type": "search_more", "label": "重新推荐几款", "product_id": None},
                        {"type": "open_cart", "label": "打开购物车", "product_id": None},
                        {"type": "search_more", "label": "我说商品名称", "product_id": None},
                    ],
                )
                yield order_status_event("failed", "缺少商品引用")
                yield sse_event("delta", {"text": assistant_content})
                if actions:
                    yield sse_event("actions", {"actions": actions})
                store_assistant_message(conn, session_id, assistant_content, image_id)
                update_session_state(conn, session_id, last_query=message, last_actions=actions or None)
                yield sse_event("done", {"session_id": session_id})
                return
            checkout_message = "确认下单并支付" if step.confirm_payment else "结算"
            yield sse_event(
                "workflow_status",
                {
                    "workflow": "react_transaction",
                    "step": "checkout",
                    "status": "start",
                    "confirm_payment": step.confirm_payment,
                    "use_default_address": step.use_default_address,
                },
            )
            yield from emit_checkout_turn(conn, session_id, checkout_message, image_id)
            return
    if completed_any_step:
        yield sse_event("done", {"session_id": session_id})


def emit_bundle_recommendation_turn(
    conn,
    session_id: str,
    message: str,
    image_id: str | None,
    turn_plan,
) -> Iterable[str]:
    result = retrieve_bundle_recommendations(
        conn,
        message,
        top_k_per_slot=1,
        bundle_slots=turn_plan.parsed_turn.bundle_slots if turn_plan else None,
    )
    yield sse_event(
        "retrieval_status",
        {
            "final_user_query": message,
            "parsed_filters": {},
            "pipeline": [
                "scene_planner",
                "category_planner",
                "parallel_retrieve",
                "slot_verifier",
                "bundle_writer",
            ],
            "sources": ["dense_milvus", "bm25", "keyword"],
            "fusion": "slot_rrf",
            "vector_backend": "milvus",
            "graph_backend": turn_plan.graph_backend,
            "turn": turn_plan.status_payload(),
            "bundle": result.diagnostics,
        },
    )
    grounded_products = build_grounded_products(conn, result.products)
    enrich_product_presentations(message, grounded_products)
    if grounded_products:
        yield sse_event("products", {"products": grounded_products})
    answer = build_bundle_answer(result)
    yield sse_event("llm_status", {"mode": "bundle_template", "reason": "multi_slot_grounded"})
    yield sse_event("delta", {"text": answer})
    actions = build_actions(conn, grounded_products, message, {})
    if actions:
        yield sse_event("actions", {"actions": actions})
    assistant_content = append_recommendation_marker(answer, grounded_products)
    store_assistant_message(conn, session_id, assistant_content, image_id)
    update_session_state(
        conn,
        session_id,
        last_query=message,
        last_recommended_product_ids=[product["id"] for product in grounded_products],
        current_product_id=grounded_products[0]["id"] if grounded_products else None,
        last_actions=actions or None,
    )
    yield sse_event("done", {"session_id": session_id})


def emit_checkout_turn(
    conn,
    session_id: str,
    message: str,
    image_id: str | None,
) -> Iterable[str]:
    if is_checkout_cancel_intent(message):
        assistant_content = "已取消本次下单，购物车商品会继续保留。需要时可以再次回复“结算”。"
        yield order_status_event("cancelled", "已取消下单")
        yield sse_event("delta", {"text": assistant_content})
        yield sse_event("cart", get_cart(conn).model_dump(mode="json"))
        store_assistant_message(conn, session_id, assistant_content, image_id)
        update_session_state(conn, session_id, last_query=message, last_actions=None)
        yield sse_event("done", {"session_id": session_id})
        return

    if is_address_change_intent(message):
        assistant_content = "可以先到地址管理新增或修改收货地址。地址确认后，回到这里回复“结算”或“确认下单”，我会重新汇总订单。"
        yield order_status_event("need_address", "等待补充收货地址")
        yield sse_event("delta", {"text": assistant_content})
        yield sse_event("actions", {"actions": [{"type": "search_more", "label": "修改收货地址", "product_id": None}]})
        store_assistant_message(conn, session_id, assistant_content, image_id)
        update_session_state(
            conn,
            session_id,
            last_query=message,
            last_actions=[{"type": "search_more", "label": "修改收货地址", "product_id": None}],
        )
        yield sse_event("done", {"session_id": session_id})
        return

    yield order_status_event("checking_cart", "正在读取购物车")
    cart = get_cart(conn).model_dump(mode="json")
    selected_items = [item for item in cart.get("items", []) if item.get("selected", True)]
    if not cart.get("items"):
        assistant_content = "购物车现在是空的，先加入商品后我再帮你确认订单。"
        yield order_status_event("failed", "购物车为空")
        yield sse_event("delta", {"text": assistant_content})
        store_assistant_message(conn, session_id, assistant_content, image_id)
        update_session_state(conn, session_id, last_query=message)
        yield sse_event("done", {"session_id": session_id})
        return
    if not selected_items:
        assistant_content = "购物车里没有选中的商品，请先选择要结算的商品。"
        yield order_status_event("failed", "没有选中商品")
        yield sse_event("delta", {"text": assistant_content})
        yield sse_event("cart", cart)
        store_assistant_message(conn, session_id, assistant_content, image_id)
        update_session_state(conn, session_id, last_query=message)
        yield sse_event("done", {"session_id": session_id})
        return

    address = load_default_address(conn)
    if is_checkout_confirm_intent(message):
        if not address:
            assistant_content = "下单前需要先补充收货地址。请到地址管理新增地址后，再回复“确认下单”。"
            actions = [{"type": "search_more", "label": "修改收货地址", "product_id": None}]
            yield order_status_event("need_address", "等待补充收货地址")
            yield sse_event("delta", {"text": assistant_content})
            yield sse_event("actions", {"actions": actions})
            store_assistant_message(conn, session_id, assistant_content, image_id)
            update_session_state(conn, session_id, last_query=message, last_actions=actions)
            yield sse_event("done", {"session_id": session_id})
            return
        yield order_status_event("creating_order", "正在创建订单")
        time.sleep(0.2)
        try:
            order = create_paid_order_from_cart(conn, address)
        except ValueError as exc:
            assistant_content = str(exc)
            actions = normalize_actions(conn, build_checkout_failure_actions(assistant_content))
            yield order_status_event("failed", "下单失败")
            yield sse_event("delta", {"text": assistant_content})
            yield sse_event("cart", get_cart(conn).model_dump(mode="json"))
            if actions:
                yield sse_event("actions", {"actions": actions})
            store_assistant_message(conn, session_id, assistant_content, image_id)
            update_session_state(conn, session_id, last_query=message, last_actions=actions or None)
            yield sse_event("done", {"session_id": session_id})
            return
        yield order_status_event("paying", "正在模拟支付")
        time.sleep(0.2)
        assistant_content = build_order_success_text(order)
        yield order_status_event(
            "paid",
            f"支付成功，订单号 {order['order_id']}",
            order_id=order["order_id"],
            payment_id=order["payment_id"],
        )
        yield sse_event("delta", {"text": assistant_content})
        yield sse_event("cart", get_cart(conn).model_dump(mode="json"))
        store_assistant_message(conn, session_id, assistant_content, image_id)
        update_session_state(conn, session_id, last_query=message, last_actions=None)
        yield sse_event("done", {"session_id": session_id})
        return

    assistant_content = build_checkout_confirmation_text(cart, address)
    raw_actions = [
        {"type": "search_more", "label": "修改收货地址", "product_id": None},
        {"type": "search_more", "label": "取消下单", "product_id": None},
    ]
    if address:
        raw_actions.insert(0, {"type": "search_more", "label": "确认下单并支付", "product_id": None})
    actions = normalize_actions(conn, raw_actions)
    yield order_status_event(
        "awaiting_confirmation" if address else "need_address",
        "等待确认下单" if address else "等待补充收货地址",
    )
    yield sse_event("delta", {"text": assistant_content})
    yield sse_event("cart", cart)
    yield sse_event("actions", {"actions": actions})
    store_assistant_message(conn, session_id, assistant_content, image_id)
    update_session_state(conn, session_id, last_query=message, last_actions=actions)
    yield sse_event("done", {"session_id": session_id})


def emit_order_cancel_turn(
    conn,
    session_id: str,
    message: str,
    image_id: str | None,
) -> Iterable[str]:
    order = resolve_cancel_order(conn, message)
    if not order:
        assistant_content = "没有找到可取消的订单。你可以到“我的订单”里查看当前订单状态。"
        yield order_status_event("failed", "没有可取消订单")
        yield sse_event("delta", {"text": assistant_content})
        store_assistant_message(conn, session_id, assistant_content, image_id)
        update_session_state(conn, session_id, last_query=message)
        yield sse_event("done", {"session_id": session_id})
        return
    if order["status"] == "cancelled":
        assistant_content = f"订单 {order['id']} 已经是已取消状态。"
        yield order_status_event("cancelled", "订单已取消", order_id=order["id"])
        yield sse_event("delta", {"text": assistant_content})
        store_assistant_message(conn, session_id, assistant_content, image_id)
        update_session_state(conn, session_id, last_query=message)
        yield sse_event("done", {"session_id": session_id})
        return
    if order["status"] == "paid":
        restore_order_stock(conn, order["id"])
    conn.execute("UPDATE orders SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", ("cancelled", order["id"]))
    assistant_content = f"已取消订单 {order['id']}。"
    if order["status"] == "paid":
        assistant_content += " 已同步恢复对应商品库存。"
    yield order_status_event("cancelled", "订单已取消", order_id=order["id"])
    yield sse_event("delta", {"text": assistant_content})
    store_assistant_message(conn, session_id, assistant_content, image_id)
    update_session_state(conn, session_id, last_query=message)
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
    if should_merge_last_query(message):
        row = conn.execute("SELECT last_query FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
        last_query = row["last_query"] if row else None
        if last_query and last_query not in message:
            parts.append(str(last_query))
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


def should_merge_last_query(message: str) -> bool:
    text = message.strip()
    if not text:
        return False
    has_catalog_term = any(
        term in text
        for term in (
            "手机",
            "耳机",
            "电脑",
            "笔记本",
            "篮球鞋",
            "跑鞋",
            "防晒",
            "背包",
            "行李箱",
        )
    )
    refinement_terms = (
        "拍照",
        "续航",
        "性能",
        "性价比",
        "预算",
        "优先",
        "便宜",
        "贵点",
        "不要",
        "排除",
        "降噪",
        "通勤",
        "实战",
    )
    return not has_catalog_term and any(term in text for term in refinement_terms)


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


def build_actions(
    conn,
    products: list[dict[str, Any]],
    query: str = "",
    parsed_filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    parsed_filters = parsed_filters or {}
    if not products:
        labels = build_empty_result_follow_up_questions(query, parsed_filters)
        return normalize_actions(
            conn,
            [{"type": "search_more", "label": label, "product_id": None} for label in labels],
        )
    actions = [
        {"type": "search_more", "label": label, "product_id": None}
        for label in build_follow_up_questions(products, query, parsed_filters)
    ]
    return normalize_actions(conn, actions)


def build_clarification_actions(conn, question: str) -> list[dict[str, Any]]:
    if "具体对什么过敏" in question:
        labels = [
            "坚果/花生过敏",
            "乳制品/鸡蛋过敏",
            "小麦/海鲜过敏",
        ]
    elif "过敏" in question or "忌口" in question:
        labels = [
            "没有过敏忌口",
            "给小孩/老人吃",
            "低糖低盐优先",
        ]
    elif "肤质" in question or "酒精" in question or "香精" in question:
        labels = [
            "敏感肌，避开酒精香精",
            "干皮，保湿优先",
            "油皮，清爽控油",
        ]
    elif "脚宽" in question or "膝盖" in question or "磨脚" in question:
        labels = [
            "跑步用，脚宽",
            "通勤穿，不磨脚",
            "篮球实战，膝盖易不适",
        ]
    elif "长时间佩戴" in question or "孩子使用" in question or "护眼" in question:
        labels = [
            "长时间佩戴要舒适",
            "给孩子用，护眼优先",
            "降噪续航优先",
        ]
    elif "宠物" in question or "肠胃敏感" in question:
        labels = [
            "猫咪，肠胃敏感",
            "狗狗，日常使用",
            "避开易过敏成分",
        ]
    elif "哪类带" in question:
        labels = build_attribute_category_labels(question)
    elif "换一批推荐" in question and "删除购物车" in question:
        labels = [
            "换一批推荐",
            "删除购物车商品",
            "加入购物车",
        ]
    elif "拍照" in question and "续航" in question:
        labels = [
            "拍照优先，预算4000",
            "续航优先，预算3000",
            "性价比优先，预算2500",
        ]
    elif "降噪" in question and "音质" in question:
        labels = [
            "降噪优先，预算500",
            "音质优先，预算800",
            "佩戴舒适，预算300",
        ]
    elif "实战" in question or "跑步" in question:
        labels = [
            "实战优先，预算500",
            "通勤穿搭，预算300",
            "跑步缓震，预算600",
        ]
    else:
        labels = ["预算低一点", "品牌不限", "更看重性价比"]
    return normalize_actions(
        conn,
        [{"type": "search_more", "label": label, "product_id": None} for label in labels],
    )


def build_attribute_category_labels(question: str) -> list[str]:
    if "蓝牙" in question:
        return ["找蓝牙耳机", "找蓝牙音箱", "找蓝牙键盘"]
    if "防水" in question:
        return ["找防水背包", "找防水鞋", "找防水外套"]
    if "轻薄" in question:
        return ["找轻薄笔记本", "找轻薄外套", "找轻薄背包"]
    if "降噪" in question:
        return ["找降噪耳机", "找降噪耳塞", "找通勤耳机"]
    if "续航" in question:
        return ["找长续航手机", "找长续航耳机", "找长续航笔记本"]
    return ["找耳机", "找背包", "找鞋服"]


def build_reference_clarification_actions(conn, response_text: str) -> list[dict[str, Any]]:
    if "购物车" in response_text:
        labels = ["打开购物车", "删除购物车第一项", "清空购物车"]
        raw_actions = [
            {"type": "open_cart", "label": labels[0], "product_id": None},
            {"type": "search_more", "label": labels[1], "product_id": None},
            {"type": "search_more", "label": labels[2], "product_id": None},
        ]
    else:
        raw_actions = [
            {"type": "search_more", "label": "重新推荐几款", "product_id": None},
            {"type": "open_cart", "label": "打开购物车", "product_id": None},
            {"type": "search_more", "label": "我说商品名称", "product_id": None},
        ]
    return normalize_actions(conn, raw_actions)


def build_empty_result_follow_up_questions(
    query: str,
    parsed_filters: dict[str, Any],
) -> list[str]:
    max_price = parsed_filters.get("max_price")
    lower_query = query.lower()
    if any(word in query for word in ("篮球鞋", "球鞋", "篮球")) or "basketball" in lower_query:
        budget = int(max_price * 1.2) if isinstance(max_price, (int, float)) and max_price > 100 else 500
        return [
            f"放宽到{budget}以内再找篮球鞋",
            "找几款非耐克篮球鞋",
            "适合外场实战的有哪些",
        ]
    if any(word in query for word in ("跑鞋", "运动鞋", "鞋")) or "shoe" in lower_query:
        budget = int(max_price * 1.2) if isinstance(max_price, (int, float)) and max_price > 100 else 300
        return [
            f"放宽到{budget}以内再找鞋",
            "通勤和运动两用的有哪些",
            "找几款性价比高的品牌",
        ]
    if any(word in query for word in ("耳机", "蓝牙", "降噪")) or "ear" in lower_query:
        budget = int(max_price * 1.2) if isinstance(max_price, (int, float)) and max_price > 100 else 300
        return [
            f"放宽到{budget}以内再找耳机",
            "优先降噪的耳机有哪些",
            "适合通勤佩戴的有哪些",
        ]
    return [
        "放宽预算范围再找找",
        "换个品牌看看",
        "描述一下使用场景",
    ]


def build_follow_up_questions(
    products: list[dict[str, Any]],
    query: str,
    parsed_filters: dict[str, Any],
) -> list[str]:
    first = products[0]
    category_text = str(first.get("subcategory") or first.get("category") or "商品")
    brands = [str(product.get("brand") or "").strip() for product in products if product.get("brand")]
    primary_brand = brands[0] if brands else ""
    excluded_brands = parsed_filters.get("excluded_brands") or []
    max_price = parsed_filters.get("max_price")
    lower_query = query.lower()

    if any(word in query for word in ("篮球鞋", "球鞋", "篮球")) or "basketball" in lower_query:
        budget = int(max_price * 0.8) if isinstance(max_price, (int, float)) and max_price > 100 else 500
        return [
            f"有没有{budget}以内的篮球鞋推荐",
            "球鞋搭配什么裤子好看",
            "帮我找耐克平替款球鞋" if not excluded_brands else "再推荐几款非耐克球鞋",
        ]

    if any(word in query for word in ("跑鞋", "运动鞋", "鞋")) or "shoe" in lower_query:
        budget = int(max_price * 0.8) if isinstance(max_price, (int, float)) and max_price > 100 else 300
        return [
            f"有没有{budget}以内的{category_text}推荐",
            "适合通勤和运动两用的有哪些",
            f"除了{primary_brand}还有什么品牌" if primary_brand else "帮我找性价比更高的款",
        ]

    if any(word in query for word in ("耳机", "蓝牙", "降噪")) or "ear" in lower_query:
        budget = int(max_price * 0.8) if isinstance(max_price, (int, float)) and max_price > 100 else 300
        return [
            f"有没有{budget}以内的蓝牙耳机推荐",
            "降噪和续航哪个更重要",
            "帮我找适合通勤的耳机",
        ]

    if max_price:
        return [
            f"有没有更便宜的{category_text}",
            f"{category_text}怎么选更划算",
            f"除了{primary_brand}还有什么选择" if primary_brand else f"有没有更适合预算的{category_text}",
        ]

    return [
        f"{category_text}怎么选更合适",
        f"有没有性价比更高的{category_text}",
        f"除了{primary_brand}还有什么选择" if primary_brand else f"还有哪些{category_text}值得看",
    ]


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


def enrich_product_presentations(user_message: str, products: list[dict[str, Any]]) -> None:
    if not products:
        return
    try:
        presentations = run_async_blocking(generate_product_presentations(user_message, products))
    except Exception as exc:
        logger.info("presentation_generation_failed=%s", exc.__class__.__name__)
        presentations = {}
    for index, product in enumerate(products):
        generated = presentations.get(str(product.get("id"))) if presentations else None
        fallback_title, fallback_reason = fallback_product_presentation(user_message, product, index)
        product["recommendation_title"] = fallback_title
        product["reason"] = (generated or {}).get("reason") or user_facing_reason(product.get("reason")) or fallback_reason


def fallback_product_presentation(user_message: str, product: dict[str, Any], index: int) -> tuple[str, str]:
    title = str(product.get("title") or "")
    category = str(product.get("subcategory") or product.get("category") or "商品")
    reason = str(product.get("reason") or "")
    price = float(product.get("price") or 0)
    if "预算" in reason or "放宽" in reason:
        return "预算备选", f"这款{category}是放宽预算后的相近选择，适合作为对比备选。"
    if any(term in user_message + title + reason for term in ("拍照", "影像", "摄影")) and "手机" in title:
        return "拍照优先", "更偏拍照和影像体验，适合把相机表现放在第一位的需求。"
    if any(term in user_message + title + reason for term in ("续航", "长续航")):
        return "长续航款", "更偏长时间稳定使用，适合通勤、出差或重度使用。"
    if any(term in user_message + title + reason for term in ("性能", "游戏")):
        return "性能配置", "更适合看重流畅度、配置和游戏表现的需求。"
    if any(term in user_message + title + reason for term in ("降噪", "通勤")) and "耳机" in title:
        return "通勤降噪", "更适合通勤、办公和嘈杂环境，重点看降噪和佩戴体验。"
    if any(term in user_message + title + reason for term in ("防晒", "海边", "三亚")):
        return "防晒防护", "适合户外或海边场景，重点看防护、轻便和便携性。"
    if any(term in title + category for term in ("篮球鞋", "球鞋")):
        return "实战支撑", "更适合运动和日常穿搭，重点看支撑、缓震和耐磨。"
    if price <= 300:
        return "高性价比", f"这款{category}价格更友好，适合作为预算有限时的实用选择。"
    return ("综合匹配" if index == 0 else "对比备选", f"这款{category}匹配当前需求，可结合价格、品牌和评分一起对比。")


def user_facing_reason(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    technical_tokens = ("RRF", "BM25", "retrieval", "Matched by", "score", "dense", "keyword")
    if any(token.lower() in text.lower() for token in technical_tokens):
        return None
    return text


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


def load_conversation_state(
    conn,
    session_id: str,
    current_product_id: str | None,
    cart_context: list[dict] | None,
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT last_query, last_recommended_product_ids, current_product_id FROM chat_sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    cart_items = cart_context or [
        item.model_dump(mode="json")
        for item in get_cart(conn).items
    ]
    return {
        "last_query": row["last_query"] if row else None,
        "last_recommended_product_ids": parse_product_id_list(row["last_recommended_product_ids"] if row else None),
        "current_product_id": current_product_id or (row["current_product_id"] if row else None),
        "cart_context": cart_items,
    }


def build_waiting_deltas(
    message: str,
    parsed_filters: dict[str, Any],
    image_id: str | None,
    has_chat_history: bool,
    skip_generic_intro: bool = False,
) -> list[str]:
    texts: list[str] = []
    lower_message = message.lower()
    excluded_brands = parsed_filters.get("excluded_brands") or []
    excluded_terms = parsed_filters.get("excluded_terms") or []
    has_exclusions = bool(excluded_brands or excluded_terms) or any(
        word in message for word in ("不要", "除了", "排除", "不含", "别要")
    )
    has_price = any(parsed_filters.get(key) is not None for key in ("min_price", "max_price"))
    wants_compare = any(word in message for word in ("对比", "比较", "哪个好", "哪款好")) or "compare" in lower_message

    if skip_generic_intro:
        if image_id:
            texts.append("我会结合图片线索一起匹配。")
        elif has_chat_history and any(word in message for word in ("再", "换", "继续", "还有", "便宜", "贵点")):
            texts.append("我会基于刚才的条件继续筛。")
        elif wants_compare:
            texts.append("我会重点整理关键差异。")
        elif has_exclusions:
            texts.append("我会先排除你不想要的条件。")
        elif has_price:
            texts.append("我会控制在预算范围内。")
    elif image_id:
        texts.append("我先根据图片线索匹配相似商品。")
    elif has_chat_history and any(word in message for word in ("再", "换", "继续", "还有", "便宜", "贵点")):
        texts.append("明白，我基于刚才的条件继续筛。")
    elif wants_compare:
        texts.append("我先把关键差异整理出来。")
    elif has_exclusions:
        texts.append("好的，我会先排除你不想要的条件。")
    elif has_price:
        texts.append("收到，我会控制在预算范围内。")
    else:
        texts.append("好的，我先帮你筛一下符合条件的商品。")

    if not skip_generic_intro and wants_compare:
        texts.append("正在对比价格、评分、库存和适合场景。")
    elif not skip_generic_intro and has_exclusions:
        texts.append("正在匹配剩余品牌、价格和库存。")
    elif not skip_generic_intro:
        texts.append("正在匹配商品、价格、评分和库存。")

    texts.append("我会优先展示最符合条件的几款。")
    return texts


def is_checkout_intent(message: str) -> bool:
    text = message.strip()
    return is_checkout_cancel_intent(text) or is_address_change_intent(text) or is_checkout_confirm_intent(text) or any(
        word in text for word in ("结算", "下单", "提交订单", "确认订单", "去支付", "支付")
    )


def is_cart_add_checkout_intent(message: str) -> bool:
    text = message.strip()
    has_add = any(word in text for word in ("加入购物车", "加购物车", "加购", "放购物车", "加入"))
    has_checkout = any(word in text for word in ("结算", "下单", "提交订单", "确认订单", "去支付", "支付"))
    return has_add and has_checkout


def pending_cart_add_checkout_message(message: str, chat_history: list[dict[str, str]]) -> str | None:
    if not is_sku_selection_message(message):
        return None
    for item in reversed(chat_history[-4:]):
        if item.get("role") != "user":
            continue
        content = str(item.get("content") or "")
        if is_cart_add_checkout_intent(content) or is_pending_direct_buy_intent(content):
            return content
        break
    return None


def is_pending_direct_buy_intent(message: str) -> bool:
    text = message.strip()
    has_reference = any(term in text for term in ("这双", "这款", "这个", "刚才", "刚刚", "第一", "第二", "第三"))
    return has_reference and has_checkout_signal(text)


def should_auto_confirm_checkout(message: str) -> bool:
    text = message.strip()
    return any(word in text for word in ("直接下单", "下单吧", "默认地址", "地址用默认", "用默认地址", "确认下单", "去支付"))


def is_order_cancel_intent(message: str) -> bool:
    text = message.strip()
    return "订单" in text and any(word in text for word in ("取消", "撤销", "关闭", "退掉", "不要了"))


def is_checkout_cancel_intent(message: str) -> bool:
    text = message.strip()
    return any(word in text for word in ("取消下单", "取消支付", "暂不下单", "先不买", "不下单"))


def is_checkout_confirm_intent(message: str) -> bool:
    text = message.strip()
    return any(
        word in text
        for word in ("确认下单", "确认下单并支付", "提交订单", "确认支付", "去支付", "直接下单", "下单吧", "默认地址", "地址用默认", "用默认地址")
    )


def is_address_change_intent(message: str) -> bool:
    text = message.strip()
    return "收货地址" in text and any(word in text for word in ("修改", "更换", "换", "新增", "添加"))


def load_default_address(conn) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM addresses ORDER BY is_default DESC, created_at DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def resolve_cancel_order(conn, message: str) -> dict[str, Any] | None:
    match = re.search(r"ord_[0-9a-fA-F]{10}", message)
    if match:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (match.group(0),)).fetchone()
        return dict(row) if row else None
    row = conn.execute(
        """
        SELECT *
        FROM orders
        WHERE status IN ('pending_payment', 'paid')
        ORDER BY created_at DESC
        LIMIT 1
        """
    ).fetchone()
    return dict(row) if row else None


def restore_order_stock(conn, order_id: str) -> None:
    rows = conn.execute("SELECT sku_id, quantity FROM order_items WHERE order_id = ?", (order_id,)).fetchall()
    for row in rows:
        if not row["sku_id"]:
            continue
        conn.execute(
            "UPDATE product_skus SET stock = stock + ? WHERE id = ?",
            (int(row["quantity"]), row["sku_id"]),
        )


def build_checkout_confirmation_text(cart: dict[str, Any], address: dict[str, Any] | None) -> str:
    selected_items = [item for item in cart.get("items", []) if item.get("selected", True)]
    address_text = (
        f"{address['receiver_name']} {address['phone']}，{address['province']}{address['city']}{address['district']}{address['detail']}"
        if address
        else "还没有默认收货地址"
    )
    lines = [
        "我先帮你核对下单信息：",
        f"收货地址：{address_text}",
        "订单商品：",
    ]
    for index, item in enumerate(selected_items[:4], start=1):
        lines.append(
            f"{index}. {item['title']}｜{item.get('sku_name') or '默认规格'}｜x{item.get('quantity') or 1}｜¥{float(item.get('price') or 0):.2f}"
        )
    if len(selected_items) > 4:
        lines.append(f"还有 {len(selected_items) - 4} 件商品未展开。")
    lines.append(f"合计 ¥{float(cart.get('total_amount') or 0):.2f}")
    if address:
        lines.append("确认无误后点“确认下单并支付”，我会模拟完成支付。")
    else:
        lines.append("请先补充收货地址，再继续下单。")
    return "\n".join(lines)


def build_checkout_failure_actions(message: str) -> list[dict[str, Any]]:
    if any(term in message for term in ("库存不足", "库存刚刚发生变化")):
        return [
            {"type": "open_cart", "label": "打开购物车", "product_id": None},
            {"type": "search_more", "label": "把数量改少一点", "product_id": None},
            {"type": "search_more", "label": "重新推荐替代商品", "product_id": None},
        ]
    if any(term in message for term in ("规格已不存在", "没有可购买规格")):
        return [
            {"type": "open_cart", "label": "打开购物车", "product_id": None},
            {"type": "search_more", "label": "重新选择规格", "product_id": None},
        ]
    return [{"type": "open_cart", "label": "打开购物车", "product_id": None}]


def create_paid_order_from_cart(conn, address: dict[str, Any]) -> dict[str, Any]:
    cart = get_cart(conn)
    selected_items = [item for item in cart.items if item.selected]
    if not selected_items:
        raise ValueError("购物车里没有选中的商品，请先选择要结算的商品。")
    stock_problem = find_stock_problem(conn, selected_items)
    if stock_problem:
        raise ValueError(stock_problem)

    order_id = f"ord_{uuid.uuid4().hex[:10]}"
    total = round(sum(item.price * item.quantity for item in selected_items), 2)
    payment_id = f"pay_{uuid.uuid4().hex[:10]}"
    conn.execute("SAVEPOINT checkout_order")
    try:
        conn.execute(
            """
            INSERT INTO orders(id, status, total_amount, address_id, address_snapshot)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                order_id,
                "paid",
                total,
                address["id"],
                json.dumps(address, ensure_ascii=False),
            ),
        )
        for item in selected_items:
            sku_id = checkout_sku_id(conn, item)
            conn.execute(
                """
                INSERT INTO order_items(id, order_id, product_id, sku_id, title, brand, image_path, sku_name, price, quantity)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"oi_{uuid.uuid4().hex[:10]}",
                    order_id,
                    item.product_id,
                    sku_id,
                    item.title,
                    item.brand,
                    item.image_path,
                    item.sku_name,
                    item.price,
                    item.quantity,
                ),
            )
            updated = conn.execute(
                "UPDATE product_skus SET stock = stock - ? WHERE id = ? AND stock >= ?",
                (item.quantity, sku_id, item.quantity),
            )
            if updated.rowcount != 1:
                raise ValueError(f"{item.title}（{item.sku_name}）库存刚刚发生变化，请重新确认后再下单。")
        conn.executemany("DELETE FROM cart_items WHERE id = ?", [(item.id,) for item in selected_items])
        conn.execute(
            "INSERT INTO payments(id, order_id, status, amount) VALUES (?, ?, ?, ?)",
            (payment_id, order_id, "paid", total),
        )
        conn.execute("RELEASE checkout_order")
    except Exception:
        conn.execute("ROLLBACK TO checkout_order")
        conn.execute("RELEASE checkout_order")
        raise
    return {
        "order_id": order_id,
        "payment_id": payment_id,
        "total_amount": total,
        "items": selected_items,
        "address": address,
    }


def checkout_sku_id(conn, item: Any) -> str:
    if item.sku_id:
        return item.sku_id
    row = conn.execute(
        "SELECT id FROM product_skus WHERE product_id = ? ORDER BY price ASC LIMIT 1",
        (item.product_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"{item.title} 没有可购买规格，请重新选择商品。")
    return row["id"]


def find_stock_problem(conn, items: list[Any]) -> str | None:
    for item in items:
        sku_id = checkout_sku_id(conn, item)
        row = conn.execute(
            """
            SELECT stock
            FROM product_skus
            WHERE id = ? AND product_id = ?
            """,
            (sku_id, item.product_id),
        ).fetchone()
        if not row:
            return f"{item.title} 的规格已不存在，请重新选择规格后再下单。"
        stock = int(row["stock"] or 0)
        if stock < item.quantity:
            return f"{item.title}（{item.sku_name}）库存不足，当前只剩 {stock} 件，请调整数量后再下单。"
    return None


def build_order_success_text(order: dict[str, Any]) -> str:
    address = order["address"]
    lines = [
        "下单完成，已模拟支付成功。",
        f"订单号：{order['order_id']}",
        f"支付流水：{order['payment_id']}",
        f"收货地址：{address['receiver_name']} {address['phone']}，{address['province']}{address['city']}{address['district']}{address['detail']}",
        "订单商品：",
    ]
    for index, item in enumerate(order["items"][:4], start=1):
        lines.append(f"{index}. {item.title}｜{item.sku_name}｜x{item.quantity}｜¥{item.price:.2f}")
    lines.append(f"实付 ¥{order['total_amount']:.2f}")
    return "\n".join(lines)


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


def stream_grounded_answer_events(
    message: str,
    grounded_products: list[dict[str, Any]],
    faq_context: list[dict[str, str]],
    chat_history: list[dict[str, str]],
):
    if not grounded_products:
        answer = build_template_answer(grounded_products, message)
        status = {"mode": "fallback", "reason": "no_retrieved_products"}
        yield sse_event("llm_status", status)
        yield sse_event("delta", {"text": answer})
        return answer, status

    yield sse_event("llm_status", {"mode": "calling", "provider": "poe", "stream": True})
    chunks: list[str] = []
    try:
        yield sse_event("delta", {"text": "\n"})
        for chunk in iter_async_blocking(
            stream_agent_reply_chunks_with_status(message, grounded_products, faq_context, chat_history)
        ):
            chunks.append(chunk)
            yield sse_event("delta", {"text": chunk})
        answer = " ".join("".join(chunks).split()).strip()
        if not answer:
            raise LLMGenerationError("LLM response is empty")
        return answer, {"mode": "llm_stream", "provider": "poe", "model": llm_model_name()}
    except LLMGenerationError as exc:
        if chunks:
            answer = " ".join("".join(chunks).split()).strip()
            return answer, {"mode": "llm_stream_partial", "provider": "poe", "model": llm_model_name()}
        answer = build_template_answer(grounded_products, message)
        status = {"mode": "fallback", "reason": str(exc)}
        yield sse_event("delta", {"text": answer})
        return answer, status
    except Exception as exc:
        if chunks:
            answer = " ".join("".join(chunks).split()).strip()
            return answer, {"mode": "llm_stream_partial", "provider": "poe", "model": llm_model_name()}
        answer = build_template_answer(grounded_products, message)
        status = {"mode": "fallback", "reason": exc.__class__.__name__}
        yield sse_event("delta", {"text": answer})
        return answer, status


def iter_async_blocking(async_iterable: AsyncIterator[str]) -> Iterable[str]:
    loop = asyncio.new_event_loop()
    try:
        iterator = async_iterable.__aiter__()
        while True:
            try:
                yield loop.run_until_complete(iterator.__anext__())
            except StopAsyncIteration:
                break
    finally:
        loop.close()


def run_async_blocking(coro) -> Any:
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


def build_alternative_answer(query: str, alternatives: list[dict[str, Any]]) -> str:
    if not alternatives:
        return build_template_answer([], query)
    first = alternatives[0]
    price = float(first.get("price") or 0)
    return (
        f"没有找到完全符合条件的商品。可选替代里最接近的是 {first['title']}，价格 ¥{price:.0f}；"
        "下方卡片已单独作为替代品展示。"
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

    session_row = conn.execute(
        "SELECT last_recommended_product_ids, current_product_id FROM chat_sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if not is_cart_intent(normalized) and not is_sku_selection_message(normalized):
        return None
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


def is_sku_selection_message(message: str) -> bool:
    return bool(re.fullmatch(r"\s*\d{2}(?:\.\d)?\s*(?:码)?\s*", message)) or any(
        word in message for word in ["尺码", "规格", "款式", "选择"]
    )


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


def fetch_cart_skus(conn, product_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, sku_name, properties_json, price, stock
        FROM product_skus
        WHERE product_id = ? AND stock > 0
        ORDER BY price ASC, id ASC
        """,
        (product_id,),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "sku_name": row["sku_name"] or "默认规格",
            "properties": parse_sku_properties(row["properties_json"]),
            "price": float(row["price"] or 0),
            "stock": int(row["stock"] or 0),
        }
        for row in rows
    ]


def resolve_sku_from_message(message: str, skus: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not skus:
        return None
    normalized = message.replace(" ", "")
    distinct_keys = sku_distinct_property_keys(skus)
    for sku in skus:
        properties = sku.get("properties") or {}
        sku_terms = [str(sku["sku_name"]), *[str(properties.get(key) or "") for key in distinct_keys]]
        if any(term and term.replace(" ", "") in normalized for term in sku_terms):
            return sku
    size_match = re.search(r"(\d{2}(?:\.\d)?)\s*码?", message)
    if size_match:
        size = size_match.group(1)
        for sku in skus:
            sku_text = " ".join([str(sku["sku_name"]), *[str(value) for value in sku.get("properties", {}).values()]])
            if size in sku_text:
                return sku
    return skus[0] if len(skus) == 1 else None


def build_sku_selection_prompt(product_title: str, skus: list[dict[str, Any]]) -> str:
    all_labels = unique_sku_option_labels(skus)
    shown_labels = all_labels[:6]
    sku_text = "、".join(shown_labels)
    suffix = " 等" if len(all_labels) > len(shown_labels) else ""
    dimension = sku_dimension_name(skus)
    if len(all_labels) > SKU_ACTION_OPTION_LIMIT:
        example = shown_labels[0] if shown_labels else "具体规格"
        return f"这款 {product_title} 有多个{dimension}可选：{sku_text}{suffix}。选项较多，请直接输入要加入购物车的{dimension}，例如“{example}”。"
    return f"这款 {product_title} 需要先确认{dimension}。可选{dimension}有：{sku_text}，你想加入哪一个？"


def build_sku_selection_actions(skus: list[dict[str, Any]]) -> list[dict[str, Any]]:
    labels = unique_sku_option_labels(skus)
    if len(labels) > SKU_ACTION_OPTION_LIMIT:
        return []
    return [
        {"type": "search_more", "label": f"选择{label}", "product_id": None}
        for label in labels
    ]


SKU_ACTION_OPTION_LIMIT = 4
SKU_DIMENSION_PRIORITY = ("尺码", "型号", "容量", "内存", "存储", "颜色", "色号", "版本", "配置", "套餐", "规格", "款式", "款型")


def unique_sku_option_labels(skus: list[dict[str, Any]], limit: int | None = None) -> list[str]:
    labels: list[str] = []
    for sku in skus:
        label = compact_sku_label(sku, skus)
        if label and label not in labels:
            labels.append(label)
        if limit is not None and len(labels) >= limit:
            break
    return labels


def compact_sku_label(sku: dict[str, Any], all_skus: list[dict[str, Any]]) -> str:
    properties = sku.get("properties") or {}
    distinct_keys = sku_distinct_property_keys(all_skus)
    values = [str(properties.get(key) or "").strip() for key in distinct_keys[:2]]
    label = " / ".join(value for value in values if value)
    if label:
        return label
    text = str(sku.get("sku_name") or "默认规格")
    size_match = re.search(r"尺码\s*[:：]?\s*([^/；，,\s]+)", text)
    if size_match:
        return size_match.group(1)
    return text.strip()[:18]


def sku_dimension_name(skus: list[dict[str, Any]]) -> str:
    keys = sku_distinct_property_keys(skus)
    if not keys:
        return "规格"
    if "尺码" in keys:
        return "尺码"
    if any(key in keys for key in ("型号", "版本", "配置")):
        return "型号"
    if any(key in keys for key in ("容量", "内存", "存储")):
        return "容量/配置"
    if any(key in keys for key in ("颜色", "色号")):
        return "颜色"
    return "规格"


def sku_distinct_property_keys(skus: list[dict[str, Any]]) -> list[str]:
    keys: list[str] = []
    all_keys = {
        key
        for sku in skus
        for key in (sku.get("properties") or {}).keys()
    }
    for key in SKU_DIMENSION_PRIORITY:
        if key not in all_keys:
            continue
        values = {
            str((sku.get("properties") or {}).get(key) or "").strip()
            for sku in skus
            if str((sku.get("properties") or {}).get(key) or "").strip()
        }
        if len(values) > 1:
            keys.append(key)
    return keys


def parse_sku_properties(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def add_product_to_cart(conn, product_id: str, sku_id: str | None = None) -> dict[str, Any] | None:
    product = conn.execute("SELECT id, title FROM products WHERE id = ?", (product_id,)).fetchone()
    if not product:
        return None
    if sku_id:
        sku = conn.execute(
            "SELECT id, sku_name FROM product_skus WHERE product_id = ? AND id = ?",
            (product_id, sku_id),
        ).fetchone()
    else:
        sku = conn.execute(
            "SELECT id, sku_name FROM product_skus WHERE product_id = ? ORDER BY price ASC LIMIT 1",
            (product_id,),
        ).fetchone()
    conn.execute(
        "INSERT INTO cart_items(id, product_id, sku_id, quantity, selected) VALUES (?, ?, ?, 1, 1)",
        (f"cart_{uuid.uuid4().hex[:10]}", product_id, sku["id"] if sku else None),
    )
    return {
        "id": product["id"],
        "title": product["title"],
        "sku_id": sku["id"] if sku else None,
        "sku_name": sku["sku_name"] if sku else None,
    }
