from __future__ import annotations

import csv
import gzip
import json
import math
import random
import re
import shutil
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = ROOT / "app" / "ecommerce_agent_dataset"
ABO_DIR = ROOT.parent / "data" / "abo"
META_DIR = ABO_DIR / "metadata"
DOWNLOAD_DIR = ABO_DIR / "downloaded_images"
MANIFEST_PATH = ABO_DIR / "selected_abo_100.json"
ATTRIBUTION_PATH = DATASET_DIR / "ABO_ATTRIBUTION.json"
PREVIEW_PATH = DATASET_DIR / "_abo_products_preview.jpg"
S3_BASE = "https://amazon-berkeley-objects.s3.amazonaws.com"
USER_AGENT = "SmartShopAIDataCuration/0.1"


CATEGORY_TARGETS = {
    "home": {
        "folder": "5_家居百货",
        "category": "家居百货",
        "prefix": "p_home",
        "subcategories": {
            "台灯": ["lamp", "lighting", "light"],
            "收纳": ["basket", "storage", "organizer", "box", "container", "bin"],
            "杯具": ["mug", "cup", "glass", "tumbler"],
            "厨房小件": ["cutting board", "utensil", "kitchen", "bowl", "plate"],
            "花器": ["vase", "planter", "plant pot", "pot"],
            "软装": ["pillow", "cushion", "throw"],
        },
        "keywords": [
            "lamp", "lighting", "basket", "storage", "organizer", "mug", "cup", "glass",
            "cutting board", "utensil", "kitchen", "vase", "planter", "pillow", "cushion",
            "home", "housewares", "decor", "bath", "bowl", "plate", "tray", "clock",
        ],
    },
    "pet": {
        "folder": "6_宠物用品",
        "category": "宠物用品",
        "prefix": "p_pet",
        "subcategories": {
            "喂食饮水": ["pet bowl", "dog bowl", "cat bowl", "feeder", "waterer"],
            "牵引用品": ["leash", "collar", "harness"],
            "玩具": ["dog toy", "cat toy", "pet toy", "chew toy"],
            "外出用品": ["pet carrier", "carrier"],
            "清洁护理": ["pet brush", "grooming", "nail clipper"],
            "猫咪用品": ["cat scratch", "litter", "cat bed"],
        },
        "keywords": [
            "pet", "dog", "cat", "leash", "collar", "harness", "pet bowl", "dog bowl",
            "cat bowl", "feeder", "pet carrier", "cat scratch", "litter", "grooming",
            "chew toy", "pet toy", "aquarium", "bird feeder",
        ],
    },
    "office": {
        "folder": "7_办公文具",
        "category": "办公文具",
        "prefix": "p_office",
        "subcategories": {
            "本册纸品": ["notebook", "notepad", "journal", "planner"],
            "书写工具": ["pen", "pencil", "marker", "highlighter"],
            "桌面整理": ["desk organizer", "file organizer", "letter tray"],
            "装订工具": ["stapler", "binder clip", "paper clip", "tape dispenser"],
            "测量裁剪": ["ruler", "scissors", "paper cutter"],
            "文件管理": ["folder", "binder", "clipboard"],
        },
        "keywords": [
            "notebook", "notepad", "journal", "planner", "pen", "pencil", "marker",
            "highlighter", "stapler", "paper clip", "binder clip", "desk organizer",
            "file organizer", "folder", "binder", "clipboard", "ruler", "scissors",
            "calculator", "tape dispenser", "office", "stationery",
        ],
    },
    "travel": {
        "folder": "8_旅行户外",
        "category": "旅行户外",
        "prefix": "p_travel",
        "subcategories": {
            "背包": ["backpack", "daypack"],
            "旅行箱包": ["suitcase", "luggage", "duffel", "travel bag"],
            "饮水保温": ["water bottle", "thermos", "tumbler"],
            "户外照明": ["flashlight", "lantern"],
            "露营装备": ["tent", "sleeping bag", "camping"],
            "徒步装备": ["hiking", "trekking", "boot"],
        },
        "keywords": [
            "backpack", "daypack", "suitcase", "luggage", "duffel", "travel bag",
            "water bottle", "thermos", "flashlight", "lantern", "tent", "sleeping bag",
            "camping", "hiking", "trekking", "outdoor", "compass", "binoculars",
        ],
    },
}

BAD_TERMS = [
    "book", "dvd", "cd", "poster", "calendar", "software", "kindle", "video game",
    "shirt", "dress", "costume", "shoes", "sandal", "jewelry", "watch", "food",
    "supplement", "vitamin", "makeup", "cosmetic", "skin care", "cell phone",
    "laptop", "television", "camera", "replacement part", "refill", "pack of",
    "phone case", "mobile cover", "cellular phone case", "screen protector",
    "amazonbasics logo", "logo",
]

