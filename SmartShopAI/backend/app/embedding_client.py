from __future__ import annotations

import math
import os
from typing import Any

import httpx

from .config import BASE_DIR, _load_env_file


class EmbeddingError(RuntimeError):
    """Raised when the optional embedding service is unavailable."""


def _env_value(name: str, default: str | None = None) -> str | None:
    env_file = _load_env_file(BASE_DIR / ".env")
    return os.getenv(name) or env_file.get(name) or default


def embedding_provider_name() -> str:
    return (_env_value("EMBEDDING_PROVIDER", "openai-compatible") or "openai-compatible").strip().lower()


def embedding_model_name() -> str:
    return _env_value("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-4B") or "Qwen/Qwen3-Embedding-4B"


def embedding_dimensions() -> int | None:
    raw_value = _env_value("EMBEDDING_DIMENSIONS")
    if not raw_value:
        return None
    try:
        value = int(raw_value)
    except ValueError:
        return None
    return value if value > 0 else None


def _timeout_seconds() -> float:
    raw_value = _env_value("EMBEDDING_TIMEOUT_SECONDS", "30")
    try:
        return max(float(raw_value or "30"), 5.0)
    except ValueError:
        return 30.0


def _embedding_base_url() -> str:
    return (_env_value("EMBEDDING_BASE_URL") or "").rstrip("/")


def _embedding_api_key() -> str | None:
    value = _env_value("EMBEDDING_API_KEY")
    if not value or value.strip().lower() in {"empty", "none", "null"}:
        return None
    return value


def _extract_vectors(data: dict[str, Any], expected_count: int) -> list[list[float]]:
    raw_items = data.get("data")
    if not isinstance(raw_items, list):
        raise EmbeddingError("Embedding response has no data array")
    sorted_items = sorted(
        [item for item in raw_items if isinstance(item, dict)],
        key=lambda item: int(item.get("index", 0)),
    )
    vectors: list[list[float]] = []
    for item in sorted_items:
        raw_vector = item.get("embedding")
        if not isinstance(raw_vector, list):
            continue
        vector = [float(value) for value in raw_vector]
        if vector:
            vectors.append(_normalize_vector(vector))
    if len(vectors) != expected_count:
        raise EmbeddingError("Embedding response count mismatch")
    return vectors


def _normalize_vector(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return vector
    return [value / norm for value in vector]


def embed_texts(texts: list[str]) -> list[list[float]]:
    provider = embedding_provider_name()
    if provider == "local":
        provider = "openai-compatible"
    if provider not in {"openai", "openai-compatible"}:
        raise EmbeddingError(f"Unsupported embedding provider: {provider}")

    base_url = _embedding_base_url()
    api_key = _embedding_api_key()
    clean_texts = [text.strip() for text in texts if text and text.strip()]
    if not base_url or not clean_texts:
        raise EmbeddingError("Embedding service is not configured")

    payload: dict[str, Any] = {
        "model": embedding_model_name(),
        "input": clean_texts,
    }
    if (_env_value("EMBEDDING_SEND_DIMENSIONS", "false") or "false").lower() == "true":
        dimensions = embedding_dimensions()
        if dimensions:
            payload["dimensions"] = dimensions

    try:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        with httpx.Client(timeout=httpx.Timeout(_timeout_seconds(), connect=8.0), trust_env=False) as client:
            response = client.post(
                f"{base_url}/embeddings",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            return _extract_vectors(response.json(), expected_count=len(clean_texts))
    except EmbeddingError:
        raise
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        raise EmbeddingError(f"Embedding HTTP status {status_code}") from exc
    except httpx.TimeoutException as exc:
        raise EmbeddingError("Embedding request timed out") from exc
    except httpx.HTTPError as exc:
        raise EmbeddingError("Embedding network error") from exc
    except Exception as exc:
        raise EmbeddingError("Embedding generation failed") from exc


def embed_query(text: str) -> list[float] | None:
    try:
        vectors = embed_texts([text])
        return vectors[0] if vectors else None
    except EmbeddingError:
        return None
