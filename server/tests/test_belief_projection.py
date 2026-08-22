"""Exact deterministic ownership-weight projection tests."""

from __future__ import annotations

import copy
import random
from dataclasses import replace

import pytest

import shengji.rl.belief_projection as PROJECTION
from shengji.ai.heuristic import HeuristicBot
from shengji.engine.cards import Ordering
from shengji.engine.game import Game
from shengji.engine.round import actual_play_after
from shengji.rl.belief_contract import (
    DeclarationEligibilityV1,
    PublicTranscriptV1,
    build_actor_observation,
    build_belief_targets,
)
from shengji.rl.belief_ownership import (KITTY_RECEIVER, PROBABILITY_SCALE,
                                         validate_ownership)
from shengji.rl.belief_projection import (
    BeliefProjectionError,
    RawCountWeightV1,
    project_count_weights,
    uniform_raw_count_weights,
)


POLICIES = ("mc-s0-report-lcb",)


def _state(seed=9981, plays=5):
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
    return (rnd, build_actor_observation(rnd, rnd.turn, transcript),
            build_belief_targets(rnd, rnd.turn), transcript)


def _state_with_no_hidden_cards(seed=9927):
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
    while rnd.phase == "play":
        actor = build_actor_observation(rnd, rnd.turn, transcript)
        if not actor.deductions.unseen:
            return actor
        seat = rnd.turn
        attempted = bot.decide_play(rnd, seat)
        previous_last = rnd.last_trick
        rnd.play(seat, attempted)
        transcript = transcript.with_play(
            seat, attempted, actual_play_after(rnd, seat, previous_last))
    raise AssertionError("natural round had no zero-hidden-card decision")


def _project(actor, weights):
    return project_count_weights(
        actor,
        behavior_policy_ids=POLICIES,
        model_schema="history-ownership-v1-test",
        model_sha256="d" * 64,
        raw_weights=weights,
    )


def test_uniform_projection_is_exact_conserved_and_deterministic():
    _, actor, _, _ = _state()
    weights = uniform_raw_count_weights(
        actor, behavior_policy_ids=POLICIES)
    first = _project(actor, weights)
    second = _project(actor, weights)
    validate_ownership(actor, first)
    assert first.canonical_bytes() == second.canonical_bytes()
    assert all(sum((row.count_0_ppb, row.count_1_ppb,
                    row.count_2_ppb)) == PROBABILITY_SCALE
               for row in first.probabilities)
    assert first.actor_observation_sha256 == actor.sha256()


def test_natural_endgame_with_no_hidden_cards_projects_empty_belief():
    actor = _state_with_no_hidden_cards()
    weights = uniform_raw_count_weights(
        actor, behavior_policy_ids=POLICIES)
    assert weights == ()
    belief = _project(actor, weights)
    validate_ownership(actor, belief)
    assert belief.probabilities == ()


def test_positive_random_weights_project_across_roles_and_round_phases():
    rng = random.Random(1201)
    for seed, plays in ((9983, 0), (9985, 7), (9987, 24)):
        _, actor, _, _ = _state(seed, plays=plays)
        uniform = uniform_raw_count_weights(
            actor, behavior_policy_ids=POLICIES)
        weighted = tuple(replace(
            row,
            count_weights=tuple(
                0 if weight == 0 else rng.randrange(1, 1_000_000)
                for weight in row.count_weights),
        ) for row in uniform)
        validate_ownership(actor, _project(actor, weighted))


