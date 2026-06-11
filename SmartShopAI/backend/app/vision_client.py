from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .config import BASE_DIR, _load_env_file


class VLMAnalysisError(RuntimeError):
    """Raised when the optional vision model path is unavailable."""


@dataclass(frozen=True)
class VLMObject:
    object_type: str
    category: str | None = None
    subcategory: str | None = None
    color: str | None = None
    style: str | None = None
    material: str | None = None
    scene: list[str] = field(default_factory=list)
    search_terms: list[str] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_type": self.object_type,
            "category": self.category,
            "subcategory": self.subcategory,
            "color": self.color,
            "style": self.style,
            "material": self.material,
            "scene": self.scene,
            "search_terms": self.search_terms,
            "confidence": round(float(self.confidence), 3),
        }


@dataclass(frozen=True)
class VLMAnalysis:
    objects: list[VLMObject]
    provider: str
    model: str
    fallback: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "objects": [item.to_dict() for item in self.objects],
            "provider": self.provider,
            "model": self.model,
            "fallback": self.fallback,
        }


def _env_value(name: str, default: str | None = None) -> str | None:
    env_file = _load_env_file(BASE_DIR / ".env")
    return os.getenv(name) or env_file.get(name) or default


def debug_vlm_event(event: str, payload: dict[str, Any]) -> None:
    data = {
        "ts": round(time.time(), 3),
        **payload,
    }
    data["event"] = event
    print(f"[{event}] {json.dumps(data, ensure_ascii=True, default=str)}", flush=True)
    try:
        path = BASE_DIR / "data" / "vlm_debug.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as out:
            out.write(json.dumps(data, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def vlm_model_name() -> str:
    return _env_value("VLM_MODEL") or _env_value("LLM_MODEL") or "gemini-3.5-flash"


def vlm_provider_name() -> str:
    return "poe" if (_env_value("VLM_API_KEY") or _env_value("POE_API_KEY")) else "fallback"


def _timeout_seconds() -> float:
    raw_value = _env_value("VLM_TIMEOUT_SECONDS", "30")
    try:
        return max(float(raw_value or "30"), 15.0)
    except ValueError:
        return 30.0


async def analyze_image_file_with_vlm(
    image_path: Path,
    user_hint: str | None = None,
    catalog_taxonomy: str | None = None,
) -> VLMAnalysis:
    api_key = _env_value("VLM_API_KEY") or _env_value("POE_API_KEY")
    if not api_key:
        raise VLMAnalysisError("VLM_API_KEY is not configured")

    base_url = (_env_value("VLM_BASE_URL") or _env_value("POE_BASE_URL", "https://api.poe.com/v1") or "").rstrip("/")
    if not base_url:
        raise VLMAnalysisError("VLM_BASE_URL is not configured")

    model = vlm_model_name()
    prompt = _build_prompt(user_hint, catalog_taxonomy)
    # VLM prompt 只产出结构化 objects；最终商品推荐仍由后续 RAG 检索和 verifier 决定。
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是 SmartShopAI 的电商拍照找货视觉理解模块。"
                    "只识别图中最主要、可购物的实物和可检索属性，不要识别人脸身份、隐私信息或臆测品牌型号。"
                    "必须只返回 JSON，不要输出解释文字。"
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": _image_data_url(image_path)}},
                ],
            },
        ],
        "temperature": 0.1,
        "max_tokens": 700,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(_timeout_seconds(), connect=8.0)) as client:
            response = await client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        raise VLMAnalysisError(f"VLM HTTP status {status_code}") from exc
    except httpx.TimeoutException as exc:
        raise VLMAnalysisError("VLM request timed out") from exc
    except httpx.HTTPError as exc:
        raise VLMAnalysisError("VLM network error") from exc

    content = _extract_content(response.json())
    debug_vlm_event(
        "VLM_RAW_RESPONSE",
        {"provider": "poe", "model": model, "content": content},
    )
    objects = parse_vlm_response_content(content)
    debug_vlm_event(
        "VLM_PARSED_OBJECTS",
        {"provider": "poe", "model": model, "objects": [item.to_dict() for item in objects]},
    )
    if not objects:
        raise VLMAnalysisError("VLM response has no objects")
    return VLMAnalysis(objects=objects, provider="poe", model=model)


