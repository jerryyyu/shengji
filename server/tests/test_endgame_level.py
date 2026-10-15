"""Level-mode exact sessions and the deeper / follow exact rules.

``CompactWorldSession(level=True).solve_level`` must place every root's
minimax value in the same interval between ``LEVEL_CUTS`` as the reference
``ExactWorldSession`` (full minimax), and ``solve_points`` must equal its
value; ``pv_exact_deep.exact_root_means`` must return the reference means on
leads.  The rule ``exact_deep_cards`` must leave every existing registry name,
and a flag-off bot, exactly as they were.
"""

from __future__ import annotations

import random

import numpy as np
import pytest

from shengji.ai.endgame import (ExactEndgameBudgetExceeded, ExactEndgameRefusal,
                                ExactWorldSession, _clone_for_play,
                                exhaustive_legal_actions)
from shengji.ai.endgame_compact import (HAVE_FAST, LEVEL_CUTS, CompactWorldSession,
                                        level_points)
from shengji.ai.env import prepare_round
from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.rl.value_afterstate import category_signed_level, signed_level_category
from shengji.train import pv_exact_deep, pv_search_policy as pv
from shengji.train.cwv_prior_admission import root_clone
from test_encoder_round_compat import pinned_production_package  # noqa: F401
from test_endgame_compact import _random_position, _session_roots, _worlds

BACKENDS = ["python"] + (["compiled"] if HAVE_FAST else [])


def _reference_points(rnd):
    session = ExactWorldSession(rnd, max_hand_cards=8, max_nodes=10**9, alpha_beta=True)
    return session.solve(rnd).attacker_points


def _expected_level_points(rnd, points):
    reduced = level_points(points)
    return reduced if reduced > rnd.attacker_points else int(rnd.attacker_points)


def test_level_points_reduces_to_the_signed_level_steps():
    for points in range(0, 400, 5):
        reduced = level_points(points)
        assert reduced <= points
        for attacker in (True, False):
            assert (category_signed_level(signed_level_category(reduced, attacker))
                    == category_signed_level(signed_level_category(points, attacker)))
    assert LEVEL_CUTS[:4] == (1, 40, 80, 120)


@pytest.mark.parametrize("backend", BACKENDS)
def test_level_mode_matches_reference_minimax(backend):
    rng = random.Random(20261015)
    compared = 0
    for _ in range(80):
        rnd = _random_position(rng)
        if rnd.phase != "play":
            continue
        roots = _session_roots(rnd)
        session = CompactWorldSession(roots[0], max_hand_cards=4, max_nodes=10**9,
                                      alpha_beta=True, backend=backend, level=True)
        for root in roots:
            want = _reference_points(root)
            assert session.solve_level(root) == _expected_level_points(root, want)
            assert session.solve_points(root) == want
            compared += 1
    assert compared >= 200


def _lead_at(seed, cards):
    game = Game(random.Random(seed))
    bots = [HeuristicBot() for _ in range(4)]
    rnd = prepare_round(game, bots)
    while rnd.phase == "play":
        if max(map(len, rnd.hands)) <= cards and not rnd.trick.plays:
            return rnd, bots
        rnd.play(rnd.turn, bots[rnd.turn].decide_play(rnd, rnd.turn))
    return None, bots


def _heuristic_leaf(root, seat, hands, buried, action, world_index):
    clone = root_clone(root, hands, buried)
    clone._trusted_rollout = False
    clone.play(seat, list(action))
    bot = HeuristicBot()
    while clone.phase == "play" and clone.trick.plays:
        clone.play(clone.turn, bot.decide_play(clone, clone.turn))
    return clone


def _reference_means(rnd, seat, actions, worlds):
    means = np.zeros(len(actions))
    for hands, buried in worlds:
        world_root = root_clone(rnd, hands, buried)
        for k, action in enumerate(actions):
            leaf = _heuristic_leaf(world_root, seat, hands, buried, action, 0)
            points = (leaf.attacker_points if leaf.phase == "round_end"
                      else _reference_points(leaf))
            means[k] += category_signed_level(signed_level_category(points, leaf.is_attacker(seat)))
    return means / len(worlds)


