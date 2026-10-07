"""The OPTIONAL lead near-tie tie-break by the policy prior in the pv-search
bot's final selection (#676 online lead review, board A8):
``lead_tiebreak_prior``.

Torch-free: the stub predictor and evaluators of the sibling rule tests on the
real fixture round, the real legal enumeration and the real engine.

Witnesses: (a) OFF, harness and served wrapper select exactly the argmax (or,
with ``tiebreak_points`` on, exactly what that rule selects) and the record
carries no rule key; (b) ON, on a LEAD the near-set candidate with the highest
policy prior is played and recorded; a FOLLOW is untouched; (c) the epsilon
boundary is inclusive, outside it the argmax stands; (d) non-finite means and
non-finite priors never qualify; (e) an exact prior tie keeps the argmax, then
admission order; (f) the anchor has no special status; (g) with
``tiebreak_points`` on as well the rule is ADDITIVE: the points rule runs
first and unchanged, a selection it moves is kept, the prior decides only a
lead where the points rule leaves the argmax in place, and a follow is the
points rule alone -- with the three tactical positions the first draft of this
rule regressed (it replaced the points rule on leads) as regression witnesses;
(h) the record's fields are scalars
and survive the screen trace filter; (i) every existing served name is
byte-identical with the flag off, ``-lp`` when on; (j) no value call, world or
ballot changes; the harvest record still reads.
"""
import copy
import json
import os
import random
from pathlib import Path

import numpy as np
import pytest

from shengji.harvest import trajectory
from shengji.harvest.legal import enumerate_legal
from shengji.train import policy_value_search as module
from shengji.train import pv_search_policy as pv
from shengji.train.policy_value_search import PolicyValueBot
from test_policy_world_search import state
from test_pv_admission_rules import (PRODUCTION_ENV, PRODUCTION_NAME, PRODUCTION_SHA,
                                     ZeroEvaluator, crafted_preferences, names, predict,
                                     production_package)  # noqa: F401  (fixture)
from test_pv_tiebreak_points import RankEvaluator, engine_points, last_position

EPS = module.LEAD_TIEBREAK_DEFAULTS["lead_tiebreak_epsilon"]
RULE_KEYS = {"lead_tiebreak_leading", "lead_tiebreak_applied", "lead_tiebreak_near_count",
             "lead_tiebreak_from_index", "lead_tiebreak_to_index", "lead_tiebreak_from",
             "lead_tiebreak_to", "lead_tiebreak_value_gap"}
FLAG = "SHENGJI_PV_LEAD_TIEBREAK_PRIOR"
# the served names this change must not move (release 36; the confirmed combo
# div+rc+tb; combo + lead-anchor), exactly as the screens served them
COMBO_NAME = "pv-search-491ee4bf-w64-k8-div-rc-tb-rfb4dfc7c-bury-hybrid-9dba7b43087f"
COMBO_LA_NAME = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-r7092480e-bury-hybrid-5517ddbd7457"
COMBO_ENV = {**PRODUCTION_ENV, "SHENGJI_PV_ADMISSION_DIVERSITY": "1",
             "SHENGJI_PV_REFUSAL_CONSTRAINTS": "1", "SHENGJI_PV_TIEBREAK_POINTS": "1"}
COMBO_LA_ENV = {**COMBO_ENV, "SHENGJI_PV_LEAD_ANCHOR": "1"}


def harness(evaluator=None, **rules):
    return PolicyValueBot(predict, evaluator=RankEvaluator() if evaluator is None else evaluator,
                          worlds=2, candidates=8, cap=4000, seed=17, **rules)


def served(evaluator=None, **rules):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=2, candidates=8,
                               cap=4000, batch_size=128, **rules)
    return pv.PVSearchBot(predict, evaluator=RankEvaluator() if evaluator is None else evaluator,
                          version=2, config=config, checkpoint="/dev/null", seed=17)


def lead():
    rnd = state()
    assert module.leading(rnd)
    return rnd


def follow():
    rnd = last_position()
    assert not module.leading(rnd)
    return rnd


ADMITTED = [["S2"], ["S3"], ["S4"], ["S5"]]


def select(bot, rnd, means, priors, admitted=ADMITTED, **kw):
    n = len(means)
    return bot._select(rnd, rnd.turn, admitted[:n], np.array(means, dtype=float),
                       priors=list(priors), **kw)


def test_the_epsilon_is_the_points_rule_constant_on_the_same_scale():
    assert module.LEAD_TIEBREAK_DEFAULTS == {"lead_tiebreak_prior": False,
                                             "lead_tiebreak_epsilon": 0.02}
    assert EPS == module.TIEBREAK_DEFAULTS["tiebreak_epsilon"]


# ------------------------------------------------------- (a) off == before

