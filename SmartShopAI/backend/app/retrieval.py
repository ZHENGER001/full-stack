from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .query_router import ParsedQuery
from .search_document import build_product_search_document
from .vector_retriever import milvus_semantic_search_with_diagnostics

try:
    import jieba
except ImportError:  # pragma: no cover - optional dependency fallback
    jieba = None


CUSTOM_SEARCH_TERMS = [
    "蓝牙耳机",
    "无线耳机",
    "降噪耳机",
    "洗面奶",
    "洁面乳",
    "防晒霜",
    "油皮",
    "干皮",
    "敏感肌",
    "控油",
    "清爽",
    "通勤包",
    "电脑包",
    "登机箱",
    "拉杆箱",
    "猫爬架",
    "宠物围栏",
    "智能手表",
    "智能手机",
]

if jieba is not None:
    for term in CUSTOM_SEARCH_TERMS:
        jieba.add_word(term)


@dataclass(frozen=True)
class RetrievalHit:
    product_id: str
    score: float
    source: str
    rank: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HybridSearchResult:
    candidates: list[dict[str, Any]]
    diagnostics: dict[str, Any]


def hybrid_search_products(conn, parsed_query: ParsedQuery, limit: int = 24) -> HybridSearchResult:
    rows = _load_search_rows(conn)
    if not rows:
        return HybridSearchResult(candidates=[], diagnostics=_empty_diagnostics(parsed_query))

    lane_limit = max(limit, 20)
    include_evidence = parsed_query.filters.get("retrieval_scope") == "full_evidence"
    documents = {str(row["id"]): _build_document(row, include_evidence=include_evidence) for row in rows}
    dense_hits, dense_diagnostics = _dense_search(parsed_query, lane_limit)
    bm25_hits = _bm25_search(parsed_query, rows, documents, lane_limit)
    keyword_hits = _keyword_search(parsed_query, rows, documents, lane_limit)
    fused_hits = _rrf_fuse([dense_hits, bm25_hits, keyword_hits], top_k=lane_limit)
    candidates = hydrate_products(conn, fused_hits, limit=lane_limit)

    diagnostics = {
        "pipeline": ["query_router", "dense_milvus", "bm25", "keyword", "rrf", "sqlite_hydrate"],
        "query": {
            "raw": parsed_query.raw_query,
            "rewritten": parsed_query.rewritten_query,
            "route_notes": parsed_query.route_notes,
            "filters": parsed_query.filters,
            "retrieval_scope": "full_evidence" if include_evidence else "catalog_only",
        },
        "lanes": {
            "dense": {**_lane_diagnostics(dense_hits, backend="milvus"), **dense_diagnostics},
            "bm25": _lane_diagnostics(bm25_hits),
            "keyword": _lane_diagnostics(keyword_hits),
        },
        "degradation": _degradation_diagnostics(dense_diagnostics, bm25_hits, keyword_hits),
        "fusion": {
            "method": "rrf",
            "rank_constant": 60,
            "candidate_count": len(fused_hits),
            "top": [
                {
                    "product_id": hit.product_id,
                    "score": round(hit.score, 6),
                    "sources": sorted(hit.metadata.get("sources", [])),
                }
                for hit in fused_hits[:10]
            ],
        },
        "hydrate": {
            "requested": len(fused_hits),
            "returned": len(candidates),
        },
    }
    return HybridSearchResult(candidates=candidates, diagnostics=diagnostics)