TYPE_CATEGORY = {
    "home": {
        "HOME", "HOME_BED_AND_BATH", "HOME_FURNITURE_AND_DECOR", "CHAIR", "SOFA",
        "TABLE", "KITCHEN", "LIGHT_FIXTURE", "LAMP", "DRINKING_CUP", "SHELF",
        "PILLOW", "PLANTER", "DESK", "RUG", "STOOL_SEATING", "OTTOMAN",
        "CABINET", "BED", "STORAGE_HOOK", "FOOD_SERVICE_SUPPLY",
    },
    "pet": {"PET_SUPPLIES"},
    "office": {"OFFICE_PRODUCTS", "STORAGE_BINDER"},
    "travel": {"SUITCASE", "BACKPACK", "LUGGAGE"},
}


def request_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=90) as response:
        return response.read()


def download_file(key: str, target: Path) -> None:
    if target.exists() and target.stat().st_size > 0:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(request_bytes(f"{S3_BASE}/{key}"))


def ensure_metadata() -> None:
    META_DIR.mkdir(parents=True, exist_ok=True)
    download_file("images/metadata/images.csv.gz", META_DIR / "images.csv.gz")
    for suffix in "0123456789abcdef":
        download_file(f"listings/metadata/listings_{suffix}.json.gz", META_DIR / f"listings_{suffix}.json.gz")


def lang_value(values: Any, preferred: tuple[str, ...] = ("zh_CN", "en_US", "")) -> str:
    if isinstance(values, str):
        return values
    if not isinstance(values, list):
        return ""
    for lang in preferred:
        for item in values:
            if not isinstance(item, dict):
                continue
            if lang and item.get("language_tag") != lang:
                continue
            value = item.get("value")
            if value:
                return str(value)
    for item in values:
        if isinstance(item, dict) and item.get("value"):
            return str(item["value"])
    return ""


def product_type(record: dict[str, Any]) -> str:
    values = record.get("product_type") or []
    if values and isinstance(values[0], dict):
        return str(values[0].get("value", ""))
    return ""


def nodes_text(record: dict[str, Any]) -> str:
    parts: list[str] = []
    for node in record.get("node") or []:
        if isinstance(node, dict):
            parts.append(str(node.get("node_name") or node.get("path") or ""))
    return " ".join(parts)


def searchable_text(record: dict[str, Any]) -> str:
    fields = [
        lang_value(record.get("item_name")),
        lang_value(record.get("brand")),
        lang_value(record.get("bullet_point")),
        lang_value(record.get("product_description")),
        lang_value(record.get("item_keywords")),
        product_type(record),
        nodes_text(record),
    ]
    return " ".join(fields).lower()


def is_bad(text: str) -> bool:
    return any(term in text for term in BAD_TERMS)


def match_category(record: dict[str, Any]) -> tuple[str, int] | None:
    text = searchable_text(record)
    type_text = product_type(record).upper()
    if is_bad(text):
        return None
    for key, types in TYPE_CATEGORY.items():
        if type_text in types:
            score = 10 + sum(1 for kw in CATEGORY_TARGETS[key]["keywords"] if kw in text)
            return key, score
    return None


def choose_subcategory(category_key: str, record: dict[str, Any]) -> str:
    text = searchable_text(record)
    subcategories = CATEGORY_TARGETS[category_key]["subcategories"]
    for subcat, keywords in subcategories.items():
        if any(keyword in text for keyword in keywords):
            return subcat
    return "其他"


