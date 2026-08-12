#!/usr/bin/env python3
"""Outcome-blind reusable-DEV population for bury/first-lead exploration.

The source asset is the already-opened 512-state S3a banker-bury pilot.  This
module reconstructs those public decision states from their fixed deal seeds,
summarises only actor-visible candidate geometry, and chooses a small mixture
of shape-rich rows plus hash-uniform anchors.  It does not read S3a utilities,
score a rollout, launch a job, or grant strength authority.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

from s3a_bury_pilot import build_bury_state  # noqa: E402
from shengji.ai.bury_lead_combo import (  # noqa: E402
    build_bury_lead_combo_ballot,
)
from shengji.ai.registry import make_bot  # noqa: E402


SCHEMA = "bury-first-lead-source-census-state-v1"
SELECTION_SCHEMA = "bury-first-lead-dev-selection-v1"
POPULATION_ID = "s3a-bury-v2-opened-dev-136m-v1"
CHAMPION = "mc-s0-report-lcb"
DEAL_SEED0 = 136_000_000
POPULATION_STATES = 512
SOURCE_GIT = "14548d3da31c3cfe899cbd7e572614ae05242c0a"
SOURCE_AGGREGATE_SHA256 = (
    "74aa5a3947e1daaa5aa4bc33eef8ae04eaaf695d0cb900c7045eb0cbbc4396cd")
SOURCE_STATE_MANIFEST_SHA256 = (
    "7313fc48a349a1fafad2e39d63c983a262ea4d858ce538a3c6697792327eaed7")
SOURCE_SHARD_SHA256S = (
    "028d6001ae55775ac6ff27fbf0710a100b982621378b8a1ba209031e0a57fb69",
    "eb2d7cbaccffc96fe864b98d94aa7953fbf33a2276194b69ce511256ca761279",
    "75b3883017765a4c465e2e7a784c3f2c631b4ab2e27a104d475c0cd7853865b5",
    "a73226347ea9a5e3a42273376500b9ad9380475d842e18ad7b7fe585fee371ed",
    "bb9dfd789bd62f36c13bf2029ee902f2a6f24409c6b5d08a7c44b206ebf12a35",
    "c1b82b9e26a1ca1d4f54fd415334d4c7251e66803374f671e8e7f4b8684254a8",
    "b4058a0d1238798e43dc26c2e391a0ce234a57e6ccf62918c2f27c70c9dad8fa",
    "8e14c7a7520dcc804daeea062ccd28be76479aeab6d9d70c5691c31f34690383",
)

STATE_KEYS = {
    "schema", "population_id", "state_id", "source_state_id", "deal_seed",
    "banker", "champion", "source_input_sha256", "source_replay_sha256",
    "ballot_sha256", "bury_count",
    "generated_buries", "combo_count", "combo_cap",
    "feasible_single_suit_voids", "shape", "score_free",
    "source_population_already_opened", "source_outcomes_read",
    "strength_claim", "production_deployment",
}
SHAPE_KEYS = {
    "groups_with_plain_void", "groups_with_structured_throw",
    "groups_with_tractor", "max_pair_run", "max_pair_units",
    "pair_unit_spread", "trump_count_spread", "retained_point_spread",
    "structured_throw_candidates", "pair_lead_candidates",
    "live_lead_candidates",
}
SELECTION_KEYS = {
    "schema", "population", "selection", "projected_work", "score_free",
    "source_population_already_opened", "source_outcomes_read",
    "exploration_only", "confirmatory_inference", "strength_claim",
    "production_promotion", "production_deployment",
}
SELECTION_ROW_KEYS = {
    "state_id", "source_state_id", "deal_seed", "selection_group",
    "selection_reason", "combo_count",
}
METRICS = (
    "combo_count",
    "feasible_void_count",
    "groups_with_plain_void",
    "groups_with_structured_throw",
    "groups_with_tractor",
    "max_pair_run",
    "pair_unit_spread",
    "retained_point_spread",
)


class PopulationRefused(RuntimeError):
    """The reusable population or outcome-blind selection drifted."""


def _canonical(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode()


def stable_digest(value) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _source_asset_digest(value) -> str:
    """Match the opened S3a asset's newline-terminated canonical JSON."""
    return hashlib.sha256(_canonical(value) + b"\n").hexdigest()


