from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.agent import analyze_image, build_final_user_query, detected_to_query, image_detection_intro, mock_detect_from_hint
from app.vision_client import VLMAnalysis, VLMObject


class ImageDetectionTest(unittest.TestCase):
    def test_agent_orchestrator_imports(self) -> None:
        import app.agent_orchestrator  # noqa: F401

    def test_phone_hint_maps_to_digital_phone(self) -> None:
        detected = mock_detect_from_hint("图片识别标签：mobile phone 推断品类：数码电子 手机")

        self.assertEqual(detected["object_type"], "手机")
        self.assertEqual(detected["style"], "数码")
        self.assertNotEqual(detected["style"], "休闲")

    def test_unknown_image_intro_does_not_claim_black_casual(self) -> None:
        detected = mock_detect_from_hint("请根据这张图片推荐相关商品")
        intro = image_detection_intro(detected)

        self.assertNotIn("黑色休闲", intro)
        self.assertIn("图片线索", intro)

    def test_generic_camera_hint_is_not_added_to_search_query(self) -> None:
        query = detected_to_query(
            {
                "object_type": "手机",
                "category": "数码电子",
                "subcategory": "智能手机",
                "search_terms": ["拍照手机", "智能手机"],
                "color": "黑色",
                "confidence": 0.8,
            },
            "识别图片中的可购物商品，并生成适合商品检索的关键词",
        )

        self.assertIn("智能手机", query)
        self.assertIn("拍照手机", query)
        self.assertNotIn("识别图片", query)
        self.assertNotIn("检索", query)

    def test_mlkit_shirt_hint_does_not_add_hoodie_to_image_query(self) -> None:
        query = detected_to_query(
            {
                "object_type": "T恤",
                "category": "服饰运动",
                "subcategory": "短袖T恤",
                "search_terms": ["T恤", "短袖", "上衣"],
                "color": "黑色",
                "confidence": 0.82,
            },
            "图片识别标签：Shirt Clothing 推断品类：衣服 卫衣 外套",
        )

        self.assertIn("短袖T恤", query)
        self.assertIn("T恤", query)
        self.assertNotIn("卫衣", query)
        self.assertNotIn("外套", query)
        self.assertNotIn("图片识别标签", query)

    def test_mlkit_hoodie_hint_can_keep_hoodie(self) -> None:
        query = detected_to_query(
            {
                "object_type": "卫衣",
                "category": "服饰运动",
                "subcategory": "卫衣",
                "search_terms": ["卫衣", "连帽上衣"],
                "confidence": 0.78,
            },
            "图片识别标签：Hoodie Clothing 推断品类：衣服 卫衣 外套",
        )

        self.assertIn("卫衣", query)
        self.assertNotIn("短袖", query)

    def test_analyze_image_uses_vlm_when_available(self) -> None:
        conn, image_path, temp_dir = make_image_test_db()
        self.addCleanup(temp_dir.cleanup)

        async def fake_vlm(path: Path, user_hint: str | None = None, catalog_taxonomy: str | None = None) -> VLMAnalysis:
            self.assertEqual(path, image_path)
            self.assertEqual(user_hint, "找类似手机")
            self.assertIn("数码电子: 手机", catalog_taxonomy or "")
            return VLMAnalysis(
                objects=[
                    VLMObject(
                        object_type="手机",
                        category="数码电子",
                        subcategory="手机",
                        color="黑色",
                        style="旗舰",
                        scene=["通勤"],
                        search_terms=["智能手机", "拍照手机"],
                        confidence=0.86,
                    )
                ],
                provider="poe",
                model="GPT-4o",
            )

        with patch("app.agent.analyze_image_file_with_vlm", side_effect=fake_vlm):
            result = analyze_image(conn, "img_test", "找类似手机")

        self.assertEqual(result.provider, "poe")
        self.assertEqual(result.model, "GPT-4o")
        self.assertFalse(result.fallback)
        self.assertEqual(result.detected["label"], "手机")
        self.assertEqual(result.detected["confidence"], 0.86)
        self.assertIn("智能手机", result.query)

    def test_analyze_image_falls_back_to_mock_when_vlm_fails(self) -> None:
        conn, _, temp_dir = make_image_test_db()
        self.addCleanup(temp_dir.cleanup)

        async def failing_vlm(*_args, **_kwargs) -> VLMAnalysis:
            raise RuntimeError("unavailable")

        with patch("app.agent.analyze_image_file_with_vlm", side_effect=failing_vlm):
            result = analyze_image(conn, "img_test", "图片识别标签：mobile phone")

        self.assertEqual(result.provider, "mock")
        self.assertTrue(result.fallback)
        self.assertEqual(result.detected["label"], "手机")
        self.assertIn("手机", result.query)

    def test_image_query_does_not_merge_previous_product_or_raw_mlkit_hint(self) -> None:
        conn = make_query_builder_test_db()
        message = "帮我找类似商品 图片识别标签：Bag Handbag Jeans Cat Jacket 推断品类：外套 包 背包 通勤"

        query = build_final_user_query(
            conn,
            message,
            "背包 旅行户外 黑色背包 通勤背包",
            "p_phone",
            "s1",
        )

        self.assertIn("黑色背包", query)
        self.assertIn("通勤背包", query)
        for term in (
            "OPPO",
            "智能手机",
            "手机",
            "咖啡",
            "Bag",
            "Handbag",
            "Jeans",
            "Cat",
            "Jacket",
            "外套",
            "图片识别标签",
            "推断品类",
        ):
            self.assertNotIn(term, query)

    def test_text_reference_still_merges_current_product(self) -> None:
        conn = make_query_builder_test_db()

        query = build_final_user_query(conn, "这款有没有类似的", None, None, "s1")

        self.assertIn("OPPO Reno 16 Pro", query)
        self.assertIn("智能手机", query)
        self.assertIn("OPPO", query)

    def test_image_query_keeps_user_constraints_before_mlkit_hint(self) -> None:
        conn = make_query_builder_test_db()
        message = "预算300以内 要通勤 帮我找类似商品 图片识别标签：Bag Jeans Cat 推断品类：外套 包"

        query = build_final_user_query(conn, message, "背包 旅行户外 黑色背包", None, "s1")

        self.assertIn("预算300以内", query)
        self.assertIn("要通勤", query)
        self.assertIn("黑色背包", query)
        for term in ("Jeans", "Cat", "外套", "图片识别标签"):
            self.assertNotIn(term, query)


