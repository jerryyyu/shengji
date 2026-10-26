"""The OPTIONAL top-m restriction of the greedy leaf finish (``leaf_greedy_top``,
``SHENGJI_PV_LEAF_GREEDY_TOP=<m>``, token ``lgft<m>``) and the lead admission width
of ``wide_lead_admission`` (``wide_lead_k``, ``SHENGJI_PV_WIDE_LEAD_K=<k>``, token
``wla<k>`` off the default 32).

With the restriction on, a decision whose value pass would finish leaves greedily
and that admits more than ``m`` candidates scores every candidate on the plain
heuristic leaf, greedy-finishes only the plain top ``m``, and ranks the pruned
candidates below every kept one by their plain means.

Torch-free and package-free.  Witnesses: (a) ``m`` at least the admitted count is
the ``lgf`` bot decision for decision; (b) the plain pass is the ``lgf``-off bot's
value pass, mean for mean, on the same worlds; (c) only the kept candidates are
greedy-finished, the played candidate is a kept one, and no pruned leaf is ever
finished; (d) ``m = 1`` plays the plain argmax wherever no re-select moved it;
(e) a passed finish deadline leaves every leaf plain; (f) under a serving budget a
pruned decision completes as a search decision; (g) the width ``wide_lead_k``
admits that many on a lead and nothing on a follow; (h) env, name, payload and
refusals.
"""
import copy

import numpy as np
import pytest

from shengji.train import pv_search_policy as pv
from shengji.train.policy_value_search import leading
from test_pv_admission_rules import names, predict, production_package  # noqa: F401
from test_pv_doomed_throw_reselect import HashNoiseEvaluator, throw_loving_scores
from test_pv_leaf_greedy_finish import LEAF_KEYS, LGF_ENV, R46_RULES, leaf_bot
from test_pv_leaf_greedy_finish_exact_skip import LGFX_ENV
from test_pv_small_joker_lead import _fresh_round
from test_policy_world_search import state

ENV = "SHENGJI_PV_LEAF_GREEDY_TOP"
K_ENV = "SHENGJI_PV_WIDE_LEAD_K"
WLA = "SHENGJI_PV_WIDE_LEAD_ADMISSION"
TOP_KEYS = {"leaf_greedy_top_applied", "leaf_greedy_top_kept", "leaf_greedy_top_plain_means"}
SEEDS = (707_014, 707_001)


def _comparable(record, drop=()):
    return {k: v for k, v in record.items()
            if not k.endswith("seconds") and not k.endswith("_ms") and k not in drop}


def _paired_rounds(make_a, make_b, check, seeds=SEEDS):
    decisions = 0
    for seed in seeds:
        rnd = _fresh_round(seed)
        a_bots = [make_a(100 + s) for s in range(4)]
        b_bots = [make_b(100 + s) for s in range(4)]
        for bot in a_bots + b_bots:
            bot.scores = throw_loving_scores
        while rnd.phase == "play":
            seat = rnd.turn
            a = a_bots[seat].decide_play(copy.deepcopy(rnd), seat)
            b = b_bots[seat].decide_play(copy.deepcopy(rnd), seat)
            check(a, b, a_bots[seat], b_bots[seat], rnd)
            assert a_bots[seat].sampler.rng.getstate() == b_bots[seat].sampler.rng.getstate()
            decisions += 1
            rnd.play(seat, a)
    return decisions


def test_m_at_least_the_ballot_is_the_lgf_bot():
    evaluator = HashNoiseEvaluator()

    def check(a, b, plain, top, rnd):
        ra, rb = plain.last_decision_record, top.last_decision_record
        assert a == b
        assert _comparable(ra) == _comparable(rb, TOP_KEYS)
        assert rb["leaf_greedy_top_applied"] is False
        assert not TOP_KEYS & set(ra)

    n = _paired_rounds(lambda s: leaf_bot(evaluator, worlds=8, seed=s, **R46_RULES),
                       lambda s: leaf_bot(evaluator, worlds=8, seed=s, leaf_greedy_top=8,
                                          **R46_RULES), check)
    assert n >= 80