def test_near_boundary_projection_uses_exact_transport_repair(monkeypatch):
    _, actor, _, _ = _state(9970, plays=60)
    exponents = (
        (4, 5, 4), (3, 7, 9), (7, 8, 10), (9, 1, 11),
        (5, 11, 0), (8, 3, 0), (0, 11, 0), (2, 9, 0),
        (1, 7, 0), (12, 0, 0), (0, 7, 0), (11, 7, 0),
        (5, 7, 0), (6, 0, 0), (1, 2, 0), (2, 9, 0),
        (9, 9, 0), (10, 0, 0), (3, 4, 0), (3, 11, 0),
        (0, 8, 10), (6, 8, 12), (7, 5, 1), (1, 8, 12),
        (7, 12, 0), (11, 5, 1), (2, 2, 0), (6, 3, 4),
        (12, 0, 0), (7, 1, 0), (10, 5, 0), (12, 12, 0),
        (6, 8, 0), (0, 6, 0), (5, 4, 0), (12, 12, 0),
        (12, 12, 0), (12, 2, 0), (1, 11, 0), (11, 10, 0),
        (11, 7, 0), (0, 0, 0), (6, 9, 0), (12, 2, 0),
        (12, 10, 9), (5, 9, 4), (3, 4, 1), (11, 10, 12),
        (9, 8, 0), (1, 6, 0), (6, 12, 0), (12, 2, 0),
        (8, 8, 0), (2, 2, 0), (8, 6, 0), (3, 12, 0),
        (9, 4, 10), (9, 4, 4), (4, 11, 12), (2, 0, 7),
        (7, 0, 0), (9, 0, 0), (2, 0, 0), (5, 5, 0),
        (3, 0, 0), (7, 0, 0), (9, 0, 0), (1, 1, 0),
        (1, 9, 0), (7, 8, 0), (5, 8, 0), (5, 12, 0),
        (9, 12, 0), (4, 3, 0), (2, 1, 0), (0, 11, 0),
        (3, 11, 0), (4, 0, 0), (11, 0, 0), (0, 4, 0),
        (1, 9, 0), (6, 0, 0), (10, 3, 0), (3, 6, 0),
        (9, 12, 0), (8, 0, 0), (7, 7, 0), (0, 9, 0),
        (1, 4, 0), (8, 0, 0), (4, 7, 0), (0, 12, 0),
        (5, 3, 0), (8, 0, 0), (8, 6, 0), (6, 4, 0),
    )
    uniform = uniform_raw_count_weights(
        actor, behavior_policy_ids=POLICIES)
    assert len(uniform) == len(exponents)
    weighted = tuple(replace(
        row, count_weights=tuple(
            10 ** exponent if allowed else 0
            for exponent, allowed in zip(
                powers, row.count_weights, strict=True)))
        for row, powers in zip(uniform, exponents, strict=True))
    monkeypatch.setattr(PROJECTION, "PROJECTION_APPROXIMATE_MARGIN_LIMIT", 0)
    with pytest.raises(BeliefProjectionError, match="did not converge"):
        _project(actor, weighted)
    monkeypatch.setattr(
        PROJECTION, "PROJECTION_APPROXIMATE_MARGIN_LIMIT", 1e-3)
    monkeypatch.setattr(PROJECTION, "PROJECTION_APPROXIMATE_GROUP_LIMIT", 0)
    with pytest.raises(BeliefProjectionError, match="did not converge"):
        _project(actor, weighted)
    monkeypatch.setattr(
        PROJECTION, "PROJECTION_APPROXIMATE_GROUP_LIMIT", 1e-8)
    belief = _project(actor, weighted)
    validate_ownership(actor, belief)
    assert belief.sha256() \
        == "d39eedcc69d49217dedeef49fe01c4fd13961c4fcb6137b1da5fe88c520f3d08"


def test_approximate_transport_refuses_nonlocal_residual(monkeypatch):
    _, actor, _, _ = _state(9971, plays=12)
    weights = uniform_raw_count_weights(
        actor, behavior_policy_ids=POLICIES)
    monkeypatch.setattr(PROJECTION, "PROJECTION_MAX_ITERATIONS", 1)
    with pytest.raises(BeliefProjectionError, match="did not converge"):
        _project(actor, weights)


def test_projection_respects_forged_hard_void_and_declaration_witnesses():
    # This fixed state leaves one effective suit absent from relative seat 1,
    # giving the test a feasible, non-vacuous forged-void witness as well as a
    # declaration witness.
    _, actor, target, _ = _state(10011)
    ordering = Ordering(actor.trump_suit, actor.trump_rank)
    first_hand = dict(target.other_hands[0].cards)
    pinned_card, copies = next(iter(first_hand.items()))
    pinned_actor = replace(actor, deductions=replace(
        actor.deductions,
        declaration_pins=((pinned_card, 1, copies),),
    ))
    belief = _project(pinned_actor, uniform_raw_count_weights(
        pinned_actor, behavior_policy_ids=POLICIES))
    owner = next(row for row in belief.probabilities
                 if row.card == pinned_card
                 and row.receiver == "seat-relative-1")
    assert owner.count_0_ppb == 0
    if copies == 2:
        assert owner.count_2_ppb == PROBABILITY_SCALE
    else:
        assert all(row.count_2_ppb == 0
                   for row in belief.probabilities
                   if row.card == pinned_card
                   and row.receiver != "seat-relative-1")

    held_suits = {ordering.eff_suit(card) for card in first_hand}
    void_suit = next(
        suit for suit in {ordering.eff_suit(card)
                          for card, _ in actor.deductions.unseen}
        if suit not in held_suits)
    voids = list(actor.deductions.voids_by_relative)
    voids[1] = tuple(sorted({*voids[1], void_suit}))
    void_actor = replace(actor, deductions=replace(
        actor.deductions, voids_by_relative=tuple(voids)))
    belief = _project(void_actor, uniform_raw_count_weights(
        void_actor, behavior_policy_ids=POLICIES))
    assert all(row.count_0_ppb == PROBABILITY_SCALE
               for row in belief.probabilities
               if row.receiver == "seat-relative-1"
               and ordering.eff_suit(row.card) == void_suit)


