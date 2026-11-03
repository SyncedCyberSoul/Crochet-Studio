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
    backup_dir: Path
    backup_time: str  # "HH:MM", local time
    backup_keep: int  # how many database snapshots to keep


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
    backup = raw.get("backup", {})
    db_path = _resolve(base, paths.get("db", "data/crochet.db"))
    if backup.get("dir"):
        backup_dir = _resolve(base, backup["dir"])
    elif os.environ.get("OneDrive"):  # Windows sets this when OneDrive is signed in
        backup_dir = Path(os.environ["OneDrive"]) / "Crochet Studio Backups"
    else:
        backup_dir = db_path.parent / "backups"
    return Settings(
        config_path=config_path,
        host=server.get("host", "127.0.0.1"),
        port=int(server.get("port", 8000)),
        db_path=db_path,
        media_dir=_resolve(base, paths.get("media", "data/media")),
        full_px=int(photos.get("full_px", 2400)),
        thumb_px=int(photos.get("thumb_px", 480)),
        backup_dir=backup_dir,
        backup_time=str(backup.get("time", "03:00")),
        backup_keep=int(backup.get("keep", 14)),
    )


settings = load_settings()
