"""The support form (``POST /api/support``), the ``/support``, ``/privacy``
and ``/terms`` page routes, and the crawler files and static rules pages
served from ``web/public`` (``shengji.api.support``).

Messages land in a private data dir; the answer never carries what was
stored. The page routes are checked on a bare app with a fake build, the way
the static mount is checked in ``test_web_cache_headers``.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.test_server_ws import client  # noqa: F401

VALID = {"topic": "bug", "message": "The trick area froze after the kitty.",
         "email": "player@example.com", "website": "", "version": "web index-abc123.js"}
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) ShengjiTest"


@pytest.fixture()
def support_on(tmp_path, monkeypatch):
    """A private data dir, a private accounts store and a fresh limiter."""
    from shengji.api import accounts, support

    monkeypatch.setenv("SHENGJI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(accounts, "STORE", accounts.Store(tmp_path / "data" / "accounts.sqlite3"))
    monkeypatch.setattr(support, "LIMITER", accounts.RateLimiter(limit=5, window=3600.0))
    return support


def _stored(support) -> list[dict]:
    path = support.messages_path()
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


def _post(client, body, **kw):
    return client.post("/api/support", json=body, headers={"user-agent": UA, **kw.pop("headers", {})}, **kw)


def test_a_valid_message_is_stored_as_one_json_line(client, support_on):
    r = _post(client, VALID)
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    [rec] = _stored(support_on)
    assert set(rec) == {"ts", "topic", "message", "email", "account_id", "account_name",
                        "version", "user_agent"}
    assert rec["topic"] == "bug"
    assert rec["message"] == VALID["message"]
    assert rec["email"] == "player@example.com"
    assert rec["account_id"] is None and rec["account_name"] is None
    assert rec["version"] == "web index-abc123.js"
    assert rec["user_agent"] == UA
    assert isinstance(rec["ts"], float)
    assert support_on.messages_path().name == "support_messages.jsonl"


def test_the_response_never_echoes_what_was_stored(client, support_on):
    r = _post(client, VALID)
    text = r.text
    for value in (VALID["message"], VALID["email"], UA, "bug"):
        assert value not in text
    assert r.json() == {"ok": True}


def test_reply_email_is_optional(client, support_on):
    for email in (None, "", "   "):
        body = {**VALID, "email": email}
        assert _post(client, body).status_code == 200
    assert [rec["email"] for rec in _stored(support_on)] == [None, None, None]


def test_a_signed_in_sender_is_recorded_by_account(client, support_on):
    from shengji.api import accounts

    user = accounts.STORE.upsert_user({"sub": "g-1", "email": "a@example.com", "name": "Ada Lovelace"})
    accounts.STORE.set_display_name(user["id"], "Ada L")
    token = accounts.STORE.create_session(user["id"])
    client.cookies.set(accounts.COOKIE, token)
    try:
        r = _post(client, {**VALID, "email": None})
    finally:
        client.cookies.clear()
    assert r.json() == {"ok": True}
    [rec] = _stored(support_on)
    assert rec["account_id"] == user["id"]
    assert rec["account_name"] == "Ada L"
    assert "Ada" not in r.text


@pytest.mark.parametrize("message", ["", "too short", " " * 30 + "short" + " " * 30, None, 12345])
def test_a_short_or_missing_message_is_refused(client, support_on, message):
    r = _post(client, {**VALID, "message": message})
    assert r.status_code == 400
    assert r.json()["detail"] == "message_too_short"
    assert _stored(support_on) == []


def test_a_long_message_is_refused(client, support_on):
    r = _post(client, {**VALID, "message": "x" * 4001})
    assert r.status_code == 400 and r.json()["detail"] == "message_too_long"
    assert _post(client, {**VALID, "message": "x" * 4000}).status_code == 200


@pytest.mark.parametrize("email", ["not-an-email", "a@b", "a b@example.com", "a@@example.com",
                                   "@example.com", "a@example.", "x" * 250 + "@example.com", 7])
def test_a_malformed_email_is_refused(client, support_on, email):
    r = _post(client, {**VALID, "email": email})
    assert r.status_code == 400
    assert r.json()["detail"] == "bad_email"
    assert _stored(support_on) == []


def test_an_unknown_topic_is_refused(client, support_on):
    r = _post(client, {**VALID, "topic": "billing"})
    assert r.status_code == 400 and r.json()["detail"] == "bad_topic"
    assert _post(client, {**VALID, "topic": "Account"}).status_code == 200
    assert _stored(support_on)[0]["topic"] == "account"


def test_the_honeypot_reads_as_success_and_stores_nothing(client, support_on):
    r = _post(client, {**VALID, "website": "http://spam.example"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert _stored(support_on) == []


def test_five_messages_an_hour_per_address(client, support_on):
    ip = {"fly-client-ip": "203.0.113.9"}
    for _ in range(5):
        assert _post(client, VALID, headers=ip).status_code == 200
    r = _post(client, VALID, headers=ip)
    assert r.status_code == 429 and r.json()["detail"] == "rate_limited"
    assert len(_stored(support_on)) == 5
    # another address has its own budget
    assert _post(client, VALID, headers={"fly-client-ip": "203.0.113.10"}).status_code == 200


def test_control_characters_are_dropped_but_line_breaks_kept(client, support_on):
    r = _post(client, {**VALID, "message": "line one\nline two\x00\x07 end", "version": "v1\n\x1b[31m"})
    assert r.status_code == 200
    [rec] = _stored(support_on)
    assert rec["message"] == "line one\nline two end"
    assert rec["version"] == "v1[31m"


def _page_client(tmp_path):
    from shengji.api.server import WebFiles
    from shengji.api import support

    (tmp_path / "index.html").write_text("<!doctype html><title>Sheng Ji</title>")
    app = FastAPI()
    support.register_support(app, tmp_path)
    app.mount("/", WebFiles(directory=tmp_path, html=True), name="web")
    return TestClient(app)


@pytest.mark.parametrize("path", ["/support", "/privacy", "/terms", "/support/", "/privacy/", "/terms/"])
def test_the_pages_serve_the_app_on_a_deep_link_or_reload(tmp_path, path):
    r = _page_client(tmp_path).get(path)
    assert r.status_code == 200
    assert "<title>Sheng Ji</title>" in r.text
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("path, page", [("/privacy", "privacy"), ("/terms/", "terms"),
                                        ("/support", "support")])
def test_each_page_names_itself_as_canonical(tmp_path, path, page):
    """The real index.html, served for an info page, points its canonical link and
    og:url at that page, not at the root; the root keeps its own."""
    shutil.copy(PUBLIC.parent / "index.html", tmp_path / "index.html")
    from shengji.api.server import WebFiles
    from shengji.api import support

    app = FastAPI()
    support.register_support(app, tmp_path)
    app.mount("/", WebFiles(directory=tmp_path, html=True), name="web")
    c = TestClient(app)
    url = f"{support.SITE_ORIGIN}/{page}"
    html = c.get(path).text
    assert f'<link rel="canonical" href="{url}" />' in html
    assert f'<meta property="og:url" content="{url}" />' in html
    assert f'href="{support.SITE_ORIGIN}/"' not in html.split("<script", 1)[0]
    root = c.get("/").text
    assert f'<link rel="canonical" href="{support.SITE_ORIGIN}/" />' in root


def test_the_server_origin_matches_the_web_constant():
    from shengji.api import support

    src = (PUBLIC.parent / "src" / "siteOrigin.ts").read_text(encoding="utf-8")
    assert f'export const SITE_ORIGIN = "{support.SITE_ORIGIN}";' in src


def test_the_pages_are_404_without_a_build(tmp_path):
    from shengji.api import support

    app = FastAPI()
    support.register_support(app, tmp_path / "missing")
    c = TestClient(app)
    assert c.get("/support").status_code == 404
    assert c.get("/privacy").status_code == 404
    assert c.get("/terms").status_code == 404



PUBLIC = Path(__file__).resolve().parents[2] / "web" / "public"
AGENT_CLAUSE = "must not create or join rooms"


def _public_client(tmp_path):
    """The real ``web/public`` files in a fake build, as Vite copies them."""
    shutil.copytree(PUBLIC, tmp_path, dirs_exist_ok=True)
    return _page_client(tmp_path)


@pytest.mark.parametrize("path, content_type, first", [
    ("/robots.txt", "text/plain", "# Sheng Ji"),
    ("/llms.txt", "text/plain", "# Sheng Ji"),
    ("/sitemap.xml", "xml", "<?xml"),
    ("/rules", "text/html", "<!doctype html>"),
    ("/rules/", "text/html", "<!doctype html>"),
    ("/rules/zh", "text/html", "<!doctype html>"),
    ("/rules/zh/", "text/html", "<!doctype html>"),
])
def test_crawler_files_and_rules_pages_are_served(tmp_path, path, content_type, first):
    r = _public_client(tmp_path).get(path, follow_redirects=False)
    assert r.status_code == 200, path
    assert content_type in r.headers["content-type"]
    assert r.text.startswith(first)


def test_the_app_is_still_served_at_the_root(tmp_path):
    r = _public_client(tmp_path).get("/")
    assert r.status_code == 200
    assert "<title>Sheng Ji</title>" in r.text


def test_robots_points_to_the_sitemap_and_keeps_crawlers_off_the_api(tmp_path):
    text = _public_client(tmp_path).get("/robots.txt").text
    directives = [line for line in text.splitlines() if line and not line.startswith("#")]
    assert directives == ["User-agent: *", "Allow: /", "Disallow: /api/", "Disallow: /ws",
                          "Sitemap: https://playshengji.com/sitemap.xml"]
    assert AGENT_CLAUSE in text


def test_the_sitemap_lists_every_public_page(tmp_path):
    import xml.etree.ElementTree as ET

    root = ET.fromstring(_public_client(tmp_path).get("/sitemap.xml").content)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [e.text for e in root.findall("s:url/s:loc", ns)]
    base = ["https://playshengji.com/" + p for p in ("", "rules", "rules/zh", "privacy", "terms")]
    guides = [f"https://playshengji.com{root}{slug}" for root in ("/guides", "/zh/guides")
              for slug in ["", *(f"/{s}" for s in _guide_slugs())]]
    assert locs[:len(base)] == base
    assert sorted(locs[len(base):]) == sorted(guides)


def test_llms_txt_states_the_automated_play_clause(tmp_path):
    text = _public_client(tmp_path).get("/llms.txt").text
    assert AGENT_CLAUSE in text
    assert "https://playshengji.com/rules" in text and "https://playshengji.com/rules/zh" in text
    assert "https://playshengji.com/guides" in text and "https://playshengji.com/zh/guides" in text


@pytest.mark.parametrize("page, lang, other", [
    ("rules/index.html", "en", "/rules/zh"),
    ("rules/zh/index.html", "zh-Hans", "/rules"),
])
def test_rules_pages_carry_canonical_hreflang_and_valid_json_ld(page, lang, other):
    import re

    html = (PUBLIC / page).read_text(encoding="utf-8")
    url = "https://playshengji.com/" + page.removesuffix("/index.html")
    assert f'<html lang="{lang}">' in html
    assert f'<link rel="canonical" href="{url}" />' in html
    assert 'hreflang="en" href="https://playshengji.com/rules"' in html
    assert 'hreflang="zh-Hans" href="https://playshengji.com/rules/zh"' in html
    assert f'href="{other}"' in html and 'href="/"' in html
    [block] = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    graph = json.loads(block)["@graph"]
    assert [node["@type"] for node in graph] == ["Article", "FAQPage"]
    assert 4 <= len(graph[1]["mainEntity"]) <= 6
    assert "<script src" not in html and 'type="module"' not in html


@pytest.mark.parametrize("page, badge, alt, ct", [
    ("rules/index.html", "/badges/app-store-en.svg", "Download on the App Store", "rules-en"),
    ("rules/zh/index.html", "/badges/app-store-zh.svg", "在 App Store 下载", "rules-zh"),
])
def test_rules_pages_end_with_apples_app_store_badge(page, badge, alt, ct):
    import re

    html = (PUBLIC / page).read_text(encoding="utf-8")
    [link] = re.findall(r'<a class="app-store" href="([^"]+)"><img\s+src="([^"]+)" alt="([^"]+)"', html)
    assert link == (f"https://apps.apple.com/app/id6833598710?ct={ct}", badge, alt)
    svg = (PUBLIC / badge.lstrip("/")).read_text(encoding="utf-8")
    assert svg.startswith("<svg") and "Download_on_the_App_Store_Badge" in svg


def test_the_app_page_json_ld_parses():
    import re

    html = (PUBLIC.parent / "index.html").read_text(encoding="utf-8")
    [block] = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    data = json.loads(block)
    assert "VideoGame" in data["@type"] and data["url"] == "https://playshengji.com/"


def _guide_slugs() -> list[str]:
    content = PUBLIC.parent / "content" / "guides" / "en"
    return sorted(p.stem for p in content.glob("*.md"))


def test_there_are_guides_in_both_languages():
    slugs = _guide_slugs()
    assert len(slugs) >= 6
    zh = PUBLIC.parent / "content" / "guides" / "zh"
    assert sorted(p.stem for p in zh.glob("*.md")) == slugs


def _guide_routes():
    for slug in ["", *(f"/{s}" for s in _guide_slugs())]:
        for root in ("/guides", "/zh/guides"):
            yield root + slug


@pytest.mark.parametrize("path", list(_guide_routes()))
def test_guide_pages_are_served_static_with_their_canonical(tmp_path, path):
    c = _public_client(tmp_path)
    for variant in (path, path + "/"):
        r = c.get(variant, follow_redirects=False)
        assert r.status_code == 200, variant
        assert r.headers["content-type"].startswith("text/html")
        assert r.headers["cache-control"] == "no-cache"
        assert r.text.startswith("<!doctype html>")
        assert f'<link rel="canonical" href="https://playshengji.com{path}" />' in r.text
        # the page itself, never the app's index.html
        assert "<title>Sheng Ji</title>" not in r.text and 'id="root"' not in r.text


def test_guide_pages_have_their_own_routes(tmp_path):
    """Served by routes of their own, not by the static mount: with no mount
    at all every guide still answers, so no later catch-all can take them."""
    shutil.copytree(PUBLIC, tmp_path, dirs_exist_ok=True)
    from shengji.api import support

    assert set(support.guide_pages(tmp_path)) == set(_guide_routes())
    app = FastAPI()
    support.register_support(app, tmp_path)
    c = TestClient(app)
    for path in _guide_routes():
        assert c.get(path, follow_redirects=False).status_code == 200, path


def test_an_unknown_guide_is_a_404_not_the_app(tmp_path):
    c = _public_client(tmp_path)
    for path in ("/guides/no-such-guide", "/zh/guides/no-such-guide", "/guides/../rules/zh/x"):
        r = c.get(path, follow_redirects=False)
        assert r.status_code == 404, path
        assert "<title>Sheng Ji</title>" not in r.text


def test_guide_routes_need_a_build(tmp_path):
    from shengji.api import support

    assert support.guide_pages(tmp_path / "missing") == {}
    (tmp_path / "guides" / "Bad_Slug").mkdir(parents=True)
    (tmp_path / "guides" / "Bad_Slug" / "index.html").write_text("x")
    (tmp_path / "guides" / "index.html").write_text("x")
    assert support.guide_pages(tmp_path) == {"/guides": "guides/index.html"}


def test_the_rules_routes_take_no_request_input(tmp_path):
    r = _public_client(tmp_path).get("/rules?file=../../etc/passwd")
    assert r.status_code == 200 and r.text.startswith("<!doctype html>")


FAKE_TEAM = "ABCDE12345"


@pytest.mark.parametrize("path", ["/.well-known/apple-app-site-association",
                                  "/apple-app-site-association"])
def test_the_app_site_association_names_the_app_and_only_invite_links(tmp_path, monkeypatch, path):
    monkeypatch.setenv("APPLE_TEAM_ID", FAKE_TEAM)
    r = _page_client(tmp_path).get(path, follow_redirects=False)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/json"
    details = r.json()["applinks"]["details"]
    assert details[0]["appIDs"] == [f"{FAKE_TEAM}.com.jerryyu.shengji"]
    matched = [(c["/"], c["?"]) for c in details[0]["components"]]
    assert matched == [("/", {"code": "?*"}), ("/", {"room": "?*"})]


@pytest.mark.parametrize("team", [None, "", "abcde12345", "ABCDE1234", "ABCDE12345X"])
def test_the_app_site_association_is_404_without_a_team_id(tmp_path, monkeypatch, team):
    if team is None:
        monkeypatch.delenv("APPLE_TEAM_ID", raising=False)
    else:
        monkeypatch.setenv("APPLE_TEAM_ID", team)
    c = _page_client(tmp_path)
    for path in ("/.well-known/apple-app-site-association", "/apple-app-site-association"):
        assert c.get(path, follow_redirects=False).status_code == 404


def test_the_bundle_id_matches_the_capacitor_app_id():
    from shengji.api import support

    config = (PUBLIC.parent / "capacitor.config.ts").read_text()
    assert f'appId: "{support.APP_BUNDLE_ID}"' in config


WWW = {"host": "www.playshengji.com"}
# What a browser sends for a typed URL, a tapped invite or a reload.
NAV = {"sec-fetch-mode": "navigate", "sec-fetch-dest": "document", "sec-fetch-site": "none",
       "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
# A client without Fetch Metadata loading a page.
HTML_ONLY = {"accept": "text/html,application/xhtml+xml,*/*;q=0.8"}
# audio.ts's fetch of a clip, with and without Fetch Metadata.
SOUND_FETCHES = [
    {"sec-fetch-mode": "cors", "sec-fetch-dest": "empty", "sec-fetch-site": "same-origin", "accept": "*/*"},
    {"sec-fetch-mode": "no-cors", "sec-fetch-dest": "audio", "accept": "*/*"},
    {"accept": "*/*"},
    {},
]
SOUND = "/sounds/bi.mp3?v=1"


@pytest.mark.parametrize("path, location", [
    ("/", "https://playshengji.com/"),
    ("/?code=ABCD", "https://playshengji.com/?code=ABCD"),
    ("/rules/zh?x=1&y=two", "https://playshengji.com/rules/zh?x=1&y=two"),
    ("/guides/a%20b", "https://playshengji.com/guides/a%20b"),
])
@pytest.mark.parametrize("host", ["www.playshengji.com", "WWW.PlayShengji.com:443"])
@pytest.mark.parametrize("load", [NAV, HTML_ONLY, {"sec-fetch-mode": "navigate"}],
                         ids=["fetch-metadata", "accept-only", "navigate-without-dest"])
def test_a_www_page_load_moves_to_the_apex_with_its_path_and_query(client, path, location, host, load):
    for method in ("GET", "HEAD"):
        r = client.request(method, path, headers={**load, "host": host}, follow_redirects=False)
        assert r.status_code == 301, (method, path)
        assert r.headers["location"] == location
        assert r.headers["strict-transport-security"].startswith("max-age=")


@pytest.mark.parametrize("host", ["playshengji.com", "shengji.fly.dev", "testserver"])
def test_the_apex_and_fly_dev_answer_in_place(client, host):
    for path in ("/healthz", "/?code=ABCD", SOUND):
        r = client.get(path, headers={**NAV, "host": host}, follow_redirects=False)
        assert r.status_code != 301 and "location" not in r.headers, (host, path)
    assert client.get("/healthz", headers={"host": host}).status_code == 200


def test_www_answers_the_app_site_association_and_healthz_in_place(client, monkeypatch):
    monkeypatch.setenv("APPLE_TEAM_ID", FAKE_TEAM)
    for load in (NAV, HTML_ONLY, {}):
        headers = {**load, **WWW}
        assert client.get("/healthz", headers=headers, follow_redirects=False).status_code == 200
        for path in ("/.well-known/apple-app-site-association", "/apple-app-site-association"):
            r = client.get(path, headers=headers, follow_redirects=False)
            assert r.status_code == 200, path
            assert r.json()["applinks"]["details"][0]["appIDs"] == [f"{FAKE_TEAM}.com.jerryyu.shengji"]


@pytest.mark.parametrize("load", [NAV, HTML_ONLY], ids=["fetch-metadata", "accept-only"])
def test_a_www_invite_reaches_the_apex_with_its_code(client, load):
    """Followed end to end through the app: one 301, then the apex answers
    the invite exactly as it answers it directly."""
    r = client.get("/?code=ABCD", headers={**load, **WWW}, follow_redirects=True)
    assert [h.status_code for h in r.history] == [301]
    assert str(r.url) == "https://playshengji.com/?code=ABCD"
    assert r.request.headers["host"] == "playshengji.com"
    direct = client.get("/?code=ABCD", headers={**load, "host": "playshengji.com"})
    assert r.status_code == direct.status_code and r.content == direct.content


@pytest.mark.parametrize("load", [SOUND_FETCHES[0], {"accept": "*/*"}], ids=["cors", "no-metadata"])
def test_an_open_www_tab_still_submits_a_support_message(client, support_on, load):
    r = _post(client, VALID, headers={**load, **WWW}, follow_redirects=True)
    assert r.history == [] and r.request.headers["host"] == "www.playshengji.com"
    assert r.status_code == 200 and r.json() == {"ok": True}
    [rec] = _stored(support_on)
    assert rec["message"] == VALID["message"]


def test_the_api_answers_in_place_on_www(client):
    direct = client.get("/api/auth/config")
    assert direct.status_code == 200
    for load in (NAV, HTML_ONLY, {}):
        r = client.get("/api/auth/config", headers={**load, **WWW}, follow_redirects=True)
        assert r.history == [] and r.status_code == 200 and r.json() == direct.json()
        for method in ("GET", "HEAD", "POST"):
            for path in ("/api", "/api/", "/api/no-such-route"):
                r = client.request(method, path, headers={**load, **WWW}, follow_redirects=False)
                assert r.status_code != 301 and "location" not in r.headers, (method, path)


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
def test_only_a_page_load_moves_off_www(client, method):
    r = client.request(method, "/?code=ABCD", headers={**NAV, **WWW}, follow_redirects=False)
    assert r.status_code != 301 and "location" not in r.headers


@pytest.mark.parametrize("fetch", SOUND_FETCHES, ids=["cors", "no-cors-audio", "accept-any", "bare"])
def test_a_www_sound_fetch_is_not_moved_by_the_server_app(client, fetch):
    r = client.get(SOUND, headers={**fetch, **WWW}, follow_redirects=True)
    assert r.history == [] and r.status_code != 301
    direct = client.get(SOUND, headers=fetch)
    assert r.status_code == direct.status_code


@pytest.fixture()
def www_site(tmp_path):
    """The server's www middleware in front of a built site: the page, a
    sound clip, a script and a stylesheet."""
    from shengji.api import server as srv
    from shengji.api import support

    (tmp_path / "index.html").write_text("<!doctype html><title>Sheng Ji</title>")
    (tmp_path / "sounds").mkdir()
    (tmp_path / "sounds" / "bi.mp3").write_bytes(b"ID3 clip")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "index-abc.js").write_text("console.log(1)")
    (tmp_path / "assets" / "index-abc.css").write_text("body{}")
    (tmp_path / "manifest.webmanifest").write_text("{}")
    app = FastAPI()
    support.register_support(app, tmp_path)
    app.mount("/", srv.WebFiles(directory=tmp_path, html=True), name="web")
    app.add_middleware(srv.WwwRedirect)
    app.add_middleware(srv.SecurityHeaders)
    return TestClient(app)


@pytest.mark.parametrize("fetch", SOUND_FETCHES, ids=["cors", "no-cors-audio", "accept-any", "bare"])
def test_a_www_tab_plays_its_sounds_in_place(www_site, fetch):
    r = www_site.get(SOUND, headers={**fetch, **WWW}, follow_redirects=True)
    assert r.history == [] and r.request.headers["host"] == "www.playshengji.com"
    assert r.status_code == 200 and r.content == b"ID3 clip"


@pytest.mark.parametrize("path", ["/assets/index-abc.js", "/assets/index-abc.css",
                                  "/manifest.webmanifest", SOUND, "/sounds/bi.mp3"])
def test_a_www_file_is_never_moved_even_when_it_asks_for_html(www_site, path):
    for load in (NAV, {"sec-fetch-mode": "navigate"}, HTML_ONLY,
                 {**NAV, "sec-fetch-mode": "no-cors", "sec-fetch-dest": "script"},
                 {**NAV, "sec-fetch-dest": "iframe"}):
        r = www_site.get(path, headers={**load, **WWW}, follow_redirects=True)
        assert r.history == [] and r.status_code == 200, (path, load)


def test_a_www_page_load_and_its_sounds_together(www_site):
    page = www_site.get("/?code=ABCD", headers={**NAV, **WWW}, follow_redirects=True)
    assert [h.status_code for h in page.history] == [301]
    assert str(page.url) == "https://playshengji.com/?code=ABCD" and page.status_code == 200
    assert "<title>Sheng Ji</title>" in page.text
    for fetch in SOUND_FETCHES:
        r = www_site.get(SOUND, headers={**fetch, **WWW}, follow_redirects=True)
        assert r.history == [] and r.status_code == 200 and r.content == b"ID3 clip"
    bare = www_site.get("/?code=ABCD", headers={**HTML_ONLY, **WWW}, follow_redirects=True)
    assert [h.status_code for h in bare.history] == [301] and bare.status_code == 200
