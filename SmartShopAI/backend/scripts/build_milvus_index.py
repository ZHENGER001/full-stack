from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.embedding_client import get_embedding_client  # noqa: E402
from app.rag import build_product_chunks  # noqa: E402
from scripts.build_rag_index import load_product  # noqa: E402


def env(name: str, default: str | None = None) -> str | None:
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(ROOT / ".env", override=False)
    except Exception:
        pass
    return os.getenv(name, default)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="./data/smartshop.db")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()

    milvus_uri = env("MILVUS_URI")
    milvus_token = env("MILVUS_TOKEN")
    collection = env("MILVUS_COLLECTION", "smartshop_products")
    if not milvus_uri:
        raise SystemExit("MILVUS_URI is not configured. Set MILVUS_URI before building the vector index.")
    try:
        from pymilvus import MilvusClient  # type: ignore
    except Exception as exc:
        raise SystemExit(f"pymilvus is not installed or unavailable: {exc}") from exc

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    chunks = []
    try:
        for row in conn.execute("SELECT * FROM products ORDER BY id").fetchall():
            product = load_product(conn, row)
            chunks.extend(build_product_chunks(product))
    finally:
        conn.close()
    if not chunks:
        raise SystemExit("No RAG chunks found. Import dataset or build rag_chunks first.")

    embedding_client = get_embedding_client()
    probe = embedding_client.embed_texts([chunks[0]["content"]])
    if not probe:
        raise SystemExit("Embedding provider is unavailable. Configure EMBEDDING_PROVIDER/MODEL or install sentence-transformers.")
    dimension = len(probe[0])

    client = MilvusClient(uri=milvus_uri, token=milvus_token, timeout=10)
    if args.reset and client.has_collection(collection):
        client.drop_collection(collection)
    if not client.has_collection(collection):
        client.create_collection(
            collection_name=collection,
            dimension=dimension,
            metric_type="COSINE",
            auto_id=True,
        )

    inserted = 0
    for start in range(0, len(chunks), args.batch_size):
        batch = chunks[start : start + args.batch_size]
        vectors = embedding_client.embed_texts([chunk["content"] for chunk in batch])
        if not vectors:
            raise SystemExit("Embedding provider failed during batch generation.")
        records = []
        for chunk, vector in zip(batch, vectors):
            metadata = json.loads(chunk["metadata_json"])
            product_id = chunk["product_id"]
            records.append(
                {
                    "vector": vector,
                    "chunk_id": chunk["id"],
                    "product_id": product_id,
                    "node_id": f"Product:{product_id}",
                    "parent_id": product_id,
                    "category": metadata.get("category", ""),
                    "brand": metadata.get("brand", ""),
                    "price": float(metadata.get("price", 0)),
                    "price_range": metadata.get("price_range", ""),
                    "features": ",".join(metadata.get("features", [])),
                    "scenarios": ",".join(metadata.get("scenarios", [])),
                    "source_type": chunk["chunk_type"],
                    "raw_text": chunk["content"],
                }
            )
        client.insert(collection_name=collection, data=records)
        inserted += len(records)
        print(f"Inserted {inserted}/{len(chunks)} vectors into {collection}")

    print(f"Built Milvus index: collection={collection}, vectors={inserted}, dimension={dimension}")


if __name__ == "__main__":
    main()
