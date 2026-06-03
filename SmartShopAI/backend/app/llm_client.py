from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

LOGGER = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parents[1]


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return
    load_dotenv(BASE_DIR / ".env", override=False)


_load_dotenv_if_available()


def _env_value(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _example_poe_key() -> str:
    example_path = BASE_DIR / ".env.example"
    if not example_path.exists():
        return ""
    for raw_line in example_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("POE_API_KEY="):
            return line.split("=", 1)[1].strip()
    return ""


@dataclass
class LLMResult:
    text: str
    available: bool
    fallback_reason: str | None = None


class PoeQwenClient:
    """OpenAI-compatible client for Poe/Qwen.

    The client never raises connection errors to callers. Missing dependencies,
    missing API keys, timeouts, and provider errors are converted into
    unavailable results so the agent can fall back to local retrieval.
    """

    def __init__(self, timeout_seconds: float | None = None) -> None:
        self.api_key = _env_value("POE_API_KEY") or _env_value("OPENAI_COMPATIBLE_API_KEY")
        self.model = _env_value("QWEN_MODEL") or "qwen3.6-plus"
        self.base_url = (
            _env_value("POE_BASE_URL")
            or _env_value("OPENAI_COMPATIBLE_BASE_URL")
            or None
        )
        self.timeout_seconds = timeout_seconds or float(_env_value("LLM_TIMEOUT_SECONDS") or "8")
        self.enabled = _env_value("LLM_PROVIDER").lower() not in {"off", "false", "disabled", "none"}
        self.example_key = _example_poe_key()

    @property
    def configured(self) -> bool:
        return self.enabled and bool(self.api_key) and self.api_key != self.example_key

    def _client(self):
        if not self.enabled:
            return None, "LLM provider is disabled"
        if self.api_key and self.api_key == self.example_key:
            return None, "POE_API_KEY is still the example placeholder"
        if not self.configured:
            return None, "POE_API_KEY is not configured"
        try:
            from openai import OpenAI  # type: ignore
        except Exception as exc:
            return None, f"openai package is unavailable: {exc}"
        try:
            kwargs = {"api_key": self.api_key, "timeout": self.timeout_seconds}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            return OpenAI(**kwargs), None
        except Exception as exc:
            return None, f"failed to initialize OpenAI-compatible client: {exc}"

    def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 900,
    ) -> LLMResult:
        client, reason = self._client()
        if client is None:
            return LLMResult(text="", available=False, fallback_reason=reason)
        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=False,
            )
            text = response.choices[0].message.content or ""
            return LLMResult(text=text.strip(), available=bool(text.strip()))
        except Exception as exc:
            LOGGER.warning("LLM completion failed: %s", exc)
            return LLMResult(text="", available=False, fallback_reason=str(exc))

    def stream_complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 900,
    ) -> Iterable[str]:
        client, reason = self._client()
        if client is None:
            LOGGER.info("LLM stream unavailable: %s", reason)
            return
        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            for chunk in response:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception as exc:
            LOGGER.warning("LLM stream failed: %s", exc)
            return


def get_llm_client() -> PoeQwenClient:
    return PoeQwenClient()