@pytest.mark.parametrize("backend", BACKENDS)
def test_exact_root_means_match_reference(monkeypatch, backend):
    real = CompactWorldSession
    monkeypatch.setattr(pv_exact_deep, "CompactWorldSession",
                        lambda *a, **kw: real(*a, backend=backend, **kw))
    rng = random.Random(7)
    checked = 0
    for seed in range(4600000, 4600012):
        rnd, bots = _lead_at(seed, 5)
        if rnd is None:
            continue
        seat = rnd.turn
        actions = exhaustive_legal_actions(rnd, seat, max_hand_cards=5)[:4]
        worlds = _worlds(rnd, seat, rng, 3)
        want = _reference_means(rnd, seat, actions, worlds)
        for level in (True, False):
            got, stats = pv_exact_deep.exact_root_means(
                rnd, seat, actions, worlds, _heuristic_leaf, None, max_hand_cards=5,
                max_nodes=10**9, level=level)
            assert got.tolist() == want.tolist()
            assert stats["worlds_completed"] == len(worlds)
        checked += 1
    assert checked >= 6


def test_exact_root_means_refusals():
    rnd, _ = _lead_at(4600001, 5)
    seat = rnd.turn
    actions = exhaustive_legal_actions(rnd, seat, max_hand_cards=5)[:2]
    worlds = _worlds(rnd, seat, random.Random(1), 2)
    with pytest.raises(ExactEndgameRefusal):
        pv_exact_deep.exact_root_means(rnd, seat, actions, worlds, _heuristic_leaf, None,
                                       max_hand_cards=4, max_nodes=100)
    with pytest.raises(ExactEndgameRefusal):
        pv_exact_deep.exact_root_means(rnd, seat, actions, worlds, _heuristic_leaf, None,
                                       max_hand_cards=9, max_nodes=100)
    follow = _clone_for_play(rnd)
    follow.play(seat, list(actions[0]))
    with pytest.raises(ExactEndgameRefusal):
        pv_exact_deep.exact_root_means(follow, follow.turn, [], worlds, _heuristic_leaf, None,
                                       max_hand_cards=5, max_nodes=100)
    with pytest.raises(ExactEndgameBudgetExceeded):
        pv_exact_deep.exact_root_means(rnd, seat, actions, worlds, _heuristic_leaf, None,
                                       max_hand_cards=5, max_nodes=3)


def test_level_session_answers_only_level_questions():
    rng = random.Random(3)
    rnd = next(r for r in (_random_position(rng) for _ in range(20)) if r.phase == "play")
    with pytest.raises(ExactEndgameRefusal):
        CompactWorldSession(rnd, level=True).solve(rnd)
    with pytest.raises(ExactEndgameRefusal):
        CompactWorldSession(rnd).solve_level(rnd)


# -- registry identity ----------------------------------------------------------

def _env(pkg, **extra):
    from scripts.qualify_exact_lead import qualification_env
    return {**qualification_env(pkg, 45), **extra}


def test_names_off_and_s18_are_unchanged_and_new_rules_name_themselves(pinned_production_package):
    from scripts.qualify_exact_lead import R45_NAMES
    pkg = pinned_production_package
    off = pv.pv_registry_entries(**pv.pv_env_recipe(_env(pkg, SHENGJI_PV_EXACT_LEAD_ENDGAME="0")))
    s18 = pv.pv_registry_entries(**pv.pv_env_recipe(_env(pkg, SHENGJI_PV_EXACT_LEAD_ENDGAME="1")))
    assert list(off) == [R45_NAMES[0]] and list(s18) == [R45_NAMES[1]]
    deep = pv.pv_registry_entries(**pv.pv_env_recipe(_env(
        pkg, SHENGJI_PV_EXACT_LEAD_ENDGAME="1", SHENGJI_PV_EXACT_DEEP_CARDS="6")))
    name, = deep
    assert "-ele-" in name and "-ed6-r" in name
    zero = pv.pv_registry_entries(**pv.pv_env_recipe(_env(
        pkg, SHENGJI_PV_EXACT_LEAD_ENDGAME="1", SHENGJI_PV_EXACT_DEEP_CARDS="0")))
    assert list(zero) == [R45_NAMES[1]]


