"""The OPTIONAL epsilon tie-break by trick points in the pv-search bot's final
selection (#676 E, #677 strategy 2): ``tiebreak_points``.

Torch-free: a stub predictor and a deterministic stub evaluator on the real
fixture round, the real legal enumeration, the real engine and the real trick
finisher.

Witnesses: (a) OFF, the harness and the served wrapper select exactly the
argmax of the value means and the record carries no tie-break key; (b) two
candidates within epsilon where the second concedes fewer points -- the second
is chosen and the record says so, the points being the engine's own resolved
trick points signed for the root team and summed over the sampled worlds;
(c) outside epsilon the argmax is unchanged and nothing is rebuilt; (d) the
production registry name is unchanged when off and carries ``-tb`` when on;
(e) the env flag refuses anything but 0/1; a points tie keeps the argmax.
"""
import copy

import numpy as np
import pytest

from shengji.ai.cwv_policy import afterstate
from shengji.ai.heuristic import HeuristicBot
from shengji.harvest.legal import enumerate_legal
from shengji.train import policy_value_search as module
from shengji.train import pv_search_policy as pv
from shengji.train.policy_value_search import PolicyValueBot
from test_policy_world_search import state
from test_pv_admission_rules import (PRODUCTION_ENV, PRODUCTION_NAME, PRODUCTION_SHA,
                                     crafted_preferences, predict,
                                     production_package)  # noqa: F401  (fixture)

EPS = module.TIEBREAK_DEFAULTS["tiebreak_epsilon"]


class RankEvaluator:
    """Deterministic, non-constant: a leaf scores by the mover's remaining hand
    size and the trick count, so the argmax is a real (if meaningless) choice."""
    backend = "numpy"
    max_batch = 128

    def score(self, leaves, seat):
        return np.array([len(r.hands[seat]) * 0.01 + len(r.history) * 0.001
                         + sum(len(h) for h in r.hands) * 1e-4 for r in leaves])


def harness(evaluator=None, **rules):
    return PolicyValueBot(predict, evaluator=RankEvaluator() if evaluator is None else evaluator,
                          worlds=2, candidates=8, cap=4000, seed=17, **rules)


def served(**rules):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=2, candidates=8,
                               cap=4000, batch_size=128, **rules)
    return pv.PVSearchBot(predict, evaluator=RankEvaluator(), version=2, config=config,
                          checkpoint="/dev/null", seed=17)


def last_position():
    """The fixture round walked by the heuristic to the first decision where the
    mover is LAST to play and its legal singles differ in trick points: seat 3,
    an attacker void in clubs, dumping into the banker's CA lead that already
    carries D10."""
    rnd = state()
    h = HeuristicBot()
    for _ in range(7):                        # trick 1 and three plays of trick 2
        rnd.play(rnd.turn, h.decide_play(rnd, rnd.turn))
    assert rnd.banker == 0 and rnd.turn == 3 and rnd.is_attacker(3)
    assert [p.cards for p in rnd.trick.plays] == [["CA"], ["C6"], ["D10"]]
    return rnd


def engine_points(rnd, seat, action, hands=None):
    """The test's own reading of the engine: play ``action`` (in ``hands`` or the
    live deal), finish the trick with the heuristic, sign the trick's points."""
    hands = rnd.hands if hands is None else hands
    leaf = afterstate(rnd, seat, hands, rnd.buried, list(action), finish_trick=True)
    trick = leaf.last_trick
    assert len(leaf.history) == len(rnd.history) + 1 and trick.winner is not None
    return trick.points if rnd.is_attacker(trick.winner) == rnd.is_attacker(seat) else -trick.points


# ------------------------------------------------------- (a) off == before

def test_off_selects_the_plain_argmax_and_carries_no_tiebreak_key():
    for build in (harness, served):
        for rnd in (state(), last_position()):
            seat = rnd.turn
            bot = build()
            assert bot.tiebreak_points is False
            played = bot.decide_play(copy.deepcopy(rnd), seat)
            record = bot.last_decision_record
            means = record["value_means"]
            argmax = int(np.argmax(means))
            assert record["selected_index"] == record["admitted_indices"][argmax]
            if "admitted" in record:                  # the served record
                assert played == record["admitted"][argmax]
            legal = enumerate_legal(rnd, seat, cap=4000)
            assert played == list(legal.actions[record["selected_index"]])
            assert not {"tiebreak_applied", "tiebreak_near_set", "tiebreak_points"} & set(record)
    # the hook itself, off: the argmax, the sampled worlds never needed
    bot = harness()
    assert bot._select(None, 0, [["S2"], ["S3"]], np.array([0.1, 0.1 + EPS / 2])) == 1
    assert bot._tiebreak_record() == {}


