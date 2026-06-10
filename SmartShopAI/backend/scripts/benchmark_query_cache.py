from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import dataclass

from app.agentic_rag import retrieve_products_for_turn
from app.database import import_dataset_if_empty, initialize_database, get_connection
from app.query_cache import SQLiteQueryCache, default_query_cache, make_query_cache_key


@dataclass(frozen=True)
class RunResult:
    label: str
    elapsed_ms: float
    cache_hit: bool
    cache_level: str
    product_count: int
    product_ids: list[str]


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark SmartShopAI hot query cache.")
    parser.add_argument("--query", default="推荐500以内篮球鞋，不要李宁")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--repeat", type=int, default=1, help="Extra memory-hit repeats after sqlite warmup.")
    parser.add_argument("--clear-sqlite", action="store_true", help="Clear persisted SQLite cache before running.")
    args = parser.parse_args()

    initialize_database()
    import_dataset_if_empty()

    conn = get_connection()
    try:
        query = args.query
        top_k = args.top_k
        sqlite_cache = SQLiteQueryCache()
        if args.clear_sqlite:
            sqlite_cache.clear()
        cache_key = make_query_cache_key(query, top_k, {}, {})
        default_query_cache().memory_cache.clear()
        sqlite_cache.delete(cache_key)

        miss = _measure("cold_miss", conn, query, top_k)
        memory_hit = _measure("memory_hit", conn, query, top_k)

        # Simulate a backend restart: L1 is empty while SQLite L2 is preserved.
        from app import query_cache as query_cache_module

        query_cache_module.default_query_cache().memory_cache.clear()
        sqlite_hit = _measure("sqlite_hit_after_memory_clear", conn, query, top_k)

        extra_hits = [_measure(f"memory_hit_repeat_{index + 1}", conn, query, top_k) for index in range(max(args.repeat, 0))]
        rows = [miss, memory_hit, sqlite_hit, *extra_hits]
        _print_table(rows)
        _print_summary(rows)
    finally:
        conn.close()


def _measure(label: str, conn, query: str, top_k: int) -> RunResult:
    start = time.perf_counter()
    result = retrieve_products_for_turn(conn, query, [], plan=None, top_k=top_k).search_result
    elapsed_ms = (time.perf_counter() - start) * 1000
    cache_diag = result.diagnostics.get("cache") if isinstance(result.diagnostics, dict) else {}
    cache_diag = cache_diag if isinstance(cache_diag, dict) else {}
    return RunResult(
        label=label,
        elapsed_ms=round(elapsed_ms, 2),
        cache_hit=bool(cache_diag.get("hit")),
        cache_level=str(cache_diag.get("level") or "-"),
        product_count=len(result.products),
        product_ids=[product.id for product in result.products],
    )


def _print_table(rows: list[RunResult]) -> None:
    print("label | cache | level | elapsed_ms | products | product_ids")
    print("----- | ----- | ----- | ---------- | -------- | -----------")
    for row in rows:
        print(
            f"{row.label} | {'hit' if row.cache_hit else 'miss'} | {row.cache_level} | "
            f"{row.elapsed_ms:.2f} | {row.product_count} | {','.join(row.product_ids)}"
        )


def _print_summary(rows: list[RunResult]) -> None:
    miss = rows[0]
    hits = [row for row in rows[1:] if row.cache_hit]
    avg_hit_ms = statistics.mean(row.elapsed_ms for row in hits) if hits else 0.0
    saved_ms = miss.elapsed_ms - avg_hit_ms if hits else 0.0
    speedup = round(miss.elapsed_ms / avg_hit_ms, 2) if avg_hit_ms > 0 else 0.0
    print(
        "summary:",
        json.dumps(
            {
                "cold_miss_ms": miss.elapsed_ms,
                "avg_hit_ms": round(avg_hit_ms, 2),
                "saved_ms": round(saved_ms, 2),
                "speedup": speedup,
                "hit_runs": len(hits),
            },
            ensure_ascii=False,
        ),
    )


if __name__ == "__main__":
    main()
