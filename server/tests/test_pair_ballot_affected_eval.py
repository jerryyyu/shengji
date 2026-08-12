from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import pair_ballot_affected_eval as EVAL  # noqa: E402
import pair_ballot_affected_aggregate as AGG  # noqa: E402
import pair_ballot_affected_states as STATES  # noqa: E402


@pytest.fixture(scope="module")
def witness() -> dict:
    return STATES._deal_rows(861_614)[0]


@pytest.fixture(scope="module")
def evaluated(witness) -> dict:
    # The production decisions still consume their exact 30+300-world dose;
    # only the separate exploration report is shortened for this unit test.
    return EVAL.evaluate_state(witness, report_worlds=2)


def test_named_witness_runs_both_complete_live_policies_at_equal_work(evaluated):
    assert evaluated["schema"] == EVAL.SCHEMA
    assert evaluated["state_id"] == "861614:0:1"
    assert evaluated["current"]["work"]["complete"] is True
    assert evaluated["retained"]["work"]["complete"] is True
    assert evaluated["candidate_world_work"] == {
        "current_policy": 1_020,
        "retained_policy": 1_020,
        "external_report": 6,
    }
    assert evaluated["policy_action_changed"] is True
    assert evaluated["retained_raw_winner_is_inserted"] is False
    assert evaluated["current_raw_winner_was_evicted"] is True


def test_external_report_separates_policy_use_from_source_headroom(evaluated):
    estimands = evaluated["estimands"]
    assert set(estimands) == {
        "retained_policy_minus_current",
        "best_inserted_pair_minus_current",
    }
    assert all(isinstance(value, float) and math_is_finite(value)
               for value in estimands.values())
    report = evaluated["external_report"]
    assert report["worlds"] == 2
    assert report["sampler"]["accepted"] == 2
    assert {row["label"] for row in report["actions"]} == {
        "current_policy", "retained_policy", "best_inserted_pair",
    }


def math_is_finite(value: float) -> bool:
    return value == value and abs(value) != float("inf")


def _rehash(row: dict) -> None:
    body = dict(row)
    body.pop("result_sha256", None)
    row["result_sha256"] = STATES.sha256_bytes(STATES.canonical_json(body))


def test_evaluation_is_deterministic_for_the_same_frozen_state(witness, evaluated):
    again = EVAL.evaluate_state(witness, report_worlds=2)
    assert again == evaluated


def test_ballot_drift_refuses_before_scored_policy_work(witness):
    rnd = STATES.replay_state(witness)
    bad = copy.deepcopy(witness["current_ballot"])
    bad.pop()
    with pytest.raises(EVAL.EvalRefused, match="ballot drift"):
        EVAL.run_policy(
            rnd, witness["seat"], retained=False, seed=1,
            expected_ballot=bad)


def test_search_unreachable_row_refuses(witness):
    bad = copy.deepcopy(witness)
    bad["search_eligible"] = False
    body = dict(bad)
    body.pop("state_sha256")
    bad["state_sha256"] = STATES.sha256_bytes(STATES.canonical_json(body))
    with pytest.raises(EVAL.EvalRefused, match="not search-reachable"):
        EVAL.evaluate_state(bad, report_worlds=2)


def test_report_split_is_unavailable_in_exploration_controller(tmp_path):
    with pytest.raises(EVAL.EvalRefused, match="DEV/CALIB only"):
        EVAL.run_shard(
            population=tmp_path / "does-not-matter.json",
            split="report", shard_index=0, shard_count=1,
            out=tmp_path / "out.json")


def test_formal_shard_refuses_a_shortened_report_fold(tmp_path):
    with pytest.raises(EVAL.EvalRefused, match="must be 300"):
        EVAL.run_shard(
            population=tmp_path / "does-not-matter.json",
            split="dev", shard_index=0, shard_count=1,
            report_worlds=2, out=tmp_path / "out.json")


def test_named_seed_streams_are_stable_and_disjoint():
    state = "861614:0:1"
    root = EVAL.seed_for(state, "policy-root")
    report = EVAL.seed_for(state, "external-report")
    assert root == EVAL.seed_for(state, "policy-root")
    assert root != report
    assert root != EVAL.seed_for("861614:1:1", "policy-root")


def test_aggregate_validator_refuses_rehashed_extra_result_fields(evaluated):
    bad = copy.deepcopy(evaluated)
    bad["winner_team"] = 0
    _rehash(bad)
    with pytest.raises(EVAL.EvalRefused, match="field population"):
        AGG._validate_result(bad, split=bad["split"], report_worlds=2)


def test_aggregate_binds_cluster_and_band_to_source(witness, evaluated):
    bad = copy.deepcopy(evaluated)
    bad["deal_seed"] += 1
    _rehash(bad)
    AGG._validate_result(bad, split=bad["split"], report_worlds=2)
    with pytest.raises(EVAL.EvalRefused, match="state binding"):
        AGG._validate_source_binding(bad, witness)
