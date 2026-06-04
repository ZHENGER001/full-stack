from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.rag import build_product_chunks  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="./data/smartshop.db")
    args = parser.parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("DELETE FROM rag_chunks")
        count = 0
        for row in conn.execute("SELECT * FROM products").fetchall():
            product = dict(row)
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
