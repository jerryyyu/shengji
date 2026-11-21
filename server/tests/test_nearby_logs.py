"""The Nearby device-test log upload (``POST /api/nearby-log``,
``shengji.api.nearby_logs``): a write-only append store with its own CORS
answer for the app's ``capacitor://localhost`` page.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import pytest

from tests.test_server_ws import client  # noqa: F401

DEVICE = "AB12CD34EF56"
APP = "capacitor://localhost"
LOG = "1732190000.123 link up peer=2\n1732190001.456 ping rtt=31\n"
CLIENT_IP = "203.0.113.77"
COOKIE_VALUE = "session-token-that-must-not-be-read"


@pytest.fixture()
def nearby(tmp_path, monkeypatch):
    """A private root, fresh limiters and a fresh sweep clock."""
    from shengji.api import accounts, nearby_logs

    monkeypatch.setenv(nearby_logs.ROOT_ENV, str(tmp_path / "nearby"))
    monkeypatch.delenv(nearby_logs.CAP_ENV, raising=False)
    monkeypatch.setattr(nearby_logs, "DEVICE_LIMITER", accounts.RateLimiter(limit=120, window=3600.0))
    monkeypatch.setattr(nearby_logs, "IP_LIMITER", accounts.RateLimiter(limit=240, window=3600.0))
    monkeypatch.setattr(nearby_logs, "_last_sweep", None)
    return nearby_logs


def _post(client, body=LOG, device=DEVICE, offset="0", build=None, extra=None):
    headers = {"content-type": "text/plain; charset=utf-8", "origin": APP,
               "fly-client-ip": CLIENT_IP}
    if device is not None:
        headers["x-nearby-device"] = device
    if offset is not None:
        headers["x-nearby-offset"] = offset
    if build is not None:
        headers["x-nearby-build"] = build
    headers.update(extra or {})
    headers = {k: v.encode("utf-8") if not v.isascii() else v for k, v in headers.items()}
    data = body.encode("utf-8") if isinstance(body, str) else body
    return client.post("/api/nearby-log", content=data, headers=headers)


def _files(nearby_logs):
    base = nearby_logs.root()
    return sorted(p for p in base.rglob("*") if p.is_file()) if base.exists() else []


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def test_an_upload_appends_under_one_header_line(client, nearby):
    r = _post(client, offset="42", build="beta 1.4.0-b7")
    assert r.status_code == 204
    assert r.headers["access-control-allow-origin"] == APP
    assert "access-control-allow-credentials" not in r.headers
    r2 = _post(client, body="1732190002.000 seat taken=1", offset="99")
    assert r2.status_code == 204
    path = nearby.root() / DEVICE / f"{_today()}.txt"
    assert _files(nearby) == [path]
    lines = path.read_text("utf-8").splitlines()
    assert lines[0].startswith("# recv ")
    assert lines[0].endswith(f" offset=42 build=beta 1.4.0-b7 bytes={len(LOG.encode())}")
    assert lines[1:3] == LOG.splitlines()
    assert lines[3].startswith("# recv ") and lines[3].endswith(" offset=99 build=- bytes=27")
    assert lines[4] == "1732190002.000 seat taken=1"
    assert len(lines) == 5
    stamp = lines[0].split()[2]
    assert datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%fZ")


@pytest.mark.parametrize("build", ["x" * 65, "beta;rm", "béta", ""])
def test_a_bad_build_label_is_dropped_not_refused(client, nearby, build):
    assert _post(client, build=build).status_code == 204
    first = _files(nearby)[0].read_text("utf-8").splitlines()[0]
    assert " build=- " in first


@pytest.mark.parametrize("device", [None, "", "ab12cd34ef56", "AB12CD34EF5", "AB12CD34EF567",
                                    "AB12CD34EF5!", "../../etc/pa", "AB12CD34EF5٠"])
def test_a_bad_device_is_a_400(client, nearby, device):
    r = _post(client, device=device)
    assert r.status_code == 400
    assert r.json() == {"detail": "bad_device"}
    assert r.headers["access-control-allow-origin"] == APP
    assert _files(nearby) == []


@pytest.mark.parametrize("offset", [None, "", "-1", "1.5", "abc", " 3", "0x10", "٣"])
def test_a_bad_offset_is_a_400(client, nearby, offset):
    r = _post(client, offset=offset)
    assert r.status_code == 400
    assert r.json() == {"detail": "bad_offset"}
    assert _files(nearby) == []


@pytest.mark.parametrize("body", [
    "hello world\n",                                   # no timestamp
    "1732190000.12 link up\n",                         # two decimals
    "1732190000.123 Link up\n",                        # upper-case tag
    "1732190000.123 link\n",                           # no space after the tag
    "1732190000.123 link up\n<script>x</script>\n",    # one bad line among good ones
    "1732190000.123 link " + "x" * 2000 + "\n",        # over the line limit
    "١732190000.123 link up\n",                   # a non-ASCII digit
    "1732190000.123 link up\r\nsecond\n",              # a stray second line
])
def test_content_outside_the_log_shape_is_a_400(client, nearby, body):
    r = _post(client, body=body)
    assert r.status_code == 400
    assert r.json() == {"detail": "bad_content"}
    assert _files(nearby) == []


def test_a_line_at_the_limit_is_kept_and_blank_lines_pass(client, nearby):
    line = "1732190000.123 link " + "x" * (2000 - len("1732190000.123 link "))
    assert len(line) == 2000
    assert _post(client, body="\n" + line + "\n\n").status_code == 204


def test_invalid_utf8_is_a_400(client, nearby):
    r = _post(client, body=b"1732190000.123 link \xff\xfe\n")
    assert r.status_code == 400
    assert r.json() == {"detail": "bad_encoding"}


def test_an_empty_body_stores_nothing(client, nearby):
    assert _post(client, body="").status_code == 204
    assert _files(nearby) == []


def test_a_body_over_the_cap_is_a_413(client, nearby):
    line = "1732190000.123 x " + "y" * 1000 + "\n"
    body = line * (nearby.MAX_BODY // len(line) + 1)
    assert len(body.encode()) > nearby.MAX_BODY
    r = _post(client, body=body)
    assert r.status_code == 413
    assert r.headers["access-control-allow-origin"] == APP
    assert _files(nearby) == []
    # at the cap exactly is accepted
    exact = (line * (nearby.MAX_BODY // len(line)))
    exact += "1732190000.123 x " + "z" * (nearby.MAX_BODY - len(exact) - 18) + "\n"
    assert len(exact.encode()) == nearby.MAX_BODY
    assert _post(client, body=exact).status_code == 204


def test_a_streamed_body_over_the_cap_is_a_413_without_content_length(nearby):
    """The read stops at the cap even when no Content-Length announces it."""
    import asyncio

    from starlette.requests import Request

    chunk = b"1732190000.123 x " + b"y" * 65000 + b"\n"
    sent = {"n": 0}

    async def receive():
        sent["n"] += 1
        return {"type": "http.request", "body": chunk, "more_body": True}

    request = Request({"type": "http", "method": "POST", "headers": []}, receive)
    with pytest.raises(nearby._TooLarge):
        asyncio.run(nearby._read_capped(request))
    assert sent["n"] == nearby.MAX_BODY // len(chunk) + 1


def test_the_default_rate_limits_are_120_per_device_and_240_per_ip():
    from shengji.api import nearby_logs

    assert (nearby_logs.DEVICE_LIMIT, nearby_logs.IP_LIMIT, nearby_logs.RATE_WINDOW) == (120, 240, 3600.0)


def test_a_device_over_120_an_hour_is_a_429(client, nearby):
    for i in range(120):
        assert _post(client, body="", extra={"fly-client-ip": f"198.51.100.{i % 2}"}).status_code == 204
    r = _post(client, body="", extra={"fly-client-ip": "198.51.100.9"})
    assert r.status_code == 429
    assert r.json() == {"detail": "rate_limited"}
    assert r.headers["access-control-allow-origin"] == APP
    assert _post(client, body="", device="ZZ12CD34EF56").status_code == 204


def test_an_address_over_240_an_hour_is_a_429(client, nearby):
    for i in range(240):
        device = f"DEV{i:09d}"
        assert _post(client, body="", device=device).status_code == 204
    assert _post(client, body="", device="FRESH0000001").status_code == 429
    assert _post(client, body="", device="FRESH0000001",
                 extra={"fly-client-ip": "198.51.100.200"}).status_code == 204


def test_the_store_cap_is_a_507(client, nearby, monkeypatch):
    monkeypatch.setenv(nearby.CAP_ENV, "400")
    assert _post(client).status_code == 204
    size = sum(p.stat().st_size for p in _files(nearby))
    assert size < 400
    r = _post(client, body=LOG * 4)
    assert r.status_code == 507
    assert r.json() == {"detail": "store_full"}
    assert r.headers["access-control-allow-origin"] == APP
    assert sum(p.stat().st_size for p in _files(nearby)) == size


def test_the_sweep_deletes_day_files_older_than_14_days(nearby):
    base = nearby.root()
    now = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
    keep, gone = base / DEVICE, base / "OLD000000001"
    keep.mkdir(parents=True)
    gone.mkdir(parents=True)

    def day(n):
        return (now - timedelta(days=n)).strftime("%Y-%m-%d") + ".txt"

    for n in (0, 13, 14):
        (keep / day(n)).write_text("x\n")
    (keep / day(15)).write_text("x\n")
    (keep / "notes.md").write_text("not a day file\n")
    (gone / day(30)).write_text("x\n")
    stray = base / "README"
    stray.write_text("left alone\n")
    assert nearby.sweep(base, now) == 2
    assert sorted(p.name for p in keep.iterdir()) == sorted([day(0), day(13), day(14), "notes.md"])
    assert not gone.exists()
    assert stray.exists()


def test_a_request_runs_the_sweep_at_most_once_an_hour(client, nearby, monkeypatch):
    calls = []
    monkeypatch.setattr(nearby, "sweep", lambda base, now: calls.append(now) or 0)
    t = [1000.0]
    monkeypatch.setattr(nearby.time, "monotonic", lambda: t[0])
    assert _post(client).status_code == 204
    assert _post(client).status_code == 204
    assert len(calls) == 1
    t[0] += nearby.SWEEP_INTERVAL + 1
    assert _post(client).status_code == 204
    assert len(calls) == 2


def test_registration_runs_a_startup_sweep(nearby):
    from fastapi import FastAPI

    old = nearby.root() / DEVICE / "2000-01-01.txt"
    old.parent.mkdir(parents=True)
    old.write_text("x\n")
    nearby.register_nearby_logs(FastAPI())
    assert not old.exists()


def test_preflight_from_the_app_origin_is_allowed(client, nearby):
    r = client.options("/api/nearby-log", headers={
        "origin": APP, "access-control-request-method": "POST",
        "access-control-request-headers": "content-type, x-nearby-device, x-nearby-offset, x-nearby-build"})
    assert r.status_code == 204
    assert r.headers["access-control-allow-origin"] == APP
    assert r.headers["access-control-allow-methods"] == "POST"
    assert r.headers["access-control-allow-headers"] == \
        "Content-Type, X-Nearby-Device, X-Nearby-Offset, X-Nearby-Build"
    assert "access-control-allow-credentials" not in r.headers


@pytest.mark.parametrize("origin", ["https://evil.example", "capacitor://localhost.evil.example",
                                    "http://localhost", "null", None])
def test_preflight_from_another_origin_gets_no_allow_origin(client, nearby, origin):
    headers = {"access-control-request-method": "POST"}
    if origin is not None:
        headers["origin"] = origin
    r = client.options("/api/nearby-log", headers=headers)
    assert "access-control-allow-origin" not in r.headers
    assert "access-control-allow-credentials" not in r.headers
    p = _post(client, extra={"origin": origin} if origin else {"origin": ""})
    assert "access-control-allow-origin" not in p.headers


def test_no_other_route_gains_cors_headers(client, nearby):
    for r in (client.get("/api/me", headers={"origin": APP}),
              client.options("/api/me", headers={"origin": APP, "access-control-request-method": "GET"}),
              client.post("/api/support", json={}, headers={"origin": APP})):
        assert not any(k.lower().startswith("access-control-") for k in r.headers), r.headers


def test_the_route_ignores_a_session_cookie_and_touches_no_account(client, nearby, monkeypatch):
    from shengji.api import accounts

    class Untouchable:
        def __getattr__(self, name):
            raise AssertionError(f"nearby-log touched the account store: {name}")

    monkeypatch.setattr(accounts, "STORE", Untouchable())
    client.cookies.set(accounts.COOKIE, COOKIE_VALUE)
    try:
        r = _post(client, extra={"authorization": "Bearer secret-bearer"})
    finally:
        client.cookies.clear()
    assert r.status_code == 204
    text = _files(nearby)[0].read_text("utf-8")
    assert COOKIE_VALUE not in text and "secret-bearer" not in text


def test_no_address_or_other_header_reaches_a_stored_file(client, nearby):
    assert _post(client, build="beta-7", extra={"user-agent": "UA-SENTINEL", "x-forwarded-for": "192.0.2.55",
                                                "cookie": "c=COOKIE-SENTINEL"}).status_code == 204
    assert _post(client, offset="5", extra={"fly-client-ip": "2001:db8::77"}).status_code == 204
    blob = b"".join(p.read_bytes() for p in _files(nearby))
    for needle in (CLIENT_IP, "203.0.113", "2001:db8", "192.0.2.55", "UA-SENTINEL", "COOKIE-SENTINEL",
                   "testclient", "127.0.0.1"):
        assert needle.encode() not in blob, needle


def test_one_info_line_per_request_with_no_body(client, nearby, caplog):
    with caplog.at_level(logging.INFO, logger="shengji.api.nearby_logs"):
        _post(client)
        _post(client, device="bad")
    lines = [r.getMessage() for r in caplog.records if r.name == "shengji.api.nearby_logs"]
    assert lines == [f"nearby-log device={DEVICE} bytes={len(LOG.encode())} status=204",
                     "nearby-log device=invalid bytes=0 status=400"]
    assert all("link up" not in line for line in lines)


def test_stored_files_are_owner_only(client, nearby):
    assert _post(client).status_code == 204
    assert (os.stat(_files(nearby)[0]).st_mode & 0o777) == 0o600
