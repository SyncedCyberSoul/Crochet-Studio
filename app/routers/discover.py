import asyncio
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session, select

from ..db import get_session
from ..deps import current_user
from ..discover import feed_list, gather
from ..models import Idea, User
from ..templating import templates

router = APIRouter(prefix="/discover")


@router.get("")
def discover(request: Request, q: str = "", user: User = Depends(current_user)):
    # The page loads instantly; the feeds arrive a moment later (they come from the internet).
    return templates.TemplateResponse(request, "discover.html", {
        "q": q, "pinterest_url": "https://www.pinterest.com/search/pins/?q=" + quote_plus(f"crochet {q}".strip()),
    })


@router.get("/items")
async def items(request: Request, q: str = "", user: User = Depends(current_user), session: Session = Depends(get_session)):
    feeds = feed_list(session)
    found, errors = await asyncio.to_thread(gather, feeds)
    if q.strip():
        words = q.lower().split()
        found = [i for i in found if all(w in f"{i.title} {i.summary}".lower() for w in words)]
    saved = set(session.exec(select(Idea.source_url).where(Idea.user_id == user.id, Idea.source_url != "")).all())
    return templates.TemplateResponse(request, "_discover_items.html", {
        "items": found, "errors": errors, "saved": saved, "q": q, "feed_count": len(feeds),
    })
