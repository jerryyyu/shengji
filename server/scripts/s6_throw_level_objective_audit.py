#!/usr/bin/env python3
"""Reprice every S6 override with the level-bracket rollout objective.

The current S6 probe selects throws with raw attacker-point rollouts even
though complete-round strength is judged by signed level utility.  This
selected-DEV diagnostic reconstructs the exact 300 report worlds for all 12
observed overrides and computes both objectives on the same candidate and
incumbent continuations.  It asks whether changing only the secondary S6
probe's scoring objective would reject the observed loss or retain a useful
subset.

The overrides were selected by the point objective, so this cannot discover
level-objective-only proposals or establish strength.  It can cheaply decide
whether a full matched DEV pilot is worth implementing.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import s6_boss_near_loss_replay as REPLAY  # noqa: E402
import s6_throw_reliability_audit as RELIABILITY  # noqa: E402
from shengji.ai.memory import Memory  # noqa: E402
from shengji.engine import combos, fast  # noqa: E402


SCHEMA = "s6-throw-level-objective-audit-v1"
REPORT_WORLDS = RELIABILITY.REPORT_WORLDS
ATTEMPT_FACTOR = RELIABILITY.ATTEMPT_FACTOR
REPORT_CRITICAL = 1.70
REPORT_MIN_GAIN = 0.0


class LevelAuditRefused(RuntimeError):
    """The selected S6 roots cannot support this objective comparison."""


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True,
        capture_output=True, text=True).stdout.strip()


def _level_score(bot, attacker_points: float) -> float:
    original = bot.LEVEL_OBJECTIVE
    try:
        bot.LEVEL_OBJECTIVE = True
        return float(bot._score(attacker_points))
    finally:
        bot.LEVEL_OBJECTIVE = original


def _signed_delta(rnd, seat: int, candidate: float, incumbent: float) -> float:
    delta = candidate - incumbent
    return delta if rnd.is_attacker(seat) else -delta


def _audit_witness(witness: tuple[int, int]) -> tuple[tuple[int, int], dict]:
    seed, flip = witness
    rnd, bot, seat, candidate, decision = RELIABILITY._capture_override(
        seed, flip)
    incumbent_record = decision.get("s6_incumbent_decision")
    report = decision.get("report_fold")
    if (not isinstance(incumbent_record, dict)
            or not isinstance(incumbent_record.get("played"), list)
            or not isinstance(report, dict)
            or report.get("complete") is not True
            or report.get("worlds") != REPORT_WORLDS):
        raise LevelAuditRefused("override lacks complete report evidence")
    incumbent = list(incumbent_record["played"])
    report_seed = decision.get("report_seed")
    if not isinstance(report_seed, int):
        raise LevelAuditRefused("override omitted report seed")

    memory = Memory(rnd, seat, own_kitty=True)
    point_deltas = []
    level_deltas = []
    attempts = 0
    original_rng = bot.rng
    try:
        bot.rng = random.Random(report_seed)
        while len(point_deltas) < REPORT_WORLDS \
                and attempts < REPORT_WORLDS * ATTEMPT_FACTOR:
            attempts += 1
            sampled = bot._sample_hands(rnd, seat, memory)
            if sampled is None:
                continue
            hands, buried = sampled
            exact_session = bot._new_exact_world_session(rnd, buried)
            candidate_points = bot._rollout(
                rnd, seat, hands, buried, candidate,
                exact_session=exact_session)
            incumbent_points = bot._rollout(
                rnd, seat, hands, buried, incumbent,
                exact_session=exact_session)
            point_deltas.append(_signed_delta(
                rnd, seat, float(candidate_points), float(incumbent_points)))
            level_deltas.append(_signed_delta(
                rnd, seat, _level_score(bot, candidate_points),
                _level_score(bot, incumbent_points)))
    finally:
        bot.rng = original_rng
    if len(point_deltas) != REPORT_WORLDS:
        raise LevelAuditRefused("report-world objective audit underfilled")
    point = RELIABILITY._paired_moments(point_deltas)
    level = RELIABILITY._paired_moments(level_deltas)
    if (abs(point["mean"] - float(report["gap"])) > 1e-12
            or abs(point["se"] - float(report["se"])) > 1e-12):
        raise LevelAuditRefused("point-objective reconstruction drift")
    point_stat = point["mean"] - REPORT_CRITICAL * point["se"]
    level_stat = level["mean"] - REPORT_CRITICAL * level["se"]

    frozen = next(row for row in json.loads(
        (SERVER / "tests/data/s6_boss_near_override_census.v1.json")
        .read_bytes())["rows"]
        if (row["seed"], row["flip"]) == witness)
    return witness, {
        "seed": seed,
        "flip": flip,
        "seat": seat,
        "role": "attacker" if rnd.is_attacker(seat) else "defender",
        "candidate": list(candidate),
        "incumbent": incumbent,
        "report_seed": report_seed,
        "report_worlds": REPORT_WORLDS,
        "sample_attempts": attempts,
        "point_objective": {
            **point,
            "statistic": point_stat,
            "accepts": point_stat >= REPORT_MIN_GAIN,
        },
        "level_objective": {
            **level,
            "statistic": level_stat,
            "accepts": level_stat >= REPORT_MIN_GAIN,
        },
        "objectives_disagree": (
            (point_stat >= REPORT_MIN_GAIN)
            != (level_stat >= REPORT_MIN_GAIN)),
        "generating_world_throw_succeeded": frozen["throw_succeeded"],
        "signed_level_utility_delta": frozen[
            "signed_level_utility_delta"],
    }


def source_sha256s() -> dict[str, str]:
    paths = {
        "audit": SCRIPT,
        "reliability": SERVER / "scripts/s6_throw_reliability_audit.py",
        "replay": SERVER / "scripts/s6_boss_near_loss_replay.py",
        "pilot": SERVER / "scripts/s6_boss_near_dev_pilot.py",
        "policy": SERVER / "shengji/ai/throw_policy.py",
        "mcbot": SERVER / "shengji/ai/mcbot.py",
        "memory": SERVER / "shengji/ai/memory.py",
        "round": SERVER / "shengji/engine/round.py",
    }
    return {name: RELIABILITY.sha256(path)
            for name, path in sorted(paths.items())}


def build_payload(*, expected_git: str, workers: int) -> dict:
    if not 1 <= workers <= 8:
        raise LevelAuditRefused("workers must be in [1, 8]")
    finished = {}
    with ProcessPoolExecutor(max_workers=workers) as executor:
        pending = {
            executor.submit(_audit_witness, witness): witness
            for witness in REPLAY.OVERRIDE_WITNESSES
        }
        for future in as_completed(pending):
            witness, row = future.result()
            finished[witness] = row
            print(json.dumps({
                "event": "s6-level-objective-audit-progress-v1",
                "witnesses_complete": len(finished),
                "witnesses_total": len(REPLAY.OVERRIDE_WITNESSES),
            }, sort_keys=True), flush=True)
    rows = [finished[witness] for witness in REPLAY.OVERRIDE_WITNESSES]
    retained = [row for row in rows if row["level_objective"]["accepts"]]
    value = {
        "schema": SCHEMA,
        "git": expected_git,
        "source_sha256s": source_sha256s(),
        "population": "all 12 point-objective overrides in frozen S6 DEV pilot",
        "design": {
            "report_worlds": REPORT_WORLDS,
            "same_exact_report_seed_sampler_candidates_and_continuations": True,
            "point_objective": "acting-team signed attacker-point delta",
            "level_objective": (
                "acting-team signed MCBot LEVEL_OBJECTIVE delta"),
            "report_critical": REPORT_CRITICAL,
            "report_min_gain": REPORT_MIN_GAIN,
            "selection_warning": (
                "roots were selected by the point objective; this audit "
                "cannot discover level-objective-only candidates"),
        },
        "rows": rows,
        "summary": {
            "witnesses": len(rows),
            "point_objective_retained": sum(
                row["point_objective"]["accepts"] for row in rows),
            "level_objective_retained": len(retained),
            "objectives_disagree": sum(
                row["objectives_disagree"] for row in rows),
            "level_retained_positive_utility": sum(
                row["signed_level_utility_delta"] > 0 for row in retained),
            "level_retained_neutral_utility": sum(
                row["signed_level_utility_delta"] == 0 for row in retained),
            "level_retained_negative_utility": sum(
                row["signed_level_utility_delta"] < 0 for row in retained),
            "observed_loss_retained": any(
                row["signed_level_utility_delta"] < 0 for row in retained),
        },
        "exploration_only": True,
        "confirmatory_claim": False,
        "whole_game_execution_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    value["internal_sha256"] = RELIABILITY.PILOT.stable_digest(value)
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-git", required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    if git("rev-parse", "HEAD") != args.expected_git:
        raise SystemExit("REFUSED: git identity drift")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise SystemExit("REFUSED: dirty producer")
    if (os.environ.get("SHENGJI_FAST") != "1"
            or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1"
            or not fast.HAVE_FAST or fast._fast is None
            or combos.decompose is not fast.decompose):
        raise SystemExit("REFUSED: strict compiled runtime required")
    value = build_payload(expected_git=args.expected_git, workers=args.workers)
    RELIABILITY.PILOT.write_exclusive(args.out, value)
    print(json.dumps({
        "status": "COMPLETE_EXPLORATION_ONLY",
        "output_sha256": RELIABILITY.sha256(args.out),
        "internal_sha256": value["internal_sha256"],
        "summary": value["summary"],
    }, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
