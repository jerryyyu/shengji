"""Device accounts, part two: ratings, the leaderboard, linking a provider,
the provider-conflict merge, unique names for new provider accounts, sign
out and delete, and a randomized check of the whole account lifecycle.

Everything here is behind ``SHENGJI_DEVICE_ACCOUNTS=1``.
"""
from __future__ import annotations

import os
import random
import sqlite3
import time
from contextlib import closing

import pytest

from tests.test_accounts import _claims, _login, _sign, accounts_on, keypair  # noqa: F401
from tests.test_server_ws import client  # noqa: F401

APP = {"x-shengji-client": "ios-app"}


@pytest.fixture()
def linking(accounts_on, monkeypatch):  # noqa: F811
    """Google sign-in configured, device accounts on, fresh limiters."""
    accounts = accounts_on
    monkeypatch.setenv("SHENGJI_DEVICE_ACCOUNTS", "1")
    monkeypatch.setattr(accounts, "DEVICE_HOURLY", accounts.RateLimiter(1000, 3600.0))
    monkeypatch.setattr(accounts, "DEVICE_DAILY", accounts.RateLimiter(1000, 86400.0))
    accounts.STORE.schema_version()
    return accounts


def _device(client):
    resp = client.post("/api/auth/device", headers=APP)
    assert resp.status_code == 200
    body = resp.json()
    return body["token"], _cookie(resp), body["user"]


def _cookie(resp) -> str:
    return resp.headers["set-cookie"].split(";")[0]


def _rows(store, sql, args=()):
    with closing(sqlite3.connect(store.path)) as db:
        return db.execute(sql, args).fetchall()


def _google(client, keypair, cookie=None, confirm=None, **claims):  # noqa: F811
    private_pem, _ = keypair
    body = {"credential": _sign(private_pem, _claims(**claims))}
    if confirm is not None:
        body["confirm"] = confirm
    headers = {"cookie": cookie} if cookie else {}
    client.cookies.clear()
    return client.post("/api/auth/google", json=body, headers=headers)


def _record(game_id, round_no, seats, winner_team=0, level_change=1):
    """A finished round: ``seats`` maps seat -> account id; other seats are bots."""
    from shengji.api import ratings

    return ratings.RoundRecord(
        game_id=game_id, round_no=round_no, banker_team=0, winner_team=winner_team,
        level_change=level_change, point_scored=False, start_accounts=dict(seats),
        seat_names=[f"P{s}" for s in range(4)],
        seat_bots=[s not in seats for s in range(4)],
        participants=[ratings.Participant(user_id=u, seat=s) for s, u in seats.items()])


def _game(game_id, last_round=1):
    return {"id": game_id, "room_code": "ABCD", "log_file": "ABCD.jsonl", "log_offset": 0,
            "started_at": int(time.time()), "last_round": last_round}


def _check_rating_ledger(store, rows=_rows):
    """rating - START_RATING equals the sum of the account's event deltas,
    and rated_rounds counts its events, for every account."""
    from shengji.api import ratings

    for uid, rating, rounds, total, n in rows(
            store, """SELECT u.id, u.rating, u.rated_rounds, COALESCE(SUM(e.delta), 0), COUNT(e.id)
                      FROM users u LEFT JOIN rating_events e ON e.user_id = u.id
                      GROUP BY u.id"""):
        assert abs(rating - ratings.START_RATING - total) < 1e-6, uid
        assert rounds == n, uid


# --------------------------------------------------------------- ratings
def test_a_device_account_at_a_ranked_table_rates_as_an_account(linking, client, monkeypatch):
    from shengji.api import ratings, server as srv
    from tests.test_ratings import Table, _force_outcome

    _token, _cookie_, user = _device(client)
    uid = 1
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [uid, "bot", "bot", "bot"])
    table.play_round(banker=0)
    assert table.room.ratings.kinds == [ratings.ACCOUNT, ratings.BOT, ratings.BOT, ratings.BOT]
    events = _rows(linking.STORE, "SELECT user_id, delta, rating_before FROM rating_events")
    assert len(events) == 1 and events[0][0] == uid and events[0][2] == ratings.START_RATING
    row = linking.STORE.user(uid)
    assert row["rated_rounds"] == 1 and row["rating"] == pytest.approx(1000 + events[0][1])
    assert user["name_shown"] == row["display_name"]
    _check_rating_ledger(linking.STORE)


