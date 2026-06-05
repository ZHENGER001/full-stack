from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class VerificationResult:
    products: list[dict[str, Any]]
    diagnostics: dict[str, Any]


def verify_products(
    products: list[dict[str, Any]],
    filters: dict[str, Any],
    limit: int,
) -> VerificationResult:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for product in products:
        reason = _rejection_reason(product, filters)
        if reason:
            rejected.append({"product_id": product.get("id"), "reason": reason})
            continue
        accepted.append(product)
        if len(accepted) >= limit:
            break

    diagnostics = {
        "pipeline_step": "verifier",
        "input_count": len(products),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "rejected": rejected[:10],
        "final_product_ids": [product["id"] for product in accepted],
    }
    return VerificationResult(products=accepted, diagnostics=diagnostics)


def _rejection_reason(product: dict[str, Any], filters: dict[str, Any]) -> str | None:
    if not product.get("id"):
        return "missing_product_id"

    max_price = filters.get("max_price")
    if max_price is not None and float(product.get("price") or 0) > float(max_price):
        return "above_max_price"

    if float(product.get("stock") or 0) <= 0:
        return "out_of_stock"

    required_terms = [str(term).lower() for term in filters.get("required_terms") or [] if str(term).strip()]
    if filters.get("match_mode") == "exact_or_none" and required_terms:
        catalog_text = _catalog_text(product)
        if not any(term in catalog_text for term in required_terms):
            return "required_term_mismatch"

    target_categories = set(filters.get("target_categories") or [])
    target_subcategories = set(filters.get("target_subcategories") or [])
    if filters.get("explicit_category") and (target_categories or target_subcategories):
        required_text_match = any(term in _catalog_text(product) for term in required_terms)
        if target_subcategories:
            subcategory_match = product.get("subcategory") in target_subcategories
            if not subcategory_match and not required_text_match:
                return "subcategory_mismatch"
        elif target_categories and product.get("category") not in target_categories and not required_text_match:
            return "category_mismatch"

    brands = set(filters.get("brands") or [])
    if brands and product.get("brand") not in brands:
        return "brand_mismatch"

    return None


def _catalog_text(product: dict[str, Any]) -> str:
    return " ".join(
        str(part or "")
        for part in [
            product.get("title"),
            product.get("brand"),
            product.get("category"),
            product.get("subcategory"),
            product.get("sku_text"),
            product.get("sku_summary"),
        ]
    ).lower()
