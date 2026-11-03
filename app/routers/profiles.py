import asyncio

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session, select

from ..auth import check_password, hash_password, read_session, write_session
from ..db import get_session
from ..deps import current_user, redirect
from ..models import AVATAR_COLORS, User
from ..templating import templates
from ..whatsnew import LATEST, WELCOME_PROFILE

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
    if user.has_password and not check_password(str(form.get("password", "")), user.password_hash):
        await asyncio.sleep(0.6)  # slow down guessing
        return _picker(request, session, error_for=user.id, error="That password didn't match.", status=401)
    if not user.seen_version and user.name != WELCOME_PROFILE:
        user.seen_version = LATEST  # a first visit isn't "new features"; only Jillian gets the welcome
        session.commit()
    target = str(form.get("next") or "/")
    if not target.startswith("/") or target.startswith("//"):
        target = "/"  # only ever return to a page on this site
    response = redirect(target)
    write_session(request, response, {**read_session(request), "uid": user.id})
    return response


@router.post("/profiles")
async def add_profile(request: Request, session: Session = Depends(get_session)):
    form = await request.form()
    name = _clean_name(form.get("name"))
    if not name:
        return _picker(request, session, add_error="Give the profile a name.", status=400)
    if session.exec(select(User).where(User.name == name)).first():
        return _picker(request, session, add_error=f"There's already a profile called {name}.", status=400)
    color = str(form.get("color") or "")
    user = User(name=name, color=color if color in AVATAR_COLORS else AVATAR_COLORS[len(name) % len(AVATAR_COLORS)],
                seen_version=0 if name == WELCOME_PROFILE else LATEST)
    password = str(form.get("password", ""))
    if password:
        user.password_hash = hash_password(password)
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

    action = form.get("password_action", "keep")
    if action in ("set", "remove") and user.has_password and not check_password(str(form.get("current", "")), user.password_hash):
        error = "Your current password didn't match, so the password wasn't changed."
    elif action == "set":
        new, confirm = str(form.get("new", "")), str(form.get("confirm", ""))
        if not new:
            error = "Type the new password."
        elif new != confirm:
            error = "The two new passwords didn't match."
        else:
            user.password_hash = hash_password(new)
    elif action == "remove":
        user.password_hash = None

    session.commit()
    if error:
        return templates.TemplateResponse(
            request, "me.html", {"user": user, "colors": AVATAR_COLORS, "error": error}, status_code=400
        )
    return redirect("/me?saved=1")
