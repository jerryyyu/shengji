"""Device accounts (``POST /api/auth/device``) and schema v10.

A device account is a ``users`` row with no provider, made for the iOS app
and held by a 256-bit credential of which the server keeps only the SHA-256.
Everything here is off unless ``SHENGJI_DEVICE_ACCOUNTS=1``.
"""
from __future__ import annotations

import random
import shutil
import sqlite3
import time
from contextlib import closing

import pytest

from tests.test_accounts import _login, _sign, _claims, keypair  # noqa: F401
from tests.test_server_ws import _drain, client  # noqa: F401

APP = {"x-shengji-client": "ios-app"}


@pytest.fixture()
def device_on(tmp_path, monkeypatch):
    """Device accounts on, a private database, fresh limiters."""
    from shengji.api import accounts

    monkeypatch.setenv("SHENGJI_DEVICE_ACCOUNTS", "1")
    monkeypatch.setenv("SHENGJI_DATA_DIR", str(tmp_path / "data"))
    store = accounts.Store(tmp_path / "data" / "accounts.sqlite3")
    store.schema_version()                  # create the file, so a test can count rows
    monkeypatch.setattr(accounts, "STORE", store)
    monkeypatch.setattr(accounts, "LIMITER", accounts.RateLimiter())
    monkeypatch.setattr(accounts, "DEVICE_HOURLY",
                        accounts.RateLimiter(accounts.DEVICE_CREATES_PER_HOUR, 3600.0))
    monkeypatch.setattr(accounts, "DEVICE_DAILY",
                        accounts.RateLimiter(accounts.DEVICE_CREATES_PER_DAY, 86400.0))
    return accounts


def _create(client, **headers):
    return client.post("/api/auth/device", headers={**APP, **headers})


def _cookie(resp) -> str:
    return resp.headers["set-cookie"].split(";")[0]


def _rows(path, sql, args=()):
    with closing(sqlite3.connect(path)) as db:
        return db.execute(sql, args).fetchall()


# ------------------------------------------------------------------ schema v10
def _v9_database(path, accounts):
    """A v9 database built by the real v1..v9 steps, with a row in every
    table that references ``users`` and a deleted id below the high-water
    mark."""
    full = accounts.SCHEMA
    assert len(full) == 10
    accounts.SCHEMA = full[:9]
    try:
        store = accounts.Store(path)
        assert store.schema_version() == 9
        g = store.upsert_user({"sub": "g-1", "email": "g@example.com", "name": "Google One"})
        a = store.upsert_apple_user("apple-1", "a@example.com", "Apple One")
        gone = store.upsert_user({"sub": "g-gone", "email": "x@example.com", "name": "Gone"})
        store.set_display_name(g["id"], "Champ")
        store.set_apple_refresh_token(a["id"], "refresh-token-value")
        store.create_session(g["id"])
        store.create_session(a["id"])
        store.link_seat({"id": "game-1", "room_code": "ABCD", "log_file": "x.jsonl",
                         "log_offset": 0, "started_at": int(time.time()), "last_round": 1},
                        g["id"], 0, 1)
        store.set_block(g["id"], a["id"], True)
        store.set_block(a["id"], g["id"], True)
        with closing(sqlite3.connect(path)) as db:
            db.execute(
                """INSERT INTO rating_events(game_id, round_no, user_id, created_at, team,
                       banker_team, won, levels, expected, actual, k, rating_before,
                       rating_after, delta) VALUES ('game-1/1', 1, ?, 1, 0, 0, 1, 1,
                       0.5, 1, 40, 1000, 1020, 20)""", (g["id"],))
            db.execute(
                """INSERT INTO game_segments(game_id, first_round, room_code, log_file,
                       log_offset) VALUES ('game-1', 2, 'EFGH', 'y.jsonl', 0)""")
            db.commit()
        store.delete_user(gone["id"])
    finally:
        accounts.SCHEMA = full
    return g["id"], a["id"], gone["id"]


