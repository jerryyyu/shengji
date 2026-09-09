"""Contract tests for the unregistered DEV CWV bury arms."""

from __future__ import annotations

import copy
import random

import numpy as np

from shengji.engine.game import Game
from shengji.train.cwv_bury_policy import (
    BuryPolicyError,
    CWVBuryBot,
    make_cwv_bury_bot,
)
from shengji.train.cwv_shortlist import CWVShortlistBot, CWVShortlistConfig
from shengji.ai.smart import SmartBot


def _bury_state(seed=7):
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
    return rnd


class _Evaluator:
    max_batch = 64

    def score(self, positions, _seat, **_kwargs):
        return np.zeros(len(positions))


class _Helper:
    MARGIN = 0.0
    LEVEL_OBJECTIVE = False

    def __init__(self, seed):
        self.seed = seed
        self.rng = random.Random(seed)
        self.rollout_policy = object()
        self.calls = []

    def _sampler_snapshot(self):
        return {"sample_attempts": 0, "accepted_worlds": 0}

    def _score(self, points):
        return float(points)


def test_arms_keep_config_and_heuristic_incumbent(monkeypatch):
    assert CWVBuryBot._candidates is CWVShortlistBot._candidates
    rnd = _bury_state()
    config = CWVShortlistConfig(worlds=32, selection_worlds=30, batch_size=17)
    incumbent = list(SmartBot().decide_bury(rnd, rnd.banker))
    candidates = [incumbent] + [list(rnd.hands[rnd.banker][i:i + 8])
                                for i in (8, 16, 24)]
    monkeypatch.setattr("shengji.train.cwv_bury_policy.bury_candidates",
                        lambda _rnd, _bot: copy.deepcopy(candidates))
    bot = make_cwv_bury_bot(_Evaluator(), config, seed=41, arm="heuristic")
    assert isinstance(bot, CWVBuryBot)
    assert bot.MC_BURY is False
    assert bot.shortlist_config is config
    before = bot.rng.getstate()
    played = bot.decide_bury(rnd, rnd.banker)
    assert played == incumbent
    assert bot.rng.getstate() == before
    assert bot.last_bury_record["picked_index"] == 0
    assert bot.last_bury_record["shortlist"] == [0]


def test_inherited_w32_play_smoke_after_bury():
    rnd = _bury_state(21)
    bot = make_cwv_bury_bot(_Evaluator(), seed=41, arm="heuristic")
    rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
    played = bot.decide_play(rnd, rnd.turn)
    assert played and bot.shortlist_config.worlds == 32


def test_hybrid_maps_local_pick_and_keeps_incumbent(monkeypatch):
    rnd = _bury_state(9)
    incumbent = list(SmartBot().decide_bury(rnd, rnd.banker))
    candidates = [incumbent] + [list(rnd.hands[rnd.banker][i:i + 8])
                                for i in (8, 16, 24, 1, 2)]
    monkeypatch.setattr("shengji.train.cwv_bury_policy.bury_candidates",
                        lambda _rnd, _bot: copy.deepcopy(candidates))
    helpers = []

    def make(_name, *, seed):
        helper = _Helper(seed)
        helpers.append(helper)
        return helper

    worlds = [("w",)] * 32
    monkeypatch.setattr("shengji.train.cwv_bury_policy.make_bot", make)
    monkeypatch.setattr("shengji.train.cwv_bury_policy.sample_worlds",
                        lambda bot, _rnd, _seat, n: (list(worlds[:n]), n))
    # Candidate 2 ranks first, then stable-index order fills the shortlist.
    means = np.asarray([[0, 1, 9, 2, 3, 4, 5]], dtype=float)
    monkeypatch.setattr(
        "shengji.train.cwv_bury_policy.score_bury_candidates",
        lambda *_args, **_kwargs: np.repeat(means, 32, axis=0))
    seen = {}

    def roll(_rnd, local, sampled, _bot):
        seen["local"] = [list(c) for c in local]
        seen["worlds"] = sampled
        # local index 1 is global candidate 2; it must be returned as 2.
        points = np.tile(np.arange(10, 10 + len(local), dtype=np.int64), (32, 1))
        points[:, 1] = 0
        return np.zeros((32, len(local))), points

    monkeypatch.setattr("shengji.train.cwv_bury_policy.rollout_bury_values", roll)
    bot = make_cwv_bury_bot(_Evaluator(), CWVShortlistConfig(worlds=32),
                            seed=13, arm="hybrid")
    played = bot.decide_bury(rnd, rnd.banker)
    assert played == candidates[2]
    assert bot.last_bury_record["shortlist"] == [0, 2, 3, 4, 5]
    assert bot.last_bury_record["picked_index"] == 2
    assert seen["local"] == [candidates[i] for i in [0, 2, 3, 4, 5]]
    assert len(seen["worlds"]) == 32


