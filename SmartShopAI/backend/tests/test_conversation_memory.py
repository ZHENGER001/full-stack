from __future__ import annotations

import json
import unittest

from app.conversation_memory import (
    apply_memory_to_parsed_turn,
    build_updated_structured_memory,
    dump_structured_memory,
    empty_structured_memory,
    parse_structured_memory,
)
from app.turn_schema import ParsedTurn, PriceConstraint, TurnConstraints


class ConversationMemoryTest(unittest.TestCase):
    def test_updates_memory_from_parsed_turn_constraints(self) -> None:
        parsed = ParsedTurn(
            raw_message="推荐500以内篮球鞋，不要李宁",
            intent_type="product_search",
            constraints=TurnConstraints(
                categories=["服饰运动"],
                subcategories=["篮球鞋"],
                price=PriceConstraint(max=500),
                brands_exclude=["李宁"],
                attributes_include=["耐磨"],
            ),
        )

        memory = build_updated_structured_memory(empty_structured_memory(), message=parsed.raw_message, parsed_turn=parsed)

        self.assertEqual(memory["category"], "服饰运动")
        self.assertEqual(memory["subcategory"], "篮球鞋")
        self.assertEqual(memory["budget_max"], 500)
        self.assertEqual(memory["brands_exclude"], ["李宁"])
        self.assertEqual(memory["attributes_include"], ["耐磨"])
        self.assertEqual(memory["current_task"], "recommendation")

    def test_sparse_refinement_inherits_product_context(self) -> None:
        memory = {
            **empty_structured_memory(),
            "category": "服饰运动",
            "subcategory": "篮球鞋",
            "budget_max": 500,
            "brands_exclude": ["李宁"],
        }
        parsed = ParsedTurn(
            raw_message="耐磨一点",
            intent_type="product_search",
            constraints=TurnConstraints(attributes_include=["耐磨"]),
        )

        enriched = apply_memory_to_parsed_turn(parsed, {"structured_memory": memory})

        self.assertEqual(enriched.intent_type, "filter_refinement")
        self.assertEqual(enriched.constraints.categories, ["服饰运动"])
        self.assertEqual(enriched.constraints.subcategories, ["篮球鞋"])
        self.assertEqual(enriched.constraints.price.max, 500)
        self.assertEqual(enriched.constraints.brands_exclude, ["李宁"])
        self.assertEqual(enriched.constraints.attributes_include, ["耐磨"])

    def test_product_results_update_reference_memory(self) -> None:
        memory = build_updated_structured_memory(
            empty_structured_memory(),
            message="推荐手机",
            visible_products=[
                {
                    "id": "p_phone_1",
                    "title": "测试手机",
                    "brand": "测试品牌",
                    "category": "数码电子",
                    "subcategory": "智能手机",
                }
            ],
        )

        self.assertEqual(memory["last_product_ids"], ["p_phone_1"])
        self.assertEqual(memory["current_product_id"], "p_phone_1")
        self.assertEqual(memory["category"], "数码电子")
        self.assertEqual(memory["subcategory"], "智能手机")
        self.assertEqual(memory["brands_include"], ["测试品牌"])

    def test_dump_and_parse_memory_round_trip(self) -> None:
        raw = dump_structured_memory({**empty_structured_memory(), "subcategory": "跑步鞋"})
        parsed = parse_structured_memory(raw)

        self.assertEqual(json.loads(raw)["subcategory"], "跑步鞋")
        self.assertEqual(parsed["subcategory"], "跑步鞋")
        self.assertIsNotNone(parsed["updated_at"])


if __name__ == "__main__":
    unittest.main()
