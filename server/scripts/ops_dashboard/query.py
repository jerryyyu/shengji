#!/usr/bin/env python3
"""Aggregate usage counts for the ops dashboard, run inside the Fly container.

The collector sends this file to ``python3 -`` over ``flyctl ssh console``
with two arguments, ``now`` and ``today_start`` (epoch seconds). It opens the accounts
database read-only (``mode=ro`` and ``PRAGMA query_only``) and runs every
database query inside one read transaction, so the counts come from one
consistent snapshot that includes rows the server has committed to its WAL. It
opens every other file for reading only and prints one JSON object of counts.
No email, account id, name, room code, IP or message text is printed: every
value is a count, a ratio or a timestamp.

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
    """A read-only connection that takes part in the server's WAL locking.

    It reads committed frames still in the server's ``-wal`` file. A reader
    never blocks the server's writers; while its read transaction is open, a
    checkpoint cannot reset the WAL past the reader's snapshot, which lasts
    for the ~0.1 s of this query. ``immutable=1`` is wrong here: it skips the
    WAL and all locking on a file the server is changing."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2.0, isolation_level=None)
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
    return {
        "rated_rounds": rated_rounds,
        "rated_rounds_2plus_humans": int(rounds[1] or 0),
        "abandoned_rounds": int(rounds[2] or 0),
        "signed_in_players": players,
        "rated_rounds_per_player": round(rated_rows / rated_players, 2) if rated_players else None,
        "saved_games_created": saved,
        "games_per_player": round(player_games / game_players, 2) if game_players else None,
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


# Saved-game rows and links are written asynchronously after the round_start
# record they describe; a round started this recently may not be in the
# database snapshot yet.
ATTRIBUTION_LAG = 120

Link = tuple[int, int, "int | None"]


def saved_game_links(conn: sqlite3.Connection) -> dict[tuple[str, int], dict]:
    """``(log file name, byte offset of the game's round 1 round_start)`` ->
    ``{"last_round": n, "links": [(seat, first round, last round or None)]}``.
    An open link (no ``to_round``) has no upper bound: the game's log segment
    bounds it, since ``games.last_round`` can trail the log. Ids and accounts
    stay in here: only seat and round numbers leave this function."""
    games: dict[tuple[str, int], dict] = {}
    for log_file, offset, last, seat, frm, to in conn.execute(
            """SELECT g.log_file, g.log_offset, g.last_round, gp.seat, gp.from_round, gp.to_round
               FROM games g JOIN game_players gp ON gp.game_id = g.id
               WHERE g.log_offset IS NOT NULL"""):
        key = (Path(log_file).name, int(offset))
        game = games.setdefault(key, {"last_round": int(last), "links": []})
        game["links"].append((int(seat), int(frm), int(to) if to is not None else None))
    return games


def _covered(links: list[Link], seat, rnd: int) -> bool:
    return any(s == seat and frm <= rnd and (to is None or rnd <= to) for s, frm, to in links)


def scan_logs(log_dir: Path, now: float, starts: dict[str, float],
              games: dict[tuple[str, int], dict] | None = None) -> dict:
    """Count ``round_start`` records in room logs changed in the last 30
    days, each attributed to its own round's timestamp.

    A roster seat is one whose ``players[].is_bot`` is false at round start.
    That is not evidence of human play: a disconnected owner's seat stays on
    the roster while a bot covers it (``server._controller`` reports
    ``bot_cover``). Roster seat-rounds split three ways: signed in (a
    saved-game link covers the seat in that round), unknown (not covered, but
    the database may not have caught up: the round is past the game's stored
    ``last_round``, or it started within ``ATTRIBUTION_LAG`` of ``now``, the
    collector's clock just before the database snapshot), and guest (the
    rest).

    A round belongs to the game whose round 1 ``round_start`` begins at the
    ``games.log_offset`` byte offset; the game runs until the next round 1
    ``round_start`` or lobby (round 0) record, as ``saved_games._scan`` reads
    it. Games with no signed-in seat have no ``games`` row."""
    games = games or {}
    windows = {k: {"rounds": 0, "bot_only_rounds": 0, "roster_seat_rounds": 0,
                   "signed_in": 0, "unknown": 0,
                   "by_roster": {"1": 0, "2": 0, "3": 0, "4": 0}} for k in starts}
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
        game: dict | None = None
        pos = 0
        with open(entry.path, "rb") as fh:
            for line in fh:
                start, pos = pos, pos + len(line)
                head = line[:160]
                if b'"round": 0,' in head:
                    game = None
                    continue
                if b'"e": "round_start"' not in head:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                rnd = rec.get("round")
                t = float(rec.get("t") or 0)
                if rnd == 1:
                    game = games.get((entry.name, start))
                if rec.get("experiment") or rec.get("training_excluded"):
                    continue
                roster = [p.get("seat") for p in rec.get("players") or () if not p.get("is_bot")]
                n = len(roster)
                signed = unknown = 0
                if isinstance(rnd, int):
                    links = game["links"] if game is not None else []
                    pending = (t >= now - ATTRIBUTION_LAG
                               or (game is not None and rnd > game["last_round"]))
                    for seat in roster:
                        if _covered(links, seat, rnd):
                            signed += 1
                        elif pending:
                            unknown += 1
                else:
                    unknown = n
                if last_round_start is None or t > last_round_start:
                    last_round_start = t
                if now - t <= LIVE_WINDOW:
                    live_rooms[entry.name] = n
                for key, since in starts.items():
                    if t < since:
                        continue
                    w = windows[key]
                    if n == 0:
                        w["bot_only_rounds"] += 1
                        continue
                    w["rounds"] += 1
                    w["roster_seat_rounds"] += n
                    w["signed_in"] += signed
                    w["unknown"] += unknown
                    w["by_roster"][str(min(n, 4))] += 1
    live = {"1": 0, "2": 0, "3": 0, "4": 0, "0": 0}
    for n in live_rooms.values():
        live[str(min(n, 4))] += 1
    return {"available": True, "files_scanned": files, "windows": windows,
            "live_tables_by_roster_seats": live, "live_window_s": LIVE_WINDOW,
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
        conn.execute("BEGIN")
        out = {
            "generated_at": now,
            "accounts": account_stats(conn, now, today_start),
            "windows": {k: window_stats(conn, s) for k, s in starts.items()},
            "returns": return_rates(conn, now),
        }
        links = saved_game_links(conn)
        conn.execute("COMMIT")
    finally:
        conn.close()
    logs = scan_logs(log_dir, now, starts, links)
    out["logs"] = logs
    if logs.get("available"):
        for key, w in out["windows"].items():
            lw = logs["windows"][key]
            w["log_rounds"] = lw["rounds"]
            w["bot_only_rounds"] = lw["bot_only_rounds"]
            w["rounds_by_roster_seats"] = lw["by_roster"]
            w["roster_seat_rounds"] = lw["roster_seat_rounds"]
            w["signed_in_roster_seat_rounds"] = lw["signed_in"]
            w["unknown_roster_seat_rounds"] = lw["unknown"]
            w["guest_roster_seat_rounds_est"] = (lw["roster_seat_rounds"] - lw["signed_in"]
                                                 - lw["unknown"])
            w["share_2plus_roster_seats"] = (round(sum(lw["by_roster"][k] for k in "234")
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
