"""Candidate scoring uses history-free static inputs without changing its contract."""
from __future__ import annotations

import copy
import random

import numpy as np
import pytest

from shengji.ai.smart import SmartBot
from shengji.engine.game import Game
from shengji.harvest.legal import enumerate_legal
from shengji.rl import value_afterstate
from shengji.train import cwv_eval


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
    assert rnd.phase == "play"
    return rnd


def _ballot(rnd, cap: int = 3):
    """A small prefix of the engine's actual legal ballot."""
    legal = enumerate_legal(rnd, rnd.turn, cap=cap)
    assert legal.actions
    return legal.actions[:cap]


def _array_bytes(entry):
    return {key: (value.dtype.str, value.shape, value.tobytes())
            for key, value in entry.items() if isinstance(value, np.ndarray)}


def _scalar_fields(entry):
    return {key: value for key, value in entry.items()
            if not isinstance(value, np.ndarray)}


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("plies", [0, 1, 70])
def test_history_free_score_candidates_matches_reference_bytes(monkeypatch, version, plies):
    rnd = _state_after(61 + plies, plies)
    candidates = _ballot(rnd)
    if plies == 0:
        assert len({tuple(action) for action in candidates}) > 1
    static = cwv_eval.tensors_from_round_static

    # Route the history-free call through the original builder to capture the
    # reference result, then restore the real static adapter for the assertion.
    monkeypatch.setattr(cwv_eval, "tensors_from_round_static", cwv_eval.tensors_at)
    reference = cwv_eval.score_candidates(rnd, rnd.turn, candidates,
                                          history=False, version=version)
    monkeypatch.setattr(cwv_eval, "tensors_from_round_static", static)
    actual = cwv_eval.score_candidates(rnd, rnd.turn, candidates,
                                       history=False, version=version)

    assert actual.keys() == reference.keys()
    assert _array_bytes(actual) == _array_bytes(reference)
    assert _scalar_fields(actual) == _scalar_fields(reference)


def test_history_true_uses_reference_builder_and_preserves_history(monkeypatch):
    rnd = _state_after(62, 35)
    seat = rnd.turn
    candidate = _ballot(rnd, cap=1)[0]
    original = cwv_eval.tensors_at
    calls = []

    def traced(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(cwv_eval, "tensors_at", traced)
    actual = cwv_eval.score_candidates(rnd, seat, [candidate], history=True, version=2)
    assert len(calls) == 1

    successor, _ = value_afterstate.apply_action(rnd, seat, list(candidate))
    expected = original(successor, seat, version=2)
    cards, meta = cwv_eval.compact_history(expected.history)
    assert actual["history_cards"].tobytes() == cards.tobytes()
    assert actual["history_meta"].tobytes() == meta.tobytes()
    assert actual["history_offsets"].tobytes() == np.asarray([0, len(cards)], np.int64).tobytes()


def test_history_false_supported_state_does_not_construct_reference_history(monkeypatch):
    rnd = _state_after(73, 35)
    candidate = _ballot(rnd, cap=1)[0]

    def tripwire(*_args, **_kwargs):
        raise AssertionError("reference history constructor called")

    monkeypatch.setattr(value_afterstate, "encode_public_history", tripwire)
    monkeypatch.setattr(cwv_eval, "tensors_at", tripwire)
    actual = cwv_eval.score_candidates(rnd, rnd.turn, [candidate],
                                       history=False, version=2)
    assert actual["public"].shape == (1, cwv_eval.public_dim(2))
    assert actual["world"].dtype == np.uint8


def _terminal_predecessor(seed: int = 91):
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
    while rnd.phase == "play":
        previous = copy.deepcopy(rnd)
        seat = rnd.turn
        candidate = bots[seat].decide_play(rnd, seat)
        rnd.play(seat, candidate)
    assert rnd.phase == "round_end"
    return previous, seat, candidate


def test_terminal_successor_is_identical_with_or_without_history():
    rnd, seat, candidate = _terminal_predecessor()
    history_free = cwv_eval.score_candidates(rnd, seat, [candidate], history=False, version=1)
    with_history = cwv_eval.score_candidates(rnd, seat, [candidate], history=True, version=1)
    for key in ("public", "world", "perspective", "terminal", "terminal_level",
                "successor_points", "successor_ply"):
        assert history_free[key].tobytes() == with_history[key].tobytes()
    assert history_free["terminal"].tolist() == [True]
    assert with_history["history_offsets"].tolist() == [0, 0]
