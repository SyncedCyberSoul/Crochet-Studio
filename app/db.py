"""SQLite engine, sessions, and a tiny add-missing-columns migration."""

from collections.abc import Iterator

from sqlalchemy import event, inspect, text
from sqlmodel import Session, SQLModel, create_engine, select

from .config import settings

settings.db_path.parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(
    f"sqlite:///{settings.db_path.as_posix()}",
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON")
    cur.execute("PRAGMA journal_mode = WAL")
    cur.close()


def _add_missing_columns() -> None:
    """Later phases add fields to existing tables; SQLite can append them in place."""
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in existing:
                    col_type = col.type.compile(dialect=engine.dialect)
                    default = _column_default(col)
                    suffix = f" NOT NULL DEFAULT {default}" if default is not None else ""
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col_type}{suffix}'))


def _column_default(col) -> str | None:
    """SQL literal used to fill existing rows when a non-nullable column is added."""
    if col.nullable:
        return None
    arg = getattr(col.default, "arg", None)
    if isinstance(arg, bool):
        return "1" if arg else "0"
    if isinstance(arg, (int, float)):
        return str(arg)
    if isinstance(arg, str):
        return "'" + arg.replace("'", "''") + "'"
    try:
        python_type = col.type.python_type
    except NotImplementedError:
        python_type = str
    return "0" if python_type in (int, float, bool) else "''"


def init_db() -> None:
    from . import models  # noqa: F401  (register tables)

    SQLModel.metadata.create_all(engine)
    _add_missing_columns()
    _seed_profiles()


DEFAULT_PROFILES = [("Jillian", "#c4694b"), ("Emma", "#7f9a7e")]


def _seed_profiles() -> None:
    """First run: create the household's profiles and give them anything made before profiles existed."""
    from .models import Idea, Model3D, Pattern, Project, User

    with Session(engine) as session:
        if session.exec(select(User)).first():
            return
        users = [User(name=name, color=color) for name, color in DEFAULT_PROFILES]
        session.add_all(users)
        session.flush()
        owner = users[0].id
        for model in (Project, Pattern, Idea, Model3D):
            for row in session.exec(select(model).where(model.user_id == None)).all():  # noqa: E711
                row.user_id = owner
        session.commit()


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
