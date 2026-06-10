from __future__ import annotations

import unittest
from unittest.mock import patch

from app import timeouts
from app.embedding_client import EmbeddingError
from app.vector_retriever import milvus_semantic_search_with_diagnostics


class StabilityDegradationTest(unittest.TestCase):
    def test_llm_timeout_defaults_to_short_service_timeout(self) -> None:
        with patch("app.timeouts.env_value", return_value=None):
            self.assertEqual(timeouts.llm_timeout_seconds(), 12.0)
            self.assertEqual(timeouts.llm_connect_timeout_seconds(), 3.0)

    def test_dense_search_degrades_when_embedding_unavailable(self) -> None:
        with patch("app.vector_retriever.embed_texts", side_effect=EmbeddingError("not configured")):
            result = milvus_semantic_search_with_diagnostics("推荐手机", top_k=3)

        self.assertEqual(result.hits, [])
        self.assertEqual(result.diagnostics["status"], "degraded")
        self.assertEqual(result.diagnostics["reason"], "embedding_unavailable")


if __name__ == "__main__":
    unittest.main()