def test_off_selects_the_plain_argmax_and_carries_no_rule_key():
    for build in (harness, served):
        for rnd in (lead(), follow()):
            seat = rnd.turn
            bot, explicit = build(), build(lead_tiebreak_prior=False)
            assert bot.lead_tiebreak_prior is False
            played = bot.decide_play(copy.deepcopy(rnd), seat)
            assert explicit.decide_play(copy.deepcopy(rnd), seat) == played
            record = bot.last_decision_record
            argmax = int(np.argmax(record["value_means"]))
            assert record["selected_index"] == record["admitted_indices"][argmax]
            legal = enumerate_legal(rnd, seat, cap=4000)
            assert played == list(legal.actions[record["selected_index"]])
            assert not RULE_KEYS & set(record)
            assert not any(k.startswith("lead_tiebreak") for k in record)
    # the hook itself, off: the argmax, neither the round nor the priors needed
    bot = harness()
    assert bot._select(None, 0, [["S2"], ["S3"]], np.array([0.1, 0.1 + EPS / 2])) == 1
    assert bot._select(None, 0, [["S2"], ["S3"]], np.array([0.1 + EPS / 2, 0.1]),
                       priors=[0.0, 99.0]) == 0
    assert bot._lead_tiebreak_record() == {}


def test_off_with_the_points_rule_on_is_the_points_rule_on_a_lead():
    """`-tb` alone DOES act on leads (it prices the trick the finisher
    completes); this rule being off must not change that."""
    rnd = lead(); seat = rnd.turn
    bot = harness(tiebreak_points=True)
    worlds, _ = bot._worlds(rnd, seat)
    legal = enumerate_legal(rnd, seat, cap=4000)
    admitted = [list(a) for a in legal.actions[:4]]
    points = [np.mean([engine_points(rnd, seat, a, hands) for hands, _ in worlds])
              for a in admitted]
    winner = bot._select(rnd, seat, admitted, np.zeros(4), worlds=worlds,
                         priors=[0.0, 1.0, 2.0, 3.0])
    assert points[winner] == max(points)
    record = bot._tiebreak_record()
    assert record["tiebreak_points"] == points and "tiebreak_superseded" not in record


# ------------------------------------------------------- (b) lead vs follow

def test_on_a_lead_the_near_tie_goes_to_the_highest_prior_and_is_recorded():
    rnd = lead()
    bot = harness(lead_tiebreak_prior=True)
    # argmax is 1; 2 is within epsilon and the policy's favourite; 3 has the
    # highest prior of all but is outside epsilon
    assert select(bot, rnd, [0.40, 0.50, 0.50 - EPS / 2, 0.30], [0.0, 1.0, 5.0, 9.0]) == 2
    record = bot._lead_tiebreak_record()
    assert record == {"lead_tiebreak_leading": True, "lead_tiebreak_applied": True,
                      "lead_tiebreak_near_count": 2, "lead_tiebreak_from_index": 1,
                      "lead_tiebreak_to_index": 2, "lead_tiebreak_from": "S3",
                      "lead_tiebreak_to": "S4",
                      "lead_tiebreak_value_gap": pytest.approx(EPS / 2)}
    # the argmax is also the policy's favourite of the near-set: nothing moves
    assert select(bot, rnd, [0.40, 0.50, 0.50 - EPS / 2, 0.30], [0.0, 5.0, 1.0, 9.0]) == 1
    record = bot._lead_tiebreak_record()
    assert record["lead_tiebreak_applied"] is False and record["lead_tiebreak_near_count"] == 2
    assert record["lead_tiebreak_from_index"] == record["lead_tiebreak_to_index"] == 1
    assert record["lead_tiebreak_value_gap"] == 0.0


def test_a_follow_is_untouched():
    rnd = follow()
    bot = harness(lead_tiebreak_prior=True)
    assert select(bot, rnd, [0.40, 0.50, 0.50 - EPS / 2], [0.0, 1.0, 5.0]) == 1
    assert bot._lead_tiebreak_record() == {
        "lead_tiebreak_leading": False, "lead_tiebreak_applied": False,
        "lead_tiebreak_near_count": 0, "lead_tiebreak_from_index": 1,
        "lead_tiebreak_to_index": 1, "lead_tiebreak_from": "S3", "lead_tiebreak_to": "S3",
        "lead_tiebreak_value_gap": 0.0}
    # a follow does not even need the priors
    assert bot._select(rnd, rnd.turn, ADMITTED[:2], np.array([0.1, 0.2])) == 1
    # whole decisions: identical to the rule off, harness and served
    for build in (harness, served):
        off, on = build(), build(lead_tiebreak_prior=True)
        assert off.decide_play(copy.deepcopy(rnd), rnd.turn) == on.decide_play(copy.deepcopy(rnd), rnd.turn)
        a, b = off.last_decision_record, on.last_decision_record
        assert a["admitted_indices"] == b["admitted_indices"]
        assert a["selected_index"] == b["selected_index"] and a["value_means"] == b["value_means"]
        assert b["lead_tiebreak_leading"] is False and b["lead_tiebreak_applied"] is False


# ------------------------------------------------------- (c) epsilon boundary

def test_the_boundary_is_inclusive_and_outside_it_the_argmax_stands():
    rnd = lead()
    bot = harness(lead_tiebreak_prior=True)
    assert select(bot, rnd, [0.40, 0.50, 0.50 - EPS * 1.5], [0.0, 1.0, 5.0]) == 1
    assert bot._lead_tiebreak_record()["lead_tiebreak_near_count"] == 1
    assert bot._lead_tiebreak_record()["lead_tiebreak_applied"] is False
    assert select(bot, rnd, [0.40, 0.50, 0.50 - EPS], [0.0, 1.0, 5.0]) == 2     # exactly at
    assert bot._lead_tiebreak_record()["lead_tiebreak_near_count"] == 2
    assert bot._lead_tiebreak_record()["lead_tiebreak_value_gap"] == pytest.approx(EPS)
    # epsilon 0: only exact value ties are near
    exact = harness(lead_tiebreak_prior=True, lead_tiebreak_epsilon=0)
    assert select(exact, rnd, [0.50, 0.50, 0.50 - 1e-9], [0.0, 1.0, 5.0]) == 1
    assert exact._lead_tiebreak_record()["lead_tiebreak_near_count"] == 2


