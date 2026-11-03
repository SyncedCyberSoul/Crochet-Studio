"""Turn pasted pattern text into ordered steps (sections, rows/rounds, stitch counts)."""

import re
from dataclasses import asdict, dataclass
from typing import Optional

KIND_LABELS = {"r": "R", "rnd": "Rnd", "rnds": "Rnd", "round": "Rnd", "rounds": "Rnd", "row": "Row", "rows": "Row"}

ROW_RE = re.compile(
    r"^(?P<kind>rnds?|rounds?|rows?|r)\s*\.?\s*(?P<start>\d+)"
    r"(?:\s*(?:-|–|—|to)\s*(?:(?:rnds?|rows?|r)\s*)?(?P<end>\d+))?"
    r"(?:\s*[:.)\-–—]\s*|\s+)(?P<text>.*)$",
    re.I,
)
NUMBERED_RE = re.compile(r"^(?P<start>\d+)\s*[.):]\s+(?P<text>.+)$")
COUNT_RES = [
    re.compile(r"[(\[{]\s*(\d+)\s*(?:sts?|stitches|sc|dc|hdc|tr)?\s*[)\]}]\s*[.;,]?\s*$", re.I),
    re.compile(r"(?:[-–—=]|total(?: of)?)\s*(\d+)\s*(?:sts?|stitches)\s*[.;]?\s*$", re.I),
]
BULLET_RE = re.compile(r"^[\s•·*\-–]+(?=\S)")
STITCH_WORDS = re.compile(r"\b(sc|dc|hdc|tr|ch|inc|dec|sl ?st|mr|magic ring|fo|blo|flo|sts?)\b", re.I)

MAX_EXPAND = 150


@dataclass
class Step:
    section: str
    label: str
    text: str
    stitch_count: Optional[int]


def stitch_count(text: str) -> Optional[int]:
    for regex in COUNT_RES:
        if m := regex.search(text):
            return int(m.group(1))
    return None


def _is_section(line: str) -> bool:
    if len(line) > 60 or line.endswith((".", ",", ";")):
        return False
    if line.endswith(":"):
        return True
    letters = [c for c in line if c.isalpha()]
    if letters and all(c.isupper() for c in letters):
        return True
    words = line.split()
    return len(words) <= 5 and line[0].isupper() and not STITCH_WORDS.search(line)


def parse(text: str, expand_ranges: bool = True) -> list[Step]:
    steps: list[Step] = []
    group: list[Step] = []  # the steps made from the most recent line ("Rnds 4-6" makes three)
    section = ""
    numbered_kind = "Step"
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = BULLET_RE.sub("", raw).strip()
        if not line:
            continue

        m = ROW_RE.match(line) or NUMBERED_RE.match(line)
        if m:
            kind = KIND_LABELS.get((m.groupdict().get("kind") or "").lower(), numbered_kind)
            if m.groupdict().get("kind"):
                numbered_kind = kind
            body = m.group("text").strip()
            start = int(m.group("start"))
            end = int(m.groupdict().get("end") or start)
            count = stitch_count(body)
            sep = "" if kind == "R" else " "
            if expand_ranges and start < end <= start + MAX_EXPAND:
                group = [Step(section, f"{kind}{sep}{n}", body, count) for n in range(start, end + 1)]
            else:
                label = f"{kind}{sep}{start}" if start == end else f"{kind}{sep}{start}–{end}"
                group = [Step(section, label, body, count)]
            steps.extend(group)
            continue

        if _is_section(line):
            section = line.rstrip(":").strip()
            group = []
            continue

        # A wrapped line (common when copying from a PDF) continues the previous row(s).
        if group and group[0].label and (line[0].islower() or line[0] in "([,&+") and group[0].section == section:
            for step in group:
                step.text = f"{step.text} {line}".strip()
                step.stitch_count = stitch_count(step.text) or step.stitch_count
            continue
        group = [Step(section, "", line, stitch_count(line))]
        steps.extend(group)
    return steps


def parse_dicts(text: str, expand_ranges: bool = True) -> list[dict]:
    return [asdict(s) for s in parse(text, expand_ranges)]
