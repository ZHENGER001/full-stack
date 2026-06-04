from __future__ import annotations

import os
from typing import Any

import httpx

from .config import BASE_DIR, _load_env_file


def _env_value(name: str, default: str | None = None) -> str | None:
    env_file = _load_env_file(BASE_DIR / ".env")
    return os.getenv(name) or env_file.get(name) or default


def asr_provider_name() -> str:
    return (_env_value("ASR_PROVIDER", "none") or "none").strip().lower()


def asr_model_name() -> str | None:
    return _env_value("ASR_MODEL", "whisper-1")


def _timeout_seconds() -> float:
    raw_value = _env_value("ASR_TIMEOUT_SECONDS", "30")
    try:
        return max(float(raw_value or "30"), 5.0)
    except ValueError:
        return 30.0


def _extract_text(data: dict[str, Any]) -> str:
    text = data.get("text")
    if isinstance(text, str):
        return text.strip()
    segments = data.get("segments")
    if isinstance(segments, list):
        parts = [str(item.get("text", "")).strip() for item in segments if isinstance(item, dict)]
        return " ".join(part for part in parts if part).strip()
    return ""


async def transcribe_audio_bytes(
    filename: str,
    content_type: str | None,
    data: bytes,
) -> str | None:
    provider = asr_provider_name()
    if provider in {"", "none"}:
        return None
    if provider not in {"openai", "openai-compatible"}:
        return None

    base_url = (_env_value("ASR_BASE_URL") or "").rstrip("/")
    api_key = _env_value("ASR_API_KEY")
    model = asr_model_name() or "whisper-1"
    if not base_url or not api_key or not data:
        return None

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(_timeout_seconds(), connect=8.0)) as client:
            response = await client.post(
                f"{base_url}/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                data={"model": model},
                files={
                    "file": (
                        filename or "speech.webm",
                        data,
                        content_type or "application/octet-stream",
                    )
                },
            )
            response.raise_for_status()
            text = _extract_text(response.json())
            return text or None
    except Exception:
        return None
