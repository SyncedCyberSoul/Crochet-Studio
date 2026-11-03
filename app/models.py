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
    pattern_id: Optional[int] = None  # linked to Pattern in phase 3
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