# ------------------------------------------------------- (d) non-finite

def test_non_finite_means_and_priors_never_qualify():
    rnd = lead()
    bot = harness(lead_tiebreak_prior=True)
    # a -inf mean is outside every near-set, whatever its prior
    assert select(bot, rnd, [0.50, -np.inf, 0.49], [0.0, 100.0, 1.0]) == 2
    assert bot._lead_tiebreak_record()["lead_tiebreak_near_count"] == 2
    # a non-finite argmax (the value pass refuses these; the hook stays inert)
    for bad in (np.nan, np.inf):
        argmax = int(np.argmax(np.array([0.50, bad, 0.49])))
        assert select(bot, rnd, [0.50, bad, 0.49], [0.0, 1.0, 100.0]) == argmax
        record = bot._lead_tiebreak_record()
        assert record["lead_tiebreak_applied"] is False and record["lead_tiebreak_near_count"] == 0
    # a masked prior (the harvest mixin's forced-in exploration draw) is never
    # preferred, even when it is +inf; the finite-rated members still compete
    assert select(bot, rnd, [0.50, 0.49, 0.49], [0.0, np.inf, 1.0]) == 2
    assert select(bot, rnd, [0.50, 0.49, 0.49], [0.0, np.nan, -1.0]) == 0
    # the argmax itself is masked: the best finite-rated near-tie is played
    assert select(bot, rnd, [0.50, 0.49, 0.49], [-np.inf, 1.0, 2.0]) == 2
    # nothing finite-rated: the argmax stands
    assert select(bot, rnd, [0.50, 0.49, 0.49], [-np.inf, -np.inf, np.nan]) == 0
    assert bot._lead_tiebreak_record()["lead_tiebreak_applied"] is False
    assert bot._lead_tiebreak_record()["lead_tiebreak_near_count"] == 3


# ------------------------------------------------------- (e) prior ties

def test_an_exact_prior_tie_keeps_the_argmax_then_admission_order():
    rnd = lead()
    bot = harness(lead_tiebreak_prior=True)
    means = [0.5 - EPS / 2, 0.5, 0.5 - EPS / 3, 0.5 - EPS / 4]
    assert select(bot, rnd, means, [3.0, 3.0, 3.0, 3.0]) == 1          # the argmax
    assert bot._lead_tiebreak_record()["lead_tiebreak_applied"] is False
    assert select(bot, rnd, means, [1.0, 3.0, 3.0, 2.0]) == 1          # argmax among the tied top
    assert select(bot, rnd, means, [1.0, 2.0, 3.0, 3.0]) == 2          # argmax out: admission order
    assert select(bot, rnd, means, [3.0, 2.0, 1.0, 3.0]) == 0
    # deterministic
    assert [select(bot, rnd, means, [1.0, 2.0, 3.0, 3.0]) for _ in range(3)] == [2, 2, 2]


# ------------------------------------------------------- (f) the anchor is not special

def test_the_anchor_slot_has_no_special_status():
    rnd = lead()
    bot = harness(lead_tiebreak_prior=True)
    # the anchor (slot 0) is the argmax; a near-tie the policy prefers replaces it
    assert select(bot, rnd, [0.50, 0.50 - EPS / 2, 0.10], [0.0, 1.0, 9.0]) == 1
    assert bot._lead_tiebreak_record()["lead_tiebreak_from_index"] == 0
    # an exact VALUE tie with the anchor is a near-tie like any other
    assert select(bot, rnd, [0.50, 0.50, 0.10], [0.0, 1.0, 9.0]) == 1
    # the anchor wins only on its own prior
    assert select(bot, rnd, [0.50 - EPS / 2, 0.50, 0.10], [5.0, 1.0, 9.0]) == 0
    assert select(bot, rnd, [0.50 - EPS / 2, 0.50, 0.10], [0.5, 1.0, 9.0]) == 1


# ------------------------------------------------------- (g) both flags: precedence

def stub_points(bot, points):
    """Give the points rule a fixed per-world reading per admitted action (the
    hook is the rule's own `_trick_points`), and count its calls."""
    calls = []

    def trick_points(rnd, seat, hands, buried, action, world_index):
        calls.append(tuple(action))
        return points[tuple(action)]
    bot._trick_points = trick_points
    return calls


