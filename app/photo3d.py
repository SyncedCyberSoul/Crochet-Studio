"""Photo -> spinnable 3D: cut the subject out of its background, then 'inflate' its outline into a rounded shape.

No AI service: the subject is found from colour clusters that keep away from the photo's edges (works best when
the piece stands out from its background), and thickness comes from how far each point is from the outline, so
thick parts (a head) puff up more than thin ones (an arm), like a stuffed toy.
"""

import io
import math
from collections import deque
from dataclasses import dataclass

from PIL import Image, ImageFilter, ImageOps

GRID = 160  # depth-map resolution (longest side): also the mesh resolution in the viewer
TEXTURE = 1024  # texture resolution (longest side)
BAND = 0.05  # how much of each edge counts as "border"


class NotAnImage(ValueError):
    pass


@dataclass
class Relief:
    texture: bytes  # WebP with transparency outside the subject
    depth: bytes  # grayscale PNG, GRID-sized
    thumb: bytes  # square WebP preview
    cutout: bool  # False when no clear subject was found (whole photo used as a gently raised card)


def _largest_component(mask: list[bool], w: int, h: int) -> list[bool]:
    seen = [False] * (w * h)
    best: list[int] = []
    for start in range(w * h):
        if not mask[start] or seen[start]:
            continue
        comp, queue = [], deque([start])
        seen[start] = True
        while queue:
            i = queue.popleft()
            comp.append(i)
            x, y = i % w, i // w
            for j in (i - 1 if x else -1, i + 1 if x < w - 1 else -1, i - w if y else -1, i + w if y < h - 1 else -1):
                if j >= 0 and mask[j] and not seen[j]:
                    seen[j] = True
                    queue.append(j)
        if len(comp) > len(best):
            best = comp
    out = [False] * (w * h)
    for i in best:
        out[i] = True
    return out


def _neighbours(i: int, w: int, h: int):
    x, y = i % w, i // w
    if x: yield i - 1
    if x < w - 1: yield i + 1
    if y: yield i - w
    if y < h - 1: yield i + w


