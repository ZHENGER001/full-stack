from __future__ import annotations

import argparse
import json
import math
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
    relevance_grades: dict[str, int]
    relevant_ids: set[str]
    should_return_empty: bool
    status: str
    mrr: float
    average_precision: float
    ndcg: float
    empty_correct: bool | None
    bad_return: bool
    forbidden_hit: bool
    constraint_pass: bool
    constraint_violations: list[str]
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


def relevance_grades(case: dict[str, Any]) -> dict[str, int]:
    grades = {str(product_id): 3 for product_id in case.get("relevant_product_ids", [])}
    raw_grades = case.get("graded_relevance") or {}
    if isinstance(raw_grades, dict):
        for product_id, grade in raw_grades.items():
            parsed_grade = int(grade)
            if parsed_grade > 0:
                grades[str(product_id)] = min(parsed_grade, 3)
            else:
                grades.pop(str(product_id), None)
    return grades


def relevant_ids_from_grades(grades: dict[str, int]) -> set[str]:
    return {product_id for product_id, grade in grades.items() if grade > 0}


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


def average_precision_at_k(ids: list[str], relevant_ids: set[str], k: int) -> float:
    if not relevant_ids or k <= 0:
        return 0.0
    hit_count = 0
    precision_sum = 0.0
    for index, product_id in enumerate(ids[:k], start=1):
        if product_id not in relevant_ids:
            continue
        hit_count += 1
        precision_sum += hit_count / index
    return precision_sum / min(len(relevant_ids), k)


def dcg_at_k(ids: list[str], grades: dict[str, int], k: int) -> float:
    score = 0.0
    for index, product_id in enumerate(ids[:k], start=1):
        grade = int(grades.get(product_id, 0))
        if grade <= 0:
            continue
        score += ((2**grade) - 1) / math.log2(index + 1)
    return score


def ndcg_at_k(ids: list[str], grades: dict[str, int], k: int) -> float:
    if not grades or k <= 0:
        return 0.0
    ideal_grades = sorted((grade for grade in grades.values() if grade > 0), reverse=True)
    ideal_ids = [f"ideal_{index}" for index, _ in enumerate(ideal_grades)]
    ideal_map = {product_id: grade for product_id, grade in zip(ideal_ids, ideal_grades)}
    ideal_dcg = dcg_at_k(ideal_ids, ideal_map, k)
    if ideal_dcg <= 0:
        return 0.0
    return dcg_at_k(ids, grades, k) / ideal_dcg


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


def list_values(case: dict[str, Any], *names: str) -> set[str]:
    values: set[str] = set()
    for name in names:
        raw_value = case.get(name)
        if raw_value is None:
            continue
        if isinstance(raw_value, str):
            values.add(raw_value)
        else:
            values.update(str(item) for item in raw_value)
    return {value for value in values if value}


def constraint_values(case: dict[str, Any], name: str) -> set[str]:
    constraints = case.get("constraints")
    if not isinstance(constraints, dict):
        return set()
    raw_value = constraints.get(name)
    if raw_value is None:
        return set()
    if isinstance(raw_value, str):
        return {raw_value}
    return {str(item) for item in raw_value if str(item)}


def constraint_violations(case: dict[str, Any], products: list[Any], ids: list[str], top_k: int) -> list[str]:
    scoped_ids = ids[:top_k]
    violations: list[str] = []
    if case.get("should_return_empty") and scoped_ids:
        violations.append("expected_empty_but_returned_products")

    must_include_ids = list_values(case, "must_include", "must_include_product_ids")
    missing_ids = sorted(product_id for product_id in must_include_ids if product_id not in scoped_ids)
    if missing_ids:
        violations.append(f"missing_required_products:{','.join(missing_ids)}")

    must_not_include_ids = list_values(case, "must_not_include", "must_not_include_product_ids")
    blocked_ids = sorted(product_id for product_id in scoped_ids if product_id in must_not_include_ids)
    if blocked_ids:
        violations.append(f"blocked_products_returned:{','.join(blocked_ids)}")

    forbidden_categories = list_values(case, "forbidden_categories")
    returned_forbidden_categories = sorted(
        {
            str(product.category)
            for product in products
            if str(product.category or "") in forbidden_categories
        }
    )
    if returned_forbidden_categories:
        violations.append(f"forbidden_categories:{','.join(returned_forbidden_categories)}")

    allowed_categories = list_values(case, "allowed_category", "allowed_categories") | constraint_values(case, "categories")
    if allowed_categories:
        mismatched_ids = [
            str(product.id)
            for product in products
            if str(product.category or "") not in allowed_categories
        ]
        if mismatched_ids:
            violations.append(f"category_mismatch:{','.join(mismatched_ids)}")

    allowed_subcategories = (
        list_values(case, "allowed_subcategory", "allowed_subcategories")
        | constraint_values(case, "subcategories")
    )
    if allowed_subcategories:
        mismatched_ids = [
            str(product.id)
            for product in products
            if str(product.subcategory or "") not in allowed_subcategories
        ]
        if mismatched_ids:
            violations.append(f"subcategory_mismatch:{','.join(mismatched_ids)}")

    return violations


