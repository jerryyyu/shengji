"""The OPTIONAL greedy-finished value leaf (``leaf_greedy_finish``,
``SHENGJI_PV_LEAF_GREEDY_FINISH``, token ``lgf``; search audit F5 / E4, board
S33): the leaf the value head scores has its current trick finished by the
tree's ``trick-greedy`` reply ply (the policy's top-4 follows plus the
heuristic's, each valued from the replying seat's team) instead of the
heuristic alone.  Admission, selection rules, the exact stages (which solve
from `_leaf`, unchanged) and the played action are what they were.

Torch-free and package-free.  Witnesses: (a) on the hand-built endgame the
scored leaf is the greedy-finished afterstate (the reply the heuristic misses),
`_leaf` stays the heuristic one, and a flag-off bot's scored leaf is `_leaf`;
(b) through a served decision the value pass finishes every leaf once, the
tie-break prices the SAME cached leaves (no leaf finished outside the pass),
and a root seat last to play runs no ply and decides exactly as the flag-off
bot; (c) a deadline inside the finish is serving's anchor fallback, never a
partial result; (d) flag off, the bot, its record and seeded rounds are the base
bot's decision for decision, and flag on the record carries the rule's fields
on every search decision; (e) env / name / digest / refusals / constants.
"""
import copy
import re

import numpy as np
import pytest

from shengji.ai.cwv_policy import afterstate
from shengji.ai.heuristic import HeuristicBot
from shengji.train import policy_value_search as module
from shengji.train import pv_search_policy as pv
from shengji.train import pv_tree_search as tree
from shengji.train.policy_value_search import PolicyValueBot
from shengji.train.pv_tree_config import PVTreeConfig, TREE_DEFAULTS
from test_pv_admission_rules import (PRODUCTION_ENV, PRODUCTION_SHA, ZeroEvaluator, names, predict,  # noqa: F401
                                     production_package)
from test_pv_doomed_throw_reselect import DTR_RULES, HashNoiseEvaluator, throw_loving_scores
from test_pv_doomed_throw_reselect_exact_guard import R46_ENV, R46_NAME
from test_pv_small_joker_lead import _fresh_round, served
from test_pv_tree_search import HashEvaluator, TeamEvaluator, endgame, plays_of

FLAG = "SHENGJI_PV_LEAF_GREEDY_FINISH"
LEAF_KEYS = {"leaf_greedy_finish_applied", "leaf_greedy_reply_plays", "leaf_greedy_reply_evaluations",
             "leaf_greedy_reply_differs_heuristic", "leaf_greedy_policy_rows",
             "leaf_greedy_uncached_leaves"}
#: release 46's rules (the package-free form of `test_pv_doomed_throw_reselect_exact_guard`)
R46_RULES = dict(doomed_throw_reselect=True, exact_lead_endgame=True, **DTR_RULES)
LGF_ENV = {**R46_ENV, FLAG: "1"}


def leaf_bot(evaluator=None, worlds=2, seed=17, on=True, budget=None, **rules):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=worlds, candidates=8,
                               cap=4000, batch_size=128, serving_budget_seconds=budget,
                               leaf_greedy_finish=on, **rules)
    return pv.PVSearchBot(predict, evaluator=evaluator or ZeroEvaluator(), version=2,
                          config=config, checkpoint="/dev/null", seed=seed)


def _comparable(record):
    return {k: v for k, v in record.items() if not k.endswith("seconds")}


def _plays(leaf):
    return [[(p.seat, list(p.cards)) for p in trick.plays] for trick in leaf.history]


# ------------------------------------------------- (a) the scored leaf

