"""Profiles, the admin logon, and signed session cookies (stdlib only)."""

import base64
import hashlib
import hmac
import json
import secrets
import time
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


MIN_PASSWORD = 6


def password_problem(new: str, confirm: str) -> str:
    """Why a new password can't be used, or '' if it's fine."""
    if len(new) < MIN_PASSWORD:
        return f"Use at least {MIN_PASSWORD} characters."
    if new != confirm:
        return "The two passwords didn't match."
    return ""


# ---------- lockout: stop guessing ----------

LOCK_AFTER = 8  # wrong passwords...
LOCK_WINDOW = 15 * 60  # ...within this many seconds locks that profile (or the admin logon) for the rest of it
_failures: dict[str, list[float]] = {}


def lock_remaining(key: str) -> int:
    """Seconds until `key` (e.g. 'user:3' or 'admin') may try again; 0 if not locked."""
    now = time.time()
    recent = [t for t in _failures.get(key, []) if now - t < LOCK_WINDOW]
    _failures[key] = recent
    return int(LOCK_WINDOW - (now - recent[0])) + 1 if len(recent) >= LOCK_AFTER else 0


def record_failure(key: str) -> None:
    _failures.setdefault(key, []).append(time.time())


def clear_failures(key: str) -> None:
    _failures.pop(key, None)


def lock_message(seconds: int) -> str:
    minutes = max(1, round(seconds / 60))
    return f"Too many wrong passwords. Try again in {minutes} minute{'s' if minutes != 1 else ''}."


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