def evaluate_case(conn: Any, case: dict[str, Any], top_k: int) -> CaseResult:
    result = call_search_products_tool(
        conn,
        SearchProductsInput(
            query=str(case["query"]),
            top_k=top_k,
            constraints=case.get("constraints") or {},
            retrieval_policy=case.get("retrieval_policy") or {},
        ),
    )
    ids = product_ids(result.products)
    grades = relevance_grades(case)
    relevant_ids = relevant_ids_from_grades(grades)
    should_return_empty = bool(case.get("should_return_empty", False))
    forbidden_categories = {str(item) for item in case.get("forbidden_categories", [])}
    violations = constraint_violations(case, result.products, ids, top_k)

    empty_correct = None
    bad_return = False
    if should_return_empty:
        empty_correct = not ids
        bad_return = bool(ids)

    return CaseResult(
        case_id=str(case.get("id") or case["query"]),
        query=str(case["query"]),
        returned_ids=ids,
        relevance_grades=grades,
        relevant_ids=relevant_ids,
        should_return_empty=should_return_empty,
        status=result.status,
        mrr=mrr_at_k(ids, relevant_ids, top_k) if relevant_ids else 0.0,
        average_precision=average_precision_at_k(ids, relevant_ids, top_k),
        ndcg=ndcg_at_k(ids, grades, top_k),
        empty_correct=empty_correct,
        bad_return=bad_return,
        forbidden_hit=has_forbidden_category(result.products, forbidden_categories),
        constraint_pass=not violations,
        constraint_violations=violations,
        category_precision=field_precision(result.products, "category", case.get("expected_category")),
        subcategory_precision=field_precision(result.products, "subcategory", case.get("expected_subcategory")),
        lane_counts=lane_counts(result.diagnostics),
    )


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def summary_values(results: list[CaseResult], k: int) -> dict[str, float]:
    retrieval_results = [result for result in results if result.relevant_ids]
    empty_results = [result for result in results if result.should_return_empty]
    return {
        "hit": mean([hit_at_k(r.returned_ids, r.relevant_ids, k) for r in retrieval_results]),
        "recall": mean([recall_at_k(r.returned_ids, r.relevant_ids, k) for r in retrieval_results]),
        "precision": mean([precision_at_k(r.returned_ids, r.relevant_ids, k) for r in retrieval_results]),
        "ndcg": mean([ndcg_at_k(r.returned_ids, r.relevance_grades, k) for r in retrieval_results]),
        "map": mean([average_precision_at_k(r.returned_ids, r.relevant_ids, k) for r in retrieval_results]),
        "mrr": mean([mrr_at_k(r.returned_ids, r.relevant_ids, k) for r in retrieval_results]),
        "constraint_pass_rate": mean([1.0 if r.constraint_pass else 0.0 for r in results]),
        "empty_accuracy": mean([1.0 if r.empty_correct else 0.0 for r in empty_results]),
        "bad_return_rate": mean([1.0 if r.bad_return else 0.0 for r in empty_results]),
        "forbidden_category_rate": mean([1.0 if r.forbidden_hit else 0.0 for r in results]),
    }


