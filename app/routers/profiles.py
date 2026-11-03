import asyncio

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session, select
from starlette.datastructures import UploadFile

from .. import media
from ..auth import (
    check_password, clear_failures, hash_password, lock_message, lock_remaining, password_problem, read_session,
    record_failure, write_session,
)
from ..db import get_session
from ..deps import current_user, redirect
from ..models import AVATAR_COLORS, User
from ..templating import templates
from ..whatsnew import LATEST, gets_welcome

router = APIRouter()


@router.post("/whatsnew/seen")
def whatsnew_seen(request: Request, user: User = Depends(current_user), session: Session = Depends(get_session)):
    user.seen_version = LATEST
    session.commit()
    if request.headers.get("content-type", "").startswith("application/json"):
        return {"ok": True}
    return redirect(request.headers.get("referer") or "/")


def _clean_name(raw) -> str:
    return " ".join(str(raw or "").split())[:40]


def _picker(request: Request, session: Session, status: int = 200, **extra):
    users = session.exec(select(User).order_by(User.id)).all()
    return templates.TemplateResponse(
        request, "profiles.html", {"users": users, "colors": AVATAR_COLORS, **extra}, status_code=status
    )


@router.get("/profiles")
def profiles(request: Request, session: Session = Depends(get_session)):
    return _picker(request, session)


@router.post("/profiles/{user_id}/enter")
async def enter_profile(request: Request, user_id: int, session: Session = Depends(get_session)):
    user = session.get(User, user_id)
    if not user:
        return redirect("/profiles")
    form = await request.form()
    lock_key = f"user:{user.id}"
    if user.has_password:
        if wait := lock_remaining(lock_key):
            return _picker(request, session, error_for=user.id, error=lock_message(wait), status=429)
        if not check_password(str(form.get("password", "")), user.password_hash):
            record_failure(lock_key)
            await asyncio.sleep(0.6)  # slow down guessing
            return _picker(request, session, error_for=user.id, error="That password didn't match.", status=401)
        clear_failures(lock_key)
    if not user.seen_version and not gets_welcome(user):
        user.seen_version = LATEST  # a first visit isn't "new features"; only the welcome profile gets a note
        session.commit()
    target = str(form.get("next") or "/")
    if not target.startswith("/") or target.startswith("//"):
        target = "/"  # only ever return to a page on this site
    response = redirect(target)
    write_session(request, response, {**read_session(request), "uid": user.id})
    return response


@router.post("/profiles")
async def add_profile(request: Request, session: Session = Depends(get_session)):
    # The site is reachable from the internet, so only the admin may add profiles.
    if not getattr(request.state, "is_admin", False):
        return _picker(request, session, add_error="Ask the admin to add a new profile.", status=403)
    form = await request.form()
    name = _clean_name(form.get("name"))
    if not name:
        return _picker(request, session, add_error="Give the profile a name.", status=400)
    if session.exec(select(User).where(User.name == name)).first():
        return _picker(request, session, add_error=f"There's already a profile called {name}.", status=400)
    password = str(form.get("password", ""))
    if problem := password_problem(password, str(form.get("confirm", ""))):
        return _picker(request, session, add_error=problem, status=400)
    color = str(form.get("color") or "")
    user = User(name=name, color=color if color in AVATAR_COLORS else AVATAR_COLORS[len(name) % len(AVATAR_COLORS)],
                password_hash=hash_password(password))
    session.add(user)
    session.commit()
    response = redirect("/")
    write_session(request, response, {**read_session(request), "uid": user.id})
    return response


@router.post("/logout")
def logout(request: Request):
    data = read_session(request)
    data.pop("uid", None)
    response = redirect("/profiles")
    write_session(request, response, data)
    return response


# ---------- first visit: every profile needs a password ----------

@router.get("/set-password")
def set_password_page(request: Request, user: User = Depends(current_user)):
    if user.has_password:
        return redirect("/")
    return templates.TemplateResponse(request, "set_password.html", {"user": user})


@router.post("/set-password")
async def set_password(request: Request, user: User = Depends(current_user), session: Session = Depends(get_session)):
    if user.has_password:
        return redirect("/")
    form = await request.form()
    if problem := password_problem(str(form.get("new", "")), str(form.get("confirm", ""))):
        return templates.TemplateResponse(request, "set_password.html", {"user": user, "error": problem}, status_code=400)
    user.password_hash = hash_password(str(form["new"]))
    session.commit()
    return redirect("/set-photo" if not user.avatar else "/")


@router.get("/set-photo")
def set_photo_page(request: Request, user: User = Depends(current_user)):
    return templates.TemplateResponse(request, "set_photo.html", {"user": user})


async def _store_avatar(user: User, form) -> str:
    upload = form.get("photo")
    if not isinstance(upload, UploadFile) or not upload.filename:
        return "Choose a photo first."
    try:
        new = media.save_avatar(await upload.read(), user.id)
    except media.NotAnImage:
        return "That file couldn't be read as a photo."
    media.delete_files(user.avatar)
    user.avatar = new
    return ""


@router.post("/set-photo")
async def set_photo(request: Request, user: User = Depends(current_user), session: Session = Depends(get_session)):
    if error := await _store_avatar(user, await request.form()):
        return templates.TemplateResponse(request, "set_photo.html", {"user": user, "error": error}, status_code=400)
    session.commit()
    return redirect("/")


@router.post("/me/photo")
async def change_photo(request: Request, user: User = Depends(current_user), session: Session = Depends(get_session)):
    form = await request.form()
    if form.get("remove"):
        media.delete_files(user.avatar)
        user.avatar = ""
    elif error := await _store_avatar(user, form):
        return templates.TemplateResponse(
            request, "me.html", {"user": user, "colors": AVATAR_COLORS, "error": error}, status_code=400
        )
    session.commit()
    return redirect("/me?saved=1")


# ---------- own profile ----------

@router.get("/me")
def me(request: Request, saved: str = "", user: User = Depends(current_user)):
    return templates.TemplateResponse(request, "me.html", {"user": user, "colors": AVATAR_COLORS, "saved": saved})


@router.post("/me")
async def update_me(request: Request, user: User = Depends(current_user), session: Session = Depends(get_session)):
    form = await request.form()
    error = ""
    name = _clean_name(form.get("name")) or user.name
    clash = session.exec(select(User).where(User.name == name, User.id != user.id)).first()
    if clash:
        error = f"There's already a profile called {name}."
    else:
        user.name = name
    color = str(form.get("color") or "")
    if color in AVATAR_COLORS:
        user.color = color

    if form.get("password_action") == "set":
        new, confirm = str(form.get("new", "")), str(form.get("confirm", ""))
        if user.has_password and not check_password(str(form.get("current", "")), user.password_hash):
            error = "Your current password didn't match, so the password wasn't changed."
        elif problem := password_problem(new, confirm):
            error = problem
        else:
            user.password_hash = hash_password(new)

    session.commit()
    if error:
        return templates.TemplateResponse(
            request, "me.html", {"user": user, "colors": AVATAR_COLORS, "error": error}, status_code=400
        )
    return redirect("/me?saved=1")
