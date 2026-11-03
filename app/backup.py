"""Nightly backups: a dated copy of the database plus a mirror of the photos folder.

Layout in the backup folder:
    db/crochet-2026-11-03-0300.db   (the last `keep` are kept)
    media/...                        (new and changed photos are copied; nothing is deleted from here)
    secret.key
"""

import json
import shutil
import sqlite3
import threading
from datetime import datetime, timedelta

from sqlmodel import Session

from .auth import get_setting, set_setting
from .config import settings
from .db import engine

_lock = threading.Lock()


def _mirror(src, dest) -> int:
    copied = 0
    for path in src.rglob("*"):
        if not path.is_file():
            continue
        target = dest / path.relative_to(src)
        st = path.stat()
        if target.exists() and target.stat().st_size == st.st_size and target.stat().st_mtime >= st.st_mtime:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied += 1
    return copied


def run_backup() -> dict:
    """Back up now. Never raises: the result (ok or the error) is recorded for the admin page."""
    with _lock:
        started = datetime.now()
        result = {"at": started.isoformat(timespec="seconds"), "dest": str(settings.backup_dir)}
        try:
            db_dir = settings.backup_dir / "db"
            db_dir.mkdir(parents=True, exist_ok=True)
            snapshot = db_dir / f"crochet-{started:%Y-%m-%d-%H%M}.db"
            # SQLite's own backup API copies a consistent snapshot even while the app is writing.
            with sqlite3.connect(settings.db_path) as src, sqlite3.connect(snapshot) as dst:
                src.backup(dst)
            for old in sorted(db_dir.glob("crochet-*.db"))[:-max(1, settings.backup_keep)]:
                old.unlink(missing_ok=True)
            copied = _mirror(settings.media_dir, settings.backup_dir / "media") if settings.media_dir.exists() else 0
            key = settings.db_path.parent / "secret.key"
            if key.exists():
                shutil.copy2(key, settings.backup_dir / "secret.key")
            result.update(ok=True, message=f"Saved {snapshot.name} and {copied} new or changed file{'s' if copied != 1 else ''}.",
                          seconds=round((datetime.now() - started).total_seconds(), 1))
        except Exception as exc:  # disk full, OneDrive offline, permissions…
            result.update(ok=False, message=f"{type(exc).__name__}: {exc}")
        with Session(engine) as session:
            set_setting(session, "last_backup", json.dumps(result))
            session.commit()
        return result


def last_backup() -> dict | None:
    with Session(engine) as session:
        raw = get_setting(session, "last_backup")
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def _next_run(now: datetime) -> datetime:
    try:
        hour, minute = (int(x) for x in settings.backup_time.split(":"))
    except ValueError:
        hour, minute = 3, 0
    run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return run if run > now else run + timedelta(days=1)


def _scheduler(stop: threading.Event) -> None:
    # If the laptop was off at backup time, catch up shortly after it starts.
    last = last_backup()
    if not last or datetime.fromisoformat(last["at"]) < datetime.now() - timedelta(hours=26):
        if stop.wait(120):
            return
        run_backup()
    target = _next_run(datetime.now())
    while not stop.is_set():
        remaining = (target - datetime.now()).total_seconds()
        if remaining <= 0:  # also true right after the laptop wakes up past backup time
            run_backup()
            target = _next_run(datetime.now() + timedelta(seconds=1))
            continue
        # Wake at least hourly so sleep or a clock change can't make it miss a night.
        if stop.wait(min(remaining, 3600)):
            return


def start_scheduler() -> threading.Event:
    stop = threading.Event()
    threading.Thread(target=_scheduler, args=(stop,), name="nightly-backup", daemon=True).start()
    return stop
