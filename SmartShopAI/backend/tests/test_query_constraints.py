from __future__ import annotations

import unittest

from app.query_parser import has_hard_filters, parse_user_filters
from app.query_router import ParsedQuery
from app.rag import apply_confidence_gate, apply_tool_constraints, build_alternative_products
from app.retrieval import _build_document, _keyword_search, _tokenize
from app.search_document import build_product_search_document
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

    def test_unknown_short_catalog_query_uses_exact_or_none(self) -> None:
        filters = parse_user_filters("\u624b\u67c4", [])

        self.assertFalse(filters["explicit_category"])
        self.assertEqual(filters["required_terms"], ["\u624b\u67c4"])
        self.assertEqual(filters["match_mode"], "exact_or_none")
        self.assertFalse(filters["allow_popular_fallback"])
        self.assertTrue(has_hard_filters(filters))

    def test_missing_office_accessory_terms_use_exact_or_none(self) -> None:
        for query in ["\u952e\u76d8", "\u9f20\u6807"]:
            filters = parse_user_filters(query, [])

            self.assertFalse(filters["explicit_category"])
            self.assertEqual(filters["required_terms"], [query])
            self.assertEqual(filters["match_mode"], "exact_or_none")
            self.assertFalse(filters["allow_popular_fallback"])

    def test_negated_brand_goes_to_exclude_not_include(self) -> None:
        filters = parse_user_filters("\u4e0d\u8981Nike\u7684\u978b", ["Nike", "\u8010\u514b"])

        self.assertEqual(filters["brands"], [])
        self.assertIn("Nike", filters["brands_exclude"])
        self.assertIn("\u8010\u514b", filters["brands_exclude"])
        self.assertTrue(has_hard_filters(filters))

    def test_positive_brand_stays_include(self) -> None:
        filters = parse_user_filters("Nike\u978b", ["Nike", "\u8010\u514b"])

        self.assertIn("Nike", filters["brands"])
        self.assertIn("\u8010\u514b", filters["brands"])
        self.assertEqual(filters["brands_exclude"], [])

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
        self.assertIn("\u5546\u54c1\u540d\u79f0", catalog_document)
        self.assertIn("\u641c\u7d22\u5173\u952e\u8bcd", catalog_document)

    def test_product_search_document_adds_retrieval_keywords(self) -> None:
        row = {
            "title": "\u6e05\u723d\u63a7\u6cb9\u6d17\u9762\u5976",
            "brand": "\u6d4b\u8bd5",
            "category": "\u7f8e\u5986\u62a4\u80a4",
            "subcategory": "\u6d01\u9762",
            "price": 89,
            "rating": 4.7,
            "stock": 10,
            "marketing_description": "\u9002\u5408\u6cb9\u76ae\u590f\u5929\u4f7f\u7528\uff0c\u6d17\u540e\u4e0d\u7d27\u7ef7",
            "sku_text": "\u6b63\u88c5",
            "review_text": "\u9001\u8d27\u5feb \u5305\u88c5\u597d",
            "faq_text": "\u654f\u611f\u808c\u5148\u6d4b\u8bd5",
            "chunk_text": "\u6d01\u9762 \u63a7\u6cb9",
        }

        document = build_product_search_document(row)

        self.assertIn("\u7c7b\u76ee\uff1a\u7f8e\u5986\u62a4\u80a4 > \u6d01\u9762", document)
        self.assertIn("\u641c\u7d22\u5173\u952e\u8bcd", document)
        self.assertIn("\u6d17\u9762\u5976", document)
        self.assertIn("\u63a7\u6cb9", document)
        self.assertIn("\u6e05\u723d", document)

    def test_tokenizer_keeps_custom_commerce_terms(self) -> None:
        tokens = _tokenize("\u6211\u8981\u84dd\u7259\u8033\u673a\u548c\u901a\u52e4\u5305")

        self.assertIn("\u84dd\u7259", tokens)
        self.assertIn("\u8033\u673a", tokens)
        self.assertIn("\u901a\u52e4", tokens)

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

    def test_verifier_rejects_subcategory_mismatch_even_with_text_match(self) -> None:
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

        self.assertEqual(result.products, [])
        self.assertEqual(result.diagnostics["rejected"][0]["reason"], "subcategory_mismatch")

    def test_exact_or_none_rejects_candidate_without_required_term(self) -> None:
        filters = {
            "required_terms": ["\u624b\u67c4"],
            "match_mode": "exact_or_none",
        }
        product = {
            "id": "p1",
            "title": "Nike Heritage86 Futura Logo \u7ecf\u5178\u523a\u7ee3\u68d2\u7403\u5e3d",
            "brand": "Nike",
            "category": "\u670d\u9970\u8fd0\u52a8",
            "subcategory": "\u5e3d\u5b50",
            "price": 169,
            "stock": 10,
        }

        result = verify_products([product], filters, limit=1)

        self.assertEqual(result.products, [])
        self.assertEqual(result.diagnostics["rejected"][0]["reason"], "required_term_mismatch")

    def test_exact_or_none_allows_core_sku_match(self) -> None:
        filters = {
            "required_terms": ["\u624b\u67c4"],
            "match_mode": "exact_or_none",
        }
        product = {
            "id": "p1",
            "title": "\u6e38\u620f\u63a7\u5236\u5668",
            "brand": "\u6d4b\u8bd5",
            "category": "\u6570\u7801\u7535\u5b50",
            "subcategory": "\u6e38\u620f\u914d\u4ef6",
            "price": 199,
            "stock": 10,
            "sku_text": "\u9ed1\u8272\u624b\u67c4",
        }

        result = verify_products([product], filters, limit=1)

        self.assertEqual([item["id"] for item in result.products], ["p1"])

    def test_exact_or_none_rejects_modifier_only_title_match(self) -> None:
        filters = {
            "required_terms": ["\u8db3\u7403"],
            "match_mode": "exact_or_none",
        }
        product = {
            "id": "p1",
            "title": "\u4e9a\u9a6c\u900a\u500d\u601d \u7070\u8272\u8db3\u7403\u7bee\u7403\u8fd0\u52a8\u80cc\u5305",
            "brand": "\u4e9a\u9a6c\u900a\u500d\u601d",
            "category": "\u65c5\u884c\u6237\u5916",
            "subcategory": "\u80cc\u5305",
            "price": 199,
            "stock": 10,
        }

        result = verify_products([product], filters, limit=1)

        self.assertEqual(result.products, [])
        self.assertEqual(result.diagnostics["rejected"][0]["reason"], "exact_term_not_product_type")

    def test_exact_or_none_allows_title_product_type_match(self) -> None:
        filters = {
            "required_terms": ["\u9a6c\u514b\u7b14"],
            "match_mode": "exact_or_none",
        }
        product = {
            "id": "p1",
            "title": "\u4e9a\u9a6c\u900a\u500d\u601d 40\u8272\u7ec6\u5934\u53ef\u6c34\u6d17\u9a6c\u514b\u7b14",
            "brand": "\u4e9a\u9a6c\u900a\u500d\u601d",
            "category": "\u529e\u516c\u6587\u5177",
            "subcategory": "\u4e66\u5199\u5de5\u5177",
            "price": 39,
            "stock": 10,
        }

        result = verify_products([product], filters, limit=1)

        self.assertEqual([item["id"] for item in result.products], ["p1"])

    def test_keyword_search_does_not_use_stock_as_match(self) -> None:
        parsed_query = ParsedQuery(
            raw_query="\u624b\u67c4",
            rewritten_query="\u624b\u67c4",
            filters={},
            route_notes=[],
        )
        rows = [
            {
                "id": "p1",
                "title": "\u666e\u901a\u5546\u54c1",
                "category": "\u6570\u7801\u7535\u5b50",
                "subcategory": "\u667a\u80fd\u624b\u673a",
                "brand": "\u6d4b\u8bd5",
                "price": 999,
                "stock": 10,
            }
        ]

        hits = _keyword_search(parsed_query, rows, {"p1": "\u666e\u901a\u5546\u54c1 \u667a\u80fd\u624b\u673a"}, limit=10)

        self.assertEqual(hits, [])

    def test_keyword_search_filters_out_of_stock_matches(self) -> None:
        parsed_query = ParsedQuery(
            raw_query="\u624b\u67c4",
            rewritten_query="\u624b\u67c4",
            filters={},
            route_notes=[],
        )
        rows = [
            {
                "id": "p1",
                "title": "\u6e38\u620f\u624b\u67c4",
                "category": "\u6570\u7801\u7535\u5b50",
                "subcategory": "\u6e38\u620f\u914d\u4ef6",
                "brand": "\u6d4b\u8bd5",
                "price": 199,
                "stock": 0,
            }
        ]

        hits = _keyword_search(parsed_query, rows, {"p1": "\u6e38\u620f\u624b\u67c4"}, limit=10)

        self.assertEqual(hits, [])

    def test_alternatives_relax_price_but_keep_subcategory(self) -> None:
        filters = {
            "target_categories": ["\u98df\u54c1\u996e\u6599"],
            "target_subcategories": ["\u575a\u679c/\u96f6\u98df"],
            "required_terms": ["\u96f6\u98df"],
            "explicit_category": True,
            "max_price": 50,
            "price_sensitive": True,
        }
        candidates = [
            {
                "id": "p_snack",
                "title": "\u826f\u54c1\u94fa\u5b50 \u4f11\u95f2\u96f6\u98df",
                "brand": "\u826f\u54c1\u94fa\u5b50",
                "category": "\u98df\u54c1\u996e\u6599",
                "subcategory": "\u575a\u679c/\u96f6\u98df",
                "price": 59,
                "rating": 4.0,
                "stock": 10,
            },
            {
                "id": "p_drink",
                "title": "\u8336\u996e",
                "brand": "\u6d4b\u8bd5",
                "category": "\u98df\u54c1\u996e\u6599",
                "subcategory": "\u8336\u996e",
                "price": 4,
                "rating": 4.0,
                "stock": 10,
            },
            {
                "id": "p_pet",
                "title": "\u72ac\u7528\u96f6\u98df",
                "brand": "\u6d4b\u8bd5",
                "category": "\u5ba0\u7269\u7528\u54c1",
                "subcategory": "\u5ba0\u7269\u96f6\u98df",
                "price": 59,
                "rating": 4.0,
                "stock": 10,
            },
        ]

        alternatives = build_alternative_products(candidates, filters, limit=3)

        self.assertEqual([product.id for product in alternatives], ["p_snack"])
        self.assertEqual(alternatives[0].price, 59)

    def test_confidence_gate_rejects_dense_only_without_hard_filters(self) -> None:
        products = [
            {
                "id": "p1",
                "title": "\u5f31\u5339\u914d\u5546\u54c1",
                "_sources": ["dense"],
                "_bm25_score": 0.0,
                "_keyword_score": 0.0,
            }
        ]

        gated, diagnostics = apply_confidence_gate(products, {"allow_popular_fallback": True})

        self.assertEqual(gated, [])
        self.assertEqual(diagnostics["status"], "rejected")

    def test_confidence_gate_allows_lexical_support(self) -> None:
        products = [
            {
                "id": "p1",
                "title": "\u5f3a\u5339\u914d\u5546\u54c1",
                "_sources": ["dense", "keyword"],
                "_bm25_score": 0.0,
                "_keyword_score": 8.0,
            }
        ]

        gated, diagnostics = apply_confidence_gate(products, {"allow_popular_fallback": True})

        self.assertEqual(gated, products)
        self.assertEqual(diagnostics["status"], "pass")

    def test_image_wide_match_keeps_category_as_weight_not_hard_filter(self) -> None:
        parsed = ParsedQuery(
            raw_query="黑色 真无线耳机 通勤",
            rewritten_query="黑色 真无线耳机 通勤",
            filters={
                "target_categories": ["数码电子"],
                "target_subcategories": ["真无线耳机"],
                "required_terms": ["耳机"],
                "explicit_category": True,
                "match_mode": "exact_or_none",
                "allow_popular_fallback": True,
            },
            route_notes=["category", "subcategory"],
        )

        result = apply_tool_constraints(parsed, {}, {"image_wide_match": True})

        self.assertFalse(result.filters["explicit_category"])
        self.assertIsNone(result.filters["match_mode"])
        self.assertFalse(result.filters["allow_popular_fallback"])
        self.assertFalse(result.filters["require_lexical_anchor"])
        self.assertIn("image_wide_match", result.route_notes)


if __name__ == "__main__":
    unittest.main()
