#!/usr/bin/env python3
"""Collect one ops-dashboard snapshot: production ``/healthz`` plus the
aggregate counts ``query.py`` prints from inside the Fly container.

Run by launchd every few minutes. Writes, under ``--home`` (default
``~/shengji-ops``): ``snapshots/<UTC date>/<UTC time>.json``, ``latest.json``
(atomic replace) and one compact line per run in ``history.jsonl``.

Nothing is written to production: ``query.py`` opens the accounts database
with ``mode=ro`` and only reads files. Before anything is stored, the output
must match ``QUERY_SCHEMA``: a fixed set of key paths, each holding a number
(or a bool or null where the schema says so). An unknown key or a string
anywhere fails the run, so a query change cannot store a name or an email
here. Failures are recorded as the stable codes in ``ERROR_CODES``, never as
key names or raw command output.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import fcntl
import json
import math
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

APP = "shengji"
HEALTHZ = "https://shengji.fly.dev/healthz"
QUERY = Path(__file__).resolve().with_name("query.py")
TZ = ZoneInfo("America/New_York")
FLY_TIMEOUT = 90
HEALTH_KEYS = ("ok", "rooms", "bot", "fast")
HEALTH_ACTIVITY_KEYS = ("rooms_created", "games_started", "rounds_recorded", "records_written",
                        "record_write_failures", "account_link_failures")

# The only diagnostics a snapshot or log line carries.
ERROR_CODES = ("healthz_failed", "query_failed", "query_timeout", "query_bad_json",
               "schema_violation", "speed_store_failed")

# Leaf kinds: NUM is an int or finite float (not a bool) or null; BOOL is a
# bool; [NUM] is a list of at most MAX_LIST NUMs, [NUM, n] of at most n.
# Every dict below lists all its allowed keys. The only strings allowed are
# in player-report rows: RID (a report's opaque id, 16 lowercase hex digits),
# ROOM (a short alphanumeric room code), REASON (one of the report reasons)
# and NAME (a seat's table name, at most 40 printable characters), each or
# null.
NUM, BOOL, RID, ROOM, REASON, NAME = "num", "bool", "rid", "room", "reason", "name"
REPORT_REASONS = ("abuse", "spam", "cheating", "other")
_BY_ROSTER = {k: NUM for k in ("1", "2", "3", "4")}
_WINDOW = {
    "rated_rounds": NUM, "rated_rounds_2plus_humans": NUM, "abandoned_rounds": NUM,
    "signed_in_players": NUM, "rated_rounds_per_player": NUM, "saved_games_created": NUM,
    "games_per_player": NUM, "log_rounds": NUM, "bot_only_rounds": NUM,
    "rounds_by_roster_seats": _BY_ROSTER, "roster_seat_rounds": NUM,
    "signed_in_roster_seat_rounds": NUM, "unknown_roster_seat_rounds": NUM,
    "guest_roster_seat_rounds_est": NUM, "share_2plus_roster_seats": NUM,
}
_RETURN = {"cohort": NUM, "returned": NUM, "rate": NUM}
QUERY_SCHEMA = {
    "generated_at": NUM,
    "accounts": {"total": NUM, "google": NUM, "apple": NUM, "new_24h": NUM, "new_7d": NUM,
                 "with_rated_round": NUM, "with_saved_game": NUM, "signups_per_day": [NUM]},
    "windows": {"today": _WINDOW, "7d": _WINDOW, "30d": _WINDOW},
    "returns": {"d1": _RETURN, "d7": _RETURN},
    "logs": {"available": BOOL, "files_scanned": NUM, "live_window_s": NUM,
             "last_round_start": NUM,
             "live_tables_by_roster_seats": {k: NUM for k in ("0", "1", "2", "3", "4")}},
    "support_7d": NUM, "reports_7d": NUM, "query_cpu_s": NUM,
    "bot_speed": None,  # filled in below
}
_LAT = {k: NUM for k in ("n", "mean", "p50", "p90", "p99", "max", "over")}
_SPEED_WINDOW = {"play": _LAT, "bury": _LAT, "declare": _LAT, "other": _LAT,
                 "rooms": NUM, "rooms_max": NUM}
QUERY_SCHEMA["bot_speed"] = {
    "available": BOOL, "files_scanned": NUM, "since": NUM, "cpu_s": NUM,
    "slots_over_60m": NUM,
    "windows": {"60m": _SPEED_WINDOW, "24h": _SPEED_WINDOW},
    "days": [dict(_SPEED_WINDOW, start=NUM)],
    "hours": [{k: NUM for k in ("start", "n", "play_n", "p50", "p90", "p99", "max", "over",
                                "rooms_max")}],
    "slow": [{k: NUM for k in ("t", "phase", "s", "rooms")}],
}
WATCH_MAX = 1000
QUERY_SCHEMA["reports"] = {
    "available": BOOL, "file": BOOL, "total": NUM, "n_24h": NUM, "n_7d": NUM,
    "latest": [{"id": RID, "t": NUM, "room": ROOM, "round": NUM, "reason": REASON,
                "reported": NAME, "reporter": NAME}],
    "watch": [{"id": RID, "t": NUM}, WATCH_MAX],
    "watch_omitted": NUM,
}
SPEED_STORE = "botspeed.json"
SPEED_HOURS_KEPT = 45 * 86400
MAX_LIST = 64


class LeakError(ValueError):
    """The container's output left ``QUERY_SCHEMA``. The message is always
    the code ``schema_violation``: the offending key or value is not
    repeated anywhere."""

    def __init__(self) -> None:
        super().__init__("schema_violation")


class QueryError(RuntimeError):
    def __init__(self, code: str) -> None:
        assert code in ERROR_CODES
        super().__init__(code)
        self.code = code


def check_schema(value, schema=QUERY_SCHEMA) -> None:
    """Raise ``LeakError`` unless ``value`` fits ``schema`` exactly: dicts
    hold only listed keys (a listed key may be absent), leaves have the
    listed kind."""
    if isinstance(schema, dict):
        if not isinstance(value, dict) or any(k not in schema for k in value):
            raise LeakError()
        for k, v in value.items():
            check_schema(v, schema[k])
    elif isinstance(schema, list):
        limit = schema[1] if len(schema) > 1 else MAX_LIST
        if not isinstance(value, list) or len(value) > limit:
            raise LeakError()
        for v in value:
            check_schema(v, schema[0])
    elif schema == BOOL:
        if not isinstance(value, bool):
            raise LeakError()
    elif schema in (RID, ROOM, REASON, NAME):
        if value is None:
            return
        if not isinstance(value, str) or not value.isprintable():
            raise LeakError()
        if schema == RID and not is_report_id(value):
            raise LeakError()
        if schema == ROOM and not (value.isalnum() and value.isascii() and len(value) <= 8):
            raise LeakError()
        if schema == REASON and value not in REPORT_REASONS:
            raise LeakError()
        if schema == NAME and len(value) > 40:
            raise LeakError()
    elif value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                or not math.isfinite(value)):
        raise LeakError()


def fetch_health() -> dict:
    req = urllib.request.Request(HEALTHZ, headers={"User-Agent": "shengji-ops-dashboard"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = json.load(resp)
    out = {k: raw.get(k) for k in HEALTH_KEYS}
    activity = raw.get("activity") or {}
    out["activity"] = {k: activity[k] for k in HEALTH_ACTIVITY_KEYS
                       if isinstance(activity.get(k), (int, float))
                       and not isinstance(activity.get(k), bool)}
    return out


def flyctl() -> str:
    return shutil.which("flyctl") or "/opt/homebrew/bin/flyctl"


def run_query(now: float, today_start: float, yesterday_start: float) -> dict:
    script = base64.b64encode(QUERY.read_bytes()).decode()
    remote = (f"sh -c 'echo {script} | base64 -d | python3 - {now:.3f} {today_start:.0f} "
              f"{yesterday_start:.0f}'")
    try:
        proc = subprocess.run([flyctl(), "ssh", "console", "-a", APP, "-C", remote],
                              capture_output=True, text=True, timeout=FLY_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise QueryError("query_timeout") from None
    except OSError:
        raise QueryError("query_failed") from None
    for line in (proc.stdout or "").splitlines():
        if line.startswith("OPS_JSON "):
            try:
                data = json.loads(line[len("OPS_JSON "):])
            except ValueError:
                raise QueryError("query_bad_json") from None
            try:
                check_schema(data)
            except LeakError:
                raise QueryError("schema_violation") from None
            return data
    raise QueryError("query_failed")


def write_atomic(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")))
    os.replace(tmp, path)


def speed_state(bs: dict) -> dict:
    """Health of bot decision time over the last hour.

    idle: no decision. amber: any decision over its phase budget (play 3 s,
    bury 2 s) or play p99 over 3 s. red (sustained): over-budget decisions
    in two or more of the hour's six 10-minute slots, or ten or more of them."""
    w = (bs.get("windows") or {}).get("60m") or {}
    n = sum((w.get(p) or {}).get("n", 0) for p in ("play", "bury", "declare", "other"))
    over = sum((w.get(p) or {}).get("over", 0) for p in ("play", "bury", "declare", "other"))
    p99 = (w.get("play") or {}).get("p99")
    slots = bs.get("slots_over_60m") or 0
    if not bs.get("available"):
        return {"state": "unknown", "reason": "room logs unavailable"}
    if not n:
        return {"state": "idle", "reason": "no bot decisions in the last hour"}
    if slots >= 2 or over >= 10:
        state = "red"
    elif over or (p99 is not None and p99 > 3):
        state = "amber"
    else:
        state = "green"
    reason = (f"{over} over budget in the last hour ({slots} of 6 ten-minute slots)"
              if over else "no decision over budget in the last hour")
    if p99 is not None and p99 > 3:
        reason += f"; play p99 {p99:.2f} s"
    return {"state": state, "reason": reason, "n": n, "over": over}


