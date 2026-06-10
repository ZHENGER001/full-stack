from __future__ import annotations

import unittest

from app.observability import AgentTurnMetrics, _parse_sse_chunk


class ObservabilityTest(unittest.TestCase):
    def test_parse_sse_chunk(self) -> None:
        event, payload = _parse_sse_chunk('event: products\ndata: {"products": [{"id": "p1"}]}\n\n')

        self.assertEqual(event, "products")
        self.assertEqual(payload["products"][0]["id"], "p1")

    def test_agent_turn_metrics_accepts_common_events(self) -> None:
        metrics = AgentTurnMetrics()

        metrics.observe_sse_chunk('event: delta\ndata: {"text": "收到"}\n\n')
        metrics.observe_sse_chunk('event: retrieval_status\ndata: {"turn": {"needs_clarification": false}}\n\n')
        metrics.observe_sse_chunk('event: products\ndata: {"products": [{"id": "p1"}, {"id": "p2"}]}\n\n')
        metrics.observe_sse_chunk('event: llm_status\ndata: {"mode": "cache_hit"}\n\n')
        metrics.observe_sse_chunk('event: cart\ndata: {"items": []}\n\n')
        metrics.finish()

        self.assertEqual(metrics.visible_product_count, 2)
        self.assertTrue(metrics.saw_visible_products)


if __name__ == "__main__":
    unittest.main()
