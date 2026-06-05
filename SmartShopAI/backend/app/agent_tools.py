from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from .rag import search_products_for_agent_with_diagnostics
from .schemas import ProductCard


class SearchProductsInput(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=3, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        query = value.strip()
        if not query:
            raise ValueError("query must not be blank")
        return query


class SearchProductsVerification(BaseModel):
    status: Literal["pass", "empty", "degraded"]
    accepted_count: int = 0
    rejected_count: int = 0
    final_product_ids: list[str] = Field(default_factory=list)


class SearchProductsResult(BaseModel):
    tool_name: Literal["search_products"] = "search_products"
    status: Literal["ok", "empty", "degraded"]
    products: list[ProductCard] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    verification: SearchProductsVerification


def call_search_products_tool(conn, request: SearchProductsInput) -> SearchProductsResult:
    products, diagnostics = search_products_for_agent_with_diagnostics(
        conn,
        request.query,
        limit=request.top_k,
    )
    verifier = diagnostics.get("verifier") if isinstance(diagnostics, dict) else {}
    verifier = verifier if isinstance(verifier, dict) else {}
    fallback = diagnostics.get("fallback") if isinstance(diagnostics, dict) else {}
    fallback = fallback if isinstance(fallback, dict) else {}
    product_ids = [product.id for product in products]

    verification = SearchProductsVerification(
        status="empty" if not products else "degraded" if fallback.get("used") else "pass",
        accepted_count=int(verifier.get("accepted_count") or len(products)),
        rejected_count=int(verifier.get("rejected_count") or 0),
        final_product_ids=list(verifier.get("final_product_ids") or product_ids),
    )
    if not products:
        status: Literal["ok", "empty", "degraded"] = "empty"
    elif fallback.get("used"):
        status = "degraded"
    else:
        status = "ok"
    return SearchProductsResult(
        status=status,
        products=products,
        diagnostics=diagnostics,
        verification=verification,
    )
