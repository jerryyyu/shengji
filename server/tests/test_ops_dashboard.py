"""The ops dashboard's in-container aggregate query, against a fixture database.

The fixture is built with the server's own schema (``accounts.Store`` runs every
migration), so a schema change that breaks a dashboard query fails here
instead of on production. The room logs and support files are tiny files in
``tmp_path``.
"""

import hashlib
import importlib.util
import json
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

from shengji.api import accounts

HERE = Path(__file__).resolve().parents[1] / "scripts" / "ops_dashboard"
DAY = 86400
NOW = 1_800_000_000.0
TODAY = NOW - 5 * 3600


def _load(name):
    spec = importlib.util.spec_from_file_location(f"ops_{name}", HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


query = _load("query")
collector = _load("collector")


def _rating(conn, game, rnd, user, at, partner_bot=1, opponents_bots=2, abandoned=0):
    conn.execute(
        """INSERT INTO rating_events(game_id, round_no, user_id, created_at, team, banker_team,
               won, levels, abandoned, expected, actual, k, rating_before, rating_after, delta,
               partner_bot, opponents_bots)
           VALUES (?, ?, ?, ?, 0, 0, 1, 1, ?, 0.5, 0.6, 32, 1000, 1003, 3, ?, ?)""",
        (game, rnd, user, at, abandoned, partner_bot, opponents_bots))


def _round_start(t, bots, rnd=1, **extra):
    players = [{"seat": i, "name": f"p{i}", "is_bot": b} for i, b in enumerate(bots)]
    return json.dumps({"t": t, "room": "ROOM", "round": rnd, "e": "round_start",
                       "deck": list(range(60)), "players": players, **extra})


def _store(data):
    store = accounts.Store(data / "accounts.sqlite3")
    store.schema_version()                      # runs every migration
    return sqlite3.connect(data / "accounts.sqlite3")


@pytest.fixture
def world(tmp_path):
    data = tmp_path / "data"
    rs = _round_start
    lines = [
        rs(NOW - 2 * DAY, [False, True, True, True]),           # G2 round 1
        rs(NOW - 3000, [False, False, True, True]),             # G3 round 1
        rs(NOW - 600, [False, False, False, True], rnd=2),      # G3 round 2, live: 3 humans
        rs(NOW - 400, [False, True, True, True], training_excluded=True),
        json.dumps({"t": NOW - 300, "room": "ROOM", "round": 1, "e": "play", "seat": 0}),
        "not json",
    ]
    offsets = {"G1": None, "G2": 0, "G3": len(lines[0]) + 1}
    conn = _store(data)
    users = [  # (google_sub, apple_sub, created_at)
        ("g1", None, NOW - 40 * DAY),
        ("g2", None, NOW - 10 * DAY),
        (None, "a1", NOW - 3 * DAY),
        ("g3", None, NOW - 3600),
        ("g4", None, NOW - 9 * DAY),            # signed up, never played
    ]
    for g, a, created in users:
        conn.execute("INSERT INTO users(google_sub, apple_sub, email, created_at, last_login_at)"
                     " VALUES (?, ?, 'x@example.com', ?, ?)", (g, a, created, created))
    for gid, started, last in (("G1", NOW - 20 * DAY, 3), ("G2", NOW - 2 * DAY, 2),
                               ("G3", NOW - 3600, 4)):
        conn.execute("INSERT INTO games(id, room_code, log_file, log_offset, started_at, last_round)"
                     " VALUES (?, 'ROOM', 'ROOM.jsonl', ?, ?, ?)", (gid, offsets[gid], started, last))
    for gid, uid, seat, frm, to in (("G1", 1, 0, 1, None), ("G2", 2, 0, 1, None),
                                    ("G2", 3, 2, 2, None), ("G3", 2, 0, 1, 2), ("G3", 4, 1, 1, None)):
        conn.execute("INSERT INTO game_players(game_id, user_id, seat, from_round, to_round)"
                     " VALUES (?, ?, ?, ?, ?)", (gid, uid, seat, frm, to))
    # G2 round 1: one human; G3 round 1: two accounts at one table; G3 round 2 abandoned.
    _rating(conn, "G2", 1, 2, NOW - 2 * DAY)
    _rating(conn, "G3", 1, 2, NOW - 3000, partner_bot=1, opponents_bots=1)
    _rating(conn, "G3", 1, 4, NOW - 3000, partner_bot=1, opponents_bots=1)
    _rating(conn, "G3", 2, 2, NOW - 2000, abandoned=1)
    conn.commit()
    conn.close()

    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "ROOM.jsonl").write_text("\n".join(lines) + "\n")
    os.utime(logs / "ROOM.jsonl", (NOW - 60, NOW - 60))
    (logs / "SMOKE.jsonl").write_text(rs(NOW - 500, [True, True, True, True]) + "\n")
    os.utime(logs / "SMOKE.jsonl", (NOW - 60, NOW - 60))
    (logs / "OLD.jsonl").write_text(rs(NOW - 3000, [False, True, True, True]) + "\n")
    os.utime(logs / "OLD.jsonl", (NOW - 40 * DAY, NOW - 40 * DAY))  # outside the scan
    (data / "support_messages.jsonl").write_text(
        json.dumps({"ts": NOW - DAY, "email": "a@b.c", "message": "hi"}) + "\n"
        + json.dumps({"ts": NOW - 9 * DAY, "message": "old"}) + "\n")
    return data, logs


