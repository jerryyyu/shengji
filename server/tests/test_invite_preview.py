"""An invite link's per-table preview: ``/?code=<code>`` for a table a join
by that code may enter carries that table's title, message and card; any
other code gets the site's own preview; the card shows initials or a companion portrait, never a name, draws
only the state its URL was made for, and stays small and cacheable.

Rooms with a game in play are driven through the real server in
test_server_ws.py (departure, a pending admission, closure); the queued
tables here come from a stub of ``Matchmaker.invite_seats``, whose own
projection test_matchmaking.py drives."""
from __future__ import annotations

import os
import struct
import zlib
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("SHENGJI_BOT", "heuristic")

from shengji.api import invite_preview as ip  # noqa: E402
from shengji.api import limits  # noqa: E402
from shengji.api import server as srv  # noqa: E402

INDEX = Path(__file__).resolve().parents[2] / "web" / "index.html"
P, B, O, H = ip.PERSON, ip.BOT, ip.OPEN, ip.HELD
TAKEN, FREE = False, True


def preview_app(dist: Path) -> TestClient:
    """The page and image routes over a copy of web/index.html, on the
    server's own rooms and matchmaker."""
    (dist / "index.html").write_text(INDEX.read_text(encoding="utf-8"), encoding="utf-8")
    a = FastAPI()
    a.add_api_route("/og/table/{code}.png", srv.og_table_card, methods=["GET", "HEAD"])
    a.mount("/", srv.WebFiles(directory=dist, html=True), name="web")
    return TestClient(a)


def card_url(page: str) -> str:
    """The og:image path and query the page names."""
    marker = '<meta property="og:image" content="https://playshengji.com'
    start = page.index(marker) + len(marker)
    return page[start:page.index('"', start)]


def _png_size(png: bytes) -> tuple[int, int]:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert png[12:16] == b"IHDR"
    return struct.unpack(">II", png[16:24])


def _png_pixels(png: bytes) -> bytes:
    n = struct.unpack(">I", png[33:37])[0]
    assert png[37:41] == b"IDAT"
    return zlib.decompress(png[41:41 + n])


class Tables:
    """A stand-in for the matchmaker's queued tables: code -> invite_seats."""

    def __init__(self) -> None:
        self.by_code: dict = {}

    def invite_seats(self, code):
        return self.by_code.get(code)

    def has_code(self, code):
        return code in self.by_code


@pytest.fixture()
def tables(monkeypatch):
    t = Tables()
    monkeypatch.setattr(srv.MATCHMAKER, "invite_seats", t.invite_seats)
    monkeypatch.setattr(srv.MATCHMAKER, "has_code", t.has_code)
    return t


@pytest.fixture()
def app(tmp_path, tables):
    srv.rooms.clear()
    limits.LOOKUPS.reset()
    limits.MISSES.reset()
    ip.CARDS.clear()
    yield preview_app(tmp_path)
    srv.rooms.clear()
    limits.LOOKUPS.reset()
    limits.MISSES.reset()


SEATS = {
    "one": [(P, "Jerrold Yuwen", TAKEN), (P, "Kaito", TAKEN), (P, "Meiqing Linwood", TAKEN), (O, None, FREE)],
    "two": [(P, "Jerrold Yuwen", TAKEN), (O, None, FREE), (P, "Meiqing Linwood", TAKEN), (O, None, FREE)],
    "three": [(P, "Jerrold Yuwen", TAKEN), (O, None, FREE), (O, None, FREE), (O, None, FREE)],
}


def test_initials_are_the_first_and_last_words_letters_only():
    assert ip.initials("Mei Lin") == "ML"
    assert ip.initials("mei") == "M"
    assert ip.initials("Anna Maria de la Cruz") == "AC"
    assert ip.initials("Zoë   wu") == "ZW"
    assert ip.initials("player_7") == "P7"
    assert ip.initials("李明") == ""          # no Latin letter: the person mark
    assert ip.initials(None) == ""


def test_a_view_keeps_initials_only_and_puts_the_opener_team_first():
    v = ip.table_view("FW4X", 1, [(P, "Mei Lin", TAKEN), (P, "Jerry Yu", TAKEN),
                                  (B, None, FREE), (O, None, FREE)])
    # the opener (seat 1) and partner (seat 3) first, then seats 2 and 0
    assert [(s.kind, s.initials, s.us, s.free) for s in v.seats] == [
        (P, "JY", True, False), (O, "", True, True), (B, "", False, True), (P, "ML", False, False)]
    assert "Mei" not in repr(v) and "Jerry" not in repr(v)


