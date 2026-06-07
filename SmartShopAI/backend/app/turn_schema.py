from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


IntentType = Literal[
    "product_search",
    "filter_refinement",
    "product_compare",
    "product_detail_qa",
    "cart_add",
    "cart_remove",
    "cart_update_quantity",
    "cart_list",
    "cart_clear",
    "bundle_recommendation",
    "greeting",
    "capability_question",
    "unknown",
]

RouteHint = Literal["direct_tool", "no_tool", "bounded_react", "plan_execute"]
MatchMode = Literal["normal", "exact_or_none"]


class PriceConstraint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    min: float | None = None
    max: float | None = None


class ProductReference(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reference_type: Literal["position", "current_product", "last_product", "product_id"] = "position"
    position: int | None = Field(default=None, ge=1)
    product_id: str | None = None
    raw_text: str | None = None


class TurnConstraints(BaseModel):
    model_config = ConfigDict(extra="ignore")

    categories: list[str] = Field(default_factory=list)
    subcategories: list[str] = Field(default_factory=list)
    brands_include: list[str] = Field(default_factory=list)
    brands_exclude: list[str] = Field(default_factory=list)
    required_terms: list[str] = Field(default_factory=list)
    attributes_include: list[str] = Field(default_factory=list)
    attributes_exclude: list[str] = Field(default_factory=list)
    scene_terms: list[str] = Field(default_factory=list)
    price: PriceConstraint = Field(default_factory=PriceConstraint)
    negative_terms: list[str] = Field(default_factory=list)


class RetrievalPolicyHint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    match_mode: MatchMode = "normal"
    allow_popular_fallback: bool = True
    allow_dense_only: bool = True
    require_lexical_anchor: bool = False


class ParsedTurn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    raw_message: str = ""
    normalized_query: str | None = None
    intent_type: IntentType = "unknown"
    route_hint: RouteHint = "direct_tool"
    needs_clarification: bool = False
    clarification_question: str | None = None
    constraints: TurnConstraints = Field(default_factory=TurnConstraints)
    retrieval_policy_hint: RetrievalPolicyHint = Field(default_factory=RetrievalPolicyHint)
    references: list[ProductReference] = Field(default_factory=list)
    compare_dimensions: list[str] = Field(default_factory=list)
    quantity: int | None = Field(default=None, ge=1)
    is_unknown_short_query: bool = False
    source: Literal["rule", "llm", "hybrid"] = "hybrid"
    confidence: float | None = Field(default=None, ge=0, le=1)
