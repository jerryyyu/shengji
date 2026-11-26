"""The equipped companion look (``accounts.LOOKS``): its default, its storage
on an account, the snapshot taken before a migration, and where it travels
(``/api/me``, each seat of a frame, each leaderboard row)."""
from __future__ import annotations

import time

import pytest

from tests.test_accounts import (  # noqa: F401
    V1_SCHEMA, _claims, _columns, _session_cookie, accounts_on, accounts_sqlite, keypair)
from tests.test_ratings import _rounds_at, env  # noqa: F401
from tests.test_server_ws import _drain, client  # noqa: F401


def test_the_default_look_and_what_parses(accounts_on):
    a = accounts_on
    assert a.DEFAULT_LOOK == "tractor/red"
    assert a.parse_look("tractor/red") == ("tractor", "red")
    assert a.parse_look("tractor/green") == ("tractor", "green")
    for bad in ("tractor/mauve", "goat/mauve", "dragon/jade", "tractor", "", None, 3, "tractor/red/x"):
        assert a.parse_look(bad) is None
    assert a.look_id(None) == "tractor/red"
    assert a.look_id({"look_companion": None, "look_colour": None}) == "tractor/red"
    # a stored look no longer offered falls back to the default
    assert a.look_id({"look_companion": "dragon", "look_colour": "jade"}) == "tractor/red"
    assert a.account_look(None) == "tractor/red"


def test_a_new_account_has_the_default_and_put_persists_it(accounts_on, keypair, client, monkeypatch):
    monkeypatch.setenv("COLLECTION_ACCOUNTS", "1")
    private_pem, _ = keypair
    cookie = _session_cookie(accounts_on, client, private_pem)
    session = {"cookie": cookie}
    assert client.get("/api/me", headers=session).json()["look"] == "tractor/red"
    assert client.put("/api/me/look", json={"look": "tractor/red"}).status_code == 401
    assert client.put("/api/me/look", json={"look": "dragon/jade"}, headers=session).status_code == 400
    resp = client.put("/api/me/look", json={"look": "tractor/red"}, headers=session)
    assert resp.status_code == 200 and resp.json()["look"] == "tractor/red"
    row = accounts_on.STORE.user(1)
    assert (row["look_companion"], row["look_colour"]) == ("tractor", "red")
    # a fresh store on the same file reads it back
    again = accounts_on.Store(accounts_on.STORE.path).user(1)
    assert accounts_on.look_id(again) == "tractor/red"


def test_seats_carry_the_look_and_bots_carry_none(accounts_on, keypair, client):
    private_pem, _ = keypair
    cookie = _session_cookie(accounts_on, client, private_pem)
    with client.websocket_connect("/ws", headers={"cookie": cookie}) as a:
        a.send_json({"type": "create_room"})
        room = _drain(a, "room")
        assert room["players"][0]["look"] == "tractor/red"
        assert accounts_on.STORE.seen_looks == {1: "tractor/red"}    # learnt at the handshake
        st = _drain(a, "state")             # the game starts at once, bots seated
        looks = {p["seat"]: p["look"] for p in st["players"]}
        assert looks == {0: "tractor/red", 1: None, 2: None, 3: None}
    # a guest seat shows the default, from no stored row
    with client.websocket_connect("/ws") as g:
        g.send_json({"type": "create_room", "name": "Guest"})
        assert _drain(g, "room")["players"][0]["look"] == "tractor/red"


def test_a_room_table_frame_gives_each_person_a_look(accounts_on, client):
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as g:
        g.send_json({"type": "create_room", "name": "Guest"})
        code = _drain(g, "room")["room"]
    frame = srv.room_table_frame(srv.rooms[code], 0)
    assert [s["look"] for s in frame["seats"]] == ["tractor/red", None, None, None]


def test_leaderboard_rows_carry_the_look(env):
    from shengji.api import ratings

    _srv, store, _ = env
    a = store.upsert_user(_claims(sub="a1", email="a@example.com", name="Ann"))
    b = store.upsert_user(_claims(sub="b1", email="b@example.com", name="Bo"))
    store.set_look(b["id"], "tractor", "red")
    now = time.time()
    _rounds_at(store, a["id"], [now - 60])
    _rounds_at(store, b["id"], [now - 30])
    board = ratings.leaderboard(store, "all", a["id"], now=now)
    assert {r["look"] for r in board["players"]} == {"tractor/red"}
    assert board["me"]["look"] == "tractor/red"
    assert "look_companion" not in board["players"][0]


