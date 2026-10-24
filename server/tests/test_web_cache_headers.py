"""Cache headers on the built web page.

The page itself keeps its name across deploys, so a browser must re-check it
each load or a phone keeps showing the previous layout after a deploy; the
hashed files under assets/ never change and may be cached for good.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from shengji.api.server import WebFiles


def _client(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>t</title>")
    (tmp_path / "assets" / "index-abc123.css").write_text("body{}")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    app = FastAPI()
    app.mount("/", WebFiles(directory=tmp_path, html=True), name="web")
    return TestClient(app)


def test_the_page_is_revalidated_every_load(tmp_path):
    c = _client(tmp_path)
    for path in ("/", "/index.html", "/favicon.svg"):
        r = c.get(path)
        assert r.status_code == 200
        assert r.headers["cache-control"] == "no-cache", path


def test_hashed_assets_are_cached_for_good(tmp_path):
    r = _client(tmp_path).get("/assets/index-abc123.css")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_a_conditional_reload_still_gets_304(tmp_path):
    c = _client(tmp_path)
    etag = c.get("/").headers["etag"]
    r = c.get("/", headers={"if-none-match": etag})
    assert r.status_code == 304