REPORT_AMBER_S, REPORT_RED_S, REPORT_WATCH_S = 12 * 3600, 24 * 3600, 7 * 86400
HANDLED_FILE = Path("state") / "reports_handled.json"


def is_report_id(value) -> bool:
    """A report id as ``query.report_id`` makes it: 16 lowercase hex digits."""
    return (isinstance(value, str) and len(value) == 16
            and all(c in "0123456789abcdef" for c in value))


def load_handled(home: Path) -> dict:
    """``{report id: unix time it was marked}`` from the local acknowledge
    list (written by ``serve.py``; the Fly volume is never written)."""
    try:
        data = json.loads((home / HANDLED_FILE).read_text())
    except (OSError, ValueError):
        return {}
    handled = data.get("handled") if isinstance(data, dict) else None
    return {k: v for k, v in handled.items() if isinstance(k, str)} if isinstance(handled, dict) else {}


def report_rows(rep: dict) -> list[dict]:
    """Every report the state is computed from: id and time of each report
    in the watch window. A snapshot without ``watch`` falls back to the
    displayed rows; a row without a valid id can never be marked handled."""
    rows = rep.get("watch")
    if not isinstance(rows, list):
        rows = rep.get("latest") or []
    return [r for r in rows if isinstance(r, dict) and isinstance(r.get("t"), (int, float))]


