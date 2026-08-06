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