def test_collect_counts_and_shape(world):
    data, logs = world
    out = query.collect(data / "accounts.sqlite3", logs, data, NOW, TODAY)

    a = out["accounts"]
    assert (a["total"], a["google"], a["apple"]) == (5, 4, 1)
    assert (a["new_24h"], a["new_7d"]) == (1, 2)
    assert (a["with_rated_round"], a["with_saved_game"]) == (2, 4)
    assert len(a["signups_per_day"]) == 30 and sum(a["signups_per_day"]) == 4
    assert a["signups_per_day"][-1] == 1

    today, week, month = (out["windows"][k] for k in ("today", "7d", "30d"))
    assert (today["rated_rounds"], today["rated_rounds_2plus_humans"], today["abandoned_rounds"]) == (2, 1, 1)
    assert week["rated_rounds"] == 3
    assert today["signed_in_players"] == 2 and week["signed_in_players"] == 3
    assert month["signed_in_players"] == 4
    assert (today["saved_games_created"], week["saved_games_created"]) == (1, 2)
    assert today["games_per_player"] == 1.0
    assert today["rated_rounds_per_player"] == 1.5

    assert today["log_rounds"] == 2 and today["bot_only_rounds"] == 1
    assert today["rounds_by_humans_at_start"] == {"1": 0, "2": 1, "3": 1, "4": 0}
    # G3 round 1: seats 0 and 1 linked; round 2: seats 0, 1 linked, seat 2 a guest.
    assert today["human_start_seat_rounds"] == 5
    assert today["signed_in_start_seat_rounds"] == 4
    assert today["guest_start_seat_rounds_est"] == 1
    # G2 round 1 adds seat 0, linked to account 2.
    assert (week["human_start_seat_rounds"], week["signed_in_start_seat_rounds"],
            week["guest_start_seat_rounds_est"]) == (6, 5, 1)
    assert week["log_rounds"] == 3 and week["share_2plus_humans_at_start"] == round(2 / 3, 3)

    logs_out = out["logs"]
    assert logs_out["live_tables_by_humans"] == {"0": 1, "1": 0, "2": 0, "3": 1, "4": 0}
    assert logs_out["last_round_start"] == NOW - 500

    # d1: accounts 1-3 and 5 (account 4 is an hour old); 5 never played.
    assert out["returns"]["d1"] == {"cohort": 4, "returned": 3, "rate": 0.75}
    # d7: accounts 1, 2 and 5; 1 played 20 days and 2 eight days after sign-up.
    assert out["returns"]["d7"] == {"cohort": 3, "returned": 2, "rate": round(2 / 3, 3)}
    assert out["support_7d"] == 1 and out["reports_7d"] == 0


def test_output_carries_counts_only(world):
    data, logs = world
    out = query.collect(data / "accounts.sqlite3", logs, data, NOW, TODAY)
    collector.check_schema(out)
    text = json.dumps(out)
    for secret in ("example.com", "a@b.c", "ROOM", "p0", "g1", "a1", "hi"):
        assert f'"{secret}' not in text and secret + '"' not in text
    for bad in ({"accounts": {"alice@example.com": 1}}, {"alice@example.com": 1},
                {"accounts": {"total": "x@example.com"}}, {"support_7d": True},
                {"accounts": {"signups_per_day": [1, "x"]}}):
        with pytest.raises(collector.LeakError) as exc:
            collector.check_schema(bad)
        assert str(exc.value) == "schema_violation"


def test_query_leaves_the_database_file_unchanged(world):
    data, logs = world
    db = data / "accounts.sqlite3"
    digest = hashlib.sha256(db.read_bytes()).hexdigest()
    before = {p.name for p in data.iterdir()}
    query.collect(db, logs, data, NOW, TODAY)
    assert hashlib.sha256(db.read_bytes()).hexdigest() == digest
    # The server keeps these WAL side files itself; nothing else may appear.
    assert {p.name for p in data.iterdir()} - before <= {db.name + "-wal", db.name + "-shm"}


