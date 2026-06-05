from __future__ import annotations

import unittest

from app.query_parser import parse_user_filters
from app.retrieval import _build_document
from app.verifier import verify_products


class QueryConstraintTest(unittest.TestCase):
    def test_watch_is_catalog_only_explicit_subcategory(self) -> None:
        filters = parse_user_filters("\u624b\u8868", [])

        self.assertTrue(filters["explicit_category"])
        self.assertEqual(filters["target_categories"], ["\u6570\u7801\u7535\u5b50"])
        self.assertEqual(filters["target_subcategories"], ["\u667a\u80fd\u624b\u8868"])
        self.assertEqual(filters["retrieval_scope"], "catalog_only")

    def test_evidence_terms_enable_full_evidence(self) -> None:
        filters = parse_user_filters("\u8fd9\u6b3e\u8033\u673a\u8bc4\u8bba\u600e\u4e48\u6837", [])

        self.assertEqual(filters["retrieval_scope"], "full_evidence")

    def test_catalog_document_excludes_reviews_and_faq(self) -> None:
        row = {
            "title": "AirPods",
            "brand": "Apple",
            "category": "\u6570\u7801\u7535\u5b50",
            "subcategory": "\u771f\u65e0\u7ebf\u8033\u673a",
            "marketing_description": "\u4e3b\u52a8\u964d\u566a\u8033\u673a",
            "sku_text": "\u767d\u8272",
            "review_text": "\u7528\u6237\u8bf4\u8dd1\u6b65\u4e0d\u7528\u62ac\u624b\u770b\u624b\u8868",
            "faq_text": "\u652f\u6301\u540c\u6b65\u624b\u8868",
            "chunk_text": "\u624b\u8868\u76f8\u5173\u95ee\u7b54",
        }

        catalog_document = _build_document(row, include_evidence=False)
        full_document = _build_document(row, include_evidence=True)

        self.assertNotIn("\u62ac\u624b\u770b\u624b\u8868", catalog_document)
        self.assertNotIn("\u652f\u6301\u540c\u6b65\u624b\u8868", catalog_document)
        self.assertIn("\u62ac\u624b\u770b\u624b\u8868", full_document)
        self.assertIn("\u652f\u6301\u540c\u6b65\u624b\u8868", full_document)

    def test_verifier_does_not_use_reviews_for_subcategory_match(self) -> None:
        filters = {
            "target_categories": ["\u6570\u7801\u7535\u5b50"],
            "target_subcategories": ["\u667a\u80fd\u624b\u8868"],
            "required_terms": ["\u624b\u8868"],
            "explicit_category": True,
        }
        product = {
            "id": "p1",
            "title": "AirPods Pro",
            "brand": "Apple",
            "category": "\u6570\u7801\u7535\u5b50",
            "subcategory": "\u771f\u65e0\u7ebf\u8033\u673a",
            "price": 1899,
            "stock": 10,
            "marketing_description": "\u8fd0\u52a8\u5fc3\u7387\u8033\u673a\u4f53\u9a8c",
            "sku_text": "\u8033\u673a\u914d\u4ef6",
            "review_text": "\u8dd1\u6b65\u65f6\u4e0d\u7528\u62ac\u624b\u770b\u624b\u8868",
            "faq_text": "\u53ef\u4ee5\u540c\u6b65 Apple Watch",
        }

        result = verify_products([product], filters, limit=1)

        self.assertEqual(result.products, [])
        self.assertEqual(result.diagnostics["rejected"][0]["reason"], "subcategory_mismatch")

    def test_verifier_does_not_use_description_for_subcategory_match(self) -> None:
        filters = {
            "target_categories": ["\u6570\u7801\u7535\u5b50"],
            "target_subcategories": ["\u771f\u65e0\u7ebf\u8033\u673a"],
            "required_terms": ["\u8033\u673a"],
            "explicit_category": True,
        }
        product = {
            "id": "p1",
            "title": "MatePad Pro",
            "brand": "\u534e\u4e3a",
            "category": "\u6570\u7801\u7535\u5b50",
            "subcategory": "\u5e73\u677f\u7535\u8111",
            "price": 3999,
            "stock": 10,
            "marketing_description": "\u53ef\u642d\u914d\u84dd\u7259\u8033\u673a\u4f7f\u7528",
        }

        result = verify_products([product], filters, limit=1)

        self.assertEqual(result.products, [])
        self.assertEqual(result.diagnostics["rejected"][0]["reason"], "subcategory_mismatch")

    def test_verifier_allows_core_catalog_text_match(self) -> None:
        filters = {
            "target_categories": ["\u6570\u7801\u7535\u5b50"],
            "target_subcategories": ["\u667a\u80fd\u624b\u8868"],
            "required_terms": ["\u624b\u8868", "watch"],
            "explicit_category": True,
        }
        product = {
            "id": "p1",
            "title": "Apple Watch \u667a\u80fd\u8155\u8868",
            "brand": "Apple",
            "category": "\u6570\u7801\u7535\u5b50",
            "subcategory": "\u667a\u80fd\u7a7f\u6234",
            "price": 2999,
            "stock": 10,
        }

        result = verify_products([product], filters, limit=1)

        self.assertEqual([item["id"] for item in result.products], ["p1"])


if __name__ == "__main__":
    unittest.main()
