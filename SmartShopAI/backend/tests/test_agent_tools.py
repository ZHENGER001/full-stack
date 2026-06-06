from __future__ import annotations

import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.agent_tools import SearchProductsInput, call_search_products_tool
from app.schemas import ProductCard


class SearchProductsToolTest(unittest.TestCase):
    def test_wraps_hybrid_rag_result(self) -> None:
        product = ProductCard(
            id="p1",
            title="Test Phone",
            brand="TestBrand",
            category="Digital",
            subcategory="Phone",
            price=999,
            rating=4.5,
            image_path="/api/product-thumbnails/p1.jpg",
        )
        diagnostics = {
            "verifier": {
                "accepted_count": 1,
                "rejected_count": 2,
                "final_product_ids": ["p1"],
            },
            "fallback": {"used": False},
        }

        with patch("app.agent_tools.search_products_for_agent_with_diagnostics") as search:
            search.return_value = ([product], diagnostics)
            result = call_search_products_tool(object(), SearchProductsInput(query="phone", top_k=3))

        search.assert_called_once()
        self.assertEqual(search.call_args.args[1], "phone")
        self.assertEqual(search.call_args.kwargs["limit"], 3)
        self.assertEqual(result.tool_name, "search_products")
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.products[0].id, "p1")
        self.assertEqual(result.verification.status, "pass")
        self.assertEqual(result.verification.rejected_count, 2)

    def test_marks_fallback_results_as_degraded(self) -> None:
        product = ProductCard(
            id="p2",
            title="Fallback Product",
            brand="FallbackBrand",
            price=100,
            rating=4.0,
            image_path="/api/product-thumbnails/p2.jpg",
        )

        with patch("app.agent_tools.search_products_for_agent_with_diagnostics") as search:
            search.return_value = ([product], {"fallback": {"used": True}})
            result = call_search_products_tool(object(), SearchProductsInput(query="cheap", top_k=1))

        self.assertEqual(result.status, "degraded")
        self.assertEqual(result.verification.status, "degraded")
        self.assertEqual(result.verification.final_product_ids, ["p2"])

    def test_marks_empty_results(self) -> None:
        with patch("app.agent_tools.search_products_for_agent_with_diagnostics") as search:
            search.return_value = ([], {"verifier": {"accepted_count": 0, "rejected_count": 0}})
            result = call_search_products_tool(object(), SearchProductsInput(query="nothing", top_k=3))

        self.assertEqual(result.status, "empty")
        self.assertEqual(result.products, [])
        self.assertEqual(result.verification.status, "empty")

    def test_exposes_alternatives_separately_from_products(self) -> None:
        alternative = ProductCard(
            id="p3",
            title="Near Match",
            brand="AltBrand",
            price=59,
            rating=4.0,
            image_path="/api/product-thumbnails/p3.jpg",
        )
        diagnostics = {
            "verifier": {"accepted_count": 0, "rejected_count": 2},
            "alternatives": {"used": True, "reason": "price_relaxed", "products": [alternative.model_dump(mode="json")]},
        }

        with patch("app.agent_tools.search_products_for_agent_with_diagnostics") as search:
            search.return_value = ([], diagnostics)
            result = call_search_products_tool(object(), SearchProductsInput(query="cheap snack", top_k=3))

        self.assertEqual(result.status, "empty")
        self.assertEqual(result.products, [])
        self.assertEqual([product.id for product in result.alternatives], ["p3"])

    def test_rejects_blank_query(self) -> None:
        with self.assertRaises(ValidationError):
            SearchProductsInput(query="   ")

    def test_passes_constraints_and_retrieval_policy(self) -> None:
        with patch("app.agent_tools.search_products_for_agent_with_diagnostics") as search:
            search.return_value = ([], {"verifier": {"accepted_count": 0, "rejected_count": 0}})
            call_search_products_tool(
                object(),
                SearchProductsInput(
                    query="手柄",
                    top_k=3,
                    constraints={"required_terms": ["手柄"]},
                    retrieval_policy={"match_mode": "exact_or_none"},
                ),
            )

        self.assertEqual(search.call_args.kwargs["constraints"], {"required_terms": ["手柄"]})
        self.assertEqual(search.call_args.kwargs["retrieval_policy"], {"match_mode": "exact_or_none"})


if __name__ == "__main__":
    unittest.main()