def reports_state(rep: dict, now: float, handled: dict | None = None) -> dict:
    """The server stores no "handled" mark on a report; this Mac keeps one
    (``state/reports_handled.json``). Only unhandled reports count: red while
    one from the last 7 days is over 24 h old, amber while one is over 12 h.
    The state reads every report in the watch window, not just the displayed
    newest rows; if the query had to leave reports out (``watch_omitted``),
    the state is red, since those are the oldest and cannot be checked."""
    if not rep.get("available"):
        return {"state": "unknown", "reason": "reports file unreadable"}
    if not rep.get("total"):
        return {"state": "green", "reason": "no reports filed yet"}
    handled = handled or {}
    rows = [r for r in report_rows(rep) if now - r["t"] <= REPORT_WATCH_S]
    is_handled = [is_report_id(r.get("id")) and r["id"] in handled for r in rows]
    n_handled = sum(is_handled)
    ages = [now - r["t"] for r, h in zip(rows, is_handled) if not h]
    omitted = rep.get("watch_omitted") or 0
    if omitted or any(a > REPORT_RED_S for a in ages):
        state = "red"
    elif any(a > REPORT_AMBER_S for a in ages):
        state = "amber"
    else:
        state = "green"
    if ages:
        reason = f"{len(ages)} unhandled in the last 7 d, oldest {max(ages) / 3600:.0f} h"
    elif rows:
        reason = "none unhandled in the last 7 d"
    else:
        reason = "none in the last 7 d"
    if n_handled:
        reason += f"; {n_handled} handled"
    if omitted:
        reason += f"; {omitted} older reports not checked"
    return {"state": state, "reason": reason}


def day_key(start: float) -> str:
    return dt.datetime.fromtimestamp(start + 43200, TZ).strftime("%Y-%m-%d")


