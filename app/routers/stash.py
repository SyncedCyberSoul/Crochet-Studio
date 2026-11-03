"""Yarn and tool inventory, linking yarn to projects, and the 'enough yarn?' check."""

from dataclasses import dataclass
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_
from sqlmodel import Session, select
from starlette.datastructures import FormData, UploadFile

from .. import media
from ..db import get_session
from ..deps import current_user, owned, redirect
from ..models import TOOL_TYPES, YARN_WEIGHTS, Project, ProjectStatus, ProjectYarn, Tool, User, Yarn
from ..templating import templates

router = APIRouter()

ACTIVE = (ProjectStatus.planned, ProjectStatus.in_progress, ProjectStatus.paused, ProjectStatus.idea)


def _num(value) -> Optional[float]:
    try:
        n = float(str(value).strip())
        return n if n >= 0 else None
    except (TypeError, ValueError):
        return None


async def _store_photo(row, form: FormData, folder: str) -> str:
    upload = form.get("photo")
    if not isinstance(upload, UploadFile) or not upload.filename:
        return ""
    try:
        stored = media.save_image(await upload.read(), folder)
    except media.NotAnImage:
        return "That file couldn't be read as a photo."
    media.delete_files(row.image, row.thumb)
    row.image, row.thumb = stored.file, stored.thumb
    return ""


# ---------- the "enough yarn?" check ----------

@dataclass
class YarnLine:
    link: ProjectYarn
    yarn: Yarn
    on_hand: Optional[float]  # yards
    elsewhere: float  # yards other active projects have claimed from the same yarn
    verdict: str  # "enough" | "short" | "unknown"
    short_by: float = 0


def yarn_lines(session: Session, project: Project) -> list[YarnLine]:
    lines = []
    links = session.exec(select(ProjectYarn).where(ProjectYarn.project_id == project.id)).all()
    for link in links:
        yarn = session.get(Yarn, link.yarn_id)
        if not yarn:
            continue
        others = session.exec(
            select(ProjectYarn, Project).join(Project, Project.id == ProjectYarn.project_id)
            .where(ProjectYarn.yarn_id == yarn.id, ProjectYarn.project_id != project.id, Project.status.in_(ACTIVE))
        ).all()
        elsewhere = sum(pl.yards_needed or 0 for pl, _ in others)
        on_hand = yarn.yards_on_hand
        if on_hand is None or not link.yards_needed or project.status == ProjectStatus.done:
            lines.append(YarnLine(link, yarn, on_hand, elsewhere, "unknown"))
            continue
        spare = on_hand - elsewhere
        verdict = "enough" if spare >= link.yards_needed else "short"
        lines.append(YarnLine(link, yarn, on_hand, elsewhere, verdict, round(max(0, link.yards_needed - spare), 1)))
    return lines


# ---------- stash pages ----------

@router.get("/stash")
def stash(request: Request, tab: str = "yarn", q: str = "", user: User = Depends(current_user),
          session: Session = Depends(get_session)):
    yarns = select(Yarn).where(Yarn.user_id == user.id)
    tools = select(Tool).where(Tool.user_id == user.id)
    if q.strip():
        like = f"%{q.strip()}%"
        yarns = yarns.where(or_(Yarn.brand.ilike(like), Yarn.line.ilike(like), Yarn.colorway.ilike(like),
                                Yarn.fiber.ilike(like), Yarn.weight.ilike(like), Yarn.location.ilike(like)))
        tools = tools.where(or_(Tool.kind.ilike(like), Tool.size.ilike(like), Tool.material.ilike(like),
                                Tool.notes.ilike(like)))
    yarn_list = session.exec(yarns.order_by(Yarn.brand, Yarn.line, Yarn.colorway)).all()
    tool_list = session.exec(tools.order_by(Tool.kind, Tool.size)).all()
    return templates.TemplateResponse(request, "stash.html", {
        "tab": "tools" if tab == "tools" else "yarn", "q": q, "yarns": yarn_list, "tools": tool_list,
    })


