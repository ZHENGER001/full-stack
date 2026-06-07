from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from .catalog import first_sku, get_cart, row_to_product_card
from .turn_schema import ParsedTurn, ProductReference


BoundedStatus = Literal["ok", "needs_reference", "not_found", "unsupported", "guard_blocked"]


ALLOWED_TOOLS_BY_INTENT: dict[str, set[str]] = {
    "product_detail_qa": {"resolve_product_reference", "get_product_detail"},
    "product_compare": {"resolve_product_reference", "compare_products"},
    "cart_add": {"resolve_product_reference", "cart_add"},
    "cart_remove": {"resolve_cart_item_reference", "cart_remove"},
    "cart_update_quantity": {"resolve_cart_item_reference", "cart_update_quantity"},
    "cart_list": {"cart_list"},
    "cart_clear": {"cart_clear"},
}


@dataclass(frozen=True)
class BoundedToolResult:
    tool_name: str
    status: BoundedStatus
    response_text: str
    product_ids: list[str] = field(default_factory=list)
    products: list[dict[str, Any]] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    current_product_id: str | None = None
    cart: dict[str, Any] | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProductSnapshot:
    id: str
    title: str
    brand: str
    category: str
    subcategory: str
    price: float
    rating: float
    stock: int
    sku_summary: str | None
    marketing_description: str


def execute_bounded_turn(conn, parsed_turn: ParsedTurn, conversation_state: dict[str, Any] | None) -> BoundedToolResult:
    intent = parsed_turn.intent_type
    if intent == "product_detail_qa":
        return _handle_product_detail_qa(conn, parsed_turn, conversation_state)
    if intent == "product_compare":
        return _handle_product_compare(conn, parsed_turn, conversation_state)
    if intent == "cart_add":
        return _handle_cart_add(conn, parsed_turn, conversation_state)
    if intent == "cart_remove":
        return _handle_cart_remove(conn, parsed_turn, conversation_state)
    if intent == "cart_update_quantity":
        return _handle_cart_update_quantity(conn, parsed_turn, conversation_state)
    if intent == "cart_list":
        return _handle_cart_list(conn)
    if intent == "cart_clear":
        return _handle_cart_clear(conn)
    return BoundedToolResult(
        tool_name="unsupported",
        status="unsupported",
        response_text="这个操作我正在支持中。",
        diagnostics={"intent_type": intent, "reason": "unsupported_intent"},
    )


def _handle_product_detail_qa(conn, parsed_turn: ParsedTurn, conversation_state: dict[str, Any] | None) -> BoundedToolResult:
    tool_name = "get_product_detail"
    guard = _guard_tool(parsed_turn.intent_type, tool_name)
    if guard:
        return guard
    product_ids, diagnostics = resolve_product_references(conn, parsed_turn.references, conversation_state)
    if not product_ids:
        return _needs_reference(tool_name, "你想查看哪一款商品？", diagnostics)
    snapshots = _fetch_product_snapshots(conn, product_ids[:1])
    if not snapshots:
        return _not_found(tool_name, diagnostics)
    product = snapshots[0]
    dimensions = set(parsed_turn.compare_dimensions or [])
    if "stock" in dimensions:
        availability = "有货" if product.stock > 0 else "暂时无货"
        text = f"{product.title} 目前{availability}，库存约 {product.stock} 件。"
    elif "price" in dimensions:
        text = f"{product.title} 当前价格是 ¥{product.price:.0f}。"
    else:
        sku_text = f"，规格有 {product.sku_summary}" if product.sku_summary else ""
        text = (
            f"{product.title} 属于 {product.category}/{product.subcategory}，"
            f"价格 ¥{product.price:.0f}，评分 {product.rating:.1f}，库存约 {product.stock} 件{sku_text}。"
        )
    product_cards = _fetch_product_cards(conn, [product.id])
    return BoundedToolResult(
        tool_name=tool_name,
        status="ok",
        response_text=text,
        product_ids=[product.id],
        products=product_cards,
        current_product_id=product.id,
        diagnostics={**diagnostics, "intent_type": parsed_turn.intent_type, "status": "ok"},
    )