def test_the_scored_leaf_is_the_greedy_finished_afterstate_and_leaf_stays_heuristic():
    """Seat 1 leads D8 (hands [D2 S2 D2] [DQ D8 C2] [SQ SA C2] [HQ D5 H5]).  The
    heuristic follows SQ at seat 2; the value head (seat 2's team) prefers SA
    gone, so the greedy finish plays SA there (the tree's own witness)."""
    rnd = endgame(3); seat = rnd.turn
    world = ([list(h) for h in rnd.hands], list(rnd.buried))
    evaluator = TeamEvaluator(lambda leaf: 1.0 if "SA" not in leaf.hands[2] else 0.0)
    bot = leaf_bot(evaluator)
    bot._greedy_prefill(rnd, seat, [["D8"]], [world])
    leaf = bot._scored_leaf(rnd, seat, world[0], world[1], ["D8"], 0)
    assert plays_of(leaf.history[12]) == [(1, ["D8"]), (2, ["SA"]), (3, ["D5"]), (0, ["D2"])]
    assert len(leaf.history) == 13 and not leaf.trick.plays
    assert [c[0] for c in evaluator.calls] == [2, 0]        # each reply valued from its own seat
    assert bot._leaf_greedy["stats"] == {"tree_policy_rows": 2, "tree_forced_plays": 1,
                                         "tree_value_batches": 2, "tree_reply_plays": 3,
                                         "tree_reply_evaluations": 5,
                                         "tree_reply_differs_heuristic": 1,
                                         "tree_reply_differs_policy": 1}
    assert bot._leaf_greedy["uncached"] == 0
    assert bot._scored_leaf(rnd, seat, world[0], world[1], ["D8"], 0) is leaf    # the cache
    # `_leaf` (the exact stage's producer) is the heuristic finish, untouched
    heur = bot._leaf(rnd, seat, world[0], world[1], ["D8"], 0)
    assert plays_of(heur.history[12]) == [(1, ["D8"]), (2, ["SQ"]), (3, ["D5"]), (0, ["D2"])]
    assert _plays(heur) == _plays(afterstate(rnd, seat, world[0], world[1], ["D8"], finish_trick=True))
    # a leaf asked for outside the pass is finished on its own and counted
    other = bot._scored_leaf(rnd, seat, world[0], world[1], ["DQ"], 1)
    assert len(other.history) == 13 and bot._leaf_greedy["uncached"] == 1
    assert len(rnd.history) == 12 and sorted(rnd.hands[1]) == ["C2", "D8", "DQ"]   # root untouched
    # flag off: the scored leaf IS `_leaf`
    off = leaf_bot(TeamEvaluator(lambda leaf: 0.0), on=False)
    assert _plays(off._scored_leaf(rnd, seat, world[0], world[1], ["D8"], 0)) == _plays(heur)
    assert off._leaf_greedy is None and "_leaf_greedy" not in vars(off)


def test_the_finish_reuses_the_trees_greedy_ply_with_its_default_r():
    assert module.LEAF_GREEDY_REPLIES == 4 == TREE_DEFAULTS["reply_candidates"]
    assert pv.LEAF_GREEDY_FINISH_RULE == "value-leaf-trick-greedy-r4"
    assert tuple(tree.greedy_stats()) == tree.GREEDY_STATS
    rnd = endgame(3); seat = rnd.turn
    world = ([list(h) for h in rnd.hands], list(rnd.buried))
    evaluator = TeamEvaluator(lambda leaf: 1.0 if "SA" not in leaf.hands[2] else 0.0)
    greedy = tree.PVTreeSearchBot(predict, evaluator=evaluator, version=2, checkpoint="/dev/null",
                                  seed=17, config=pv.PVSearchConfig(
                                      checkpoint_sha256="f" * 64, worlds=2, candidates=8, cap=4000,
                                      batch_size=128, tree=PVTreeConfig(sims=8, cont="trick-greedy")))
    _, stats = greedy._tree_lookahead(rnd, seat, [["D8"]], [world])
    bot = leaf_bot(TeamEvaluator(lambda leaf: 1.0 if "SA" not in leaf.hands[2] else 0.0))
    bot._greedy_prefill(rnd, seat, [["D8"]], [world])
    mine = bot._leaf_greedy["stats"]
    # the same plies: the tree adds the final leaf valuation batch
    assert {k: v for k, v in stats.items() if k in mine and k != "tree_value_batches"} == \
        {k: v for k, v in mine.items() if k != "tree_value_batches"}
    assert stats["tree_value_batches"] == mine["tree_value_batches"] + 1


