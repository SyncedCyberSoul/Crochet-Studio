from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select
from starlette.datastructures import FormData, UploadFile

from .. import media
from ..db import get_session
from ..models import DASHBOARD_ORDER, Project, ProjectPhoto, ProjectStatus, ProjectTagLink, Tag, utcnow
from ..templating import templates

router = APIRouter()

TEXT_FIELDS = ("recipient", "hook_size", "gauge", "finished_size", "notes")


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _get_project(session: Session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


def _parse_date(value) -> Optional[date]:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _parse_tags(session: Session, raw: str) -> list[Tag]:
    names = []
    for part in raw.split(","):
        name = " ".join(part.split()).lower()
        if name and name not in names:
            names.append(name)
    existing = {t.name: t for t in session.exec(select(Tag).where(Tag.name.in_(names))).all()} if names else {}
    return [existing.get(n) or Tag(name=n) for n in names]


def _set_status(project: Project, status: ProjectStatus) -> None:
    project.status = status
    if status == ProjectStatus.in_progress and not project.start_date:
        project.start_date = date.today()
    if status == ProjectStatus.done and not project.finish_date:
        project.finish_date = date.today()


def _apply_form(session: Session, project: Project, form: FormData) -> None:
    project.name = " ".join(str(form.get("name", "")).split()) or "Untitled project"
    for field in TEXT_FIELDS:
        setattr(project, field, str(form.get(field, "")).strip())
    project.start_date = _parse_date(form.get("start_date"))
    project.finish_date = _parse_date(form.get("finish_date"))
    try:
        status = ProjectStatus(form.get("status", "idea"))
    except ValueError:
        status = ProjectStatus.idea
    _set_status(project, status)
    project.tags = _parse_tags(session, str(form.get("tags", "")))
    project.updated_at = utcnow()


async def _save_photos(session: Session, project: Project, files: list) -> int:
    """Store uploaded photos; returns how many files were rejected."""
    rejected = 0
    for upload in files:
        if not isinstance(upload, UploadFile) or not upload.filename:
            continue
        try:
            stored = media.save_image(await upload.read(), f"projects/{project.id}")
        except media.NotAnImage:
            rejected += 1
            continue
        project.photos.append(
            ProjectPhoto(file=stored.file, thumb=stored.thumb, taken_on=stored.taken_on or date.today())
        )
    if project.photos and not any(p.is_cover for p in project.photos):
        project.photos[0].is_cover = True
    return rejected


def _tag_options(session: Session) -> list[str]:
    return list(session.exec(select(Tag.name).join(ProjectTagLink).distinct().order_by(Tag.name)).all())


# ---------- dashboard ----------

@router.get("/")
def dashboard(request: Request, q: str = "", tag: str = "", session: Session = Depends(get_session)):
    q = q.strip()
    stmt = select(Project).options(selectinload(Project.tags), selectinload(Project.photos))
    if q:
        like = f"%{q}%"
        tag_hits = select(ProjectTagLink.project_id).join(Tag, Tag.id == ProjectTagLink.tag_id).where(Tag.name.ilike(like))
        stmt = stmt.where(or_(
            Project.name.ilike(like),
            Project.recipient.ilike(like),
            Project.notes.ilike(like),
            Project.hook_size.ilike(like),
            Project.id.in_(tag_hits),
        ))
    if tag:
        tagged = select(ProjectTagLink.project_id).join(Tag, Tag.id == ProjectTagLink.tag_id).where(Tag.name == tag)
        stmt = stmt.where(Project.id.in_(tagged))
    projects = session.exec(stmt.order_by(Project.updated_at.desc())).all()

    groups = {status: [] for status in DASHBOARD_ORDER}
    for p in projects:
        groups[p.status].append(p)

    tag_counts = session.exec(
        select(Tag.name, func.count(ProjectTagLink.project_id))
        .join(ProjectTagLink).group_by(Tag.name).order_by(Tag.name)
    ).all()
    total = session.exec(select(func.count(Project.id))).one()

    context = {"groups": groups, "q": q, "tag": tag, "tag_counts": tag_counts, "found": len(projects), "total": total}
    is_htmx = request.headers.get("HX-Request") == "true"
    return templates.TemplateResponse(request, "_results.html" if is_htmx else "dashboard.html", context)


# ---------- create / edit ----------

@router.get("/projects/new")
def new_project(request: Request, status: str = "planned", session: Session = Depends(get_session)):
    try:
        initial = ProjectStatus(status)
    except ValueError:
        initial = ProjectStatus.planned
    project = Project(name="", status=initial)
    return templates.TemplateResponse(
        request, "project_form.html", {"project": project, "tag_names": [], "all_tags": _tag_options(session)}
    )


@router.post("/projects")
async def create_project(request: Request, session: Session = Depends(get_session)):
    form = await request.form()
    project = Project(name="")
    _apply_form(session, project, form)
    session.add(project)
    session.flush()  # need the id for the photo folder
    rejected = await _save_photos(session, project, form.getlist("photos"))
    session.commit()
    return _redirect(f"/projects/{project.id}" + (f"?rejected={rejected}" if rejected else ""))


@router.get("/projects/{project_id}")
def project_detail(request: Request, project_id: int, rejected: int = 0, session: Session = Depends(get_session)):
    project = _get_project(session, project_id)
    return templates.TemplateResponse(request, "project_detail.html", {"project": project, "rejected": rejected})


@router.get("/projects/{project_id}/edit")
def edit_project(request: Request, project_id: int, session: Session = Depends(get_session)):
    project = _get_project(session, project_id)
    return templates.TemplateResponse(
        request,
        "project_form.html",
        {"project": project, "tag_names": [t.name for t in project.tags], "all_tags": _tag_options(session)},
    )


@router.post("/projects/{project_id}")
async def update_project(request: Request, project_id: int, session: Session = Depends(get_session)):
    project = _get_project(session, project_id)
    form = await request.form()
    _apply_form(session, project, form)
    rejected = await _save_photos(session, project, form.getlist("photos"))
    session.commit()
    return _redirect(f"/projects/{project.id}" + (f"?rejected={rejected}" if rejected else ""))


@router.post("/projects/{project_id}/status")
async def change_status(request: Request, project_id: int, session: Session = Depends(get_session)):
    project = _get_project(session, project_id)
    form = await request.form()
    try:
        _set_status(project, ProjectStatus(form.get("status")))
    except ValueError:
        raise HTTPException(400, "Unknown status")
    project.updated_at = utcnow()
    session.commit()
    return _redirect(f"/projects/{project.id}")


@router.post("/projects/{project_id}/delete")
def delete_project(project_id: int, session: Session = Depends(get_session)):
    project = _get_project(session, project_id)
    session.delete(project)
    session.commit()
    media.delete_folder(f"projects/{project_id}")
    return _redirect("/")


# ---------- photos ----------

@router.post("/projects/{project_id}/photos")
async def add_photos(request: Request, project_id: int, session: Session = Depends(get_session)):
    project = _get_project(session, project_id)
    form = await request.form()
    rejected = await _save_photos(session, project, form.getlist("photos"))
    project.updated_at = utcnow()
    session.commit()
    return _redirect(f"/projects/{project.id}" + (f"?rejected={rejected}" if rejected else "") + "#photos")


def _get_photo(session: Session, photo_id: int) -> ProjectPhoto:
    photo = session.get(ProjectPhoto, photo_id)
    if not photo:
        raise HTTPException(404, "Photo not found")
    return photo


@router.post("/photos/{photo_id}/cover")
def set_cover(photo_id: int, session: Session = Depends(get_session)):
    photo = _get_photo(session, photo_id)
    for p in photo.project.photos:
        p.is_cover = p.id == photo.id
    session.commit()
    return _redirect(f"/projects/{photo.project_id}#photos")


@router.post("/photos/{photo_id}/caption")
async def set_caption(request: Request, photo_id: int, session: Session = Depends(get_session)):
    photo = _get_photo(session, photo_id)
    form = await request.form()
    photo.caption = str(form.get("caption", "")).strip()
    session.commit()
    return _redirect(f"/projects/{photo.project_id}#photos")


@router.post("/photos/{photo_id}/delete")
def delete_photo(photo_id: int, session: Session = Depends(get_session)):
    photo = _get_photo(session, photo_id)
    project = photo.project
    was_cover = photo.is_cover
    files = (photo.file, photo.thumb)
    project.photos.remove(photo)
    if was_cover and project.photos:
        project.photos[0].is_cover = True
    session.commit()
    media.delete_files(*files)
    return _redirect(f"/projects/{project.id}#photos")
