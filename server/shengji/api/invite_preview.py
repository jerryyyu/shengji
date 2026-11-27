"""A table's link preview: what Messages and other apps show for an invite
link ``/?code=<code>`` while that table is live.

``table_view`` turns the seats anyone holding the code can already peek into
the preview's view: per seat only open, held, a bot, or a person's initials
or companion, and never a full name, an account or a rating. ``page_tags`` rewrites the
built page's preview tags for that view, and ``render_png`` draws its
1200 x 630 card: the felt, the 升级 wordmark, the code, four seats (the
opener's team first, in blue) and one line for the seat count. An unknown or
ended code, a table a join by that code cannot enter, and an image URL made
for an earlier state of the table get the site's own tags and
``default_png``, which carries nothing about any table.

The card is composed from baked coverage masks (``invite_atlas.npz``, made
by web/scripts/og-table/bake.mjs), tinted and blended with numpy, and
written as a PNG with zlib, so serving it needs no font or image library.
A person whose Collection is on (``accounts.card_look``) shows their
companion's round portrait in place of their initials: a pre-rendered PNG
per look under ``portraits/<companion>/<colour>.png``, read with zlib and
numpy once and kept, so no drawing is rasterized for a request.
"""

from __future__ import annotations

import html
import json
import re
import struct
import threading
import time
import unicodedata
import zlib
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import accounts, matchmaking

SITE_ORIGIN = "https://playshengji.com"
WIDTH, HEIGHT = 1200, 630
CODE_RE = re.compile(rf"^[{matchmaking.CODE_ALPHABET}]{{{matchmaking.CODE_LEN}}}$")
# How long a card may be reused: a seat that fills shows within a minute.
CACHE_SECS = 60.0
CACHE_MAX = 256

# What one seat shows: a person's initials, a bot, an empty seat, or a Duo
# opener's seat held for their partner.
PERSON, BOT, OPEN, HELD = "person", "bot", "open", "held"


@dataclass(frozen=True)
class Seat:
    kind: str
    initials: str = ""    # PERSON only: one or two of A-Z 0-9, or "" for the person mark
    look: str = ""        # PERSON only: the companion drawn in place of the initials, or ""
    us: bool = True       # on the opener's team
    free: bool = False    # a join by this code may take it


@dataclass(frozen=True)
class TableView:
    code: str
    seats: tuple[Seat, ...]   # display order: the opener's team first
    table: str = ""           # which table holds the code now, so a reused code is a new card

    @property
    def free(self) -> int:
        return sum(s.free for s in self.seats)

    @property
    def ask(self) -> str:
        """Which invite this is: ``partner`` when the code's join takes a
        held seat, else ``one``/``two``/``three`` by the seats it may take."""
        if any(s.free and s.kind == HELD for s in self.seats):
            return "partner"
        return {1: "one", 2: "two"}.get(self.free, "three")

    def key(self) -> str:
        """The state the card draws and the table it is of, for the card's
        cache and its URL."""
        seats = "".join(f"{s.kind[0]}{s.initials}{int(s.us)}{int(s.free)}{s.look}|" for s in self.seats)
        return f"{self.table}:{seats}{self.ask}"

    def state(self) -> str:
        return f"{zlib.crc32(self.key().encode()) & 0xFFFFFFFF:08x}"


def valid_code(raw: object) -> str | None:
    code = str(raw or "").strip().upper()
    return code if CODE_RE.match(code) else None


def initials(name: str | None) -> str:
    """A name's initials as the card draws them: the first letters of its
    first and last words, Latin letters and digits only (accents dropped),
    uppercase; "" when it has none, drawn as the person mark."""
    flat = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    words = [w for w in re.split(r"[^A-Za-z0-9]+", flat) if w]
    if not words:
        return ""
    picked = words[0][0] + (words[-1][0] if len(words) > 1 else "")
    return picked.upper()


