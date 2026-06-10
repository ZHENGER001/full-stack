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


async def wrong_bundle_for_single_product_llm(message, *args, **kwargs):
    return ParsedTurnCandidate(
        raw_message=message,
        intent_type="bundle_recommendation",
        proposed_tool="bundle_recommendation",
        core_product_query="\u7ec4\u5408\u642d\u914d",
        bundle_slots=[
            BundleSlotCandidate(key="core", title="\u6838\u5fc3\u5546\u54c1", query=message),
            BundleSlotCandidate(key="accessory", title="\u914d\u5957\u5546\u54c1", query=f"{message} \u914d\u5957"),
        ],
        source="llm",
    )


async def generated_dorm_scene_slots(message, *args, **kwargs):
    return [
        BundleSlotCandidate(
            key="bedding",
            title="\u5e8a\u54c1",
            query="\u5bbf\u820d \u5e8a\u54c1 \u88ab\u5b50",
            reason="\u5bbf\u820d\u4f4f\u5bbf\u9700\u8981\u57fa\u7840\u5e8a\u54c1\u3002",
            product_mentions=["\u88ab\u5b50"],
            scene_terms=["\u5bbf\u820d", "\u5f00\u5b66"],
        ),
        BundleSlotCandidate(
            key="storage",
            title="\u6536\u7eb3",
            query="\u5bbf\u820d \u6536\u7eb3\u7bb1",
            reason="\u5bbf\u820d\u7a7a\u95f4\u6709\u9650\uff0c\u9700\u8981\u6536\u7eb3\u3002",
            product_mentions=["\u6536\u7eb3\u7bb1"],
            scene_terms=["\u5bbf\u820d", "\u5f00\u5b66"],
        ),
    ]


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
        self.assertTrue(parsed.needs_clarification)
        self.assertEqual(parsed.route_hint, "no_tool")
        self.assertIn("数码电子", parsed.constraints.categories)
        self.assertIn("智能手机", parsed.constraints.subcategories)
        self.assertIn("拍照", parsed.clarification_question or "")
        self.assertIn("续航", parsed.clarification_question or "")

    def test_bluetooth_earphones_with_price(self) -> None:
        parsed = parse("200元以下蓝牙耳机")

        self.assertEqual(parsed.intent_type, "product_search")
        self.assertFalse(parsed.needs_clarification)
        self.assertEqual(parsed.route_hint, "direct_tool")
        self.assertEqual(parsed.constraints.price.max, 200)
        self.assertIn("真无线耳机", parsed.constraints.subcategories)
        self.assertIn("耳机", parsed.constraints.required_terms)

    def test_bluetooth_earphones_with_budget_does_not_trigger_wearable_safety_question(self) -> None:
        parsed = parse("推荐一款500元以内的蓝牙耳机")

        self.assertEqual(parsed.intent_type, "product_search")
        self.assertFalse(parsed.needs_clarification)
        self.assertEqual(parsed.route_hint, "direct_tool")
        self.assertEqual(parsed.constraints.price.max, 500)
        self.assertIn("真无线耳机", parsed.constraints.subcategories)

    def test_premium_bluetooth_earphones_ask_preference_before_recommendation(self) -> None:
        parsed = parse("推荐一款2000元以内的蓝牙耳机")

        self.assertEqual(parsed.intent_type, "product_search")
        self.assertTrue(parsed.needs_clarification)
        self.assertEqual(parsed.route_hint, "no_tool")
        self.assertIn("降噪", parsed.clarification_question or "")
        self.assertIn("续航", parsed.clarification_question or "")
        self.assertNotIn("预算大概多少", parsed.clarification_question or "")

    def test_general_earphone_search_asks_preference_before_recommendation(self) -> None:
        parsed = parse("推荐一款耳机")

        self.assertEqual(parsed.intent_type, "product_search")
        self.assertTrue(parsed.needs_clarification)
        self.assertEqual(parsed.route_hint, "no_tool")
        self.assertIn("真无线耳机", parsed.constraints.subcategories)
        self.assertEqual(parsed.constraints.required_terms, ["耳机"])
        self.assertIn("降噪", parsed.clarification_question or "")
        self.assertIn("续航", parsed.clarification_question or "")

    def test_noise_cancelling_earphone_refinement_does_not_repeat_preference_question(self) -> None:
        parsed = parse(
            "优先降噪的耳机有哪些",
            {
                "structured_memory": {
                    "category": "数码电子",
                    "subcategory": "真无线耳机",
                }
            },
        )

        self.assertEqual(parsed.intent_type, "product_search")
        self.assertFalse(parsed.needs_clarification)
        self.assertEqual(parsed.route_hint, "direct_tool")
        self.assertIn("降噪", parsed.constraints.attributes_include)
        self.assertEqual(parsed.constraints.required_terms, ["耳机"])

    def test_earphone_preference_tradeoff_is_not_product_compare(self) -> None:
        parsed = parse(
            "降噪和续航哪个更重要",
            {
                "structured_memory": {
                    "category": "数码电子",
                    "subcategory": "真无线耳机",
                    "budget_max": 500,
                }
            },
        )

        self.assertEqual(parsed.intent_type, "preference_question")
        self.assertEqual(parsed.route_hint, "no_tool")
        self.assertIn("通勤", parsed.clarification_question or "")
        self.assertIn("长途", parsed.clarification_question or "")

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

    def test_single_product_replenishment_not_overridden_by_bundle_llm(self) -> None:
        with patch("app.turn_parser_hybrid.parse_turn_with_llm", new=wrong_bundle_for_single_product_llm):
            parsed = asyncio.run(
                parse_turn_hybrid(
                    "\u5bb6\u91cc\u9171\u6cb9\u6ca1\u4e86",
                    chat_history=None,
                    conversation_state={"last_query": "\u7ed9\u6211\u63a8\u8350\u4e00\u5957\u4e0b\u6c34\u6e38\u6cf3\u88c5\u5907"},
                )
            )

        self.assertEqual(parsed.intent_type, "product_search")
        self.assertEqual(parsed.route_hint, "direct_tool")
        self.assertEqual(parsed.bundle_slots, [])
        self.assertIn("\u98df\u54c1\u996e\u6599", parsed.constraints.categories)
        self.assertEqual(parsed.constraints.required_terms, ["\u9171\u6cb9"])
        self.assertFalse(parsed.retrieval_policy_hint.allow_popular_fallback)

    def test_swimming_bundle_uses_strict_swim_slots(self) -> None:
        parsed = parse("\u7ed9\u6211\u63a8\u8350\u4e00\u5957\u4e0b\u6c34\u6e38\u6cf3\u88c5\u5907")

        self.assertEqual(parsed.intent_type, "bundle_recommendation")
        self.assertEqual(parsed.route_hint, "direct_tool")
        self.assertGreaterEqual(len(parsed.bundle_slots), 3)
        self.assertIn("swimwear", [slot.key for slot in parsed.bundle_slots])
        self.assertIn("goggles", [slot.key for slot in parsed.bundle_slots])
        self.assertIn("swim_cap", [slot.key for slot in parsed.bundle_slots])
        self.assertTrue(any("\u6cf3\u955c" in slot.product_mentions for slot in parsed.bundle_slots))

    def test_unknown_scene_bundle_can_be_filled_by_dynamic_generator(self) -> None:
        with patch("app.turn_parser_hybrid.parse_turn_with_llm", new=fail_llm), patch(
            "app.turn_parser_hybrid.generate_scene_slots_with_llm",
            new=generated_dorm_scene_slots,
        ):
            parsed = asyncio.run(
                parse_turn_hybrid(
                    "\u5bbf\u820d\u5f00\u5b66\u6e05\u5355",
                    chat_history=None,
                    conversation_state={},
                )
            )

        self.assertEqual(parsed.intent_type, "bundle_recommendation")
        self.assertEqual([slot.key for slot in parsed.bundle_slots], ["bedding", "storage"])
        self.assertIn("\u88ab\u5b50", parsed.bundle_slots[0].product_mentions)

    def test_food_search_asks_safety_clarification(self) -> None:
        parsed = parse("\u63a8\u8350\u96f6\u98df")

        self.assertTrue(parsed.needs_clarification)
        self.assertEqual(parsed.route_hint, "no_tool")
        self.assertIn("\u8fc7\u654f", parsed.clarification_question or "")
        self.assertIn("\u5fcc\u53e3", parsed.clarification_question or "")

    def test_vague_food_allergy_asks_specific_allergen(self) -> None:
        parsed = parse("\u5e2e\u6211\u63a8\u8350\u51e0\u6b3e\u96f6\u98df\uff0c\u4f46\u5bf9\u67d0\u4e9b\u4e1c\u897f\u8fc7\u654f")

        self.assertTrue(parsed.needs_clarification)
        self.assertEqual(parsed.route_hint, "no_tool")
        self.assertIn("\u5177\u4f53\u5bf9\u4ec0\u4e48\u8fc7\u654f", parsed.clarification_question or "")

    def test_specific_food_allergy_does_not_block_search(self) -> None:
        parsed = parse("\u63a8\u8350\u96f6\u98df\uff0c\u6211\u575a\u679c\u8fc7\u654f")

        self.assertFalse(parsed.needs_clarification)
        self.assertEqual(parsed.route_hint, "direct_tool")

    def test_skincare_search_asks_safety_clarification(self) -> None:
        parsed = parse("\u63a8\u8350\u9762\u971c")

        self.assertTrue(parsed.needs_clarification)
        self.assertEqual(parsed.route_hint, "no_tool")
        self.assertIn("\u80a4\u8d28", parsed.clarification_question or "")

    def test_sport_shoe_search_asks_health_fit_clarification(self) -> None:
        parsed = parse("\u63a8\u8350\u8dd1\u6b65\u978b")

        self.assertTrue(parsed.needs_clarification)
        self.assertEqual(parsed.route_hint, "no_tool")
        self.assertIn("\u811a\u5bbd", parsed.clarification_question or "")

    def test_specific_replenishment_does_not_force_safety_clarification(self) -> None:
        parsed = parse("\u5bb6\u91cc\u9171\u6cb9\u6ca1\u4e86")

        self.assertEqual(parsed.intent_type, "product_search")
        self.assertEqual(parsed.route_hint, "direct_tool")
        self.assertFalse(parsed.needs_clarification)
        self.assertEqual(parsed.constraints.required_terms, ["\u9171\u6cb9"])


if __name__ == "__main__":
    unittest.main()
