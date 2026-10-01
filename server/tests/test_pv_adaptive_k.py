"""The OPTIONAL adaptive admission width of the pv-search bot (#676 C):
``adaptive_k`` -- K=16 instead of 8 on a lead whose legal set holds a
multi-card action, K unchanged otherwise.

Torch-free: the stub predictor and evaluator of `test_pv_admission_rules` on
the real fixture round, the real legal enumeration and the real engine.

Witnesses: (a) OFF, the harness and the served wrapper admit exactly the K=8
ranked prefix on a lead and on a follow and the record carries no adaptive
keys; (b) ON, a multi-card lead admits 16 whose first 8 ARE the K=8 ballot
and whose last 8 are the next-best by the same preference (a strict superset,
same order); (c) a single-only lead and (d) a follow keep K=8; (e) the
diversity caps apply within the widened K; (f) the production registry name
is unchanged when off, carries ``-ak16`` when on, the payload carries the
width only when on, the env flag refuses anything but 0/1; (g) under the
harvest mixin the CAPTURED production ballot is the widened one and
`pv_fields_from_record` accepts the record, with and without an exploration
draw, and with the forced-single rule on as well (the width is decided
before the forced extras, so the final ballot is at most 16+2 and is
captured whole; the #680 HOLD was a ballot appended after capture).
"""
import copy
import random

import numpy as np
import pytest

from shengji.harvest import trajectory
from shengji.harvest.common import action_key
from shengji.harvest.legal import LegalSet, enumerate_legal
from shengji.train import policy_value_search as module
from shengji.train import pv_search_policy as pv
from shengji.train.policy_value_search import PolicyValueBot, structure_key
from test_policy_world_search import state
from test_pv_admission_rules import (PRODUCTION_ENV, PRODUCTION_NAME, PRODUCTION_SHA,
                                     ZeroEvaluator, crafted_preferences, legacy_admission,
                                     names, predict, production_package)  # noqa: F401

WIDE = module.ADAPTIVE_K_DEFAULTS["candidates_lead_multi"]
ADAPTIVE_KEYS = {"adaptive_k_applied", "k_used"}


def harness(**rules):
    return PolicyValueBot(predict, evaluator=ZeroEvaluator(), worlds=2, candidates=8,
                          cap=4000, seed=17, **rules)


def served(**rules):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=2, candidates=8,
                               cap=4000, batch_size=128, **rules)
    return pv.PVSearchBot(predict, evaluator=ZeroEvaluator(), version=2, config=config,
                          checkpoint="/dev/null", seed=17)


def follow_position():
    """The fixture round walked by the heuristic to the first FOLLOW with at
    least nine legal actions, some of them multi-card (the first trick's
    fourth seat: 18 actions)."""
    rnd = state()
    h = module.HeuristicBot()
    while True:
        rnd.play(rnd.turn, h.decide_play(rnd, rnd.turn))
        legal = enumerate_legal(rnd, rnd.turn, cap=4000)
        if not module.leading(rnd) and len(legal.actions) >= 9 \
                and any(len(a) >= 2 for a in legal.actions):
            assert rnd.trick.plays
            return rnd


def preferences_of(bot, rnd, seat):
    """The bot's own policy preferences over the served scored set (anchor forced
    in), so the expected admission can be computed outside the bot."""
    anchor = module.HeuristicBot().decide_play(rnd, seat)
    legal = enumerate_legal(rnd, seat, cap=bot.cap, must_include=[anchor])
    worlds, _ = PolicyValueBot(predict, evaluator=ZeroEvaluator(), worlds=2, seed=17)._worlds(rnd, seat)
    return legal, bot.scores(rnd, seat, list(legal.actions), worlds).mean(axis=0)


# ------------------------------------------------------- (a) off == before

def test_off_admits_exactly_the_k8_prefix_and_carries_no_adaptive_keys():
    assert module.ADAPTIVE_K_DEFAULTS["adaptive_k"] is False and WIDE == 16
    for build in (harness, served):
        for rnd in (state(), follow_position()):
            seat = rnd.turn
            bot = build()
            assert bot.adaptive_k is False and bot.candidates_lead_multi == WIDE
            played = bot.decide_play(copy.deepcopy(rnd), seat)
            record = bot.last_decision_record
            legal, prefs = preferences_of(bot, rnd, seat)
            anchor = record["admitted_indices"][0]
            assert record["admitted_indices"] == legacy_admission(prefs, anchor, 8)
            assert len(record["admitted_indices"]) == 8
            assert played == list(legal.actions[record["selected_index"]])
            assert not ADAPTIVE_KEYS & set(record)
            assert record["value_evaluations"] == 2 * 8
    # the width hook itself, off: never widened, even on a multi-card lead
    bot = harness()
    assert bot._admission_k(state(), [["C3"], ["C3", "C3"]], np.array([0.0, 1.0])) == (8, False)


