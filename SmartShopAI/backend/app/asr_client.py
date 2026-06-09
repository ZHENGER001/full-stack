from __future__ import annotations

import base64
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


def _extract_chat_text(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    return content.strip() if isinstance(content, str) else ""


async def _transcribe_with_poe(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    model: str,
    filename: str,
    content_type: str | None,
    data: bytes,
) -> str | None:
    mime_type = content_type or "audio/mp4"
    encoded_audio = base64.b64encode(data).decode("utf-8")
    response = await client.post(
        f"{base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "请把音频里的用户发言转写成原文。只输出转写文本，"
                                "不要解释，不要加标题，不要使用 Markdown。"
                            ),
                        },
                        {
                            "type": "file",
                            "file": {
                                "filename": filename or "voice_input.m4a",
                                "file_data": f"data:{mime_type};base64,{encoded_audio}",
                            },
                        },
                    ],
                }
            ],
            "stream": False,
            "temperature": 0,
        },
    )
    response.raise_for_status()
    text = _extract_chat_text(response.json())
    return text or None


async def _transcribe_with_audio_api(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    model: str,
    filename: str,
    content_type: str | None,
    data: bytes,
) -> str | None:
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


async def transcribe_audio_bytes(
    filename: str,
    content_type: str | None,
    data: bytes,
) -> str | None:
    provider = asr_provider_name()
    if provider in {"", "none"}:
        return None
    if provider not in {"openai", "openai-compatible", "poe"}:
        return None

    base_url = (_env_value("ASR_BASE_URL") or "").rstrip("/")
    api_key = _env_value("ASR_API_KEY")
    model = asr_model_name() or "whisper-1"
    if provider == "poe":
        base_url = base_url or (_env_value("POE_BASE_URL", "https://api.poe.com/v1") or "").rstrip("/")
        api_key = api_key or _env_value("POE_API_KEY")
        model = model if model != "whisper-1" else "Qwen3.5-Omni-Flash"
    if not base_url or not api_key or not data:
        return None

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(_timeout_seconds(), connect=8.0)) as client:
            if provider == "poe":
                return await _transcribe_with_poe(
                    client=client,
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                    filename=filename,
                    content_type=content_type,
                    data=data,
                )
            return await _transcribe_with_audio_api(
                client=client,
                base_url=base_url,
                api_key=api_key,
                model=model,
                filename=filename,
                content_type=content_type,
                data=data,
            )
    except Exception:
        return None
