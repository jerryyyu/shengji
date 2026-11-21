"""Device-test log upload for Nearby builds (``POST /api/nearby-log``).

A Nearby device-test build posts its log text here so a soak can be read
without the phone in hand. The route is write-only: nothing stored is ever
served back over HTTP; the files are read on the volume over ``flyctl ssh``.

Each accepted request is appended to ``<root>/<device>/<UTC date>.txt`` after
one header line ``# recv <UTC iso> offset=<n> build=<label> bytes=<n>``. The
root is ``SHENGJI_NEARBY_LOG_ROOT`` (default ``/data/nearby_logs``). Only the
validated device id, offset, build label and log lines are stored: never the
client address, a cookie, an account or any other header. The route reads no
cookie and no session, and touches no room, game or account state.

CORS: the device build's page is served from ``capacitor://localhost``, a
different origin from the server, so this one route answers that exact origin
(preflight and every POST status, never credentials). No other route sends
CORS headers.

Limits: 120 requests an hour per device and 240 per client address (memory
only); a body over 1,000,000 bytes is a 413; more than
``SHENGJI_NEARBY_LOG_CAP_BYTES`` (default 500 MB) under the root is a 507.
Day files older than 14 days are deleted by a sweep at registration and then
at most once an hour, run by the request that finds the hour has passed.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from . import accounts

log = logging.getLogger(__name__)

PATH = "/api/nearby-log"
ROOT_ENV = "SHENGJI_NEARBY_LOG_ROOT"
DEFAULT_ROOT = "/data/nearby_logs"
CAP_ENV = "SHENGJI_NEARBY_LOG_CAP_BYTES"
DEFAULT_CAP = 500 * 1000 * 1000
MAX_BODY = 1_000_000
MAX_LINE = 2000
RETENTION_DAYS = 14
SWEEP_INTERVAL = 3600.0
DEVICE_LIMIT = 120
IP_LIMIT = 240
RATE_WINDOW = 3600.0

APP_ORIGIN = "capacitor://localhost"
CORS_PREFLIGHT_HEADERS = {
    "Access-Control-Allow-Origin": APP_ORIGIN,
    "Access-Control-Allow-Methods": "POST",
    "Access-Control-Allow-Headers": "Content-Type, X-Nearby-Device, X-Nearby-Offset, X-Nearby-Build",
    "Access-Control-Max-Age": "600",
    "Vary": "Origin",
}

DEVICE_RE = re.compile(r"[A-Z0-9]{12}")
OFFSET_RE = re.compile(r"[0-9]{1,18}")
BUILD_RE = re.compile(r"[A-Za-z0-9 ._-]{1,64}")
LINE_RE = re.compile(r"\d+\.\d{3} [a-z]+ .*", re.ASCII)
DAY_FILE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\.txt")

DEVICE_LIMITER = accounts.RateLimiter(limit=DEVICE_LIMIT, window=RATE_WINDOW)
IP_LIMITER = accounts.RateLimiter(limit=IP_LIMIT, window=RATE_WINDOW)
_write_lock = threading.Lock()
# Monotonic time of the last retention sweep; None until the first one.
_last_sweep: float | None = None


class StoreFull(Exception):
    """The root already holds the cap, so the record is refused."""


def root() -> Path:
    return Path(os.environ.get(ROOT_ENV) or DEFAULT_ROOT)


def cap_bytes() -> int:
    try:
        value = int(os.environ.get(CAP_ENV, ""))
    except ValueError:
        return DEFAULT_CAP
    return value if value > 0 else DEFAULT_CAP


def build_label(raw: str | None) -> str:
    """The build header when it is a short plain label, else ``-``."""
    if raw is not None and BUILD_RE.fullmatch(raw):
        return raw
    return "-"


def valid_log_text(text: str) -> bool:
    """Every non-empty line has the log shape and fits the line limit."""
    for line in text.split("\n"):
        if not line:
            continue
        if len(line) > MAX_LINE or not LINE_RE.fullmatch(line):
            return False
    return True


def sweep(base: Path, today: datetime) -> int:
    """Delete day files older than the retention window; returns the count.
    Only ``<device>/<YYYY-MM-DD>.txt`` files are considered."""
    if not base.is_dir():
        return 0
    oldest_kept = (today - timedelta(days=RETENTION_DAYS)).date()
    removed = 0
    for device_dir in base.iterdir():
        if not device_dir.is_dir() or device_dir.is_symlink() or not DEVICE_RE.fullmatch(device_dir.name):
            continue
        for f in device_dir.iterdir():
            m = DAY_FILE_RE.fullmatch(f.name)
            if not m or not f.is_file() or f.is_symlink():
                continue
            try:
                day = datetime.strptime(m.group(1), "%Y-%m-%d").date()
            except ValueError:
                continue
            if day < oldest_kept:
                f.unlink(missing_ok=True)
                removed += 1
        try:
            device_dir.rmdir()          # only succeeds when empty
        except OSError:
            pass
    return removed


def _sweep_if_due(base: Path, now: datetime) -> None:
    global _last_sweep
    t = time.monotonic()
    if _last_sweep is not None and t - _last_sweep < SWEEP_INTERVAL:
        return
    _last_sweep = t
    try:
        sweep(base, now)
    except OSError as exc:
        log.warning("nearby-log sweep failed: %s", type(exc).__name__)


def _stored_bytes(base: Path) -> int:
    total = 0
    if not base.is_dir():
        return 0
    for dirpath, _dirs, files in os.walk(base):
        for name in files:
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_size
            except OSError:
                pass
    return total


def _append(device: str, offset: int, build: str, text: str, now: datetime) -> None:
    base = root()
    body = text if text.endswith("\n") else text + "\n"
    payload = body.encode("utf-8")
    header = (f"# recv {now.strftime('%Y-%m-%dT%H:%M:%S.%fZ')} offset={offset} "
              f"build={build} bytes={len(text.encode('utf-8'))}\n").encode("utf-8")
    record = header + payload
    with _write_lock:
        _sweep_if_due(base, now)
        if _stored_bytes(base) + len(record) > cap_bytes():
            raise StoreFull
        path = base / device / f"{now.strftime('%Y-%m-%d')}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            start = os.fstat(fd).st_size
            try:
                view = memoryview(record)
                while view:
                    n = os.write(fd, view)
                    if n <= 0:
                        raise OSError("append made no progress")
                    view = view[n:]
                os.fsync(fd)
            except OSError:
                # a record is whole or absent: cut back to the length before this append
                try:
                    os.ftruncate(fd, start)
                    os.fsync(fd)
                except OSError:
                    pass
                raise
        finally:
            os.close(fd)


class _TooLarge(Exception):
    pass


async def _read_capped(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > MAX_BODY:
                raise _TooLarge
        except ValueError:
            pass
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY:
            raise _TooLarge
        chunks.append(chunk)
    return b"".join(chunks)


def _cors(request: Request) -> dict[str, str]:
    if request.headers.get("origin") == APP_ORIGIN:
        return {"Access-Control-Allow-Origin": APP_ORIGIN, "Vary": "Origin"}
    return {"Vary": "Origin"}


def _answer(request: Request, status: int, device: str, size: int, code: str | None = None) -> Response:
    log.info("nearby-log device=%s bytes=%d status=%d", device, size, status)
    headers = _cors(request)
    if code is None:
        return Response(status_code=status, headers=headers)
    return JSONResponse({"detail": code}, status_code=status, headers=headers)


router = APIRouter()


@router.options(PATH, include_in_schema=False)
async def preflight(request: Request) -> Response:
    if request.headers.get("origin") == APP_ORIGIN:
        return Response(status_code=204, headers=CORS_PREFLIGHT_HEADERS)
    return Response(status_code=204, headers={"Vary": "Origin"})


@router.post(PATH, include_in_schema=False)
async def post_nearby_log(request: Request) -> Response:
    device = request.headers.get("x-nearby-device", "")
    if not DEVICE_RE.fullmatch(device):
        return _answer(request, 400, "invalid", 0, "bad_device")
    raw_offset = request.headers.get("x-nearby-offset", "")
    if not OFFSET_RE.fullmatch(raw_offset):
        return _answer(request, 400, device, 0, "bad_offset")
    offset = int(raw_offset)
    build = build_label(request.headers.get("x-nearby-build"))
    if not IP_LIMITER.allow(accounts.client_ip(request)):
        return _answer(request, 429, device, 0, "rate_limited")
    if not DEVICE_LIMITER.allow(device):
        return _answer(request, 429, device, 0, "rate_limited")
    try:
        raw = await _read_capped(request)
    except _TooLarge:
        return _answer(request, 413, device, 0, "too_large")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return _answer(request, 400, device, len(raw), "bad_encoding")
    if not valid_log_text(text):
        return _answer(request, 400, device, len(raw), "bad_content")
    if not text.strip("\n"):
        return _answer(request, 204, device, 0)
    try:
        await run_in_threadpool(_append, device, offset, build, text, datetime.now(timezone.utc))
    except StoreFull:
        return _answer(request, 507, device, len(raw), "store_full")
    except OSError as exc:
        log.warning("nearby-log write failed: %s", type(exc).__name__)
        return _answer(request, 503, device, len(raw), "not_stored")
    return _answer(request, 204, device, len(raw))


def register_nearby_logs(app) -> None:
    """Add the route and run the startup retention sweep; call before the
    static mount."""
    global _last_sweep
    _last_sweep = time.monotonic()
    try:
        sweep(root(), datetime.now(timezone.utc))
    except OSError as exc:
        log.warning("nearby-log sweep failed: %s", type(exc).__name__)
    app.include_router(router)
