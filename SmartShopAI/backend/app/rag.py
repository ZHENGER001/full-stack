from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from .graph_retriever import expand_related_product_ids
from .query_parser import has_hard_filters, parse_user_filters
from .reranker import rerank_products
from .schemas import ProductCard
from .vector_retriever import semantic_search


DOMAIN_PHRASES = [
    "学生党",
    "性价比",
    "预算",
    "便宜",
    "宿舍",
    "上课",
    "学习",
    "通勤",
    "办公",
    "出差",
    "旅行",
    "户外",
    "跑步",
    "健身",
    "篮球",
    "护肤",
    "油皮",
    "控油",
    "洁面",
    "洗面奶",
    "防晒",
    "耳机",
    "蓝牙",
    "手机",
    "平板",
    "电脑",
    "笔记本",
    "咖啡",
    "零食",
    "宠物",
]


@dataclass(frozen=True)
class QueryIntent:
    expanded_query: str
    max_price: float | None
    price_sensitive: bool
    required_terms: set[str]
    category_boosts: dict[str, float]
    subcategory_boosts: dict[str, float]
    scene_terms: set[str]


def tokenize(text: str) -> list[str]:
    lower = (text or "").lower()
    tokens = re.findall(r"[a-z0-9]+", lower)
    tokens.extend(phrase for phrase in DOMAIN_PHRASES if phrase in lower)
    cjk_chars = [char for char in lower if "\u4e00" <= char <= "\u9fff"]
    tokens.extend("".join(cjk_chars[index : index + 2]) for index in range(max(len(cjk_chars) - 1, 0)))
    return [token for token in tokens if token.strip()]


