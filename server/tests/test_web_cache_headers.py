"""Cache headers and precompressed files on the built web page.

The page itself keeps its name across deploys, so a browser must re-check it
each load or a phone keeps showing the previous layout after a deploy; the
hashed files under assets/ never change and may be cached for good, as may a
sound clip fetched with its ``?v=`` version. A file under assets/ with a
``.br`` or ``.gz`` sibling (written by the build) is sent as that sibling to a
browser that accepts the coding.
"""
from __future__ import annotations

import gzip

from fastapi import FastAPI
from fastapi.testclient import TestClient

from shengji.api.server import WebFiles


def _client(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>t</title>")
    (tmp_path / "assets" / "index-abc123.css").write_text("body{}")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    (tmp_path / "sounds").mkdir()
    (tmp_path / "sounds" / "bi.mp3").write_bytes(b"ID3")
    js = b"console.log('a long enough line to compress');\n" * 40
    (tmp_path / "assets" / "index-abc123.js").write_bytes(js)
    (tmp_path / "assets" / "index-abc123.js.gz").write_bytes(gzip.compress(js))
    (tmp_path / "assets" / "index-abc123.js.br").write_bytes(b"brotli bytes")
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


JS = "/assets/index-abc123.js"


def test_a_browser_that_takes_brotli_gets_the_br_file(tmp_path):
    r = _client(tmp_path).get(JS, headers={"accept-encoding": "gzip, deflate, br"})
    assert r.status_code == 200
    assert r.headers["content-encoding"] == "br"
    assert r.headers["content-type"] == "text/javascript; charset=utf-8"
    assert r.headers["vary"] == "Accept-Encoding"
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert r.headers["content-length"] == str(len(b"brotli bytes"))


def test_gzip_when_brotli_is_not_accepted(tmp_path):
    c = _client(tmp_path)
    for header in ("gzip", "br;q=0, gzip;q=0.5", "GZIP"):
        r = c.get(JS, headers={"accept-encoding": header})
        assert r.headers["content-encoding"] == "gzip", header
        # the test client inflates it, as a browser does
        assert r.content == (tmp_path / "assets" / "index-abc123.js").read_bytes()


def test_identity_without_an_accepted_coding_or_a_sibling(tmp_path):
    c = _client(tmp_path)
    for header in ("identity", "br;q=0, gzip;q=0", "deflate"):
        r = c.get(JS, headers={"accept-encoding": header})
        assert "content-encoding" not in r.headers, header
        assert r.headers["vary"] == "Accept-Encoding"
        assert r.content == (tmp_path / "assets" / "index-abc123.js").read_bytes()
    r = c.get("/assets/index-abc123.css", headers={"accept-encoding": "br, gzip"})
    assert "content-encoding" not in r.headers and r.text == "body{}"
    assert r.headers["content-type"].startswith("text/css")


def test_a_precompressed_file_revalidates_by_its_own_etag(tmp_path):
    c = _client(tmp_path)
    first = c.get(JS, headers={"accept-encoding": "br"})
    again = c.get(JS, headers={"accept-encoding": "br", "if-none-match": first.headers["etag"]})
    assert again.status_code == 304
    plain = c.get(JS, headers={"accept-encoding": "identity"})
    assert plain.headers["etag"] != first.headers["etag"]


def test_head_gets_the_same_headers(tmp_path):
    r = _client(tmp_path).head(JS, headers={"accept-encoding": "br"})
    assert r.status_code == 200 and r.headers["content-encoding"] == "br"


def test_a_versioned_sound_is_cached_for_good_and_an_unversioned_one_is_not(tmp_path):
    c = _client(tmp_path)
    assert c.get("/sounds/bi.mp3?v=9").headers["cache-control"] == "public, max-age=31536000, immutable"
    assert c.get("/sounds/bi.mp3").headers["cache-control"] == "no-cache"
    assert c.get("/sounds/bi.mp3?x=9").headers["cache-control"] == "no-cache"