def _dump(path):
    out = {}
    with closing(sqlite3.connect(path)) as db:
        for table in ("users", "sessions", "game_players", "rating_events", "apple_tokens",
                      "blocks", "games", "game_segments"):
            out[table] = sorted(db.execute(f"SELECT * FROM {table}").fetchall(), key=repr)
    return out


def test_a_v9_database_upgrades_to_v10_and_keeps_every_row(device_on, tmp_path):
    accounts = device_on
    fixture = tmp_path / "v9" / "fixture.sqlite3"
    fixture.parent.mkdir()
    g, a, gone = _v9_database(fixture, accounts)
    assert "CHECK" in _rows(fixture, "SELECT sql FROM sqlite_master WHERE name='users'")[0][0]
    copy = tmp_path / "v9" / "accounts.sqlite3"
    shutil.copy(fixture, copy)
    before = _dump(copy)
    seq_before = dict(_rows(copy, "SELECT name, seq FROM sqlite_sequence"))
    indexes_before = set(_rows(copy, "SELECT name, sql FROM sqlite_master WHERE type='index'"))

    store = accounts.Store(copy)
    assert store.schema_version() == 10
    assert _dump(copy) == before
    assert dict(_rows(copy, "SELECT name, seq FROM sqlite_sequence")) == seq_before
    assert set(_rows(copy, "SELECT name, sql FROM sqlite_master WHERE type='index'")) \
        >= indexes_before
    assert _rows(copy, "PRAGMA foreign_key_check") == []
    names = {r[0] for r in _rows(copy, "SELECT name FROM sqlite_master")}
    assert not {n for n in names if n.endswith("_v9") or n.endswith("_v10")}
    assert "device_credentials" in names
    users_sql = _rows(copy, "SELECT sql FROM sqlite_master WHERE name='users'")[0][0]
    assert "CHECK" not in users_sql and "AUTOINCREMENT" in users_sql
    for child in ("sessions", "game_players", "rating_events", "apple_tokens", "blocks"):
        fks = _rows(copy, f"PRAGMA foreign_key_list({child})")
        assert fks and all(fk[2] in ("users", "games") for fk in fks), child
        assert all(fk[6] == "CASCADE" for fk in fks), child
    assert "WITHOUT ROWID" in _rows(copy, "SELECT sql FROM sqlite_master WHERE name='blocks'")[0][0]

    # The rebuilt tables behave: sessions sign in, ids are never reused, the
    # cascades follow the new users table, and a provider-less row is allowed.
    assert store.user(g)["display_name"] == "Champ"
    device = store.create_device_user("t" * 43)
    assert device["id"] > gone and device["google_sub"] is None and device["apple_sub"] is None
    assert store.delete_user(a) is True
    assert _rows(copy, "SELECT COUNT(*) FROM blocks") == [(0,)]
    assert _rows(copy, "SELECT COUNT(*) FROM apple_tokens") == [(0,)]
    assert _rows(copy, "SELECT user_id FROM sessions") == [(g,)]

    # Idempotent: the step re-runs on a migrated table, and a new Store has
    # nothing to do.
    with closing(sqlite3.connect(copy)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        accounts._migrate_v10(db)
        db.commit()
    assert accounts.Store(copy).schema_version() == 10
    assert accounts.Store(copy).user(g)["display_name"] == "Champ"
    # The fixture itself is untouched.
    assert _dump(fixture) == before


def test_a_fresh_database_matches_a_migrated_one(device_on, tmp_path):
    accounts = device_on
    migrated = tmp_path / "m" / "accounts.sqlite3"
    migrated.parent.mkdir()
    _v9_database(migrated, accounts)
    accounts.Store(migrated).schema_version()
    fresh = tmp_path / "f" / "accounts.sqlite3"
    accounts.Store(fresh).schema_version()
    for table in ("users", "sessions", "game_players", "rating_events", "apple_tokens",
                  "blocks", "device_credentials"):
        assert (_rows(migrated, f"PRAGMA table_info({table})")
                == _rows(fresh, f"PRAGMA table_info({table})")), table
        assert (_rows(migrated, f"PRAGMA foreign_key_list({table})")
                == _rows(fresh, f"PRAGMA foreign_key_list({table})")), table


# --------------------------------------------------------- the endpoint gates
def test_the_endpoint_is_404_when_the_flag_is_off(device_on, client, monkeypatch):
    monkeypatch.delenv("SHENGJI_DEVICE_ACCOUNTS")
    assert _create(client).status_code == 404
    monkeypatch.setenv("SHENGJI_DEVICE_ACCOUNTS", "0")
    assert _create(client).status_code == 404
    assert _create(client, authorization="Device " + "a" * 43).status_code == 404
    assert _rows(device_on.STORE.path, "SELECT COUNT(*) FROM users") == [(0,)]


def test_only_a_request_declaring_the_ios_app_gets_an_account(device_on, client):
    for headers in ({}, {"x-shengji-client": "web"}, {"x-shengji-client": "ios"}):
        resp = client.post("/api/auth/device", headers=headers)
        assert resp.status_code == 403, headers
        assert "set-cookie" not in resp.headers
    assert _rows(device_on.STORE.path, "SELECT COUNT(*) FROM users") == [(0,)]
    assert client.post("/api/auth/device", headers={"x-shengji-client": "iOS-App"}).status_code == 200


# --------------------------------------------------- create, auth and refresh
def test_create_then_auth_then_refresh(device_on, client):
    accounts = device_on
    resp = _create(client)
    assert resp.status_code == 200
    body = resp.json()
    token, user = body["token"], body["user"]
    assert len(token) == 43                        # 32 random bytes, base64url
    assert user["display_name"] == user["name_shown"] and user["rounds_played"] == 0
    assert user["email"] == "" and user["picture"] is None
    first_cookie = _cookie(resp)
    assert first_cookie.startswith("sj_session=")
    assert client.get("/api/me", headers={"cookie": first_cookie}).json()["name_shown"] \
        == user["name_shown"]

    # The credential signs the same account in again and mints a new session.
    again = _create(client, authorization=f"Device {token}")
    assert again.status_code == 200
    assert again.json() == {"user": user}
    second_cookie = _cookie(again)
    assert second_cookie != first_cookie
    assert client.get("/api/me", headers={"cookie": second_cookie}).status_code == 200
    assert _rows(accounts.STORE.path, "SELECT COUNT(*) FROM users") == [(1,)]
    assert accounts.STORE.count_sessions(1) == 2

    # An unknown, malformed or wrongly-schemed credential creates nothing.
    for header in ("Device " + "b" * 43, "Device short", "Device ", "Bearer " + token):
        assert _create(client, authorization=header).status_code == 401, header
    assert _rows(accounts.STORE.path, "SELECT COUNT(*) FROM users") == [(1,)]


def test_auth_marks_the_credential_seen_and_the_account_used(device_on):
    store = device_on.STORE
    user = store.create_device_user("c" * 43, now=1_000)
    row = store.device_account("c" * 43, now=5_000)
    assert row["id"] == user["id"] and row["last_login_at"] == 5_000
    assert _rows(store.path, "SELECT created_at, last_seen_at FROM device_credentials") \
        == [(1_000, 5_000)]


def test_the_token_is_stored_only_as_its_hash(device_on, client):
    accounts = device_on
    resp = _create(client)
    token = resp.json()["token"]
    stored = _rows(accounts.STORE.path, "SELECT token_hash, user_id FROM device_credentials")
    assert stored == [(accounts._hash_token(token), 1)]
    raw = accounts.STORE.path.read_bytes()
    for suffix in ("", "-wal"):
        path = accounts.STORE.path.with_name(accounts.STORE.path.name + suffix)
        if path.exists():
            raw += path.read_bytes()
    assert token.encode() not in raw


def test_a_suspended_device_account_gets_no_session(device_on, client):
    token = _create(client).json()["token"]
    device_on.STORE.set_suspended(1, True)
    resp = _create(client, authorization=f"Device {token}")
    assert resp.status_code == 403 and "set-cookie" not in resp.headers


def test_a_device_session_is_an_account_on_the_socket(device_on, client):
    from shengji.api import server as srv

    resp = _create(client)
    name = resp.json()["user"]["name_shown"]
    with client.websocket_connect("/ws", headers={"cookie": _cookie(resp)}) as ws:
        ws.send_json({"type": "create_room"})
        room = _drain(ws, "room")
        assert room["players"][0]["name"] == name
        assert srv.rooms[room["room"]].seats[0].user_id == 1


# --------------------------------------------------------------------- names
def test_every_generated_name_is_valid_and_filtered(device_on):
    from shengji.api import chat_filter, device_names

    names = device_names.all_names()
    assert len(names) == len(set(n.casefold() for n in names)) == 2400
    for name in names:
        assert device_on.validate_display_name(name) == name, name
        assert not chat_filter.contains(name), name


def test_generated_names_are_unique_case_insensitively(device_on, monkeypatch):
    from shengji.api import device_names

    accounts = device_on
    store = accounts.STORE
    # A pool of four names, one already shown (in another case) by a Google
    # account: three device accounts get the other three, then the pool is spent.
    monkeypatch.setattr(device_names, "ADJECTIVES", ("Lucky", "Bold"))
    monkeypatch.setattr(device_names, "NOUNS", ("Ace", "King"))
    google = store.upsert_user({"sub": "g", "email": "g@example.com", "name": "G"})
    store.set_display_name(google["id"], "LUCKY ACE")
    rng = random.Random(7)
    got = {store.create_device_user(f"{i}" * 43, rng=rng)["display_name"] for i in range(3)}
    assert got == {"Lucky King", "Bold Ace", "Bold King"}
    with pytest.raises(accounts.DisplayNameError) as err:
        store.create_device_user("9" * 43, rng=rng)
    assert err.value.reason == "taken"
    assert _rows(store.path, "SELECT COUNT(*) FROM device_credentials") == [(3,)]


def test_a_filtered_name_is_never_drawn(device_on, monkeypatch):
    from shengji.api import device_names

    monkeypatch.setattr(device_names, "ADJECTIVES", ("Lucky",))
    monkeypatch.setattr(device_names, "NOUNS", ("Ace", "King"))
    monkeypatch.setattr(device_on, "DISPLAY_NAME_BLOCKLIST", lambda name: "Ace" in name)
    for i in range(3):
        try:
            row = device_on.STORE.create_device_user(f"{i}" * 43)
        except device_on.DisplayNameError:
            break
        assert row["display_name"] == "Lucky King"
    assert _rows(device_on.STORE.path, "SELECT display_name FROM users") == [("Lucky King",)]


# --------------------------------------------------------- edited-name rule
def test_an_edit_into_a_taken_name_is_refused(device_on, client):
    accounts = device_on
    first = _create(client)
    second = _create(client)
    taken = first.json()["user"]["name_shown"]
    session = {"cookie": _cookie(second)}
    resp = client.patch("/api/me", json={"display_name": taken.upper()}, headers=session)
    assert resp.status_code == 400 and resp.json()["detail"] == "taken"
    assert client.patch("/api/me", json={"display_name": "Fresh Name"},
                        headers=session).status_code == 200
    # A device account cannot clear its only name.
    resp = client.patch("/api/me", json={"display_name": None}, headers=session)
    assert resp.status_code == 400 and resp.json()["detail"] == "empty"
    assert accounts.STORE.user(2)["display_name"] == "Fresh Name"


def test_existing_colliding_names_are_kept_and_only_new_edits_refused(device_on):
    store = device_on.STORE
    a = store.upsert_user({"sub": "a", "email": "a@example.com", "name": "Sam One"})
    b = store.upsert_apple_user("b", None, "Sam Two")
    store.set_display_name(a["id"], "Sam")
    store.set_display_name(b["id"], "Sam")          # a collision from before the rule
    # Each keeps its name, and may re-save it in another case.
    assert store.set_unique_display_name(a["id"], "SAM")["display_name"] == "SAM"
    assert store.user(b["id"])["display_name"] == "Sam"
    c = store.upsert_user({"sub": "c", "email": "c@example.com", "name": "Cleo"})
    with pytest.raises(device_on.DisplayNameError):
        store.set_unique_display_name(c["id"], "sam")
    # A Google first name shown by default counts as taken too.
    with pytest.raises(device_on.DisplayNameError):
        store.set_unique_display_name(a["id"], "cleo")
    # Clearing back to the provider name is not an edit into a name.
    assert store.set_unique_display_name(b["id"], None)["display_name"] is None


def test_the_edit_rule_is_off_with_the_flag(device_on, client, keypair, monkeypatch):
    accounts = device_on
    private_pem, public_pem = keypair
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "1234567890-test.apps.googleusercontent.com")
    monkeypatch.setattr(accounts, "CERTS",
                        accounts.GoogleCerts(fetch=lambda: ({"kid-test-1": public_pem}, 3600.0)))
    other = accounts.STORE.upsert_user({"sub": "o", "email": "o@example.com", "name": "Other"})
    accounts.STORE.set_display_name(other["id"], "Taken Name")
    resp = _login(client, _sign(private_pem, _claims()))
    session = {"cookie": _cookie(resp)}
    monkeypatch.delenv("SHENGJI_DEVICE_ACCOUNTS")
    resp = client.patch("/api/me", json={"display_name": "taken name"}, headers=session)
    assert resp.status_code == 200          # production behaviour, unchanged
    monkeypatch.setenv("SHENGJI_DEVICE_ACCOUNTS", "1")
    resp = client.patch("/api/me", json={"display_name": "Taken Name"}, headers=session)
    assert resp.status_code == 200          # its own current name, in another case
    accounts.STORE.set_display_name(other["id"], "Second")
    resp = client.patch("/api/me", json={"display_name": "second"}, headers=session)
    assert resp.status_code == 400 and resp.json()["detail"] == "taken"