# ------------------------------------------------- (b) through a served decision

def test_value_pass_finishes_every_leaf_once_and_the_tiebreak_prices_the_same_leaves():
    """`ZeroEvaluator`: every mean ties, so the points tie-break rebuilds every
    admitted candidate in every world -- all cache hits, none finished twice."""
    rnd = _fresh_round(707_101)
    evaluator = HashEvaluator()
    bot = leaf_bot(evaluator, worlds=4, tiebreak_points=True)
    evaluator.scale = 0.0           # exact ties: the near-set is the whole ballot
    seat = rnd.turn
    bot.decide_play(copy.deepcopy(rnd), seat)
    record = bot.last_decision_record
    assert record["schema"] == pv.RECORD_SCHEMA and LEAF_KEYS <= set(record)
    assert record["leaf_greedy_finish_applied"] is True
    assert record["leaf_greedy_uncached_leaves"] == 0
    assert len(record["tiebreak_near_set"]) == len(record["admitted_indices"]) >= 2
    assert len(record["tiebreak_points"]) == len(record["tiebreak_near_set"])
    worlds, admitted = record["worlds"], len(record["admitted_indices"])
    # the value pass handed the evaluator one finished leaf per (world, candidate),
    # each with the root's trick resolved; the replies' own valuations precede it
    pass_leaves = evaluator.seen[-worlds * admitted:]
    assert all(len(leaf.history) == len(rnd.history) + 1 and not leaf.trick.plays
               for leaf in pass_leaves)
    assert record["leaf_greedy_reply_evaluations"] == len(evaluator.seen) - worlds * admitted
    assert record["leaf_greedy_reply_plays"] >= worlds * admitted     # >= one reply per leaf
    assert record["leaf_greedy_policy_rows"] <= record["leaf_greedy_reply_plays"]
    assert record["value_evaluations"] == worlds * admitted            # the pass itself, as before


def test_a_root_seat_last_to_play_runs_no_ply_and_decides_as_the_flag_off_bot():
    rnd = endgame(3)
    h = HeuristicBot()
    for _ in range(3):
        rnd.play(rnd.turn, h.decide_play(rnd, rnd.turn))
    seat = rnd.turn
    assert len(rnd.trick.plays) == 3
    on, off = leaf_bot(HashEvaluator(), worlds=4), leaf_bot(HashEvaluator(), worlds=4, on=False)
    a = on.decide_play(copy.deepcopy(rnd), seat)
    b = off.decide_play(copy.deepcopy(rnd), seat)
    ra, rb = on.last_decision_record, off.last_decision_record
    assert a == b
    assert ra["leaf_greedy_finish_applied"] is False and ra["leaf_greedy_reply_plays"] == 0
    assert ra["leaf_greedy_reply_evaluations"] == 0 and ra["leaf_greedy_uncached_leaves"] == 0
    assert {k: v for k, v in _comparable(ra).items() if k not in LEAF_KEYS} == _comparable(rb)
    assert not LEAF_KEYS & set(rb)


# ------------------------------------------------- (c) the deadline

def test_a_deadline_inside_the_finish_is_servings_anchor_fallback(monkeypatch):
    rnd = _fresh_round(707_102); seat = rnd.turn
    seen = {}

    def expire(bot, clones, target, gate, keep, version, stats=None):
        seen["gate"] = gate; seen["keep"] = keep; seen["clones"] = len(clones); seen["version"] = version
        raise pv.PVSearchBudgetExceeded("pv-search serving budget expired")
    monkeypatch.setattr(tree, "greedy_finish_current_trick", expire)
    bot = leaf_bot(HashEvaluator(), worlds=4, budget=3.0)
    before = bot.sampler.rng.getstate()
    played = bot.decide_play(copy.deepcopy(rnd), seat)
    record = bot.last_decision_record
    assert record["schema"] == pv.FALLBACK_SCHEMA and record["reason"] == "budget"
    assert played == HeuristicBot().decide_play(copy.deepcopy(rnd), seat) and not LEAF_KEYS & set(record)
    assert bot.sampler.rng.getstate() == before            # the sampler stream restored
    assert seen["gate"] is not None and seen["keep"] == module.LEAF_GREEDY_REPLIES and seen["version"] == 2
    assert seen["clones"] == 4 * 8 or seen["clones"] % 4 == 0   # W x K clones (K the admitted width)
    # without a serving budget the finish runs ungated
    bot = leaf_bot(HashEvaluator(), worlds=4)
    with pytest.raises(pv.PVSearchBudgetExceeded):
        bot.decide_play(copy.deepcopy(rnd), seat)
    assert seen["gate"] is None


