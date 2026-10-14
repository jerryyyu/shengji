"""Correctness boundary for the S3b sampled exact-endgame inner solver."""

from __future__ import annotations

import random
from types import SimpleNamespace

import pytest

from shengji.ai.endgame import (ExactEndgameBudgetExceeded,
                                ExactEndgameRefusal,
                                ExactWorldSession,
                                exhaustive_legal_actions,
                                solve_exact_endgame)
from shengji.rl.value_afterstate import category_signed_level, signed_level_category
from shengji.train.cwv_prior_admission import root_clone
from shengji.train.pv_exact_endgame import exact_lead_means
from shengji.ai.heuristic import HeuristicBot
from shengji.ai.mcbot import DeterminizationContractError, MCBot
from shengji.engine.cards import Ordering
from shengji.engine.game import Game
from shengji.engine.round import Round, Trick, TrickPlay


def _round(hands, *, leader=0, plays=(), attacker_points=0, buried=()):
    rnd = Round("7", banker=0, rng=random.Random(0))
    rnd.phase = "play"
    rnd.ordering = Ordering("H", "7")
    rnd.trump_suit = "H"
    rnd.trump_is_nt = False
    rnd.hands = [list(h) for h in hands]
    rnd.buried = list(buried)
    rnd.attacker_points = attacker_points
    rnd.trick = Trick(leader=leader,
                      plays=[TrickPlay(s, list(cs)) for s, cs in plays])
    rnd.turn = (leader + len(plays)) % 4
    rnd.deck = [card for hand in hands for card in hand] + list(buried) + [
        card for _, cards in plays for card in cards]
    return rnd


def test_exhaustive_leads_cover_every_same_suit_submultiset():
    rnd = _round([
        ["C3", "C4", "D5", "D5"],
        ["C6"] * 4,
        ["C8"] * 4,
        ["C9"] * 4,
    ])
    got = {tuple(a) for a in exhaustive_legal_actions(rnd, 0)}
    assert got == {
        ("C3",), ("C4",), ("C3", "C4"),
        ("D5",), ("D5", "D5"),
    }


def test_exhaustive_follow_enforces_pair_obligation():
    rnd = _round([
        ["C3", "C3"],
        ["C4", "C4", "C5", "D2"],
        ["C6"] * 4,
        ["C8"] * 4,
    ], plays=[(0, ["C3", "C3"])])
    assert exhaustive_legal_actions(rnd, 1) == [["C4", "C4"]]


def test_one_trick_value_includes_points_and_kitty_multiplier():
    rnd = _round([
        ["C3"], ["C4"], ["C5"], ["CA"],
    ], attacker_points=7, buried=["H5"])
    before = [list(h) for h in rnd.hands]
    result = solve_exact_endgame(rnd)
    # Attacker seat 3 wins: existing 7 + C5 trick 5 + H5 kitty 10. Aces are
    # high cards but carry no points in Shengji.
    assert result.attacker_points == 22
    assert result.action == ("C3",)
    assert rnd.hands == before and rnd.phase == "play", \
        "the exact solver mutated its caller's information set"


def test_two_card_tree_uses_defender_min_at_internal_nodes():
    """Mutation witness: replacing the recursive min with max changes value."""
    rnd = _round([
        ["H2", "C3"],
        ["CA", "C9"],
        ["C10", "C4"],
        ["C6", "C8"],
    ], leader=1)
    assert rnd.banker == 0 and rnd.trump_rank == "7"
    result = solve_exact_endgame(rnd, max_hand_cards=2)
    # The root attacker must anticipate the defenders minimizing points on the
    # following moves. An unconditional recursive max returns 10/CA here.
    assert result.attacker_points == 0
    assert result.action == ("C9",)


@pytest.mark.parametrize('leader', range(4))
@pytest.mark.parametrize('hands', [
    [['H2', 'C3'], ['CA', 'C9'], ['C10', 'C4'], ['C6', 'C8']],
    [['C3', 'C3', 'C5'], ['C4', 'C4', 'C10'],
     ['C6', 'C6', 'CK'], ['CA', 'CA', 'C9']],
])
def test_alpha_beta_matches_exhaustive_and_reused_frontiers(leader, hands):
    from shengji.ai.endgame import _clone_for_play
    rnd = _round(hands, leader=leader, buried=['H5'])
    pruned = ExactWorldSession(rnd, alpha_beta=True)
    plain = ExactWorldSession(rnd)
    frontiers = [rnd]
    for action in exhaustive_legal_actions(rnd, leader):
        child = _clone_for_play(rnd)
        child.play(leader, action)
        frontiers.append(child)
    for frontier in frontiers + list(reversed(frontiers)):
        expected = plain.solve(frontier)
        actual = pruned.solve(frontier)
        assert (actual.attacker_points, actual.action) == (expected.attacker_points, expected.action)
    # Bound-cache reuse must preserve exact values even across different windows;
    # pruning is not guaranteed to reduce total nodes for every move ordering.