@pytest.mark.parametrize("seats,ask", [
    ([(P, "a", TAKEN), (P, "b", TAKEN), (P, "c", TAKEN), (O, None, FREE)], "one"),
    # a bot's seat counts only when a join may claim it
    ([(P, "a", TAKEN), (P, "b", TAKEN), (B, None, FREE), (B, None, TAKEN)], "one"),
    ([(P, "a", TAKEN), (P, "b", TAKEN), (B, None, FREE), (B, None, FREE)], "two"),
    ([(P, "a", TAKEN), (O, None, FREE), (O, None, FREE), (O, None, FREE)], "three"),
    # the code's own held seat asks for a partner; someone else's does not count
    ([(P, "a", TAKEN), (O, None, TAKEN), (H, None, FREE), (O, None, TAKEN)], "partner"),
    ([(P, "a", TAKEN), (P, "b", TAKEN), (H, None, TAKEN), (O, None, FREE)], "one"),
])
def test_the_ask_counts_the_seats_a_join_by_the_code_may_take(seats, ask):
    assert ip.table_view("FW4X", 0, seats).ask == ask


def test_a_table_the_code_cannot_enter_has_no_view():
    assert ip.table_view("FW4X", 0, [(P, "a", TAKEN), (B, None, TAKEN),
                                     (H, None, TAKEN), (P, "d", TAKEN)]) is None


def test_codes_must_have_the_code_format():
    assert ip.valid_code("fw4x") == "FW4X"
    for bad in ("FW4", "FW4XX", "FW1X", "FWOX", "FW-X", "", None, "../x"):
        assert ip.valid_code(bad) is None


def test_chinese_is_chosen_by_accept_language_weight():
    assert ip.prefers_zh("zh-CN,zh;q=0.9,en;q=0.8")
    assert ip.prefers_zh("en;q=0.5, zh-Hans;q=0.9")
    assert not ip.prefers_zh("en-US,en;q=0.9,zh;q=0.8")
    assert not ip.prefers_zh(None)


@pytest.mark.parametrize("ask,title,description", [
    ("one", "Table FW4X · 1 open seat", "We need a 4th for Tractor. Code FW4X"),
    ("two", "Table FW4X · 2 open seats", "Two seats open for Tractor. Code FW4X"),
    ("three", "Table FW4X · 3 open seats", "Play Tractor with me? Code FW4X"),
])
def test_a_live_code_carries_its_tables_preview(app, tables, ask, title, description):
    tables.by_code["FW4X"] = (0, SEATS[ask], "t1")
    r = app.get("/?code=FW4X")
    assert r.status_code == 200
    page = r.text
    assert f'<meta property="og:title" content="{title}" />' in page
    assert f'<meta property="og:description" content="{description}" />' in page
    assert f'<meta name="twitter:title" content="{title}" />' in page
    assert card_url(page).startswith("/og/table/FW4X.png?s=")
    assert '<meta property="og:image:type" content="image/png" />' in page
    assert '<meta property="og:url" content="https://playshengji.com/?code=FW4X" />' in page
    assert '<link rel="canonical" href="https://playshengji.com/" />' in page
    assert "og:video" not in page
    assert 'content="https://playshengji.com/og/preview.jpg" />' not in page
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["vary"] == "Accept-Language"
    for name in ("Jerrold", "Yuwen", "Meiqing", "Linwood", "Kaito"):
        assert name not in page


def test_a_chinese_asker_gets_the_chinese_preview(app, tables):
    tables.by_code["FW4X"] = (0, SEATS["one"], "t1")
    page = app.get("/?code=fw4x", headers={"accept-language": "zh-CN,zh;q=0.9"}).text
    assert '<meta property="og:title" content="牌桌 FW4X · 三缺一" />' in page
    assert '<meta property="og:description" content="三缺一，来打升级！房间码 FW4X" />' in page


