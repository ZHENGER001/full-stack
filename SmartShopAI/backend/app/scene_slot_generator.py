from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError

from .config import BASE_DIR
from .llm_client import LLMGenerationError, _env_value, _extract_content, _timeout_seconds, llm_model_name
from .turn_schema import BundleSlotCandidate


MAX_GENERATED_SLOTS = 6


class GeneratedSceneSlots(BaseModel):
    scene: str = Field(default="组合搭配")
    triggers: list[str] = Field(default_factory=list)
    slots: list[BundleSlotCandidate] = Field(default_factory=list)


SCENE_SLOT_SYSTEM_PROMPT = """
你是电商导购系统的场景拆解器。
你的任务是把用户的组合型购物需求拆成 2-6 个可检索的商品槽位。
只能输出 JSON object，不能输出 markdown、解释、商品推荐、价格、库存或商品 ID。

输出 schema:
{
  "scene": "简短场景名",
  "triggers": ["用于识别该场景的关键词"],
  "slots": [
    {
      "key": "英文或拼音短 key",
      "title": "槽位名",
      "query": "用于商品检索的短查询",
      "reason": "为什么需要这个槽位",
      "product_mentions": ["必须命中的商品词"],
      "attributes_include": ["可选属性词"],
      "scene_terms": ["场景词"]
    }
  ]
}

规则:
1. product_mentions 必须是商品类型词，不要写品牌、价格、营销词。
2. query 必须短，适合搜索，不要写长句。
3. 不确定的槽位不要编太多，优先输出核心必需品。
4. 如果商品库未命中，后续系统会过滤，你不用兜底推荐无关商品。
"""


async def generate_scene_slots_with_llm(
    message: str,
    catalog_summary: dict[str, Any] | None = None,
) -> list[BundleSlotCandidate]:
    api_key = _env_value("POE_API_KEY")
    if not api_key:
        raise LLMGenerationError("POE_API_KEY is not configured")

    base_url = (_env_value("POE_BASE_URL", "https://api.poe.com/v1") or "https://api.poe.com/v1").rstrip("/")
    model = llm_model_name()
    payload = {
        "message": message,
        "catalog_summary": _compact_catalog_summary(catalog_summary or {}),
    }
    user_prompt = f"请拆解这个组合购物需求，只输出 JSON object：\n{json.dumps(payload, ensure_ascii=False)}"

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(_timeout_seconds(), connect=8.0)) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": SCENE_SLOT_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 900,
                },
            )
            response.raise_for_status()
            data = GeneratedSceneSlots.model_validate(json.loads(_extract_json_object(_extract_content(response.json()))))
            slots = _sanitize_slots(data.slots)
            if slots:
                _maybe_store_generated_scene(message, data, slots)
            return slots
    except (json.JSONDecodeError, ValidationError) as exc:
        raise LLMGenerationError("scene slot generator returned invalid JSON") from exc
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        raise LLMGenerationError(f"scene slot generator HTTP status {status_code}") from exc
    except httpx.TimeoutException as exc:
        raise LLMGenerationError("scene slot generator timed out") from exc
    except httpx.HTTPError as exc:
        raise LLMGenerationError("scene slot generator network error") from exc


def _compact_catalog_summary(catalog_summary: dict[str, Any]) -> dict[str, Any]:
    terms = catalog_summary.get("terms") if isinstance(catalog_summary, dict) else []
    labels = catalog_summary.get("labels") if isinstance(catalog_summary, dict) else []
    return {
        "terms": list(terms or [])[:120],
        "labels": list(labels or [])[:120],
    }


def _sanitize_slots(slots: list[BundleSlotCandidate]) -> list[BundleSlotCandidate]:
    clean: list[BundleSlotCandidate] = []
    seen_keys: set[str] = set()
    for index, slot in enumerate(slots[:MAX_GENERATED_SLOTS], start=1):
        title = (slot.title or "").strip()
        query = (slot.query or "").strip()
        mentions = _string_list(slot.product_mentions)
        if not title or not query or not mentions:
            continue
        key = (slot.key or f"slot_{index}").strip()[:40]
        if key in seen_keys:
            key = f"{key}_{index}"
        seen_keys.add(key)
        clean.append(
            BundleSlotCandidate(
                key=key,
                title=title[:30],
                query=query[:80],
                reason=(slot.reason or title)[:120],
                product_mentions=mentions[:4],
                attributes_include=_string_list(slot.attributes_include)[:6],
                scene_terms=_string_list(slot.scene_terms)[:6],
            )
        )
    return clean


def _string_list(values: list[str] | None) -> list[str]:
    result: list[str] = []
    for value in values or []:
        text = str(value).strip()
        if text:
            result.append(text[:30])
    return list(dict.fromkeys(result))


def _maybe_store_generated_scene(message: str, generated: GeneratedSceneSlots, slots: list[BundleSlotCandidate]) -> None:
    enabled = (_env_value("AUTO_SCENE_SLOT_WRITE_CANDIDATES", "false") or "false").lower() in {"1", "true", "yes"}
    if not enabled:
        return
    row = {
        "source_message": message,
        "scene": generated.scene.strip() or "组合搭配",
        "triggers": _string_list(generated.triggers),
        "slots": [slot.model_dump(mode="json") for slot in slots],
    }
    path = BASE_DIR / "data" / "scene_slots.generated.json"
    existing: list[dict[str, Any]] = []
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                existing = [item for item in loaded if isinstance(item, dict)]
        except json.JSONDecodeError:
            existing = []
    key = json.dumps({"scene": row["scene"], "triggers": row["triggers"]}, ensure_ascii=False, sort_keys=True)
    seen = {
        json.dumps({"scene": item.get("scene"), "triggers": item.get("triggers")}, ensure_ascii=False, sort_keys=True)
        for item in existing
    }
    if key not in seen:
        existing.append(row)
        _atomic_write_json(path, existing)


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _extract_json_object(content: str) -> str:
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise json.JSONDecodeError("No JSON object found", text, 0)
    return text[start : end + 1]