def test_shared_session_state_key_separates_accumulated_attacker_points():
    """Two otherwise-identical frontiers must not collide in the exact cache."""
    hands = [
        ["H2", "C3"],
        ["CA", "C9"],
        ["C10", "C4"],
        ["C6", "C8"],
    ]
    zero = _round(hands, leader=1, attacker_points=0)
    twenty = _round(hands, leader=1, attacker_points=20)
    session = ExactWorldSession(zero, max_hand_cards=2)
    first = session.solve(zero)
    second = session.solve(twenty)
    assert (first.attacker_points, first.action) == (0, ("C9",))
    assert (second.attacker_points, second.action) == (20, ("C9",))
    assert second.nodes > 0, \
        "a zero-node second solve indicates an attacker-points cache collision"


@pytest.mark.parametrize('leader', range(4))
@pytest.mark.parametrize('direction', ['lower', 'upper'])
def test_stored_bounds_narrow_later_full_window_without_changing_value(leader, direction):
    from shengji.ai.endgame import _state_key
    rnd = _round([['C3', 'C3', 'C5'], ['C4', 'C4', 'C10'],
                  ['C6', 'C6', 'CK'], ['CA', 'CA', 'C9']],
                 leader=leader, buried=['H5'])
    expected = ExactWorldSession(rnd).value(rnd)
    session = ExactWorldSession(rnd, alpha_beta=True)
    # Produce a real one-sided bound using an aspiration window, rather than
    # injecting an unproved table entry. A later full window must remain exact.
    alpha, beta = ((expected - 1, expected) if direction == 'lower'
                   else (expected, expected + 1))
    session.solver.value(rnd, alpha, beta)
    assert _state_key(rnd) in session.solver.bounds
    assert session.value(rnd) == expected
    assert session.solver.cache[_state_key(rnd)] == expected
    assert session.solve(rnd).attacker_points == expected


def test_complementary_bounds_avoid_reexpansion_at_node_cap():
    from shengji.ai.endgame import _state_key
    rnd = _round([['C3'], ['C4'], ['C5'], ['CA']], buried=['H5'])
    expected = ExactWorldSession(rnd).value(rnd)
    session = ExactWorldSession(rnd, alpha_beta=True)
    session.solver.value(rnd, expected - 1, expected)
    session.solver.value(rnd, expected, expected + 1)
    assert session.solver.bounds[_state_key(rnd)] == (expected, expected)
    before = session.nodes
    session.solver.max_nodes = before
    assert session.value(rnd) == expected
    assert session.nodes == before


def test_follow_action_cache_isolated_and_defensive(monkeypatch):
    import shengji.ai.endgame as endgame
    rnd = _round([['C3'], ['C4', 'C5'], ['C6'], ['CA']], plays=[(0, ['C3'])])
    session = ExactWorldSession(rnd, alpha_beta=True)
    original = endgame.exhaustive_legal_actions
    calls = []
    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(endgame, 'exhaustive_legal_actions', counted)
    expected = session.solver.actions(rnd, 1)
    poisoned = session.solver.actions(rnd, 1)
    poisoned[0].append('BJ')
    rnd.attacker_points += 20
    assert session.solver.actions(rnd, 1) == expected and len(calls) == 1
    rnd.hands[1].append('CK')
    assert session.solver.actions(rnd, 1) == original(rnd, 1)
    assert len(calls) == 2
    session.solver.max_hand_cards = 1
    with pytest.raises(ExactEndgameRefusal):
        session.solver.actions(rnd, 1)
    other = ExactWorldSession(rnd, alpha_beta=True)
    other.solver.actions(rnd, 1)
    assert len(calls) == 4  # cap refusal + separate world's own enumeration


@pytest.mark.parametrize('leader', range(4))
def test_follow_cache_reduces_real_first_trick_enumerations(monkeypatch, leader):
    import copy
    import numpy as np
    import shengji.ai.endgame as endgame
    from shengji.train.pv_exact_endgame import exact_first_trick_means
    rnd = _round([['C3', 'C3', 'C5', 'H2'], ['C4', 'C4', 'C10', 'D5'],
                  ['C6', 'C6', 'CK', 'H3'], ['CA', 'CA', 'C9', 'DA']],
                 leader=leader, buried=['H5'])
    actions = exhaustive_legal_actions(rnd, leader)
    worlds = [(copy.deepcopy(rnd.hands), list(rnd.buried))]
    original = endgame.exhaustive_legal_actions
    calls = []
    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(endgame, 'exhaustive_legal_actions', counted)
    cached = exact_first_trick_means(rnd, leader, actions, worlds)
    cached_count = len(calls)
    calls.clear()
    monkeypatch.setattr(endgame._ExactSolver, 'actions', lambda self, r, s:
        counted(r, s, max_hand_cards=self.max_hand_cards))
    plain = exact_first_trick_means(rnd, leader, actions, worlds)
    assert np.array_equal(cached[0], plain[0])
    assert cached[1] == plain[1]  # same expansions, cache hits, completed worlds
    assert cached_count < len(calls) // 2


