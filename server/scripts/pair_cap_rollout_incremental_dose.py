#!/usr/bin/env python3
"""Score-free natural-root dose of the opponent-pair-cap v2 extension.

The fixed population contains the first 32 natural lead states in each
early/mid/late × attacker/defender cell.  On every state, the reviewed v1
treatment, v2 treatment, and v2 matched null receive the same decision seed,
root ballot, and exact MC work.  No round outcome or utility is computed.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import platform
import random
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SERVER))

from shengji.ai.heuristic import HeuristicBot  # noqa: E402
from shengji.ai.pair_aware_rollout import (  # noqa: E402
    PAIR_AWARE_COUNTER_FIELDS,
    make_pair_aware_bot,
)
from shengji.ai.pair_cap_rollout import (  # noqa: E402
    PAIR_CAP_COUNTER_FIELDS,
    make_pair_cap_bot,
)
from shengji.engine.game import Game  # noqa: E402
from shengji.evaluation import counters  # noqa: E402


SCHEMA = "pair-cap-rollout-incremental-root-dose-v1"
SEED0 = 447_000_000
MAX_DEALS = 20_000
STATES_PER_CELL = 32
PHASES = ("early", "mid", "late")
ROLES = ("attacker", "defender")
SCORE_FIELDS = frozenset({
    "attacker_points", "kitty_bonus", "level_change", "level_utility",
    "outcome", "outcomes", "points", "utility", "win_rate", "winner",
    "winner_team", "won", "wins", "losses",
})
WORK_FIELDS = tuple(key for key in counters([]) if key != "search_secs")


class DoseRefused(RuntimeError):
    """The diagnostic cannot support its score-free dose description."""


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


def phase_band(completed_tricks: int) -> str:
    if completed_tricks <= 7:
        return "early"
    if completed_tricks <= 16:
        return "mid"
    return "late"


def _public_state_digest(rnd, seat: int) -> str:
    return stable_digest({
        "trump_rank": rnd.trump_rank,
        "trump_suit": rnd.trump_suit,
        "trump_is_nt": rnd.trump_is_nt,
        "banker": rnd.banker,
        "seat": seat,
        "history": [
            {
                "leader": trick.leader,
                "plays": [
                    {"seat": play.seat, "cards": sorted(play.cards)}
                    for play in trick.plays
                ],
            }
            for trick in rnd.history
        ],
        "own_hand": sorted(rnd.hands[seat]),
        "own_buried": sorted(rnd.buried) if seat == rnd.banker else [],
    })


def _work(bot) -> dict[str, int]:
    raw = counters([bot])
    work = {name: raw[name] for name in WORK_FIELDS}
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
           for value in work.values()):
        raise DoseRefused("MC work counters are not non-negative integers")
    if work["sample_attempts"] != work["accepted_worlds"] + work["failed_worlds"]:
        raise DoseRefused("sampler work does not reconcile")
    return work


def _candidates(bot) -> list[list[str]] | None:
    record = bot.last_decision_record
    if record is None:
        return None
    value = record.get("candidates")
    if not isinstance(value, list):
        raise DoseRefused("searched decision omitted root candidates")
    return [list(action) for action in value]


def _counter_projection(value: dict, fields: tuple[str, ...],
                        *, omit: frozenset[str]) -> dict[str, int]:
    return {name: int(value[name]) for name in fields if name not in omit}


def evaluate_state(rnd, seat: int, *, decision_seed: int) -> dict:
    v1 = make_pair_aware_bot(treatment=True, seed=decision_seed)
    v2 = make_pair_cap_bot(treatment=True, seed=decision_seed)
    null = make_pair_cap_bot(treatment=False, seed=decision_seed)
    v1_action = v1.decide_play(copy.deepcopy(rnd), seat)
    v2_action = v2.decide_play(copy.deepcopy(rnd), seat)
    null_action = null.decide_play(copy.deepcopy(rnd), seat)

    candidate_sets = [_candidates(bot) for bot in (v1, v2, null)]
    if candidate_sets[0] != candidate_sets[1] \
            or candidate_sets[0] != candidate_sets[2]:
        raise DoseRefused("v1/v2/null root ballot identity drift")
    work = [_work(bot) for bot in (v1, v2, null)]
    if work[0] != work[1] or work[0] != work[2]:
        raise DoseRefused("v1/v2/null exact MC work drift")

    v2_pair = v2.rollout_policy.pair_cap_telemetry()
    null_pair = null.rollout_policy.pair_cap_telemetry()
    omit = frozenset({"changes", "matched_noops"})
    if _counter_projection(v2_pair, PAIR_CAP_COUNTER_FIELDS, omit=omit) != \
            _counter_projection(null_pair, PAIR_CAP_COUNTER_FIELDS, omit=omit):
        # Once treatment changes a rollout continuation, later public histories
        # can legitimately differ.  Require exact treatment/null accounting,
        # but do not pretend post-divergence trigger streams are paired.
        post_divergence_pair_streams_equal = False
    else:
        post_divergence_pair_streams_equal = True
    v2_base = v2.pair_aware_telemetry()
    null_base = null.pair_aware_telemetry()
    for payload in (v2_base, null_base):
        if any(name not in payload for name in PAIR_AWARE_COUNTER_FIELDS):
            raise DoseRefused("combined pair-aware telemetry is incomplete")

    return {
        "decision_seed": decision_seed,
        "public_state_sha256": _public_state_digest(rnd, seat),
        "root_candidate_count": (
            len(candidate_sets[0]) if candidate_sets[0] is not None else 1),
        "searched": work[0]["searches"] > 0,
        "v1_action": list(v1_action),
        "v2_action": list(v2_action),
        "matched_null_action": list(null_action),
        "v1_root_change": sorted(v1_action) != sorted(null_action),
        "v2_root_change": sorted(v2_action) != sorted(null_action),
        "v2_incremental_root_change": sorted(v2_action) != sorted(v1_action),
        "work": work[0],
        "v2_combined_pair_dose": v2_base,
        "null_combined_pair_dose": null_base,
        "v2_pair_cap_dose": v2_pair,
        "null_pair_cap_dose": null_pair,
        "post_divergence_pair_streams_equal": post_divergence_pair_streams_equal,
    }


def _start_round(seed: int):
    rnd = Game(random.Random(seed)).start_round()
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
        raise DoseRefused("fresh deal has no banker")
    rnd.bury(rnd.banker, actors[rnd.banker].decide_bury(rnd, rnd.banker))
    return rnd, actors


def _all_cells_full(counts: Counter, states_per_cell: int) -> bool:
    return all(counts[(phase, role)] >= states_per_cell
               for phase in PHASES for role in ROLES)


def _assert_score_free(value) -> None:
    if isinstance(value, dict):
        overlap = SCORE_FIELDS.intersection(value)
        if overlap:
            raise DoseRefused(
                "score-free artifact contains outcome fields: "
                + ", ".join(sorted(overlap)))
        for child in value.values():
            _assert_score_free(child)
    elif isinstance(value, list):
        for child in value:
            _assert_score_free(child)


def _source_sha256s() -> dict[str, str]:
    paths = {
        "dose": SCRIPT,
        "pair_cap": SERVER / "shengji/ai/pair_cap_rollout.py",
        "pair_v1": SERVER / "shengji/ai/pair_aware_rollout.py",
        "mcbot": SERVER / "shengji/ai/mcbot.py",
        "memory": SERVER / "shengji/ai/memory.py",
        "heuristic": SERVER / "shengji/ai/heuristic.py",
        "evaluation": SERVER / "shengji/evaluation.py",
        "round": SERVER / "shengji/engine/round.py",
    }
    return {name: sha256(path) for name, path in sorted(paths.items())}


def run_census(*, seed0: int = SEED0, max_deals: int = MAX_DEALS,
               states_per_cell: int = STATES_PER_CELL) -> dict:
    if isinstance(seed0, bool) or not isinstance(seed0, int) or seed0 < 0:
        raise DoseRefused("seed0 must be a non-negative integer")
    if isinstance(max_deals, bool) or not isinstance(max_deals, int) \
            or max_deals < 1:
        raise DoseRefused("max_deals must be positive")
    if isinstance(states_per_cell, bool) or not isinstance(states_per_cell, int) \
            or not 1 <= states_per_cell <= 128:
        raise DoseRefused("states_per_cell must be in [1, 128]")

    started = time.monotonic()
    rows = []
    counts: Counter = Counter()
    deals_scanned = 0
    for deal_offset in range(max_deals):
        deal_seed = seed0 + deal_offset
        deals_scanned += 1
        rnd, actors = _start_round(deal_seed)
        while rnd.phase == "play":
            seat = rnd.turn
            if seat is None or rnd.trick is None:
                raise DoseRefused("fresh round lost active play state")
            if not rnd.trick.plays:
                phase = phase_band(len(rnd.history))
                role = "attacker" if rnd.is_attacker(seat) else "defender"
                cell = (phase, role)
                if counts[cell] < states_per_cell:
                    decision_seed = (
                        992_000_000 + deal_offset * 101
                        + len(rnd.history) * 4 + seat)
                    row = evaluate_state(rnd, seat, decision_seed=decision_seed)
                    row.update({
                        "state_id": f"{deal_seed}:{len(rnd.history)}:{seat}",
                        "deal_seed": deal_seed,
                        "completed_tricks": len(rnd.history),
                        "phase_band": phase,
                        "role": role,
                        "seat": seat,
                    })
                    rows.append(row)
                    counts[cell] += 1
                    print(json.dumps({
                        "event": "pair-cap-incremental-dose-progress-v1",
                        "states_complete": len(rows),
                        "states_total": states_per_cell * len(PHASES) * len(ROLES),
                        "cell": [phase, role],
                        "cell_complete": counts[cell],
                        "pair_cap_triggers": row["v2_pair_cap_dose"]["triggers"],
                        "incremental_root_change": row[
                            "v2_incremental_root_change"],
                    }, sort_keys=True), flush=True)
                    if _all_cells_full(counts, states_per_cell):
                        break
            rnd.play(seat, actors[seat].decide_play(rnd, seat))
        if _all_cells_full(counts, states_per_cell):
            break
    if not _all_cells_full(counts, states_per_cell):
        raise DoseRefused(f"fresh census underfilled cells: {dict(counts)}")

    aggregate = {
        "states": len(rows),
        "cell_counts": {
            f"{phase}_{role}": counts[(phase, role)]
            for phase in PHASES for role in ROLES
        },
        "searched_states": sum(row["searched"] for row in rows),
        "pair_cap_triggered_states": sum(
            row["v2_pair_cap_dose"]["triggers"] > 0 for row in rows),
        "pair_cap_triggers": sum(
            row["v2_pair_cap_dose"]["triggers"] for row in rows),
        "v1_root_changes": sum(row["v1_root_change"] for row in rows),
        "v2_root_changes": sum(row["v2_root_change"] for row in rows),
        "v2_incremental_root_changes": sum(
            row["v2_incremental_root_change"] for row in rows),
        "post_divergence_pair_streams_equal_states": sum(
            row["post_divergence_pair_streams_equal"] for row in rows),
        "searches": sum(row["work"]["searches"] for row in rows),
        "accepted_worlds": sum(row["work"]["accepted_worlds"] for row in rows),
        "elapsed_seconds": time.monotonic() - started,
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
        "source_sha256s": _source_sha256s(),
        "design": {
            "seed0": seed0,
            "max_deals": max_deals,
            "states_per_cell": states_per_cell,
            "phases": list(PHASES),
            "roles": list(ROLES),
            "selection": (
                "first natural lead states in ascending fresh deals, balanced "
                "by early/mid/late and attacker/defender"),
            "arms": ["reviewed_v1_treatment", "pair_cap_v2_treatment",
                     "pair_cap_v2_matched_null"],
            "score_free": True,
        },
        "deals_scanned": deals_scanned,
        "rows": rows,
        "aggregate": aggregate,
        "score_free": True,
        "outcomes_published": False,
        "exploration_only": True,
        "whole_game_execution_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    _assert_score_free(payload)
    payload["internal_sha256"] = stable_digest(payload)
    return payload


def write_exclusive(path: Path, payload: dict) -> None:
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise DoseRefused("refusing to overwrite pair-cap dose artifact")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":"))
           + "\n").encode()
    with partial.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.link(partial, path)
    partial.unlink()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--seed0", type=int, default=SEED0)
    parser.add_argument("--max-deals", type=int, default=MAX_DEALS)
    parser.add_argument("--states-per-cell", type=int, default=STATES_PER_CELL)
    args = parser.parse_args()
    payload = run_census(
        seed0=args.seed0, max_deals=args.max_deals,
        states_per_cell=args.states_per_cell)
    write_exclusive(Path(args.out), payload)
    print(json.dumps({
        "status": "COMPLETE_SCORE_FREE_EXPLORATION",
        "aggregate": payload["aggregate"],
        "output_sha256": sha256(args.out),
        "internal_sha256": payload["internal_sha256"],
    }, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
