from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from time import time

from .config import BASE_DIR, get_settings
from .parser_safety import compact_text, safe_candidate_terms, strip_intent_wrappers


TYPE_ALIASES = [
    "手机",
    "耳机",
    "笔记本",
    "电脑",
    "平板",
    "手表",
    "腕表",
    "鞋",
    "裤",
    "包",
    "背包",
    "帽",
    "泳衣",
    "泳裤",
    "泳镜",
    "泳帽",
    "防水包",
    "速干毛巾",
    "卫衣",
    "T恤",
    "零食",
    "饮料",
    "咖啡",
    "牛奶",
    "酸奶",
    "酱油",
    "生抽",
    "老抽",
    "调味品",
    "调味料",
    "面膜",
    "面霜",
    "精华",
    "防晒",
    "唇釉",
    "粉底液",
    "眉笔",
    "蜜粉",
    "卸妆",
    "洁面",
    "化妆水",
    "胶带",
    "墨盒",
    "计划本",
    "挂钟",
]

ALIAS_CATEGORY_HINTS = {
    "零食": {"食品饮料"},
    "饮料": {"食品饮料"},
    "咖啡": {"食品饮料"},
    "牛奶": {"食品饮料"},
    "酸奶": {"食品饮料"},
    "酱油": {"食品饮料"},
    "生抽": {"食品饮料"},
    "老抽": {"食品饮料"},
    "调味品": {"食品饮料"},
    "调味料": {"食品饮料"},
}

DOMAIN_SUBCATEGORY_ALIASES = {
    "墨盒": "打印耗材",
    "墨水": "打印耗材",
    "打印机墨水": "打印耗材",
    "打印机耗材": "打印耗材",
    "打印机没墨水": "打印耗材",
}

SHORT_QUERY_MAX_CHARS = 8


@dataclass(frozen=True)
class CatalogMatch:
    term: str
    categories: list[str] = field(default_factory=list)
    subcategories: list[str] = field(default_factory=list)
    required_terms: list[str] = field(default_factory=list)
    source: str = "catalog"


@dataclass(frozen=True)
class CatalogGroundingResult:
    core_query: str
    matches: list[CatalogMatch] = field(default_factory=list)
    ambiguous_terms: list[str] = field(default_factory=list)
    unknown_terms: list[str] = field(default_factory=list)

    @property
    def has_match(self) -> bool:
        return bool(self.matches)


@dataclass(frozen=True)
class CatalogLexicon:
    matches: list[CatalogMatch]
    labels: list[tuple[str, str, str]]
    built_at: float = field(default_factory=time)


def ground_catalog_terms(raw: str, candidate_terms: list[str] | None = None) -> CatalogGroundingResult:
    raw_compact = compact_text(raw)
    core_query = strip_intent_wrappers(raw_compact)
    candidates = safe_candidate_terms(raw_compact, [core_query, *(candidate_terms or [])])
    lexicon = _load_catalog_lexicon()

    search_texts = [raw_compact, core_query, *candidates]
    matches: list[CatalogMatch] = []
    for entry in sorted(lexicon.matches, key=lambda item: len(item.term), reverse=True):
        if any(entry.term and entry.term in text for text in search_texts if text):
            matches.append(entry)

    matches = _dedupe_matches(matches)
    if matches:
        return CatalogGroundingResult(core_query=core_query, matches=matches)

    if _is_short_query(core_query):
        ambiguous = _ambiguous_short_terms(core_query, lexicon)
        if ambiguous:
            return CatalogGroundingResult(core_query=core_query, ambiguous_terms=[core_query])
        return CatalogGroundingResult(core_query=core_query, unknown_terms=[core_query])

    return CatalogGroundingResult(core_query=core_query)


def default_catalog_summary() -> dict[str, list[str]]:
    lexicon = _load_catalog_lexicon()
    return {
        "terms": sorted({match.term for match in lexicon.matches if match.term}),
        "labels": sorted({label for label, _, _ in lexicon.labels if label}),
    }


def catalog_summary_cache_stats() -> dict[str, float | int | bool]:
    info = _load_catalog_lexicon.cache_info()
    lexicon = _load_catalog_lexicon()
    return {
        "hits": info.hits,
        "misses": info.misses,
        "currsize": info.currsize,
        "matches": len(lexicon.matches),
        "labels": len(lexicon.labels),
        "built_at": lexicon.built_at,
    }