def hydrate_products(conn, fused_hits: list[RetrievalHit], limit: int) -> list[dict[str, Any]]:
    product_ids = [hit.product_id for hit in fused_hits if hit.product_id]
    if not product_ids:
        return []
    placeholders = ",".join("?" for _ in product_ids)
    rows = conn.execute(
        f"""
        SELECT
            p.*,
            COALESCE(rv.review_text, '') AS review_text,
            COALESCE(rv.review_count, 0) AS review_count,
            COALESCE(fq.faq_text, '') AS faq_text,
            COALESCE(fq.faq_count, 0) AS faq_count,
            COALESCE(sk.sku_text, '') AS sku_text,
            COALESCE(sk.sku_summary, '') AS sku_summary,
            COALESCE(sk.sku_count, 0) AS sku_count,
            COALESCE(sk.stock, 0) AS stock,
            COALESCE(rg.chunk_text, '') AS chunk_text
        FROM products p
        LEFT JOIN (
            SELECT product_id, GROUP_CONCAT(content, ' ') AS review_text, COUNT(*) AS review_count
            FROM product_reviews
            GROUP BY product_id
        ) rv ON rv.product_id = p.id
        LEFT JOIN (
            SELECT product_id, GROUP_CONCAT(question || ' ' || answer, ' ') AS faq_text, COUNT(*) AS faq_count
            FROM product_faqs
            GROUP BY product_id
        ) fq ON fq.product_id = p.id
        LEFT JOIN (
            SELECT
                product_id,
                GROUP_CONCAT(sku_name || ' ' || properties_json, ' ') AS sku_text,
                GROUP_CONCAT(sku_name, ' / ') AS sku_summary,
                COUNT(*) AS sku_count,
                SUM(stock) AS stock
            FROM product_skus
            GROUP BY product_id
        ) sk ON sk.product_id = p.id
        LEFT JOIN (
            SELECT product_id, GROUP_CONCAT(content, ' ') AS chunk_text
            FROM rag_chunks
            GROUP BY product_id
        ) rg ON rg.product_id = p.id
        WHERE p.id IN ({placeholders})
        """,
        product_ids,
    ).fetchall()
    row_by_id = {str(row["id"]): row for row in rows}
    hydrated: list[dict[str, Any]] = []
    for hit in fused_hits:
        row = row_by_id.get(hit.product_id)
        if row is None:
            continue
        hydrated.append(_row_to_candidate(row, hit))
        if len(hydrated) >= limit:
            break
    return hydrated


def _load_search_rows(conn) -> list[Any]:
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


def _dense_search(parsed_query: ParsedQuery, limit: int) -> tuple[list[RetrievalHit], dict[str, Any]]:
    result = milvus_semantic_search_with_diagnostics(parsed_query.rewritten_query, top_k=limit)
    ranked: list[RetrievalHit] = []
    for index, item in enumerate(result.hits, start=1):
        product_id = str(item.get("product_id") or "")
        if not product_id:
            continue
        ranked.append(
            RetrievalHit(
                product_id=product_id,
                score=float(item.get("score") or 0.0),
                source="dense",
                rank=index,
                metadata={"backend": "milvus"},
            )
        )
    return ranked, result.diagnostics


def _bm25_search(
    parsed_query: ParsedQuery,
    rows: list[Any],
    documents: dict[str, str],
    limit: int,
) -> list[RetrievalHit]:
    query_tokens = _tokenize(parsed_query.rewritten_query)
    if not query_tokens:
        return []
    doc_tokens = {product_id: _tokenize(document) for product_id, document in documents.items()}
    idf = _build_idf(list(doc_tokens.values()))
    avg_doc_len = sum(len(tokens) for tokens in doc_tokens.values()) / max(len(doc_tokens), 1)
    hits: list[RetrievalHit] = []
    for row in rows:
        product_id = str(row["id"])
        score = _bm25(query_tokens, doc_tokens.get(product_id, []), idf, avg_doc_len)
        if score <= 0:
            continue
        hits.append(RetrievalHit(product_id=product_id, score=score, source="bm25"))
    return _rank_hits(hits, limit)


