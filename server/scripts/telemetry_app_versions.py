#!/usr/bin/env python3
"""Sessions by app version, from the UI telemetry day files.

Counts distinct ``sid`` (one per socket) by ``platform`` and ``app_version``
over ``ui-YYYYMMDD.jsonl`` and ``ui-id-YYYYMMDD.jsonl`` in the telemetry
directory (``$SHENGJI_TELEMETRY_DIR`` or ``--dir``). An ``ios_app`` session
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
    sids: dict[tuple[str, str], set[str]] = defaultdict(set)
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
                platform = rec.get("platform") if isinstance(rec.get("platform"), str) else NONE
                version = rec.get("app_version") if isinstance(rec.get("app_version"), str) else None
                if version is None:
                    version = LEGACY_APP if platform == "ios_app" else NONE
                sids[(platform, version)].add(rec["sid"])
    return {key: len(v) for key, v in sids.items()}


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
    # a session that sent a platform-less batch as well counts under both rows
    for (platform, version), n in sorted(counts.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        print(f"{platform:<10} {version:<12} {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