def test_device_and_provider_accounts_are_rated_by_one_formula(linking):
    """The same seat in the same round moves a device account and a Google
    account by the same delta from the same start."""
    from shengji.api import ratings

    store = linking.STORE
    device = store.create_device_user("d" * 43)["id"]
    google = store.upsert_user(_claims(sub="g-same", name="Same Person"))["id"]
    out_d = ratings.apply_round(store, _record("g1/1", 1, {0: device}))
    out_g = ratings.apply_round(store, _record("g2/1", 1, {0: google}))
    assert out_d[device]["delta"] == pytest.approx(out_g[google]["delta"])
    assert out_d[device]["delta"] > 0


# ----------------------------------------------------------- leaderboard
def test_a_device_account_is_listed_at_once_and_respects_the_switch(linking, client):
    from shengji.api import ratings

    store = linking.STORE
    _token, cookie, user = _device(client)
    ratings.apply_round(store, _record("g1/1", 1, {0: 1}))
    board = client.get("/api/leaderboard?period=all").json()
    assert [r["name"] for r in board["players"]] == [user["name_shown"]]
    assert board["players"][0]["provisional"] is True        # the "new" tag only
    assert client.get("/api/leaderboard?period=week").json()["players"][0]["rounds"] == 1

    resp = client.post("/api/me/leaderboard-visibility", json={"visible": False}, headers={"cookie": cookie})
    assert resp.status_code == 200
    hidden = client.get("/api/leaderboard?period=all", headers={"cookie": cookie}).json()
    assert hidden["players"] == []
    assert hidden["me"]["name"] == user["name_shown"] and hidden["me"]["visible"] is False
    assert client.get("/api/leaderboard?period=all").json()["players"] == []


# ------------------------------------------------------- link in place
def test_linking_a_new_identity_keeps_the_device_account(linking, client, keypair):  # noqa: F811
    from shengji.api import ratings

    store = linking.STORE
    token, cookie, user = _device(client)
    ratings.apply_round(store, _record("g1/1", 1, {0: 1}))
    store.link_seat(_game("g1"), 1, 0, 1)
    before = store.user(1)
    resp = _google(client, keypair, cookie=cookie, sub="g-new", name="New Person")
    assert resp.status_code == 200
    assert resp.json()["name_shown"] == user["name_shown"]
    after = store.user(1)
    assert after["google_sub"] == "g-new" and after["email"] == "jerry@example.com"
    assert (after["rating"], after["rated_rounds"], after["display_name"]) == (
        before["rating"], before["rated_rounds"], before["display_name"])
    assert _rows(store, "SELECT COUNT(*) FROM users") == [(1,)]
    assert _rows(store, "SELECT user_id FROM game_players") == [(1,)]
    # The new session is the same account; the credential still signs it in.
    assert client.get("/api/me", headers={"cookie": _cookie(resp)}).json()["name_shown"] \
        == user["name_shown"]
    again = client.post("/api/auth/device", headers={**APP, "authorization": f"Device {token}"})
    assert again.status_code == 200
    # A later plain Google sign-in finds the same row.
    assert _google(client, keypair, sub="g-new").json()["name_shown"] == user["name_shown"]
    assert _rows(store, "SELECT COUNT(*) FROM users") == [(1,)]


def test_linking_apple_in_place(linking, client, monkeypatch):
    from tests import test_apple_signin as ta

    apple_auth, _fake = _apple(monkeypatch)
    _token, cookie, user = _device(client)
    resp = client.post("/api/auth/apple", headers={"cookie": cookie}, json={
        "identity_token": ta._sign(_RSA, ta._claims(sub="apple-new")), "nonce": ta.RAW_NONCE})
    assert resp.status_code == 200 and resp.json()["name_shown"] == user["name_shown"]
    assert linking.STORE.user(1)["apple_sub"] == "apple-new"
    assert _rows(linking.STORE, "SELECT COUNT(*) FROM users") == [(1,)]


