from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session, select

from ..db import get_session
from ..deps import current_user, redirect
from ..models import Stitch, User
from ..templating import templates

router = APIRouter(prefix="/stitches")


def glossary_json(session: Session) -> list[dict]:
    """For tap-to-explain in follow mode."""
    return [
        {"us": s.us, "uk": s.uk, "name": s.name, "how": s.how_to, "notes": s.notes}
        for s in session.exec(select(Stitch).order_by(Stitch.us)).all()
    ]


@router.get("")
def stitches(request: Request, user: User = Depends(current_user), session: Session = Depends(get_session)):
    rows = session.exec(select(Stitch).order_by(Stitch.name)).all()
    return templates.TemplateResponse(request, "stitches.html", {"stitches": rows})


@router.post("/{stitch_id}/notes")
async def save_notes(request: Request, stitch_id: int, user: User = Depends(current_user),
                     session: Session = Depends(get_session)):
    stitch = session.get(Stitch, stitch_id)
    if not stitch:
        raise HTTPException(404, "Stitch not found")
    form = await request.form()
    stitch.notes = str(form.get("notes", "")).strip()[:1000]
    session.commit()
    return redirect(f"/stitches#s{stitch.id}")


@router.post("")
async def add_stitch(request: Request, user: User = Depends(current_user), session: Session = Depends(get_session)):
    form = await request.form()
    us = str(form.get("us", "")).strip()[:30]
    if us:
        session.add(Stitch(us=us, uk=str(form.get("uk", "")).strip()[:30] or us,
                           name=str(form.get("name", "")).strip()[:80], how_to=str(form.get("how_to", "")).strip()[:1000]))
        session.commit()
    return redirect("/stitches")
