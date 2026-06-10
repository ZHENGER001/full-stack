from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.agent_tools import SearchProductsResult, SearchProductsVerification
from app.query_cache import MultiLevelQueryCache, QueryCache, SQLiteQueryCache, make_query_cache_key
from app.schemas import ProductCard


def sample_result(product_id: str = "p1") -> SearchProductsResult:
    product = ProductCard(
        id=product_id,
        title="测试商品",
        brand="测试品牌",
        category="食品饮料",
        subcategory="零食",
        price=19.9,
        rating=4.8,
        image_path="/images/p1.jpg",
        stock=10,
    )
    return SearchProductsResult(
        status="ok",
        products=[product],
        alternatives=[],
        diagnostics={"pipeline": ["test"]},
        verification=SearchProductsVerification(status="pass", accepted_count=1, final_product_ids=[product_id]),
    )


class QueryCacheTest(unittest.TestCase):
    def test_cache_key_is_stable_for_dict_order(self) -> None:
        key1 = make_query_cache_key(
            " 推荐 零食 ",
            3,
            {"price": {"max": 100}, "required_terms": ["零食"]},
            {"allow_dense_only": False, "match_mode": "normal"},
        )
        key2 = make_query_cache_key(
            "推荐 零食",
            3,
            {"required_terms": ["零食"], "price": {"max": 100}},
            {"match_mode": "normal", "allow_dense_only": False},
        )

        self.assertEqual(key1, key2)

    def test_get_returns_cached_result_with_hit_diagnostics(self) -> None:
        cache = QueryCache(max_size=2, ttl_seconds=60)
        key = make_query_cache_key("推荐零食", 3, {}, {})
        cache.set(key, sample_result())

        cached = cache.get(key)

        self.assertIsNotNone(cached)
        self.assertEqual(cached.products[0].id, "p1")
        self.assertTrue(cached.diagnostics["cache"]["hit"])

    def test_cache_evicts_lru_entry(self) -> None:
        cache = QueryCache(max_size=1, ttl_seconds=60)
        key1 = make_query_cache_key("推荐零食", 3, {}, {})
        key2 = make_query_cache_key("推荐手机", 3, {}, {})

        cache.set(key1, sample_result("p1"))
        cache.set(key2, sample_result("p2"))

        self.assertIsNone(cache.get(key1))
        self.assertEqual(cache.get(key2).products[0].id, "p2")

    def test_cache_expires_entries(self) -> None:
        cache = QueryCache(max_size=2, ttl_seconds=1)
        key = make_query_cache_key("推荐零食", 3, {}, {})
        cache.set(key, sample_result())

        with patch("app.query_cache.time.time", return_value=9999999999):
            self.assertIsNone(cache.get(key))

    def test_sqlite_cache_persists_across_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "cache.db")
            key = make_query_cache_key("推荐零食", 3, {}, {})

            first = SQLiteQueryCache(database_path=db_path, ttl_seconds=60, max_size=10)
            first.set(key, sample_result("p_sqlite"), query_text="推荐零食")

            second = SQLiteQueryCache(database_path=db_path, ttl_seconds=60, max_size=10)
            cached = second.get(key)

        self.assertIsNotNone(cached)
        self.assertEqual(cached.products[0].id, "p_sqlite")
        self.assertTrue(cached.diagnostics["cache"]["hit"])
        self.assertEqual(cached.diagnostics["cache"]["level"], "sqlite")

    def test_multilevel_cache_promotes_sqlite_hit_to_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "cache.db")
            key = make_query_cache_key("推荐零食", 3, {}, {})
            sqlite_cache = SQLiteQueryCache(database_path=db_path, ttl_seconds=60, max_size=10)
            sqlite_cache.set(key, sample_result("p_l2"), query_text="推荐零食")
            memory_cache = QueryCache(max_size=2, ttl_seconds=60)
            cache = MultiLevelQueryCache(memory_cache, sqlite_cache)

            first = cache.get(key)
            second = cache.get(key)

        self.assertEqual(first.diagnostics["cache"]["level"], "sqlite")
        self.assertEqual(second.diagnostics["cache"]["level"], "memory")


if __name__ == "__main__":
    unittest.main()
