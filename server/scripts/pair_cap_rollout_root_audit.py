#!/usr/bin/env python3
"""High-N common-world audit of the roots changed by pair-cap rollout v2.

The score-free dose found only three natural roots where v2 changed v1's
chosen action.  This exploration reconstructs those roots, draws one fresh
stream of partial-information worlds per root, and prices the v1 and v2 root
actions on every world under both continuation policies.

This is deliberately diagnostic rather than a strength gate.  It can tell us
whether a root flip is stable, and whether it appears only because v2 grades
its own move more generously.  Three selected roots cannot establish a
population or whole-game effect.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import subprocess
import sys
from collections import Counter
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import pair_cap_rollout_incremental_dose as DOSE  # noqa: E402
from shengji.ai.memory import Memory  # noqa: E402
from shengji.ai.pair_aware_rollout import make_pair_aware_bot  # noqa: E402
from shengji.ai.pair_cap_rollout import make_pair_cap_bot  # noqa: E402


SCHEMA = "pair-cap-rollout-changed-root-audit-v1"
EXPECTED_DOSE_SHA256 = (
    "f2e1d28bff52e6dee7d733d78eedb9d6d741c414b4e864b477d60f881d7b0d78"
)
DEFAULT_DOSE = SERVER / "tests/data/pair_cap_rollout_incremental_dose.v1.json"
DEFAULT_WORLDS = 4_096
CHECKPOINTS = (512, 2_048, 4_096)
SEED0 = 996_000_000
ATTEMPT_FACTOR = 40
Z_95 = 1.96


class AuditRefused(RuntimeError):
    """The diagnostic cannot support its bounded description."""


def sha256(path: os.PathLike | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_digest(value) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _team_level_value(attacker_points: int, acting_is_attacker: bool) -> float:
    if attacker_points >= 80:
        attacker_value = (attacker_points - 80) // 40 + 0.5
    elif attacker_points == 0:
        attacker_value = -3.5
    else:
        attacker_value = -(1 + (79 - attacker_points) // 40) - 0.5
    return attacker_value if acting_is_attacker else -attacker_value


def paired_moments(values: list[float]) -> dict[str, float | int]:
    if len(values) < 2:
        raise AuditRefused("paired moments require at least two worlds")
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    se = math.sqrt(variance / len(values))
    return {
        "n": len(values),
        "mean": mean,
        "se": se,
        "ci_two_sided_95": [mean - Z_95 * se, mean + Z_95 * se],
        "wins": sum(value > 0 for value in values),
        "ties": sum(value == 0 for value in values),
        "losses": sum(value < 0 for value in values),
    }


def reconstruct_root(row: dict):
    rnd, actors = DOSE._start_round(int(row["deal_seed"]))
    target = int(row["completed_tricks"])
    while rnd.phase == "play" and len(rnd.history) < target:
        seat = rnd.turn
        if seat is None:
            raise AuditRefused("replay lost the acting seat")
        rnd.play(seat, actors[seat].decide_play(rnd, seat))
    if rnd.phase != "play" or len(rnd.history) != target:
        raise AuditRefused(f"{row['state_id']}: replay did not reach root")
    if rnd.trick is None or rnd.trick.plays:
        raise AuditRefused(f"{row['state_id']}: replay root is not a lead")
    if rnd.turn != row["seat"]:
        raise AuditRefused(f"{row['state_id']}: replay actor drift")
    if DOSE._public_state_digest(rnd, int(row["seat"])) != \
            row["public_state_sha256"]:
        raise AuditRefused(f"{row['state_id']}: public replay digest drift")
    return rnd


def changed_rows(path: Path) -> tuple[dict, list[dict]]:
    if sha256(path) != EXPECTED_DOSE_SHA256:
        raise AuditRefused("incremental-dose input hash drift")
    payload = json.loads(path.read_bytes())
    rows = [row for row in payload["rows"]
            if sorted(row["v1_action"]) != sorted(row["v2_action"])]
    if len(rows) != payload["aggregate"]["v2_incremental_root_changes"] \
            or len(rows) != 3:
        raise AuditRefused("changed-root population drift")
    if len({row["state_id"] for row in rows}) != len(rows):
        raise AuditRefused("changed-root identity collision")
    return payload, rows


def _source_sha256s(dose: Path) -> dict[str, str]:
    paths = {
        "audit": SCRIPT,
        "dose_script": SCRIPT.with_name("pair_cap_rollout_incremental_dose.py"),
        "dose_artifact": dose,
        "pair_cap": SERVER / "shengji/ai/pair_cap_rollout.py",
        "pair_v1": SERVER / "shengji/ai/pair_aware_rollout.py",
        "mcbot": SERVER / "shengji/ai/mcbot.py",
        "memory": SERVER / "shengji/ai/memory.py",
        "heuristic": SERVER / "shengji/ai/heuristic.py",
        "round": SERVER / "shengji/engine/round.py",
    }
    return {name: sha256(path) for name, path in sorted(paths.items())}


def _world_digest(hands: dict[int, list[str]], buried: list[str]) -> str:
    return stable_digest({
        "hands": {str(seat): sorted(cards)
                  for seat, cards in sorted(hands.items())},
        "buried": sorted(buried),
    })


def _sampler_delta(bot, before: dict[str, int]) -> dict[str, int]:
    after = bot._sampler_snapshot()
    return {name: after[name] - before[name] for name in before}


def _score_world(scorer, rnd, seat: int, hands, buried,
                 v1_action: list[str], v2_action: list[str]) -> tuple[float, float]:
    acting_is_attacker = rnd.is_attacker(seat)
    v1_points = int(scorer._rollout(
        rnd, seat, hands, buried, list(v1_action)))
    v2_points = int(scorer._rollout(
        rnd, seat, hands, buried, list(v2_action)))
    sign = 1 if acting_is_attacker else -1
    point_delta = float(sign * (v2_points - v1_points))
    level_delta = (
        _team_level_value(v2_points, acting_is_attacker)
        - _team_level_value(v1_points, acting_is_attacker)
    )
    return point_delta, level_delta


def audit_root(row: dict, *, n_worlds: int, sample_seed: int) -> dict:
    rnd = reconstruct_root(row)
    seat = int(row["seat"])
    v1_action = list(row["v1_action"])
    v2_action = list(row["v2_action"])
    sampler = make_pair_aware_bot(treatment=True, seed=sample_seed)
    scorers = {
        "v1_pair_aware": make_pair_aware_bot(treatment=True, seed=0),
        "v2_opponent_pair_cap": make_pair_cap_bot(treatment=True, seed=0),
    }
    values = {
        name: {"signed_point_delta": [], "signed_level_utility_delta": []}
        for name in scorers
    }
    checkpoints: list[dict] = []
    memory = Memory(rnd, seat, own_kitty=True)
    before = sampler._sampler_snapshot()
    attempts = 0
    world_stream = hashlib.sha256()
    while len(values["v1_pair_aware"]["signed_point_delta"]) < n_worlds \
            and attempts < n_worlds * ATTEMPT_FACTOR:
        attempts += 1
        sampled = sampler._sample_hands(rnd, seat, memory)
        if sampled is None:
            continue
        hands, buried = sampled
        world_stream.update(_world_digest(hands, buried).encode())
        for name, scorer in scorers.items():
            point_delta, level_delta = _score_world(
                scorer, rnd, seat, hands, buried, v1_action, v2_action)
            values[name]["signed_point_delta"].append(point_delta)
            values[name]["signed_level_utility_delta"].append(level_delta)
        used = len(values["v1_pair_aware"]["signed_point_delta"])
        if used in {n for n in CHECKPOINTS if n <= n_worlds} | {n_worlds}:
            checkpoints.append({
                "worlds": used,
                "by_continuation": {
                    name: {
                        metric: paired_moments(series)
                        for metric, series in metrics.items()
                    }
                    for name, metrics in values.items()
                },
            })
    used = len(values["v1_pair_aware"]["signed_point_delta"])
    if used != n_worlds:
        raise AuditRefused(
            f"{row['state_id']}: sampler underfilled {used}/{n_worlds}")
    sampler_work = _sampler_delta(sampler, before)
    if sampler_work["sample_attempts"] != \
            sampler_work["accepted_worlds"] + sampler_work["failed_worlds"]:
        raise AuditRefused(f"{row['state_id']}: sampler work does not reconcile")
    if sampler_work["accepted_worlds"] != n_worlds:
        raise AuditRefused(f"{row['state_id']}: accepted-world drift")

    # The generating deal is one interpretable witness, not an independent
    # population.  Keep it visibly separate from the posterior-world moments.
    true_hands = {other: list(rnd.hands[other]) for other in range(4)
                  if other != seat}
    true_world = {
        name: dict(zip(
            ("signed_point_delta", "signed_level_utility_delta"),
            _score_world(scorer, rnd, seat, true_hands, list(rnd.buried),
                         v1_action, v2_action),
        )) for name, scorer in scorers.items()
    }
    terminal = checkpoints[-1]
    return {
        "state_id": row["state_id"],
        "deal_seed": row["deal_seed"],
        "completed_tricks": row["completed_tricks"],
        "phase_band": row["phase_band"],
        "role": row["role"],
        "seat": seat,
        "public_state_sha256": row["public_state_sha256"],
        "v1_action": v1_action,
        "v2_action": v2_action,
        "original_decision_seed": row["decision_seed"],
        "sample_seed": sample_seed,
        "attempts": attempts,
        "sampler_work": sampler_work,
        "world_stream_sha256": world_stream.hexdigest(),
        "checkpoints": checkpoints,
        "terminal": terminal,
        "generating_world_witness": true_world,
        "continuation_dose": {
            "v1_pair_aware": scorers[
                "v1_pair_aware"].pair_aware_telemetry(),
            "v2_pair_aware_total": scorers[
                "v2_opponent_pair_cap"].pair_aware_telemetry(),
            "v2_incremental_pair_cap": scorers[
                "v2_opponent_pair_cap"].rollout_policy.pair_cap_telemetry(),
        },
    }


def run_audit(*, dose: Path = DEFAULT_DOSE,
              n_worlds: int = DEFAULT_WORLDS) -> dict:
    if isinstance(n_worlds, bool) or not isinstance(n_worlds, int) \
            or n_worlds < 2 or n_worlds > 16_384:
        raise AuditRefused("world count must be an integer in [2, 16384]")
    dose_payload, rows = changed_rows(dose)
    results = []
    for index, row in enumerate(rows):
        result = audit_root(
            row, n_worlds=n_worlds,
            sample_seed=SEED0 + index * 1_000_003)
        results.append(result)
        print(json.dumps({
            "event": "pair-cap-changed-root-audit-progress-v1",
            "roots_complete": len(results),
            "roots_total": len(rows),
            "state_id": row["state_id"],
            "terminal": result["terminal"],
        }, sort_keys=True), flush=True)

    directions = {}
    for policy in ("v1_pair_aware", "v2_opponent_pair_cap"):
        intervals = [
            root["terminal"]["by_continuation"][policy]
                ["signed_point_delta"]["ci_two_sided_95"]
            for root in results
        ]
        directions[policy] = {
            "v2_action_positive_roots": sum(low > 0 for low, _ in intervals),
            "v1_action_positive_roots": sum(high < 0 for _, high in intervals),
            "unresolved_roots": sum(low <= 0 <= high for low, high in intervals),
        }
    payload = {
        "schema": SCHEMA,
        "git": git("rev-parse", "HEAD"),
        "tree_dirty": bool(git("status", "--porcelain")),
        "runtime": {
            "hostname": platform.node(),
            "python": platform.python_version(),
            "executable": str(Path(sys.executable).resolve()),
        },
        "source_sha256s": _source_sha256s(dose),
        "design": {
            "input_dose_sha256": EXPECTED_DOSE_SHA256,
            "population": "all three natural roots changed by v2 in frozen dose",
            "worlds_per_root": n_worlds,
            "common_worlds_across_actions_and_continuation_policies": True,
            "checkpoints": [n for n in CHECKPOINTS if n <= n_worlds],
            "primary_contrast": (
                "acting-team value of v2 root action minus v1 root action"),
            "selection_warning": (
                "roots were selected because v2 changed them; no population "
                "or whole-game inference is permitted"),
        },
        "input_dose_internal_sha256": dose_payload["internal_sha256"],
        "roots": results,
        "direction_summary": directions,
        "exploration_only": True,
        "strength_claim": False,
        "whole_game_execution_authorized": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    payload["internal_sha256"] = stable_digest(payload)
    return payload


def write_exclusive(path: Path, payload: dict) -> None:
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise AuditRefused("refusing to overwrite changed-root audit")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":"))
           + "\n").encode()
    with partial.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.link(partial, path)
    partial.unlink()
    if json.loads(path.read_bytes()) != payload:
        raise AuditRefused("changed-root audit failed exact reopen")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dose", type=Path, default=DEFAULT_DOSE)
    parser.add_argument("--worlds", type=int, default=DEFAULT_WORLDS)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    payload = run_audit(dose=args.dose, n_worlds=args.worlds)
    write_exclusive(args.out, payload)
    print(json.dumps({
        "status": "COMPLETE_EXPLORATION_ONLY",
        "direction_summary": payload["direction_summary"],
        "output_sha256": sha256(args.out),
        "internal_sha256": payload["internal_sha256"],
    }, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
