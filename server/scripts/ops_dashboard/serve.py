#!/usr/bin/env python3
"""Serve the ops dashboard: ``index.html`` and the collector's JSON
(``latest.json``, ``history.jsonl``, ``botspeed.json``).

Binds only the addresses given with ``--bind`` (default localhost, plus
``$OPS_BIND_EXTRA``, e.g. a Tailscale address), never the wildcard. Every
request needs ``?t=<token>`` matching ``<home>/token``; anything else answers
403. An address that is not up yet (Tailscale after a reboot) is retried
every 30 s.

The one write is ``POST /api/reports/handled`` (``{"id": ..., "handled":
true|false}``), which edits the local acknowledge list
``<home>/state/reports_handled.json``. It is accepted only on the loopback
listener from a loopback client, with the token and a JSON body. Nothing is
written to production.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collector import HANDLED_FILE, is_report_id, load_handled, reports_state  # noqa: E402

PAGE = Path(__file__).resolve().with_name("index.html")
HISTORY_LINES = 2016          # seven days at one snapshot per 5 minutes
WILDCARDS = {"0.0.0.0", "::", ""}
LOOPBACK = {"127.0.0.1", "::1"}
HANDLED_KEPT_S = 90 * 86400   # marks for reports this old leave the list
MAX_BODY = 1024
_handled_lock = threading.Lock()


def with_handled(body: bytes, home: Path) -> bytes:
    """``latest.json`` with ``reports_state`` recomputed from the current
    acknowledge list, each displayed report row's ``handled`` flag, and
    ``older``: the unhandled watch-window reports not among the displayed
    newest rows (oldest first, id and time only), so they can be marked."""
    try:
        snap = json.loads(body)
    except ValueError:
        return body
    rep = (snap.get("db") or {}).get("reports")
    if not isinstance(rep, dict):
        return body
    handled = load_handled(home)
    snap["reports_state"] = reports_state(rep, snap.get("collected_at") or time.time(), handled)
    shown = set()
    for r in rep.get("latest") or ():
        if not is_report_id(r.get("id")):
            r.pop("id", None)
        r["handled"] = r.get("id") in handled
        shown.add(r.get("id"))
    older = [{"id": r["id"], "t": r["t"], "handled": False}
             for r in rep.pop("watch", None) or ()
             if is_report_id(r.get("id")) and r["id"] not in shown
             and r["id"] not in handled and isinstance(r.get("t"), (int, float))]
    rep["older"] = sorted(older, key=lambda r: r["t"])
    return json.dumps(snap, separators=(",", ":")).encode()


def mark_handled(home: Path, rid: str, on: bool) -> dict:
    with _handled_lock:
        handled = load_handled(home)
        now = time.time()
        if on:
            handled[rid] = round(now)
        else:
            handled.pop(rid, None)
        handled = {k: v for k, v in handled.items()
                   if not isinstance(v, (int, float)) or v >= now - HANDLED_KEPT_S}
        path = home / HANDLED_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"handled": handled}, indent=1, sort_keys=True))
        os.replace(tmp, path)
    return {"id": rid, "handled": on}


def make_handler(home: Path, token: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ops"
        sys_version = ""

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Robots-Tag", "noindex")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            url = urlparse(self.path)
            given = (parse_qs(url.query).get("t") or [""])[0]
            if not hmac.compare_digest(given.encode(), token.encode()):
                return self._send(403, b"forbidden\n", "text/plain")
            if url.path in ("/", "/index.html"):
                return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            if url.path == "/api/latest":
                path = home / "latest.json"
                body = with_handled(path.read_bytes(), home) if path.exists() else b'{"errors":["no snapshot yet"]}'
                return self._send(200, body, "application/json")
            if url.path == "/api/botspeed":
                path = home / "botspeed.json"
                body = path.read_bytes() if path.exists() else b'{"days":{},"hours":{}}'
                return self._send(200, body, "application/json")
            if url.path == "/api/history":
                lines: deque = deque(maxlen=HISTORY_LINES)
                path = home / "history.jsonl"
                if path.exists():
                    with open(path) as fh:
                        lines.extend(fh)
                rows = []
                for line in lines:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue
                return self._send(200, json.dumps(rows).encode(), "application/json")
            return self._send(404, b"not found\n", "text/plain")

        do_HEAD = do_GET

        def do_POST(self) -> None:  # noqa: N802
            url = urlparse(self.path)
            given = (parse_qs(url.query).get("t") or [""])[0]
            if not hmac.compare_digest(given.encode(), token.encode()):
                return self._send(403, b"forbidden\n", "text/plain")
            if url.path != "/api/reports/handled":
                return self._send(404, b"not found\n", "text/plain")
            if (self.server.server_address[0] not in LOOPBACK
                    or self.client_address[0] not in LOOPBACK):
                return self._send(403, b"marking reports works on this Mac only\n", "text/plain")
            if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
                return self._send(415, b"json only\n", "text/plain")
            try:
                n = int(self.headers.get("Content-Length") or 0)
                req = json.loads(self.rfile.read(n)) if 0 < n <= MAX_BODY else None
                rid, on = req["id"], req["handled"]
            except (ValueError, TypeError, KeyError):
                return self._send(400, b"bad request\n", "text/plain")
            if not is_report_id(rid) or not isinstance(on, bool):
                return self._send(400, b"bad request\n", "text/plain")
            out = mark_handled(home, rid, on)
            return self._send(200, json.dumps(out).encode(), "application/json")

        def log_message(self, fmt, *args):  # the query string holds the token
            sys.stderr.write(f"{self.log_date_time_string()} {self.command} "
                             f"{urlparse(self.path).path} {args[1] if len(args) > 1 else ''}\n")

    return Handler


def serve_one(addr: str, port: int, handler) -> None:
    while True:
        try:
            httpd = ThreadingHTTPServer((addr, port), handler)
        except OSError as exc:
            print(f"bind {addr}:{port} failed ({exc.strerror}); retrying in 30 s", file=sys.stderr)
            time.sleep(30)
            continue
        print(f"listening on http://{addr}:{port}/", file=sys.stderr)
        httpd.serve_forever()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--home", type=Path, default=Path.home() / "shengji-ops")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--bind", default=",".join(
        a for a in ("127.0.0.1", os.environ.get("OPS_BIND_EXTRA", "")) if a))
    args = ap.parse_args()
    addrs = [a.strip() for a in args.bind.split(",")]
    if any(a in WILDCARDS for a in addrs):
        ap.error("refusing to bind a wildcard address")
    token = (args.home / "token").read_text().strip()
    if len(token) < 16:
        ap.error("token file is missing or shorter than 16 characters")
    handler = make_handler(args.home, token)
    threads = [threading.Thread(target=serve_one, args=(a, args.port, handler), daemon=True)
               for a in addrs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return 0


if __name__ == "__main__":
    sys.exit(main())
