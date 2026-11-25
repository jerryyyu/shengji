"""An invite link's per-table preview: ``/?code=<code>`` for a live table
carries that table's title, message and card; any other code gets the site's
own preview; the card shows initials only and stays small and cacheable."""
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


def _png_size(png: bytes) -> tuple[int, int]:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert png[12:16] == b"IHDR"
    return struct.unpack(">II", png[16:24])


def _png_pixels(png: bytes) -> bytes:
    """The filtered scanlines of a one-IDAT PNG, for a content check."""
    n = struct.unpack(">I", png[33:37])[0]
    assert png[37:41] == b"IDAT"
    return zlib.decompress(png[41:41 + n])


@pytest.fixture()
def app(tmp_path):
    (tmp_path / "index.html").write_text(INDEX.read_text(encoding="utf-8"), encoding="utf-8")
    a = FastAPI()
    a.add_api_route("/og/table/{code}.png", srv.og_table_card, methods=["GET", "HEAD"])
    a.mount("/", srv.WebFiles(directory=tmp_path, html=True), name="web")
    srv.rooms.clear()
    limits.LOOKUPS.reset()
    limits.MISSES.reset()
    ip.CARDS.clear()
    yield TestClient(a)
    srv.rooms.clear()
    limits.LOOKUPS.reset()
    limits.MISSES.reset()


def _room(code: str, seats: list, host: int = 0) -> None:
    srv.rooms[code] = srv.Room(code=code, seats=seats, host=host)


def _person(name: str):
    return srv.Seat(name=name, connected=True)


