from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .schemas import ProductCard


"""
Hallucination controls for AI shopping guidance.

The main risks are hallucinated products, fabricated prices/SKUs/stock,
unsupported capability claims, budget violations, and graph relationships stated
as facts without evidence. This verifier keeps final product cards locked to the
local database and downgrades unsupported text to safer wording before the SSE
response is returned.
"""


FEATURE_CLAIMS = ["主动降噪", "降噪", "快充", "高刷", "护眼", "轻薄", "拍照", "防水", "防滑", "续航"]


@dataclass
class VerificationResult:
    passed: bool
    corrected_fields: list[str] = field(default_factory=list)
    removed_products: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    budget_violations: list[str] = field(default_factory=list)
    category_violations: list[str] = field(default_factory=list)
    hallucinated_products: list[str] = field(default_factory=list)
    fallback_used: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VerifiedGeneration:
    verified_text: str
    verified_products: list[ProductCard]
    verification_result: VerificationResult


class PostGenerationVerifier:
    def verify(
        self,
        user_query: str,
        llm_text: str,
        retrieved_contexts: list[dict[str, Any]],
        candidate_products: list[ProductCard],
        selected_products: list[ProductCard],
        graph_context: str,
        parsed_constraints: dict[str, Any],
    ) -> VerifiedGeneration:
        candidate_ids = {product.id for product in candidate_products}
        candidate_by_id = {product.id: product for product in candidate_products}
        result = VerificationResult(passed=True)
        verified_products: list[ProductCard] = []

        for product in selected_products:
            if product.id not in candidate_ids:
                result.removed_products.append(product.id)
                result.hallucinated_products.append(product.id)
                continue
            if not self._within_budget(product, parsed_constraints):
                result.removed_products.append(product.id)
                result.budget_violations.append(product.id)
                continue
            if not self._matches_category(product, parsed_constraints):
                result.removed_products.append(product.id)
                result.category_violations.append(product.id)
                continue
            verified_products.append(candidate_by_id[product.id])

        verified_text = llm_text.strip() or self._fallback_text(verified_products)
        verified_text = self._sanitize_prices(verified_text, verified_products, result)
        verified_text = self._sanitize_stock_and_sku(verified_text, result)
        verified_text = self._sanitize_feature_claims(
            verified_text,
            retrieved_contexts,
            graph_context,
            result,
        )

        if not verified_products:
            result.passed = False
            result.fallback_used = True
            result.reason = "No verified products remained after post-generation checks"
        elif result.corrected_fields or result.removed_products or result.unsupported_claims:
            result.passed = False
            result.reason = "Some generated content was corrected or removed"
        else:
            result.reason = "Generated answer passed product, budget, category, and claim checks"

        return VerifiedGeneration(
            verified_text=verified_text,
            verified_products=verified_products,
            verification_result=result,
        )

    @staticmethod
    def _within_budget(product: ProductCard, constraints: dict[str, Any]) -> bool:
        budget = constraints.get("budget_max")
        return budget is None or float(product.price) <= float(budget)

    @staticmethod
    def _matches_category(product: ProductCard, constraints: dict[str, Any]) -> bool:
        categories = constraints.get("categories") or []
        if not categories:
            return True
        text = f"{product.category or ''} {product.subcategory or ''} {product.title}".lower()
        return any(category.lower() in text for category in categories)

    @staticmethod
    def _sanitize_prices(text: str, products: list[ProductCard], result: VerificationResult) -> str:
        allowed_prices = {str(int(product.price)) for product in products if float(product.price).is_integer()}
        allowed_prices.update(f"{product.price:.1f}".rstrip("0").rstrip(".") for product in products)
        found_prices = set(re.findall(r"(?:¥|￥)?\s*(\d+(?:\.\d+)?)\s*元", text))
        unsupported = [price for price in found_prices if price not in allowed_prices]
        if unsupported:
            result.corrected_fields.append("price")
            return re.sub(r"(?:¥|￥)?\s*\d+(?:\.\d+)?\s*元", "以商品卡片价格为准", text)
        return text

    @staticmethod
    def _sanitize_stock_and_sku(text: str, result: VerificationResult) -> str:
        sanitized = text
        if re.search(r"库存\s*\d+", sanitized):
            result.corrected_fields.append("stock")
            sanitized = re.sub(r"库存\s*\d+", "库存以商品卡片为准", sanitized)
        if re.search(r"SKU\s*[:：]\s*[\w\-\u4e00-\u9fff/ ]+", sanitized, flags=re.IGNORECASE):
            result.corrected_fields.append("sku")
            sanitized = re.sub(r"SKU\s*[:：]\s*[\w\-\u4e00-\u9fff/ ]+", "SKU 以商品详情为准", sanitized, flags=re.IGNORECASE)
        return sanitized

    @staticmethod
    def _sanitize_feature_claims(
        text: str,
        contexts: list[dict[str, Any]],
        graph_context: str,
        result: VerificationResult,
    ) -> str:
        evidence = " ".join(str(item.get("raw_text") or item.get("text") or "") for item in contexts)
        evidence = f"{evidence} {graph_context}"
        sanitized = text
        for claim in FEATURE_CLAIMS:
            if claim in sanitized and claim not in evidence:
                result.unsupported_claims.append(claim)
                sanitized = sanitized.replace(claim, f"{claim}相关表现需以详情为准")
        if result.unsupported_claims:
            result.corrected_fields.append("unsupported_claims")
        return sanitized

    @staticmethod
    def _fallback_text(products: list[ProductCard]) -> str:
        if not products:
            return "当前信息不足以生成可靠推荐，我先保留本地规则检索结果供你参考。"
        titles = "、".join(product.title for product in products[:3])
        return f"我先基于本地商品库给你筛出这些候选：{titles}。价格、库存和 SKU 请以商品卡片与详情页为准。"
