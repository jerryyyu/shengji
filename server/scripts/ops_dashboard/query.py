#!/usr/bin/env python3
"""Aggregate usage counts for the ops dashboard, run inside the Fly container.

The collector sends this file to ``python3 -`` over ``flyctl ssh console``
with two arguments, ``now`` and ``today_start`` (epoch seconds). It opens the accounts
database read-only (``mode=ro&immutable=1`` and ``PRAGMA query_only``, so not
even SQLite's ``-wal``/``-shm`` side files are created), opens every other
file for reading only, and prints one JSON object of counts. No email, account
id, name, room code, IP or message text is printed: every value is a count, a
ratio or a timestamp.

Stdlib only, and cheap: the room-log scan reads only files changed in the last
30 days and parses only ``round_start`` lines.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

DAY = 86400
LIVE_WINDOW = 20 * 60
LOG_WINDOW_DAYS = 30
SIGNUP_DAYS = 30
COHORT_DAYS = 60


def _connect(db: Path) -> sqlite3.Connection:
    """Open the database file without writing anything beside it.

    ``mode=ro`` alone still creates and maps ``-wal``/``-shm`` side files on a
    WAL database; ``immutable=1`` reads the main file with no locks and no
    side files. Frames still in the server's WAL are not seen (``wal_bytes``
    in the output says how many bytes that could be); the server checkpoints
    when its connections close, so the lag is small."""
    conn = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True, timeout=2.0)
    conn.execute("PRAGMA query_only = 1")
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _one(conn: sqlite3.Connection, sql: str, args: tuple = ()) -> int:
    row = conn.execute(sql, args).fetchone()
    return int(row[0] or 0) if row else 0


def account_stats(conn: sqlite3.Connection, now: float, today_start: float) -> dict:
    cols = _columns(conn, "users")
    apple = "apple_sub IS NOT NULL" if "apple_sub" in cols else "0"
    out = {
        "total": _one(conn, "SELECT COUNT(*) FROM users"),
        "google": _one(conn, "SELECT COUNT(*) FROM users WHERE google_sub IS NOT NULL"),
        "apple": _one(conn, f"SELECT COUNT(*) FROM users WHERE {apple}"),
        "new_24h": _one(conn, "SELECT COUNT(*) FROM users WHERE created_at >= ?", (now - DAY,)),
        "new_7d": _one(conn, "SELECT COUNT(*) FROM users WHERE created_at >= ?", (now - 7 * DAY,)),
        "with_rated_round": _one(conn, "SELECT COUNT(DISTINCT user_id) FROM rating_events"),
        "with_saved_game": _one(conn, "SELECT COUNT(DISTINCT user_id) FROM game_players"),
    }
    # Sign-ups per local day (days start at ``today_start``), oldest first,
    # ending with today.
    first = today_start - (SIGNUP_DAYS - 1) * DAY
    days = [0] * SIGNUP_DAYS
    for (created,) in conn.execute("SELECT created_at FROM users WHERE created_at >= ?", (first,)):
        i = int((created - first) // DAY)
        if 0 <= i < SIGNUP_DAYS:
            days[i] += 1
    out["signups_per_day"] = days
    return out


# One row per (account, moment it played): a rated round, or the start of a
# saved game it sat in. Used for distinct players and for return rates.
_ACTIVITY = """
    SELECT user_id, created_at AS at FROM rating_events
    UNION ALL
    SELECT gp.user_id, g.started_at AS at FROM game_players gp JOIN games g ON g.id = gp.game_id
