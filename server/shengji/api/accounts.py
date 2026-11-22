"""Optional Google sign-in: ID-token verification, users and sessions in SQLite.

Sign in with Apple (the iOS app only) lives in ``apple_auth``; its accounts
share the ``users`` table, keyed by ``apple_sub`` instead of ``google_sub``.
Device accounts (the iOS app only, ``POST /api/auth/device``, off unless
``SHENGJI_DEVICE_ACCOUNTS=1``) are ``users`` rows with neither, held by a
device credential.

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
login. No Google client secret exists anywhere: client ids are public by design.

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
import random
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

from . import chat_filter, device_names

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
# A new account's rating; ``ratings.START_RATING`` reads it from here. The
# ``users.rating`` column default predates the 1000 scale, so every insert
# sets the rating itself.
START_RATING = 1000.0
# The schema v5 scale move: every stored absolute rating drops by this much.
RATING_SCALE_SHIFT = 500.0
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
# The profanity check: a callable taking the normalised name and returning
# True when it must be refused (reason ``not_allowed``); the chat filter's
# word list. None means no such filter is installed.
DISPLAY_NAME_BLOCKLIST: Callable[[str], bool] | None = chat_filter.contains
# Device accounts (``POST /api/auth/device``): accounts with no provider, for
# the iOS app only. Everything about them, and the unique-name rule on
# ``PATCH /api/me``, is off unless ``SHENGJI_DEVICE_ACCOUNTS=1``.
DEVICE_FLAG = "SHENGJI_DEVICE_ACCOUNTS"
DEVICE_AUTH_SCHEME = "Device"
# The header by which a client declares itself the iOS app, and the value it
# sends. A soft gate: any HTTP client can send it. The web client never calls
# the endpoint, so web players stay guests; the header keeps a stray or older
# web caller from minting accounts.
CLIENT_HEADER = "X-Shengji-Client"
IOS_APP_CLIENT = "ios-app"
# New device accounts per address: per hour and per day. Over either, the
# endpoint answers 429 and the app plays on as a guest.
DEVICE_CREATES_PER_HOUR = 5
DEVICE_CREATES_PER_DAY = 20
# A device account is purged when it has no rated round and nobody has used
# it (signed in with it, or used its credential) for ``DEVICE_UNRATED_DAYS``,
# so a player who only plays casual games is kept while they keep playing;
# any device account unused for ``DEVICE_IDLE_DAYS`` is purged too.
DEVICE_UNRATED_DAYS = 30
DEVICE_IDLE_DAYS = 365
# A device account's session use is written to ``users.last_seen_at`` at most
# this often; the purge adds it to its grace, so a throttled write never
# makes a used account look unused.
DEVICE_SEEN_EVERY = 3600
# Random draws before the name search walks the whole list.
NAME_DRAWS = 32
# Numbers tried on a new provider account's taken default name before it
# gets a generated name.
NUMBERED_TRIES = 1000
_NAME_RNG = random.SystemRandom()
# The ``users`` column holding each provider's subject.
PROVIDER_COLUMNS = {"google": "google_sub", "apple": "apple_sub"}


class AuthError(Exception):
    """A token that must not become a session; ``reason`` is a short code that
    is safe to return to the browser and never carries token material."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class DisplayNameError(ValueError):
    """A display name the server will not store; ``reason`` is one of
    ``empty``, ``too_long``, ``control_chars``, ``reserved``, ``not_allowed``,
    ``not_a_string`` or ``taken`` (another account shows it), safe to return
    to the browser."""

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


def device_accounts_enabled() -> bool:
    """Whether device accounts are on; read per request, like ``client_id``."""
    return os.environ.get(DEVICE_FLAG, "").strip() == "1"


def _free_device_name(taken: Collection[str], rng: random.Random) -> str:
    """An "Adjective Noun" name whose casefold is not in ``taken`` and that
    passes ``validate_display_name``: up to ``NAME_DRAWS`` random draws,
    then every name in a random order. ``DisplayNameError("taken")`` when
    none is free."""
    def usable(name: str) -> bool:
        if name.casefold() in taken:
            return False
        try:
            return validate_display_name(name) == name
        except DisplayNameError:
            return False

    for _ in range(NAME_DRAWS):
        name = f"{rng.choice(device_names.ADJECTIVES)} {rng.choice(device_names.NOUNS)}"
        if usable(name):
            return name
    names = device_names.all_names()
    rng.shuffle(names)
    for name in names:
        if usable(name):
            return name
    raise DisplayNameError("taken")


def _numbered_name(base: str, taken: Collection[str], rng: random.Random | None = None) -> str:
    """``base`` with the smallest number from 2 up whose result is not in
    ``taken`` (casefolded) and passes ``validate_display_name``, the base
    cut so the result fits ``DISPLAY_NAME_MAX``. A base that yields no such
    name within ``NUMBERED_TRIES`` (``Bot`` is reserved with any number)
    gets a free generated name instead."""
    for n in range(2, NUMBERED_TRIES + 2):
        suffix = f" {n}"
        candidate = base[:DISPLAY_NAME_MAX - len(suffix)].rstrip() + suffix
        if candidate.casefold() in taken:
            continue
        try:
            if validate_display_name(candidate) == candidate:
                return candidate
        except DisplayNameError:
            continue
    return _free_device_name(taken, rng or _NAME_RNG)


def _google_profile(claims: Mapping[str, Any]) -> tuple[str, Any, Any, Any]:
    """``(sub, email, name, picture)`` of verified Google claims; the name
    falls back to the given name, then the email's local part."""
    email = claims.get("email")
    name = claims.get("name") or claims.get("given_name") or (
        email.split("@")[0] if isinstance(email, str) else None)
    return str(claims["sub"]), email, name, claims.get("picture")


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


def _migrate_v5(conn: sqlite3.Connection) -> None:
    """Move the rating scale from 1500 to 1000: every account's rating and
    every absolute rating in ``rating_events`` (``rating_before``,
    ``rating_after``) drops by ``RATING_SCALE_SHIFT``, so gaps, deltas,
    expected and actual scores are unchanged. The ``rating_scale`` row marks
    the shift as done, so a re-run (a lost version row) never shifts twice."""
    done = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='rating_scale'").fetchone()
    if done:
        return
    conn.execute("CREATE TABLE rating_scale (start_rating REAL NOT NULL)")
    conn.execute("INSERT INTO rating_scale(start_rating) VALUES (?)", (START_RATING,))
    conn.execute("UPDATE users SET rating = rating - ?", (RATING_SCALE_SHIFT,))
    conn.execute(
        """UPDATE rating_events SET rating_before = rating_before - ?,
                                    rating_after = rating_after - ?""",
        (RATING_SCALE_SHIFT, RATING_SCALE_SHIFT))


# Accounts from Sign in with Apple: ``google_sub`` becomes nullable, an
# account carries ``apple_sub`` instead, and every row has at least one of
# the two. The same person through Google and through Apple is two accounts.
_USERS_V6 = """
    CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        google_sub TEXT NULL UNIQUE,
        email TEXT,
        name TEXT,
        picture TEXT,
        created_at INTEGER NOT NULL,
        last_login_at INTEGER NOT NULL,
        display_name TEXT NULL,
        rating REAL NOT NULL DEFAULT 1500,
        rated_rounds INTEGER NOT NULL DEFAULT 0,
        leaderboard_visible INTEGER NOT NULL DEFAULT 1,
        apple_sub TEXT NULL UNIQUE,
        CHECK (google_sub IS NOT NULL OR apple_sub IS NOT NULL)
    )"""
