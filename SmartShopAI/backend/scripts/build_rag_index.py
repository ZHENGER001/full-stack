from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.rag import build_product_chunks  # noqa: E402


def load_product(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    product_id = row["id"]
    skus = [
        {
            "sku_id": sku["id"],
            "properties": json.loads(sku["properties_json"]),
            "price": float(sku["price"]),
            "stock": int(sku["stock"]),
        }
        for sku in conn.execute(
            "SELECT id, properties_json, price, stock FROM product_skus WHERE product_id = ? ORDER BY id",
            (product_id,),
        ).fetchall()
    ]
    faqs = [
        {"question": faq["question"], "answer": faq["answer"]}
        for faq in conn.execute(
            "SELECT question, answer FROM product_faqs WHERE product_id = ? ORDER BY id",
            (product_id,),
        ).fetchall()
    ]
    reviews = [
        {"nickname": review["nickname"], "rating": float(review["rating"]), "content": review["content"]}
        for review in conn.execute(
            "SELECT nickname, rating, content FROM product_reviews WHERE product_id = ? ORDER BY id",
            (product_id,),
        ).fetchall()
    ]
    return {
        "id": product_id,
        "title": row["title"],
        "brand": row["brand"],
        "category": row["category"],
        "subcategory": row["subcategory"],
        "price": float(row["price"]),
        "rating": float(row["rating"]),
        "marketing_description": row["marketing_description"],
        "skus": skus,
        "official_faq": faqs,
        "user_reviews": reviews,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="./data/smartshop.db")
    args = parser.parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("DELETE FROM rag_chunks")
        count = 0
        for row in conn.execute("SELECT * FROM products ORDER BY id").fetchall():
            product = load_product(conn, row)
            for chunk in build_product_chunks(product):
                conn.execute(
                    "INSERT INTO rag_chunks(id, product_id, chunk_type, content, metadata_json) VALUES (?, ?, ?, ?, ?)",
                    (
                        chunk["id"],
                        chunk["product_id"],
                        chunk["chunk_type"],
                        chunk["content"],
                        chunk["metadata_json"],
                    ),
                )
                count += 1
        conn.commit()
        print(f"Built {count} RAG chunks")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
