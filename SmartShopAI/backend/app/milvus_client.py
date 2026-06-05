from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from .config import BASE_DIR, _load_env_file


class MilvusError(RuntimeError):
    """Raised when the optional Milvus vector store operation fails."""


def _env_value(name: str, default: str | None = None) -> str | None:
    env_file = _load_env_file(BASE_DIR / ".env")
    return os.getenv(name) or env_file.get(name) or default


def milvus_base_url() -> str:
    value = _env_value("MILVUS_BASE_URL") or _env_value("MILVUS_URI") or "http://localhost:19530"
    return value.rstrip("/")


def milvus_collection_name() -> str:
    return _env_value("MILVUS_COLLECTION", "smartshop_products") or "smartshop_products"


def milvus_vector_field_name() -> str:
    return _env_value("MILVUS_VECTOR_FIELD", "vector") or "vector"


def milvus_primary_field_name() -> str:
    return _env_value("MILVUS_PRIMARY_FIELD", "product_id") or "product_id"


def milvus_metric_type() -> str:
    return _env_value("MILVUS_METRIC_TYPE", "COSINE") or "COSINE"


def _milvus_db_name() -> str | None:
    value = _env_value("MILVUS_DB_NAME")
    return value or None


def _milvus_token() -> str | None:
    return _env_value("MILVUS_TOKEN", "root:Milvus")


@dataclass(frozen=True)
class MilvusSearchHit:
    product_id: str
    score: float
    source: str = "milvus"


class MilvusRestClient:
    def __init__(self, base_url: str | None = None, token: str | None = None, timeout_seconds: float = 10.0):
        self.base_url = (base_url or milvus_base_url()).rstrip("/")
        self.token = token if token is not None else _milvus_token()
        self.timeout_seconds = timeout_seconds

    def create_collection(self, dimension: int, recreate: bool = False) -> None:
        if recreate:
            self.drop_collection(ignore_missing=True)
        payload = self._with_db(
            {
                "collectionName": milvus_collection_name(),
                "dimension": dimension,
                "metricType": milvus_metric_type(),
                "primaryFieldName": milvus_primary_field_name(),
                "vectorFieldName": milvus_vector_field_name(),
                "idType": "VarChar",
                "autoID": False,
                "params": {"max_length": "128"},
            }
        )
        self._post("/v2/vectordb/collections/create", payload, ignore_exists=True)

    def drop_collection(self, ignore_missing: bool = False) -> None:
        payload = self._with_db({"collectionName": milvus_collection_name()})
        self._post("/v2/vectordb/collections/drop", payload, ignore_missing=ignore_missing)

    def insert_vectors(self, items: list[dict[str, Any]]) -> int:
        if not items:
            return 0
        payload = self._with_db({"collectionName": milvus_collection_name(), "data": items})
        data = self._post("/v2/vectordb/entities/insert", payload)
        result = data.get("data") if isinstance(data, dict) else None
        if isinstance(result, dict):
            return int(result.get("insertCount") or result.get("insert_count") or len(items))
        return len(items)

    def load_collection(self) -> None:
        payload = self._with_db({"collectionName": milvus_collection_name()})
        self._post("/v2/vectordb/collections/load", payload, ignore_exists=True)

    def search(self, vector: list[float], top_k: int = 20) -> list[MilvusSearchHit]:
        if not vector:
            return []
        payload = self._with_db(
            {
                "collectionName": milvus_collection_name(),
                "data": [vector],
                "annsField": milvus_vector_field_name(),
                "limit": top_k,
                "outputFields": [milvus_primary_field_name()],
                "searchParams": {
                    "metricType": milvus_metric_type(),
                    "params": {},
                },
            }
        )
        data = self._post("/v2/vectordb/entities/search", payload)
        raw_hits = data.get("data") if isinstance(data, dict) else []
        if isinstance(raw_hits, dict):
            raw_hits = raw_hits.get("data") or raw_hits.get("results") or []
        hits: list[MilvusSearchHit] = []
        for item in raw_hits if isinstance(raw_hits, list) else []:
            if not isinstance(item, dict):
                continue
            entity = item.get("entity") if isinstance(item.get("entity"), dict) else item
            product_id = entity.get(milvus_primary_field_name()) or entity.get("product_id") or entity.get("id")
            if not product_id:
                continue
            score = item.get("distance", item.get("score", 0.0))
            hits.append(MilvusSearchHit(product_id=str(product_id), score=float(score or 0.0)))
        return hits

    def _post(
        self,
        path: str,
        payload: dict[str, Any],
        ignore_exists: bool = False,
        ignore_missing: bool = False,
    ) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=httpx.Timeout(self.timeout_seconds, connect=5.0), trust_env=False) as client:
                response = client.post(
                    f"{self.base_url}{path}",
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            raise MilvusError(f"Milvus request failed: {path}") from exc

        code = data.get("code") if isinstance(data, dict) else None
        message = str(data.get("message", "")) if isinstance(data, dict) else ""
        if code in {0, 200, "0", "200", None}:
            return data
        lowered = message.lower()
        if ignore_exists and ("exist" in lowered or "duplicat" in lowered):
            return data
        if ignore_missing and ("not exist" in lowered or "not found" in lowered):
            return data
        raise MilvusError(f"Milvus API error: {message or code}")

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Request-Timeout": str(int(self.timeout_seconds)),
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _with_db(self, payload: dict[str, Any]) -> dict[str, Any]:
        db_name = _milvus_db_name()
        if db_name:
            payload = dict(payload)
            payload["dbName"] = db_name
        return payload
