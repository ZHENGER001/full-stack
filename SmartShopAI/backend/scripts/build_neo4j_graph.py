from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.rag import extract_features, extract_scenarios, price_range  # noqa: E402
from scripts.build_rag_index import load_product  # noqa: E402


def load_env() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(ROOT / ".env", override=False)
    except Exception:
        pass


def product_text(product: dict) -> str:
    sku_text = " ".join(
        " ".join(str(value) for value in (sku.get("properties") or {}).values())
        for sku in product.get("skus", [])
    )
    faq_text = " ".join(
        f"{faq.get('question', '')} {faq.get('answer', '')}"
        for faq in product.get("official_faq", [])
    )
    review_text = " ".join(review.get("content", "") for review in product.get("user_reviews", []))
    return " ".join(
        [
            product.get("title", ""),
            product.get("brand", ""),
            product.get("category", ""),
            product.get("subcategory", ""),
            product.get("marketing_description", ""),
            sku_text,
            faq_text,
            review_text,
        ]
    )


def load_products(db_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [load_product(conn, row) for row in conn.execute("SELECT * FROM products ORDER BY id").fetchall()]
    finally:
        conn.close()


def merge_product(tx, product: dict) -> None:
    text = product_text(product)
    features = extract_features(text)
    scenarios = extract_scenarios(text)
    prange = price_range(float(product["price"]))
    tx.run(
        """
        MERGE (p:Product {id: $id})
        SET p.title = $title,
            p.brand = $brand,
            p.category = $category,
            p.subcategory = $subcategory,
            p.price = $price,
            p.rating = $rating
        MERGE (c:Category {name: $category})
        MERGE (sc:Category {name: $subcategory})
        MERGE (b:Brand {name: $brand})
        MERGE (r:PriceRange {name: $price_range})
        MERGE (p)-[:BELONGS_TO]->(c)
        MERGE (p)-[:BELONGS_TO]->(sc)
        MERGE (p)-[:MADE_BY]->(b)
        MERGE (p)-[:IN_PRICE_RANGE]->(r)
        """,
        id=product["id"],
        title=product["title"],
        brand=product["brand"],
        category=product["category"],
        subcategory=product["subcategory"],
        price=float(product["price"]),
        rating=float(product["rating"]),
        price_range=prange,
    )
    for sku in product.get("skus", []):
        props = sku.get("properties") or {}
        sku_name = " / ".join(str(value) for value in props.values()) or "默认规格"
        tx.run(
            """
            MATCH (p:Product {id: $product_id})
            MERGE (s:SKU {id: $sku_id})
            SET s.name = $sku_name,
                s.price = $price,
                s.stock = $stock,
                s.properties_json = $properties_json
            MERGE (p)-[:HAS_SKU]->(s)
            """,
            product_id=product["id"],
            sku_id=sku["sku_id"],
            sku_name=sku_name,
            price=float(sku.get("price", product["price"])),
            stock=int(sku.get("stock", 0)),
            properties_json=json.dumps(props, ensure_ascii=False),
        )
    for feature in features:
        tx.run(
            """
            MATCH (p:Product {id: $product_id})
            MERGE (f:Feature {name: $feature})
            MERGE (p)-[:HAS_FEATURE]->(f)
            """,
            product_id=product["id"],
            feature=feature,
        )
    for scenario in scenarios:
        tx.run(
            """
            MATCH (p:Product {id: $product_id})
            MERGE (s:Scenario {name: $scenario})
            MERGE (p)-[:SUITABLE_FOR]->(s)
            MERGE (p)-[:BETTER_FOR]->(s)
            """,
            product_id=product["id"],
            scenario=scenario,
        )
    for index, faq in enumerate(product.get("official_faq", [])[:6], start=1):
        tx.run(
            """
            MATCH (p:Product {id: $product_id})
            MERGE (f:FAQ {id: $faq_id})
            SET f.question = $question, f.answer = $answer
            MERGE (p)-[:HAS_FAQ]->(f)
            """,
            product_id=product["id"],
            faq_id=f"{product['id']}:faq:{index}",
            question=faq.get("question", ""),
            answer=faq.get("answer", ""),
        )
    for index, review in enumerate(product.get("user_reviews", [])[:5], start=1):
        tx.run(
            """
            MATCH (p:Product {id: $product_id})
            MERGE (r:Review {id: $review_id})
            SET r.nickname = $nickname, r.rating = $rating, r.content = $content
            MERGE (p)-[:HAS_REVIEW]->(r)
            """,
            product_id=product["id"],
            review_id=f"{product['id']}:review:{index}",
            nickname=review.get("nickname", "匿名用户"),
            rating=float(review.get("rating", 4)),
            content=review.get("content", ""),
        )


def merge_similarity(tx, products: list[dict]) -> None:
    groups: dict[tuple[str, str], list[dict]] = {}
    for product in products:
        key = (product["category"], price_range(float(product["price"])))
        groups.setdefault(key, []).append(product)
    for group in groups.values():
        sorted_group = sorted(group, key=lambda item: (item["brand"], item["price"]))
        for left, right in zip(sorted_group, sorted_group[1:]):
            tx.run(
                """
                MATCH (a:Product {id: $left_id})
                MATCH (b:Product {id: $right_id})
                MERGE (a)-[:SIMILAR_TO]->(b)
                MERGE (b)-[:SIMILAR_TO]->(a)
                """,
                left_id=left["id"],
                right_id=right["id"],
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="./data/smartshop.db")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    load_env()
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    password = os.getenv("NEO4J_PASSWORD")
    if not uri or not user or not password:
        raise SystemExit("NEO4J_URI, NEO4J_USER, and NEO4J_PASSWORD must be configured.")
    try:
        from neo4j import GraphDatabase  # type: ignore
    except Exception as exc:
        raise SystemExit(f"neo4j package is not installed or unavailable: {exc}") from exc

    products = load_products(args.db)
    driver = GraphDatabase.driver(uri, auth=(user, password), connection_timeout=10)
    try:
        driver.verify_connectivity()
        with driver.session() as session:
            if args.reset:
                session.run("MATCH (n) DETACH DELETE n").consume()
            for product in products:
                session.execute_write(merge_product, product)
            session.execute_write(merge_similarity, products)
        print(f"Built Neo4j graph for {len(products)} products")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
