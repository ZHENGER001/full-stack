from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path

from app.agent import BATCH_CART_CONFIRM_PREFIX, emit_batch_cart_confirm_turn, emit_react_transaction_turn, ensure_session, update_session_state
from app.database import dict_factory
from app.react_planner import plan_react_transaction_with_rules


def event_payload(raw_event: str) -> tuple[str, dict]:
    lines = [line for line in raw_event.splitlines() if line]
    event = lines[0].removeprefix("event:").strip()
    data = json.loads(lines[1].removeprefix("data:").strip())
    return event, data


class ReactTransactionExecutionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = dict_factory
        schema_path = Path(__file__).resolve().parents[1] / "app" / "schema.sql"
        self.conn.executescript(schema_path.read_text(encoding="utf-8"))
        for index in range(1, 4):
            self._insert_product(f"p{index}", f"Product {index}")
        ensure_session(self.conn, "session-1")
        update_session_state(
            self.conn,
            "session-1",
            last_recommended_product_ids=["p1", "p2", "p3"],
            current_product_id="p1",
        )

    def tearDown(self) -> None:
        self.conn.close()

    def test_all_recent_products_are_added_with_stable_recommendation_state(self) -> None:
        message = "全部加入购物车"
        plan = plan_react_transaction_with_rules(
            message,
            {"last_recommended_product_ids": ["p1", "p2", "p3"], "current_product_id": "p1"},
        )

        list(emit_react_transaction_turn(self.conn, "session-1", message, None, plan))

        rows = self.conn.execute("SELECT product_id FROM cart_items ORDER BY product_id").fetchall()
        self.assertEqual([row["product_id"] for row in rows], ["p1", "p2", "p3"])

    def test_batch_cart_with_multi_sku_emits_selection_payload_before_adding(self) -> None:
        self._insert_sku("p2", "sku_p2_blue", "蓝色", {"颜色": "蓝色"}, 105, 5)
        message = "全部加入购物车"
        plan = plan_react_transaction_with_rules(
            message,
            {"last_recommended_product_ids": ["p1", "p2", "p3"], "current_product_id": "p1"},
        )

        events = [event_payload(event) for event in emit_react_transaction_turn(self.conn, "session-1", message, None, plan)]

        batch_events = [payload for event, payload in events if event == "batch_cart"]
        self.assertEqual(len(batch_events), 1)
        self.assertEqual([item["product_id"] for item in batch_events[0]["items"]], ["p1", "p2", "p3"])
        self.assertEqual(batch_events[0]["items"][1]["status"], "needs_sku")
        self.assertEqual(len(batch_events[0]["items"][1]["skus"]), 2)
        total = self.conn.execute("SELECT COUNT(*) AS total FROM cart_items").fetchone()["total"]
        self.assertEqual(total, 0)

    def test_batch_cart_confirm_adds_selected_skus(self) -> None:
        self._insert_sku("p2", "sku_p2_blue", "蓝色", {"颜色": "蓝色"}, 105, 5)
        payload = {
            "items": [
                {"product_id": "p1", "sku_id": "sku_p1", "quantity": 1},
                {"product_id": "p2", "sku_id": "sku_p2_blue", "quantity": 1},
                {"product_id": "p3", "sku_id": "sku_p3", "quantity": 1},
            ]
        }
        message = BATCH_CART_CONFIRM_PREFIX + json.dumps(payload, ensure_ascii=False)

        list(emit_batch_cart_confirm_turn(self.conn, "session-1", message, None))

        rows = self.conn.execute("SELECT product_id, sku_id FROM cart_items ORDER BY product_id").fetchall()
        self.assertEqual(
            [(row["product_id"], row["sku_id"]) for row in rows],
            [("p1", "sku_p1"), ("p2", "sku_p2_blue"), ("p3", "sku_p3")],
        )

    def _insert_product(self, product_id: str, title: str) -> None:
        self.conn.execute(
            """
            INSERT INTO products(id, title, brand, category, subcategory, price, rating, image_path, marketing_description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (product_id, title, "Brand", "数码电子", "智能手机", 100, 4.5, f"{product_id}.jpg", "test"),
        )
        self._insert_sku(product_id, f"sku_{product_id}", "默认规格", {}, 100, 5)

    def _insert_sku(
        self,
        product_id: str,
        sku_id: str,
        sku_name: str,
        properties: dict,
        price: float,
        stock: int,
    ) -> None:
        self.conn.execute(
            "INSERT INTO product_skus(id, product_id, sku_name, properties_json, price, stock) VALUES (?, ?, ?, ?, ?, ?)",
            (sku_id, product_id, sku_name, json.dumps(properties, ensure_ascii=False), price, stock),
        )


if __name__ == "__main__":
    unittest.main()