# ------------------------------------------------------- (b) within epsilon

def test_within_epsilon_the_candidate_conceding_fewer_points_wins_and_is_recorded():
    rnd = last_position(); seat = rnd.turn
    worse, better = ["DK"], ["D6"]            # DK dumps 10 more points into a lost trick
    assert engine_points(rnd, seat, worse) == -20 and engine_points(rnd, seat, better) == -10
    bot = harness(tiebreak_points=True)
    worlds, _ = bot._worlds(rnd, seat)
    # the hook: argmax is the point dump by less than epsilon; the dump loses
    admitted = [["H4"], worse, better]
    means = np.array([0.40, 0.50, 0.50 - EPS / 2])
    assert bot._select(rnd, seat, admitted, means, worlds=worlds) == 2
    record = bot._tiebreak_record()
    assert record == {"tiebreak_applied": True, "tiebreak_near_set": [1, 2],
                      "tiebreak_points": [-20.0, -10.0]}
    # the whole decision: both admitted, the crafted means put the dump on top
    legal = enumerate_legal(rnd, seat, cap=4000)
    worse_index, better_index = legal.actions.index(worse), legal.actions.index(better)
    crafted_preferences(bot, rnd, seat, [worse_index, better_index])

    def value_means(rnd_, seat_, admitted_, worlds_):
        means = np.full(len(admitted_), -1.0)
        means[admitted_.index(worse)] = 0.5
        means[admitted_.index(better)] = 0.5 - EPS / 2
        return means, 1
    bot._value_means = value_means
    assert bot.decide_play(copy.deepcopy(rnd), seat) == better
    record = bot.last_decision_record
    chosen = record["admitted_indices"]
    assert record["selected_index"] == better_index
    assert record["tiebreak_applied"] is True
    assert record["tiebreak_near_set"] == sorted([chosen.index(worse_index), chosen.index(better_index)])
    assert sorted(record["tiebreak_points"]) == [-20.0, -10.0]
    # the served wrapper's record carries the same keys
    bot2 = served(tiebreak_points=True)
    crafted_preferences(bot2, rnd, seat, [worse_index, better_index])
    bot2._value_means = lambda rnd_, seat_, admitted_, worlds_, check_budget=None: value_means(rnd_, seat_, admitted_, worlds_)
    assert bot2.decide_play(copy.deepcopy(rnd), seat) == better
    assert bot2.last_decision_record["tiebreak_applied"] is True
    assert bot2.last_decision_record["selected_index"] == better_index


def test_points_are_the_engine_trick_points_summed_over_the_sampled_worlds():
    """A LEAD: the finisher's follows depend on each world's hidden hands, so the
    recorded points are the mean over the worlds of the test's own engine reading."""
    rnd = state(); seat = rnd.turn
    assert not rnd.trick.plays
    bot = harness(tiebreak_points=True)
    worlds, _ = bot._worlds(rnd, seat)
    legal = enumerate_legal(rnd, seat, cap=4000)
    admitted = [list(a) for a in legal.actions[:4]]
    expected = [np.mean([engine_points(rnd, seat, a, hands) for hands, _ in worlds]) for a in admitted]
    means = np.zeros(4)                       # every candidate in the near-set
    winner = bot._select(rnd, seat, admitted, means, worlds=worlds)
    record = bot._tiebreak_record()
    assert record["tiebreak_near_set"] == [0, 1, 2, 3]
    assert record["tiebreak_points"] == expected
    best = max(expected)
    assert expected[winner] == best
    assert winner == (0 if expected[0] == best else expected.index(best))
    assert record["tiebreak_applied"] is (winner != 0)
    assert rnd.hands == state().hands          # pure


# ------------------------------------------------------- (c) outside epsilon

def test_outside_epsilon_the_argmax_stands_and_nothing_is_rebuilt():
    rnd = last_position(); seat = rnd.turn
    bot = harness(tiebreak_points=True)
    worlds, _ = bot._worlds(rnd, seat)
    rebuilt = []
    original = bot._leaf
    bot._leaf = lambda *a: rebuilt.append(a) or original(*a)
    means = np.array([0.40, 0.50, 0.50 - EPS * 1.5])
    assert bot._select(rnd, seat, [["H4"], ["DK"], ["D6"]], means, worlds=worlds) == 1
    assert bot._tiebreak_record() == {"tiebreak_applied": False, "tiebreak_near_set": [1],
                                      "tiebreak_points": []}
    assert rebuilt == []
    # exactly at the boundary is inside the near-set
    means = np.array([0.40, 0.50, 0.50 - EPS])
    assert bot._select(rnd, seat, [["H4"], ["DK"], ["D6"]], means, worlds=worlds) == 2
    assert len(rebuilt) == 2 * len(worlds)


