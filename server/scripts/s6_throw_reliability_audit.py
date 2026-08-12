#!/usr/bin/env python3
"""Audit whether report-world throw failures explain S6's bad override.

The 32-cluster boss/near DEV pilot produced twelve treatment overrides: eleven
ties and one two-level loss.  The loss was also the only throw that failed in
the generating hidden world.  This exploration replays every override and
reconstructs its exact 300-world report fold, adding one statistic the live
search did not retain: whether the complete proposed throw actually survives
each sampled world.

This is a selected-DEV diagnostic.  It may motivate a safety rule; it cannot
establish strength or authorize a screen.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import random
import subprocess
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import s6_boss_near_dev_pilot as PILOT  # noqa: E402
import s6_boss_near_loss_replay as REPLAY  # noqa: E402
import s6_throw_duel as BASE  # noqa: E402
from shengji.ai.memory import Memory  # noqa: E402
from shengji.engine import combos, fast  # noqa: E402
from shengji.engine.game import Game  # noqa: E402
from shengji.engine.round import Trick, TrickPlay, actual_play_after  # noqa: E402


SCHEMA = "s6-throw-report-reliability-audit-v1"
REPORT_WORLDS = 300
ATTEMPT_FACTOR = 40
Z_95 = 1.96


class ReliabilityRefused(RuntimeError):
    """The selected DEV roots cannot support this diagnostic."""


def sha256(path: os.PathLike | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _source_sha256s() -> dict[str, str]:
    paths = {
        "audit": SCRIPT,
        "replay": SERVER / "scripts/s6_boss_near_loss_replay.py",
        "pilot": SERVER / "scripts/s6_boss_near_dev_pilot.py",
        "duel": SERVER / "scripts/s6_throw_duel.py",
        "gate": SERVER / "shengji/ai/throw_search_gate.py",
        "policy": SERVER / "shengji/ai/throw_policy.py",
        "source": SERVER / "shengji/ai/throw_sourcing.py",
        "mcbot": SERVER / "shengji/ai/mcbot.py",
        "memory": SERVER / "shengji/ai/memory.py",
        "round": SERVER / "shengji/engine/round.py",
    }
    return {name: sha256(path) for name, path in sorted(paths.items())}


def wilson_interval(successes: int, total: int) -> list[float]:
    if total <= 0 or not 0 <= successes <= total:
        raise ReliabilityRefused("Wilson inputs are invalid")
    proportion = successes / total
    denominator = 1 + Z_95 * Z_95 / total
    center = (proportion + Z_95 * Z_95 / (2 * total)) / denominator
    half = Z_95 * math.sqrt(
        proportion * (1 - proportion) / total
        + Z_95 * Z_95 / (4 * total * total)
    ) / denominator
    return [max(0.0, center - half), min(1.0, center + half)]


def _capture_override(seed: int, flip: int):
    policies = REPLAY._policies("treatment", seed, flip)
    game = Game(random.Random(seed))
    rnd = game.start_round()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = policies[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = policies[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    if rnd.banker is None:
        raise ReliabilityRefused("replay has no banker")
    rnd.bury(rnd.banker, policies[rnd.banker].decide_bury(rnd, rnd.banker))

    while rnd.phase == "play":
        seat = rnd.turn
        if seat is None:
            raise ReliabilityRefused("replay lost acting seat")
        bot = policies[seat]
        attempted = list(bot.decide_play(rnd, seat))
        s6 = getattr(bot, "last_s6_throw_record", None)
        if isinstance(s6, dict) and s6.get("treatment_override") is True:
            decision = copy.deepcopy(bot.last_decision_record)
            if not isinstance(decision, dict):
                raise ReliabilityRefused("override omitted MC decision record")
            return copy.deepcopy(rnd), bot, seat, attempted, decision
        rnd.play(seat, attempted)
    raise ReliabilityRefused(f"{seed}/{flip}: no treatment override replayed")


def _full_throw_succeeds(bot, rnd, seat: int, sampled, buried,
                         candidate: list[str]) -> bool:
    clone = copy.copy(rnd)
    clone.hands = bot._complete_determinized_hands(
        rnd, seat, sampled, buried=buried)
    clone.buried = sorted(buried)
    if rnd.trick is None:
        raise ReliabilityRefused("override root has no current trick")
    clone.trick = Trick(
        leader=rnd.trick.leader,
        plays=[TrickPlay(play.seat, list(play.cards))
               for play in rnd.trick.plays],
    )
    clone.history = list(rnd.history)
    clone.last_trick = rnd.last_trick
    clone.message = None
    clone._trusted_rollout = True
    clone._determinized_world = True
    previous_last = clone.last_trick
    clone.play(seat, list(candidate))
    actual = actual_play_after(clone, seat, previous_last)
    return Counter(actual) == Counter(candidate)


def _paired_moments(values: list[float]) -> dict[str, float | int]:
    if len(values) < 2:
        raise ReliabilityRefused("paired moments need at least two worlds")
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return {
        "n": len(values),
        "mean": mean,
        "se": math.sqrt(variance / len(values)),
    }


def _audit_witness(witness: tuple[int, int]) -> tuple[tuple[int, int], dict]:
    seed, flip = witness
    rnd, bot, seat, candidate, decision = _capture_override(seed, flip)
    incumbent_record = decision.get("s6_incumbent_decision")
    report = decision.get("report_fold")
    if (not isinstance(incumbent_record, dict)
            or not isinstance(incumbent_record.get("played"), list)
            or not isinstance(report, dict)
            or report.get("complete") is not True
            or report.get("worlds") != REPORT_WORLDS):
        raise ReliabilityRefused("override lacks complete incumbent/report data")
    incumbent = list(incumbent_record["played"])
    report_seed = decision.get("report_seed")
    if not isinstance(report_seed, int):
        raise ReliabilityRefused("override omitted report seed")
    memory = Memory(rnd, seat, own_kitty=True)
    original_rng = bot.rng
    deltas = []
    success_deltas = []
    failure_deltas = []
    attempts = 0
    try:
        bot.rng = random.Random(report_seed)
        while len(deltas) < REPORT_WORLDS \
                and attempts < REPORT_WORLDS * ATTEMPT_FACTOR:
            attempts += 1
            sampled = bot._sample_hands(rnd, seat, memory)
            if sampled is None:
                continue
            hands, buried = sampled
            success = _full_throw_succeeds(
                bot, rnd, seat, hands, buried, candidate)
            exact_session = bot._new_exact_world_session(rnd, buried)
            candidate_value = bot._score(bot._rollout(
                rnd, seat, hands, buried, candidate,
                exact_session=exact_session))
            incumbent_value = bot._score(bot._rollout(
                rnd, seat, hands, buried, incumbent,
                exact_session=exact_session))
            delta = candidate_value - incumbent_value
            if not rnd.is_attacker(seat):
                delta = -delta
            deltas.append(delta)
            (success_deltas if success else failure_deltas).append(delta)
    finally:
        bot.rng = original_rng
    if len(deltas) != REPORT_WORLDS:
        raise ReliabilityRefused("report-world reconstruction underfilled")
    moments = _paired_moments(deltas)
    if (abs(moments["mean"] - float(report["gap"])) > 1e-12
            or abs(moments["se"] - float(report["se"])) > 1e-12):
        raise ReliabilityRefused("reconstructed report moments drift")

    frozen = next(row for row in json.loads(
        (SERVER / "tests/data/s6_boss_near_override_census.v1.json")
        .read_bytes())["rows"]
        if (row["seed"], row["flip"]) == witness)
    failures = len(failure_deltas)
    return witness, {
        "seed": seed,
        "flip": flip,
        "seat": seat,
        "role": "attacker" if rnd.is_attacker(seat) else "defender",
        "candidate": candidate,
        "incumbent": incumbent,
        "report_seed": report_seed,
        "report_worlds": REPORT_WORLDS,
        "sample_attempts": attempts,
        "reproduced_gap": moments["mean"],
        "reproduced_se": moments["se"],
        "report_throw_successes": REPORT_WORLDS - failures,
        "report_throw_failures": failures,
        "report_failure_rate_wilson_95": wilson_interval(
            failures, REPORT_WORLDS),
        "mean_delta_when_throw_succeeds": (
            sum(success_deltas) / len(success_deltas)
            if success_deltas else None),
        "mean_delta_when_throw_fails": (
            sum(failure_deltas) / len(failure_deltas)
            if failure_deltas else None),
        "zero_report_failures_gate_accepts": failures == 0,
        "public_all_boss_gate_accepts": frozen["component_proof"][
            "all_components_publicly_proven_boss"],
        "generating_world_throw_succeeded": frozen["throw_succeeded"],
        "signed_level_utility_delta": frozen["signed_level_utility_delta"],
    }


def build_payload(expected_git: str, workers: int) -> dict:
    if not 1 <= workers <= 8:
        raise ReliabilityRefused("worker count must be in [1, 8]")
    rows_by_witness = {}
    with ProcessPoolExecutor(max_workers=workers) as executor:
        pending = {
            executor.submit(_audit_witness, witness): witness
            for witness in REPLAY.OVERRIDE_WITNESSES
        }
        for future in as_completed(pending):
            witness, row = future.result()
            rows_by_witness[witness] = row
            print(json.dumps({
                "event": "s6-throw-reliability-progress-v1",
                "witnesses_complete": len(rows_by_witness),
                "witnesses_total": len(REPLAY.OVERRIDE_WITNESSES),
            }, sort_keys=True), flush=True)
    rows = [rows_by_witness[witness]
            for witness in REPLAY.OVERRIDE_WITNESSES]
    retained = [row for row in rows
                if row["zero_report_failures_gate_accepts"]]
    payload = {
        "schema": SCHEMA,
        "git": expected_git,
        "source_sha256s": _source_sha256s(),
        "population": "all 12 treatment overrides in frozen S6 DEV pilot",
        "design": {
            "report_worlds": REPORT_WORLDS,
            "same_exact_report_seed_and_sampler": True,
            "candidate_contrast": "S6 attempted throw minus champion action",
            "candidate_safety_statistic": "complete throw survival per world",
        },
        "rows": rows,
        "summary": {
            "witnesses": len(rows),
            "report_world_failures": sum(
                row["report_throw_failures"] for row in rows),
            "zero_failure_gate_retained": len(retained),
            "zero_failure_gate_positive_utility": sum(
                row["signed_level_utility_delta"] > 0 for row in retained),
            "zero_failure_gate_neutral_utility": sum(
                row["signed_level_utility_delta"] == 0 for row in retained),
            "zero_failure_gate_negative_utility": sum(
                row["signed_level_utility_delta"] < 0 for row in retained),
            "loss_witness_rejected": not next(
                row["zero_report_failures_gate_accepts"] for row in rows
                if row["signed_level_utility_delta"] < 0),
        },
        "exploration_only": True,
        "confirmatory_claim": False,
        "strength_claim": False,
        "whole_game_execution_authorized": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    payload["internal_sha256"] = PILOT.stable_digest(payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-git", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--workers", type=int, default=4)
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
    payload = build_payload(args.expected_git, args.workers)
    PILOT.write_exclusive(args.out, payload)
    print(json.dumps({
        "status": "COMPLETE_EXPLORATION_ONLY",
        "result_sha256": sha256(args.out),
        "result_internal_sha256": payload["internal_sha256"],
        "summary": payload["summary"],
    }, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
