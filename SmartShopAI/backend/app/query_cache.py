from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from .agent_tools import SearchProductsResult
from .config import get_settings


DEFAULT_CACHE_TTL_SECONDS = 300
DEFAULT_CACHE_MAX_SIZE = 128


@dataclass
class QueryCacheEntry:
    payload: dict[str, Any]
    created_at: float


class QueryCache:
    def __init__(self, max_size: int = DEFAULT_CACHE_MAX_SIZE, ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS) -> None:
        self.max_size = max(max_size, 1)
        self.ttl_seconds = max(ttl_seconds, 1)
        self._items: OrderedDict[str, QueryCacheEntry] = OrderedDict()

    def get(self, key: str) -> SearchProductsResult | None:
        entry = self._items.get(key)
        if entry is None:
            return None
        if time.time() - entry.created_at > self.ttl_seconds:
            self._items.pop(key, None)
            return None
        self._items.move_to_end(key)
        try:
            result = SearchProductsResult.model_validate(entry.payload)
        except ValidationError:
            self._items.pop(key, None)
            return None
        diagnostics = dict(result.diagnostics or {})
        diagnostics["cache"] = {"hit": True, "key": key, "age_seconds": round(time.time() - entry.created_at, 3)}
        return result.model_copy(update={"diagnostics": diagnostics})

    def set(self, key: str, result: SearchProductsResult, query_text: str = "") -> None:
        diagnostics = dict(result.diagnostics or {})
        diagnostics["cache"] = {"hit": False, "key": key, "stored": True}
        payload = result.model_copy(update={"diagnostics": diagnostics}).model_dump(mode="json")
        self._items[key] = QueryCacheEntry(payload=payload, created_at=time.time())
        self._items.move_to_end(key)
        self._evict_expired()
        while len(self._items) > self.max_size:
            self._items.popitem(last=False)

    def clear(self) -> None:
        self._items.clear()

    def stats(self) -> dict[str, int]:
        self._evict_expired()
        return {"size": len(self._items), "max_size": self.max_size, "ttl_seconds": self.ttl_seconds}

    def _evict_expired(self) -> None:
        now = time.time()
        expired = [key for key, entry in self._items.items() if now - entry.created_at > self.ttl_seconds]
        for key in expired:
            self._items.pop(key, None)


