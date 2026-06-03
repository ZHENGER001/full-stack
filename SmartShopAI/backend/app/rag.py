from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .embedding_client import get_embedding_client
from .schemas import ProductCard

LOGGER = logging.getLogger(__name__)


@dataclass
class RetrievedContext:
    chunk_id: str
    product_id: str
    text: str
    source_type: str
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["raw_text"] = self.text
        return data


@dataclass
class RetrievalResult:
    products: list[ProductCard]
    contexts: list[RetrievedContext]
    candidate_product_ids: list[str]
    strategy: str = "hybrid"
    fallback_used: bool = False
    reason: str = ""

    def context_dicts(self) -> list[dict[str, Any]]:
        return [context.to_dict() for context in self.contexts]


def tokenize(text: str) -> set[str]:
    return set(tokenize_list(text))


def tokenize_list(text: str) -> list[str]:
    lower = text.lower()
    ascii_tokens = re.findall(r"[a-z0-9]+", lower)
    cjk_tokens = [
        lower[i : i + 2]
        for i in range(max(len(lower) - 1, 0))
        if "\u4e00" <= lower[i] <= "\u9fff"
    ]
    return ascii_tokens + cjk_tokens


def price_range(price: float) -> str:
    if price <= 100:
        return "100元以内"
    if price <= 500:
        return "100-500元"
    if price <= 1000:
        return "500-1000元"
    if price <= 3000:
        return "1000-3000元"
    if price <= 6000:
        return "3000-6000元"
    return "6000元以上"


FEATURE_KEYWORDS = {
    "降噪": ["降噪", "通话清晰", "耳机"],
    "续航": ["续航", "电池", "持久"],
    "快充": ["快充", "充电"],
    "拍照": ["拍照", "影像", "摄像", "夜景"],
    "护眼": ["护眼", "低蓝光"],
    "轻薄": ["轻薄", "便携"],
    "高刷": ["高刷", "刷新率"],
    "控油": ["控油", "油皮", "清爽"],
    "防滑": ["防滑", "稳定"],
    "防水": ["防水", "防雨"],
}

SCENARIO_KEYWORDS = {
    "学生党": ["学生党", "学生", "上学"],
    "办公": ["办公", "会议", "工作", "通勤"],
    "游戏": ["游戏", "电竞"],
    "送礼": ["送礼", "礼物", "女朋友", "男朋友"],
    "运动": ["运动", "跑步", "训练"],
    "旅行": ["旅行", "出差", "户外", "徒步"],
    "家居": ["家居", "卧室", "客厅"],
    "宠物家庭": ["养猫", "养狗", "宠物"],
}


def extract_features(text: str) -> list[str]:
    return [feature for feature, words in FEATURE_KEYWORDS.items() if any(word in text for word in words)]


def extract_scenarios(text: str) -> list[str]:
    return [scenario for scenario, words in SCENARIO_KEYWORDS.items() if any(word in text for word in words)]