def test_an_old_database_is_snapshotted_once_before_it_migrates(accounts_on, tmp_path):
    path = tmp_path / "old" / "accounts.sqlite3"
    path.parent.mkdir()
    with accounts_sqlite(path) as db:
        db.executescript(V1_SCHEMA)
    store = accounts_on.Store(path)
    assert store.schema_version() == len(accounts_on.SCHEMA)
    assert {"look_companion", "look_colour"} <= set(_columns(path, "users"))
    backup = store.backup_path(1)
    assert backup.exists()
    # the copy is the database as it stood: version 1, its row, no look columns
    with accounts_sqlite(backup) as db:
        assert db.execute("SELECT MAX(version) FROM schema_version").fetchone() == (1,)
        assert db.execute("SELECT name FROM users").fetchall() == [("Old Timer",)]
    assert "look_companion" not in _columns(backup, "users")
    # an up-to-date database takes no copy, and a brand-new one none either
    accounts_on.Store(path).schema_version()
    assert sorted(p.name for p in path.parent.iterdir() if p.name.endswith(".bak")) == [backup.name]
    fresh = accounts_on.Store(tmp_path / "new" / "accounts.sqlite3")
    fresh.schema_version()
    assert not any(p.name.endswith(".bak") for p in fresh.path.parent.iterdir())


def test_the_look_migration_reruns_and_keeps_rows(accounts_on, tmp_path):
    path = tmp_path / "old" / "accounts.sqlite3"
    path.parent.mkdir()
    with accounts_sqlite(path) as db:
        db.executescript(V1_SCHEMA)
    store = accounts_on.Store(path)
    assert accounts_on.look_id(store.user(1)) == "tractor/red"
    with accounts_sqlite(path) as db:
        db.row_factory = accounts_on.sqlite3.Row
        accounts_on._migrate_v11(db)
    assert _columns(path, "users").count("look_colour") == 1


def test_the_web_client_draws_the_same_default(accounts_on):
    """``web/src/companion/look.ts`` mirrors the default by hand."""
    import re
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / "web" / "src" / "companion" / "look.ts").read_text()
    found = dict(re.findall(r'^export const (DEFAULT_COMPANION|DEFAULT_COLOUR) = "([^"]+)";', text, re.M))
    assert found == {"DEFAULT_COMPANION": accounts_on.DEFAULT_COMPANION,
                     "DEFAULT_COLOUR": accounts_on.DEFAULT_COLOUR}
    unlocks = {look: (count, int(of)) for look, count, of in re.findall(
        r'^  "([a-z]+/[a-z]+)": \{ count: "([a-z_]+)", of: (\d+) \},$', text, re.M)}
    assert unlocks == accounts_on.LOOK_UNLOCKS
    palette = (Path(__file__).resolve().parents[2] / "web" / "src" / "companion" / "palette.ts").read_text()
    colours = re.findall(r"^  ([a-z]+): \{ body:", palette, re.M)
    assert tuple(colours) == accounts_on.LOOKS["tractor"]
    store = (Path(__file__).resolve().parents[2] / "web" / "src" / "companion" / "storePalette.ts").read_text()
    for kind in ("bun", "chick", "sparrow"):
        table = re.search(rf"^export const {kind.upper()}_COLOURS = \{{\n(.*?)^\}} as const", store, re.M | re.S)
        assert tuple(re.findall(r"^  ([a-z]+): \{", table.group(1), re.M)) == accounts_on.LOOKS[kind]
    modes = re.search(r"^export const COMPANION_MODES = \[([^\]]*)\] as const;", text, re.M)
    assert tuple(re.findall(r'"([a-z]+)"', modes.group(1))) == accounts_on.COMPANION_MODES


def test_the_catalogue_lists_free_and_earned_colours(accounts_on):
    a = accounts_on
    fresh = {e["id"]: e for e in a.look_catalogue({"rounds": 0, "ranked_wins": 0, "ranked_games": 0})}
    assert list(fresh)[0] == a.DEFAULT_LOOK and len(fresh) >= 6
    assert [k for k, e in fresh.items() if e["unlocked"] and k.startswith("tractor/")] == [
        "tractor/red", "tractor/green", "tractor/blue"]
    assert {k: e["needs"] for k, e in fresh.items() if e["needs"]} == {
        "tractor/yellow": {"count": "ranked_games", "of": 10}, "tractor/orange": {"count": "ranked_games", "of": 25},
        "tractor/jade": {"count": "ranked_games", "of": 50}, "tractor/porcelain": {"count": "ranked_games", "of": 100},
        "tractor/ink": {"count": "ranked_games", "of": 1000}}
    # rounds played and rounds won unlock nothing now: only ranked games won do
    many = {e["id"]: e["unlocked"] for e in a.look_catalogue({"rounds": 500, "ranked_wins": 300, "ranked_games": 0})}
    assert not any(many[k] for k in ("tractor/yellow", "tractor/ink"))
    played = {e["id"]: e["unlocked"] for e in a.look_catalogue({"ranked_games": 25})}
    assert played["tractor/yellow"] and played["tractor/orange"]
    assert not played["tractor/jade"] and not played["tractor/porcelain"] and not played["tractor/ink"]
    # in Collection order, each colour asks for more than the one before
    needs = [e["needs"]["of"] for e in a.look_catalogue({}) if e["needs"]]
    assert needs == sorted(needs) == [10, 25, 50, 100, 1000]
    # an equipped look stays unlocked when its count falls short
    kept = {e["id"]: e["unlocked"] for e in a.look_catalogue({"ranked_games": 0}, "tractor/porcelain")}
    assert kept["tractor/porcelain"]