# ------------------------------------------------- (d) flag off is the base bot

def test_flag_off_is_the_base_bot():
    base = served(ZeroEvaluator(), worlds=8, **R46_RULES)
    off = leaf_bot(worlds=8, on=False, **R46_RULES)
    assert off.leaf_greedy_finish is False and "leaf_greedy_finish" not in vars(off)
    assert "_leaf_greedy" not in vars(off)
    assert set(vars(off)) == set(vars(base)) and off.config == base.config
    assert PolicyValueBot.leaf_greedy_finish is False and PolicyValueBot._leaf_greedy is None
    assert module.LEAF_GREEDY_DEFAULTS == {"leaf_greedy_finish": False}
    on = leaf_bot(worlds=8, **R46_RULES)
    assert vars(on)["leaf_greedy_finish"] is True and on.config.leaf_greedy_finish is True


def test_flag_off_and_on_over_seeded_rounds():
    """Paired bots on one trajectory (the base bot's, release-46 rules): the
    flag-off bot is the base bot decision for decision; the flag-on bot carries
    the rule's fields on every search decision, never finishes a leaf outside
    the value pass, and where no reply ply ran (the root seat last to play, or
    an exact-stage decision over `_leaf`) plays exactly the base decision."""
    evaluator = HashNoiseEvaluator()
    decisions = applied = changed = exact = 0
    for seed in range(707_001, 707_003):
        rnd = _fresh_round(seed)
        base = [served(evaluator, worlds=8, seed=100 + s, **R46_RULES) for s in range(4)]
        off = [leaf_bot(evaluator, worlds=8, seed=100 + s, on=False, **R46_RULES) for s in range(4)]
        on = [leaf_bot(evaluator, worlds=8, seed=100 + s, **R46_RULES) for s in range(4)]
        for bot in base + off + on:
            bot.scores = throw_loving_scores
        while rnd.phase == "play":
            seat = rnd.turn
            state = base[seat].sampler.rng.getstate()
            off[seat].sampler.rng.setstate(state)
            on[seat].sampler.rng.setstate(state)
            a = base[seat].decide_play(copy.deepcopy(rnd), seat)
            b = off[seat].decide_play(copy.deepcopy(rnd), seat)
            c = on[seat].decide_play(copy.deepcopy(rnd), seat)
            ra, rb, rc = (x[seat].last_decision_record for x in (base, off, on))
            decisions += 1
            assert a == b and _comparable(ra) == _comparable(rb)
            assert not LEAF_KEYS & set(rb)
            assert LEAF_KEYS <= set(rc) and rc["leaf_greedy_uncached_leaves"] == 0
            assert rc["admitted_indices"] == ra["admitted_indices"]      # the admission is untouched
            stripped = {k: v for k, v in _comparable(rc).items() if k not in LEAF_KEYS}
            if rc["leaf_greedy_finish_applied"]:
                applied += 1
                changed += c != a
            else:
                assert rc["leaf_greedy_reply_plays"] == 0
                assert c == a and stripped == _comparable(ra)
            if ra.get("exact_lead_status") == "complete":
                exact += 1
                # the exact stage selects over its own means from `_leaf`: the same
                # means on both bots (the finished-leaf cache never reaches it)
                assert rc["value_means"] == ra["value_means"]
            rnd.play(seat, a)
    print(f"\nlgf parity: decisions={decisions} applied={applied} changed={changed} complete_exact={exact}")
    assert decisions >= 40 and applied > 0 and exact > 0


