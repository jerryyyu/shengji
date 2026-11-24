#!/usr/bin/env python3
"""Sessions by app version, from the UI telemetry day files.

Counts distinct ``sid`` (one per socket) by ``platform`` and ``app_version``
over ``ui-YYYYMMDD.jsonl`` and ``ui-id-YYYYMMDD.jsonl`` in the telemetry
directory (``$SHENGJI_TELEMETRY_DIR`` or ``--dir``). A session's rows are
joined by ``sid`` first: its queue events carry ``app_version`` but no
``platform``, so a platform or version seen on any row is the session's. An
``ios_app`` session
with no ``app_version`` is reported as ``<=1.0.1``: apps before 1.0.2 send no
version token. Rows without a ``sid`` (the sign-in count) are skipped, and so
is any line over ``MAX_LINE`` bytes or not a JSON object.

    server/.venv/bin/python server/scripts/telemetry_app_versions.py --dir /data/telemetry --since 20261201
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

DAY_FILE = re.compile(r"ui-(?:id-)?(\d{8})\.jsonl")
MAX_LINE = 4096
LEGACY_APP = "<=1.0.1"
NONE = "-"


def count_sessions(directory: Path, since: str | None = None) -> dict[tuple[str, str], int]:
    """(platform, app version) -> distinct sessions over the day files on or after ``since``."""
    # sid -> [platform, app_version], each the first one any of its rows carried
    seen: dict[str, list[str | None]] = {}
    for path in sorted(directory.iterdir()):
        m = DAY_FILE.fullmatch(path.name)
        if m is None or (since is not None and m.group(1) < since):
            continue
        with open(path, "rb") as f:
            for raw in f:
                if len(raw) > MAX_LINE:
                    continue
                try:
                    rec = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(rec, dict) or not isinstance(rec.get("sid"), str):
                    continue
                session = seen.setdefault(rec["sid"], [None, None])
                for i, field in enumerate(("platform", "app_version")):
                    if session[i] is None and isinstance(rec.get(field), str):
                        session[i] = rec[field]
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for platform, version in seen.values():
        platform = platform or NONE
        counts[(platform, version or (LEGACY_APP if platform == "ios_app" else NONE))] += 1
    return dict(counts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--dir", type=Path, default=os.environ.get("SHENGJI_TELEMETRY_DIR") or None)
    ap.add_argument("--since", help="first UTC day to count, YYYYMMDD")
    args = ap.parse_args(argv)
    if args.dir is None or not Path(args.dir).is_dir():
        print("no telemetry directory (--dir or SHENGJI_TELEMETRY_DIR)", file=sys.stderr)
        return 2
    if args.since is not None and not re.fullmatch(r"\d{8}", args.since):
        print("--since takes YYYYMMDD", file=sys.stderr)
        return 2
    counts = count_sessions(Path(args.dir), args.since)
    print(f"{'platform':<10} {'app_version':<12} sessions")
    for (platform, version), n in sorted(counts.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        print(f"{platform:<10} {version:<12} {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
