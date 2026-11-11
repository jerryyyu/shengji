"""The support form (``POST /api/support``) and the ``/support`` and
``/privacy`` page routes (``shengji.api.support``).

Messages land in a private data dir; the answer never carries what was
stored. The page routes are checked on a bare app with a fake build, the way
the static mount is checked in ``test_web_cache_headers``.
"""
from __future__ import annotations

import json

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


@pytest.mark.parametrize("path", ["/support", "/privacy", "/support/", "/privacy/"])
def test_the_pages_serve_the_app_on_a_deep_link_or_reload(tmp_path, path):
    r = _page_client(tmp_path).get(path)
    assert r.status_code == 200
    assert "<title>Sheng Ji</title>" in r.text
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["cache-control"] == "no-cache"


def test_the_pages_are_404_without_a_build(tmp_path):
    from shengji.api import support

    app = FastAPI()
    support.register_support(app, tmp_path / "missing")
    c = TestClient(app)
    assert c.get("/support").status_code == 404
    assert c.get("/privacy").status_code == 404

