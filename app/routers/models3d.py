import base64
import io
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from PIL import Image
from sqlmodel import Session, select
from starlette.datastructures import UploadFile

from .. import media, photo3d
from ..db import get_session
from ..deps import current_user, owned, redirect
from ..models import Idea, Model3D, Project, ProjectPhoto, User
from ..templating import templates

router = APIRouter(prefix="/3d")

MAX_MODEL_BYTES = 60 * 1024 * 1024
KINDS = {".glb": "glb", ".stl": "stl", ".obj": "obj"}


def _folder(model: Model3D) -> str:
    return f"models/{model.id}"


def _write(rel: str, data: bytes) -> None:
    path = media.settings.media_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _own_project(session: Session, raw, user: User) -> Optional[Project]:
    raw = str(raw or "")
    project = session.get(Project, int(raw)) if raw.isdigit() else None
    return project if project and project.user_id == user.id else None


def _looks_like(kind: str, data: bytes) -> bool:
    if kind == "glb":
        return data[:4] == b"glTF"
    if kind == "stl":
        return data[:5].lower() == b"solid" or len(data) > 84  # ascii or binary STL
    return b"\nv " in data[:200000] or data.startswith(b"v ")  # OBJ: has vertex lines


@router.get("")
def gallery(request: Request, user: User = Depends(current_user), session: Session = Depends(get_session)):
    models = session.exec(select(Model3D).where(Model3D.user_id == user.id).order_by(Model3D.created_at.desc())).all()
    return templates.TemplateResponse(request, "models3d.html", {"models": models})


@router.get("/new")
def new_model(request: Request, project: int = 0, idea: int = 0, error: str = "",
              user: User = Depends(current_user), session: Session = Depends(get_session)):
    linked = _own_project(session, project, user)
    the_idea = session.get(Idea, idea) if idea else None
    if the_idea and the_idea.user_id != user.id:
        the_idea = None
    projects = session.exec(select(Project).where(Project.user_id == user.id).order_by(Project.updated_at.desc())).all()
    return templates.TemplateResponse(request, "model_new.html", {
        "linked": linked, "idea": the_idea, "projects": projects, "error": error,
        "photos": linked.photos if linked else [],
    })


@router.post("/photo")
async def from_photo(request: Request, user: User = Depends(current_user), session: Session = Depends(get_session)):
    form = await request.form()
    project = _own_project(session, form.get("project_id"), user)
    data, title = b"", str(form.get("title", "")).strip()
    upload = form.get("photo")
    source = str(form.get("source", ""))
    if isinstance(upload, UploadFile) and upload.filename:
        data = await upload.read()
    elif source.startswith("photo:") and source[6:].isdigit():
        photo = session.get(ProjectPhoto, int(source[6:]))
        if photo and photo.project.user_id == user.id:
            data = (media.settings.media_dir / photo.file).read_bytes()
            project = project or photo.project
    elif source.startswith("idea:") and source[5:].isdigit():
        idea = session.get(Idea, int(source[5:]))
        if idea and idea.user_id == user.id and idea.image:
            data = (media.settings.media_dir / idea.image).read_bytes()
            title = title or idea.title
    if not data:
        return redirect("/3d/new?error=Choose+a+photo+first" + (f"&project={project.id}" if project else ""))
    try:
        relief = photo3d.make_relief(data)
    except photo3d.NotAnImage:
        return redirect("/3d/new?error=That+file+couldn%27t+be+read+as+a+photo")

    model = Model3D(user_id=user.id, project_id=project.id if project else None,
                    title=title or (project.name if project else "Photo model"), kind="photo", file="")
    session.add(model)
    session.flush()
    folder = _folder(model)
    model.file, model.depth, model.thumb = f"{folder}/texture.webp", f"{folder}/depth.png", f"{folder}/thumb.webp"
    _write(model.file, relief.texture)
    _write(model.depth, relief.depth)
    _write(model.thumb, relief.thumb)
    session.commit()
    return redirect(f"/3d/{model.id}" + ("" if relief.cutout else "?card=1"))


@router.post("/upload")
async def upload_model(request: Request, user: User = Depends(current_user), session: Session = Depends(get_session)):
    form = await request.form()
    upload = form.get("model")
    project = _own_project(session, form.get("project_id"), user)
    back = "/3d/new" + (f"?project={project.id}&" if project else "?")
    if not isinstance(upload, UploadFile) or not upload.filename:
        return redirect(back + "error=Choose+a+3D+file+first")
    ext = "." + upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else ""
    kind = KINDS.get(ext)
    data = await upload.read(MAX_MODEL_BYTES + 1)
    if not kind or len(data) > MAX_MODEL_BYTES or not _looks_like(kind, data):
        return redirect(back + "error=Use+a+.glb,+.stl+or+.obj+file+under+60+MB")
    title = str(form.get("title", "")).strip() or upload.filename.rsplit(".", 1)[0][:80]
    model = Model3D(user_id=user.id, project_id=project.id if project else None, title=title, kind=kind, file="")
    session.add(model)
    session.flush()
    model.file = f"{_folder(model)}/model{ext}"
    _write(model.file, data)
    session.commit()
    return redirect(f"/3d/{model.id}")


@router.get("/{model_id}")
def view(request: Request, model_id: int, card: int = 0, user: User = Depends(current_user), session: Session = Depends(get_session)):
    model = owned(session, Model3D, model_id, user)
    project = _own_project(session, model.project_id, user)
    projects = session.exec(select(Project).where(Project.user_id == user.id).order_by(Project.name)).all()
    return templates.TemplateResponse(request, "model_view.html", {
        "model": model, "project": project, "projects": projects, "card": card,
    })


@router.post("/{model_id}/details")
async def update_details(request: Request, model_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)):
    model = owned(session, Model3D, model_id, user)
    form = await request.form()
    model.title = str(form.get("title", "")).strip()[:120] or model.title
    project = _own_project(session, form.get("project_id"), user)
    model.project_id = project.id if project else None
    session.commit()
    return redirect(f"/3d/{model.id}")


@router.post("/{model_id}/thumb")
async def save_thumb(request: Request, model_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)):
    """The viewer sends a snapshot of uploaded models the first time they're shown."""
    model = owned(session, Model3D, model_id, user)
    if model.thumb:
        return {"ok": True}
    body = await request.json()
    raw = str(body.get("image", ""))
    if not raw.startswith("data:image/") or len(raw) > 6_000_000:
        raise HTTPException(400, "Bad snapshot")
    try:
        img = Image.open(io.BytesIO(base64.b64decode(raw.split(",", 1)[1])))
        img.thumbnail((480, 480))
        buf = io.BytesIO()
        img.save(buf, "WEBP", quality=85)
    except Exception:
        raise HTTPException(400, "Bad snapshot")
    model.thumb = f"{_folder(model)}/thumb.webp"
    _write(model.thumb, buf.getvalue())
    session.commit()
    return {"ok": True}


@router.post("/{model_id}/delete")
def delete(model_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)):
    model = owned(session, Model3D, model_id, user)
    back = f"/projects/{model.project_id}#models" if model.project_id else "/3d"
    session.delete(model)
    session.commit()
    media.delete_folder(f"models/{model_id}")
    return redirect(back)
