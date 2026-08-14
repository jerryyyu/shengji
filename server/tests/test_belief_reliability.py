"""BELIEF-V1 count reliability and public-stratum tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.rl.belief_b2_protocol import (
    b2_split_round_seeds,
    champion_policy_seeds,
)
from shengji.rl.belief_capture import _capture_with_policies
from shengji.rl.belief_evaluation import reopen_score_pair, target_count_population
from shengji.rl.belief_ownership import (
    PROBABILITY_SCALE,
    BeliefOwnershipV1,
    ReceiverCountProbabilityV1,
    receiver_sizes,
)
from shengji.rl.belief_reliability import (
    BeliefReliabilityError,
    ReliabilityExampleV1,
    build_count_reliability_report,
)


POLICIES = ("mc-s0-report-lcb",)


def _examples(decisions=5):
    seed = b2_split_round_seeds("test")[0]
    captured = _capture_with_policies(
        seed, POLICIES[0], champion_policy_seeds(seed),
        [HeuristicBot() for _ in range(4)])
    result = []
    for pair in captured.pairs[:decisions]:
        actor, target, _ = reopen_score_pair(pair)
        counts = target_count_population(actor, target)
        prediction = BeliefOwnershipV1(
            actor_observation_sha256=actor.sha256(),
            model_schema="belief-v1-perfect-test-model",
            model_sha256="a" * 64,
            behavior_policy_ids=POLICIES,
            receiver_sizes=receiver_sizes(actor),
            probabilities=tuple(ReceiverCountProbabilityV1(
                card=card, receiver=receiver,
                count_0_ppb=PROBABILITY_SCALE if count == 0 else 0,
                count_1_ppb=PROBABILITY_SCALE if count == 1 else 0,
                count_2_ppb=PROBABILITY_SCALE if count == 2 else 0,
            ) for (card, receiver), count in counts.items()),
        )
        result.append(ReliabilityExampleV1(pair=pair, prediction=prediction))
    return tuple(result)


def test_perfect_predictions_have_zero_ece_brier_and_unit_slope():
    report = build_count_reliability_report(_examples())
    overall = report.strata[0]
    assert overall.name == "all"
    assert overall.ece_ppb == 0
    assert overall.brier_numerator == 0
    assert overall.reliability_slope_defined is True
    assert overall.reliability_slope_numerator == 1
    assert overall.reliability_slope_denominator == 1
    assert overall.probability_cell_count >= 1000
    assert overall.underpowered is False
    assert sum(row.probability_cell_count for row in overall.bins) \
        == overall.probability_cell_count
    assert {row.name.split(":")[0] for row in report.strata[1:]} \
        == {"declaration", "kitty", "phase", "role"}
    assert {row.metric.split(":")[0] for row in report.linear_expectations} \
        == {"pair-count", "point-card-count", "suit-length", "trump-length"}
    assert all(row.mean_signed_error_count_ppb == 0
               and row.mean_absolute_error_count_ppb == 0
               and row.squared_error_numerator == 0
               for row in report.linear_expectations)
    assert all(
        not row.reliability_slope_defined
        or (row.reliability_slope_numerator,
            row.reliability_slope_denominator) == (1, 1)
        for row in report.linear_expectations)
    payload = report.to_dict()
    assert payload["joint_posterior_claimed"] is False
    assert all(payload[key] is False for key in payload
               if key.endswith("_authorized"))


def test_reliability_refuses_target_model_and_duplicate_drift():
    examples = _examples(decisions=3)
    with pytest.raises(BeliefReliabilityError,
                       match="corpus pair reconstruction refused"):
        build_count_reliability_report((replace(
            examples[0], pair=replace(
                examples[0].pair,
                target_bytes=examples[0].pair.target_bytes + b" ")),
                                        *examples[1:]))
    with pytest.raises(BeliefReliabilityError, match="model/split"):
        build_count_reliability_report((examples[0], replace(
            examples[1], prediction=replace(
                examples[1].prediction, model_sha256="b" * 64)),
                                        *examples[2:]))
    with pytest.raises(BeliefReliabilityError, match="duplicate"):
        build_count_reliability_report((examples[0], examples[0]))
