#!/usr/bin/env python3
"""Score-free natural-state dose census for pair-aware MC rollouts.

The exact four-card screen asks whether a promoted low-pair lead can be good.
This census asks the next, deliberately narrower question: when the complete
live report-LCB search sees ordinary early/mid/late lead states, does replacing
only its rollout continuation expose the mechanism and ever change the root
move?

No round outcome, points, winner, utility, or win rate is published.  The
artifact exists only to size a later reviewed whole-game packet; it cannot
support a strength or deployment claim.
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
from shengji.engine.game import Game  # noqa: E402
from shengji.evaluation import counters  # noqa: E402


SCHEMA = "pair-aware-rollout-root-dose-v1"
SEED0 = 333_000_000
MAX_DEALS = 10_000
STATES_PER_CELL = 4
PHASES = ("early", "mid", "late")
ROLES = ("attacker", "defender")
SCORE_FIELDS = frozenset({
    "attacker_points", "kitty_bonus", "level_change", "level_utility",
    "outcome", "outcomes", "points", "utility", "win_rate", "winner",
    "winner_team", "won", "wins", "losses",
})
WORK_FIELDS = tuple(
    key for key in counters([]) if key != "search_secs"
)


class DoseRefused(RuntimeError):
    """The census cannot support even its score-free sizing claim."""


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
    if isinstance(completed_tricks, bool) or not isinstance(completed_tricks, int):
        raise DoseRefused("completed trick count is not an integer")
    if not 0 <= completed_tricks <= 24:
        raise DoseRefused("completed trick count outside a Shengji round")
    if completed_tricks <= 7:
        return "early"
    if completed_tricks <= 16:
        return "mid"
    return "late"


def _source_sha256s() -> dict[str, str]:
    paths = {
        "dose": SCRIPT,
        "pair_aware": SERVER / "shengji/ai/pair_aware_rollout.py",
        "mcbot": SERVER / "shengji/ai/mcbot.py",
        "memory": SERVER / "shengji/ai/memory.py",
        "heuristic": SERVER / "shengji/ai/heuristic.py",
        "evaluation": SERVER / "shengji/evaluation.py",
        "round": SERVER / "shengji/engine/round.py",
        "game": SERVER / "shengji/engine/game.py",
    }
    return {name: sha256(path) for name, path in sorted(paths.items())}


def _public_state_digest(rnd, seat: int) -> str:
    """Digest only information available to the acting player."""
    history = [
        {
            "leader": trick.leader,
            "plays": [
                {"seat": play.seat, "cards": sorted(play.cards)}
                for play in trick.plays
            ],
        }
        for trick in rnd.history
    ]
    actor_private = {
        "own_hand": sorted(rnd.hands[seat]),
        # The banker knows what they buried; no other seat may use it.
        "own_buried": sorted(rnd.buried) if seat == rnd.banker else [],
    }
    return stable_digest({
        "trump_rank": rnd.trump_rank,
        "trump_suit": rnd.trump_suit,
        "trump_is_nt": rnd.trump_is_nt,
        "banker": rnd.banker,
        "seat": seat,
        "history": history,
        "current_leader": rnd.trick.leader if rnd.trick else None,
        "current_plays": [] if rnd.trick is None else [
            {"seat": play.seat, "cards": sorted(play.cards)}
            for play in rnd.trick.plays
        ],
        **actor_private,
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


def _candidate_identity(bot) -> list[list[str]] | None:
    record = bot.last_decision_record
    if record is None:
        return None
    candidates = record.get("candidates")
    if not isinstance(candidates, list):
        raise DoseRefused("searched decision omitted root candidates")
    return [list(cards) for cards in candidates]


def evaluate_state(rnd, seat: int, *, decision_seed: int) -> dict:
    treatment = make_pair_aware_bot(treatment=True, seed=decision_seed)
    matched_null = make_pair_aware_bot(treatment=False, seed=decision_seed)
    treatment_action = treatment.decide_play(copy.deepcopy(rnd), seat)
    null_action = matched_null.decide_play(copy.deepcopy(rnd), seat)

    treatment_candidates = _candidate_identity(treatment)
    null_candidates = _candidate_identity(matched_null)
    if treatment_candidates != null_candidates:
        raise DoseRefused("treatment/null root ballot identity drift")
    treatment_work = _work(treatment)
    null_work = _work(matched_null)
    if treatment_work != null_work:
        raise DoseRefused("treatment/null exact MC work drift")

    treatment_dose = treatment.pair_aware_telemetry()
    null_dose = matched_null.pair_aware_telemetry()
    if set(treatment_dose) != set(null_dose):
        raise DoseRefused("treatment/null dose field population drift")
    if treatment_dose["mode"] != "treatment" or null_dose["mode"] != "matched_null":
        raise DoseRefused("pair-aware dose modes drifted")
    for dose in (treatment_dose, null_dose):
        if any(name not in dose for name in PAIR_AWARE_COUNTER_FIELDS):
            raise DoseRefused("pair-aware dose counters are incomplete")

    return {
        "decision_seed": decision_seed,
        "public_state_sha256": _public_state_digest(rnd, seat),
        "root_candidate_count": (
            len(treatment_candidates) if treatment_candidates is not None else 1
        ),
        "searched": treatment_work["searches"] > 0,
        "treatment_action": list(treatment_action),
        "matched_null_action": list(null_action),
        "root_action_changed": sorted(treatment_action) != sorted(null_action),
        "work": treatment_work,
        "treatment_dose": treatment_dose,
        "matched_null_dose": null_dose,
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


def run_census(*, seed0: int = SEED0, max_deals: int = MAX_DEALS,
               states_per_cell: int = STATES_PER_CELL) -> dict:
    if isinstance(seed0, bool) or not isinstance(seed0, int) or seed0 < 0:
        raise DoseRefused("seed0 must be a non-negative integer")
    if isinstance(max_deals, bool) or not isinstance(max_deals, int) or max_deals < 1:
        raise DoseRefused("max_deals must be positive")
    if (isinstance(states_per_cell, bool) or not isinstance(states_per_cell, int)
            or not 1 <= states_per_cell <= 64):
        raise DoseRefused("states_per_cell must be in [1, 64]")

    started = time.monotonic()
    rows: list[dict] = []
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
                        991_000_000 + deal_offset * 101 + len(rnd.history) * 4 + seat
                    )
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
                        "event": "pair-aware-root-dose-progress-v1",
                        "states_complete": len(rows),
                        "states_total": states_per_cell * len(PHASES) * len(ROLES),
                        "cell": [phase, role],
                        "cell_complete": counts[cell],
                        "searched": row["searched"],
                        "root_action_changed": row["root_action_changed"],
                        "treatment_triggers": row["treatment_dose"]["triggers"],
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
        "treatment_triggered_states": sum(
            row["treatment_dose"]["triggers"] > 0 for row in rows),
        "matched_null_triggered_states": sum(
            row["matched_null_dose"]["triggers"] > 0 for row in rows),
        "root_action_changes": sum(row["root_action_changed"] for row in rows),
        "treatment_triggers": sum(
            row["treatment_dose"]["triggers"] for row in rows),
        "matched_null_triggers": sum(
            row["matched_null_dose"]["triggers"] for row in rows),
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
                "by early/mid/late and attacker/defender"
            ),
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
        raise DoseRefused("refusing to overwrite root-dose artifact")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    with partial.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.link(partial, path)
    partial.unlink()
    if path.read_bytes() != raw:
        raise DoseRefused("root-dose artifact failed exact reopen")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--seed0", type=int, default=SEED0)
    parser.add_argument("--max-deals", type=int, default=MAX_DEALS)
    parser.add_argument("--states-per-cell", type=int, default=STATES_PER_CELL)
    args = parser.parse_args()
    payload = run_census(
        seed0=args.seed0,
        max_deals=args.max_deals,
        states_per_cell=args.states_per_cell,
    )
    write_exclusive(Path(args.out), payload)
    print(json.dumps({
        "status": "SCORE_FREE_ROOT_DOSE_COMPLETE",
        "aggregate": payload["aggregate"],
        "output_sha256": sha256(args.out),
        "internal_sha256": payload["internal_sha256"],
    }, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