def load_image_index() -> dict[str, str]:
    index: dict[str, str] = {}
    with gzip.open(META_DIR / "images.csv.gz", "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            image_id = row.get("image_id", "")
            path = row.get("path", "")
            if image_id and path:
                index[image_id] = path
    return index


def iter_listings() -> Any:
    for path in sorted(META_DIR.glob("listings_*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    yield json.loads(line)


def image_quality_ok(path: Path) -> bool:
    try:
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image)
            width, height = image.size
            if width < 180 or height < 180:
                return False
            ratio = max(width / height, height / width)
            return ratio <= 2.4
    except Exception:
        return False


def normalize_image(src: Path, dst: Path) -> None:
    with Image.open(src) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        canvas = Image.new("RGB", (640, 640), "white")
        image.thumbnail((590, 590), Image.Resampling.LANCZOS)
        canvas.paste(image, ((640 - image.width) // 2, (640 - image.height) // 2))
        dst.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(dst, "JPEG", quality=90, optimize=True)


def price_for(category_key: str, idx: int) -> float:
    bases = {
        "home": [39, 49, 59, 69, 79, 89, 99, 129, 159],
        "pet": [19, 29, 35, 45, 59, 79, 99, 129, 169],
        "office": [8, 12, 18, 24, 29, 35, 49, 69, 89],
        "travel": [29, 39, 49, 69, 89, 119, 159, 199, 299],
    }
    return float(bases[category_key][idx % len(bases[category_key])])


def build_reviews(title: str, subcat: str) -> list[dict[str, Any]]:
    names = ["林小北", "陈一然", "周予安", "顾清禾", "赵念念"]
    return [
        {"nickname": names[0], "rating": 5, "content": f"{title}主体和图片一致，{subcat}日常使用够方便，整体质感不错。"},
        {"nickname": names[1], "rating": 5, "content": "包装完整，商品没有明显瑕疵，尺寸和预期差不多。"},
        {"nickname": names[2], "rating": 4, "content": "做工比较规整，价格可以接受，如果颜色选择更多会更好。"},
        {"nickname": names[3], "rating": 4, "content": "使用体验稳定，适合基础需求，不算特别惊艳但很实用。"},
        {"nickname": names[4], "rating": 3, "content": "细节还有提升空间，重度使用建议选择更高规格版本。"},
    ]


def clean_title(title: str, fallback: str) -> str:
    title = re.sub(r"\s+", " ", title).strip()
    title = re.sub(r"\bAmazon Brand\s*[-–]\s*", "", title, flags=re.IGNORECASE)
    return title[:80] or fallback


def build_product(record: dict[str, Any], category_key: str, idx: int, product_id: str, image_path: str) -> dict[str, Any]:
    config = CATEGORY_TARGETS[category_key]
    subcat = choose_subcategory(category_key, record)
    title = clean_title(lang_value(record.get("item_name"), ("zh_CN", "en_US", "")), f"{config['category']}{subcat}商品")
    brand = clean_title(lang_value(record.get("brand"), ("zh_CN", "en_US", "")), "Amazon.com")
    price = price_for(category_key, idx)
    description = clean_title(lang_value(record.get("product_description"), ("zh_CN", "en_US", "")) or lang_value(record.get("bullet_point"), ("zh_CN", "en_US", "")), "")
    if not description:
        description = f"{title}来自 Amazon Berkeley Objects 商品目录图片数据，适合非商业演示、检索和数据蒸馏测试。图片保留商品主体，已统一处理为白底方图。"
    return {
        "product_id": product_id,
        "title": title,
        "brand": brand,
        "category": config["category"],
        "sub_category": subcat,
        "base_price": price,
        "image_path": image_path,
        "skus": [
            {"sku_id": f"s_{product_id}_1", "properties": {"规格": "标准款"}, "price": price, "stock": 32},
            {"sku_id": f"s_{product_id}_2", "properties": {"规格": "升级款"}, "price": round(price * 1.18, 1), "stock": 26},
            {"sku_id": f"s_{product_id}_3", "properties": {"规格": "组合款"}, "price": round(price * 1.36, 1), "stock": 18},
        ],
        "rag_knowledge": {
            "marketing_description": description[:420],
            "official_faq": [
                {"question": f"{title}适合什么场景？", "answer": f"适合{config['category']}中的{subcat}需求，建议根据尺寸、材质和使用频率选择规格。"},
                {"question": "图片来源是什么？", "answer": "图片来自 Amazon Berkeley Objects (ABO) 数据集，按非商业数据演示用途处理，并保留来源署名信息。"},
                {"question": "是否可以商用？", "answer": "本项目按非商业用途处理。ABO 公开页面存在 CC BY 与 CC BY-NC 描述差异，因此这里按更严格的 CC BY-NC 口径使用。"},
            ],
            "user_reviews": build_reviews(title, subcat),
        },
    }


def select_records(image_index: dict[str, str]) -> list[dict[str, Any]]:
    selected: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_images: set[str] = set()
    for record in iter_listings():
        if all(len(selected[key]) >= 25 for key in CATEGORY_TARGETS):
            break
        image_id = record.get("main_image_id")
        if not image_id or image_id not in image_index or image_id in seen_images:
            continue
        match = match_category(record)
        if not match:
            continue
        category_key, _score = match
        if len(selected[category_key]) >= 25:
            continue
        image_key = image_index[image_id]
        if image_key.startswith("images/original/"):
            original_key = image_key
        elif image_key.startswith("images/small/"):
            original_key = image_key.replace("images/small/", "images/original/")
        else:
            original_key = f"images/original/{image_key}"
        local_raw = DOWNLOAD_DIR / original_key.removeprefix("images/original/")
        try:
            download_file(original_key, local_raw)
        except Exception:
            small_key = original_key.replace("images/original/", "images/small/")
            local_raw = DOWNLOAD_DIR / small_key.removeprefix("images/small/")
            try:
                download_file(small_key, local_raw)
            except Exception:
                continue
        if not image_quality_ok(local_raw):
            continue
        seen_images.add(image_id)
        selected[category_key].append({"record": record, "image_id": image_id, "image_key": original_key, "local_raw": str(local_raw)})
        print(f"{category_key}: {len(selected[category_key])}/25", flush=True)
    missing = {key: 25 - len(selected[key]) for key in CATEGORY_TARGETS if len(selected[key]) < 25}
    if missing:
        raise RuntimeError(f"Not enough ABO matches: {missing}")
    rows: list[dict[str, Any]] = []
    for key in CATEGORY_TARGETS:
        rows.extend(selected[key][:25])
    return rows


def write_dataset(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    counters = defaultdict(int)
    for row in rows:
        record = row["record"]
        category_key, _score = match_category(record) or ("home", 1)
        counters[category_key] += 1
        idx = counters[category_key]
        config = CATEGORY_TARGETS[category_key]
        product_id = f"{config['prefix']}_{idx:03d}"
        folder = config["folder"]
        image_rel = f"{folder}/images/{product_id}_abo.jpg"
        image_path = DATASET_DIR / folder / "images" / f"{product_id}_abo.jpg"
        json_path = DATASET_DIR / folder / "data" / f"{product_id}.json"
        normalize_image(Path(row["local_raw"]), image_path)
        product = build_product(record, category_key, idx - 1, product_id, image_rel)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(product, ensure_ascii=False, indent=2), encoding="utf-8")
        old_virtual = image_path.with_name(f"{product_id}_virtual.jpg")
        old_virtual.unlink(missing_ok=True)
        manifest.append({
            "product_id": product_id,
            "category": config["category"],
            "sub_category": product["sub_category"],
            "title": product["title"],
            "brand": product["brand"],
            "abo_item_id": record.get("item_id", ""),
            "abo_main_image_id": row["image_id"],
            "abo_image_key": row["image_key"],
            "local_image": str(image_path),
            "license_policy": "ABO public dataset; use under attribution, treated here as CC BY-NC 4.0 because AWS Registry lists CC BY-NC 4.0.",
            "attribution": "Credit for data/images: Amazon.com. Dataset: Amazon Berkeley Objects (ABO).",
        })
    return manifest


def make_preview(manifest: list[dict[str, Any]]) -> None:
    thumbs: list[Image.Image] = []
    for item in manifest:
        with Image.open(item["local_image"]) as image:
            thumb = image.convert("RGB")
            thumb.thumbnail((124, 124), Image.Resampling.LANCZOS)
            tile = Image.new("RGB", (132, 132), "white")
            tile.paste(thumb, ((132 - thumb.width) // 2, (132 - thumb.height) // 2))
            thumbs.append(tile)
    cols = 10
    rows = math.ceil(len(thumbs) / cols)
    sheet = Image.new("RGB", (cols * 132, rows * 132), "white")
    for index, thumb in enumerate(thumbs):
        sheet.paste(thumb, ((index % cols) * 132, (index // cols) * 132))
    sheet.save(PREVIEW_PATH, "JPEG", quality=88, optimize=True)


def main() -> None:
    random.seed(42)
    ensure_metadata()
    image_index = load_image_index()
    rows = select_records(image_index)
    manifest = write_dataset(rows)
    ABO_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    ATTRIBUTION_PATH.write_text(json.dumps({
        "dataset": "Amazon Berkeley Objects (ABO)",
        "source": "https://amazon-berkeley-objects.s3.amazonaws.com/index.html",
        "aws_registry": "https://registry.opendata.aws/amazon-berkeley-objects/",
        "license_note": "ABO pages currently show CC BY 4.0 in the S3 index and CC BY-NC 4.0 in AWS Registry. This project treats the images as CC BY-NC 4.0 and uses them for non-commercial purposes only.",
        "required_credit": "Credit for the data/images: Amazon.com. Credit for dataset builders as listed by ABO.",
        "items": manifest,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    make_preview(manifest)
    counts = defaultdict(int)
    for item in manifest:
        counts[item["category"]] += 1
    print(json.dumps({"selected": len(manifest), "counts": dict(counts), "preview": str(PREVIEW_PATH)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
