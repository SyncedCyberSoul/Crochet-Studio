import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlmodel import Session, select
from starlette.datastructures import FormData, UploadFile

from .. import media
from ..db import get_session
from ..deps import current_user, owned, redirect
from ..models import Pattern, PatternStep, Project, StepDone, User, utcnow
from ..patternparse import parse_dicts
from ..terms import both
from ..templating import templates

router = APIRouter()

MAX_PDF_BYTES = 40 * 1024 * 1024
DIFFICULTIES = ["", "Beginner", "Easy", "Intermediate", "Experienced"]


def _steps_json(pattern: Pattern) -> list[dict]:
    return [
        {"id": s.id, "section": s.section, "label": s.label, "text": s.text, "stitch_count": s.stitch_count}
        for s in pattern.steps
    ]


def _int_or_none(value) -> Optional[int]:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _apply_steps(pattern: Pattern, raw: str) -> None:
    """Update steps in place (keeps checked-off progress for steps that still exist)."""
    try:
        rows = json.loads(raw or "[]")
    except ValueError:
        return
    existing = {s.id: s for s in pattern.steps}
    keep: list[PatternStep] = []
    for position, row in enumerate(r for r in rows if isinstance(r, dict) and str(r.get("text", "")).strip()):
        step = existing.get(_int_or_none(row.get("id"))) or PatternStep(pattern_id=pattern.id)
        step.position = position
        step.section = str(row.get("section", "")).strip()[:80]
        step.label = str(row.get("label", "")).strip()[:40]
        step.text = str(row.get("text", "")).strip()
        step.stitch_count = _int_or_none(row.get("stitch_count"))
        keep.append(step)
    pattern.steps = keep


async def _save_pdf(pattern: Pattern, upload) -> str:
    if not isinstance(upload, UploadFile) or not upload.filename:
        return ""
    data = await upload.read(MAX_PDF_BYTES + 1)
    if len(data) > MAX_PDF_BYTES or not data.startswith(b"%PDF"):
        return "That file isn't a PDF (or is over 40 MB), so it wasn't attached."
    folder = media.settings.media_dir / f"patterns/{pattern.id}"
    folder.mkdir(parents=True, exist_ok=True)
    media.delete_files(pattern.pdf_file)
    name = f"pattern-{utcnow().strftime('%Y%m%d%H%M%S')}.pdf"
    (folder / name).write_bytes(data)
    pattern.pdf_file = f"patterns/{pattern.id}/{name}"
    return ""


def _apply_form(pattern: Pattern, form: FormData) -> None:
    pattern.title = " ".join(str(form.get("title", "")).split()) or "Untitled pattern"
    for field in ("designer", "source_url", "notes", "raw_text"):
        setattr(pattern, field, str(form.get(field, "")).strip())
    if not pattern.source_url.startswith(("http://", "https://")):
        pattern.source_url = ""
    pattern.difficulty = str(form.get("difficulty", "")) if form.get("difficulty") in DIFFICULTIES else ""
    pattern.terms = "uk" if form.get("terms") == "uk" else "us"
    pattern.updated_at = utcnow()


def _form(request: Request, pattern: Pattern, error: str = ""):
    return templates.TemplateResponse(request, "pattern_form.html", {
        "pattern": pattern, "steps": _steps_json(pattern) if pattern.id else [],
        "difficulties": DIFFICULTIES, "error": error,
    })


# ---------- list / create ----------

@router.get("/patterns")
def pattern_list(request: Request, user: User = Depends(current_user), session: Session = Depends(get_session)):
    patterns = session.exec(select(Pattern).where(Pattern.user_id == user.id).order_by(Pattern.updated_at.desc())).all()
    step_counts = dict(session.exec(
        select(PatternStep.pattern_id, func.count(PatternStep.id)).group_by(PatternStep.pattern_id)
    ).all())
    projects = session.exec(select(Project).where(Project.user_id == user.id, Project.pattern_id != None)).all()  # noqa: E711
    used = {}
    for p in projects:
        used.setdefault(p.pattern_id, []).append(p)
    return templates.TemplateResponse(request, "patterns.html", {
        "patterns": patterns, "step_counts": step_counts, "used": used,
    })


@router.get("/patterns/new")
def new_pattern(request: Request, user: User = Depends(current_user)):
    return _form(request, Pattern(title=""))


@router.post("/patterns/parse")
async def parse_text(request: Request, user: User = Depends(current_user)):
    body = await request.json()
    return JSONResponse({"steps": parse_dicts(str(body.get("text", "")), bool(body.get("expand", True)))})


