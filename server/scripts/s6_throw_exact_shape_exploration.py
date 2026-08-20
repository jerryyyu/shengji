#!/usr/bin/env python3
"""Exploration-tier exact value of S6 throw-source strata.

The full S6 source is intentionally broad: it offers a legal throw whenever
one exists.  Before paying for a large whole-game search experiment, this
diagnostic asks a narrower action-set question at fully solvable four-card
endgames:

* does a newly sourced action beat the *best* action already present on the
  live ballot under perfect-information partnership minimax; and
* which source family carries that opportunity: boss/near-boss bundle,
  whole plain-suit evacuation, or whole-trump evacuation?

State selection is score-free and balanced before any exact outcome is
computed.  Each deal contributes at most one state.  Solver refusals are
retained rather than invalidating scoreable rows.  The output is reusable
exploration only: its oracle selector cannot authorize a policy, strength
claim, scored whole-game run, promotion, or deployment.
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
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.ai.throw_sourcing import (  # noqa: E402
    BOSS_NEAR_BUNDLE,
    WHOLE_SUIT_EVACUATION,
    WHOLE_TRUMP_EVACUATION,
    structured_throw_ballot,
)
from shengji.engine.game import Game  # noqa: E402
from shengji.engine.round import actual_play_after  # noqa: E402


SCHEMA = "s6-throw-exact-shape-exploration-v1"
CAPTURE_SCHEMA = "s6-throw-exact-shape-capture-v1"
ROW_SCHEMA = "s6-throw-exact-shape-row-v1"
SEED0 = 432_000_000
MAX_DEALS = 100_000
HAND_CARDS = 4
MAX_EXACT_NODES = 500_000
CELL_QUOTA = 32
ROLES = ("attacker", "defender")
STRATA = ("boss_near", "whole_plain", "whole_trump")
DESCRIPTIVE_Z = 1.96


class ExplorationRefused(RuntimeError):
    """The diagnostic cannot honestly reproduce its bounded claim."""


def sha256(path: os.PathLike | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True, capture_output=True, text=True,
    ).stdout.strip()


def source_sha256s() -> dict[str, str]:
    paths = {
        "exploration": SCRIPT,
        "throw_source": SERVER / "shengji/ai/throw_sourcing.py",
        "mcbot": SERVER / "shengji/ai/mcbot.py",
        "memory": SERVER / "shengji/ai/memory.py",
        "heuristic": SERVER / "shengji/ai/heuristic.py",
        "endgame": SERVER / "shengji/ai/endgame.py",
        "round": SERVER / "shengji/engine/round.py",
        "game": SERVER / "shengji/engine/game.py",
    }
    return {name: sha256(path) for name, path in sorted(paths.items())}


def action_key(cards) -> tuple[str, ...]:
    return tuple(sorted(cards))


def candidate_stratum(sources) -> str:
    """Assign one stable stratum, preferring the more specific source."""
    sources = set(sources)
    if BOSS_NEAR_BUNDLE in sources:
        return "boss_near"
    if WHOLE_TRUMP_EVACUATION in sources:
        return "whole_trump"
    if WHOLE_SUIT_EVACUATION in sources:
        return "whole_plain"
    raise ExplorationRefused(f"unknown S6 source family: {sorted(sources)}")


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
        raise ExplorationRefused("fresh deal has no banker")
    rnd.bury(rnd.banker, actors[rnd.banker].decide_bury(rnd, rnd.banker))
    return rnd, actors


def _source_state(rnd, seat: int) -> dict[str, object] | None:
    if (rnd.phase != "play" or rnd.trick is None or rnd.trick.plays
            or max(map(len, rnd.hands)) != HAND_CARDS):
        return None
    live = make_bot("mc-s0-report-lcb", seed=0)._candidates(rnd, seat)
    live_keys = {action_key(action) for action in live}
    grouped = {stratum: [] for stratum in STRATA}
    for candidate in structured_throw_ballot(rnd, seat).candidates:
        if candidate.cards in live_keys:
            continue
        stratum = candidate_stratum(candidate.sources)
        grouped[stratum].append(candidate.record())
    if not any(grouped.values()):
        return None
    return {
        "live_candidates": [list(action) for action in live],
        "added_by_stratum": grouped,
    }


def capture_states(*, seed0: int = SEED0, max_deals: int = MAX_DEALS,
                   cell_quota: int = CELL_QUOTA) -> dict:
    """Select balanced public states before opening exact outcomes."""
    if (isinstance(cell_quota, bool) or not isinstance(cell_quota, int)
            or cell_quota < 1):
        raise ValueError("cell_quota must be a positive integer")
    requested = {(role, stratum): cell_quota
                 for role in ROLES for stratum in STRATA}
    accepted = Counter()
    rows = []
    scanned = 0
    for offset in range(max_deals):
        if all(accepted[cell] == quota for cell, quota in requested.items()):
            break
        seed = seed0 + offset
        scanned += 1
        rnd, actors = _start_round(seed)
        selected = None
        while rnd.phase == "play":
            seat = rnd.turn
            if seat is None:
                raise ExplorationRefused("play state lost its acting seat")
            source = _source_state(rnd, seat)
            if source is not None:
                role = "attacker" if rnd.is_attacker(seat) else "defender"
                available = [
                    stratum for stratum in STRATA
                    if source["added_by_stratum"][stratum]
                    and accepted[(role, stratum)] < cell_quota
                ]
                if available:
                    stratum = min(
                        available,
                        key=lambda value: (
                            accepted[(role, value)], STRATA.index(value)),
                    )
                    selected = {
                        "schema": CAPTURE_SCHEMA,
                        "state_id": f"{seed}:{len(rnd.history)}:{seat}",
                        "deal_seed": seed,
                        "completed_tricks": len(rnd.history),
                        "seat": seat,
                        "role": role,
                        "stratum": stratum,
                        "hand_cards": HAND_CARDS,
                        "live_candidates": source["live_candidates"],
                        "added_candidates": source["added_by_stratum"][stratum],
                        "score_free_selection": True,
                    }
                    break
            rnd.play(seat, actors[seat].decide_play(rnd, seat))
        if selected is not None:
            rows.append(selected)
            accepted[(selected["role"], selected["stratum"])] += 1

    cell_counts = {
        f"{role}:{stratum}": accepted[(role, stratum)]
        for role in ROLES for stratum in STRATA
    }
    complete = all(value == cell_quota for value in cell_counts.values())
    return {
        "schema": "s6-throw-exact-shape-capture-population-v1",
        "score_free": True,
        "outcomes_computed": False,
        "seed0": seed0,
        "max_deals": max_deals,
        "deals_scanned": scanned,
        "cell_quota": cell_quota,
        "cell_counts": cell_counts,
        "complete": complete,
        "rows": rows,
    }


def replay_capture(record: dict):
    rnd, actors = _start_round(int(record["deal_seed"]))
    target = int(record["completed_tricks"])
    while rnd.phase == "play":
        seat = rnd.turn
        if (seat == record["seat"] and len(rnd.history) == target
                and rnd.trick is not None and not rnd.trick.plays):
            source = _source_state(rnd, seat)
            if source is None:
                raise ExplorationRefused("captured source state disappeared")
            expected_added = source["added_by_stratum"][record["stratum"]]
            if (source["live_candidates"] != record["live_candidates"]
                    or expected_added != record["added_candidates"]):
                raise ExplorationRefused("captured ballot/source drift")
            return rnd
        rnd.play(seat, actors[seat].decide_play(rnd, seat))
    raise ExplorationRefused("captured lead was not replayed")


def _acting_level_value(attacker_points: int,
                        acting_is_attacker: bool) -> float:
    """House bracket plus half-level deal possession, from actor team."""
    if attacker_points >= 80:
        attacker_value = (attacker_points - 80) // 40 + 0.5
    elif attacker_points == 0:
        attacker_value = -3.5
    else:
        attacker_value = -(1 + (79 - attacker_points) // 40) - 0.5
    return attacker_value if acting_is_attacker else -attacker_value


def _score_action(rnd, seat: int, action: list[str]) -> dict:
    clone = copy.deepcopy(rnd)
    previous_last = clone.last_trick
    clone.play(seat, list(action))
    actual = actual_play_after(clone, seat, previous_last)
    message = clone.message
    if clone.phase == "round_end":
        final_points = int(clone.attacker_points)
        nodes = cache_hits = 0
    else:
        result = solve_exact_endgame(
            clone, max_hand_cards=HAND_CARDS, max_nodes=MAX_EXACT_NODES)
        final_points = int(result.attacker_points)
        nodes = int(result.nodes)
        cache_hits = int(result.cache_hits)
    attacker = rnd.is_attacker(seat)
    return {
        "submitted": list(action),
        "actual": actual,
        "throw_failed": action_key(actual) != action_key(action),
        "engine_message": message,
        "final_attacker_points": final_points,
        "acting_team_points": final_points if attacker else -final_points,
        "acting_team_level_value": _acting_level_value(final_points, attacker),
        "exact_nodes": nodes,
        "exact_cache_hits": cache_hits,
    }


def _best(scored: list[dict]) -> dict:
    if not scored:
        raise ExplorationRefused("cannot choose an oracle from no actions")
    return max(
        scored,
        key=lambda row: (
            row["acting_team_level_value"],
            row["acting_team_points"],
            action_key(row["submitted"]),
        ),
    )


def score_capture(record: dict) -> dict:
    rnd = replay_capture(record)
    seat = int(record["seat"])
    live_scores = [_score_action(rnd, seat, list(action))
                   for action in record["live_candidates"]]
    new_scores = [_score_action(rnd, seat, list(candidate["cards"]))
                  for candidate in record["added_candidates"]]
    live_best = _best(live_scores)
    new_best = _best(new_scores)
    return {
        "schema": ROW_SCHEMA,
        "state_id": record["state_id"],
        "deal_seed": record["deal_seed"],
        "role": record["role"],
        "stratum": record["stratum"],
        "status": "SCORED",
        "live_candidate_count": len(live_scores),
        "new_candidate_count": len(new_scores),
        "live_oracle": live_best,
        "new_source_oracle": new_best,
        "signed_level_utility_delta": (
            new_best["acting_team_level_value"]
            - live_best["acting_team_level_value"]),
        "signed_point_delta": (
            new_best["acting_team_points"]
            - live_best["acting_team_points"]),
        "perfect_information_oracle": True,
        "strength_claim": False,
    }


def _descriptive(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"n": 0, "mean": None, "se": None,
                "two_sided_95_half_width": None}
    mean = sum(values) / len(values)
    if len(values) < 2:
        return {"n": len(values), "mean": mean, "se": None,
                "two_sided_95_half_width": None}
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    se = math.sqrt(variance / len(values))
    return {"n": len(values), "mean": mean, "se": se,
            "two_sided_95_half_width": DESCRIPTIVE_Z * se}


def aggregate(rows: list[dict], *, cell_quota: int) -> dict:
    scored = [row for row in rows if row.get("status") == "SCORED"]
    refused = [row for row in rows if row.get("status") == "REFUSED"]
    cells = {}
    for role in ROLES:
        for stratum in STRATA:
            values = [row for row in scored
                      if row["role"] == role and row["stratum"] == stratum]
            cells[f"{role}:{stratum}"] = {
                "level_delta": _descriptive([
                    row["signed_level_utility_delta"] for row in values]),
                "point_delta": _descriptive([
                    row["signed_point_delta"] for row in values]),
                "wins": sum(row["signed_level_utility_delta"] > 0
                            for row in values),
                "losses": sum(row["signed_level_utility_delta"] < 0
                              for row in values),
                "ties": sum(row["signed_level_utility_delta"] == 0
                            for row in values),
                "requested": cell_quota,
            }
    strata = {}
    for stratum in STRATA:
        values = [row for row in scored if row["stratum"] == stratum]
        strata[stratum] = {
            "level_delta": _descriptive([
                row["signed_level_utility_delta"] for row in values]),
            "point_delta": _descriptive([
                row["signed_point_delta"] for row in values]),
            "wins": sum(row["signed_level_utility_delta"] > 0
                        for row in values),
            "losses": sum(row["signed_level_utility_delta"] < 0
                          for row in values),
            "ties": sum(row["signed_level_utility_delta"] == 0
                        for row in values),
        }
    ranking = sorted(
        STRATA,
        key=lambda name: (
            strata[name]["level_delta"]["mean"] is not None,
            (strata[name]["level_delta"]["mean"]
             if strata[name]["level_delta"]["mean"] is not None
             else float("-inf")),
            -STRATA.index(name),
        ),
        reverse=True,
    )
    coverage_complete = all(
        cells[f"{role}:{stratum}"]["level_delta"]["n"] == cell_quota
        for role in ROLES for stratum in STRATA
    )
    return {
        "primary": (
            "perfect-information best-new-source action minus best-live-ballot "
            "action, acting-team level utility"),
        "cells": cells,
        "strata": strata,
        "descriptive_ranking": ranking,
        "scored_rows": len(scored),
        "refused_rows": len(refused),
        "coverage_complete": coverage_complete,
        "multiple_comparison_adjustment": False,
        "policy_selector_tested": False,
        "whole_game_execution_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }


def run_exploration() -> dict:
    capture = capture_states()
    result_rows = []
    for index, record in enumerate(capture["rows"], 1):
        try:
            result_rows.append(score_capture(record))
        except Exception as exc:
            result_rows.append({
                "schema": ROW_SCHEMA,
                "state_id": record["state_id"],
                "deal_seed": record["deal_seed"],
                "role": record["role"],
                "stratum": record["stratum"],
                "status": "REFUSED",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "strength_claim": False,
            })
        if index % 16 == 0 or index == len(capture["rows"]):
            print(json.dumps({
                "event": "s6-exact-shape-progress-v1",
                "states_complete": index,
                "states_total": len(capture["rows"]),
            }, sort_keys=True), flush=True)
    payload = {
        "schema": SCHEMA,
        "git": git("rev-parse", "HEAD"),
        "tree_dirty": bool(git("status", "--porcelain")),
        "source_sha256s": source_sha256s(),
        "design": {
            "seed0": SEED0,
            "max_deals": MAX_DEALS,
            "hand_cards": HAND_CARDS,
            "max_exact_nodes_per_action": MAX_EXACT_NODES,
            "cell_quota": CELL_QUOTA,
            "roles": list(ROLES),
            "strata": list(STRATA),
            "selection": (
                "one score-free four-card lead per deal; balance the least-"
                "filled available role/stratum cell before exact scoring"),
            "estimand": (
                "oracle action-set value of each new source stratum versus the "
                "oracle best action already on the live ballot"),
        },
        "capture": capture,
        "rows": result_rows,
        "aggregate": aggregate(result_rows, cell_quota=CELL_QUOTA),
        "exploration_only": True,
        "reusable_diagnostic": True,
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
        raise ExplorationRefused("refusing to overwrite S6 shape artifact")
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
        raise ExplorationRefused("S6 shape artifact failed exact reopen")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    payload = run_exploration()
    write_exclusive(Path(args.out), payload)
    print(json.dumps({
        "status": "COMPLETE_EXPLORATION" if
            payload["aggregate"]["coverage_complete"] else
            "PARTIAL_EXPLORATION_RETAINED",
        "output_sha256": sha256(args.out),
        "internal_sha256": payload["internal_sha256"],
        "aggregate": payload["aggregate"],
        "strength_claim": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
