#!/usr/bin/env python3
"""Build or independently reopen the outcome-blind E3/E4 population."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def _preimport_guard() -> None:
    if not sys.flags.safe_path or not sys.dont_write_bytecode \
            or os.environ.get("PYTHONPATH") \
            or os.environ.get("SHENGJI_FAST") != "1" \
            or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise RuntimeError("population requires -P -B and strict environment")
    server = Path(__file__).resolve().parents[1]
    bytecode = [
        path for root in (server / "shengji", server / "scripts")
        for path in root.rglob("*")
        if path.is_file() and (path.suffix == ".pyc"
                               or "__pycache__" in path.parts)]
    if bytecode:
        raise RuntimeError("population source tree contains Python bytecode")


_preimport_guard()
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

from shengji.engine import combos, fast
from shengji.engine.round import Round
from shengji.rl.world_afterstate_population_builder import (
    build_outcome_blind_population, publish_population_build,
    reopen_population_build)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True,
        text=True).stdout.strip()


def _strict_source(expected_git: str) -> Path:
    repo = Path(__file__).resolve().parents[2]
    if type(expected_git) is not str or len(expected_git) != 40 \
            or any(char not in "0123456789abcdef" for char in expected_git) \
            or _git(repo, "rev-parse", "HEAD") != expected_git \
            or _git(repo, "status", "--porcelain", "--untracked-files=all"):
        raise RuntimeError("population requires the exact clean source head")
    native = getattr(fast, "_fast", None)
    if fast.HAVE_FAST is not True or native is None \
            or combos.decompose is not fast.decompose \
            or Round.play is not native.round_play:
        raise RuntimeError("population requires the active compiled engine")
    return repo


def _progress(stage: str, completed: int, total: int) -> None:
    if not 0 <= completed <= total or total <= 0:
        raise RuntimeError("population progress drift")
    print(json.dumps({
        "schema": "world-afterstate-population-progress-v0",
        "stage": stage, "completed": completed, "total": total,
        "percent_basis_points": completed * 10_000 // total,
        "outcome_opened": False, "evidence_artifact": False,
        "scientific_training_authorized": False,
        "gameplay_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }, sort_keys=True, separators=(",", ":")), flush=True)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("mode", choices=("build", "verify"))
    value.add_argument("--out", required=True)
    value.add_argument("--expected-git", required=True)
    value.add_argument("--pt-sol-report")
    value.add_argument("--pt-sol-private")
    return value


def main() -> None:
    args = parser().parse_args()
    _strict_source(args.expected_git)
    target = Path(args.out)
    started = time.monotonic_ns()
    if args.mode == "build":
        if not args.pt_sol_report or not args.pt_sol_private:
            raise RuntimeError("population build requires PT-Sol inputs")
        report_raw = Path(args.pt_sol_report).read_bytes()
        build = build_outcome_blind_population(
            source_git=args.expected_git, pt_sol_report_raw=report_raw,
            pt_sol_private_root=Path(args.pt_sol_private),
            progress=_progress)
        publish_population_build(target, build)
    receipt = reopen_population_build(target)
    print(json.dumps({
        "schema": "world-afterstate-population-completion-v0",
        "mode": args.mode, "elapsed_nanoseconds": time.monotonic_ns() - started,
        **receipt, "evidence_artifact": False,
        "continuation_dataset_generation_authorized": False,
        "scientific_training_authorized": False,
        "report_opening_authorized": False,
        "gameplay_authorized": False, "strength_claim_authorized": False,
        "deployment_authorized": False,
    }, sort_keys=True, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