def test_the_harness_bot_carries_the_rule_too():
    rnd = _fresh_round(707_103); seat = rnd.turn
    bot = PolicyValueBot(predict, evaluator=ZeroEvaluator(), worlds=2, cap=4000, seed=3,
                         tiebreak_points=True, leaf_greedy_finish=True)
    bot.decide_play(copy.deepcopy(rnd), seat)
    record = bot.last_decision_record
    assert record["schema"] == "policy-admit-value-mean-v1" and LEAF_KEYS <= set(record)
    assert record["leaf_greedy_finish_applied"] is True and record["leaf_greedy_uncached_leaves"] == 0
    plain = PolicyValueBot(predict, evaluator=ZeroEvaluator(), worlds=2, cap=4000, seed=3,
                           tiebreak_points=True)
    plain.decide_play(copy.deepcopy(rnd), seat)
    assert not LEAF_KEYS & set(plain.last_decision_record)


# ------------------------------------------------- (e) env, name, digest, refusals

def _rules_prefix(name):
    return re.sub(r"-r[0-9a-f]{8}-bury-.*$", "", name)


def test_release46_rule_name_unchanged_when_off_and_lgf_token_after_lpft(production_package):
    assert names(R46_ENV) == [R46_NAME]
    for raw in ("0", ""):
        assert names({**R46_ENV, FLAG: raw}) == [R46_NAME]
    on, = names(LGF_ENV)
    assert on != R46_NAME and "-vdef-lgf-ed7-" in on
    assert _rules_prefix(on) == _rules_prefix(R46_NAME).replace("-vdef-ed7-", "-vdef-lgf-ed7-")
    tokens = [t for _, t in pv.RULE_TOKENS]
    assert tokens.index("lgf") == tokens.index("lpft") + 1 and tokens[-1] == "orc"
    assert pv.RULE_FLAGS["LEAF_GREEDY_FINISH"] == "leaf_greedy_finish"
    assert pv.pv_env_recipe(LGF_ENV)["leaf_greedy_finish"] is True
    assert "leaf_greedy_finish" not in pv.pv_env_recipe({**R46_ENV, FLAG: "0"})


def test_payload_carries_the_rule_only_when_on():
    base = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                             **R46_RULES)
    off = pv.recipe_payload(base)
    assert "leaf_greedy_finish" not in off and "leaf_finish" not in off
    on = pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA,
                                             serving_budget_seconds=3.0, leaf_greedy_finish=True,
                                             **R46_RULES))
    assert on["leaf_greedy_finish"] is True and on["leaf_finish"] == "value-leaf-trick-greedy-r4"
    assert {k: v for k, v in on.items() if k not in ("leaf_greedy_finish", "leaf_finish")} == off


@pytest.mark.parametrize("other", [dict(tree=PVTreeConfig(sims=8)), dict(adaptive_worlds=True),
                                   dict(adaptive_worlds_leads=True)])
def test_the_rule_refuses_the_tree_and_the_adaptive_worlds(other):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, leaf_greedy_finish=True, **other)
    with pytest.raises(pv.PVSearchPolicyError, match="does not combine"):
        pv.recipe_payload(config)
    with pytest.raises(pv.PVSearchPolicyError, match="does not combine"):
        pv.PVSearchBot(predict, evaluator=ZeroEvaluator(), version=2, config=config,
                       checkpoint="/dev/null", seed=1)


def test_env_flag_refuses_anything_but_0_or_1_and_bad_values(production_package):
    for bad in ("2", "true", "yes", " 1"):
        with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
            pv.pv_env_recipe({**R46_ENV, FLAG: bad})
    with pytest.raises(pv.PVSearchPolicyError, match="does not combine"):
        names({**PRODUCTION_ENV, FLAG: "1", "SHENGJI_PV_TREE_SIMS": "8"})   # no exact stage: the tree refusal is this rule's
    with pytest.raises(ValueError, match="leaf_greedy_finish must be a bool"):
        PolicyValueBot(predict, evaluator=ZeroEvaluator(), leaf_greedy_finish=1)
    with pytest.raises(pv.PVSearchPolicyError, match="must be a bool"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, leaf_greedy_finish="1"))