def test_a_selection_the_points_rule_moves_is_kept_whatever_the_prior_says():
    rnd = lead(); seat = rnd.turn
    admitted = ADMITTED[:3]
    means = np.array([0.50 - EPS / 2, 0.50, 0.50 - EPS / 3])
    points = {("S2",): 10, ("S3",): -5, ("S4",): 0}
    both = harness(tiebreak_points=True, lead_tiebreak_prior=True)
    only = harness(tiebreak_points=True)
    worlds, _ = both._worlds(rnd, seat)
    stub_points(both, points); stub_points(only, points)
    # the prior prefers S4, then the argmax S3; the points rule moves to S2
    for priors in ([0.0, 1.0, 9.0], [0.0, 9.0, 1.0], [9.0, 1.0, 0.0]):
        assert both._select(rnd, seat, admitted, means, worlds=worlds, priors=priors) == 0
        assert only._select(rnd, seat, admitted, means, worlds=worlds) == 0
        assert both._tiebreak_record() == only._tiebreak_record() == {
            "tiebreak_applied": True, "tiebreak_near_set": [0, 1, 2],
            "tiebreak_points": [10.0, -5.0, 0.0]}
        record = both._lead_tiebreak_record()
        assert record["lead_tiebreak_applied"] is False
        assert record["lead_tiebreak_superseded"] == "tiebreak_points"
        assert record["lead_tiebreak_near_count"] == 3
        assert record["lead_tiebreak_from_index"] == record["lead_tiebreak_to_index"] == 1
        assert record["lead_tiebreak_value_gap"] == 0.0


def test_the_prior_decides_a_lead_the_points_rule_leaves_on_the_argmax():
    rnd = lead(); seat = rnd.turn
    admitted = ADMITTED[:3]
    means = np.array([0.50 - EPS / 2, 0.50, 0.50 - EPS / 3])
    both = harness(tiebreak_points=True, lead_tiebreak_prior=True)
    only = harness(tiebreak_points=True)
    worlds, _ = both._worlds(rnd, seat)
    # (1) the argmax banks the most points; (2) an exact points tie keeps it
    for points in ({("S2",): -5, ("S3",): 10, ("S4",): 0},
                   {("S2",): 10, ("S3",): 10, ("S4",): 10}):
        calls = stub_points(both, points); stub_points(only, points)
        assert only._select(rnd, seat, admitted, means, worlds=worlds) == 1
        assert both._select(rnd, seat, admitted, means, worlds=worlds, priors=[0.0, 1.0, 9.0]) == 2
        assert len(calls) == 3 * len(worlds)               # the points rule DID run, first
        assert both._tiebreak_record() == only._tiebreak_record()
        assert both._tiebreak_record()["tiebreak_applied"] is False
        record = both._lead_tiebreak_record()
        assert record["lead_tiebreak_applied"] is True and "lead_tiebreak_superseded" not in record
        assert (record["lead_tiebreak_from_index"], record["lead_tiebreak_to_index"]) == (1, 2)
        # the prior agrees with the argmax: nothing moves at all
        assert both._select(rnd, seat, admitted, means, worlds=worlds, priors=[0.0, 9.0, 1.0]) == 1
    # (3) a singleton near-set: neither rule has anything to decide
    calls = stub_points(both, {})
    far = np.array([0.1, 0.5, 0.2])
    assert both._select(rnd, seat, admitted, far, worlds=worlds, priors=[9.0, 0.0, 9.0]) == 1
    assert calls == [] and both._lead_tiebreak_record()["lead_tiebreak_near_count"] == 1
    # both rules need their inputs on a lead
    with pytest.raises(ValueError, match="sampled worlds"):
        both._select(rnd, seat, admitted, means, priors=[0.0, 1.0, 9.0])


def test_the_prior_decides_when_the_points_rule_abandons_itself_on_the_budget():
    rnd = lead(); seat = rnd.turn
    admitted = ADMITTED[:3]
    means = np.array([0.50 - EPS / 2, 0.50, 0.50 - EPS / 3])
    both = harness(tiebreak_points=True, lead_tiebreak_prior=True)
    worlds, _ = both._worlds(rnd, seat)
    stub_points(both, {("S2",): 10, ("S3",): -5, ("S4",): 0})

    def expired():
        raise pv.PVSearchBudgetExceeded("pv-search serving budget expired")
    assert both._select(rnd, seat, admitted, means, worlds=worlds, check_budget=expired,
                        priors=[0.0, 1.0, 9.0]) == 2
    assert both._tiebreak_record()["tiebreak_abandoned"] == "budget"
    assert both._tiebreak_record()["tiebreak_applied"] is False
    assert both._lead_tiebreak_record()["lead_tiebreak_applied"] is True


def test_with_the_points_rule_on_a_real_lead_is_the_points_rule_when_it_moves():
    """The real engine and finisher on the fixture lead (every mean tied, so
    the whole ballot is near): both-on plays what the points rule alone plays
    whenever that rule moves, else the prior's choice."""
    rnd = lead(); seat = rnd.turn
    both = harness(tiebreak_points=True, lead_tiebreak_prior=True)
    only = harness(tiebreak_points=True)
    worlds, _ = both._worlds(rnd, seat)
    legal = enumerate_legal(rnd, seat, cap=4000)
    moved = kept = 0
    for start in range(0, 12, 2):
        admitted = [list(a) for a in legal.actions[start:start + 4]]
        by_points = only._select(rnd, seat, admitted, np.zeros(4), worlds=worlds)
        priors = [0.0, 1.0, 2.0, 3.0]
        chosen = both._select(rnd, seat, admitted, np.zeros(4), worlds=worlds, priors=priors)
        assert both._tiebreak_record() == only._tiebreak_record()
        if by_points != 0:
            moved += 1
            assert chosen == by_points
            assert both._lead_tiebreak_record()["lead_tiebreak_superseded"] == "tiebreak_points"
        else:
            kept += 1
            assert chosen == 3 and both._lead_tiebreak_record()["lead_tiebreak_applied"] is True
    assert moved and moved + kept == 6


