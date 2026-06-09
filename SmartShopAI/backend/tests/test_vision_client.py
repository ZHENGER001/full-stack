from __future__ import annotations

import json
import unittest

from app.vision_client import parse_vlm_response_content


class VisionClientTest(unittest.TestCase):
    def test_parses_vlm_json_code_fence(self) -> None:
        content = """
        ```json
        {
          "objects": [
            {
              "object_type": "双肩包",
              "category": "旅行户外",
              "subcategory": "背包",
              "color": "黑色",
              "style": "商务通勤",
              "material": "尼龙",
              "scene": ["通勤", "办公"],
              "search_terms": ["双肩包", "电脑包"],
              "confidence": 0.78
            }
          ]
        }
        ```
        """

        objects = parse_vlm_response_content(content)

        self.assertEqual(len(objects), 1)
        self.assertEqual(objects[0].object_type, "双肩包")
        self.assertEqual(objects[0].scene, ["通勤", "办公"])
        self.assertEqual(objects[0].search_terms, ["双肩包", "电脑包"])
        self.assertAlmostEqual(objects[0].confidence, 0.78)

    def test_limits_to_three_objects(self) -> None:
        content = {
            "objects": [
                {"object_type": "耳机", "confidence": 0.9},
                {"object_type": "充电盒", "confidence": 0.7},
                {"object_type": "数据线", "confidence": 0.4},
                {"object_type": "桌面", "confidence": 0.3},
            ]
        }

        objects = parse_vlm_response_content(json.dumps(content, ensure_ascii=False))

        self.assertEqual([item.object_type for item in objects], ["耳机", "充电盒", "数据线"])


if __name__ == "__main__":
    unittest.main()
