from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path

from app import agent
from app.agent import (
    BATCH_CART_CONFIRM_PREFIX,
    emit_batch_cart_confirm_turn,
    emit_react_transaction_turn,
    ensure_session,
    update_session_state,
)
from app.bundle_recommendation import BundleRecommendationResult
from app.database import dict_factory
from app.react_planner import plan_react_transaction_with_rules
from app.schemas import ProductCard


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
        self._insert_address()
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

    def test_bundle_recommendation_state_matches_visible_products(self) -> None:
        for index in range(4, 6):
            self._insert_product(f"p{index}", f"Product {index}")

        products = [self._product_card(f"p{index}", f"Product {index}") for index in range(1, 6)]
        original_retrieve = agent.retrieve_bundle_recommendations
        original_enrich = agent.enrich_product_presentations

        def fake_retrieve_bundle_recommendations(*_args, **_kwargs) -> BundleRecommendationResult:
            return BundleRecommendationResult(scene="组合方案", slots=[], products=products, diagnostics={})

        class FakeParsedTurn:
            bundle_slots = None

        class FakeTurnPlan:
            graph_backend = "test"
            parsed_turn = FakeParsedTurn()

            def status_payload(self) -> dict:
                return {"graph_backend": "test"}

        try:
            agent.retrieve_bundle_recommendations = fake_retrieve_bundle_recommendations
            agent.enrich_product_presentations = lambda *_args, **_kwargs: None
            events = [
                event_payload(event)
                for event in agent.emit_bundle_recommendation_turn(
                    self.conn,
                    "session-1",
                    "推荐一个方案",
                    None,
                    FakeTurnPlan(),
                )
            ]
        finally:
            agent.retrieve_bundle_recommendations = original_retrieve
            agent.enrich_product_presentations = original_enrich

        product_payloads = [payload for event, payload in events if event == "products"]
        self.assertEqual(len(product_payloads), 1)
        self.assertEqual([item["id"] for item in product_payloads[0]["products"]], ["p1", "p2", "p3"])
        row = self.conn.execute("SELECT last_recommended_product_ids FROM chat_sessions WHERE id = ?", ("session-1",)).fetchone()
        self.assertEqual(json.loads(row["last_recommended_product_ids"]), ["p1", "p2", "p3"])

    def test_react_checkout_requires_address_confirmation_before_payment(self) -> None:
        message = "第一款直接买"
        plan = plan_react_transaction_with_rules(
            message,
            {"last_recommended_product_ids": ["p1", "p2", "p3"], "current_product_id": "p1"},
        )

        events = [event_payload(event) for event in emit_react_transaction_turn(self.conn, "session-1", message, None, plan)]

        statuses = [payload["status"] for event, payload in events if event == "order_status"]
        self.assertIn("awaiting_confirmation", statuses)
        self.assertNotIn("paid", statuses)
        confirmation_text = "".join(payload["text"] for event, payload in events if event == "delta")
        self.assertIn("订单确认卡", confirmation_text)
        self.assertNotIn("| 字段 | 内容 |", confirmation_text)
        confirmation_cards = [payload for event, payload in events if event == "checkout_confirmation"]
        self.assertEqual(len(confirmation_cards), 1)
        confirmation_card = confirmation_cards[0]
        self.assertEqual(confirmation_card["status_label"], "待确认订单")
        self.assertEqual(confirmation_card["receiver_name"], "张三")
        self.assertEqual(confirmation_card["receiver_phone"], "13800000000")
        self.assertEqual(confirmation_card["address"], "浙江省杭州市西湖区文三路 1 号")
        self.assertEqual(confirmation_card["item_count"], 1)
        self.assertEqual(confirmation_card["product_total"], 100.0)
        self.assertEqual(confirmation_card["payable_amount"], 100.0)
        self.assertEqual(confirmation_card["shown_limit"], 3)
        self.assertEqual(confirmation_card["items"][0]["title"], "Product 1")
        self.assertEqual(confirmation_card["items"][0]["line_total"], 100.0)
        actions = [payload for event, payload in events if event == "actions"][-1]["actions"]
        self.assertEqual([action["label"] for action in actions], ["修改商品", "修改地址", "确认下单并支付"])
        self.assertEqual(actions[0]["type"], "open_cart")
        self.assertIn("checkout_signature", actions[-1])
        total_orders = self.conn.execute("SELECT COUNT(*) AS total FROM orders").fetchone()["total"]
        self.assertEqual(total_orders, 0)

        confirm_message = "确认下单并支付"
        confirm_plan = plan_react_transaction_with_rules(confirm_message, {"current_product_id": "p1"})
        confirm_events = [
            event_payload(event)
            for event in emit_react_transaction_turn(self.conn, "session-1", confirm_message, None, confirm_plan)
        ]

        confirm_statuses = [payload["status"] for event, payload in confirm_events if event == "order_status"]
        self.assertIn("paid", confirm_statuses)
        success_cards = [payload for event, payload in confirm_events if event == "order_success"]
        self.assertEqual(len(success_cards), 1)
        success_card = success_cards[0]
        self.assertTrue(success_card["order_id"].startswith("ord_"))
        self.assertTrue(success_card["payment_id"].startswith("pay_"))
        self.assertEqual(success_card["receiver_name"], "张三")
        self.assertEqual(success_card["receiver_phone"], "13800000000")
        self.assertEqual(success_card["receiver_address"], "浙江省杭州市西湖区文三路 1 号")
        self.assertEqual(success_card["paid_amount"], 100.0)
        self.assertEqual(success_card["items"][0]["product_id"], "p1")
        self.assertEqual(success_card["items"][0]["name"], "Product 1")
        self.assertEqual(success_card["items"][0]["spec_text"], "默认规格")
        self.assertEqual(success_card["items"][0]["line_total"], 100.0)
        paid_text = "".join(payload["text"] for event, payload in confirm_events if event == "delta")
        self.assertIn("订单号：", paid_text)
        self.assertIn("Product 1（默认规格）", paid_text)
        self.assertNotIn("| 商品 | 规格 | 单价 | 数量 | 小计 |", paid_text)
        total_orders = self.conn.execute("SELECT COUNT(*) AS total FROM orders").fetchone()["total"]
        self.assertEqual(total_orders, 1)

    def _insert_product(self, product_id: str, title: str) -> None:
        self.conn.execute(
            """
            INSERT INTO products(id, title, brand, category, subcategory, price, rating, image_path, marketing_description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (product_id, title, "Brand", "数码电子", "智能手机", 100, 4.5, f"{product_id}.jpg", "test"),
        )
        self._insert_sku(product_id, f"sku_{product_id}", "默认规格", {}, 100, 5)

    def _product_card(self, product_id: str, title: str) -> ProductCard:
        return ProductCard(
            id=product_id,
            title=title,
            brand="Brand",
            category="数码电子",
            subcategory="智能手机",
            price=100,
            rating=4.5,
            image_path=f"{product_id}.jpg",
            marketing_description="test",
        )

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

    def _insert_address(self) -> None:
        self.conn.execute(
            """
            INSERT INTO addresses(id, receiver_name, phone, province, city, district, detail, is_default)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("addr_1", "张三", "13800000000", "浙江省", "杭州市", "西湖区", "文三路 1 号", 1),
        )


if __name__ == "__main__":
    unittest.main()