def test_an_apple_conflict_asks_then_merges(linking, client, monkeypatch):
    from tests import test_apple_signin as ta

    _apple(monkeypatch)
    store = linking.STORE
    target = store.upsert_apple_user("apple-old", None, "Mei Lin")["id"]
    _token, cookie, _user = _device(client)
    body = {"identity_token": ta._sign(_RSA, ta._claims(sub="apple-old")), "nonce": ta.RAW_NONCE}
    resp = client.post("/api/auth/apple", headers={"cookie": cookie}, json=body)
    assert resp.status_code == 409
    assert resp.json() == {"detail": {"code": "account_exists", "name": "Mei"}}
    assert store.user(2) is not None
    resp = client.post("/api/auth/apple", headers={"cookie": cookie}, json={**body, "confirm": True})
    assert resp.status_code == 200 and resp.json()["name_shown"] == "Mei"
    assert store.user(2) is None and store.user(target)["apple_sub"] == "apple-old"


_RSA = None


def _apple(monkeypatch):
    """Apple's keys mocked against the module's RSA key; the network refused."""
    global _RSA
    from cryptography.hazmat.primitives.asymmetric import rsa
    from shengji.api import accounts, apple_auth
    from tests import test_apple_signin as ta

    if _RSA is None:
        _RSA = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nums = _RSA.public_key().public_numbers()
    jwks = {"keys": [{"kty": "RSA", "kid": ta.KID, "use": "sig", "alg": "RS256",
                      "n": ta._b64(nums.n), "e": ta._b64(nums.e)}]}
    monkeypatch.setattr(apple_auth, "KEYS", accounts.GoogleCerts(
        fetch=lambda: (apple_auth.jwks_to_pem(jwks), 3600.0)))
    fake = ta.FakeApple()
    monkeypatch.setattr(apple_auth, "post_form", fake)
    for name in ("APPLE_SIGNIN_KEY", "APPLE_KEY_ID", "APPLE_TEAM_ID"):
        monkeypatch.delenv(name, raising=False)
    return apple_auth, fake


# --------------------------------------------------- conflict and merge
# Every ``users`` column but ``last_seen_at``, which a session's use writes.
USERS_BUT_SEEN = ("SELECT id, google_sub, apple_sub, email, name, picture, created_at, "
                  "last_login_at, display_name, rating, rated_rounds, leaderboard_visible, "
                  "suspended_at FROM users ORDER BY id")


def _existing(store, sub="g-old", name="Mei Lin"):
    """A Google account with a rated round, a game and a block of its own."""
    from shengji.api import ratings

    uid = store.upsert_user(_claims(sub=sub, name=name))["id"]
    store.set_display_name(uid, name.split()[0])
    ratings.apply_round(store, _record("old/1", 1, {0: uid}, winner_team=1))
    store.link_seat(_game("old"), uid, 0, 1)
    return uid


def test_a_taken_identity_answers_409_with_the_name_only_and_changes_nothing(
        linking, client, keypair):  # noqa: F811
    store = linking.STORE
    target = _existing(store)
    _token, cookie, _user = _device(client)
    snapshot = _rows(store, USERS_BUT_SEEN)
    sessions = _rows(store, "SELECT COUNT(*) FROM sessions")
    resp = _google(client, keypair, cookie=cookie, sub="g-old")
    assert resp.status_code == 409
    assert resp.json() == {"detail": {"code": "account_exists", "name": "Mei"}}
    assert "set-cookie" not in resp.headers
    assert _rows(store, USERS_BUT_SEEN) == snapshot
    assert _rows(store, "SELECT COUNT(*) FROM sessions") == sessions
    assert store.user(target)["google_sub"] == "g-old"


