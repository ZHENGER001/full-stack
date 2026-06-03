from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

LOGGER = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parents[1]


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return
    load_dotenv(BASE_DIR / ".env", override=False)


_load_dotenv_if_available()


class EmbeddingProvider(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]] | None:
        ...


@dataclass
class EmbeddingStatus:
    provider: str
    available: bool
    reason: str | None = None


class LocalSentenceTransformerProvider:
    def __init__(self, model_name: str, timeout_seconds: float = 30.0) -> None:
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self._model = None
        self._error: str | None = None

    def _load_model(self):
        if self._model is not None:
            return self._model
        if self._error:
            return None
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
            self._model = SentenceTransformer(self.model_name)
            return self._model
        except Exception as exc:
            self._error = str(exc)
            LOGGER.warning("Local embedding model unavailable: %s", exc)
            return None

    def embed_texts(self, texts: list[str]) -> list[list[float]] | None:
        model = self._load_model()
        if model is None:
            return None
        try:
            vectors = model.encode(texts, normalize_embeddings=True)
            return [vector.astype(float).tolist() for vector in vectors]
        except Exception as exc:
            LOGGER.warning("Local embedding failed: %s", exc)
            return None


class OpenAICompatibleEmbeddingProvider:
    def __init__(self, model_name: str, timeout_seconds: float = 20.0) -> None:
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.api_key = os.getenv("OPENAI_COMPATIBLE_API_KEY") or os.getenv("POE_API_KEY")
        self.base_url = os.getenv("OPENAI_COMPATIBLE_BASE_URL") or os.getenv("POE_BASE_URL")

    def embed_texts(self, texts: list[str]) -> list[list[float]] | None:
        if not self.api_key:
            return None
        try:
            from openai import OpenAI  # type: ignore
            kwargs = {"api_key": self.api_key, "timeout": self.timeout_seconds}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            client = OpenAI(**kwargs)
            response = client.embeddings.create(model=self.model_name, input=texts)
            return [item.embedding for item in response.data]
        except Exception as exc:
            LOGGER.warning("OpenAI-compatible embedding failed: %s", exc)
            return None


class DashScopeEmbeddingProvider:
    def __init__(self, model_name: str, timeout_seconds: float = 20.0) -> None:
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.api_key = os.getenv("DASHSCOPE_API_KEY")
        self.endpoint = os.getenv("DASHSCOPE_EMBEDDING_URL")

    def embed_texts(self, texts: list[str]) -> list[list[float]] | None:
        if not self.api_key or not self.endpoint:
            return None
        payload = json.dumps({"model": self.model_name, "input": texts}).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
            embeddings = data.get("data", {}).get("embeddings") or data.get("embeddings")
            if not embeddings:
                return None
            return [item.get("embedding", item) for item in embeddings]
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, Exception) as exc:
            LOGGER.warning("DashScope embedding failed: %s", exc)
            return None


class OllamaEmbeddingProvider:
    def __init__(self, model_name: str, timeout_seconds: float = 20.0) -> None:
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.endpoint = os.getenv("OLLAMA_EMBEDDING_URL", "http://127.0.0.1:11434/api/embeddings")

    def embed_texts(self, texts: list[str]) -> list[list[float]] | None:
        vectors: list[list[float]] = []
        for text in texts:
            payload = json.dumps({"model": self.model_name, "prompt": text}).encode("utf-8")
            request = urllib.request.Request(
                self.endpoint,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    data = json.loads(response.read().decode("utf-8"))
                vector = data.get("embedding")
                if not vector:
                    return None
                vectors.append(vector)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, Exception) as exc:
                LOGGER.warning("Ollama embedding failed: %s", exc)
                return None
        return vectors


class EmbeddingClient:
    def __init__(self) -> None:
        self.provider_name = os.getenv("EMBEDDING_PROVIDER", "local").lower()
        self.model_name = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
        self.provider = self._build_provider()

    def _build_provider(self) -> EmbeddingProvider:
        if self.provider_name in {"openai", "openai-compatible", "poe"}:
            return OpenAICompatibleEmbeddingProvider(self.model_name)
        if self.provider_name == "dashscope":
            return DashScopeEmbeddingProvider(self.model_name)
        if self.provider_name == "ollama":
            return OllamaEmbeddingProvider(self.model_name)
        return LocalSentenceTransformerProvider(self.model_name)

    def embed_texts(self, texts: list[str]) -> list[list[float]] | None:
        clean_texts = [text.strip() for text in texts if text and text.strip()]
        if not clean_texts:
            return []
        return self.provider.embed_texts(clean_texts)

    def status(self) -> EmbeddingStatus:
        probe = self.embed_texts(["SmartShopAI embedding probe"])
        return EmbeddingStatus(
            provider=self.provider_name,
            available=bool(probe),
            reason=None if probe else "embedding provider unavailable",
        )


def get_embedding_client() -> EmbeddingClient:
    return EmbeddingClient()
