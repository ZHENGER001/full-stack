from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .milvus_client import MilvusError, MilvusRestClient
from .visual_embedding_client import (
    VisualEmbeddingError,
    embed_image_path,
    visual_match_min_score,
    visual_milvus_collection_name,
)


@dataclass(frozen=True)
class VisualSearchResult:
    hits: list[dict[str, Any]]
    diagnostics: dict[str, Any]


def visual_image_search_with_diagnostics(image_path: Path | str | None, top_k: int = 20) -> VisualSearchResult:
    if not image_path or top_k <= 0:
        return VisualSearchResult(
            hits=[],
            diagnostics={"status": "skipped", "reason": "missing_image_path"},
        )
    path = Path(image_path)
    if not path.exists():
        return VisualSearchResult(
            hits=[],
            diagnostics={"status": "skipped", "reason": "image_not_found"},
        )

    try:
        query_vector = embed_image_path(path)
    except VisualEmbeddingError as exc:
        return VisualSearchResult(
            hits=[],
            diagnostics={"status": "degraded", "reason": "visual_embedding_unavailable", "error": str(exc)},
        )
    if not query_vector:
        return VisualSearchResult(
            hits=[],
            diagnostics={"status": "degraded", "reason": "visual_embedding_empty"},
        )

    collection = visual_milvus_collection_name()
    try:
        raw_hits = MilvusRestClient(collection_name=collection).search(query_vector, top_k=top_k)
    except MilvusError as exc:
        return VisualSearchResult(
            hits=[],
            diagnostics={
                "status": "degraded",
                "reason": "visual_milvus_unavailable",
                "collection": collection,
                "error": str(exc),
            },
        )
    except Exception as exc:
        return VisualSearchResult(
            hits=[],
            diagnostics={
                "status": "degraded",
                "reason": "visual_search_failed",
                "collection": collection,
                "error": exc.__class__.__name__,
            },
        )

    min_score = visual_match_min_score()
    hits = [
        {
            "product_id": hit.product_id,
            "score": clamp_score(hit.score),
            "source": "visual_milvus",
        }
        for hit in raw_hits
        if clamp_score(hit.score) >= min_score
    ]
    return VisualSearchResult(
        hits=hits,
        diagnostics={
            "status": "ok",
            "reason": None,
            "collection": collection,
            "raw_count": len(raw_hits),
            "accepted_count": len(hits),
            "min_score": min_score,
        },
    )


def clamp_score(value: float) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(score, 1.0))
