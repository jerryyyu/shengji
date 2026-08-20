#!/usr/bin/env python3
"""Cheap exact-endgame exploration for promoted low-pair continuations.

This is the exploration-tier bridge between a live-game observation and an
expensive whole-game MC screen.  It generates fresh complete games, freezes
the first late lead in each deal where treatment and matched null differ, then
uses the fully known deal only as an exact evaluator of the two forced actions.

The result is diagnostic, reusable, and explicitly non-promotable.  A positive
result justifies a reviewed whole-game packet; it is not evidence that the
rollout policy improves the live champion after composition with MC search.
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
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SERVER))

from shengji.ai.endgame import solve_exact_endgame  # noqa: E402
from shengji.ai.heuristic import HeuristicBot  # noqa: E402
from shengji.ai.pair_aware_rollout import (  # noqa: E402
    PAIR_AWARE_COUNTER_FIELDS,
    PairAwareRolloutPolicy,
)
from shengji.engine.game import Game  # noqa: E402


SCHEMA = "pair-aware-rollout-exact-screen-v1"
SEED0 = 331_000_000
MAX_DEALS = 100_000
ROLE_QUOTA = {"attacker": 32, "defender": 32}
MAX_HAND_CARDS = 4
MAX_EXACT_NODES = 500_000
T_CRITICAL = 1.669  # one-sided 95%, df=63


class ScreenRefused(RuntimeError):
    """The exploration cannot be reproduced honestly."""


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


def source_sha256s() -> dict[str, str]:
    paths = {
        "screen": SCRIPT,
        "pair_aware": SERVER / "shengji/ai/pair_aware_rollout.py",
        "heuristic": SERVER / "shengji/ai/heuristic.py",
        "memory": SERVER / "shengji/ai/memory.py",
        "endgame": SERVER / "shengji/ai/endgame.py",
        "round": SERVER / "shengji/engine/round.py",
        "game": SERVER / "shengji/engine/game.py",
    }
    return {name: sha256(path) for name, path in sorted(paths.items())}


def _team_level_value(attacker_points: int,
                      acting_is_attacker: bool) -> float:
    if attacker_points >= 80:
        attacker_value = (attacker_points - 80) // 40 + 0.5
    elif attacker_points == 0:
        attacker_value = -3.5
    else:
        attacker_value = -(1 + (79 - attacker_points) // 40) - 0.5
    return attacker_value if acting_is_attacker else -attacker_value


def _drive_to_trigger(seed: int):
    game = Game(random.Random(seed))
    rnd = game.start_round()
    actors = [HeuristicBot() for _ in range(4)]
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = actors[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = actors[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    if rnd.banker is None:
        raise ScreenRefused("fresh deal has no banker after final declaration")
    rnd.bury(rnd.banker, actors[rnd.banker].decide_bury(rnd, rnd.banker))

    while rnd.phase == "play":
        seat = rnd.turn
        if seat is None or rnd.trick is None:
            raise ScreenRefused("fresh deal lost active play state")
        if not rnd.trick.plays and max(map(len, rnd.hands)) <= MAX_HAND_CARDS:
            treatment = PairAwareRolloutPolicy(apply_treatment=True)
            null = PairAwareRolloutPolicy(apply_treatment=False)
            treatment_action = treatment.decide_play(rnd, seat)
            null_action = null.decide_play(rnd, seat)
            tr = treatment.pair_aware_telemetry()
            nr = null.pair_aware_telemetry()
            tr_work = {key: value for key, value in tr.items()
                       if key not in {"mode", "changes", "matched_noops"}}
            nr_work = {key: value for key, value in nr.items()
                       if key not in {"mode", "changes", "matched_noops"}}
            if tr_work != nr_work:
                raise ScreenRefused("treatment/null mechanism work drift")
            if tr["triggers"]:
                if (tr["triggers"] != tr["changes"]
                        or nr["triggers"] != nr["matched_noops"]
                        or treatment_action == null_action):
                    raise ScreenRefused("trigger lacks exact matched dose")
                return rnd, seat, null_action, treatment_action, tr
        rnd.play(seat, actors[seat].decide_play(rnd, seat))
    return None


def _score_trigger(seed: int, found) -> dict:
    rnd, seat, null_action, treatment_action, telemetry = found
    values = {}
    nodes = {}
    for label, action in (
            ("null", null_action), ("treatment", treatment_action)):
        clone = copy.deepcopy(rnd)
        clone.play(seat, list(action))
        result = solve_exact_endgame(
            clone, max_hand_cards=MAX_HAND_CARDS,
            max_nodes=MAX_EXACT_NODES)
        values[label] = int(result.attacker_points)
        nodes[label] = int(result.nodes)
    attacker = rnd.is_attacker(seat)
    point_delta = (values["treatment"] - values["null"] if attacker
                   else values["null"] - values["treatment"])
    level_delta = (
        _team_level_value(values["treatment"], attacker)
        - _team_level_value(values["null"], attacker)
    )
    return {
        "state_id": f"{seed}:first-promoted-pair-lead",
        "deal_seed": seed,
        "seat": seat,
        "role": "attacker" if attacker else "defender",
        "hand_size": len(rnd.hands[seat]),
        "null_action": sorted(null_action),
        "treatment_action": sorted(treatment_action),
        "null_final_attacker_points": values["null"],
        "treatment_final_attacker_points": values["treatment"],
        "signed_point_delta": point_delta,
        "signed_level_utility_delta": level_delta,
        "exact_nodes": nodes,
        "trigger_counters": {
            key: int(telemetry[key]) for key in PAIR_AWARE_COUNTER_FIELDS
        },
    }


def _mean_se_lcb(values: list[float]) -> dict[str, float | int]:
    if len(values) < 2:
        raise ScreenRefused("exact screen metric needs at least two states")
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    se = math.sqrt(variance / len(values))
    return {
        "n": len(values), "mean": mean, "se": se,
        "lcb_one_sided_95": mean - T_CRITICAL * se,
    }


def aggregate(rows: list[dict]) -> dict:
    expected = sum(ROLE_QUOTA.values())
    if len(rows) != expected or len({row["deal_seed"] for row in rows}) != expected:
        raise ScreenRefused("exact screen row/deal population drift")
    role_counts = Counter(row["role"] for row in rows)
    if dict(role_counts) != ROLE_QUOTA:
        raise ScreenRefused("exact screen role population drift")
    primary = _mean_se_lcb([row["signed_point_delta"] for row in rows])
    by_role = {
        role: _mean_se_lcb([
            row["signed_point_delta"] for row in rows if row["role"] == role
        ]) for role in ROLE_QUOTA
    }
    level_mean = sum(
        row["signed_level_utility_delta"] for row in rows) / len(rows)
    criteria = {
        "overall_point_lcb_gt_0": primary["lcb_one_sided_95"] > 0,
        "both_role_point_means_ge_0": all(
            value["mean"] >= 0 for value in by_role.values()),
        "level_utility_mean_ge_0": level_mean >= 0,
    }
    return {
        "primary": "acting-team signed exact final attacker-point delta",
        "points": primary,
        "by_role": by_role,
        "level_utility_mean": level_mean,
        "wins": sum(row["signed_point_delta"] > 0 for row in rows),
        "losses": sum(row["signed_point_delta"] < 0 for row in rows),
        "ties": sum(row["signed_point_delta"] == 0 for row in rows),
        "criteria": criteria,
        "exploration_verdict": (
            "ADVANCE_TO_REVIEWED_WHOLE_GAME_SCREEN"
            if all(criteria.values()) else "DO_NOT_ADVANCE_THIS_RECIPE"),
        "whole_game_execution_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
    }


def run_screen() -> dict:
    rows = []
    accepted = Counter()
    triggers = Counter()
    exact_refusals = Counter()
    deals_scanned = 0
    for offset in range(MAX_DEALS):
        seed = SEED0 + offset
        deals_scanned += 1
        found = _drive_to_trigger(seed)
        if found is None:
            continue
        role = "attacker" if found[0].is_attacker(found[1]) else "defender"
        triggers[role] += 1
        if accepted[role] >= ROLE_QUOTA[role]:
            continue
        try:
            row = _score_trigger(seed, found)
        except Exception as exc:
            exact_refusals[type(exc).__name__] += 1
            continue
        rows.append(row)
        accepted[role] += 1
        if all(accepted[key] == ROLE_QUOTA[key] for key in ROLE_QUOTA):
            break
    if dict(accepted) != ROLE_QUOTA:
        raise ScreenRefused(
            f"fresh exploration exhausted: accepted={dict(accepted)}")
    payload = {
        "schema": SCHEMA,
        "git": git("rev-parse", "HEAD"),
        "tree_dirty": bool(git("status", "--porcelain")),
        "source_sha256s": source_sha256s(),
        "design": {
            "seed0": SEED0,
            "max_deals": MAX_DEALS,
            "role_quota": ROLE_QUOTA,
            "max_hand_cards": MAX_HAND_CARDS,
            "max_exact_nodes": MAX_EXACT_NODES,
            "selection": "first scoreable trigger per role in ascending fresh deals",
        },
        "deals_scanned": deals_scanned,
        "triggers_observed": dict(triggers),
        "exact_refusals": dict(exact_refusals),
        "rows": rows,
        "aggregate": aggregate(rows),
        "exploration_only": True,
        "training_authorized": False,
        "whole_game_execution_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    payload["internal_sha256"] = stable_digest(payload)
    return payload


def write_exclusive(path: Path, payload: dict) -> None:
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise ScreenRefused("refusing to overwrite exact-screen artifact")
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
        raise ScreenRefused("exact screen failed exact reopen")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    payload = run_screen()
    write_exclusive(Path(args.out), payload)
    print(json.dumps({
        "status": payload["aggregate"]["exploration_verdict"],
        "deals_scanned": payload["deals_scanned"],
        "aggregate": payload["aggregate"],
        "output_sha256": sha256(args.out),
        "internal_sha256": payload["internal_sha256"],
        "strength_claim": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