def test_a_full_or_closed_queued_table_keeps_the_sites_preview(app, tables):
    tables.by_code["FW4X"] = (0, [(P, "a", TAKEN), (P, "b", TAKEN), (H, None, TAKEN), (P, "d", TAKEN)], "t1")
    assert app.get("/?code=FW4X").text == INDEX.read_text(encoding="utf-8")
    assert app.get("/og/table/FW4X.png?s=00000000").content == ip.default_png()
    # a live code that is merely full spends no miss
    assert not limits.MISSES._hits.get("testclient")


def test_an_unknown_or_malformed_code_gets_the_sites_own_preview(app):
    original = INDEX.read_text(encoding="utf-8")
    for path in ("/?code=ZZZZ", "/?code=Z!", "/?room=ZZZZ", "/"):
        r = app.get(path)
        assert r.status_code == 200
        assert r.text == original, path
    # the two lookups of a code that names nothing spent misses; the malformed one never looked
    assert len(limits.MISSES._hits.get("testclient", [])) == 2


def test_past_the_lookup_budget_a_live_code_reads_as_unknown(app, tables, monkeypatch):
    tables.by_code["FW4X"] = (0, SEATS["one"], "t1")
    url = card_url(app.get("/?code=FW4X").text)
    monkeypatch.setattr(srv, "_lookup_allowed", lambda ip_: False)
    assert app.get("/?code=FW4X").text == INDEX.read_text(encoding="utf-8")
    assert app.get(url).content == ip.default_png()


def test_the_card_is_a_small_cacheable_png_of_the_right_size(app, tables):
    tables.by_code["FW4X"] = (0, SEATS["one"], "t1")
    url = card_url(app.get("/?code=FW4X").text)
    r = app.get(url)
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "public, max-age=60"
    assert _png_size(r.content) == (1200, 630)
    assert len(r.content) < 150_000
    assert r.content != ip.default_png()
    assert app.head(url).status_code == 200


def test_a_card_url_draws_only_the_state_it_was_made_for(app, tables):
    """A delayed fetch of an earlier page's image after a seat fills, or
    after the code passes to another table, gets the generic card; the
    newer page's URL gets the newer roster."""
    tables.by_code["FW4X"] = (0, SEATS["two"], "t1")
    old = card_url(app.get("/?code=FW4X").text)
    old_card = app.get(old).content
    assert old_card != ip.default_png()
    tables.by_code["FW4X"] = (0, SEATS["one"], "t1")
    new = card_url(app.get("/?code=FW4X").text)
    assert new != old
    assert app.get(old).content == ip.default_png()
    new_card = app.get(new).content
    assert new_card not in (ip.default_png(), old_card)
    # the same seats at a later table holding the code: neither URL is its card
    tables.by_code["FW4X"] = (0, SEATS["one"], "t2")
    assert app.get(new).content == ip.default_png()
    assert card_url(app.get("/?code=FW4X").text) not in (old, new)
    # with no state, or a made-up one, nothing of the table is drawn
    for path in ("/og/table/FW4X.png", "/og/table/FW4X.png?s=deadbeef"):
        assert app.get(path).content == ip.default_png()


def test_an_unknown_codes_card_shows_no_table(app):
    for code in ("ZZZZ", "QQQQ", "x"):
        r = app.get(f"/og/table/{code}.png?s=00000000")
        assert r.status_code == 200
        assert r.content == ip.default_png()
        assert _png_size(r.content) == (1200, 630)


def test_each_seat_count_draws_its_own_card():
    cards = set()
    for seats in (SEATS["one"], SEATS["two"], SEATS["three"],
                  [(P, "a", TAKEN), (O, None, TAKEN), (H, None, FREE), (O, None, TAKEN)],
                  [(P, "a", TAKEN), (B, None, FREE), (P, "李", TAKEN), (P, "d e", TAKEN)]):
        png = ip.render_png(ip.table_view("FW4X", 0, seats))
        assert _png_size(png) == (1200, 630) and len(png) < 150_000
        assert len(_png_pixels(png)) == 630 * (1 + 1200 * 3)
        cards.add(png)
    assert len(cards) == 5


def test_a_card_is_reused_within_the_minute_and_redrawn_after():
    ip.CARDS.clear()
    v = ip.table_view("FW4X", 0, SEATS["three"])
    first = ip.render_png(v, now=100.0)
    assert ip.render_png(v, now=150.0) is first
    assert ip.render_png(v, now=161.0) is not first