def build_product_chunks(product: dict[str, Any]) -> list[dict[str, Any]]:
    title = str(product.get("title", ""))
    brand = str(product.get("brand", ""))
    category = str(product.get("category", ""))
    subcategory = str(product.get("subcategory", product.get("sub_category", "")))
    price = float(product.get("price", product.get("base_price", 0)) or 0)
    rating = float(product.get("rating", 4.5) or 4.5)
    skus = product.get("skus", []) or []
    faqs = product.get("official_faq", []) or []
    reviews = product.get("user_reviews", []) or []
    marketing = str(product.get("marketing_description", ""))

    sku_text = "；".join(
        _sku_text(sku)
        for sku in skus
    )
    faq_text = "；".join(
        f"问：{faq.get('question', '')} 答：{faq.get('answer', '')}" for faq in faqs[:6]
    )
    review_text = "；".join(
        f"{review.get('nickname', '用户')}：{review.get('content', '')}" for review in reviews[:6]
    )
    full_text = " ".join([title, brand, category, subcategory, marketing, sku_text, faq_text, review_text])
    features = extract_features(full_text)
    scenarios = extract_scenarios(full_text)
    metadata = {
        "product_id": product.get("id", product.get("product_id")),
        "title": title,
        "brand": brand,
        "category": category,
        "subcategory": subcategory,
        "price": price,
        "price_range": price_range(price),
        "rating": rating,
        "features": features,
        "scenarios": scenarios,
    }
    chunks = [
        {
            "id": f"{metadata['product_id']}:basic_info",
            "product_id": metadata["product_id"],
            "chunk_type": "basic_info",
            "content": f"{title} {brand} {category} {subcategory} 价格 {price} 评分 {rating} 特性 {' '.join(features)} 场景 {' '.join(scenarios)}",
            "metadata_json": json.dumps({**metadata, "chunk_type": "basic_info"}, ensure_ascii=False),
        },
        {
            "id": f"{metadata['product_id']}:marketing",
            "product_id": metadata["product_id"],
            "chunk_type": "marketing",
            "content": marketing,
            "metadata_json": json.dumps({**metadata, "chunk_type": "marketing"}, ensure_ascii=False),
        },
    ]
    if sku_text:
        chunks.append(
            {
                "id": f"{metadata['product_id']}:sku",
                "product_id": metadata["product_id"],
                "chunk_type": "sku",
                "content": sku_text,
                "metadata_json": json.dumps({**metadata, "chunk_type": "sku"}, ensure_ascii=False),
            }
        )
    if faq_text:
        chunks.append(
            {
                "id": f"{metadata['product_id']}:faq",
                "product_id": metadata["product_id"],
                "chunk_type": "faq",
                "content": faq_text,
                "metadata_json": json.dumps({**metadata, "chunk_type": "faq"}, ensure_ascii=False),
            }
        )
    if review_text:
        chunks.append(
            {
                "id": f"{metadata['product_id']}:reviews",
                "product_id": metadata["product_id"],
                "chunk_type": "reviews",
                "content": review_text,
                "metadata_json": json.dumps({**metadata, "chunk_type": "reviews"}, ensure_ascii=False),
            }
        )
    return [chunk for chunk in chunks if chunk["content"] and chunk["product_id"]]


def hybrid_retrieve(conn, query: str, top_k: int = 10) -> RetrievalResult:
    expanded_query = expand_query(query)
    rows = load_product_search_rows(conn)
    rows_by_id = {str(_row_get(row, "id")): row for row in rows}

    dense_used = should_use_dense_search(expanded_query)
    if dense_used:
        dense_ids, dense_contexts, dense_available = dense_vector_rank(expanded_query, limit=max(top_k * 2, 10))
    else:
        dense_ids, dense_contexts, dense_available = [], [], True
    keyword_ids = [product_id for product_id, _, _ in keyword_rank(rows, expanded_query, limit=max(top_k * 2, 10))]
    bm25_ids = bm25_rank(rows, expanded_query, limit=max(top_k * 2, 10))

    rankings = [ranking for ranking in [dense_ids, keyword_ids, bm25_ids] if ranking]
    fused_ids = rrf_fuse(rankings, top_k=top_k)
    fallback_used = False
    reason = (
        "RRF fused dense, keyword, and BM25 retrieval."
        if dense_used
        else "Fast path fused keyword and BM25 retrieval; dense search skipped for explicit query."
    )

    if not fused_ids:
        fallback_used = True
        reason = "Hybrid retrieval produced no match; falling back to rating and budget rules."
        max_price = extract_max_price(expanded_query)
        strong_terms = fallback_required_terms(expanded_query)
        fallback_rows = []
        if strong_terms:
            fallback_rows = [
                row for row in rows
                if any(term in f"{_row_get(row, 'title', '')} {_row_get(row, 'subcategory', '')}".lower() for term in strong_terms)
            ]
            fallback_rows.sort(
                key=lambda row: (
                    0 if max_price is None or float(_row_get(row, "price", 0)) <= max_price else 1,
                    -float(_row_get(row, "rating", 0)),
                    float(_row_get(row, "price", 0)),
                )
            )
        if not fallback_rows:
            fallback_rows = [
                row for row in rows
                if max_price is None or float(_row_get(row, "price", 0)) <= max_price
            ]
            fallback_rows.sort(key=lambda row: (-float(_row_get(row, "rating", 0)), float(_row_get(row, "price", 0))))
        fused_ids = [str(_row_get(row, "id")) for row in fallback_rows[:top_k]]
    elif dense_used and not dense_available:
        fallback_used = True
        reason = "Milvus or embedding unavailable; fused keyword and BM25 results with local rules."

    product_cards = [
        row_to_product_card_for_agent(rows_by_id[product_id], build_reason(rows_by_id[product_id], expanded_query))
        for product_id in fused_ids
        if product_id in rows_by_id
    ]
    contexts = dense_contexts + load_contexts_for_products(conn, fused_ids, limit_per_product=3)
    return RetrievalResult(
        products=product_cards[:top_k],
        contexts=dedupe_contexts(contexts),
        candidate_product_ids=fused_ids,
        strategy="hybrid",
        fallback_used=fallback_used,
        reason=reason,
    )


