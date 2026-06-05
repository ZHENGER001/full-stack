from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .query_parser import parse_user_filters


@dataclass(frozen=True)
class ParsedQuery:
    raw_query: str
    rewritten_query: str
    filters: dict[str, Any]
    route_notes: list[str]


def parse_query(query: str, known_brands: list[str] | None = None) -> ParsedQuery:
    raw_query = (query or "").strip()
    filters = parse_user_filters(raw_query, known_brands or [])
    expansion_terms = [raw_query]
    route_notes: list[str] = []

    if filters.get("target_categories"):
        expansion_terms.extend(str(item) for item in filters["target_categories"])
        route_notes.append("category")
    if filters.get("target_subcategories"):
        expansion_terms.extend(str(item) for item in filters["target_subcategories"])
        route_notes.append("subcategory")
    if filters.get("scene_terms"):
        expansion_terms.extend(str(item) for item in filters["scene_terms"])
        route_notes.append("scene")
    if filters.get("colors"):
        expansion_terms.extend(str(item) for item in filters["colors"])
        route_notes.append("color")
    if filters.get("brands"):
        expansion_terms.extend(str(item) for item in filters["brands"])
        route_notes.append("brand")
    if filters.get("price_sensitive"):
        route_notes.append("price_sensitive")
    if filters.get("retrieval_scope") == "full_evidence":
        route_notes.append("evidence")
    if filters.get("match_mode") == "exact_or_none":
        route_notes.append("exact_or_none")

    rewritten_query = " ".join(dict.fromkeys(term.strip() for term in expansion_terms if term and term.strip()))
    return ParsedQuery(
        raw_query=raw_query,
        rewritten_query=rewritten_query or raw_query,
        filters=filters,
        route_notes=route_notes,
    )