def test_a_confirmed_merge_moves_games_drops_the_device_rating_and_deletes_it(
        linking, client, keypair):  # noqa: F811
    from shengji.api import ratings

    store = linking.STORE
    target = _existing(store)
    target_before = store.user(target)
    token, cookie, _user = _device(client)
    device = 2
    other = store.upsert_user(_claims(sub="g-other", name="Other Person"))["id"]
    # The device account: two rated rounds, two games (one shared with the
    # other player, one still open), a block it made and one made of it.
    ratings.apply_round(store, _record("a/1", 1, {0: device, 1: other}))
    ratings.apply_round(store, _record("b/1", 1, {0: device}))
    other_rating = store.user(other)["rating"]
    store.link_seat(_game("a", last_round=3), device, 0, 1)
    store.close_link("a", device, 0, 2)
    store.link_seat(_game("a", last_round=3), other, 1, 1)
    store.link_seat(_game("b", last_round=4), device, 2, 1)
    store.set_block(device, other, True)
    store.set_block(other, device, True)

    resp = _google(client, keypair, cookie=cookie, confirm=True, sub="g-old")
    assert resp.status_code == 200
    assert resp.json()["name_shown"] == "Mei"
    assert store.user(device) is None and device in store.deleted_ids
    after = store.user(target)
    assert (after["rating"], after["rated_rounds"]) == (
        target_before["rating"], target_before["rated_rounds"])
    assert store.user(other)["rating"] == other_rating          # others untouched
    links = sorted(_rows(store, "SELECT game_id, user_id, seat, from_round, to_round "
                                "FROM game_players"))
    assert links == sorted([("a", other, 1, 1, None), ("a", target, 0, 1, 2),
                            ("b", target, 2, 1, 4), ("old", target, 0, 1, None)])
    assert sorted(g["id"] for g in store.list_games(target)) == ["a", "b", "old"]
    assert _rows(store, "SELECT blocker_id, blocked_id FROM blocks") == [(target, other)]
    assert _rows(store, "SELECT COUNT(*) FROM rating_events WHERE user_id = ?", (device,)) \
        == [(0,)]
    assert _rows(store, "SELECT COUNT(*) FROM device_credentials") == [(0,)]
    assert _rows(store, "SELECT COUNT(*) FROM sessions WHERE user_id = ?", (device,)) == [(0,)]
    # The old device session and credential are dead; the new session is Mei's.
    assert client.get("/api/me", headers={"cookie": cookie}).status_code == 401
    assert client.post("/api/auth/device",
                       headers={**APP, "authorization": f"Device {token}"}).status_code == 401
    assert client.get("/api/me", headers={"cookie": _cookie(resp)}).json()["name_shown"] == "Mei"
    _check_rating_ledger(store)


def test_a_merge_detaches_the_device_from_live_seats(linking, client, keypair):  # noqa: F811
    from shengji.api import server as srv

    store = linking.STORE
    _existing(store)
    _token, cookie, _user = _device(client)
    room = srv.Room(code="MRGE")
    room.seats = [srv.Seat(name="Dev", user_id=2, connected=True)] + [
        srv.Seat(name=f"Bot {i}", is_bot=True) for i in range(1, 4)]
    srv.rooms["MRGE"] = room
    try:
        assert _google(client, keypair, cookie=cookie, confirm=True,
                       sub="g-old").status_code == 200
        assert room.seats[0].user_id is None
    finally:
        srv.rooms.pop("MRGE", None)


def test_a_suspended_holder_refuses_the_link(linking, client, keypair):  # noqa: F811
    store = linking.STORE
    target = _existing(store)
    store.set_suspended(target, True)
    _token, cookie, _user = _device(client)
    for confirm in (None, True):
        resp = _google(client, keypair, cookie=cookie, confirm=confirm, sub="g-old")
        assert resp.status_code == 403
    assert store.user(2) is not None and store.user(2)["google_sub"] is None