def test_the_plain_pass_is_the_lgf_off_value_pass_and_only_the_kept_are_finished(monkeypatch):
    evaluator = HashNoiseEvaluator()
    seen = {"pruned": 0, "decisions": 0}

    def check(a, b, off, top, rnd):
        ro, rt = off.last_decision_record, top.last_decision_record
        assert ro["admitted"] == rt["admitted"]
        if not rt["leaf_greedy_top_applied"]:
            return
        seen["pruned"] += 1
        means = np.asarray(rt["value_means"])
        plain = np.asarray(rt["leaf_greedy_top_plain_means"])
        if rt.get("exact_lead_status") == "complete":
            # the record's means are the exact stage's; the pass is checked elsewhere
            seen["exact"] = seen.get("exact", 0) + 1
            return
        # the plain pass is the flag-off value pass on the same worlds
        assert rt["leaf_greedy_top_plain_means"] == ro["value_means"]
        kept = rt["leaf_greedy_top_kept"]
        assert len(kept) == 3 and kept == sorted(kept)
        order = sorted(range(len(plain)), key=lambda i: (-plain[i], i))
        assert set(kept) == set(order[:3])
        pruned = [i for i in range(len(plain)) if i not in kept]
        assert np.array_equal(means[pruned], plain[pruned] - pv.LEAF_GREEDY_TOP_OFFSET)
        assert means[kept].min() > means[pruned].max()
        assert rt["leaf_greedy_uncached_leaves"] == 0
        position = rt["admitted_indices"].index(rt["selected_index"])
        if not rt.get("doomed_throw_reselect_applied") \
                and not rt.get("doomed_throw_reselect_fallback_forced"):
            assert position in kept, {k: v for k, v in rt.items() if "doomed" in k or "tiebreak" in k}
        else:
            seen["moved"] = seen.get("moved", 0) + 1
        seen["decisions"] += 1

    finished = []
    prefill = pv.PVSearchBot._greedy_prefill

    def spy(self, rnd, seat, actions, worlds, check_budget=None):
        finished.append(len(actions))
        return prefill(self, rnd, seat, actions, worlds, check_budget)
    monkeypatch.setattr(pv.PVSearchBot, "_greedy_prefill", spy)
    n = _paired_rounds(lambda s: leaf_bot(evaluator, worlds=8, seed=s, on=False, **R46_RULES),
                       lambda s: leaf_bot(evaluator, worlds=8, seed=s, leaf_greedy_top=3,
                                          **R46_RULES), check)
    assert n >= 80 and seen["decisions"] > 20
    assert seen["decisions"] + seen.get("exact", 0) == seen["pruned"]
    assert finished and max(finished) <= 3


def test_m_one_plays_the_plain_argmax_unless_a_reselect_moved_it():
    evaluator = HashNoiseEvaluator()
    seen = {"checked": 0}

    def check(a, b, off, top, rnd):
        rt = top.last_decision_record
        if not rt["leaf_greedy_top_applied"] or rt.get("exact_lead_status") == "complete" \
                or rt.get("doomed_throw_reselect_applied"):
            return
        plain = rt["leaf_greedy_top_plain_means"]
        best = max(range(len(plain)), key=lambda i: (plain[i], -i))
        assert rt["admitted_indices"].index(rt["selected_index"]) == best
        seen["checked"] += 1

    _paired_rounds(lambda s: leaf_bot(evaluator, worlds=8, seed=s, on=False, **R46_RULES),
                   lambda s: leaf_bot(evaluator, worlds=8, seed=s, leaf_greedy_top=1,
                                      **R46_RULES), check)
    assert seen["checked"] > 20