SEATS = {
    "one": [_person("Jerrold Yuwen"), _person("Kaito"), _person("Meiqing Linwood"), None],
    "two": [_person("Jerrold Yuwen"), None, _person("Meiqing Linwood"), None],
    "three": [_person("Jerrold Yuwen"), None, None, None],
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
    v = ip.table_view("FW4X", 1, [(P, "Mei Lin"), (P, "Jerry Yu"), (B, None), (O, None)])
    # the opener (seat 1) and partner (seat 3) first, then seats 2 and 0
    assert [(s.kind, s.initials, s.us) for s in v.seats] == [
        (P, "JY", True), (O, "", True), (B, "", False), (P, "ML", False)]
    assert "Mei" not in repr(v) and "Jerry" not in repr(v)


@pytest.mark.parametrize("seats,ask", [
    ([(P, "a"), (P, "b"), (P, "c"), (O, None)], "one"),
    ([(P, "a"), (P, "b"), (B, None), (B, None)], "two"),
    ([(P, "a"), (O, None), (O, None), (O, None)], "three"),
    ([(P, "a"), (O, None), (H, None), (O, None)], "partner"),
    ([(P, "a"), (P, "b"), (P, "c"), (P, "d")], "full"),
])
def test_the_ask_counts_people_and_a_held_seat(seats, ask):
    assert ip.table_view("FW4X", 0, seats).ask == ask


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
def test_a_live_code_carries_its_tables_preview(app, ask, title, description):
    _room("FW4X", SEATS[ask])
    r = app.get("/?code=FW4X")
    assert r.status_code == 200
    page = r.text
    assert f'<meta property="og:title" content="{title}" />' in page
    assert f'<meta property="og:description" content="{description}" />' in page
    assert f'<meta name="twitter:title" content="{title}" />' in page
    assert '<meta property="og:image" content="https://playshengji.com/og/table/FW4X.png?s=' in page
    assert '<meta property="og:image:type" content="image/png" />' in page
    assert '<meta property="og:url" content="https://playshengji.com/?code=FW4X" />' in page
    assert '<link rel="canonical" href="https://playshengji.com/" />' in page
    assert "og:video" not in page
    assert 'content="https://playshengji.com/og/preview.jpg" />' not in page
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["vary"] == "Accept-Language"
    for name in ("Jerrold", "Yuwen", "Meiqing", "Linwood", "Kaito"):
        assert name not in page


def test_a_chinese_asker_gets_the_chinese_preview(app):
    _room("FW4X", SEATS["one"])
    page = app.get("/?code=fw4x", headers={"accept-language": "zh-CN,zh;q=0.9"}).text
    assert '<meta property="og:title" content="牌桌 FW4X · 三缺一" />' in page
    assert '<meta property="og:description" content="三缺一，来打升级！房间码 FW4X" />' in page


def test_a_duo_table_asks_for_a_partner(app, monkeypatch):
    monkeypatch.setattr(srv.MATCHMAKER, "invite_seats",
                        lambda code: (0, [(P, "Jerry"), (O, None), (H, None), (O, None)]) if code == "DU0X" else None)
    page = app.get("/?code=DU0X").text   # 0 is not in the code alphabet
    assert "og:title\" content=\"Sheng Ji" in page
    monkeypatch.setattr(srv.MATCHMAKER, "invite_seats",
                        lambda code: (0, [(P, "Jerry"), (O, None), (H, None), (O, None)]) if code == "DUPX" else None)
    page = app.get("/?code=DUPX").text
    assert '<meta property="og:title" content="Table DUPX · partner seat open" />' in page
    assert '<meta property="og:description" content="Be my partner for Tractor? Code DUPX" />' in page


def test_an_unknown_or_malformed_code_gets_the_sites_own_preview(app):
    original = INDEX.read_text(encoding="utf-8")
    for path in ("/?code=ZZZZ", "/?code=Z!", "/?room=ZZZZ", "/"):
        r = app.get(path)
        assert r.status_code == 200
        assert r.text == original, path
    # the known miss spent the code-guessing budget; the malformed one never looked
    assert len(limits.MISSES._hits.get("testclient", [])) == 2


def test_past_the_lookup_budget_a_live_code_reads_as_unknown(app, monkeypatch):
    _room("FW4X", SEATS["one"])
    monkeypatch.setattr(srv, "_lookup_allowed", lambda ip_: False)
    assert app.get("/?code=FW4X").text == INDEX.read_text(encoding="utf-8")
    assert app.get("/og/table/FW4X.png").content == ip.default_png()


def test_the_card_is_a_small_cacheable_png_of_the_right_size(app):
    _room("FW4X", SEATS["one"])
    r = app.get("/og/table/FW4X.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "public, max-age=60"
    assert _png_size(r.content) == (1200, 630)
    assert len(r.content) < 150_000
    assert r.content != ip.default_png()
    assert app.head("/og/table/FW4X.png").status_code == 200


def test_an_unknown_codes_card_shows_no_table(app):
    for code in ("ZZZZ", "QQQQ", "x"):
        r = app.get(f"/og/table/{code}.png")
        assert r.status_code == 200
        assert r.content == ip.default_png()
        assert _png_size(r.content) == (1200, 630)


def test_each_seat_count_draws_its_own_card():
    cards = set()
    for seats in ([(P, "a"), (P, "b"), (P, "c"), (O, None)],
                  [(P, "a"), (O, None), (P, "c"), (O, None)],
                  [(P, "a"), (O, None), (O, None), (O, None)],
                  [(P, "a"), (O, None), (H, None), (O, None)],
                  [(P, "a"), (B, None), (P, "李"), (P, "d e")]):
        png = ip.render_png(ip.table_view("FW4X", 0, seats))
        assert _png_size(png) == (1200, 630) and len(png) < 150_000
        assert len(_png_pixels(png)) == 630 * (1 + 1200 * 3)
        cards.add(png)
    assert len(cards) == 5


def test_a_card_is_reused_within_the_minute_and_redrawn_after():
    ip.CARDS.clear()
    v = ip.table_view("FW4X", 0, [(P, "a"), (O, None), (O, None), (O, None)])
    first = ip.render_png(v, now=100.0)
    assert ip.render_png(v, now=150.0) is first
    assert ip.render_png(v, now=161.0) is not first


def test_the_image_url_changes_with_the_seats():
    a = ip.table_view("FW4X", 0, [(P, "a"), (O, None), (O, None), (O, None)])
    b = ip.table_view("FW4X", 0, [(P, "a"), (P, "b"), (O, None), (O, None)])
    assert ip.image_url(a) != ip.image_url(b)
    assert ip.image_url(a).startswith("https://playshengji.com/og/table/FW4X.png?s=")