def _keyword_search(
    parsed_query: ParsedQuery,
    rows: list[Any],
    documents: dict[str, str],
    limit: int,
) -> list[RetrievalHit]:
    filters = parsed_query.filters
    query_terms = set(_tokenize(parsed_query.raw_query))
    query_terms.update(str(item).lower() for item in filters.get("required_terms") or [])
    query_terms.update(str(item).lower() for item in filters.get("scene_terms") or [])
    query_terms.update(str(item).lower() for item in filters.get("colors") or [])

    target_categories = set(filters.get("target_categories") or [])
    target_subcategories = set(filters.get("target_subcategories") or [])
    target_brands = set(filters.get("brands") or [])
    max_price = filters.get("max_price")
    hits: list[RetrievalHit] = []
    for row in rows:
        if float(row["stock"] or 0) <= 0:
            continue
        product_id = str(row["id"])
        title = str(row["title"] or "").lower()
        document = documents.get(product_id, "")
        score = 0.0
        for term in query_terms:
            if not term:
                continue
            if term in title:
                score += 5.0
            elif term in document:
                score += 1.5
        if row["category"] in target_categories:
            score += 8.0
        if row["subcategory"] in target_subcategories:
            score += 12.0
        if row["brand"] in target_brands:
            score += 8.0
        if max_price is not None and float(row["price"] or 0) <= float(max_price):
            score += 3.0
        if filters.get("price_sensitive"):
            score += _price_score(float(row["price"] or 0))
        if score <= 0:
            continue
        hits.append(RetrievalHit(product_id=product_id, score=score, source="keyword"))
    return _rank_hits(hits, limit)


def _rrf_fuse(ranked_lists: list[list[RetrievalHit]], top_k: int, rank_constant: int = 60) -> list[RetrievalHit]:
    fused: dict[str, dict[str, Any]] = {}
    for hits in ranked_lists:
        for index, hit in enumerate(hits, start=1):
            item = fused.setdefault(
                hit.product_id,
                {"score": 0.0, "sources": set(), "source_scores": {}, "source_ranks": {}},
            )
            item["score"] += 1.0 / (rank_constant + index)
            item["sources"].add(hit.source)
            item["source_scores"][hit.source] = round(hit.score, 6)
            item["source_ranks"][hit.source] = index

    fused_hits = [
        RetrievalHit(
            product_id=product_id,
            score=data["score"],
            source="rrf",
            rank=index,
            metadata={
                "sources": data["sources"],
                "source_scores": data["source_scores"],
                "source_ranks": data["source_ranks"],
            },
        )
        for index, (product_id, data) in enumerate(
            sorted(fused.items(), key=lambda item: item[1]["score"], reverse=True),
            start=1,
        )
    ]
    return fused_hits[:top_k]


def _rank_hits(hits: list[RetrievalHit], limit: int) -> list[RetrievalHit]:
    ranked = sorted(hits, key=lambda hit: hit.score, reverse=True)[:limit]
    return [
        RetrievalHit(
            product_id=hit.product_id,
            score=hit.score,
            source=hit.source,
            rank=index,
            metadata=hit.metadata,
        )
        for index, hit in enumerate(ranked, start=1)
    ]


def _degradation_diagnostics(
    dense_diagnostics: dict[str, Any],
    bm25_hits: list[RetrievalHit],
    keyword_hits: list[RetrievalHit],
) -> dict[str, Any]:
    degraded = dense_diagnostics.get("status") == "degraded"
    if not degraded:
        return {"used": False, "reason": None}
    fallback_lanes = []
    if bm25_hits:
        fallback_lanes.append("bm25")
    if keyword_hits:
        fallback_lanes.append("keyword")
    return {
        "used": True,
        "reason": dense_diagnostics.get("reason") or "dense_unavailable",
        "fallback_lanes": fallback_lanes,
    }