def _spread(values: list[int]) -> int:
    return max(values) - min(values)


def census_state(
    deal_seed: int,
    *,
    state_builder: Callable = build_bury_state,
    bot_factory: Callable = make_bot,
) -> dict:
    """Reconstruct and describe one state without evaluating an outcome."""
    if (isinstance(deal_seed, bool) or not isinstance(deal_seed, int)
            or not DEAL_SEED0 <= deal_seed < DEAL_SEED0 + POPULATION_STATES):
        raise PopulationRefused("deal seed is outside the opened S3a DEV asset")
    rnd, incumbent, replay = state_builder(deal_seed, CHAMPION)
    seat = rnd.banker
    if rnd.phase != "bury" or seat is None or rnd.ordering is None:
        raise PopulationRefused("reconstructed state is not an acting bury")
    bot = bot_factory(CHAMPION, seed=0)
    rng_before = bot.rng.getstate()
    ballot = build_bury_lead_combo_ballot(
        rnd, seat, incumbent, live_lead_ballot=bot._candidates)
    if bot.rng.getstate() != rng_before:
        raise PopulationRefused("source census consumed search RNG")

    groups = ballot.groups
    pair_units = [int(group.retained_shape["pair_units"])
                  for group in groups]
    trumps = [int(group.retained_shape["trump_count"])
              for group in groups]
    retained_points = [int(group.retained_shape["retained_point_total"])
                       for group in groups]
    shape = {
        "groups_with_plain_void": sum(
            bool(group.retained_shape["plain_voids"]) for group in groups),
        "groups_with_structured_throw": sum(
            bool(group.structured_throw_ballot.candidates)
            for group in groups),
        "groups_with_tractor": sum(
            int(group.retained_shape["max_pair_run"]) >= 2
            for group in groups),
        "max_pair_run": max(
            int(group.retained_shape["max_pair_run"]) for group in groups),
        "max_pair_units": max(pair_units),
        "pair_unit_spread": _spread(pair_units),
        "trump_count_spread": _spread(trumps),
        "retained_point_spread": _spread(retained_points),
        "structured_throw_candidates": sum(
            sum(lead.structured_throw for lead in group.leads)
            for group in groups),
        "pair_lead_candidates": sum(
            sum(lead.pair_lead for lead in group.leads)
            for group in groups),
        "live_lead_candidates": sum(
            group.live_lead_count for group in groups),
    }
    source_input = {
        "banker": seat,
        "banker_hand": list(rnd.hands[seat]),
        "incumbent": list(incumbent),
        "ordering": {
            "trump_suit": rnd.ordering.trump_suit,
            "trump_rank": rnd.ordering.trump_rank,
        },
    }
    result = {
        "schema": SCHEMA,
        "population_id": POPULATION_ID,
        "state_id": f"{POPULATION_ID}:deal:{deal_seed}:banker:{seat}",
        "source_state_id":
            f"s3a-bury-pilot-v2:deal:{deal_seed}:banker:{seat}",
        "deal_seed": deal_seed,
        "banker": seat,
        "champion": CHAMPION,
        "source_input_sha256": _source_asset_digest(source_input),
        "source_replay_sha256": stable_digest(replay),
        "ballot_sha256": stable_digest(ballot.record()),
        "bury_count": len(groups),
        "generated_buries": ballot.generated_buries,
        "combo_count": ballot.combo_count,
        "combo_cap": ballot.max_combos,
        "feasible_single_suit_voids":
            list(ballot.feasible_single_suit_voids),
        "shape": shape,
        "score_free": True,
        "source_population_already_opened": True,
        "source_outcomes_read": False,
        "strength_claim": False,
        "production_deployment": False,
    }
    return result