def _handle_product_compare(conn, parsed_turn: ParsedTurn, conversation_state: dict[str, Any] | None) -> BoundedToolResult:
    tool_name = "compare_products"
    guard = _guard_tool(parsed_turn.intent_type, tool_name)
    if guard:
        return guard
    product_ids, diagnostics = resolve_product_references(conn, parsed_turn.references, conversation_state)
    product_ids = list(dict.fromkeys(product_ids))
    if len(product_ids) < 2:
        return _needs_reference(tool_name, "请选择要比较的两款商品。", diagnostics)
    snapshots = _fetch_product_snapshots(conn, product_ids[:3])
    if len(snapshots) < 2:
        return _not_found(tool_name, diagnostics)

    dimensions = set(parsed_turn.compare_dimensions or ["price", "rating", "stock"])
    if "price" in dimensions:
        cheapest = min(snapshots, key=lambda item: item.price)
        parts = [f"{item.title} ¥{item.price:.0f}" for item in snapshots]
        text = f"{'；'.join(parts)}。更便宜的是 {cheapest.title}。"
    else:
        parts = [
            f"{item.title}：¥{item.price:.0f}、评分 {item.rating:.1f}、库存 {item.stock} 件"
            for item in snapshots
        ]
        text = "；".join(parts) + "。"
    product_cards = _fetch_product_cards(conn, [item.id for item in snapshots])
    return BoundedToolResult(
        tool_name=tool_name,
        status="ok",
        response_text=text,
        product_ids=[item.id for item in snapshots],
        products=product_cards,
        current_product_id=snapshots[0].id,
        diagnostics={**diagnostics, "intent_type": parsed_turn.intent_type, "status": "ok"},
    )


def _handle_cart_add(conn, parsed_turn: ParsedTurn, conversation_state: dict[str, Any] | None) -> BoundedToolResult:
    tool_name = "cart_add"
    guard = _guard_tool(parsed_turn.intent_type, tool_name)
    if guard:
        return guard
    product_ids, diagnostics = resolve_product_references(conn, parsed_turn.references, conversation_state)
    if not product_ids:
        return _needs_reference(tool_name, "你想把哪一款商品加入购物车？", diagnostics)
    quantity = parsed_turn.quantity or 1
    product = _fetch_product_snapshots(conn, product_ids[:1])
    if not product:
        return _not_found(tool_name, diagnostics)
    _add_product_to_cart(conn, product[0].id, quantity)
    product_cards = _fetch_product_cards(conn, [product[0].id])
    return BoundedToolResult(
        tool_name=tool_name,
        status="ok",
        response_text=f"已把 {product[0].title} 加入购物车，数量 {quantity}。",
        product_ids=[product[0].id],
        products=product_cards,
        actions=[{"type": "open_cart", "label": "打开购物车", "product_id": None}],
        current_product_id=product[0].id,
        cart=_cart_payload(conn),
        diagnostics={**diagnostics, "intent_type": parsed_turn.intent_type, "status": "ok"},
    )


def _handle_cart_remove(conn, parsed_turn: ParsedTurn, conversation_state: dict[str, Any] | None) -> BoundedToolResult:
    tool_name = "cart_remove"
    guard = _guard_tool(parsed_turn.intent_type, tool_name)
    if guard:
        return guard
    item_ids, diagnostics = resolve_cart_item_references(conn, parsed_turn.references, conversation_state)
    if not item_ids:
        return _needs_reference(tool_name, "你想删除购物车里的哪一项？", diagnostics)
    titles = _cart_item_titles(conn, item_ids)
    conn.executemany("DELETE FROM cart_items WHERE id = ?", [(item_id,) for item_id in item_ids])
    title_text = "、".join(titles) if titles else f"{len(item_ids)} 项商品"
    return BoundedToolResult(
        tool_name=tool_name,
        status="ok",
        response_text=f"已从购物车删除 {title_text}。",
        cart=_cart_payload(conn),
        diagnostics={**diagnostics, "intent_type": parsed_turn.intent_type, "status": "ok"},
    )


def _handle_cart_update_quantity(conn, parsed_turn: ParsedTurn, conversation_state: dict[str, Any] | None) -> BoundedToolResult:
    tool_name = "cart_update_quantity"
    guard = _guard_tool(parsed_turn.intent_type, tool_name)
    if guard:
        return guard
    if not parsed_turn.quantity:
        return _needs_reference(tool_name, "你想把数量改成几件？", {"reason": "missing_quantity"})
    item_ids, diagnostics = resolve_cart_item_references(conn, parsed_turn.references, conversation_state)
    if not item_ids:
        return _needs_reference(tool_name, "你想修改购物车里的哪一项？", diagnostics)
    conn.executemany(
        "UPDATE cart_items SET quantity = ?, selected = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        [(parsed_turn.quantity, item_id) for item_id in item_ids],
    )
    titles = _cart_item_titles(conn, item_ids)
    title_text = "、".join(titles) if titles else f"{len(item_ids)} 项商品"
    return BoundedToolResult(
        tool_name=tool_name,
        status="ok",
        response_text=f"已把 {title_text} 的数量改为 {parsed_turn.quantity}。",
        cart=_cart_payload(conn),
        diagnostics={**diagnostics, "intent_type": parsed_turn.intent_type, "status": "ok"},
    )


