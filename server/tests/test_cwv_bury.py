"""Witnesses for the bounded development bury-value core."""

from __future__ import annotations

import copy
import random
from collections import Counter

import numpy as np
import pytest

from shengji.ai.mcbot import MCBot
from shengji.ai.smart import SmartBot
from shengji.engine.game import Game
from shengji.rl.value_afterstate import category_signed_level, signed_level_category
from shengji.train.cwv_bury import (
    BuryValueError,
    bury_candidates,
    post_bury_world,
    rollout_bury_values,
    score_bury_candidates,
)


def _bury_state(seed: int = 7):
    rnd = Game(random.Random(seed)).start_round()
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
    assert rnd.phase == "bury"
    return rnd


def _world(rnd):
    return ([list(hand) for hand in rnd.hands], [])


def test_candidates_keep_literal_incumbent_and_refuse_mc_bury():
    rnd = _bury_state()
    bot = MCBot(seed=3)
    incumbent = list(bot.decide_bury(rnd, rnd.banker))
    candidates = bury_candidates(rnd, bot)
    assert candidates[0] == incumbent
    assert len({tuple(sorted(candidate)) for candidate in candidates}) == len(candidates)
    bot.MC_BURY = True
    with pytest.raises(BuryValueError, match="MC_BURY"):
        bury_candidates(rnd, bot)


def test_post_bury_is_real_engine_state_and_preserves_sources():
    rnd = _bury_state(9)
    bot = MCBot(seed=4)
    candidates = bury_candidates(rnd, bot)
    world = _world(rnd)
    before = copy.deepcopy((rnd.phase, rnd.turn, rnd.hands, rnd.buried,
                            rnd.history, rnd.trick, world, candidates[0]))
    post = post_bury_world(rnd, world[0], candidates[0])
    assert post.phase == "play" and post.turn == rnd.banker
    assert post.buried == candidates[0]
    assert [len(hand) for hand in post.hands] == [25, 25, 25, 25]
    physical = Counter(post.buried)
    for hand in post.hands:
        physical.update(hand)
    assert physical == Counter(rnd.deck)
    after = (rnd.phase, rnd.turn, rnd.hands, rnd.buried,
             rnd.history, rnd.trick, world, candidates[0])
    assert after == before

    bad = [list(hand) for hand in world[0]]
    bad[rnd.banker][0], bad[(rnd.banker + 1) % 4][0] = (
        bad[(rnd.banker + 1) % 4][0], bad[rnd.banker][0])
    with pytest.raises(BuryValueError, match="banker hand"):
        post_bury_world(rnd, bad, candidates[0])


def test_scoring_is_world_major_and_bounded():
    rnd = _bury_state(11)
    candidates = bury_candidates(rnd, MCBot(seed=5))[:2]
    worlds = [_world(rnd), _world(rnd)]

    class Evaluator:
        max_batch = 2

        def __init__(self):
            self.batches = []

        def score(self, positions, banker):
            self.batches.append((len(positions), banker))
            return np.asarray([float(len(position.buried)) for position in positions])

    evaluator = Evaluator()
    values = score_bury_candidates(rnd, candidates, worlds, evaluator)
    assert values.shape == (2, 2)
    assert np.all(values == 8.0)
    assert [size for size, _ in evaluator.batches] == [2, 2]
    assert all(banker == rnd.banker for _, banker in evaluator.batches)


def test_rollout_maps_banker_units_and_reuses_each_world():
    rnd = _bury_state(13)
    candidates = bury_candidates(rnd, MCBot(seed=6))[:2]
    worlds = [_world(rnd), _world(rnd)]

    class Rollout:
        def __init__(self):
            self.calls = []

        def _rollout_from_bury(self, root, banker, sampled, candidate):
            self.calls.append((root, banker, sampled, list(candidate)))
            return 0 if candidate == candidates[0] else 120

    bot = Rollout()
    values, points = rollout_bury_values(rnd, candidates, worlds, bot)
    assert points.dtype == np.int64
    assert points.tolist() == [[0, 120], [0, 120]]
    assert values.tolist() == [
        [category_signed_level(signed_level_category(0, False)),
         category_signed_level(signed_level_category(120, False))],
        [category_signed_level(signed_level_category(0, False)),
         category_signed_level(signed_level_category(120, False))],
    ]
    assert len(bot.calls) == 4
    assert all(call[1] == rnd.banker for call in bot.calls)
    assert all(set(call[2]) == {seat for seat in range(4) if seat != rnd.banker}
               for call in bot.calls)
    assert rnd.buried == [] and rnd.phase == "bury"
