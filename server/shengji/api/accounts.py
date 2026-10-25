"""Optional Google sign-in: ID-token verification, users and sessions in SQLite.

The feature is OFF unless ``GOOGLE_CLIENT_ID`` is set: the login endpoint then
answers 404 and ``/api/auth/config`` reports no client id, so the web app shows
no button. Guest play never touches this module beyond one cookie read on the
websocket handshake, and only when a ``sj_session`` cookie is present.

Trust boundary: the browser posts a Google ID token (a JWT the Google Identity
Services button handed it). The server verifies the RS256 signature against
Google's published certificates, the issuer, the audience (our client id), the
validity window and ``email_verified`` before it will mint a session. The
session token is 32 random bytes; the database stores only its SHA-256, so a
copy of the database cannot be replayed as a login. No client secret exists
anywhere: the client id is public by design.

Database access is synchronous ``sqlite3`` (WAL) on a fresh connection per
call, run off the event loop with ``run_in_executor`` so a slow disk cannot
stall a trick. Each call is a handful of indexed statements.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.request
from collections import deque
from contextlib import closing
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, WebSocket
from pydantic import BaseModel

log = logging.getLogger(__name__)

COOKIE = "sj_session"
SESSION_DAYS = 30
SESSION_SECONDS = SESSION_DAYS * 86400
GOOGLE_ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})
# PEM x509 certificates keyed by ``kid``; the format ``google.auth.jwt.decode``
# takes directly (the JWKS endpoint would need an n/e conversion first).
GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v1/certs"
CERTS_DEFAULT_TTL = 3600.0
CLOCK_SKEW_SECONDS = 10
# Per-IP budget for the login endpoint: a token verification is cheap, but a
# flood of them is the only CPU an anonymous caller can spend here.
RATE_LIMIT = 10
RATE_WINDOW = 60.0
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class AuthError(Exception):
    """A token that must not become a session; ``reason`` is a short code that
    is safe to return to the browser and never carries token material."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# ----------------------------------------------------------------- config
def client_id() -> str | None:
    """The configured Google OAuth client id, or None when sign-in is off.
    Read per request so a test (or a restart) can turn the feature on or off."""
    value = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    return value or None


def data_dir() -> Path:
    """Where the accounts database lives: ``SHENGJI_DATA_DIR``; else the Fly
    volume at ``/data`` when it exists; else the dev tree's local log folder
    (the same place a dev server writes its room logs)."""
    explicit = os.environ.get("SHENGJI_DATA_DIR")
    if explicit:
        return Path(explicit)
    volume = Path("/data")
    if volume.is_dir():
        return volume
    return Path(__file__).resolve().parents[3] / "logs" / "local"


def db_path() -> Path:
    return data_dir() / "accounts.sqlite3"


# ------------------------------------------------------------------ store
SCHEMA: list[str] = [
    # version 1
    """
    CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        google_sub TEXT NOT NULL UNIQUE,
        email TEXT,
        name TEXT,
        picture TEXT,
        created_at INTEGER NOT NULL,
        last_login_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS sessions (
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
    CREATE INDEX IF NOT EXISTS sessions_expires ON sessions(expires_at);
    """,
]


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


