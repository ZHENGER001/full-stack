import sqlite3
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.config import get_settings
from app.search_document import build_search_keywords


def dict_factory(cursor: sqlite3.Cursor, row: tuple[object, ...]) -> dict[str, object]:
    return {column[0]: row[index] for index, column in enumerate(cursor.description)}


def get_connection() -> sqlite3.Connection:
    settings = get_settings()
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(settings.database_path)
    connection.row_factory = dict_factory
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    if settings.database_path.name != ":memory:":
        connection.execute("PRAGMA journal_mode = WAL")
    return connection


def get_db():
    return db_session()


@contextmanager
def db_session() -> Iterator[sqlite3.Connection]:
    connection = get_connection()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database() -> None:
    schema_path = Path(__file__).with_name("schema.sql")
    with db_session() as db:
        db.executescript(schema_path.read_text(encoding="utf-8"))
        _ensure_column(db, "orders", "address_id", "TEXT REFERENCES addresses(id) ON DELETE SET NULL")
        _ensure_column(db, "orders", "address_snapshot", "TEXT")
        _ensure_column(db, "chat_sessions", "last_query", "TEXT")
        _ensure_column(db, "chat_sessions", "last_recommended_product_ids", "TEXT")
        _ensure_column(db, "chat_sessions", "current_product_id", "TEXT")
        _ensure_column(db, "chat_sessions", "last_actions", "TEXT")
        _ensure_column(db, "chat_sessions", "structured_state_json", "TEXT")
        _ensure_query_cache_table(db)


def _ensure_column(db: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _ensure_query_cache_table(db: sqlite3.Connection) -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS query_cache_entries (
            cache_key TEXT PRIMARY KEY,
            query_text TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            hit_count INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    db.execute("CREATE INDEX IF NOT EXISTS idx_query_cache_expires ON query_cache_entries(expires_at)")


def _sku_name(properties: dict[str, str]) -> str:
    return " / ".join(str(value) for value in properties.values()) or "默认规格"


def _rating_from_reviews(reviews: list[dict]) -> float:
    if not reviews:
        return 4.5
    return round(sum(float(review.get("rating", 4)) for review in reviews) / len(reviews), 1)


def _normalize_product(raw: dict) -> dict:
    rag = raw.get("rag_knowledge", {})
    reviews = rag.get("user_reviews", [])
    return {
        "id": raw["product_id"],
        "title": raw["title"],
        "brand": raw.get("brand", ""),
        "category": raw.get("category", ""),
        "subcategory": raw.get("sub_category", ""),
        "price": float(raw.get("base_price", 0)),
        "rating": _rating_from_reviews(reviews),
        "image_path": raw.get("image_path", ""),
        "marketing_description": rag.get("marketing_description", ""),
        "skus": raw.get("skus", []),
        "official_faq": rag.get("official_faq", []),
        "user_reviews": reviews,
    }


def _build_product_chunks(product: dict) -> list[dict]:
    metadata = {
        "product_id": product["id"],
        "title": product["title"],
        "brand": product["brand"],
        "category": product["category"],
        "subcategory": product["subcategory"],
        "price": product["price"],
        "rating": product["rating"],
    }
    chunks = [
        {
            "id": f"{product['id']}:basic_info",
            "product_id": product["id"],
            "chunk_type": "basic_info",
            "content": (
                f"商品名称：{product['title']}\n"
                f"品牌：{product['brand']}\n"
                f"类目：{product['category']} > {product['subcategory']}\n"
                f"价格：{product['price']}\n"
                f"评分：{product['rating']}\n"
                f"搜索关键词：{build_search_keywords(product)}"
            ),
            "metadata_json": json.dumps({**metadata, "chunk_type": "basic_info"}, ensure_ascii=False),
        },
        {
            "id": f"{product['id']}:marketing",
            "product_id": product["id"],
            "chunk_type": "marketing",
            "content": product.get("marketing_description", ""),
            "metadata_json": json.dumps({**metadata, "chunk_type": "marketing"}, ensure_ascii=False),
        },
    ]
    return [chunk for chunk in chunks if chunk["content"]]


def import_dataset_if_empty() -> int:
    settings = get_settings()
    if not settings.dataset_path.exists():
        return 0

    files = sorted(settings.dataset_path.glob("*/data/*.json"))
    with db_session() as db:
        existing = db.execute("SELECT COUNT(*) AS total FROM products").fetchone()["total"]
        if existing:
            return int(existing)

        for path in files:
            product = _normalize_product(json.loads(path.read_text(encoding="utf-8")))
            db.execute(
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
                db.execute(
                    """
                    INSERT INTO product_skus(id, product_id, sku_name, properties_json, price, stock)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sku["sku_id"],
                        product["id"],
                        _sku_name(properties),
                        json.dumps(properties, ensure_ascii=False),
                        float(sku.get("price", product["price"])),
                        20,
                    ),
                )
            for faq in product["official_faq"]:
                db.execute(
                    "INSERT INTO product_faqs(product_id, question, answer) VALUES (?, ?, ?)",
                    (product["id"], faq.get("question", ""), faq.get("answer", "")),
                )
            for review in product["user_reviews"]:
                db.execute(
                    "INSERT INTO product_reviews(product_id, nickname, rating, content) VALUES (?, ?, ?, ?)",
                    (
                        product["id"],
                        review.get("nickname", "匿名用户"),
                        float(review.get("rating", 4)),
                        review.get("content", ""),
                    ),
                )
            for chunk in _build_product_chunks(product):
                db.execute(
                    "INSERT INTO rag_chunks(id, product_id, chunk_type, content, metadata_json) VALUES (?, ?, ?, ?, ?)",
                    (chunk["id"], chunk["product_id"], chunk["chunk_type"], chunk["content"], chunk["metadata_json"]),
                )
    return len(files)


def seed_initial_user_data() -> None:
    with db_session() as db:
        if not db.execute("SELECT COUNT(*) AS total FROM addresses").fetchone()["total"]:
            db.execute(
                """
                INSERT INTO addresses(id, receiver_name, phone, province, city, district, detail, is_default)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """,
                ("addr_default", "购物达人", "13800000000", "广东省", "深圳市", "南山区", "科技园科苑路 88 号",),
            )


def init_db() -> None:
    initialize_database()
    import_dataset_if_empty()
    seed_initial_user_data()
