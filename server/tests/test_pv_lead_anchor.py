"""The OPTIONAL lead-anchor rule of the pv-search bot (#676 online lead review,
board A7): ``lead_anchor`` -- on a LEAD whose heuristic anchor is a single
non-trump card that is not the top live card of its suit, slot 0 goes to the
highest held plain pair/tractor, else the policy's top-ranked action, else the
heuristic card stays.

Torch-free: the stub predictor and evaluator of `test_pv_admission_rules` on
the real fixture round (walked by the heuristic), the real legal enumeration
and the real engine.  The fixture's leads include the case the review found:
trick 7, seat 3 leads H4 single while holding H4 H4 (no ace, no pair >= Q).

Witnesses: (a) OFF, harness and served wrapper admit and select exactly the
legacy ballot on a lead and a follow, no rule keys; (b) ON, the low-single lead
with a held pair puts the pair in slot 0, the replaced single stays eligible,
the K-1 slots are the same ranked fill; (c) no pair -> the policy's top-ranked
action; (d) a follow, a top-live single, a trump single and a multi-card anchor
are unchanged; (e) the rule adds no value call; (f) name / env / digest; (g)
under the harvest mixin the captured ballot carries the replaced slot 0 and
`pv_fields_from_record` reads the record, with every other rule on as well.
"""
import copy
import random

import numpy as np
import pytest

from shengji.harvest import trajectory
from shengji.harvest.common import action_key
from shengji.harvest.legal import enumerate_legal
from shengji.train import policy_value_search as module
from shengji.train import pv_search_policy as pv
from shengji.train.policy_value_search import PolicyValueBot
from test_policy_world_search import state
from test_pv_admission_rules import (PRODUCTION_ENV, PRODUCTION_NAME, PRODUCTION_SHA,
                                     ZeroEvaluator, legacy_admission, names, predict,
                                     production_package)  # noqa: F401
from test_pv_adaptive_k import follow_position

RULE_KEYS = {"lead_anchor_applied", "lead_anchor_from", "lead_anchor_to", "lead_anchor_source"}


def harness(**rules):
    return PolicyValueBot(predict, evaluator=ZeroEvaluator(), worlds=2, candidates=8,
                          cap=4000, seed=17, **rules)


def served(**rules):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=2, candidates=8,
                               cap=4000, batch_size=128, **rules)
    return pv.PVSearchBot(predict, evaluator=ZeroEvaluator(), version=2, config=config,
                          checkpoint="/dev/null", seed=17)


def lead_at(trick):
    """The fixture round walked by the heuristic to the lead of ``trick`` (0-based)."""
    rnd = state()
    h = module.HeuristicBot()
    while len(rnd.history) < trick or not module.leading(rnd):
        rnd.play(rnd.turn, h.decide_play(rnd, rnd.turn))
    assert module.leading(rnd) and len(rnd.history) == trick
    return rnd


def prefs_of(bot, rnd, seat):
    anchor = module.HeuristicBot().decide_play(rnd, seat)
    legal = enumerate_legal(rnd, seat, cap=bot.cap, must_include=[anchor])
    worlds, _ = PolicyValueBot(predict, evaluator=ZeroEvaluator(), worlds=2, seed=17)._worlds(rnd, seat)
    actions = list(legal.actions)
    return actions, bot.scores(rnd, seat, actions, worlds).mean(axis=0), anchor


def index_of(actions, cards):
    return next(i for i, a in enumerate(actions) if sorted(a) == sorted(cards))


PAIR_LEAD, NO_PAIR_LEAD, TOP_LEAD, TRUMP_LEAD = 6, 10, 5, 9


def test_fixture_leads_are_what_the_tests_claim():
    rnd = lead_at(PAIR_LEAD); seat = rnd.turn
    assert module.HeuristicBot().decide_play(rnd, seat) == ["H4"]
    assert rnd.hands[seat].count("H4") == 2 and not module._is_top_live(rnd, seat, "H4")
    rnd = lead_at(NO_PAIR_LEAD); seat = rnd.turn
    assert module.HeuristicBot().decide_play(rnd, seat) == ["D7"]
    assert not module._is_top_live(rnd, seat, "D7")
    rnd = lead_at(TOP_LEAD); seat = rnd.turn
    assert module.HeuristicBot().decide_play(rnd, seat) == ["C5"]
    assert module._is_top_live(rnd, seat, "C5")
    rnd = lead_at(TRUMP_LEAD); seat = rnd.turn
    anchor = module.HeuristicBot().decide_play(rnd, seat)
    assert len(anchor) == 1 and rnd.ordering.eff_suit(anchor[0]) == "T"


