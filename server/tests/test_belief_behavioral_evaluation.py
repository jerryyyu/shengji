"""Exact C2 behavioral scoring and N1 collapse tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.rl import belief_capture as CAPTURE
from shengji.rl.belief_b2_protocol import b2_split_round_seeds
from shengji.rl.belief_behavioral import build_behavioral_signal_round
from shengji.rl.belief_behavioral_evaluation import (
    POOLED_STRATUM,
    BehavioralDecisionPredictionsV1,
    BeliefBehavioralEvaluationError,
    build_behavioral_round_score,
    evaluate_c2,
    validate_behavioral_round_score,
)
from shengji.rl.belief_evaluation import (
    reopen_score_pair,
    target_count_population,
)
from shengji.rl.belief_ownership import (
    PROBABILITY_SCALE,
    BeliefOwnershipV1,
    ReceiverCountProbabilityV1,
    receiver_sizes,
)
from shengji.rl.belief_refc_capture import (
    capture_champion_round_with_ref_c,
)


def _truth(actor, target):
    counts = target_count_population(actor, target)
    return BeliefOwnershipV1(
        actor_observation_sha256=actor.sha256(),
        model_schema="belief-v1-behavioral-test-model",
        model_sha256="a" * 64,
        behavior_policy_ids=("mc-s0-report-lcb",),
        receiver_sizes=receiver_sizes(actor),
        probabilities=tuple(ReceiverCountProbabilityV1(
            card=card, receiver=receiver,
            count_0_ppb=PROBABILITY_SCALE if count == 0 else 0,
            count_1_ppb=PROBABILITY_SCALE if count == 1 else 0,
            count_2_ppb=PROBABILITY_SCALE if count == 2 else 0,
        ) for (card, receiver), count in counts.items()))


@pytest.fixture(scope="module")
def behavioral_round():
    patch = pytest.MonkeyPatch()
    patch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    patch.setattr(
        CAPTURE, "make_bot", lambda _name, *, seed: HeuristicBot())
    seed = b2_split_round_seeds("test")[0]
    reference = capture_champion_round_with_ref_c(
        seed, replicate="test-primary")
    signals = build_behavioral_signal_round(reference.captured)
    predictions = []
    for pair, batch in zip(reference.captured.pairs, reference.batches,
                           strict=True):
        actor, target, _ = reopen_score_pair(pair)
        candidate = _truth(actor, target)
        history = replace(
            batch.ownership(), model_schema=candidate.model_schema,
            model_sha256=candidate.model_sha256)
        predictions.append(BehavioralDecisionPredictionsV1(
            candidate=candidate, history_ablated=history))
    result = build_behavioral_round_score(
        reference, signals, tuple(predictions))
    patch.undo()
    return result


def test_behavioral_round_scores_only_confirmed_receiver_cells(
        behavioral_round):
    validate_behavioral_round_score(behavioral_round)
    pooled = behavioral_round.strata[0]
    assert pooled.stratum == POOLED_STRATUM
    assert pooled.public_receiver_decision_count \
        >= pooled.confirmed_receiver_decision_count > 0
    assert pooled.probability_cell_count > 0
    assert pooled.candidate_brier_numerator == 0
    assert pooled.reference_brier_numerator > 0
    assert pooled.history_ablated_brier_numerator \
        == pooled.reference_brier_numerator
    assert behavioral_round.to_dict()["privileged_targets_consumed"] is True
    assert behavioral_round.to_dict()["runtime_artifact"] is False


def test_c2_requires_population_lift_and_history_collapse(behavioral_round):
    rounds = tuple(replace(behavioral_round, round_seed=seed)
                   for seed in b2_split_round_seeds("test"))
    result = evaluate_c2(rounds)
    pooled = result.strata[0]
    assert pooled.candidate_lift_supported is True
    assert pooled.history_ablation_collapsed is True
    assert result.pooled_behavioral_claim_passed is True
    assert all(result.to_dict()[key] is False
               for key in result.to_dict() if key.endswith("_authorized"))

    changed = replace(
        behavioral_round.strata[0],
        history_ablated_brier_numerator=
        behavioral_round.strata[0].candidate_brier_numerator)
    no_collapse_round = replace(
        behavioral_round,
        strata=(changed, *behavioral_round.strata[1:]))
    no_collapse = evaluate_c2(tuple(
        replace(no_collapse_round, round_seed=seed)
        for seed in b2_split_round_seeds("test")))
    assert no_collapse.strata[0].history_ablation_collapsed is False
    assert no_collapse.pooled_behavioral_claim_passed is False
    with pytest.raises(BeliefBehavioralEvaluationError,
                       match="population/order"):
        evaluate_c2(rounds[:-1])