# ------------------------------------------------------- (b) multi-card lead

def test_multi_card_lead_admits_16_as_a_strict_superset_of_the_8_in_order():
    rnd = state(); seat = rnd.turn
    assert module.leading(rnd)
    legal = enumerate_legal(rnd, seat, cap=4000)
    assert any(len(a) >= 2 for a in legal.actions)
    for build in (harness, served):
        off, on = build(), build(adaptive_k=True)
        off.decide_play(copy.deepcopy(rnd), seat)
        on.decide_play(copy.deepcopy(rnd), seat)
        narrow, wide = off.last_decision_record, on.last_decision_record
        assert len(narrow["admitted_indices"]) == 8 and len(wide["admitted_indices"]) == WIDE
        # superset, same order: the K=8 ballot IS the first 8 of the widened one
        assert wide["admitted_indices"][:8] == narrow["admitted_indices"]
        assert len(set(wide["admitted_indices"])) == WIDE
        # the extra slots are the next-best by the same preference
        _, prefs = preferences_of(on, rnd, seat)
        assert wide["admitted_indices"] == legacy_admission(prefs, wide["admitted_indices"][0], WIDE)
        assert wide["adaptive_k_applied"] is True and wide["k_used"] == WIDE
        assert wide["value_evaluations"] == 2 * WIDE
        assert wide["value_means"][:8] == narrow["value_means"]
        if "admitted" in wide:                       # the served record
            assert wide["admitted"][:8] == narrow["admitted"]
            assert len(wide["policy_log_odds_admitted"]) == WIDE
            assert wide["work_complete"] is True and wide["schema"] == pv.RECORD_SCHEMA
    # the legal set is capped (4,000 of this lead's actions): the width is
    # decided on the scored set the search actually sees
    assert not legal.complete


# ------------------------------------------------------- (c) single-only lead

def single_only_lead():
    """The fixture round walked by the heuristic to a lead where the anchor is
    a single; the served scored set is then narrowed to its singles."""
    rnd = state()
    h = module.HeuristicBot()
    while True:
        seat = rnd.turn
        anchor = h.decide_play(rnd, seat)
        singles = [a for a in enumerate_legal(rnd, seat, cap=4000).actions if len(a) == 1]
        if module.leading(rnd) and len(anchor) == 1 and len(singles) >= 9:
            return rnd, singles
        rnd.play(seat, anchor)


def test_single_only_lead_keeps_8():
    rnd, singles = single_only_lead(); seat = rnd.turn
    bot = served(adaptive_k=True)
    bot._legal = lambda rnd_, seat_, must_include: LegalSet("lead", [list(a) for a in singles],
                                                            len(singles), True)
    played = bot.decide_play(copy.deepcopy(rnd), seat)
    record = bot.last_decision_record
    assert record["schema"] == pv.RECORD_SCHEMA
    assert len(record["admitted_indices"]) == 8
    assert record["adaptive_k_applied"] is False and record["k_used"] == 8
    assert all(len(a) == 1 for a in record["admitted"]) and len(played) == 1
    # the hook: a lead, singles only
    assert bot._admission_k(rnd, singles, np.zeros(len(singles))) == (8, False)
    # a masked (non-production) multi-card entry never decides the width
    assert bot._admission_k(rnd, [["S2"], ["H2", "H2"]], np.array([0.0, -np.inf])) == (8, False)
    assert bot._admission_k(rnd, [["S2"], ["H2", "H2"]], np.array([0.0, 1.0])) == (WIDE, True)


# ------------------------------------------------------- (d) follow

def test_follow_keeps_8():
    rnd = follow_position(); seat = rnd.turn
    legal = enumerate_legal(rnd, seat, cap=4000)
    assert any(len(a) >= 2 for a in legal.actions)      # multi-card follows exist here
    for build in (harness, served):
        off, on = build(), build(adaptive_k=True)
        off.decide_play(copy.deepcopy(rnd), seat)
        on.decide_play(copy.deepcopy(rnd), seat)
        assert on.last_decision_record["admitted_indices"] == off.last_decision_record["admitted_indices"]
        assert len(on.last_decision_record["admitted_indices"]) == 8
        assert on.last_decision_record["adaptive_k_applied"] is False
        assert on.last_decision_record["k_used"] == 8


# ------------------------------------------------------- (e) with diversity

