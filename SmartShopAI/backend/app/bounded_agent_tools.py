from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from .catalog import first_sku, get_cart, row_to_product_card
from .llm_client import LLMGenerationError, _env_value, _extract_content, _extract_json_object, llm_model_name
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
    comparison: dict[str, Any] | None = None
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

    priority_dimensions = set(parsed_turn.compare_dimensions or [])
    dimensions = priority_dimensions or {"price", "rating", "feature"}
    comparison = _build_compare_payload(snapshots, dimensions, priority_dimensions)
    compare_writer = "rule"
    try:
        comparison = _write_compare_payload_with_llm(parsed_turn.raw_message, snapshots, comparison, priority_dimensions)
        compare_writer = "llm"
    except LLMGenerationError:
        compare_writer = "rule_fallback"
    text = _build_compare_response(comparison)
    product_cards = _fetch_product_cards(conn, [item.id for item in snapshots])
    return BoundedToolResult(
        tool_name=tool_name,
        status="ok",
        response_text=text,
        product_ids=[item.id for item in snapshots],
        products=product_cards,
        current_product_id=snapshots[0].id,
        comparison=comparison,
        diagnostics={**diagnostics, "intent_type": parsed_turn.intent_type, "status": "ok", "compare_writer": compare_writer},
    )


def _build_compare_payload(
    products: list[ProductSnapshot],
    dimensions: set[str],
    priority_dimensions: set[str],
) -> dict[str, Any]:
    columns = _comparison_columns(products)
    rows = _comparison_rows(products, dimensions)
    sections = [
        {
            "title": f"选{column['label']}如果",
            "product_id": column["product_id"],
            "bullets": _product_advantages(product, products, priority_dimensions),
        }
        for column, product in zip(columns, products)
    ]
    recommendation = _compare_recommendation(products, priority_dimensions)
    return {
        "title": f"{' vs '.join(column['label'] for column in columns)} 对比",
        "summary": _compare_summary(products, columns, rows, priority_dimensions),
        "columns": columns,
        "rows": rows,
        "sections": sections,
        "recommendation": recommendation,
        "footnote": "仅基于当前商品库里的价格、评分、库存和商品说明生成。",
    }


def _build_compare_response(comparison: dict[str, Any]) -> str:
    return f"{comparison['title']}\n{comparison['summary']}\n{comparison['recommendation']}"


def _comparison_columns(products: list[ProductSnapshot]) -> list[dict[str, str]]:
    brands = [item.brand.strip() or _compact_title(item.title, 12) for item in products]
    if len(set(brands)) < len(brands):
        brands = [_compact_title(item.title, 12) for item in products]
    return [
        {"label": brand, "product_id": product.id}
        for brand, product in zip(brands, products)
    ]


