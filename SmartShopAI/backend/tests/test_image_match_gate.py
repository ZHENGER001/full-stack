from __future__ import annotations

import unittest

from app.agent import (
    build_image_candidate_query,
    image_analysis_event_payload,
    is_acceptable_image_match,
    is_searchable_image_object,
    mock_detect_from_hint,
    normalize_image_object,
    score_image_product_match,
)


class ImageMatchGateTest(unittest.TestCase):
    def test_default_photo_request_does_not_search_generic_fallback(self) -> None:
        item = normalize_image_object(mock_detect_from_hint(None))

        self.assertFalse(is_searchable_image_object(item))
        self.assertEqual(build_image_candidate_query(item, "帮我找这张图片里的类似商品"), "")

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

    def test_no_match_summary_does_not_claim_matching(self) -> None:
        payload = image_analysis_event_payload(
            {"objects": [{"object_type": "鞋"}]},
            {"match_level": "no_match"},
        )

        self.assertIn("没有足够相似", payload["summary"])
        self.assertNotIn("正在匹配", payload["summary"])


if __name__ == "__main__":
    unittest.main()