def test_a_passed_deadline_leaves_every_leaf_plain():
    evaluator = HashNoiseEvaluator()
    seen = {"fired": 0}

    def check(a, b, off, top, rnd):
        ro, rt = off.last_decision_record, top.last_decision_record
        if rt.get("leaf_greedy_deadline_fired") and rt["leaf_greedy_top_applied"]:
            means = np.asarray(rt["value_means"])
            kept = rt["leaf_greedy_top_kept"]
            assert list(means[kept]) == [ro["value_means"][i] for i in kept]
            seen["fired"] += 1

    def expired(seed):
        bot = leaf_bot(evaluator, worlds=8, seed=seed, leaf_greedy_top=3,
                       leaf_greedy_deadline_ms=1, **R46_RULES)
        prefill = bot._greedy_prefill

        def expired_prefill(*args, **kwargs):
            bot._leaf_greedy_deadline_at = float("-inf")
            return prefill(*args, **kwargs)
        bot._greedy_prefill = expired_prefill
        return bot

    _paired_rounds(lambda s: leaf_bot(evaluator, worlds=8, seed=s, on=False, **R46_RULES),
                   expired, check)
    assert seen["fired"] > 10


def test_a_pruned_decision_completes_under_the_serving_budget():
    rnd = _fresh_round(707_014)
    bot = leaf_bot(HashNoiseEvaluator(), worlds=8, budget=3.0, leaf_greedy_top=3, **R46_RULES)
    bot.scores = throw_loving_scores
    bot.decide_play(copy.deepcopy(rnd), rnd.turn)
    record = bot.last_decision_record
    assert record["schema"] == pv.RECORD_SCHEMA and record["work_complete"] is True
    assert record["leaf_greedy_top_applied"] is True and LEAF_KEYS <= set(record)
    # one value pass on every candidate plus the kept ones' finished leaves
    assert record["value_batches"] >= 2


def test_no_pruning_survives_into_the_next_decision():
    rnd = _fresh_round(707_014)
    bot = leaf_bot(HashNoiseEvaluator(), worlds=8, leaf_greedy_top=3, **R46_RULES)
    bot.scores = throw_loving_scores
    seat = rnd.turn
    rnd.play(seat, bot.decide_play(copy.deepcopy(rnd), seat))
    assert bot.last_decision_record["leaf_greedy_top_applied"] is True
    assert bot._leaf_greedy_pruned
    # a stale pruned set (every candidate of the next decision) must not reach it
    stale = copy.deepcopy(bot)
    stale.scores = throw_loving_scores
    stale._leaf_greedy_pruned = frozenset(tuple(a) for a in
                                          bot.last_decision_record["admitted"]) | {("SA",)}
    stale._leaf_greedy_top = {"leaf_greedy_top_applied": "stale"}
    seat = rnd.turn
    a = bot.decide_play(copy.deepcopy(rnd), seat)
    b = stale.decide_play(copy.deepcopy(rnd), seat)
    assert a == b
    assert _comparable(bot.last_decision_record) == _comparable(stale.last_decision_record)


@pytest.mark.parametrize("k", [24, 32])
def test_wide_lead_k_admits_k_on_a_lead_and_nothing_wider_on_a_follow(k):
    rnd = state()
    assert leading(rnd)
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=8, candidates=8, cap=4000,
                               batch_size=128, wide_lead_admission=True, wide_lead_k=k)
    bot = pv.PVSearchBot(predict, evaluator=HashNoiseEvaluator(), version=2, config=config,
                         checkpoint="/dev/null", seed=17)
    bot.decide_play(copy.deepcopy(rnd), rnd.turn)
    record = bot.last_decision_record
    assert record["wide_lead_admission_k"] == k and len(record["admitted_indices"]) == k
    assert bot._candidate_limit(rnd) == max(k, 16)
    assert ("wide_lead_k" in vars(bot)) == (k != pv.WIDE_LEAD_K)