_USER_COLUMNS_V5 = ("id, google_sub, email, name, picture, created_at, last_login_at, "
                    "display_name, rating, rated_rounds, leaderboard_visible")
# The tables whose rows reference ``users``, rebuilt under a temporary name;
# each keeps its v3/v4 columns and constraints exactly.
_CHILDREN_V6 = {
    "sessions": """
        CREATE TABLE sessions_v6 (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL
        )""",
    "game_players": """
        CREATE TABLE game_players_v6 (
            game_id TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            seat INTEGER NOT NULL,
            from_round INTEGER NOT NULL,
            to_round INTEGER NULL,
            hidden INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (game_id, user_id, seat, from_round)
        )""",
    "rating_events": """
        CREATE TABLE rating_events_v6 (
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
        )""",
}
_INDEXES_V6 = """
    CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
    CREATE INDEX IF NOT EXISTS sessions_expires ON sessions(expires_at);
    CREATE INDEX IF NOT EXISTS game_players_user ON game_players(user_id, game_id);
    CREATE INDEX IF NOT EXISTS rating_events_user ON rating_events(user_id, created_at);
    CREATE INDEX IF NOT EXISTS rating_events_created ON rating_events(created_at)
"""
# The Apple refresh token of an account, kept only to revoke the grant when
# the account is deleted. It never leaves the server: no API returns it and
# no ``users`` row (which most code reads with ``SELECT *``) carries it.
_APPLE_TOKENS_V6 = """
    CREATE TABLE IF NOT EXISTS apple_tokens (
        user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        refresh_token TEXT NOT NULL,
        updated_at INTEGER NOT NULL
    )"""


def _sequence(conn: sqlite3.Connection, table: str) -> int:
    row = conn.execute("SELECT seq FROM sqlite_sequence WHERE name = ?", (table,)).fetchone()
    return int(row["seq"]) if row else 0


def _set_sequence(conn: sqlite3.Connection, table: str, floor: int) -> None:
    """Keep ``table``'s AUTOINCREMENT high-water mark at least ``floor``, so an
    id freed before a rebuild is not handed out after it."""
    current = _sequence(conn, table)
    if conn.execute("SELECT 1 FROM sqlite_sequence WHERE name = ?", (table,)).fetchone():
        conn.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = ?",
                     (max(current, floor), table))
    elif floor:
        conn.execute("INSERT INTO sqlite_sequence(name, seq) VALUES (?, ?)", (table, floor))


def _migrate_v7(conn: sqlite3.Connection) -> None:
    """Add ``users.suspended_at``: NULL for an account in good standing, else
    when an operator suspended it (``scripts/suspend_account.py``)."""
    _add_column_if_missing(conn, "users", "suspended_at", "INTEGER")


# One row per account a signed-in player blocked (``blocks.py``). Either
# account's deletion removes the row by cascade.
_BLOCKS_V8 = """
    CREATE TABLE IF NOT EXISTS blocks (
        blocker_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        blocked_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at INTEGER NOT NULL,
        PRIMARY KEY (blocker_id, blocked_id)
    ) WITHOUT ROWID;
    CREATE INDEX IF NOT EXISTS blocks_blocked ON blocks(blocked_id)
"""


def _migrate_v6(conn: sqlite3.Connection) -> None:
    """Rebuild ``users`` with a nullable ``google_sub``, an ``apple_sub`` and
    the at-least-one CHECK, and add ``apple_tokens``.

    The same constraints as v3 apply (``PRAGMA foreign_keys`` stays on inside
    the transaction, so no referenced ``users`` row may ever be deleted while
    a child still points at it, or its cascade would fire): the old table is
    renamed, which repoints ``sessions``, ``game_players`` and
    ``rating_events`` at the renamed table; the new ``users`` and a new copy
    of each child (referencing the new ``users``) are filled from the old rows
    with their ids; then the old children are dropped, the old ``users`` last,
    and the copies take the old names and indexes. Both AUTOINCREMENT
    high-water marks carry over, so no deleted account or rating-event id is
    reused. A re-run on an already-rebuilt table only re-creates what is
    missing."""
    present = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    if "apple_sub" not in present:
        users_seq = _sequence(conn, "users")
        events_seq = _sequence(conn, "rating_events")
        conn.execute("ALTER TABLE users RENAME TO users_v5")
        conn.execute(_USERS_V6)
        conn.execute(f"INSERT INTO users({_USER_COLUMNS_V5}) "
                     f"SELECT {_USER_COLUMNS_V5} FROM users_v5 ORDER BY id")
        for child, ddl in _CHILDREN_V6.items():
            conn.execute(ddl)
            conn.execute(f"INSERT INTO {child}_v6 SELECT * FROM {child}")
        for child in _CHILDREN_V6:
            conn.execute(f"DROP TABLE {child}")
        conn.execute("DROP TABLE users_v5")
        for child in _CHILDREN_V6:
            conn.execute(f"ALTER TABLE {child}_v6 RENAME TO {child}")
        _set_sequence(conn, "users", users_seq)
        _set_sequence(conn, "rating_events", events_seq)
    for statement in filter(None, (s.strip() for s in _INDEXES_V6.split(";"))):
        conn.execute(statement)
    conn.execute(_APPLE_TOKENS_V6)
    problems = conn.execute("PRAGMA foreign_key_check").fetchall()
    if problems:
        raise sqlite3.IntegrityError(f"foreign key check failed after v6: {len(problems)} rows")


# A saved game continued at a new table (``saved_games`` continuations): each
# continuation's room log, read from game round ``first_round`` on (its own
# round 1). The ``games`` row's own log holds the rounds before the first
# continuation, so a game never continued has no row here.
_SEGMENTS_V9 = """
    CREATE TABLE IF NOT EXISTS game_segments (
        game_id TEXT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
        first_round INTEGER NOT NULL,
        room_code TEXT NOT NULL,
        log_file TEXT NOT NULL,
        log_offset INTEGER NULL,
        PRIMARY KEY (game_id, first_round)
    ) WITHOUT ROWID
"""


# The v6 rule that every account has a provider; v10 drops it, so a device
# account (``POST /api/auth/device``) has neither ``google_sub`` nor
# ``apple_sub``.
_PROVIDER_CHECK_RE = re.compile(
    r",\s*CHECK\s*\(\s*google_sub\s+IS\s+NOT\s+NULL\s+OR\s+apple_sub\s+IS\s+NOT\s+NULL\s*\)",
    re.IGNORECASE)
_CREATE_TABLE_RE = re.compile(r'^\s*CREATE\s+TABLE\s+("?)(\w+)\1', re.IGNORECASE)
# A device account's credential: only the SHA-256 of the 256-bit token the
# app holds. Deleting the account deletes its credentials by cascade.
_DEVICE_CREDENTIALS_V10 = """
    CREATE TABLE IF NOT EXISTS device_credentials (
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at INTEGER NOT NULL,
        last_seen_at INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS device_credentials_user ON device_credentials(user_id)
"""


def _children_of_users(conn: sqlite3.Connection) -> list[str]:
    """Every table with a foreign key to ``users``, in ``sqlite_master`` order."""
    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY rowid")]
    return [t for t in tables if t != "users" and any(
        fk["table"] == "users" for fk in conn.execute(f"PRAGMA foreign_key_list({t})"))]