def _png_rows(px, filters) -> bytes:
    """An RGBA PNG of ``px`` (rows of RGBA tuples), each row filtered with
    its type in ``filters``, as an encoder other than ours might write it."""
    h, w = len(px), len(px[0])
    flat = [bytes(c for p in row for c in p) for row in px]
    out = bytearray()
    prior = bytes(w * 4)
    for y, (row, f) in enumerate(zip(flat, filters)):
        line = bytearray([f])
        for x in range(w * 4):
            a = row[x - 4] if x >= 4 else 0
            b = prior[x]
            c = prior[x - 4] if x >= 4 else 0
            pred = (0, a, b, (a + b) >> 1)[f] if f < 4 else ip._paeth(a, b, c)
            line.append((row[x] - pred) & 0xFF)
        out += line
        prior = row

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(out))) + chunk(b"IEND", b""))


def test_the_png_reader_undoes_every_row_filter():
    px = [[((x * 37 + y * 11) % 256, (x * 5 + 90) % 256, (y * 53) % 256, (x * y * 7 + 30) % 256)
           for x in range(6)] for y in range(5)]
    got = ip.read_png(_png_rows(px, [0, 1, 2, 3, 4]))
    assert got.shape == (5, 6, 4)
    assert got.tolist() == [[list(p) for p in row] for row in px]
    # the card's own RGB encoding reads back with an opaque alpha
    rgb = ip.read_png(ip.encode_png(ip._draw(None)))
    assert rgb.shape == (630, 1200, 4) and (rgb[..., 3] == 255).all()


def test_every_look_ships_a_portrait():
    from shengji.api import accounts
    for companion, colours in accounts.LOOKS.items():
        for colour in colours:
            path = ip.portrait_path(f"{companion}/{colour}")
            assert path is not None, f"{companion}/{colour}"
            px = ip.read_png(path.read_bytes())
            assert px.shape == (192, 192, 4)
            assert px[0, 0, 3] == 0 and px[96, 96, 3] == 255      # a disc on a clear square
    assert ip.portrait_path("tractor/../../x") is None and ip.portrait_path("dragon/red") is None


def test_a_person_with_a_look_shows_their_companion_in_place_of_initials():
    base = [(P, "Jerry Yu", TAKEN), (O, None, TAKEN), (H, None, FREE), (O, None, TAKEN)]
    plain = ip.table_view("4SMP", 0, base)
    tractor = ip.table_view("4SMP", 0, [(P, "Jerry Yu", TAKEN, "tractor/red")] + base[1:])
    bun = ip.table_view("4SMP", 0, [(P, "Jerry Yu", TAKEN, "bun/taro")] + base[1:])
    unknown = ip.table_view("4SMP", 0, [(P, "Jerry Yu", TAKEN, "dragon/red")] + base[1:])
    assert (plain.seats[0].look, tractor.seats[0].look, bun.seats[0].look) == ("", "tractor/red", "bun/taro")
    assert unknown.seats[0].look == "" and unknown.state() == plain.state()
    assert tractor.seats[0].initials == "JY"         # still only initials, never the name
    # a bot or an empty seat never carries a look
    assert ip.table_view("4SMP", 0, [(P, "a", TAKEN), (B, None, FREE, "bun/taro"),
                                     (O, None, FREE), (O, None, FREE)]).seats[2].look == ""
    # the card's cache and URL are keyed by the look
    assert len({plain.state(), tractor.state(), bun.state()}) == 3
    ip.CARDS.clear()
    cards = [ip._draw(v) for v in (plain, tractor, bun)]
    d = ip._load()["spec"]["seat"]
    left = (ip.WIDTH - 4 * d - 3 * ip.SEAT_GAP) / 2
    cx, cy = int(left + d / 2), int(ip.SEAT_TOP + d / 2)
    centres = [tuple(int(v) for v in c[cy + 40, cx]) for c in cards]
    assert len(set(centres)) == 3
    # the ring stays the opener team's blue over the portrait's edge
    ring = ip.TEAM[True][1]
    assert all(max(abs(int(c[cy, int(left) + 3][i]) - ring[i]) for i in range(3)) < 40 for c in cards)
    # the other seats draw the same
    other = int(left + d + ip.SEAT_GAP + d / 2)
    assert (cards[0][cy, other] == cards[1][cy, other]).all()
    assert ip.render_png(tractor) != ip.render_png(plain)


