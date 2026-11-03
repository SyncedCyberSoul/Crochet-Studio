"""Import patterns for projects that don't have one, from the web page their idea links to.

    .venv\\Scripts\\python tools\\import_patterns.py              (every project missing a pattern)
    .venv\\Scripts\\python tools\\import_patterns.py --project 7  (just that one)
    .venv\\Scripts\\python tools\\import_patterns.py --project 7 --url https://...   (use this link instead)
    .venv\\Scripts\\python tools\\import_patterns.py --project 7 --replace          (re-import over an older import)

Run it on the computer that hosts Crochet Studio, from the app folder. Nobody has to sign in.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select  # noqa: E402

from app.db import engine, init_db  # noqa: E402
from app.models import Idea, Pattern, PatternStep, Project, StepDone, User  # noqa: E402
from app.patternimport import FetchError, import_from_url  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Import patterns from linked web pages")
    p.add_argument("--project", type=int, help="project id (default: every project without a pattern)")
    p.add_argument("--url", help="pattern page to use instead of the idea's link")
    p.add_argument("--replace", action="store_true",
                   help="re-import even if the project has a pattern (the old one is removed only if nothing else uses it)")
    args = p.parse_args()

    init_db()
    with Session(engine) as session:
        stmt = select(Project).where(Project.pattern_id == None)  # noqa: E711
        if args.project:
            stmt = select(Project).where(Project.id == args.project)
        projects = session.exec(stmt).all()
        if not projects:
            print("No matching projects.")
            return 1
        for project in projects:
            if project.pattern_id and not args.replace:
                print(f"#{project.id} {project.name!r}: already has a pattern (use --replace to re-import)")
                continue
            idea = session.exec(select(Idea).where(Idea.project_id == project.id)).first()
            url = args.url or (idea.source_url if idea else "")
            if not url:
                print(f"#{project.id} {project.name!r}: no link to import from (skipped)")
                continue
            try:
                imp = import_from_url(url, project.name)
            except FetchError as exc:
                print(f"#{project.id} {project.name!r}: couldn't open {url}: {exc}")
                continue
            if not imp:
                print(f"#{project.id} {project.name!r}: no written rows on {url} (paid pattern, PDF, video or photo post?)")
                continue
            old = session.get(Pattern, project.pattern_id) if project.pattern_id else None
            if old:
                others = session.exec(select(Project).where(Project.pattern_id == old.id, Project.id != project.id)).first()
                progress = session.exec(select(StepDone).where(StepDone.project_id == project.id)).first()
                if progress:
                    print(f"#{project.id} {project.name!r}: has checked-off steps, so the old pattern was kept (skipped)")
                    continue
                if not others:
                    session.delete(old)
                    session.flush()
            user = session.get(User, project.user_id)
            pattern = Pattern(user_id=user.id, title=imp.title, designer=imp.designer, source_url=imp.source_url,
                              raw_text=imp.text, notes=imp.materials and f"Materials (from the page):\n{imp.materials}")
            session.add(pattern)
            session.flush()
            pattern.steps = [PatternStep(pattern_id=pattern.id, position=i, section=s.section[:80], label=s.label[:40],
                                         text=s.text, stitch_count=s.stitch_count) for i, s in enumerate(imp.steps)]
            project.pattern_id = pattern.id
            if imp.hook and not project.hook_size:
                project.hook_size = imp.hook
            session.commit()
            print(f"#{project.id} {project.name!r}: imported {len(imp.steps)} steps from {imp.designer}"
                  + (f", hook {imp.hook}" if imp.hook else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