def test_a_provider_session_signing_in_elsewhere_is_unchanged(linking, client, keypair):  # noqa: F811
    store = linking.STORE
    _existing(store)
    first = _google(client, keypair, sub="g-first", name="First Person")
    resp = _google(client, keypair, cookie=_cookie(first), sub="g-old")
    assert resp.status_code == 200 and resp.json()["name_shown"] == "Mei"
    assert _rows(store, "SELECT COUNT(*) FROM users") == [(2,)]


def test_with_the_flag_off_a_device_session_signs_in_as_before(
        linking, client, keypair, monkeypatch):  # noqa: F811
    store = linking.STORE
    _existing(store)
    _token, cookie, _user = _device(client)
    monkeypatch.delenv("SHENGJI_DEVICE_ACCOUNTS")
    resp = _google(client, keypair, cookie=cookie, sub="g-old")
    assert resp.status_code == 200 and resp.json()["name_shown"] == "Mei"
    assert store.user(2) is not None                 # left alone, not merged


def test_the_merge_writes_wait_for_queued_link_writes(linking):
    """``after_link_writes`` runs behind every link write already queued."""
    import asyncio

    from shengji.api import saved_games

    order = []
    gate = __import__("threading").Event()

    async def main():
        loop = asyncio.get_running_loop()
        first = loop.run_in_executor(saved_games._EXECUTOR,
                                     lambda: (gate.wait(5), order.append("queued")))
        second = asyncio.ensure_future(saved_games.after_link_writes(order.append, "merge"))
        await asyncio.sleep(0.05)
        assert order == []
        gate.set()
        await first
        await second

    asyncio.run(main())
    assert order == ["queued", "merge"]


# ------------------------------------------------ names of new accounts
def test_a_new_provider_account_with_a_taken_name_gets_the_smallest_free_number(
        linking, client, keypair):  # noqa: F811
    store = linking.STORE
    store.upsert_user(_claims(sub="g-1", name="Jerry Yu"))         # shows "Jerry"
    store.upsert_user(_claims(sub="g-2", name="Jerry Two"))
    store.set_display_name(2, "jerry 2")                        # case-insensitive
    resp = _google(client, keypair, sub="g-3", name="Jerry Three")
    assert resp.json()["name_shown"] == "Jerry 3"
    # A returning account is never renamed, even when its name now collides.
    store.set_display_name(1, None)
    assert _google(client, keypair, sub="g-1").json()["name_shown"] == "Jerry"
    assert store.user(2)["display_name"] == "jerry 2"


def test_numbered_names_fit_and_pass_the_rules(linking):
    accounts = linking
    assert accounts._numbered_name("A" * 20, {"a" * 20}) == "A" * 18 + " 2"
    # "Bot <n>" is reserved for every n: a generated name instead.
    fallback = accounts._numbered_name("Bot", {"bot"}, random.Random(1))
    assert accounts.validate_display_name(fallback) == fallback and " " in fallback
    assert not fallback.lower().startswith("bot")


def test_an_apple_account_with_a_taken_name_is_numbered(linking):
    store = linking.STORE
    store.upsert_user(_claims(sub="g-1", name="Ana Smith"))
    assert accounts_name(store.upsert_apple_user("a-1", None, "Ana Jones")) == "Ana 2"
    assert accounts_name(store.upsert_apple_user("a-2", None, None)) == ""   # no name to clash


def test_names_are_left_alone_with_the_flag_off(linking, monkeypatch):
    monkeypatch.delenv("SHENGJI_DEVICE_ACCOUNTS")
    store = linking.STORE
    store.upsert_user(_claims(sub="g-1", name="Ana Smith"))
    assert store.upsert_user(_claims(sub="g-2", name="Ana Jones"))["display_name"] is None


def accounts_name(row):
    from shengji.api import accounts

    return accounts.effective_name(row)