def table_view(code: str, opener: int, seats: list[tuple],
               table: str = "") -> TableView | None:
    """The view of four seats ``(kind, name, free)`` or ``(kind, name,
    free, look)`` by seat number, seen from the opener's seat: the opener
    and their partner, then the other team. ``free`` is what a join by
    ``code`` may take (the Join panel's own projection); ``look`` is a
    person's ``accounts.card_look``, kept only when a portrait of it ships.
    None when it may take nothing: a full or closed table has no preview of
    its own. Names become initials here and go no further."""
    order = [opener % 4, (opener + 2) % 4, (opener + 1) % 4, (opener + 3) % 4]
    view = []
    for n, i in enumerate(order):
        kind, name, free, *rest = seats[i] if i < len(seats) else (OPEN, None, False)
        look = rest[0] if rest and kind == PERSON and portrait_path(rest[0]) is not None else ""
        view.append(Seat(kind, initials(name) if kind == PERSON else "", look, n < 2, bool(free)))
    if not any(s.free for s in view):
        return None
    return TableView(code, tuple(view), table)


# The words, per ask. The message text matches the web's share text
# (web/src/i18n/messages/home.ts "home.invite.*").
TITLE_EN = {"one": "1 open seat", "two": "2 open seats", "three": "3 open seats",
            "partner": "partner seat open"}
TITLE_ZH = {"one": "三缺一", "two": "二缺二", "three": "一缺三", "partner": "等搭档"}
MESSAGE_EN = {"one": "We need a 4th for Tractor. Code {code}",
              "two": "Two seats open for Tractor. Code {code}",
              "three": "Play Tractor with me? Code {code}",
              "partner": "Be my partner for Tractor? Code {code}"}
MESSAGE_ZH = {"one": "三缺一，来打升级！房间码 {code}",
              "two": "还差两个人，来打升级！房间码 {code}",
              "three": "来打升级吗？房间码 {code}",
              "partner": "来跟我搭档打升级！房间码 {code}"}


def prefers_zh(accept_language: str | None) -> bool:
    """Whether the asker's first language, by Accept-Language weight, is Chinese."""
    best, best_q = "", -1.0
    for item in (accept_language or "").split(","):
        tag, _, params = item.strip().partition(";")
        q = 1.0
        for p in params.split(";"):
            k, _, v = p.strip().partition("=")
            if k == "q":
                try:
                    q = float(v)
                except ValueError:
                    q = 0.0
        if tag and q > best_q:
            best, best_q = tag.lower(), q
    return best.startswith("zh")


def texts(view: TableView, zh: bool) -> tuple[str, str]:
    """The preview's title and description in one language."""
    if zh:
        return (f"牌桌 {view.code} · {TITLE_ZH[view.ask]}",
                MESSAGE_ZH[view.ask].format(code=view.code))
    return (f"Table {view.code} · {TITLE_EN[view.ask]}",
            MESSAGE_EN[view.ask].format(code=view.code))


def image_url(view: TableView) -> str:
    # The state in the query: the image route draws this table only while its
    # state still matches, so an old URL never shows a newer roster.
    return f"{SITE_ORIGIN}/og/table/{view.code}.png?s={view.state()}"


def card_for(view: TableView | None, state: object) -> TableView | None:
    """The view an image request with ``state`` may draw: the live view
    only when the URL was made for exactly this table and seats."""
    if view is None or not isinstance(state, str) or state != view.state():
        return None
    return view


def _set_meta(page: str, attr: str, key: str, value: str) -> str:
    pattern = re.compile(rf'<meta {attr}="{re.escape(key)}" content="[^"]*" />')
    return pattern.sub(lambda _: f'<meta {attr}="{key}" content="{html.escape(value)}" />', page, count=1)


def page_tags(page: str, view: TableView, zh: bool) -> str:
    """The built index.html with this table's preview: its title, the message
    as the description, its card as the image, and no video, which an app
    would play in the card's place. The canonical link stays the root's."""
    title, description = texts(view, zh)
    image = image_url(view)
    alt = f"{TITLE_ZH[view.ask]} · {view.code}"
    page = re.sub(r'\s*<meta property="og:video[^"]*" content="[^"]*" />', "", page)
    for attr, key, value in (
            ("property", "og:url", f"{SITE_ORIGIN}/?code={view.code}"),
            ("property", "og:title", title),
            ("property", "og:description", description),
            ("property", "og:image", image),
            ("property", "og:image:secure_url", image),
            ("property", "og:image:type", "image/png"),
            ("property", "og:image:alt", alt),
            ("name", "twitter:title", title),
            ("name", "twitter:description", description),
            ("name", "twitter:image", image),
            ("name", "twitter:image:alt", alt)):
        page = _set_meta(page, attr, key, value)
    return page


