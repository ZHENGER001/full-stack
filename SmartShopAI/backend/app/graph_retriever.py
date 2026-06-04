from __future__ import annotations

import os
from typing import Any

from .config import BASE_DIR, _load_env_file


def _env_value(name: str, default: str | None = None) -> str | None:
    env_file = _load_env_file(BASE_DIR / ".env")
    return os.getenv(name) or env_file.get(name) or default


def graph_backend_name() -> str:
    return (_env_value("GRAPH_BACKEND", "none") or "none").strip().lower()


def expand_related_product_ids(
    conn,
    seed_product_ids: list[str],
    query: str = "",
    top_k: int = 12,
) -> list[dict[str, Any]]:
    backend = graph_backend_name()
    seeds = [product_id for product_id in dict.fromkeys(seed_product_ids) if product_id]
    if not seeds or top_k <= 0 or backend in {"", "none"}:
        return []
    if backend == "local":
        return _local_graph_expand(conn, seeds, query, top_k)
    if backend == "neo4j":
        return _neo4j_graph_expand(seeds, query, top_k)
    return []


def _local_graph_expand(conn, seed_product_ids: list[str], query: str, top_k: int) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in seed_product_ids)
    seed_rows = conn.execute(
        f"SELECT id, brand, category, subcategory, price FROM products WHERE id IN ({placeholders})",
        seed_product_ids,
    ).fetchall()
    if not seed_rows:
        return []

    categories = {row["category"] for row in seed_rows if row["category"]}
    subcategories = {row["subcategory"] for row in seed_rows if row["subcategory"]}
    brands = {row["brand"] for row in seed_rows if row["brand"]}
    seed_prices = [float(row["price"] or 0) for row in seed_rows]
    avg_price = sum(seed_prices) / max(len(seed_prices), 1)
    wants_cheaper = any(word in query for word in ["更便宜", "便宜一点", "低价", "平价", "学生党", "性价比"])

    rows = conn.execute(
        """
        SELECT p.id, p.brand, p.category, p.subcategory, p.price, COALESCE(SUM(s.stock), 0) AS stock
        FROM products p
        LEFT JOIN product_skus s ON s.product_id = p.id
        GROUP BY p.id
        """
    ).fetchall()
    results: list[dict[str, Any]] = []
    seed_set = set(seed_product_ids)
    for row in rows:
        if row["id"] in seed_set:
            continue
        score = 0.0
        if row["subcategory"] in subcategories:
            score += 5.0
        if row["category"] in categories:
            score += 3.0
        if row["brand"] in brands:
            score += 2.0
        price = float(row["price"] or 0)
        if avg_price > 0:
            distance = abs(price - avg_price) / avg_price
            score += max(0.0, 2.0 * (1.0 - distance))
        if wants_cheaper and price <= avg_price:
            score += 3.0
        if float(row["stock"] or 0) > 0:
            score += 1.0
        if score <= 0:
            continue
        results.append({"product_id": row["id"], "score": round(score, 3), "source": "graph_local"})
    results.sort(key=lambda item: float(item["score"]), reverse=True)
    return results[:top_k]


def _neo4j_graph_expand(seed_product_ids: list[str], query: str, top_k: int) -> list[dict[str, Any]]:
    uri = _env_value("NEO4J_URI")
    user = _env_value("NEO4J_USER")
    password = _env_value("NEO4J_PASSWORD")
    if not uri or not user or not password:
        return []
    try:
        from neo4j import GraphDatabase  # type: ignore
    except Exception:
        return []

    wants_cheaper = any(word in query for word in ["更便宜", "便宜一点", "低价", "平价"])
    price_clause = "AND (seed.price IS NULL OR related.price <= seed.price)" if wants_cheaper else ""
    cypher = f"""
    UNWIND $seed_ids AS seed_id
    MATCH (seed:Product {{id: seed_id}})
    MATCH path = (seed)-[:SIMILAR_TO|SAME_CATEGORY|SAME_BRAND|BOUGHT_TOGETHER*1..2]-(related:Product)
    WHERE related.id <> seed.id {price_clause}
    RETURN related.id AS product_id, count(path) AS relation_count, max(length(path)) AS hops
    ORDER BY relation_count DESC, hops ASC
    LIMIT $top_k
    """
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session() as session:
            records = session.run(cypher, seed_ids=seed_product_ids, top_k=top_k)
            results = [
                {
                    "product_id": str(record["product_id"]),
                    "score": float(record["relation_count"]),
                    "source": "neo4j",
                }
                for record in records
                if record.get("product_id")
            ]
        driver.close()
        return results
    except Exception:
        return []
