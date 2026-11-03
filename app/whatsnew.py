"""'What's new' popups. Add a release at the end of RELEASES whenever features ship."""

from dataclasses import dataclass

from sqlmodel import Session

from .auth import get_setting
from .db import WELCOME_KEY, engine


def welcome_user_id() -> int | None:
    """The one profile that gets the one-time welcome note on first open (set on the admin page)."""
    with Session(engine) as session:
        raw = get_setting(session, WELCOME_KEY)
    return int(raw) if raw.isdigit() else None


def gets_welcome(user) -> bool:
    return user is not None and user.id == welcome_user_id()


@dataclass(frozen=True)
class Release:
    version: int
    title: str
    items: tuple[str, ...]


RELEASES = (
    Release(1, "Your projects", (
        "Projects grouped by status, with photos, tags and search.",
    )),
    Release(2, "A big update", (
        "Dark mode: tap the moon at the top.",
        "Profiles for everyone, with optional passwords.",
        "Patterns: paste one in and it splits into rows you can follow step by step. Your place saves automatically.",
        "Big row and stitch counters, and a US/UK terms switch.",
        "Ideas board: save inspiration from Pinterest or any link.",
        "Discover: fresh project ideas from crochet blogs.",
        "3D: turn a photo of your work into a model you can spin around.",
    )),
    Release(3, "Passwords and photos", (
        "Every profile now has its own password.",
        "Add a profile photo: tap your circle at the top, then Profile & password.",
    )),
    Release(4, "Helpers for while you crochet", (
        "Stash: your yarn and tools, with photos. Link yarn to a project and it tells you if you have enough.",
        "Pick what you count while following a pattern: rows, repeats like \"(sc, inc) x6\", or every stitch.",
        "When you finish a round it reminds you what your stitch count should be, with help if it's off.",
        "Tap pad: the whole screen becomes one big counter, great for long chains.",
        "Make 2: \"Arms (make 2)\" becomes Arm 1 of 2 and Arm 2 of 2. \"Repeat rows 4-7 three times\" becomes real steps too.",
        "Frog the last row with one tap. It happens to everyone!",
        "Marker and stretch reminders: a nudge every N stitches, and a reminder to rest your hands and check your tension.",
        "Tap any underlined stitch in a pattern to see how to do it, or open the Stitch glossary.",
        "Hands-free: tap the mic and say \"next\", \"count\", \"back\", \"frog\" or \"read\".",
        "Time tracking: see how long you've spent on each project.",
        "Add Crochet Studio to your phone's home screen and it opens like an app.",
    )),
)
LATEST = RELEASES[-1].version


def popup_for(user) -> tuple[str, list[Release]]:
    """('welcome' | 'hello' | 'whatsnew' | '', releases to show) for this profile right now.

    First open: the chosen profile gets the personal anniversary note; everyone else gets a general welcome.
    Either way it's dismissed once (seen_version jumps to LATEST) and never shows again.
    """
    if user is None:
        return "", []
    seen = user.seen_version or 0
    if seen == 0:
        return ("welcome" if gets_welcome(user) else "hello"), []
    unseen = [r for r in RELEASES if r.version > seen]
    return ("whatsnew", unseen) if unseen else ("", [])
