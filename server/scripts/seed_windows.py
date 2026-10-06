#!/usr/bin/env python3
"""Seed-window registry CLI (see shengji/seeds.py).

    python -P -B scripts/seed_windows.py list
    python -P -B scripts/seed_windows.py check SEED0 CLUSTERS [--purpose trajectory|screen|calibration|other]
    python -P -B scripts/seed_windows.py clear SEED0 CLUSTERS [--windows N --step S]
        --checkpoint PATH [--checkpoint PATH ...] [--follow-init] [--control-seed SEED ...]
        [--allow-unresolved] [--allow-seed-overlap] [--purpose screen]

``list`` prints every registered window; ``check`` prints the windows the
candidate span [SEED0, SEED0 + CLUSTERS) would overlap and exits 1 when it
overlaps any (2 when a --purpose's always-refused overlap is hit: a
trajectory refuses every overlap, a screen / calibration any trajectory).
``$SHENGJI_SEED_WINDOWS`` or ``--registry`` selects another registry file.

``clear`` is the check a screen needs before it deals (``shengji.train.seed_clearance``): the
registry check for every window, then the DEAL KEYS of every scheduled deal intersected with each
checkpoint's recorded exposure (fit + selection; with ``--follow-init`` every warm-start link too),
plus a positive control proving the recipe reproduces keys the exposure does hold.  It prints one
JSON summary line and one human line, and exits 0 only when every window is registry-clear, no
scheduled deal is in any exposure, every link resolved (or ``--allow-unresolved``, printed) and
every control passed; 1 otherwise; 2 when an input cannot be read.  torch is imported only by
``clear``.
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
    clr = sub.add_parser("clear", help="registry + deal-key exposure clearance of screen windows")
    clr.add_argument("seed0", type=int)
    clr.add_argument("clusters", type=int, help="clusters (deals) per window")
    clr.add_argument("--windows", type=int, default=1, help="number of windows (default 1)")
    clr.add_argument("--step", type=int, default=None, help="seed0 stride between windows")
    clr.add_argument("--checkpoint", action="append", required=True, default=None,
                     help="a CWV checkpoint (.pt) whose exposure the windows must avoid; repeatable")
    clr.add_argument("--follow-init", action="store_true",
                     help="also load every warm-start link (config/receipt init, exposure ancestors)")
    clr.add_argument("--allow-unresolved", action="store_true",
                     help="report, but do not fail on, links that cannot be resolved")
    clr.add_argument("--control-seed", type=int, action="append", default=[],
                     help="a training-store seed0 to probe for the positive control (default: "
                          "the first readable store manifest the checkpoint names)")
    clr.add_argument("--control-probes", type=int, default=None,
                     help="seeds probed per control start (default 64)")
    clr.add_argument("--purpose", choices=seeds.PURPOSES, default="screen")
    clr.add_argument("--allow-seed-overlap", action="store_true",
                     help="a registry overlap that the purpose allows (a deliberate replicate) passes")
    return ap


def clear(args, registry: dict) -> int:
    import json

    from shengji.train import seed_clearance as sc

    try:
        spans = sc.windows_of(args.seed0, args.clusters, args.windows, args.step)
    except sc.ClearanceError as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 2
    reg = []
    for lo, hi in spans:
        hits = seeds.overlaps(registry, lo, hi - lo)
        refused = [h["name"] for h in hits if h["purpose"] in ALWAYS_REFUSE[args.purpose]]
        status = ("refused" if refused else "overlap" if hits else "clear")
        reg.append({"seed0": lo, "status": status, "overlaps": [h["name"] for h in hits]})
    registry_ok = all(r["status"] == "clear" or (r["status"] == "overlap" and args.allow_seed_overlap)
                      for r in reg)
    try:
        report = sc.clear(spans, args.checkpoint, follow_init=args.follow_init,
                          control_seeds=args.control_seed,
                          control_probes=args.control_probes or sc.DEFAULT_CONTROL_PROBES)
    except (OSError, sc.ClearanceError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 2
    report["registry"] = {"path": str(seeds.registry_path(args.registry)), "purpose": args.purpose,
                          "ok": registry_ok, "windows": reg}
    failures = []
    if not registry_ok:
        failures.append("registry overlap")
    if report["overlaps"]:
        failures.append(f"{report['overlaps']} scheduled deal(s) in a training exposure")
    if report["unresolved"] and not args.allow_unresolved:
        failures.append(f"{len(report['unresolved'])} unresolved link(s)")
    if not report["controls_ok"]:
        failures.append("positive control failed")
    report["allow_unresolved"] = bool(args.allow_unresolved)
    report["ok"] = not failures
    report["failures"] = failures
    print(json.dumps(report, sort_keys=True, default=sorted))
    nodes = sum(len(c["nodes"]) for c in report["checkpoints"])
    ctl = ", ".join(f"{p['hits']}/{p['probed']} from {p['seed0']}"
                    for c in report["checkpoints"] for p in c["control"]["probes"]) or "none"
    unres = (f"; UNRESOLVED (allowed): {', '.join(u['path'] for u in report['unresolved'])}"
             if report["unresolved"] and args.allow_unresolved else "")
    print(f"{'CLEAR' if report['ok'] else 'NOT CLEAR: ' + '; '.join(failures)} -- "
          f"{len(spans)} window(s) x {args.clusters} = {report['deals']} deals "
          f"({report['distinct_keys']} keys) vs {len(args.checkpoint)} checkpoint(s) / {nodes} "
          f"lineage node(s): {report['overlaps']} overlap(s), registry "
          f"{'clear' if registry_ok else 'NOT clear'}, control {ctl}{unres}")
    return 0 if report["ok"] else 1


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
        if args.command == "clear":
            return clear(args, registry)
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
