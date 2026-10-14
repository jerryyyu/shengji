"""Focused tests for the bounded engine-backed first-trick evaluator."""

from __future__ import annotations

import copy
import random

import pytest

from shengji.ai.endgame import (ExactEndgameBudgetExceeded,
                                ExactEndgameRefusal, _clone_for_play)
from shengji.ai.endgame import solve_exact_endgame
from shengji.ai.endgame import ExactWorldSession
from shengji.engine.cards import Ordering
from shengji.engine.round import Round, Trick, TrickPlay
from shengji.rl.value_afterstate import category_signed_level, signed_level_category
from shengji.train.pv_exact_endgame import exact_first_trick_means


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


@pytest.mark.parametrize('leader', range(4))
@pytest.mark.parametrize('alpha_beta', [False, True])
def test_value_only_matches_action_solver_and_reuses_root(leader, alpha_beta):
    rnd = _round([['C3', 'C4'], ['C5', 'C6'], ['C8', 'C9'], ['CA', 'C10']],
                 leader=leader, buried=['D5'])
    before = copy.deepcopy(rnd)
    expected = solve_exact_endgame(rnd, max_nodes=10000).attacker_points
    session = ExactWorldSession(rnd, max_nodes=10000, alpha_beta=alpha_beta)
    assert session.value(rnd) == expected
    nodes = session.nodes
    assert session.value(rnd) == expected
    assert session.nodes == nodes and session.cache_hits > 0
    assert rnd.hands == before.hands and rnd.trick == before.trick
    changed = copy.deepcopy(rnd)
    changed.buried = ['D10']
    with pytest.raises(ExactEndgameRefusal, match='context'):
        session.value(changed)


def test_value_only_retains_budget_and_cancellation():
    rnd = _round([['C3'], ['C4'], ['C5'], ['CA']])
    with pytest.raises(ExactEndgameBudgetExceeded):
        ExactWorldSession(rnd, max_nodes=1).value(rnd)
    def cancel():
        raise RuntimeError('cancelled')
    with pytest.raises(RuntimeError, match='cancelled'):
        ExactWorldSession(rnd, check_budget=cancel).value(rnd)


def test_value_only_avoids_unneeded_full_window_root_action_scores():
    rnd = _round([['C3', 'C4'], ['C5', 'C6'], ['C8', 'C9'], ['CA', 'C10']])
    action_session = ExactWorldSession(rnd, alpha_beta=True)
    scalar_session = ExactWorldSession(rnd, alpha_beta=True)
    assert scalar_session.value(rnd) == action_session.solve(rnd).attacker_points
    assert scalar_session.nodes < action_session.nodes


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


def test_first_trick_means_keeps_failed_throw_forced_component(monkeypatch):
    # The attempted pair+single contains a component the other hands can
    # beat, so the real engine downgrades it to the forced singleton C4.
    rnd = _round([
        ["C3", "C3", "C4"],
        ["C9", "C9", "C10"],
        ["D3", "D4", "D5"],
        ["S3", "S4", "S5"],
    ])
    world = (copy.deepcopy(rnd.hands), list(rnd.buried))
    committed = []
    original_play = Round.play

    def record_first_lead(self, seat, cards):
        if self.trick is not None and not self.trick.plays and seat == 0:
            attempted = list(cards)
            original_play(self, seat, cards)
            committed.append((attempted, list(self.trick.plays[0].cards)))
            return
        return original_play(self, seat, cards)

    # The evaluator must expose the engine's actual forced component, not
    # merely score the submitted throw as if it were played.
    monkeypatch.setattr(Round, "play", record_first_lead)
    # Use the public evaluator, while observing the clone that is actually
    # submitted to the engine through the existing Round implementation.
    means, stats = exact_first_trick_means(
        rnd, 0, [["C3", "C3", "C4"]], [world], max_nodes=10_000)
    forced, _ = exact_first_trick_means(
        rnd, 0, [["C4"]], [world], max_nodes=10_000)
    assert means.shape == (1,)
    assert means[0] == forced[0]
    assert committed[0] == (["C3", "C3", "C4"], ["C4"])
    assert stats["worlds_completed"] == 1


def test_first_trick_means_matches_individual_solves_for_multiple_worlds_actions():
    rnd = _round([
        ["C3", "C4"], ["C5", "C6"], ["C8", "C9"], ["CA", "C10"],
    ])
    worlds = [
        (copy.deepcopy(rnd.hands), []),
        ([list(h) for h in rnd.hands[:1]] +
         [["D3", "D4"], ["S3", "S4"], ["H3", "H4"]], []),
    ]
    actions = [["C3"], ["C4"]]
    means, stats = exact_first_trick_means(
        rnd, 0, actions, worlds, max_nodes=100_000)
    expected = [0.0, 0.0]
    for hands, buried in worlds:
        for index, action in enumerate(actions):
            child = _clone_for_play(rnd)
            child.hands = copy.deepcopy(hands)
            child.buried = list(buried)
            child.play(0, action)
            result = solve_exact_endgame(child, max_nodes=100_000)
            expected[index] += category_signed_level(
                signed_level_category(result.attacker_points,
                                      child.is_attacker(0)))
    expected = [value / len(worlds) for value in expected]
    assert means.tolist() == pytest.approx(expected)
    assert stats["worlds_completed"] == 2
    assert stats["nodes"] > 0


@pytest.mark.parametrize(("leader", "expected"), [(0, 2.5), (1, -2.5)])
def test_first_trick_means_supports_both_partnership_perspectives(leader, expected):
    rnd = _round([["C3"], ["C4"], ["C5"], ["CA"]], leader=leader)
    world = (copy.deepcopy(rnd.hands), list(rnd.buried))
    means, _ = exact_first_trick_means(
        rnd, leader, [[rnd.hands[leader][0]]], [world], max_nodes=100)
    assert means.shape == (1,)
    assert means[0] == pytest.approx(expected)


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