def _yarn_form(request: Request, yarn: Yarn, error: str = ""):
    return templates.TemplateResponse(request, "yarn_form.html", {"yarn": yarn, "weights": YARN_WEIGHTS, "error": error})


def _apply_yarn(yarn: Yarn, form: FormData) -> None:
    for field in ("brand", "line", "colorway", "dye_lot", "fiber", "location", "notes"):
        setattr(yarn, field, str(form.get(field, "")).strip()[:200])
    yarn.weight = str(form.get("weight", "")) if form.get("weight") in YARN_WEIGHTS else ""
    hex_ = str(form.get("color_hex", "")).strip()
    yarn.color_hex = hex_ if len(hex_) == 7 and hex_.startswith("#") else ""
    yarn.yards_per_skein = _num(form.get("yards_per_skein"))
    yarn.grams_per_skein = _num(form.get("grams_per_skein"))
    yarn.skeins_on_hand = _num(form.get("skeins_on_hand")) or 0


@router.get("/stash/yarn/new")
def new_yarn(request: Request, user: User = Depends(current_user)):
    return _yarn_form(request, Yarn())


@router.post("/stash/yarn")
async def create_yarn(request: Request, user: User = Depends(current_user), session: Session = Depends(get_session)):
    form = await request.form()
    yarn = Yarn(user_id=user.id)
    _apply_yarn(yarn, form)
    session.add(yarn)
    session.flush()
    note = await _store_photo(yarn, form, f"stash/yarn/{yarn.id}")
    session.commit()
    return redirect(f"/stash/yarn/{yarn.id}" + ("?note=" + note.replace(" ", "+") if note else ""))


@router.get("/stash/yarn/{yarn_id}")
def yarn_detail(request: Request, yarn_id: int, note: str = "", user: User = Depends(current_user),
                session: Session = Depends(get_session)):
    yarn = owned(session, Yarn, yarn_id, user)
    uses = session.exec(
        select(ProjectYarn, Project).join(Project, Project.id == ProjectYarn.project_id).where(ProjectYarn.yarn_id == yarn.id)
    ).all()
    claimed = sum(link.yards_needed or 0 for link, p in uses if p.status in ACTIVE)
    return templates.TemplateResponse(request, "yarn_detail.html", {"yarn": yarn, "uses": uses, "claimed": claimed, "note": note})


@router.get("/stash/yarn/{yarn_id}/edit")
def edit_yarn(request: Request, yarn_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)):
    return _yarn_form(request, owned(session, Yarn, yarn_id, user))


@router.post("/stash/yarn/{yarn_id}")
async def update_yarn(request: Request, yarn_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)):
    yarn = owned(session, Yarn, yarn_id, user)
    form = await request.form()
    _apply_yarn(yarn, form)
    note = await _store_photo(yarn, form, f"stash/yarn/{yarn.id}")
    session.commit()
    return redirect(f"/stash/yarn/{yarn.id}" + ("?note=" + note.replace(" ", "+") if note else ""))


@router.post("/stash/yarn/{yarn_id}/skeins")
async def bump_skeins(request: Request, yarn_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)):
    yarn = owned(session, Yarn, yarn_id, user)
    form = await request.form()
    yarn.skeins_on_hand = max(0, (yarn.skeins_on_hand or 0) + (_num(form.get("by")) or 0) * (-1 if form.get("dir") == "down" else 1))
    session.commit()
    back = str(form.get("back") or "")
    return redirect(back if back.startswith("/") and not back.startswith("//") else f"/stash/yarn/{yarn.id}")


