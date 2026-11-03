from sqlmodel import Session, select

from .models import Tag


def parse_tags(session: Session, raw: str) -> list[Tag]:
    """'Blanket, granny squares,blanket' -> [Tag(blanket), Tag(granny squares)], reusing existing tags."""
    names = []
    for part in str(raw or "").split(","):
        name = " ".join(part.split()).lower()
        if name and name not in names:
            names.append(name)
    existing = {t.name: t for t in session.exec(select(Tag).where(Tag.name.in_(names))).all()} if names else {}
    return [existing.get(n) or Tag(name=n) for n in names]
