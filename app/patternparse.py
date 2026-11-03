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
MAX_STEPS = 2000

NUMBER_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve".split())} | {"twice": 2, "once": 1}
REPEAT_RE = re.compile(
    r"^rep(?:eat)?\.?\s+(?:(?P<kind>rnds?|rounds?|rows?|r)\s*)?(?P<start>\d+)\s*(?:-|–|—|to|through|thru)\s*"
    r"(?:(?:rnds?|rounds?|rows?|r)\s*)?(?P<end>\d+)[\s,]*(?:"
    r"(?P<n>\d+|[a-z]+)\s*(?P<more>more\s+)?times?|x\s*(?P<x>\d+)|(?P<x2>\d+)\s*x|(?P<word>twice|once)(?P<more2>\s+more)?)",
    re.I,
)


def _repeat_count(m: re.Match) -> tuple[int, bool] | None:
    """(count, is_extra) from a repeat line; is_extra means 'N more times' (on top of the first pass)."""
    raw = m.group("n") or m.group("x") or m.group("x2") or m.group("word")
    raw = raw.lower()
    count = int(raw) if raw.isdigit() else NUMBER_WORDS.get(raw)
    if not count:
        return None
    return count, bool(m.group("more") or m.group("more2"))


def _expand_repeat(steps: list["Step"], m: re.Match) -> bool:
    """Copy the rows a 'Repeat Rows 4-7 3 times' line refers to. Returns False if they can't be found."""
    parsed = _repeat_count(m)
    if not parsed:
        return False
    count, extra = parsed
    total = count + 1 if extra else count
    if total < 2:
        return True  # "repeat once" after the first pass already written out: nothing to add
    kind = KIND_LABELS.get((m.group("kind") or "").lower())
    start, end = int(m.group("start")), int(m.group("end"))

    def is_row(step: Step, n: int) -> bool:
        k, _, num = step.label.rpartition(" ") if " " in step.label else (step.label[:1], "", step.label[1:])
        return num.isdigit() and int(num) == n and (kind is None or k == kind)

    last_end = next((i for i in range(len(steps) - 1, -1, -1) if is_row(steps[i], end)), None)
    if last_end is None:
        return False
    first = next((i for i in range(last_end, -1, -1) if is_row(steps[i], start)), None)
    if first is None:
        return False
    block = steps[first:last_end + 1]
    if len(steps) + len(block) * (total - 1) > MAX_STEPS:
        return False
    for step in block:
        if step.label:
            step.label = f"{step.label} · rep 1/{total}"
    for k in range(2, total + 1):
        for step in block:
            base = step.label.split(" · rep ")[0]
            steps.append(Step(step.section, f"{base} · rep {k}/{total}" if base else "", step.text, step.stitch_count))
    return True


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
    section_start, section_make = 0, 1  # where the current section began, and how many pieces it makes
    numbered_kind = "Step"
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = BULLET_RE.sub("", raw).strip()
        if not line:
            continue

        if rep := REPEAT_RE.match(line):
            if not _expand_repeat(steps, rep):
                steps.append(Step(section, "", line, None))  # rows not found: keep it as a written reminder
            group = []
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
            _finish_section(steps, section_start, section_make)
            section, section_make = _section_name(line.rstrip(":").strip())
            section_start = len(steps)
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
    _finish_section(steps, section_start, section_make)
    return steps


MAKE_RE = re.compile(r"\s*[(\[]?\s*make\s+(\d+|two|three|four|five|six)\s*(?:pieces|pcs|of them)?\s*[)\]]?\s*", re.I)


def _section_name(raw: str) -> tuple[str, int]:
    """'Arms (make 2)' -> ('Arms', 2). Amigurumi parts are often made more than once."""
    m = MAKE_RE.search(raw)
    if not m:
        return raw, 1
    n = m.group(1).lower()
    count = int(n) if n.isdigit() else NUMBER_WORDS.get(n, 1)
    name = (raw[:m.start()] + " " + raw[m.end():]).strip(" -–:,") or raw
    return name, count if 2 <= count <= 12 else 1


def _finish_section(steps: list[Step], start: int, make: int) -> None:
    """Write out a 'make 2' section once per piece: 'Arms · 1 of 2', then 'Arms · 2 of 2'."""
    if make < 2 or start >= len(steps):
        return
    block = steps[start:]
    if len(steps) + len(block) * (make - 1) > MAX_STEPS:
        return
    name = block[0].section
    for step in block:
        step.section = f"{name} · 1 of {make}"
    for k in range(2, make + 1):
        steps.extend(Step(f"{name} · {k} of {make}", s.label, s.text, s.stitch_count) for s in block)


def parse_dicts(text: str, expand_ranges: bool = True) -> list[dict]:
    return [asdict(s) for s in parse(text, expand_ranges)]