# ---------------------------------------------------------------- rate limit
def test_creation_is_limited_per_address(device_on, client):
    accounts = device_on
    for _ in range(accounts.DEVICE_CREATES_PER_HOUR):
        assert _create(client).status_code == 200
    resp = _create(client)
    assert resp.status_code == 429 and "set-cookie" not in resp.headers
    assert _rows(accounts.STORE.path, "SELECT COUNT(*) FROM users") == [(5,)]
    # Another address has its own budget.
    assert _create(client, **{"fly-client-ip": "203.0.113.9"}).status_code == 200


def test_the_daily_limit_holds_across_hours(device_on):
    accounts = device_on
    hourly, daily = accounts.DEVICE_HOURLY, accounts.DEVICE_DAILY
    def made(hours):
        n = 0
        for hour in hours:
            for _ in range(10):
                t = hour * 3600.0
                n += bool(hourly.allow("ip", now=t) and daily.allow("ip", now=t))
        return n

    # Five an hour, but twenty a day: the day's budget is spent by hour 4.
    assert made(range(24)) == accounts.DEVICE_CREATES_PER_DAY
    # A day after the first creations, the budget comes back.
    assert made([24]) == accounts.DEVICE_CREATES_PER_HOUR


# --------------------------------------------------------------------- purge
DAY = 86400


