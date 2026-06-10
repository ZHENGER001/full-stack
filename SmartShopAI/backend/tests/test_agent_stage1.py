from __future__ import annotations

import unittest
from unittest.mock import patch

from app import agent
from app.agent_state import AgentTurnRequest
from app.tool_registry import DEFAULT_TOOL_REGISTRY, ToolRegistry, ToolSpec


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


if __name__ == "__main__":
    unittest.main()