# --------------------------------------------------- sign out and delete
def test_sign_out_with_the_credential_removes_it(linking, client, keypair):  # noqa: F811
    store = linking.STORE
    token, cookie, _user = _device(client)
    linked = _google(client, keypair, cookie=cookie, sub="g-new")
    other_token, _c, _u = _device(client)
    # Another account's credential is never removed by this sign-out.
    resp = client.post("/api/auth/logout", headers={
        "cookie": _cookie(linked), "authorization": f"Device {other_token}"})
    assert resp.status_code == 200
    assert _rows(store, "SELECT COUNT(*) FROM device_credentials") == [(2,)]
    again = client.post("/api/auth/device", headers={**APP, "authorization": f"Device {token}"})
    resp = client.post("/api/auth/logout", headers={
        "cookie": _cookie(again), "authorization": f"Device {token}"})
    assert resp.status_code == 200
    assert client.post("/api/auth/device",
                       headers={**APP, "authorization": f"Device {token}"}).status_code == 401
    assert store.user(1)["google_sub"] == "g-new"            # the account stays
    # A malformed header still signs out.
    third = _google(client, keypair, sub="g-new")
    assert client.post("/api/auth/logout", headers={
        "cookie": _cookie(third), "authorization": "Bearer x"}).status_code == 200
    assert client.get("/api/me", headers={"cookie": _cookie(third)}).status_code == 401


def test_deleting_a_device_account_removes_everything_it_owns_and_nothing_else(
        linking, client):
    from shengji.api import ratings

    store = linking.STORE
    token, cookie, _user = _device(client)
    other = store.upsert_user(_claims(sub="g-other", name="Other Person"))["id"]
    ratings.apply_round(store, _record("a/1", 1, {0: 1, 1: other}))
    store.link_seat(_game("a"), 1, 0, 1)
    store.link_seat(_game("a"), other, 1, 1)
    store.link_seat(_game("solo"), 1, 0, 1)
    store.set_block(1, other, True)
    store.set_block(other, 1, True)
    other_before = store.user(other)
    assert client.delete("/api/me", headers={"cookie": cookie}).status_code == 204
    for table in ("sessions", "device_credentials", "rating_events", "game_players"):
        assert _rows(store, f"SELECT COUNT(*) FROM {table} WHERE user_id = 1") == [(0,)], table
    assert _rows(store, "SELECT COUNT(*) FROM blocks") == [(0,)]
    assert _rows(store, "SELECT id FROM games ORDER BY id") == [("a",)]
    assert store.user(other) == other_before
    assert _rows(store, "SELECT COUNT(*) FROM rating_events WHERE user_id = ?", (other,)) \
        == [(1,)]
    assert client.post("/api/auth/device",
                       headers={**APP, "authorization": f"Device {token}"}).status_code == 401


# ------------------------------------------------- the lifecycle property
SEQUENCES = int(os.environ.get("SHENGJI_U2_SEQUENCES", "1000"))
SEED = 20261122
GOOGLE_SUBS = ("g-a", "g-b", "g-c")
APPLE_SUBS = ("a-a", "a-b")
CHILD_TABLES = ("sessions", "device_credentials", "rating_events", "game_players",
                "apple_tokens")


