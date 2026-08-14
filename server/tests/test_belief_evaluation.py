"""Privileged offline proper-score boundary tests for BELIEF-V1."""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import replace

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.engine.round import actual_play_after
from shengji.rl.belief_contract import (
    PublicTranscriptV1,
    build_actor_observation,
    build_belief_targets,
)
from shengji.rl.belief_evaluation import (
    BeliefEvaluationError,
    score_corpus_decision,
    target_count_population,
    validate_decision_score,
)
from shengji.rl.belief_corpus import capture_corpus_pair
from shengji.rl.belief_ownership import (
    KITTY_RECEIVER,
    PROBABILITY_SCALE,
    BeliefOwnershipV1,
    ReceiverCountProbabilityV1,
    receiver_sizes,
)
from shengji.rl.belief_reference import REF_C_MODEL_SCHEMA


POLICIES = ("mc-s0-report-lcb",)


def _state(seed=10101):
    rnd = Game(random.Random(seed)).start_round()
    bot = HeuristicBot()
    while rnd.phase == "deal":
        rnd.deal_next()
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
    transcript = PublicTranscriptV1()
    seat = rnd.turn
    attempted = bot.decide_play(rnd, seat)
    previous_last = rnd.last_trick
    rnd.play(seat, attempted)
    transcript = transcript.with_play(
        seat, attempted, actual_play_after(rnd, seat, previous_last))
    actor = build_actor_observation(rnd, rnd.turn, transcript)
    target = build_belief_targets(rnd, rnd.turn)
    pair = capture_corpus_pair(
        rnd, rnd.turn, round_seed=seed, decision_index=1,
        transcript=transcript)
    return pair, actor, target


def _truth_belief(actor, target, *, schema, source):
    counts = target_count_population(actor, target)
    rows = tuple(ReceiverCountProbabilityV1(
        card=card, receiver=receiver,
        count_0_ppb=PROBABILITY_SCALE if count == 0 else 0,
        count_1_ppb=PROBABILITY_SCALE if count == 1 else 0,
        count_2_ppb=PROBABILITY_SCALE if count == 2 else 0,
    ) for (card, receiver), count in counts.items())
    return BeliefOwnershipV1(
        actor_observation_sha256=actor.sha256(),
        model_schema=schema,
        model_sha256=source,
        behavior_policy_ids=POLICIES,
        receiver_sizes=receiver_sizes(actor),
        probabilities=rows,
    )


def _two_world_mixture(actor, target):
    truth = target_count_population(actor, target)
    changed = dict(truth)
    first_card = next(card for card, copies in actor.deductions.unseen
                      if copies == 1)
    owner = next(receiver for receiver, _ in receiver_sizes(actor)
                 if truth[(first_card, receiver)] == 1)
    other = next(receiver for receiver, _ in receiver_sizes(actor)
                 if receiver != owner)
    exchange = next(
        card for card, copies in actor.deductions.unseen
        if copies == 1 and truth[(card, owner)] == 0
        and truth[(card, other)] == 1)
    changed[(first_card, owner)] = 0
    changed[(first_card, other)] = 1
    changed[(exchange, owner)] = 1
    changed[(exchange, other)] = 0
    rows = []
    for key, count in truth.items():
        histogram = Counter((count, changed[key]))
        rows.append(ReceiverCountProbabilityV1(
            card=key[0], receiver=key[1],
            count_0_ppb=histogram[0] * (PROBABILITY_SCALE // 2),
            count_1_ppb=histogram[1] * (PROBABILITY_SCALE // 2),
            count_2_ppb=histogram[2] * (PROBABILITY_SCALE // 2),
        ))
    return BeliefOwnershipV1(
        actor_observation_sha256=actor.sha256(),
        model_schema=REF_C_MODEL_SCHEMA,
        model_sha256="a" * 64,
        behavior_policy_ids=POLICIES,
        receiver_sizes=receiver_sizes(actor),
        probabilities=tuple(rows),
    )


def test_truth_candidate_has_positive_exact_brier_and_log_loss_lift():
    pair, actor, target = _state()
    reference = _two_world_mixture(actor, target)
    candidate = _truth_belief(
        actor, target, schema="history-ownership-v1-test", source="b" * 64)
    score = score_corpus_decision(pair, reference, candidate)
    assert score.brier_improvement_numerator > 0
    assert score.log_loss_improvement_nanonats > 0
    assert score.candidate_brier_numerator == 0
    assert score.count_rows == len(reference.probabilities)
    assert score.privileged_targets_consumed is True
    assert score.runtime_artifact is False
    assert len(score.canonical_bytes()) > 0


def test_equal_predictions_score_exactly_equal():
    pair, actor, target = _state(10103)
    reference = _two_world_mixture(actor, target)
    candidate = replace(
        reference, model_schema="history-ownership-v1-test",
        model_sha256="c" * 64)
    score = score_corpus_decision(pair, reference, candidate)
    assert score.brier_improvement_numerator == 0
    assert score.log_loss_improvement_nanonats == 0


def test_target_population_includes_hidden_kitty_only_for_nonbanker_actor():
    _, actor, target = _state(10105)
    counts = target_count_population(actor, target)
    assert (KITTY_RECEIVER in dict(receiver_sizes(actor))) \
        == any(receiver == KITTY_RECEIVER for _, receiver in counts)
    assert sum(counts.values()) == sum(size for _, size in receiver_sizes(actor))


def test_evaluator_refuses_target_policy_reference_and_score_drift():
    pair, actor, target = _state(10107)
    reference = _two_world_mixture(actor, target)
    candidate = _truth_belief(
        actor, target, schema="history-ownership-v1-test", source="d" * 64)
    with pytest.raises(BeliefEvaluationError,
                       match="corpus pair reconstruction refused"):
        score_corpus_decision(
            replace(pair, target_bytes=pair.target_bytes + b" "),
            reference, candidate)
    with pytest.raises(BeliefEvaluationError, match="exact REF-C"):
        score_corpus_decision(pair, replace(
            reference, model_schema="forged-reference"), candidate)
    with pytest.raises(BeliefEvaluationError, match="behavior-policy"):
        score_corpus_decision(pair, reference, replace(
            candidate, behavior_policy_ids=("wrong",)))

    score = score_corpus_decision(pair, reference, candidate)
    with pytest.raises(BeliefEvaluationError, match="derivation drift"):
        validate_decision_score(
            pair, reference, candidate,
            replace(score, candidate_brier_numerator=
                    score.candidate_brier_numerator + 1))
