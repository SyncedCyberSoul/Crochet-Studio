"""Admin logon: not a profile, just a password that unlocks managing every profile."""

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func
from sqlmodel import Session, select

from .. import media
from ..auth import check_password, get_setting, hash_password, is_local_request, read_session, set_setting, write_session
from ..db import get_session
from ..deps import redirect
from ..discover import DEFAULT_FEEDS, feed_list
from ..models import AVATAR_COLORS, Idea, Model3D, Pattern, Project, User
from ..templating import templates
from ..whatsnew import LATEST, WELCOME_PROFILE

router = APIRouter(prefix="/admin")

ADMIN_KEY = "admin_password_hash"


@router.get("/login")
def login_page(request: Request, session: Session = Depends(get_session)):
    if read_session(request).get("admin"):
        return redirect("/admin")
    configured = bool(get_setting(session, ADMIN_KEY))
    return templates.TemplateResponse(
        request, "admin_login.html", {"configured": configured, "local": is_local_request(request)}
    )


@router.post("/setup")
async def setup(request: Request, session: Session = Depends(get_session)):
    # Only the very first admin password, and only from a browser on the laptop itself.
    if get_setting(session, ADMIN_KEY) or not is_local_request(request):
        return redirect("/admin/login")
    form = await request.form()
    password, confirm = str(form.get("password", "")), str(form.get("confirm", ""))
    if len(password) < 6 or password != confirm:
        return templates.TemplateResponse(
            request, "admin_login.html",
            {"configured": False, "local": True, "error": "Use at least 6 characters, typed the same twice."},
            status_code=400,
        )
    set_setting(session, ADMIN_KEY, hash_password(password))
    session.commit()
    response = redirect("/admin")
    write_session(request, response, {**read_session(request), "admin": True})
    return response


@router.post("/login")
async def login(request: Request, session: Session = Depends(get_session)):
    form = await request.form()
    if not check_password(str(form.get("password", "")), get_setting(session, ADMIN_KEY)):
        await asyncio.sleep(0.8)
        return templates.TemplateResponse(
            request, "admin_login.html",
            {"configured": True, "local": is_local_request(request), "error": "Wrong admin password."},
            status_code=401,
        )
    response = redirect("/admin")
    write_session(request, response, {**read_session(request), "admin": True})
    return response


@router.post("/logout")
def logout(request: Request):
    response = redirect("/profiles")
    write_session(request, response, {})
    return response


# ---------- dashboard ----------

def _counts(session: Session, model) -> dict[int, int]:
    rows = session.exec(select(model.user_id, func.count(model.id)).group_by(model.user_id)).all()
    return {uid: n for uid, n in rows}


@router.get("")
def admin_home(request: Request, saved: str = "", error: str = "", session: Session = Depends(get_session)):
    users = session.exec(select(User).order_by(User.id)).all()
    counts = {name: _counts(session, model) for name, model in
              (("projects", Project), ("patterns", Pattern), ("ideas", Idea), ("models", Model3D))}
    feeds = "\n".join(f"{f['name']} | {f['url']}" for f in feed_list(session))
    return templates.TemplateResponse(request, "admin.html", {
        "users": users, "counts": counts, "colors": AVATAR_COLORS, "feeds_text": feeds,
        "saved": saved, "error": error, "default_feed_count": len(DEFAULT_FEEDS),
    })


@router.post("/users/{user_id}/view")
def view_as(request: Request, user_id: int, session: Session = Depends(get_session)):
    if not session.get(User, user_id):
        return redirect("/admin")
    response = redirect("/")
    write_session(request, response, {**read_session(request), "uid": user_id, "admin": True})
    return response


@router.post("/users")
async def create_user(request: Request, session: Session = Depends(get_session)):
    form = await request.form()
    name = " ".join(str(form.get("name", "")).split())[:40]
    if not name or session.exec(select(User).where(User.name == name)).first():
        return redirect("/admin?error=" + ("Name+is+required" if not name else "That+name+is+taken"))
    user = User(name=name, color=str(form.get("color") or AVATAR_COLORS[0]),
                seen_version=0 if name == WELCOME_PROFILE else LATEST)
    if form.get("password"):
        user.password_hash = hash_password(str(form["password"]))
    session.add(user)
    session.commit()
    return redirect("/admin?saved=Added+" + name)


@router.post("/users/{user_id}/update")
async def update_user(request: Request, user_id: int, session: Session = Depends(get_session)):
    user = session.get(User, user_id)
    if not user:
        return redirect("/admin")
    form = await request.form()
    name = " ".join(str(form.get("name", "")).split())[:40]
    if name and not session.exec(select(User).where(User.name == name, User.id != user.id)).first():
        user.name = name
    if form.get("color") in AVATAR_COLORS:
        user.color = str(form["color"])
    if form.get("clear_password"):
        user.password_hash = None
    elif form.get("password"):
        user.password_hash = hash_password(str(form["password"]))
    session.commit()
    return redirect(f"/admin?saved=Saved+{user.name}")


@router.post("/users/{user_id}/delete")
def delete_user(user_id: int, session: Session = Depends(get_session)):
    user = session.get(User, user_id)
    if not user:
        return redirect("/admin")
    folders = []
    for model, folder in ((Project, "projects"), (Pattern, "patterns"), (Idea, "ideas"), (Model3D, "models")):
        for row in session.exec(select(model).where(model.user_id == user_id)).all():
            folders.append(f"{folder}/{row.id}")
            session.delete(row)
    session.delete(user)
    session.commit()
    for folder in folders:
        media.delete_folder(folder)
    return redirect(f"/admin?saved=Deleted+{user.name}")


@router.post("/feeds")
async def save_feeds(request: Request, session: Session = Depends(get_session)):
    form = await request.form()
    feeds = []
    for line in str(form.get("feeds", "")).splitlines():
        name, sep, url = line.partition("|")
        url = (url if sep else name).strip()
        if url.startswith(("http://", "https://")):
            feeds.append({"name": (name.strip() if sep else "") or url, "url": url})
    set_setting(session, "discover_feeds", json.dumps(feeds))
    session.commit()
    return redirect("/admin?saved=Saved+Discover+feeds")


@router.post("/password")
async def change_password(request: Request, session: Session = Depends(get_session)):
    form = await request.form()
    if not check_password(str(form.get("current", "")), get_setting(session, ADMIN_KEY)):
        return redirect("/admin?error=Current+admin+password+was+wrong")
    new = str(form.get("new", ""))
    if len(new) < 6 or new != form.get("confirm"):
        return redirect("/admin?error=New+password+needs+6%2B+characters,+typed+the+same+twice")
    set_setting(session, ADMIN_KEY, hash_password(new))
    session.commit()
    return redirect("/admin?saved=Admin+password+changed")