class Store:
    """Users and sessions in one SQLite file. Every public method is
    synchronous and opens its own connection; ``run`` moves one onto a
    worker thread for use from the event loop."""

    def __init__(self, path: Path | None = None):
        self._path = Path(path) if path is not None else None
        self._ready = False
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path if self._path is not None else db_path()

    def _connect(self) -> sqlite3.Connection:
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            conn.execute("BEGIN IMMEDIATE")
            try:
                has = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
                ).fetchone()
                version = 0
                if has:
                    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
                    version = int(row["v"] or 0)
                for i in range(version, len(SCHEMA)):
                    for statement in filter(None, (s.strip() for s in SCHEMA[i].split(";"))):
                        conn.execute(statement)
                    conn.execute("DELETE FROM schema_version")
                    conn.execute("INSERT INTO schema_version(version) VALUES (?)", (i + 1,))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            self._ready = True

    def _open(self) -> sqlite3.Connection:
        conn = self._connect()
        try:
            self._ensure_schema(conn)
        except Exception:
            conn.close()
            raise
        return conn

    def schema_version(self) -> int:
        with closing(self._open()) as conn:
            row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
            return int(row["v"] or 0)

    # -- users
    def upsert_user(self, claims: Mapping[str, Any], now: float | None = None) -> dict:
        """Create or refresh the user for a verified token's claims; returns
        the stored row as a dict."""
        t = int(now if now is not None else time.time())
        sub = str(claims["sub"])
        email = claims.get("email")
        name = claims.get("name") or claims.get("given_name") or (
            email.split("@")[0] if isinstance(email, str) else None)
        picture = claims.get("picture")
        with closing(self._open()) as conn:
            conn.execute(
                """INSERT INTO users(google_sub, email, name, picture, created_at, last_login_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(google_sub) DO UPDATE SET
                       email = excluded.email,
                       name = COALESCE(excluded.name, users.name),
                       picture = COALESCE(excluded.picture, users.picture),
                       last_login_at = excluded.last_login_at""",
                (sub, email, name, picture, t, t))
            row = conn.execute("SELECT * FROM users WHERE google_sub = ?", (sub,)).fetchone()
            return dict(row)

    def user(self, user_id: int) -> dict | None:
        with closing(self._open()) as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return dict(row) if row else None

    # -- sessions
    def create_session(self, user_id: int, now: float | None = None) -> str:
        """Mint a session token (returned once, never stored) and purge
        whatever sessions have expired."""
        t = int(now if now is not None else time.time())
        token = secrets.token_urlsafe(32)
        with closing(self._open()) as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (t,))
            conn.execute(
                "INSERT INTO sessions(token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (_hash_token(token), user_id, t, t + SESSION_SECONDS))
        return token

    def session_user(self, token: str | None, now: float | None = None) -> dict | None:
        """The user behind a live session token, else None."""
        if not token or not re.fullmatch(r"[A-Za-z0-9_-]{20,200}", token):
            return None
        t = int(now if now is not None else time.time())
        with closing(self._open()) as conn:
            row = conn.execute(
                """SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
                   WHERE s.token_hash = ? AND s.expires_at > ?""",
                (_hash_token(token), t)).fetchone()
            return dict(row) if row else None

    def delete_session(self, token: str | None) -> None:
        if not token:
            return
        with closing(self._open()) as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash_token(token),))

    def count_sessions(self, user_id: int) -> int:
        with closing(self._open()) as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM sessions WHERE user_id = ?",
                               (user_id,)).fetchone()
            return int(row["n"])

    async def run(self, fn: Callable[..., Any], *args: Any) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, fn, *args)


STORE = Store()


# ------------------------------------------------------ Google certificates
class GoogleCerts:
    """Google's current signing certificates, cached until their
    ``Cache-Control: max-age`` runs out (an hour when the header is missing).
    A fetch failure keeps serving the last good set rather than failing every
    login while Google is briefly unreachable."""

    def __init__(self, fetch: Callable[[], tuple[dict, float]] | None = None):
        self._fetch = fetch or self._fetch_http
        self._certs: dict[str, str] = {}
        self._expires = 0.0
        self._lock = threading.Lock()

    @staticmethod
    def _fetch_http() -> tuple[dict, float]:
        req = urllib.request.Request(GOOGLE_CERTS_URL, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:   # noqa: S310 - fixed https URL
            body = json.loads(resp.read().decode("utf-8"))
            ttl = CERTS_DEFAULT_TTL
            m = re.search(r"max-age=(\d+)", resp.headers.get("Cache-Control", ""))
            if m:
                ttl = float(m.group(1))
        if not isinstance(body, dict) or not all(isinstance(v, str) for v in body.values()):
            raise AuthError("certs_malformed")
        return body, ttl

    def get(self, force: bool = False) -> dict[str, str]:
        now = time.time()
        with self._lock:
            if self._certs and not force and now < self._expires:
                return self._certs
            try:
                certs, ttl = self._fetch()
            except Exception as exc:          # noqa: BLE001 - keep the last good set
                if self._certs:
                    log.warning("google certs refresh failed (%s); using cached set",
                                type(exc).__name__)
                    return self._certs
                raise AuthError("certs_unavailable") from exc
            self._certs, self._expires = dict(certs), now + max(60.0, ttl)
            return self._certs

    def reset(self) -> None:
        with self._lock:
            self._certs, self._expires = {}, 0.0


CERTS = GoogleCerts()


def _header_kid(token: str) -> str | None:
    from google.auth import jwt as google_jwt
    header, _payload, _signed, _sig = google_jwt._unverified_decode(token)  # noqa: SLF001
    kid = header.get("kid")
    return str(kid) if kid else None


def verify_google_id_token(token: str, audience: str,
                           certs: GoogleCerts | None = None) -> dict:
    """Verify a Google ID token and return its claims, or raise ``AuthError``.

    Checks, in order: a well-formed RS256 JWT whose ``kid`` names one of
    Google's current certificates (refetched once on a miss, for key
    rotation); the signature; ``aud`` equal to our client id; ``iat``/``exp``
    within the clock skew; ``iss`` one of Google's two issuers; a ``sub``; and
    ``email_verified`` true."""
    from google.auth import exceptions as google_exceptions
    from google.auth import jwt as google_jwt

    certs = certs or CERTS
    if not isinstance(token, str) or not token or len(token) > 8192:
        raise AuthError("malformed")
    try:
        kid = _header_kid(token)
    except Exception as exc:            # noqa: BLE001 - any parse failure is one answer
        raise AuthError("malformed") from exc
    current = certs.get()
    if kid is not None and kid not in current:
        current = certs.get(force=True)
    try:
        claims = google_jwt.decode(token, certs=current, audience=audience,
                                   clock_skew_in_seconds=CLOCK_SKEW_SECONDS)
    except google_exceptions.InvalidValue as exc:
        text = str(exc).lower()
        if "expired" in text or "too early" in text or "iat" in text:
            raise AuthError("expired") from exc
        if "audience" in text:
            raise AuthError("bad_audience") from exc
        raise AuthError("invalid") from exc
    except google_exceptions.GoogleAuthError as exc:
        raise AuthError("bad_signature") from exc
    except Exception as exc:            # noqa: BLE001 - never leak a parser traceback
        raise AuthError("malformed") from exc
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise AuthError("bad_issuer")
    if claims.get("aud") != audience:
        raise AuthError("bad_audience")
    if not claims.get("sub"):
        raise AuthError("no_subject")
    verified = claims.get("email_verified")
    if verified is not True and verified != "true":
        raise AuthError("email_unverified")
    return dict(claims)


# ------------------------------------------------------------- rate limit
class RateLimiter:
    """``limit`` events per ``window`` seconds per key, in memory. One
    process serves everything, so there is nothing to share."""

    def __init__(self, limit: int = RATE_LIMIT, window: float = RATE_WINDOW):
        self.limit, self.window = limit, window
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str, now: float | None = None) -> bool:
        t = now if now is not None else time.time()
        q = self._hits.setdefault(key, deque())
        while q and q[0] <= t - self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(t)
        if len(self._hits) > 10000:        # bound memory under a wide scan
            for k in [k for k, v in self._hits.items() if not v or v[-1] <= t - self.window]:
                self._hits.pop(k, None)
        return True

    def reset(self) -> None:
        self._hits.clear()


