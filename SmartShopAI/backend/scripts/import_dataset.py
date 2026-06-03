from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import init_db  # noqa: E402
from app.rag import build_product_chunks  # noqa: E402
from scripts.build_thumbnails import build_thumbnails  # noqa: E402


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def sku_name(properties: dict[str, str]) -> str:
    return " / ".join(str(value) for value in properties.values()) or "默认规格"


def rating_from_reviews(reviews: list[dict]) -> float:
    if not reviews:
        return 4.5
    return round(sum(float(review.get("rating", 4)) for review in reviews) / len(reviews), 1)


def resolve_image_path(dataset_dir: Path, image_path: str) -> str:
    image_name = Path(image_path).name
    match = next(dataset_dir.glob(f"*/images/{image_name}"), None)
    if match:
        return match.relative_to(dataset_dir).as_posix()
    return image_path


def normalize_product(raw: dict, dataset_dir: Path) -> dict:
    rag = raw.get("rag_knowledge", {})
    reviews = rag.get("user_reviews", [])
    return {
        "id": raw["product_id"],
        "title": raw["title"],
        "brand": raw.get("brand", ""),
        "category": raw.get("category", ""),
        "subcategory": raw.get("sub_category", ""),
        "price": float(raw.get("base_price", 0)),
        "rating": rating_from_reviews(reviews),
        "image_path": resolve_image_path(dataset_dir, raw.get("image_path", "")),
        "marketing_description": rag.get("marketing_description", ""),
        "skus": raw.get("skus", []),
        "official_faq": rag.get("official_faq", []),
        "user_reviews": reviews,
    }


def import_products(dataset_dir: Path, db_path: Path, clean_path: Path) -> int:
    init_db()
    products: list[dict] = []
    for path in sorted(dataset_dir.glob("*/data/*.json")):
        with path.open("r", encoding="utf-8") as handle:
            products.append(normalize_product(json.load(handle), dataset_dir))

    conn = connect(db_path)
    try:
        conn.executescript(
            """
            DELETE FROM rag_chunks;
            DELETE FROM product_image_tags;
            DELETE FROM product_reviews;
            DELETE FROM product_faqs;
            DELETE FROM product_skus;
            DELETE FROM products;
            """
        )
        for product in products:
            conn.execute(
                """
                INSERT INTO products(id, title, brand, category, subcategory, price, rating, image_path, marketing_description)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    product["id"],
                    product["title"],
                    product["brand"],
                    product["category"],
                    product["subcategory"],
                    product["price"],
                    product["rating"],
                    product["image_path"],
                    product["marketing_description"],
                ),
            )
            for sku in product["skus"]:
                properties = sku.get("properties", {})
                conn.execute(
                    """
                    INSERT INTO product_skus(id, product_id, sku_name, properties_json, price, stock)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sku["sku_id"],
                        product["id"],
                        sku_name(properties),
                        json.dumps(properties, ensure_ascii=False),
                        float(sku.get("price", product["price"])),
                        int(sku.get("stock", 20)),
                    ),
                )
            for faq in product["official_faq"]:
                conn.execute(
                    "INSERT INTO product_faqs(product_id, question, answer) VALUES (?, ?, ?)",
                    (product["id"], faq.get("question", ""), faq.get("answer", "")),
                )
            for review in product["user_reviews"]:
                conn.execute(
                    "INSERT INTO product_reviews(product_id, nickname, rating, content) VALUES (?, ?, ?, ?)",
                    (
                        product["id"],
                        review.get("nickname", "匿名用户"),
                        float(review.get("rating", 4)),
                        review.get("content", ""),
                    ),
                )
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
        conn.commit()
    finally:
        conn.close()

    clean_path.parent.mkdir(parents=True, exist_ok=True)
    with clean_path.open("w", encoding="utf-8") as handle:
        json.dump(products, handle, ensure_ascii=False, indent=2)
    build_thumbnails(
        dataset_dir=dataset_dir,
        db_path=db_path,
        output_dir=ROOT / "data" / "uploads" / "product_thumbnails",
    )
    return len(products)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="../app/ecommerce_agent_dataset")
    parser.add_argument("--db", default="./data/smartshop.db")
    parser.add_argument("--clean", default="./data/products_clean.json")
    args = parser.parse_args()
    count = import_products(Path(args.dataset), Path(args.db), Path(args.clean))
    print(f"Imported {count} products into {args.db}")


if __name__ == "__main__":
    main()
