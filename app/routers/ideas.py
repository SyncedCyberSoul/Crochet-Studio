from datetime import date

from fastapi import APIRouter, Depends, Request
from sqlalchemy import or_
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select
from starlette.datastructures import UploadFile

from .. import media
from ..db import get_session
from ..deps import current_user, owned, redirect
from ..models import Idea, IdeaTagLink, Project, ProjectPhoto, ProjectStatus, Tag, User, utcnow
from ..tags import parse_tags
from ..templating import templates
from ..webfetch import FetchError, fetch_image, link_preview

router = APIRouter(prefix="/ideas")


def _clean_url(raw) -> str:
    url = str(raw or "").strip()
    return url if url.startswith(("http://", "https://")) else ""


def _store_image(idea: Idea, data: bytes) -> bool:
    try:
        stored = media.save_image(data, f"ideas/{idea.id}")
    except media.NotAnImage:
        return False
    media.delete_files(idea.image, idea.thumb)
    idea.image, idea.thumb = stored.file, stored.thumb
    return True


async def _apply_image(idea: Idea, form) -> str:
    """Upload wins over a remote image URL. Returns a message if the picture couldn't be used."""
    upload = form.get("photo")
    if isinstance(upload, UploadFile) and upload.filename:
        return "" if _store_image(idea, await upload.read()) else "That file couldn't be read as a photo."
    image_url = _clean_url(form.get("image_url"))
    if image_url:
        try:
            return "" if _store_image(idea, fetch_image(image_url)) else "That picture couldn't be read."
        except FetchError as exc:
            return f"Couldn't download the picture: {exc}"
    return ""


def _tag_options(session: Session, user: User) -> list[str]:
    stmt = (select(Tag.name).join(IdeaTagLink).join(Idea, Idea.id == IdeaTagLink.idea_id)
            .where(Idea.user_id == user.id).distinct().order_by(Tag.name))
    return list(session.exec(stmt).all())


# ---------- board ----------

@router.get("")
def board(request: Request, q: str = "", tag: str = "", user: User = Depends(current_user), session: Session = Depends(get_session)):
    stmt = select(Idea).where(Idea.user_id == user.id).options(selectinload(Idea.tags))
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Idea.title.ilike(like), Idea.notes.ilike(like), Idea.source_url.ilike(like)))
    if tag:
        tagged = select(IdeaTagLink.idea_id).join(Tag, Tag.id == IdeaTagLink.tag_id).where(Tag.name == tag)
        stmt = stmt.where(Idea.id.in_(tagged))
    ideas = session.exec(stmt.order_by(Idea.created_at.desc())).all()
    return templates.TemplateResponse(request, "ideas.html", {
        "ideas": ideas, "q": q, "tag": tag, "tags": _tag_options(session, user),
    })


@router.get("/new")
def new_idea(request: Request, url: str = "", user: User = Depends(current_user), session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "idea_form.html", {
        "idea": Idea(title="", source_url=_clean_url(url)), "tag_names": [], "all_tags": _tag_options(session, user),
    })


@router.post("/preview")
async def preview(request: Request, user: User = Depends(current_user)):
    """HTMX: look up a link's title and picture so she doesn't have to type them."""
    form = await request.form()
    url = _clean_url(form.get("source_url"))
    context = {"preview": None, "error": ""}
    if not url:
        context["error"] = "Paste a link that starts with http:// or https://"
    else:
        try:
            context["preview"] = link_preview(url)
            if not context["preview"].image:
                context["error"] = "Found the page, but it has no picture to save. You can add your own photo below."
        except FetchError as exc:
            context["error"] = str(exc)
    return templates.TemplateResponse(request, "_idea_preview.html", context)


@router.post("")
async def create_idea(request: Request, user: User = Depends(current_user), session: Session = Depends(get_session)):
    form = await request.form()
    idea = Idea(
        user_id=user.id,
        title=" ".join(str(form.get("title", "")).split())[:200] or "Untitled idea",
        source_url=_clean_url(form.get("source_url")),
        notes=str(form.get("notes", "")).strip(),
    )
    idea.tags = parse_tags(session, str(form.get("tags", "")))
    session.add(idea)
    session.flush()
    note = await _apply_image(idea, form)
    session.commit()
    return redirect(f"/ideas/{idea.id}" + ("?note=" + note.replace(" ", "+") if note else ""))


