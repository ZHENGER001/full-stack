from __future__ import annotations

import hashlib
import math
import os
import re
from collections import Counter
from typing import Any

import httpx

from .config import BASE_DIR, _load_env_file
from .database import get_connection
from .embedding_client import embed_query
from .milvus_client import MilvusError, MilvusRestClient


DOMAIN_PHRASES = [
    "蓝牙耳机",
    "真无线耳机",
    "降噪",
    "通勤",
    "学生党",
    "性价比",
    "办公",
    "运动",
    "跑步",
    "护肤",
    "洁面",
    "手机",
    "平板",
    "键盘",
    "鼠标",
    "充电器",
    "背包",
    "咖啡",
    "零食",
]


def _env_value(name: str, default: str | None = None) -> str | None:
    env_file = _load_env_file(BASE_DIR / ".env")
    return os.getenv(name) or env_file.get(name) or default


def vector_backend_name() -> str:
    return (_env_value("VECTOR_BACKEND", "none") or "none").strip().lower()


def _vector_dimensions() -> int:
    raw_value = _env_value("VECTOR_DIMENSIONS", "256")
    try:
        return max(int(raw_value or "256"), 32)
    except ValueError:
        return 256


def _tokenize(text: str) -> list[str]:
    lower = (text or "").lower()
    tokens = re.findall(r"[a-z0-9]+", lower)
    tokens.extend(phrase for phrase in DOMAIN_PHRASES if phrase in lower)
    cjk_chars = [char for char in lower if "\u4e00" <= char <= "\u9fff"]
    tokens.extend("".join(cjk_chars[index : index + 2]) for index in range(max(len(cjk_chars) - 1, 0)))
    return [token for token in tokens if token.strip()]


def _hash_index(token: str, dimensions: int) -> int:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, byteorder="little", signed=False) % dimensions


def _hash_vector(text: str, dimensions: int | None = None) -> list[float]:
    size = dimensions or _vector_dimensions()
    vector = [0.0] * size
    counts = Counter(_tokenize(text))
    for token, count in counts.items():
        vector[_hash_index(token, size)] += 1.0 + math.log(count)
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return vector
    return [value / norm for value in vector]


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def _load_product_documents() -> list[dict[str, str]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                p.id,
                p.title,
                p.brand,
                p.category,
                p.subcategory,
                COALESCE(p.marketing_description, '') AS marketing_description,
                COALESCE(rg.chunk_text, '') AS chunk_text,
                COALESCE(fq.faq_text, '') AS faq_text,
                COALESCE(rv.review_text, '') AS review_text
            FROM products p
            LEFT JOIN (
                SELECT product_id, GROUP_CONCAT(content, ' ') AS chunk_text
                FROM rag_chunks
                GROUP BY product_id
            ) rg ON rg.product_id = p.id
            LEFT JOIN (
                SELECT product_id, GROUP_CONCAT(question || ' ' || answer, ' ') AS faq_text
                FROM product_faqs
                GROUP BY product_id
            ) fq ON fq.product_id = p.id
            LEFT JOIN (
                SELECT product_id, GROUP_CONCAT(content, ' ') AS review_text
                FROM product_reviews
                GROUP BY product_id
            ) rv ON rv.product_id = p.id
            """
        ).fetchall()
    documents: list[dict[str, str]] = []
    for row in rows:
        documents.append(
            {
                "product_id": str(row["id"]),
                "text": " ".join(
                    str(part or "")
                    for part in [
                        row["title"],
                        row["brand"],
                        row["category"],
                        row["subcategory"],
                        row["marketing_description"],
                        row["chunk_text"],
                        row["faq_text"],
                        row["review_text"],
                    ]
                ),
            }
        )
    return documents


def _local_semantic_search(query: str, top_k: int) -> list[dict[str, Any]]:
    dimensions = _vector_dimensions()
    query_vector = _hash_vector(query, dimensions)
    if not any(query_vector):
        return []
    scored: list[dict[str, Any]] = []
    for document in _load_product_documents():
        score = _cosine(query_vector, _hash_vector(document["text"], dimensions))
        if score > 0:
            scored.append(
                {
                    "product_id": document["product_id"],
                    "score": round(score, 6),
                    "source": "vector_local",
                }
            )
    scored.sort(key=lambda item: float(item["score"]), reverse=True)
    return scored[:top_k]


def _qdrant_semantic_search(query: str, top_k: int) -> list[dict[str, Any]]:
    url = (_env_value("QDRANT_URL") or "").rstrip("/")
    collection = _env_value("QDRANT_COLLECTION", "smartshop_products") or "smartshop_products"
    if not url:
        return []
    headers: dict[str, str] = {}
    api_key = _env_value("QDRANT_API_KEY")
    if api_key:
        headers["api-key"] = api_key
    try:
        response = httpx.post(
            f"{url}/collections/{collection}/points/search",
            headers=headers,
            json={
                "vector": _hash_vector(query),
                "limit": top_k,
                "with_payload": True,
            },
            timeout=5.0,
        )
        response.raise_for_status()
        items = response.json().get("result", [])
        results: list[dict[str, Any]] = []
        for item in items:
            payload = item.get("payload") if isinstance(item, dict) else None
            if not isinstance(payload, dict):
                continue
            product_id = payload.get("product_id") or payload.get("id")
            if not product_id:
                continue
            results.append(
                {
                    "product_id": str(product_id),
                    "score": float(item.get("score") or 0.0),
                    "source": "qdrant",
                }
            )
        return results
    except Exception:
        return []


def _milvus_semantic_search(query: str, top_k: int) -> list[dict[str, Any]]:
    query_vector = embed_query(query)
    if not query_vector:
        return []
    try:
        hits = MilvusRestClient(timeout_seconds=5.0).search(query_vector, top_k=top_k)
        return [
            {
                "product_id": hit.product_id,
                "score": hit.score,
                "source": hit.source,
            }
            for hit in hits
        ]
    except (MilvusError, Exception):
        return []


def semantic_search(query: str, top_k: int = 20) -> list[dict[str, Any]]:
    backend = vector_backend_name()
    if not query.strip() or top_k <= 0:
        return []
    if backend == "none":
        return []
    if backend == "local":
        return _local_semantic_search(query, top_k)
    if backend == "qdrant":
        return _qdrant_semantic_search(query, top_k)
    if backend == "milvus":
        return _milvus_semantic_search(query, top_k)
    return []
