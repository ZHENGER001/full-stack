from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from app.react_planner import plan_react_transaction, plan_react_transaction_with_rules


def state(count: int = 4) -> dict:
    return {"last_recommended_product_ids": [f"p{i}" for i in range(1, count + 1)]}


def cart_add_positions(message: str, count: int = 4) -> list[int | None]:
    plan = plan_react_transaction_with_rules(message, state(count))
    return [step.position for step in plan.steps if step.action == "cart_add"]


class ReactPlannerTest(unittest.TestCase):
    def test_front_two_cart_add_expands_to_position_steps(self) -> None:
        plan = plan_react_transaction_with_rules("把前两个加入购物车", state())

        self.assertTrue(plan.should_execute)
        self.assertEqual([step.position for step in plan.steps], [1, 2])
        self.assertEqual([step.quantity for step in plan.steps], [1, 1])

    def test_last_two_cart_add_expands_to_position_steps(self) -> None:
        self.assertEqual(cart_add_positions("把后两款加入购物车", count=4), [3, 4])

    def test_all_cart_add_expands_to_all_recent_positions(self) -> None:
        self.assertEqual(cart_add_positions("全部加入购物车", count=3), [1, 2, 3])

    def test_numeric_list_cart_add_expands_to_position_steps(self) -> None:
        self.assertEqual(cart_add_positions("加入1，4进入购物车", count=4), [1, 4])

    def test_ordinal_list_cart_add_expands_to_position_steps(self) -> None:
        self.assertEqual(cart_add_positions("第一款和第三款加购物车", count=4), [1, 3])

    def test_invalid_batch_reference_does_not_default_to_first_product(self) -> None:
        plan = plan_react_transaction_with_rules("加入1，4进入购物车", state(count=2))

        self.assertFalse(plan.should_execute)
        self.assertEqual(plan.steps, [])

    def test_rule_resolved_batch_reference_skips_llm_config_lookup(self) -> None:
        with patch("app.react_planner._env_value", side_effect=AssertionError("LLM should not be used")):
            plan = asyncio.run(plan_react_transaction("把前两款加入购物车", [], state()))

        self.assertEqual([step.position for step in plan.steps if step.action == "cart_add"], [1, 2])


if __name__ == "__main__":
    unittest.main()