@router.post("/save")
async def save_from_discover(request: Request, user: User = Depends(current_user), session: Session = Depends(get_session)):
    """HTMX: one-tap save from Discover. Responds with the replacement button."""
    form = await request.form()
    link = _clean_url(form.get("link"))
    existing = session.exec(select(Idea).where(Idea.user_id == user.id, Idea.source_url == link)).first() if link else None
    if existing:
        return templates.TemplateResponse(request, "_saved_button.html", {"idea": existing})
    idea = Idea(user_id=user.id, title=" ".join(str(form.get("title", "")).split())[:200] or "Saved idea",
                source_url=link, notes=str(form.get("summary", "")).strip()[:600])
    session.add(idea)
    session.flush()
    note = await _apply_image(idea, form)
    session.commit()
    return templates.TemplateResponse(request, "_saved_button.html", {"idea": idea, "note": note})


# ---------- one idea ----------

@router.get("/{idea_id}")
def idea_detail(request: Request, idea_id: int, note: str = "", user: User = Depends(current_user), session: Session = Depends(get_session)):
    idea = owned(session, Idea, idea_id, user)
    project = session.get(Project, idea.project_id) if idea.project_id else None
    if project and project.user_id != user.id:
        project = None
    return templates.TemplateResponse(request, "idea_detail.html", {"idea": idea, "project": project, "note": note})


@router.get("/{idea_id}/edit")
def edit_idea(request: Request, idea_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)):
    idea = owned(session, Idea, idea_id, user)
    return templates.TemplateResponse(request, "idea_form.html", {
        "idea": idea, "tag_names": [t.name for t in idea.tags], "all_tags": _tag_options(session, user),
    })


@router.post("/{idea_id}")
async def update_idea(request: Request, idea_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)):
    idea = owned(session, Idea, idea_id, user)
    form = await request.form()
    idea.title = " ".join(str(form.get("title", "")).split())[:200] or idea.title
    idea.source_url = _clean_url(form.get("source_url"))
    idea.notes = str(form.get("notes", "")).strip()
    idea.tags = parse_tags(session, str(form.get("tags", "")))
    note = await _apply_image(idea, form)
    session.commit()
    return redirect(f"/ideas/{idea.id}" + ("?note=" + note.replace(" ", "+") if note else ""))


@router.post("/{idea_id}/promote")
def promote(idea_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)):
    """Turn an idea into a planned project, carrying over its picture, tags and link."""
    idea = owned(session, Idea, idea_id, user)
    existing = session.get(Project, idea.project_id) if idea.project_id else None
    if existing and existing.user_id == user.id:
        return redirect(f"/projects/{existing.id}")
    notes = "\n\n".join(x for x in (idea.notes, f"Idea from: {idea.source_url}" if idea.source_url else "") if x)
    project = Project(name=idea.title, status=ProjectStatus.planned, user_id=user.id, notes=notes)
    project.tags = list(idea.tags)
    session.add(project)
    session.flush()
    if idea.image:
        try:
            stored = media.save_image((media.settings.media_dir / idea.image).read_bytes(), f"projects/{project.id}")
            project.photos.append(ProjectPhoto(file=stored.file, thumb=stored.thumb, taken_on=date.today(), is_cover=True,
                                               caption="Inspiration"))
        except (OSError, media.NotAnImage):
            pass
    idea.project_id = project.id
    project.updated_at = utcnow()
    session.commit()
    return redirect(f"/projects/{project.id}")


@router.post("/{idea_id}/delete")
def delete_idea(idea_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)):
    idea = owned(session, Idea, idea_id, user)
    session.delete(idea)
    session.commit()
    media.delete_folder(f"ideas/{idea_id}")
    return redirect("/ideas")