LIMITER = RateLimiter()


def client_ip(request: Request) -> str:
    """Fly's proxy stamps the real client on ``Fly-Client-IP``; without a
    proxy the socket peer is the client."""
    forwarded = request.headers.get("fly-client-ip")
    if forwarded:
        return forwarded.strip()
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------- HTTP API
router = APIRouter(prefix="/api")


class GoogleLogin(BaseModel):
    credential: str
    nonce: str | None = None


def public_user(row: Mapping[str, Any]) -> dict:
    return {"name": row.get("name") or "", "email": row.get("email") or "",
            "picture": row.get("picture")}


def first_name(name: str | None) -> str:
    """The display-name default for a signed-in player who typed none."""
    if not name:
        return ""
    return name.strip().split()[0][:20] if name.strip() else ""


def _cookie_secure(request: Request) -> bool:
    return (request.url.hostname or "") not in LOCAL_HOSTS


def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
                        secure=_cookie_secure(request), samesite="lax", path="/")


def _clear_session_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(COOKIE, path="/", httponly=True,
                           secure=_cookie_secure(request), samesite="lax")


@router.get("/auth/config")
async def auth_config() -> dict:
    return {"google_client_id": client_id()}


@router.post("/auth/google")
async def auth_google(body: GoogleLogin, request: Request, response: Response) -> dict:
    audience = client_id()
    if audience is None:
        raise HTTPException(status_code=404, detail="Sign-in is not enabled.")
    if not LIMITER.allow(client_ip(request)):
        raise HTTPException(status_code=429, detail="Too many sign-in attempts; try again in a minute.")
    loop = asyncio.get_running_loop()
    try:
        claims = await loop.run_in_executor(None, verify_google_id_token, body.credential, audience)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=f"Sign-in rejected ({exc.reason}).") from exc
    if body.nonce is not None and claims.get("nonce") != body.nonce:
        raise HTTPException(status_code=401, detail="Sign-in rejected (nonce).")
    user = await STORE.run(STORE.upsert_user, claims)
    token = await STORE.run(STORE.create_session, user["id"])
    _set_session_cookie(response, request, token)
    return public_user(user)


@router.get("/me")
async def me(request: Request) -> dict:
    user = await STORE.run(STORE.session_user, request.cookies.get(COOKIE))
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in.")
    return public_user(user)


@router.post("/auth/logout")
async def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(COOKIE)
    if token:
        await STORE.run(STORE.delete_session, token)
    _clear_session_cookie(response, request)
    return {"ok": True}


async def websocket_user(ws: WebSocket) -> dict | None:
    """The signed-in user behind a websocket's ``sj_session`` cookie, or None.
    No cookie means no database access at all: a guest's handshake is
    unchanged. A storage error is logged and read as a guest, never a
    refused game."""
    token = ws.cookies.get(COOKIE)
    if not token:
        return None
    try:
        return await STORE.run(STORE.session_user, token)
    except Exception as exc:            # noqa: BLE001 - gameplay over identity
        log.warning("session lookup failed on websocket (%s)", type(exc).__name__)
        return None


def health() -> dict:
    """What ``/healthz`` shows: whether sign-in is on. No path, no counts."""
    return {"google_sign_in": client_id() is not None}


def register_accounts(app) -> None:
    app.include_router(router)