def _games_won(store, uid, n, rounds=3):
    """`n` ranked games won, each its last of `rounds` won rated rounds, plus a won round of a game lost."""
    with store._open() as conn:
        for g in range(n):
            for r in range(rounds):
                conn.execute(
                    """INSERT INTO rating_events(game_id, round_no, user_id, created_at, team, banker_team, won,
                           levels, game_won, expected, actual, k, rating_before, rating_after, delta)
                       VALUES (?, ?, ?, ?, 0, 1, 1, 1, ?, 0.5, 1, 20, 1000, 1003, 3)""",
                    (f"g{g}", r + 1, uid, time.time() - 600, 1 if r == rounds - 1 else 0))
        conn.execute(
            """INSERT INTO rating_events(game_id, round_no, user_id, created_at, team, banker_team, won,
                   levels, game_won, expected, actual, k, rating_before, rating_after, delta)
               VALUES ('lost', 1, ?, ?, 0, 1, 1, 1, 0, 0.5, 1, 20, 1000, 1003, 3)""", (uid, time.time() - 600))


def test_ranked_games_counts_games_won_not_rounds(accounts_on):
    store = accounts_on.STORE
    uid = store.upsert_user(_claims(sub="sub-games", email="games@example.com"))["id"]
    _games_won(store, uid, 3)
    assert store.ranked_wins(uid) == 10            # every won round
    assert store.ranked_games(uid) == 3            # only the rounds that won a game
    assert accounts_on.Store(store.path).look_progress(uid)["ranked_games"] == 3


def test_a_locked_colour_is_refused_and_unlocks_with_ranked_games(accounts_on, keypair, client, monkeypatch):
    monkeypatch.setenv("COLLECTION_ENABLED", "1")
    private_pem, _ = keypair
    session = {"cookie": _session_cookie(accounts_on, client, private_pem)}
    assert client.put("/api/me/look", json={"look": "tractor/yellow"}, headers=session).status_code == 403
    assert accounts_on.STORE.user(1)["look_colour"] is None
    resp = client.put("/api/me/look", json={"look": "tractor/blue"}, headers=session)
    assert resp.status_code == 200 and resp.json()["look"] == "tractor/blue"
    assert accounts_on.account_look(1) == "tractor/blue"
    _games_won(accounts_on.STORE, 1, 10, rounds=1)
    me = client.get("/api/me", headers=session).json()
    # ten ranked rounds won, each the one that won its game, and one more won round of a game lost
    assert me["ranked_games"] == 10 and me["ranked_wins"] == 11
    unlocked = {e["id"] for e in me["looks"] if e["unlocked"]}
    assert "tractor/yellow" in unlocked and not {"tractor/orange", "tractor/ink"} & unlocked
    resp = client.put("/api/me/look", json={"look": "tractor/yellow"}, headers=session)
    assert resp.status_code == 200 and resp.json()["look"] == "tractor/yellow"
    assert client.put("/api/me/look", json={"look": "tractor/orange"}, headers=session).status_code == 403


def test_an_equipped_colour_no_longer_earned_stays_but_cannot_be_picked_again(accounts_on, keypair, client, monkeypatch):
    monkeypatch.setenv("COLLECTION_ENABLED", "1")
    private_pem, _ = keypair
    session = {"cookie": _session_cookie(accounts_on, client, private_pem)}
    client.get("/api/me", headers=session)
    # chosen under the old rules: jade, with no ranked game won
    accounts_on.STORE.set_look(1, "tractor", "jade")
    me = client.get("/api/me", headers=session).json()
    assert me["look"] == "tractor/jade"
    assert next(e for e in me["looks"] if e["id"] == "tractor/jade")["unlocked"]
    assert client.put("/api/me/look", json={"look": "tractor/jade"}, headers=session).status_code == 200
    assert client.put("/api/me/look", json={"look": "tractor/green"}, headers=session).status_code == 200
    assert client.put("/api/me/look", json={"look": "tractor/jade"}, headers=session).status_code == 403
    assert client.get("/api/me", headers=session).json()["look"] == "tractor/green"