def test_the_purge_takes_unrated_and_idle_device_accounts_only(device_on):
    accounts = device_on
    store = accounts.STORE
    now = 1_000 * DAY
    fresh = store.create_device_user("f" * 43, now=now - 29 * DAY)
    unrated = store.create_device_user("u" * 43, now=now - 31 * DAY)
    rated = store.create_device_user("r" * 43, now=now - 400 * DAY)
    idle = store.create_device_user("i" * 43, now=now - 400 * DAY)
    google = store.upsert_user({"sub": "g", "email": "g@example.com", "name": "G"},
                               now=now - 900 * DAY)
    # Casual players: unrated and old, but signed in, or seen through the
    # credential, within the last 30 days.
    casual = store.create_device_user("k" * 43, now=now - 400 * DAY)
    store.device_account("k" * 43, now=now - 1 * DAY)
    seen = store.create_device_user("s" * 43, now=now - 60 * DAY)
    with closing(sqlite3.connect(store.path)) as db:
        db.execute("UPDATE users SET rated_rounds = 3 WHERE id IN (?, ?, ?)",
                   (rated["id"], idle["id"], google["id"]))
        db.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now - 10 * DAY, rated["id"]))
        db.execute("UPDATE device_credentials SET last_seen_at = ? WHERE user_id = ?",
                   (now - 29 * DAY, seen["id"]))
        db.commit()
    store.create_session(unrated["id"], now=now - 31 * DAY)    # expired a day ago
    store.set_block(fresh["id"], unrated["id"], True)

    gone = store.purge_device_accounts(now=now)
    assert sorted(gone) == sorted([unrated["id"], idle["id"]])
    left = {r[0] for r in _rows(store.path, "SELECT id FROM users")}
    assert left == {fresh["id"], rated["id"], google["id"], casual["id"], seen["id"]}
    assert {r[0] for r in _rows(store.path, "SELECT user_id FROM device_credentials")} \
        == {fresh["id"], rated["id"], casual["id"], seen["id"]}
    assert _rows(store.path, "SELECT COUNT(*) FROM sessions") == [(0,)]
    assert _rows(store.path, "SELECT COUNT(*) FROM blocks") == [(0,)]
    assert accounts.is_deleted(unrated["id"]) and not accounts.is_deleted(fresh["id"])
    assert store.purge_device_accounts(now=now) == []
    # Once the casual player stops for 30 days, the unrated account goes too.
    later = store.purge_device_accounts(now=now + 30 * DAY)
    assert casual["id"] in later and rated["id"] not in later


