from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parents[1]


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


class Settings(BaseModel):
    app_name: str = Field(default="SmartShopAI Backend")
    app_env: str = Field(default="development")
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8000)
    database_path: Path = Field(default=BASE_DIR / "data" / "smartshop.db")
    dataset_path: Path = Field(default=BASE_DIR.parent / "app" / "ecommerce_agent_dataset")
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])
    upload_dir: Path = Field(default=BASE_DIR / "data" / "uploads")

    @property
    def allowed_origins(self) -> list[str]:
        return self.cors_origins

    @property
    def db_path(self) -> Path:
        return self.database_path


@lru_cache
def get_settings() -> Settings:
    env = _load_env_file(BASE_DIR / ".env")

    def value(name: str, default: str | None = None) -> str | None:
        return env.get(name, default)

    database_path = Path(value("DATABASE_PATH", str(BASE_DIR / "data" / "smartshop.db")) or "")
    dataset_path = Path(value("DATASET_PATH", str(BASE_DIR.parent / "app" / "ecommerce_agent_dataset")) or "")
    upload_dir = Path(value("UPLOAD_DIR", str(BASE_DIR / "data" / "uploads")) or "")
    cors_origins = [
        origin.strip()
        for origin in (value("CORS_ORIGINS", "*") or "*").split(",")
        if origin.strip()
    ]

    return Settings(
        app_name=value("APP_NAME", "SmartShopAI Backend") or "SmartShopAI Backend",
        app_env=value("APP_ENV", "development") or "development",
        host=value("HOST", "127.0.0.1") or "127.0.0.1",
        port=int(value("PORT", "8000") or "8000"),
        database_path=(BASE_DIR / database_path).resolve() if not database_path.is_absolute() else database_path,
        dataset_path=(BASE_DIR / dataset_path).resolve() if not dataset_path.is_absolute() else dataset_path,
        cors_origins=cors_origins,
        upload_dir=(BASE_DIR / upload_dir).resolve() if not upload_dir.is_absolute() else upload_dir,
    )