def state_problems(row: Mapping[str, object]) -> list[str]:
    problems = []
    if set(row) != STATE_KEYS:
        problems.append("state field population")
    if row.get("schema") != SCHEMA or row.get("population_id") != POPULATION_ID:
        problems.append("state identity")
    seed = row.get("deal_seed")
    if (isinstance(seed, bool) or not isinstance(seed, int)
            or not DEAL_SEED0 <= seed < DEAL_SEED0 + POPULATION_STATES):
        problems.append("deal seed")
    if row.get("champion") != CHAMPION:
        problems.append("champion")
    shape = row.get("shape")
    if not isinstance(shape, Mapping) or set(shape) != SHAPE_KEYS:
        problems.append("shape field population")
    if (row.get("score_free") is not True
            or row.get("source_population_already_opened") is not True
            or row.get("source_outcomes_read") is not False):
        problems.append("score-free boundary")
    if row.get("strength_claim") is not False \
            or row.get("production_deployment") is not False:
        problems.append("authority boundary")
    for field in ("bury_count", "generated_buries", "combo_count", "combo_cap"):
        value = row.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            problems.append(field)
    if (isinstance(row.get("combo_count"), int)
            and isinstance(row.get("combo_cap"), int)
            and row["combo_count"] > row["combo_cap"]):
        problems.append("combo cap")
    for field in (
            "source_input_sha256", "source_replay_sha256", "ballot_sha256"):
        value = row.get(field)
        if (not isinstance(value, str) or len(value) != 64
                or any(char not in "0123456789abcdef" for char in value)):
            problems.append(field)
    banker = row.get("banker")
    if isinstance(banker, bool) or not isinstance(banker, int) \
            or banker not in range(4):
        problems.append("banker")
    if isinstance(seed, int) and isinstance(banker, int) \
            and row.get("state_id") != \
            f"{POPULATION_ID}:deal:{seed}:banker:{banker}":
        problems.append("state id")
    if isinstance(seed, int) and isinstance(banker, int) \
            and row.get("source_state_id") != \
            f"s3a-bury-pilot-v2:deal:{seed}:banker:{banker}":
        problems.append("source state id")
    voids = row.get("feasible_single_suit_voids")
    if (not isinstance(voids, list)
            or any(not isinstance(suit, str) for suit in voids)
            or len(voids) != len(set(voids))
            or any(suit not in "SHDC" for suit in voids)):
        problems.append("feasible voids")
    if isinstance(shape, Mapping) and set(shape) == SHAPE_KEYS:
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
               for value in shape.values()):
            problems.append("shape values")
    return sorted(set(problems))


def _metric(row: Mapping[str, object], name: str) -> int:
    if name == "combo_count":
        return int(row[name])
    if name == "feasible_void_count":
        return len(row["feasible_single_suit_voids"])
    return int(row["shape"][name])


def _tie(row: Mapping[str, object], purpose: str) -> str:
    return stable_digest({
        "population_id": POPULATION_ID,
        "state_id": row["state_id"],
        "purpose": purpose,
    })


def _source_manifest_digest(rows: Iterable[Mapping[str, object]]) -> str:
    material = [{
        "deal_seed": row["deal_seed"],
        "state_id": row["source_state_id"],
        "source_input_sha256": row["source_input_sha256"],
        "source_replay_sha256": row["source_replay_sha256"],
    } for row in sorted(rows, key=lambda value: value["deal_seed"])]
    return stable_digest(material)


