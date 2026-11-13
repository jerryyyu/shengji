"""The public support form and the two public pages App Store Connect links to.

``POST /api/support`` appends one JSON line per message to
``support_messages.jsonl`` in ``accounts.data_dir()`` (the Fly volume in
production). Nothing is emailed and nothing stored is ever sent back: the
answer is ``{"ok": true}`` or an error code. A filled honeypot field reads as
success to its sender and is not stored.

``GET /support`` and ``GET /privacy`` answer with the built page's
``index.html`` so a deep link or a reload lands on the page; the web app
picks the screen from the path. ``GET /rules`` and ``GET /rules/zh`` answer
with the static rules pages, which need no script.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import accounts

FILE_NAME = "support_messages.jsonl"
TOPICS = frozenset({"bug", "feedback", "account", "other"})
MESSAGE_MIN = 10
MESSAGE_MAX = 4000
EMAIL_MAX = 254
VERSION_MAX = 80
USER_AGENT_MAX = 400
# Five messages an hour per client address: enough for a person writing a
# follow-up, too few for a script to fill the volume.
RATE_LIMIT = 5
RATE_WINDOW = 3600.0
# A plausible address: one @, no spaces, a dot in the domain. Deliverability
# is not checkable without sending mail, which this server never does.
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s.]+(\.[^@\s.]+)+$")
# Control characters other than the line breaks and tab a message may hold.
_MESSAGE_ALLOWED_CONTROLS = frozenset("\n\r\t")

LIMITER = accounts.RateLimiter(limit=RATE_LIMIT, window=RATE_WINDOW)
_write_lock = threading.Lock()

router = APIRouter()


class SupportPost(BaseModel):
    topic: Any = None
    message: Any = None
    email: Any = None
    # The honeypot: hidden from people, so only a form-filling script sets it.
    website: Any = None
    version: Any = None


def messages_path() -> Path:
    return accounts.data_dir() / FILE_NAME


def _clean_line(value: Any, limit: int) -> str | None:
    """A short single-line string with control characters dropped, or None."""
    if not isinstance(value, str):
        return None
    text = "".join(ch for ch in value if unicodedata.category(ch) != "Cc").strip()
    return text[:limit] or None


def validate(body: SupportPost) -> dict:
    """The fields to store, or ``HTTPException(400)`` with a short code."""
    topic = body.topic.strip().lower() if isinstance(body.topic, str) else ""
    if topic not in TOPICS:
        raise HTTPException(status_code=400, detail="bad_topic")
    if not isinstance(body.message, str):
        raise HTTPException(status_code=400, detail="message_too_short")
    message = "".join(ch for ch in body.message
                      if unicodedata.category(ch) != "Cc" or ch in _MESSAGE_ALLOWED_CONTROLS).strip()
    if len(message) < MESSAGE_MIN:
        raise HTTPException(status_code=400, detail="message_too_short")
    if len(message) > MESSAGE_MAX:
        raise HTTPException(status_code=400, detail="message_too_long")
    email: str | None = None
    if body.email is not None:
        if not isinstance(body.email, str):
            raise HTTPException(status_code=400, detail="bad_email")
        email = body.email.strip() or None
        if email is not None and (len(email) > EMAIL_MAX or not EMAIL_RE.match(email)):
            raise HTTPException(status_code=400, detail="bad_email")
    return {"topic": topic, "message": message, "email": email,
            "version": _clean_line(body.version, VERSION_MAX)}


def _append(record: dict) -> None:
    path = messages_path()
    line = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
    with _write_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "ab") as f:
            f.write(line)


async def _session_account(request: Request) -> dict | None:
    """The signed-in account behind the request, or None. A storage error
    reads as signed out: the message is still worth keeping."""
    token = request.cookies.get(accounts.COOKIE)
    if not token:
        return None
    try:
        return await accounts.STORE.run(accounts.STORE.session_user, token)
    except Exception:           # noqa: BLE001 - a message over an identity
        return None


@router.post("/api/support")
async def post_support(body: SupportPost, request: Request) -> dict:
    fields = validate(body)
    if not LIMITER.allow(accounts.client_ip(request)):
        raise HTTPException(status_code=429, detail="rate_limited")
    if isinstance(body.website, str) and body.website.strip():
        return {"ok": True}
    user = await _session_account(request)
    record = {
        "ts": round(time.time(), 3),
        "topic": fields["topic"],
        "message": fields["message"],
        "email": fields["email"],
        "account_id": int(user["id"]) if user else None,
        "account_name": accounts.effective_name(user) if user else None,
        "version": fields["version"],
        "user_agent": _clean_line(request.headers.get("user-agent"), USER_AGENT_MAX),
    }
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, _append, record)
    except OSError as exc:
        raise HTTPException(status_code=503, detail="not_stored") from exc
    return {"ok": True}


# Static rules pages built from web/public/rules/: each URL answers with its
# own index.html, with or without the trailing slash, so the canonical
# address (no slash) is a 200 rather than the static mount's redirect.
RULES_PAGES = {"/rules": "rules/index.html", "/rules/zh": "rules/zh/index.html"}


def _html(file: Path) -> FileResponse:
    if not file.is_file():
        raise HTTPException(status_code=404, detail="Not found.")
    return FileResponse(file, media_type="text/html",
                        headers={"Cache-Control": "no-cache"})


def _static_page(file: Path):
    """A handler with no parameters, so no request value can choose the file."""

    def handler() -> FileResponse:
        return _html(file)

    return handler


def register_support(app, dist: Path) -> None:
    """The API route and the page routes; call before the static mount,
    whose catch-all would otherwise answer ``/support`` with a 404."""

    def page() -> FileResponse:
        return _html(dist / "index.html")

    pages = APIRouter()
    for path in ("/support", "/support/", "/privacy", "/privacy/"):
        pages.add_api_route(path, page, methods=["GET", "HEAD"], include_in_schema=False)
    for path, rel in RULES_PAGES.items():
        for variant in (path, path + "/"):
            pages.add_api_route(variant, _static_page(dist / rel), methods=["GET", "HEAD"],
                                include_in_schema=False)
    app.include_router(router)
    app.include_router(pages)
