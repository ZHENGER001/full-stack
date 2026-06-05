from __future__ import annotations

from typing import Any

from .embedding_client import embed_query
from .milvus_client import MilvusError, MilvusRestClient


def milvus_semantic_search(query: str, top_k: int = 20) -> list[dict[str, Any]]:
    if not query.strip() or top_k <= 0:
        return []
    query_vector = embed_query(query)
    if not query_vector:
        return []
    try:
        hits = MilvusRestClient(timeout_seconds=5.0).search(query_vector, top_k=top_k)
    except (MilvusError, Exception):
        return []
    return [
        {
            "product_id": hit.product_id,
            "score": hit.score,
            "source": hit.source,
        }
        for hit in hits
    ]
