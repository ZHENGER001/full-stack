from __future__ import annotations

import threading
from contextlib import asynccontextmanager, contextmanager
from typing import AsyncIterator, Iterator

from .timeouts import env_value


def concurrency_limit(name: str, default: int, *, minimum: int = 1, maximum: int = 64) -> int:
    raw_value = env_value(name, str(default))
    try:
        value = int(raw_value or default)
    except ValueError:
        value = default
    return min(max(value, minimum), maximum)


_llm_semaphore: threading.BoundedSemaphore | None = None
_llm_semaphore_limit: int | None = None
_embedding_semaphore: threading.BoundedSemaphore | None = None
_embedding_semaphore_limit: int | None = None
_milvus_semaphore: threading.BoundedSemaphore | None = None
_milvus_semaphore_limit: int | None = None


def _llm_limit() -> int:
    return concurrency_limit("LLM_MAX_CONCURRENCY", 4)


def _embedding_limit() -> int:
    return concurrency_limit("EMBEDDING_MAX_CONCURRENCY", 4)


def _milvus_limit() -> int:
    return concurrency_limit("MILVUS_MAX_CONCURRENCY", 8)


@asynccontextmanager
async def llm_slot() -> AsyncIterator[None]:
    global _llm_semaphore, _llm_semaphore_limit
    limit = _llm_limit()
    if _llm_semaphore is None or _llm_semaphore_limit != limit:
        _llm_semaphore = threading.BoundedSemaphore(limit)
        _llm_semaphore_limit = limit
    _llm_semaphore.acquire()
    try:
        yield
    finally:
        _llm_semaphore.release()


@contextmanager
def sync_llm_slot() -> Iterator[None]:
    global _llm_semaphore, _llm_semaphore_limit
    limit = _llm_limit()
    if _llm_semaphore is None or _llm_semaphore_limit != limit:
        _llm_semaphore = threading.BoundedSemaphore(limit)
        _llm_semaphore_limit = limit
    with _llm_semaphore:
        yield


@contextmanager
def embedding_slot() -> Iterator[None]:
    global _embedding_semaphore, _embedding_semaphore_limit
    limit = _embedding_limit()
    if _embedding_semaphore is None or _embedding_semaphore_limit != limit:
        _embedding_semaphore = threading.BoundedSemaphore(limit)
        _embedding_semaphore_limit = limit
    with _embedding_semaphore:
        yield


@contextmanager
def milvus_slot() -> Iterator[None]:
    global _milvus_semaphore, _milvus_semaphore_limit
    limit = _milvus_limit()
    if _milvus_semaphore is None or _milvus_semaphore_limit != limit:
        _milvus_semaphore = threading.BoundedSemaphore(limit)
        _milvus_semaphore_limit = limit
    with _milvus_semaphore:
        yield
