"""The two data-generation hooks on `PVSearchBot._search` (#592): the scored set and the
admission.  Serving is byte-for-byte unchanged; a subclass can widen the scored set and
append candidates beyond K, which the value head then prices; the record carries the
admitted cards and the policy log-odds so a trajectory record never re-derives them."""
import copy
import random

import numpy as np
import pytest

from shengji.ai.env import prepare_round
from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.train import pv_search_policy as pv
from test_pv_search_serving import package  # noqa: F401

SMALL = dict(worlds=3, candidates=4, cap=400, batch_size=16)


def _state(seed=7):
    game = Game(random.Random(seed))
    prepare_round(game, [HeuristicBot() for _ in range(4)])
    rnd = game.round
    # walk to a seat with more than K legal plays so admission actually selects
    bots = [HeuristicBot() for _ in range(4)]
    from shengji.harvest.legal import enumerate_legal
    while rnd.phase == "play":
        legal = enumerate_legal(rnd, rnd.turn, cap=64)
        if len(legal.actions) > 8:
            return rnd
        rnd.play(rnd.turn, bots[rnd.turn].decide_play(rnd, rnd.turn))
    raise AssertionError("no wide decision in this deal")


def test_default_hooks_reproduce_the_served_decision_and_record_the_ballot(package):
    path, sha = package
    rnd = _state()
    seat = rnd.turn
    a = pv.make_pv_search_bot(path, sha256=sha, seed=3, **SMALL)
    b = pv.make_pv_search_bot(path, sha256=sha, seed=3, **SMALL)
    play_a = a.decide_play(copy.deepcopy(rnd), seat)
    play_b = b.decide_play(copy.deepcopy(rnd), seat)
    assert play_a == play_b
    rec = a.last_decision_record
    assert rec["schema"] == "pv-search-decision-v1"
    assert rec["admitted"] == [list(x) for x in rec["admitted"]] and len(rec["admitted"]) == len(rec["admitted_indices"]) <= SMALL["candidates"]
    assert rec["played"] == rec["admitted"][rec["admitted_indices"].index(rec["selected_index"])]
    assert len(rec["policy_log_odds_admitted"]) == len(rec["admitted"])
    assert len(rec["policy_log_odds_listing"]) == min(rec["actions"], 256)
    anchor = HeuristicBot().decide_play(copy.deepcopy(rnd), seat)
    assert sorted(rec["admitted"][0]) == sorted(anchor)                    # the anchor is admitted first
    assert all(np.isfinite(rec["policy_log_odds_listing"])) and rec["legal_count"] >= rec["actions"]


def test_an_admission_override_can_append_a_candidate_beyond_k_and_it_is_priced(package):
    """Codex #592 (1): a winner whose legal index exceeds K, in a non-sorted admitted order,
    must map through admitted_indices.index(selected_index), not the legal index."""
    path, sha = package
    rnd = _state()
    seat = rnd.turn
    seen = {}

    class Widened(pv.PVSearchBot):
        def _admit(self, rnd, seat, actions, preferences, anchor_index):
            base = super()._admit(rnd, seat, actions, preferences, anchor_index)
            extra = max(i for i in range(len(actions)) if i not in base)   # the last legal index
            seen["extra"] = extra
            return [base[0]] + base[1:][::-1] + [extra]                   # anchor first, rest unsorted

    bot = pv.make_pv_search_bot(path, sha256=sha, seed=3, **SMALL)
    bot.__class__ = Widened
    played = bot.decide_play(copy.deepcopy(rnd), seat)
    rec = bot.last_decision_record
    assert len(rec["admitted_indices"]) == SMALL["candidates"] + 1 and rec["admitted_indices"][-1] == seen["extra"]
    assert len(rec["value_means"]) == SMALL["candidates"] + 1               # the extra candidate was priced
    assert rec["value_evaluations"] == rec["worlds"] * (SMALL["candidates"] + 1)
    assert rec["admitted_indices"] != sorted(rec["admitted_indices"])       # not a sorted order
    pos = rec["admitted_indices"].index(rec["selected_index"])
    assert rec["admitted"][pos] == played == rec["played"]


def test_a_scored_set_override_can_force_a_candidate_in(package):
    path, sha = package
    rnd = _state()
    seat = rnd.turn
    from shengji.harvest.legal import enumerate_legal
    full = enumerate_legal(rnd, seat, cap=None)
    wanted = [list(a) for a in full.actions][-1]

    class Forced(pv.PVSearchBot):
        def _legal(self, rnd, seat, must_include):
            return super()._legal(rnd, seat, list(must_include) + [wanted])

    bot = pv.make_pv_search_bot(path, sha256=sha, seed=3, **SMALL)
    bot.__class__ = Forced
    bot.decide_play(copy.deepcopy(rnd), seat)
    rec = bot.last_decision_record
    assert rec["actions"] >= 1 and rec["legal_count"] == full.count


def test_a_malformed_admission_is_refused_and_falls_back_under_a_budget(package):
    path, sha = package
    rnd = _state()
    seat = rnd.turn

    class Bad(pv.PVSearchBot):
        def _admit(self, rnd, seat, actions, preferences, anchor_index):
            return [anchor_index, anchor_index]                              # duplicate

    bot = pv.make_pv_search_bot(path, sha256=sha, seed=3, serving_budget_seconds=30, **SMALL)
    bot.__class__ = Bad
    played = bot.decide_play(copy.deepcopy(rnd), seat)
    assert bot.last_decision_record["schema"] == "pv-search-fallback-v1"
    assert bot.last_decision_record["reason"] == "search-error" and played
    bot2 = pv.make_pv_search_bot(path, sha256=sha, seed=3, **SMALL)
    bot2.__class__ = Bad
    with pytest.raises(pv.PVSearchPolicyError):
        bot2.decide_play(copy.deepcopy(rnd), seat)                         # no budget: the harness sees it