def _row_to_candidate(row: Any, hit: RetrievalHit) -> dict[str, Any]:
    source_scores = hit.metadata.get("source_scores", {})
    source_ranks = hit.metadata.get("source_ranks", {})
    sources = sorted(hit.metadata.get("sources", []))
    score_for_card = round(hit.score * 100.0, 3)
    return {
        "id": row["id"],
        "title": row["title"],
        "brand": row["brand"],
        "category": row["category"],
        "subcategory": row["subcategory"],
        "price": float(row["price"]),
        "rating": float(row["rating"]),
        "image_path": f"/api/product-thumbnails/{row['id']}.jpg",
        "reason": _build_reason(sources, score_for_card),
        "marketing_description": row["marketing_description"],
        "stock": int(row["stock"] or 0),
        "sku_text": row["sku_text"],
        "sku_summary": row["sku_summary"],
        "sku_count": int(row["sku_count"] or 0),
        "faq_text": row["faq_text"],
        "faq_count": int(row["faq_count"] or 0),
        "review_text": row["review_text"],
        "review_count": int(row["review_count"] or 0),
        "chunk_text": row["chunk_text"],
        "_dense_score": float(source_scores.get("dense") or 0.0),
        "_bm25_score": float(source_scores.get("bm25") or 0.0),
        "_keyword_score": float(source_scores.get("keyword") or 0.0),
        "_rrf_score": round(hit.score, 6),
        "_retrieval_score": score_for_card,
        "_source_ranks": source_ranks,
        "_sources": sources,
        "rerank_score": score_for_card,
        "rerank_reason": _build_reason(sources, score_for_card),
    }


def _build_document(row: Any, include_evidence: bool = True) -> str:
    return build_product_search_document(row, include_evidence=include_evidence).lower()


def _tokenize(text: str) -> list[str]:
    lower = (text or "").lower()
    tokens = re.findall(r"[a-z0-9]+", lower)
    cjk_text = "".join(char if "\u4e00" <= char <= "\u9fff" else " " for char in lower)
    if jieba is not None:
        tokens.extend(token.strip() for token in jieba.cut(cjk_text) if token.strip())
    cjk_chars = [char for char in cjk_text if "\u4e00" <= char <= "\u9fff"]
    tokens.extend("".join(cjk_chars[index : index + 2]) for index in range(max(len(cjk_chars) - 1, 0)))
    return [token for token in tokens if token.strip()]


def _build_idf(doc_tokens: list[list[str]]) -> dict[str, float]:
    total_docs = len(doc_tokens)
    df = Counter()
    for tokens in doc_tokens:
        df.update(set(tokens))
    return {term: math.log(1 + (total_docs - count + 0.5) / (count + 0.5)) for term, count in df.items()}


def _bm25(query_tokens: list[str], doc_tokens: list[str], idf: dict[str, float], avg_doc_len: float) -> float:
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


def _price_score(price: float) -> float:
    if price <= 50:
        return 6.0
    if price <= 100:
        return 5.0
    if price <= 200:
        return 4.0
    if price <= 500:
        return 3.0
    if price <= 1000:
        return 2.0
    if price <= 2000:
        return 1.0
    if price <= 3000:
        return -1.0
    return -3.0


def _build_reason(sources: list[str], score: float) -> str:
    source_text = "/".join(sources) if sources else "retrieval"
    return f"Matched by {source_text} retrieval, RRF score {score:.3f}."


def _lane_diagnostics(hits: list[RetrievalHit], backend: str | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "count": len(hits),
        "top": [
            {"product_id": hit.product_id, "score": round(hit.score, 6), "rank": hit.rank}
            for hit in hits[:5]
        ],
    }
    if backend:
        data["backend"] = backend
    return data


def _empty_diagnostics(parsed_query: ParsedQuery) -> dict[str, Any]:
    return {
        "pipeline": ["query_router", "dense_milvus", "bm25", "keyword", "rrf", "sqlite_hydrate"],
        "query": {
            "raw": parsed_query.raw_query,
            "rewritten": parsed_query.rewritten_query,
            "route_notes": parsed_query.route_notes,
            "filters": parsed_query.filters,
            "retrieval_scope": parsed_query.filters.get("retrieval_scope", "catalog_only"),
        },
        "lanes": {"dense": {"count": 0, "backend": "milvus"}, "bm25": {"count": 0}, "keyword": {"count": 0}},
        "fusion": {"method": "rrf", "rank_constant": 60, "candidate_count": 0, "top": []},
        "hydrate": {"requested": 0, "returned": 0},
    }
