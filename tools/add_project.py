"""Add a project to a profile from the command line (e.g. importing a finished piece with its photo).

    .venv\\Scripts\\python tools\\add_project.py --profile Jillian --name "Little Green Alien" \\
        --status done --recipient Ren --tags "amigurumi, gift" --photo C:\\path\\alien.webp --make-3d

Run it on the computer that hosts Crochet Studio, from the app folder. It writes straight to the database,
so nobody has to sign in, and it doesn't count as the profile being opened (no welcome or What's new is used up).
"""

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select  # noqa: E402

from app import media, photo3d  # noqa: E402
from app.db import engine, init_db  # noqa: E402
from app.models import Model3D, Project, ProjectPhoto, ProjectStatus, User  # noqa: E402
from app.tags import parse_tags  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Add a project to a Crochet Studio profile")
    p.add_argument("--profile", required=True, help="profile name, e.g. Jillian")
    p.add_argument("--name", required=True)
    p.add_argument("--status", default="planned", choices=[s.value for s in ProjectStatus])
    p.add_argument("--recipient", default="")
    p.add_argument("--tags", default="")
    p.add_argument("--notes", default="")
    p.add_argument("--photo", type=Path, help="photo file to attach as the cover")
    p.add_argument("--make-3d", action="store_true", help="also turn the photo into a 3D model")
    args = p.parse_args()

    init_db()
    with Session(engine) as session:
        user = session.exec(select(User).where(User.name == args.profile)).first()
        if not user:
            names = ", ".join(u.name for u in session.exec(select(User)).all())
            print(f"No profile called {args.profile!r}. Profiles: {names}")
            return 1
        if session.exec(select(Project).where(Project.user_id == user.id, Project.name == args.name)).first():
            print(f"{args.profile} already has a project called {args.name!r}; nothing added.")
            return 1
        data = args.photo.read_bytes() if args.photo else b""

        status = ProjectStatus(args.status)
        project = Project(name=args.name, status=status, user_id=user.id, recipient=args.recipient, notes=args.notes)
        if status == ProjectStatus.done:
            project.finish_date = date.today()
        project.tags = parse_tags(session, args.tags)
        session.add(project)
        session.flush()

        if data:
            stored = media.save_image(data, f"projects/{project.id}")
            project.photos.append(ProjectPhoto(file=stored.file, thumb=stored.thumb, is_cover=True,
                                               taken_on=stored.taken_on or date.today()))
        model = None
        if data and args.make_3d:
            relief = photo3d.make_relief(data)
            model = Model3D(user_id=user.id, project_id=project.id, title=args.name, kind="photo", file="")
            session.add(model)
            session.flush()
            folder = f"models/{model.id}"
            for attr, name, blob in (("file", "texture.webp", relief.texture), ("depth", "depth.png", relief.depth),
                                     ("thumb", "thumb.webp", relief.thumb)):
                (media.settings.media_dir / folder).mkdir(parents=True, exist_ok=True)
                (media.settings.media_dir / folder / name).write_bytes(blob)
                setattr(model, attr, f"{folder}/{name}")
        session.commit()
        print(f"Added project #{project.id} {args.name!r} ({status.value}) to {user.name}"
              + (", with photo" if data else "") + (f" and 3D model #{model.id}" if model else "")
              + (" (no clear subject found: the 3D is a raised photo card)" if model and not relief.cutout else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
