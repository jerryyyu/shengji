"""Target isolation and exact feature tests for HistoryOwnershipV1 input."""

from __future__ import annotations

import copy
import random
from collections import Counter
from dataclasses import replace

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.point_context import build_point_context
from shengji.engine.cards import Ordering
from shengji.engine.game import Game
from shengji.engine.round import actual_play_after
from shengji.rl.belief_contract import (
    PublicTranscriptV1,
    build_actor_observation,
    build_belief_targets,
)
from shengji.rl.belief_input import (
    CARD_CODES,
    BeliefInputError,
    build_history_ownership_input,
    validate_history_ownership_input,
)


POLICIES = ("mc-s0-report-lcb",)


def _state(seed=9811, plays=7):
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
    actor = build_actor_observation(rnd, rnd.turn, transcript)
    target = build_belief_targets(rnd, rnd.turn)
    return rnd, actor, target, transcript


def _swap_equal_hidden_hands(rnd):
    changed = copy.deepcopy(rnd)
    actor_seat = rnd.turn
    hidden = [seat for seat in range(4) if seat != actor_seat]
    left, right = next(
        (left, right) for index, left in enumerate(hidden)
        for right in hidden[index + 1:]
        if len(changed.hands[left]) == len(changed.hands[right]))
    changed.hands[left], changed.hands[right] = (
        changed.hands[right], changed.hands[left])
    return changed


def test_input_is_fixed_order_target_blind_and_point_context_exact():
    rnd, actor, target, _ = _state()
    feature = build_history_ownership_input(
        actor, behavior_policy_ids=POLICIES)
    validate_history_ownership_input(actor, feature)
    assert [row.card for row in feature.card_facts] == list(CARD_CODES)
    assert [row.card_index for row in feature.card_facts] \
        == list(range(len(CARD_CODES)))
    assert feature.privileged_targets_consumed is False
    raw = feature.canonical_bytes()
    assert b'"target"' not in raw
    assert target.sha256().encode() not in raw

    point_context = build_point_context(rnd, rnd.turn).to_dict()
    payload = feature.to_dict()["point_context"]
    assert payload["trick_points"] == point_context["trick_points"]
    assert payload["points_left_total"] == point_context["points_left_total"]
    assert payload["points_left_by_suit"] \
        == point_context["points_left_by_suit"]
    assert payload["bracket_distance"] == point_context["bracket_distance"]


def test_hidden_world_twins_produce_identical_model_inputs():
    rnd, actor, target, transcript = _state(9817)
    changed = _swap_equal_hidden_hands(rnd)
    changed_actor = build_actor_observation(changed, rnd.turn, transcript)
    changed_target = build_belief_targets(changed, rnd.turn)
    assert changed_actor.canonical_bytes() == actor.canonical_bytes()
    assert changed_target.canonical_bytes() != target.canonical_bytes()
    first = build_history_ownership_input(
        actor, behavior_policy_ids=POLICIES)
    second = build_history_ownership_input(
        changed_actor, behavior_policy_ids=POLICIES)
    assert first.canonical_bytes() == second.canonical_bytes()


def test_events_preserve_declarations_play_order_and_attempted_actual_fields():
    _, actor, _, _ = _state(9821, plays=9)
    feature = build_history_ownership_input(
        actor, behavior_policy_ids=POLICIES)
    declarations = [event for event in feature.events
                    if event.event_kind == "declaration"]
    plays = [event for event in feature.events if event.event_kind == "play"]
    assert len(declarations) == len(actor.declaration_history)
    assert len(plays) == 9
    assert [event.trick_position for event in plays] == [0, 1, 2, 3,
                                                         0, 1, 2, 3, 0]
    actor_plays = [
        play
        for trick in (*actor.completed_tricks, actor.current_trick)
        for play in trick.plays
    ]
    assert [dict(event.attempted_cards) for event in plays] \
        == [dict(Counter(play.attempted_cards)) for play in actor_plays]
    assert [dict(event.actual_cards) for event in plays] \
        == [dict(Counter(play.cards)) for play in actor_plays]


def test_card_receiver_bounds_encode_void_pair_cap_and_declaration_pin():
    _, actor, target, _ = _state(9829)
    first_hand = dict(target.other_hands[0].cards)
    pinned_card, copies = next(iter(first_hand.items()))
    pins = ((pinned_card, 1, copies),)
    deductions = replace(actor.deductions, declaration_pins=pins)
    pinned_actor = replace(actor, deductions=deductions)
    feature = build_history_ownership_input(
        pinned_actor, behavior_policy_ids=POLICIES)
    row = next(row for row in feature.card_facts if row.card == pinned_card)
    assert row.min_count_by_receiver[0] == copies
    if copies == row.unseen_count:
        assert row.max_count_by_receiver[1:] == (0,) * (
            len(row.max_count_by_receiver) - 1)

    ordering = Ordering(actor.trump_suit, actor.trump_rank)
    existing_voids = set(actor.deductions.voids_by_relative[1])
    pinned_codes = {current for current, _, _
                    in actor.deductions.declaration_pins}
    pair_card = next(
        current for current, count in actor.deductions.unseen
        if count == 2 and current not in pinned_codes
        and ordering.eff_suit(current) not in existing_voids
    )
    pair_suit = ordering.eff_suit(pair_card)
    pair_caps = list(actor.deductions.pair_caps_by_relative)
    pair_caps[1] = tuple(sorted({**dict(pair_caps[1]), pair_suit: 0}.items()))
    pair_actor = replace(actor, deductions=replace(
        actor.deductions, pair_caps_by_relative=tuple(pair_caps)))
    feature = build_history_ownership_input(
        pair_actor, behavior_policy_ids=POLICIES)
    row = next(row for row in feature.card_facts if row.card == pair_card)
    assert row.max_count_by_receiver[0] == 1

    receiver_cards = set(first_hand)
    candidate = next(
        (card, ordering.eff_suit(card))
        for card, _ in actor.deductions.unseen
        if card not in receiver_cards
    )
    card, suit = candidate
    voids = list(actor.deductions.voids_by_relative)
    voids[1] = tuple(sorted({*voids[1], suit}))
    bounded_actor = replace(actor, deductions=replace(
        actor.deductions, voids_by_relative=tuple(voids)))
    feature = build_history_ownership_input(
        bounded_actor, behavior_policy_ids=POLICIES)
    row = next(row for row in feature.card_facts if row.card == card)
    assert row.max_count_by_receiver[0] == 0


def test_input_refuses_bad_identity_population_and_derived_drift():
    _, actor, _, _ = _state(9833)
    for policies in ((), ("b", "a"), ("a", "a"), ["a"]):
        with pytest.raises(BeliefInputError, match="policy identity"):
            build_history_ownership_input(
                actor, behavior_policy_ids=policies)
    malformed = replace(
        actor, hand_sizes_relative=(True, *actor.hand_sizes_relative[1:]))
    with pytest.raises(BeliefInputError):
        build_history_ownership_input(
            malformed, behavior_policy_ids=POLICIES)

    feature = build_history_ownership_input(
        actor, behavior_policy_ids=POLICIES)
    with pytest.raises(BeliefInputError, match="derivation drift"):
        validate_history_ownership_input(
            actor, replace(feature,
                           points_left_total=feature.points_left_total + 1))
