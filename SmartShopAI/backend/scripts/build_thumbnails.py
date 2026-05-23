from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from PIL import Image


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def build_thumbnail(source: Path, target: Path, size: int, quality: int) -> bool:
    if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        image.thumbnail((size, size))
        image.convert("RGB").save(target, format="JPEG", quality=quality, optimize=True)
    return True


def build_thumbnails(dataset_dir: Path, db_path: Path, output_dir: Path, size: int = 360, quality: int = 82) -> tuple[int, int]:
    conn = connect(db_path)
    created = 0
    total = 0
    try:
        rows = conn.execute("SELECT id, image_path FROM products ORDER BY id").fetchall()
        for row in rows:
            source = dataset_dir / Path(row["image_path"])
            if not source.exists():
                continue
            total += 1
            target = output_dir / f"{row['id']}.jpg"
            if build_thumbnail(source, target, size, quality):
                created += 1
    finally:
        conn.close()
    return total, created


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="../app/ecommerce_agent_dataset")
    parser.add_argument("--db", default="./data/smartshop.db")
    parser.add_argument("--out", default="./data/uploads/product_thumbnails")
    parser.add_argument("--size", type=int, default=360)
    parser.add_argument("--quality", type=int, default=82)
    args = parser.parse_args()
    total, created = build_thumbnails(
        dataset_dir=Path(args.dataset),
        db_path=Path(args.db),
        output_dir=Path(args.out),
        size=args.size,
        quality=args.quality,
    )
    print(f"Prepared {total} thumbnails, generated {created}")


if __name__ == "__main__":
    main()