def test_real_three_card_endgame_completes_and_returns_a_legal_action():
    game = Game(random.Random(19))
    bots = [HeuristicBot() for _ in range(4)]
    rnd = game.start_round()
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
    assert rnd.banker is not None
    rnd.bury(rnd.banker, bots[rnd.banker].decide_bury(rnd, rnd.banker))
    while max(len(h) for h in rnd.hands) > 3:
        seat = rnd.turn
        assert seat is not None
        rnd.play(seat, bots[seat].decide_play(rnd, seat))

    legal = {tuple(a) for a in exhaustive_legal_actions(rnd, rnd.turn)}
    result = solve_exact_endgame(rnd, max_hand_cards=3, max_nodes=100_000)
    assert result.action in legal
    assert result.nodes <= 100_000


def test_solver_refuses_states_and_work_outside_declared_bounds():
    too_large = _round([["C2"] * 5] * 4)
    with pytest.raises(ExactEndgameRefusal, match="completeness cap"):
        solve_exact_endgame(too_large)

    bounded = _round([
        ["C3", "D3"], ["C4", "D4"],
        ["C5", "D5"], ["C6", "D6"],
    ])
    with pytest.raises(ExactEndgameBudgetExceeded, match="max_nodes=1"):
        solve_exact_endgame(bounded, max_nodes=1)


def test_mc_rollout_switches_to_exact_only_inside_a_determinized_world(
        monkeypatch):
    rnd = _round([
        ["C3"], ["C4"], ["C5"], ["CA"],
    ], attacker_points=7, buried=["H5"])
    bot = type("ExactMC", (MCBot,), {"EXACT_ENDGAME": True})(seed=4)
    seen = []

    class FakeSession:
        def __init__(self, clone, *, max_hand_cards, max_nodes):
            seen.append(("session", max_hand_cards, max_nodes))

        def solve(self, clone):
            seen.append((clone.turn, [len(h) for h in clone.hands]))
            return SimpleNamespace(attacker_points=123, nodes=17, cache_hits=6)

    monkeypatch.setattr("shengji.ai.endgame.ExactWorldSession", FakeSession)
    value = bot._rollout(
        rnd, 0,
        {1: ["C4"], 2: ["C5"], 3: ["CA"]},
        ["H5"], ["C3"],
    )
    assert value == 123.0
    assert seen == [("session", 4, 250_000), (1, [0, 1, 1, 1])]
    assert (bot.exact_endgame_calls, bot.exact_endgame_nodes,
            bot.exact_endgame_cache_hits) == (1, 17, 6)
    assert (bot.exact_endgame_attempts, bot.exact_endgame_refusals,
            bot.exact_endgame_sessions) == (1, 0, 1)


def test_evaluator_counters_expose_exact_endgame_work():
    from shengji.evaluation import counters

    bot = MCBot(seed=1)
    bot.exact_endgame_calls = 2
    bot.exact_endgame_nodes = 91
    bot.exact_endgame_cache_hits = 13
    got = counters([bot])
    assert got["exact_endgames"] == 2
    assert got["exact_endgame_attempts"] == 0
    assert got["exact_endgame_refusals"] == 0
    assert got["exact_endgame_budget_exceeded"] == 0
    assert got["exact_endgame_sessions"] == 0
    assert got["exact_endgame_nodes"] == 91
    assert got["exact_endgame_cache_hits"] == 13


def test_mc_exact_seam_refuses_an_unmarked_live_round():
    rnd = _round([
        ["C3"], ["C4"], ["C5"], ["CA"],
    ])
    bot = type("ExactMC", (MCBot,), {"EXACT_ENDGAME": True})(seed=2)
    with pytest.raises(ExactEndgameRefusal, match="marked determinized world"):
        bot._exact_endgame_value(rnd)


def test_rollout_refuses_incomplete_sample_instead_of_using_live_hidden_hand():
    rnd = _round([
        ["C3"], ["C4"], ["C5"], ["CA"],
    ], buried=["H5"])
    bot = MCBot(seed=2)
    with pytest.raises(DeterminizationContractError, match="sampled hand keys"):
        bot._rollout(rnd, 0, {1: ["C4"], 2: ["C5"]}, ["H5"], ["C3"])


