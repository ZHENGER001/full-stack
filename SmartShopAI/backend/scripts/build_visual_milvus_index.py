from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings  # noqa: E402
from app.database import dict_factory, init_db  # noqa: E402
from app.milvus_client import (  # noqa: E402
    MilvusError,
    MilvusRestClient,
    milvus_primary_field_name,
    milvus_vector_field_name,
)
from app.visual_embedding_client import (  # noqa: E402
    VisualEmbeddingError,
    embed_image_path,
    visual_milvus_collection_name,
)


def load_product_images(db_path: Path) -> list[dict[str, str]]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = dict_factory
    try:
        rows = connection.execute(
            """
            SELECT id, image_path
            FROM products
            WHERE COALESCE(image_path, '') <> ''
            ORDER BY id
            """
        ).fetchall()
    finally:
        connection.close()
    return [{"product_id": str(row["id"]), "image_path": str(row["image_path"])} for row in rows]


def resolve_product_image_path(dataset_path: Path, image_path: str) -> Path | None:
    candidate = dataset_path / image_path
    if candidate.exists():
        return candidate
    image_name = Path(image_path).name
    matches = list(dataset_path.glob(f"*/images/{image_name}"))
    return matches[0] if matches else None


def batched(items: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
    return [items[index : index + batch_size] for index in range(0, len(items), batch_size)]


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def build_index(recreate: bool, batch_size: int) -> int:
    init_db()
    settings = get_settings()
    rows = load_product_images(settings.database_path)
    if not rows:
        print("No product images found in SQLite.")
        return 0

    collection = visual_milvus_collection_name()
    client = MilvusRestClient(collection_name=collection, timeout_seconds=30.0)
    primary_field = milvus_primary_field_name()
    vector_field = milvus_vector_field_name()
    created = False
    inserted = 0
    pending: list[dict[str, Any]] = []
    skipped = 0

    for row in rows:
        image_path = resolve_product_image_path(settings.dataset_path, row["image_path"])
        if image_path is None:
            skipped += 1
            continue
        try:
            vector = embed_image_path(image_path)
        except VisualEmbeddingError as exc:
            skipped += 1
            print(f"Skipped {row['product_id']}: {exc}")
            continue
        if not created:
            try:
                client.create_collection(dimension=len(vector), recreate=recreate)
            except MilvusError as exc:
                raise SystemExit(f"Visual Milvus collection setup failed: {exc}") from exc
            created = True
            print(f"Visual Milvus collection ready: {collection}, dimension={len(vector)}.")
        pending.append({primary_field: row["product_id"], vector_field: vector})
        if len(pending) >= batch_size:
            inserted += insert_batch(client, pending)
            pending = []

    if pending:
        inserted += insert_batch(client, pending)

    if created:
        try:
            client.load_collection()
        except MilvusError:
            print("Milvus load request failed or is unsupported by this deployment; continuing.")
    print(f"Visual index build complete. inserted={inserted}, skipped={skipped}")
    return inserted


def insert_batch(client: MilvusRestClient, payload: list[dict[str, Any]]) -> int:
    try:
        inserted = client.insert_vectors(payload)
    except MilvusError as exc:
        raise SystemExit(f"Visual Milvus insert failed: {exc}") from exc
    print(f"Inserted visual batch: {len(payload)} vectors")
    return inserted


def main() -> None:
    parser = argparse.ArgumentParser(description="Build SmartShopAI product image embeddings in Milvus.")
    parser.add_argument("--recreate", action="store_true", help="Drop and recreate the visual collection first.")
    parser.add_argument("--batch-size", type=positive_int, default=16)
    args = parser.parse_args()

    build_index(recreate=args.recreate, batch_size=args.batch_size)


if __name__ == "__main__":
    main()
