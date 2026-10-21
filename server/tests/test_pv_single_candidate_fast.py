"""The single-candidate latency switch (``SHENGJI_PV_SINGLE_CANDIDATE_FAST``):
when the admission returns one candidate and no exact lead stage would start
on it, the value pass is skipped.  The worlds are still drawn (the sampler
stream is unchanged), and the selection rules and the doomed-throw
finalization still run on them.

Torch-free and package-free.  Witnesses: (a) a sole doomed throw is finalized
to its forced component exactly as with the pass, under the swap and under the
re-select, and the decision after it is the flag-off decision with the same
sampler state; (b) over seeded rounds with release 46's rules every decision
(played cards, record, sampler state) is the flag-off one, the only record
differences being the skipped pass's own fields; (c) where it does not apply
(more than one candidate, an exact lead stage that starts, ``lgf``, an
overridden value pass) the pass runs; (d) env, name and defaults.
"""
import copy

import numpy as np
import pytest

from shengji.train import pv_search_policy as pv
from test_pv_admission_rules import ZeroEvaluator, predict
from test_pv_adaptive_worlds import RELEASE42_RULES
from test_pv_doomed_throw_reselect import DECISIONS, DTR_RULES, HashNoiseEvaluator, SEAT, yjqj
from test_pv_doomed_throw_reselect_exact_guard import R46_ENV
from test_pv_leaf_greedy_finish import R46_RULES
from test_pv_small_joker_lead import _fresh_round
from test_pv_tree_search import endgame

FLAG = "SHENGJI_PV_SINGLE_CANDIDATE_FAST"
#: the fields a skipped pass leaves out: its value, batches and evaluations, and the marker
SKIPPED = ("value_means", "value_batches", "value_evaluations", "single_candidate_fast")
#: release 46's rules with a deeper exact lead and the exact follow stage, at bounds the
#: reference solvers finish quickly
SERVED_RULES = dict(R46_RULES, exact_deep_cards=5, exact_follow=True)


class CountingEvaluator(HashNoiseEvaluator):
    def __init__(self):
        self.leaves = 0

    def score(self, leaves, seat):
        self.leaves += len(leaves)
        return super().score(leaves, seat)


def bot(on, rules, evaluator=None, worlds=8, seed=17, cls=pv.PVSearchBot, candidates=8):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=worlds, candidates=candidates,
                               cap=4000, batch_size=128, **rules)
    b = cls(predict, evaluator=evaluator or ZeroEvaluator(), version=2, config=config,
            checkpoint="/dev/null", seed=seed)
    if on:
        b.single_candidate_fast = True
    return b


def comparable(record, skipped=False):
    out = {k: v for k, v in record.items() if not k.endswith("seconds") and not k.endswith("_ms")}
    if skipped:
        for key in SKIPPED:
            out.pop(key, None)
    return out


def assert_same_decision(off, on, rnd, seat):
    a = off.decide_play(copy.deepcopy(rnd), seat)
    b = on.decide_play(copy.deepcopy(rnd), seat)
    assert a == b
    skipped = bool(on.last_decision_record.get("single_candidate_fast"))
    assert comparable(off.last_decision_record, skipped) == comparable(on.last_decision_record, skipped)
    assert off.sampler.rng.getstate() == on.sampler.rng.getstate()
    return a, skipped


# ------------------------------------------------- (a) a sole doomed throw

class SoleThrow(pv.PVSearchBot):
    """The served search with the admission narrowed to one given lead (slot 0
    is that lead, as the anchor contract requires)."""
    sole = None

    def _effective_anchor_key(self, anchor_key):
        if self.sole is None:
            return super()._effective_anchor_key(anchor_key)
        return tuple(sorted(self.sole))

    def _admission(self, rnd, seat, actions, preferences, anchor_index, worlds, check_budget=None):
        chosen = super()._admission(rnd, seat, actions, preferences, anchor_index, worlds,
                                    check_budget)
        if self.sole is None:
            return chosen
        key = tuple(sorted(self.sole))
        return [next(i for i, a in enumerate(actions) if tuple(sorted(a)) == key)]


