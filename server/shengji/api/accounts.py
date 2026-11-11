"""Optional Google sign-in: ID-token verification, users and sessions in SQLite.

The feature is OFF unless ``GOOGLE_CLIENT_ID`` is set: the login endpoint then
answers 404 and ``/api/auth/config`` reports no client id, so the web app shows
no button. Guest play never touches this module beyond one cookie read on the
websocket handshake, and only when a ``sj_session`` cookie is present.

Trust boundary: the browser posts a Google ID token (a JWT the Google Identity
Services button handed it, or, in the iOS app, the native Google sign-in). The
server verifies the RS256 signature against Google's published certificates,
the issuer, the audience (our web client id, or an iOS client id listed in
``GOOGLE_IOS_CLIENT_IDS``), the validity window and ``email_verified`` before
it will mint a session. The session token is 32 random bytes; the database
stores only its SHA-256, so a copy of the database cannot be replayed as a
login. No client secret exists anywhere: client ids are public by design.

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
import unicodedata
import urllib.request
from collections import deque
from contextlib import closing
from collections.abc import Callable, Collection, Mapping
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
# A chosen display name: 1..20 characters after trimming and collapsing
# whitespace runs; any script, no control characters, no line breaks.
DISPLAY_NAME_MAX = 20
# Names a player may not take because the server or the game uses them: the
# bots are seated as "Bot N" (server.py), the chat's system line speaks as
# the system, and the rest read as staff. Compared case-insensitively on the
# normalised name.
RESERVED_NAMES = frozenset({"bot", "system", "admin", "dealer", "moderator", "server"})
BOT_NAME_RE = re.compile(r"^bot\s*\d*$")
# Unicode categories a display name may not contain: control characters
# (which includes every line break), surrogates, private use, and the line
# and paragraph separators.
_FORBIDDEN_CATEGORIES = frozenset({"Cc", "Cs", "Co", "Zl", "Zp"})
# Hook for a profanity or block-list check: a callable taking the normalised
# name and returning True when it must be refused (reason ``not_allowed``).
# None means no such filter is installed.
DISPLAY_NAME_BLOCKLIST: Callable[[str], bool] | None = None


class AuthError(Exception):
    """A token that must not become a session; ``reason`` is a short code that
    is safe to return to the browser and never carries token material."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class DisplayNameError(ValueError):
    """A display name the server will not store; ``reason`` is one of
    ``empty``, ``too_long``, ``control_chars``, ``reserved``, ``not_allowed``
    or ``not_a_string``, safe to return to the browser."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def normalise_display_name(raw: str) -> str:
    """Trim and collapse every whitespace run to one space."""
    return " ".join(raw.split())


def validate_display_name(raw: Any) -> str:
    """The stored form of a requested display name, or ``DisplayNameError``.

    Order: a string; no forbidden character anywhere in the raw text (a line
    break is refused, not collapsed away); then trimmed and whitespace-
    collapsed; 1..``DISPLAY_NAME_MAX`` characters; not a reserved or bot-like
    name; and not refused by ``DISPLAY_NAME_BLOCKLIST`` when one is set."""
    if not isinstance(raw, str):
        raise DisplayNameError("not_a_string")
    if len(raw) > 1000:
        raise DisplayNameError("too_long")
    if any(unicodedata.category(ch) in _FORBIDDEN_CATEGORIES for ch in raw):
        raise DisplayNameError("control_chars")
    name = normalise_display_name(raw)
    if not name:
        raise DisplayNameError("empty")
    if len(name) > DISPLAY_NAME_MAX:
        raise DisplayNameError("too_long")
    folded = name.casefold()
    if folded in RESERVED_NAMES or BOT_NAME_RE.match(folded):
        raise DisplayNameError("reserved")
    if DISPLAY_NAME_BLOCKLIST is not None and DISPLAY_NAME_BLOCKLIST(name):
        raise DisplayNameError("not_allowed")
    return name


# ----------------------------------------------------------------- config
def client_id() -> str | None:
    """The configured Google OAuth client id, or None when sign-in is off.
    Read per request so a test (or a restart) can turn the feature on or off."""
    value = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    return value or None


def accepted_audiences() -> tuple[str, ...]:
    """The ``aud`` values a login token may carry: the web client id, then any
    native-app client ids in the comma-separated ``GOOGLE_IOS_CLIENT_IDS``.
    Empty when sign-in is off, whatever the iOS list says."""
    web = client_id()
    if web is None:
        return ()
    native = (part.strip() for part in os.environ.get("GOOGLE_IOS_CLIENT_IDS", "").split(","))
    return tuple(dict.fromkeys([web, *(part for part in native if part)]))


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
def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    """``ALTER TABLE ADD COLUMN`` is not idempotent in SQLite; checking the
    table first lets a migration re-run (an interrupted first run, a
    database whose version row was lost) without failing."""
    present = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in present:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def _migrate_v2(conn: sqlite3.Connection) -> None:
    _add_column_if_missing(conn, "users", "display_name", "TEXT NULL")


_USERS_V3 = """
    CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        google_sub TEXT NOT NULL UNIQUE,
        email TEXT,
        name TEXT,
        picture TEXT,
        created_at INTEGER NOT NULL,
        last_login_at INTEGER NOT NULL,
        display_name TEXT NULL
    )"""
_SESSIONS_V3 = """
    CREATE TABLE sessions_v3 (
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL
    )"""
# The room log stays the source of truth; these tables hold only which
# account sat where, for which rounds, and a small summary, so no log record
# ever carries an account id.
_GAMES_V3 = """
    CREATE TABLE IF NOT EXISTS games (
        id TEXT PRIMARY KEY,
        room_code TEXT NOT NULL,
        log_file TEXT NOT NULL,
        log_offset INTEGER NULL,
        started_at INTEGER NOT NULL,
        last_round INTEGER NOT NULL DEFAULT 1,
        ended_at INTEGER NULL,
        final_levels TEXT NULL,
        games_won TEXT NULL,
        incomplete INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS games_started ON games(started_at);
    CREATE TABLE IF NOT EXISTS game_players (
        game_id TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        seat INTEGER NOT NULL,
        from_round INTEGER NOT NULL,
        to_round INTEGER NULL,
        hidden INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (game_id, user_id, seat, from_round)
    );
    CREATE INDEX IF NOT EXISTS game_players_user ON game_players(user_id, game_id)
"""


def _users_autoincrement(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
    return row is not None and "AUTOINCREMENT" in row["sql"].upper()


def _migrate_v3(conn: sqlite3.Connection) -> None:
    """Rebuild ``users`` with ``AUTOINCREMENT`` so a deleted account's id is
    never handed to a later signup (a live seat or socket may still hold the
    old id), then add the saved-games tables.

    SQLite cannot add ``AUTOINCREMENT`` in place, and ``PRAGMA foreign_keys``
    cannot change inside the migration's transaction, so the rebuild never
    deletes a referenced ``users`` row: the old table is renamed first
    (``sessions`` now references the renamed table), the new ``users`` and a
    new ``sessions`` are filled from the old rows with their ids, and only then
    are the old tables dropped, sessions first. Every user, id and session is
    kept; the sequence starts at the largest kept id. A re-run on an
    already-rebuilt table only re-creates what is missing."""
    _add_column_if_missing(conn, "users", "display_name", "TEXT NULL")
    if not _users_autoincrement(conn):
        conn.execute("ALTER TABLE users RENAME TO users_v2")
        conn.execute(_USERS_V3)
        conn.execute(
            """INSERT INTO users(id, google_sub, email, name, picture, created_at,
                                 last_login_at, display_name)
               SELECT id, google_sub, email, name, picture, created_at,
                      last_login_at, display_name FROM users_v2 ORDER BY id""")
        conn.execute(_SESSIONS_V3)
        conn.execute(
            """INSERT INTO sessions_v3(token_hash, user_id, created_at, expires_at)
               SELECT token_hash, user_id, created_at, expires_at FROM sessions""")
        conn.execute("DROP TABLE sessions")
        conn.execute("DROP TABLE users_v2")
        conn.execute("ALTER TABLE sessions_v3 RENAME TO sessions")
        conn.execute("CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS sessions_expires ON sessions(expires_at)")
    for statement in filter(None, (s.strip() for s in _GAMES_V3.split(";"))):
        conn.execute(statement)
    problems = conn.execute("PRAGMA foreign_key_check").fetchall()
    if problems:
        raise sqlite3.IntegrityError(f"foreign key check failed after v3: {len(problems)} rows")


# Ratings (``ratings.py``): each user's current rating, how many rounds it
# rests on and whether they show on the leaderboard live on ``users``; every
# rated round adds one ``rating_events`` row per rated account, so stats and
# weekly deltas are derived rather than stored twice.
_RATINGS_V4 = """
    CREATE TABLE IF NOT EXISTS rating_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id TEXT NOT NULL,
        round_no INTEGER NOT NULL,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at INTEGER NOT NULL,
        team INTEGER NOT NULL,
        banker_team INTEGER NOT NULL,
        won INTEGER NOT NULL,
        levels INTEGER NOT NULL,
        game_won INTEGER NOT NULL DEFAULT 0,
        abandoned INTEGER NOT NULL DEFAULT 0,
        expected REAL NOT NULL,
        actual REAL NOT NULL,
        k REAL NOT NULL,
        rating_before REAL NOT NULL,
        rating_after REAL NOT NULL,
        delta REAL NOT NULL,
        partner TEXT NULL,
        partner_bot INTEGER NOT NULL DEFAULT 0,
        opponents_bots INTEGER NOT NULL DEFAULT 0,
        UNIQUE (game_id, round_no, user_id)
    );
    CREATE INDEX IF NOT EXISTS rating_events_user ON rating_events(user_id, created_at);
    CREATE INDEX IF NOT EXISTS rating_events_created ON rating_events(created_at)
