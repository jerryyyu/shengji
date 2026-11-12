"""The ops dashboard's in-container aggregate query, against a fixture database.

The fixture is built with the server's own schema (``accounts.Store`` runs every
migration), so a schema change that breaks a dashboard query fails here
instead of on production. The room logs and support files are tiny files in
``tmp_path``.
"""

import importlib.util
import json
import os
import sqlite3
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


@pytest.fixture
def world(tmp_path):
    data = tmp_path / "data"
    store = accounts.Store(data / "accounts.sqlite3")
    store.schema_version()                      # runs every migration
    conn = sqlite3.connect(data / "accounts.sqlite3")
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
        conn.execute("INSERT INTO games(id, room_code, log_file, started_at, last_round)"
                     " VALUES (?, 'ROOM', 'ROOM.jsonl', ?, ?)", (gid, started, last))
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

    def rs(t, bots, **extra):
        players = [{"seat": i, "name": f"p{i}", "is_bot": b} for i, b in enumerate(bots)]
        return json.dumps({"t": t, "room": "ROOM", "round": 1, "e": "round_start",
                           "deck": list(range(60)), "players": players, **extra})

    lines = [
        rs(NOW - 2 * DAY, [False, True, True, True]),
        rs(NOW - 3000, [False, False, True, True]),
        rs(NOW - 600, [False, False, False, True]),          # live: a 3-human table
        rs(NOW - 400, [False, True, True, True], training_excluded=True),
        json.dumps({"t": NOW - 300, "room": "ROOM", "round": 1, "e": "play", "seat": 0}),
        "not json",
    ]
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
    # G3: account 2 rounds 1-2, account 4 rounds 1-4.
    assert today["signed_in_seat_rounds"] == 6

    assert today["log_rounds"] == 2 and today["bot_only_rounds"] == 1
    assert today["rounds_by_humans"] == {"1": 0, "2": 1, "3": 1, "4": 0}
    assert today["human_seat_rounds"] == 5
    assert today["guest_seat_rounds_est"] == 0
    assert week["log_rounds"] == 3 and week["share_2plus_humans"] == round(2 / 3, 3)

    logs_out = out["logs"]
    assert logs_out["live_tables_by_humans"] == {"0": 1, "1": 0, "2": 0, "3": 1, "4": 0}
    assert logs_out["last_round_start"] == NOW - 500

    # d1: accounts 1-3 and 5 (account 4 is an hour old); 5 never played.
    assert out["returns"]["d1"] == {"cohort": 4, "returned": 3, "rate": 0.75}
    # d7: accounts 1, 2 and 5; 1 played 20 days and 2 eight days after sign-up.
    assert out["returns"]["d7"] == {"cohort": 3, "returned": 2, "rate": round(2 / 3, 3)}
    assert out["support_7d"] == 1 and out["reports_7d"] == 0
    assert out["wal_bytes"] == 0


def test_output_carries_counts_only(world):
    data, logs = world
    out = query.collect(data / "accounts.sqlite3", logs, data, NOW, TODAY)
    collector.assert_counts_only(out)
    text = json.dumps(out)
    for secret in ("example.com", "a@b.c", "ROOM", "p0", "g1", "a1", "hi"):
        assert f'"{secret}' not in text and secret + '"' not in text
    with pytest.raises(collector.LeakError):
        collector.assert_counts_only({"a": [1, {"b": "x@example.com"}]})


def test_query_opens_the_database_without_side_files(world):
    data, logs = world
    before = sorted(p.name for p in data.iterdir())
    query.collect(data / "accounts.sqlite3", logs, data, NOW, TODAY)
    assert sorted(p.name for p in data.iterdir()) == before
