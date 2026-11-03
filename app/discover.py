"""Discover: project ideas pulled from crochet blog / Pinterest board / Reddit feeds."""

import json
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from html import unescape
from itertools import zip_longest
from urllib.parse import urljoin, urlparse

from sqlmodel import Session

from .auth import get_setting
from .webfetch import FetchError, fetch

DEFAULT_FEEDS = [
    {"name": "r/crochet (top this week)", "url": "https://www.reddit.com/r/crochet/top/.rss?t=week"},
    {"name": "Moogly", "url": "https://www.mooglyblog.com/feed/"},
    {"name": "Repeat Crafter Me", "url": "https://www.repeatcrafterme.com/feed"},
    {"name": "Hooked on Homemade Happiness", "url": "https://www.hookedonhomemadehappiness.com/feed/"},
    {"name": "Daisy Farm Crafts", "url": "https://www.daisyfarmcrafts.com/feed/"},
    {"name": "PlanetJune (amigurumi)", "url": "https://www.planetjune.com/blog/feed/"},
    {"name": "Sarah Maker", "url": "https://sarahmaker.com/feed/"},
]
CACHE_SECONDS = 60 * 60
PER_FEED = 18

_cache: dict[str, tuple[float, list["Item"]]] = {}
_lock = threading.Lock()

IMG_RE = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.I)
TAG_RE = re.compile(r"<[^>]+>")
NS = {
    "media": "http://search.yahoo.com/mrss/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "atom": "http://www.w3.org/2005/Atom",
}


@dataclass
class Item:
    title: str
    link: str
    image: str
    source: str
    summary: str


def feed_list(session: Session) -> list[dict]:
    raw = get_setting(session, "discover_feeds")
    try:
        feeds = json.loads(raw) if raw else []
    except ValueError:
        feeds = []
    return feeds or DEFAULT_FEEDS


def _text(el) -> str:
    return (el.text or "").strip() if el is not None else ""


def _image_from(entry, html_blobs: list[str], base: str) -> str:
    for path in ("media:thumbnail", "media:content", "media:group/media:thumbnail", "media:group/media:content"):
        for el in entry.findall(path, NS):
            url = el.get("url", "")
            if url and (el.get("medium") in (None, "image") or "image" in el.get("type", "image")):
                return unescape(url)
    for el in entry.findall("enclosure"):
        if el.get("type", "").startswith("image/") and el.get("url"):
            return el.get("url")
    for blob in html_blobs:
        for src in IMG_RE.findall(blob):
            src = unescape(src)
            # Skip tracking pixels, emoji and avatars.
            if not re.search(r"(gravatar|emoji|pixel|feeds\.feedburner|1x1|spacer)", src, re.I):
                return urljoin(base, src)
    return ""


def parse_feed(data: bytes, source: str, base: str) -> list[Item]:
    root = ET.fromstring(data)
    items: list[Item] = []
    entries = root.findall("./channel/item") or root.findall("atom:entry", NS) or root.findall(".//item")
    for entry in entries[:PER_FEED * 2]:
        if entry.tag.endswith("entry"):  # Atom (Reddit)
            title = _text(entry.find("atom:title", NS))
            link_el = entry.find("atom:link[@rel='alternate']", NS)
            if link_el is None:  # (an Element with no children is falsy, so no `or` here)
                link_el = entry.find("atom:link", NS)
            link = link_el.get("href", "") if link_el is not None else ""
            blobs = [_text(entry.find("atom:content", NS)), _text(entry.find("atom:summary", NS))]
        else:  # RSS
            title = _text(entry.find("title"))
            link = _text(entry.find("link"))
            blobs = [_text(entry.find("content:encoded", NS)), _text(entry.find("description"))]
        image = _image_from(entry, blobs, base)
        if not (title and link and image):
            continue  # Discover is a picture board; skip posts without one
        summary = " ".join(unescape(TAG_RE.sub(" ", blobs[1] or blobs[0])).split())[:220]
        items.append(Item(unescape(title)[:160], link, image, source, summary))
        if len(items) >= PER_FEED:
            break
    return items


def _load(feed: dict) -> tuple[list[Item], str]:
    url = feed["url"]
    with _lock:
        cached = _cache.get(url)
    if cached and time.time() - cached[0] < CACHE_SECONDS:
        return cached[1], ""
    try:
        got = fetch(url, max_bytes=4_000_000, accept="application/rss+xml,application/atom+xml,application/xml,text/xml")
        items = parse_feed(got.data, feed.get("name") or urlparse(url).hostname or url, got.url)
    except (FetchError, ET.ParseError) as exc:
        if cached:
            return cached[1], ""  # keep showing the last good copy
        return [], f"{feed.get('name') or url}: {exc if isinstance(exc, FetchError) else 'not a readable feed'}"
    with _lock:
        _cache[url] = (time.time(), items)
    return items, ""


def gather(feeds: list[dict]) -> tuple[list[Item], list[str]]:
    """All feeds' items, mixed so one busy blog doesn't fill the whole page."""
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(_load, feeds))
    errors = [err for _, err in results if err]
    mixed = [item for group in zip_longest(*(items for items, _ in results)) for item in group if item]
    return mixed, errors