# The card.
_ATLAS_PATH = Path(__file__).with_name("invite_atlas.npz")
_atlas: dict | None = None
_atlas_lock = threading.RLock()

FELT = ((0x2D, 0x7A, 0x50), (0x16, 0x4A, 0x2F), (0x0F, 0x3A, 0x24))
GOLD, GOLD_TEXT, CODE_LINE = (0xF2, 0xC1, 0x4E), (0xFF, 0xD7, 0x7A), (0xB9, 0x8D, 0x2A)
SUB, WHITE, OPEN_LINE = (0xC3, 0xCA, 0xD6), (0xFF, 0xFF, 0xFF), (0xE9, 0xEC, 0xF2)
TEAM = {True: ((0x1F, 0x3E, 0x74), (0x5B, 0x9D, 0xFF)),     # fill, ring: blue, the opener's team
        False: ((0x5A, 0x34, 0x17), (0xFF, 0x9D, 0x4A))}    # orange, the other team
MARGIN, SEAT_TOP, SEAT_GAP, LINE_BASE = 60, 214, 60, 560
_PORTRAIT_DIR = Path(__file__).with_name("portraits")
_portraits: dict[tuple[str, int], tuple[np.ndarray, np.ndarray]] = {}


def portrait_path(look: object) -> Path | None:
    """The shipped portrait of ``look`` ("<companion>/<colour>"), or None
    when the look is unknown or has no portrait."""
    parsed = accounts.parse_look(look)
    if parsed is None:
        return None
    path = _PORTRAIT_DIR / parsed[0] / f"{parsed[1]}.png"
    return path if path.is_file() else None


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else b if pb <= pc else c


