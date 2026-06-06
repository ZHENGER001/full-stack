from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from app.llm_client import LLMGenerationError
from app.turn_parser_hybrid import parse_turn_hybrid
from app.turn_schema import ParsedTurn, TurnConstraints


async def fail_llm(*args, **kwargs):
    raise LLMGenerationError("disabled in tests")


async def bad_snack_llm(message, *args, **kwargs):
    return ParsedTurn(
        raw_message=message,
        intent_type="product_search",
        route_hint="direct_tool",
        constraints=TurnConstraints(
            categories=["\u96f6\u98df"],
            subcategories=["\u575a\u679c/\u96f6\u98df"],
            required_terms=["\u96f6\u98df"],
        ),
        source="llm",
    )


def parse(message: str, state: dict | None = None):
    with patch("app.turn_parser_hybrid.parse_turn_with_llm", new=fail_llm):
        return asyncio.run(parse_turn_hybrid(message, chat_history=None, conversation_state=state or {}))


class TurnParserHybridTest(unittest.TestCase):
    def test_product_search_phone(self) -> None:
        parsed = parse("推荐手机")

        self.assertEqual(parsed.intent_type, "product_search")
        self.assertEqual(parsed.route_hint, "direct_tool")
        self.assertIn("数码电子", parsed.constraints.categories)
        self.assertIn("智能手机", parsed.constraints.subcategories)

    def test_bluetooth_earphones_with_price(self) -> None:
        parsed = parse("200元以下蓝牙耳机")

        self.assertEqual(parsed.intent_type, "product_search")
        self.assertEqual(parsed.constraints.price.max, 200)
        self.assertIn("真无线耳机", parsed.constraints.subcategories)
        self.assertIn("耳机", parsed.constraints.required_terms)

    def test_unknown_short_controller_exact_or_none(self) -> None:
        parsed = parse("手柄")

        self.assertEqual(parsed.constraints.required_terms, ["手柄"])
        self.assertEqual(parsed.retrieval_policy_hint.match_mode, "exact_or_none")
        self.assertFalse(parsed.retrieval_policy_hint.allow_popular_fallback)
        self.assertFalse(parsed.retrieval_policy_hint.allow_dense_only)
        self.assertTrue(parsed.retrieval_policy_hint.require_lexical_anchor)
        self.assertEqual(parsed.route_hint, "direct_tool")

    def test_unknown_short_football_exact_or_none(self) -> None:
        parsed = parse("足球")

        self.assertEqual(parsed.constraints.required_terms, ["足球"])
        self.assertEqual(parsed.retrieval_policy_hint.match_mode, "exact_or_none")
        self.assertFalse(parsed.retrieval_policy_hint.allow_popular_fallback)

    def test_attribute_only_bluetooth_requires_clarification(self) -> None:
        parsed = parse("蓝牙")

        self.assertTrue(parsed.needs_clarification)
        self.assertEqual(parsed.route_hint, "no_tool")
        self.assertIn("蓝牙", parsed.clarification_question or "")

    def test_excludes_apple_phone(self) -> None:
        parsed = parse("不要苹果的手机")

        self.assertIn("智能手机", parsed.constraints.subcategories)
        self.assertTrue("Apple" in parsed.constraints.brands_exclude or "苹果" in parsed.constraints.negative_terms)

    def test_cart_add_second_product(self) -> None:
        parsed = parse("把第二个加购物车")

        self.assertEqual(parsed.intent_type, "cart_add")
        self.assertEqual(parsed.route_hint, "bounded_react")
        self.assertEqual(parsed.quantity, 1)
        self.assertEqual(parsed.references[0].position, 2)

    def test_compare_first_and_second_by_price(self) -> None:
        parsed = parse("第一个和第二个哪个更便宜")

        self.assertEqual(parsed.intent_type, "product_compare")
        self.assertEqual(parsed.route_hint, "bounded_react")
        self.assertEqual([ref.position for ref in parsed.references], [1, 2])
        self.assertIn("price", parsed.compare_dimensions)

    def test_current_product_stock_question(self) -> None:
        parsed = parse("这个有货吗")

        self.assertEqual(parsed.intent_type, "product_detail_qa")
        self.assertEqual(parsed.route_hint, "bounded_react")
        self.assertEqual(parsed.references[0].reference_type, "current_product")
        self.assertIn("stock", parsed.compare_dimensions)

    def test_filter_refinement_cheaper(self) -> None:
        parsed = parse("再便宜点")

        self.assertEqual(parsed.intent_type, "filter_refinement")
        self.assertEqual(parsed.route_hint, "direct_tool")


    def test_rule_constraints_are_preserved_when_llm_category_is_wrong(self) -> None:
        with patch("app.turn_parser_hybrid.parse_turn_with_llm", new=bad_snack_llm):
            parsed = asyncio.run(
                parse_turn_hybrid(
                    "50\u4ee5\u4e0b\u96f6\u98df",
                    chat_history=None,
                    conversation_state={},
                )
            )

        self.assertIn("\u98df\u54c1\u996e\u6599", parsed.constraints.categories)
        self.assertIn("\u575a\u679c/\u96f6\u98df", parsed.constraints.subcategories)
        self.assertEqual(parsed.constraints.price.max, 50)


if __name__ == "__main__":
    unittest.main()
