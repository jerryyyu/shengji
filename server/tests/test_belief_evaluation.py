"""Privileged offline proper-score boundary tests for BELIEF-V1."""

from __future__ import annotations

import random
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
from shengji.rl.belief_refc_capture import capture_ref_c_worlds


POLICIES = ("mc-s0-report-lcb",)


def _state(seed=10101):
    rnd = Game(random.Random(seed)).start_round()
    bot = HeuristicBot()
    transcript = PublicTranscriptV1()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = bot.decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
            accepted = rnd.declaration
            transcript = transcript.with_declaration(
                accepted["seat"], accepted["cards"], accepted["strength"])
    for seat in range(4):
        cards = bot.decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
            accepted = rnd.declaration
            transcript = transcript.with_declaration(
                accepted["seat"], accepted["cards"], accepted["strength"])
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
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
    return pair, actor, target, rnd, transcript


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


def test_truth_candidate_has_positive_exact_brier_and_log_loss_lift(
        monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    pair, actor, target, rnd, transcript = _state()
    reference_batch = capture_ref_c_worlds(
        rnd, rnd.turn, transcript, sampler_seed=1201)
    candidate = _truth_belief(
        actor, target, schema="history-ownership-v1-test", source="b" * 64)
    score = score_corpus_decision(pair, reference_batch, candidate)
    assert score.brier_improvement_numerator > 0
    assert score.log_loss_improvement_nanonats > 0
    assert score.candidate_brier_numerator == 0
    assert score.count_rows == len(reference_batch.ownership().probabilities)
    assert score.privileged_targets_consumed is True
    assert score.runtime_artifact is False
    assert len(score.canonical_bytes()) > 0


def test_empirical_reference_clone_cannot_bank_sampling_bias(monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    pair, _, _, rnd, transcript = _state(10103)
    reference_batch = capture_ref_c_worlds(
        rnd, rnd.turn, transcript, sampler_seed=1213)
    candidate = replace(
        reference_batch.ownership(), model_schema="history-ownership-v1-test",
        model_sha256="c" * 64)
    score = score_corpus_decision(pair, reference_batch, candidate)
    assert score.reference_raw_brier_numerator \
        == score.candidate_raw_brier_numerator
    assert score.reference_finite_sample_bias_numerator > 0
    assert score.reference_brier_numerator == (
        score.reference_raw_brier_numerator * 255
        - score.reference_finite_sample_bias_numerator)
    assert score.candidate_brier_numerator \
        == score.candidate_raw_brier_numerator * 255
    assert score.brier_improvement_numerator \
        == -score.reference_finite_sample_bias_numerator < 0
    assert score.log_loss_improvement_nanonats == 0


def test_target_population_includes_hidden_kitty_only_for_nonbanker_actor():
    _, actor, target, _, _ = _state(10105)
    counts = target_count_population(actor, target)
    assert (KITTY_RECEIVER in dict(receiver_sizes(actor))) \
        == any(receiver == KITTY_RECEIVER for _, receiver in counts)
    assert sum(counts.values()) == sum(size for _, size in receiver_sizes(actor))


def test_evaluator_refuses_target_policy_reference_and_score_drift(
        monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    pair, actor, target, rnd, transcript = _state(10107)
    reference_batch = capture_ref_c_worlds(
        rnd, rnd.turn, transcript, sampler_seed=1223)
    candidate = _truth_belief(
        actor, target, schema="history-ownership-v1-test", source="d" * 64)
    with pytest.raises(BeliefEvaluationError,
                       match="corpus pair reconstruction refused"):
        score_corpus_decision(
            replace(pair, target_bytes=pair.target_bytes + b" "),
            reference_batch, candidate)
    with pytest.raises(BeliefEvaluationError, match="batch validation"):
        score_corpus_decision(pair, replace(
            reference_batch, sampler_source_sha256="e" * 64), candidate)
    with pytest.raises(BeliefEvaluationError, match="behavior-policy"):
        score_corpus_decision(pair, reference_batch, replace(
            candidate, behavior_policy_ids=("wrong",)))

    score = score_corpus_decision(pair, reference_batch, candidate)
    with pytest.raises(BeliefEvaluationError, match="derivation drift"):
        validate_decision_score(
            pair, reference_batch, candidate,
            replace(score, candidate_brier_numerator=
                    score.candidate_brier_numerator + 1))


def test_evaluator_refuses_a_valid_ref_c_batch_for_another_actor(monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    pair, actor, target, _, _ = _state(10109)
    _, _, _, other_round, other_transcript = _state(10111)
    other_batch = capture_ref_c_worlds(
        other_round, other_round.turn, other_transcript, sampler_seed=1237)
    candidate = _truth_belief(
        actor, target, schema="history-ownership-v1-test", source="f" * 64)
    with pytest.raises(BeliefEvaluationError, match="actor binding"):
        score_corpus_decision(pair, other_batch, candidate)