def test_with_the_points_rule_on_a_follow_is_exactly_the_points_rule():
    rnd = follow(); seat = rnd.turn
    worse, better = ["DK"], ["D6"]
    admitted = [["H4"], worse, better]
    means = np.array([0.40, 0.50, 0.50 - EPS / 2])
    both = harness(tiebreak_points=True, lead_tiebreak_prior=True)
    only = harness(tiebreak_points=True)
    worlds, _ = both._worlds(rnd, seat)
    # the prior prefers the point dump; on a follow it has no say
    assert both._select(rnd, seat, admitted, means, worlds=worlds, priors=[0.0, 9.0, 1.0]) == 2
    assert only._select(rnd, seat, admitted, means, worlds=worlds) == 2
    assert both._tiebreak_record() == only._tiebreak_record() == {
        "tiebreak_applied": True, "tiebreak_near_set": [1, 2], "tiebreak_points": [-20.0, -10.0]}
    record = both._lead_tiebreak_record()
    assert record["lead_tiebreak_leading"] is False and record["lead_tiebreak_applied"] is False
    assert "lead_tiebreak_superseded" not in record       # that key is a LEAD's
    # the points rule leaving the argmax on a follow does not hand it to the prior
    assert both._select(rnd, seat, admitted, np.array([0.40, 0.50 - EPS / 2, 0.50]),
                        worlds=worlds, priors=[0.0, 9.0, 1.0]) == 2
    assert both._tiebreak_record()["tiebreak_applied"] is False
    # whole follow decisions: both-on == points-only, harness and served
    for build in (harness, served):
        a, b = build(tiebreak_points=True), build(tiebreak_points=True, lead_tiebreak_prior=True)
        assert a.decide_play(copy.deepcopy(rnd), seat) == b.decide_play(copy.deepcopy(rnd), seat)
        ra, rb = a.last_decision_record, b.last_decision_record
        for key in ("admitted_indices", "value_means", "selected_index", "tiebreak_applied",
                    "tiebreak_near_set", "tiebreak_points"):
            assert ra[key] == rb[key]


# The three tactical positions (tests/tactical/fixtures.jsonl) that the FIRST
# draft of this rule regressed on combo+la (#699: 12/22 -> 9/22): there the
# prior replaced the points rule on leads, so the lead went back to the value
# argmax, a multi-component throw.  Recorded from the real package
# (smv3out-491ee4bf, combo+la, seed 0): the admitted ballot, the 64-world value
# means, the policy log-odds, the points rule's near-set and mean points, and
# the action combo+la played.
REGRESSED = {
    "lkmu-r1-s2-t0-throw": dict(
        admitted=["SA", "C2 C2 C6 C6 C7", "C10 C2 C2 C6 C6 C7", "C10 C10 C2 C2 C6 C6 C7",
                  "C2 C6 C6 C7", "C6 C6 C7", "C10 C10 C6 C6 C7", "C10 C10 C6 C6 C7 D2"],
        means=[-0.318595, -0.312636, -0.312636, -0.312636, -0.312636, -0.312636, -0.312636,
               -0.312636],
        priors=[0.364, 1.5962, 1.5514, 1.5067, 1.4207, 1.2453, 1.1558, 1.0023],
        near=[0, 1, 2, 3, 4, 5, 6, 7],
        points=[5.9375, -3.984375, -3.984375, -3.984375, -3.984375, -3.984375, -3.984375,
                -3.984375],
        combo_la="SA", argmax="C2 C2 C6 C6 C7"),
    "cdce-r1-s2-t5-throw": dict(
        admitted=["DK DK", "D6 D6 DK DK", "D6 D6 DK DK DQ", "D6 DK DK", "D6 D6", "D6 D6 DQ",
                  "H6 H6", "DK"],
        means=[-1.802997, -1.721759, -1.618315, -1.72863, -1.755788, -1.63141, -1.634484,
               -1.791435],
        priors=[0.4888, 0.9699, 0.8409, 0.7293, 0.4811, 0.3521, 0.2698, 0.2444],
        near=[2, 5, 6], points=[-6.71875, -6.328125, -4.6875],
        combo_la="H6 H6", argmax="D6 D6 DK DK DQ"),
    "khpx-r2-s2-t10-rethrow": dict(
        admitted=["D7", "D7 D7 D9 D9", "D7 D7 D9 D9 DQ", "D7 D7 D9", "D7 D7 D9 D9 DJ DQ",
                  "D7 D7", "D7 D7 D9 D9 DJ DK DQ", "D9 D9"],
        means=[-0.54959, -0.550073, -0.527059, -0.551245, -0.528215, -0.541512, -0.528215,
               -0.544046],
        priors=[0.8038, 2.8451, 2.6364, 2.2264, 2.188, 1.6077, 1.5388, 1.2374],
        near=[2, 4, 5, 6, 7], points=[-2.890625, -1.640625, 0.15625, -1.640625, 0.15625],
        combo_la="D7 D7", argmax="D7 D7 D9 D9 DQ"),
}