def test_mc_and_hybrid_have_same_mc_worlds_without_round_mutation(monkeypatch):
    rnd = _bury_state(11)
    original = copy.deepcopy((rnd.phase, rnd.turn, rnd.hands, rnd.buried,
                              rnd.history, rnd.trick))
    incumbent = list(SmartBot().decide_bury(rnd, rnd.banker))
    candidates = [incumbent] + [list(rnd.hands[rnd.banker][i:i + 8])
                                for i in (8, 16, 24)]
    monkeypatch.setattr("shengji.train.cwv_bury_policy.bury_candidates",
                        lambda _rnd, _bot: copy.deepcopy(candidates))
    monkeypatch.setattr("shengji.train.cwv_bury_policy.make_bot",
                        lambda _name, *, seed: _Helper(seed))
    sampled = []

    def worlds(bot, _rnd, _seat, n):
        value = (bot.seed, n)
        sampled.append(value)
        return ([(value,)] * n, n)

    monkeypatch.setattr("shengji.train.cwv_bury_policy.sample_worlds", worlds)
    monkeypatch.setattr(
        "shengji.train.cwv_bury_policy.score_bury_candidates",
        lambda _rnd, local, _worlds, _evaluator, **_kwargs:
        np.zeros((32, len(local))))
    monkeypatch.setattr(
        "shengji.train.cwv_bury_policy.rollout_bury_values",
        lambda _rnd, local, ws, _bot: (
            np.zeros((len(ws), len(local))),
            np.zeros((len(ws), len(local)), dtype=np.int64)))
    config = CWVShortlistConfig(worlds=32)
    mc = make_cwv_bury_bot(_Evaluator(), config, seed=99, arm="mc")
    hybrid = make_cwv_bury_bot(_Evaluator(), config, seed=99, arm="hybrid")
    assert mc.shortlist_config is hybrid.shortlist_config is config
    assert mc.reuse_successors is hybrid.reuse_successors is True
    mc.decide_bury(rnd, rnd.banker)
    hybrid.decide_bury(rnd, rnd.banker)
    assert sampled[0] == sampled[-1]  # MC stream is shared by both arms.
    assert sampled[0][0] != sampled[1][0]  # model and MC streams are independent.
    assert (rnd.phase, rnd.turn, rnd.hands, rnd.buried, rnd.history, rnd.trick) == original


def test_sample_underfill_and_wrong_seat_refuse(monkeypatch):
    rnd = _bury_state(12)
    bot = make_cwv_bury_bot(_Evaluator(), seed=5, arm="mc")
    with np.testing.assert_raises(BuryPolicyError):
        bot.decide_bury(rnd, (rnd.banker + 1) % 4)
    monkeypatch.setattr(
        "shengji.train.cwv_bury_policy.sample_worlds",
        lambda *_args, **_kwargs: ([], 32))
    with np.testing.assert_raises(BuryPolicyError):
        bot.decide_bury(rnd, rnd.banker)
