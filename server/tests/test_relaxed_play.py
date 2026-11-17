"""Relaxed opponents (`train.relaxed_play`): off by default, served declare/bury, legal and repeatable
relaxed play, and a near-best draw that never leaves its value window."""
from __future__ import annotations

import random
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from shengji.ai import belief_numpy as bn
from shengji.ai import unified_numpy as un
from shengji.ai.env import play_prepared_round, prepare_round
from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.harvest.legal import enumerate_legal
from shengji.train import relaxed_play as rp
from shengji.train import search_free_play as sf

SERVER = Path(__file__).resolve().parents[1]


def test_nothing_imports_relaxed_play_by_default():
    code = ("import sys, shengji.ai.registry, shengji.api.server; "
            "print('shengji.train.relaxed_play' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], cwd=SERVER, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_near_best_zero_tau_is_the_argmax_or_the_kept_choice():
    rng = random.Random(0)
    assert rp.near_best([0.1, 0.5, 0.5, 0.2], 0.0, 0.0, rng) == 1
    assert rp.near_best([0.1, 0.5, 0.5, 0.2], 0.0, 0.0, rng, keep=3) == 3
    assert rp.near_best([0.9, 0.5], 0.0, 0.0, rng, allowed=[False, True]) == 1


def test_near_best_stays_inside_delta_and_allowed():
    rng = random.Random(1)
    v = [1.0, 0.95, 0.5, 0.99, -3.0]
    picks = {rp.near_best(v, 0.5, 0.1, rng, allowed=[True, True, True, False, True]) for _ in range(500)}
    assert picks == {0, 1}


def test_near_best_is_repeatable_and_tracks_tau():
    v = [0.0, -0.2, -0.4]
    a = [rp.near_best(v, 0.2, 0.0, random.Random(7)) for _ in range(3)]
    assert len(set(a)) == 1
    rng_lo, rng_hi = random.Random(3), random.Random(3)
    lo = sum(rp.near_best(v, 0.05, 0.0, rng_lo) == 0 for _ in range(400))
    hi = sum(rp.near_best(v, 5.0, 0.0, rng_hi) == 0 for _ in range(400))
    assert lo > 380 and hi < 200


def test_near_best_refuses_bad_values():
    with pytest.raises(rp.RelaxedPlayError):
        rp.near_best([float("nan")], 1.0, 0.0, random.Random(0))
    with pytest.raises(rp.RelaxedPlayError):
        rp.RelaxedBot(HeuristicBot(), HeuristicBot(), mode="search", tau=-1.0)
    with pytest.raises(rp.RelaxedPlayError):
        rp.RelaxedBot(HeuristicBot(), HeuristicBot(), mode="other")
    with pytest.raises(rp.RelaxedPlayError):
        rp.level_spec("nope")


class _Served(HeuristicBot):
    def __init__(self):
        self.calls = []
        self.observed = 0
        self.policy_name = "served"

    def decide_declare(self, rnd, seat, final=False):
        self.calls.append("declare")
        return HeuristicBot.decide_declare(self, rnd, seat, final=final)

    def decide_bury(self, rnd, seat):
        self.calls.append("bury")
        return HeuristicBot.decide_bury(self, rnd, seat)

    def decide_play(self, rnd, seat):
        raise AssertionError("the served bot of a relaxed seat never plays")

    def observe_public(self, rnd):
        self.observed += 1


class _SearchPlayer(HeuristicBot):
    """A search stand-in: plays the legal play with the best made-up value and leaves a pv-search record."""

    def __init__(self):
        self.observed = 0
        self.policy_name = "player"
        self.last_decision_record = None

    def observe_public(self, rnd):
        self.observed += 1

    def decide_play(self, rnd, seat):
        anchor = HeuristicBot.decide_play(self, rnd, seat)
        actions = [list(a) for a in enumerate_legal(rnd, seat, cap=64, must_include=[anchor]).actions][:6]
        key = tuple(sorted(anchor))
        actions.sort(key=lambda a: tuple(sorted(a)) != key)
        means = [0.1 * ((len(rnd.history) * 7 + i * 3) % 5) for i in range(len(actions))]
        win = int(np.argmax(means))
        self.last_decision_record = {"schema": "pv-search-decision-v1", "admitted": actions,
                                     "admitted_indices": list(range(len(actions))), "selected_index": win,
                                     "value_means": means, "worlds": 4}
        return list(actions[win])


def _round(make, seed):
    bots = [make(seat) for seat in range(4)]
    game = Game(random.Random(seed))
    prepare_round(game, bots)
    log = play_prepared_round(game, bots, record=True)
    return bots, log


def test_search_mode_at_zero_tau_plays_the_players_choice_and_served_declares():
    def make(seat):
        if seat % 2:
            return HeuristicBot()
        return rp.RelaxedBot(_Served(), _SearchPlayer(), mode="search", tau=0.0, seed=seat)
    bots, log = _round(make, 11)

    def make_plain(seat):
        if seat % 2:
            return HeuristicBot()
        player = _SearchPlayer()

        class Seat(HeuristicBot):
            def decide_play(self, rnd, s):
                return player.decide_play(rnd, s)
        return Seat()
    _, plain = _round(make_plain, 11)
    assert log.history == plain.history
    for b in bots[::2]:
        assert "declare" in b.served.calls
        assert b.relaxed_redrawn == 0 and b.relaxed_decisions > 0
        assert b.last_decision_record["schema"] == "pv-search-decision-v1"


def test_search_mode_redraw_is_legal_in_window_and_repeatable():
    def make(seat):
        return rp.RelaxedBot(_Served(), _SearchPlayer(), mode="search", tau=1.0, delta=0.15, seed=seat)
    bots, log = _round(make, 12)
    _, again = _round(make, 12)
    assert log.history == again.history
    assert sum(b.relaxed_redrawn for b in bots) > 0
    for b in bots:
        rec = b.last_decision_record
        if rec.get("relaxed_pick") is not None:
            means = rec["value_means"]
            assert means[rec["relaxed_pick"]] >= max(means) - 0.15 - 1e-12


class _PriorPlayer(HeuristicBot):
    cap = 4000

    def __init__(self):
        self.policy_name = "prior"

    def _legal(self, rnd, seat, must):
        return enumerate_legal(rnd, seat, cap=self.cap, must_include=must)

    def _worlds(self, rnd, seat, check_budget=None):
        return [None, None], 0

    def scores(self, rnd, seat, actions, worlds):
        s = np.array([[float(len(a)) - 0.01 * i for i, a in enumerate(actions)]] * len(worlds))
        return s


@pytest.mark.parametrize("tau", [0.0, 1.0])
def test_prior_mode_plays_legal_safe_plays(tau):
    def make(seat):
        return rp.RelaxedBot(_Served(), _PriorPlayer(), mode="prior", tau=tau, delta=4.0, seed=seat)
    bots, log = _round(make, 13)
    for b in bots:
        assert b.relaxed_decisions > 0
        assert b.last_decision_record["schema"] == rp.RECORD_SCHEMA


SMALL = {"d": 16, "heads": 4, "enc_layers": 1, "xattn_layers": 1, "x_hidden": 16, "card_self_attn": True}
CONFIG = {"trunk": SMALL, "heads": {"q_hidden": 8, "policy_hidden": 8}}


@pytest.fixture(scope="module")
def sf_model(tmp_path_factory):
    rng = np.random.default_rng(5)

    def w(shapes):
        return {k: (0.3 * rng.standard_normal(s)).astype(np.float32) for k, s in shapes.items()}
    path = tmp_path_factory.mktemp("sf") / "sf.npz"
    sha = sf.save_package(path, CONFIG, w(bn.expected_shapes(SMALL, **bn.DIMS)), w(un.head_shapes(CONFIG)),
                          w(sf.cand_shapes(CONFIG)), {"note": "test"})
    return sf.load_package(path, sha256=sha)


def test_search_free_mode_zero_tau_equals_the_search_free_bot(sf_model):
    def relaxed(seat):
        served = _Served()
        return rp.RelaxedBot(served, sf.SearchFreeBot(served, sf_model), mode="search_free", seed=seat)

    def plain(seat):
        return sf.SearchFreeBot(HeuristicBot(), sf_model)
    bots, log = _round(relaxed, 14)
    _, ref = _round(plain, 14)
    assert log.history == ref.history
    assert all(b.served.observed > 0 for b in bots)


def test_search_free_mode_with_tau_is_legal_repeatable_and_redraws(sf_model):
    def relaxed(seat):
        served = _Served()
        return rp.RelaxedBot(served, sf.SearchFreeBot(served, sf_model), mode="search_free", tau=1.0, delta=4.0,
                             seed=seat)
    bots, log = _round(relaxed, 15)
    _, again = _round(relaxed, 15)
    assert log.history == again.history
    assert all(b.last_decision_record["schema"] == rp.RECORD_SCHEMA for b in bots)