def _handle_cart_list(conn) -> BoundedToolResult:
    tool_name = "cart_list"
    guard = _guard_tool("cart_list", tool_name)
    if guard:
        return guard
    cart = get_cart(conn)
    if not cart.items:
        text = "购物车现在是空的。"
    else:
        parts = [f"{item.title} x{item.quantity}" for item in cart.items[:4]]
        suffix = "，还有更多商品" if len(cart.items) > 4 else ""
        text = f"购物车里有 {'、'.join(parts)}{suffix}，合计 ¥{cart.total_amount:.0f}。"
    return BoundedToolResult(
        tool_name=tool_name,
        status="ok",
        response_text=text,
        cart=cart.model_dump(mode="json"),
        diagnostics={"intent_type": "cart_list", "status": "ok"},
    )


def _handle_cart_clear(conn) -> BoundedToolResult:
    tool_name = "cart_clear"
    guard = _guard_tool("cart_clear", tool_name)
    if guard:
        return guard
    before = get_cart(conn)
    conn.execute("DELETE FROM cart_items")
    count = sum(item.quantity for item in before.items)
    text = "购物车已经是空的。" if count == 0 else f"已清空购物车，共移除 {count} 件商品。"
    return BoundedToolResult(
        tool_name=tool_name,
        status="ok",
        response_text=text,
        cart=_cart_payload(conn),
        diagnostics={"intent_type": "cart_clear", "status": "ok", "removed_quantity": count},
    )


def resolve_product_references(
    conn,
    references: list[ProductReference],
    conversation_state: dict[str, Any] | None,
) -> tuple[list[str], dict[str, Any]]:
    state = conversation_state or {}
    recent_ids = _valid_product_ids(conn, _recent_product_ids(state))
    current_product_id = state.get("current_product_id")
    if current_product_id and not _product_exists(conn, str(current_product_id)):
        current_product_id = None

    resolved: list[str] = []
    for reference in references:
        product_id = _resolve_product_reference(reference, recent_ids, str(current_product_id) if current_product_id else None)
        if product_id and _product_exists(conn, product_id):
            resolved.append(product_id)
    if not references and current_product_id:
        resolved.append(str(current_product_id))
    resolved = list(dict.fromkeys(resolved))
    return resolved, {
        "tool_gate": "bounded_react",
        "reference_count": len(references),
        "recent_product_ids": recent_ids,
        "resolved_product_ids": resolved,
    }


def resolve_cart_item_references(
    conn,
    references: list[ProductReference],
    conversation_state: dict[str, Any] | None,
) -> tuple[list[str], dict[str, Any]]:
    cart = get_cart(conn)
    current_product_id = (conversation_state or {}).get("current_product_id")
    resolved: list[str] = []
    for reference in references:
        if reference.reference_type == "position" and reference.position:
            index = reference.position - 1
            if 0 <= index < len(cart.items):
                resolved.append(cart.items[index].id)
        elif reference.reference_type == "product_id" and reference.product_id:
            resolved.extend(item.id for item in cart.items if item.product_id == reference.product_id)
        elif reference.reference_type in {"current_product", "last_product"} and current_product_id:
            resolved.extend(item.id for item in cart.items if item.product_id == current_product_id)
    resolved = list(dict.fromkeys(resolved))
    return resolved, {
        "tool_gate": "bounded_react",
        "reference_count": len(references),
        "cart_item_count": len(cart.items),
        "resolved_cart_item_ids": resolved,
    }


def _resolve_product_reference(
    reference: ProductReference,
    recent_ids: list[str],
    current_product_id: str | None,
) -> str | None:
    if reference.reference_type == "product_id":
        return reference.product_id
    if reference.reference_type == "current_product":
        return current_product_id
    if reference.reference_type == "last_product":
        return recent_ids[0] if recent_ids else current_product_id
    if reference.reference_type == "position" and reference.position:
        index = reference.position - 1
        if 0 <= index < len(recent_ids):
            return recent_ids[index]
    return None


def _guard_tool(intent_type: str, tool_name: str) -> BoundedToolResult | None:
    allowed = ALLOWED_TOOLS_BY_INTENT.get(intent_type, set())
    if tool_name in allowed:
        return None
    return BoundedToolResult(
        tool_name=tool_name,
        status="guard_blocked",
        response_text="这个操作暂时不能这样执行。",
        diagnostics={"intent_type": intent_type, "blocked_tool": tool_name, "allowed_tools": sorted(allowed)},
    )


def _needs_reference(tool_name: str, response_text: str, diagnostics: dict[str, Any]) -> BoundedToolResult:
    return BoundedToolResult(
        tool_name=tool_name,
        status="needs_reference",
        response_text=response_text,
        diagnostics={**diagnostics, "status": "needs_reference"},
    )


def _not_found(tool_name: str, diagnostics: dict[str, Any]) -> BoundedToolResult:
    return BoundedToolResult(
        tool_name=tool_name,
        status="not_found",
        response_text="没有找到对应商品。",
        diagnostics={**diagnostics, "status": "not_found"},
    )