def selection_problems(value: object, *, require_full_population: bool = True) \
        -> list[str]:
    """Validate a materialized selection without trusting its description."""
    if not isinstance(value, Mapping):
        return ["selection is not an object"]
    problems = []
    if set(value) != SELECTION_KEYS or value.get("schema") != SELECTION_SCHEMA:
        problems.append("selection field population or schema")
    if (value.get("score_free") is not True
            or value.get("source_population_already_opened") is not True
            or value.get("source_outcomes_read") is not False
            or value.get("exploration_only") is not True
            or value.get("confirmatory_inference") is not False
            or value.get("strength_claim") is not False
            or value.get("production_promotion") is not False
            or value.get("production_deployment") is not False):
        problems.append("selection authority boundary")

    population = value.get("population")
    expected_population = {
        "id": POPULATION_ID,
        "opened_reusable_dev": True,
        "source_git": SOURCE_GIT,
        "source_aggregate_sha256": SOURCE_AGGREGATE_SHA256,
        "source_state_manifest_sha256": SOURCE_STATE_MANIFEST_SHA256,
        "source_shard_sha256s": list(SOURCE_SHARD_SHA256S),
        "deal_seed0": DEAL_SEED0,
    }
    if not isinstance(population, Mapping):
        problems.append("selection population missing")
    else:
        for key, expected in expected_population.items():
            if population.get(key) != expected:
                problems.append(f"selection population {key}")
        states = population.get("states")
        if (isinstance(states, bool) or not isinstance(states, int)
                or states < 1
                or (require_full_population
                    and states != POPULATION_STATES)):
            problems.append("selection population states")

    selection = value.get("selection")
    rows = selection.get("rows") if isinstance(selection, Mapping) else None
    if not isinstance(rows, list) or not rows:
        problems.append("selection rows missing")
        rows = []
    else:
        ids = []
        seeds = []
        groups = {"shape_rich": 0, "hash_uniform_anchor": 0}
        for row in rows:
            if not isinstance(row, Mapping) or set(row) != SELECTION_ROW_KEYS:
                problems.append("selection row fields")
                continue
            seed = row.get("deal_seed")
            state_id = row.get("state_id")
            source_state_id = row.get("source_state_id")
            if (isinstance(seed, bool) or not isinstance(seed, int)
                    or not DEAL_SEED0 <= seed <
                    DEAL_SEED0 + POPULATION_STATES):
                problems.append("selection row deal seed")
            if not isinstance(state_id, str) or f":deal:{seed}:" not in state_id:
                problems.append("selection row state id")
            if (not isinstance(source_state_id, str)
                    or f":deal:{seed}:" not in source_state_id):
                problems.append("selection row source state id")
            group = row.get("selection_group")
            if group not in groups:
                problems.append("selection row group")
            else:
                groups[group] += 1
            combo_count = row.get("combo_count")
            if (isinstance(combo_count, bool)
                    or not isinstance(combo_count, int)
                    or not 1 <= combo_count <= 1088):
                problems.append("selection row combo count")
            ids.append(state_id)
            seeds.append(seed)
        if len(ids) != len(set(ids)) or len(seeds) != len(set(seeds)):
            problems.append("selection row duplicates")
        if isinstance(selection, Mapping):
            if selection.get("total") != len(rows):
                problems.append("selection total")
            if selection.get("shape_rich") != groups["shape_rich"]:
                problems.append("selection shape count")
            if selection.get("hash_uniform_anchor") != \
                    groups["hash_uniform_anchor"]:
                problems.append("selection anchor count")
            if selection.get("metrics") != list(METRICS):
                problems.append("selection metrics")
            if selection.get("rows_sha256") != stable_digest(rows):
                problems.append("selection rows digest")

    work = value.get("projected_work")
    if not isinstance(work, Mapping):
        problems.append("selection projected work missing")
    else:
        total = sum(
            int(row["combo_count"]) for row in rows
            if isinstance(row, Mapping)
            and isinstance(row.get("combo_count"), int)
            and not isinstance(row.get("combo_count"), bool))
        expected_work = {
            "total_combos_per_common_world": total,
            "candidate_rollouts_at_1_world": total,
            "candidate_rollouts_at_5_worlds": 5 * total,
            "candidate_rollouts_at_30_worlds": 30 * total,
            "capacity_measurement_required_before_run": True,
        }
        if dict(work) != expected_work:
            problems.append("selection projected work")
    return sorted(set(problems))


