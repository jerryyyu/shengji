"""``harvest`` command line (see ``scripts/harvest.py``).

    harvest <source> --out DIR        one of luna-rpc room-log pt1 highn human
    harvest all --out DIR             every source + ballot-gap + manifest
    harvest ballot-gap --out DIR      the ballot-gap report only
    harvest manifest DIR              (re)build manifest.json from DIR
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from .common import InputRegistry
from .legal import DEFAULT_CAP

SOURCES = ("luna-rpc", "room-log", "pt1", "highn", "human")


def run_source(name: str, out: Path, *, cap: int | None, limit: int | None,
               workers: int | None, log=print) -> dict:
    from .manifest import write_source
    registry = InputRegistry()
    t0 = time.perf_counter()
    if name == "luna-rpc":
        from .luna_rpc import extract_luna
        result = extract_luna(cap=cap, registry=registry, limit=limit)
    elif name == "room-log":
        from .room_log import extract_room_logs
        result = extract_room_logs(cap=cap, registry=registry, limit_rounds=limit)
    elif name == "pt1":
        from .pt1 import extract_pt1

        def progress(i, n):
            if (i + 1) % 20 == 0 or i + 1 == n:
                log(f"  pt1 replay {i + 1}/{n} ({time.perf_counter() - t0:.0f}s)")
        result = extract_pt1(cap=cap, registry=registry, workers=workers,
                             limit=limit, progress=progress)
    elif name == "highn":
        from .highn import extract_highn
        result = extract_highn(cap=cap, registry=registry, limit=limit)
    elif name == "human":
        from .human import extract_human
        result = extract_human(cap=cap, registry=registry)
    else:
        raise SystemExit(f"unknown source {name!r}")
    sidecar = write_source(out, result, cap=cap)
    log(f"{name}: {sidecar['counts']} -> {out} ({time.perf_counter() - t0:.1f}s)")
    return sidecar


def run_ballot_gap(out: Path, log=print) -> dict:
    from .ballot_gap import build_report, headline, write_report
    t0 = time.perf_counter()
    report = build_report(InputRegistry())
    path = write_report(out, report)
    log(headline(report))
    log(f"ballot-gap -> {path} ({time.perf_counter() - t0:.1f}s)")
    return report


def run_manifest(out: Path, log=print) -> dict:
    from .manifest import build_manifest, summary_lines
    manifest = build_manifest(out)
    for line in summary_lines(manifest):
        log(line)
    log(f"manifest -> {Path(out) / 'manifest.json'}")
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harvest", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p):
        p.add_argument("--out", required=True, type=Path, help="output directory")
        p.add_argument("--cap", type=int, default=DEFAULT_CAP,
                       help=f"max legal actions listed per record (default {DEFAULT_CAP}; "
                            "0 = unbounded)")
        p.add_argument("--limit", type=int, default=None,
                       help="extract only the first N games/rounds/rows (smoke runs)")
        p.add_argument("--pt1-workers", type=int, default=None,
                       help="process-pool size for the PT1 replay (default min(8, cpus))")

    for name in (*SOURCES, "all"):
        add_common(sub.add_parser(name))
    sub.add_parser("ballot-gap").add_argument("--out", required=True, type=Path)
    sub.add_parser("manifest").add_argument("dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    os.environ.setdefault("SHENGJI_REQUIRE_VOIDS", "1")
    args = build_parser().parse_args(argv)
    if args.command == "manifest":
        run_manifest(args.dir)
        return 0
    if args.command == "ballot-gap":
        run_ballot_gap(args.out)
        return 0
    cap = None if args.cap == 0 else args.cap
    names = SOURCES if args.command == "all" else (args.command,)
    for name in names:
        run_source(name, args.out, cap=cap, limit=args.limit,
                   workers=args.pt1_workers)
    if args.command == "all":
        run_ballot_gap(args.out)
        run_manifest(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
