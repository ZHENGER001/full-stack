from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, AsyncIterator, Iterable

from fastapi import HTTPException, UploadFile

from .agentic_rag import plan_agentic_turn, retrieve_products_for_turn
from .bounded_agent_tools import BoundedToolResult, execute_bounded_turn, resolve_product_references
from .bundle_recommendation import build_bundle_answer, retrieve_bundle_recommendations
from .catalog import get_cart, row_to_product_card
from .config import get_settings
from .conversation_memory import (
    STRUCTURED_MEMORY_KEY,
    build_updated_structured_memory,
    dump_structured_memory,
    parse_structured_memory,
)
from .llm_client import (
    LLMGenerationError,
    LLMGenerationResult,
    generate_agent_reply_with_status,
    generate_preference_answer_with_status,
    generate_product_presentations,
    llm_model_name,
    stream_agent_reply_chunks_with_status,
)
from .observability import AgentTurnMetrics
from .react_planner import has_checkout_signal, message_with_sku_hint, plan_react_transaction, product_reference_from_step
from .schemas import ProductCard
from .turn_schema import ParsedTurn
from .visual_embedding_client import visual_match_min_score
from .visual_retriever import visual_image_search_with_diagnostics
from .vision_client import analyze_image_file_with_vlm, debug_vlm_event


logger = logging.getLogger(__name__)

ACTION_LABELS = {
    "go_detail": "查看详情",
    "add_to_cart": "加入购物车",
    "open_cart": "打开购物车",
    "search_more": "查看更多",
}
PRODUCT_ACTION_TYPES = {"go_detail", "add_to_cart"}
ALLOWED_ACTION_TYPES = set(ACTION_LABELS)
BATCH_CART_CONFIRM_PREFIX = "__batch_cart_confirm__:"
CHAT_RECOMMENDATION_DISPLAY_LIMIT = 3
CHECKOUT_CONFIRM_LABEL = "确认下单并支付"
CHECKOUT_SIGNATURE_FIELD = "checkout_signature"
CHECKOUT_DETAIL_PREVIEW_LIMIT = 3
HIGH_VALUE_ORDER_THRESHOLD = 5000.0
GENERIC_IMAGE_OBJECT_TYPES = {"", "商品", "物品", "实物", "相似商品", "可购物商品", "主要物品", "配件", "用品"}
GENERIC_IMAGE_HINT_FRAGMENTS = (
    "识别图片中的可购物商品",
    "生成适合商品检索的关键词",
    "请根据这张图片推荐相关商品",
    "帮我找这张图片里的类似商品",
    "帮我找类似商品",
    "随手拍图找相似商品",
    "类似款",
)
LOW_SIGNAL_IMAGE_TERMS = {
    "",
    "未知",
    "通用",
    "日常使用",
    "商品",
    "物品",
    "实物",
    "可购物商品",
    "主要物品",
    "类似款",
    "检索词",
    "关键词",
    "简约",
}
COMMON_IMAGE_BRAND_NOISE_TERMS = {
    "apple",
    "苹果",
    "huawei",
    "华为",
    "xiaomi",
    "小米",
    "oppo",
    "vivo",
    "honor",
    "荣耀",
    "samsung",
    "三星",
    "redmi",
    "红米",
    "nike",
    "耐克",
    "adidas",
    "阿迪达斯",
    "lenovo",
    "联想",
    "dell",
    "戴尔",
    "hp",
    "惠普",
}
MLKIT_HINT_MARKERS = {"图片识别标签", "推断品类"}
MLKIT_CLOTHING_HINT_RULES = (
    {
        "labels": ("hoodie", "sweatshirt"),
        "include": ("卫衣",),
        "exclude": ("T恤", "短袖", "短袖T恤", "速干T恤", "外套"),
    },
    {
        "labels": ("jacket", "coat"),
        "include": ("外套",),
        "exclude": ("T恤", "短袖", "短袖T恤", "速干T恤", "卫衣"),
    },
    {
        "labels": ("t shirt", "t-shirt", "tshirt", "tee shirt", "shirt"),
        "include": ("T恤", "短袖", "上衣"),
        "exclude": ("卫衣", "外套"),
    },
    {
        "labels": ("clothing",),
        "include": ("上衣", "服饰"),
        "exclude": ("卫衣", "外套"),
    },
)
VISUAL_TERM_CONFLICTS = {
    "T恤": {"卫衣", "外套", "夹克", "大衣", "风衣"},
    "短袖": {"卫衣", "外套", "夹克", "大衣", "风衣"},
    "短袖T恤": {"卫衣", "外套", "夹克", "大衣", "风衣"},
    "速干T恤": {"卫衣", "外套", "夹克", "大衣", "风衣"},
    "卫衣": {"T恤", "短袖", "短袖T恤", "速干T恤", "外套", "夹克"},
    "外套": {"T恤", "短袖", "短袖T恤", "速干T恤", "卫衣"},
}


@dataclass(frozen=True)
class ImageAnalysisResult:
    detected: dict[str, Any]
    query: str
    objects: list[dict[str, Any]]
    provider: str
    model: str | None = None
    fallback: bool = False
    image_id: str | None = None
    file_path: str | None = None

    def to_cache_payload(self) -> dict[str, Any]:
        return {
            "detected": self.detected,
            "objects": self.objects,
            "provider": self.provider,
            "model": self.model,
            "fallback": self.fallback,
            "image_id": self.image_id,
        }