def test_only_an_account_with_the_collection_on_has_a_card_look(monkeypatch):
    from shengji.api import accounts
    monkeypatch.delenv("COLLECTION_ENABLED", raising=False)
    monkeypatch.setenv("COLLECTION_ACCOUNTS", "7")
    accounts.STORE.seen_looks[7] = "panda/gilded"
    accounts.STORE.seen_looks[8] = "bun/taro"
    assert accounts.card_look(7) == "panda/gilded"
    assert accounts.card_look(8) == ""              # Collection off for the account
    assert accounts.card_look(None) == ""           # a guest
    monkeypatch.setenv("COLLECTION_ENABLED", "1")
    assert accounts.card_look(8) == "bun/taro"
    assert accounts.card_look(9) == accounts.DEFAULT_LOOK    # on, nothing chosen: the default Tractor
    assert accounts.card_look(None) == ""


# Rooms with a game in play, through the real server: the preview follows the
# Join panel's projection (``room_seats_json``) as seats change.
from tests.test_server_ws import _four_humans, _room_with_bots, client, clock  # noqa: E402,F401


@pytest.fixture()
def pages(tmp_path):
    limits.LOOKUPS.reset()
    limits.MISSES.reset()
    ip.CARDS.clear()
    yield preview_app(tmp_path)
    limits.LOOKUPS.reset()
    limits.MISSES.reset()


def _title(page: str) -> str:
    marker = '<meta property="og:title" content="'
    start = page.index(marker) + len(marker)
    return page[start:page.index('"', start)]


def test_a_departed_players_seat_shows_open_only_once_a_join_may_take_it(client, clock, pages):
    from contextlib import ExitStack

    with client.websocket_connect("/ws") as a, ExitStack() as sockets:
        code, room, _, peer_stacks = _four_humans(client, a, sockets)
        # four people: nothing to take, so the site's own preview
        assert _title(pages.get(f"/?code={code}").text) == "Sheng Ji 升级"
        peer_stacks[0].close()                       # amy (seat 1) drops
        # her seat is reserved for her: still full, and her seat keeps her initial
        assert _title(pages.get(f"/?code={code}").text) == "Sheng Ji 升级"
        assert srv.room_invite_seats(room)[1] == (P, "amy", False, "")
        clock["v"] += srv.TAKEOVER_AFTER + 1
        # past the reservation a join may take it: an open seat, not her initial
        page = pages.get(f"/?code={code}").text
        assert _title(page) == f"Table {code} · 1 open seat"
        assert srv.room_invite_seats(room)[1] == (O, None, True)
        view = srv.invite_view(code)
        assert [s.initials for s in view.seats if s.kind == P] == ["J", "B", "C"]   # seats 0, 2, then 3
        card = pages.get(card_url(page))
        assert card.content == ip.render_png(view) != ip.default_png()


def test_a_ranked_bot_seat_a_pending_join_holds_is_not_offered(client, pages):
    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        room = srv.rooms[code]
        room.matched = True
        try:
            page = pages.get(f"/?code={code}").text
            assert _title(page) == f"Table {code} · 3 open seats"
            room.pending_joins.update({1: object(), 2: object()})
            page = pages.get(f"/?code={code}").text
            assert _title(page) == f"Table {code} · 1 open seat"
            url = card_url(page)
            assert pages.get(url).content != ip.default_png()
            # a pending join on the last bot seat: Join reports full, and so does the preview
            room.pending_joins[3] = object()
            assert pages.get(f"/?code={code}").text == INDEX.read_text(encoding="utf-8")
            assert pages.get(url).content == ip.default_png()
        finally:
            room.pending_joins.clear()
            room.matched = False


def test_a_closing_room_has_no_preview_of_its_own(client, pages):
    with client.websocket_connect("/ws") as a:
        code = _room_with_bots(a)
        room = srv.rooms[code]
        room.matched = True
        try:
            url = card_url(pages.get(f"/?code={code}").text)
            assert pages.get(url).content != ip.default_png()
            room.closing = True
            assert pages.get(f"/?code={code}").text == INDEX.read_text(encoding="utf-8")
            assert pages.get(url).content == ip.default_png()
        finally:
            room.closing = False
            room.matched = False