def search_products_for_agent(conn, query: str, limit: int = 3) -> list[ProductCard]:
    return hybrid_retrieve(conn, query, top_k=limit).products


def should_use_dense_search(query: str) -> bool:
    mode = (os.getenv("DENSE_SEARCH_MODE") or "auto").strip().lower()
    if mode in {"off", "false", "disabled", "keyword"}:
        return False
    if mode in {"on", "true", "dense"}:
        return True

    relational_terms = ["相似", "类似", "替代", "对比", "比较", "更好", "更适合", "兼容", "同类"]
    if any(term in query for term in relational_terms):
        return True

    explicit_terms = [
        "耳机", "手机", "电脑", "笔记本", "平板", "键盘", "鼠标", "充电器",
        "鞋", "衣", "外套", "护肤", "洁面", "零食", "宠物", "猫", "狗",
        "文具", "办公", "旅行", "户外", "家居",
    ]
    if any(term in query for term in explicit_terms) and len(query) <= 40:
        return False
    return True


def load_product_search_rows(conn) -> list[Any]:
    return conn.execute(
        """
        SELECT p.*,
               COALESCE(rc.review_count, 0) AS review_count,
               COALESCE(sc.sku_count, 0) AS sku_count,
               COALESCE(fc.faq_count, 0) AS faq_count,
               COALESCE(ss.stock, 0) AS stock,
               ss.sku_summary AS sku_summary,
               fs.faq_text AS faq_text,
               rs.review_text AS review_text
        FROM products p
        LEFT JOIN (SELECT product_id, COUNT(*) AS review_count, GROUP_CONCAT(content, ' ') AS review_text FROM product_reviews GROUP BY product_id) rc ON rc.product_id = p.id
        LEFT JOIN (SELECT product_id, COUNT(*) AS sku_count FROM product_skus GROUP BY product_id) sc ON sc.product_id = p.id
        LEFT JOIN (SELECT product_id, COUNT(*) AS faq_count FROM product_faqs GROUP BY product_id) fc ON fc.product_id = p.id
        LEFT JOIN (SELECT product_id, SUM(stock) AS stock, GROUP_CONCAT(sku_name, ' / ') AS sku_summary FROM product_skus GROUP BY product_id) ss ON ss.product_id = p.id
        LEFT JOIN (SELECT product_id, GROUP_CONCAT(question || ' ' || answer, ' ') AS faq_text FROM product_faqs GROUP BY product_id) fs ON fs.product_id = p.id
        LEFT JOIN (SELECT product_id, GROUP_CONCAT(content, ' ') AS review_text FROM product_reviews GROUP BY product_id) rs ON rs.product_id = p.id
        GROUP BY p.id
        """
    ).fetchall()


def keyword_rank(rows: list[Any], query: str, limit: int = 20) -> list[tuple[str, float, str]]:
    max_price = extract_max_price(query)
    strong_terms = required_terms(query)
    query_tokens = tokenize(query)
    scored: list[tuple[float, str, Any, str]] = []
    for row in rows:
        if max_price is not None and float(_row_get(row, "price", 0)) > max_price:
            continue
        text = row_search_text(row)
        if strong_terms and not any(term in text for term in strong_terms):
            continue
        tokens = tokenize(text)
        score = len(query_tokens & tokens)
        for phrase in ["油皮", "控油", "洗面奶", "洁面", "蓝牙", "耳机", "外套", "鞋", "休闲", "黑色", "学生党", "办公", "游戏", "旅行", "宠物"]:
            if phrase in query and phrase in text:
                score += 3
        if ("洗面奶" in query or "洁面" in query) and (
            "洁面" in _row_get(row, "subcategory", "") or "洁面" in _row_get(row, "title", "") or "洗面奶" in _row_get(row, "title", "")
        ):
            score += 12
        if ("蓝牙" in query or "耳机" in query) and (
            "耳机" in _row_get(row, "subcategory", "") or "耳机" in _row_get(row, "title", "") or "蓝牙" in text
        ):
            score += 12
        if score > 0:
            reason = build_reason(row, query)
            scored.append((score + float(_row_get(row, "rating", 0)) / 10, str(_row_get(row, "id")), row, reason))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [(product_id, score, reason) for score, product_id, _, reason in scored[:limit]]