def merge_speed(home: Path, bs: dict, now: float) -> None:
    """Fold one run's day and hour rows into ``botspeed.json``: a row the
    run computed replaces the stored one (it covers the whole day or hour so
    far); older rows stay as the backfill or an earlier run left them."""
    path = home / SPEED_STORE
    try:
        store = json.loads(path.read_text())
    except (OSError, ValueError):
        store = {}
    days = store.setdefault("days", {})
    hours = store.setdefault("hours", {})
    for d in bs.get("days") or ():
        days[day_key(d["start"])] = d
    for h in bs.get("hours") or ():
        hours[str(int(h["start"]))] = h
    for k in [k for k in hours if float(k) < now - SPEED_HOURS_KEPT]:
        del hours[k]
    store["updated_at"] = now
    write_atomic(path, store)


def collect(home: Path) -> int:
    now = time.time()
    local = dt.datetime.fromtimestamp(now, TZ)
    today_start = local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    yesterday_start = (local.replace(hour=12, minute=0, second=0, microsecond=0)
                       - dt.timedelta(days=1)).replace(hour=0).timestamp()
    snap = {"collected_at": now, "today_start": today_start, "tz": "America/New_York",
            "errors": []}
    try:
        snap["health"] = fetch_health()
    except Exception:  # noqa: BLE001 - recorded as a code, the run goes on
        snap["errors"].append("healthz_failed")
    t0 = time.time()
    try:
        snap["db"] = run_query(now, today_start, yesterday_start)
    except QueryError as exc:
        snap["errors"].append(exc.code)
    except Exception:  # noqa: BLE001 - recorded as a code, the run goes on
        snap["errors"].append("query_failed")
    snap["query_wall_s"] = round(time.time() - t0, 2)
    rep = (snap.get("db") or {}).get("reports")
    if rep:
        snap["reports_state"] = reports_state(rep, now, load_handled(home))
    bs = (snap.get("db") or {}).get("bot_speed")
    if bs:
        snap["bot_speed_state"] = speed_state(bs)
        if bs.get("available"):
            try:
                merge_speed(home, bs, now)
            except Exception:  # noqa: BLE001 - the snapshot still lands
                snap["errors"].append("speed_store_failed")

    stamp = dt.datetime.fromtimestamp(now, dt.timezone.utc)
    day_dir = home / "snapshots" / stamp.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / (stamp.strftime("%H%M%SZ") + ".json")).write_text(json.dumps(snap))

    latest_path = home / "latest.json"
    if "db" not in snap and latest_path.exists():
        # Keep the last good counts on screen, flagged stale.
        try:
            prev = json.loads(latest_path.read_text())
            if "db" in prev:
                snap["db"] = prev["db"]
                snap["db_stale_from"] = prev.get("db_collected_at", prev.get("collected_at"))
        except ValueError:
            pass
    if "db_stale_from" not in snap and "db" in snap:
        snap["db_collected_at"] = now
    elif "db_stale_from" in snap:
        snap["db_collected_at"] = snap["db_stale_from"]
    write_atomic(latest_path, snap)

    health = snap.get("health") or {}
    today = ((snap.get("db") or {}).get("windows") or {}).get("today") or {}
    live = ((snap.get("db") or {}).get("logs") or {}).get("live_tables_by_roster_seats") or {}
    fresh = bs if "db_stale_from" not in snap else None
    w60 = ((fresh or {}).get("windows") or {}).get("60m") or {}
    with open(home / "history.jsonl", "a") as fh:
        fh.write(json.dumps({"t": round(now), "rooms": health.get("rooms"),
                             "live_tables": sum(v for k, v in live.items() if k != "0") if live else None,
                             "log_rounds_today": today.get("log_rounds"),
                             "bot_p99_60m": (w60.get("play") or {}).get("p99"),
                             "bot_over_60m": (snap.get("bot_speed_state") or {}).get("over")
                             if fresh else None,
                             "ok": not snap["errors"]}) + "\n")
    for e in snap["errors"]:
        print(f"{stamp.isoformat()} ERROR {e}", file=sys.stderr)
    print(f"{stamp.isoformat()} snapshot rooms={health.get('rooms')} "
          f"query={snap['query_wall_s']}s cpu={(snap.get('db') or {}).get('query_cpu_s')} "
          f"bot={(snap.get('bot_speed_state') or {}).get('state')} "
          f"reports={(snap.get('reports_state') or {}).get('state')} "
          f"bot_cpu={(bs or {}).get('cpu_s')} errors={len(snap['errors'])}")
    return 1 if snap["errors"] else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--home", type=Path, default=Path.home() / "shengji-ops")
    args = ap.parse_args()
    args.home.mkdir(parents=True, exist_ok=True)
    with open(args.home / "collector.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("another collector run holds the lock; skipping", file=sys.stderr)
            return 0
        return collect(args.home)


if __name__ == "__main__":
    sys.exit(main())