class SQLiteQueryCache:
    def __init__(self, database_path: str | None = None, ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS, max_size: int = 1000) -> None:
        self.database_path = database_path or str(get_settings().database_path)
        self.ttl_seconds = max(ttl_seconds, 1)
        self.max_size = max(max_size, 1)
        self._ensure_table()

    def get(self, key: str) -> SearchProductsResult | None:
        now = time.time()
        try:
            with self._session() as conn:
                row = conn.execute(
                    "SELECT payload_json, created_at, expires_at FROM query_cache_entries WHERE cache_key = ?",
                    (key,),
                ).fetchone()
                if row is None:
                    return None
                if float(row["expires_at"]) <= now:
                    conn.execute("DELETE FROM query_cache_entries WHERE cache_key = ?", (key,))
                    return None
                conn.execute(
                    "UPDATE query_cache_entries SET hit_count = hit_count + 1, updated_at = CURRENT_TIMESTAMP WHERE cache_key = ?",
                    (key,),
                )
                payload = json.loads(str(row["payload_json"]))
        except (sqlite3.Error, json.JSONDecodeError, OSError):
            return None
        try:
            result = SearchProductsResult.model_validate(payload)
        except ValidationError:
            self.delete(key)
            return None
        diagnostics = dict(result.diagnostics or {})
        diagnostics["cache"] = {"hit": True, "level": "sqlite", "key": key, "age_seconds": round(now - float(row["created_at"]), 3)}
        return result.model_copy(update={"diagnostics": diagnostics})

    def set(self, key: str, result: SearchProductsResult, query_text: str = "") -> None:
        now = time.time()
        diagnostics = dict(result.diagnostics or {})
        diagnostics["cache"] = {"hit": False, "level": "sqlite", "key": key, "stored": True}
        payload = result.model_copy(update={"diagnostics": diagnostics}).model_dump(mode="json")
        try:
            with self._session() as conn:
                conn.execute(
                    """
                    INSERT INTO query_cache_entries(cache_key, query_text, payload_json, created_at, expires_at, hit_count, updated_at)
                    VALUES (?, ?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
                    ON CONFLICT(cache_key) DO UPDATE SET
                        query_text = excluded.query_text,
                        payload_json = excluded.payload_json,
                        created_at = excluded.created_at,
                        expires_at = excluded.expires_at,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (key, query_text, json.dumps(payload, ensure_ascii=False), now, now + self.ttl_seconds),
                )
                self._evict(conn, now)
        except (sqlite3.Error, OSError):
            return

    def delete(self, key: str) -> None:
        try:
            with self._session() as conn:
                conn.execute("DELETE FROM query_cache_entries WHERE cache_key = ?", (key,))
        except (sqlite3.Error, OSError):
            return

    def clear(self) -> None:
        try:
            with self._session() as conn:
                conn.execute("DELETE FROM query_cache_entries")
        except (sqlite3.Error, OSError):
            return

    def stats(self) -> dict[str, int]:
        try:
            with self._session() as conn:
                self._evict(conn, time.time())
                row = conn.execute("SELECT COUNT(*) AS size FROM query_cache_entries").fetchone()
                size = int(row["size"] if row else 0)
        except (sqlite3.Error, OSError):
            size = 0
        return {"size": size, "max_size": self.max_size, "ttl_seconds": self.ttl_seconds}

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _ensure_table(self) -> None:
        try:
            with self._session() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS query_cache_entries (
                        cache_key TEXT PRIMARY KEY,
                        query_text TEXT NOT NULL DEFAULT '',
                        payload_json TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        expires_at REAL NOT NULL,
                        hit_count INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_query_cache_expires ON query_cache_entries(expires_at)")
        except (sqlite3.Error, OSError):
            return

    def _evict(self, conn: sqlite3.Connection, now: float) -> None:
        conn.execute("DELETE FROM query_cache_entries WHERE expires_at <= ?", (now,))
        rows = conn.execute(
            "SELECT cache_key FROM query_cache_entries ORDER BY updated_at DESC, created_at DESC LIMIT -1 OFFSET ?",
            (self.max_size,),
        ).fetchall()
        if rows:
            conn.executemany("DELETE FROM query_cache_entries WHERE cache_key = ?", [(row["cache_key"],) for row in rows])


class MultiLevelQueryCache:
    def __init__(self, memory_cache: QueryCache, persistent_cache: SQLiteQueryCache | None = None) -> None:
        self.memory_cache = memory_cache
        self.persistent_cache = persistent_cache

    def get(self, key: str) -> SearchProductsResult | None:
        result = self.memory_cache.get(key)
        if result is not None:
            diagnostics = dict(result.diagnostics or {})
            cache_diag = dict(diagnostics.get("cache") or {})
            cache_diag["level"] = "memory"
            diagnostics["cache"] = cache_diag
            return result.model_copy(update={"diagnostics": diagnostics})
        if self.persistent_cache is None:
            return None
        result = self.persistent_cache.get(key)
        if result is None:
            return None
        self.memory_cache.set(key, result)
        return result

    def set(self, key: str, result: SearchProductsResult, query_text: str = "") -> None:
        self.memory_cache.set(key, result)
        if self.persistent_cache is not None:
            self.persistent_cache.set(key, result, query_text=query_text)

    def clear(self) -> None:
        self.memory_cache.clear()
        if self.persistent_cache is not None:
            self.persistent_cache.clear()

    def stats(self) -> dict[str, dict[str, int]]:
        return {
            "memory": self.memory_cache.stats(),
            "sqlite": self.persistent_cache.stats() if self.persistent_cache is not None else {"size": 0, "max_size": 0, "ttl_seconds": 0},
        }


def query_cache_enabled() -> bool:
    return _bool_env("HOT_QUERY_CACHE_ENABLED", True)


def make_query_cache_key(
    query: str,
    top_k: int,
    constraints: dict[str, Any] | None,
    retrieval_policy: dict[str, Any] | None,
) -> str:
    payload = {
        "query": " ".join((query or "").strip().lower().split()),
        "top_k": int(top_k),
        "constraints": _stable_jsonable(constraints or {}),
        "retrieval_policy": _stable_jsonable(retrieval_policy or {}),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def default_query_cache() -> MultiLevelQueryCache:
    global _DEFAULT_QUERY_CACHE
    try:
        return _DEFAULT_QUERY_CACHE
    except NameError:
        ttl_seconds = _int_env("HOT_QUERY_CACHE_TTL_SECONDS", DEFAULT_CACHE_TTL_SECONDS)
        memory_cache = QueryCache(max_size=_int_env("HOT_QUERY_CACHE_MAX_SIZE", DEFAULT_CACHE_MAX_SIZE), ttl_seconds=ttl_seconds)
        persistent_cache = (
            SQLiteQueryCache(ttl_seconds=_int_env("HOT_QUERY_CACHE_SQLITE_TTL_SECONDS", ttl_seconds), max_size=_int_env("HOT_QUERY_CACHE_SQLITE_MAX_SIZE", 1000))
            if _bool_env("HOT_QUERY_CACHE_SQLITE_ENABLED", True)
            else None
        )
        _DEFAULT_QUERY_CACHE = MultiLevelQueryCache(memory_cache, persistent_cache)
        return _DEFAULT_QUERY_CACHE


def _stable_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _stable_jsonable(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_stable_jsonable(item) for item in value]
    return value


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        return max(int(raw), 1) if raw is not None else default
    except ValueError:
        return default
