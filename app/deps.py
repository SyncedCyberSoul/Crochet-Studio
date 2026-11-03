"""Request-scoped helpers shared by the routers."""

from typing import TypeVar

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from .db import get_session
from .models import User

T = TypeVar("T")


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def current_user(request: Request, session: Session = Depends(get_session)) -> User:
    """The profile in use. The auth middleware has already redirected visitors without one."""
    signed_in = getattr(request.state, "user", None)
    user = session.get(User, signed_in.id) if signed_in else None
    if not user:
        raise HTTPException(401, "Pick a profile first")
    return user


def owned(session: Session, model: type[T], obj_id: int, user: User) -> T:
    """Fetch a row that belongs to this profile, or 404 (never reveal other profiles' things)."""
    obj = session.get(model, obj_id)
    if not obj or getattr(obj, "user_id", None) != user.id:
        raise HTTPException(404, f"{model.__name__} not found")
    return obj