def build_product_chunks(product: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = {
        "product_id": product["id"],
        "title": product["title"],
        "brand": product["brand"],
        "category": product["category"],
        "subcategory": product["subcategory"],
        "price": product["price"],
        "rating": product["rating"],
    }
    chunks = [
        {
            "id": f"{product['id']}:basic_info",
            "product_id": product["id"],
            "chunk_type": "basic_info",
            "content": f"{product['title']} {product['brand']} {product['category']} {product['subcategory']} 价格 {product['price']} 评分 {product['rating']}",
            "metadata_json": json.dumps({**metadata, "chunk_type": "basic_info"}, ensure_ascii=False),
        },
        {
            "id": f"{product['id']}:marketing",
            "product_id": product["id"],
            "chunk_type": "marketing",
            "content": product.get("marketing_description", ""),
            "metadata_json": json.dumps({**metadata, "chunk_type": "marketing"}, ensure_ascii=False),
        },
    ]
    return [chunk for chunk in chunks if chunk["content"]]


def search_products_for_agent(conn, query: str, limit: int = 3) -> list[ProductCard]:
    intent = analyze_query_intent(query)
    rows = load_search_rows(conn)
    known_brands = sorted({str(row["brand"]) for row in rows if row["brand"]})
    user_filters = parse_user_filters(query, known_brands)
    semantic_results = semantic_search(query, top_k=max(20, limit * 8))
    semantic_scores = {str(item.get("product_id")): float(item.get("score") or 0.0) for item in semantic_results}
    row_by_id = {str(row["id"]): row for row in rows}
    documents = [build_search_document(row) for row in rows]
    query_tokens = tokenize(intent.expanded_query)
    if not rows or not query_tokens:
        return fallback_products(conn, intent, limit)

    doc_tokens = [tokenize(document) for document in documents]
    idf = build_idf(doc_tokens)
    avg_doc_len = sum(len(tokens) for tokens in doc_tokens) / max(len(doc_tokens), 1)
    candidates: list[dict[str, Any]] = []
    for row, document, tokens in zip(rows, documents, doc_tokens):
        if intent.required_terms and not document_contains_any(document, intent.required_terms):
            continue

        bm25_score = bm25(query_tokens, tokens, idf, avg_doc_len)
        rule_score = rule_score_for_row(row, document, intent)
        rerank_score = rerank_score_for_row(row, intent)
        semantic_score = semantic_scores.get(str(row["id"]), 0.0)
        total_score = bm25_score + rule_score + rerank_score + semantic_score * 18.0 + float(row["rating"]) * 0.2
        category_candidate = (
            row["category"] in set(user_filters.get("target_categories") or [])
            or row["subcategory"] in set(user_filters.get("target_subcategories") or [])
        )
        if total_score <= 0 and not category_candidate and semantic_score <= 0:
            continue
        candidates.append(
            row_to_product_dict_for_agent(
                row,
                build_reason(row, intent, bm25_score, rule_score, rerank_score, semantic_score),
                bm25_score=bm25_score,
                rule_score=rule_score,
                semantic_score=semantic_score,
                retrieval_score=total_score,
            )
        )

    enrich_candidates_with_graph(conn, candidates, row_by_id, query, limit)

    if not candidates:
        if has_hard_filters(user_filters):
            return []
        return fallback_products(conn, intent, limit)

    top_products = rerank_products(
        query=query,
        products=candidates,
        user_filters=user_filters,
        session_state=None,
        top_k=limit,
    )
    if not top_products:
        if has_hard_filters(user_filters):
            return []
        return fallback_products(conn, intent, limit)
    return [product_dict_to_product_card(product) for product in top_products]


def enrich_candidates_with_graph(
    conn,
    candidates: list[dict[str, Any]],
    row_by_id: dict[str, Any],
    query: str,
    limit: int,
) -> None:
    if not candidates:
        return
    graph_results = expand_related_product_ids(
        conn,
        [str(product["id"]) for product in candidates[: max(limit * 2, 4)]],
        query=query,
        top_k=max(limit * 6, 12),
    )
    if not graph_results:
        return
    candidate_by_id = {str(product["id"]): product for product in candidates}
    for item in graph_results:
        product_id = str(item.get("product_id") or "")
        graph_score = float(item.get("score") or 0.0)
        if not product_id or graph_score <= 0:
            continue
        if product_id in candidate_by_id:
            product = candidate_by_id[product_id]
            product["_graph_score"] = round(graph_score, 3)
            product["_retrieval_score"] = round(float(product.get("_retrieval_score") or 0) + graph_score * 3.0, 3)
            reason = str(product.get("reason") or "")
            if "图关系扩展命中" not in reason:
                product["reason"] = f"{reason}，图关系扩展命中".strip("，")
            continue
        row = row_by_id.get(product_id)
        if row is None:
            continue
        candidates.append(
            row_to_product_dict_for_agent(
                row,
                reason="基于相似品类、品牌或价格关系做图扩展召回。",
                graph_score=graph_score,
                retrieval_score=graph_score * 3.0,
            )
        )


def analyze_query_intent(query: str) -> QueryIntent:
    expanded_terms = [query]
    max_price = extract_max_price(query)
    required = required_terms(query)
    category_boosts: dict[str, float] = {}
    subcategory_boosts: dict[str, float] = {}
    scene_terms = set()
    price_sensitive = any(word in query for word in ["学生党", "预算", "便宜", "性价比", "平价", "入门"])

    if any(word in query for word in ["学生", "学生党", "上课", "学习", "宿舍", "校园"]):
        expanded_terms.extend(["学习", "办公", "文具", "平板", "耳机", "背包", "咖啡", "零食"])
        category_boosts.update({"办公文具": 9.0, "食品饮料": 8.0, "旅行户外": 5.0, "数码电子": 2.0})
        subcategory_boosts.update({"书写工具": 8.0, "本册纸品": 8.0, "文件管理": 5.0, "桌面整理": 5.0, "办公配件": 1.0, "真无线耳机": 5.0, "背包": 5.0, "咖啡": 5.0, "坚果/零食": 5.0})
        scene_terms.update({"学生党", "学习", "上课", "宿舍", "性价比"})
        price_sensitive = True
    if any(word in query for word in ["耳机", "蓝牙", "降噪"]):
        expanded_terms.extend(["真无线耳机", "蓝牙", "通勤"])
        category_boosts["数码电子"] = category_boosts.get("数码电子", 0.0) + 6.0
        subcategory_boosts["真无线耳机"] = subcategory_boosts.get("真无线耳机", 0.0) + 8.0
    if any(word in query for word in ["护肤", "油皮", "控油", "洁面", "洗面奶"]):
        expanded_terms.extend(["美妆护肤", "洁面", "控油", "清爽"])
        category_boosts["美妆护肤"] = category_boosts.get("美妆护肤", 0.0) + 7.0
        subcategory_boosts["洁面"] = subcategory_boosts.get("洁面", 0.0) + 8.0
    if any(word in query for word in ["跑步", "健身", "篮球", "运动"]):
        expanded_terms.extend(["服饰运动", "透气", "训练"])
        category_boosts["服饰运动"] = category_boosts.get("服饰运动", 0.0) + 6.0
    if any(word in query for word in ["旅行", "出差", "户外", "徒步"]):
        expanded_terms.extend(["旅行户外", "收纳", "背包", "耐磨"])
        category_boosts["旅行户外"] = category_boosts.get("旅行户外", 0.0) + 6.0

    return QueryIntent(
        expanded_query=" ".join(expanded_terms),
        max_price=max_price,
        price_sensitive=price_sensitive,
        required_terms=required,
        category_boosts=category_boosts,
        subcategory_boosts=subcategory_boosts,
        scene_terms=scene_terms,
    )


def load_search_rows(conn) -> list[Any]:
    return conn.execute(
        """
        SELECT
            p.*,
            COALESCE(rv.review_text, '') AS review_text,
            COALESCE(fq.faq_text, '') AS faq_text,
            COALESCE(sk.sku_text, '') AS sku_text,
            COALESCE(sk.stock, 0) AS stock,
            COALESCE(rg.chunk_text, '') AS chunk_text
        FROM products p
        LEFT JOIN (
            SELECT product_id, GROUP_CONCAT(content, ' ') AS review_text
            FROM product_reviews
            GROUP BY product_id
        ) rv ON rv.product_id = p.id
        LEFT JOIN (
            SELECT product_id, GROUP_CONCAT(question || ' ' || answer, ' ') AS faq_text
            FROM product_faqs
            GROUP BY product_id
        ) fq ON fq.product_id = p.id
        LEFT JOIN (
            SELECT product_id, GROUP_CONCAT(sku_name || ' ' || properties_json, ' ') AS sku_text, SUM(stock) AS stock
            FROM product_skus
            GROUP BY product_id
        ) sk ON sk.product_id = p.id
        LEFT JOIN (
            SELECT product_id, GROUP_CONCAT(content, ' ') AS chunk_text
            FROM rag_chunks
            GROUP BY product_id
        ) rg ON rg.product_id = p.id
        """
    ).fetchall()


def build_search_document(row: Any) -> str:
    return " ".join(
        str(part or "")
        for part in [
            row["title"],
            row["brand"],
            row["category"],
            row["subcategory"],
            row["marketing_description"],
            row["review_text"],
            row["faq_text"],
            row["sku_text"],
            row["chunk_text"],
        ]
    ).lower()


def build_idf(doc_tokens: list[list[str]]) -> dict[str, float]:
    total_docs = len(doc_tokens)
    df = Counter()
    for tokens in doc_tokens:
        df.update(set(tokens))
    return {term: math.log(1 + (total_docs - count + 0.5) / (count + 0.5)) for term, count in df.items()}


def bm25(query_tokens: list[str], doc_tokens: list[str], idf: dict[str, float], avg_doc_len: float) -> float:
    counts = Counter(doc_tokens)
    doc_len = max(len(doc_tokens), 1)
    k1 = 1.5
    b = 0.75
    score = 0.0
    for token in query_tokens:
        tf = counts.get(token, 0)
        if tf <= 0:
            continue
        denominator = tf + k1 * (1 - b + b * doc_len / max(avg_doc_len, 1))
        score += idf.get(token, 0.0) * (tf * (k1 + 1)) / denominator
    return score


def rule_score_for_row(row: Any, document: str, intent: QueryIntent) -> float:
    score = 0.0
    for phrase in set(tokenize(intent.expanded_query)) | intent.scene_terms:
        if phrase and phrase in str(row["title"]).lower():
            score += 5.0
        elif phrase and phrase in document:
            score += 2.0
    score += intent.category_boosts.get(row["category"], 0.0)
    score += intent.subcategory_boosts.get(row["subcategory"], 0.0)
    if float(row["stock"] or 0) > 0:
        score += 1.5
    return score


def rerank_score_for_row(row: Any, intent: QueryIntent) -> float:
    score = 0.0
    price = float(row["price"])
    marketing = str(row["marketing_description"] or "")
    if "非商业演示" in marketing or "商品目录图片数据" in marketing:
        score -= 14.0
    if intent.price_sensitive:
        if price <= 50:
            score += 22.0
        elif price <= 100:
            score += 19.0
        elif price <= 200:
            score += 16.0
        elif price <= 500:
            score += 12.0
        elif price <= 1000:
            score += 7.0
        elif price <= 2000:
            score += 2.0
        elif price <= 3000:
            score -= 5.0
        elif price >= 3000:
            score -= 14.0
        if price >= 5000:
            score -= 8.0
    if intent.max_price is not None and price <= intent.max_price:
        score += 3.0
    stock = float(row["stock"] or 0)
    if stock <= 0:
        score -= 8.0
    elif stock >= 20:
        score += 2.0
    return score


def diversify(scored: list[tuple[float, Any, str]], limit: int) -> list[tuple[float, Any, str]]:
    selected: list[tuple[float, Any, str]] = []
    seen_subcategories: set[str] = set()
    for item in scored:
        _, row, _ = item
        if row["subcategory"] not in seen_subcategories or len(selected) >= max(limit - 1, 1):
            selected.append(item)
            seen_subcategories.add(row["subcategory"])
        if len(selected) >= limit:
            return selected
    for item in scored:
        if item not in selected:
            selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def document_contains_any(document: str, terms: set[str]) -> bool:
    return any(term in document for term in terms)


def extract_max_price(text: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*元?\s*(?:以下|以内|内|之内)", text)
    if match:
        return float(match.group(1))
    return None


def required_terms(query: str) -> set[str]:
    terms = set()
    if "蓝牙" in query or "耳机" in query:
        terms.update({"蓝牙", "耳机", "真无线"})
    if "洗面奶" in query or "洁面" in query:
        terms.update({"洗面奶", "洁面"})
    if "外套" in query:
        terms.update({"外套", "夹克", "卫衣", "上衣"})
    if "宠物" in query:
        terms.update({"宠物", "猫", "狗"})
    return terms


def build_reason(
    row: Any,
    intent: QueryIntent,
    bm25_score: float,
    rule_score: float,
    rerank_score: float,
    semantic_score: float = 0.0,
) -> str:
    parts = []
    if intent.category_boosts.get(row["category"]) or intent.subcategory_boosts.get(row["subcategory"]):
        parts.append(f"品类/场景匹配{row['category']}·{row['subcategory']}")
    if intent.price_sensitive:
        parts.append("价格更适合预算敏感需求")
    if float(row["stock"] or 0) > 0:
        parts.append("库存可用")
    if bm25_score > 0:
        parts.append("商品文本、FAQ或评价与需求有关键词匹配")
    if semantic_score > 0:
        parts.append("语义向量召回命中")
    if not parts:
        parts.append("基于商品库规则排序得到的候选")
    return "，".join(parts) + f"。（检索分: {bm25_score:.1f}/{rule_score:.1f}/{rerank_score:.1f}/{semantic_score:.2f}）"


def fallback_products(conn, intent: QueryIntent, limit: int) -> list[ProductCard]:
    rows = conn.execute(
        """
        SELECT p.*, COALESCE(SUM(s.stock), 0) AS stock
        FROM products p
        LEFT JOIN product_skus s ON s.product_id = p.id
        WHERE p.price <= COALESCE(?, p.price)
        GROUP BY p.id
        ORDER BY
            CASE WHEN COALESCE(SUM(s.stock), 0) > 0 THEN 0 ELSE 1 END,
            p.rating DESC,
            p.price ASC
        LIMIT ?
        """,
        (intent.max_price, limit),
    ).fetchall()
    return [
        row_to_product_card_for_agent(row, "当前商品数据匹配信息有限，按库存、评分和价格给出兜底候选。")
        for row in rows
    ]


def row_to_product_dict_for_agent(
    row: Any,
    reason: str | None = None,
    bm25_score: float = 0.0,
    rule_score: float = 0.0,
    semantic_score: float = 0.0,
    graph_score: float = 0.0,
    retrieval_score: float = 0.0,
) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "brand": row["brand"],
        "category": row["category"],
        "subcategory": row["subcategory"],
        "price": float(row["price"]),
        "rating": float(row["rating"]),
        "image_path": f"/api/product-thumbnails/{row['id']}.jpg",
        "reason": reason,
        "marketing_description": row["marketing_description"],
        "stock": int(row["stock"] or 0),
        "sku_text": row["sku_text"],
        "faq_text": row["faq_text"],
        "review_text": row["review_text"],
        "chunk_text": row["chunk_text"],
        "_bm25_score": round(bm25_score, 3),
        "_rule_score": round(rule_score, 3),
        "_semantic_score": round(semantic_score, 3),
        "_graph_score": round(graph_score, 3),
        "_retrieval_score": round(retrieval_score, 3),
    }


def product_dict_to_product_card(product: dict[str, Any]) -> ProductCard:
    reason = product.get("rerank_reason") or product.get("reason")
    return ProductCard(
        id=product["id"],
        title=product["title"],
        brand=product["brand"],
        category=product.get("category"),
        subcategory=product.get("subcategory"),
        price=float(product["price"]),
        rating=float(product.get("rating") or 0),
        image_path=product.get("image_path") or f"/api/product-thumbnails/{product['id']}.jpg",
        reason=reason,
        marketing_description=product.get("marketing_description"),
        stock=int(product.get("stock") or 0),
        rerank_score=product.get("rerank_score"),
        rerank_reason=product.get("rerank_reason"),
    )


def row_to_product_card_for_agent(row: Any, reason: str | None = None) -> ProductCard:
    return ProductCard(
        id=row["id"],
        title=row["title"],
        brand=row["brand"],
        category=row["category"],
        subcategory=row["subcategory"],
        price=float(row["price"]),
        rating=float(row["rating"]),
        image_path=f"/api/product-thumbnails/{row['id']}.jpg",
        reason=reason,
    )
