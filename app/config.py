"""Settings loaded from config.toml (override the file location with CROCHET_CONFIG)."""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
BASE_DIR = APP_DIR.parent


@dataclass(frozen=True)
class Settings:
    config_path: Path
    host: str
    port: int
    db_path: Path
    media_dir: Path
    full_px: int
    thumb_px: int


def _resolve(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def load_settings() -> Settings:
    config_path = Path(os.environ.get("CROCHET_CONFIG", BASE_DIR / "config.toml")).resolve()
    raw = {}
    if config_path.exists():
        with config_path.open("rb") as f:
            raw = tomllib.load(f)
    base = config_path.parent
    server = raw.get("server", {})
    paths = raw.get("paths", {})
    photos = raw.get("photos", {})
    return Settings(
        config_path=config_path,
        host=server.get("host", "127.0.0.1"),
        port=int(server.get("port", 8000)),
        db_path=_resolve(base, paths.get("db", "data/crochet.db")),
        media_dir=_resolve(base, paths.get("media", "data/media")),
        full_px=int(photos.get("full_px", 2400)),
        thumb_px=int(photos.get("thumb_px", 480)),
    )


settings = load_settings()
