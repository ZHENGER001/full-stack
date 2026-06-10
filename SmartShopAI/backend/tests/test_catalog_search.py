from __future__ import annotations

import sqlite3
import unittest

from app.catalog import list_products


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE products (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            brand TEXT NOT NULL,
            category TEXT NOT NULL,
            subcategory TEXT NOT NULL,
            price REAL NOT NULL,
            rating REAL NOT NULL,
            image_path TEXT,
            marketing_description TEXT
        );
        CREATE TABLE product_reviews (
            id INTEGER PRIMARY KEY,
            product_id TEXT,
            nickname TEXT,
            content TEXT
        );
        CREATE TABLE product_skus (
            id TEXT PRIMARY KEY,
            product_id TEXT,
            sku_name TEXT,
            stock INTEGER
        );
        CREATE TABLE product_faqs (
            id INTEGER PRIMARY KEY,
            product_id TEXT,
            question TEXT,
            answer TEXT
        );
        """
    )
    conn.executemany(
        """
        INSERT INTO products (
            id, title, brand, category, subcategory, price, rating, image_path, marketing_description
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "laptop",
                "Apple MacBook Pro 14英寸 高性能笔记本电脑",
                "Apple",
                "数码电子",
                "笔记本电脑",
                12999,
                4.9,
                "",
                "适合办公，也可以和平板协同。",
            ),
            (
                "tablet",
                "华为 MatePad Pro 12.6英寸 平板电脑",
                "HUAWEI",
                "数码电子",
                "平板电脑",
                3999,
                5.0,
                "",
                "轻办公平板，不等同于完整笔记本。",
            ),
            (
                "laptop_bag",
                "城市双肩包",
                "测试品牌",
                "旅行户外",
                "背包",
                299,
                5.0,
                "",
                "可放 16 英寸笔记本电脑，适合通勤。",
            ),
            (
                "commuter_bag",
                "通勤背包",
                "测试品牌",
                "旅行户外",
                "背包",
                199,
                4.0,
                "",
                "日常出行使用。",
            ),
        ],
    )
    return conn


class CatalogSearchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_conn()

    def tearDown(self) -> None:
        self.conn.close()

    def test_laptop_query_requires_laptop_subcategory(self) -> None:
        products, total = list_products(self.conn, keyword="笔记本", limit=20)

        self.assertEqual(total, 1)
        self.assertEqual([product.id for product in products], ["laptop"])
        self.assertEqual({product.subcategory for product in products}, {"笔记本电脑"})

    def test_tablet_query_requires_tablet_subcategory(self) -> None:
        products, total = list_products(self.conn, keyword="平板", limit=20)

        self.assertEqual(total, 1)
        self.assertEqual([product.id for product in products], ["tablet"])
        self.assertEqual({product.subcategory for product in products}, {"平板电脑"})

    def test_scene_term_can_match_description_but_ranks_behind_title(self) -> None:
        products, total = list_products(self.conn, keyword="通勤", limit=20)

        self.assertEqual(total, 2)
        self.assertEqual([product.id for product in products], ["commuter_bag", "laptop_bag"])


if __name__ == "__main__":
    unittest.main()
