from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from shengji.rl.world_afterstate import OUTCOME_CLASSES
from shengji.rl.world_afterstate_evaluation import (
    PROBABILITY_SCALE, EvaluationOutcomeV0, PredictionV0,
    WorldAfterstateEvaluationError, build_train_prior,
    evaluate_action_gate, evaluate_primary_gate, predict_batch)
from shengji.rl.world_afterstate_model import (
    CAPACITY_SHAPES, new_world_afterstate_model)
from shengji.rl.world_afterstate_training import (
    collate_training_examples, model_state_sha256)

from test_world_afterstate_training import _example


def _probability(category: int, mass: int = 900_000_000):
    values = [0] * OUTCOME_CLASSES
    values[category] = mass
    remaining = PROBABILITY_SCALE - mass
    for index in range(OUTCOME_CLASSES):
        if index != category:
            share = remaining // (OUTCOME_CLASSES - 1)
            values[index] = share
    values[next(index for index in range(OUTCOME_CLASSES)
                if index != category)] += PROBABILITY_SCALE - sum(values)
    return tuple(values)


def _outcome(*, fold: str, deal: int, group: int, candidate: int,
             replicate: int, category: int) -> EvaluationOutcomeV0:
    value = EvaluationOutcomeV0(
        deal_group_sha256=f"{deal:064x}", state_group_id=f"{group:064x}",
        source="production-policy", fold=fold, root_role="attacker",
        play_phase="middle", position="lead", trump_rank="7",
        trump_mode="H", points_bucket="40-79",
        candidate_index=candidate, protected_incumbent=candidate == 0,
        successor_sha256=f"{group * 10 + candidate:064x}",
        replicate=replicate, signed_level_category=category)
    value.validate()
    return value


def _predictions(outcomes, categories):
    result = []
    identities = sorted({(row.state_group_id, row.candidate_index,
                          row.successor_sha256) for row in outcomes})
    for group, candidate, successor in identities:
        category = categories[(group, candidate)]
        for member in range(8):
            result.append(PredictionV0(
                state_group_id=group, candidate_index=candidate,
                successor_sha256=successor, member_index=member,
                model_state_sha256=f"{member + 100:064x}",
                probabilities_ppb=_probability(category)))
    return result


def test_prediction_rows_are_exact_nonzero_and_do_not_mutate_member():
    model = new_world_afterstate_model(919, CAPACITY_SHAPES["small"])
    before = model_state_sha256(model)
    batch = collate_training_examples(
        ["report-0", "report-1"], [_example(0), _example(1)],
        split="report")
    groups = [f"{801 + index:064x}" for index in range(2)]
    rows = predict_batch(
        model, batch, member_index=3, state_group_ids=groups,
        candidate_indexes=[0, 1])
    assert model_state_sha256(model) == before
    assert model.training is True
    assert [row.state_group_id for row in rows] == groups
    assert all(sum(row.probabilities_ppb) == PROBABILITY_SCALE
               and min(row.probabilities_ppb) >= 1 for row in rows)

    with pytest.raises(WorldAfterstateEvaluationError,
                       match="identity population drift"):
        predict_batch(
            model, batch, member_index=3, state_group_ids=groups[:1],
            candidate_indexes=[0, 1])


def test_primary_scores_raw_outcomes_and_requires_six_members():
    train = [_outcome(fold="train", deal=index + 1, group=index + 1,
                      candidate=0, replicate=0, category=100)
             for index in range(8)]
    prior = build_train_prior(train)
    report = [_outcome(fold="report", deal=index + 100,
                       group=index + 100, candidate=0, replicate=0,
                       category=140) for index in range(12)]
    predictions = _predictions(
        report, {(row.state_group_id, 0): 140 for row in report})
    result = evaluate_primary_gate(
        report, predictions, prior, bootstrap_replicates=200)
    assert result["passed"] is True
    assert result["bootstrap_lower_nanonats"] > 0
    assert result["positive_member_count"] == 8

    forged = predictions[:-1]
    with pytest.raises(WorldAfterstateEvaluationError,
                       match="prediction binding drift"):
        evaluate_primary_gate(
            report, forged, prior, bootstrap_replicates=200)


def test_prior_refuses_held_out_and_duplicate_rows():
    row = _outcome(fold="train", deal=1, group=1, candidate=0,
                   replicate=0, category=100)
    with pytest.raises(WorldAfterstateEvaluationError, match="split drift"):
        build_train_prior([copy.copy(row).__class__(
            **{**row.__dict__, "fold": "report"})])
    with pytest.raises(WorldAfterstateEvaluationError, match="duplicate"):
        build_train_prior([row, row])


def test_action_gate_compares_low_work_to_disjoint_truth_replicates():
    outcomes = []
    # Low-work samples choose candidate zero, while disjoint truth and model
    # identify candidate one.  The model therefore improves both metrics and
    # never demotes a truly better protected incumbent.
    for group in range(20, 32):
        for candidate in (0, 1):
            for replicate in range(8):
                category = 100 if candidate == 0 else (
                    80 if replicate < 4 else 140)
                outcomes.append(_outcome(
                    fold="provider-audit", deal=group, group=group,
                    candidate=candidate, replicate=replicate,
                    category=category))
    categories = {}
    for row in outcomes:
        categories[(row.state_group_id, row.candidate_index)] = (
            100 if row.candidate_index == 0 else 140)
    result = evaluate_action_gate(
        outcomes, _predictions(outcomes, categories),
        bootstrap_replicates=200)
    assert result["passed"] is True
    assert result["expected_utility_error_improvement_ppm"][
        "bootstrap_lower"] > 0
    assert result["simple_regret_improvement_ppm"]["bootstrap_lower"] > 0

    with pytest.raises(WorldAfterstateEvaluationError,
                       match="replicate population drift"):
        evaluate_action_gate(
            outcomes[:-1], _predictions(outcomes, categories),
            bootstrap_replicates=200)

    cross_deal = [
        replace(row, deal_group_sha256="f" * 64)
        if row.candidate_index == 1 else row
        for row in outcomes
    ]
    with pytest.raises(WorldAfterstateEvaluationError,
                       match="cross-candidate binding drift"):
        evaluate_action_gate(
            cross_deal, _predictions(cross_deal, categories),
            bootstrap_replicates=200)
