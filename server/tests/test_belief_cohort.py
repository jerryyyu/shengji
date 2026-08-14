"""Fixed eight-member BELIEF-V1 ensemble contract tests."""

from __future__ import annotations

import random
from dataclasses import replace

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.engine.round import actual_play_after
from shengji.rl.belief_cohort import (
    COHORT_SCHEMA,
    BeliefCohortError,
    ensemble_identity,
    ensemble_ownership,
)
from shengji.rl.belief_contract import PublicTranscriptV1, build_actor_observation
from shengji.rl.belief_model import new_from_scratch_model, predict_ownership
from shengji.rl.belief_ownership import validate_ownership


POLICIES = ("mc-s0-report-lcb",)


def _actor(seed=10501, plays=5):
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
    for _ in range(plays):
        seat = rnd.turn
        attempted = bot.decide_play(rnd, seat)
        previous_last = rnd.last_trick
        rnd.play(seat, attempted)
        transcript = transcript.with_play(
            seat, attempted, actual_play_after(rnd, seat, previous_last))
    return build_actor_observation(rnd, rnd.turn, transcript)


def _members(actor):
    prototype = predict_ownership(
        new_from_scratch_model(495023836), actor,
        behavior_policy_ids=POLICIES, model_sha256="1" * 64)
    return tuple(replace(prototype, model_sha256=f"{index + 1:064x}")
                 for index in range(8))


def test_identical_member_predictions_reproduce_exact_prediction():
    actor = _actor()
    members = _members(actor)
    ensemble = ensemble_ownership(actor, members)
    validate_ownership(actor, ensemble)
    assert ensemble.model_schema == COHORT_SCHEMA
    assert ensemble.model_sha256 == ensemble_identity(tuple(
        member.model_sha256 for member in members))
    assert ensemble.behavior_policy_ids == POLICIES
    assert ensemble.probabilities == members[0].probabilities


def test_member_order_is_load_bearing_even_when_predictions_match():
    actor = _actor(10503)
    members = _members(actor)
    first = ensemble_ownership(actor, members)
    second = ensemble_ownership(actor, tuple(reversed(members)))
    assert first.probabilities == second.probabilities
    assert first.model_sha256 != second.model_sha256


def test_cohort_refuses_missing_duplicate_policy_and_actor_drift():
    actor = _actor(10507)
    members = _members(actor)
    with pytest.raises(BeliefCohortError, match="population"):
        ensemble_ownership(actor, members[:-1])
    with pytest.raises(BeliefCohortError, match="identity population"):
        ensemble_ownership(actor, (members[0], members[0], *members[2:]))
    with pytest.raises(BeliefCohortError, match="behavior-policy"):
        ensemble_ownership(actor, (
            *members[:-1], replace(
                members[-1], behavior_policy_ids=("wrong",))))
    other = _actor(10509)
    with pytest.raises(BeliefCohortError, match="ownership refused"):
        ensemble_ownership(other, members)
