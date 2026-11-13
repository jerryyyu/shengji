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
               "schema_violation")

# Leaf kinds: NUM is an int or finite float (not a bool) or null; BOOL is a
# bool; [NUM] is a list of NUM. Every dict below lists all its allowed keys.
NUM, BOOL = "num", "bool"
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
}
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
        if not isinstance(value, list) or len(value) > MAX_LIST:
            raise LeakError()
        for v in value:
            check_schema(v, schema[0])
    elif schema == BOOL:
        if not isinstance(value, bool):
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


def run_query(now: float, today_start: float) -> dict:
    script = base64.b64encode(QUERY.read_bytes()).decode()
    remote = f"sh -c 'echo {script} | base64 -d | python3 - {now:.3f} {today_start:.0f}'"
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


def collect(home: Path) -> int:
    now = time.time()
    local = dt.datetime.fromtimestamp(now, TZ)
    today_start = local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    snap = {"collected_at": now, "today_start": today_start, "tz": "America/New_York",
            "errors": []}
    try:
        snap["health"] = fetch_health()
    except Exception:  # noqa: BLE001 - recorded as a code, the run goes on
        snap["errors"].append("healthz_failed")
    t0 = time.time()
    try:
        snap["db"] = run_query(now, today_start)
    except QueryError as exc:
        snap["errors"].append(exc.code)
    except Exception:  # noqa: BLE001 - recorded as a code, the run goes on
        snap["errors"].append("query_failed")
    snap["query_wall_s"] = round(time.time() - t0, 2)

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
    with open(home / "history.jsonl", "a") as fh:
        fh.write(json.dumps({"t": round(now), "rooms": health.get("rooms"),
                             "live_tables": sum(v for k, v in live.items() if k != "0") if live else None,
                             "log_rounds_today": today.get("log_rounds"),
                             "ok": not snap["errors"]}) + "\n")
    for e in snap["errors"]:
        print(f"{stamp.isoformat()} ERROR {e}", file=sys.stderr)
    print(f"{stamp.isoformat()} snapshot rooms={health.get('rooms')} "
          f"query={snap['query_wall_s']}s cpu={(snap.get('db') or {}).get('query_cpu_s')} "
          f"errors={len(snap['errors'])}")
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