def test_diversity_caps_apply_within_the_widened_k():
    rnd = state(); seat = rnd.turn
    bot = harness(adaptive_k=True, admission_diversity=True)
    legal = enumerate_legal(rnd, seat, cap=bot.cap)
    key = ("C", 3, (("C", 0), ("C", 1)))
    variants = [i for i, a in enumerate(legal.actions) if structure_key(rnd, a) == key][:7]
    assert len(variants) == 7
    crafted_preferences(bot, rnd, seat, variants)
    bot.decide_play(copy.deepcopy(rnd), seat)
    record = bot.last_decision_record
    chosen = record["admitted_indices"]
    assert len(chosen) == WIDE and len(set(chosen)) == WIDE
    assert record["adaptive_k_applied"] is True and record["k_used"] == WIDE
    from collections import Counter
    admitted_keys = Counter(structure_key(rnd, legal.actions[i]) for i in chosen)
    assert admitted_keys[key] <= 2 and all(n <= 2 for n in admitted_keys.values())
    assert not set(record["diversity_skipped"]) & set(chosen)
    assert record["value_evaluations"] == 2 * WIDE
    # the explicit width argument of the diverse admission, and its default
    actions = [["C3"], ["C10", "C3"], ["C10", "C5"], ["C3", "C3"], ["D2", "D2"]]
    assert bot._admit_diverse(rnd, actions, [1, 2, 3, 4], 0, 3) == [0, 1, 4]
    assert bot._admit_diverse(rnd, actions, [1, 2, 3, 4], 0) == [0, 1, 4, 2, 3]


# ------------------------------------------------------- (f) name / env / digest

def test_production_name_unchanged_when_off_and_ak16_when_on(production_package):
    assert names(PRODUCTION_ENV) == [PRODUCTION_NAME]
    assert names({**PRODUCTION_ENV, "SHENGJI_PV_ADAPTIVE_K": "0"}) == [PRODUCTION_NAME]
    ak, = names({**PRODUCTION_ENV, "SHENGJI_PV_ADAPTIVE_K": "1"})
    assert ak != PRODUCTION_NAME
    assert ak.startswith("pv-search-491ee4bf-w64-k8-ak16-r") and "-bury-hybrid-" in ak
    every, = names({**PRODUCTION_ENV, "SHENGJI_PV_ADMISSION_DIVERSITY": "1",
                    "SHENGJI_PV_ADMIT_FORCED_SINGLE": "1", "SHENGJI_PV_ADAPTIVE_K": "1",
                    "SHENGJI_PV_TIEBREAK_POINTS": "1"})
    assert every.startswith("pv-search-491ee4bf-w64-k8-div-fs-tb-ak16-r")
    assert pv.ADAPTIVE_K_TOKEN == ("adaptive_k", "ak16")
    # the payload: absent when off (the pre-rule digest), the width when on
    config = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0)
    assert pv.recipe_digest(config) == "4a09aef5"
    assert not {"adaptive_k", "candidates_lead_multi"} & set(pv.recipe_payload(config))
    on = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0, adaptive_k=True)
    assert pv.recipe_payload(on)["adaptive_k"] is True
    assert pv.recipe_payload(on)["candidates_lead_multi"] == 16
    assert pv.recipe_digest(on) != pv.recipe_digest(config)
    assert pv.RULE_FLAGS["ADAPTIVE_K"] == "adaptive_k"


@pytest.mark.parametrize("bad", ["2", "true", "yes", "on", " 1"])
def test_env_flag_refuses_anything_but_0_or_1(bad):
    with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
        pv.pv_env_recipe({**PRODUCTION_ENV, "SHENGJI_PV_ADAPTIVE_K": bad})
    assert "adaptive_k" not in pv.pv_env_recipe({**PRODUCTION_ENV, "SHENGJI_PV_ADAPTIVE_K": ""})
    assert "adaptive_k" not in pv.pv_env_recipe({**PRODUCTION_ENV, "SHENGJI_PV_ADAPTIVE_K": "0"})
    assert pv.pv_env_recipe({**PRODUCTION_ENV, "SHENGJI_PV_ADAPTIVE_K": "1"})["adaptive_k"] is True


def test_bad_values_are_refused():
    with pytest.raises(ValueError, match="adaptive_k must be a bool"):
        PolicyValueBot(predict, evaluator=ZeroEvaluator(), adaptive_k=1)
    with pytest.raises(ValueError, match="candidates_lead_multi"):
        PolicyValueBot(predict, evaluator=ZeroEvaluator(), candidates=8, candidates_lead_multi=7)
    with pytest.raises(ValueError, match="candidates_lead_multi"):
        PolicyValueBot(predict, evaluator=ZeroEvaluator(), candidates_lead_multi=16.0)
    with pytest.raises(pv.PVSearchPolicyError, match="must be a bool"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, adaptive_k="1"))


