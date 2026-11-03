from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select
from starlette.datastructures import FormData, UploadFile

from .. import media
from ..db import get_session
from ..deps import current_user, owned, redirect
from ..models import (
    DASHBOARD_ORDER, Model3D, Pattern, Project, ProjectPhoto, ProjectStatus, ProjectTagLink, StepDone, Tag, User, Yarn,
    utcnow,
)
from ..tags import parse_tags
from ..templating import templates
from .stash import yarn_lines

router = APIRouter()

TEXT_FIELDS = ("recipient", "hook_size", "gauge", "finished_size", "notes")


def _parse_date(value) -> Optional[date]:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _set_status(project: Project, status: ProjectStatus) -> None:
    project.status = status
    if status == ProjectStatus.in_progress and not project.start_date:
        project.start_date = date.today()
    if status == ProjectStatus.done and not project.finish_date:
        project.finish_date = date.today()


def _apply_form(session: Session, project: Project, form: FormData, user: User) -> None:
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
    project.tags = parse_tags(session, str(form.get("tags", "")))
    pattern_id = str(form.get("pattern_id") or "")
    pattern = session.get(Pattern, int(pattern_id)) if pattern_id.isdigit() else None
    project.pattern_id = pattern.id if pattern and pattern.user_id == user.id else None
    project.updated_at = utcnow()


async def save_photos(project: Project, files: list) -> int:
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


def _tag_options(session: Session, user: User) -> list[str]:
    stmt = (select(Tag.name).join(ProjectTagLink).join(Project, Project.id == ProjectTagLink.project_id)
            .where(Project.user_id == user.id).distinct().order_by(Tag.name))
    return list(session.exec(stmt).all())


def _form_context(session: Session, project: Project, user: User) -> dict:
    patterns = session.exec(select(Pattern).where(Pattern.user_id == user.id).order_by(Pattern.title)).all()
    return {
        "project": project,
        "tag_names": [t.name for t in project.tags],
        "all_tags": _tag_options(session, user),
        "patterns": patterns,
    }


def _after_save(project: Project, rejected: int, anchor: str = "") -> str:
    return f"/projects/{project.id}" + (f"?rejected={rejected}" if rejected else "") + anchor


# ---------- dashboard ----------

@router.get("/")
def dashboard(request: Request, q: str = "", tag: str = "",
              user: User = Depends(current_user), session: Session = Depends(get_session)):
    q = q.strip()
    mine = Project.user_id == user.id
    stmt = select(Project).where(mine).options(selectinload(Project.tags), selectinload(Project.photos))
    tag_project = select(ProjectTagLink.project_id).join(Tag, Tag.id == ProjectTagLink.tag_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(
            Project.name.ilike(like),
            Project.recipient.ilike(like),
            Project.notes.ilike(like),
            Project.hook_size.ilike(like),
            Project.id.in_(tag_project.where(Tag.name.ilike(like))),
        ))
    if tag:
        stmt = stmt.where(Project.id.in_(tag_project.where(Tag.name == tag)))
    projects = session.exec(stmt.order_by(Project.updated_at.desc())).all()

    groups = {status: [] for status in DASHBOARD_ORDER}
    for p in projects:
        groups[p.status].append(p)

    tag_counts = session.exec(
        select(Tag.name, func.count(ProjectTagLink.project_id))
        .join(ProjectTagLink).join(Project, Project.id == ProjectTagLink.project_id)
        .where(mine).group_by(Tag.name).order_by(Tag.name)
    ).all()
    total = session.exec(select(func.count(Project.id)).where(mine)).one()

    context = {"groups": groups, "q": q, "tag": tag, "tag_counts": tag_counts, "found": len(projects), "total": total}
    is_htmx = request.headers.get("HX-Request") == "true"
    return templates.TemplateResponse(request, "_results.html" if is_htmx else "dashboard.html", context)


# ---------- create / edit ----------

@router.get("/projects/new")
def new_project(request: Request, status: str = "planned", pattern: int = 0,
                user: User = Depends(current_user), session: Session = Depends(get_session)):
    try:
        initial = ProjectStatus(status)
    except ValueError:
        initial = ProjectStatus.planned
    project = Project(name="", status=initial, pattern_id=pattern or None)
    linked = session.get(Pattern, pattern) if pattern else None
    if linked and linked.user_id == user.id:
        project.name = linked.title
    return templates.TemplateResponse(request, "project_form.html", _form_context(session, project, user))


