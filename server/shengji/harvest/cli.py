"""``harvest`` command line (see ``scripts/harvest.py``).

    harvest <source> --out DIR        one of luna-rpc room-log pt1 highn human
    harvest all --out DIR             every source + ballot-gap + manifest
    harvest ballot-gap --out DIR      the ballot-gap report only
    harvest ballot-capture --out DIR [--inputs DIR] [--variants ...] [--limit N]
                                      candidate-generator variant capture rates
                                      over human.jsonl + luna-rpc.private.jsonl
    harvest manifest DIR              (re)build manifest.json from DIR
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from .ballot_capture import SOURCE_FILES, VARIANTS
from .common import InputRegistry
from .legal import DEFAULT_CAP

SOURCES = ("luna-rpc", "room-log", "pt1", "highn", "human")


def _log(*parts) -> None:
    """Unbuffered progress lines (a redirected stdout is block-buffered and
    a 30-minute PT1 replay would otherwise look stuck)."""
    print(*parts, flush=True)


def run_source(name: str, out: Path, *, cap: int | None, limit: int | None,
               workers: int | None, log=_log) -> dict:
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


def run_ballot_gap(out: Path, log=_log) -> dict:
    from .ballot_gap import build_report, headline, write_report
    t0 = time.perf_counter()
    report = build_report(InputRegistry())
    path = write_report(out, report)
    log(headline(report))
    log(f"ballot-gap -> {path} ({time.perf_counter() - t0:.1f}s)")
    return report


def run_ballot_capture(out: Path, *, inputs: Path | None = None,
                       variants: list[str] | None = None, limit: int | None = None,
                       log=_log) -> dict:
    """Read ``human.jsonl`` and ``luna-rpc.private.jsonl`` from ``inputs``
    (default: ``out``, the ``harvest all`` layout) and write
    ``ballot_capture.json`` / ``ballot_capture.md`` to ``out``."""
    from .ballot_capture import build_report, headline, write_report
    t0 = time.perf_counter()
    inputs = Path(out if inputs is None else inputs)
    paths = {name: inputs / file_name for name, file_name in SOURCE_FILES}
    report = build_report(human=paths["human"], luna=paths["luna"],
                          variants=tuple(variants or VARIANTS), limit=limit)
    json_path, _ = write_report(out, report)
    for line in headline(report):
        log(line)
    for note in report["notes"]:
        if "source skipped" in note:
            log(f"note: {note}")
    log(f"ballot-capture -> {json_path} ({time.perf_counter() - t0:.1f}s)")
    return report


def run_manifest(out: Path, log=_log) -> dict:
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
    quality = sub.add_parser("luna-quality", help="explicit flat gameplay export; excluded from all")
    quality.add_argument("--run", type=Path, action="append", required=True)
    quality.add_argument("--split", choices=("fit", "validation"), required=True)
    quality.add_argument("--out", type=Path, required=True)
    quality.add_argument("--cap", type=int, default=DEFAULT_CAP)
    sub.add_parser("ballot-gap").add_argument("--out", required=True, type=Path)
    capture = sub.add_parser("ballot-capture")
    capture.add_argument("--out", required=True, type=Path, help="output directory")
    capture.add_argument("--inputs", type=Path, default=None,
                         help="directory holding human.jsonl and "
                              "luna-rpc.private.jsonl (default: --out)")
    capture.add_argument("--variants", nargs="+", choices=VARIANTS, default=None,
                         metavar="VARIANT",
                         help=f"variants to score (default: all of {', '.join(VARIANTS)}; "
                              "production is always included)")
    capture.add_argument("--limit", type=int, default=None,
                         help="score only the first N rows of each input file (smoke runs)")
    sub.add_parser("manifest").add_argument("dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    os.environ.setdefault("SHENGJI_REQUIRE_VOIDS", "1")
    args = build_parser().parse_args(argv)
    if args.command == "luna-quality":
        from .luna_quality import extract_quality_games
        from .manifest import write_source
        if args.out.exists() and any(args.out.iterdir()):
            raise SystemExit("luna-quality output must be new or empty; source artifacts are never overwritten")
        cap = None if args.cap == 0 else args.cap
        result = extract_quality_games(args.run, split=args.split, cap=cap)
        sidecar = write_source(args.out, result, cap=cap)
        _log(f"luna-quality {args.split}: {sidecar['counts']} -> {args.out}")
        return 0
    if args.command == "manifest":
        run_manifest(args.dir)
        return 0
    if args.command == "ballot-gap":
        run_ballot_gap(args.out)
        return 0
    if args.command == "ballot-capture":
        run_ballot_capture(args.out, inputs=args.inputs, variants=args.variants,
                           limit=args.limit)
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
