from __future__ import annotations

import os

from .config import BASE_DIR, _load_env_file


def env_value(name: str, default: str | None = None) -> str | None:
    env_file = _load_env_file(BASE_DIR / ".env")
    return os.getenv(name) or env_file.get(name) or default


def timeout_seconds(name: str, default: float, *, minimum: float = 1.0, maximum: float = 60.0) -> float:
    raw_value = env_value(name, str(default))
    try:
        value = float(raw_value or default)
    except ValueError:
        value = default
    return min(max(value, minimum), maximum)


def llm_timeout_seconds() -> float:
    return timeout_seconds("LLM_TIMEOUT_SECONDS", 12.0, minimum=3.0, maximum=60.0)


def llm_connect_timeout_seconds() -> float:
    return timeout_seconds("LLM_CONNECT_TIMEOUT_SECONDS", 3.0, minimum=1.0, maximum=15.0)


def embedding_timeout_seconds() -> float:
    return timeout_seconds("EMBEDDING_TIMEOUT_SECONDS", 5.0, minimum=1.0, maximum=30.0)


def embedding_connect_timeout_seconds() -> float:
    return timeout_seconds("EMBEDDING_CONNECT_TIMEOUT_SECONDS", 3.0, minimum=1.0, maximum=15.0)


def milvus_timeout_seconds() -> float:
    return timeout_seconds("MILVUS_TIMEOUT_SECONDS", 5.0, minimum=1.0, maximum=30.0)


def milvus_connect_timeout_seconds() -> float:
    return timeout_seconds("MILVUS_CONNECT_TIMEOUT_SECONDS", 3.0, minimum=1.0, maximum=15.0)