def _comparison_rows(products: list[ProductSnapshot], dimensions: set[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if _has_distinct_values(products, lambda item: f"{item.category}/{item.subcategory}"):
        rows.append({"dimension": "品类", "values": [f"{item.category}/{item.subcategory}" for item in products]})

    price_needed = "price" in dimensions or _has_distinct_values(products, lambda item: item.price)
    if price_needed:
        min_price = min(item.price for item in products)
        values = []
        highlight_index = None
        for item in products:
            value = f"¥{item.price:.0f}"
            if item.price == min_price and _has_distinct_values(products, lambda product: product.price):
                value += "（更低）"
                highlight_index = products.index(item)
            values.append(value)
        rows.append({"dimension": "价格", "values": values, "highlight_index": highlight_index})

    if _has_distinct_values(products, lambda item: item.rating):
        max_rating = max(item.rating for item in products)
        values = []
        highlight_index = None
        for item in products:
            value = f"{item.rating:.1f}"
            if item.rating == max_rating:
                value += "（更高）"
                highlight_index = products.index(item)
            values.append(value)
        rows.append({"dimension": "评分", "values": values, "highlight_index": highlight_index})

    if "stock" in dimensions and _has_distinct_values(products, lambda item: item.stock):
        max_stock = max(item.stock for item in products)
        values = []
        highlight_index = None
        for item in products:
            value = f"约 {item.stock} 件"
            if item.stock == max_stock:
                value += "（更多）"
                highlight_index = products.index(item)
            values.append(value)
        rows.append({"dimension": "库存", "values": values, "highlight_index": highlight_index})

    marketing_values = [_compact_marketing(item.marketing_description, max_length=18) for item in products]
    if any(marketing_values) and len(set(marketing_values)) > 1:
        rows.append({"dimension": "核心卖点", "values": [value or "暂无明确说明" for value in marketing_values]})

    if not rows:
        rows.append({"dimension": "差异", "values": ["当前核心字段差异不明显" for _ in products]})
    return rows


def _compare_summary(
    products: list[ProductSnapshot],
    columns: list[dict[str, str]],
    rows: list[dict[str, Any]],
    priority_dimensions: set[str],
) -> str:
    dimensions = "、".join(row["dimension"] for row in rows if row["dimension"] not in {"核心卖点"})
    if not dimensions:
        dimensions = "商品说明"
    recommended = _recommended_product(products, priority_dimensions)
    recommended_label = next(
        (column["label"] for column in columns if column["product_id"] == recommended.id),
        recommended.brand or recommended.title,
    )
    return f"这几款的共同点不用重复看，核心差异主要在{dimensions}。简单说：{recommended_label} 目前更值得优先看。"


def _product_advantages(product: ProductSnapshot, products: list[ProductSnapshot], priority_dimensions: set[str]) -> list[str]:
    advantages: list[str] = []
    prices = [item.price for item in products]
    ratings = [item.rating for item in products]
    stocks = [item.stock for item in products]

    if len(set(prices)) > 1 and product.price == min(prices):
        gap = max(prices) - product.price
        advantages.append(f"价格更低，比最高价低约 ¥{gap:.0f}。")
    if len(set(ratings)) > 1 and product.rating == max(ratings):
        advantages.append(f"评分更高，当前评分 {product.rating:.1f}。")
    if "stock" in priority_dimensions and len(set(stocks)) > 1 and product.stock == max(stocks):
        advantages.append(f"库存更多，当前约 {product.stock} 件。")

    marketing = _compact_marketing(product.marketing_description)
    if marketing:
        distinct_marketing = _has_distinct_values(products, lambda item: _compact_marketing(item.marketing_description))
        if distinct_marketing:
            advantages.append(f"商品说明提到：{marketing}")
    if not advantages:
        advantages.append("当前结构化数据里没有明显领先项，可按品牌、外观或规格偏好作为备选。")
    return advantages[:3]


def _compare_recommendation(products: list[ProductSnapshot], priority_dimensions: set[str]) -> str:
    recommended = _recommended_product(products, priority_dimensions)
    reasons = []
    if recommended.price == min(item.price for item in products) and _has_distinct_values(products, lambda item: item.price):
        reasons.append("价格更低")
    if recommended.rating == max(item.rating for item in products) and _has_distinct_values(products, lambda item: item.rating):
        reasons.append("评分更高")
    if "stock" in priority_dimensions and recommended.stock == max(item.stock for item in products) and _has_distinct_values(products, lambda item: item.stock):
        reasons.append("库存更多")
    reason_text = "、".join(reasons) if reasons else "核心字段更均衡"
    return f"建议：如果没有更明确的品牌或规格偏好，优先看 {recommended.title}，因为它在{reason_text}上更占优。"


def _recommended_product(products: list[ProductSnapshot], priority_dimensions: set[str]) -> ProductSnapshot:
    if "price" in priority_dimensions:
        return min(products, key=lambda item: item.price)
    if "rating" in priority_dimensions:
        return max(products, key=lambda item: item.rating)
    if "stock" in priority_dimensions:
        return max(products, key=lambda item: item.stock)
    return max(products, key=lambda item: _recommendation_score(item, products))


def _recommendation_score(product: ProductSnapshot, products: list[ProductSnapshot]) -> tuple[int, float, int]:
    price_score = 1 if product.price == min(item.price for item in products) else 0
    rating_score = 1 if product.rating == max(item.rating for item in products) else 0
    return (price_score + rating_score, product.rating, -int(product.price))


def _write_compare_payload_with_llm(
    user_message: str,
    products: list[ProductSnapshot],
    fallback: dict[str, Any],
    priority_dimensions: set[str],
) -> dict[str, Any]:
    api_key = _env_value("POE_API_KEY")
    if not api_key:
        raise LLMGenerationError("POE_API_KEY is not configured")
    base_url = (_env_value("POE_BASE_URL", "https://api.poe.com/v1") or "https://api.poe.com/v1").rstrip("/")
    timeout = _compare_writer_timeout_seconds()
    evidence = {
        "user_message": user_message,
        "rule_fallback": fallback,
        "priority_dimensions": sorted(priority_dimensions),
        "strict_rules": [
            "只能基于 products 和 rule_fallback 输出，不得新增商品事实",
            "库存默认只表示购买状态，不能作为推荐理由；除非 priority_dimensions 包含 stock",
            "表格单元格要短，避免超过手机屏幕",
            "不要把两款共同点重复列成差异",
        ],
        "products": [_comparison_evidence(product) for product in products],
        "output_schema": {
            "summary": "不超过70字",
            "rows": [{"dimension": "维度名", "values": ["每个商品一个短值"], "highlight_index": 0}],
            "sections": [{"product_id": "商品id", "title": "选X如果", "bullets": ["每条不超过24字"]}],
            "recommendation": "不超过90字，允许按不同偏好给建议",
        },
    }
    system_prompt = (
        "你是电商商品对比文案生成器。你只能压缩和改写输入事实，不能编造价格、评分、库存、功能、品牌或评价。"
        "输出必须是 JSON object。rows 最多 5 行；每个 values 长度必须等于商品数量；sections 每个商品最多 3 条。"
        "如果证据不足，就写“当前数据不足”。不要输出 Markdown。"
    )
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=4.0)) as client:
            response = client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": llm_model_name(),
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(evidence, ensure_ascii=False)},
                    ],
                    "temperature": 0.45,
                    "max_tokens": 900,
                },
            )
            response.raise_for_status()
            data = json.loads(_extract_json_object(_extract_content(response.json())))
            return _sanitize_llm_comparison_payload(data, fallback, products, priority_dimensions)
    except LLMGenerationError:
        raise
    except (json.JSONDecodeError, httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise LLMGenerationError("comparison writer failed") from exc


def _comparison_evidence(product: ProductSnapshot) -> dict[str, Any]:
    return {
        "id": product.id,
        "title": product.title,
        "brand": product.brand,
        "category": product.category,
        "subcategory": product.subcategory,
        "price": product.price,
        "rating": product.rating,
        "purchase_status": "有货" if product.stock > 0 else "无货",
        "sku_summary": product.sku_summary,
        "marketing_description": product.marketing_description[:260],
    }


def _sanitize_llm_comparison_payload(
    data: dict[str, Any],
    fallback: dict[str, Any],
    products: list[ProductSnapshot],
    priority_dimensions: set[str],
) -> dict[str, Any]:
    product_ids = [product.id for product in products]
    column_count = len(product_ids)
    rows = _sanitize_llm_rows(data.get("rows"), fallback["rows"], column_count, priority_dimensions)
    sections = _sanitize_llm_sections(data.get("sections"), fallback["sections"], product_ids, priority_dimensions)
    recommendation = _clean_compare_text(str(data.get("recommendation") or ""), 100)
    if not recommendation or ("stock" not in priority_dimensions and "库存" in recommendation):
        recommendation = fallback["recommendation"]
    summary = _clean_compare_text(str(data.get("summary") or ""), 80) or fallback["summary"]
    if "stock" not in priority_dimensions and "库存" in summary:
        summary = fallback["summary"]
    return {
        **fallback,
        "summary": summary,
        "rows": rows,
        "sections": sections,
        "recommendation": recommendation,
    }


def _sanitize_llm_rows(
    raw_rows: Any,
    fallback_rows: list[dict[str, Any]],
    column_count: int,
    priority_dimensions: set[str],
) -> list[dict[str, Any]]:
    if not isinstance(raw_rows, list):
        return fallback_rows
    rows: list[dict[str, Any]] = []
    for row in raw_rows[:6]:
        if not isinstance(row, dict):
            continue
        dimension = _clean_compare_text(str(row.get("dimension") or ""), 8)
        if not dimension:
            continue
        if "stock" not in priority_dimensions and any(term in dimension for term in ("库存", "有货", "现货")):
            continue
        raw_values = row.get("values")
        if not isinstance(raw_values, list) or len(raw_values) < column_count:
            continue
        values = [_clean_compare_text(str(value), 18) or "当前数据不足" for value in raw_values[:column_count]]
        highlight_index = row.get("highlight_index")
        if not isinstance(highlight_index, int) or not 0 <= highlight_index < column_count:
            highlight_index = None
        rows.append({"dimension": dimension, "values": values, "highlight_index": highlight_index})
    return rows or fallback_rows


def _sanitize_llm_sections(
    raw_sections: Any,
    fallback_sections: list[dict[str, Any]],
    product_ids: list[str],
    priority_dimensions: set[str],
) -> list[dict[str, Any]]:
    if not isinstance(raw_sections, list):
        return fallback_sections
    by_product: dict[str, dict[str, Any]] = {}
    for section in raw_sections:
        if not isinstance(section, dict):
            continue
        product_id = str(section.get("product_id") or "")
        if product_id not in product_ids:
            continue
        bullets_raw = section.get("bullets")
        if not isinstance(bullets_raw, list):
            continue
        bullets = []
        for bullet in bullets_raw[:3]:
            text = _clean_compare_text(str(bullet), 26)
            if text and ("stock" in priority_dimensions or "库存" not in text):
                bullets.append(text)
        if bullets:
            by_product[product_id] = {
                "title": _clean_compare_text(str(section.get("title") or ""), 12) or f"选这款如果",
                "product_id": product_id,
                "bullets": bullets,
            }
    ordered = [by_product[product_id] for product_id in product_ids if product_id in by_product]
    return ordered if len(ordered) == len(product_ids) else fallback_sections


def _clean_compare_text(text: str, max_length: int) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip(" ，,。；;")
    forbidden = ("RRF", "BM25", "retrieval", "score", "dense", "keyword", "SQL")
    if not cleaned or any(token.lower() in cleaned.lower() for token in forbidden):
        return ""
    return cleaned[:max_length].rstrip("，,。；; ")


def _compare_writer_timeout_seconds() -> float:
    raw = _env_value("COMPARE_LLM_TIMEOUT_SECONDS", "8")
    try:
        return min(max(float(raw or "8"), 3.0), 12.0)
    except ValueError:
        return 8.0


def _has_distinct_values(products: list[ProductSnapshot], getter) -> bool:
    return len({getter(item) for item in products}) > 1


def _compact_title(title: str, max_length: int = 24) -> str:
    return title if len(title) <= max_length else title[: max_length - 1].rstrip() + "…"


def _compact_marketing(text: str, max_length: int = 48) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return ""
    sentence = re.split(r"[。！？；]", cleaned, maxsplit=1)[0].strip()
    if not sentence:
        return ""
    return sentence if len(sentence) <= max_length else sentence[: max_length - 1].rstrip() + "…"


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
    skus = _fetch_available_skus(conn, product[0].id)
    selected_sku = _resolve_sku_from_message(parsed_turn.raw_message, skus)
    if len(skus) > 1 and selected_sku is None:
        return BoundedToolResult(
            tool_name=tool_name,
            status="needs_reference",
            response_text=_sku_selection_prompt(product[0].title, skus),
            product_ids=[product[0].id],
            actions=_sku_selection_actions(skus),
            current_product_id=product[0].id,
            diagnostics={**diagnostics, "intent_type": parsed_turn.intent_type, "status": "needs_sku"},
        )
    _add_product_to_cart(conn, product[0].id, quantity, selected_sku["id"] if selected_sku else None)
    cart = get_cart(conn)
    sku_text = f"（{selected_sku['sku_name']}）" if selected_sku else ""
    return BoundedToolResult(
        tool_name=tool_name,
        status="ok",
        response_text=f"已把 {product[0].title}{sku_text} 加入购物车，数量 {quantity}。购物车详情如下。",
        product_ids=[product[0].id],
        actions=[{"type": "open_cart", "label": "打开购物车", "product_id": None}],
        current_product_id=product[0].id,
        cart=cart.model_dump(mode="json"),
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
    quantity_delta = _cart_quantity_delta(parsed_turn.raw_message)
    if not parsed_turn.quantity and quantity_delta is None:
        return _needs_reference(tool_name, "你想把数量改成几件，或者增加/减少几件？", {"reason": "missing_quantity"})
    item_ids, diagnostics = resolve_cart_item_references(conn, parsed_turn.references, conversation_state)
    if not item_ids:
        return _needs_reference(tool_name, "你想修改购物车里的哪一项？", diagnostics)
    titles = _cart_item_titles(conn, item_ids)
    changed: list[tuple[int, str]] = []
    removed: list[str] = []
    if quantity_delta is not None:
        rows = conn.execute(
            f"SELECT id, quantity FROM cart_items WHERE id IN ({','.join('?' for _ in item_ids)})",
            item_ids,
        ).fetchall()
        for row in rows:
            next_quantity = int(row["quantity"]) + quantity_delta
            if next_quantity <= 0:
                removed.append(row["id"])
            else:
                changed.append((next_quantity, row["id"]))
    else:
        changed = [(parsed_turn.quantity or 1, item_id) for item_id in item_ids]
    stock_problem = _cart_quantity_stock_problem(conn, changed)
    if stock_problem:
        return BoundedToolResult(
            tool_name=tool_name,
            status="guard_blocked",
            response_text=stock_problem,
            cart=_cart_payload(conn),
            diagnostics={**diagnostics, "intent_type": parsed_turn.intent_type, "status": "stock_blocked"},
        )
    if changed:
        conn.executemany(
            "UPDATE cart_items SET quantity = ?, selected = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            changed,
        )
    if removed:
        conn.executemany("DELETE FROM cart_items WHERE id = ?", [(item_id,) for item_id in removed])
    title_text = "、".join(titles) if titles else f"{len(item_ids)} 项商品"
    action_text = (
        f"数量已{'增加' if quantity_delta and quantity_delta > 0 else '减少'} {abs(quantity_delta)} 件"
        if quantity_delta is not None
        else f"数量改为 {parsed_turn.quantity}"
    )
    return BoundedToolResult(
        tool_name=tool_name,
        status="ok",
        response_text=f"已把 {title_text} 的{action_text}。",
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


def _cart_quantity_delta(raw: str) -> int | None:
    if any(term in raw for term in ["增加", "加一", "再加", "多加", "加到购物车"]):
        return _quantity_amount(raw) or 1
    if any(term in raw for term in ["减少", "减一", "少一", "少买"]):
        return -(_quantity_amount(raw) or 1)
    return None


def _quantity_amount(raw: str) -> int | None:
    match = re.search(r"(\d+)\s*(?:件|个|份)?", raw)
    if match:
        return max(int(match.group(1)), 1)
    if "一" in raw and any(term in raw for term in ["件", "个", "份"]):
        return 1
    if "两" in raw and any(term in raw for term in ["件", "个", "份"]):
        return 2
    return None


def _cart_quantity_stock_problem(conn, changes: list[tuple[int, str]]) -> str | None:
    for quantity, item_id in changes:
        row = conn.execute(
            """
            SELECT c.quantity, p.title, COALESCE(s.stock, 999999) AS stock
            FROM cart_items c
            JOIN products p ON p.id = c.product_id
            LEFT JOIN product_skus s ON s.id = c.sku_id
            WHERE c.id = ?
            """,
            (item_id,),
        ).fetchone()
        if row and int(row["stock"]) < quantity:
            return f"{row['title']} 库存不足，当前最多可买 {int(row['stock'])} 件。"
    return None


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
    if not references and len(cart.items) == 1:
        return [cart.items[0].id], {
            "tool_gate": "bounded_react",
            "reference_count": 0,
            "cart_item_count": len(cart.items),
            "resolved_cart_item_ids": [cart.items[0].id],
            "resolution": "single_cart_item_default",
        }
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


def _fetch_available_skus(conn, product_id: str) -> list[dict[str, Any]]:
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
            "properties": _parse_sku_properties(row["properties_json"]),
            "price": float(row["price"] or 0),
            "stock": int(row["stock"] or 0),
        }
        for row in rows
    ]


def _resolve_sku_from_message(message: str, skus: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not skus:
        return None
    normalized = message.replace(" ", "")
    distinct_keys = _sku_distinct_property_keys(skus)
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


def _sku_selection_prompt(product_title: str, skus: list[dict[str, Any]]) -> str:
    all_labels = _unique_sku_option_labels(skus)
    shown_labels = all_labels[:6]
    sku_text = "、".join(shown_labels)
    suffix = " 等" if len(all_labels) > len(shown_labels) else ""
    dimension = _sku_dimension_name(skus)
    if len(all_labels) > SKU_ACTION_OPTION_LIMIT:
        example = shown_labels[0] if shown_labels else "具体规格"
        return f"这款 {product_title} 有多个{dimension}可选：{sku_text}{suffix}。选项较多，请直接输入要加入购物车的{dimension}，例如“{example}”。"
    return f"这款 {product_title} 需要先确认{dimension}。可选{dimension}有：{sku_text}，你想加入哪一个？"


def _sku_selection_actions(skus: list[dict[str, Any]]) -> list[dict[str, Any]]:
    labels = _unique_sku_option_labels(skus)
    if len(labels) > SKU_ACTION_OPTION_LIMIT:
        return []
    return [
        {"type": "search_more", "label": f"选择{label}", "product_id": None}
        for label in labels
    ]


SKU_ACTION_OPTION_LIMIT = 4
SKU_DIMENSION_PRIORITY = ("尺码", "型号", "容量", "内存", "存储", "颜色", "色号", "版本", "配置", "套餐", "规格", "款式", "款型")


def _unique_sku_option_labels(skus: list[dict[str, Any]], limit: int | None = None) -> list[str]:
    labels: list[str] = []
    for sku in skus:
        label = _compact_sku_label(sku, skus)
        if label and label not in labels:
            labels.append(label)
        if limit is not None and len(labels) >= limit:
            break
    return labels


def _compact_sku_label(sku: dict[str, Any], all_skus: list[dict[str, Any]]) -> str:
    properties = sku.get("properties") or {}
    distinct_keys = _sku_distinct_property_keys(all_skus)
    values = [str(properties.get(key) or "").strip() for key in distinct_keys[:2]]
    label = " / ".join(value for value in values if value)
    if label:
        return label
    text = str(sku.get("sku_name") or "默认规格")
    size_match = re.search(r"尺码\s*[:：]?\s*([^/；，,\s]+)", text)
    if size_match:
        return size_match.group(1)
    return text.strip()[:18]


def _sku_dimension_name(skus: list[dict[str, Any]]) -> str:
    keys = _sku_distinct_property_keys(skus)
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


def _sku_distinct_property_keys(skus: list[dict[str, Any]]) -> list[str]:
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


def _parse_sku_properties(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _add_product_to_cart(conn, product_id: str, quantity: int, sku_id: str | None = None) -> None:
    sku = None
    if sku_id:
        sku = first_sku(conn, product_id, sku_id)
    if sku is None:
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
