#!/usr/bin/env python3
"""Value-at-leaf equal-work screen (DEV): fit the no-learning prior, calibrate
CPU parity, run the paired mirrored screen.  See shengji/train/leaf_screen.py.

    # 1. the no-learning control's table: the trainer's strata on FINAL
    #    attacker points, refitted on the receipt's TRAIN cache files
    python -P -B scripts/vleaf_screen.py fit-prior \
        --receipt /path/to/runA-points/receipt.json --out /path/to/prior_points.json

    # 2. outcome-blind CPU-parity calibration of the learned arm's selection N
    SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 python -P -B scripts/vleaf_screen.py calibrate \
        --checkpoint /path/to/runA-points/best.pt --leaf-tricks 1 \
        --clusters 4 --workers 2 --out /path/to/calib

    # 3. the screen: {learned, prior} x fresh clusters vs production
    SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 python -P -B scripts/vleaf_screen.py run \
        --checkpoint /path/to/runA-points/best.pt --prior /path/to/prior_points.json \
        --calibration /path/to/calib/calibration.json --leaf-tricks 1 \
        --clusters 4 --workers 2 --seed0 50260904 --out /path/to/screen

    # the complete-world net at the leaf (`--leaf-model cwv`): the checkpoint
    # is a train_cwv.py --arch mlp --aux-points best.pt; the arm is
    # mc-vleaf-cwv-<ckpt8>-t<T>; calibrate and run take the same flag and a
    # calibration made for one leaf model is refused by the other
    SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 python -P -B scripts/vleaf_screen.py calibrate \
        --leaf-model cwv --checkpoint /path/to/cwv/runAB-mlp-points/best.pt --leaf-tricks 1 \
        --trump-ranks 2 --clusters 4 --workers 2 --out /path/to/calib-cwv

    # variants (both bind into the calibration and the names): the leaf in the
    # report fold only (`--leaf-stage report`, mc-vleaf-cwv-<ckpt8>-t<T>-report;
    # selection rollouts are production's, so parity N sits near production's
    # 30) and the control variate (`--leaf-mode control-variate`, ...-cv; full
    # playouts plus the net calls, only the report fold's paired SE changes)
    SHENGJI_FAST=1 SHENGJI_REQUIRE_VOIDS=1 python -P -B scripts/vleaf_screen.py calibrate \
        --leaf-model cwv --leaf-stage report --checkpoint /path/to/cwv/best.pt --leaf-tricks 1 \
        --trump-ranks 2 --grid 15,20,25,30 --clusters 4 --workers 2 --out /path/to/calib-report

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

from shengji.ai.registry import VLEAF_LEAF_TRICKS  # noqa: E402
from shengji.train import leaf_screen as S  # noqa: E402
from shengji.train.leaf_policy import LeafError, fit_points_prior  # noqa: E402
from shengji.train.search_screen import _publish  # noqa: E402


def _grid(text: str) -> tuple[int, ...]:
    try:
        grid = tuple(int(v) for v in text.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError("grid must be comma-separated integers")
    if not grid or len(set(grid)) != len(grid) or min(grid) < 1:
        raise argparse.ArgumentTypeError("grid must be distinct positive integers")
    return grid


def _trump_ranks(text: str) -> tuple[str, ...]:
    try:
        return S.parse_trump_ranks(text)
    except S.ScreenError as exc:
        raise argparse.ArgumentTypeError(str(exc))


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    fit = sub.add_parser("fit-prior", help="refit the stratified prior on final attacker points")
    fit.add_argument("--receipt", required=True,
                     help="train_v0 receipt.json: its split and TRAIN cache files are authoritative")
    fit.add_argument("--out", required=True, help="prior_points.json to write")
    fit.add_argument("--part", default="train", choices=("train",),
                     help="rows to fit on (the trainer fits its prior on train)")

    def common(p, *, seed0):
        p.add_argument("--checkpoint", required=True)
        p.add_argument("--allow-legacy", action="store_true",
                       help="accept the v2 checkpoint schema (no held-out claim)")
        p.add_argument("--leaf-tricks", type=int, choices=VLEAF_LEAF_TRICKS, default=1)
        p.add_argument("--leaf-model", choices=S.LEAF_MODELS, default=S.DEFAULT_LEAF_MODEL,
                       help="which net evaluates the truncated leaf: 'public' = the search "
                            "checkpoint's aux points head on the public observation "
                            "(mc-vleaf-<ckpt8>-t<T>); 'cwv' = the complete-world value net's "
                            "aux points head on the determinized clone itself "
                            "(mc-vleaf-cwv-<ckpt8>-t<T>; needs a train_cwv.py --arch mlp "
                            "--aux-points checkpoint)")
        p.add_argument("--leaf-stage", choices=S.LEAF_STAGES, default=S.DEFAULT_LEAF_STAGE,
                       help="where the leaf is consulted: 'all' = every rollout (current "
                            "behaviour); 'report' = only inside the report fold (the top two "
                            "candidates on the R paired worlds), selection rollouts run to "
                            "round end exactly as production's (name suffix -report)")
        p.add_argument("--leaf-mode", choices=S.LEAF_MODES, default=S.DEFAULT_LEAF_MODE,
                       help="'replace' = the rollout stops at the horizon and returns the "
                            "estimate; 'control-variate' = the rollout runs to round end and "
                            "the estimate at the horizon is subtracted as a per-candidate "
                            "centred control variate: means and the paired gap stay "
                            "production's, only the paired SE (hence the LCB) changes "
                            "(name suffix -cv)")
        p.add_argument("--beta", type=float, default=S.DEFAULT_CV_BETA,
                       help="control-variate coefficient (default 1.0; 0 is production "
                            "byte for byte)")
        p.add_argument("--clusters", type=int, default=4)
        p.add_argument("--seed0", type=int, default=seed0)
        p.add_argument("--workers", type=int, default=2)
        p.add_argument("--report-worlds", type=int, default=S.REPORT_WORLDS)
        p.add_argument("--baseline-select-worlds", type=int, default=S.BASELINE_SELECT_WORLDS)
        p.add_argument("--trump-ranks", type=_trump_ranks, default=None,
                       help="comma-separated trump ranks cycled over clusters (default: all 13, "
                            "#222's cycle); the Run A/B/C checkpoints saw rank-2 first rounds "
                            "only and the encoder one-hots the rank, so --trump-ranks 2 keeps "
                            "the learned leaf in distribution; run refuses a calibration made "
                            "on other ranks")
        p.add_argument("--out", type=Path, required=True)

    cal = sub.add_parser("calibrate", help="outcome-blind CPU-parity calibration of N")
    common(cal, seed0=S.DEFAULT_CALIBRATION_SEED0)
    cal.add_argument("--grid", type=_grid, default=S.DEFAULT_GRID,
                     help="selection doses to measure (default 30,45,60,90)")

    run = sub.add_parser("run", help="the paired mirrored screen")
    common(run, seed0=S.DEFAULT_SEED0)
    run.add_argument("--prior", required=True, help="prior_points.json (fit-prior)")
    run.add_argument("--calibration", help="calibration.json (calibrate); frozen arm N")
    run.add_argument("--arm-select-worlds", type=int,
                     help="explicit arm N (smoke/wiring only; the calibration is the method)")
    run.add_argument("--allow-extrapolated-n", action="store_true",
                     help="accept a calibration whose parity N lies outside its measured grid "
                          "(an extrapolation, not an interpolation); prefer re-calibrating "
                          "with --grid around that N")
    run.add_argument("--arms", default="learned,prior",
                     help="comma-separated subset of learned,prior")
    run.add_argument("--bootstrap-replicates", type=int, default=S.DEFAULT_BOOTSTRAP_REPLICATES)
    return ap


def _fit_prior(args) -> int:
    receipt_path = Path(args.receipt).resolve()
    receipt = json.loads(receipt_path.read_text())
    split = receipt.get("split") or {}
    stores = receipt.get("data") or []
    files = [(entry["cache"], entry["shard_sha256"]) for store in stores
             for entry in store.get("cache", [])]
    if not files or "seed" not in split:
        print("REFUSING: receipt has no cache file list or split", file=sys.stderr)
        return 2
    missing = [path for path, _ in files if not Path(path).exists()]
    if missing:
        print(f"REFUSING: {len(missing)} cache files named by the receipt are missing "
              f"(first: {missing[0]})", file=sys.stderr)
        return 2
    print(f"fit-prior: {len(files)} cache files, split seed={split['seed']} "
          f"val={split['val_fraction']} test={split['test_fraction']}", flush=True)
    try:
        table = fit_points_prior([p for p, _ in files], split_seed=int(split["seed"]),
                                 val_fraction=float(split["val_fraction"]),
                                 test_fraction=float(split["test_fraction"]),
                                 part=args.part, expected_shards=dict(files))
    except LeafError as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 2
    prov = table.provenance
    expected = {"deals": split.get(f"{args.part}_deals"), "records": split.get(f"{args.part}_records")}
    got = {"deals": prov["deals"][args.part], "records": prov["rows"][args.part]}
    if expected["deals"] is not None and (expected["deals"], expected["records"]) != (got["deals"], got["records"]):
        print(f"REFUSING: refit population {got} != receipt's {args.part} split {expected}",
              file=sys.stderr)
        return 2
    prov["receipt"] = {"path": str(receipt_path),
                       "sha256": S.vleaf_checkpoint_sha256(receipt_path),
                       "schema": receipt.get("schema"), "config_sha256": receipt.get("config_sha256"),
                       "split": {k: split.get(k) for k in ("seed", "val_fraction", "test_fraction",
                                                           "train_deals", "train_records")}}
    payload = table.to_dict()
    _publish(Path(args.out), payload)
    print(json.dumps({"out": str(args.out), "n": payload["n"], "global_mean": payload["global_mean"],
                      "empty_cells": payload["empty_cells"],
                      "cells": [(c["stratum"], c["n"], round(c["mean"], 2)) for c in payload["cells"]]},
                     indent=2))
    return 0


def _calibrate(args) -> int:
    config = S.build_config(arm="learned", leaf_tricks=args.leaf_tricks, seed0=args.seed0,
                            clusters=args.clusters, arm_select_worlds=args.grid[0],
                            checkpoint=args.checkpoint, allow_legacy=args.allow_legacy,
                            baseline_select_worlds=args.baseline_select_worlds,
                            report_worlds=args.report_worlds, trump_ranks=args.trump_ranks,
                            leaf_model=args.leaf_model, leaf_stage=args.leaf_stage,
                            leaf_mode=args.leaf_mode, beta=args.beta)
    calibration = S.calibrate(config, output=args.out, workers=args.workers, grid=args.grid)
    print(json.dumps({
        "chosen_arm_select_worlds": calibration["chosen_arm_select_worlds"],
        "arm_policy": calibration["arm_policy"], "leaf_model": calibration["leaf_model"],
        "leaf_stage": calibration["leaf_stage"], "leaf_mode": calibration["leaf_mode"],
        "cv_beta": calibration["cv_beta"],
        "trump_ranks": calibration["trump_ranks"],
        "predicted_decision_cpu_ratio": calibration["predicted_decision_cpu_ratio"],
        "within_band": calibration["within_band"], "within_grid": calibration["within_grid"],
        "grid": [{"n": row["n"], "decision_cpu_ratio": row["decision_cpu_ratio"],
                  "per_decision_cpu_ratio": row["per_decision_cpu_ratio"],
                  "arm_cpu_s": row["decision_cpu_seconds"]["arm"],
                  "baseline_cpu_s": row["decision_cpu_seconds"]["baseline"],
                  "per_leaf_usecs": row["per_leaf_usecs"]["arm"],
                  "net_calls_by_stage": row["net_calls_by_stage"]["arm"]}
                 for row in calibration["grid"]],
        "fit": calibration["choice"].get("fit"),
        "outcomes_read": calibration["outcomes_read"],
        "calibration": str(Path(args.out) / "calibration.json"),
    }, indent=2))
    return 0


def _run(args) -> int:
    arms = tuple(a.strip() for a in args.arms.split(",") if a.strip())
    if not arms or any(a not in S.ARMS for a in arms):
        print(f"REFUSING: --arms must be a subset of {S.ARMS}", file=sys.stderr)
        return 2
    calibration = None
    if args.arm_select_worlds is not None:
        n = args.arm_select_worlds
    elif args.calibration:
        calibration = S.load_calibration(args.calibration)
        n = calibration["chosen_arm_select_worlds"]
        if not calibration.get("within_band", False):
            print(f"REFUSING: calibration predicts CPU ratio "
                  f"{calibration.get('predicted_decision_cpu_ratio')} at N={n}, outside "
                  f"{S.PARITY_BAND}; parity was not reached", file=sys.stderr)
            return 2
        if not calibration.get("within_grid", False) and not args.allow_extrapolated_n:
            grid = [row["n"] for row in calibration.get("grid", [])]
            print(f"REFUSING: parity N={n} lies outside the calibration grid {grid} "
                  f"(extrapolated); re-run calibrate with --grid around {n}, or pass "
                  f"--allow-extrapolated-n for a wiring run", file=sys.stderr)
            return 2
    else:
        print("REFUSING: run needs --calibration (the method) or --arm-select-worlds (wiring)",
              file=sys.stderr)
        return 2
    out = Path(args.out)
    summaries = {}
    for arm in arms:
        config = S.build_config(arm=arm, leaf_tricks=args.leaf_tricks, seed0=args.seed0,
                                clusters=args.clusters, arm_select_worlds=n,
                                checkpoint=args.checkpoint, allow_legacy=args.allow_legacy,
                                prior=args.prior, baseline_select_worlds=args.baseline_select_worlds,
                                report_worlds=args.report_worlds, calibration=calibration,
                                bootstrap_replicates=args.bootstrap_replicates,
                                trump_ranks=args.trump_ranks, leaf_model=args.leaf_model,
                                leaf_stage=args.leaf_stage, leaf_mode=args.leaf_mode,
                                beta=args.beta)
        summaries[arm] = S.run_arm(config, output=out / arm, workers=args.workers)
    combined = S.combined_summary(summaries, seed0=args.seed0,
                                  replicates=args.bootstrap_replicates)
    _publish(out / "summary.json", combined)
    print(json.dumps(combined, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "fit-prior":
            return _fit_prior(args)
        if args.command == "calibrate":
            return _calibrate(args)
        return _run(args)
    except (S.ScreenError, LeafError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
