from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings  # noqa: E402
from app.database import dict_factory, init_db  # noqa: E402
from app.embedding_client import EmbeddingError, embed_texts  # noqa: E402
from app.milvus_client import (  # noqa: E402
    MilvusError,
    MilvusRestClient,
    milvus_primary_field_name,
    milvus_vector_field_name,
)
from app.search_document import build_product_search_document  # noqa: E402


def load_documents(db_path: Path) -> list[dict[str, str]]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = dict_factory
    try:
        rows = connection.execute(
            """
            SELECT
                p.id,
                p.title,
                p.brand,
                p.category,
                p.subcategory,
                p.price,
                p.rating,
                COALESCE(p.marketing_description, '') AS marketing_description,
                COALESCE(sk.sku_text, '') AS sku_text,
                COALESCE(sk.stock, 0) AS stock,
                COALESCE(fq.faq_text, '') AS faq_text,
                COALESCE(rv.review_text, '') AS review_text,
                COALESCE(rg.chunk_text, '') AS chunk_text
            FROM products p
            LEFT JOIN (
                SELECT
                    product_id,
                    GROUP_CONCAT(sku_name || ' ' || properties_json, ' ') AS sku_text,
                    SUM(stock) AS stock
                FROM product_skus
                GROUP BY product_id
            ) sk ON sk.product_id = p.id
            LEFT JOIN (
                SELECT product_id, GROUP_CONCAT(question || ' ' || answer, ' ') AS faq_text
                FROM product_faqs
                GROUP BY product_id
            ) fq ON fq.product_id = p.id
            LEFT JOIN (
                SELECT product_id, GROUP_CONCAT(content, ' ') AS review_text
                FROM product_reviews
                GROUP BY product_id
            ) rv ON rv.product_id = p.id
            LEFT JOIN (
                SELECT product_id, GROUP_CONCAT(content, ' ') AS chunk_text
                FROM rag_chunks
                GROUP BY product_id
            ) rg ON rg.product_id = p.id
            ORDER BY p.id
            """
        ).fetchall()
    finally:
        connection.close()

    documents: list[dict[str, str]] = []
    for row in rows:
        text = build_product_search_document(row, include_evidence=True)
        documents.append({"product_id": str(row["id"]), "text": text})
    return documents


def batched(items: list[dict[str, str]], batch_size: int) -> list[list[dict[str, str]]]:
    return [items[index : index + batch_size] for index in range(0, len(items), batch_size)]


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def is_retryable_embedding_error(exc: EmbeddingError) -> bool:
    message = str(exc)
    return (
        message in {"Embedding network error", "Embedding request timed out"}
        or message.startswith("Embedding HTTP status 5")
    )


def embed_batch_with_retries(
    texts: list[str],
    batch_index: int,
    attempts: int,
    retry_delay_seconds: float,
) -> list[list[float]]:
    for attempt in range(1, attempts + 1):
        try:
            return embed_texts(texts)
        except EmbeddingError as exc:
            if attempt >= attempts or not is_retryable_embedding_error(exc):
                raise SystemExit(f"Embedding failed on batch {batch_index}: {exc}") from exc
            print(
                f"Embedding failed on batch {batch_index} "
                f"(attempt {attempt}/{attempts}): {exc}; "
                f"retrying in {retry_delay_seconds:g}s"
            )
            time.sleep(retry_delay_seconds)
    raise SystemExit(f"Embedding failed on batch {batch_index}: no attempts were run")


def build_index(
    recreate: bool,
    batch_size: int,
    embedding_attempts: int = 36,
    embedding_retry_delay: float = 5.0,
) -> int:
    init_db()
    settings = get_settings()
    documents = load_documents(settings.database_path)
    if not documents:
        print("No products found in SQLite.")
        return 0

    client = MilvusRestClient(timeout_seconds=30.0)
    created = False
    inserted = 0
    primary_field = milvus_primary_field_name()
    vector_field = milvus_vector_field_name()

    for batch_index, batch in enumerate(batched(documents, batch_size), start=1):
        vectors = embed_batch_with_retries(
            [item["text"] for item in batch],
            batch_index=batch_index,
            attempts=embedding_attempts,
            retry_delay_seconds=embedding_retry_delay,
        )
        if not vectors:
            continue
        if not created:
            dimension = len(vectors[0])
            try:
                client.create_collection(dimension=dimension, recreate=recreate)
            except MilvusError as exc:
                raise SystemExit(f"Milvus collection setup failed: {exc}") from exc
            created = True
            print(f"Milvus collection ready with dimension={dimension}.")

        payload: list[dict[str, Any]] = []
        for document, vector in zip(batch, vectors):
            payload.append(
                {
                    primary_field: document["product_id"],
                    vector_field: vector,
                }
            )
        try:
            inserted += client.insert_vectors(payload)
        except MilvusError as exc:
            raise SystemExit(f"Milvus insert failed on batch {batch_index}: {exc}") from exc
        print(f"Inserted batch {batch_index}: {len(payload)} vectors")

    if created:
        try:
            client.load_collection()
        except MilvusError:
            print("Milvus load request failed or is unsupported by this deployment; continuing.")
    return inserted


def main() -> None:
    parser = argparse.ArgumentParser(description="Build SmartShopAI product embeddings in Milvus.")
    parser.add_argument("--recreate", action="store_true", help="Drop and recreate the Milvus collection first.")
    parser.add_argument("--batch-size", type=positive_int, default=8)
    parser.add_argument(
        "--embedding-attempts",
        type=positive_int,
        default=36,
        help="Maximum attempts for each embedding batch when the service is still warming up.",
    )
    parser.add_argument(
        "--embedding-retry-delay",
        type=positive_float,
        default=5.0,
        help="Seconds to wait between transient embedding retries.",
    )
    args = parser.parse_args()

    inserted = build_index(
        recreate=args.recreate,
        batch_size=args.batch_size,
        embedding_attempts=args.embedding_attempts,
        embedding_retry_delay=args.embedding_retry_delay,
    )
    print(f"Milvus index build complete. inserted={inserted}")


if __name__ == "__main__":
    main()
