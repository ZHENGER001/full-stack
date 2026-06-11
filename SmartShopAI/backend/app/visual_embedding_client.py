from __future__ import annotations

import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from .config import BASE_DIR, _load_env_file


class VisualEmbeddingError(RuntimeError):
    """Raised when image embedding generation is unavailable."""


def _env_value(name: str, default: str | None = None) -> str | None:
    env_file = _load_env_file(BASE_DIR / ".env")
    return os.getenv(name) or env_file.get(name) or default


def visual_embedding_enabled() -> bool:
    value = (_env_value("VISUAL_EMBEDDING_ENABLED", "true") or "true").strip().lower()
    return value not in {"0", "false", "no", "off"}


def visual_embedding_provider_name() -> str:
    return (_env_value("VISUAL_EMBEDDING_PROVIDER", "perceptual") or "perceptual").strip().lower()


def visual_embedding_model_name() -> str:
    return _env_value("VISUAL_EMBEDDING_MODEL", "openai/clip-vit-base-patch32") or "openai/clip-vit-base-patch32"


def visual_milvus_collection_name() -> str:
    return _env_value("VISUAL_MILVUS_COLLECTION", "smartshop_product_images") or "smartshop_product_images"


def visual_match_min_score() -> float:
    raw_value = _env_value("VISUAL_MATCH_MIN_SCORE", "0.30") or "0.30"
    try:
        return max(0.0, min(float(raw_value), 1.0))
    except ValueError:
        return 0.30


def embed_image_path(path: Path) -> list[float]:
    if not visual_embedding_enabled():
        raise VisualEmbeddingError("visual embedding disabled")
    provider = visual_embedding_provider_name()
    if provider in {"clip", "siglip", "transformers"}:
        return embed_image_with_transformers(path)
    if provider in {"perceptual", "local", "pillow"}:
        return embed_image_perceptual(path)
    raise VisualEmbeddingError(f"Unsupported visual embedding provider: {provider}")


def embed_image_perceptual(path: Path) -> list[float]:
    try:
        with Image.open(path) as raw_image:
            image = ImageOps.exif_transpose(raw_image).convert("RGB")
            grid = ImageOps.fit(image, (8, 8), method=Image.Resampling.BICUBIC)
            histogram_image = image.copy()
            histogram_image.thumbnail((96, 96))
            histogram_image = histogram_image.convert("RGB")
            vector = pixel_grid_features(grid) + color_histogram_features(histogram_image)
    except Exception as exc:
        raise VisualEmbeddingError("visual image embedding failed") from exc
    return l2_normalize(vector)


def pixel_grid_features(image: Image.Image) -> list[float]:
    features: list[float] = []
    for red, green, blue in image.getdata():
        features.extend([red / 255.0, green / 255.0, blue / 255.0])
    return features


def color_histogram_features(image: Image.Image) -> list[float]:
    bins_per_channel = 8
    counts = [0.0] * (bins_per_channel * 3)
    total = 0
    for red, green, blue in image.getdata():
        counts[min(red * bins_per_channel // 256, bins_per_channel - 1)] += 1.0
        counts[bins_per_channel + min(green * bins_per_channel // 256, bins_per_channel - 1)] += 1.0
        counts[bins_per_channel * 2 + min(blue * bins_per_channel // 256, bins_per_channel - 1)] += 1.0
        total += 1
    if not total:
        return counts
    return [value / float(total) for value in counts]


def l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return vector
    return [float(value / norm) for value in vector]


@lru_cache(maxsize=1)
def _load_transformers_model() -> tuple[Any, Any, Any]:
    try:
        import torch
        from transformers import AutoModel, AutoProcessor
    except Exception as exc:
        raise VisualEmbeddingError("transformers/torch is not installed") from exc

    model_id = visual_embedding_model_name()
    try:
        processor = AutoProcessor.from_pretrained(model_id)
        model = AutoModel.from_pretrained(model_id)
        model.eval()
    except Exception as exc:
        raise VisualEmbeddingError(f"visual model load failed: {model_id}") from exc
    return processor, model, torch


def embed_image_with_transformers(path: Path) -> list[float]:
    processor, model, torch = _load_transformers_model()
    try:
        with Image.open(path) as raw_image:
            image = ImageOps.exif_transpose(raw_image).convert("RGB")
            inputs = processor(images=image, return_tensors="pt")
        with torch.no_grad():
            if hasattr(model, "get_image_features"):
                features = model.get_image_features(**inputs)
            else:
                outputs = model(**inputs)
                features = getattr(outputs, "image_embeds", None)
                if features is None:
                    features = getattr(outputs, "pooler_output", None)
        if features is None:
            raise VisualEmbeddingError("visual model did not return image features")
        return l2_normalize([float(value) for value in features[0].detach().cpu().tolist()])
    except VisualEmbeddingError:
        raise
    except Exception as exc:
        raise VisualEmbeddingError("transformers visual embedding failed") from exc