@router.post("/patterns")
async def create_pattern(request: Request, user: User = Depends(current_user), session: Session = Depends(get_session)):
    form = await request.form()
    pattern = Pattern(title="", user_id=user.id)
    _apply_form(pattern, form)
    session.add(pattern)
    session.flush()
    _apply_steps(pattern, str(form.get("steps_json", "")))
    note = await _save_pdf(pattern, form.get("pdf"))
    session.commit()
    return redirect(f"/patterns/{pattern.id}" + ("?pdf_error=1" if note else ""))


# ---------- detail / edit ----------

@router.get("/patterns/{pattern_id}")
def pattern_detail(request: Request, pattern_id: int, pdf_error: int = 0,
                   user: User = Depends(current_user), session: Session = Depends(get_session)):
    pattern = owned(session, Pattern, pattern_id, user)
    projects = session.exec(select(Project).where(Project.pattern_id == pattern.id, Project.user_id == user.id)).all()
    steps = [{**s, "text_by_terms": both(s["text"], pattern.terms)} for s in _steps_json(pattern)]
    return templates.TemplateResponse(request, "pattern_detail.html", {
        "pattern": pattern, "steps": steps, "projects": projects, "pdf_error": pdf_error,
    })


@router.get("/patterns/{pattern_id}/edit")
def edit_pattern(request: Request, pattern_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)):
    return _form(request, owned(session, Pattern, pattern_id, user))


@router.post("/patterns/{pattern_id}")
async def update_pattern(request: Request, pattern_id: int,
                         user: User = Depends(current_user), session: Session = Depends(get_session)):
    pattern = owned(session, Pattern, pattern_id, user)
    form = await request.form()
    _apply_form(pattern, form)
    _apply_steps(pattern, str(form.get("steps_json", "")))
    if form.get("remove_pdf"):
        media.delete_files(pattern.pdf_file)
        pattern.pdf_file = ""
    note = await _save_pdf(pattern, form.get("pdf"))
    session.commit()
    return redirect(f"/patterns/{pattern.id}" + ("?pdf_error=1" if note else ""))


@router.post("/patterns/{pattern_id}/delete")
def delete_pattern(pattern_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)):
    pattern = owned(session, Pattern, pattern_id, user)
    for project in session.exec(select(Project).where(Project.pattern_id == pattern.id)).all():
        project.pattern_id = None
        project.current_step_id = None
    session.delete(pattern)
    session.commit()
    media.delete_folder(f"patterns/{pattern_id}")
    return redirect("/patterns")


# ---------- follow along (per project) ----------

@router.get("/projects/{project_id}/follow")
def follow(request: Request, project_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)):
    project = owned(session, Project, project_id, user)
    pattern = session.get(Pattern, project.pattern_id) if project.pattern_id else None
    if not pattern:
        return redirect(f"/projects/{project.id}/edit")
    done = set(session.exec(select(StepDone.step_id).where(StepDone.project_id == project.id)).all())
    steps = [
        {
            "id": s.id, "section": s.section, "label": s.label, "count": s.stitch_count,
            "text": both(s.text, pattern.terms), "done": s.id in done,
        }
        for s in pattern.steps
    ]
    state = {
        "projectId": project.id,
        "steps": steps,
        "current": project.current_step_id,
        "rows": project.row_counter or 0,
        "stitches": project.stitch_counter or 0,
        "terms": pattern.terms,
    }
    return templates.TemplateResponse(request, "follow.html", {"project": project, "pattern": pattern, "state": state})


@router.post("/projects/{project_id}/progress")
async def save_progress(request: Request, project_id: int,
                        user: User = Depends(current_user), session: Session = Depends(get_session)):
    project = owned(session, Project, project_id, user)
    body = await request.json()
    pattern_steps = set()
    if project.pattern_id:
        pattern_steps = set(session.exec(select(PatternStep.id).where(PatternStep.pattern_id == project.pattern_id)).all())

    if "step_id" in body and "done" in body:
        step_id = _int_or_none(body["step_id"])
        if step_id not in pattern_steps:
            raise HTTPException(400, "Step isn't part of this project's pattern")
        row = session.get(StepDone, (project.id, step_id))
        if body["done"] and not row:
            session.add(StepDone(project_id=project.id, step_id=step_id))
        elif not body["done"] and row:
            session.delete(row)
    if "current" in body:
        current = _int_or_none(body["current"])
        project.current_step_id = current if current in pattern_steps else None
    for key, field in (("rows", "row_counter"), ("stitches", "stitch_counter")):
        if key in body:
            value = _int_or_none(body[key])
            setattr(project, field, max(0, min(value or 0, 100000)))
    project.updated_at = utcnow()
    session.commit()
    return {"ok": True}
