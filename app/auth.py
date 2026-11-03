"""Profiles, the admin logon, and signed session cookies (stdlib only)."""

import base64
import hashlib
import hmac
import json
import secrets
from typing import Optional

from fastapi import Request
from fastapi.responses import Response
from sqlmodel import Session

from .config import settings
from .models import AppSetting

COOKIE = "cs_session"
MAX_AGE = 60 * 60 * 24 * 120  # 120 days: she shouldn't have to pick her profile often


def _load_secret() -> bytes:
    path = settings.db_path.parent / "secret.key"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(secrets.token_hex(32))
    return bytes.fromhex(path.read_text().strip())


SECRET = _load_secret()


# ---------- passwords ----------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: Optional[str]) -> bool:
    if not stored:
        return False
    try:
        _, salt, digest = stored.split("$")
        candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
    except ValueError:
        return False
    return hmac.compare_digest(candidate.hex(), digest)


# ---------- signed cookie ----------

def _sign(payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def read_session(request: Request) -> dict:
    raw = request.cookies.get(COOKIE, "")
    body, _, sig = raw.partition(".")
    if not body or not hmac.compare_digest(hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest(), sig):
        return {}
    try:
        return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except ValueError:
        return {}


def write_session(request: Request, response: Response, data: dict) -> None:
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(COOKIE, _sign(data), max_age=MAX_AGE, httponly=True, samesite="lax", secure=secure)


def is_local_request(request: Request) -> bool:
    """True only for a browser on this machine, not traffic arriving through a tunnel or proxy."""
    proxied = any(h in request.headers for h in ("cf-connecting-ip", "x-forwarded-for", "forwarded"))
    host = request.client.host if request.client else ""
    return not proxied and host in ("127.0.0.1", "::1", "localhost")


# ---------- app settings ----------

def get_setting(session: Session, key: str, default: str = "") -> str:
    row = session.get(AppSetting, key)
    return row.value if row else default


def set_setting(session: Session, key: str, value: str) -> None:
    row = session.get(AppSetting, key) or AppSetting(key=key)
    row.value = value
    session.add(row)
