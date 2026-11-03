"""'What's new' popups. Add a release at the end of RELEASES whenever features ship."""

from dataclasses import dataclass

# Only this profile gets the one-time welcome note on first open.
WELCOME_PROFILE = "Jillian"


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
)
LATEST = RELEASES[-1].version


def popup_for(user) -> tuple[str, list[Release]]:
    """('welcome' | 'whatsnew' | '', releases to show) for this profile right now."""
    if user is None:
        return "", []
    seen = user.seen_version or 0
    if seen == 0:
        return ("welcome", []) if user.name == WELCOME_PROFILE else ("", [])
    unseen = [r for r in RELEASES if r.version > seen]
    return ("whatsnew", unseen) if unseen else ("", [])