def test_top_live_counts_the_own_hand_and_the_played_cards():
    rnd = state(); seat = rnd.turn
    o = rnd.ordering
    # nothing played: an ace of a plain suit is top only if it is the top level
    plain = [c for c in rnd.hands[seat] if o.eff_suit(c) != "T"]
    top = max(plain, key=o.level)
    lower = [c for c in plain if o.eff_suit(c) == o.eff_suit(top) and o.level(c) < o.level(top)]
    assert lower and not module._is_top_live(rnd, seat, lower[0])     # a held higher card counts


# ------------------------------------------------------- (a) off == before

def test_off_is_the_legacy_ballot_and_selection_on_a_lead_and_a_follow():
    assert module.LEAD_ANCHOR_DEFAULTS["lead_anchor"] is False
    for build in (harness, served):
        for rnd in (lead_at(PAIR_LEAD), lead_at(NO_PAIR_LEAD), follow_position(), state()):
            seat = rnd.turn
            bot, explicit = build(), build(lead_anchor=False)
            assert bot.lead_anchor is False
            played = bot.decide_play(copy.deepcopy(rnd), seat)
            assert explicit.decide_play(copy.deepcopy(rnd), seat) == played
            record = bot.last_decision_record
            assert explicit.last_decision_record["admitted_indices"] == record["admitted_indices"]
            actions, prefs, anchor = prefs_of(bot, rnd, seat)
            anchor_index = index_of(actions, anchor)
            assert record["admitted_indices"] == legacy_admission(prefs, anchor_index, 8)
            assert played == list(actions[record["selected_index"]])
            assert not RULE_KEYS & set(record)


# ------------------------------------------------------- (b) low single + held pair

@pytest.mark.parametrize("build", [harness, served], ids=["harness", "served"])
def test_low_single_with_a_held_pair_anchors_the_pair(build):
    rnd = lead_at(PAIR_LEAD); seat = rnd.turn
    bot = build(lead_anchor=True)
    played = bot.decide_play(copy.deepcopy(rnd), seat)
    record = bot.last_decision_record
    actions, prefs, _ = prefs_of(bot, rnd, seat)
    pair = index_of(actions, ["H4", "H4"])
    assert record["admitted_indices"][0] == pair
    # the K-1 slots are the same ranked fill around the new slot 0; the replaced
    # single is NOT excluded (it competes like any other action)
    assert record["admitted_indices"] == legacy_admission(prefs, pair, 8)
    assert record["lead_anchor_applied"] is True
    assert record["lead_anchor_from"] == "H4" and record["lead_anchor_to"] == "H4 H4"
    assert record["lead_anchor_source"] == "pair"
    assert all(type(record[k]) in (bool, str) for k in RULE_KEYS)     # scalars only
    assert played == list(actions[record["selected_index"]])
    if "admitted" in record:
        assert record["admitted"][0] == ["H4", "H4"] and record["anchor_selected"] == (
            record["selected_index"] == pair)


def test_the_replaced_single_is_admitted_when_the_policy_ranks_it():
    rnd = lead_at(PAIR_LEAD); seat = rnd.turn
    bot = served(lead_anchor=True)
    actions, _, _ = prefs_of(bot, rnd, seat)
    single = index_of(actions, ["H4"])

    def scores(rnd_, seat_, actions_, worlds):
        prefs = np.array([-float(i) for i in range(len(actions_))])
        prefs[single] = 100.0                    # the policy's favourite
        return np.tile(prefs, (len(worlds), 1))
    bot.scores = scores
    bot.decide_play(copy.deepcopy(rnd), seat)
    record = bot.last_decision_record
    assert record["admitted"][0] == ["H4", "H4"] and record["admitted"][1] == ["H4"]


def test_the_highest_plain_pair_or_tractor_wins_slot_0():
    rnd = lead_at(PAIR_LEAD); seat = rnd.turn
    bot = harness(lead_anchor=True)
    assert rnd.ordering.eff_suit("SA") == "T" and rnd.ordering.eff_suit("HA") == "H"  # spades trump
    actions = [["H4"], ["H3", "H3"], ["C9", "C9"], ["C9", "C9", "C10", "C10"],
               ["HQ", "HQ", "HK"],            # a throw (two components): never
               ["SA", "SA"],                  # a trump pair: never
               ["D10", "D10"],                # same top level as C10, shorter
               ["H5", "D5"]]                  # two suits: never
    prefs = np.zeros(len(actions))
    ranked = list(range(len(actions)))
    # highest top level (C10 = D10), then the longer: the C9-C10 tractor
    assert bot._lead_anchor_index(rnd, seat, actions, prefs, 0, ranked) == 3
    assert bot._lead_anchor["lead_anchor_to"] == "C9 C9 C10 C10"
    # a masked (non-finite) entry never qualifies: the next best is D10 D10
    prefs[3] = -np.inf
    assert bot._lead_anchor_index(rnd, seat, actions, prefs, 0, ranked) == 6
    # only the low pair left: it still replaces the single
    assert bot._lead_anchor_index(rnd, seat, actions[:2], prefs[:2], 0, [0, 1]) == 1


