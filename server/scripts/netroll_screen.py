#!/usr/bin/env python3
"""Net-rollout screen (DEV): coarse cost calibration per K, then the paired
mirrored screen of production-with-net-rollouts against production.  See
shengji/train/netroll_screen.py and shengji/train/net_rollout.py.

    # 1. outcome-blind cost calibration of the learned arm at K in {1,2,4}
    #    (production's N=30/R=300; ratios reported, never gated)
    SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 python -P -B scripts/netroll_screen.py calibrate \
        --checkpoint /path/to/cwv/runAB-mlp-points/best.pt --tricks 1,2,4 \
        --trump-ranks 2 --clusters 4 --workers 2 --out /path/to/netroll-calib

    # 2. the screen: {learned, prior} x K x fresh clusters vs production, plus
    #    production's x3 reference on the same deals
    SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 python -P -B scripts/netroll_screen.py run \
        --checkpoint /path/to/cwv/runAB-mlp-points/best.pt --tricks 1,2 \
        --arms learned,prior,reference --calibration /path/to/netroll-calib/calibration.json \
        --trump-ranks 2 --clusters 256 --workers 3 --out /path/to/netroll-screen

Every complete mirrored pair publishes atomically; rerun the identical
command to finish only missing pairs.  Nothing here registers a production
default or makes a strength claim.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from shengji.train import netroll_screen as S  # noqa: E402
from shengji.train.net_rollout import NET_STAGES, NetRolloutError  # noqa: E402
from shengji import seeds  # noqa: E402
from shengji.train.search_screen import _publish  # noqa: E402


def _tricks(text: str) -> tuple[int, ...]:
    try:
        values = tuple(int(v) for v in text.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError("tricks must be comma-separated integers")
    if not values or len(set(values)) != len(values) or min(values) < 1:
        raise argparse.ArgumentTypeError("tricks must be distinct positive integers")
    return values


def _trump_ranks(text: str):
    try:
        return S.parse_trump_ranks(text)
    except S.ScreenError as exc:
        raise argparse.ArgumentTypeError(str(exc))


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    def common(p, *, seed0):
        p.add_argument("--checkpoint", required=True,
                       help="train_cwv.py --arch mlp checkpoint (its metadata carries the prior)")
        p.add_argument("--net-stage", choices=NET_STAGES, default="report",
                       help="report: net rollouts in the report fold only; all: selection too")
        p.add_argument("--tricks", type=_tricks, default=(1, 2),
                       help="K values (net-driven tricks per continuation)")
        p.add_argument("--clusters", type=int, default=4)
        p.add_argument("--seed0", type=int, default=seed0)
        p.add_argument("--workers", type=int, default=2)
        p.add_argument("--report-worlds", type=int, default=S.REPORT_WORLDS)
        p.add_argument("--baseline-select-worlds", type=int, default=S.BASELINE_SELECT_WORLDS)
        p.add_argument("--trump-ranks", type=_trump_ranks, default=None,
                       help="comma-separated trump ranks cycled over clusters (default: all 13); "
                            "the Run A/B checkpoints saw rank-2 rounds only, so --trump-ranks 2 "
                            "keeps the net in distribution")
        p.add_argument("--out", type=Path, required=True)

    cal = sub.add_parser("calibrate", help="outcome-blind cost calibration per K")
    common(cal, seed0=S.DEFAULT_CALIBRATION_SEED0)

    run = sub.add_parser("run", help="the paired mirrored screen")
    common(run, seed0=S.DEFAULT_SEED0)
    run.add_argument("--calibration", help="calibration.json (calibrate); binds K/stage/checkpoint")
    run.add_argument("--allow-seed-overlap", action="store_true",
                     help="screen a window that overlaps another registered SCREEN / "
                          "calibration window (a deliberate same-seed replicate; recorded "
                          "in summary.json seed_window); an overlap with a trajectory "
                          "(training) window always refuses")
    run.add_argument("--arms", default="learned,prior,reference",
                     help="comma-separated subset of learned,prior,reference")
    run.add_argument("--reference-multiplier", type=float, default=S.REFERENCE_MULTIPLIER)
    run.add_argument("--bootstrap-replicates", type=int, default=S.DEFAULT_BOOTSTRAP_REPLICATES)
    return ap


def _screen_window(args, out: Path) -> dict:
    """The screen's deal window [seed0, seed0 + clusters) against the
    seed-window registry BEFORE any deal: an overlap with a trajectory
    (training) window always refuses; with another screen / calibration
    window only with --allow-seed-overlap (a deliberate replicate, named in
    the receipt).  The window is registered under this --out (a rerun of the
    identical command reuses it)."""
    return seeds.check_and_register(
        name=f"netroll-screen:{out.resolve()}", purpose="screen", seed0=args.seed0,
        clusters=args.clusters, refuse=("trajectory",), allow_overlap=args.allow_seed_overlap,
        resume=True, note=f"netroll_screen run out={out.resolve()}",
        what=f"netroll_screen run {out}")


def _calibration_window(args, out: Path) -> dict:
    """Register the outcome-blind calibration window (refuses only a
    trajectory overlap; other overlaps are recorded) and leave a receipt
    next to calibration.json."""
    receipt = seeds.check_and_register(
        name=f"netroll-calibrate:{out.resolve()}", purpose="calibration", seed0=args.seed0,
        clusters=args.clusters, refuse=("trajectory",), allow_overlap=True, resume=True,
        note=f"netroll_screen calibrate out={out.resolve()}", what=f"netroll_screen calibrate {out}")
    out.mkdir(parents=True, exist_ok=True)
    _publish(out / "seed_window.json", receipt)
    return receipt


def _calibrate(args) -> int:
    _calibration_window(args, Path(args.out))
    config = S.build_config(arm="learned", net_tricks=args.tricks[0], net_stage=args.net_stage,
                            seed0=args.seed0, clusters=args.clusters, checkpoint=args.checkpoint,
                            baseline_select_worlds=args.baseline_select_worlds,
                            report_worlds=args.report_worlds, trump_ranks=args.trump_ranks)
    calibration = S.calibrate(config, output=args.out, workers=args.workers, tricks=args.tricks)
    print(json.dumps({
        "binding": calibration["binding"], "identity_sha256": calibration["identity_sha256"],
        "table": [{k: row[k] for k in ("net_tricks", "arm_policy", "clusters", "decision_cpu_ratio",
                                       "decision_wall_ratio", "per_decision_cpu_seconds",
                                       "per_decision_wall_seconds", "per_decision_net_plays",
                                       "per_decision_net_positions", "per_decision_batches",
                                       "per_net_position_usecs", "net_share_of_decision_wall")}
                  for row in calibration["table"]],
        "outcomes_read": calibration["outcomes_read"],
        "calibration": str(Path(args.out) / "calibration.json"),
    }, indent=2))
    return 0


def _run(args) -> int:
    arms = tuple(a.strip() for a in args.arms.split(",") if a.strip())
    if not arms or any(a not in S.ARMS for a in arms):
        print(f"REFUSING: --arms must be a subset of {S.ARMS}", file=sys.stderr)
        return 2
    calibration = S.load_calibration(args.calibration) if args.calibration else None
    out = Path(args.out)
    seed_window = _screen_window(args, out)      # refuse before any deal
    summaries = {}
    for arm in arms:
        ks = (None,) if arm == "reference" else args.tricks
        for k in ks:
            config = S.build_config(
                arm=arm, net_tricks=k, net_stage=args.net_stage, seed0=args.seed0,
                clusters=args.clusters, checkpoint=args.checkpoint,
                baseline_select_worlds=args.baseline_select_worlds,
                report_worlds=args.report_worlds, trump_ranks=args.trump_ranks,
                reference_multiplier=args.reference_multiplier,
                calibration=calibration if arm != "reference" else None,
                bootstrap_replicates=args.bootstrap_replicates)
            summaries[config["arm_label"]] = S.run_arm(config, output=out / config["arm_label"],
                                                       workers=args.workers)
    combined = S.combined_summary(summaries, seed0=args.seed0, replicates=args.bootstrap_replicates)
    combined["seed_window"] = seed_window
    _publish(out / "summary.json", combined)
    print(json.dumps(combined, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "calibrate":
            return _calibrate(args)
        return _run(args)
    except (S.ScreenError, NetRolloutError, seeds.SeedWindowError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