@pytest.mark.parametrize("fixture_id", sorted(REGRESSED))
def test_regression_witness_the_points_rule_lead_is_kept(fixture_id):
    """Package-free: the recorded means, priors and points through the real
    `_select`.  combo+la+lp must play combo+la's action; the prior alone (no
    points rule) keeps the throw, which is why replacing the points rule
    regressed these."""
    row = REGRESSED[fixture_id]
    rnd = lead(); seat = rnd.turn
    admitted = [a.split(" ") for a in row["admitted"]]
    means = np.array(row["means"])
    points = {tuple(admitted[i]): p for i, p in zip(row["near"], row["points"])}
    both = harness(tiebreak_points=True, lead_tiebreak_prior=True)
    only = harness(tiebreak_points=True)
    prior_only = harness(lead_tiebreak_prior=True)
    worlds, _ = both._worlds(rnd, seat)
    stub_points(both, points); stub_points(only, points)
    assert " ".join(admitted[int(np.argmax(means))]) == row["argmax"]
    combo = only._select(rnd, seat, admitted, means, worlds=worlds)
    assert " ".join(admitted[combo]) == row["combo_la"] != row["argmax"]
    assert only._tiebreak_record()["tiebreak_near_set"] == row["near"]
    assert only._tiebreak_record()["tiebreak_points"] == row["points"]
    chosen = both._select(rnd, seat, admitted, means, worlds=worlds, priors=row["priors"])
    assert chosen == combo and " ".join(admitted[chosen]) == row["combo_la"]
    assert both._tiebreak_record() == only._tiebreak_record()
    record = both._lead_tiebreak_record()
    assert record["lead_tiebreak_applied"] is False
    assert record["lead_tiebreak_superseded"] == "tiebreak_points"
    # the first draft's behaviour, for the record: the prior alone keeps the throw
    alone = prior_only._select(rnd, seat, admitted, means, priors=row["priors"])
    assert " ".join(admitted[alone]) == row["argmax"]


def _package():
    ckpt, sha = os.environ.get("SHENGJI_PV_CKPT"), os.environ.get("SHENGJI_PV_SHA256")
    if not ckpt or not sha or not Path(ckpt).is_file():
        pytest.skip("SHENGJI_PV_CKPT/SHENGJI_PV_SHA256 not set to a local served package")
    return ckpt, sha


COMBO_LA_FLAGS = {k: v for k, v in COMBO_LA_ENV.items() if k not in PRODUCTION_ENV}


@pytest.mark.parametrize("seed", [0, 1])
def test_real_package_every_lead_the_points_rule_moves_is_played_as_combo_la(seed):
    """The served bot on the real package, all 22 tactical fixtures: the ballot,
    the value means and the points rule's record are identical with the flag
    on; wherever the points rule moves the selection the action is combo+la's;
    wherever the action differs the prior rule says it applied, on a lead."""
    from shengji.eval import tactical as T
    ckpt, sha = _package()
    # no serving budget: a loaded machine must not turn a decision into the
    # anchor fallback (the search itself is the same computation)
    base = T.production_environ(ckpt, sha, SHENGJI_PV_SERVING_BUDGET_SECONDS="",
                                **COMBO_LA_FLAGS)
    cand = {**base, FLAG: "1"}
    fixtures = T.load_fixtures()
    for fx in fixtures:
        a = T.run_fixture(T.bot_from_environ(base, seed=seed)[1], fx)
        b = T.run_fixture(T.bot_from_environ(cand, seed=seed)[1], fx)
        assert a.error is None and b.error is None, fx.id
        ra, rb = a.record, b.record
        for key in ("admitted", "value_means", "tiebreak_applied", "tiebreak_near_set",
                    "tiebreak_points"):
            assert ra[key] == rb[key], (fx.id, key)
        if ra["tiebreak_applied"] or not rb["lead_tiebreak_leading"]:
            assert a.action == b.action, fx.id
            assert rb["lead_tiebreak_applied"] is False
        if a.action != b.action:
            assert rb["lead_tiebreak_applied"] is True and rb["lead_tiebreak_leading"] is True
        if seed == 0 and fx.id in REGRESSED:
            assert " ".join(a.action) == " ".join(b.action) == REGRESSED[fx.id]["combo_la"]
            assert rb["lead_tiebreak_superseded"] == "tiebreak_points"


# ------------------------------------------------------- (h) whole decision + telemetry

def crafted_decision(bot, rnd, seat):
    """Two legal actions: ``first`` is the value argmax by EPS/2, ``second`` is
    the policy's favourite; every other admitted candidate is far below."""
    legal = enumerate_legal(rnd, seat, cap=4000)
    first, second = list(legal.actions[0]), list(legal.actions[1])
    crafted_preferences(bot, rnd, seat, [1, 0])

    def value_means(rnd_, seat_, admitted_, worlds_, check_budget=None):
        means = np.full(len(admitted_), -1.0)
        means[admitted_.index(first)] = 0.5
        means[admitted_.index(second)] = 0.5 - EPS / 2
        return means, 1
    bot._value_means = value_means
    return first, second


