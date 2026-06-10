from __future__ import annotations

import unittest

from app.scene_slots import bundle_slot_candidates_for_message, is_scene_bundle_request, scene_name_for_message


class SceneSlotsTest(unittest.TestCase):
    def test_swimming_scene_loads_from_config(self) -> None:
        message = "\u7ed9\u6211\u63a8\u8350\u4e00\u5957\u4e0b\u6c34\u6e38\u6cf3\u88c5\u5907"
        slots = bundle_slot_candidates_for_message(message)

        self.assertTrue(is_scene_bundle_request(message))
        self.assertEqual(scene_name_for_message(message), "\u4e0b\u6c34\u6e38\u6cf3")
        self.assertEqual([slot.key for slot in slots[:3]], ["swimwear", "goggles", "swim_cap"])
        self.assertIn("\u6cf3\u955c", slots[1].product_mentions)

    def test_plain_single_product_need_is_not_scene_bundle(self) -> None:
        self.assertFalse(is_scene_bundle_request("\u5bb6\u91cc\u9171\u6cb9\u6ca1\u4e86"))


if __name__ == "__main__":
    unittest.main()
