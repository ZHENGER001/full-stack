from __future__ import annotations

import logging
import time
import uuid
from typing import Iterable

from .agent_state import AgentTurnRequest, AgentTurnState
from .agentic_rag import plan_agentic_turn
from .catalog import get_cart
from .react_planner import plan_react_transaction
from .tool_registry import DEFAULT_TOOL_REGISTRY

logger = logging.getLogger(__name__)


def stream_agent_turn(conn, request: AgentTurnRequest) -> Iterable[str]:
    # Import the legacy emitters lazily to keep this stage as a routing shell,
    # without moving every SSE helper in the same PR.
    from . import agent as legacy

    session_id = request.session_id
    message = request.message
    image_id = request.image_id
    current_product_id = request.current_product_id
    cart_context = request.cart_context or []

    legacy.ensure_session(conn, session_id)
    if current_product_id and legacy.product_exists(conn, current_product_id):
        legacy.update_session_state(conn, session_id, current_product_id=current_product_id)
    previous_chat_history = legacy.load_chat_history(conn, session_id)
    stored_user_message = legacy.batch_cart_confirm_display_text(message) or message
    conn.execute(
        "INSERT INTO chat_messages(id, session_id, role, content, image_id) VALUES (?, ?, ?, ?, ?)",
        (f"msg_{uuid.uuid4().hex[:12]}", session_id, "user", stored_user_message, image_id),
    )
    if legacy.is_batch_cart_confirm_message(message):
        yield from legacy.emit_batch_cart_confirm_turn(conn, session_id, message, image_id)
        return

    state = AgentTurnState(
        request=request,
        chat_history=previous_chat_history,
        conversation_state=legacy.load_conversation_state(conn, session_id, current_product_id, cart_context),
    )

    if legacy.is_order_cancel_intent(message):
        yield from legacy.emit_order_cancel_turn(conn, session_id, message, image_id)
        return
    pending_checkout_message = legacy.pending_cart_add_checkout_message(message, state.chat_history)
    if pending_checkout_message:
        yield from legacy.emit_cart_add_checkout_turn(
            conn,
            session_id,
            f"{pending_checkout_message} {message}",
            image_id,
            state.chat_history,
            state.conversation_state,
        )
        return
    react_plan = legacy.run_async_blocking(
        plan_react_transaction(message, state.chat_history, state.conversation_state)
    )
    if react_plan.should_execute and any(step.action in {"cart_add", "checkout"} for step in react_plan.steps):
        yield from legacy.emit_react_transaction_turn(conn, session_id, message, image_id, react_plan)
        return
    if legacy.is_cart_add_checkout_intent(message):
        yield from legacy.emit_cart_add_checkout_turn(
            conn,
            session_id,
            message,
            image_id,
            state.chat_history,
            state.conversation_state,
        )
        return
    if legacy.is_checkout_intent(message):
        yield from legacy.emit_checkout_turn(conn, session_id, message, image_id)
        return

    try:
        state.turn_plan = legacy.run_async_blocking(
            plan_agentic_turn(message, state.chat_history, state.conversation_state)
        )
        state.parsed_turn = state.turn_plan.parsed_turn
        logger.info("agent_parsed_turn=%s", state.parsed_turn.model_dump(mode="json"))
        if state.turn_plan.should_run_bounded_tool:
            bounded_result = DEFAULT_TOOL_REGISTRY.call(
                "bounded_agent",
                conn=conn,
                parsed_turn=state.parsed_turn,
                conversation_state=state.conversation_state,
            )
            yield from legacy.emit_bounded_result(conn, session_id, message, image_id, bounded_result)
            return
        if state.parsed_turn.intent_type == "bundle_recommendation":
            yield from legacy.emit_bundle_recommendation_turn(conn, session_id, message, image_id, state.turn_plan)
            return
        if not state.turn_plan.should_search_products:
            assistant_content = state.turn_plan.policy.response_text or "这个操作我正在支持中。"
            actions = legacy.build_clarification_actions(
                conn,
                state.parsed_turn.clarification_question or assistant_content,
            )
            yield legacy.sse_event("delta", {"text": assistant_content})
            if actions:
                yield legacy.sse_event("actions", {"actions": actions})
            legacy.store_assistant_message(conn, session_id, assistant_content, image_id)
            legacy.update_session_state(conn, session_id, last_query=message, last_actions=actions or None)
            yield legacy.sse_event("done", {"session_id": session_id})
            return
    except Exception as exc:
        logger.info("turn_parser_failed=%s", exc.__class__.__name__)

    cart_product_id = legacy.resolve_cart_product_id(conn, session_id, message, current_product_id, cart_context)
    if cart_product_id:
        skus = legacy.fetch_cart_skus(conn, cart_product_id)
        selected_sku = legacy.resolve_sku_from_message(message, skus)
        if len(skus) > 1 and selected_sku is None:
            product = conn.execute("SELECT id, title FROM products WHERE id = ?", (cart_product_id,)).fetchone()
            if product:
                actions = legacy.build_sku_selection_actions(skus)
                assistant_content = legacy.build_sku_selection_prompt(product["title"], skus)
                yield legacy.sse_event("delta", {"text": assistant_content})
                yield legacy.sse_event("actions", {"actions": actions})
                legacy.store_assistant_message(conn, session_id, assistant_content, image_id)
                legacy.update_session_state(
                    conn,
                    session_id,
                    last_query=message,
                    current_product_id=cart_product_id,
                    last_actions=actions,
                )
                yield legacy.sse_event("done", {"session_id": session_id})
                return
        cart_product = legacy.add_product_to_cart(conn, cart_product_id, selected_sku["id"] if selected_sku else None)
        if cart_product:
            actions = legacy.normalize_actions(conn, [{"type": "open_cart", "label": "打开购物车", "product_id": None}])
            sku_text = f"（{cart_product['sku_name']}）" if cart_product.get("sku_name") else ""
            cart_payload = get_cart(conn).model_dump(mode="json")
            assistant_content = f"已把 {cart_product['title']}{sku_text} 加入购物车，数量 1。购物车详情如下。"
            yield legacy.sse_event("delta", {"text": assistant_content})
            yield legacy.sse_event("cart", cart_payload)
            yield legacy.sse_event("actions", {"actions": actions})
            legacy.store_assistant_message(conn, session_id, assistant_content, image_id)
            legacy.update_session_state(
                conn,
                session_id,
                last_query=message,
                current_product_id=cart_product_id,
                last_actions=actions,
            )
            yield legacy.sse_event("done", {"session_id": session_id})
            return

    image_query = None
    if image_id:
        detected, image_query = legacy.analyze_image(conn, image_id, message)
        yield legacy.sse_event(
            "delta",
            {
                "text": (
                    f"我识别到图片里像是{detected['color']}{detected['style']}风格的{detected['object_type']}，"
                    f"材质特征偏{detected['material']}，场景更接近{detected['scene']}。"
                )
            },
        )

    final_user_query = legacy.build_final_user_query(conn, message, image_query, current_product_id, session_id)
    retrieval_result = DEFAULT_TOOL_REGISTRY.call(
        "search_products",
        conn=conn,
        query=final_user_query,
        known_brands=legacy.load_known_brands(conn),
        turn_plan=state.turn_plan,
    )
    parsed_filters = retrieval_result.parsed_filters
    logger.info("agent_final_user_query=%s parsed_filters=%s", final_user_query, parsed_filters)
    for waiting_text in legacy.build_waiting_deltas(message, parsed_filters, image_id, bool(state.chat_history)):
        yield legacy.sse_event("delta", {"text": f"{waiting_text}\n"})
        time.sleep(0.25)
    yield legacy.sse_event(
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
                "intent_type": state.parsed_turn.intent_type if state.parsed_turn else "unknown",
                "route_hint": state.parsed_turn.route_hint if state.parsed_turn else "direct_tool",
                "needs_clarification": state.parsed_turn.needs_clarification if state.parsed_turn else False,
                "graph_backend": state.turn_plan.graph_backend if state.turn_plan else "langgraph_fallback",
            },
        },
    )
    search_result = retrieval_result.search_result
    products = search_result.products
    alternatives = search_result.alternatives
    yield legacy.sse_event("retrieval_diagnostics", search_result.diagnostics)
    grounded_products = legacy.build_grounded_products(conn, products)
    visible_products_from_search = legacy.visible_chat_products(grounded_products)
    grounded_alternatives = [] if grounded_products else legacy.build_grounded_products(conn, alternatives)
    visible_alternatives = legacy.visible_chat_products(grounded_alternatives)
    visible_products = visible_products_from_search or visible_alternatives
    legacy.enrich_product_presentations(message, visible_products)
    faq_context = legacy.load_faq_context(conn, [product["id"] for product in visible_products_from_search])
    chat_history = legacy.load_chat_history(conn, session_id)
    actions = legacy.build_actions(conn, visible_products, final_user_query, parsed_filters)
    if visible_products_from_search:
        yield legacy.sse_event("products", {"products": visible_products_from_search})
    elif visible_alternatives:
        yield legacy.sse_event("alternatives", {"products": visible_alternatives, "match_type": "alternatives"})
    if not visible_products_from_search and visible_alternatives:
        answer = legacy.build_alternative_answer(message, visible_alternatives)
        llm_status = {"mode": "fallback", "reason": "alternatives_available"}
        yield legacy.sse_event("llm_status", llm_status)
        yield legacy.sse_event("delta", {"text": answer})
    else:
        answer, llm_status = yield from legacy.stream_grounded_answer_events(
            message,
            visible_products_from_search,
            faq_context,
            chat_history,
        )
        if visible_products_from_search:
            yield legacy.sse_event("llm_status", llm_status)

    if actions:
        yield legacy.sse_event("actions", {"actions": actions})

    assistant_content = legacy.append_recommendation_marker(answer, visible_products)
    legacy.store_assistant_message(conn, session_id, assistant_content, image_id)
    legacy.update_session_state(
        conn,
        session_id,
        last_query=message,
        last_recommended_product_ids=[product["id"] for product in visible_products],
        current_product_id=visible_products[0]["id"] if visible_products else current_product_id,
        last_actions=actions,
    )
    yield legacy.sse_event("done", {"session_id": session_id})