def test_query_reads_rows_committed_to_a_live_wal(world):
    data, logs = world
    db = data / "accounts.sqlite3"
    writer = sqlite3.connect(db, isolation_level=None)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO users(google_sub, email, created_at, last_login_at)"
                       " VALUES ('g9', 'y@example.com', ?, ?)", (NOW - 60, NOW - 60))
        assert Path(f"{db}-wal").stat().st_size > 0      # committed, not checkpointed
        immutable = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
        try:
            assert immutable.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 5
        finally:
            immutable.close()
        out = query.collect(db, logs, data, NOW, TODAY)
        assert out["accounts"]["total"] == 6
        assert out["accounts"]["new_24h"] == 2
    finally:
        writer.close()


def test_guest_estimate_attributes_each_round_by_its_own_time(tmp_path):
    """A signed-in game that starts before midnight and plays its only round
    after it: today has one human seat-round, and it is signed in."""
    data, logs = tmp_path / "data", tmp_path / "logs"
    logs.mkdir()
    conn = _store(data)
    conn.execute("INSERT INTO users(google_sub, email, created_at, last_login_at)"
                 " VALUES ('g1', 'x@example.com', ?, ?)", (NOW - 9 * DAY, NOW - 9 * DAY))
    conn.execute("INSERT INTO games(id, room_code, log_file, log_offset, started_at, last_round)"
                 " VALUES ('G1', 'ROOM', 'ROOM.jsonl', 0, ?, 1)", (TODAY - 60,))
    conn.execute("INSERT INTO game_players(game_id, user_id, seat, from_round, to_round)"
                 " VALUES ('G1', 1, 0, 1, NULL)")
    conn.commit()
    conn.close()
    (logs / "ROOM.jsonl").write_text(_round_start(TODAY + 60, [False, True, True, True]) + "\n")
    os.utime(logs / "ROOM.jsonl", (NOW - 60, NOW - 60))
    today = query.collect(data / "accounts.sqlite3", logs, data, NOW, TODAY)["windows"]["today"]
    assert today["human_start_seat_rounds"] == 1
    assert today["signed_in_start_seat_rounds"] == 1
    assert today["guest_start_seat_rounds_est"] == 0


SECRET = "alice@example.com"


@pytest.fixture
def collector_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(collector, "fetch_health",
                        lambda: {"ok": True, "rooms": 1, "bot": "mc", "fast": True, "activity": {}})
    return home


def _fake_fly(monkeypatch, stdout, stderr="", rc=0):
    def run(args, **kw):
        return subprocess.CompletedProcess(args, rc, stdout=stdout, stderr=stderr)
    monkeypatch.setattr(collector.subprocess, "run", run)


def _stored_text(home):
    return "\n".join(p.read_text() for p in home.rglob("*") if p.is_file())


def test_collector_stores_a_valid_query_output(world, collector_home, monkeypatch):
    data, logs = world
    out = query.collect(data / "accounts.sqlite3", logs, data, NOW, TODAY)
    _fake_fly(monkeypatch, "noise\nOPS_JSON " + json.dumps(out) + "\n")
    assert collector.collect(collector_home) == 0
    latest = json.loads((collector_home / "latest.json").read_text())
    assert latest["errors"] == [] and latest["db"] == out


@pytest.mark.parametrize("stdout,stderr,rc,code", [
    ("OPS_JSON " + json.dumps({"accounts": {"total": 3, SECRET: 1}}), "", 0, "schema_violation"),
    ("OPS_JSON " + json.dumps({SECRET: {"n": 1}}), "", 0, "schema_violation"),
    ("OPS_JSON " + json.dumps({SECRET: "secret"}), "", 0, "schema_violation"),
    ("OPS_JSON " + json.dumps({"accounts": {"total": SECRET}}), "", 0, "schema_violation"),
    ("OPS_JSON {" + SECRET, "", 0, "query_bad_json"),
    ("", f"Error: no route for {SECRET} token=s3cr3t", 1, "query_failed"),
    (f"traceback mentioning {SECRET}", "", 0, "query_failed"),
])
def test_collector_never_stores_rejected_keys_or_error_text(
        collector_home, monkeypatch, capsys, stdout, stderr, rc, code):
    _fake_fly(monkeypatch, stdout, stderr, rc)
    assert collector.collect(collector_home) == 1
    latest = json.loads((collector_home / "latest.json").read_text())
    assert latest["errors"] == [code] and "db" not in latest
    printed = capsys.readouterr()
    for text in (_stored_text(collector_home), printed.out, printed.err):
        assert SECRET not in text and "s3cr3t" not in text
