from __future__ import annotations

import unittest

from app.agent import image_detection_intro, mock_detect_from_hint


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


if __name__ == "__main__":
    unittest.main()
