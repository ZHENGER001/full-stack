from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .agent_tools import SearchProductsInput, SearchProductsResult, call_search_products_tool
from .policy_engine import PolicyDecision, decide_policy
from .query_parser import parse_user_filters
from .turn_parser_hybrid import parse_turn_hybrid
from .turn_schema import ParsedTurn


GRAPH_PIPELINE = [
    "turn_memory",
    "intent_parser",
    "policy_router",
    "dense_milvus",
    "bm25",
    "keyword",
    "rrf",
    "sqlite_hydrate",
    "verifier",
    "grounded_writer",
]


@dataclass(frozen=True)
class AgenticTurnPlan:
    parsed_turn: ParsedTurn
    policy: PolicyDecision

    @property
    def should_run_bounded_tool(self) -> bool:
        return self.policy.route_hint == "bounded_react"

    @property
    def should_search_products(self) -> bool:
        return self.policy.should_call_search

    def retrieval_constraints(self) -> dict[str, Any]:
        return self.parsed_turn.constraints.model_dump(mode="json")

    def retrieval_policy(self) -> dict[str, Any]:
        return self.parsed_turn.retrieval_policy_hint.model_dump(mode="json")

    def status_payload(self) -> dict[str, Any]:
        return {
            "intent_type": self.parsed_turn.intent_type,
            "route_hint": self.parsed_turn.route_hint,
            "needs_clarification": self.parsed_turn.needs_clarification,
        }


@dataclass(frozen=True)
class AgenticRetrievalResult:
    query: str
    parsed_filters: dict[str, Any]
    search_result: SearchProductsResult
    pipeline: list[str] = field(default_factory=lambda: list(GRAPH_PIPELINE))
    sources: list[str] = field(default_factory=lambda: ["dense_milvus", "bm25", "keyword"])
    fusion: str = "rrf"
    vector_backend: str = "milvus"


async def plan_agentic_turn(
    message: str,
    chat_history: list[dict[str, str]],
    conversation_state: dict[str, Any],
) -> AgenticTurnPlan:
    parsed_turn = await parse_turn_hybrid(message, chat_history, conversation_state)
    return AgenticTurnPlan(
        parsed_turn=parsed_turn,
        policy=decide_policy(parsed_turn, conversation_state),
    )


def retrieve_products_for_turn(
    conn,
    query: str,
    known_brands: list[str],
    plan: AgenticTurnPlan | None,
    top_k: int = 3,
) -> AgenticRetrievalResult:
    parsed_filters = parse_user_filters(query, known_brands)
    search_result = call_search_products_tool(
        conn,
        SearchProductsInput(
            query=query,
            top_k=top_k,
            constraints=plan.retrieval_constraints() if plan else {},
            retrieval_policy=plan.retrieval_policy() if plan else {},
        ),
    )
    return AgenticRetrievalResult(
        query=query,
        parsed_filters=parsed_filters,
        search_result=search_result,
    )
