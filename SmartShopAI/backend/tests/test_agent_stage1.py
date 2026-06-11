from __future__ import annotations

import sqlite3
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from app import agent
from app.agent import ImageAnalysisResult
from app.agent_tools import SearchProductsResult, SearchProductsVerification
from app.agentic_rag import AgenticRetrievalResult, AgenticTurnPlan
from app.agent_state import AgentTurnRequest
from app.policy_engine import PolicyDecision
from app.tool_registry import DEFAULT_TOOL_REGISTRY, ToolRegistry, ToolSpec
from app.turn_schema import ParsedTurn


class AgentStage1Test(unittest.TestCase):
    def test_stream_chat_delegates_to_orchestrator(self) -> None:
        with patch(
            "app.agent_orchestrator.stream_agent_turn",
            return_value=iter(["event-one"]),
        ) as stream:
            events = list(
                agent._stream_chat(
                    object(),
                    "session-1",
                    "推荐手机",
                    None,
                    "p-phone-1",
                    [{"product_id": "p-phone-1"}],
                )
            )

        self.assertEqual(events, ["event-one"])
        request = stream.call_args.args[1]
        self.assertIsInstance(request, AgentTurnRequest)
        self.assertEqual(request.session_id, "session-1")
        self.assertEqual(request.message, "推荐手机")
        self.assertEqual(request.current_product_id, "p-phone-1")
        self.assertEqual(request.cart_context, [{"product_id": "p-phone-1"}])

    def test_default_tool_registry_contains_stage1_tools(self) -> None:
        self.assertEqual(
            DEFAULT_TOOL_REGISTRY.names(),
            ["bounded_agent", "bundle_recommendation", "search_products"],
        )
        self.assertEqual(
            DEFAULT_TOOL_REGISTRY.get("search_products").route_scope,
            ("direct_tool",),
        )
        self.assertEqual(
            DEFAULT_TOOL_REGISTRY.get("bounded_agent").route_scope,
            ("bounded_react",),
        )

    def test_tool_registry_calls_registered_handler(self) -> None:
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name="echo",
                handler=lambda *, value: {"value": value},
                route_scope=("test",),
            )
        )

        self.assertEqual(registry.call("echo", value="ok"), {"value": "ok"})
        with self.assertRaises(KeyError):
            registry.call("missing")

    def test_image_turn_bypasses_text_clarification_and_calls_vlm(self) -> None:
        from app.agent_orchestrator import stream_agent_turn

        conn = make_stream_test_db()
        plan = make_phone_clarification_plan()
        retrieval_result = make_empty_retrieval_result()
        analysis = ImageAnalysisResult(
            detected={
                "object_type": "背包",
                "label": "背包",
                "category": "旅行户外",
                "subcategory": "背包",
                "color": "黑色",
                "style": "通勤",
                "scene": ["通勤"],
                "search_terms": ["黑色背包", "通勤背包"],
                "confidence": 0.92,
            },
            query="背包 旅行户外 黑色背包 通勤背包",
            objects=[],
            provider="test",
        )

        with common_stream_patches(plan, retrieval_result) as patches:
            patches["analyze"].return_value = analysis
            events = list(
                stream_agent_turn(
                    conn,
                    AgentTurnRequest(
                        session_id="s1",
                        message="帮我找类似商品 图片识别标签：mobile phone 推断品类：数码电子 手机",
                        image_id="img_1",
                    ),
                )
            )

        joined = "\n".join(events)
        self.assertTrue(patches["analyze"].called)
        self.assertTrue(patches["search"].called)
        self.assertIsNone(patches["search"].call_args.kwargs["turn_plan"])
        self.assertIn("event: retrieval_status", joined)
        self.assertIn("event: image_analysis", joined)
        self.assertIn('"needs_clarification": false', joined)
        self.assertNotIn("更看重拍照", joined)

    def test_text_turn_still_returns_preference_clarification(self) -> None:
        from app.agent_orchestrator import stream_agent_turn

        conn = make_stream_test_db()
        plan = make_phone_clarification_plan()
        retrieval_result = make_empty_retrieval_result()

        with common_stream_patches(plan, retrieval_result) as patches:
            events = list(
                stream_agent_turn(
                    conn,
                    AgentTurnRequest(
                        session_id="s1",
                        message="推荐手机",
                    ),
                )
            )

        joined = "\n".join(events)
        self.assertFalse(patches["analyze"].called)
        self.assertFalse(patches["search"].called)
        self.assertIn("更看重拍照", joined)


def make_stream_test_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE chat_sessions (
            id TEXT PRIMARY KEY,
            last_query TEXT,
            last_recommended_product_ids TEXT,
            current_product_id TEXT,
            last_actions TEXT,
            structured_state_json TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE chat_messages (
            id TEXT PRIMARY KEY,
            session_id TEXT,
            role TEXT,
            content TEXT,
            image_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
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
    return conn


def make_phone_clarification_plan() -> AgenticTurnPlan:
    question = "请问你更看重拍照、续航、性能还是性价比？预算大概多少？"
    parsed = ParsedTurn(
        raw_message="推荐手机",
        intent_type="product_search",
        route_hint="no_tool",
        needs_clarification=True,
        clarification_question=question,
    )
    return AgenticTurnPlan(
        parsed_turn=parsed,
        policy=PolicyDecision(route_hint="no_tool", should_call_search=False, response_text=question),
    )


def make_empty_retrieval_result() -> AgenticRetrievalResult:
    search_result = SearchProductsResult(
        status="empty",
        products=[],
        alternatives=[],
        diagnostics={},
        verification=SearchProductsVerification(status="empty"),
    )
    return AgenticRetrievalResult(
        query="背包 旅行户外 黑色背包 通勤背包",
        parsed_filters={},
        search_result=search_result,
    )


def fake_stream_grounded_answer_events(*_args, **_kwargs):
    if False:
        yield ""
    return "当前商品库没有找到完全匹配的商品。", {"mode": "fallback"}


@contextmanager
def common_stream_patches(plan: AgenticTurnPlan, retrieval_result: AgenticRetrievalResult):
    async def fake_react_plan(*_args, **_kwargs):
        return SimpleNamespace(should_execute=False, steps=[])

    async def fake_agentic_plan(*_args, **_kwargs):
        return plan

    with (
        patch("app.agent_orchestrator.plan_react_transaction", side_effect=fake_react_plan),
        patch("app.agent_orchestrator.plan_agentic_turn", side_effect=fake_agentic_plan),
        patch("app.agent_orchestrator.DEFAULT_TOOL_REGISTRY.call", return_value=retrieval_result) as search,
        patch("app.agent.analyze_image") as analyze,
        patch("app.agent.resolve_cart_product_id", return_value=None),
        patch("app.agent.get_cart", return_value=SimpleNamespace(items=[])),
        patch("app.agent.retrieve_visual_image_candidates", return_value=([], {"status": "skipped"}, {})),
        patch("app.agent.build_actions", return_value=[]),
        patch("app.agent.debug_vlm_event"),
        patch("app.agent.stream_grounded_answer_events", side_effect=fake_stream_grounded_answer_events),
        patch("app.agent_orchestrator.time.sleep"),
    ):
        yield {"analyze": analyze, "search": search}


if __name__ == "__main__":
    unittest.main()