def make_image_test_db() -> tuple[sqlite3.Connection, Path, tempfile.TemporaryDirectory[str]]:
    temp_dir = tempfile.TemporaryDirectory()
    image_path = Path(temp_dir.name) / "upload.jpg"
    image_path.write_bytes(b"fake image")
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE uploaded_images (
            image_id TEXT PRIMARY KEY,
            image_url TEXT NOT NULL,
            file_path TEXT NOT NULL,
            detected_json TEXT,
            query TEXT
        )
        """
    )
    conn.execute("CREATE TABLE products (brand TEXT, category TEXT, subcategory TEXT)")
    conn.execute("INSERT INTO products(brand, category, subcategory) VALUES ('OPPO', '数码电子', '手机')")
    conn.execute(
        "INSERT INTO uploaded_images(image_id, image_url, file_path) VALUES (?, ?, ?)",
        ("img_test", "/uploads/upload.jpg", str(image_path)),
    )
    return conn, image_path, temp_dir


def make_query_builder_test_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE products (
            id TEXT PRIMARY KEY,
            title TEXT,
            brand TEXT,
            category TEXT,
            subcategory TEXT,
            marketing_description TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE chat_sessions (
            id TEXT PRIMARY KEY,
            last_query TEXT,
            current_product_id TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO products(id, title, brand, category, subcategory, marketing_description)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "p_phone",
            "OPPO Reno 16 Pro 轻薄人像摄影高刷屏快充5G智能手机12+256GB",
            "OPPO",
            "数码电子",
            "智能手机",
            "适合咖啡馆拍照和日常通勤的人像摄影手机",
        ),
    )
    conn.execute(
        "INSERT INTO chat_sessions(id, last_query, current_product_id) VALUES (?, ?, ?)",
        ("s1", "推荐一款拍照手机", "p_phone"),
    )
    return conn


if __name__ == "__main__":
    unittest.main()
