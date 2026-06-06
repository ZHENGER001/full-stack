from __future__ import annotations

import math
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts import eval_retrieval


class RetrievalEvalMetricTest(unittest.TestCase):
    def test_default_retrieval_cases_have_expected_count_and_unique_ids(self) -> None:
        cases = eval_retrieval.load_cases(eval_retrieval.DEFAULT_CASES_PATH)
        case_ids = [case["id"] for case in cases]

        self.assertEqual(len(cases), 100)
        self.assertEqual(len(case_ids), len(set(case_ids)))

    def test_relevance_grades_backfill_legacy_ids_and_allow_overrides(self) -> None:
        case = {
            "relevant_product_ids": ["p1", "p2"],
            "graded_relevance": {"p1": 2, "p2": 0, "p3": 1},
        }

        grades = eval_retrieval.relevance_grades(case)

        self.assertEqual(grades, {"p1": 2, "p3": 1})

    def test_ndcg_uses_graded_relevance_order(self) -> None:
        grades = {"strong": 3, "weak": 1}
        ids = ["weak", "strong"]

        actual = eval_retrieval.ndcg_at_k(ids, grades, 2)
        expected = ((1 / math.log2(2)) + (7 / math.log2(3))) / (
            (7 / math.log2(2)) + (1 / math.log2(3))
        )

        self.assertAlmostEqual(actual, expected)

    def test_average_precision_at_k_scores_ranked_binary_hits(self) -> None:
        ids = ["miss", "p1", "p2"]
        relevant_ids = {"p1", "p2"}

        actual = eval_retrieval.average_precision_at_k(ids, relevant_ids, 3)

        self.assertAlmostEqual(actual, ((1 / 2) + (2 / 3)) / 2)

    def test_constraint_violations_detect_required_blocked_and_category_errors(self) -> None:
        case = {
            "constraints": {
                "categories": ["数码电子"],
                "subcategories": ["智能手机"],
            },
            "forbidden_categories": ["美妆护肤"],
            "must_include_product_ids": ["p_required"],
            "must_not_include_product_ids": ["p_blocked"],
        }
        products = [
            SimpleNamespace(id="p_blocked", category="美妆护肤", subcategory="精华"),
        ]

        violations = eval_retrieval.constraint_violations(case, products, ["p_blocked"], top_k=3)

        self.assertIn("missing_required_products:p_required", violations)
        self.assertIn("blocked_products_returned:p_blocked", violations)
        self.assertIn("forbidden_categories:美妆护肤", violations)
        self.assertIn("category_mismatch:p_blocked", violations)
        self.assertIn("subcategory_mismatch:p_blocked", violations)

    def test_evaluate_case_passes_constraints_and_retrieval_policy_to_tool(self) -> None:
        result = SimpleNamespace(
            status="ok",
            products=[
                SimpleNamespace(id="p1", category="数码电子", subcategory="智能手机"),
            ],
            diagnostics={"lanes": {"dense": {"count": 1}}},
        )
        case = {
            "id": "phone_under_budget",
            "query": "3000以内手机",
            "graded_relevance": {"p1": 3},
            "expected_category": "数码电子",
            "expected_subcategory": "智能手机",
            "constraints": {"price": {"max": 3000}},
            "retrieval_policy": {"match_mode": "normal"},
        }

        with patch("scripts.eval_retrieval.call_search_products_tool") as search:
            search.return_value = result
            evaluated = eval_retrieval.evaluate_case(object(), case, top_k=3)

        request = search.call_args.args[1]
        self.assertEqual(request.constraints, {"price": {"max": 3000}})
        self.assertEqual(request.retrieval_policy, {"match_mode": "normal"})
        self.assertTrue(evaluated.constraint_pass)
        self.assertEqual(evaluated.lane_counts, {"dense": 1})


if __name__ == "__main__":
    unittest.main()
