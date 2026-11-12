#!/usr/bin/env python3
"""Serve the ops dashboard: ``index.html`` and the collector's JSON.

Binds only the addresses given with ``--bind`` (default localhost and the
Mini's Tailscale address), never the wildcard. Every request needs
``?t=<token>`` matching ``<home>/token``; anything else answers 403. An
address that is not up yet (Tailscale after a reboot) is retried every 30 s.
"""

from __future__ import annotations

import argparse
import hmac
import json
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PAGE = Path(__file__).resolve().with_name("index.html")
HISTORY_LINES = 2016          # seven days at one snapshot per 5 minutes
WILDCARDS = {"0.0.0.0", "::", ""}


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
                body = path.read_bytes() if path.exists() else b'{"errors":["no snapshot yet"]}'
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
    ap.add_argument("--bind", default="127.0.0.1,100.113.192.116")
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