@pytest.mark.parametrize("build", [harness, served], ids=["harness", "served"])
def test_a_whole_lead_decision_plays_the_policy_favourite_and_records_scalars(build):
    rnd = lead(); seat = rnd.turn
    off = build()
    first, second = crafted_decision(off, rnd, seat)
    assert off.decide_play(copy.deepcopy(rnd), seat) == first          # the plain argmax
    assert not RULE_KEYS & set(off.last_decision_record)
    bot = build(lead_tiebreak_prior=True)
    crafted_decision(bot, rnd, seat)
    assert bot.decide_play(copy.deepcopy(rnd), seat) == second
    record = bot.last_decision_record
    assert RULE_KEYS <= set(record)
    chosen = record["admitted_indices"]
    assert chosen == off.last_decision_record["admitted_indices"]      # the ballot is untouched
    assert record["value_means"] == off.last_decision_record["value_means"]
    assert record["selected_index"] == 1
    assert record["lead_tiebreak_applied"] is True and record["lead_tiebreak_leading"] is True
    assert record["lead_tiebreak_near_count"] == 2
    assert record["lead_tiebreak_from_index"] == chosen.index(0)
    assert record["lead_tiebreak_to_index"] == chosen.index(1)
    assert record["lead_tiebreak_from"] == " ".join(first)
    assert record["lead_tiebreak_to"] == " ".join(second)
    assert record["lead_tiebreak_value_gap"] == pytest.approx(EPS / 2)
    # scalars only: they survive the screen trace filter unchanged and JSON
    assert all(type(record[k]) in (bool, int, float, str) for k in RULE_KEYS)
    assert json.loads(json.dumps({k: record[k] for k in RULE_KEYS})) == {
        k: record[k] for k in RULE_KEYS}
    if "played" in record:
        assert record["played"] == second and record["anchor_selected"] == (
            record["lead_tiebreak_to_index"] == 0)


def test_the_record_fields_survive_the_screen_trace_filter():
    """The served-screen trace writer (`search_screen.trace_fields`, #695) keeps
    scalars key for key; every field of this rule is one, so nothing is
    summarised or dropped.  (The screen module imports torch.)"""
    pytest.importorskip("torch")
    from shengji.train import search_screen
    rnd = lead(); seat = rnd.turn
    bot = served(lead_tiebreak_prior=True)
    first, second = crafted_decision(bot, rnd, seat)
    assert bot.decide_play(copy.deepcopy(rnd), seat) == second
    record = bot.last_decision_record
    policy = search_screen.TimedPolicy(bot)
    assert policy.decide_play(copy.deepcopy(rnd), seat) == second
    (trace,) = policy.decisions
    for source in (trace, search_screen.trace_fields(record)):
        assert {k: source[k] for k in RULE_KEYS - {"lead_tiebreak_value_gap"}} == {
            k: record[k] for k in RULE_KEYS - {"lead_tiebreak_value_gap"}}
        assert source["lead_tiebreak_value_gap"] == pytest.approx(EPS / 2)
        assert not any(f"{k}__len" in source for k in RULE_KEYS)
        assert source["lead_tiebreak_applied"] is True
    # the "points rule's change was kept" marker is a scalar too
    kept = search_screen.trace_fields({**record, "lead_tiebreak_superseded": "tiebreak_points"})
    assert kept["lead_tiebreak_superseded"] == "tiebreak_points"
    assert json.loads(json.dumps(trace))["lead_tiebreak_to"] == " ".join(second)


def test_the_rule_changes_no_world_no_ballot_and_adds_no_value_call():
    for rnd in (lead(), follow()):
        seat = rnd.turn
        seen = {}
        for flag in (False, True):
            bot = served(lead_tiebreak_prior=flag)
            count = [0]
            score = bot.evaluator.score

            def counted(leaves, s, score=score, count=count):
                count[0] += len(leaves)
                return score(leaves, s)
            bot.evaluator.score = counted
            before = bot.sampler.rng.getstate()
            bot.decide_play(copy.deepcopy(rnd), seat)
            record = bot.last_decision_record
            seen[flag] = (count[0], record["value_batches"], record["admitted_indices"],
                          record["value_means"], record["sample_attempts"],
                          bot.sampler.rng.getstate(), before)
        assert seen[False] == seen[True]


def test_a_lead_without_priors_and_bad_parameters_are_refused():
    rnd = lead()
    bot = harness(lead_tiebreak_prior=True)
    with pytest.raises(ValueError, match="policy priors"):
        bot._select(rnd, rnd.turn, ADMITTED[:2], np.array([0.1, 0.1]))
    with pytest.raises(ValueError, match="one prior per admitted"):
        bot._select(rnd, rnd.turn, ADMITTED[:2], np.array([0.1, 0.1]), priors=[0.0])
    for bad in (1, "1", None):
        with pytest.raises(ValueError, match="lead_tiebreak_prior must be a bool"):
            harness(lead_tiebreak_prior=bad)
    for bad in (-0.01, float("nan"), float("inf"), "0.02"):
        with pytest.raises(ValueError, match="lead_tiebreak_epsilon"):
            harness(lead_tiebreak_epsilon=bad)
    with pytest.raises(pv.PVSearchPolicyError, match="must be a bool"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, lead_tiebreak_prior="1"))


# ------------------------------------------------------- (i) name / env / digest

def test_every_existing_served_name_is_byte_identical_with_the_flag_off(production_package):
    for env, name in ((PRODUCTION_ENV, PRODUCTION_NAME), (COMBO_ENV, COMBO_NAME),
                      (COMBO_LA_ENV, COMBO_LA_NAME)):
        assert names(env) == [name]
        assert names({**env, FLAG: "0"}) == [name]
        assert names({**env, FLAG: ""}) == [name]
    assert PRODUCTION_NAME == "pv-search-491ee4bf-w64-k8-r4a09aef5-bury-hybrid-355958b4db25"


