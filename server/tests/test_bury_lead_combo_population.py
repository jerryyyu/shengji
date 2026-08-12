"""Outcome-blind population contracts for bury/first-lead exploration."""
from __future__ import annotations

import copy
import random
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import bury_lead_combo_population as P  # noqa: E402


def _row(offset: int) -> dict:
    seed = P.DEAL_SEED0 + offset
    shape = {
        "groups_with_plain_void": offset % 6,
        "groups_with_structured_throw": (offset * 3) % 7,
        "groups_with_tractor": (offset * 5) % 8,
        "max_pair_run": 1 + offset % 4,
        "max_pair_units": 2 + offset % 5,
        "pair_unit_spread": offset % 3,
        "trump_count_spread": (offset * 2) % 4,
        "retained_point_spread": (offset * 5) % 25,
        "structured_throw_candidates": 3 + offset,
        "pair_lead_candidates": 5 + offset,
        "live_lead_candidates": 7 + offset,
    }
    return {
        "schema": P.SCHEMA,
        "population_id": P.POPULATION_ID,
        "state_id": f"{P.POPULATION_ID}:deal:{seed}:banker:{offset % 4}",
        "source_state_id":
            f"s3a-bury-pilot-v2:deal:{seed}:banker:{offset % 4}",
        "deal_seed": seed,
        "banker": offset % 4,
        "champion": P.CHAMPION,
        "source_input_sha256": f"{offset + 1:064x}",
        "source_replay_sha256": f"{offset + 51:064x}",
        "ballot_sha256": f"{offset + 101:064x}",
        "bury_count": 10 + offset,
        "generated_buries": 20 + offset,
        "combo_count": 100 + offset * 3,
        "combo_cap": 1088,
        "feasible_single_suit_voids": list("SHDC"[:1 + offset % 4]),
        "shape": shape,
        "score_free": True,
        "source_population_already_opened": True,
        "source_outcomes_read": False,
        "strength_claim": False,
        "production_deployment": False,
    }


def test_opened_population_identity_is_exact_and_not_report():
    assert P.POPULATION_ID == "s3a-bury-v2-opened-dev-136m-v1"
    assert P.POPULATION_STATES == 512
    assert len(P.SOURCE_SHARD_SHA256S) == 8
    assert P.SOURCE_AGGREGATE_SHA256 == \
        "74aa5a3947e1daaa5aa4bc33eef8ae04eaaf695d0cb900c7045eb0cbbc4396cd"
    assert P.SOURCE_STATE_MANIFEST_SHA256 == \
        "7313fc48a349a1fafad2e39d63c983a262ea4d858ce538a3c6697792327eaed7"


def test_real_state_census_is_deterministic_actor_visible_and_score_free():
    first = P.census_state(P.DEAL_SEED0)
    second = P.census_state(P.DEAL_SEED0)
    assert first == second
    assert P.state_problems(first) == []
    assert first["source_input_sha256"] == \
        "d6a7453dbc58ad2089c3002ade54c48f49605634d8751ee2d14f6c01b30b3b95"
    assert first["source_replay_sha256"] == \
        "36be06f4d73563071e4fb9f84b95e71930f1ff7f3c0f76ecaf5671ba67f9dbfd"
    assert first["bury_count"] == 32
    assert first["combo_count"] == 546
    assert first["combo_count"] <= first["combo_cap"]
    assert first["feasible_single_suit_voids"] == ["S", "H", "D", "C"]
    assert first["shape"]["groups_with_structured_throw"] > 0
    assert first["score_free"] is True
    assert first["source_population_already_opened"] is True
    assert first["source_outcomes_read"] is False
    assert not any(key in first for key in (
        "utility", "winner", "attacker_points", "level_delta"))


def test_census_refuses_seed_outside_the_opened_asset():
    with pytest.raises(P.PopulationRefused, match="outside"):
        P.census_state(P.DEAL_SEED0 - 1)
    with pytest.raises(P.PopulationRefused, match="outside"):
        P.census_state(P.DEAL_SEED0 + P.POPULATION_STATES)


def test_selection_is_order_invariant_diverse_and_work_explicit():
    rows = [_row(index) for index in range(24)]
    first = P.select_dev_states(
        rows, shape_count=8, anchor_count=8,
        require_full_population=False)
    shuffled = list(rows)
    random.Random(7).shuffle(shuffled)
    second = P.select_dev_states(
        shuffled, shape_count=8, anchor_count=8,
        require_full_population=False)
    assert first == second
    assert P.selection_problems(
        first, require_full_population=False) == []
    selected = first["selection"]["rows"]
    assert len(selected) == 16
    assert len({row["state_id"] for row in selected}) == 16
    assert sum(row["selection_group"] == "shape_rich"
               for row in selected) == 8
    assert sum(row["selection_group"] == "hash_uniform_anchor"
               for row in selected) == 8
    assert {row["selection_reason"] for row in selected[:8]} == set(P.METRICS)
    total = sum(row["combo_count"] for row in selected)
    assert first["projected_work"] == {
        "total_combos_per_common_world": total,
        "candidate_rollouts_at_1_world": total,
        "candidate_rollouts_at_5_worlds": 5 * total,
        "candidate_rollouts_at_30_worlds": 30 * total,
        "capacity_measurement_required_before_run": True,
    }
    assert first["score_free"] is True
    assert first["source_population_already_opened"] is True
    assert first["source_outcomes_read"] is False
    assert first["confirmatory_inference"] is False
    assert first["strength_claim"] is False


def test_selection_refuses_outcome_fields_duplicates_and_partial_full_asset():
    rows = [_row(index) for index in range(12)]
    contaminated = copy.deepcopy(rows)
    contaminated[0]["utility"] = 1.0
    with pytest.raises(P.PopulationRefused, match="field population"):
        P.select_dev_states(
            contaminated, shape_count=4, anchor_count=4,
            require_full_population=False)

    duplicate = copy.deepcopy(rows)
    duplicate[-1] = copy.deepcopy(duplicate[0])
    with pytest.raises(P.PopulationRefused, match="duplicate"):
        P.select_dev_states(
            duplicate, shape_count=4, anchor_count=4,
            require_full_population=False)

    with pytest.raises(P.PopulationRefused, match="full population"):
        P.select_dev_states(rows, shape_count=4, anchor_count=4)


def test_selection_refuses_bad_authority_or_impossible_caps():
    row = _row(0)
    row["strength_claim"] = True
    assert "authority boundary" in P.state_problems(row)
    row = _row(0)
    row["combo_count"] = row["combo_cap"] + 1
    assert "combo cap" in P.state_problems(row)


@pytest.mark.parametrize(("mutator", "problem"), [
    (lambda value: value["selection"].__setitem__("rows_sha256", "0" * 64),
     "selection rows digest"),
    (lambda value: value["selection"]["rows"][0].__setitem__(
        "combo_count", 0), "selection row combo count"),
    (lambda value: value.__setitem__("strength_claim", True),
     "selection authority boundary"),
    (lambda value: value["projected_work"].__setitem__(
        "candidate_rollouts_at_30_worlds", 1),
     "selection projected work"),
])
def test_selection_validator_rejects_self_describing_drift(mutator, problem):
    selection = P.select_dev_states(
        [_row(index) for index in range(16)], shape_count=4,
        anchor_count=4, require_full_population=False)
    mutator(selection)
    assert problem in P.selection_problems(
        selection, require_full_population=False)