def _build_prompt(user_hint: str | None, catalog_taxonomy: str | None) -> str:
    taxonomy_text = catalog_taxonomy or "无"
    hint_text = user_hint or "用户没有补充文字，只是随手拍图找相似商品。"
    # 商品库 taxonomy 会约束 category/subcategory，减少 VLM 自由发挥和品牌型号臆测。
    return (
        "请识别图片里 1 到 3 个最可能用于电商找货的主要物品，按可能性从高到低排序。"
        "object_type 必须是具体商品名词，例如 手机、跑步鞋、双肩包、洁面乳，不要写商品、物品、配件这类泛词。"
        "如果能匹配商品库类目，请使用商品库里的中文 category/subcategory；不能确定时对应字段填空字符串。"
        "search_terms 输出 2 到 5 个适合商品检索的短中文词，优先使用商品库里的子类目、同义商品名和明显用途；"
        "不要复制用户提示语，不要输出“可购物商品/检索关键词/类似款”等泛词，不要猜图片里看不清的品牌型号。"
        "confidence 取 0 到 1，低置信不要硬猜。\n"
        f"商品库类目候选：{taxonomy_text}\n"
        f"用户补充线索：{hint_text}\n"
        "返回 JSON 格式："
        '{"objects":[{"object_type":"物品名","category":"类目","subcategory":"子类目",'
        '"color":"颜色","style":"风格","material":"材质","scene":["场景"],'
        '"search_terms":["检索词"],"confidence":0.0}]}'
    )


def _image_data_url(image_path: Path) -> str:
    if not image_path.exists():
        raise VLMAnalysisError("image file does not exist")
    mime_type = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
    data = image_path.read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _extract_content(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise VLMAnalysisError("VLM response has no choices")
    message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts).strip()
    raise VLMAnalysisError("VLM response content is invalid")


def parse_vlm_response_content(content: str) -> list[VLMObject]:
    payload = _extract_json_object(content)
    raw_objects = payload.get("objects")
    if isinstance(raw_objects, dict):
        raw_objects = [raw_objects]
    if not isinstance(raw_objects, list):
        raw_objects = []
    objects = [_normalize_object(item) for item in raw_objects[:3] if isinstance(item, dict)]
    return [item for item in objects if item is not None]


def _extract_json_object(content: str) -> dict[str, Any]:
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise VLMAnalysisError("VLM response is not JSON")
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise VLMAnalysisError("VLM response JSON is not an object")
    return parsed


def _normalize_object(raw: dict[str, Any]) -> VLMObject | None:
    object_type = _string_value(raw.get("object_type") or raw.get("name") or raw.get("label"))
    if not object_type:
        return None
    return VLMObject(
        object_type=object_type,
        category=_string_value(raw.get("category")),
        subcategory=_string_value(raw.get("subcategory") or raw.get("sub_category")),
        color=_string_value(raw.get("color")),
        style=_string_value(raw.get("style")),
        material=_string_value(raw.get("material")),
        scene=_list_value(raw.get("scene")),
        search_terms=_list_value(raw.get("search_terms") or raw.get("keywords")),
        confidence=_confidence_value(raw.get("confidence")),
    )


def _string_value(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _list_value(value: Any) -> list[str]:
    if isinstance(value, str):
        values = re.split(r"[,，、\s]+", value)
    elif isinstance(value, list):
        values = [str(item) for item in value]
    else:
        values = []
    return list(dict.fromkeys(item.strip() for item in values if item.strip()))


def _confidence_value(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(confidence, 1.0))
