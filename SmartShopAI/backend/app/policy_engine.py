from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .turn_schema import ParsedTurn, RouteHint


@dataclass(frozen=True)
class PolicyDecision:
    route_hint: RouteHint
    should_call_search: bool
    response_text: str | None = None


def decide_policy(parsed_turn: ParsedTurn, conversation_state: dict[str, Any] | None = None) -> PolicyDecision:
    route_hint = parsed_turn.route_hint
    if parsed_turn.intent_type == "greeting":
        return PolicyDecision(route_hint="no_tool", should_call_search=False, response_text="你好，我可以帮你查找和筛选商品。")
    if parsed_turn.intent_type == "capability_question":
        return PolicyDecision(route_hint="no_tool", should_call_search=False, response_text="我可以帮你找商品、筛选条件、查看商品信息和处理购物车操作。")
    if parsed_turn.needs_clarification or route_hint == "no_tool":
        return PolicyDecision(
            route_hint="no_tool",
            should_call_search=False,
            response_text=parsed_turn.clarification_question or "你想找哪一类商品？",
        )
    if route_hint == "direct_tool":
        return PolicyDecision(route_hint="direct_tool", should_call_search=True)
    if route_hint == "plan_execute":
        return PolicyDecision(route_hint="plan_execute", should_call_search=False, response_text="组合推荐能力正在接入中。")
    return PolicyDecision(route_hint="bounded_react", should_call_search=False, response_text="这个操作我正在支持中。")