# ------------------------------------------------------- (g) harvest capture

def trajectory_bot(explore, **rules):
    bot = served(adaptive_k=True, **rules)
    bot.__class__ = trajectory.pv_trajectory_class(type(bot))
    bot._trajectory_init(random.Random(0))
    if explore:
        bot.EXPLORE_RATE, bot.EXPLORE_K = 1.0, 1
    return bot


@pytest.mark.parametrize("explore", [False, True])
def test_harvest_captures_the_widened_production_ballot_and_the_record_reads(explore):
    rnd = state(); seat = rnd.turn
    bot = trajectory_bot(explore)
    played = bot.decide_play(copy.deepcopy(rnd), seat)
    record = bot.last_decision_record
    assert record["schema"] == pv.RECORD_SCHEMA
    assert record["adaptive_k_applied"] is True and record["k_used"] == WIDE
    # the CAPTURED production ballot is the widened one, and the priced ballot
    # is production's list plus (at most) the draw: nothing appended after capture
    assert len(bot.last_production_ballot) == WIDE
    assert bot.last_ballot[:WIDE] == bot.last_production_ballot
    assert len(bot.last_ballot) == WIDE + (1 if explore and bot.last_exploration else 0)
    assert bot.last_ballot == record["admitted"]
    assert len(set(action_key(a) for a in bot.last_ballot)) == len(bot.last_ballot)
    assert {action_key(a) for a in bot.last_ballot} <= {action_key(a) for a in bot.last_legal.actions}
    allocation, preference, values = trajectory.pv_fields_from_record(record, bot.last_ballot)
    k = len(bot.last_ballot)
    assert allocation["played_index"] == bot.last_ballot.index(played)
    assert allocation["selection_worlds"] == [2] * k and allocation["total_worlds"] == 2 * k
    assert allocation["work"]["value_evaluations"] == record["value_evaluations"] == 2 * k
    assert len(values["means"]) == k == len(values["policy_log_odds"])
    assert len(preference["softmax"]) == k and preference["played_index"] == allocation["played_index"]
    if explore:
        assert bot.last_exploration is not None and len(bot.last_exploration["added"]) == 1
    # the K=8 production ballot is the head of the widened capture
    narrow = served()
    narrow.decide_play(copy.deepcopy(rnd), seat)
    assert bot.last_production_ballot[:8] == narrow.last_decision_record["admitted"]
    # a widened record with a ballot that was NOT captured whole still refuses
    with pytest.raises(trajectory.TrajectoryError):
        trajectory.pv_fields_from_record(record, bot.last_ballot[:8])


def test_with_forced_single_the_final_ballot_is_at_most_18_and_captured_whole():
    """The width is decided BEFORE the forced extras: production's ballot is the
    widened 16 plus at most FORCED_EXTRA_SLOTS forced components, and the mixin
    captures that final list.  Without an exploration draw: the served guard
    ``len(chosen) > K + FORCED_EXTRA_SLOTS`` (#680) does not count the mixin's
    draw, so K + 2 extras + 1 draw is refused on the data path at K=8 as at
    K=16 -- a #680 guard matter, reported on #687, not widened here."""
    explore = False
    rnd = state(); seat = rnd.turn
    bot = trajectory_bot(explore, admit_forced_single=True)
    played = bot.decide_play(copy.deepcopy(rnd), seat)
    record = bot.last_decision_record
    assert record["schema"] == pv.RECORD_SCHEMA
    assert record["adaptive_k_applied"] is True and record["k_used"] == WIDE
    extras = record["forced_single_added"]
    assert 0 <= len(extras) <= module.FORCED_EXTRA_SLOTS
    production = bot.last_production_ballot
    assert len(production) == WIDE + len(extras) <= WIDE + module.FORCED_EXTRA_SLOTS
    assert record["admitted_indices"][WIDE:WIDE + len(extras)] == extras
    assert bot.last_ballot[:len(production)] == production
    assert len(bot.last_ballot) == len(production) and bot.last_exploration is None
    assert len(extras) == module.FORCED_EXTRA_SLOTS      # both extra slots used here
    assert bot.last_ballot == record["admitted"]
    assert len({action_key(a) for a in bot.last_ballot}) == len(bot.last_ballot)
    allocation, _, values = trajectory.pv_fields_from_record(record, bot.last_ballot)
    assert allocation["played_index"] == bot.last_ballot.index(played)
    assert len(values["means"]) == len(bot.last_ballot) == record["value_evaluations"] // 2
    # the widened 16 are still the K=8 ballot's superset in order
    narrow = served()
    narrow.decide_play(copy.deepcopy(rnd), seat)
    assert production[:8] == narrow.last_decision_record["admitted"]