@pytest.mark.parametrize("extra", [dict(SHENGJI_PV_EXACT_DEEP_CARDS="6")])
def test_new_rules_require_the_exact_lead(extra, pinned_production_package):
    with pytest.raises(pv.PVSearchPolicyError, match="require exact_lead_endgame"):
        pv.pv_registry_entries(**pv.pv_env_recipe(_env(pinned_production_package, **extra)))


@pytest.mark.parametrize("raw", ["3", "9", "x", "-1"])
def test_exact_deep_cards_range(raw, pinned_production_package):
    with pytest.raises(pv.PVSearchPolicyError):
        pv.pv_registry_entries(**pv.pv_env_recipe(_env(
            pinned_production_package, SHENGJI_PV_EXACT_LEAD_ENDGAME="1", SHENGJI_PV_EXACT_DEEP_CARDS=raw)))


def test_flag_off_bots_carry_no_new_instance_state(pinned_production_package):
    pkg = pinned_production_package
    for endgame in ("0", "1"):
        entries = pv.pv_registry_entries(**pv.pv_env_recipe(_env(
            pkg, SHENGJI_PV_EXACT_LEAD_ENDGAME=endgame)))
        bot = next(iter(entries.values()))(seed=1)
        assert "exact_deep_cards" not in vars(bot) and bot.exact_deep_cards == 0
    entries = pv.pv_registry_entries(**pv.pv_env_recipe(_env(
        pkg, SHENGJI_PV_EXACT_LEAD_ENDGAME="1", SHENGJI_PV_EXACT_DEEP_CARDS="5")))
    bot = next(iter(entries.values()))(seed=1)
    assert vars(bot)["exact_deep_cards"] == 5


# -- exact follow (`pv_exact_follow`) on the compiled level session -------------

def _follow_at(seed, cards):
    rnd, bots = _lead_at(seed, cards)
    if rnd is None:
        return None
    rnd.play(rnd.turn, bots[rnd.turn].decide_play(rnd, rnd.turn))
    return rnd if rnd.phase == "play" else None


@pytest.mark.parametrize("backend", BACKENDS)
def test_rerank_follow_compact_level_matches_reference(monkeypatch, backend):
    from shengji.train import pv_exact_follow
    real = CompactWorldSession
    monkeypatch.setattr(pv_exact_follow, "CompactWorldSession",
                        lambda *a, **kw: real(*a, backend=backend, **kw))
    rng = random.Random(11)
    checked = 0
    for seed in range(4600100, 4600112):
        rnd = _follow_at(seed, 4)
        if rnd is None:
            continue
        seat = rnd.turn
        admitted = exhaustive_legal_actions(rnd, seat, max_hand_cards=4)[:4]
        worlds = _worlds(rnd, seat, rng, 3)
        want = pv_exact_follow.rerank_follow(rnd, seat, admitted, worlds,
                                             max_nodes=10**9, solver="reference")
        got = pv_exact_follow.rerank_follow(rnd, seat, admitted, worlds,
                                            max_nodes=10**9, solver="compact-level")
        assert (got.winner, got.scores, got.worlds) == (want.winner, want.scores, want.worlds)
        checked += 1
    assert checked >= 6
    with pytest.raises(pv_exact_follow.ExactFollowRefusal):
        pv_exact_follow.rerank_follow(rnd, seat, admitted, worlds, solver="other")
