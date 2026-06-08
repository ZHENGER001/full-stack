from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict

from .agent_tools import SearchProductsInput, SearchProductsResult, call_search_products_tool
from .policy_engine import PolicyDecision, decide_policy
from .query_parser import parse_user_filters
from .turn_parser_hybrid import parse_turn_hybrid
from .turn_schema import ParsedTurn

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:  # pragma: no cover - exercised only when dependency is absent.
    END = START = StateGraph = None


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
    graph_backend: str = "langgraph_fallback"

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
            "graph_backend": self.graph_backend,
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
    graph_backend: str = "langgraph_fallback"


class AgenticPlanState(TypedDict, total=False):
    message: str
    chat_history: list[dict[str, str]]
    conversation_state: dict[str, Any]
    parsed_turn: ParsedTurn
    policy: PolicyDecision


class AgenticRetrievalState(TypedDict, total=False):
    conn: Any
    query: str
    known_brands: list[str]
    plan: AgenticTurnPlan | None
    top_k: int
    parsed_filters: dict[str, Any]
    search_result: SearchProductsResult


_PLAN_GRAPH = None
_RETRIEVAL_GRAPH = None


async def _parse_turn_node(state: AgenticPlanState) -> dict[str, Any]:
    parsed_turn = await parse_turn_hybrid(
        state["message"],
        state.get("chat_history") or [],
        state.get("conversation_state") or {},
    )
    return {"parsed_turn": parsed_turn}


def _policy_router_node(state: AgenticPlanState) -> dict[str, Any]:
    parsed_turn = state["parsed_turn"]
    return {"policy": decide_policy(parsed_turn, state.get("conversation_state") or {})}


def _parse_filters_node(state: AgenticRetrievalState) -> dict[str, Any]:
    return {
        "parsed_filters": parse_user_filters(
            state["query"],
            state.get("known_brands") or [],
        )
    }


def _search_products_node(state: AgenticRetrievalState) -> dict[str, Any]:
    plan = state.get("plan")
    search_result = call_search_products_tool(
        state["conn"],
        SearchProductsInput(
            query=state["query"],
            top_k=state.get("top_k") or 3,
            constraints=plan.retrieval_constraints() if plan else {},
            retrieval_policy=plan.retrieval_policy() if plan else {},
        ),
    )
    return {"search_result": search_result}


def langgraph_available() -> bool:
    return StateGraph is not None


def _compiled_plan_graph():
    global _PLAN_GRAPH
    if not langgraph_available():
        return None
    if _PLAN_GRAPH is None:
        builder = StateGraph(AgenticPlanState)
        builder.add_node("intent_parser", _parse_turn_node)
        builder.add_node("policy_router", _policy_router_node)
        builder.add_edge(START, "intent_parser")
        builder.add_edge("intent_parser", "policy_router")
        builder.add_edge("policy_router", END)
        _PLAN_GRAPH = builder.compile()
    return _PLAN_GRAPH


def _compiled_retrieval_graph():
    global _RETRIEVAL_GRAPH
    if not langgraph_available():
        return None
    if _RETRIEVAL_GRAPH is None:
        builder = StateGraph(AgenticRetrievalState)
        builder.add_node("parse_filters", _parse_filters_node)
        builder.add_node("search_products", _search_products_node)
        builder.add_edge(START, "parse_filters")
        builder.add_edge("parse_filters", "search_products")
        builder.add_edge("search_products", END)
        _RETRIEVAL_GRAPH = builder.compile()
    return _RETRIEVAL_GRAPH


async def plan_agentic_turn(
    message: str,
    chat_history: list[dict[str, str]],
    conversation_state: dict[str, Any],
) -> AgenticTurnPlan:
    graph = _compiled_plan_graph()
    if graph is not None:
        state = await graph.ainvoke(
            {
                "message": message,
                "chat_history": chat_history,
                "conversation_state": conversation_state,
            }
        )
        return AgenticTurnPlan(
            parsed_turn=state["parsed_turn"],
            policy=state["policy"],
            graph_backend="langgraph",
        )

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
    graph = _compiled_retrieval_graph()
    if graph is not None:
        state = graph.invoke(
            {
                "conn": conn,
                "query": query,
                "known_brands": known_brands,
                "plan": plan,
                "top_k": top_k,
            }
        )
        return AgenticRetrievalResult(
            query=query,
            parsed_filters=state["parsed_filters"],
            search_result=state["search_result"],
            graph_backend="langgraph",
        )

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