# ------------------------------------------------------- (c) no pair -> the policy's top lead

@pytest.mark.parametrize("build", [harness, served], ids=["harness", "served"])
def test_no_pair_takes_the_policy_top_lead(build):
    rnd = lead_at(NO_PAIR_LEAD); seat = rnd.turn
    bot = build(lead_anchor=True)
    bot.decide_play(copy.deepcopy(rnd), seat)
    record = bot.last_decision_record
    actions, prefs, _ = prefs_of(bot, rnd, seat)
    top = sorted(range(len(actions)), key=lambda i: (-prefs[i], i))[0]
    assert actions[top] != ["D7"]
    assert record["admitted_indices"][0] == top
    assert record["admitted_indices"] == legacy_admission(prefs, top, 8)
    assert record["lead_anchor_applied"] is True and record["lead_anchor_source"] == "policy"
    assert record["lead_anchor_from"] == "D7" and record["lead_anchor_to"] == " ".join(actions[top])


def test_policy_top_equal_to_the_heuristic_card_keeps_it():
    rnd = lead_at(NO_PAIR_LEAD); seat = rnd.turn
    bot = harness(lead_anchor=True)
    actions = [["D7"], ["D8"], ["SJ"]]
    prefs = np.array([5.0, 1.0, 0.0])
    assert bot._lead_anchor_index(rnd, seat, actions, prefs, 0, [0, 1, 2]) == 0
    assert bot._lead_anchor == {"lead_anchor_applied": False, "lead_anchor_from": "D7",
                                "lead_anchor_to": "D7", "lead_anchor_source": "heuristic"}
    # nothing finite -> the heuristic card stays
    prefs = np.array([-np.inf, -np.inf, -np.inf])
    assert bot._lead_anchor_index(rnd, seat, actions, prefs, 0, [0, 1, 2]) == 0


# ------------------------------------------------------- (d) unchanged positions

@pytest.mark.parametrize("where", ["follow", "top", "trump", "multi"])
@pytest.mark.parametrize("build", [harness, served], ids=["harness", "served"])
def test_follow_top_trump_and_multi_card_anchors_are_unchanged(build, where):
    rnd = {"follow": follow_position, "top": lambda: lead_at(TOP_LEAD),
           "trump": lambda: lead_at(TRUMP_LEAD), "multi": state}[where]()
    seat = rnd.turn
    off, on = build(), build(lead_anchor=True)
    assert off.decide_play(copy.deepcopy(rnd), seat) == on.decide_play(copy.deepcopy(rnd), seat)
    a, b = off.last_decision_record, on.last_decision_record
    assert a["admitted_indices"] == b["admitted_indices"]
    assert a["selected_index"] == b["selected_index"] and a["value_means"] == b["value_means"]
    assert b["lead_anchor_applied"] is False and b["lead_anchor_source"] == "heuristic"
    assert b["lead_anchor_from"] == b["lead_anchor_to"]


# ------------------------------------------------------- (e) budget

def test_no_extra_value_calls():
    for trick in (PAIR_LEAD, NO_PAIR_LEAD):
        rnd = lead_at(trick); seat = rnd.turn
        calls = {}
        for flag in (False, True):
            bot = served(lead_anchor=flag)
            count = [0]
            score = bot.evaluator.score

            def counted(leaves, s, score=score, count=count):
                count[0] += len(leaves)
                return score(leaves, s)
            bot.evaluator.score = counted
            bot.decide_play(copy.deepcopy(rnd), seat)
            calls[flag] = (count[0], bot.last_decision_record["value_batches"])
        assert calls[False] == calls[True] == (2 * 8, 1)


# ------------------------------------------------------- (f) name / env / digest