def select_dev_states(
    rows: Iterable[Mapping[str, object]],
    *,
    shape_count: int = 32,
    anchor_count: int = 32,
    require_full_population: bool = True,
) -> dict:
    """Select diverse shape rows plus hash-uniform anchors, outcomes blind."""
    for value, label in ((shape_count, "shape_count"),
                         (anchor_count, "anchor_count")):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{label} must be a positive integer")
    materialized = [dict(row) for row in rows]
    problems = [
        problem for row in materialized for problem in state_problems(row)]
    if problems:
        raise PopulationRefused("; ".join(sorted(set(problems))))
    ordered = sorted(materialized, key=lambda row: row["state_id"])
    ids = [row.get("state_id") for row in ordered]
    seeds = [row.get("deal_seed") for row in ordered]
    if len(ids) != len(set(ids)) or len(seeds) != len(set(seeds)):
        problems.append("duplicate state or deal seed")
    if require_full_population:
        expected = list(range(DEAL_SEED0, DEAL_SEED0 + POPULATION_STATES))
        if sorted(seeds) != expected:
            problems.append("full population coverage")
        elif _source_manifest_digest(ordered) != SOURCE_STATE_MANIFEST_SHA256:
            problems.append("source population material")
    if len(ordered) < shape_count + anchor_count:
        problems.append("selection exceeds population")
    if problems:
        raise PopulationRefused("; ".join(sorted(set(problems))))

    ranked = {
        metric: sorted(
            range(len(ordered)),
            key=lambda index: (
                -_metric(ordered[index], metric),
                _tie(ordered[index], f"shape:{metric}")),
        )
        for metric in METRICS
    }
    pointers = {metric: 0 for metric in METRICS}
    selected: list[int] = []
    reasons: dict[int, str] = {}
    while len(selected) < shape_count:
        before = len(selected)
        for metric in METRICS:
            candidates = ranked[metric]
            while (pointers[metric] < len(candidates)
                   and candidates[pointers[metric]] in reasons):
                pointers[metric] += 1
            if pointers[metric] >= len(candidates):
                continue
            index = candidates[pointers[metric]]
            pointers[metric] += 1
            selected.append(index)
            reasons[index] = metric
            if len(selected) == shape_count:
                break
        if len(selected) == before:
            raise PopulationRefused("shape selection made no progress")

    remaining = [
        index for index in range(len(ordered)) if index not in reasons]
    anchors = sorted(
        remaining, key=lambda index: _tie(ordered[index], "uniform-anchor"),
    )[:anchor_count]
    selected_rows = [
        {
            "state_id": ordered[index]["state_id"],
            "source_state_id": ordered[index]["source_state_id"],
            "deal_seed": ordered[index]["deal_seed"],
            "selection_group": "shape_rich",
            "selection_reason": reasons[index],
            "combo_count": ordered[index]["combo_count"],
        }
        for index in selected
    ] + [
        {
            "state_id": ordered[index]["state_id"],
            "source_state_id": ordered[index]["source_state_id"],
            "deal_seed": ordered[index]["deal_seed"],
            "selection_group": "hash_uniform_anchor",
            "selection_reason": "uniform_anchor",
            "combo_count": ordered[index]["combo_count"],
        }
        for index in anchors
    ]
    total_combos = sum(int(row["combo_count"]) for row in selected_rows)
    result = {
        "schema": SELECTION_SCHEMA,
        "population": {
            "id": POPULATION_ID,
            "opened_reusable_dev": True,
            "source_git": SOURCE_GIT,
            "source_aggregate_sha256": SOURCE_AGGREGATE_SHA256,
            "source_state_manifest_sha256": SOURCE_STATE_MANIFEST_SHA256,
            "source_shard_sha256s": list(SOURCE_SHARD_SHA256S),
            "deal_seed0": DEAL_SEED0,
            "states": len(ordered),
        },
        "selection": {
            "shape_rich": shape_count,
            "hash_uniform_anchor": anchor_count,
            "total": len(selected_rows),
            "metrics": list(METRICS),
            "rows": selected_rows,
            "rows_sha256": stable_digest(selected_rows),
        },
        "projected_work": {
            "total_combos_per_common_world": total_combos,
            "candidate_rollouts_at_1_world": total_combos,
            "candidate_rollouts_at_5_worlds": 5 * total_combos,
            "candidate_rollouts_at_30_worlds": 30 * total_combos,
            "capacity_measurement_required_before_run": True,
        },
        "score_free": True,
        "source_population_already_opened": True,
        "source_outcomes_read": False,
        "exploration_only": True,
        "confirmatory_inference": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    final_problems = selection_problems(
        result, require_full_population=require_full_population)
    if final_problems:
        raise PopulationRefused("; ".join(final_problems))
    return result