def _migrate_v10(conn: sqlite3.Connection) -> None:
    """Rebuild ``users`` without the provider CHECK, and add
    ``device_credentials``.

    The rebuild follows v6 (foreign keys stay on inside the transaction, so
    no referenced ``users`` row is ever deleted while a child still points at
    it): every child's and index's DDL is read first, ``users`` is renamed
    (which repoints the children at the renamed table), the new ``users`` is
    the old DDL minus the CHECK and is filled with every row and id, each
    child is copied into a twin made from its own DDL (so it references the
    new ``users``), the old children and then the old ``users`` are dropped,
    the twins take the old names and the indexes are re-created. Column
    order, constraints, ``WITHOUT ROWID`` and the AUTOINCREMENT high-water
    marks are kept. Then ``users.last_seen_at`` is added. A re-run on a table
    with no CHECK only re-creates what is missing."""
    users_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()["sql"]
    relaxed = _PROVIDER_CHECK_RE.sub("", users_sql)
    if relaxed != users_sql:
        children = _children_of_users(conn)
        ddl = {t: conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                               (t,)).fetchone()["sql"] for t in children}
        owners = [*children, "users"]
        indexes = [r["sql"] for r in conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL "
            f"AND tbl_name IN ({','.join('?' * len(owners))})", owners)]
        sequences = {r["name"]: int(r["seq"]) for r in conn.execute(
            "SELECT name, seq FROM sqlite_sequence")}
        conn.execute("ALTER TABLE users RENAME TO users_v9")
        conn.execute(relaxed)
        conn.execute("INSERT INTO users SELECT * FROM users_v9 ORDER BY id")
        for child in children:
            twin = _CREATE_TABLE_RE.sub(f"CREATE TABLE {child}_v10", ddl[child], count=1)
            conn.execute(twin)
            conn.execute(f"INSERT INTO {child}_v10 SELECT * FROM {child}")
        for child in children:
            conn.execute(f"DROP TABLE {child}")
        conn.execute("DROP TABLE users_v9")
        for child in children:
            conn.execute(f"ALTER TABLE {child}_v10 RENAME TO {child}")
        for statement in indexes:
            conn.execute(_CREATE_INDEX_RE.sub("CREATE INDEX IF NOT EXISTS ", statement, count=1))
        for table, seq in sequences.items():
            _set_sequence(conn, table, seq)
    for statement in filter(None, (s.strip() for s in _DEVICE_CREDENTIALS_V10.split(";"))):
        conn.execute(statement)
    # When a device account last used a session (``Store.session_account``).
    _add_column_if_missing(conn, "users", "last_seen_at", "INTEGER NULL")
    problems = conn.execute("PRAGMA foreign_key_check").fetchall()
    if problems:
        raise sqlite3.IntegrityError(f"foreign key check failed after v10: {len(problems)} rows")


