from __future__ import annotations

from dataclasses import dataclass

from .graph_client import get_graph_client
from .query_router import QueryRoute
from .rag import RetrievalResult, hybrid_retrieve


@dataclass
class GraphRAGResult:
    product_ids: list[str]
    graph_context: str
    fallback_used: bool
    reason: str | None = None


class GraphRAGRetrieval:
    def __init__(self) -> None:
        self.graph = get_graph_client()

    def retrieve(self, route: QueryRoute, top_k: int = 10) -> GraphRAGResult:
        result = self.graph.query_products(route.parsed_constraints.to_dict(), limit=top_k)
        return GraphRAGResult(
            product_ids=result.product_ids,
            graph_context=result.context,
            fallback_used=result.fallback_used,
            reason=result.reason,
        )


def graph_rag_retrieve(route: QueryRoute, top_k: int = 10) -> GraphRAGResult:
    return GraphRAGRetrieval().retrieve(route, top_k=top_k)


def graph_hybrid_retrieve(conn, query: str, route: QueryRoute, top_k: int = 10) -> tuple[GraphRAGResult, RetrievalResult]:
    graph_result = graph_rag_retrieve(route, top_k=top_k)
    hybrid_result = hybrid_retrieve(conn, query, top_k=top_k)
    if not graph_result.product_ids:
        graph_result.fallback_used = True
        graph_result.reason = graph_result.reason or "Neo4j did not return matching products"
    return graph_result, hybrid_result