def read_png(data: bytes) -> np.ndarray:
    """An 8-bit, non-interlaced RGB or RGBA PNG as rows by columns by 4
    (RGB gets an opaque alpha); ValueError for anything else."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos, idat, head = 8, [], None
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            head = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
        pos += 12 + length
    if head is None:
        raise ValueError("no IHDR")
    w, h, depth, colour, _, _, interlace = head
    if depth != 8 or colour not in (2, 6) or interlace:
        raise ValueError("unsupported PNG")
    bpp = 4 if colour == 6 else 3
    raw = zlib.decompress(b"".join(idat))
    stride = w * bpp
    if len(raw) != h * (stride + 1):
        raise ValueError("bad PNG data")
    out = np.zeros((h, stride), dtype=np.uint8)
    prior = np.zeros(stride, dtype=np.uint8)
    for y in range(h):
        kind = raw[y * (stride + 1)]
        row = np.frombuffer(raw, dtype=np.uint8, count=stride, offset=y * (stride + 1) + 1)
        if kind == 0:
            cur = row.copy()
        elif kind == 1:
            cur = (np.cumsum(row.reshape(w, bpp).astype(np.int64), axis=0) % 256).astype(np.uint8).reshape(stride)
        elif kind == 2:
            cur = row + prior
        elif kind in (3, 4):
            line, up = bytearray(row.tobytes()), prior.tobytes()
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                b = up[x]
                if kind == 3:
                    line[x] = (line[x] + ((a + b) >> 1)) & 0xFF
                else:
                    c = up[x - bpp] if x >= bpp else 0
                    line[x] = (line[x] + _paeth(a, b, c)) & 0xFF
            cur = np.frombuffer(bytes(line), dtype=np.uint8)
        else:
            raise ValueError("bad PNG filter")
        out[y], prior = cur, cur
    px = out.reshape(h, w, bpp)
    if bpp == 3:
        px = np.concatenate([px, np.full((h, w, 1), 255, dtype=np.uint8)], axis=2)
    return px


def _resample(n_in: int, n_out: int) -> np.ndarray:
    """The ``n_out`` by ``n_in`` matrix that averages each output pixel's
    share of the input (area resampling)."""
    scale = n_in / n_out
    m = np.zeros((n_out, n_in), dtype=np.float32)
    for i in range(n_out):
        lo, hi = i * scale, (i + 1) * scale
        for j in range(int(lo), min(int(np.ceil(hi)), n_in)):
            m[i, j] = (min(hi, j + 1) - max(lo, j)) / scale
    return m


def _portrait(look: str, size: int) -> tuple[np.ndarray, np.ndarray] | None:
    """``look``'s portrait at ``size`` pixels square: its premultiplied
    colour and its coverage, read once and kept; None without one."""
    key = (look, size)
    with _atlas_lock:
        hit = _portraits.get(key)
    if hit is not None:
        return hit
    path = portrait_path(look)
    if path is None:
        return None
    px = read_png(path.read_bytes()).astype(np.float32) / 255.0
    alpha = px[..., 3:4]
    rgba = np.concatenate([px[..., :3] * alpha, alpha], axis=2)
    ry, rx = _resample(px.shape[0], size), _resample(px.shape[1], size)
    small = np.einsum("ij,jkc->ikc", ry, np.einsum("lk,jkc->jlc", rx, rgba))
    out = (np.ascontiguousarray(small[..., :3] * 255.0), np.ascontiguousarray(small[..., 3:4]))
    with _atlas_lock:
        _portraits[key] = out
    return out


def _load() -> dict:
    global _atlas
    with _atlas_lock:
        if _atlas is None:
            with np.load(_ATLAS_PATH, allow_pickle=False) as z:
                spec = json.loads(str(z["spec"]))
                masks = {k[2:]: (z[k].astype(np.float32) / 255.0, tuple(float(v) for v in z["x_" + k[2:]]))
                         for k in z.files if k.startswith("m_")}
            _atlas = {"spec": spec, "masks": masks, "base": None}
        return _atlas


def _blend(img: np.ndarray, name: str, x: float, y: float, color: tuple[int, int, int]) -> None:
    """Draws mask ``name`` in ``color`` with its top left at (x, y), clipped."""
    mask = _load()["masks"][name][0]
    h, w = mask.shape
    x, y = int(round(x)), int(round(y))
    x1, y1, x2, y2 = max(x, 0), max(y, 0), min(x + w, WIDTH), min(y + h, HEIGHT)
    if x1 >= x2 or y1 >= y2:
        return
    a = mask[y1 - y:y2 - y, x1 - x:x2 - x, None]
    region = img[y1:y2, x1:x2]
    region *= 1.0 - a
    region += a * np.asarray(color, dtype=np.float32)


def _text(img: np.ndarray, name: str, pen_x: float, base: float, color) -> None:
    x0, y0, _ = _load()["masks"][name][1]
    _blend(img, name, pen_x + x0, base + y0, color)


def _adv(name: str) -> float:
    return _load()["masks"][name][1][2]


def _felt() -> np.ndarray:
    """The felt with the wordmark: radial-gradient(ellipse at 60% 50%, three
    stops at 0, 65% and 100% of the farthest corner)."""
    yy, xx = np.mgrid[0:HEIGHT, 0:WIDTH].astype(np.float32)
    cx, cy = 0.6 * WIDTH, 0.5 * HEIGHT
    rx, ry = max(cx, WIDTH - cx) * np.sqrt(2), max(cy, HEIGHT - cy) * np.sqrt(2)
    t = np.clip(np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2), 0, 1)[..., None]
    c0, c1, c2 = (np.asarray(c, dtype=np.float32) for c in FELT)
    inner = c0 + (c1 - c0) * np.clip(t / 0.65, 0, 1)
    img = np.where(t <= 0.65, inner, c1 + (c2 - c1) * np.clip((t - 0.65) / 0.35, 0, 1))
    img = np.ascontiguousarray(img, dtype=np.float32)
    base = MARGIN + 84
    _text(img, "brand_zh", MARGIN, base, GOLD)
    _text(img, "brand_en", MARGIN + _adv("brand_zh") + 24, base, SUB)
    return img


def _base() -> np.ndarray:
    atlas = _load()
    with _atlas_lock:
        if atlas["base"] is None:
            atlas["base"] = _felt()
        return atlas["base"]


def _glyph_row(img, names: list[str], cx: float, base: float, spacing: float, color) -> None:
    width = sum(_adv(n) for n in names) + spacing * (len(names) - 1)
    pen = cx - width / 2
    for n in names:
        _text(img, n, pen, base, color)
        pen += _adv(n) + spacing


def _cap(name: str) -> float:
    return -_load()["masks"][name][1][1] - 4   # the mask's top pad is 4


def _seat(img, seat: Seat, left: float, top: float) -> None:
    spec = _load()["spec"]
    d = spec["seat"]
    cx, cy = left + d / 2, top + d / 2
    if seat.kind in (OPEN, HELD):
        # an empty seat this code's join cannot take (held for someone else) has no +
        _blend(img, "dash_ring", left, top, OPEN_LINE)
        if seat.free:
            mask = _load()["masks"]["plus"][0]
            _blend(img, "plus", cx - mask.shape[1] / 2, cy - mask.shape[0] / 2, OPEN_LINE)
        return
    fill, ring = TEAM[seat.us]
    _blend(img, "disc", left, top, fill)
    art = _portrait(seat.look, d - 2 * spec["seatBorder"] + 2) if seat.look else None
    if art is not None:
        # the companion inside the ring, which is drawn over its edge
        colour, cover = art
        size = colour.shape[0]
        x, y = int(round(cx - size / 2)), int(round(cy - size / 2))
        region = img[y:y + size, x:x + size]
        region *= 1.0 - cover
        region += colour
        _blend(img, "ring", left, top, ring)
        return
    _blend(img, "ring", left, top, ring)
    if seat.kind == BOT or not seat.initials:
        name = "bot" if seat.kind == BOT else "person"
        mask = _load()["masks"][name][0]
        _blend(img, name, cx - mask.shape[1] / 2, cy - mask.shape[0] / 2, WHITE)
        return
    _glyph_row(img, [f"init_{c}" for c in seat.initials], cx, cy + _cap("cap_init") / 2, 2, WHITE)


def _draw(view: TableView | None) -> np.ndarray:
    img = _base().copy()
    if view is None:
        return img
    spec = _load()["spec"]
    box = _load()["masks"]["code_box"][0]
    bx, by = WIDTH - MARGIN - box.shape[1], MARGIN + 2
    _blend(img, "code_box", bx, by, CODE_LINE)
    _glyph_row(img, [f"code_{c}" for c in view.code], bx + box.shape[1] / 2,
               by + box.shape[0] / 2 + _cap("cap_code") / 2, spec["codeSpacing"], GOLD_TEXT)
    d = spec["seat"]
    left = (WIDTH - 4 * d - 3 * SEAT_GAP) / 2
    for n, seat in enumerate(view.seats):
        _seat(img, seat, left + n * (d + SEAT_GAP), SEAT_TOP)
    line = f"line_{view.ask}"
    _text(img, line, (WIDTH - _adv(line)) / 2, LINE_BASE, WHITE)
    return img


def encode_png(rgb: np.ndarray) -> bytes:
    """An 8-bit RGB PNG of ``rgb`` (rows by columns by 3), each row filtered
    with Sub, which suits the smooth felt."""
    px = np.clip(np.rint(rgb), 0, 255).astype(np.uint8)
    h, w, _ = px.shape
    sub = px.astype(np.int16)
    sub[:, 1:] -= px[:, :-1].astype(np.int16)
    rows = np.empty((h, 1 + w * 3), dtype=np.uint8)
    rows[:, 0] = 1
    rows[:, 1:] = (sub % 256).astype(np.uint8).reshape(h, w * 3)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows.tobytes(), 9)) + chunk(b"IEND", b""))


class _Cards:
    """Cards drawn in the last ``CACHE_SECS``, by the state they draw."""

    def __init__(self) -> None:
        self._items: OrderedDict[str, tuple[float, bytes]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str, make, now: float) -> bytes:
        with self._lock:
            hit = self._items.get(key)
            if hit is not None and now - hit[0] < CACHE_SECS:
                self._items.move_to_end(key)
                return hit[1]
        png = make()
        with self._lock:
            self._items[key] = (now, png)
            self._items.move_to_end(key)
            while len(self._items) > CACHE_MAX:
                self._items.popitem(last=False)
        return png

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


CARDS = _Cards()


def render_png(view: TableView | None, now: float | None = None) -> bytes:
    """The card for ``view``; for None, the card with no table on it."""
    key = view.code + view.key() if view is not None else ""
    return CARDS.get(key, lambda: encode_png(_draw(view)), time.monotonic() if now is None else now)


def default_png() -> bytes:
    return render_png(None)
