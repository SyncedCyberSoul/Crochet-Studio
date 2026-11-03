"""Saving uploaded photos: fix phone rotation, store a resized JPEG plus a square thumbnail."""

import io
import shutil
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from PIL import Image, ImageOps, UnidentifiedImageError

from .config import settings

BACKGROUND = (250, 245, 238)  # fills transparent areas of PNGs


class NotAnImage(ValueError):
    pass


@dataclass
class StoredImage:
    file: str
    thumb: str
    taken_on: Optional[date]


def _exif_date(img: Image.Image) -> Optional[date]:
    try:
        exif = img.getexif()
        raw = exif.get_ifd(0x8769).get(0x9003) or exif.get(0x0132)  # DateTimeOriginal, DateTime
        return datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S").date() if raw else None
    except (ValueError, KeyError, TypeError):
        return None


def _to_rgb(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, BACKGROUND)
        bg.paste(img, mask=img.getchannel("A"))
        return bg
    return img.convert("RGB")


def save_image(data: bytes, subdir: str) -> StoredImage:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise NotAnImage(str(exc)) from exc

    taken_on = _exif_date(img)
    img = _to_rgb(ImageOps.exif_transpose(img))

    folder = settings.media_dir / subdir
    folder.mkdir(parents=True, exist_ok=True)
    stem = uuid.uuid4().hex[:16]

    full = img.copy()
    full.thumbnail((settings.full_px, settings.full_px), Image.Resampling.LANCZOS)
    full.save(folder / f"{stem}.jpg", "JPEG", quality=88, optimize=True)

    thumb = ImageOps.fit(img, (settings.thumb_px, settings.thumb_px), Image.Resampling.LANCZOS)
    thumb.save(folder / f"{stem}_t.webp", "WEBP", quality=82)

    return StoredImage(file=f"{subdir}/{stem}.jpg", thumb=f"{subdir}/{stem}_t.webp", taken_on=taken_on)


def delete_files(*rel_paths: str) -> None:
    for rel in rel_paths:
        if rel:
            (settings.media_dir / rel).unlink(missing_ok=True)


def delete_folder(subdir: str) -> None:
    shutil.rmtree(settings.media_dir / subdir, ignore_errors=True)
