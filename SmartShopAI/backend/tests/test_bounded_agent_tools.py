from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from app.bounded_agent_tools import _sanitize_llm_comparison_payload, execute_bounded_turn
from app.database import dict_factory
from app.llm_client import LLMGenerationError
from app.turn_schema import ParsedTurn, ProductReference


class BoundedAgentToolsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = dict_factory
        schema_path = Path(__file__).resolve().parents[1] / "app" / "schema.sql"
        self.conn.executescript(schema_path.read_text(encoding="utf-8"))
        self._insert_product("p1", "Alpha Phone", "Alpha", "数码电子", "智能手机", 100, 5)
        self._insert_product("p2", "Beta Phone", "Beta", "数码电子", "智能手机", 60, 3)
        self._insert_product("p3", "Gamma Earbuds", "Gamma", "数码电子", "真无线耳机", 80, 0)

    def tearDown(self) -> None:
        self.conn.close()

    def test_adds_referenced_second_product_to_cart(self) -> None:
        parsed = ParsedTurn(
            raw_message="把第二个加购物车",
            intent_type="cart_add",
            route_hint="bounded_react",
            references=[ProductReference(reference_type="position", position=2)],
            quantity=2,
        )

        with patch(
            "app.bounded_agent_tools._write_compare_payload_with_llm",
            side_effect=LLMGenerationError("skip network"),
        ):
            result = execute_bounded_turn(self.conn, parsed, self._state())

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.product_ids, ["p2"])
        self.assertIn("Beta Phone", result.response_text)
        row = self.conn.execute("SELECT product_id, quantity FROM cart_items").fetchone()
        self.assertEqual(row["product_id"], "p2")
        self.assertEqual(row["quantity"], 2)

    def test_compares_referenced_products_by_price(self) -> None:
        parsed = ParsedTurn(
            raw_message="第一个和第二个哪个更便宜",
            intent_type="product_compare",
            route_hint="bounded_react",
            references=[
                ProductReference(reference_type="position", position=1),
                ProductReference(reference_type="position", position=2),
            ],
            compare_dimensions=["price"],
        )

        result = execute_bounded_turn(self.conn, parsed, self._state())

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.product_ids, ["p1", "p2"])
        self.assertIn("建议", result.response_text)
        self.assertIn("Beta Phone", result.response_text)
        self.assertIsNotNone(result.comparison)
        self.assertEqual(result.comparison["title"], "Alpha vs Beta 对比")
        self.assertIn("价格", [row["dimension"] for row in result.comparison["rows"]])
        self.assertNotIn("品类", [row["dimension"] for row in result.comparison["rows"]])
        self.assertEqual(len(result.comparison["sections"]), 2)
        self.assertEqual([product["id"] for product in result.products], ["p1", "p2"])

    def test_overall_compare_does_not_use_stock_as_default_winner_reason(self) -> None:
        parsed = ParsedTurn(
            raw_message="对比前两个",
            intent_type="product_compare",
            route_hint="bounded_react",
            references=[
                ProductReference(reference_type="position", position=1),
                ProductReference(reference_type="position", position=2),
            ],
            compare_dimensions=["overall"],
        )

        with patch(
            "app.bounded_agent_tools._write_compare_payload_with_llm",
            side_effect=LLMGenerationError("skip network"),
        ):
            result = execute_bounded_turn(self.conn, parsed, self._state())

        dimensions = [row["dimension"] for row in result.comparison["rows"]]
        self.assertNotIn("库存", dimensions)
        self.assertNotIn("库存更多", result.comparison["recommendation"])

    def test_llm_compare_payload_is_sanitized_and_keeps_stock_out_by_default(self) -> None:
        fallback = {
            "title": "Alpha vs Beta 对比",
            "summary": "核心差异在价格。",
            "columns": [{"label": "Alpha", "product_id": "p1"}, {"label": "Beta", "product_id": "p2"}],
            "rows": [{"dimension": "价格", "values": ["¥100", "¥60（更低）"], "highlight_index": 1}],
            "sections": [
                {"title": "选Alpha如果", "product_id": "p1", "bullets": ["更看重品牌"]},
                {"title": "选Beta如果", "product_id": "p2", "bullets": ["更看重价格"]},
            ],
            "recommendation": "预算优先选 Beta Phone。",
            "footnote": "仅基于当前商品库。",
        }
        llm_payload = {
            "summary": "Beta 更便宜，但 Alpha 库存更多。",
            "rows": [
                {"dimension": "库存", "values": ["约5件", "约3件"], "highlight_index": 0},
                {"dimension": "核心卖点", "values": ["品牌更明确", "价格更低"], "highlight_index": 1},
            ],
            "sections": [
                {"product_id": "p1", "title": "选Alpha如果", "bullets": ["偏好Alpha品牌", "库存更多"]},
                {"product_id": "p2", "title": "选Beta如果", "bullets": ["预算更敏感"]},
            ],
            "recommendation": "建议选 Alpha，因为库存更多。",
        }

        result = _sanitize_llm_comparison_payload(llm_payload, fallback, self._snapshots(["p1", "p2"]), set())

        self.assertNotIn("库存", result["summary"])
        self.assertNotIn("库存", [row["dimension"] for row in result["rows"]])
        self.assertNotIn("库存", result["recommendation"])
        for section in result["sections"]:
            self.assertTrue(all("库存" not in bullet for bullet in section["bullets"]))

    def test_answers_current_product_stock_from_database(self) -> None:
        parsed = ParsedTurn(
            raw_message="这个有货吗",
            intent_type="product_detail_qa",
            route_hint="bounded_react",
            references=[ProductReference(reference_type="current_product")],
            compare_dimensions=["stock"],
        )

        result = execute_bounded_turn(self.conn, parsed, self._state())

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.product_ids, ["p1"])
        self.assertIn("库存约 5 件", result.response_text)

    def test_invalid_position_does_not_fall_back_to_search_or_random_product(self) -> None:
        parsed = ParsedTurn(
            raw_message="把第三个加购物车",
            intent_type="cart_add",
            route_hint="bounded_react",
            references=[ProductReference(reference_type="position", position=3)],
            quantity=1,
        )

        result = execute_bounded_turn(self.conn, parsed, {"last_recommended_product_ids": ["p1"]})

        self.assertEqual(result.status, "needs_reference")
        self.assertEqual(result.product_ids, [])
        total = self.conn.execute("SELECT COUNT(*) AS total FROM cart_items").fetchone()["total"]
        self.assertEqual(total, 0)

    def test_lists_cart_items(self) -> None:
        self.conn.execute(
            "INSERT INTO cart_items(id, product_id, sku_id, quantity, selected) VALUES (?, ?, ?, ?, 1)",
            ("cart_1", "p1", "sku_p1", 1),
        )
        parsed = ParsedTurn(raw_message="购物车里有什么", intent_type="cart_list", route_hint="bounded_react")

        result = execute_bounded_turn(self.conn, parsed, self._state())

        self.assertEqual(result.status, "ok")
        self.assertIn("Alpha Phone x1", result.response_text)
        self.assertEqual(result.cart["items"][0]["product_id"], "p1")

    def test_clears_cart_items(self) -> None:
        self.conn.execute(
            "INSERT INTO cart_items(id, product_id, sku_id, quantity, selected) VALUES (?, ?, ?, ?, 1)",
            ("cart_1", "p1", "sku_p1", 2),
        )
        parsed = ParsedTurn(raw_message="清空购物车", intent_type="cart_clear", route_hint="bounded_react")

        result = execute_bounded_turn(self.conn, parsed, self._state())

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.cart["items"], [])
        total = self.conn.execute("SELECT COUNT(*) AS total FROM cart_items").fetchone()["total"]
        self.assertEqual(total, 0)

    def test_tool_gate_blocks_wrong_tool_for_intent(self) -> None:
        parsed = ParsedTurn(
            raw_message="第一个和第二个哪个更便宜",
            intent_type="product_compare",
            route_hint="bounded_react",
            references=[ProductReference(reference_type="position", position=1)],
        )

        result = execute_bounded_turn(self.conn, parsed, {"last_recommended_product_ids": ["missing"]})

        self.assertEqual(result.status, "needs_reference")
        self.assertEqual(result.products, [])

    def _state(self) -> dict:
        return {
            "last_recommended_product_ids": ["p1", "p2"],
            "current_product_id": "p1",
            "cart_context": [],
        }

    def _insert_product(
        self,
        product_id: str,
        title: str,
        brand: str,
        category: str,
        subcategory: str,
        price: float,
        stock: int,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO products(id, title, brand, category, subcategory, price, rating, image_path, marketing_description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (product_id, title, brand, category, subcategory, price, 4.5, f"{product_id}.jpg", "test"),
        )
        self.conn.execute(
            "INSERT INTO product_skus(id, product_id, sku_name, properties_json, price, stock) VALUES (?, ?, ?, ?, ?, ?)",
            (f"sku_{product_id}", product_id, "默认规格", "{}", price, stock),
        )

    def _snapshots(self, product_ids: list[str]):
        from app.bounded_agent_tools import _fetch_product_snapshots

        return _fetch_product_snapshots(self.conn, product_ids)


if __name__ == "__main__":
    unittest.main()