def _fill_holes(mask: list[bool], w: int, h: int, pixels: list[tuple]) -> list[bool]:
    """Fill gaps enclosed by the subject (eyes, shadowy stitches) but not background seen through a gap
    (the floor between an arm and the body): a hole is background if it looks like the background next to it."""
    n = w * h
    outside = [False] * n
    queue = deque(i for i in range(n) if (i % w in (0, w - 1) or i // w in (0, h - 1)) and not mask[i])
    for i in queue:
        outside[i] = True
    while queue:
        for j in _neighbours(queue.popleft(), w, h):
            if not mask[j] and not outside[j]:
                outside[j] = True
                queue.append(j)

    def mean(indices) -> tuple[float, float, float]:
        k = len(indices)
        return tuple(sum(pixels[i][c] for i in indices) / k for c in range(3))

    margin = max(6, round(max(w, h) * 0.07))
    out = list(mask)
    seen = [False] * n
    for start in range(n):
        if mask[start] or outside[start] or seen[start]:
            continue
        hole, queue = [], deque([start])
        seen[start] = True
        while queue:
            i = queue.popleft()
            hole.append(i)
            for j in _neighbours(i, w, h):
                if not mask[j] and not outside[j] and not seen[j]:
                    seen[j] = True
                    queue.append(j)
        xs, ys = [i % w for i in hole], [i // w for i in hole]
        x0, x1 = max(0, min(xs) - margin), min(w - 1, max(xs) + margin)
        y0, y1 = max(0, min(ys) - margin), min(h - 1, max(ys) + margin)
        nearby = [y * w + x for y in range(y0, y1 + 1) for x in range(x0, x1 + 1) if outside[y * w + x]]
        looks_like_background = False
        if nearby and len(hole) >= n * 0.0015:
            a, b = mean(hole), mean(nearby)
            looks_like_background = math.dist(a, b) < 55
        if not looks_like_background:
            for i in hole:
                out[i] = True
    return out


def _distance(mask: list[bool], w: int, h: int) -> list[float]:
    """Chamfer (3-4) distance from each subject pixel to the nearest background pixel."""
    d = [10**9 if m else 0 for m in mask]

    def at(x: int, y: int) -> int:  # outside the photo counts as background
        return d[y * w + x] if 0 <= x < w and 0 <= y < h else 0

    forward = ((-1, 0, 3), (0, -1, 3), (-1, -1, 4), (1, -1, 4))
    backward = ((1, 0, 3), (0, 1, 3), (1, 1, 4), (-1, 1, 4))
    for passes, ys, xs in ((forward, range(h), range(w)), (backward, range(h - 1, -1, -1), range(w - 1, -1, -1))):
        for y in ys:
            for x in xs:
                i = y * w + x
                if d[i]:
                    d[i] = min(d[i], *(at(x + dx, y + dy) + cost for dx, dy, cost in passes))
    return [v / 3 for v in d]


def _subject_mask(small: Image.Image) -> list[bool]:
    w, h = small.size
    # Cluster colours (median cut is fast and keeps distinct colours apart), after a light blur to calm texture.
    quant = small.filter(ImageFilter.GaussianBlur(1.2)).quantize(colors=10, method=Image.Quantize.MEDIANCUT)
    labels = list(quant.getdata())
    bx, by = max(1, int(w * BAND)), max(1, int(h * BAND))
    total = [0] * 256
    border = [0] * 256
    for i, c in enumerate(labels):
        total[c] += 1
        x, y = i % w, i // w
        if x < bx or x >= w - bx or y < by or y >= h - by:
            border[c] += 1
    band_share = sum(border) / len(labels)
    # A colour spread evenly over the photo touches the border about band_share of the time; the subject far less.
    fg = {c for c in range(256) if total[c] > len(labels) * 0.004 and border[c] / total[c] < band_share * 0.35}
    mask = [c in fg for c in labels]
    # Close small gaps (stitch shadows), then keep the main piece and fill its holes.
    img = Image.frombytes("L", (w, h), bytes(255 if m else 0 for m in mask))
    img = img.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    mask = [p > 127 for p in img.getdata()]
    return _fill_holes(_largest_component(mask, w, h), w, h, list(small.getdata()))


def make_relief(data: bytes) -> Relief:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:  # Pillow raises several kinds for bad input
        raise NotAnImage(str(exc)) from exc
    img = ImageOps.exif_transpose(img).convert("RGB")

    scale = GRID / max(img.size)
    gw, gh = max(8, round(img.width * scale)), max(8, round(img.height * scale))
    small = img.resize((gw, gh), Image.Resampling.LANCZOS)
    mask = _subject_mask(small)
    area = sum(mask) / len(mask)
    cutout = 0.03 < area < 0.85

    lum = list(small.convert("L").getdata())
    if cutout:
        dist = _distance(mask, gw, gh)
        peak = max(dist) or 1
        # Height in grid pixels: sqrt gives round, stuffed-toy cross sections (as tall as the piece is wide at its
        # thickest), and a touch of brightness adds stitch-scale texture.
        heights = [math.sqrt(d * peak) * (0.96 + 0.08 * (lum[i] / 255 - 0.5)) if mask[i] else 0.0
                   for i, d in enumerate(dist)]
    else:
        # No clear subject: a photo "card" with gentle relief from brightness, raised in the middle.
        mask = [True] * (gw * gh)
        long_side = max(gw, gh)
        heights = []
        for i, v in enumerate(lum):
            x, y = (i % gw) / (gw - 1) - 0.5, (i // gw) / (gh - 1) - 0.5
            dome = max(0.0, 1 - (x * x + y * y) * 2.2)
            heights.append((0.02 + 0.05 * dome + 0.03 * (v / 255)) * long_side)
    # Stored so that 255 = half the photo's long side; the viewer scales by the same rule.
    unit = 0.5 * max(gw, gh)
    depth = Image.frombytes("L", (gw, gh), bytes(min(255, int(hgt / unit * 255)) for hgt in heights))
    depth = depth.filter(ImageFilter.GaussianBlur(0.8))

    tex_scale = min(1.0, TEXTURE / max(img.size))
    tex = img.resize((max(1, round(img.width * tex_scale)), max(1, round(img.height * tex_scale))), Image.Resampling.LANCZOS)
    alpha = Image.frombytes("L", (gw, gh), bytes(255 if m else 0 for m in mask))
    alpha = alpha.resize(tex.size, Image.Resampling.BILINEAR).filter(ImageFilter.GaussianBlur(1))
    tex.putalpha(alpha)

    def encode(image: Image.Image, fmt: str, **kw) -> bytes:
        buf = io.BytesIO()
        image.save(buf, fmt, **kw)
        return buf.getvalue()

    # Thumbnail: the cut-out centred on a soft card.
    box = tex.getbbox() or (0, 0, *tex.size)
    piece = tex.crop(box)
    piece.thumbnail((400, 400), Image.Resampling.LANCZOS)
    thumb = Image.new("RGB", (480, 480), (243, 234, 224))
    thumb.paste(piece, ((480 - piece.width) // 2, (480 - piece.height) // 2), piece)

    return Relief(
        texture=encode(tex, "WEBP", quality=90),
        depth=encode(depth, "PNG"),
        thumb=encode(thumb, "WEBP", quality=85),
        cutout=cutout,
    )