def test_projection_enforces_banker_hand_or_hidden_kitty_group():
    _, actor, _, _ = _state(10013)
    assert actor.hidden_burial_size == 8
    card = next(card for card, count in actor.deductions.unseen if count == 2)
    group = (
        f"seat-relative-{actor.banker_relative}",
        KITTY_RECEIVER,
    )
    constrained = replace(actor, deductions=replace(
        actor.deductions,
        declaration_pins=(),
        declaration_eligibility=(DeclarationEligibilityV1(
            card=card, eligible_receivers=group, minimum_copies=1),),
    ))
    belief = _project(constrained, uniform_raw_count_weights(
        constrained, behavior_policy_ids=POLICIES))
    validate_ownership(constrained, belief)
    expected_in_group = sum(
        row.expected_count_ppb for row in belief.probabilities
        if row.card == card and row.receiver in group
    )
    assert expected_in_group >= PROBABILITY_SCALE
    assert all(
        row.count_2_ppb == 0 for row in belief.probabilities
        if row.card == card and row.receiver not in group
    )


def test_public_hidden_twins_project_to_identical_bytes():
    rnd, actor, _, transcript = _state(9991)
    changed = copy.deepcopy(rnd)
    hidden = [seat for seat in range(4) if seat != rnd.turn]
    left, right = next(
        (left, right) for index, left in enumerate(hidden)
        for right in hidden[index + 1:]
        if len(changed.hands[left]) == len(changed.hands[right]))
    changed.hands[left], changed.hands[right] = (
        changed.hands[right], changed.hands[left])
    changed_actor = build_actor_observation(changed, rnd.turn, transcript)
    assert changed_actor.canonical_bytes() == actor.canonical_bytes()
    weights = uniform_raw_count_weights(
        actor, behavior_policy_ids=POLICIES)
    assert _project(actor, weights).canonical_bytes() \
        == _project(changed_actor, weights).canonical_bytes()


def test_projection_refuses_missing_bad_bound_and_identity_weights():
    _, actor, _, _ = _state(9997)
    weights = uniform_raw_count_weights(
        actor, behavior_policy_ids=POLICIES)
    with pytest.raises(BeliefProjectionError, match="population/order"):
        _project(actor, weights[:-1])
    row = next(row for row in weights if 0 in row.count_weights)
    index = weights.index(row)
    values = list(row.count_weights)
    values[values.index(0)] = 1
    changed = (*weights[:index], replace(
        row, count_weights=tuple(values)), *weights[index + 1:])
    with pytest.raises(BeliefProjectionError, match="hard count bounds"):
        _project(actor, changed)
    allowed_row = next(
        row for row in weights if sum(weight > 0 for weight in row.count_weights)
        > 1)
    index = weights.index(allowed_row)
    values = list(allowed_row.count_weights)
    values[next(position for position, value in enumerate(values) if value)] = 0
    zero_allowed = (*weights[:index], replace(
        allowed_row, count_weights=tuple(values)), *weights[index + 1:])
    with pytest.raises(BeliefProjectionError, match="hard count bounds"):
        _project(actor, zero_allowed)
    with pytest.raises(BeliefProjectionError, match="model identity"):
        project_count_weights(
            actor, behavior_policy_ids=POLICIES,
            model_schema="history-ownership-v1-test",
            model_sha256="not-a-sha", raw_weights=weights)
    bool_values = replace(weights[0], count_weights=(True, 0, 0))
    with pytest.raises(BeliefProjectionError, match="malformed|hard"):
        _project(actor, (bool_values, *weights[1:]))
