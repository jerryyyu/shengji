"""The equipped companion look (``accounts.LOOKS``): its default, its storage
on an account, the snapshot taken before a migration, and where it travels
(``/api/me``, each seat of a frame, each leaderboard row)."""
from __future__ import annotations

import time

from tests.test_accounts import (  # noqa: F401
    V1_SCHEMA, _claims, _columns, _session_cookie, accounts_on, accounts_sqlite, keypair)
from tests.test_ratings import _rounds_at, env  # noqa: F401
from tests.test_server_ws import _drain, client  # noqa: F401


def test_the_default_look_and_what_parses(accounts_on):
    a = accounts_on
    assert a.DEFAULT_LOOK == "tractor/red"
    assert a.parse_look("tractor/red") == ("tractor", "red")
    assert a.parse_look("tractor/green") == ("tractor", "green")
    for bad in ("tractor/mauve", "goat/jade", "tractor", "", None, 3, "tractor/red/x"):
        assert a.parse_look(bad) is None
    assert a.look_id(None) == "tractor/red"
    assert a.look_id({"look_companion": None, "look_colour": None}) == "tractor/red"
    # a stored look no longer offered falls back to the default
    assert a.look_id({"look_companion": "goat", "look_colour": "jade"}) == "tractor/red"
    assert a.account_look(None) == "tractor/red"


def test_a_new_account_has_the_default_and_put_persists_it(accounts_on, keypair, client):
    private_pem, _ = keypair
    cookie = _session_cookie(accounts_on, client, private_pem)
    session = {"cookie": cookie}
    assert client.get("/api/me", headers=session).json()["look"] == "tractor/red"
    assert client.put("/api/me/look", json={"look": "tractor/red"}).status_code == 401
    assert client.put("/api/me/look", json={"look": "goat/jade"}, headers=session).status_code == 400
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
    accounts_on._SEEN_LOOKS.clear()
    with client.websocket_connect("/ws", headers={"cookie": cookie}) as a:
        a.send_json({"type": "create_room"})
        room = _drain(a, "room")
        assert room["players"][0]["look"] == "tractor/red"
        assert accounts_on._SEEN_LOOKS == {1: "tractor/red"}    # learnt at the handshake
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
    modes = re.search(r"^export const COMPANION_MODES = \[([^\]]*)\] as const;", text, re.M)
    assert tuple(re.findall(r'"([a-z]+)"', modes.group(1))) == accounts_on.COMPANION_MODES


def test_the_catalogue_lists_free_and_earned_colours(accounts_on):
    a = accounts_on
    fresh = {e["id"]: e for e in a.look_catalogue({"rounds": 0, "ranked_wins": 0})}
    assert list(fresh)[0] == a.DEFAULT_LOOK and len(fresh) >= 6
    assert [k for k, e in fresh.items() if e["unlocked"]] == ["tractor/red", "tractor/green", "tractor/blue"]
    assert fresh["tractor/yellow"]["needs"] == {"count": "rounds", "of": 10}
    assert fresh["tractor/ink"]["needs"] == {"count": "ranked_wins", "of": 1}
    played = {e["id"]: e["unlocked"] for e in a.look_catalogue({"rounds": 25, "ranked_wins": 1})}
    assert played["tractor/yellow"] and played["tractor/orange"] and played["tractor/ink"]
    assert not played["tractor/jade"] and not played["tractor/porcelain"]
    # an equipped look stays unlocked when its count falls
    kept = {e["id"]: e["unlocked"] for e in a.look_catalogue({"rounds": 3}, "tractor/yellow")}
    assert kept["tractor/yellow"]


def test_a_locked_colour_is_refused_and_unlocks_with_play(accounts_on, keypair, client):
    private_pem, _ = keypair
    session = {"cookie": _session_cookie(accounts_on, client, private_pem)}
    assert client.put("/api/me/look", json={"look": "tractor/yellow"}, headers=session).status_code == 403
    assert accounts_on.STORE.user(1)["look_colour"] is None
    resp = client.put("/api/me/look", json={"look": "tractor/blue"}, headers=session)
    assert resp.status_code == 200 and resp.json()["look"] == "tractor/blue"
    assert accounts_on.account_look(1) == "tractor/blue"
    store = accounts_on.STORE
    _rounds_at(store, 1, [time.time() - 60 * i for i in range(10)])
    with store._open() as conn:
        conn.execute("UPDATE users SET rated_rounds = 10 WHERE id = 1")
        conn.execute("UPDATE rating_events SET won = 0 WHERE user_id = 1")
    me = client.get("/api/me", headers=session).json()
    assert me["rounds_played"] == 10 and me["ranked_wins"] == 0
    unlocked = {e["id"] for e in me["looks"] if e["unlocked"]}
    assert "tractor/yellow" in unlocked and "tractor/ink" not in unlocked
    resp = client.put("/api/me/look", json={"look": "tractor/yellow"}, headers=session)
    assert resp.status_code == 200 and resp.json()["look"] == "tractor/yellow"
    assert client.put("/api/me/look", json={"look": "tractor/ink"}, headers=session).status_code == 403


def test_where_companions_show_is_stored_on_the_account(accounts_on, keypair, client):
    private_pem, _ = keypair
    session = {"cookie": _session_cookie(accounts_on, client, private_pem)}
    assert client.get("/api/me", headers=session).json()["companions"] == "team"
    assert client.put("/api/me/look", json={"companions": "loud"}, headers=session).status_code == 400
    resp = client.put("/api/me/look", json={"companions": "off"}, headers=session)
    assert resp.status_code == 200 and resp.json()["companions"] == "off"
    assert resp.json()["look"] == "tractor/red"           # the look is untouched
    assert client.get("/api/me", headers=session).json()["companions"] == "off"
    both = client.put("/api/me/look", json={"look": "tractor/green", "companions": "individual"},
                      headers=session).json()
    assert (both["look"], both["companions"]) == ("tractor/green", "individual")
