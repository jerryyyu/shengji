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
    # This is deliberately a DEV witness.  The old 861614 witness belonged to
    # REPORT, which contradicted the evaluator's documented authority boundary
    # even though the formal shard entry point rejected REPORT.
    return STATES._deal_rows(862_219)[0]


@pytest.fixture(scope="module")
def evaluated(witness) -> dict:
    # The production decisions still consume their exact 30+300-world dose;
    # only the separate exploration report is shortened for this unit test.
    return EVAL.evaluate_state(witness, report_worlds=2)


def test_named_witness_runs_both_complete_live_policies_at_equal_work(evaluated):
    assert evaluated["schema"] == EVAL.SCHEMA
    assert evaluated["state_id"] == "862219:0:2"
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


def test_report_row_is_unavailable_at_direct_evaluator_boundary():
    report_witness = STATES._deal_rows(861_614)[0]
    assert report_witness["split"] == "report"
    with pytest.raises(EVAL.EvalRefused, match="DEV/CALIB only"):
        EVAL.evaluate_state(report_witness, report_worlds=2)


def test_formal_shard_refuses_a_shortened_report_fold(tmp_path):
    with pytest.raises(EVAL.EvalRefused, match="must be 300"):
        EVAL.run_shard(
            population=tmp_path / "does-not-matter.json",
            split="dev", shard_index=0, shard_count=1,
            report_worlds=2, out=tmp_path / "out.json")


def test_named_seed_streams_are_stable_and_disjoint():
    state = "862219:0:2"
    root = EVAL.seed_for(state, "policy-root")
    report = EVAL.seed_for(state, "external-report")
    assert root == EVAL.seed_for(state, "policy-root")
    assert root != report
    assert root != EVAL.seed_for("862219:1:2", "policy-root")


def test_evaluation_runtime_does_not_reuse_score_free_capture_claim(
        monkeypatch):
    capture_runtime = {
        field: False for field in STATES.RUNTIME_FIELDS
    }
    capture_runtime.update({
        "git": "a" * 40,
        "tree_dirty": False,
        "host": "test-host",
        "python": "3.14.0",
        "fast_engine": True,
        "score_free": True,
        "outcomes_computed": False,
        "strength_claim": False,
        "production_authority": False,
    })
    monkeypatch.setattr(
        STATES, "_runtime", lambda *, smoke: dict(capture_runtime))
    runtime = EVAL.evaluation_runtime()
    assert set(runtime) == EVAL.RUNTIME_FIELDS
    assert runtime["score_free"] is False
    assert runtime["outcomes_computed"] is True
    assert runtime["diagnostic_only"] is True


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


def test_aggregate_recomputes_rehashed_external_utility(evaluated):
    bad = copy.deepcopy(evaluated)
    bad["external_report"]["actions"][0][
        "acting_level_utilities"][0] += 1.0
    bad["external_report"]["actions"][0][
        "mean_acting_level_utility"] += 0.5
    _rehash(bad)
    with pytest.raises(EVAL.EvalRefused, match="utility mapping"):
        AGG._validate_result(bad, split=bad["split"], report_worlds=2)


def test_aggregate_recomputes_rehashed_estimand(evaluated):
    bad = copy.deepcopy(evaluated)
    bad["estimands"]["retained_policy_minus_current"] += 1.0
    _rehash(bad)
    with pytest.raises(EVAL.EvalRefused, match="estimand reconstruction"):
        AGG._validate_result(bad, split=bad["split"], report_worlds=2)


def test_aggregate_recomputes_rehashed_work(evaluated):
    bad = copy.deepcopy(evaluated)
    bad["candidate_world_work"]["external_report"] += 1
    _rehash(bad)
    with pytest.raises(EVAL.EvalRefused, match="total work reconstruction"):
        AGG._validate_result(bad, split=bad["split"], report_worlds=2)


def test_aggregate_binds_report_evidence_to_recorded_play(evaluated):
    bad = copy.deepcopy(evaluated)
    record = bad["retained"]
    # Flip the pass/fallback side regardless of which side this witness
    # originally occupied.  A fixed negative statistic was a no-op whenever
    # the recorded decision had already fallen back to candidate zero.
    statistic = (-0.1 if record["played_index"]
                 == record["report_candidate_index"] else 0.1)
    record["report_fold"]["statistic"] = statistic
    bad["retained"]["report_fold"]["gap"] = (
        bad["retained"]["report_fold"]["critical"]
        * bad["retained"]["report_fold"]["se"] + statistic)
    _rehash(bad)
    with pytest.raises(EVAL.EvalRefused, match="report-fold decision"):
        AGG._validate_result(bad, split=bad["split"], report_worlds=2)


def test_aggregate_recomputes_best_inserted_pair(witness, evaluated):
    bad = copy.deepcopy(evaluated)
    inserted_indices = [
        index for index, cards in enumerate(witness["retained_ballot"])
        if EVAL.action_key(cards)
        in {EVAL.action_key(action)
            for action in witness["inserted_actions"]}
    ]
    wrong = next((index for index in inserted_indices
                  if index != bad["best_inserted_index"]), None)
    if wrong is None:
        wrong = next(index for index in range(len(witness["retained_ballot"]))
                     if index not in inserted_indices)
    bad["best_inserted_index"] = wrong
    bad["best_inserted_pair"] = sorted(witness["retained_ballot"][wrong])
    _rehash(bad)
    with pytest.raises(
            EVAL.EvalRefused,
            match="action binding|selector drift|inserted-pair binding"):
        AGG._validate_source_binding(bad, witness)


def test_aggregate_recomputes_selector_flags(witness, evaluated):
    bad = copy.deepcopy(evaluated)
    bad["current_raw_winner_was_evicted"] = not bad[
        "current_raw_winner_was_evicted"]
    _rehash(bad)
    with pytest.raises(EVAL.EvalRefused, match="selector telemetry"):
        AGG._validate_source_binding(bad, witness)
