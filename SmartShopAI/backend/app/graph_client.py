from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parents[1]


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return
    load_dotenv(BASE_DIR / ".env", override=False)


_load_dotenv_if_available()


@dataclass
class GraphQueryResult:
    product_ids: list[str]
    context: str
    fallback_used: bool
    reason: str | None = None


class GraphClient:
    def __init__(self, timeout_seconds: float = 5.0) -> None:
        self.uri = os.getenv("NEO4J_URI")
        self.user = os.getenv("NEO4J_USER")
        self.password = os.getenv("NEO4J_PASSWORD")
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.uri and self.user and self.password)

    def _driver(self):
        if not self.configured:
            return None, "Neo4j is not configured"
        try:
            from neo4j import GraphDatabase  # type: ignore
        except Exception as exc:
            return None, f"neo4j package is unavailable: {exc}"
        try:
            driver = GraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password),
                connection_timeout=self.timeout_seconds,
            )
            driver.verify_connectivity()
            return driver, None
        except Exception as exc:
            LOGGER.warning("Neo4j connection failed: %s", exc)
            return None, str(exc)

    def run_write(self, cypher: str, **params: Any) -> bool:
        driver, reason = self._driver()
        if driver is None:
            LOGGER.info("Neo4j write skipped: %s", reason)
            return False
        try:
            with driver.session() as session:
                session.run(cypher, **params).consume()
            return True
        except Exception as exc:
            LOGGER.warning("Neo4j write failed: %s", exc)
            return False
        finally:
            driver.close()

    def query_products(self, constraints: dict[str, Any], limit: int = 10) -> GraphQueryResult:
        driver, reason = self._driver()
        if driver is None:
            return GraphQueryResult([], "", True, reason)
        categories = constraints.get("categories") or []
        brands = constraints.get("brands") or []
        features = constraints.get("features") or []
        scenarios = constraints.get("scenarios") or []
        budget_max = constraints.get("budget_max")
        try:
            with driver.session() as session:
                rows = session.run(
                    """
                    MATCH (p:Product)
                    OPTIONAL MATCH (p)-[:BELONGS_TO]->(c:Category)
                    OPTIONAL MATCH (p)-[:MADE_BY]->(b:Brand)
                    OPTIONAL MATCH (p)-[:HAS_FEATURE]->(f:Feature)
                    OPTIONAL MATCH (p)-[:SUITABLE_FOR|BETTER_FOR]->(s:Scenario)
                    WITH p,
                         collect(DISTINCT c.name) AS categories,
                         collect(DISTINCT b.name) AS brands,
                         collect(DISTINCT f.name) AS features,
                         collect(DISTINCT s.name) AS scenarios
                    WHERE ($budget_max IS NULL OR p.price <= $budget_max)
                      AND (size($categories) = 0 OR any(x IN categories WHERE x IN $categories) OR p.category IN $categories OR p.subcategory IN $categories)
                      AND (size($brands) = 0 OR any(x IN brands WHERE x IN $brands) OR p.brand IN $brands)
                      AND (size($features) = 0 OR any(x IN features WHERE x IN $features))
                      AND (size($scenarios) = 0 OR any(x IN scenarios WHERE x IN $scenarios))
                    OPTIONAL MATCH (p)-[r:SIMILAR_TO|COMPATIBLE_WITH|BETTER_FOR|SUITABLE_FOR|HAS_FEATURE|BELONGS_TO|MADE_BY]->(n)
                    RETURN p.id AS product_id,
                           p.title AS title,
                           p.brand AS brand,
                           p.category AS category,
                           p.subcategory AS subcategory,
                           p.price AS price,
                           collect(DISTINCT type(r) + ' -> ' + coalesce(n.name, n.title, n.id, '')) AS relations
                    ORDER BY p.rating DESC, p.price ASC
                    LIMIT $limit
                    """,
                    budget_max=budget_max,
                    categories=categories,
                    brands=brands,
                    features=features,
                    scenarios=scenarios,
                    limit=limit,
                ).data()
            product_ids = [row["product_id"] for row in rows if row.get("product_id")]
            context_lines = []
            for row in rows:
                context_lines.append(
                    f"{row['product_id']} {row.get('title')} | {row.get('brand')} | "
                    f"{row.get('category')}/{row.get('subcategory')} | 价格 {row.get('price')} | "
                    f"关系: {'; '.join(row.get('relations') or [])}"
                )
            return GraphQueryResult(product_ids, "\n".join(context_lines), False)
        except Exception as exc:
            LOGGER.warning("Neo4j query failed: %s", exc)
            return GraphQueryResult([], "", True, str(exc))
        finally:
            driver.close()

    def reset_graph(self) -> bool:
        return self.run_write("MATCH (n) DETACH DELETE n")


def get_graph_client() -> GraphClient:
    return GraphClient()
