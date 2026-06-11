from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.milvus_client import MilvusSearchHit
from app.visual_embedding_client import embed_image_perceptual
from app.visual_retriever import visual_image_search_with_diagnostics


class VisualRetrieverTest(unittest.TestCase):
    def test_perceptual_embedding_is_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "red.jpg"
            Image.new("RGB", (32, 32), color=(220, 20, 30)).save(image_path)

            vector = embed_image_perceptual(image_path)

        self.assertGreater(len(vector), 100)
        self.assertAlmostEqual(math.sqrt(sum(value * value for value in vector)), 1.0, places=5)

    def test_visual_search_returns_milvus_hits(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "shoe.jpg"
            Image.new("RGB", (32, 32), color=(20, 20, 20)).save(image_path)

            with (
                patch("app.visual_retriever.MilvusRestClient") as client_cls,
                patch("app.visual_retriever.visual_match_min_score", return_value=0.3),
            ):
                client_cls.return_value.search.return_value = [
                    MilvusSearchHit(product_id="shoe_1", score=0.86),
                    MilvusSearchHit(product_id="weak", score=0.1),
                ]
                result = visual_image_search_with_diagnostics(image_path, top_k=5)

        self.assertEqual([hit["product_id"] for hit in result.hits], ["shoe_1"])
        self.assertEqual(result.diagnostics["status"], "ok")
        self.assertEqual(result.diagnostics["accepted_count"], 1)

    def test_visual_search_degrades_on_invalid_image(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "bad.jpg"
            image_path.write_bytes(b"not an image")

            result = visual_image_search_with_diagnostics(image_path, top_k=5)

        self.assertEqual(result.hits, [])
        self.assertEqual(result.diagnostics["status"], "degraded")
        self.assertEqual(result.diagnostics["reason"], "visual_embedding_unavailable")


if __name__ == "__main__":
    unittest.main()