_CREATE_INDEX_RE = re.compile(r"^\s*CREATE\s+INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?", re.IGNORECASE)


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
    # version 5: the rating scale moves from 1500 to 1000.
    _migrate_v5,
    # version 6: Sign in with Apple accounts.
    _migrate_v6,
    # version 7: operator account suspension.
    _migrate_v7,
    # version 8: the accounts a signed-in player blocked.
    _BLOCKS_V8,
    # version 9: the logs of a saved game's continuations.
    _SEGMENTS_V9,
    # version 10: device accounts (no provider) and their credentials.
    _migrate_v10,
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
    def upsert_user(self, claims: Mapping[str, Any], now: float | None = None,
                    unique_name: bool | None = None) -> dict:
        """Create or refresh the user for a verified token's claims; returns
        the stored row as a dict. With ``unique_name`` (default: device
        accounts on), a new account whose default name another account
        already shows is given a numbered display name (``_numbered_name``);
        an existing account is never renamed."""
        t = int(now if now is not None else time.time())
        sub, email, name, picture = _google_profile(claims)
        with closing(self._open()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                display = self._new_account_name(conn, "google_sub", sub, name, unique_name)
                conn.execute(
                    """INSERT INTO users(google_sub, email, name, picture, created_at,
                                         last_login_at, rating, display_name)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(google_sub) DO UPDATE SET
                           email = excluded.email,
                           name = COALESCE(excluded.name, users.name),
                           picture = COALESCE(excluded.picture, users.picture),
                           last_login_at = excluded.last_login_at""",
                    (sub, email, name, picture, t, t, START_RATING, display))
                row = conn.execute("SELECT * FROM users WHERE google_sub = ?", (sub,)).fetchone()
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            return dict(row)

    def upsert_apple_user(self, sub: str, email: str | None, name: str | None,
                          now: float | None = None, unique_name: bool | None = None) -> dict:
        """Create or refresh the account of a verified Apple identity. Apple
        sends the name only on the first authorization and may omit the email
        later, so a missing value keeps the stored one. ``unique_name`` as
        for ``upsert_user``."""
        t = int(now if now is not None else time.time())
        with closing(self._open()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                display = self._new_account_name(conn, "apple_sub", str(sub), name, unique_name)
                conn.execute(
                    """INSERT INTO users(apple_sub, email, name, picture, created_at,
                                         last_login_at, rating, display_name)
                       VALUES (?, ?, ?, NULL, ?, ?, ?, ?)
                       ON CONFLICT(apple_sub) DO UPDATE SET
                           email = COALESCE(excluded.email, users.email),
                           name = COALESCE(excluded.name, users.name),
                           last_login_at = excluded.last_login_at""",
                    (str(sub), email, name, t, t, START_RATING, display))
                row = conn.execute("SELECT * FROM users WHERE apple_sub = ?",
                                   (str(sub),)).fetchone()
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            return dict(row)

    def _new_account_name(self, conn: sqlite3.Connection, column: str, sub: str,
                          name: str | None, unique_name: bool | None) -> str | None:
        """The display name a new provider account starts with: None (its
        provider first name shows) unless names are unique and that first
        name is already shown by another account, then a numbered one. None
        for an existing account, which keeps its name."""
        if not (device_accounts_enabled() if unique_name is None else unique_name):
            return None
        if conn.execute(f"SELECT 1 FROM users WHERE {column} = ?", (sub,)).fetchone():
            return None
        shown = first_name(name)
        taken = self._shown_names(conn)
        if not shown or shown.casefold() not in taken:
            return None
        return _numbered_name(shown, taken)

    def set_apple_refresh_token(self, user_id: int, refresh_token: str,
                                now: float | None = None) -> None:
        t = int(now if now is not None else time.time())
        with closing(self._open()) as conn:
            conn.execute(
                """INSERT INTO apple_tokens(user_id, refresh_token, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(user_id) DO UPDATE SET
                       refresh_token = excluded.refresh_token, updated_at = excluded.updated_at""",
                (user_id, refresh_token, t))

    def apple_refresh_token(self, user_id: int) -> str | None:
        with closing(self._open()) as conn:
            row = conn.execute("SELECT refresh_token FROM apple_tokens WHERE user_id = ?",
                               (user_id,)).fetchone()
            return str(row["refresh_token"]) if row else None

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

    @staticmethod
    def _shown_names(conn: sqlite3.Connection, exclude_id: int | None = None) -> set[str]:
        """Every account's effective name, casefolded, but ``exclude_id``'s."""
        return {effective_name(dict(r)).casefold() for r in conn.execute(
            "SELECT id, display_name, name FROM users WHERE id IS NOT ?", (exclude_id,))}

    def set_unique_display_name(self, user_id: int, name: str | None) -> dict | None:
        """``set_display_name``, refusing with ``DisplayNameError("taken")`` a
        name another account shows (case-insensitively). Keeping one's own
        current name, in any case, is never refused, so an account whose name
        already collided keeps it. Clearing (None) is not checked."""
        with closing(self._open()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
                if row is None:
                    conn.execute("COMMIT")
                    return None
                if (name is not None
                        and name.casefold() != effective_name(dict(row)).casefold()
                        and name.casefold() in self._shown_names(conn, user_id)):
                    raise DisplayNameError("taken")
                conn.execute("UPDATE users SET display_name = ? WHERE id = ?", (name, user_id))
                row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            return dict(row)

    # -- device accounts
    def create_device_user(self, token: str, now: float | None = None,
                           rng: random.Random | None = None) -> dict:
        """Create a device account (no provider) holding ``token``'s
        credential, named with an unused generated name; returns the row.
        Only the token's SHA-256 is stored. Raises ``DisplayNameError("taken")``
        when every generated name is in use. ``create_device_account`` also
        starts the first session in the same transaction."""
        return self._create_device(token, now, rng, with_session=False)[0]

    def _create_device(self, token: str, now: float | None, rng: random.Random | None,
                       with_session: bool) -> tuple[dict, str | None]:
        t = int(now if now is not None else time.time())
        with closing(self._open()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                name = _free_device_name(self._shown_names(conn), rng or _NAME_RNG)
                cur = conn.execute(
                    """INSERT INTO users(google_sub, apple_sub, email, name, picture, created_at,
                                         last_login_at, display_name, rating)
                       VALUES (NULL, NULL, NULL, ?, NULL, ?, ?, ?, ?)""",
                    (name, t, t, name, START_RATING))
                user_id = int(cur.lastrowid)
                conn.execute(
                    """INSERT INTO device_credentials(token_hash, user_id, created_at, last_seen_at)
                       VALUES (?, ?, ?, ?)""", (_hash_token(token), user_id, t, t))
                row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
                session = self._insert_session(conn, user_id, t) if with_session else None
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            return dict(row), session

    def create_device_account(self, token: str, now: float | None = None,
                              rng: random.Random | None = None) -> tuple[dict, str]:
        """A new device account and its first session token, in one
        transaction."""
        row, session = self._create_device(token, now, rng, with_session=True)
        assert session is not None
        return row, session

    def device_sign_in(self, token: str | None,
                       now: float | None = None) -> tuple[dict, str | None] | None:
        """Sign in with a device credential, in one transaction: find the
        account, mark the credential seen and the account logged in, and
        start a session unless the account is suspended. Returns the row and
        the session token (None for a suspended account), or None when no
        account holds the credential, including one deleted a moment ago:
        a delete either commits first (None) or waits for this to commit."""
        if not token or not re.fullmatch(r"[A-Za-z0-9_-]{20,200}", token):
            return None
        t = int(now if now is not None else time.time())
        digest = _hash_token(token)
        with closing(self._open()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    """SELECT u.id FROM device_credentials d JOIN users u ON u.id = d.user_id
                       WHERE d.token_hash = ?""", (digest,)).fetchone()
                if row is None:
                    conn.execute("COMMIT")
                    return None
                user_id = int(row["id"])
                conn.execute("UPDATE device_credentials SET last_seen_at = ? WHERE token_hash = ?",
                             (t, digest))
                conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (t, user_id))
                user = dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())
                session = None if is_suspended(user) else self._insert_session(conn, user_id, t)
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            return user, session

    def link_provider(self, device_id: int, provider: str, sub: str,
                      profile: Mapping[str, Any], confirm: bool,
                      now: float | None = None) -> dict:
        """A signed-in device account signs in with a verified provider
        identity, decided and done in one transaction. Returns a dict whose
        ``outcome`` is one of:

        - ``not_device``: ``device_id`` is gone, suspended or already has a
          provider; nothing changed, and the caller signs in as usual.
        - ``linked``: no account held ``sub``, so it is written onto the
          device account, which keeps its id, name, rating, stats and games;
          ``user`` and a new ``session``.
        - ``suspended``: the account holding ``sub`` is suspended (``user``);
          nothing changed.
        - ``conflict``: another account holds ``sub`` and ``confirm`` is
          false; only that account's shown ``name``, nothing changed.
        - ``merged``: ``confirm`` was true. The account holding ``sub`` wins:
          the device account's game links (open ones closed at their game's
          latest round) and every block it made or that others placed on it
          move to it, then the device account is deleted with its rating,
          rating history, credentials and sessions. ``user`` (the winner,
          its profile refreshed), a new ``session``, and ``device_token``: a
          new device credential for the winner, returned this once, which
          the app keeps in place of the deleted one.

        ``profile`` holds the provider's ``email``, ``name`` and ``picture``;
        a missing value keeps the stored one."""
        column = PROVIDER_COLUMNS[provider]
        t = int(now if now is not None else time.time())
        email, name, picture = profile.get("email"), profile.get("name"), profile.get("picture")
        with closing(self._open()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                found = conn.execute("SELECT * FROM users WHERE id = ?", (device_id,)).fetchone()
                device = dict(found) if found is not None else None
                if device is None or not is_device_account(device) or is_suspended(device):
                    conn.execute("COMMIT")
                    return {"outcome": "not_device"}
                found = conn.execute(f"SELECT * FROM users WHERE {column} = ?", (sub,)).fetchone()
                target = dict(found) if found is not None else None
                if target is not None and is_suspended(target):
                    conn.execute("COMMIT")
                    return {"outcome": "suspended", "user": dict(target)}
                if target is not None and not confirm:
                    conn.execute("COMMIT")
                    return {"outcome": "conflict", "name": effective_name(target) or "Player"}
                user_id = device_id if target is None else int(target["id"])
                device_token = None
                if target is not None:
                    self._merge_device(conn, device_id, user_id)
                    device_token = secrets.token_urlsafe(32)
                    conn.execute(
                        """INSERT INTO device_credentials(token_hash, user_id, created_at,
                                                          last_seen_at) VALUES (?, ?, ?, ?)""",
                        (_hash_token(device_token), user_id, t, t))
                conn.execute(
                    f"""UPDATE users SET {column} = ?, email = COALESCE(?, email),
                            name = COALESCE(?, name), picture = COALESCE(?, picture),
                            last_login_at = ? WHERE id = ?""",
                    (sub, email, name, picture, t, user_id))
                user = dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())
                session = self._insert_session(conn, user_id, t)
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        if target is None:
            return {"outcome": "linked", "user": user, "session": session}
        return {"outcome": "merged", "user": user, "session": session,
                "device_token": device_token}

    @staticmethod
    def _merge_device(conn: sqlite3.Connection, device_id: int, target_id: int) -> None:
        """Move a device account's game links and its blocks, both the ones
        it made and the ones others placed on it, to ``target_id``, then
        delete it (caller holds the transaction). A link the target already
        has at the same game, seat and first round is kept as the target's;
        the device's copy goes with the row. A block that would be between
        the target and itself is dropped, and one the target already has is
        kept once."""
        conn.execute(
            """UPDATE game_players SET to_round = (
                   SELECT g.last_round FROM games g WHERE g.id = game_players.game_id)
               WHERE user_id = ? AND to_round IS NULL""", (device_id,))
        conn.execute("UPDATE OR IGNORE game_players SET user_id = ? WHERE user_id = ?",
                     (target_id, device_id))
        conn.execute(
            """INSERT OR IGNORE INTO blocks(blocker_id, blocked_id, created_at)
               SELECT ?, blocked_id, created_at FROM blocks
               WHERE blocker_id = ? AND blocked_id != ?""", (target_id, device_id, target_id))
        conn.execute(
            """INSERT OR IGNORE INTO blocks(blocker_id, blocked_id, created_at)
               SELECT blocker_id, ?, created_at FROM blocks
               WHERE blocked_id = ? AND blocker_id != ?""", (target_id, device_id, target_id))
        conn.execute("DELETE FROM users WHERE id = ?", (device_id,))
        conn.execute(
            """DELETE FROM games WHERE NOT EXISTS (
                   SELECT 1 FROM game_players p WHERE p.game_id = games.id)""")

    def sign_out(self, session: str | None, device_token: str | None = None) -> bool:
        """End a session and, when ``device_token`` is given, remove that
        device credential if it belongs to the session's account, in one
        transaction, so the device cannot sign straight back in with it.
        Refused (False, nothing changed) when the session's account is a
        device account with no provider: signing out would leave an account
        nobody can reach. True otherwise, an unknown session included."""
        if not session:
            return True
        digest = _hash_token(session)
        with closing(self._open()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    """SELECT s.user_id, u.google_sub, u.apple_sub FROM sessions s
                       JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?""",
                    (digest,)).fetchone()
                if row is not None and is_device_account(dict(row)):
                    conn.execute("COMMIT")
                    return False
                conn.execute("DELETE FROM sessions WHERE token_hash = ?", (digest,))
                if (row is not None and device_token
                        and re.fullmatch(r"[A-Za-z0-9_-]{20,200}", device_token)):
                    conn.execute(
                        "DELETE FROM device_credentials WHERE token_hash = ? AND user_id = ?",
                        (_hash_token(device_token), int(row["user_id"])))
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return True

    def purge_device_accounts(self, now: float | None = None) -> list[int]:
        """Delete the device accounts (no provider) that have no rated round
        and have been unused for ``DEVICE_UNRATED_DAYS``, or that have been
        unused for ``DEVICE_IDLE_DAYS``. An account's last use is the latest
        of its sign-in (``users.last_login_at``), its session use
        (``users.last_seen_at``, written at most every ``DEVICE_SEEN_EVERY``,
        which the cutoffs allow for) and its credential use
        (``device_credentials.last_seen_at``). An account with an unexpired
        session is never purged. Credentials, sessions, links and blocks go
        by cascade, and so do games no other account links. A linked
        account is never touched. Returns the ids, which also join
        ``deleted_ids`` so a live socket holding one reads as signed out."""
        t = int(now if now is not None else time.time())
        with closing(self._open()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                ids = [int(r["id"]) for r in conn.execute(
                    """SELECT id FROM (
                           SELECT id, rated_rounds,
                                  MAX(last_login_at, COALESCE(last_seen_at, 0),
                                      COALESCE((SELECT MAX(d.last_seen_at) FROM device_credentials d
                                                WHERE d.user_id = users.id), 0)) AS used
                           FROM users
                           WHERE google_sub IS NULL AND apple_sub IS NULL
                             AND NOT EXISTS (SELECT 1 FROM sessions s
                                             WHERE s.user_id = users.id AND s.expires_at > :now))
                       WHERE (rated_rounds = 0 AND used < :since) OR used < :idle""",
                    {"now": t,
                     "since": t - DEVICE_UNRATED_DAYS * 86400 - DEVICE_SEEN_EVERY,
                     "idle": t - DEVICE_IDLE_DAYS * 86400 - DEVICE_SEEN_EVERY})]
                for user_id in ids:
                    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
                if ids:
                    conn.execute(
                        """DELETE FROM games WHERE NOT EXISTS (
                               SELECT 1 FROM game_players p WHERE p.game_id = games.id)""")
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        self.deleted_ids.update(ids)
        return ids

    # -- sessions
    def create_session(self, user_id: int, now: float | None = None) -> str:
        """Mint a session token (returned once, never stored) and purge
        whatever sessions have expired."""
        t = int(now if now is not None else time.time())
        with closing(self._open()) as conn:
            return self._insert_session(conn, user_id, t)

    @staticmethod
    def _insert_session(conn: sqlite3.Connection, user_id: int, t: int) -> str:
        token = secrets.token_urlsafe(32)
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (t,))
        conn.execute(
            "INSERT INTO sessions(token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (_hash_token(token), user_id, t, t + SESSION_SECONDS))
        return token

    def session_user(self, token: str | None, now: float | None = None) -> dict | None:
        """The user behind a live session token, else None. A suspended
        account's sessions read as signed out wherever a session is used."""
        row = self.session_account(token, now)
        return None if row is None or is_suspended(row) else row

    def session_account(self, token: str | None, now: float | None = None) -> dict | None:
        """The account behind a live session token, suspended or not; only
        what tells a suspended player so reads this instead of ``session_user``."""
        if not token or not re.fullmatch(r"[A-Za-z0-9_-]{20,200}", token):
            return None
        t = int(now if now is not None else time.time())
        with closing(self._open()) as conn:
            row = conn.execute(
                """SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
                   WHERE s.token_hash = ? AND s.expires_at > ?""",
                (_hash_token(token), t)).fetchone()
            if row is None:
                return None
            user = dict(row)
            # A device account's use of a session is its activity for the
            # purge; accounts with a provider are never written here.
            if is_device_account(user) and (user.get("last_seen_at") or 0) <= t - DEVICE_SEEN_EVERY:
                conn.execute("UPDATE users SET last_seen_at = ? WHERE id = ?", (t, user["id"]))
                user["last_seen_at"] = t
            return user

    def delete_session(self, token: str | None) -> None:
        if not token:
            return
        with closing(self._open()) as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash_token(token),))

    # -- suspension
    def set_suspended(self, user_id: int, suspended: bool, now: float | None = None) -> dict | None:
        """Suspend (keeping the first suspension time) or unsuspend an account;
        returns the updated row, or None for an unknown id. Sessions, ratings
        and saved games are kept: a suspended account's sessions are refused
        on use, and unsuspending makes them good again until they expire."""
        t = int(now if now is not None else time.time())
        with closing(self._open()) as conn:
            if suspended:
                conn.execute("UPDATE users SET suspended_at = COALESCE(suspended_at, ?) WHERE id = ?",
                             (t, user_id))
            else:
                conn.execute("UPDATE users SET suspended_at = NULL WHERE id = ?", (user_id,))
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return dict(row) if row else None

    def users_by_email(self, email: str) -> list[dict]:
        """Every account with this email, case-insensitively (a Google and an
        Apple account can share one)."""
        with closing(self._open()) as conn:
            rows = conn.execute("SELECT * FROM users WHERE lower(email) = lower(?) ORDER BY id",
                                (email.strip(),)).fetchall()
            return [dict(r) for r in rows]

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
        a link row is open afterwards.

        A header with ``first_round`` above 1 is a continuation of the
        existing game ``id`` at a new table, whose log holds the game's rounds
        from ``first_round`` on: its first link binds that log to the game
        from that round (``_continue_game``). A continuation whose game is
        gone, or whose boundary was already rated, links nothing."""
        first_round = int(game.get("first_round") or 1)
        with closing(self._open()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                if conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone() is None:
                    conn.execute("COMMIT")
                    return False
                if first_round > 1:
                    if not self._continue_game(conn, game, first_round):
                        conn.execute("COMMIT")
                        return False
                else:
                    self._insert_game(conn, game)
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

    @staticmethod
    def _insert_game(conn: sqlite3.Connection, game: Mapping[str, Any]) -> None:
        conn.execute(
                    """INSERT INTO games(id, room_code, log_file, log_offset, started_at,
                                         last_round, incomplete)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(id) DO NOTHING""",
                    (game["id"], game["room_code"], game["log_file"], game["log_offset"],
                     int(game["started_at"]), int(game.get("last_round") or 1),
                     1 if game.get("incomplete") else 0))

    @staticmethod
    def _continue_game(conn: sqlite3.Connection, game: Mapping[str, Any],
                       first_round: int) -> bool:
        """Bind a continuation's log to the game from ``first_round`` on
        (caller holds the transaction). False when the game row no longer
        exists, or when a round from ``first_round`` on was already rated, so
        that boundary is not the game's any more.

        Another seat of the same table finds its own segment and changes
        nothing. A different table at the boundary (the first continuation
        there, or one replacing a table that never finished a round there:
        Continue resumes only after the latest finished round, so a table
        bound at or after it finished none) takes the boundary. Every later
        segment and every link opened from the boundary on are dropped, and
        each earlier link is closed before it, so no seat at another table
        reads this table's rounds."""
        gid = game["id"]
        if conn.execute("SELECT 1 FROM games WHERE id = ?", (gid,)).fetchone() is None:
            return False
        bound = conn.execute(
            """SELECT room_code, log_file, log_offset FROM game_segments
               WHERE game_id = ? AND first_round = ?""", (gid, first_round)).fetchone()
        if bound is not None and (bound["room_code"], bound["log_file"], bound["log_offset"]) == (
                game["room_code"], game["log_file"], game["log_offset"]):
            return True
        if conn.execute(
                """SELECT 1 FROM rating_events
                   WHERE (game_id = ? OR substr(game_id, 1, ?) = ?) AND round_no >= ? LIMIT 1""",
                (gid, len(gid) + 1, gid + "/", first_round)).fetchone() is not None:
            return False
        conn.execute("DELETE FROM game_segments WHERE game_id = ? AND first_round >= ?",
                     (gid, first_round))
        conn.execute(
            """INSERT INTO game_segments(game_id, first_round, room_code, log_file, log_offset)
               VALUES (?, ?, ?, ?, ?)""",
            (gid, first_round, game["room_code"], game["log_file"], game["log_offset"]))
        conn.execute("DELETE FROM game_players WHERE game_id = ? AND from_round >= ?",
                     (gid, first_round))
        conn.execute(
            """UPDATE game_players SET to_round = ?
               WHERE game_id = ? AND (to_round IS NULL OR to_round >= ?)""",
            (first_round - 1, gid, first_round))
        conn.execute(
            """UPDATE games SET last_round = MAX(last_round, ?),
                   incomplete = MAX(incomplete, ?) WHERE id = ?""",
            (int(game.get("last_round") or first_round),
             1 if game.get("incomplete") else 0, gid))
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

    def rounds_played(self, user_id: int) -> int:
        """Rounds the account has sat in: its saved-game rounds (each link's
        interval, an open one up to the game's last round started, hidden
        games included), or its rated rounds when those are more, since a
        purged game drops its links but not the rating count."""
        with closing(self._open()) as conn:
            rated = conn.execute("SELECT rated_rounds FROM users WHERE id = ?",
                                 (user_id,)).fetchone()
            linked = conn.execute(
                """SELECT COALESCE(SUM(MAX(0, MIN(COALESCE(p.to_round, g.last_round), g.last_round)
                                           - MAX(1, p.from_round) + 1)), 0) AS n
                   FROM game_players p JOIN games g ON g.id = p.game_id
                   WHERE p.user_id = ?""", (user_id,)).fetchone()
        return max(int(rated["rated_rounds"]) if rated else 0, int(linked["n"]))

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
            game["segments"] = [dict(r) for r in conn.execute(
                """SELECT first_round, room_code, log_file, log_offset FROM game_segments
                   WHERE game_id = ? ORDER BY first_round""", (game_id,))]
            return game

    def game_ranked(self, game_id: str) -> bool:
        """Whether any round of the game was rated: only a ranked table
        writes a rating event, under the game's id plus ``/<segment>``."""
        with closing(self._open()) as conn:
            return conn.execute(
                """SELECT 1 FROM rating_events
                   WHERE game_id = ? OR substr(game_id, 1, ?) = ? LIMIT 1""",
                (game_id, len(game_id) + 1, game_id + "/")).fetchone() is not None

    def segment_delta(self, user_id: int, segment_id: str) -> float:
        """``user_id``'s summed rating change in one rated segment
        (``<game id>/<n>``, the game to a held Ace)."""
        with closing(self._open()) as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(delta), 0) AS d FROM rating_events "
                "WHERE game_id = ? AND user_id = ?", (segment_id, user_id)).fetchone()
        return float(row["d"])

    def game_ratings(self, user_id: int, game_ids: list[str]) -> dict[str, dict]:
        """``user_id``'s own rating change in each of ``game_ids``, in one
        grouped query: game id -> ``rating_change`` (summed delta),
        ``rating_after`` (the latest event's) and ``rated_rounds``. A rated
        round's ``game_id`` is the saved game's id plus ``/<segment>`` (one
        segment per game to a held Ace at that table), so every segment
        counts toward its saved game. Games with no event are absent."""
        if not game_ids:
            return {}
        marks = ",".join("?" * len(game_ids))
        with closing(self._open()) as conn:
            rows = conn.execute(
                f"""SELECT gid, SUM(delta) AS change, COUNT(*) AS n,
                           rating_after, MAX(id) AS last_id
                    FROM (SELECT id, delta, rating_after,
                                 CASE WHEN instr(game_id, '/') > 0
                                      THEN substr(game_id, 1, instr(game_id, '/') - 1)
                                      ELSE game_id END AS gid
                          FROM rating_events WHERE user_id = ?)
                    WHERE gid IN ({marks})
                    GROUP BY gid""",
                (user_id, *game_ids)).fetchall()
        # SQLite takes a bare column alongside MAX() from the row holding the
        # maximum, so ``rating_after`` is the latest event's.
        return {r["gid"]: {"rating_change": r["change"], "rating_after": r["rating_after"],
                           "rated_rounds": r["n"]} for r in rows}

    def game_round_ratings(self, user_id: int, game_id: str) -> dict[int, float]:
        """``user_id``'s own rating delta per round of one saved game, across
        all of its segments: round number -> summed delta."""
        with closing(self._open()) as conn:
            rows = conn.execute(
                """SELECT round_no, SUM(delta) AS delta FROM rating_events
                   WHERE user_id = ? AND (game_id = ? OR substr(game_id, 1, ?) = ?)
                   GROUP BY round_no""",
                (user_id, game_id, len(game_id) + 1, game_id + "/")).fetchall()
        return {int(r["round_no"]): r["delta"] for r in rows}

    def current_seat_names(self, game_ids: list[str], round_no: int) -> dict[str, dict[int, str]]:
        """For each of ``game_ids``, seat -> the current effective name of
        the account linked at that seat in round ``round_no``. Seats no
        existing account held then are absent; no account id leaves here."""
        if not game_ids:
            return {}
        marks = ",".join("?" * len(game_ids))
        with closing(self._open()) as conn:
            rows = conn.execute(
                f"""SELECT p.game_id, p.seat, u.display_name, u.name
                    FROM game_players p JOIN users u ON u.id = p.user_id
                    WHERE p.game_id IN ({marks}) AND p.from_round <= ?
                      AND (p.to_round IS NULL OR p.to_round >= ?)
                    ORDER BY p.from_round""",
                (*game_ids, round_no, round_no)).fetchall()
        out: dict[str, dict[int, str]] = {}
        for r in rows:
            name = effective_name(dict(r))
            if name and 0 <= r["seat"] < 4:
                out.setdefault(r["game_id"], {})[int(r["seat"])] = name
        return out

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

    def forget_game(self, game_id: str) -> int:
        """Delete one game row (its links go by cascade): a start that was
        rolled back never became a game anyone played."""
        with closing(self._open()) as conn:
            return conn.execute("DELETE FROM games WHERE id = ?", (game_id,)).rowcount

    def forget_segment(self, game_id: str, first_round: int) -> int:
        """Delete a continuation that was rolled back before it began: its
        segment and the links it opened. The game's earlier rounds and links
        stay as they are."""
        with closing(self._open()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                n = conn.execute("DELETE FROM game_segments WHERE game_id = ? AND first_round = ?",
                                 (game_id, first_round)).rowcount
                conn.execute("DELETE FROM game_players WHERE game_id = ? AND from_round >= ?",
                             (game_id, first_round))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            return n

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
        """Remove a user; its sessions, game links and blocks (made by it or
        of it) go by cascade, and so do the games no other account links. The anonymous room logs are
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

    # -- blocks
    def blocked_ids(self, user_id: int) -> list[int]:
        """The accounts ``user_id`` blocked."""
        with closing(self._open()) as conn:
            rows = conn.execute("SELECT blocked_id FROM blocks WHERE blocker_id = ?",
                                (user_id,)).fetchall()
            return [int(row["blocked_id"]) for row in rows]

    def set_block(self, blocker_id: int, blocked_id: int, on: bool,
                  now: float | None = None) -> None:
        """Store or remove one block. A block naming an account that no longer
        exists stores nothing (the foreign key refuses it)."""
        t = int(now if now is not None else time.time())
        with closing(self._open()) as conn:
            if on:
                try:
                    conn.execute("INSERT OR IGNORE INTO blocks(blocker_id, blocked_id, created_at) "
                                 "VALUES (?, ?, ?)", (blocker_id, blocked_id, t))
                except sqlite3.IntegrityError:
                    pass
            else:
                conn.execute("DELETE FROM blocks WHERE blocker_id = ? AND blocked_id = ?",
                             (blocker_id, blocked_id))

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
                 clock: Callable[[], float] | None = None, label: str = "google"):
        self._fetch = fetch or self._fetch_http
        self._label = label
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
                    log.warning("%s certs refresh failed (%s); using cached set",
                                self._label, type(exc).__name__)
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
    # A signed-in device account confirms giving way to the account that
    # already holds this identity (``link_device_session``).
    confirm: bool = False


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


def public_user(row: Mapping[str, Any], rounds_played: int = 0) -> dict:
    """The ``/api/me`` payload: the Google profile, the chosen display name
    (null when none), ``name_shown``, the effective name, and
    ``rounds_played`` (``Store.rounds_played``), which tells the client
    whether the account is still new."""
    return {"name": row.get("name") or "", "email": row.get("email") or "",
            "picture": row.get("picture"), "display_name": row.get("display_name"),
            "name_shown": effective_name(row), "rounds_played": int(rounds_played)}


async def account_payload(store: "Store", row: Mapping[str, Any]) -> dict:
    """``public_user`` with the account's rounds played read off the loop."""
    return public_user(row, await store.run(store.rounds_played, int(row["id"])))


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
    sub, email, name, picture = _google_profile(claims)
    linked = await link_device_session(
        request, "google", sub, {"email": email, "name": name, "picture": picture}, body.confirm)
    device_token = None
    if linked is not None:
        user, token, device_token = linked
    else:
        user = await STORE.run(STORE.upsert_user, claims)
        refuse_suspended(user)
        token = await STORE.run(STORE.create_session, user["id"])
    _set_session_cookie(response, request, token)
    return sign_in_payload(await account_payload(STORE, user), device_token)


@router.get("/me")
async def me(request: Request) -> dict:
    user = await STORE.run(STORE.session_user, request.cookies.get(COOKIE))
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in.")
    return await account_payload(STORE, user)


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
    if not device_accounts_enabled():
        updated = await STORE.run(STORE.set_display_name, user["id"], name)
    else:
        # A device account's only name is its display name: clearing it
        # would leave the first word of the generated one.
        if name is None and is_device_account(user):
            raise HTTPException(status_code=400, detail="empty")
        try:
            updated = await STORE.run(STORE.set_unique_display_name, user["id"], name)
        except DisplayNameError as exc:
            raise HTTPException(status_code=400, detail=exc.reason) from exc
    if updated is None:
        raise HTTPException(status_code=401, detail="Not signed in.")
    shown = effective_name(updated)
    for hook in USER_RENAMED_HOOKS:
        try:
            hook(int(updated["id"]), shown)
        except Exception:           # noqa: BLE001 - the rename is stored either way
            log.exception("account-rename hook failed")
    return await account_payload(STORE, updated)


# Called on the event loop with the id and the new effective name, after the
# display name is stored: the game server renames the account's live sockets,
# pair and seats.
USER_RENAMED_HOOKS: list[Callable[[int, str], None]] = []


# Called on the event loop with the id, before the row is deleted: the game
# server detaches the id from every live seat.
USER_DELETED_HOOKS: list[Callable[[int], None]] = []


SUSPENDED_MESSAGE = "This account is suspended. Contact support if you think this is a mistake."


def is_suspended(row: Mapping[str, Any]) -> bool:
    return row.get("suspended_at") is not None


def refuse_suspended(row: Mapping[str, Any]) -> None:
    """Sign-in's check, after the identity is verified: a suspended account
    gets no session."""
    if is_suspended(row):
        raise HTTPException(status_code=403, detail=SUSPENDED_MESSAGE)


def is_deleted(user_id: int) -> bool:
    """Whether the account was deleted while this process runs: a socket
    opened before the delete still holds the id and reads as signed out."""
    return user_id in STORE.deleted_ids


@router.delete("/me", status_code=204)
async def delete_me(request: Request) -> Response:
    """Delete the account: the user row, its sessions and its saved-game
    links (by cascade). Live seats and open sockets holding the account are
    detached first, so nothing links the id afterwards (ids are never
    reused, schema v3). An Apple account's grant is then revoked at Apple,
    best effort: a failed revocation never keeps the account. The anonymous
    room logs never held the account and are unchanged."""
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
    refresh_token = None
    if user.get("apple_sub"):
        try:
            refresh_token = await STORE.run(STORE.apple_refresh_token, user["id"])
        except Exception as exc:    # noqa: BLE001 - the delete still happens
            log.warning("apple token lookup failed before delete (%s)", type(exc).__name__)
    await STORE.run(STORE.delete_user, user["id"])
    if user.get("apple_sub"):
        from . import apple_auth
        await apple_auth.revoke_after_delete(refresh_token)
    response = Response(status_code=204)
    _clear_session_cookie(response, request)
    return response


@router.post("/auth/logout")
async def logout(request: Request, response: Response) -> dict:
    """End the cookie's session. The app also sends its device credential
    (``Authorization: Device <token>``), which is then removed when it
    belongs to the same account, so signing out of a linked account on the
    phone does not sign it straight back in. A device account with no
    provider cannot sign out (409 ``{"code": "unlinked_device_account"}``,
    the session kept): it would be left with no way back in; it can be
    deleted instead."""
    token = request.cookies.get(COOKIE)
    try:
        device = _device_token(request)
    except HTTPException:
        device = None
    if token and not await STORE.run(STORE.sign_out, token, device):
        raise HTTPException(status_code=409, detail={"code": "unlinked_device_account"})
    _clear_session_cookie(response, request)
    return {"ok": True}


# Called on the event loop with ``(device_id, user_id)`` after a device
# account gave way to the account ``user_id`` and was deleted
# (``link_device_session``), before ``USER_DELETED_HOOKS`` run for it, so a
# hook can still find the device id where it was held.
USER_MERGED_HOOKS: list[Callable[[int, int], None]] = []


async def link_device_session(request: Request, provider: str, sub: str,
                              profile: Mapping[str, Any],
                              confirm: bool) -> tuple[dict, str, str | None] | None:
    """A provider sign-in from a device account's session
    (``Store.link_provider``). Returns ``(user, session token, device
    token)`` when the identity was linked in place (device token None: the
    app's credential still holds the same account) or the device account was
    merged into the identity's account (a new credential for that account);
    None when there is no device-account session (or device accounts are
    off), so the caller signs in as usual.

    When another account holds the identity and ``confirm`` is false: 409
    with ``{"code": "account_exists", "name": <its shown name>}`` and
    nothing changed; the client asks "Switch to <name>?" and repeats the
    request with ``confirm``. A suspended holder: 403.

    The decision and the write run on the saved-games link worker, after
    every link write already queued, so a game link the device account's
    live seat queued is in place before it moves. After a merge the device
    id is detached from live seats, sockets and block lists as a deletion
    would be; the client's next connection carries the winner's session."""
    if not device_accounts_enabled():
        return None
    current = await STORE.run(STORE.session_user, request.cookies.get(COOKIE))
    if current is None or not is_device_account(current):
        return None
    from . import saved_games
    device_id = int(current["id"])
    outcome = await saved_games.after_link_writes(
        STORE.link_provider, device_id, provider, sub, dict(profile), bool(confirm))
    kind = outcome["outcome"]
    if kind == "not_device":
        return None
    if kind == "suspended":
        raise HTTPException(status_code=403, detail=SUSPENDED_MESSAGE)
    if kind == "conflict":
        raise HTTPException(status_code=409,
                            detail={"code": "account_exists", "name": outcome["name"]})
    user = outcome["user"]
    if kind == "merged":
        STORE.deleted_ids.add(device_id)
        for merged_hook in USER_MERGED_HOOKS:
            try:
                merged_hook(device_id, int(user["id"]))
            except Exception:       # noqa: BLE001 - the merge is stored either way
                log.exception("account-merge hook failed")
        for hook in USER_DELETED_HOOKS:
            try:
                hook(device_id)
            except Exception:       # noqa: BLE001 - the merge is stored either way
                log.exception("account-deletion hook failed after merge")
    return user, outcome["session"], outcome.get("device_token")


def sign_in_payload(payload: dict, device_token: str | None) -> dict:
    """The sign-in response: the account, plus ``device_token`` when a merge
    issued the app a new device credential (returned this once)."""
    return payload if device_token is None else {**payload, "device_token": device_token}


def is_device_account(row: Mapping[str, Any]) -> bool:
    """An account with no provider: made by ``POST /api/auth/device``."""
    return row.get("google_sub") is None and row.get("apple_sub") is None


DEVICE_HOURLY = RateLimiter(DEVICE_CREATES_PER_HOUR, 3600.0)
DEVICE_DAILY = RateLimiter(DEVICE_CREATES_PER_DAY, 86400.0)


def _device_token(request: Request) -> str | None:
    """The token of an ``Authorization: Device <token>`` header; None when
    the header is absent. Any other scheme, or an empty token, is a 401."""
    header = request.headers.get("authorization")
    if header is None:
        return None
    scheme, _, token = header.strip().partition(" ")
    token = token.strip()
    if scheme.lower() != DEVICE_AUTH_SCHEME.lower() or not token:
        raise HTTPException(status_code=401, detail="Device sign-in rejected (malformed).")
    return token


@router.post("/auth/device")
async def auth_device(request: Request, response: Response) -> dict:
    """The iOS app's account, with no provider.

    With no ``Authorization`` header: create a device account with a
    server-assigned unique name, start a session (the ``sj_session``
    cookie, as every sign-in does) and return ``{"token", "user"}``. The
    256-bit token is returned this once; the server keeps only its SHA-256.
    With ``Authorization: Device <token>``: start a session for the account
    holding that credential and return ``{"user"}``.

    404 unless ``SHENGJI_DEVICE_ACCOUNTS=1``. 403 unless the request
    declares the iOS app (``X-Shengji-Client: ios-app``), a soft gate: the
    web client never calls this, so web players stay guests. Creation is
    limited per address (``DEVICE_CREATES_PER_HOUR`` and ``_PER_DAY``),
    sign-in shares the sign-in endpoints' per-address budget; over either,
    429, and the app plays on as a guest."""
    if not device_accounts_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    if request.headers.get(CLIENT_HEADER, "").strip().lower() != IOS_APP_CLIENT:
        raise HTTPException(status_code=403, detail="Device accounts are for the app only.")
    token = _device_token(request)
    ip = client_ip(request)
    if token is not None:
        if not LIMITER.allow(ip):
            raise HTTPException(status_code=429, detail="Too many sign-in attempts; try again in a minute.")
        signed_in = await STORE.run(STORE.device_sign_in, token)
        if signed_in is None:
            raise HTTPException(status_code=401, detail="Device sign-in rejected (unknown).")
        user, session = signed_in
        refuse_suspended(user)
        assert session is not None
        _set_session_cookie(response, request, session)
        return {"user": await account_payload(STORE, user)}
    if not DEVICE_HOURLY.allow(ip) or not DEVICE_DAILY.allow(ip):
        raise HTTPException(status_code=429, detail="Too many new accounts; play as a guest for now.")
    token = secrets.token_urlsafe(32)
    try:
        user, session = await STORE.run(STORE.create_device_account, token)
    except DisplayNameError as exc:
        log.warning("device account not created: no free name")
        raise HTTPException(status_code=503, detail="No account available; play as a guest.") from exc
    _set_session_cookie(response, request, session)
    return {"token": token, "user": await account_payload(STORE, user)}


def detach_purged(user_ids: list[int]) -> None:
    """After ``Store.purge_device_accounts``, on the event loop: the same
    hooks a ``DELETE /api/me`` runs, so no live seat keeps a purged id."""
    for user_id in user_ids:
        for hook in USER_DELETED_HOOKS:
            try:
                hook(user_id)
            except Exception:       # noqa: BLE001 - the purge already happened
                log.exception("account-deletion hook failed after purge")


async def websocket_user(ws: WebSocket) -> dict | None:
    """The signed-in user behind a websocket's ``sj_session`` cookie, or None.
    No cookie means no database access at all: a guest's handshake is
    unchanged. A storage error is logged and read as a guest, never a
    refused game. A suspended account's socket is told so (the socket is
    already accepted) and plays on as a guest."""
    cookies = getattr(ws, "cookies", None) or {}   # a socket without a cookie jar is a guest
    token = cookies.get(COOKIE)
    if not token:
        return None
    try:
        row = await STORE.run(STORE.session_account, token)
    except Exception as exc:            # noqa: BLE001 - gameplay over identity
        log.warning("session lookup failed on websocket (%s)", type(exc).__name__)
        return None
    if row is not None and is_suspended(row):
        try:
            await ws.send_json({"type": "error", "code": "account_suspended", "message": SUSPENDED_MESSAGE})
        except Exception:               # noqa: BLE001 - a gone socket ends on its own
            pass
        return None
    return row


def health() -> dict:
    """What ``/healthz`` shows: whether sign-in is on. No path, no counts."""
    return {"google_sign_in": client_id() is not None}


def register_accounts(app) -> None:
    from .apple_auth import router as apple_router

    app.include_router(router)
    app.include_router(apple_router)