def test_lp_token_digest_and_payload_when_on(production_package):
    lp, = names({**PRODUCTION_ENV, FLAG: "1"})
    assert lp.startswith("pv-search-491ee4bf-w64-k8-lp-r") and "-bury-hybrid-" in lp
    candidate, = names({**COMBO_LA_ENV, FLAG: "1"})
    assert candidate.startswith("pv-search-491ee4bf-w64-k8-div-rc-tb-la-lp-r")
    every, = names({**COMBO_LA_ENV, "SHENGJI_PV_ADMIT_FORCED_SINGLE": "1",
                    "SHENGJI_PV_ADAPTIVE_K": "1", FLAG: "1"})
    assert every.startswith("pv-search-491ee4bf-w64-k8-div-fs-rc-tb-ak16-la-lp-r")
    assert len({lp, candidate, every, PRODUCTION_NAME, COMBO_NAME, COMBO_LA_NAME}) == 6
    config = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0)
    assert pv.recipe_digest(config) == "4a09aef5"
    assert not {"lead_tiebreak_prior", "lead_tiebreak_epsilon"} & set(pv.recipe_payload(config))
    on = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                           lead_tiebreak_prior=True)
    payload = pv.recipe_payload(on)
    assert payload["lead_tiebreak_prior"] is True and payload["lead_tiebreak_epsilon"] == EPS
    assert "tiebreak_epsilon" not in payload
    assert pv.recipe_digest(on) != "4a09aef5"
    assert pv.RULE_FLAGS["LEAD_TIEBREAK_PRIOR"] == "lead_tiebreak_prior"
    assert pv.RULE_TOKENS[-4] == ("lead_tiebreak_prior", "lp")   # dts, sjg (#707 S4), then aw follow
    assert [t for _, t in pv.RULE_TOKENS] == ["div", "fs", "rc", "rcec", "tb", "ak16", "la", "lp", "dts", "sjg", "aw"]
    assert served(lead_tiebreak_prior=True).lead_tiebreak_prior is True
    assert served().lead_tiebreak_prior is False


@pytest.mark.parametrize("bad", ["2", "true", "yes", "on", " 1", "0.0"])
def test_env_flag_refuses_anything_but_0_or_1(bad):
    with pytest.raises(pv.PVSearchPolicyError, match="LEAD_TIEBREAK_PRIOR must be 0 or 1"):
        pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: bad})
    assert "lead_tiebreak_prior" not in pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: ""})
    assert "lead_tiebreak_prior" not in pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: "0"})
    assert pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: "1"})["lead_tiebreak_prior"] is True


# ------------------------------------------------------- (j) harvest

ALL_OTHER_RULES = dict(admission_diversity=True, admit_forced_single=True,
                       refusal_constraints=True, tiebreak_points=True, adaptive_k=True,
                       lead_anchor=True)


@pytest.mark.parametrize("others", [False, True], ids=["alone", "every-rule"])
@pytest.mark.parametrize("explore", [False, True])
def test_the_harvest_record_reads_with_the_rule_on(explore, others):
    rnd = lead(); seat = rnd.turn
    bot = served(evaluator=ZeroEvaluator(), lead_tiebreak_prior=True,
                 **(ALL_OTHER_RULES if others else {}))
    bot.__class__ = trajectory.pv_trajectory_class(type(bot))
    bot._trajectory_init(random.Random(0))
    if explore:
        bot.EXPLORE_RATE, bot.EXPLORE_K = 1.0, 1
    played = bot.decide_play(copy.deepcopy(rnd), seat)
    record = bot.last_decision_record
    assert record["schema"] == pv.RECORD_SCHEMA and RULE_KEYS <= set(record)
    assert record["lead_tiebreak_leading"] is True
    # every value mean is 0: the whole ballot is the near-set.  The points rule
    # (when on) goes first and a selection it moves is kept; otherwise the play
    # is the finite-rated candidate the policy ranks first (argmax on a tie)
    k = len(bot.last_ballot)
    assert record["lead_tiebreak_near_count"] == k
    odds = record["policy_log_odds_admitted"]
    rated = [i for i in range(k) if np.isfinite(odds[i])]
    best = min(rated, key=lambda i: (-odds[i], i != 0, i))
    index = bot.last_ballot.index(played)
    if record.get("tiebreak_applied"):
        assert others and record["lead_tiebreak_superseded"] == "tiebreak_points"
        assert record["lead_tiebreak_applied"] is False and index != 0
        points = record["tiebreak_points"]
        assert points[record["tiebreak_near_set"].index(index)] == max(points)
    else:
        assert index == best == record["lead_tiebreak_to_index"]
        assert "lead_tiebreak_superseded" not in record
    allocation, preference, values = trajectory.pv_fields_from_record(record, bot.last_ballot)
    assert allocation["played_index"] == index
    assert len(values["means"]) == k == len(values["policy_log_odds"])
    if others:
        assert {"tiebreak_applied", "tiebreak_near_set", "tiebreak_points"} <= set(record)
        assert "tiebreak_superseded" not in record
