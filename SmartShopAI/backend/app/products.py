import json
from pathlib import Path
from urllib.parse import quote

from app.database import db_session
from app.models import ProductDetail, ProductSummary


def image_url(image_path: str) -> str:
    normalized_path = image_path.replace("\\", "/")
    return f"/assets/{quote(normalized_path)}"


def _product_summary(row: dict[str, object]) -> ProductSummary:
    path = str(row["image_path"])
    return ProductSummary(
        product_id=str(row["product_id"]),
        title=str(row["title"]),
        brand=str(row["brand"]),
        category=str(row["category"]),
        sub_category=str(row["sub_category"]),
        base_price=float(row["base_price"]),
        image_path=path,
        image_url=image_url(path),
    )


def sync_products_from_dataset(dataset_path: Path) -> int:
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset path does not exist: {dataset_path}")

    product_files = sorted(dataset_path.glob("*/data/*.json"))
    with db_session() as db:
        for file_path in product_files:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
            rag = payload.get("rag_knowledge") or {}
            db.execute(
                """
                INSERT INTO products (
                    product_id, title, brand, category, sub_category, base_price,
                    image_path, marketing_description, raw_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(product_id) DO UPDATE SET
                    title = excluded.title,
                    brand = excluded.brand,
                    category = excluded.category,
                    sub_category = excluded.sub_category,
                    base_price = excluded.base_price,
                    image_path = excluded.image_path,
                    marketing_description = excluded.marketing_description,
                    raw_json = excluded.raw_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    payload["product_id"],
                    payload["title"],
                    payload["brand"],
                    payload["category"],
                    payload["sub_category"],
                    float(payload["base_price"]),
                    payload["image_path"],
                    rag.get("marketing_description", ""),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            db.execute("DELETE FROM skus WHERE product_id = ?", (payload["product_id"],))
            for sku in payload.get("skus", []):
                db.execute(
                    """
                    INSERT INTO skus (sku_id, product_id, properties_json, price)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        sku["sku_id"],
                        payload["product_id"],
                        json.dumps(sku.get("properties", {}), ensure_ascii=False),
                        float(sku["price"]),
                    ),
                )
    return len(product_files)


def list_products(
    category: str | None = None,
    sub_category: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[ProductSummary], int]:
    clauses: list[str] = []
    params: list[object] = []
    if category:
        clauses.append("category = ?")
        params.append(category)
    if sub_category:
        clauses.append("sub_category = ?")
        params.append(sub_category)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with db_session() as db:
        total = db.execute(f"SELECT COUNT(*) AS count FROM products {where}", params).fetchone()["count"]
        rows = db.execute(
            f"""
            SELECT product_id, title, brand, category, sub_category, base_price, image_path
            FROM products
            {where}
            ORDER BY product_id
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
    return [_product_summary(row) for row in rows], int(total)


def search_products(query: str, limit: int = 20, offset: int = 0) -> tuple[list[ProductSummary], int]:
    pattern = f"%{query}%"
    params = [pattern, pattern, pattern, pattern]
    where = """
    WHERE title LIKE ?
       OR brand LIKE ?
       OR category LIKE ?
       OR sub_category LIKE ?
    """
    with db_session() as db:
        total = db.execute(f"SELECT COUNT(*) AS count FROM products {where}", params).fetchone()["count"]
        rows = db.execute(
            f"""
            SELECT product_id, title, brand, category, sub_category, base_price, image_path
            FROM products
            {where}
            ORDER BY product_id
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
    return [_product_summary(row) for row in rows], int(total)


def get_product(product_id: str) -> ProductDetail | None:
    with db_session() as db:
        row = db.execute("SELECT * FROM products WHERE product_id = ?", (product_id,)).fetchone()
        if not row:
            return None
        skus = db.execute(
            "SELECT sku_id, properties_json, price FROM skus WHERE product_id = ? ORDER BY sku_id",
            (product_id,),
        ).fetchall()

    raw = json.loads(str(row["raw_json"]))
    summary = _product_summary(row)
    return ProductDetail(
        **summary.model_dump(),
        skus=[
            {
                "sku_id": str(sku["sku_id"]),
                "properties": json.loads(str(sku["properties_json"])),
                "price": float(sku["price"]),
            }
            for sku in skus
        ],
        marketing_description=str(row["marketing_description"]),
        rag_knowledge=raw.get("rag_knowledge") or {},
    )


def list_categories() -> list[dict[str, object]]:
    with db_session() as db:
        rows = db.execute(
            """
            SELECT category, sub_category, COUNT(*) AS count
            FROM products
            GROUP BY category, sub_category
            ORDER BY category, sub_category
            """
        ).fetchall()

    grouped: dict[str, dict[str, object]] = {}
    for row in rows:
        category = str(row["category"])
        item = grouped.setdefault(category, {"name": category, "sub_categories": [], "product_count": 0})
        item["sub_categories"].append(str(row["sub_category"]))
        item["product_count"] = int(item["product_count"]) + int(row["count"])
    return list(grouped.values())