def clear_catalog_summary_cache() -> None:
    _load_catalog_lexicon.cache_clear()


@lru_cache(maxsize=1)
def _load_catalog_lexicon() -> CatalogLexicon:
    products = _load_products_from_sqlite() or _load_products_from_clean_json()
    categories: dict[str, set[str]] = {}
    subcategories: dict[str, set[str]] = {}
    labels: list[tuple[str, str, str]] = []

    for product in products:
        category = str(product.get("category") or "").strip()
        subcategory = str(product.get("subcategory") or product.get("sub_category") or "").strip()
        title = str(product.get("title") or "").strip()
        if not category or not subcategory:
            continue
        categories.setdefault(category, set()).add(subcategory)
        subcategories.setdefault(subcategory, set()).add(category)
        labels.append((category, category, subcategory))
        labels.append((subcategory, category, subcategory))
        if title:
            labels.append((title, category, subcategory))

    matches: list[CatalogMatch] = []
    for category, subcats in categories.items():
        matches.append(
            CatalogMatch(
                term=category,
                categories=[category],
                subcategories=sorted(subcats),
                required_terms=[],
                source="category",
            )
        )
    for subcategory, cats in subcategories.items():
        matches.append(
            CatalogMatch(
                term=subcategory,
                categories=sorted(cats),
                subcategories=[subcategory],
                required_terms=[subcategory],
                source="subcategory",
            )
        )

    for alias, subcategory in DOMAIN_SUBCATEGORY_ALIASES.items():
        cats = sorted(subcategories.get(subcategory) or [])
        if not cats:
            continue
        matches.append(
            CatalogMatch(
                term=alias,
                categories=cats,
                subcategories=[subcategory],
                required_terms=[subcategory],
                source="domain_alias",
            )
        )

    for alias in TYPE_ALIASES:
        alias_rows = [
            (label, category, subcategory)
            for label, category, subcategory in labels
            if alias in subcategory or alias in category
        ]
        category_hints = ALIAS_CATEGORY_HINTS.get(alias)
        if category_hints:
            alias_rows = [row for row in alias_rows if row[1] in category_hints]
        if not alias_rows:
            continue
        cats = sorted({category for _, category, _ in alias_rows})
        subcats = sorted({subcategory for _, _, subcategory in alias_rows})
        matches.append(
            CatalogMatch(
                term=alias,
                categories=cats,
                subcategories=subcats,
                required_terms=[alias],
                source="alias",
            )
        )

    return CatalogLexicon(matches=_dedupe_matches(matches), labels=list(dict.fromkeys(labels)))


def _load_products_from_sqlite() -> list[dict[str, str]]:
    db_path = get_settings().database_path
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT title, category, subcategory FROM products").fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except sqlite3.Error:
        return []


def _load_products_from_clean_json() -> list[dict[str, str]]:
    path = BASE_DIR / "data" / "products_clean.json"
    if not path.exists():
        path = Path(__file__).resolve().parents[1] / "data" / "products_clean.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in data if isinstance(item, dict)]


def _ambiguous_short_terms(term: str, lexicon: CatalogLexicon) -> bool:
    hits = {
        (category, subcategory)
        for label, category, subcategory in lexicon.labels
        if term in label and term != label
    }
    return len(hits) > 1


def _is_short_query(text: str) -> bool:
    return bool(text) and len(text) <= SHORT_QUERY_MAX_CHARS


def _dedupe_matches(matches: list[CatalogMatch]) -> list[CatalogMatch]:
    deduped: dict[str, CatalogMatch] = {}
    for match in matches:
        if not match.term:
            continue
        existing = deduped.get(match.term)
        if existing is None:
            deduped[match.term] = match
            continue
        deduped[match.term] = CatalogMatch(
            term=match.term,
            categories=_merge_unique(existing.categories, match.categories),
            subcategories=_merge_unique(existing.subcategories, match.subcategories),
            required_terms=_merge_unique(existing.required_terms, match.required_terms),
            source=existing.source,
        )
    return list(deduped.values())


def _merge_unique(first: list[str], second: list[str]) -> list[str]:
    return list(dict.fromkeys([*first, *second]))
