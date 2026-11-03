"""Decision identity of the served bot's degradation telemetry
(``world_draws_by_stage``, ``belief_fallback_by_stage``, the history fill
split, ``leaf_greedy_deadline_fired_lead_confirm``, the bury record reset).

The telemetry only reads what the search already computed.  Witness: a fixed
set of seeded decisions (leads and follows with the history-legal draw and the
lead confirmation, with adaptive worlds, with the belief proposal; burys;
declarations) plays the same cards and leaves every RNG stream in the same
state as the code before the telemetry, pinned as one digest per fixture.
A digest changes only when a decision or an RNG draw changes.
"""
import copy
import hashlib
import json
import sys

import pytest

from shengji.ai import belief_numpy as bn
from shengji.ai.heuristic import HeuristicBot
from shengji.train import pv_search_policy as pv
from test_cwv_bury_wide_value import served_bury
from test_cwv_leaf_policy_first_trick import bury_state
from test_policy_world_search import state
from test_pv_belief_worlds import package  # noqa: F401
from test_pv_declare_served_bury import bot as declare_bot
from test_pv_doomed_throw_reselect import HashNoiseEvaluator
from test_pv_lead_confirm import OutsideBallotEvaluator, short_loving_scores
from test_pv_leaf_greedy_finish import R46_RULES, leaf_bot
from test_pv_value_declare import drive
from test_world_history_legal import served

#: decisions per play fixture: the self-play continues from ``state()`` with
#: the bot at every seat, so leads and follows alternate
PLAYS = 16

#: taken on the code before the telemetry (origin/main fa8301a4), pure and
#: compiled engines alike
GOLDEN = {
    "play_whl_lcc": "63a8bdd79d7155e9c4014bcde26185766ec5757f8d6432338b59b5e276fb6cb8",
    "play_whl_adaptive": "6bab4f929809a6c4449cf4bfd0361a21e3283b2e496bc58cb86a2ecc2b5a04f6",
    "play_belief_lcc": "0b3ebc6867eae0d31bb6a1af94cf3b16017d1c8d5e74b42056d0ce234aed3fe2",
    "bury_wide": "05839e2300259b22d4a1c3e95e72eb1b104730bea4379a949a2af3319e2540e8",
    "declare_vd": "3fd2c9a9ca678b31395dd6a3c69f8cb00d48db4e006384b3971b2a03cf6b3723",
}


def _digest(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def _rng(rng):
    return hashlib.sha256(repr(rng.getstate()).encode()).hexdigest()[:16]


def _play_rows(bot, plays=PLAYS):
    rnd = copy.deepcopy(state())
    rows = []
    while rnd.phase == "play" and len(rows) < plays:
        seat = rnd.turn
        lead = not rnd.trick.plays
        cards = bot.decide_play(copy.deepcopy(rnd), seat)
        rows.append([seat, lead, sorted(cards), _rng(bot.sampler.rng)])
        rnd.play(seat, cards)
    assert any(r[1] for r in rows) and not all(r[1] for r in rows)
    return rows


def play_whl_lcc():
    bot = leaf_bot(OutsideBallotEvaluator(1.0), worlds=8, world_history_legal=True,
                   world_history_draw=True, lead_confirm=24, **R46_RULES)
    bot.scores = short_loving_scores
    return _play_rows(bot)


def play_whl_adaptive():
    bot = served(worlds=8, world_history_legal=True, world_history_draw=True,
                 adaptive_worlds=True)
    bot.evaluator = HashNoiseEvaluator()
    return _play_rows(bot)


def play_belief_lcc(package):
    bot = leaf_bot(OutsideBallotEvaluator(1.0), worlds=8, world_history_legal=True,
                   world_history_draw=True, belief_worlds=True,
                   belief_sha256=package["sha256"], lead_confirm=24, **R46_RULES)
    bot.belief_model = bn.load_belief_numpy(package["path"], package["sha256"])
    bot.scores = short_loving_scores
    return _play_rows(bot)


def bury_wide():
    rows = []
    for index in (0, 1, 2):
        bot = served_bury(bury_wide_value=True, bury_wide_k=16)
        rnd = bury_state(index)
        cards = bot.decide_bury(copy.deepcopy(rnd), rnd.banker)
        rows.append([index, sorted(cards), _rng(bot._bury_rng()), _rng(bot.sampler.rng)])
    return rows


def declare_vd():
    rows = []
    for seed in (3, 22):
        b = declare_bot()

        def check(before, seat, final, choice, record):
            rows.append([seed, seat, final, choice, _rng(b.sampler.rng)])
        drive(seed, b, check)
    return rows


FIXTURES = {"play_whl_lcc": play_whl_lcc, "play_whl_adaptive": play_whl_adaptive,
            "bury_wide": bury_wide, "declare_vd": declare_vd}


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_decisions_and_rng_streams_match_the_pinned_tape(name):
    assert _digest(FIXTURES[name]()) == GOLDEN[name]


def test_belief_decisions_and_rng_stream_match_the_pinned_tape(package):
    assert _digest(play_belief_lcc(package)) == GOLDEN["play_belief_lcc"]


if __name__ == "__main__":
    # prints the digests (run on the code whose decisions the tape pins)
    out = {name: _digest(fn()) for name, fn in sorted(FIXTURES.items())}
    print(json.dumps(out, indent=1), file=sys.stdout)
