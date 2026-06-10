from __future__ import annotations

import unittest
from unittest.mock import patch

from app.agent_tools import SearchProductsResult, SearchProductsVerification
from app.agentic_rag import retrieve_products_for_turn
from app.query_cache import QueryCache
from app.schemas import ProductCard


def sample_result() -> SearchProductsResult:
    product = ProductCard(
        id="p_cache",
        title="缓存商品",
        brand="测试品牌",
        category="食品饮料",
        subcategory="零食",
        price=29.0,
        rating=4.6,
        image_path="/images/cache.jpg",
        stock=8,
    )
    return SearchProductsResult(
        status="ok",
        products=[product],
        alternatives=[],
        diagnostics={"source": "mock"},
        verification=SearchProductsVerification(status="pass", accepted_count=1, final_product_ids=["p_cache"]),
    )


def empty_result() -> SearchProductsResult:
    return SearchProductsResult(
        status="empty",
        products=[],
        alternatives=[],
        diagnostics={"source": "mock"},
        verification=SearchProductsVerification(status="empty", accepted_count=0, final_product_ids=[]),
    )


class AgenticCacheTest(unittest.TestCase):
    def test_retrieve_products_for_turn_uses_hot_query_cache(self) -> None:
        cache = QueryCache(max_size=8, ttl_seconds=60)
        calls = {"count": 0}

        def fake_search_tool(*_args, **_kwargs):
            calls["count"] += 1
            return sample_result()

        with (
            patch("app.agentic_rag.query_cache_enabled", return_value=True),
            patch("app.agentic_rag.default_query_cache", return_value=cache),
            patch("app.agentic_rag.call_search_products_tool", side_effect=fake_search_tool),
        ):
            first = retrieve_products_for_turn(None, "推荐零食", [], plan=None, top_k=3)
            second = retrieve_products_for_turn(None, "推荐零食", [], plan=None, top_k=3)

        self.assertEqual(calls["count"], 1)
        self.assertFalse(first.search_result.diagnostics["cache"]["hit"])
        self.assertTrue(second.search_result.diagnostics["cache"]["hit"])
        self.assertEqual(second.search_result.products[0].id, "p_cache")

    def test_retrieve_products_for_turn_does_not_cache_empty_result(self) -> None:
        cache = QueryCache(max_size=8, ttl_seconds=60)
        calls = {"count": 0}

        def fake_search_tool(*_args, **_kwargs):
            calls["count"] += 1
            return empty_result()

        with (
            patch("app.agentic_rag.query_cache_enabled", return_value=True),
            patch("app.agentic_rag.default_query_cache", return_value=cache),
            patch("app.agentic_rag.call_search_products_tool", side_effect=fake_search_tool),
        ):
            first = retrieve_products_for_turn(None, "鎺ㄨ崘涓嶅瓨鍦ㄧ殑鍟嗗搧", [], plan=None, top_k=3)
            second = retrieve_products_for_turn(None, "鎺ㄨ崘涓嶅瓨鍦ㄧ殑鍟嗗搧", [], plan=None, top_k=3)

        self.assertEqual(calls["count"], 2)
        self.assertFalse(first.search_result.diagnostics["cache"]["hit"])
        self.assertFalse(first.search_result.diagnostics["cache"]["stored"])
        self.assertFalse(second.search_result.diagnostics["cache"]["hit"])
        self.assertFalse(second.search_result.diagnostics["cache"]["stored"])


if __name__ == "__main__":
    unittest.main()