def test_where_companions_show_is_stored_on_the_account(accounts_on, keypair, client, monkeypatch):
    monkeypatch.setenv("COLLECTION_ACCOUNTS", "7, 1")
    private_pem, _ = keypair
    session = {"cookie": _session_cookie(accounts_on, client, private_pem)}
    assert client.get("/api/me", headers=session).json()["companions"] == "individual"
    assert client.put("/api/me/look", json={"companions": "loud"}, headers=session).status_code == 400
    resp = client.put("/api/me/look", json={"companions": "off"}, headers=session)
    assert resp.status_code == 200 and resp.json()["companions"] == "off"
    assert resp.json()["look"] == "tractor/red"           # the look is untouched
    assert client.get("/api/me", headers=session).json()["companions"] == "off"
    both = client.put("/api/me/look", json={"look": "tractor/green", "companions": "individual"},
                      headers=session).json()
    assert (both["look"], both["companions"]) == ("tractor/green", "individual")


def test_the_collection_is_shown_only_to_listed_accounts_unless_on_for_all(accounts_on, keypair, client, monkeypatch):
    monkeypatch.delenv("COLLECTION_ENABLED", raising=False)
    monkeypatch.setenv("COLLECTION_ACCOUNTS", "2, x,")
    private_pem, _ = keypair
    one = {"cookie": _session_cookie(accounts_on, client, private_pem)}
    two = {"cookie": _session_cookie(accounts_on, client, private_pem, sub="222", email="two@example.com")}
    assert client.get("/api/auth/config").json()["collection"] is False
    assert client.get("/api/me", headers=one).json()["features"] == {"collection": False, "store": False}
    assert client.get("/api/me", headers=two).json()["features"] == {"collection": True, "store": False}
    # a listed account equips; any other is told the endpoint is not there
    assert client.put("/api/me/look", json={"look": "tractor/green"}, headers=one).status_code == 404
    assert client.put("/api/me/look", json={"companions": "off"}, headers=one).status_code == 404
    assert accounts_on.STORE.user(1)["look_colour"] is None
    assert client.put("/api/me/look", json={"look": "tractor/green"}, headers=two).json()["look"] == "tractor/green"
    monkeypatch.setenv("COLLECTION_ENABLED", "1")
    assert client.get("/api/auth/config").json()["collection"] is True
    assert client.get("/api/me", headers=one).json()["features"] == {"collection": True, "store": False}
    assert client.put("/api/me/look", json={"look": "tractor/blue"}, headers=one).status_code == 200


def _v1_database(tmp_path):
    path = tmp_path / "old" / "accounts.sqlite3"
    path.parent.mkdir()
    with accounts_sqlite(path) as db:
        db.executescript(V1_SCHEMA)
    return path


def _tables(path):
    with accounts_sqlite(path) as db:
        return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_an_interrupted_backup_is_redone_before_the_migration_retries(accounts_on, tmp_path, monkeypatch):
    path = _v1_database(tmp_path)
    store = accounts_on.Store(path)
    backup = store.backup_path(1)
    real = accounts_on.Store._vacuum_into

    def interrupted(self, conn, target):
        target.write_bytes(b"")          # what a killed VACUUM INTO leaves
        raise accounts_on.sqlite3.OperationalError("interrupted")

    monkeypatch.setattr(accounts_on.Store, "_vacuum_into", interrupted)
    with pytest.raises(accounts_on.sqlite3.OperationalError):
        store.schema_version()
    # nothing migrated, and no backup published under the real name
    with accounts_sqlite(path) as db:
        assert db.execute("SELECT MAX(version) FROM schema_version").fetchone() == (1,)
    assert not backup.exists() or backup.stat().st_size == 0
    monkeypatch.setattr(accounts_on.Store, "_vacuum_into", real)
    retry = accounts_on.Store(path)
    assert retry.schema_version() == len(accounts_on.SCHEMA)
    assert {"users", "sessions", "schema_version"} <= _tables(backup)
    with accounts_sqlite(backup) as db:
        assert db.execute("SELECT MAX(version) FROM schema_version").fetchone() == (1,)
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert not [p for p in path.parent.iterdir() if ".tmp" in p.name]


