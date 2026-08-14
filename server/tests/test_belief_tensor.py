"""Target-blind BELIEF-V1 tensor feature tests."""

from __future__ import annotations

import copy
import random
from dataclasses import replace

import numpy as np
import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.engine.round import actual_play_after
from shengji.rl.belief_contract import (
    PublicTranscriptV1,
    build_actor_observation,
)
from shengji.rl.belief_input import CARD_CODES
from shengji.rl.belief_tensor import (
    CARD_FEATURE_DIM,
    EVENT_FEATURE_DIM,
    GLOBAL_FEATURE_DIM,
    MAX_RECEIVERS,
    RECEIVER_FEATURE_DIM,
    BeliefTensorError,
    build_history_ownership_tensors,
    validate_history_ownership_tensors,
)


POLICIES = ("mc-s0-report-lcb",)


def _state(seed=10201, plays=7):
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
    return rnd, actor, transcript


def test_tensor_shapes_dtypes_bounds_and_determinism():
    _, actor, _ = _state()
    first = build_history_ownership_tensors(
        actor, behavior_policy_ids=POLICIES)
    second = build_history_ownership_tensors(
        actor, behavior_policy_ids=POLICIES)
    assert first.events.shape == (len(actor.declaration_history) + 7,
                                  EVENT_FEATURE_DIM)
    assert first.global_features.shape == (GLOBAL_FEATURE_DIM,)
    assert first.card_features.shape == (len(CARD_CODES), CARD_FEATURE_DIM)
    assert first.receiver_features.shape == (
        MAX_RECEIVERS, RECEIVER_FEATURE_DIM)
    assert first.receiver_mask.shape == (MAX_RECEIVERS,)
    assert first.unseen_mask.shape == (len(CARD_CODES),)
    assert first.count_minimums.shape == (len(CARD_CODES), MAX_RECEIVERS)
    assert first.count_maximums.shape == (len(CARD_CODES), MAX_RECEIVERS)
    assert first.events.dtype == np.float32
    assert first.count_minimums.dtype == np.int64
    for field in ("events", "global_features", "card_features",
                  "receiver_features", "receiver_mask", "unseen_mask",
                  "count_minimums", "count_maximums"):
        assert np.array_equal(getattr(first, field), getattr(second, field))


def test_public_hidden_twins_have_bit_identical_tensors():
    rnd, actor, transcript = _state(10203)
    changed = copy.deepcopy(rnd)
    hidden = [seat for seat in range(4) if seat != rnd.turn]
    left, right = next(
        (left, right) for index, left in enumerate(hidden)
        for right in hidden[index + 1:]
        if len(changed.hands[left]) == len(changed.hands[right]))
    changed.hands[left], changed.hands[right] = (
        changed.hands[right], changed.hands[left])
    twin = build_actor_observation(changed, rnd.turn, transcript)
    assert twin.canonical_bytes() == actor.canonical_bytes()
    first = build_history_ownership_tensors(
        actor, behavior_policy_ids=POLICIES)
    second = build_history_ownership_tensors(
        twin, behavior_policy_ids=POLICIES)
    for field in ("events", "global_features", "card_features",
                  "receiver_features", "receiver_mask", "unseen_mask",
                  "count_minimums", "count_maximums"):
        assert getattr(first, field).tobytes() == getattr(second, field).tobytes()


def test_attempted_and_engine_actual_cards_have_separate_planes():
    _, actor, _ = _state(10205)
    play_index = next(
        index for index, event in enumerate(actor.completed_tricks[0].plays)
        if event.attempted_cards == event.cards)
    event = actor.completed_tricks[0].plays[play_index]
    replacement = replace(event, attempted_cards=(event.cards[0],))
    trick = replace(
        actor.completed_tricks[0],
        plays=(*actor.completed_tricks[0].plays[:play_index], replacement,
               *actor.completed_tricks[0].plays[play_index + 1:]))
    changed = replace(
        actor, completed_tricks=(trick, *actor.completed_tricks[1:]))
    tensor = build_history_ownership_tensors(
        changed, behavior_policy_ids=POLICIES)
    row = tensor.events[len(actor.declaration_history) + play_index]
    attempted_start = EVENT_FEATURE_DIM - 2 * len(CARD_CODES)
    actual_start = EVENT_FEATURE_DIM - len(CARD_CODES)
    assert not np.array_equal(
        row[attempted_start:actual_start], row[actual_start:])


def test_constraint_bounds_and_receiver_mask_are_explicit():
    _, actor, _ = _state(10207)
    tensor = build_history_ownership_tensors(
        actor, behavior_policy_ids=POLICIES)
    receivers = 4 if actor.hidden_burial_size else 3
    assert tensor.receiver_mask.tolist() == [
        index < receivers for index in range(MAX_RECEIVERS)]
    assert np.all(tensor.count_minimums <= tensor.count_maximums)
    assert np.all(tensor.count_maximums[:, receivers:] == 0)
    assert np.array_equal(tensor.unseen_mask,
                          tensor.count_maximums.sum(axis=1) > 0)


def test_tensor_derivation_and_policy_identity_refuse():
    _, actor, _ = _state(10209)
    tensor = build_history_ownership_tensors(
        actor, behavior_policy_ids=POLICIES)
    changed = tensor.card_features.copy()
    changed[0, 0] = 1.0 - changed[0, 0]
    with pytest.raises(BeliefTensorError, match="derivation drift"):
        validate_history_ownership_tensors(
            actor, replace(tensor, card_features=changed))
    with pytest.raises(ValueError, match="policy identity"):
        build_history_ownership_tensors(
            actor, behavior_policy_ids=("z", "a"))
