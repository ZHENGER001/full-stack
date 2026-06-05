from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agent_tools import SearchProductsInput, call_search_products_tool  # noqa: E402
from app.database import db_session  # noqa: E402


DEFAULT_CASES_PATH = BACKEND_DIR / "evals" / "retrieval_cases.json"


@dataclass
class CaseResult:
    case_id: str
    query: str
    returned_ids: list[str]
    relevant_ids: set[str]
    should_return_empty: bool
    status: str
    mrr: float
    empty_correct: bool | None
    bad_return: bool
    forbidden_hit: bool
    category_precision: float | None
    subcategory_precision: float | None
    lane_counts: dict[str, int]


def load_cases(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def parse_k_values(raw: str) -> list[int]:
    values = sorted({positive_int(item.strip()) for item in raw.split(",") if item.strip()})
    if not values:
        raise argparse.ArgumentTypeError("at least one K value is required")
    return values


def product_ids(products: list[Any]) -> list[str]:
    return [str(product.id) for product in products]


def lane_counts(diagnostics: dict[str, Any]) -> dict[str, int]:
    lanes = diagnostics.get("lanes") if isinstance(diagnostics, dict) else {}
    lanes = lanes if isinstance(lanes, dict) else {}
    return {
        name: int((lane if isinstance(lane, dict) else {}).get("count") or 0)
        for name, lane in lanes.items()
    }


def mrr_at_k(ids: list[str], relevant_ids: set[str], k: int) -> float:
    for index, product_id in enumerate(ids[:k], start=1):
        if product_id in relevant_ids:
            return 1.0 / index
    return 0.0


def precision_at_k(ids: list[str], relevant_ids: set[str], k: int) -> float:
    if k <= 0:
        return 0.0
    return sum(1 for product_id in ids[:k] if product_id in relevant_ids) / k


def recall_at_k(ids: list[str], relevant_ids: set[str], k: int) -> float:
    if not relevant_ids:
        return 0.0
    return sum(1 for product_id in ids[:k] if product_id in relevant_ids) / len(relevant_ids)


def hit_at_k(ids: list[str], relevant_ids: set[str], k: int) -> float:
    return 1.0 if any(product_id in relevant_ids for product_id in ids[:k]) else 0.0


def field_precision(products: list[Any], field: str, expected: str | None) -> float | None:
    if not expected:
        return None
    if not products:
        return 0.0
    matches = sum(1 for product in products if getattr(product, field) == expected)
    return matches / len(products)


def has_forbidden_category(products: list[Any], forbidden_categories: set[str]) -> bool:
    if not forbidden_categories:
        return False
    return any((product.category or "") in forbidden_categories for product in products)


def evaluate_case(conn: Any, case: dict[str, Any], top_k: int) -> CaseResult:
    result = call_search_products_tool(
        conn,
        SearchProductsInput(query=str(case["query"]), top_k=top_k),
    )
    ids = product_ids(result.products)
    relevant_ids = {str(item) for item in case.get("relevant_product_ids", [])}
    should_return_empty = bool(case.get("should_return_empty", False))
    forbidden_categories = {str(item) for item in case.get("forbidden_categories", [])}

    empty_correct = None
    bad_return = False
    if should_return_empty:
        empty_correct = not ids
        bad_return = bool(ids)

    return CaseResult(
        case_id=str(case.get("id") or case["query"]),
        query=str(case["query"]),
        returned_ids=ids,
        relevant_ids=relevant_ids,
        should_return_empty=should_return_empty,
        status=result.status,
        mrr=mrr_at_k(ids, relevant_ids, top_k) if relevant_ids else 0.0,
        empty_correct=empty_correct,
        bad_return=bad_return,
        forbidden_hit=has_forbidden_category(result.products, forbidden_categories),
        category_precision=field_precision(result.products, "category", case.get("expected_category")),
        subcategory_precision=field_precision(result.products, "subcategory", case.get("expected_subcategory")),
        lane_counts=lane_counts(result.diagnostics),
    )


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def print_case_rows(results: list[CaseResult], top_k: int) -> None:
    print("\nPer-case results")
    print("-" * 120)
    header = f"{'case':<20} {'query':<12} {'status':<9} {'hit':>4} {'mrr':>5} {'empty':>7} {'bad':>5} {'forbid':>7} {'returned'}"
    print(header)
    print("-" * 120)
    for result in results:
        hit = hit_at_k(result.returned_ids, result.relevant_ids, top_k) if result.relevant_ids else 0.0
        empty = "" if result.empty_correct is None else str(result.empty_correct).lower()
        print(
            f"{result.case_id:<20} {result.query:<12} {result.status:<9} "
            f"{hit:>4.0f} {result.mrr:>5.2f} {empty:>7} "
            f"{str(result.bad_return).lower():>5} {str(result.forbidden_hit).lower():>7} "
            f"{','.join(result.returned_ids)}"
        )


def print_summary(results: list[CaseResult], k_values: list[int]) -> None:
    retrieval_results = [result for result in results if result.relevant_ids]
    empty_results = [result for result in results if result.should_return_empty]

    print("\nSummary")
    print("-" * 120)
    print(f"cases={len(results)} retrieval_cases={len(retrieval_results)} empty_cases={len(empty_results)}")
    for k in k_values:
        print(
            f"hit@{k}={mean([hit_at_k(r.returned_ids, r.relevant_ids, k) for r in retrieval_results]):.3f} "
            f"recall@{k}={mean([recall_at_k(r.returned_ids, r.relevant_ids, k) for r in retrieval_results]):.3f} "
            f"precision@{k}={mean([precision_at_k(r.returned_ids, r.relevant_ids, k) for r in retrieval_results]):.3f}"
        )
    max_k = max(k_values)
    print(f"mrr@{max_k}={mean([mrr_at_k(r.returned_ids, r.relevant_ids, max_k) for r in retrieval_results]):.3f}")
    print(f"empty_accuracy={mean([1.0 if r.empty_correct else 0.0 for r in empty_results]):.3f}")
    print(f"bad_return_rate={mean([1.0 if r.bad_return else 0.0 for r in empty_results]):.3f}")
    print(f"forbidden_category_rate={mean([1.0 if r.forbidden_hit else 0.0 for r in results]):.3f}")

    category_values = [r.category_precision for r in results if r.category_precision is not None]
    subcategory_values = [r.subcategory_precision for r in results if r.subcategory_precision is not None]
    if category_values:
        print(f"category_precision={mean(category_values):.3f}")
    if subcategory_values:
        print(f"subcategory_precision={mean(subcategory_values):.3f}")

    lane_names = sorted({name for result in results for name in result.lane_counts})
    if lane_names:
        lane_summary = " ".join(
            f"{name}_count_avg={mean([float(r.lane_counts.get(name, 0)) for r in results]):.1f}"
            for name in lane_names
        )
        print(lane_summary)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate SmartShopAI product retrieval.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--top-k", type=positive_int, default=10)
    parser.add_argument("--k-values", type=parse_k_values, default=parse_k_values("1,3,5,10"))
    args = parser.parse_args()

    if args.top_k > 20:
        raise SystemExit("top-k must be <= 20 because SearchProductsInput caps tool results at 20")
    if max(args.k_values) > args.top_k:
        raise SystemExit("max k-values must be <= top-k")

    cases = load_cases(args.cases)
    with db_session() as conn:
        results = [evaluate_case(conn, case, top_k=args.top_k) for case in cases]

    print_case_rows(results, top_k=max(args.k_values))
    print_summary(results, args.k_values)


if __name__ == "__main__":
    main()
