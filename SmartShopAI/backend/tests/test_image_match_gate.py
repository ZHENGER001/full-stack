from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.agent import (
    ImageAnalysisResult,
    build_image_candidate_query,
    filter_products_for_image_match,
    image_analysis_event_payload,
    is_acceptable_image_match,
    is_searchable_image_object,
    mock_detect_from_hint,
    normalize_image_object,
    retrieve_image_match_products,
    score_image_product_match,
)
from app.query_parser import parse_user_filters
from app.schemas import ProductCard


class ImageMatchGateTest(unittest.TestCase):
    def test_default_photo_request_does_not_search_generic_fallback(self) -> None:
        item = normalize_image_object(mock_detect_from_hint(None))

        self.assertFalse(is_searchable_image_object(item))
        self.assertEqual(build_image_candidate_query(item, "帮我找这张图片里的类似商品"), "")

    def test_vlm_brand_guess_is_removed_from_image_query(self) -> None:
        item = normalize_image_object(
            {
                "object_type": "智能手机",
                "category": "数码电子",
                "subcategory": "智能手机",
                "color": "蓝色",
                "search_terms": ["智能手机", "vivo手机", "蓝色手机"],
                "confidence": 0.95,
            }
        )

        query = build_image_candidate_query(item, "帮我找类似商品", brand_terms=["vivo"])
        filters = parse_user_filters(query, known_brands=["vivo"])

        self.assertIn("智能手机", query)
        self.assertIn("手机", query)
        self.assertNotIn("vivo", query.lower())
        self.assertEqual(filters["brands"], [])

    def test_category_only_image_match_is_rejected(self) -> None:
        product = {
            "id": "p1",
            "title": "保温运动水壶",
            "brand": "测试",
            "category": "服饰运动",
            "subcategory": "运动配件",
            "marketing_description": "户外补水",
            "sku_summary": "黑色",
            "rerank_score": 1.6,
        }
        item = normalize_image_object(
            {
                "object_type": "鞋",
                "category": "服饰运动",
                "subcategory": "跑步鞋",
                "search_terms": ["鞋"],
                "confidence": 0.9,
            }
        )

        score, level, _ = score_image_product_match(product, item, object_index=0)

        self.assertEqual(level, "weak")
        self.assertFalse(is_acceptable_image_match(score, level))

    def test_subcategory_and_name_evidence_is_accepted(self) -> None:
        product = {
            "id": "p1",
            "title": "Nike 飞马 男款跑步鞋",
            "brand": "Nike",
            "category": "服饰运动",
            "subcategory": "跑步鞋",
            "marketing_description": "轻量缓震",
            "sku_summary": "黑色 42码",
            "rerank_score": 1.6,
        }
        item = normalize_image_object(
            {
                "object_type": "鞋",
                "category": "服饰运动",
                "subcategory": "跑步鞋",
                "color": "黑色",
                "search_terms": ["跑步鞋"],
                "confidence": 0.62,
            }
        )

        score, level, _ = score_image_product_match(product, item, object_index=0)

        self.assertEqual(level, "exact_like")
        self.assertTrue(is_acceptable_image_match(score, level))

    def test_visual_vector_evidence_can_accept_image_candidate(self) -> None:
        product = {
            "id": "p1",
            "title": "商品主图相似候选",
            "brand": "测试",
            "category": "服饰运动",
            "subcategory": "运动配件",
            "marketing_description": "图片向量召回的候选",
            "sku_summary": "默认规格",
            "_visual_vector_score": 0.92,
        }
        item = normalize_image_object(
            {
                "object_type": "鞋",
                "category": "服饰运动",
                "subcategory": "跑步鞋",
                "search_terms": ["跑步鞋"],
                "confidence": 0.7,
            }
        )

        score, level, evidence = score_image_product_match(product, item, object_index=0)

        self.assertEqual(level, "similar")
        self.assertTrue(is_acceptable_image_match(score, level))
        self.assertIn("visual_vector", evidence["evidence"])

    def test_image_filter_rejects_conflicting_clothing_subcategory(self) -> None:
        image_item = normalize_image_object(
            {
                "object_type": "T恤",
                "category": "服饰运动",
                "subcategory": "短袖T恤",
                "color": "黑色",
                "search_terms": ["T恤", "短袖"],
                "confidence": 0.82,
            }
        )
        products = [
            {
                "id": "hoodie",
                "title": "李宁 男子黑色连帽卫衣",
                "brand": "李宁",
                "category": "服饰运动",
                "subcategory": "卫衣",
                "marketing_description": "可内搭薄T恤",
                "sku_summary": "黑色",
            },
            {
                "id": "tee",
                "title": "优衣库 黑色短袖T恤",
                "brand": "优衣库",
                "category": "服饰运动",
                "subcategory": "短袖T恤",
                "marketing_description": "基础纯色上衣",
                "sku_summary": "黑色",
            },
        ]
        analysis = ImageAnalysisResult(
            detected=image_item,
            query="短袖T恤 T恤 黑色",
            objects=[image_item],
            provider="test",
        )

        filtered, diagnostics = filter_products_for_image_match(products, analysis)

        self.assertEqual([product["id"] for product in filtered], ["tee"])
        self.assertEqual(diagnostics["accepted_count"], 1)
        self.assertEqual(diagnostics["rejected"][0]["reason"], "visual_conflict")

    def test_image_recommendation_uses_visual_filter_after_retrieval(self) -> None:
        image_item = normalize_image_object(
            {
                "object_type": "T恤",
                "category": "服饰运动",
                "subcategory": "短袖T恤",
                "search_terms": ["T恤", "短袖"],
                "confidence": 0.82,
            }
        )
        analysis = ImageAnalysisResult(
            detected=image_item,
            query="短袖T恤 T恤",
            objects=[image_item],
            provider="test",
        )
        cards = [
            product_card("hoodie", "李宁 男子黑色连帽卫衣", "卫衣"),
            product_card("tee", "优衣库 黑色短袖T恤", "短袖T恤"),
        ]
        grounded = [
            {
                **cards[0].model_dump(),
                "marketing_description": "可内搭薄T恤",
                "sku_summary": "黑色",
            },
            {
                **cards[1].model_dump(),
                "marketing_description": "基础纯色上衣",
                "sku_summary": "黑色",
            },
        ]
        retrieval_result = SimpleNamespace(
            search_result=SimpleNamespace(products=cards, alternatives=[], status="ok"),
            parsed_filters={},
        )

        with (
            patch("app.agent.retrieve_products_for_turn", return_value=retrieval_result) as retrieve,
            patch("app.agent.load_known_brands", return_value=[]),
            patch("app.agent.build_grounded_products", return_value=grounded),
        ):
            products, diagnostics = retrieve_image_match_products(object(), analysis, limit=12)

        retrieve.assert_called_once()
        self.assertEqual([product.id for product in products], ["tee"])
        self.assertEqual(diagnostics["image_match"]["accepted_count"], 1)
        self.assertEqual(diagnostics["candidate_count"], 2)

    def test_no_match_summary_does_not_claim_matching(self) -> None:
        payload = image_analysis_event_payload(
            {"objects": [{"object_type": "鞋"}]},
            {"match_level": "no_match"},
        )

        self.assertIn("没有足够相似", payload["summary"])
        self.assertNotIn("正在匹配", payload["summary"])


def product_card(product_id: str, title: str, subcategory: str) -> ProductCard:
    return ProductCard(
        id=product_id,
        title=title,
        brand="测试",
        category="服饰运动",
        subcategory=subcategory,
        price=99.0,
        rating=4.6,
        image_path=f"/api/product-thumbnails/{product_id}.jpg",
        stock=10,
    )


if __name__ == "__main__":
    unittest.main()