"""


def _migrate_v4(conn: sqlite3.Connection) -> None:
    """Add the rating columns and the per-round rating log. Every step checks
    or uses ``IF NOT EXISTS``, so a re-run on a database that already has
    them changes nothing."""
    _add_column_if_missing(conn, "users", "rating", "REAL NOT NULL DEFAULT 1500")
    _add_column_if_missing(conn, "users", "rated_rounds", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "users", "leaderboard_visible", "INTEGER NOT NULL DEFAULT 1")
    for statement in filter(None, (s.strip() for s in _RATINGS_V4.split(";"))):
        conn.execute(statement)


# Each entry is one version: SQL statements separated by ';', or a callable
# taking the connection. Entry i brings the database to version i + 1.
SCHEMA: list[str | Callable[[sqlite3.Connection], None]] = [
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
    # version 2: a player-chosen display name; NULL means "use the Google
    # first name".
    _migrate_v2,
    # version 3: account ids that are never reused, and saved games.
    _migrate_v3,
    # version 4: player ratings and the leaderboard opt-out.
    _migrate_v4,
]

# Saved games: kept for twelve months; the history list shows the latest
# ``GAMES_LIST_CAP`` of them.
GAMES_RETENTION_SECONDS = 365 * 86400
GAMES_LIST_CAP = 100


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


class Store:
    """Users, sessions and saved-game links in one SQLite file. Every public method is
    synchronous and opens its own connection; ``run`` moves one onto a
    worker thread for use from the event loop."""

    def __init__(self, path: Path | None = None):
        self._path = Path(path) if path is not None else None
        self._ready = False
        self._lock = threading.Lock()
        # Ids deleted through ``DELETE /api/me`` since this process started.
        self.deleted_ids: set[int] = set()

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
                    step = SCHEMA[i]
                    if callable(step):
                        step(conn)
                    else:
                        for statement in filter(None, (s.strip() for s in step.split(";"))):
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

    def set_display_name(self, user_id: int, name: str | None) -> dict | None:
        """Store an already-validated display name (None clears it back to
        the Google first name); returns the updated row, or None for an
        unknown user."""
        with closing(self._open()) as conn:
            conn.execute("UPDATE users SET display_name = ? WHERE id = ?", (name, user_id))
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

    # -- saved games
    def link_seat(self, game: Mapping[str, Any], user_id: int, seat: int,
                  from_round: int) -> bool:
        """Open a link from ``from_round`` on for one account at one seat.

        ``game`` is the header the room holds (``id``, ``room_code``,
        ``log_file``, ``log_offset``, ``started_at``, ``last_round``,
        ``incomplete``); the ``games`` row is created by the first link, so
        a game nobody signed in to never reaches the database. An account
        deleted while its seat is still live links nothing. Returns whether
        a link row is open afterwards."""
        with closing(self._open()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                if conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone() is None:
                    conn.execute("COMMIT")
                    return False
                conn.execute(
                    """INSERT INTO games(id, room_code, log_file, log_offset, started_at,
                                         last_round, incomplete)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(id) DO NOTHING""",
                    (game["id"], game["room_code"], game["log_file"], game["log_offset"],
                     int(game["started_at"]), int(game.get("last_round") or 1),
                     1 if game.get("incomplete") else 0))
                conn.execute(
                    """INSERT INTO game_players(game_id, user_id, seat, from_round, to_round)
                       VALUES (?, ?, ?, ?, NULL)
                       ON CONFLICT(game_id, user_id, seat, from_round)
                       DO UPDATE SET to_round = NULL""",
                    (game["id"], user_id, seat, from_round))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return True

    def close_link(self, game_id: str, user_id: int, seat: int, to_round: int) -> int:
        """Close the open link of one account at one seat after ``to_round``;
        returns the number of rows closed."""
        with closing(self._open()) as conn:
            cur = conn.execute(
                """UPDATE game_players SET to_round = ?
                   WHERE game_id = ? AND user_id = ? AND seat = ? AND to_round IS NULL""",
                (to_round, game_id, user_id, seat))
            return cur.rowcount

    def record_round_start(self, game_id: str, round_no: int) -> None:
        with closing(self._open()) as conn:
            conn.execute("UPDATE games SET last_round = MAX(last_round, ?) WHERE id = ?",
                         (round_no, game_id))

    def record_round_end(self, game_id: str, round_no: int, final_levels: Any,
                         games_won: Any, now: float | None = None) -> None:
        t = int(now if now is not None else time.time())
        with closing(self._open()) as conn:
            conn.execute(
                """UPDATE games SET last_round = MAX(last_round, ?), ended_at = ?,
                       final_levels = ?, games_won = ? WHERE id = ?""",
                (round_no, t, json.dumps(final_levels), json.dumps(games_won), game_id))

    def mark_incomplete(self, game_id: str) -> None:
        with closing(self._open()) as conn:
            conn.execute("UPDATE games SET incomplete = 1 WHERE id = ?", (game_id,))

    @staticmethod
    def _game_dict(row: sqlite3.Row) -> dict:
        game = dict(row)
        for key in ("final_levels", "games_won"):
            game[key] = json.loads(game[key]) if game[key] is not None else None
        game["incomplete"] = bool(game["incomplete"]) or game["log_offset"] is None
        return game

    def list_games(self, user_id: int, before: tuple[int, str] | None = None,
                   limit: int = 50, now: float | None = None) -> list[dict]:
        """The account's visible games, newest first by ``(started_at, id)``:
        within retention, not hidden, among its latest ``GAMES_LIST_CAP``, and
        strictly after the cursor ``before`` in that order when given (a
        ``(started_at, id)`` pair, see ``game_cursor``), so games that share a
        start second are neither skipped nor repeated across pages. Each game
        carries its ``links`` (seat, from_round, to_round) for the account."""
        t = int(now if now is not None else time.time())
        with closing(self._open()) as conn:
            rows = conn.execute(
                """SELECT g.* FROM games g
                   WHERE g.started_at >= ? AND EXISTS (
                       SELECT 1 FROM game_players p
                       WHERE p.game_id = g.id AND p.user_id = ? AND p.hidden = 0)
                   ORDER BY g.started_at DESC, g.id DESC LIMIT ?""",
                (t - GAMES_RETENTION_SECONDS, user_id, GAMES_LIST_CAP)).fetchall()
            games = [self._game_dict(r) for r in rows
                     if before is None
                     or (r["started_at"], r["id"]) < (int(before[0]), str(before[1]))
                     ][:max(0, limit)]
            for game in games:
                game["links"] = self._links(conn, game["id"], user_id)
            return games

    @staticmethod
    def game_cursor(game: Mapping[str, Any]) -> str:
        """The paging cursor that lists the games after ``game``: an opaque
        ``"<started_at>:<id>"`` string to clients."""
        return f"{int(game['started_at'])}:{game['id']}"

    @staticmethod
    def parse_game_cursor(raw: str) -> tuple[int, str]:
        """``"<started_at>:<id>"`` as ``(started_at, id)``. A bare integer is
        read as ``(started_at, "")``: every game started before that second.
        Anything else raises ``ValueError``."""
        stamp, sep, game_id = raw.partition(":")
        if not stamp.isdigit() or len(stamp) > 12 or len(game_id) > 64:
            raise ValueError("bad cursor")
        if sep and not re.fullmatch(r"[0-9A-Za-z_-]+", game_id):
            raise ValueError("bad cursor")
        return int(stamp), game_id

    def user_game(self, user_id: int, game_id: str, now: float | None = None) -> dict | None:
        """One game with the account's links, or None when the account has
        no visible link to it (unknown, someone else's, hidden or past
        retention all read the same)."""
        t = int(now if now is not None else time.time())
        with closing(self._open()) as conn:
            row = conn.execute("SELECT * FROM games WHERE id = ? AND started_at >= ?",
                               (game_id, t - GAMES_RETENTION_SECONDS)).fetchone()
            if row is None:
                return None
            links = self._links(conn, game_id, user_id)
            if not links:
                return None
            game = self._game_dict(row)
            game["links"] = links
            return game

    @staticmethod
    def _links(conn: sqlite3.Connection, game_id: str, user_id: int) -> list[dict]:
        return [dict(r) for r in conn.execute(
            """SELECT seat, from_round, to_round FROM game_players
               WHERE game_id = ? AND user_id = ? AND hidden = 0
               ORDER BY from_round, seat""", (game_id, user_id))]

    def hide_game(self, user_id: int, game_id: str) -> int:
        """Hide a game from one account; returns the rows hidden (0 when the
        account had no visible link)."""
        with closing(self._open()) as conn:
            return conn.execute(
                "UPDATE game_players SET hidden = 1 WHERE game_id = ? AND user_id = ? AND hidden = 0",
                (game_id, user_id)).rowcount

    def purge_games(self, now: float | None = None) -> int:
        """Delete games past retention (their links go by cascade) and games
        no account links any more; returns the games deleted."""
        t = int(now if now is not None else time.time())
        with closing(self._open()) as conn:
            return conn.execute(
                """DELETE FROM games WHERE started_at < ? OR NOT EXISTS (
                       SELECT 1 FROM game_players p WHERE p.game_id = games.id)""",
                (t - GAMES_RETENTION_SECONDS,)).rowcount

    def delete_user(self, user_id: int) -> bool:
        """Remove a user; its sessions and game links go by cascade, and so
        do the games no other account links. The anonymous room logs are
        untouched: they never held the account."""
        with closing(self._open()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                gone = conn.execute("DELETE FROM users WHERE id = ?", (user_id,)).rowcount
                conn.execute(
                    """DELETE FROM games WHERE NOT EXISTS (
                           SELECT 1 FROM game_players p WHERE p.game_id = games.id)""")
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return gone > 0

    async def run(self, fn: Callable[..., Any], *args: Any) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, fn, *args)


STORE = Store()


# ------------------------------------------------------ Google certificates
class GoogleCerts:
    """Google's current signing certificates, cached until their
    ``Cache-Control: max-age`` runs out (an hour when the header is missing).

    Refreshes are SINGLE-FLIGHT and BOUNDED: one fetch at a time, run outside
    the lock so other threads keep serving the cached set; a forced refresh
    (an unknown ``kid``, which any anonymous caller can present) happens at
    most once per ``REFRESH_COOLDOWN`` seconds, and after a failure the next
    attempt waits ``FAIL_BACKOFF`` doubling up to ``FAIL_BACKOFF_MAX``. A
    failure keeps serving the last good set. Legitimate key rotation still
    works: the first unknown kid after rotation triggers the one refresh.
    """

    REFRESH_COOLDOWN = 60.0
    FAIL_BACKOFF = 30.0
    FAIL_BACKOFF_MAX = 600.0
    COLD_WAIT = 10.0

    def __init__(self, fetch: Callable[[], tuple[dict, float]] | None = None,
                 clock: Callable[[], float] | None = None):
        self._fetch = fetch or self._fetch_http
        self._clock = clock or time.time
        self._certs: dict[str, str] = {}
        self._expires = 0.0
        self._next_refresh = 0.0       # no refresh before this instant
        self._fail_backoff = self.FAIL_BACKOFF
        self._refreshing = False
        self._cond = threading.Condition(threading.Lock())
        self.fetches = 0

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
        """The cached set, refreshed when expired or when ``force`` asks and
        the cooldown allows. Returns the (possibly stale) cached set whenever
        another thread is already refreshing or the bound says no; raises
        ``certs_unavailable`` only when there is no set at all."""
        with self._cond:
            now = self._clock()
            stale = not self._certs or now >= self._expires
            wanted = stale or force
            allowed = now >= self._next_refresh
            if not wanted or not allowed or self._refreshing:
                if self._certs:
                    return self._certs
                if self._refreshing:
                    # cold start under contention: wait for the one in flight
                    self._cond.wait_for(lambda: not self._refreshing, timeout=self.COLD_WAIT)
                    if self._certs:
                        return self._certs
                raise AuthError("certs_unavailable")
            self._refreshing = True
        try:
            certs, ttl = self._fetch()
        except Exception as exc:          # noqa: BLE001 - keep the last good set
            with self._cond:
                now = self._clock()
                self._next_refresh = now + self._fail_backoff
                self._fail_backoff = min(self._fail_backoff * 2, self.FAIL_BACKOFF_MAX)
                self._refreshing = False
                self._cond.notify_all()
                if self._certs:
                    log.warning("google certs refresh failed (%s); using cached set",
                                type(exc).__name__)
                    return self._certs
            raise AuthError("certs_unavailable") from exc
        with self._cond:
            now = self._clock()
            self.fetches += 1
            self._certs, self._expires = dict(certs), now + max(60.0, ttl)
            self._next_refresh = now + self.REFRESH_COOLDOWN
            self._fail_backoff = self.FAIL_BACKOFF
            self._refreshing = False
            self._cond.notify_all()
            return self._certs

    def reset(self) -> None:
        with self._cond:
            self._certs, self._expires, self._next_refresh = {}, 0.0, 0.0
            self._fail_backoff = self.FAIL_BACKOFF


CERTS = GoogleCerts()


def _header_kid(token: str) -> str | None:
    from google.auth import jwt as google_jwt
    header, _payload, _signed, _sig = google_jwt._unverified_decode(token)  # noqa: SLF001
    kid = header.get("kid")
    return str(kid) if kid else None


def verify_google_id_token(token: str, audience: str | Collection[str],
                           certs: GoogleCerts | None = None) -> dict:
    """Verify a Google ID token and return its claims, or raise ``AuthError``.

    Checks, in order: a well-formed RS256 JWT whose ``kid`` names one of
    Google's current certificates (a miss asks for one bounded refresh, for
    key rotation; see ``GoogleCerts``); the signature; ``aud`` one of our client
    ids (``audience``: one id or several); ``iat``/``exp`` within the clock skew; ``iss`` one of Google's two issuers; a ``sub``; and
    ``email_verified`` true."""
    from google.auth import exceptions as google_exceptions
    from google.auth import jwt as google_jwt

    certs = certs or CERTS
    audiences = (audience,) if isinstance(audience, str) else tuple(audience)
    if not audiences:
        raise AuthError("bad_audience")
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
        claims = google_jwt.decode(token, certs=current, audience=list(audiences),
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
    if claims.get("aud") not in audiences:
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


class DisplayNamePatch(BaseModel):
    display_name: str | None = None


def first_name(name: str | None) -> str:
    """The default for a player who chose no display name: the first word of
    the Google name."""
    if not name:
        return ""
    return name.strip().split()[0][:DISPLAY_NAME_MAX] if name.strip() else ""


def effective_name(row: Mapping[str, Any]) -> str:
    """What a signed-in player is called when they type no name in the
    room: the chosen display name, else the Google first name."""
    return row.get("display_name") or first_name(row.get("name"))


def public_user(row: Mapping[str, Any]) -> dict:
    """The ``/api/me`` payload: the Google profile, the chosen display name
    (null when none) and ``name_shown``, the effective name."""
    return {"name": row.get("name") or "", "email": row.get("email") or "",
            "picture": row.get("picture"), "display_name": row.get("display_name"),
            "name_shown": effective_name(row)}


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
    audiences = accepted_audiences()
    if not audiences:
        raise HTTPException(status_code=404, detail="Sign-in is not enabled.")
    if not LIMITER.allow(client_ip(request)):
        raise HTTPException(status_code=429, detail="Too many sign-in attempts; try again in a minute.")
    loop = asyncio.get_running_loop()
    try:
        claims = await loop.run_in_executor(None, verify_google_id_token, body.credential, audiences)
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


@router.patch("/me")
async def patch_me(body: DisplayNamePatch, request: Request) -> dict:
    """Set (or, with null, clear) the display name. Shares the sign-in
    endpoint's per-IP budget: an anonymous caller spends a session lookup
    here, and a signed-in one a write."""
    if not LIMITER.allow(client_ip(request)):
        raise HTTPException(status_code=429, detail="Too many changes; try again in a minute.")
    user = await STORE.run(STORE.session_user, request.cookies.get(COOKIE))
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in.")
    name: str | None = None
    if body.display_name is not None:
        try:
            name = validate_display_name(body.display_name)
        except DisplayNameError as exc:
            raise HTTPException(status_code=400, detail=exc.reason) from exc
    updated = await STORE.run(STORE.set_display_name, user["id"], name)
    if updated is None:
        raise HTTPException(status_code=401, detail="Not signed in.")
    return public_user(updated)


# Called on the event loop with the id, before the row is deleted: the game
# server detaches the id from every live seat.
USER_DELETED_HOOKS: list[Callable[[int], None]] = []


def is_deleted(user_id: int) -> bool:
    """Whether the account was deleted while this process runs: a socket
    opened before the delete still holds the id and reads as signed out."""
    return user_id in STORE.deleted_ids


@router.delete("/me", status_code=204)
async def delete_me(request: Request) -> Response:
    """Delete the account: the user row, its sessions and its saved-game
    links (by cascade). Live seats and open sockets holding the account are
    detached first, so nothing links the id afterwards (ids are never
    reused, schema v3). The anonymous room logs never held the account and
    are unchanged."""
    if not LIMITER.allow(client_ip(request)):
        raise HTTPException(status_code=429, detail="Too many changes; try again in a minute.")
    user = await STORE.run(STORE.session_user, request.cookies.get(COOKIE))
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in.")
    STORE.deleted_ids.add(int(user["id"]))
    for hook in USER_DELETED_HOOKS:
        try:
            hook(int(user["id"]))
        except Exception:           # noqa: BLE001 - the delete still happens
            log.exception("account-deletion hook failed")
    await STORE.run(STORE.delete_user, user["id"])
    response = Response(status_code=204)
    _clear_session_cookie(response, request)
    return response


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
    cookies = getattr(ws, "cookies", None) or {}   # a socket without a cookie jar is a guest
    token = cookies.get(COOKIE)
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
