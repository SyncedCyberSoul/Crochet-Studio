"""Pull a written pattern off a web page (a free blog pattern, usually) and turn it into steps.

Pages are mostly chatter, photos and ads with the pattern in the middle, so this finds the run of lines
that look like rows/rounds ("Rnd 3: ...", "Row 12: ...", "1. ..."), keeps the section headings and
finishing lines around them, and hands that to the normal pattern parser. It also picks out the hook size
and the materials list if the page has them.
"""

import re
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlparse

from .patternparse import NUMBERED_RE, REPEAT_RE, ROW_RE, Step, _is_section, parse
from .webfetch import FetchError, fetch

SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "footer", "header", "aside", "form", "button", "select",
             "iframe", "template", "figure", "figcaption"}
BLOCK_TAGS = {"p", "li", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "td", "section", "article", "blockquote",
              "pre", "dt", "dd", "ul", "ol", "table"}
JUNK = re.compile(r"^(advertisement|ad|pin it|save|print|share|tweet|jump to|skip to|this post may contain|"
                  r"click here|subscribe|sign up|leave a comment|related|you may also like)\b", re.I)
# Where a blog's sign-off starts: stop collecting finishing lines here.
SIGNOFF = re.compile(r"(follow me|facebook|instagram|pinterest|youtube|tiktok|newsletter|subscribe|affiliate|"
                     r"copyright|©|all rights reserved|looking for more|more patterns|share (it|this)|tag me|#\w)", re.I)
HOOK_RE = re.compile(r"\b(\d{1,2}(?:\.\d{1,2})?)\s*mm\b", re.I)
MATERIALS_HEAD = re.compile(r"^(materials|supplies|you will need|what you'?ll need|yarn|notions|tools)\b", re.I)
MIN_ROWS = 3


class _TextLines(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._buf: list[str] = []
        self._skip = 0
        self.title = ""
        self._in_title = False

    def _flush(self):
        text = " ".join("".join(self._buf).split())
        if text:
            self.lines.append(text)
        self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        if tag in BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        if tag in BLOCK_TAGS:
            self._flush()

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self._buf.append(data)

    def close(self):
        super().close()
        self._flush()


def page_lines(html: str) -> tuple[str, list[str]]:
    parser = _TextLines()
    parser.feed(html)
    parser.close()
    lines = [unescape(l).strip() for l in parser.lines]
    return " ".join(parser.title.split()), [l for l in lines if l and not JUNK.match(l) and len(l) < 1200]


def _is_row(line: str) -> bool:
    line = re.sub(r"^[\s•·*\-–]+", "", line)
    return bool(ROW_RE.match(line) or REPEAT_RE.match(line) or (NUMBERED_RE.match(line) and re.search(
        r"\b(sc|dc|hdc|tr|ch|inc|dec|sl ?st|st|sts|mr|blo|flo)\b", line, re.I)))


@dataclass
class Imported:
    title: str
    source_url: str
    designer: str
    text: str  # the pattern part of the page, as plain lines
    steps: list[Step] = field(default_factory=list)
    hook: str = ""
    materials: str = ""


def find_pattern(lines: list[str]) -> tuple[int, int] | None:
    """Start/end (inclusive) of the densest run of row lines on the page."""
    rows = [i for i, l in enumerate(lines) if _is_row(l)]
    if len(rows) < MIN_ROWS:
        return None
    # Split into clusters wherever there's a long gap of non-row lines (a different part of the page),
    # then keep the cluster with the most rows: that's the pattern.
    clusters, current = [], [rows[0]]
    for i in rows[1:]:
        if i - current[-1] > 25:
            clusters.append(current)
            current = []
        current.append(i)
    clusters.append(current)
    best = max(clusters, key=len)
    if len(best) < MIN_ROWS:
        return None
    start, end = best[0], best[-1]
    # Include the headings just before the first row ("HEAD", "Arms (make 2)", "Round 1 notes").
    while start > 0 and best[0] - start < 4 and _is_section(lines[start - 1]):
        start -= 1
    # And the finishing lines just after ("Fasten off, leaving a long tail.").
    while (end + 1 < len(lines) and end - best[-1] < 3 and len(lines[end + 1]) < 160
           and not _is_section(lines[end + 1]) and not SIGNOFF.search(lines[end + 1])):
        end += 1
    return start, end


def _materials(lines: list[str], before: int) -> str:
    for i, line in enumerate(lines[:before]):
        if MATERIALS_HEAD.match(line) and len(line) < 60:
            block = [l for l in lines[i + 1:min(i + 12, before)] if len(l) < 200]
            return "\n".join(block[:10])
    return ""


def import_from_url(url: str, title_hint: str = "") -> Imported | None:
    """Fetch the page and pull out the pattern. None if the page has no written rows we can find."""
    got = fetch(url, max_bytes=4_000_000, accept="text/html,application/xhtml+xml")
    if not got.content_type.startswith(("text/html", "application/xhtml")):
        return None
    page_title, lines = page_lines(got.data.decode("utf-8", "replace"))
    span = find_pattern(lines)
    if not span:
        return None
    start, end = span
    text = "\n".join(l for l in lines[start:end + 1] if not SIGNOFF.search(l))
    steps = parse(text)
    if sum(1 for s in steps if s.label) < MIN_ROWS:
        return None
    materials = _materials(lines, start)
    hook_match = HOOK_RE.search(materials) or HOOK_RE.search(" ".join(lines[max(0, start - 40):start]))
    host = (urlparse(got.url).hostname or "").removeprefix("www.")
    title = (title_hint or page_title.split(" | ")[0].split(" - ")[0] or "Imported pattern").strip()[:200]
    return Imported(title=title, source_url=got.url, designer=host, text=text, steps=steps,
                    hook=f"{hook_match.group(1)} mm" if hook_match else "", materials=materials)


__all__ = ["FetchError", "Imported", "import_from_url"]