def test_the_purge_keeps_an_account_with_an_unexpired_session(device_on):
    store = device_on.STORE
    now = 1_000 * DAY
    user = store.create_device_user("v" * 43, now=now - 31 * DAY)
    store.create_session(user["id"], now=now - 31 * DAY)
    with closing(sqlite3.connect(store.path)) as db:
        db.execute("UPDATE sessions SET expires_at = ? WHERE user_id = ?", (now + DAY, user["id"]))
        db.commit()
    assert store.purge_device_accounts(now=now) == []
    assert store.user(user["id"]) is not None
    # Once that session has expired, the unrated, unused account goes.
    assert store.purge_device_accounts(now=now + 2 * DAY) == [user["id"]]


def test_the_purge_runs_with_the_saved_games_sweep_only_when_on(device_on, monkeypatch):
    from shengji.api import saved_games

    accounts = device_on
    store = accounts.STORE
    old = store.create_device_user("o" * 43, now=time.time() - 40 * DAY)
    detached = []
    monkeypatch.setattr(accounts, "USER_DELETED_HOOKS", [detached.append])
    monkeypatch.setattr(saved_games, "_last_purge", 0.0)
    monkeypatch.delenv("SHENGJI_DEVICE_ACCOUNTS")
    saved_games._maybe_purge()
    assert store.user(old["id"]) is not None
    monkeypatch.setenv("SHENGJI_DEVICE_ACCOUNTS", "1")
    monkeypatch.setattr(saved_games, "_last_purge", 0.0)
    saved_games._maybe_purge()
    assert store.user(old["id"]) is None
    assert detached == [old["id"]]


# ------------------------------------------------------------------ deletion
def test_deleting_a_device_account_deletes_its_credentials(device_on, client):
    accounts = device_on
    resp = _create(client)
    token = resp.json()["token"]
    assert client.delete("/api/me", headers={"cookie": _cookie(resp)}).status_code == 204
    assert _rows(accounts.STORE.path, "SELECT COUNT(*) FROM device_credentials") == [(0,)]
    assert _rows(accounts.STORE.path, "SELECT COUNT(*) FROM users") == [(0,)]
    assert _create(client, authorization=f"Device {token}").status_code == 401
