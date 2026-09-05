#!/usr/bin/env python3
"""Seed-window registry CLI (see shengji/seeds.py).

    python -P -B scripts/seed_windows.py list
    python -P -B scripts/seed_windows.py check SEED0 CLUSTERS [--purpose trajectory|screen|calibration|other]

``list`` prints every registered window; ``check`` prints the windows the
candidate span [SEED0, SEED0 + CLUSTERS) would overlap and exits 1 when it
overlaps any (2 when a --purpose's always-refused overlap is hit: a
trajectory refuses every overlap, a screen / calibration any trajectory).
``$SHENGJI_SEED_WINDOWS`` or ``--registry`` selects another registry file.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shengji import seeds  # noqa: E402

#: the purposes whose overlap always refuses, per purpose of the candidate
ALWAYS_REFUSE = {"trajectory": seeds.PURPOSES, "screen": ("trajectory",),
                 "calibration": ("trajectory",), "other": ()}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="seed_windows", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--registry", default=None, help="registry file (default: committed)")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="print every registered window")
    chk = sub.add_parser("check", help="which registered windows a candidate span overlaps")
    chk.add_argument("seed0", type=int)
    chk.add_argument("clusters", type=int)
    chk.add_argument("--purpose", choices=seeds.PURPOSES, default="trajectory")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        registry = seeds.load(args.registry)
        if args.command == "list":
            print(f"{seeds.registry_path(args.registry)}: {len(registry['windows'])} window(s)")
            for w in sorted(registry["windows"], key=lambda w: (w["seed0"], w["name"])):
                print(f"  [{w['span'][0]}, {w['span'][1]}) {w['purpose']:<11} "
                      f"{w['name']:<32} clusters={w['clusters']:<6} {w['created_at']}"
                      + (f"  -- {w['note']}" if w["note"] else ""))
            return 0
        hits = seeds.overlaps(registry, args.seed0, args.clusters)
        lo, hi = seeds.window(args.seed0, args.clusters)
        if not hits:
            print(f"[{lo}, {hi}) is disjoint from every registered window")
            return 0
        print(f"[{lo}, {hi}) overlaps {len(hits)} registered window(s):")
        for h in hits:
            print("  " + seeds.describe(h))
        refused = [h for h in hits if h["purpose"] in ALWAYS_REFUSE[args.purpose]]
        if refused:
            print(f"REFUSED for a {args.purpose} window: overlaps "
                  + ", ".join(h["name"] for h in refused))
            return 2
        print(f"allowed for a {args.purpose} window only with --allow-seed-overlap "
              "(a deliberate replicate)")
        return 1
    except seeds.SeedWindowError as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
