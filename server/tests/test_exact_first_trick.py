"""Focused tests for the bounded engine-backed first-trick evaluator."""

from __future__ import annotations

import copy
import random

import pytest

from shengji.ai.endgame import (ExactEndgameBudgetExceeded,
                                ExactEndgameRefusal, _clone_for_play)
from shengji.ai.endgame import category_signed_level, signed_level_category
from shengji.ai.endgame import solve_exact_endgame
from shengji.engine.cards import Ordering
from shengji.engine.round import Round, Trick, TrickPlay
from shengji.ai.endgame import exact_first_trick_means


def _round(hands, *, leader=0, banker=0, buried=()):
    rnd = Round("7", banker=banker, rng=random.Random(0))
    rnd.phase = "play"
    rnd.ordering = Ordering("H", "7")
    rnd.trump_suit = "H"
    rnd.hands = [list(hand) for hand in hands]
    rnd.buried = list(buried)
    rnd.trick = Trick(leader=leader)
    rnd.turn = leader
    rnd.deck = [card for hand in hands for card in hand] + list(buried)
    return rnd


def test_first_trick_means_applies_real_engine_lead_and_preserves_root():
    rnd = _round([["C3"], ["C4"], ["C5"], ["CA"]], leader=0)
    world = (copy.deepcopy(rnd.hands), list(rnd.buried))
    before = copy.deepcopy(rnd)
    means, stats = exact_first_trick_means(
        rnd, 0, [["C3"]], [world], max_nodes=100)
    assert means.shape == (1,)
    assert stats["worlds_completed"] == 1
    assert rnd.hands == before.hands
    assert rnd.trick == before.trick and rnd.turn == before.turn


def test_first_trick_means_matches_direct_exact_continuation():
    rnd = _round([["C3"], ["C4"], ["C5"], ["CA"]], leader=1)
    world = (copy.deepcopy(rnd.hands), list(rnd.buried))
    means, _ = exact_first_trick_means(
        rnd, 1, [["C4"]], [world], max_nodes=100)
    child = _clone_for_play(rnd)
    child.hands = copy.deepcopy(world[0])
    child.buried = list(world[1])
    child.play(1, ["C4"])
    result = solve_exact_endgame(child, max_nodes=100)
    expected = category_signed_level(
        signed_level_category(result.attacker_points, child.is_attacker(1)))
    assert means[0] == pytest.approx(expected)


def test_first_trick_means_keeps_failed_throw_forced_component():
    # The attempted pair+single contains a pair that seat 1 can beat, so the
    # real engine downgrades it to that pair before exact continuation.
    rnd = _round([
        ["C3", "C3", "C4"],
        ["C9", "C9", "C10"],
        ["D3", "D4", "D5"],
        ["S3", "S4", "S5"],
    ])
    world = (copy.deepcopy(rnd.hands), list(rnd.buried))
    # Use the public evaluator, while observing the clone that is actually
    # submitted to the engine through the existing Round implementation.
    means, stats = exact_first_trick_means(
        rnd, 0, [["C3", "C3", "C4"]], [world], max_nodes=10_000)
    forced, _ = exact_first_trick_means(
        rnd, 0, [["C3", "C3"]], [world], max_nodes=10_000)
    assert means.shape == (1,)
    assert means[0] == forced[0]
    assert stats["worlds_completed"] == 1


@pytest.mark.parametrize("leader", [0, 1])
def test_first_trick_means_supports_both_partnership_perspectives(leader):
    rnd = _round([["C3"], ["C4"], ["C5"], ["CA"]], leader=leader)
    world = (copy.deepcopy(rnd.hands), list(rnd.buried))
    means, _ = exact_first_trick_means(
        rnd, leader, [[rnd.hands[leader][0]]], [world], max_nodes=100)
    assert means.shape == (1,)


def test_first_trick_means_propagates_cancellation_and_no_partial_result():
    rnd = _round([["C3"], ["C4"], ["C5"], ["CA"]])
    world = (copy.deepcopy(rnd.hands), list(rnd.buried))
    calls = []

    def cancel():
        calls.append(True)
        raise RuntimeError("deadline")

    with pytest.raises(RuntimeError, match="deadline"):
        exact_first_trick_means(rnd, 0, [["C3"]], [world], cancel)
    assert calls


def test_first_trick_means_refuses_per_world_cap():
    rnd = _round([
        ["C3", "C4"], ["C5", "C6"], ["C8", "C9"], ["CA", "C10"],
    ])
    world = (copy.deepcopy(rnd.hands), list(rnd.buried))
    with pytest.raises(ExactEndgameBudgetExceeded):
        exact_first_trick_means(rnd, 0, [["C3"]], [world], max_nodes=1)


def test_first_trick_means_rejects_partial_or_nonlead_root():
    rnd = _round([["C3"], ["C4"], ["C5"], ["CA"]])
    world = (copy.deepcopy(rnd.hands), list(rnd.buried))
    rnd.trick.plays.append(TrickPlay(0, ["C3"]))
    with pytest.raises(ExactEndgameRefusal, match="lead root"):
        exact_first_trick_means(rnd, 0, [["C3"]], [world])

