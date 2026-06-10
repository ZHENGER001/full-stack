from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .embedding_client import EmbeddingError, embed_texts
from .milvus_client import MilvusError, MilvusRestClient


@dataclass(frozen=True)
class SemanticSearchResult:
    hits: list[dict[str, Any]]
    diagnostics: dict[str, Any]


def milvus_semantic_search(query: str, top_k: int = 20) -> list[dict[str, Any]]:
    return milvus_semantic_search_with_diagnostics(query, top_k).hits


def milvus_semantic_search_with_diagnostics(query: str, top_k: int = 20) -> SemanticSearchResult:
    if not query.strip() or top_k <= 0:
        return SemanticSearchResult(
            hits=[],
            diagnostics={"status": "skipped", "reason": "empty_query"},
        )
    try:
        vectors = embed_texts([query])
    except EmbeddingError as exc:
        return SemanticSearchResult(
            hits=[],
            diagnostics={"status": "degraded", "reason": "embedding_unavailable", "error": str(exc)},
        )
    query_vector = vectors[0] if vectors else None
    if not query_vector:
        return SemanticSearchResult(
            hits=[],
            diagnostics={"status": "degraded", "reason": "embedding_empty"},
        )
    try:
        hits = MilvusRestClient().search(query_vector, top_k=top_k)
    except MilvusError as exc:
        return SemanticSearchResult(
            hits=[],
            diagnostics={"status": "degraded", "reason": "milvus_unavailable", "error": str(exc)},
        )
    except Exception as exc:
        return SemanticSearchResult(
            hits=[],
            diagnostics={"status": "degraded", "reason": "dense_search_failed", "error": exc.__class__.__name__},
        )
    normalized_hits = [
        {
            "product_id": hit.product_id,
            "score": hit.score,
            "source": hit.source,
        }
        for hit in hits
    ]
    return SemanticSearchResult(
        hits=normalized_hits,
        diagnostics={"status": "ok", "reason": None},
    )