def test_an_exact_points_tie_keeps_the_argmax_then_admission_order():
    rnd = last_position(); seat = rnd.turn
    bot = harness(tiebreak_points=True)
    worlds, _ = bot._worlds(rnd, seat)
    assert engine_points(rnd, seat, ["D6"]) == engine_points(rnd, seat, ["H4"]) == -10
    admitted = [["H4"], ["D6"], ["D8"]]
    assert bot._select(rnd, seat, admitted, np.array([0.5 - EPS / 2, 0.5, 0.5 - EPS / 3]), worlds=worlds) == 1
    assert bot._tiebreak_record()["tiebreak_applied"] is False
    assert bot._tiebreak_record()["tiebreak_points"] == [-10.0, -10.0, -10.0]
    # the argmax loses on points; the two remaining tie -> admission order
    admitted = [["D6"], ["DK"], ["D8"]]
    assert bot._select(rnd, seat, admitted, np.array([0.5 - EPS / 2, 0.5, 0.5 - EPS / 3]), worlds=worlds) == 0


def test_the_hook_refuses_to_run_without_worlds_and_bad_parameters_are_refused():
    bot = harness(tiebreak_points=True)
    with pytest.raises(ValueError, match="sampled worlds"):
        bot._select(None, 0, [["S2"], ["S3"]], np.array([0.1, 0.1]))
    for bad in (1, "1", None):
        with pytest.raises(ValueError, match="must be a bool"):
            harness(tiebreak_points=bad)
    for bad in (-0.01, float("nan"), float("inf"), "0.02"):
        with pytest.raises(ValueError, match="tiebreak_epsilon"):
            harness(tiebreak_epsilon=bad)
    assert harness(tiebreak_epsilon=0).tiebreak_epsilon == 0.0


# ------------------------------------------------------- (d) registry names

def names(env):
    return list(pv.pv_registry_entries(**pv.pv_env_recipe(env)))


def test_production_name_unchanged_when_off_and_tb_token_when_on(production_package):
    assert names(PRODUCTION_ENV) == [PRODUCTION_NAME]
    assert names({**PRODUCTION_ENV, "SHENGJI_PV_TIEBREAK_POINTS": "0"}) == [PRODUCTION_NAME]
    tb, = names({**PRODUCTION_ENV, "SHENGJI_PV_TIEBREAK_POINTS": "1"})
    assert tb.startswith("pv-search-491ee4bf-w64-k8-tb-r") and "-bury-hybrid-" in tb
    assert tb != PRODUCTION_NAME
    both, = names({**PRODUCTION_ENV, "SHENGJI_PV_ADMISSION_DIVERSITY": "1",
                   "SHENGJI_PV_TIEBREAK_POINTS": "1"})
    assert both.startswith("pv-search-491ee4bf-w64-k8-div-tb-r")
    config = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0)
    assert pv.recipe_digest(config) == "4a09aef5"
    assert not {"tiebreak_points", "tiebreak_epsilon"} & set(pv.recipe_payload(config))
    on = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                           tiebreak_points=True)
    payload = pv.recipe_payload(on)
    assert payload["tiebreak_points"] is True and payload["tiebreak_epsilon"] == EPS
    assert pv.recipe_digest(on) != "4a09aef5"
    with pytest.raises(pv.PVSearchPolicyError, match="must be a bool"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, tiebreak_points="1"))
    # the served bot built from the config carries the flag
    assert served(tiebreak_points=True).tiebreak_points is True
    assert served().tiebreak_points is False


# ------------------------------------------------------- (e) env flag

@pytest.mark.parametrize("bad", ["2", "true", "yes", "on", " 1", "0.0"])
def test_env_recipe_refuses_anything_but_0_or_1(bad):
    with pytest.raises(pv.PVSearchPolicyError, match="TIEBREAK_POINTS must be 0 or 1"):
        pv.pv_env_recipe({**PRODUCTION_ENV, "SHENGJI_PV_TIEBREAK_POINTS": bad})
    assert "tiebreak_points" not in pv.pv_env_recipe({**PRODUCTION_ENV, "SHENGJI_PV_TIEBREAK_POINTS": ""})
    assert "tiebreak_points" not in pv.pv_env_recipe({**PRODUCTION_ENV, "SHENGJI_PV_TIEBREAK_POINTS": "0"})
    assert pv.pv_env_recipe({**PRODUCTION_ENV, "SHENGJI_PV_TIEBREAK_POINTS": "1"})["tiebreak_points"] is True
