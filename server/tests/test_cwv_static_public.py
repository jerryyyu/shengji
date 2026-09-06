"""Parity and refusal witnesses for the static public observation helper."""
from __future__ import annotations

import copy
import random

import numpy as np
import pytest

from shengji.ai.cwv_static_encoding import encode_obs_static
from shengji.ai.smart import SmartBot
from shengji.engine.cards import Ordering
from shengji.engine.game import Game
from shengji.engine.round import Trick, TrickPlay
from shengji.rl import encode as reference_encode
from shengji.rl.encode import CARD_INDEX, OBS_DIM


def _state_after(seed: int, plies: int):
    game = Game(random.Random(seed))
    rnd = game.start_round()
    bots = [SmartBot() for _ in range(4)]
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = bots[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = bots[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bots[rnd.banker].decide_bury(rnd, rnd.banker))
    for _ in range(plies):
        if rnd.phase != "play":
            break
        seat = rnd.turn
        rnd.play(seat, bots[seat].decide_play(rnd, seat))
    return rnd


def test_exact_list_and_float32_parity_all_seats_ranks_and_nt():
    for seed, plies in ((61, 1), (62, 35), (63, 70)):
        original = _state_after(seed, plies)
        for trump_rank, trump_suit, is_nt in (
                ("2", "S", False), ("7", "H", False), ("A", "D", False),
                ("5", None, True)):
            rnd = copy.deepcopy(original)
            rnd.trump_rank = trump_rank
            rnd.trump_suit = trump_suit
            rnd.trump_is_nt = is_nt
            rnd.ordering = Ordering(trump_suit, trump_rank)
            for seat in range(4):
                reference = reference_encode.encode_obs(rnd, seat)
                fast = encode_obs_static(rnd, seat)
                assert fast == reference
                assert np.array_equal(np.asarray(fast, dtype=np.float32),
                                      np.asarray(reference, dtype=np.float32))
                assert len(fast) == OBS_DIM


def test_banker_hidden_burial_is_not_subtracted_from_unseen():
    rnd = _state_after(71, 0)
    banker = rnd.banker
    card = rnd.buried[0]
    fast = encode_obs_static(rnd, banker)
    # Own-kitty=False is part of the frozen reference encoder contract.
    unseen_offset = 8 * 54
    assert fast[unseen_offset + CARD_INDEX[card]] == 1.0
    assert reference_encode.encode_obs(rnd, banker) == fast


def test_static_observation_bypasses_memory_but_reference_does_not(monkeypatch):
    rnd = _state_after(73, 30)

    class Tripwire:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("reference Memory called")

    monkeypatch.setattr(reference_encode, "Memory", Tripwire)
    result = encode_obs_static(rnd, 0)
    assert len(result) == OBS_DIM
    with pytest.raises(AssertionError, match="reference Memory called"):
        reference_encode.encode_obs(rnd, 0)


def test_evaluator_wiring_skips_unused_memory_and_keeps_scores(model, monkeypatch):
    # Witness the actual inference consumer, not just the helper: reverting
    # its call site to encode_obs must fail even if the helper stays correct.
    from shengji.ai.cwv_policy import CompleteWorldEvaluator

    rnd = _state_after(73, 30)
    reference = CompleteWorldEvaluator(None, model=model, encoding="reference")
    expected = reference.score([rnd], 0)

    class Tripwire:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("reference Memory called")

    monkeypatch.setattr(reference_encode, "Memory", Tripwire)
    actual = CompleteWorldEvaluator(None, model=model, encoding="mlp-static").score(
        [rnd], 0)
    assert np.array_equal(actual, expected)
    with pytest.raises(AssertionError, match="^reference Memory called$"):
        reference.score([rnd], 0)


@pytest.fixture(scope="module")
def model():
    import torch
    from shengji.rl.value_model import ValueModelConfig, ValueNetwork

    torch.manual_seed(37)
    return ValueNetwork(ValueModelConfig(
        architecture="mlp", width=16, feedforward_width=32,
        history_layers=1, attention_heads=1))


def _same_error(rnd, seat=0):
    with pytest.raises((AssertionError, AttributeError, IndexError, KeyError,
                        TypeError, ValueError)) as reference_error:
        reference_encode.encode_obs(rnd, seat)
    with pytest.raises(type(reference_error.value)) as static_error:
        encode_obs_static(rnd, seat)
    assert str(static_error.value) == str(reference_error.value)


def test_malformed_shapes_delegate_with_reference_exception():
    empty_history_trick = _state_after(79, 0)
    empty_history_trick.history = [Trick(leader=0, plays=[])]
    _same_error(empty_history_trick)

    bad_declaration = _state_after(80, 0)
    bad_declaration.declaration = []
    _same_error(bad_declaration)

    float_seat = _state_after(81, 1)
    _same_error(float_seat, 0.0)

    bad_current_card = _state_after(82, 0)
    bad_current_card.trick.plays = [TrickPlay(0, ["not-a-card"])]
    _same_error(bad_current_card)
