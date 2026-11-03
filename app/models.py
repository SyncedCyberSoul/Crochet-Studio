from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProjectStatus(str, Enum):
    idea = "idea"
    planned = "planned"
    in_progress = "in_progress"
    paused = "paused"
    frogged = "frogged"
    done = "done"


STATUS_LABELS = {
    ProjectStatus.idea: "Idea",
    ProjectStatus.planned: "Planned",
    ProjectStatus.in_progress: "In progress",
    ProjectStatus.paused: "Paused",
    ProjectStatus.frogged: "Frogged",
    ProjectStatus.done: "Done",
}

# Order of the groups on the dashboard: what she's working on comes first.
DASHBOARD_ORDER = [
    ProjectStatus.in_progress,
    ProjectStatus.planned,
    ProjectStatus.idea,
    ProjectStatus.paused,
    ProjectStatus.done,
    ProjectStatus.frogged,
]


AVATAR_COLORS = ["#c4694b", "#7f9a7e", "#6d9dc5", "#b58bc4", "#d98c3f", "#c9706f", "#5f8f8b", "#a37b5c"]


class User(SQLModel, table=True):
    """A profile. The password is optional; admin is a separate logon, not a user."""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    color: str = AVATAR_COLORS[0]
    password_hash: Optional[str] = None
    seen_version: int = 0  # newest "What's new" release this profile has seen; 0 = never opened
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def initial(self) -> str:
        return self.name[:1].upper()

    @property
    def has_password(self) -> bool:
        return bool(self.password_hash)


class AppSetting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str = ""


class ProjectTagLink(SQLModel, table=True):
    project_id: Optional[int] = Field(default=None, foreign_key="project.id", primary_key=True, ondelete="CASCADE")
    tag_id: Optional[int] = Field(default=None, foreign_key="tag.id", primary_key=True, ondelete="CASCADE")


class Tag(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)

    projects: list["Project"] = Relationship(back_populates="tags", link_model=ProjectTagLink)


class Project(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    status: ProjectStatus = Field(default=ProjectStatus.idea, index=True)
    recipient: str = ""
    start_date: Optional[date] = None
    finish_date: Optional[date] = None
    hook_size: str = ""
    gauge: str = ""
    finished_size: str = ""
    notes: str = ""
    pattern_id: Optional[int] = Field(default=None, index=True)  # Pattern.id (no FK: added after the table existed)
    user_id: Optional[int] = Field(default=None, index=True)
    row_counter: int = 0
    stitch_counter: int = 0
    current_step_id: Optional[int] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    tags: list[Tag] = Relationship(back_populates="projects", link_model=ProjectTagLink)
    photos: list["ProjectPhoto"] = Relationship(
        back_populates="project",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "order_by": "ProjectPhoto.id"},
    )

    @property
    def cover(self) -> Optional["ProjectPhoto"]:
        return next((p for p in self.photos if p.is_cover), self.photos[0] if self.photos else None)

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[self.status]


class ProjectPhoto(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True, ondelete="CASCADE")
    file: str  # path under media dir, forward slashes
    thumb: str
    caption: str = ""
    taken_on: Optional[date] = None
    is_cover: bool = False

    project: Optional[Project] = Relationship(back_populates="photos")


# ---------- patterns ----------

class Pattern(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, index=True)
    title: str
    designer: str = ""
    source_url: str = ""
    difficulty: str = ""
    terms: str = "us"  # "us" or "uk": which terms the pattern text is written in
    notes: str = ""
    raw_text: str = ""
    pdf_file: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    steps: list["PatternStep"] = Relationship(
        back_populates="pattern",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "order_by": "PatternStep.position"},
    )


class PatternStep(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    pattern_id: int = Field(foreign_key="pattern.id", index=True, ondelete="CASCADE")
    position: int = 0
    section: str = ""
    label: str = ""  # "Rnd 3", "Row 12"
    text: str = ""
    stitch_count: Optional[int] = None

    pattern: Optional[Pattern] = Relationship(back_populates="steps")


class StepDone(SQLModel, table=True):
    """A pattern step checked off within one project."""

    project_id: int = Field(foreign_key="project.id", primary_key=True, ondelete="CASCADE")
    step_id: int = Field(foreign_key="patternstep.id", primary_key=True, ondelete="CASCADE")
    done_at: datetime = Field(default_factory=utcnow)


# ---------- ideas ----------

class IdeaTagLink(SQLModel, table=True):
    idea_id: Optional[int] = Field(default=None, foreign_key="idea.id", primary_key=True, ondelete="CASCADE")
    tag_id: Optional[int] = Field(default=None, foreign_key="tag.id", primary_key=True, ondelete="CASCADE")


class Idea(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, index=True)
    title: str
    source_url: str = ""
    notes: str = ""
    image: str = ""
    thumb: str = ""
    project_id: Optional[int] = None  # set once promoted to a project
    created_at: datetime = Field(default_factory=utcnow)

    tags: list[Tag] = Relationship(link_model=IdeaTagLink)

    @property
    def source_host(self) -> str:
        from urllib.parse import urlparse

        host = urlparse(self.source_url).hostname or ""
        return host.removeprefix("www.")


# ---------- 3D ----------

class Model3D(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, index=True)
    project_id: Optional[int] = Field(default=None, index=True)
    title: str
    kind: str  # "glb", "stl", "obj" (uploaded) or "photo" (made from a photo)
    file: str  # model file, or the cut-out texture PNG for "photo"
    depth: str = ""  # depth map PNG for "photo"
    thumb: str = ""
    created_at: datetime = Field(default_factory=utcnow)
