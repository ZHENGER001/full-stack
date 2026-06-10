from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import BASE_DIR
from .turn_schema import BundleSlotCandidate


BUNDLE_WORDS = ("搭配", "一套", "方案", "组合", "清单", "从", "到")


@dataclass(frozen=True)
class SceneSlotTemplate:
    key: str
    title: str
    query: str
    reason: str
    product_mentions: list[str] = field(default_factory=list)
    attributes_include: list[str] = field(default_factory=list)
    scene_terms: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SceneTemplate:
    scene: str
    triggers: list[str]
    slots: list[SceneSlotTemplate]
    required_any_groups: list[list[str]] = field(default_factory=list)
    requires_bundle_word: bool = True

    def matches(self, text: str) -> bool:
        if not any(term in text for term in self.triggers):
            return False
        return all(any(term in text for term in group) for group in self.required_any_groups)

    def can_route_as_bundle(self, text: str) -> bool:
        if not self.matches(text):
            return False
        return not self.requires_bundle_word or any(term in text for term in BUNDLE_WORDS)


def find_scene_template(text: str) -> SceneTemplate | None:
    clean_text = (text or "").strip()
    for template in load_scene_templates():
        if template.matches(clean_text):
            return template
    return None


def is_scene_bundle_request(text: str) -> bool:
    template = find_scene_template(text)
    return bool(template and template.can_route_as_bundle(text))


def scene_name_for_message(text: str, default: str = "组合搭配") -> str:
    template = find_scene_template(text)
    return template.scene if template else default


def bundle_slot_candidates_for_message(text: str) -> list[BundleSlotCandidate]:
    template = find_scene_template(text)
    if not template:
        return []
    return [
        BundleSlotCandidate(
            key=slot.key,
            title=slot.title,
            query=slot.query,
            reason=slot.reason,
            product_mentions=list(slot.product_mentions),
            attributes_include=list(slot.attributes_include),
            scene_terms=list(slot.scene_terms),
        )
        for slot in template.slots
    ]


@lru_cache(maxsize=1)
def load_scene_templates() -> tuple[SceneTemplate, ...]:
    path = _scene_slots_path()
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    if not isinstance(rows, list):
        return ()
    return tuple(_parse_scene_template(row) for row in rows if isinstance(row, dict))


def _scene_slots_path() -> Path:
    path = BASE_DIR / "data" / "scene_slots.json"
    if path.exists():
        return path
    return Path(__file__).resolve().parents[1] / "data" / "scene_slots.json"


def _parse_scene_template(row: dict[str, Any]) -> SceneTemplate:
    return SceneTemplate(
        scene=str(row.get("scene") or "").strip() or "组合搭配",
        triggers=_string_list(row.get("triggers")),
        required_any_groups=[_string_list(group) for group in row.get("required_any_groups") or [] if _string_list(group)],
        requires_bundle_word=bool(row.get("requires_bundle_word", True)),
        slots=tuple(_parse_slot(slot) for slot in row.get("slots") or [] if isinstance(slot, dict)),
    )


def _parse_slot(row: dict[str, Any]) -> SceneSlotTemplate:
    return SceneSlotTemplate(
        key=str(row.get("key") or "").strip(),
        title=str(row.get("title") or "").strip(),
        query=str(row.get("query") or "").strip(),
        reason=str(row.get("reason") or "").strip(),
        product_mentions=_string_list(row.get("product_mentions")),
        attributes_include=_string_list(row.get("attributes_include")),
        scene_terms=_string_list(row.get("scene_terms")),
    )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