def test_exact_session_reuses_one_world_but_refuses_kitty_context_collision():
    first = _round([
        ["C3"], ["C4"], ["C5"], ["CA"],
    ], attacker_points=7, buried=["H5"])
    session = ExactWorldSession(first)
    one = session.solve(first)
    two = session.solve(first)
    assert one.attacker_points == two.attacker_points == 22
    assert two.nodes == 0 and two.cache_hits > 0

    different_kitty = _round([
        ["C3"], ["C4"], ["C5"], ["CA"],
    ], attacker_points=7, buried=["C2"])
    assert solve_exact_endgame(different_kitty).attacker_points == 12
    with pytest.raises(ExactEndgameRefusal, match="context differs"):
        session.solve(different_kitty)


def test_exact_budget_refusal_is_counted_with_consumed_work():
    rnd = _round([
        ["C3"], ["C4"], ["C5"], ["CA"],
    ], buried=["H5"])
    rnd._determinized_world = True
    bot = type("ExactMC", (MCBot,), {"EXACT_ENDGAME": True})(seed=2)

    class RefusingSession:
        def solve(self, _clone):
            raise ExactEndgameBudgetExceeded(
                "cap", nodes=19, cache_hits=4)

    with pytest.raises(ExactEndgameBudgetExceeded):
        bot._exact_endgame_value(rnd, RefusingSession())
    assert (bot.exact_endgame_attempts, bot.exact_endgame_calls,
            bot.exact_endgame_refusals,
            bot.exact_endgame_budget_exceeded) == (1, 0, 1, 1)
    assert (bot.exact_endgame_nodes,
            bot.exact_endgame_cache_hits) == (19, 4)


def _exact_leaf(root, seat, hands, buried, action, world_index):
    clone = root_clone(root, hands, buried)
    clone.play(seat, list(action))
    return clone


@pytest.mark.parametrize("seat", [0, 1])
def test_exact_lead_means_matches_individual_solver_for_both_teams(seat):
    rnd = _round([
        ["C3"], ["C4"], ["C5"], ["CA"],
    ], leader=seat)
    worlds = [(list(map(list, rnd.hands)), list(rnd.buried))]
    actions = [[rnd.hands[seat][0]]]
    means, stats = exact_lead_means(rnd, seat, actions, worlds,
                                    _exact_leaf, None, max_nodes=100)
    leaf = _exact_leaf(rnd, seat, worlds[0][0], worlds[0][1], actions[0], 0)
    expected = solve_exact_endgame(leaf, max_nodes=100)
    expected = category_signed_level(
        signed_level_category(expected.attacker_points,
                              leaf.is_attacker(seat)))
    assert means.tolist() == pytest.approx([expected])
    assert stats["worlds_completed"] == 1


def test_exact_lead_means_covers_every_world_candidate_and_preserves_root():
    rnd = _round([
        ["C3", "C4"], ["C5", "C6"], ["C8", "C9"], ["CA", "C10"],
    ], leader=0)
    before = (rnd.phase, rnd.turn, [list(h) for h in rnd.hands],
              tuple((p.seat, tuple(p.cards)) for p in rnd.trick.plays))
    worlds = [(list(map(list, rnd.hands)), list(rnd.buried)),
              (list(map(list, rnd.hands)), list(rnd.buried))]
    seen = []

    def leaf(root, seat, hands, buried, action, world_index):
        seen.append((world_index, tuple(action)))
        return _exact_leaf(root, seat, hands, buried, action, world_index)

    exact_lead_means(rnd, 0, [["C3"], ["C4"]], worlds, leaf, None,
                     max_nodes=1000)
    assert seen == [(0, ("C3",)), (0, ("C4",)),
                    (1, ("C3",)), (1, ("C4",))]
    assert before == (rnd.phase, rnd.turn, [list(h) for h in rnd.hands],
                      tuple((p.seat, tuple(p.cards)) for p in rnd.trick.plays))


def test_exact_lead_means_propagates_cancellation_without_returning_partial():
    rnd = _round([["C3"], ["C4"], ["C5"], ["CA"]])
    worlds = [(list(map(list, rnd.hands)), list(rnd.buried))]
    class Cancelled(Exception):
        pass
    calls = []

    def check():
        calls.append(True)
        raise Cancelled

    with pytest.raises(Cancelled):
        exact_lead_means(rnd, 0, [["C3"]], worlds, _exact_leaf,
                         check, max_nodes=100)
    assert calls


def test_exact_lead_means_refuses_per_world_node_cap():
    rnd = _round([["C3", "C4"], ["C5", "C6"], ["C8", "C9"], ["CA", "C10"]])
    worlds = [(list(map(list, rnd.hands)), list(rnd.buried))]
    with pytest.raises(ExactEndgameBudgetExceeded):
        exact_lead_means(rnd, 0, [["C3"]], worlds, _exact_leaf,
                         None, max_nodes=1)