def test_a_zero_byte_backup_already_in_place_is_replaced_not_trusted(accounts_on, tmp_path):
    path = _v1_database(tmp_path)
    store = accounts_on.Store(path)
    store.backup_path(1).write_bytes(b"")
    assert store.schema_version() == len(accounts_on.SCHEMA)
    assert "users" in _tables(store.backup_path(1))


def test_a_valid_backup_already_in_place_is_kept(accounts_on, tmp_path):
    path = _v1_database(tmp_path)
    store = accounts_on.Store(path)
    backup = store.backup_path(1)
    with accounts_sqlite(path) as db:
        db.execute("VACUUM INTO ?", (str(backup),))
    with accounts_sqlite(backup) as db:
        db.execute("UPDATE users SET name = 'Marked'")
        db.commit()
    assert store.schema_version() == len(accounts_on.SCHEMA)
    with accounts_sqlite(backup) as db:
        assert db.execute("SELECT name FROM users").fetchall() == [("Marked",)]


def test_no_migration_runs_without_a_verified_backup(accounts_on, tmp_path, monkeypatch):
    path = _v1_database(tmp_path)
    monkeypatch.setattr(accounts_on.Store, "_vacuum_into", lambda self, conn, target: target.write_bytes(b"junk"))
    with pytest.raises(accounts_on.sqlite3.DatabaseError):
        accounts_on.Store(path).schema_version()
    with accounts_sqlite(path) as db:
        assert db.execute("SELECT MAX(version) FROM schema_version").fetchone() == (1,)
    assert not accounts_on.Store(path).backup_path(1).exists()


def test_cached_looks_belong_to_their_store(accounts_on, tmp_path, monkeypatch):
    first = accounts_on.Store(tmp_path / "a.sqlite3")
    second = accounts_on.Store(tmp_path / "b.sqlite3")
    monkeypatch.setattr(accounts_on, "STORE", first)
    accounts_on.remember_look({"id": 1, "look_companion": "tractor", "look_colour": "green"})
    assert accounts_on.account_look(1) == "tractor/green"
    monkeypatch.setattr(accounts_on, "STORE", second)
    assert accounts_on.account_look(1) == "tractor/red"


def test_a_seat_left_by_choice_shows_no_portrait(accounts_on, client):
    from shengji.api import server as srv

    with client.websocket_connect("/ws") as g:
        g.send_json({"type": "create_room", "name": "Guest"})
        code = _drain(g, "room")["room"]
        _drain(g, "state")
    room = srv.rooms[code]
    room.seats[0].left_by_choice = True
    assert srv.seat_look(room.seats[0]) is None
    assert srv.state_for(room, 1)["players"][0]["look"] is None
    assert [p["look"] for p in srv.room_json(room, 1)["players"] if p["seat"] == 0] == [None]
    assert srv.room_table_frame(room, 1)["seats"][0]["look"] is None


FREE_LOOKS = [f"{kind}/{colour}" for kind, colours in (
    ("bun", ("plain", "custard", "taro", "peach")),
    ("chick", ("yellow", "cream", "cocoa", "ink")),
    ("sparrow", ("tree", "java", "snow", "oriole"))) for colour in colours]


def test_the_free_companions_parse_and_are_unlocked_from_the_start(accounts_on):
    a = accounts_on
    for look in FREE_LOOKS:
        assert a.parse_look(look) == tuple(look.split("/"))
        assert look not in a.LOOK_UNLOCKS
    fresh = {e["id"]: e for e in a.look_catalogue({"rounds": 0, "ranked_wins": 0, "ranked_games": 0})}
    assert all(fresh[look]["unlocked"] and fresh[look]["needs"] is None for look in FREE_LOOKS)
    for bad in ("bun/red", "chick/jade", "sparrow/plain", "bun/", "sparrow", "chick/yellow/x", "goat/jade"):
        assert a.parse_look(bad) is None


def test_a_free_companion_equips_and_an_unknown_colour_is_refused(accounts_on, keypair, client, monkeypatch):
    monkeypatch.setenv("COLLECTION_ACCOUNTS", "1")
    private_pem, _ = keypair
    session = {"cookie": _session_cookie(accounts_on, client, private_pem)}
    for look in ("bun/custard", "chick/ink", "sparrow/oriole"):
        resp = client.put("/api/me/look", json={"look": look}, headers=session)
        assert resp.status_code == 200 and resp.json()["look"] == look
        assert accounts_on.account_look(1) == look
        assert client.get("/api/me", headers=session).json()["look"] == look
    for bad in ("bun/red", "sparrow/jade", "chick/", "goat/newyear"):
        assert client.put("/api/me/look", json={"look": bad}, headers=session).status_code == 400
    assert accounts_on.account_look(1) == "sparrow/oriole"
