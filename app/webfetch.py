"""Fetching from the internet safely: public addresses only, size and time limits."""

import ipaddress
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0 Safari/537.36 CrochetStudio/1.0")


class FetchError(Exception):
    """Something the person can be told: blocked, unreachable, too big, wrong type."""


def _check_public(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise FetchError("Only web links (http or https) work here.")
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror:
        raise FetchError("Couldn't find that website.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        # Never let a link make the server talk to the laptop itself or the home network.
        if not ip.is_global:
            raise FetchError("That address isn't on the public internet.")


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_public(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_CheckedRedirects)


@dataclass
class Fetched:
    data: bytes
    content_type: str
    url: str


def fetch(url: str, max_bytes: int = 5_000_000, timeout: float = 12, accept: str = "*/*") -> Fetched:
    url = url.strip()
    _check_public(url)
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept, "Accept-Language": "en"})
    try:
        with _opener.open(request, timeout=timeout) as response:
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise FetchError("That file is too big.")
            return Fetched(data, response.headers.get_content_type(), response.geturl())
    except urllib.error.HTTPError as exc:
        raise FetchError(f"The website answered with an error ({exc.code}).")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        if isinstance(exc, FetchError):
            raise
        raise FetchError("Couldn't reach that website.")


def fetch_image(url: str) -> bytes:
    got = fetch(url, max_bytes=15_000_000, accept="image/*")
    if not got.content_type.startswith("image/") and not got.data[:4] in (b"\x89PNG", b"RIFF") and got.data[:2] != b"\xff\xd8":
        raise FetchError("That link isn't an image.")
    return got.data


# ---------- link previews (Pinterest pins, blog posts, shop pages) ----------

class _MetaParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title = ""
        self._in_title = False
        self.first_img = ""

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key and a.get("content") and key not in self.meta:
                self.meta[key] = a["content"]
        elif tag == "link" and a.get("rel", "").lower() == "image_src" and a.get("href"):
            self.meta.setdefault("image_src", a["href"])
        elif tag == "title":
            self._in_title = True
        elif tag == "img" and not self.first_img and a.get("src", "").startswith(("http", "/")):
            self.first_img = a["src"]

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title and len(self.title) < 300:
            self.title += data


@dataclass
class Preview:
    url: str
    title: str
    image: str
    description: str


def link_preview(url: str) -> Preview:
    got = fetch(url, max_bytes=3_000_000, accept="text/html,application/xhtml+xml,image/*")
    if got.content_type.startswith("image/"):
        return Preview(got.url, "", got.url, "")
    parser = _MetaParser()
    parser.feed(got.data.decode("utf-8", "replace"))
    m = parser.meta
    image = m.get("og:image") or m.get("og:image:url") or m.get("twitter:image") or m.get("image_src") or parser.first_img
    title = m.get("og:title") or m.get("twitter:title") or parser.title
    description = m.get("og:description") or m.get("description") or ""
    return Preview(
        url=m.get("og:url") or got.url,
        title=" ".join(unescape(title).split())[:200],
        image=urljoin(got.url, image) if image else "",
        description=" ".join(unescape(description).split())[:600],
    )