def bm25_rank(rows: list[Any], query: str, limit: int = 20) -> list[str]:
    try:
        from rank_bm25 import BM25Okapi  # type: ignore
    except Exception:
        return []
    if not rows:
        return []
    corpus = [tokenize_list(row_search_text(row)) for row in rows]
    try:
        bm25 = BM25Okapi(corpus)
        scores = bm25.get_scores(tokenize_list(query))
    except Exception as exc:
        LOGGER.warning("BM25 failed: %s", exc)
        return []
    ranked = sorted(
        ((float(score), str(_row_get(row, "id"))) for row, score in zip(rows, scores) if score > 0),
        key=lambda item: item[0],
        reverse=True,
    )
    return [product_id for _, product_id in ranked[:limit]]


def dense_vector_rank(query: str, limit: int = 20) -> tuple[list[str], list[RetrievedContext], bool]:
    uri = os.getenv("MILVUS_URI")
    collection = os.getenv("MILVUS_COLLECTION", "smartshop_products")
    token = os.getenv("MILVUS_TOKEN") or None
    if not uri or not collection:
        return [], [], False
    try:
        from pymilvus import MilvusClient  # type: ignore
    except Exception:
        return [], [], False
    embedding_client = get_embedding_client()
    vectors = embedding_client.embed_texts([query])
    if not vectors:
        return [], [], False
    try:
        client = MilvusClient(uri=uri, token=token, timeout=5)
        hits = client.search(
            collection_name=collection,
            data=vectors,
            limit=limit,
            output_fields=[
                "chunk_id",
                "product_id",
                "node_id",
                "parent_id",
                "category",
                "brand",
                "price",
                "price_range",
                "features",
                "scenarios",
                "source_type",
                "raw_text",
            ],
        )
    except Exception as exc:
        LOGGER.warning("Milvus dense search failed: %s", exc)
        return [], [], False
    product_ids: list[str] = []
    contexts: list[RetrievedContext] = []
    for hit in hits[0] if hits else []:
        entity = hit.get("entity", {})
        product_id = str(entity.get("product_id") or "")
        if not product_id:
            continue
        product_ids.append(product_id)
        contexts.append(
            RetrievedContext(
                chunk_id=str(entity.get("chunk_id") or hit.get("id") or product_id),
                product_id=product_id,
                text=str(entity.get("raw_text") or ""),
                source_type=str(entity.get("source_type") or "milvus"),
                score=float(hit.get("distance", 0.0) or 0.0),
                metadata=entity,
            )
        )
    return product_ids, contexts, True


def rrf_fuse(rankings: list[list[str]], top_k: int, k: int = 60) -> list[str]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        seen: set[str] = set()
        for rank, product_id in enumerate(ranking, start=1):
            if not product_id or product_id in seen:
                continue
            seen.add(product_id)
            scores[product_id] = scores.get(product_id, 0.0) + 1.0 / (k + rank)
    return [product_id for product_id, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)[:top_k]]


def load_contexts_for_products(conn, product_ids: list[str], limit_per_product: int = 3) -> list[RetrievedContext]:
    contexts: list[RetrievedContext] = []
    for product_id in product_ids:
        rows = conn.execute(
            "SELECT id, product_id, chunk_type, content, metadata_json FROM rag_chunks WHERE product_id = ? ORDER BY chunk_type LIMIT ?",
            (product_id, limit_per_product),
        ).fetchall()
        for row in rows:
            metadata_raw = _row_get(row, "metadata_json", "{}")
            try:
                metadata = json.loads(metadata_raw)
            except Exception:
                metadata = {}
            contexts.append(
                RetrievedContext(
                    chunk_id=str(_row_get(row, "id")),
                    product_id=str(_row_get(row, "product_id")),
                    text=str(_row_get(row, "content")),
                    source_type=str(_row_get(row, "chunk_type")),
                    metadata=metadata,
                )
            )
    return contexts


def dedupe_contexts(contexts: list[RetrievedContext]) -> list[RetrievedContext]:
    seen: set[str] = set()
    deduped: list[RetrievedContext] = []
    for context in contexts:
        key = context.chunk_id
        if key in seen:
            continue
        seen.add(key)
        deduped.append(context)
    return deduped