def _recent_product_ids(conversation_state: dict[str, Any]) -> list[str]:
    raw = conversation_state.get("last_recommended_product_ids") or []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = []
    product_ids = [str(item) for item in raw if item]
    current_product_id = conversation_state.get("current_product_id")
    if current_product_id:
        product_ids = [str(current_product_id), *[item for item in product_ids if item != str(current_product_id)]]
    return list(dict.fromkeys(product_ids))


def _valid_product_ids(conn, product_ids: list[str]) -> list[str]:
    return [product_id for product_id in product_ids if _product_exists(conn, product_id)]


def _product_exists(conn, product_id: str | None) -> bool:
    if not product_id:
        return False
    return conn.execute("SELECT id FROM products WHERE id = ?", (product_id,)).fetchone() is not None


def _fetch_product_snapshots(conn, product_ids: list[str]) -> list[ProductSnapshot]:
    snapshots: list[ProductSnapshot] = []
    for product_id in product_ids:
        row = conn.execute(
            """
            SELECT p.id, p.title, p.brand, p.category, p.subcategory, p.price, p.rating,
                   p.marketing_description,
                   COALESCE(SUM(s.stock), 0) AS stock,
                   GROUP_CONCAT(s.sku_name, ' / ') AS sku_summary
            FROM products p
            LEFT JOIN product_skus s ON s.product_id = p.id
            WHERE p.id = ?
            GROUP BY p.id
            """,
            (product_id,),
        ).fetchone()
        if row:
            snapshots.append(
                ProductSnapshot(
                    id=str(row["id"]),
                    title=str(row["title"]),
                    brand=str(row["brand"]),
                    category=str(row["category"]),
                    subcategory=str(row["subcategory"]),
                    price=float(row["price"]),
                    rating=float(row["rating"]),
                    stock=int(row["stock"] or 0),
                    sku_summary=str(row["sku_summary"]) if row["sku_summary"] else None,
                    marketing_description=str(row["marketing_description"] or ""),
                )
            )
    return snapshots


def _fetch_product_cards(conn, product_ids: list[str]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for product_id in product_ids:
        row = conn.execute(
            """
            SELECT p.id, p.title, p.brand, p.category, p.subcategory, p.price, p.rating, p.image_path,
                   p.marketing_description,
                   COALESCE(rc.review_count, 0) AS review_count,
                   COALESCE(sc.sku_count, 0) AS sku_count,
                   COALESCE(fc.faq_count, 0) AS faq_count,
                   COALESCE(ss.stock, 0) AS stock,
                   ss.sku_summary AS sku_summary
            FROM products p
            LEFT JOIN (SELECT product_id, COUNT(*) AS review_count FROM product_reviews GROUP BY product_id) rc ON rc.product_id = p.id
            LEFT JOIN (SELECT product_id, COUNT(*) AS sku_count FROM product_skus GROUP BY product_id) sc ON sc.product_id = p.id
            LEFT JOIN (SELECT product_id, COUNT(*) AS faq_count FROM product_faqs GROUP BY product_id) fc ON fc.product_id = p.id
            LEFT JOIN (SELECT product_id, SUM(stock) AS stock, GROUP_CONCAT(sku_name, ' / ') AS sku_summary FROM product_skus GROUP BY product_id) ss ON ss.product_id = p.id
            WHERE p.id = ?
            """,
            (product_id,),
        ).fetchone()
        if row:
            cards.append(row_to_product_card(row).model_dump(mode="json"))
    return cards


def _add_product_to_cart(conn, product_id: str, quantity: int) -> None:
    sku = first_sku(conn, product_id)
    sku_id = sku["id"] if sku else None
    current = conn.execute(
        "SELECT id, quantity FROM cart_items WHERE product_id = ? AND COALESCE(sku_id, '') = COALESCE(?, '')",
        (product_id, sku_id),
    ).fetchone()
    if current:
        conn.execute(
            "UPDATE cart_items SET quantity = ?, selected = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (int(current["quantity"]) + quantity, current["id"]),
        )
        return
    conn.execute(
        "INSERT INTO cart_items(id, product_id, sku_id, quantity, selected) VALUES (?, ?, ?, ?, 1)",
        (f"cart_{uuid.uuid4().hex[:10]}", product_id, sku_id, quantity),
    )


def _cart_item_titles(conn, item_ids: list[str]) -> list[str]:
    titles: list[str] = []
    for item_id in item_ids:
        row = conn.execute(
            """
            SELECT p.title
            FROM cart_items c
            JOIN products p ON p.id = c.product_id
            WHERE c.id = ?
            """,
            (item_id,),
        ).fetchone()
        if row:
            titles.append(str(row["title"]))
    return titles


def _cart_payload(conn) -> dict[str, Any]:
    return get_cart(conn).model_dump(mode="json")