"""


def window_stats(conn: sqlite3.Connection, since: float) -> dict:
    rounds = conn.execute(
        """SELECT COUNT(*),
                  SUM(CASE WHEN humans >= 2 THEN 1 ELSE 0 END),
                  SUM(abandoned)
           FROM (SELECT game_id, round_no,
                        MAX(4 - partner_bot - opponents_bots) AS humans,
                        MAX(abandoned) AS abandoned
                 FROM rating_events WHERE created_at >= ?
                 GROUP BY game_id, round_no)""", (since,)).fetchone()
    rated_rounds = int(rounds[0] or 0)
    rated_rows = _one(conn, "SELECT COUNT(*) FROM rating_events WHERE created_at >= ?", (since,))
    rated_players = _one(
        conn, "SELECT COUNT(DISTINCT user_id) FROM rating_events WHERE created_at >= ?", (since,))
    players = _one(conn, f"SELECT COUNT(DISTINCT user_id) FROM ({_ACTIVITY}) WHERE at >= ?",
                   (since,))
    saved = _one(conn, "SELECT COUNT(*) FROM games WHERE started_at >= ?", (since,))
    player_games = _one(
        conn, """SELECT COUNT(*) FROM (SELECT DISTINCT gp.game_id, gp.user_id
                 FROM game_players gp JOIN games g ON g.id = gp.game_id
                 WHERE g.started_at >= ?)""", (since,))
    game_players = _one(
        conn, """SELECT COUNT(DISTINCT gp.user_id) FROM game_players gp
                 JOIN games g ON g.id = gp.game_id WHERE g.started_at >= ?""", (since,))
    # Signed-in seat-rounds in saved games started in the window: each link
    # covers rounds from_round..to_round (open links run to the game's last
    # round).
    signed_seat_rounds = _one(
        conn, """SELECT SUM(MAX(0, COALESCE(gp.to_round, g.last_round) - gp.from_round + 1))
                 FROM game_players gp JOIN games g ON g.id = gp.game_id
                 WHERE g.started_at >= ?""", (since,))
    return {
        "rated_rounds": rated_rounds,
        "rated_rounds_2plus_humans": int(rounds[1] or 0),
        "abandoned_rounds": int(rounds[2] or 0),
        "signed_in_players": players,
        "rated_rounds_per_player": round(rated_rows / rated_players, 2) if rated_players else None,
        "saved_games_created": saved,
        "games_per_player": round(player_games / game_players, 2) if game_players else None,
        "signed_in_seat_rounds": signed_seat_rounds,
    }


def return_rates(conn: sqlite3.Connection, now: float) -> dict:
    """Of accounts created at least ``d`` days ago (and within COHORT_DAYS),
    the share that played again ``d`` or more days after signing up."""
    out = {}
    for d in (1, 7):
        cohort, back = conn.execute(
            f"""SELECT COUNT(*), SUM(CASE WHEN EXISTS (
                       SELECT 1 FROM ({_ACTIVITY}) a
                       WHERE a.user_id = u.id AND a.at >= u.created_at + ?) THEN 1 ELSE 0 END)
                FROM users u WHERE u.created_at <= ? AND u.created_at >= ?""",
            (d * DAY, now - d * DAY, now - COHORT_DAYS * DAY)).fetchone()
        cohort, back = int(cohort or 0), int(back or 0)
        out[f"d{d}"] = {"cohort": cohort, "returned": back,
                        "rate": round(back / cohort, 3) if cohort else None}
    return out


def scan_logs(log_dir: Path, now: float, starts: dict[str, float]) -> dict:
    """Count ``round_start`` records in room logs changed in the last 30
    days: rounds by number of human seats, and human seat-rounds per window.
    The ``players`` list names no account, so guests and signed-in humans
    look alike here; ``guest_seat_rounds`` subtracts the saved-game links."""
    windows = {k: {"rounds": 0, "bot_only_rounds": 0, "human_seat_rounds": 0,
                   "by_humans": {"1": 0, "2": 0, "3": 0, "4": 0}} for k in starts}
    live_rooms: dict[str, int] = {}
    last_round_start = None
    files = 0
    if not log_dir.is_dir():
        return {"available": False}
    for entry in os.scandir(log_dir):
        if not entry.name.endswith(".jsonl") or not entry.is_file():
            continue
        if now - entry.stat().st_mtime > LOG_WINDOW_DAYS * DAY:
            continue
        files += 1
        with open(entry.path, "rb") as fh:
            for line in fh:
                if b'"e": "round_start"' not in line[:160]:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("experiment") or rec.get("training_excluded"):
                    continue
                t = float(rec.get("t") or 0)
                humans = sum(1 for p in rec.get("players") or () if not p.get("is_bot"))
                if last_round_start is None or t > last_round_start:
                    last_round_start = t
                if now - t <= LIVE_WINDOW:
                    live_rooms[entry.name] = humans
                for key, since in starts.items():
                    if t < since:
                        continue
                    w = windows[key]
                    if humans == 0:
                        w["bot_only_rounds"] += 1
                        continue
                    w["rounds"] += 1
                    w["human_seat_rounds"] += humans
                    w["by_humans"][str(min(humans, 4))] += 1
    live = {"1": 0, "2": 0, "3": 0, "4": 0, "0": 0}
    for humans in live_rooms.values():
        live[str(min(humans, 4))] += 1
    return {"available": True, "files_scanned": files, "windows": windows,
            "live_tables_by_humans": live, "live_window_s": LIVE_WINDOW,
            "last_round_start": last_round_start}


def count_jsonl_since(path: Path, since: float, key: str = "ts") -> int | None:
    if not path.is_file():
        return 0
    n = 0
    with open(path, "rb") as fh:
        for line in fh:
            try:
                if float(json.loads(line).get(key) or 0) >= since:
                    n += 1
            except (ValueError, AttributeError, TypeError):
                continue
    return n


def collect(db: Path, log_dir: Path, data_dir: Path, now: float, today_start: float) -> dict:
    t0 = time.process_time()
    starts = {"today": today_start, "7d": now - 7 * DAY, "30d": now - 30 * DAY}
    conn = _connect(db)
    try:
        out = {
            "generated_at": now,
            "accounts": account_stats(conn, now, today_start),
            "windows": {k: window_stats(conn, s) for k, s in starts.items()},
            "returns": return_rates(conn, now),
        }
    finally:
        conn.close()
    wal = Path(f"{db}-wal")
    out["wal_bytes"] = wal.stat().st_size if wal.is_file() else 0
    logs = scan_logs(log_dir, now, starts)
    out["logs"] = logs
    if logs.get("available"):
        for key, w in out["windows"].items():
            lw = logs["windows"][key]
            w["log_rounds"] = lw["rounds"]
            w["bot_only_rounds"] = lw["bot_only_rounds"]
            w["rounds_by_humans"] = lw["by_humans"]
            w["human_seat_rounds"] = lw["human_seat_rounds"]
            w["guest_seat_rounds_est"] = max(0, lw["human_seat_rounds"] - w["signed_in_seat_rounds"])
            w["share_2plus_humans"] = (round(sum(lw["by_humans"][k] for k in "234")
                                             / lw["rounds"], 3) if lw["rounds"] else None)
        del logs["windows"]
    out["support_7d"] = count_jsonl_since(data_dir / "support_messages.jsonl", now - 7 * DAY)
    out["reports_7d"] = count_jsonl_since(data_dir / "player_reports.jsonl", now - 7 * DAY)
    out["query_cpu_s"] = round(time.process_time() - t0, 3)
    return out


def main(argv: list[str]) -> int:
    now = float(argv[1]) if len(argv) > 1 else time.time()
    today_start = float(argv[2]) if len(argv) > 2 else (now // DAY) * DAY
    data_dir = Path(os.environ.get("SHENGJI_DATA_DIR") or "/data")
    log_dir = Path(os.environ.get("SHENGJI_LOG_DIR") or data_dir / "logs")
    out = collect(data_dir / "accounts.sqlite3", log_dir, data_dir, now, today_start)
    print("OPS_JSON " + json.dumps(out, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