def extract_max_price(text: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*元?\s*(?:以下|以内|内|之内)", text)
    if match:
        return float(match.group(1))
    match = re.search(r"(?:低于|不超过|小于|少于)\s*(\d+(?:\.\d+)?)", text)
    if match:
        return float(match.group(1))
    return None


def expand_query(query: str) -> str:
    additions = []
    if "洗面奶" in query:
        additions.extend(["洁面", "清洁"])
    if "油皮" in query:
        additions.extend(["控油", "清爽"])
    if "蓝牙" in query or "耳机" in query:
        additions.extend(["无线耳机", "降噪", "通勤"])
    if "手机" in query:
        additions.extend(["智能手机", "拍照", "续航"])
    if "学生党" in query:
        additions.extend(["学生", "性价比", "预算"])
    if "同款" in query or "类似" in query:
        additions.append("相似")
    return " ".join([query, *additions])


def required_terms(query: str) -> set[str]:
    terms = set()
    if "蓝牙" in query or "耳机" in query:
        terms.update({"蓝牙", "耳机", "无线"})
    if "洗面奶" in query or "洁面" in query:
        terms.update({"洗面奶", "洁面"})
    if "外套" in query:
        terms.update({"外套", "夹克", "卫衣", "上衣"})
    if "手机" in query:
        terms.update({"手机", "iphone", "redmi", "智能"})
    return terms


def fallback_required_terms(query: str) -> set[str]:
    if "耳机" in query or "蓝牙" in query:
        return {"耳机", "蓝牙耳机", "真无线耳机"}
    if "手机" in query:
        return {"手机", "智能手机"}
    if "洗面奶" in query or "洁面" in query:
        return {"洗面奶", "洁面"}
    if "外套" in query:
        return {"外套", "夹克", "卫衣", "上衣"}
    return required_terms(query)


def build_reason(row: Any, query: str) -> str:
    parts = []
    if _row_get(row, "subcategory", "") in query or _row_get(row, "category", "") in query:
        parts.append(f"品类匹配{_row_get(row, 'subcategory', '')}")
    if _row_get(row, "brand", "") in query:
        parts.append(f"品牌匹配{_row_get(row, 'brand', '')}")
    if "油皮" in query and ("油" in _row_get(row, "marketing_description", "") or "洁面" in _row_get(row, "subcategory", "")):
        parts.append("适合围绕肤质和清洁需求进一步比较")
    if "蓝牙" in query and ("蓝牙" in _row_get(row, "marketing_description", "") or "耳机" in _row_get(row, "title", "")):
        parts.append("标题或卖点中包含蓝牙/耳机相关信息")
    if "学生党" in query:
        parts.append("可结合预算、价格和使用场景进一步判断")
    if not parts:
        parts.append("与当前需求在标题、分类、描述、FAQ 或评价中有匹配")
    return "，".join(parts) + "。"


def row_to_product_card_for_agent(row: Any, reason: str | None = None) -> ProductCard:
    return ProductCard(
        id=str(_row_get(row, "id")),
        title=str(_row_get(row, "title")),
        brand=str(_row_get(row, "brand")),
        category=str(_row_get(row, "category", "")),
        subcategory=str(_row_get(row, "subcategory", "")),
        price=float(_row_get(row, "price", 0)),
        rating=float(_row_get(row, "rating", 0)),
        image_path=f"/api/product-images/{_row_get(row, 'id')}.jpg",
        reason=reason,
        marketing_description=str(_row_get(row, "marketing_description", "")),
        review_count=int(_row_get(row, "review_count", 0) or 0),
        sku_count=int(_row_get(row, "sku_count", 0) or 0),
        faq_count=int(_row_get(row, "faq_count", 0) or 0),
        stock=int(_row_get(row, "stock", 0) or 0),
        sku_summary=_row_get(row, "sku_summary", None),
    )


def row_search_text(row: Any) -> str:
    return " ".join(
        str(_row_get(row, key, "") or "")
        for key in [
            "title",
            "brand",
            "category",
            "subcategory",
            "marketing_description",
            "sku_summary",
            "faq_text",
            "review_text",
        ]
    ).lower()


def _sku_text(sku: dict[str, Any]) -> str:
    properties = sku.get("properties") or {}
    prop_text = " / ".join(str(value) for value in properties.values()) or "默认规格"
    return f"{prop_text} 价格 {sku.get('price', '')} 库存 {sku.get('stock', '')}"


def _row_get(row: Any, key: str, default: Any = "") -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        value = row[key]
        return default if value is None else value
    except Exception:
        return default
