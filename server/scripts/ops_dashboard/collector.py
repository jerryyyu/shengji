#!/usr/bin/env python3
"""Collect one ops-dashboard snapshot: production ``/healthz`` plus the
aggregate counts ``query.py`` prints from inside the Fly container.

Run by launchd every few minutes. Writes, under ``--home`` (default
``~/shengji-ops``): ``snapshots/<UTC date>/<UTC time>.json``, ``latest.json``
(atomic replace) and one compact line per run in ``history.jsonl``.

Nothing is written to production: ``query.py`` opens the accounts database
with ``mode=ro`` and only reads files. Before anything is stored, every value
that came out of the container must be a number, a bool or null; a string
anywhere fails the run, so a query change cannot leak a name or an email.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import fcntl
import json
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


class LeakError(ValueError):
    pass


def assert_counts_only(value, path="$"):
    """Every leaf is a number, bool or null; dict keys are the only text."""
    if isinstance(value, dict):
        for k, v in value.items():
            assert_counts_only(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            assert_counts_only(v, f"{path}[{i}]")
    elif value is not None and not isinstance(value, (int, float, bool)):
        raise LeakError(f"non-numeric value at {path}")


def fetch_health() -> dict:
    req = urllib.request.Request(HEALTHZ, headers={"User-Agent": "shengji-ops-dashboard"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = json.load(resp)
    out = {k: raw.get(k) for k in HEALTH_KEYS}
    out["activity"] = {k: v for k, v in (raw.get("activity") or {}).items()
                       if isinstance(v, (int, float)) and not isinstance(v, bool)}
    return out


def flyctl() -> str:
    return shutil.which("flyctl") or "/opt/homebrew/bin/flyctl"


def run_query(now: float, today_start: float) -> dict:
    script = base64.b64encode(QUERY.read_bytes()).decode()
    remote = f"sh -c 'echo {script} | base64 -d | python3 - {now:.3f} {today_start:.0f}'"
    proc = subprocess.run([flyctl(), "ssh", "console", "-a", APP, "-C", remote],
                          capture_output=True, text=True, timeout=FLY_TIMEOUT)
    for line in proc.stdout.splitlines():
        if line.startswith("OPS_JSON "):
            data = json.loads(line[len("OPS_JSON "):])
            assert_counts_only(data)
            return data
    tail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or [""]
    raise RuntimeError(f"flyctl rc={proc.returncode}: {tail[0][:200]}")


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
    except Exception as exc:  # noqa: BLE001 - recorded, the run goes on
        snap["errors"].append(f"healthz: {type(exc).__name__}")
    t0 = time.time()
    try:
        snap["db"] = run_query(now, today_start)
    except Exception as exc:  # noqa: BLE001
        snap["errors"].append(f"query: {type(exc).__name__}: {str(exc)[:200]}")
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
    live = ((snap.get("db") or {}).get("logs") or {}).get("live_tables_by_humans") or {}
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