def test_off_by_default_name_payload_and_refusals(production_package):  # noqa: F811
    assert pv.PVSearchBot.leaf_greedy_top == 0 and pv.PVSearchBot.wide_lead_k == pv.WIDE_LEAD_K
    off = leaf_bot(worlds=2)
    assert "leaf_greedy_top" not in vars(off) and "wide_lead_k" not in vars(off)
    lgfx, = names(LGFX_ENV)
    for raw in ("", "0"):
        assert names({**LGFX_ENV, ENV: raw}) == [lgfx]
    on, = names({**LGFX_ENV, ENV: "3"})
    assert "-lgf-lgfx-lgft3-" in on and on != lgfx
    ond, = names({**LGFX_ENV, ENV: "3", "SHENGJI_PV_LEAF_GREEDY_DEADLINE": "2"})
    assert "-lgf-lgfx-lgfd2000-lgft3-" in ond
    lgf_only, = names({**LGF_ENV, ENV: "3"})
    assert "-lgf-lgft3-" in lgf_only
    assert names({**LGFX_ENV, ENV: "4"}) != [on]
    assert pv.pv_env_recipe({**LGFX_ENV, ENV: "3"})["leaf_greedy_top"] == 3
    assert "leaf_greedy_top" not in pv.pv_env_recipe(LGFX_ENV)
    base = pv.PVSearchConfig(checkpoint_sha256="f" * 64, leaf_greedy_finish=True)
    payload = pv.recipe_payload(base)
    assert "leaf_greedy_top" not in payload and "wide_lead_k" not in payload
    on_payload = pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64,
                                                     leaf_greedy_finish=True, leaf_greedy_top=3))
    assert on_payload["leaf_greedy_top"] == {"m": 3, "rule": pv.LEAF_GREEDY_TOP_RULE_ID,
                                             "offset": pv.LEAF_GREEDY_TOP_OFFSET}
    assert {k: v for k, v in on_payload.items() if k != "leaf_greedy_top"} == payload
    without_lgf = {k: v for k, v in LGF_ENV.items() if k != "SHENGJI_PV_LEAF_GREEDY_FINISH"}
    for env in ({**without_lgf, ENV: "3"}, {**LGF_ENV, ENV: "abc"}, {**LGF_ENV, ENV: "-1"},
                {**LGF_ENV, ENV: "65"}, {**LGF_ENV, ENV: "1.5"}):
        with pytest.raises(pv.PVSearchPolicyError, match="LEAF_GREEDY_TOP|leaf_greedy_top"):
            pv.pv_env_recipe(env)
    for bad in (True, 1.5, -1, 65):
        with pytest.raises(pv.PVSearchPolicyError, match="leaf_greedy_top"):
            pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, leaf_greedy_finish=True,
                                                leaf_greedy_top=bad))
    with pytest.raises(pv.PVSearchPolicyError, match="requires leaf_greedy_finish"):
        leaf_bot(worlds=2, on=False, leaf_greedy_top=3)


def test_wide_lead_k_name_payload_and_refusals(production_package):  # noqa: F811
    wla32, = names({**LGFX_ENV, WLA: "1"})
    assert names({**LGFX_ENV, WLA: "1", K_ENV: "32"}) == [wla32] and "-wla-" in wla32
    wla24, = names({**LGFX_ENV, WLA: "1", K_ENV: "24"})
    assert "-ele-wla24-la-" in wla24 and wla24 != wla32
    both, = names({**LGFX_ENV, WLA: "1", K_ENV: "24", ENV: "3",
                   "SHENGJI_PV_LEAF_GREEDY_DEADLINE": "2"})
    assert "-wla24-" in both and "-lgfd2000-lgft3-" in both
    on = pv.PVSearchConfig(checkpoint_sha256="f" * 64, wide_lead_admission=True)
    assert pv.recipe_payload(on)["wide_lead_k"] == 32
    assert pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, wide_lead_admission=True,
                                               wide_lead_k=24))["wide_lead_k"] == 24
    for env in ({**LGFX_ENV, K_ENV: "24"}, {**LGFX_ENV, WLA: "1", K_ENV: "8"},
                {**LGFX_ENV, WLA: "1", K_ENV: "65"}, {**LGFX_ENV, WLA: "1", K_ENV: "x"}):
        with pytest.raises(pv.PVSearchPolicyError, match="WIDE_LEAD_K|wide_lead_k"):
            pv.pv_env_recipe(env)
    with pytest.raises(pv.PVSearchPolicyError, match="wide_lead_k needs wide_lead_admission"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, wide_lead_k=24))
