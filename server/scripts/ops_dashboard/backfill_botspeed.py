#!/usr/bin/env python3
"""One-off: fill ``botspeed.json`` with every ET day and UTC hour found in a
local copy of the room logs (read only), using the same code ``query.py``
runs on Fly. Rows already in the store for days or hours the copy does not
reach are kept; the collector's own rows for yesterday and today replace the
backfill's on its next run.

    python3 backfill_botspeed.py --logs ~/Projects/shengji/logs

Prints the all-history totals per phase so they can be checked by hand.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collector  # noqa: E402
import query  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--logs", type=Path, required=True)
    ap.add_argument("--home", type=Path, default=Path.home() / "shengji-ops")
    args = ap.parse_args()
    t0 = time.time()
    paths = sorted(str(p) for p in args.logs.glob("*.jsonl"))
    dec = query.read_decisions(paths, 0)
    if not dec:
        print("no decisions found")
        return 1
    conc = query.concurrent_rooms(dec)
    first, last = dec[0][0], dec[-1][0]
    day = dt.datetime.fromtimestamp(first, collector.TZ).replace(hour=0, minute=0, second=0,
                                                                 microsecond=0)
    starts = []
    while day.timestamp() <= last:
        starts.append(day.timestamp())
        day = (day.replace(hour=12) + dt.timedelta(days=1)).replace(hour=0)
    days = []
    for lo, hi in zip(starts, starts[1:] + [last + 1]):
        w = query.speed_window(dec, conc, lo, hi)
        if any(w[p]["n"] for p in query.PHASES):
            w["start"] = lo
            days.append(w)
    hours = []
    h = first // 3600 * 3600
    while h <= last:
        row = query.speed_hour(dec, conc, h)
        if row:
            hours.append(row)
        h += 3600
    # The same leaf checks the collector applies to Fly's rows (one row at a
    # time: the list cap is for one run's output).
    sch = collector.QUERY_SCHEMA["bot_speed"]
    for d in days:
        collector.check_schema(d, sch["days"][0])
    for r in hours:
        collector.check_schema(r, sch["hours"][0])
    with open(args.home / "collector.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = args.home / collector.SPEED_STORE
        try:
            store = json.loads(path.read_text())
        except (OSError, ValueError):
            store = {}
        # Keep rows the collector wrote for the newest days; the copy may be
        # older than them.
        newer_days = {k: v for k, v in (store.get("days") or {}).items()}
        newer_hours = {k: v for k, v in (store.get("hours") or {}).items()}
        store["days"] = {collector.day_key(d["start"]): d for d in days}
        store["hours"] = {str(int(r["start"])): r for r in hours}
        cut = last - 3600
        for k, v in newer_days.items():
            if v["start"] >= cut - 86400 or k not in store["days"]:
                store["days"][k] = v
        for k, v in newer_hours.items():
            if float(k) >= cut or k not in store["hours"]:
                store["hours"][k] = v
        store["backfill"] = {"through": last, "files": len(paths), "at": time.time()}
        collector.write_atomic(path, store)
    total = query.speed_window(dec, conc, 0, last + 1)
    for p in query.PHASES:
        print(p, json.dumps(total[p]))
    print(f"days={len(days)} hours={len(hours)} files={len(paths)} "
          f"through={dt.datetime.fromtimestamp(last, dt.timezone.utc):%Y-%m-%d %H:%MZ} "
          f"wall={time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