@router.post("/projects")
async def create_project(request: Request, user: User = Depends(current_user), session: Session = Depends(get_session)):
    form = await request.form()
    project = Project(name="", user_id=user.id)
    _apply_form(session, project, form, user)
    session.add(project)
    session.flush()  # need the id for the photo folder
    rejected = await save_photos(project, form.getlist("photos"))
    session.commit()
    return redirect(_after_save(project, rejected))


@router.get("/projects/{project_id}")
def project_detail(request: Request, project_id: int, rejected: int = 0,
                   user: User = Depends(current_user), session: Session = Depends(get_session)):
    project = owned(session, Project, project_id, user)
    pattern = session.get(Pattern, project.pattern_id) if project.pattern_id else None
    done = 0
    if pattern:
        done = session.exec(select(func.count()).select_from(StepDone).where(StepDone.project_id == project.id)).one()
    models = session.exec(select(Model3D).where(Model3D.project_id == project.id)).all()
    my_yarn = session.exec(select(Yarn).where(Yarn.user_id == user.id).order_by(Yarn.brand, Yarn.line)).all()
    return templates.TemplateResponse(request, "project_detail.html", {
        "project": project, "rejected": rejected, "pattern": pattern, "steps_done": done, "models": models,
        "yarn_lines": yarn_lines(session, project), "my_yarn": my_yarn,
    })


@router.get("/projects/{project_id}/edit")
def edit_project(request: Request, project_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)):
    project = owned(session, Project, project_id, user)
    return templates.TemplateResponse(request, "project_form.html", _form_context(session, project, user))


@router.post("/projects/{project_id}")
async def update_project(request: Request, project_id: int,
                         user: User = Depends(current_user), session: Session = Depends(get_session)):
    project = owned(session, Project, project_id, user)
    form = await request.form()
    _apply_form(session, project, form, user)
    rejected = await save_photos(project, form.getlist("photos"))
    session.commit()
    return redirect(_after_save(project, rejected))


@router.post("/projects/{project_id}/status")
async def change_status(request: Request, project_id: int,
                        user: User = Depends(current_user), session: Session = Depends(get_session)):
    project = owned(session, Project, project_id, user)
    form = await request.form()
    try:
        _set_status(project, ProjectStatus(form.get("status")))
    except ValueError:
        raise HTTPException(400, "Unknown status")
    project.updated_at = utcnow()
    session.commit()
    return redirect(f"/projects/{project.id}")


@router.post("/projects/{project_id}/delete")
def delete_project(project_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)):
    project = owned(session, Project, project_id, user)
    for model in session.exec(select(Model3D).where(Model3D.project_id == project.id)).all():
        model.project_id = None
    session.delete(project)
    session.commit()
    media.delete_folder(f"projects/{project_id}")
    return redirect("/")


# ---------- photos ----------

@router.post("/projects/{project_id}/photos")
async def add_photos(request: Request, project_id: int,
                     user: User = Depends(current_user), session: Session = Depends(get_session)):
    project = owned(session, Project, project_id, user)
    form = await request.form()
    rejected = await save_photos(project, form.getlist("photos"))
    project.updated_at = utcnow()
    session.commit()
    return redirect(_after_save(project, rejected, "#photos"))


def _get_photo(session: Session, photo_id: int, user: User) -> ProjectPhoto:
    photo = session.get(ProjectPhoto, photo_id)
    if not photo or photo.project.user_id != user.id:
        raise HTTPException(404, "Photo not found")
    return photo


@router.post("/photos/{photo_id}/cover")
def set_cover(photo_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)):
    photo = _get_photo(session, photo_id, user)
    for p in photo.project.photos:
        p.is_cover = p.id == photo.id
    session.commit()
    return redirect(f"/projects/{photo.project_id}#photos")


@router.post("/photos/{photo_id}/caption")
async def set_caption(request: Request, photo_id: int,
                      user: User = Depends(current_user), session: Session = Depends(get_session)):
    photo = _get_photo(session, photo_id, user)
    form = await request.form()
    photo.caption = str(form.get("caption", "")).strip()
    session.commit()
    return redirect(f"/projects/{photo.project_id}#photos")


@router.post("/photos/{photo_id}/delete")
def delete_photo(photo_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)):
    photo = _get_photo(session, photo_id, user)
    project = photo.project
    was_cover = photo.is_cover
    files = (photo.file, photo.thumb)
    project.photos.remove(photo)
    if was_cover and project.photos:
        project.photos[0].is_cover = True
    session.commit()
    media.delete_files(*files)
    return redirect(f"/projects/{project.id}#photos")