@router.post("/stash/yarn/{yarn_id}/delete")
def delete_yarn(yarn_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)):
    yarn = owned(session, Yarn, yarn_id, user)
    for link in session.exec(select(ProjectYarn).where(ProjectYarn.yarn_id == yarn.id)).all():
        session.delete(link)
    session.delete(yarn)
    session.commit()
    media.delete_folder(f"stash/yarn/{yarn_id}")
    return redirect("/stash")


# ---------- tools ----------

def _apply_tool(tool: Tool, form: FormData) -> None:
    tool.kind = str(form.get("kind", "Other")) if form.get("kind") in TOOL_TYPES else "Other"
    for field in ("size", "material", "notes"):
        setattr(tool, field, str(form.get(field, "")).strip()[:200])
    tool.quantity = int(_num(form.get("quantity")) or 1)


@router.get("/stash/tools/new")
def new_tool(request: Request, user: User = Depends(current_user)):
    return templates.TemplateResponse(request, "tool_form.html", {"tool": Tool(), "kinds": TOOL_TYPES})


@router.post("/stash/tools")
async def create_tool(request: Request, user: User = Depends(current_user), session: Session = Depends(get_session)):
    form = await request.form()
    tool = Tool(user_id=user.id)
    _apply_tool(tool, form)
    session.add(tool)
    session.flush()
    await _store_photo(tool, form, f"stash/tools/{tool.id}")
    session.commit()
    return redirect("/stash?tab=tools")


@router.get("/stash/tools/{tool_id}/edit")
def edit_tool(request: Request, tool_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "tool_form.html", {"tool": owned(session, Tool, tool_id, user), "kinds": TOOL_TYPES})


@router.post("/stash/tools/{tool_id}")
async def update_tool(request: Request, tool_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)):
    tool = owned(session, Tool, tool_id, user)
    form = await request.form()
    _apply_tool(tool, form)
    await _store_photo(tool, form, f"stash/tools/{tool.id}")
    session.commit()
    return redirect("/stash?tab=tools")


@router.post("/stash/tools/{tool_id}/delete")
def delete_tool(tool_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)):
    tool = owned(session, Tool, tool_id, user)
    session.delete(tool)
    session.commit()
    media.delete_folder(f"stash/tools/{tool_id}")
    return redirect("/stash?tab=tools")


# ---------- yarn on a project ----------

@router.post("/projects/{project_id}/yarn")
async def add_project_yarn(request: Request, project_id: int, user: User = Depends(current_user),
                           session: Session = Depends(get_session)):
    project = owned(session, Project, project_id, user)
    form = await request.form()
    yarn_id = str(form.get("yarn_id", ""))
    yarn = owned(session, Yarn, int(yarn_id), user) if yarn_id.isdigit() else None
    if not yarn:
        raise HTTPException(400, "Pick a yarn")
    session.add(ProjectYarn(project_id=project.id, yarn_id=yarn.id, yards_needed=_num(form.get("yards_needed")),
                            notes=str(form.get("notes", "")).strip()[:200]))
    session.commit()
    return redirect(f"/projects/{project.id}#yarn")


def _own_link(session: Session, link_id: int, user: User) -> ProjectYarn:
    link = session.get(ProjectYarn, link_id)
    project = session.get(Project, link.project_id) if link else None
    if not project or project.user_id != user.id:
        raise HTTPException(404, "Not found")
    return link


@router.post("/project-yarn/{link_id}")
async def update_project_yarn(request: Request, link_id: int, user: User = Depends(current_user),
                              session: Session = Depends(get_session)):
    link = _own_link(session, link_id, user)
    form = await request.form()
    link.yards_needed = _num(form.get("yards_needed"))
    session.commit()
    return redirect(f"/projects/{link.project_id}#yarn")


@router.post("/project-yarn/{link_id}/delete")
def delete_project_yarn(link_id: int, user: User = Depends(current_user), session: Session = Depends(get_session)):
    link = _own_link(session, link_id, user)
    project_id = link.project_id
    session.delete(link)
    session.commit()
    return redirect(f"/projects/{project_id}#yarn")