class Lifecycle:
    """One random sequence of account operations against one store, with
    what the test expects to have happened kept beside it."""

    def __init__(self, store, rng: random.Random, db: sqlite3.Connection):
        self.store, self.rng, self.db = store, rng, db
        self.sessions: dict[str, int] = {}           # live-looking session -> account
        self.credentials: dict[str, int] = {}        # device credential -> account
        self.deleted: set[int] = set()
        self.owner: dict[str, int] = {}              # provider sub -> account
        self.games = 0
        self.rounds = 0

    def q(self, sql, args=()):
        return self.db.execute(sql, args).fetchall()

    def live(self) -> list[int]:
        return [r[0] for r in self.q("SELECT id FROM users ORDER BY id")]

    def token(self) -> str:
        return "".join(self.rng.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(43))

    def device_sessions(self) -> list[tuple[str, int]]:
        devices = {r[0] for r in self.q(
            "SELECT id FROM users WHERE google_sub IS NULL AND apple_sub IS NULL")}
        return [(s, u) for s, u in self.sessions.items() if u in devices]

    # -- operations
    def create(self):
        token = self.token()
        row, session = self.store.create_device_account(token, rng=self.rng)
        self.credentials[token] = row["id"]
        self.sessions[session] = row["id"]

    def provider_sign_in(self):
        provider = self.rng.choice(("google", "apple"))
        sub = self.rng.choice(GOOGLE_SUBS if provider == "google" else APPLE_SUBS)
        if provider == "google":
            row = self.store.upsert_user(_claims(sub=sub, name=f"Person {sub}"), unique_name=True)
        else:
            row = self.store.upsert_apple_user(sub, None, f"Person {sub}", unique_name=True)
        assert self.owner.setdefault(sub, row["id"]) == row["id"]
        self.sessions[self.store.create_session(row["id"])] = row["id"]

    def link(self):
        candidates = self.device_sessions()
        if not candidates:
            return
        session, device = self.rng.choice(candidates)
        provider = self.rng.choice(("google", "apple"))
        sub = self.rng.choice(GOOGLE_SUBS if provider == "google" else APPLE_SUBS)
        confirm = self.rng.random() < 0.6
        before = self.store.user(device)
        target = self.owner.get(sub)
        target_before = self.store.user(target) if target is not None else None
        games_before = {r[0] for r in self.q(
            "SELECT game_id FROM game_players WHERE user_id IN (?, ?)",
            (device, target if target is not None else -1))}
        users_before = self.q("SELECT * FROM users ORDER BY id")
        out = self.store.link_provider(device, provider, sub, {"name": f"Person {sub}"}, confirm)
        if target is None:
            assert out["outcome"] == "linked"
            after = self.store.user(device)
            assert (after["rating"], after["rated_rounds"], after["display_name"]) == (
                before["rating"], before["rated_rounds"], before["display_name"])
            self.owner[sub] = device
            self.sessions[out["session"]] = device
        elif not confirm:
            assert out == {"outcome": "conflict",
                           "name": accounts_name(target_before) or "Player"}
            assert self.q("SELECT * FROM users ORDER BY id") == users_before
        else:
            assert out["outcome"] == "merged" and out["user"]["id"] == target
            assert self.store.user(device) is None
            after = self.store.user(target)
            assert (after["rating"], after["rated_rounds"]) == (
                target_before["rating"], target_before["rated_rounds"])
            games_after = {r[0] for r in self.q(
                "SELECT game_id FROM game_players WHERE user_id = ?", (target,))}
            assert games_after == games_before
            self.forget(device)
            self.sessions[out["session"]] = target

    def sign_out(self):
        if not self.sessions:
            return
        session = self.rng.choice(sorted(self.sessions))
        uid = self.sessions.pop(session)
        mine = [t for t, u in self.credentials.items() if u == uid]
        token = self.rng.choice(mine) if mine and self.rng.random() < 0.5 else None
        self.store.sign_out(session, token)
        if token is not None:
            del self.credentials[token]
        assert self.store.session_user(session) is None

    def delete(self):
        live = self.live()
        if not live:
            return
        uid = self.rng.choice(live)
        assert self.store.delete_user(uid)
        self.forget(uid)

    def forget(self, uid):
        self.deleted.add(uid)
        for table in (self.sessions, self.credentials, self.owner):
            for key in [k for k, v in table.items() if v == uid]:
                del table[key]

    def play(self):
        from shengji.api import ratings

        live = self.live()
        if not live:
            return
        seated = self.rng.sample(live, min(len(live), self.rng.randint(1, 4)))
        seats = dict(zip(self.rng.sample(range(4), len(seated)), seated))
        self.games += 1
        game_id = f"G{self.games}"
        for seat, uid in seats.items():
            self.store.link_seat(_game(game_id, last_round=1), uid, seat, 1)
        for round_no in range(1, self.rng.randint(1, 3) + 1):
            self.store.record_round_start(game_id, round_no)
            ratings.apply_round(self.store, _record(
                f"{game_id}/1", round_no, seats, winner_team=self.rng.randint(0, 1),
                level_change=self.rng.randint(-1, 3)))
            self.rounds += 1
        if self.rng.random() < 0.5:
            seat, uid = self.rng.choice(sorted(seats.items()))
            self.store.close_link(game_id, uid, seat, 1)

    def block(self):
        live = self.live()
        if len(live) >= 2:
            a, b = self.rng.sample(live, 2)
            self.store.set_block(a, b, True)

    def reauth(self):
        if self.credentials and self.rng.random() < 0.7:
            token = self.rng.choice(sorted(self.credentials))
            row, session = self.store.device_sign_in(token)
            assert row["id"] == self.credentials[token]
            self.sessions[session] = row["id"]
        for session, uid in list(self.sessions.items()):
            row = self.store.session_user(session)
            assert row is not None and row["id"] == uid

    OPS = (("create", 4), ("provider_sign_in", 2), ("link", 4), ("sign_out", 1),
           ("delete", 1), ("play", 4), ("block", 1), ("reauth", 2))

    def step(self):
        names = [n for n, _ in self.OPS]
        weights = [w for _, w in self.OPS]
        getattr(self, self.rng.choices(names, weights)[0])()

    # -- invariants
    def check(self):
        store = self.store
        for column in ("google_sub", "apple_sub"):
            assert self.q(f"SELECT {column} FROM users WHERE {column} IS NOT NULL "
                                f"GROUP BY {column} HAVING COUNT(*) > 1") == []
        held = {sub: uid for sub, uid in self.q(
            "SELECT google_sub, id FROM users WHERE google_sub IS NOT NULL "
                   "UNION ALL SELECT apple_sub, id FROM users WHERE apple_sub IS NOT NULL")}
        assert held == self.owner
        _check_rating_ledger(store, lambda _s, sql, args=(): self.q(sql, args))
        live = set(self.live())
        assert not (live & self.deleted)
        for table in CHILD_TABLES:
            owners = {r[0] for r in self.q(f"SELECT DISTINCT user_id FROM {table}")}
            assert owners <= live, table
        blockers = {u for r in self.q("SELECT blocker_id, blocked_id FROM blocks") for u in r}
        assert blockers <= live
        assert self.q("SELECT COUNT(*) FROM games g WHERE NOT EXISTS ("
                            "SELECT 1 FROM game_players p WHERE p.game_id = g.id)") == [(0,)]
        assert self.q("PRAGMA foreign_key_check") == []
        for token, uid in self.credentials.items():
            assert self.q("SELECT user_id FROM device_credentials WHERE token_hash = ?",
                         (_hash(token),)) == [(uid,)]