def enforce_thresholds(results: list[CaseResult], args: argparse.Namespace) -> None:
    values = summary_values(results, args.threshold_k)
    failures: list[str] = []
    minimums = [
        ("hit", args.min_hit),
        ("ndcg", args.min_ndcg),
        ("constraint_pass_rate", args.min_constraint_pass_rate),
        ("empty_accuracy", args.min_empty_accuracy),
    ]
    maximums = [
        ("bad_return_rate", args.max_bad_return_rate),
        ("forbidden_category_rate", args.max_forbidden_category_rate),
    ]
    for name, threshold in minimums:
        if threshold is not None and values[name] < threshold:
            label = f"{name}@{args.threshold_k}" if name in {"hit", "ndcg"} else name
            failures.append(f"{label}={values[name]:.3f} < {threshold:.3f}")
    for name, threshold in maximums:
        if threshold is not None and values[name] > threshold:
            failures.append(f"{name}={values[name]:.3f} > {threshold:.3f}")
    if failures:
        raise SystemExit("Retrieval eval thresholds failed: " + "; ".join(failures))


def print_case_rows(results: list[CaseResult], top_k: int) -> None:
    print("\nPer-case results")
    print("-" * 120)
    header = (
        f"{'case':<24} {'query':<16} {'status':<9} {'hit':>4} {'mrr':>5} "
        f"{'ndcg':>6} {'ap':>5} {'cpass':>7} {'empty':>7} {'bad':>5} {'forbid':>7} {'returned'}"
    )
    print(header)
    print("-" * 120)
    for result in results:
        hit = hit_at_k(result.returned_ids, result.relevant_ids, top_k) if result.relevant_ids else 0.0
        empty = "" if result.empty_correct is None else str(result.empty_correct).lower()
        print(
            f"{result.case_id:<24} {result.query:<16} {result.status:<9} "
            f"{hit:>4.0f} {result.mrr:>5.2f} {result.ndcg:>6.2f} {result.average_precision:>5.2f} "
            f"{str(result.constraint_pass).lower():>7} {empty:>7} "
            f"{str(result.bad_return).lower():>5} {str(result.forbidden_hit).lower():>7} "
            f"{','.join(result.returned_ids)}"
        )
        if result.constraint_violations:
            print(f"{'':<24} violations: {', '.join(result.constraint_violations)}")


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
            f"precision@{k}={mean([precision_at_k(r.returned_ids, r.relevant_ids, k) for r in retrieval_results]):.3f} "
            f"ndcg@{k}={mean([ndcg_at_k(r.returned_ids, r.relevance_grades, k) for r in retrieval_results]):.3f} "
            f"map@{k}={mean([average_precision_at_k(r.returned_ids, r.relevant_ids, k) for r in retrieval_results]):.3f}"
        )
    max_k = max(k_values)
    print(f"mrr@{max_k}={mean([mrr_at_k(r.returned_ids, r.relevant_ids, max_k) for r in retrieval_results]):.3f}")
    print(f"constraint_pass_rate={mean([1.0 if r.constraint_pass else 0.0 for r in results]):.3f}")
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
    parser.add_argument("--threshold-k", type=positive_int, default=3)
    parser.add_argument("--min-hit", type=non_negative_float)
    parser.add_argument("--min-ndcg", type=non_negative_float)
    parser.add_argument("--min-constraint-pass-rate", type=non_negative_float)
    parser.add_argument("--min-empty-accuracy", type=non_negative_float)
    parser.add_argument("--max-bad-return-rate", type=non_negative_float)
    parser.add_argument("--max-forbidden-category-rate", type=non_negative_float)
    args = parser.parse_args()

    if args.top_k > 20:
        raise SystemExit("top-k must be <= 20 because SearchProductsInput caps tool results at 20")
    if max(args.k_values) > args.top_k:
        raise SystemExit("max k-values must be <= top-k")
    if args.threshold_k > args.top_k:
        raise SystemExit("threshold-k must be <= top-k")

    cases = load_cases(args.cases)
    with db_session() as conn:
        results = [evaluate_case(conn, case, top_k=args.top_k) for case in cases]

    print_case_rows(results, top_k=max(args.k_values))
    print_summary(results, args.k_values)
    enforce_thresholds(results, args)


if __name__ == "__main__":
    main()