def test_production_name_unchanged_when_off_and_la_when_on(production_package):
    assert names(PRODUCTION_ENV) == [PRODUCTION_NAME]
    assert names({**PRODUCTION_ENV, "SHENGJI_PV_LEAD_ANCHOR": "0"}) == [PRODUCTION_NAME]
    la, = names({**PRODUCTION_ENV, "SHENGJI_PV_LEAD_ANCHOR": "1"})
    assert la != PRODUCTION_NAME
    assert la.startswith("pv-search-491ee4bf-w64-k8-la-r") and "-bury-hybrid-" in la
    every, = names({**PRODUCTION_ENV, "SHENGJI_PV_ADMISSION_DIVERSITY": "1",
                    "SHENGJI_PV_ADMIT_FORCED_SINGLE": "1", "SHENGJI_PV_REFUSAL_CONSTRAINTS": "1",
                    "SHENGJI_PV_TIEBREAK_POINTS": "1", "SHENGJI_PV_ADAPTIVE_K": "1",
                    "SHENGJI_PV_LEAD_ANCHOR": "1"})
    assert every.startswith("pv-search-491ee4bf-w64-k8-div-fs-rc-tb-ak16-la-r")
    config = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0)
    assert pv.recipe_digest(config) == "4a09aef5"
    assert "lead_anchor" not in pv.recipe_payload(config)
    on = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                           lead_anchor=True)
    assert pv.recipe_payload(on)["lead_anchor"] is True
    assert pv.recipe_digest(on) != pv.recipe_digest(config)
    assert pv.RULE_FLAGS["LEAD_ANCHOR"] == "lead_anchor"


@pytest.mark.parametrize("bad", ["2", "true", "yes", "on", " 1"])
def test_env_flag_refuses_anything_but_0_or_1(bad):
    with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
        pv.pv_env_recipe({**PRODUCTION_ENV, "SHENGJI_PV_LEAD_ANCHOR": bad})
    assert "lead_anchor" not in pv.pv_env_recipe({**PRODUCTION_ENV, "SHENGJI_PV_LEAD_ANCHOR": ""})
    assert "lead_anchor" not in pv.pv_env_recipe({**PRODUCTION_ENV, "SHENGJI_PV_LEAD_ANCHOR": "0"})
    assert pv.pv_env_recipe({**PRODUCTION_ENV, "SHENGJI_PV_LEAD_ANCHOR": "1"})["lead_anchor"] is True


def test_bad_values_are_refused():
    with pytest.raises(ValueError, match="lead_anchor must be a bool"):
        PolicyValueBot(predict, evaluator=ZeroEvaluator(), lead_anchor=1)
    with pytest.raises(pv.PVSearchPolicyError, match="must be a bool"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, lead_anchor="1"))


# ------------------------------------------------------- (g) harvest capture

def trajectory_bot(explore, **rules):
    bot = served(lead_anchor=True, **rules)
    bot.__class__ = trajectory.pv_trajectory_class(type(bot))
    bot._trajectory_init(random.Random(0))
    if explore:
        bot.EXPLORE_RATE, bot.EXPLORE_K = 1.0, 1
    return bot


ALL_OTHER_RULES = dict(admission_diversity=True, admit_forced_single=True,
                       refusal_constraints=True, tiebreak_points=True, adaptive_k=True)


@pytest.mark.parametrize("others", [False, True], ids=["alone", "every-rule"])
@pytest.mark.parametrize("explore", [False, True])
def test_harvest_captures_the_replaced_anchor_and_the_record_reads(explore, others):
    rnd = lead_at(PAIR_LEAD); seat = rnd.turn
    bot = trajectory_bot(explore, **(ALL_OTHER_RULES if others else {}))
    played = bot.decide_play(copy.deepcopy(rnd), seat)
    record = bot.last_decision_record
    assert record["schema"] == pv.RECORD_SCHEMA
    assert record["lead_anchor_applied"] is True and record["lead_anchor_to"] == "H4 H4"
    # the anchor is decided inside the admission, BEFORE capture
    assert bot.last_production_ballot[0] == ["H4", "H4"]
    assert bot.last_ballot[:len(bot.last_production_ballot)] == bot.last_production_ballot
    assert bot.last_ballot == record["admitted"]
    assert len({action_key(a) for a in bot.last_ballot}) == len(bot.last_ballot)
    allocation, preference, values = trajectory.pv_fields_from_record(record, bot.last_ballot)
    k = len(bot.last_ballot)
    assert allocation["played_index"] == bot.last_ballot.index(played)
    assert len(values["means"]) == k == len(values["policy_log_odds"])
    assert preference["played_index"] == allocation["played_index"]
    if explore:
        assert bot.last_exploration is not None and len(bot.last_exploration["added"]) == 1
    if others:
        assert {"diversity_skipped", "forced_single_added", "tiebreak_near_set",
                "adaptive_k_applied", "refusal_observations"} <= set(record)
