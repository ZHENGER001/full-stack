from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from app.llm_client import LLMGenerationError
from app.turn_parser_hybrid import parse_turn_hybrid
from app.turn_schema import BundleSlotCandidate, ParsedTurn, ParsedTurnCandidate, TurnConstraints


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


async def bad_bundle_llm(message, *args, **kwargs):
    return ParsedTurn(
        raw_message=message,
        intent_type="product_search",
        route_hint="direct_tool",
        constraints=TurnConstraints(
            categories=["\u7f8e\u5986\u62a4\u80a4"],
            subcategories=["\u9632\u6652"],
            required_terms=["\u9632\u6652"],
        ),
        source="llm",
    )


async def semantic_bundle_llm(message, *args, **kwargs):
    return ParsedTurnCandidate(
        raw_message=message,
        intent_type="bundle_recommendation",
        proposed_tool="bundle_recommendation",
        core_product_query="\u624b\u673a\u7535\u8111\u4e92\u8054",
        product_mentions=["\u624b\u673a", "\u7535\u8111"],
        scene_terms=["\u4e92\u8054\u751f\u6001"],
        bundle_slots=[
            BundleSlotCandidate(
                key="phone",
                title="\u624b\u673a",
                query="\u667a\u80fd\u624b\u673a \u4e92\u8054",
                product_mentions=["\u624b\u673a"],
            ),
            BundleSlotCandidate(
                key="computer",
                title="\u7535\u8111",
                query="\u7b14\u8bb0\u672c\u7535\u8111 \u4e92\u8054",
                product_mentions=["\u7b14\u8bb0\u672c"],
            ),
        ],
        source="llm",
    )