def visible_chat_products(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return products[:CHAT_RECOMMENDATION_DISPLAY_LIMIT]


def sse_event(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def product_debug_summary(products: list[Any], limit: int = 5) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for product in products[:limit]:
        if hasattr(product, "model_dump"):
            data = product.model_dump(mode="json")
        elif isinstance(product, dict):
            data = product
        else:
            data = {}
        summary.append(
            {
                "id": data.get("id"),
                "title": data.get("title") or data.get("name"),
                "category": data.get("category"),
                "subcategory": data.get("subcategory"),
                "score": data.get("_image_match_score") or data.get("rerank_score"),
            }
        )
    return summary


def order_status_event(
    status: str,
    message: str,
    order_id: str | None = None,
    payment_id: str | None = None,
) -> str:
    payload: dict[str, Any] = {"status": status, "message": message}
    if order_id:
        payload["order_id"] = order_id
    if payment_id:
        payload["payment_id"] = payment_id
    return sse_event("order_status", payload)


def mock_detect_from_hint(user_hint: str | None, filename: str | None = None) -> dict[str, str]:
    # TODO: replace mock image detection with real vision encoder.
    text = f"{user_hint or ''} {filename or ''}".lower()
    if any(word in text for word in ["手机", "phone", "mobile", "redmi", "iphone", "huawei", "xiaomi", "oppo", "vivo"]):
        return {"object_type": "手机", "color": "未知", "style": "数码", "material": "玻璃机身", "scene": "日常使用"}
    if any(word in text for word in ["平板", "tablet", "ipad"]):
        return {"object_type": "平板电脑", "color": "未知", "style": "数码", "material": "金属机身", "scene": "影音办公"}
    if any(word in text for word in ["笔记本", "电脑", "laptop", "computer"]):
        return {"object_type": "笔记本电脑", "color": "未知", "style": "数码", "material": "金属机身", "scene": "办公学习"}
    if any(word in text for word in ["鞋", "shoe", "sneaker", "跑步"]):
        return {"object_type": "鞋", "color": "黑色", "style": "运动", "material": "织物", "scene": "跑步通勤"}
    if any(word in text for word in ["耳机", "headphone", "earbud"]):
        return {"object_type": "耳机", "color": "黑色", "style": "简约", "material": "塑料", "scene": "通勤降噪"}
    if any(word in text for word in ["t恤", "t-shirt", "tshirt", "tee shirt", "shirt", "短袖"]):
        return {
            "object_type": "T恤",
            "category": "服饰运动",
            "subcategory": "短袖T恤",
            "color": "未知",
            "style": "休闲",
            "material": "棉质",
            "scene": "日常穿搭",
            "search_terms": ["短袖T恤", "T恤", "上衣"],
        }
    if any(word in text for word in ["卫衣", "hoodie", "sweatshirt"]):
        return {
            "object_type": "卫衣",
            "category": "服饰运动",
            "subcategory": "卫衣",
            "color": "未知",
            "style": "休闲",
            "material": "棉质",
            "scene": "日常穿搭",
            "search_terms": ["卫衣", "连帽上衣"],
        }
    if any(word in text for word in ["外套", "jacket", "coat"]):
        return {
            "object_type": "外套",
            "category": "服饰运动",
            "subcategory": "外套",
            "color": "未知",
            "style": "休闲",
            "material": "织物",
            "scene": "日常穿搭",
            "search_terms": ["外套", "夹克"],
        }
    if any(word in text for word in ["洗面奶", "洁面", "护肤", "beauty"]):
        return {"object_type": "洁面产品", "color": "白色", "style": "护肤", "material": "乳液", "scene": "日常洁面"}
    return {"object_type": "相似商品", "color": "未知", "style": "通用", "material": "未知", "scene": "日常使用"}


def image_detection_intro(detected: dict[str, str]) -> str:
    object_type = detected.get("object_type") or "相似商品"
    color = detected.get("color") or "未知"
    style = detected.get("style") or "通用"
    material = detected.get("material") or "未知"
    scene = scene_to_text(detected.get("scene")) or "日常使用"
    if object_type == "相似商品" and color == "未知" and material == "未知":
        return "我会根据图片线索匹配相似商品。"
    description_parts = []
    if color != "未知":
        description_parts.append(color)
    if style not in {"未知", "通用"}:
        description_parts.append(style)
    description = "".join(description_parts) + object_type
    details = [f"我识别到图片里像是{description}"]
    if material != "未知":
        details.append(f"材质特征偏{material}")
    if scene:
        details.append(f"场景更接近{scene}")
    return "，".join(details) + "。"


def detected_to_query(
    detected: dict[str, Any],
    user_hint: str | None,
    brand_terms: list[str] | None = None,
) -> str:
    parts: list[str] = []
    hint = semantic_image_hint(user_hint)
    for key in ("subcategory", "category"):
        add_image_query_part(parts, detected.get(key))
    search_terms = detected.get("search_terms")
    if isinstance(search_terms, list):
        for item in search_terms:
            add_image_query_part(parts, item, brand_terms=brand_terms, brand_hint=hint)
    add_image_query_part(parts, detected.get("object_type"), brand_terms=brand_terms, brand_hint=hint)
    for key in ("color", "style"):
        add_image_query_part(
            parts,
            detected.get(key),
            allow_low_signal=False,
            brand_terms=brand_terms,
            brand_hint=hint,
        )
    add_image_query_part(parts, scene_to_text(detected.get("scene")), allow_low_signal=False)
    if hint:
        add_image_query_part(parts, hint)
    return " ".join(resolve_visual_query_conflicts(parts, detected)[:10])


def add_image_query_part(
    parts: list[str],
    value: Any,
    *,
    allow_low_signal: bool = True,
    brand_terms: list[str] | None = None,
    brand_hint: str | None = None,
) -> None:
    text = strip_unhinted_image_brand(str(value or "").strip(), brand_terms, brand_hint)
    if not text:
        return
    for token in re.split(r"[,，、/；;\s]+", text):
        normalized = token.strip()
        if not normalized:
            continue
        if normalized in LOW_SIGNAL_IMAGE_TERMS:
            continue
        if not allow_low_signal and len(normalized) <= 1:
            continue
        parts.append(normalized)


def strip_unhinted_image_brand(text: str, brand_terms: list[str] | None, brand_hint: str | None = None) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    hint_lower = str(brand_hint or "").lower()
    for term in sorted(image_brand_noise_terms(brand_terms), key=len, reverse=True):
        term_text = term.strip()
        if not term_text or term_text.lower() in hint_lower:
            continue
        value = re.sub(re.escape(term_text), "", value, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", value).strip(" -_/，,、")


def image_brand_noise_terms(brand_terms: list[str] | None) -> set[str]:
    terms = set(COMMON_IMAGE_BRAND_NOISE_TERMS)
    for brand in brand_terms or []:
        brand_text = str(brand or "").strip()
        if not brand_text:
            continue
        terms.add(brand_text)
        for token in re.split(r"[\s/|&+·,，、()（）-]+", brand_text):
            token = token.strip()
            if token:
                terms.add(token)
    return {term for term in terms if len(term) >= 2}


def semantic_image_hint(user_hint: str | None) -> str | None:
    text = " ".join((user_hint or "").strip().split())
    if not text:
        return None
    if "图片识别标签" in text or "推断品类" in text:
        return sanitize_mlkit_image_hint(text)
    cleaned = text
    for fragment in GENERIC_IMAGE_HINT_FRAGMENTS:
        cleaned = cleaned.replace(fragment, " ")
    cleaned = re.sub(r"[，,。.;；:：]+", " ", cleaned)
    cleaned = " ".join(cleaned.split())
    if not cleaned or cleaned in LOW_SIGNAL_IMAGE_TERMS:
        return None
    if len(cleaned) > 60:
        return None
    return cleaned


def sanitize_mlkit_image_hint(text: str) -> str | None:
    label_text = extract_mlkit_section(text, "图片识别标签", ("推断品类",))
    inferred_text = extract_mlkit_section(text, "推断品类", ())
    clothing_terms = mlkit_clothing_terms(label_text)
    if clothing_terms:
        return " ".join(clothing_terms)

    terms: list[str] = []
    for token in split_image_terms(inferred_text):
        if token in MLKIT_HINT_MARKERS or token in LOW_SIGNAL_IMAGE_TERMS:
            continue
        terms.append(token)
    return " ".join(dict.fromkeys(terms)) or None


def extract_mlkit_section(text: str, marker: str, stop_markers: tuple[str, ...]) -> str:
    start = text.find(marker)
    if start < 0:
        return ""
    start += len(marker)
    while start < len(text) and text[start] in "：: ":
        start += 1
    end = len(text)
    for stop in stop_markers:
        stop_index = text.find(stop, start)
        if stop_index >= 0:
            end = min(end, stop_index)
    return text[start:end].strip(" ：:")


def mlkit_clothing_terms(label_text: str) -> list[str]:
    if not label_text:
        return []
    for rule in MLKIT_CLOTHING_HINT_RULES:
        if mlkit_label_matches(label_text, rule["labels"]):
            excluded = set(rule["exclude"])
            return [term for term in rule["include"] if term not in excluded]
    return []


def mlkit_label_matches(label_text: str, needles: tuple[str, ...]) -> bool:
    normalized = re.sub(r"[-_/]+", " ", label_text.lower())
    tokens = set(re.findall(r"[a-z0-9]+", normalized))
    for needle in needles:
        normalized_needle = re.sub(r"[-_/]+", " ", needle.lower()).strip()
        if " " in normalized_needle:
            if normalized_needle in normalized:
                return True
        elif normalized_needle in tokens:
            return True
    return False


def split_image_terms(text: str) -> list[str]:
    return [
        token.strip()
        for token in re.split(r"[,，、/；;:：\s]+", text or "")
        if token.strip()
    ]


def resolve_visual_query_conflicts(parts: list[str], detected: dict[str, Any] | None = None) -> list[str]:
    unique_parts = list(dict.fromkeys(str(part).strip() for part in parts if str(part).strip()))
    active_terms = visual_anchor_terms(detected, unique_parts)
    if not active_terms:
        return unique_parts
    excluded: set[str] = set()
    for term in active_terms:
        excluded.update(VISUAL_TERM_CONFLICTS.get(term, set()))
    excluded.difference_update(active_terms)
    return [
        part
        for part in unique_parts
        if not any(conflict and conflict in part for conflict in excluded)
    ]


def visual_anchor_terms(detected: dict[str, Any] | None, fallback_parts: list[str]) -> set[str]:
    values: list[Any] = []
    if detected:
        values.extend([detected.get("subcategory"), detected.get("object_type")])
        search_terms = detected.get("search_terms")
        if isinstance(search_terms, list):
            values.extend(search_terms)
    if not values:
        values = fallback_parts

    anchors: set[str] = set()
    for value in values:
        text = str(value or "")
        for term in VISUAL_TERM_CONFLICTS:
            if term in text:
                anchors.add(term)
    return anchors


def scene_to_text(scene: Any) -> str:
    if isinstance(scene, list):
        return " ".join(str(item).strip() for item in scene if str(item).strip())
    return str(scene or "").strip()


def save_upload(file: UploadFile) -> tuple[str, str, Path]:
    settings = get_settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "upload.jpg").suffix or ".jpg"
    image_id = f"img_{uuid.uuid4().hex[:12]}"
    filename = f"{image_id}{ext}"
    file_path = settings.upload_dir / filename
    with file_path.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    return image_id, f"/uploads/{filename}", file_path


def analyze_image(conn, image_id: str, user_hint: str | None = None) -> ImageAnalysisResult:
    row = conn.execute("SELECT * FROM uploaded_images WHERE image_id = ?", (image_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Image not found")
    known_brands = load_known_brands(conn)
    debug_vlm_event(
        "VLM_ANALYZE_START",
        {
            "image_id": image_id,
            "has_cache": bool(row["detected_json"] and row["query"]),
            "has_user_hint": bool(user_hint),
            "file_path": row["file_path"],
        },
    )
    if row["detected_json"] and row["query"] and not user_hint:
        analysis = cached_image_analysis(row["detected_json"], row["query"], image_id=image_id, file_path=row["file_path"])
        sanitized_query = detected_to_query(analysis.detected, None, brand_terms=known_brands)
        if sanitized_query and sanitized_query != analysis.query:
            analysis = replace(analysis, query=sanitized_query)
            conn.execute(
                "UPDATE uploaded_images SET query = ? WHERE image_id = ?",
                (analysis.query, image_id),
            )
        debug_vlm_event(
            "VLM_CACHE_HIT",
            {
                "image_id": image_id,
                "detected": analysis.detected,
                "objects": analysis.objects,
                "query": analysis.query,
                "provider": analysis.provider,
                "model": analysis.model,
                "fallback": analysis.fallback,
            },
        )
        return analysis

    try:
        vlm_result = run_async_blocking(
            analyze_image_file_with_vlm(
                Path(row["file_path"]),
                user_hint=user_hint,
                catalog_taxonomy=catalog_taxonomy_for_vlm(conn),
            )
        )
        objects = [image_detected_payload(item.to_dict()) for item in vlm_result.objects]
        if not objects:
            raise ValueError("VLM returned no objects")
        detected = objects[0]
        analysis = ImageAnalysisResult(
            detected=detected,
            query=detected_to_query(detected, user_hint, brand_terms=known_brands),
            objects=objects,
            provider=vlm_result.provider,
            model=vlm_result.model,
            fallback=False,
            image_id=image_id,
            file_path=str(row["file_path"]),
        )
    except Exception as exc:
        logger.info("vlm_image_analysis_failed=%s", exc.__class__.__name__)
        detected = image_detected_payload(mock_detect_from_hint(user_hint, row["file_path"]))
        debug_vlm_event(
            "VLM_FALLBACK",
            {
                "image_id": image_id,
                "error": exc.__class__.__name__,
                "detected": detected,
            },
        )
        analysis = ImageAnalysisResult(
            detected=detected,
            query=detected_to_query(detected, user_hint, brand_terms=known_brands),
            objects=[detected],
            provider="mock",
            model=None,
            fallback=True,
            image_id=image_id,
            file_path=str(row["file_path"]),
        )

    conn.execute(
        "UPDATE uploaded_images SET detected_json = ?, query = ? WHERE image_id = ?",
        (json.dumps(analysis.to_cache_payload(), ensure_ascii=False), analysis.query, image_id),
    )
    return analysis


def cached_image_analysis(
    raw_detected_json: str,
    query: str,
    image_id: str | None = None,
    file_path: str | None = None,
) -> ImageAnalysisResult:
    payload = json.loads(raw_detected_json)
    if isinstance(payload, dict) and isinstance(payload.get("detected"), dict):
        detected = image_detected_payload(payload["detected"])
        objects = [
            image_detected_payload(item)
            for item in payload.get("objects", [])
            if isinstance(item, dict)
        ] or [detected]
        cached_image_id = payload.get("image_id") if isinstance(payload.get("image_id"), str) else None
        return ImageAnalysisResult(
            detected=detected,
            query=query,
            objects=objects,
            provider=str(payload.get("provider") or "cache"),
            model=payload.get("model") if isinstance(payload.get("model"), str) else None,
            fallback=bool(payload.get("fallback", False)),
            image_id=image_id or cached_image_id,
            file_path=file_path,
        )
    detected = image_detected_payload(payload if isinstance(payload, dict) else {})
    return ImageAnalysisResult(
        detected=detected,
        query=query,
        objects=[detected],
        provider="mock",
        model=None,
        fallback=True,
        image_id=image_id,
        file_path=file_path,
    )


def image_detected_payload(raw: dict[str, Any]) -> dict[str, Any]:
    object_type = str(raw.get("object_type") or raw.get("label") or "相似商品").strip() or "相似商品"
    color = nullable_text(raw.get("color"))
    style = nullable_text(raw.get("style"))
    material = nullable_text(raw.get("material"))
    scene = raw.get("scene") if raw.get("scene") is not None else []
    scene_text = scene_to_text(scene)
    attributes = {
        key: value
        for key, value in {
            "color": color,
            "style": style,
            "material": material,
            "scene": scene_text,
        }.items()
        if value
    }
    search_terms = raw.get("search_terms")
    if not isinstance(search_terms, list):
        search_terms = []
    return {
        "object_type": object_type,
        "label": nullable_text(raw.get("label")) or object_type,
        "attributes": attributes,
        "color": color,
        "style": style,
        "material": material,
        "scene": scene,
        "category": nullable_text(raw.get("category")),
        "subcategory": nullable_text(raw.get("subcategory")),
        "search_terms": [str(item).strip() for item in search_terms if str(item).strip()],
        "confidence": clamp_confidence(raw.get("confidence")),
    }


def normalize_image_object(raw: dict[str, Any]) -> dict[str, Any]:
    return image_detected_payload(raw)


def is_searchable_image_object(item: dict[str, Any]) -> bool:
    normalized = normalize_image_object(item)
    object_type = str(normalized.get("object_type") or "").strip()
    if object_type in GENERIC_IMAGE_OBJECT_TYPES:
        return False
    if normalized.get("subcategory") or normalized.get("search_terms"):
        return True
    return float(normalized.get("confidence") or 0.0) >= 0.35


def build_image_candidate_query(
    item: dict[str, Any],
    user_hint: str | None = None,
    brand_terms: list[str] | None = None,
) -> str:
    normalized = normalize_image_object(item)
    if not is_searchable_image_object(normalized):
        return ""
    return detected_to_query(normalized, user_hint, brand_terms=brand_terms)


def score_image_product_match(
    product: dict[str, Any],
    item: dict[str, Any],
    object_index: int = 0,
) -> tuple[float, str, dict[str, Any]]:
    normalized = normalize_image_object(item)
    text = product_match_text(product)
    score = 0.0
    evidence: list[str] = []

    if normalized.get("category") and product.get("category") == normalized["category"]:
        score += 0.18
        evidence.append("category")
    if normalized.get("subcategory") and product.get("subcategory") == normalized["subcategory"]:
        score += 0.42
        evidence.append("subcategory")

    lexical_hits = 0
    terms = [normalized.get("object_type"), *(normalized.get("search_terms") or [])]
    for term in dict.fromkeys(str(term or "").strip() for term in terms):
        if not term or term in GENERIC_IMAGE_OBJECT_TYPES or term in LOW_SIGNAL_IMAGE_TERMS:
            continue
        if term.lower() in text:
            lexical_hits += 1
    if lexical_hits:
        score += min(0.34, 0.18 + 0.08 * (lexical_hits - 1))
        evidence.append("lexical")

    color = str(normalized.get("color") or "").strip()
    if color and color not in LOW_SIGNAL_IMAGE_TERMS and color.lower() in text:
        score += 0.08
        evidence.append("color")

    visual_score = clamp_confidence(product.get("_visual_vector_score"))
    if visual_score >= visual_match_min_score():
        score += min(0.46, visual_score * 0.46)
        evidence.append("visual_vector")

    confidence = float(normalized.get("confidence") or 0.0)
    score += min(confidence, 1.0) * 0.08
    score -= max(object_index, 0) * 0.04
    score = max(0.0, min(score, 1.0))

    evidence_set = set(evidence)
    if "subcategory" in evidence_set and ("lexical" in evidence_set or "visual_vector" in evidence_set) and score >= 0.62:
        level = "exact_like"
    elif "visual_vector" in evidence_set and score >= 0.50:
        level = "similar"
    elif "lexical" in evidence_set and score >= 0.48:
        level = "similar"
    elif evidence_set <= {"category"} or score < 0.48:
        level = "weak"
    else:
        level = "similar"
    return round(score, 3), level, {
        "evidence": evidence,
        "lexical_hits": lexical_hits,
        "visual_vector_score": visual_score or None,
    }


def is_acceptable_image_match(score: float, level: str) -> bool:
    return level in {"exact_like", "similar"} and score >= 0.48


def filter_products_for_image_match(
    products: list[dict[str, Any]],
    analysis: ImageAnalysisResult | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not analysis or not products:
        return products, {"match_level": "not_applicable", "accepted_count": len(products), "rejected_count": 0}

    objects = [
        normalize_image_object(item)
        for item in analysis.objects
        if isinstance(item, dict) and is_searchable_image_object(item)
    ]
    if not objects:
        return products, {"match_level": "not_searchable", "accepted_count": len(products), "rejected_count": 0}

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for product_index, product in enumerate(products):
        best: tuple[float, str, dict[str, Any], dict[str, Any]] | None = None
        conflict_reasons: list[str] = []
        for object_index, item in enumerate(objects):
            if product_conflicts_with_visual_anchor(product, item):
                conflict_reasons.append(str(item.get("subcategory") or item.get("object_type") or "visual_anchor"))
                continue
            score, level, evidence = score_image_product_match(product, item, object_index)
            if best is None or score > best[0]:
                best = (score, level, evidence, item)
        if best and is_acceptable_image_match(best[0], best[1]):
            enriched = dict(product)
            enriched["_image_match_score"] = best[0]
            enriched["_image_match_level"] = best[1]
            enriched["_image_match_evidence"] = best[2]
            enriched["_image_original_index"] = product_index
            accepted.append(enriched)
        else:
            rejected.append(
                {
                    "id": product.get("id"),
                    "reason": "visual_conflict" if conflict_reasons else "weak_visual_match",
                    "visual_conflicts": conflict_reasons,
                    "best_score": best[0] if best else 0.0,
                    "best_level": best[1] if best else "weak",
                }
            )

    accepted.sort(
        key=lambda product: (
            0 if product.get("_image_match_level") == "exact_like" else 1,
            -float(product.get("_image_match_score") or 0.0),
            int(product.get("_image_original_index") or 0),
        )
    )
    for product in accepted:
        product.pop("_image_original_index", None)

    if not accepted:
        return [], {
            "match_level": "no_match",
            "accepted_count": 0,
            "rejected_count": len(rejected),
            "rejected": rejected,
        }
    return accepted, {
        "match_level": str(accepted[0].get("_image_match_level") or "similar"),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "rejected": rejected,
        "top_score": accepted[0].get("_image_match_score"),
    }


def product_conflicts_with_visual_anchor(product: dict[str, Any], item: dict[str, Any]) -> bool:
    anchors = visual_anchor_terms(item, [])
    if not anchors:
        return False
    catalog_text = " ".join(
        str(product.get(key) or "")
        for key in ("title", "category", "subcategory")
    )
    for anchor in anchors:
        conflicts = VISUAL_TERM_CONFLICTS.get(anchor) or set()
        if any(conflict and conflict in catalog_text for conflict in conflicts):
            return True
    return False


def retrieve_visual_image_candidates(
    conn,
    analysis: ImageAnalysisResult | None,
    limit: int = 20,
) -> tuple[list[ProductCard], dict[str, Any], dict[str, float]]:
    if not analysis or not analysis.file_path:
        return [], {"status": "skipped", "reason": "missing_analysis_file_path"}, {}

    visual_result = visual_image_search_with_diagnostics(analysis.file_path, top_k=limit)
    visual_scores = {
        str(hit["product_id"]): float(hit.get("score") or 0.0)
        for hit in visual_result.hits
        if hit.get("product_id")
    }
    cards = load_product_cards_by_ids(conn, list(visual_scores))
    diagnostics = {
        **visual_result.diagnostics,
        "candidate_ids": list(visual_scores)[:limit],
    }
    return cards, diagnostics, visual_scores


def load_product_cards_by_ids(conn, product_ids: list[str]) -> list[ProductCard]:
    ordered_ids = [str(product_id) for product_id in dict.fromkeys(product_ids) if str(product_id).strip()]
    if not ordered_ids:
        return []
    placeholders = ", ".join("?" for _ in ordered_ids)
    rows = conn.execute(
        f"""
        SELECT p.id, p.title, p.brand, p.category, p.subcategory, p.price, p.rating, p.image_path,
               p.marketing_description,
               COALESCE(rc.review_count, 0) AS review_count,
               COALESCE(sc.sku_count, 0) AS sku_count,
               COALESCE(fc.faq_count, 0) AS faq_count,
               COALESCE(ss.stock, 0) AS stock,
               ss.sku_summary AS sku_summary
        FROM products p
        LEFT JOIN (
            SELECT product_id, COUNT(*) AS review_count
            FROM product_reviews
            GROUP BY product_id
        ) rc ON rc.product_id = p.id
        LEFT JOIN (
            SELECT product_id, COUNT(*) AS sku_count
            FROM product_skus
            GROUP BY product_id
        ) sc ON sc.product_id = p.id
        LEFT JOIN (
            SELECT product_id, COUNT(*) AS faq_count
            FROM product_faqs
            GROUP BY product_id
        ) fc ON fc.product_id = p.id
        LEFT JOIN (
            SELECT product_id, SUM(stock) AS stock, GROUP_CONCAT(sku_name, ' / ') AS sku_summary
            FROM product_skus
            GROUP BY product_id
        ) ss ON ss.product_id = p.id
        WHERE p.id IN ({placeholders})
        """,
        ordered_ids,
    ).fetchall()
    by_id = {str(row["id"]): row_to_product_card(row) for row in rows}
    return [by_id[product_id] for product_id in ordered_ids if product_id in by_id]


def merge_product_cards(*groups: list[ProductCard]) -> list[ProductCard]:
    merged: list[ProductCard] = []
    seen: set[str] = set()
    for group in groups:
        for product in group:
            if product.id in seen:
                continue
            seen.add(product.id)
            merged.append(product)
    return merged


def apply_visual_match_metadata(products: list[dict[str, Any]], visual_scores: dict[str, float]) -> list[dict[str, Any]]:
    for product in products:
        product_id = str(product.get("id") or "")
        score = visual_scores.get(product_id)
        if score is None:
            continue
        product["_visual_vector_score"] = score
        sources = set(product.get("_candidate_sources") or [])
        sources.add("visual_milvus")
        product["_candidate_sources"] = sorted(sources)
    return products


def image_match_diagnostics_with_visual(
    image_match: dict[str, Any],
    visual_diagnostics: dict[str, Any],
    visual_scores: dict[str, float],
) -> dict[str, Any]:
    diagnostics = dict(image_match)
    diagnostics["visual_search"] = visual_diagnostics
    diagnostics["visual_candidate_count"] = len(visual_scores)
    diagnostics["sources"] = ["visual_milvus", "vlm_attributes", "text_rag_fallback"]
    return diagnostics


def retrieve_image_match_products(
    conn,
    analysis: ImageAnalysisResult,
    limit: int = 12,
    query_override: str | None = None,
) -> tuple[list[ProductCard], dict[str, Any]]:
    query = query_override or analysis.query or detected_to_query(
        analysis.detected,
        None,
        brand_terms=load_known_brands(conn),
    )
    top_k = min(20, max(limit * 2, 3))
    visual_products, visual_diagnostics, visual_scores = retrieve_visual_image_candidates(conn, analysis, top_k)
    retrieval_result = retrieve_products_for_turn(
        conn,
        query,
        load_known_brands(conn),
        plan=None,
        top_k=top_k,
    )
    candidate_products = merge_product_cards(visual_products, retrieval_result.search_result.products)
    grounded_products = apply_visual_match_metadata(
        build_grounded_products(conn, candidate_products),
        visual_scores,
    )
    filtered_products, image_match = filter_products_for_image_match(grounded_products, analysis)
    image_match = image_match_diagnostics_with_visual(image_match, visual_diagnostics, visual_scores)

    alternatives_match: dict[str, Any] | None = None
    if not filtered_products and retrieval_result.search_result.alternatives:
        grounded_alternatives = apply_visual_match_metadata(
            build_grounded_products(conn, retrieval_result.search_result.alternatives),
            visual_scores,
        )
        filtered_products, alternatives_match = filter_products_for_image_match(grounded_alternatives, analysis)
        if filtered_products:
            image_match = image_match_diagnostics_with_visual(alternatives_match, visual_diagnostics, visual_scores)

    product_cards = [
        ProductCard.model_validate(product)
        for product in filtered_products[:limit]
    ]
    diagnostics = {
        "query": query,
        "retrieval_status": retrieval_result.search_result.status,
        "parsed_filters": retrieval_result.parsed_filters,
        "image_match": image_match,
        "alternatives_match": alternatives_match,
        "visual_search": visual_diagnostics,
        "retrieval_sources": ["visual_milvus", "vlm_attributes", "text_rag_fallback"],
        "candidate_count": len(candidate_products),
        "text_candidate_count": len(retrieval_result.search_result.products),
        "visual_candidate_count": len(visual_products),
        "returned_count": len(product_cards),
    }
    debug_vlm_event(
        "IMAGE_RETRIEVAL_RESULT",
        {
            "image_id": analysis.image_id,
            "query": query,
            "detected": analysis.detected,
            "candidate_count": len(candidate_products),
            "text_candidate_count": len(retrieval_result.search_result.products),
            "visual_candidate_count": len(visual_products),
            "returned_count": len(product_cards),
            "products": product_debug_summary(product_cards, limit=8),
            "image_match": image_match,
        },
    )
    return product_cards, diagnostics


def image_analysis_event_payload(analysis: dict[str, Any], diagnostics: dict[str, Any]) -> dict[str, Any]:
    objects = analysis.get("objects") if isinstance(analysis, dict) else []
    image_diagnostics = (diagnostics or {}).get("image_match") if isinstance(diagnostics, dict) else None
    if not isinstance(image_diagnostics, dict):
        image_diagnostics = diagnostics or {}
    match_level = str(image_diagnostics.get("match_level") or "unknown")
    if match_level == "no_match":
        summary = "没有足够相似的商品，建议换个角度拍摄或补充品类。"
    elif objects:
        first = normalize_image_object(objects[0])
        summary = f"识别到可能是{first.get('label') or first.get('object_type')}，正在匹配相似商品。"
    else:
        summary = "正在根据图片线索匹配相似商品。"
    return {
        "objects": objects or [],
        "match_level": match_level,
        "summary": summary,
        "sources": image_diagnostics.get("sources") or [],
        "visual_search": image_diagnostics.get("visual_search") or {},
    }


def product_match_text(product: dict[str, Any]) -> str:
    return " ".join(
        str(product.get(key) or "")
        for key in (
            "title",
            "brand",
            "category",
            "subcategory",
            "marketing_description",
            "sku_text",
            "sku_summary",
            "reason",
        )
    ).lower()


def nullable_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def clamp_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(confidence, 1.0))


def catalog_taxonomy_for_vlm(conn) -> str:
    rows = conn.execute(
        "SELECT DISTINCT category, subcategory FROM products ORDER BY category, subcategory"
    ).fetchall()
    grouped: dict[str, list[str]] = {}
    for row in rows:
        category = str(row["category"] or "").strip()
        subcategory = str(row["subcategory"] or "").strip()
        if not category:
            continue
        grouped.setdefault(category, [])
        if subcategory and subcategory not in grouped[category]:
            grouped[category].append(subcategory)
    return "\n".join(
        f"{category}: {'、'.join(subcategories)}"
        for category, subcategories in grouped.items()
    )


def stream_chat(
    conn,
    session_id: str,
    message: str,
    image_id: str | None,
    current_product_id: str | None = None,
    cart_context: list[dict] | None = None,
) -> Iterable[str]:
    metrics = AgentTurnMetrics()
    try:
        for chunk in _stream_chat(conn, session_id, message, image_id, current_product_id, cart_context or []):
            metrics.observe_sse_chunk(chunk)
            yield chunk
    except Exception:
        logger.exception("agent_stream_failed session_id=%s image_id=%s", session_id, image_id)
        for chunk in (
            sse_event("error", {"message": "AI 导购暂时遇到问题，请稍后再试。"}),
            sse_event("delta", {"text": "AI 导购暂时遇到问题，请稍后再试。"}),
            sse_event("done", {"session_id": session_id}),
        ):
            metrics.observe_sse_chunk(chunk)
            yield chunk
    finally:
        metrics.finish()


def commit_stream_progress(conn) -> None:
    try:
        conn.commit()
    except Exception:
        logger.exception("agent_stream_commit_failed")
        raise


def _stream_chat(
    conn,
    session_id: str,
    message: str,
    image_id: str | None,
    current_product_id: str | None,
    cart_context: list[dict],
) -> Iterable[str]:
    from .agent_orchestrator import stream_agent_turn
    from .agent_state import AgentTurnRequest

    yield from stream_agent_turn(
        conn,
        AgentTurnRequest(
            session_id=session_id,
            message=message,
            image_id=image_id,
            current_product_id=current_product_id,
            cart_context=cart_context,
        ),
    )


def _stream_chat_legacy(
    conn,
    session_id: str,
    message: str,
    image_id: str | None,
    current_product_id: str | None,
    cart_context: list[dict],
) -> Iterable[str]:
    ensure_session(conn, session_id)
    if current_product_id and product_exists(conn, current_product_id):
        update_session_state(conn, session_id, current_product_id=current_product_id)
    previous_chat_history = load_chat_history(conn, session_id)
    stored_user_message = batch_cart_confirm_display_text(message) or message
    conn.execute(
        "INSERT INTO chat_messages(id, session_id, role, content, image_id) VALUES (?, ?, ?, ?, ?)",
        (f"msg_{uuid.uuid4().hex[:12]}", session_id, "user", stored_user_message, image_id),
    )
    if is_batch_cart_confirm_message(message):
        yield from emit_batch_cart_confirm_turn(conn, session_id, message, image_id)
        return

    chat_history = previous_chat_history
    conversation_state = load_conversation_state(conn, session_id, current_product_id, cart_context)
    if is_order_cancel_intent(message):
        yield from emit_order_cancel_turn(conn, session_id, message, image_id)
        return
    pending_checkout_message = pending_cart_add_checkout_message(message, chat_history)
    if pending_checkout_message:
        yield from emit_cart_add_checkout_turn(
            conn,
            session_id,
            f"{pending_checkout_message} {message}",
            image_id,
            chat_history,
            conversation_state,
        )
        return
    react_plan = run_async_blocking(plan_react_transaction(message, chat_history, conversation_state))
    if react_plan.should_execute and any(step.action in {"cart_add", "checkout"} for step in react_plan.steps):
        yield from emit_react_transaction_turn(conn, session_id, message, image_id, react_plan)
        return
    if is_cart_add_checkout_intent(message):
        yield from emit_cart_add_checkout_turn(conn, session_id, message, image_id, chat_history, conversation_state)
        return
    if is_checkout_intent(message):
        yield from emit_checkout_turn(conn, session_id, message, image_id)
        return
    # legacy 入口保持和 agent_orchestrator 一致：带图请求先做 VLM，再进入检索。
    image_query = None
    image_analysis = None
    if image_id:
        image_analysis = analyze_image(conn, image_id, message)
        detected = image_analysis.detected
        image_query = image_analysis.query
        yield sse_event(
            "delta",
            {
                "text": image_detection_intro(detected)
            },
        )

    turn_plan = None
    parsed_turn = None
    try:
        turn_plan = run_async_blocking(plan_agentic_turn(message, chat_history, conversation_state))
        parsed_turn = turn_plan.parsed_turn
        logger.info("agent_parsed_turn=%s", parsed_turn.model_dump(mode="json"))
        # 图片请求不允许被文本 planner 的工具路由或澄清分支提前截断。
        if turn_plan.should_run_bounded_tool and not image_id:
            bounded_result = execute_bounded_turn(conn, parsed_turn, conversation_state)
            yield from emit_bounded_result(conn, session_id, message, image_id, bounded_result)
            return
        if parsed_turn.intent_type == "bundle_recommendation" and not image_id:
            yield from emit_bundle_recommendation_turn(conn, session_id, message, image_id, turn_plan)
            return
        if not turn_plan.should_search_products and not image_id:
            assistant_content = turn_plan.policy.response_text or "这个操作我正在支持中。"
            llm_status = None
            if parsed_turn.intent_type == "preference_question":
                assistant_content, llm_status = build_preference_answer(
                    message,
                    assistant_content,
                    conversation_state,
                )
            actions = build_clarification_actions(conn, parsed_turn.clarification_question or assistant_content)
            if llm_status:
                yield sse_event("llm_status", llm_status)
            yield sse_event("delta", {"text": assistant_content})
            if actions:
                yield sse_event("actions", {"actions": actions})
            store_assistant_message(conn, session_id, assistant_content, image_id)
            update_session_state(
                conn,
                session_id,
                last_query=message,
                last_actions=actions or None,
                parsed_turn=parsed_turn,
            )
            yield sse_event("done", {"session_id": session_id})
            return
    except Exception as exc:
        logger.info("turn_parser_failed=%s", exc.__class__.__name__)

    cart_product_id = resolve_cart_product_id(conn, session_id, message, current_product_id, cart_context)
    if cart_product_id:
        skus = fetch_cart_skus(conn, cart_product_id)
        selected_sku = resolve_sku_from_message(message, skus)
        if len(skus) > 1 and selected_sku is None:
            product = conn.execute("SELECT id, title FROM products WHERE id = ?", (cart_product_id,)).fetchone()
            if product:
                actions = build_sku_selection_actions(skus)
                assistant_content = build_sku_selection_prompt(product["title"], skus)
                yield sse_event("delta", {"text": assistant_content})
                yield sse_event("actions", {"actions": actions})
                store_assistant_message(conn, session_id, assistant_content, image_id)
                update_session_state(
                    conn,
                    session_id,
                    last_query=message,
                    current_product_id=cart_product_id,
                    last_actions=actions,
                )
                yield sse_event("done", {"session_id": session_id})
                return
        cart_product = add_product_to_cart(conn, cart_product_id, selected_sku["id"] if selected_sku else None)
        if cart_product:
            actions = normalize_actions(conn, [{"type": "open_cart", "label": "打开购物车", "product_id": None}])
            sku_text = f"（{cart_product['sku_name']}）" if cart_product.get("sku_name") else ""
            cart_payload = get_cart(conn).model_dump(mode="json")
            assistant_content = f"已把 {cart_product['title']}{sku_text} 加入购物车，数量 1。购物车详情如下。"
            yield sse_event("delta", {"text": assistant_content})
            yield sse_event("cart", cart_payload)
            yield sse_event("actions", {"actions": actions})
            store_assistant_message(conn, session_id, assistant_content, image_id)
            update_session_state(
                conn,
                session_id,
                last_query=message,
                current_product_id=cart_product_id,
                last_actions=actions,
            )
            yield sse_event("done", {"session_id": session_id})
            return

    final_user_query = build_final_user_query(conn, message, image_query, current_product_id, session_id)
    # 图片检索只使用最终 query 自身解析出的过滤条件，不沿用文本 planner 的约束。
    retrieval_turn_plan = None if image_id else turn_plan
    retrieval_result = retrieve_products_for_turn(conn, final_user_query, load_known_brands(conn), retrieval_turn_plan)
    parsed_filters = retrieval_result.parsed_filters
    logger.info("agent_final_user_query=%s parsed_filters=%s", final_user_query, parsed_filters)
    for waiting_text in build_waiting_deltas(message, parsed_filters, image_id, bool(chat_history)):
        yield sse_event("delta", {"text": f"{waiting_text}\n"})
        time.sleep(0.25)
    yield sse_event(
        "retrieval_status",
        {
            "final_user_query": final_user_query,
            "parsed_filters": parsed_filters,
            "pipeline": retrieval_result.pipeline,
            "sources": retrieval_result.sources,
            "fusion": retrieval_result.fusion,
            "vector_backend": retrieval_result.vector_backend,
            "graph_backend": retrieval_result.graph_backend,
            "turn": {
                "intent_type": "image_search" if image_id else parsed_turn.intent_type if parsed_turn else "unknown",
                "route_hint": "direct_tool" if image_id else parsed_turn.route_hint if parsed_turn else "direct_tool",
                "needs_clarification": False if image_id else parsed_turn.needs_clarification if parsed_turn else False,
                "graph_backend": turn_plan.graph_backend if turn_plan else "langgraph_fallback",
            },
        },
    )
    search_result = retrieval_result.search_result
    products = search_result.products
    alternatives = search_result.alternatives
    yield sse_event("retrieval_diagnostics", search_result.diagnostics)
    visual_scores: dict[str, float] = {}
    visual_diagnostics: dict = {"status": "skipped", "reason": "no_image"}
    if image_analysis:
        visual_products, visual_diagnostics, visual_scores = retrieve_visual_image_candidates(
            conn,
            image_analysis,
            limit=max(20, len(products) + 8),
        )
        products = merge_product_cards(visual_products, products)
    grounded_products = apply_visual_match_metadata(
        build_grounded_products(conn, products),
        visual_scores,
    )
    if image_analysis:
        grounded_products, image_match_diagnostics = filter_products_for_image_match(
            grounded_products,
            image_analysis,
        )
        image_match_diagnostics = image_match_diagnostics_with_visual(
            image_match_diagnostics,
            visual_diagnostics,
            visual_scores,
        )
        grounded_alternatives = build_grounded_products(conn, alternatives)
        grounded_alternatives = apply_visual_match_metadata(grounded_alternatives, visual_scores)
        grounded_alternatives, alternative_match_diagnostics = filter_products_for_image_match(
            grounded_alternatives,
            image_analysis,
        )
        if not grounded_products and grounded_alternatives:
            image_match_diagnostics = image_match_diagnostics_with_visual(
                alternative_match_diagnostics,
                visual_diagnostics,
                visual_scores,
            )
        yield sse_event(
            "image_analysis",
            image_analysis_event_payload(image_analysis.to_cache_payload(), image_match_diagnostics),
        )
    else:
        grounded_alternatives = [] if grounded_products else build_grounded_products(conn, alternatives)
    visible_products_from_search = visible_chat_products(grounded_products)
    visible_alternatives = visible_chat_products(grounded_alternatives)
    visible_products = visible_products_from_search or visible_alternatives
    enrich_product_presentations(message, visible_products)
    faq_context = load_faq_context(conn, [product["id"] for product in visible_products_from_search])
    chat_history = load_chat_history(conn, session_id)
    actions = build_actions(conn, visible_products, final_user_query, parsed_filters)
    if visible_products_from_search:
        yield sse_event("products", {"products": visible_products_from_search})
    elif visible_alternatives:
        yield sse_event("alternatives", {"products": visible_alternatives, "match_type": "alternatives"})
    if not visible_products_from_search and visible_alternatives:
        answer = build_alternative_answer(message, visible_alternatives)
        llm_status = {"mode": "fallback", "reason": "alternatives_available"}
        yield sse_event("llm_status", llm_status)
        yield sse_event("delta", {"text": answer})
    else:
        answer, llm_status = yield from stream_grounded_answer_events(
            message,
            visible_products_from_search,
            faq_context,
            chat_history,
        )
        if visible_products_from_search:
            yield sse_event("llm_status", llm_status)

    if actions:
        yield sse_event("actions", {"actions": actions})

    assistant_content = append_recommendation_marker(answer, visible_products)
    store_assistant_message(conn, session_id, assistant_content, image_id)
    update_session_state(
        conn,
        session_id,
        last_query=message,
        last_recommended_product_ids=[product["id"] for product in visible_products],
        current_product_id=visible_products[0]["id"] if visible_products else current_product_id,
        last_actions=actions,
        parsed_turn=parsed_turn,
        visible_products=visible_products,
    )
    yield sse_event("done", {"session_id": session_id})


def emit_bounded_result(
    conn,
    session_id: str,
    message: str,
    image_id: str | None,
    result: BoundedToolResult,
) -> Iterable[str]:
    yield from emit_bounded_events(conn, session_id, message, image_id, result, store=True, done=True)


def build_preference_answer(
    message: str,
    fallback_answer: str,
    conversation_state: dict[str, Any] | None,
) -> tuple[str, dict[str, str]]:
    try:
        result = run_async_blocking(generate_preference_answer_with_status(message, fallback_answer, conversation_state))
        return result.content, {"mode": "preference_llm", "provider": result.provider, "model": result.model}
    except LLMGenerationError as exc:
        return fallback_answer, {"mode": "fallback", "reason": str(exc)}
    except Exception as exc:
        return fallback_answer, {"mode": "fallback", "reason": exc.__class__.__name__}


def emit_bounded_events(
    conn,
    session_id: str,
    message: str,
    image_id: str | None,
    result: BoundedToolResult,
    *,
    store: bool,
    done: bool,
) -> Iterable[str]:
    actions = normalize_actions(conn, result.actions)
    yield sse_event(
        "tool_diagnostics",
        {
            "tool_name": result.tool_name,
            "status": result.status,
            **result.diagnostics,
        },
    )
    yield sse_event("delta", {"text": result.response_text})
    if result.comparison:
        yield sse_event("comparison", result.comparison)
    if result.products:
        yield sse_event("products", {"products": result.products})
    if result.cart is not None:
        yield sse_event("cart", result.cart)
    if result.status == "needs_reference" and not actions:
        actions = build_reference_clarification_actions(conn, result.response_text)
    if actions:
        yield sse_event("actions", {"actions": actions})

    if not store:
        return
    store_assistant_message(conn, session_id, result.response_text, image_id)
    update_session_state(
        conn,
        session_id,
        last_query=message,
        last_recommended_product_ids=result.product_ids or None,
        current_product_id=result.current_product_id,
        last_actions=actions or None,
        visible_products=result.products or None,
        cart=result.cart,
    )
    if done:
        yield sse_event("done", {"session_id": session_id})


def emit_cart_add_checkout_turn(
    conn,
    session_id: str,
    message: str,
    image_id: str | None,
    chat_history: list[dict[str, str]],
    conversation_state: dict[str, Any],
) -> Iterable[str]:
    try:
        turn_plan = run_async_blocking(plan_agentic_turn(message, chat_history, conversation_state))
        parsed_turn = turn_plan.parsed_turn
    except Exception as exc:
        logger.info("cart_add_checkout_parse_failed=%s", exc.__class__.__name__)
        yield from emit_checkout_turn(conn, session_id, message, image_id)
        return

    if parsed_turn.intent_type != "cart_add":
        yield from emit_checkout_turn(conn, session_id, message, image_id)
        return

    add_result = execute_bounded_turn(conn, parsed_turn, conversation_state)
    yield sse_event(
        "workflow_status",
        {
            "workflow": "cart_add_checkout",
            "step": "cart_add",
            "status": add_result.status,
            "graph_backend": turn_plan.graph_backend,
        },
    )
    yield from emit_bounded_events(conn, session_id, message, image_id, add_result, store=True, done=False)
    if add_result.status != "ok":
        yield sse_event("done", {"session_id": session_id})
        return

    yield sse_event(
        "workflow_status",
        {
            "workflow": "cart_add_checkout",
            "step": "checkout",
            "status": "start",
            "graph_backend": turn_plan.graph_backend,
        },
    )
    checkout_message = "确认下单并支付" if should_auto_confirm_checkout(message) else message
    yield from emit_checkout_turn(conn, session_id, checkout_message, image_id)


def emit_react_transaction_turn(
    conn,
    session_id: str,
    message: str,
    image_id: str | None,
    react_plan,
) -> Iterable[str]:
    yield sse_event(
        "workflow_status",
        {
            "workflow": "react_transaction",
            "step": "planner",
            "status": "ok",
            "confidence": react_plan.confidence,
            "actions": [step.action for step in react_plan.steps],
        },
    )
    completed_any_step = False
    react_conversation_state = load_conversation_state(conn, session_id, None, None)
    cart_add_steps = [step for step in react_plan.steps if step.action == "cart_add"]
    if len(cart_add_steps) > 1:
        batch_payload = build_batch_cart_payload(conn, message, cart_add_steps, react_conversation_state)
        if batch_payload:
            yield sse_event(
                "workflow_status",
                {
                    "workflow": "react_transaction",
                    "step": "batch_cart_prepare",
                    "status": "needs_sku",
                    "item_count": len(batch_payload["items"]),
                },
            )
            assistant_content = batch_payload["message"]
            yield sse_event("delta", {"text": assistant_content})
            yield sse_event("batch_cart", batch_payload)
            store_assistant_message(conn, session_id, assistant_content, image_id)
            update_session_state(conn, session_id, last_query=message)
            yield sse_event("done", {"session_id": session_id})
            return
    for step in react_plan.steps:
        if step.action == "cart_add":
            parsed_turn = ParsedTurn(
                raw_message=message_with_sku_hint(message, step),
                intent_type="cart_add",
                route_hint="bounded_react",
                references=product_reference_from_step(step),
                quantity=step.quantity or 1,
                source="llm",
            )
            result = execute_bounded_turn(conn, parsed_turn, react_conversation_state)
            yield sse_event(
                "workflow_status",
                {
                    "workflow": "react_transaction",
                    "step": "cart_add",
                    "status": result.status,
                },
            )
            yield from emit_bounded_events(conn, session_id, message, image_id, result, store=True, done=False)
            if result.status != "ok":
                yield sse_event("done", {"session_id": session_id})
                return
            completed_any_step = True
            continue
        if step.action == "checkout":
            if not completed_any_step and not get_cart(conn).items:
                assistant_content = "我还不知道你想买哪一款商品。请先告诉我具体商品，或先让我推荐几款再说“第一款 42 码直接买”。"
                actions = normalize_actions(
                    conn,
                    [
                        {"type": "search_more", "label": "重新推荐几款", "product_id": None},
                        {"type": "open_cart", "label": "打开购物车", "product_id": None},
                        {"type": "search_more", "label": "我说商品名称", "product_id": None},
                    ],
                )
                yield order_status_event("failed", "缺少商品引用")
                yield sse_event("delta", {"text": assistant_content})
                if actions:
                    yield sse_event("actions", {"actions": actions})
                store_assistant_message(conn, session_id, assistant_content, image_id)
                update_session_state(conn, session_id, last_query=message, last_actions=actions or None)
                yield sse_event("done", {"session_id": session_id})
                return
            checkout_message = CHECKOUT_CONFIRM_LABEL if step.confirm_payment and is_checkout_address_confirm_message(message) else "结算"
            yield sse_event(
                "workflow_status",
                {
                    "workflow": "react_transaction",
                    "step": "checkout",
                    "status": "start",
                    "confirm_payment": step.confirm_payment,
                    "use_default_address": step.use_default_address,
                },
            )
            yield from emit_checkout_turn(conn, session_id, checkout_message, image_id)
            return
    if completed_any_step:
        yield sse_event("done", {"session_id": session_id})


def build_batch_cart_payload(conn, message: str, cart_add_steps: list[Any], conversation_state: dict[str, Any]) -> dict[str, Any] | None:
    items: list[dict[str, Any]] = []
    needs_sku = False
    seen_product_ids: set[str] = set()
    for index, step in enumerate(cart_add_steps, start=1):
        product_ids, _diagnostics = resolve_product_references(conn, product_reference_from_step(step), conversation_state)
        if not product_ids:
            return None
        product_id = product_ids[0]
        if product_id in seen_product_ids:
            continue
        seen_product_ids.add(product_id)
        product = conn.execute(
            "SELECT id, title, brand, image_path, price FROM products WHERE id = ?",
            (product_id,),
        ).fetchone()
        if not product:
            return None
        skus = fetch_cart_skus(conn, product_id)
        selected_sku = resolve_sku_from_message(message_with_sku_hint(message, step), skus)
        if len(skus) > 1 and selected_sku is None:
            needs_sku = True
        selected_sku_id = selected_sku["id"] if selected_sku else None
        items.append(
            {
                "product_id": product["id"],
                "title": product["title"],
                "brand": product["brand"],
                "image_path": product["image_path"],
                "price": float(product["price"] or 0),
                "quantity": step.quantity or 1,
                "position": index,
                "status": "selected" if selected_sku_id else "needs_sku",
                "selected_sku_id": selected_sku_id,
                "skus": build_batch_cart_sku_options(skus),
            }
        )
    if not needs_sku:
        return None
    return {
        "batch_id": f"batch_{uuid.uuid4().hex[:10]}",
        "title": "批量加入购物车",
        "message": "这些商品需要先确认规格，选好后我会一次性加入购物车。",
        "items": items,
    }


def build_batch_cart_sku_options(skus: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "sku_id": sku["id"],
            "sku_name": sku["sku_name"],
            "label": compact_sku_label(sku, skus),
            "price": float(sku.get("price") or 0),
            "stock": int(sku.get("stock") or 0),
        }
        for sku in skus
    ]


def is_batch_cart_confirm_message(message: str) -> bool:
    return message.strip().startswith(BATCH_CART_CONFIRM_PREFIX)


def batch_cart_confirm_display_text(message: str) -> str | None:
    if not is_batch_cart_confirm_message(message):
        return None
    return "确认加入购物车"


def parse_batch_cart_confirm_payload(message: str) -> dict[str, Any]:
    raw = message.strip()[len(BATCH_CART_CONFIRM_PREFIX) :].strip()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("invalid batch cart payload")
    return data


def emit_batch_cart_confirm_turn(conn, session_id: str, message: str, image_id: str | None) -> Iterable[str]:
    try:
        payload = parse_batch_cart_confirm_payload(message)
        selections = validate_batch_cart_selections(conn, payload)
    except (json.JSONDecodeError, ValueError) as exc:
        assistant_content = f"批量加入购物车失败：{exc}"
        yield sse_event("delta", {"text": assistant_content})
        store_assistant_message(conn, session_id, assistant_content, image_id)
        update_session_state(conn, session_id, last_query="确认加入购物车")
        yield sse_event("done", {"session_id": session_id})
        return

    added: list[dict[str, Any]] = []
    for product_id, sku_id, quantity in selections:
        for _ in range(quantity):
            cart_product = add_product_to_cart(conn, product_id, sku_id)
            if cart_product:
                added.append(cart_product)

    cart_payload = get_cart(conn).model_dump(mode="json")
    title_text = "、".join(item["title"] for item in added[:3])
    suffix = f" 等 {len(added)} 件商品" if len(added) > 3 else ""
    assistant_content = f"已把 {title_text}{suffix} 加入购物车。购物车详情如下。"
    actions = normalize_actions(conn, [{"type": "open_cart", "label": "打开购物车", "product_id": None}])
    yield sse_event("delta", {"text": assistant_content})
    yield sse_event("cart", cart_payload)
    yield sse_event("actions", {"actions": actions})
    store_assistant_message(conn, session_id, assistant_content, image_id)
    update_session_state(
        conn,
        session_id,
        last_query="确认加入购物车",
        current_product_id=added[0]["id"] if added else None,
        last_actions=actions,
    )
    yield sse_event("done", {"session_id": session_id})


def validate_batch_cart_selections(conn, payload: dict[str, Any]) -> list[tuple[str, str, int]]:
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("缺少待加入商品")
    selections: list[tuple[str, str, int]] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("商品选择格式不正确")
        product_id = str(item.get("product_id") or "").strip()
        sku_id = str(item.get("sku_id") or "").strip()
        quantity = int(item.get("quantity") or 1)
        if not product_id or not sku_id:
            raise ValueError("还有商品没有选择规格")
        if quantity < 1:
            raise ValueError("商品数量不正确")
        row = conn.execute(
            """
            SELECT s.id
            FROM product_skus s
            JOIN products p ON p.id = s.product_id
            WHERE p.id = ? AND s.id = ? AND s.stock >= ?
            """,
            (product_id, sku_id, quantity),
        ).fetchone()
        if not row:
            raise ValueError("有商品规格不可购买，请重新选择")
        selections.append((product_id, sku_id, quantity))
    return selections


def emit_bundle_recommendation_turn(
    conn,
    session_id: str,
    message: str,
    image_id: str | None,
    turn_plan,
) -> Iterable[str]:
    result = retrieve_bundle_recommendations(
        conn,
        message,
        top_k_per_slot=1,
        bundle_slots=turn_plan.parsed_turn.bundle_slots if turn_plan else None,
    )
    yield sse_event(
        "retrieval_status",
        {
            "final_user_query": message,
            "parsed_filters": {},
            "pipeline": [
                "scene_planner",
                "category_planner",
                "parallel_retrieve",
                "slot_verifier",
                "bundle_writer",
            ],
            "sources": ["dense_milvus", "bm25", "keyword"],
            "fusion": "slot_rrf",
            "vector_backend": "milvus",
            "graph_backend": turn_plan.graph_backend,
            "turn": turn_plan.status_payload(),
            "bundle": result.diagnostics,
        },
    )
    grounded_products = build_grounded_products(conn, result.products)
    visible_products = visible_chat_products(grounded_products)
    enrich_product_presentations(message, visible_products)
    if visible_products:
        yield sse_event("products", {"products": visible_products})
    answer = build_bundle_answer(result)
    yield sse_event("llm_status", {"mode": "bundle_template", "reason": "multi_slot_grounded"})
    yield sse_event("delta", {"text": answer})
    actions = build_actions(conn, visible_products, message, {})
    if actions:
        yield sse_event("actions", {"actions": actions})
    assistant_content = append_recommendation_marker(answer, visible_products)
    store_assistant_message(conn, session_id, assistant_content, image_id)
    update_session_state(
        conn,
        session_id,
        last_query=message,
        last_recommended_product_ids=[product["id"] for product in visible_products],
        current_product_id=visible_products[0]["id"] if visible_products else None,
        last_actions=actions or None,
        parsed_turn=turn_plan.parsed_turn if turn_plan else None,
        visible_products=grounded_products,
    )
    yield sse_event("done", {"session_id": session_id})


def emit_checkout_turn(
    conn,
    session_id: str,
    message: str,
    image_id: str | None,
) -> Iterable[str]:
    if is_checkout_cancel_intent(message):
        assistant_content = "已取消本次下单，购物车商品会继续保留。需要时可以再次回复“结算”。"
        yield order_status_event("cancelled", "已取消下单")
        yield sse_event("delta", {"text": assistant_content})
        yield sse_event("cart", get_cart(conn).model_dump(mode="json"))
        store_assistant_message(conn, session_id, assistant_content, image_id)
        update_session_state(conn, session_id, last_query=message, last_actions=None)
        yield sse_event("done", {"session_id": session_id})
        return

    if is_address_change_intent(message):
        assistant_content = "可以先到地址管理新增或修改收货地址。地址确认后，回到这里回复“结算”或“确认下单”，我会重新汇总订单。"
        yield order_status_event("need_address", "待确认收货地址")
        yield sse_event("delta", {"text": assistant_content})
        yield sse_event("actions", {"actions": [{"type": "search_more", "label": "修改地址", "product_id": None}]})
        store_assistant_message(conn, session_id, assistant_content, image_id)
        update_session_state(
            conn,
            session_id,
            last_query=message,
            last_actions=[{"type": "search_more", "label": "修改地址", "product_id": None}],
        )
        yield sse_event("done", {"session_id": session_id})
        return

    yield order_status_event("checking_cart", "正在读取购物车")
    cart = get_cart(conn).model_dump(mode="json")
    selected_items = [item for item in cart.get("items", []) if item.get("selected", True)]
    if not cart.get("items"):
        assistant_content = "购物车现在是空的，先加入商品后我再帮你确认订单。"
        yield order_status_event("failed", "购物车为空")
        yield sse_event("delta", {"text": assistant_content})
        store_assistant_message(conn, session_id, assistant_content, image_id)
        update_session_state(conn, session_id, last_query=message)
        yield sse_event("done", {"session_id": session_id})
        return
    if not selected_items:
        assistant_content = "购物车里没有选中的商品，请先选择要结算的商品。"
        yield order_status_event("failed", "没有选中商品")
        yield sse_event("delta", {"text": assistant_content})
        yield sse_event("cart", cart)
        store_assistant_message(conn, session_id, assistant_content, image_id)
        update_session_state(conn, session_id, last_query=message)
        yield sse_event("done", {"session_id": session_id})
        return

    address = load_default_address(conn)
    if is_checkout_confirm_intent(message):
        if not address:
            assistant_content = "下单前需要先补充收货地址。请到地址管理新增地址后，再回复“确认下单”。"
            actions = [{"type": "search_more", "label": "修改地址", "product_id": None}]
            yield order_status_event("need_address", "待确认收货地址")
            yield sse_event("delta", {"text": assistant_content})
            yield sse_event("actions", {"actions": actions})
            store_assistant_message(conn, session_id, assistant_content, image_id)
            update_session_state(conn, session_id, last_query=message, last_actions=actions)
            yield sse_event("done", {"session_id": session_id})
            return
        if has_valid_checkout_confirmation(conn, session_id, cart, address):
            yield order_status_event("creating_order", "正在创建订单")
            time.sleep(0.2)
            try:
                order = create_paid_order_from_cart(conn, address)
            except ValueError as exc:
                assistant_content = str(exc)
                actions = normalize_actions(conn, build_checkout_failure_actions(assistant_content))
                yield order_status_event("failed", "下单失败")
                yield sse_event("delta", {"text": assistant_content})
                yield sse_event("cart", get_cart(conn).model_dump(mode="json"))
                if actions:
                    yield sse_event("actions", {"actions": actions})
                store_assistant_message(conn, session_id, assistant_content, image_id)
                update_session_state(conn, session_id, last_query=message, last_actions=actions or None)
                yield sse_event("done", {"session_id": session_id})
                return
            yield order_status_event("paying", "正在模拟支付")
            time.sleep(0.2)
            assistant_content = build_order_success_text(order)
            yield order_status_event(
                "paid",
                f"支付成功，订单号 {order['order_id']}",
                order_id=order["order_id"],
                payment_id=order["payment_id"],
            )
            yield sse_event("order_success", build_order_success_payload(order))
            yield sse_event("delta", {"text": assistant_content})
            yield sse_event("cart", get_cart(conn).model_dump(mode="json"))
            store_assistant_message(conn, session_id, assistant_content, image_id)
            update_session_state(conn, session_id, last_query=message, last_actions=[])
            yield sse_event("done", {"session_id": session_id})
            return

    actions = build_checkout_confirmation_actions(conn, cart, address)
    assistant_content = build_checkout_confirmation_text(cart, address)
    confirmation_payload = build_checkout_confirmation_payload(cart, address, actions)
    yield order_status_event(
        "awaiting_confirmation" if address else "need_address",
        "待确认订单" if address else "待确认收货地址",
    )
    yield sse_event("delta", {"text": assistant_content})
    yield sse_event("checkout_confirmation", confirmation_payload)
    yield sse_event("cart", cart)
    yield sse_event("actions", {"actions": actions})
    store_assistant_message(conn, session_id, assistant_content, image_id)
    update_session_state(conn, session_id, last_query=message, last_actions=actions)
    yield sse_event("done", {"session_id": session_id})


def emit_order_cancel_turn(
    conn,
    session_id: str,
    message: str,
    image_id: str | None,
) -> Iterable[str]:
    order = resolve_cancel_order(conn, message)
    if not order:
        assistant_content = "没有找到可取消的订单。你可以到“我的订单”里查看当前订单状态。"
        yield order_status_event("failed", "没有可取消订单")
        yield sse_event("delta", {"text": assistant_content})
        store_assistant_message(conn, session_id, assistant_content, image_id)
        update_session_state(conn, session_id, last_query=message)
        yield sse_event("done", {"session_id": session_id})
        return
    if order["status"] == "cancelled":
        assistant_content = f"订单 {order['id']} 已经是已取消状态。"
        yield order_status_event("cancelled", "订单已取消", order_id=order["id"])
        yield sse_event("delta", {"text": assistant_content})
        store_assistant_message(conn, session_id, assistant_content, image_id)
        update_session_state(conn, session_id, last_query=message)
        yield sse_event("done", {"session_id": session_id})
        return
    if order["status"] == "paid":
        restore_order_stock(conn, order["id"])
    conn.execute("UPDATE orders SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", ("cancelled", order["id"]))
    assistant_content = f"已取消订单 {order['id']}。"
    if order["status"] == "paid":
        assistant_content += " 已同步恢复对应商品库存。"
    yield order_status_event("cancelled", "订单已取消", order_id=order["id"])
    yield sse_event("delta", {"text": assistant_content})
    store_assistant_message(conn, session_id, assistant_content, image_id)
    update_session_state(conn, session_id, last_query=message)
    yield sse_event("done", {"session_id": session_id})


def ensure_session(conn, session_id: str) -> None:
    conn.execute("INSERT OR IGNORE INTO chat_sessions(id) VALUES (?)", (session_id,))


def load_known_brands(conn) -> list[str]:
    return [row["brand"] for row in conn.execute("SELECT DISTINCT brand FROM products").fetchall() if row["brand"]]


def build_final_user_query(
    conn,
    message: str,
    image_query: str | None,
    current_product_id: str | None,
    session_id: str,
) -> str:
    # 图片线路以 VLM 结构化结果生成的 image_query 为主。
    # message 只保留用户真实补充约束，避免 MLKit 原始标签和上一轮商品上下文污染检索。
    if image_query and image_query.strip():
        parts = [clean_user_text_for_image_query(message), image_query.strip()]
        return " ".join(part for part in parts if part)

    # 文本线路保留会话上下文能力：追问“这款/刚才/类似”时才补当前商品信息。
    parts = [message.strip()]
    if should_merge_last_query(message):
        row = conn.execute("SELECT last_query FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
        last_query = row["last_query"] if row else None
        if last_query and last_query not in message:
            parts.append(str(last_query))
    anchor_product_id = current_product_id
    if not anchor_product_id and any(word in message for word in ["这个", "这款", "刚刚", "刚才", "类似", "同款"]):
        row = conn.execute("SELECT current_product_id FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
        anchor_product_id = row["current_product_id"] if row else None
    if anchor_product_id and product_exists(conn, anchor_product_id):
        product = conn.execute(
            "SELECT title, brand, category, subcategory, marketing_description FROM products WHERE id = ?",
            (anchor_product_id,),
        ).fetchone()
        if product:
            parts.extend(
                [
                    product["title"],
                    product["brand"],
                    product["category"],
                    product["subcategory"],
                    str(product["marketing_description"])[:160],
                ]
            )
    return " ".join(part for part in parts if part)


def clean_user_text_for_image_query(message: str) -> str:
    # Android 端 MLKit hint 只是弱线索，不能直接进入最终检索 query。
    # 这里截掉“图片识别标签/推断品类”后的原始标签，只保留用户手输的预算、颜色、场景等约束。
    cleaned = " ".join((message or "").strip().split())
    if not cleaned:
        return ""

    marker_positions = [cleaned.find(marker) for marker in MLKIT_HINT_MARKERS if cleaned.find(marker) >= 0]
    if marker_positions:
        cleaned = cleaned[: min(marker_positions)]

    for fragment in GENERIC_IMAGE_HINT_FRAGMENTS:
        cleaned = cleaned.replace(fragment, " ")
    cleaned = re.sub(r"[，,。.;；:：]+", " ", cleaned)
    cleaned = " ".join(cleaned.split())
    if cleaned in LOW_SIGNAL_IMAGE_TERMS:
        return ""
    return cleaned


def should_merge_last_query(message: str) -> bool:
    text = message.strip()
    if not text:
        return False
    has_catalog_term = any(
        term in text
        for term in (
            "手机",
            "耳机",
            "电脑",
            "笔记本",
            "篮球鞋",
            "跑鞋",
            "防晒",
            "背包",
            "行李箱",
        )
    )
    refinement_terms = (
        "拍照",
        "续航",
        "性能",
        "性价比",
        "预算",
        "优先",
        "便宜",
        "贵点",
        "不要",
        "排除",
        "降噪",
        "通勤",
        "实战",
    )
    return not has_catalog_term and any(term in text for term in refinement_terms)


def product_exists(conn, product_id: str | None) -> bool:
    if not product_id:
        return False
    row = conn.execute("SELECT id FROM products WHERE id = ?", (product_id,)).fetchone()
    return row is not None


def normalize_actions(conn, actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for action in actions:
        action_type = str(action.get("type", "")).strip()
        if action_type not in ALLOWED_ACTION_TYPES:
            continue
        product_id = action.get("product_id")
        if product_id is not None:
            product_id = str(product_id).strip() or None
        if action_type in PRODUCT_ACTION_TYPES and not product_exists(conn, product_id):
            continue
        label = str(action.get("label") or ACTION_LABELS[action_type])
        normalized_action = {"type": action_type, "label": label, "product_id": product_id}
        if CHECKOUT_SIGNATURE_FIELD in action:
            normalized_action[CHECKOUT_SIGNATURE_FIELD] = str(action[CHECKOUT_SIGNATURE_FIELD])
        normalized.append(normalized_action)
    return normalized


def build_actions(
    conn,
    products: list[dict[str, Any]],
    query: str = "",
    parsed_filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    parsed_filters = parsed_filters or {}
    if not products:
        labels = build_empty_result_follow_up_questions(query, parsed_filters)
        return normalize_actions(
            conn,
            [{"type": "search_more", "label": label, "product_id": None} for label in labels],
        )
    actions = [
        {"type": "search_more", "label": label, "product_id": None}
        for label in build_follow_up_questions(products, query, parsed_filters)
    ]
    return normalize_actions(conn, actions)


def build_clarification_actions(conn, question: str) -> list[dict[str, Any]]:
    if "具体对什么过敏" in question:
        labels = [
            "坚果/花生过敏",
            "乳制品/鸡蛋过敏",
            "小麦/海鲜过敏",
        ]
    elif "过敏" in question or "忌口" in question:
        labels = [
            "没有过敏忌口",
            "给小孩/老人吃",
            "低糖低盐优先",
        ]
    elif "肤质" in question or "酒精" in question or "香精" in question:
        labels = [
            "敏感肌，避开酒精香精",
            "干皮，保湿优先",
            "油皮，清爽控油",
        ]
    elif "脚宽" in question or "膝盖" in question or "磨脚" in question:
        labels = [
            "跑步用，脚宽",
            "通勤穿，不磨脚",
            "篮球实战，膝盖易不适",
        ]
    elif "长时间佩戴" in question or "孩子使用" in question or "护眼" in question:
        labels = [
            "长时间佩戴要舒适",
            "给孩子用，护眼优先",
            "降噪续航优先",
        ]
    elif "宠物" in question or "肠胃敏感" in question:
        labels = [
            "猫咪，肠胃敏感",
            "狗狗，日常使用",
            "避开易过敏成分",
        ]
    elif "哪类带" in question:
        labels = build_attribute_category_labels(question)
    elif "换一批推荐" in question and "删除购物车" in question:
        labels = [
            "换一批推荐",
            "删除购物车商品",
            "加入购物车",
        ]
    elif "拍照" in question and "续航" in question:
        labels = [
            "拍照优先，预算4000",
            "续航优先，预算3000",
            "性价比优先，预算2500",
        ]
    elif "降噪" in question and "音质" in question:
        labels = [
            "降噪优先，预算500",
            "音质优先，预算800",
            "佩戴舒适，预算300",
        ]
    elif "实战" in question or "跑步" in question:
        labels = [
            "实战优先，预算500",
            "通勤穿搭，预算300",
            "跑步缓震，预算600",
        ]
    else:
        labels = ["预算低一点", "品牌不限", "更看重性价比"]
    return normalize_actions(
        conn,
        [{"type": "search_more", "label": label, "product_id": None} for label in labels],
    )


def build_attribute_category_labels(question: str) -> list[str]:
    if "蓝牙" in question:
        return ["找蓝牙耳机", "找蓝牙音箱", "找蓝牙键盘"]
    if "防水" in question:
        return ["找防水背包", "找防水鞋", "找防水外套"]
    if "轻薄" in question:
        return ["找轻薄笔记本", "找轻薄外套", "找轻薄背包"]
    if "降噪" in question:
        return ["找降噪耳机", "找降噪耳塞", "找通勤耳机"]
    if "续航" in question:
        return ["找长续航手机", "找长续航耳机", "找长续航笔记本"]
    return ["找耳机", "找背包", "找鞋服"]


def build_reference_clarification_actions(conn, response_text: str) -> list[dict[str, Any]]:
    if "购物车" in response_text:
        labels = ["打开购物车", "删除购物车第一项", "清空购物车"]
        raw_actions = [
            {"type": "open_cart", "label": labels[0], "product_id": None},
            {"type": "search_more", "label": labels[1], "product_id": None},
            {"type": "search_more", "label": labels[2], "product_id": None},
        ]
    else:
        raw_actions = [
            {"type": "search_more", "label": "重新推荐几款", "product_id": None},
            {"type": "open_cart", "label": "打开购物车", "product_id": None},
            {"type": "search_more", "label": "我说商品名称", "product_id": None},
        ]
    return normalize_actions(conn, raw_actions)


def build_empty_result_follow_up_questions(
    query: str,
    parsed_filters: dict[str, Any],
) -> list[str]:
    max_price = parsed_filters.get("max_price")
    lower_query = query.lower()
    if any(word in query for word in ("篮球鞋", "球鞋", "篮球")) or "basketball" in lower_query:
        budget = int(max_price * 1.2) if isinstance(max_price, (int, float)) and max_price > 100 else 500
        return [
            f"放宽到{budget}以内再找篮球鞋",
            "找几款非耐克篮球鞋",
            "适合外场实战的有哪些",
        ]
    if any(word in query for word in ("跑鞋", "运动鞋", "鞋")) or "shoe" in lower_query:
        budget = int(max_price * 1.2) if isinstance(max_price, (int, float)) and max_price > 100 else 300
        return [
            f"放宽到{budget}以内再找鞋",
            "通勤和运动两用的有哪些",
            "找几款性价比高的品牌",
        ]
    if any(word in query for word in ("耳机", "蓝牙", "降噪")) or "ear" in lower_query:
        budget = int(max_price * 1.2) if isinstance(max_price, (int, float)) and max_price > 100 else 300
        return [
            f"放宽到{budget}以内再找耳机",
            "优先降噪的耳机有哪些",
            "适合通勤佩戴的有哪些",
        ]
    return [
        "放宽预算范围再找找",
        "换个品牌看看",
        "描述一下使用场景",
    ]


def build_follow_up_questions(
    products: list[dict[str, Any]],
    query: str,
    parsed_filters: dict[str, Any],
) -> list[str]:
    first = products[0]
    category_text = str(first.get("subcategory") or first.get("category") or "商品")
    brands = [str(product.get("brand") or "").strip() for product in products if product.get("brand")]
    primary_brand = brands[0] if brands else ""
    excluded_brands = parsed_filters.get("excluded_brands") or []
    max_price = parsed_filters.get("max_price")
    lower_query = query.lower()

    if any(word in query for word in ("篮球鞋", "球鞋", "篮球")) or "basketball" in lower_query:
        budget = int(max_price * 0.8) if isinstance(max_price, (int, float)) and max_price > 100 else 500
        return [
            f"有没有{budget}以内的篮球鞋推荐",
            "球鞋搭配什么裤子好看",
            "帮我找耐克平替款球鞋" if not excluded_brands else "再推荐几款非耐克球鞋",
        ]

    if any(word in query for word in ("跑鞋", "运动鞋", "鞋")) or "shoe" in lower_query:
        budget = int(max_price * 0.8) if isinstance(max_price, (int, float)) and max_price > 100 else 300
        return [
            f"有没有{budget}以内的{category_text}推荐",
            "适合通勤和运动两用的有哪些",
            f"除了{primary_brand}还有什么品牌" if primary_brand else "帮我找性价比更高的款",
        ]

    if any(word in query for word in ("耳机", "蓝牙", "降噪")) or "ear" in lower_query:
        budget = int(max_price * 0.8) if isinstance(max_price, (int, float)) and max_price > 100 else 300
        return [
            f"有没有{budget}以内的蓝牙耳机推荐",
            "降噪和续航哪个更重要",
            "帮我找适合通勤的耳机",
        ]

    if max_price:
        return [
            f"有没有更便宜的{category_text}",
            f"{category_text}怎么选更划算",
            f"除了{primary_brand}还有什么选择" if primary_brand else f"有没有更适合预算的{category_text}",
        ]

    return [
        f"{category_text}怎么选更合适",
        f"有没有性价比更高的{category_text}",
        f"除了{primary_brand}还有什么选择" if primary_brand else f"还有哪些{category_text}值得看",
    ]


def build_grounded_products(conn, products: list[ProductCard]) -> list[dict[str, Any]]:
    grounded: list[dict[str, Any]] = []
    for product in products:
        data = product.model_dump()
        row = conn.execute(
            """
            SELECT
                COUNT(s.id) AS sku_count,
                COALESCE(SUM(s.stock), 0) AS stock,
                GROUP_CONCAT(s.sku_name, '；') AS sku_summary,
                p.marketing_description AS marketing_description
            FROM products p
            LEFT JOIN product_skus s ON s.product_id = p.id
            WHERE p.id = ?
            GROUP BY p.id
            """,
            (product.id,),
        ).fetchone()
        if row:
            data.update(
                {
                    "marketing_description": row["marketing_description"],
                    "sku_count": int(row["sku_count"] or 0),
                    "stock": int(row["stock"] or 0),
                    "sku_summary": row["sku_summary"],
                }
            )
        data["faq_summary"] = [
            f"{item['question']}：{item['answer']}"
            for item in conn.execute(
                "SELECT question, answer FROM product_faqs WHERE product_id = ? LIMIT 2",
                (product.id,),
            ).fetchall()
        ]
        data["review_summary"] = [
            item["content"]
            for item in conn.execute(
                "SELECT content FROM product_reviews WHERE product_id = ? ORDER BY rating DESC LIMIT 2",
                (product.id,),
            ).fetchall()
        ]
        data["review_count"] = int(
            conn.execute("SELECT COUNT(*) AS total FROM product_reviews WHERE product_id = ?", (product.id,)).fetchone()[
                "total"
            ]
        )
        data["faq_count"] = int(
            conn.execute("SELECT COUNT(*) AS total FROM product_faqs WHERE product_id = ?", (product.id,)).fetchone()[
                "total"
            ]
        )
        grounded.append(data)
    return grounded


def enrich_product_presentations(user_message: str, products: list[dict[str, Any]]) -> None:
    if not products:
        return
    try:
        presentations = run_async_blocking(generate_product_presentations(user_message, products))
    except Exception as exc:
        logger.info("presentation_generation_failed=%s", exc.__class__.__name__)
        presentations = {}
    for index, product in enumerate(products):
        generated = presentations.get(str(product.get("id"))) if presentations else None
        fallback_title, fallback_reason = fallback_product_presentation(user_message, product, index)
        product["recommendation_title"] = fallback_title
        product["reason"] = (generated or {}).get("reason") or user_facing_reason(product.get("reason")) or fallback_reason


def fallback_product_presentation(user_message: str, product: dict[str, Any], index: int) -> tuple[str, str]:
    title = str(product.get("title") or "")
    category = str(product.get("subcategory") or product.get("category") or "商品")
    reason = str(product.get("reason") or "")
    price = float(product.get("price") or 0)
    if "预算" in reason or "放宽" in reason:
        return "预算备选", f"这款{category}是放宽预算后的相近选择，适合作为对比备选。"
    if any(term in user_message + title + reason for term in ("拍照", "影像", "摄影")) and "手机" in title:
        return "拍照优先", "更偏拍照和影像体验，适合把相机表现放在第一位的需求。"
    if any(term in user_message + title + reason for term in ("续航", "长续航")):
        return "长续航款", "更偏长时间稳定使用，适合通勤、出差或重度使用。"
    if any(term in user_message + title + reason for term in ("性能", "游戏")):
        return "性能配置", "更适合看重流畅度、配置和游戏表现的需求。"
    if any(term in user_message + title + reason for term in ("降噪", "通勤")) and "耳机" in title:
        return "通勤降噪", "更适合通勤、办公和嘈杂环境，重点看降噪和佩戴体验。"
    if any(term in user_message + title + reason for term in ("防晒", "海边", "三亚")):
        return "防晒防护", "适合户外或海边场景，重点看防护、轻便和便携性。"
    if any(term in title + category for term in ("篮球鞋", "球鞋")):
        return "实战支撑", "更适合运动和日常穿搭，重点看支撑、缓震和耐磨。"
    if price <= 300:
        return "高性价比", f"这款{category}价格更友好，适合作为预算有限时的实用选择。"
    return ("综合匹配" if index == 0 else "对比备选", f"这款{category}匹配当前需求，可结合价格、品牌和评分一起对比。")


def user_facing_reason(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    technical_tokens = ("RRF", "BM25", "retrieval", "Matched by", "score", "dense", "keyword")
    if any(token.lower() in text.lower() for token in technical_tokens):
        return None
    return text


def load_faq_context(conn, product_ids: list[str]) -> list[dict[str, str]]:
    if not product_ids:
        return []
    placeholders = ",".join("?" for _ in product_ids)
    rows = conn.execute(
        f"""
        SELECT product_id, question, answer
        FROM product_faqs
        WHERE product_id IN ({placeholders})
        LIMIT 12
        """,
        product_ids,
    ).fetchall()
    return [
        {"product_id": row["product_id"], "question": row["question"], "answer": row["answer"]}
        for row in rows
    ]


def load_chat_history(conn, session_id: str, limit: int = 6) -> list[dict[str, str]]:
    rows = conn.execute(
        """
        SELECT role, content
        FROM chat_messages
        WHERE session_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (session_id, limit),
    ).fetchall()
    return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]


def load_conversation_state(
    conn,
    session_id: str,
    current_product_id: str | None,
    cart_context: list[dict] | None,
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT last_query, last_recommended_product_ids, current_product_id, structured_state_json
        FROM chat_sessions
        WHERE id = ?
        """,
        (session_id,),
    ).fetchone()
    cart_items = cart_context or [
        item.model_dump(mode="json")
        for item in get_cart(conn).items
    ]
    structured_memory = parse_structured_memory(row["structured_state_json"] if row else None)
    return {
        "last_query": row["last_query"] if row else None,
        "last_recommended_product_ids": parse_product_id_list(row["last_recommended_product_ids"] if row else None),
        "current_product_id": current_product_id or (row["current_product_id"] if row else None),
        "cart_context": cart_items,
        STRUCTURED_MEMORY_KEY: structured_memory,
        "structured_state": structured_memory,
    }


def build_waiting_deltas(
    message: str,
    parsed_filters: dict[str, Any],
    image_id: str | None,
    has_chat_history: bool,
    skip_generic_intro: bool = False,
) -> list[str]:
    texts: list[str] = []
    lower_message = message.lower()
    excluded_brands = parsed_filters.get("excluded_brands") or []
    excluded_terms = parsed_filters.get("excluded_terms") or []
    has_exclusions = bool(excluded_brands or excluded_terms) or any(
        word in message for word in ("不要", "除了", "排除", "不含", "别要")
    )
    has_price = any(parsed_filters.get(key) is not None for key in ("min_price", "max_price"))
    wants_compare = any(word in message for word in ("对比", "比较", "哪个好", "哪款好")) or "compare" in lower_message

    if skip_generic_intro:
        if image_id:
            texts.append("我会结合图片线索一起匹配。")
        elif has_chat_history and any(word in message for word in ("再", "换", "继续", "还有", "便宜", "贵点")):
            texts.append("我会基于刚才的条件继续筛。")
        elif wants_compare:
            texts.append("我会重点整理关键差异。")
        elif has_exclusions:
            texts.append("我会先排除你不想要的条件。")
        elif has_price:
            texts.append("我会控制在预算范围内。")
    elif image_id:
        texts.append("我先根据图片线索匹配相似商品。")
    elif has_chat_history and any(word in message for word in ("再", "换", "继续", "还有", "便宜", "贵点")):
        texts.append("明白，我基于刚才的条件继续筛。")
    elif wants_compare:
        texts.append("我先把关键差异整理出来。")
    elif has_exclusions:
        texts.append("好的，我会先排除你不想要的条件。")
    elif has_price:
        texts.append("收到，我会控制在预算范围内。")
    else:
        texts.append("好的，我先帮你筛一下符合条件的商品。")

    if not skip_generic_intro and wants_compare:
        texts.append("正在对比价格、评分、库存和适合场景。")
    elif not skip_generic_intro and has_exclusions:
        texts.append("正在匹配剩余品牌、价格和库存。")
    elif not skip_generic_intro:
        texts.append("正在匹配商品、价格、评分和库存。")

    texts.append("我会优先展示最符合条件的几款。")
    return texts


def is_checkout_intent(message: str) -> bool:
    text = message.strip()
    return is_checkout_cancel_intent(text) or is_address_change_intent(text) or is_checkout_confirm_intent(text) or any(
        word in text for word in ("结算", "下单", "提交订单", "确认订单", "去支付", "支付")
    )


def is_cart_add_checkout_intent(message: str) -> bool:
    text = message.strip()
    has_add = any(word in text for word in ("加入购物车", "加购物车", "加购", "放购物车", "加入"))
    has_checkout = any(word in text for word in ("结算", "下单", "提交订单", "确认订单", "去支付", "支付"))
    return has_add and has_checkout


def pending_cart_add_checkout_message(message: str, chat_history: list[dict[str, str]]) -> str | None:
    if not is_sku_selection_message(message):
        return None
    for item in reversed(chat_history[-4:]):
        if item.get("role") != "user":
            continue
        content = str(item.get("content") or "")
        if is_cart_add_checkout_intent(content) or is_pending_direct_buy_intent(content):
            return content
        break
    return None


def is_pending_direct_buy_intent(message: str) -> bool:
    text = message.strip()
    has_reference = any(term in text for term in ("这双", "这款", "这个", "刚才", "刚刚", "第一", "第二", "第三"))
    return has_reference and has_checkout_signal(text)


def should_auto_confirm_checkout(message: str) -> bool:
    text = message.strip()
    return any(word in text for word in ("直接下单", "下单吧", "默认地址", "地址用默认", "用默认地址", "确认下单", "去支付"))


def is_order_cancel_intent(message: str) -> bool:
    text = message.strip()
    return "订单" in text and any(word in text for word in ("取消", "撤销", "关闭", "退掉", "不要了"))


def is_checkout_cancel_intent(message: str) -> bool:
    text = message.strip()
    return any(word in text for word in ("取消下单", "取消支付", "暂不下单", "先不买", "不下单"))


def is_checkout_confirm_intent(message: str) -> bool:
    text = message.strip()
    return any(
        word in text
        for word in ("确认下单", "确认下单并支付", "提交订单", "确认支付", "去支付", "直接下单", "下单吧", "默认地址", "地址用默认", "用默认地址")
    )


def is_checkout_address_confirm_message(message: str) -> bool:
    text = message.strip()
    return any(word in text for word in ("确认下单", "确认下单并支付", "提交订单", "确认支付"))


def is_address_change_intent(message: str) -> bool:
    text = message.strip()
    return "地址" in text and any(word in text for word in ("修改", "更换", "换", "新增", "添加"))


def load_default_address(conn) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM addresses ORDER BY is_default DESC, created_at DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def resolve_cancel_order(conn, message: str) -> dict[str, Any] | None:
    match = re.search(r"ord_[0-9a-fA-F]{10}", message)
    if match:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (match.group(0),)).fetchone()
        return dict(row) if row else None
    row = conn.execute(
        """
        SELECT *
        FROM orders
        WHERE status IN ('pending_payment', 'paid')
        ORDER BY created_at DESC
        LIMIT 1
        """
    ).fetchone()
    return dict(row) if row else None


def restore_order_stock(conn, order_id: str) -> None:
    rows = conn.execute("SELECT sku_id, quantity FROM order_items WHERE order_id = ?", (order_id,)).fetchall()
    for row in rows:
        if not row["sku_id"]:
            continue
        conn.execute(
            "UPDATE product_skus SET stock = stock + ? WHERE id = ?",
            (int(row["quantity"]), row["sku_id"]),
        )


def build_checkout_confirmation_text(cart: dict[str, Any], address: dict[str, Any] | None) -> str:
    if address:
        return "我已整理好订单确认卡。请重点核对收货人、收货地址、商品数量和应付金额，确认无误后再继续支付。"
    return "下单前需要先补充收货地址。地址确认后，我再帮你继续核对订单。"


def build_checkout_confirmation_payload(
    cart: dict[str, Any],
    address: dict[str, Any] | None,
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    selected_items = [item for item in cart.get("items", []) if item.get("selected", True)]
    product_total = round(
        sum(float(item.get("price") or 0) * int(item.get("quantity") or 1) for item in selected_items),
        2,
    )
    payable_amount = round(float(cart.get("total_amount") or product_total), 2)
    item_count = sum(int(item.get("quantity") or 0) for item in selected_items)
    high_value = payable_amount > HIGH_VALUE_ORDER_THRESHOLD or any(
        float(item.get("price") or 0) >= HIGH_VALUE_ORDER_THRESHOLD
        or float(item.get("price") or 0) * int(item.get("quantity") or 1) >= HIGH_VALUE_ORDER_THRESHOLD
        for item in selected_items
    )

    items: list[dict[str, Any]] = []
    for item in selected_items:
        price = float(item.get("price") or 0)
        quantity = int(item.get("quantity") or 1)
        items.append(
            {
                "id": item.get("id"),
                "product_id": item.get("product_id"),
                "sku_id": item.get("sku_id"),
                "title": item.get("title") or "商品",
                "brand": item.get("brand") or "",
                "image_path": item.get("image_path") or "",
                "sku_name": item.get("sku_name") or "默认规格",
                "price": round(price, 2),
                "quantity": quantity,
                "line_total": round(price * quantity, 2),
            }
        )

    full_address = (
        f"{address['province']}{address['city']}{address['district']}{address['detail']}"
        if address
        else ""
    )
    preview_notice = (
        f"当前仅展示前 {CHECKOUT_DETAIL_PREVIEW_LIMIT} 件，共 {len(items)} 件商品"
        if len(items) > CHECKOUT_DETAIL_PREVIEW_LIMIT
        else None
    )

    payload: dict[str, Any] = {
        "title": "确认订单",
        "status_label": "待确认订单" if address else "待确认收货地址",
        "receiver_name": address["receiver_name"] if address else "待补充",
        "receiver_phone": address["phone"] if address else "",
        "address": full_address if address else "还没有默认收货地址",
        "item_count": item_count,
        "line_item_count": len(items),
        "product_total": product_total,
        "payable_amount": payable_amount,
        "shown_limit": CHECKOUT_DETAIL_PREVIEW_LIMIT,
        "preview_notice": preview_notice,
        "items": items,
        "actions": actions,
        "requires_second_confirm": high_value,
        "risk_message": "订单金额较高，请再次核对商品、数量和收货地址后再支付。" if high_value else None,
    }
    return payload


def build_checkout_confirmation_actions(
    conn,
    cart: dict[str, Any],
    address: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    raw_actions = [
        {"type": "open_cart", "label": "修改商品", "product_id": None},
        {"type": "search_more", "label": "修改地址", "product_id": None},
    ]
    if address:
        raw_actions.append(
            {
                "type": "search_more",
                "label": CHECKOUT_CONFIRM_LABEL,
                "product_id": None,
                CHECKOUT_SIGNATURE_FIELD: checkout_confirmation_signature(cart, address),
            },
        )
    return normalize_actions(conn, raw_actions)


def checkout_confirmation_signature(cart: dict[str, Any], address: dict[str, Any]) -> str:
    selected_items = [item for item in cart.get("items", []) if item.get("selected", True)]
    signature = {
        "address_id": address.get("id"),
        "items": [
            {
                "id": item.get("id"),
                "product_id": item.get("product_id"),
                "sku_id": item.get("sku_id"),
                "quantity": int(item.get("quantity") or 0),
            }
            for item in sorted(selected_items, key=lambda item: str(item.get("id") or ""))
        ],
    }
    return json.dumps(signature, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def has_valid_checkout_confirmation(
    conn,
    session_id: str,
    cart: dict[str, Any],
    address: dict[str, Any],
) -> bool:
    row = conn.execute("SELECT last_actions FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
    if not row or not row["last_actions"]:
        return False
    try:
        actions = json.loads(row["last_actions"])
    except json.JSONDecodeError:
        return False
    if not isinstance(actions, list):
        return False
    expected = checkout_confirmation_signature(cart, address)
    return any(
        isinstance(action, dict)
        and action.get("label") == CHECKOUT_CONFIRM_LABEL
        and action.get(CHECKOUT_SIGNATURE_FIELD) == expected
        for action in actions
    )


def build_checkout_failure_actions(message: str) -> list[dict[str, Any]]:
    if any(term in message for term in ("库存不足", "库存刚刚发生变化")):
        return [
            {"type": "open_cart", "label": "打开购物车", "product_id": None},
            {"type": "search_more", "label": "把数量改少一点", "product_id": None},
            {"type": "search_more", "label": "重新推荐替代商品", "product_id": None},
        ]
    if any(term in message for term in ("规格已不存在", "没有可购买规格")):
        return [
            {"type": "open_cart", "label": "打开购物车", "product_id": None},
            {"type": "search_more", "label": "重新选择规格", "product_id": None},
        ]
    return [{"type": "open_cart", "label": "打开购物车", "product_id": None}]


def create_paid_order_from_cart(conn, address: dict[str, Any]) -> dict[str, Any]:
    cart = get_cart(conn)
    selected_items = [item for item in cart.items if item.selected]
    if not selected_items:
        raise ValueError("购物车里没有选中的商品，请先选择要结算的商品。")
    stock_problem = find_stock_problem(conn, selected_items)
    if stock_problem:
        raise ValueError(stock_problem)

    order_id = f"ord_{uuid.uuid4().hex[:10]}"
    total = round(sum(item.price * item.quantity for item in selected_items), 2)
    payment_id = f"pay_{uuid.uuid4().hex[:10]}"
    conn.execute("SAVEPOINT checkout_order")
    try:
        conn.execute(
            """
            INSERT INTO orders(id, status, total_amount, address_id, address_snapshot)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                order_id,
                "paid",
                total,
                address["id"],
                json.dumps(address, ensure_ascii=False),
            ),
        )
        for item in selected_items:
            sku_id = checkout_sku_id(conn, item)
            conn.execute(
                """
                INSERT INTO order_items(id, order_id, product_id, sku_id, title, brand, image_path, sku_name, price, quantity)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"oi_{uuid.uuid4().hex[:10]}",
                    order_id,
                    item.product_id,
                    sku_id,
                    item.title,
                    item.brand,
                    item.image_path,
                    item.sku_name,
                    item.price,
                    item.quantity,
                ),
            )
            updated = conn.execute(
                "UPDATE product_skus SET stock = stock - ? WHERE id = ? AND stock >= ?",
                (item.quantity, sku_id, item.quantity),
            )
            if updated.rowcount != 1:
                raise ValueError(f"{item.title}（{item.sku_name}）库存刚刚发生变化，请重新确认后再下单。")
        conn.executemany("DELETE FROM cart_items WHERE id = ?", [(item.id,) for item in selected_items])
        conn.execute(
            "INSERT INTO payments(id, order_id, status, amount) VALUES (?, ?, ?, ?)",
            (payment_id, order_id, "paid", total),
        )
        conn.execute("RELEASE checkout_order")
    except Exception:
        conn.execute("ROLLBACK TO checkout_order")
        conn.execute("RELEASE checkout_order")
        raise
    return {
        "order_id": order_id,
        "payment_id": payment_id,
        "total_amount": total,
        "items": selected_items,
        "address": address,
    }


def checkout_sku_id(conn, item: Any) -> str:
    if item.sku_id:
        return item.sku_id
    row = conn.execute(
        "SELECT id FROM product_skus WHERE product_id = ? ORDER BY price ASC LIMIT 1",
        (item.product_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"{item.title} 没有可购买规格，请重新选择商品。")
    return row["id"]


def find_stock_problem(conn, items: list[Any]) -> str | None:
    for item in items:
        sku_id = checkout_sku_id(conn, item)
        row = conn.execute(
            """
            SELECT stock
            FROM product_skus
            WHERE id = ? AND product_id = ?
            """,
            (sku_id, item.product_id),
        ).fetchone()
        if not row:
            return f"{item.title} 的规格已不存在，请重新选择规格后再下单。"
        stock = int(row["stock"] or 0)
        if stock < item.quantity:
            return f"{item.title}（{item.sku_name}）库存不足，当前只剩 {stock} 件，请调整数量后再下单。"
    return None


def build_order_success_text(order: dict[str, Any]) -> str:
    address = order["address"]
    full_address = f"{address['province']}{address['city']}{address['district']}{address['detail']}"
    lines = [
        "下单完成，已模拟支付成功。",
        "",
        f"订单号：{order['order_id']}",
        f"支付流水：{order['payment_id']}",
        f"收货人：{address['receiver_name']} {address['phone']}",
        f"收货地址：{full_address}",
        f"实付金额：¥{float(order['total_amount']):.2f}",
        "",
        "商品明细：",
    ]
    for index, item in enumerate(order["items"][:CHECKOUT_DETAIL_PREVIEW_LIMIT], start=1):
        line_total = float(item.price) * int(item.quantity)
        lines.append(f"{index}. {item.title}（{item.sku_name}）")
        lines.append(f"   单价 ¥{float(item.price):.2f}，数量 {int(item.quantity)}，小计 ¥{line_total:.2f}")
    if len(order["items"]) > CHECKOUT_DETAIL_PREVIEW_LIMIT:
        lines.append(f"当前仅展示前 {CHECKOUT_DETAIL_PREVIEW_LIMIT} 件，共 {len(order['items'])} 件商品。可在“我的订单”查看全部明细。")
    else:
        lines.append("可在“我的订单”查看订单详情。")
    return "\n".join(lines)


def build_order_success_payload(order: dict[str, Any]) -> dict[str, Any]:
    address = order["address"]
    full_address = f"{address['province']}{address['city']}{address['district']}{address['detail']}"
    items: list[dict[str, Any]] = []
    for item in order["items"]:
        price = float(item.price)
        quantity = int(item.quantity)
        items.append(
            {
                "product_id": item.product_id,
                "name": item.title,
                "spec_text": item.sku_name or "默认规格",
                "quantity": quantity,
                "price": round(price, 2),
                "line_total": round(price * quantity, 2),
                "image_url": item.image_path or f"/api/product-thumbnails/{item.product_id}.jpg",
            }
        )
    return {
        "order_id": order["order_id"],
        "payment_id": order["payment_id"],
        "receiver_name": address["receiver_name"],
        "receiver_phone": address["phone"],
        "receiver_address": full_address,
        "paid_amount": round(float(order["total_amount"]), 2),
        "items": items,
    }


def generate_grounded_answer(
    message: str,
    grounded_products: list[dict[str, Any]],
    faq_context: list[dict[str, str]],
    chat_history: list[dict[str, str]],
) -> tuple[str, dict[str, str]]:
    # LLM 只负责把已检索出的 grounded_products 写成导购话术，不参与决定商品集合。
    # 检索为空或 LLM 不可用时，用模板回答保证链路可降级。
    if not grounded_products:
        return build_template_answer(grounded_products, message), {"mode": "fallback", "reason": "no_retrieved_products"}
    try:
        result = run_async_blocking(generate_agent_reply_with_status(message, grounded_products, faq_context, chat_history))
        return sanitize_llm_answer(result.content, grounded_products), {
            "mode": "llm",
            "provider": result.provider,
            "model": result.model,
        }
    except LLMGenerationError as exc:
        return build_template_answer(grounded_products, message), {"mode": "fallback", "reason": str(exc)}
    except Exception as exc:
        return build_template_answer(grounded_products, message), {"mode": "fallback", "reason": exc.__class__.__name__}


def stream_grounded_answer_events(
    message: str,
    grounded_products: list[dict[str, Any]],
    faq_context: list[dict[str, str]],
    chat_history: list[dict[str, str]],
):
    # 流式回答同样遵守 grounded 约束：先发状态，再逐块输出 LLM 文本；失败时回退模板。
    if not grounded_products:
        answer = build_template_answer(grounded_products, message)
        status = {"mode": "fallback", "reason": "no_retrieved_products"}
        yield sse_event("llm_status", status)
        yield sse_event("delta", {"text": answer})
        return answer, status

    yield sse_event("llm_status", {"mode": "calling", "provider": "poe", "stream": True})
    chunks: list[str] = []
    try:
        for chunk in iter_async_blocking(
            stream_agent_reply_chunks_with_status(message, grounded_products, faq_context, chat_history)
        ):
            chunks.append(chunk)
            yield sse_event("delta", {"text": chunk})
        answer = " ".join("".join(chunks).split()).strip()
        if not answer:
            raise LLMGenerationError("LLM response is empty")
        return answer, {"mode": "llm_stream", "provider": "poe", "model": llm_model_name()}
    except LLMGenerationError as exc:
        if chunks:
            answer = " ".join("".join(chunks).split()).strip()
            return answer, {"mode": "llm_stream_partial", "provider": "poe", "model": llm_model_name()}
        answer = build_template_answer(grounded_products, message)
        status = {"mode": "fallback", "reason": str(exc)}
        yield sse_event("delta", {"text": answer})
        return answer, status
    except Exception as exc:
        if chunks:
            answer = " ".join("".join(chunks).split()).strip()
            return answer, {"mode": "llm_stream_partial", "provider": "poe", "model": llm_model_name()}
        answer = build_template_answer(grounded_products, message)
        status = {"mode": "fallback", "reason": exc.__class__.__name__}
        yield sse_event("delta", {"text": answer})
        return answer, status


def iter_async_blocking(async_iterable: AsyncIterator[str]) -> Iterable[str]:
    loop = asyncio.new_event_loop()
    try:
        iterator = async_iterable.__aiter__()
        while True:
            try:
                yield loop.run_until_complete(iterator.__anext__())
            except StopAsyncIteration:
                break
    finally:
        loop.close()


def run_async_blocking(coro) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except Exception as exc:
            result["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result["value"]


def sanitize_llm_answer(answer: str, products: list[dict[str, Any]]) -> str:
    cleaned = " ".join(answer.split()).strip()
    if not cleaned:
        return build_template_answer(products)
    if len(cleaned) > 160:
        return build_template_answer(products)
    return cleaned


def build_template_answer(products: list[dict[str, Any]], query: str = "") -> str:
    if not products:
        max_price_match = re.search(r"(\d+(?:\.\d+)?)\s*元?\s*(?:以下|以内|内|之内)", query)
        if "耳机" in query and max_price_match:
            return f"当前商品库没有找到 {max_price_match.group(1)} 元以内的蓝牙耳机，可以尝试放宽预算、品牌或品类条件。"
        return "当前商品库没有找到完全匹配的商品，可以尝试放宽价格、品牌或品类条件。"
    first = products[0]
    return (
        f"找到 {len(products)} 款匹配商品，优先看 {first['title']}。"
        "已按品类、预算、库存和评价排序，详细信息见下方商品卡片。"
    )


def build_alternative_answer(query: str, alternatives: list[dict[str, Any]]) -> str:
    if not alternatives:
        return build_template_answer([], query)
    first = alternatives[0]
    price = float(first.get("price") or 0)
    return (
        f"没有找到完全符合条件的商品。可选替代里最接近的是 {first['title']}，价格 ¥{price:.0f}；"
        "下方卡片已单独作为替代品展示。"
    )


def append_recommendation_marker(answer: str, products: list[dict[str, Any]]) -> str:
    if not products:
        return answer
    return f"{answer}\n推荐商品: {','.join(product['id'] for product in products)}"


def store_assistant_message(conn, session_id: str, content: str, image_id: str | None) -> None:
    conn.execute(
        "INSERT INTO chat_messages(id, session_id, role, content, image_id) VALUES (?, ?, ?, ?, ?)",
        (f"msg_{uuid.uuid4().hex[:12]}", session_id, "assistant", content, image_id),
    )


def update_session_state(
    conn,
    session_id: str,
    last_query: str | None = None,
    last_recommended_product_ids: list[str] | None = None,
    current_product_id: str | None = None,
    last_actions: list[dict[str, Any]] | None = None,
    parsed_turn: ParsedTurn | None = None,
    visible_products: list[dict[str, Any]] | None = None,
    cart: dict[str, Any] | None = None,
) -> None:
    row = conn.execute(
        "SELECT structured_state_json FROM chat_sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    previous_memory = parse_structured_memory(row["structured_state_json"] if row else None)
    should_update_memory = (
        last_query is not None
        or parsed_turn is not None
        or visible_products is not None
        or current_product_id is not None
        or cart is not None
    )
    structured_state_json = None
    if should_update_memory:
        structured_state_json = dump_structured_memory(
            build_updated_structured_memory(
                previous_memory,
                message=last_query or previous_memory.get("last_query") or "",
                parsed_turn=parsed_turn,
                visible_products=visible_products,
                current_product_id=current_product_id,
                cart=cart,
            )
        )
    conn.execute(
        """
        UPDATE chat_sessions
        SET
            last_query = COALESCE(?, last_query),
            last_recommended_product_ids = COALESCE(?, last_recommended_product_ids),
            current_product_id = COALESCE(?, current_product_id),
            last_actions = COALESCE(?, last_actions),
            structured_state_json = COALESCE(?, structured_state_json)
        WHERE id = ?
        """,
        (
            last_query,
            json.dumps(last_recommended_product_ids, ensure_ascii=False) if last_recommended_product_ids is not None else None,
            current_product_id,
            json.dumps(last_actions, ensure_ascii=False) if last_actions is not None else None,
            structured_state_json,
            session_id,
        ),
    )


def resolve_cart_product_id(
    conn,
    session_id: str,
    message: str,
    current_product_id: str | None = None,
    cart_context: list[dict] | None = None,
) -> str | None:
    normalized = message.strip()
    explicit = parse_explicit_product_id(normalized)
    if explicit:
        return explicit if product_exists(conn, explicit) else None

    session_row = conn.execute(
        "SELECT last_recommended_product_ids, current_product_id FROM chat_sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if not is_cart_intent(normalized) and not is_sku_selection_message(normalized):
        return None
    recent_ids = parse_product_id_list(session_row["last_recommended_product_ids"] if session_row else None)
    if current_product_id and product_exists(conn, current_product_id):
        recent_ids = [current_product_id, *[pid for pid in recent_ids if pid != current_product_id]]
    if session_row and session_row["current_product_id"] and product_exists(conn, session_row["current_product_id"]):
        recent_ids = [
            session_row["current_product_id"],
            *[pid for pid in recent_ids if pid != session_row["current_product_id"]],
        ]
    if cart_context:
        recent_ids.extend(
            str(item.get("product_id") or item.get("productId"))
            for item in cart_context
            if item.get("product_id") or item.get("productId")
        )

    selected_index = parse_ordinal_index(normalized)
    if selected_index is not None and 0 <= selected_index < len(recent_ids):
        return recent_ids[selected_index]
    if any(word in normalized for word in ["刚刚", "刚才", "上一个", "那个", "这款", "这个"]) and recent_ids:
        return recent_ids[0]
    if recent_ids:
        return recent_ids[0]
    return resolve_from_assistant_marker(conn, session_id)


def parse_explicit_product_id(message: str) -> str | None:
    for prefix in ["加入购物车:", "加入购物车：", "加购:", "加购："]:
        if message.startswith(prefix):
            return message.split(prefix, 1)[1].strip() or None
    return None


def is_cart_intent(message: str) -> bool:
    return any(word in message for word in ["加入购物车", "加购物车", "加购", "放购物车", "购物车"])


def is_sku_selection_message(message: str) -> bool:
    return bool(re.fullmatch(r"\s*\d{2}(?:\.\d)?\s*(?:码)?\s*", message)) or any(
        word in message for word in ["尺码", "规格", "款式", "选择"]
    )


def parse_product_id_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if item]


def parse_ordinal_index(message: str) -> int | None:
    number_map = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5}
    match = re.search(r"第?\s*([一二两三四五\d]+)\s*个", message)
    if not match:
        return None
    token = match.group(1)
    value = int(token) if token.isdigit() else number_map.get(token)
    return value - 1 if value else None


def resolve_from_assistant_marker(conn, session_id: str) -> str | None:
    row = conn.execute(
        """
        SELECT content FROM chat_messages
        WHERE session_id = ? AND role = 'assistant' AND content LIKE '%推荐商品:%'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (session_id,),
    ).fetchone()
    if not row:
        return None
    product_ids = row["content"].split("推荐商品:", 1)[1].split(",")
    first_id = product_ids[0].strip() if product_ids else None
    return first_id if product_exists(conn, first_id) else None


def fetch_cart_skus(conn, product_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, sku_name, properties_json, price, stock
        FROM product_skus
        WHERE product_id = ? AND stock > 0
        ORDER BY price ASC, id ASC
        """,
        (product_id,),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "sku_name": row["sku_name"] or "默认规格",
            "properties": parse_sku_properties(row["properties_json"]),
            "price": float(row["price"] or 0),
            "stock": int(row["stock"] or 0),
        }
        for row in rows
    ]


def resolve_sku_from_message(message: str, skus: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not skus:
        return None
    normalized = message.replace(" ", "")
    distinct_keys = sku_distinct_property_keys(skus)
    for sku in skus:
        properties = sku.get("properties") or {}
        sku_terms = [str(sku["sku_name"]), *[str(properties.get(key) or "") for key in distinct_keys]]
        if any(term and term.replace(" ", "") in normalized for term in sku_terms):
            return sku
    size_match = re.search(r"(\d{2}(?:\.\d)?)\s*码?", message)
    if size_match:
        size = size_match.group(1)
        for sku in skus:
            sku_text = " ".join([str(sku["sku_name"]), *[str(value) for value in sku.get("properties", {}).values()]])
            if size in sku_text:
                return sku
    return skus[0] if len(skus) == 1 else None


def build_sku_selection_prompt(product_title: str, skus: list[dict[str, Any]]) -> str:
    all_labels = unique_sku_option_labels(skus)
    shown_labels = all_labels[:6]
    sku_text = "、".join(shown_labels)
    suffix = " 等" if len(all_labels) > len(shown_labels) else ""
    dimension = sku_dimension_name(skus)
    if len(all_labels) > SKU_ACTION_OPTION_LIMIT:
        example = shown_labels[0] if shown_labels else "具体规格"
        return f"这款 {product_title} 有多个{dimension}可选：{sku_text}{suffix}。选项较多，请直接输入要加入购物车的{dimension}，例如“{example}”。"
    return f"这款 {product_title} 需要先确认{dimension}。可选{dimension}有：{sku_text}，你想加入哪一个？"


def build_sku_selection_actions(skus: list[dict[str, Any]]) -> list[dict[str, Any]]:
    labels = unique_sku_option_labels(skus)
    if len(labels) > SKU_ACTION_OPTION_LIMIT:
        return []
    return [
        {"type": "search_more", "label": f"选择{label}", "product_id": None}
        for label in labels
    ]


SKU_ACTION_OPTION_LIMIT = 4
SKU_DIMENSION_PRIORITY = ("尺码", "型号", "容量", "内存", "存储", "颜色", "色号", "版本", "配置", "套餐", "规格", "款式", "款型")


def unique_sku_option_labels(skus: list[dict[str, Any]], limit: int | None = None) -> list[str]:
    labels: list[str] = []
    for sku in skus:
        label = compact_sku_label(sku, skus)
        if label and label not in labels:
            labels.append(label)
        if limit is not None and len(labels) >= limit:
            break
    return labels


def compact_sku_label(sku: dict[str, Any], all_skus: list[dict[str, Any]]) -> str:
    properties = sku.get("properties") or {}
    distinct_keys = sku_distinct_property_keys(all_skus)
    values = [str(properties.get(key) or "").strip() for key in distinct_keys[:2]]
    label = " / ".join(value for value in values if value)
    if label:
        return label
    text = str(sku.get("sku_name") or "默认规格")
    size_match = re.search(r"尺码\s*[:：]?\s*([^/；，,\s]+)", text)
    if size_match:
        return size_match.group(1)
    return text.strip()[:18]


def sku_dimension_name(skus: list[dict[str, Any]]) -> str:
    keys = sku_distinct_property_keys(skus)
    if not keys:
        return "规格"
    if "尺码" in keys:
        return "尺码"
    if any(key in keys for key in ("型号", "版本", "配置")):
        return "型号"
    if any(key in keys for key in ("容量", "内存", "存储")):
        return "容量/配置"
    if any(key in keys for key in ("颜色", "色号")):
        return "颜色"
    return "规格"


def sku_distinct_property_keys(skus: list[dict[str, Any]]) -> list[str]:
    keys: list[str] = []
    all_keys = {
        key
        for sku in skus
        for key in (sku.get("properties") or {}).keys()
    }
    for key in SKU_DIMENSION_PRIORITY:
        if key not in all_keys:
            continue
        values = {
            str((sku.get("properties") or {}).get(key) or "").strip()
            for sku in skus
            if str((sku.get("properties") or {}).get(key) or "").strip()
        }
        if len(values) > 1:
            keys.append(key)
    return keys


def parse_sku_properties(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def add_product_to_cart(conn, product_id: str, sku_id: str | None = None) -> dict[str, Any] | None:
    product = conn.execute("SELECT id, title FROM products WHERE id = ?", (product_id,)).fetchone()
    if not product:
        return None
    if sku_id:
        sku = conn.execute(
            "SELECT id, sku_name FROM product_skus WHERE product_id = ? AND id = ?",
            (product_id, sku_id),
        ).fetchone()
    else:
        sku = conn.execute(
            "SELECT id, sku_name FROM product_skus WHERE product_id = ? ORDER BY price ASC LIMIT 1",
            (product_id,),
        ).fetchone()
    conn.execute(
        "INSERT INTO cart_items(id, product_id, sku_id, quantity, selected) VALUES (?, ?, ?, 1, 1)",
        (f"cart_{uuid.uuid4().hex[:10]}", product_id, sku["id"] if sku else None),
    )
    return {
        "id": product["id"],
        "title": product["title"],
        "sku_id": sku["id"] if sku else None,
        "sku_name": sku["sku_name"] if sku else None,
    }
