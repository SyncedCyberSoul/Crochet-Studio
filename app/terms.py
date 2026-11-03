"""US <-> UK crochet terms. The same stitch has different names, so this swaps them in one pass."""

import re

# US term -> UK term. Order doesn't matter: matching is longest-first, single pass.
US_TO_UK = {
    "half double crochet": "half treble crochet",
    "single crochet": "double crochet",
    "double crochet": "treble crochet",
    "treble crochet": "double treble crochet",
    "double treble crochet": "triple treble crochet",
    "yarn over": "yarn round hook",
    "skip": "miss",
    "gauge": "tension",
    "sc": "dc",
    "hdc": "htr",
    "dc": "tr",
    "tr": "dtr",
    "dtr": "trtr",
    "yo": "yrh",
}
UK_TO_US = {uk: us for us, uk in US_TO_UK.items()} | {"ttr": "dtr", "ss": "sl st"}

# Abbreviations may carry suffixes: sc2tog, dc3tog, dcs, hdc-blo.
_ABBR_SUFFIX = r"(?P<suffix>\d+tog|s)?"


def _build(mapping: dict[str, str]) -> re.Pattern:
    keys = sorted(mapping, key=len, reverse=True)
    words = "|".join(re.escape(k) for k in keys)
    return re.compile(rf"(?<![\w-])(?P<term>{words}){_ABBR_SUFFIX}(?![\w])", re.I)


_PATTERNS = {("us", "uk"): (_build(US_TO_UK), US_TO_UK), ("uk", "us"): (_build(UK_TO_US), UK_TO_US)}


def _match_case(original: str, replacement: str) -> str:
    if original.isupper() and len(original) > 1:
        return replacement.upper()
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def convert(text: str, source: str, target: str) -> str:
    source, target = source.lower(), target.lower()
    if source == target or not text:
        return text
    regex, mapping = _PATTERNS[(source, target)]

    def swap(m: re.Match) -> str:
        term = m.group("term")
        suffix = m.group("suffix") or ""
        if suffix == "s" and " " not in term and len(term) > 3:
            return m.group(0)  # "skips", "yos" etc. are rare; avoid mangling real words
        return _match_case(term, mapping[term.lower()]) + suffix

    return regex.sub(swap, text)


def both(text: str, source: str) -> dict[str, str]:
    """{'us': ..., 'uk': ...} for a text written in `source` terms."""
    source = source.lower() if source.lower() in ("us", "uk") else "us"
    other = "uk" if source == "us" else "us"
    return {source: text, other: convert(text, source, other)}