async def semantic_printer_ink_llm(message, *args, **kwargs):
    return ParsedTurnCandidate(
        raw_message=message,
        intent_type="product_search",
        proposed_tool="search_products",
        core_product_query="\u6253\u5370\u673a\u58a8\u6c34",
        product_mentions=["\u6253\u5370\u673a\u58a8\u6c34"],
        query_expansions=["\u58a8\u76d2", "\u6253\u5370\u8017\u6750"],
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

    def test_excludes_nike_shoes(self) -> None:
        parsed = parse("不要Nike的鞋")

        self.assertIn("Nike", parsed.constraints.brands_exclude)
        self.assertIn("耐克", parsed.constraints.brands_exclude)

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

    def test_clear_cart(self) -> None:
        parsed = parse("清空购物车")

        self.assertEqual(parsed.intent_type, "cart_clear")
        self.assertEqual(parsed.route_hint, "bounded_react")


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

    def test_buy_lip_glaze_grounds_to_catalog_subcategory(self) -> None:
        parsed = parse("\u6211\u60f3\u4e70\u5507\u91c9")

        self.assertEqual(parsed.intent_type, "product_search")
        self.assertEqual(parsed.route_hint, "direct_tool")
        self.assertEqual(parsed.normalized_query, "\u5507\u91c9")
        self.assertIn("\u7f8e\u5986\u62a4\u80a4", parsed.constraints.categories)
        self.assertIn("\u5507\u91c9", parsed.constraints.subcategories)
        self.assertEqual(parsed.constraints.required_terms, ["\u5507\u91c9"])

    def test_ambiguous_pen_phrase_asks_clarification(self) -> None:
        parsed = parse("\u6211\u60f3\u4e70\u7b14")

        self.assertEqual(parsed.route_hint, "no_tool")
        self.assertTrue(parsed.needs_clarification)
        self.assertEqual(parsed.normalized_query, "\u7b14")
        self.assertNotIn("\u7b14\u8bb0\u672c\u7535\u8111", parsed.constraints.subcategories)
        self.assertNotEqual(parsed.constraints.required_terms, ["\u6211\u60f3\u4e70\u7b14"])

    def test_hungry_snack_does_not_expand_to_pet_snack(self) -> None:
        parsed = parse("\u4eca\u5929\u997f\u4e86\uff0c\u60f3\u5403\u70b9\u96f6\u98df")

        self.assertEqual(parsed.route_hint, "direct_tool")
        self.assertIn("\u98df\u54c1\u996e\u6599", parsed.constraints.categories)
        self.assertIn("\u575a\u679c/\u96f6\u98df", parsed.constraints.subcategories)
        self.assertNotIn("\u5ba0\u7269\u96f6\u98df", parsed.constraints.subcategories)

    def test_printer_out_of_ink_fallback_grounds_to_printing_supplies(self) -> None:
        parsed = parse("\u5bb6\u91cc\u6253\u5370\u673a\u6ca1\u58a8\u6c34\u4e86")

        self.assertEqual(parsed.route_hint, "direct_tool")
        self.assertIn("\u529e\u516c\u6587\u5177", parsed.constraints.categories)
        self.assertIn("\u6253\u5370\u8017\u6750", parsed.constraints.subcategories)
        self.assertEqual(parsed.constraints.required_terms, ["\u6253\u5370\u8017\u6750"])
        self.assertFalse(parsed.retrieval_policy_hint.allow_popular_fallback)
        self.assertFalse(parsed.retrieval_policy_hint.allow_dense_only)
        self.assertTrue(parsed.retrieval_policy_hint.require_lexical_anchor)

    def test_llm_query_expansions_are_grounded_before_execution(self) -> None:
        with patch("app.turn_parser_hybrid.parse_turn_with_llm", new=semantic_printer_ink_llm):
            parsed = asyncio.run(
                parse_turn_hybrid(
                    "\u5bb6\u91cc\u7684\u673a\u5668\u65ad\u58a8\u4e86",
                    chat_history=None,
                    conversation_state={},
                )
            )

        self.assertIn("\u529e\u516c\u6587\u5177", parsed.constraints.categories)
        self.assertIn("\u6253\u5370\u8017\u6750", parsed.constraints.subcategories)
        self.assertEqual(parsed.constraints.required_terms, ["\u6253\u5370\u8017\u6750"])

    def test_bundle_rule_is_not_overridden_by_llm_product_search(self) -> None:
        with patch("app.turn_parser_hybrid.parse_turn_with_llm", new=bad_bundle_llm):
            parsed = asyncio.run(
                parse_turn_hybrid(
                    "\u4e0b\u5468\u53bb\u4e09\u4e9a\u5ea6\u5047\uff0c\u5e2e\u6211\u642d\u914d\u4e00\u5957\u4ece\u9632\u6652\u5230\u7a7f\u642d\u7684\u65b9\u6848",
                    chat_history=None,
                    conversation_state={},
                )
            )

        self.assertEqual(parsed.intent_type, "bundle_recommendation")
        self.assertEqual(parsed.route_hint, "direct_tool")
        self.assertEqual(parsed.constraints.required_terms, [])

    def test_digital_ecosystem_bundle_fallback_not_product_search(self) -> None:
        parsed = parse("\u914d\u4e00\u5957\u624b\u673a\u7535\u8111\uff0c\u80fd\u4e92\u8054\u7684\u90a3\u79cd")

        self.assertEqual(parsed.intent_type, "bundle_recommendation")
        self.assertEqual(parsed.route_hint, "direct_tool")
        self.assertEqual(parsed.constraints.required_terms, [])
        self.assertGreaterEqual(len(parsed.bundle_slots), 2)
        self.assertTrue(any("\u624b\u673a" in slot.product_mentions for slot in parsed.bundle_slots))

    def test_llm_candidate_bundle_is_not_compressed_to_product_search(self) -> None:
        with patch("app.turn_parser_hybrid.parse_turn_with_llm", new=semantic_bundle_llm):
            parsed = asyncio.run(
                parse_turn_hybrid(
                    "\u60f3\u8981\u624b\u673a\u548c\u7535\u8111\u534f\u540c\u529e\u516c",
                    chat_history=None,
                    conversation_state={},
                )
            )

        self.assertEqual(parsed.intent_type, "bundle_recommendation")
        self.assertEqual(parsed.route_hint, "direct_tool")
        self.assertEqual(parsed.constraints.required_terms, [])
        self.assertEqual([slot.key for slot in parsed.bundle_slots], ["phone", "computer"])


if __name__ == "__main__":
    unittest.main()
