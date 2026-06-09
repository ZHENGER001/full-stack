from __future__ import annotations

import re


INTENT_WORDS = [
    "我想买",
    "我要买",
    "想买",
    "买",
    "帮我找",
    "帮我搜",
    "给我找",
    "推荐一下",
    "推荐",
    "搜一下",
    "搜索",
    "找",
    "有没有",
    "有没",
    "来点",
    "来个",
    "想吃点",
    "想吃",
    "今天饿了",
]

TRAILING_FILLERS = ["商品", "东西", "一下", "的"]


def compact_text(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip())


def strip_intent_wrappers(text: str) -> str:
    cleaned = compact_text(text)
    cleaned = cleaned.strip("，。！？,.!?;；：:")
    changed = True
    while changed:
        changed = False
        cleaned = cleaned.strip("，。！？,.!?;；：:")
        for word in INTENT_WORDS:
            if cleaned.startswith(word) and len(cleaned) > len(word):
                cleaned = cleaned[len(word) :]
                cleaned = cleaned.strip("，。！？,.!?;；：:")
                changed = True
                break
    for filler in TRAILING_FILLERS:
        if cleaned.endswith(filler) and len(cleaned) > len(filler):
            cleaned = cleaned[: -len(filler)]
    return cleaned.strip("，。！？,.!?;；：:")


def is_wrapped_query(raw: str, term: str) -> bool:
    raw_compact = compact_text(raw)
    term_compact = compact_text(term)
    if not raw_compact or not term_compact or raw_compact == term_compact:
        return False
    return term_compact == strip_intent_wrappers(raw_compact)


def safe_candidate_terms(raw: str, terms: list[str]) -> list[str]:
    result: list[str] = []
    raw_compact = compact_text(raw)
    for term in terms:
        compact = compact_text(str(term))
        if not compact:
            continue
        if compact == raw_compact:
            compact = strip_intent_wrappers(compact)
        if compact:
            result.append(compact)
    return list(dict.fromkeys(result))