@pytest.mark.parametrize("rule", ["swap", "reselect"])
def test_a_sole_doomed_throw_is_finalized_and_the_next_decision_is_unchanged(rule):
    rules = (dict(RELEASE42_RULES) if rule == "swap"
             else dict(DTR_RULES, doomed_throw_reselect=True))
    d = DECISIONS["SJ"]
    rnd = yjqj(d["plays"])
    off = bot(False, rules, CountingEvaluator(), worlds=16, cls=SoleThrow)
    on = bot(True, rules, CountingEvaluator(), worlds=16, cls=SoleThrow)
    off.sole = on.sole = d["throw"]
    played, skipped = assert_same_decision(off, on, rnd, SEAT)
    assert skipped and played == d["played"]               # the forced component
    record = on.last_decision_record
    assert record["admitted"] == [d["throw"]] and record["played"] == d["played"]
    assert record["value_means"] == [None] and record["value_batches"] == 0
    assert record["value_evaluations"] == 0
    assert off.last_decision_record["value_evaluations"] == 16
    assert on.evaluator.leaves == 0 and off.evaluator.leaves == 16
    doomed = {k: v for k, v in record.items() if k.startswith("doomed_throw_")}
    assert doomed and doomed == {k: v for k, v in off.last_decision_record.items()
                                 if k.startswith("doomed_throw_")}
    assert (doomed.get("doomed_throw_swap_applied") is True
            or doomed.get("doomed_throw_reselect_fallback_forced") is True)
    # the second decision of the sequence: the next seat, the full ballot again
    rnd.play(SEAT, played)
    off.sole = on.sole = None
    _, skipped = assert_same_decision(off, on, rnd, rnd.turn)
    assert not skipped and len(on.last_decision_record["admitted"]) > 1


# ------------------------------------------------- (b) seeded rounds

@pytest.mark.parametrize("seed", [17, 23])
def test_seeded_rounds_are_the_flag_off_decisions(seed):
    off = bot(False, SERVED_RULES, CountingEvaluator(), seed=seed)
    on = bot(True, SERVED_RULES, CountingEvaluator(), seed=seed)
    decisions, skips, after_skip = 0, 0, 0
    previous = False
    rnd = _fresh_round(seed)
    while rnd.phase == "play":
        seat = rnd.turn
        played, skipped = assert_same_decision(off, on, rnd, seat)
        decisions += 1
        skips += skipped
        after_skip += previous
        previous = skipped
        if skipped:
            assert len(on.last_decision_record["admitted"]) == 1
            assert on.last_decision_record["value_means"] == [None]
        rnd.play(seat, played)
    assert decisions > 40 and skips >= 3 and after_skip >= 3
    assert on.evaluator.leaves < off.evaluator.leaves


# ------------------------------------------------- (c) where it does not apply

def test_the_pass_runs_where_a_consumer_reads_it():
    rnd = _fresh_round(17)                                  # the opening lead: no exact stage
    b = bot(True, SERVED_RULES)
    assert b._exact_lead_gate(rnd, [["x"]]) == "ineligible"
    assert b._single_candidate_fast(rnd, [["x"]])
    assert not b._single_candidate_fast(rnd, [["x"], ["y"]])
    assert not bot(False, SERVED_RULES)._single_candidate_fast(rnd, [["x"]])
    lgf = bot(True, dict(SERVED_RULES, leaf_greedy_finish=True))
    assert not lgf._single_candidate_fast(rnd, [["x"]])

    class OwnPass(pv.PVSearchBot):
        def _value_means(self, rnd, seat, actions, worlds, check_budget=None):
            return super()._value_means(rnd, seat, actions, worlds, check_budget)
    assert not bot(True, SERVED_RULES, cls=OwnPass)._single_candidate_fast(rnd, [["x"]])


def test_an_exact_lead_stage_that_starts_keeps_the_pass():
    """Without the deeper rule a one-candidate lead inside the card bound still
    starts the exact lead stage, which reads the base means: no skip."""
    rules = dict(R46_RULES)                                 # exact lead, no exact_deep_cards
    b = bot(True, rules)
    end = endgame(3)
    assert b._exact_lead_gate(end, [["x"]]) is None
    assert not b._single_candidate_fast(end, [["x"]])
    deep = bot(True, dict(rules, exact_deep_cards=7))
    assert deep._exact_lead_gate(end, [["x"]]) == "single_candidate"
    assert deep._single_candidate_fast(end, [["x"]])


# ------------------------------------------------- (d) env, name and defaults

def test_the_switch_is_off_by_default_and_enters_no_name():
    assert pv.PVSearchBot.single_candidate_fast is False
    assert "single_candidate_fast" not in vars(bot(False, SERVED_RULES))
    assert pv.latency_switches({FLAG: "1"}) == {"encode_prefix_cache": False,
                                                "single_candidate_fast": True}
    with pytest.raises(pv.PVSearchPolicyError, match=FLAG):
        pv.latency_switches({FLAG: "true"})
    env = {**R46_ENV, "SHENGJI_PV_CKPT": "/x.npz", "SHENGJI_PV_SHA256": "f" * 64}
    assert pv.pv_env_recipe({**env, FLAG: "1"}) == pv.pv_env_recipe(env)
    off = bot(False, SERVED_RULES)
    rnd = _fresh_round(23)
    off.decide_play(copy.deepcopy(rnd), rnd.turn)
    assert "single_candidate_fast" not in off.last_decision_record
    assert np.isfinite(off.last_decision_record["value_means"]).all()