def _hash(token):
    from shengji.api import accounts

    return accounts._hash_token(token)


def test_the_account_lifecycle_keeps_its_invariants(linking):
    """U2: ``SEQUENCES`` random sequences (``SHENGJI_U2_SEQUENCES``, 1,000
    by default; the bar is 10,000) of create, provider sign-in, link with
    and without confirm, sign out, delete, rated rounds, blocks and
    re-authentication, each on an emptied store, checked after every step."""
    store = linking.STORE
    totals = {"links": 0, "merges": 0, "conflicts": 0, "rounds": 0}
    real = store.link_provider

    def counted(*args, **kwargs):
        out = real(*args, **kwargs)
        key = {"linked": "links", "merged": "merges", "conflict": "conflicts"}.get(out["outcome"])
        if key:
            totals[key] += 1
        return out

    store.link_provider = counted
    db = sqlite3.connect(store.path, isolation_level=None)
    for i in range(SEQUENCES):
        with closing(store._open()) as conn:
            conn.execute("DELETE FROM users")
            conn.execute("DELETE FROM games")
        rng = random.Random(SEED + i)
        life = Lifecycle(store, rng, db)
        try:
            for _ in range(rng.randint(5, 25)):
                life.step()
                life.check()
        except AssertionError as exc:
            raise AssertionError(f"sequence {i} (seed {SEED + i}) broke an invariant") from exc
        totals["rounds"] += life.rounds
    db.close()
    # The sequences reached every path, so a pass is not vacuous.
    assert min(totals.values()) > SEQUENCES // 20, totals
    print(f"U2: {SEQUENCES} sequences, {totals}")
