"""The OPTIONAL deadline on the greedy leaf finish (``leaf_greedy_deadline_ms``,
``SHENGJI_PV_LEAF_GREEDY_DEADLINE=<seconds>``, token ``lgfd<ms>``): once the
decision's elapsed time passes the deadline inside ``lgf``'s reply plies, the
finish stops and every leaf of the decision is the heuristic-finished `_leaf`,
the flag-off leaf.

Torch-free and package-free.  Witnesses: (a) a deadline that is never reached
is the ``lgf`` bot decision for decision (cards, record apart from the rule's
own fields, sampler state); (b) a deadline that has passed when the finish starts is the
``lgf``-off bot's value pass: the same cards and value means on every
decision, the record saying it fired and how many leaves it cut, and it fires
exactly where ``lgf`` runs a reply ply; (c) under a serving budget a fired
decision completes as a search decision; (d) env, name, payload, refusals.
"""
import copy

import pytest

from shengji.train import pv_search_policy as pv
from test_pv_admission_rules import names, production_package  # noqa: F401
from test_pv_doomed_throw_reselect import HashNoiseEvaluator, throw_loving_scores
from test_pv_leaf_greedy_finish import LEAF_KEYS, LGF_ENV, R46_RULES, leaf_bot
from test_pv_leaf_greedy_finish_exact_skip import LGFX_ENV
from test_pv_small_joker_lead import _fresh_round

ENV = "SHENGJI_PV_LEAF_GREEDY_DEADLINE"
DEADLINE_KEYS = {"leaf_greedy_deadline_fired", "leaf_greedy_deadline_cut_leaves"}


def _comparable(record, drop=()):
    return {k: v for k, v in record.items()
            if not k.endswith("seconds") and not k.endswith("_ms") and k not in drop}


def _paired_rounds(seeds, make_a, make_b, check):
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


def test_an_unreached_deadline_is_the_lgf_bot():
    evaluator = HashNoiseEvaluator()
    seen = {"applied": 0}

    def check(a, b, plain, guarded, rnd):
        ra, rb = plain.last_decision_record, guarded.last_decision_record
        assert a == b
        assert _comparable(ra) == _comparable(rb, DEADLINE_KEYS)
        assert rb["leaf_greedy_deadline_fired"] is False
        assert rb["leaf_greedy_deadline_cut_leaves"] == 0
        assert not DEADLINE_KEYS & set(ra)
        seen["applied"] += bool(ra["leaf_greedy_finish_applied"])

    n = _paired_rounds((707_014, 707_001),
                       lambda s: leaf_bot(evaluator, worlds=8, seed=s, **R46_RULES),
                       lambda s: leaf_bot(evaluator, worlds=8, seed=s, leaf_greedy_deadline_ms=60_000,
                                          **R46_RULES), check)
    assert n >= 80 and seen["applied"] > 20


def test_a_deadline_that_fires_at_once_is_the_lgf_off_value_pass():
    evaluator = HashNoiseEvaluator()
    seen = {"fired": 0, "decisions": 0}

    def check(a, b, off, guarded, rnd):
        ro, rg = off.last_decision_record, guarded.last_decision_record
        assert a == b and ro["value_means"] == rg["value_means"]
        assert LEAF_KEYS <= set(rg) and not LEAF_KEYS & set(ro)
        stripped = {k: v for k, v in _comparable(rg, DEADLINE_KEYS).items() if k not in LEAF_KEYS}
        assert stripped == _comparable(ro)
        fired = rg["leaf_greedy_deadline_fired"]
        cut = rg["leaf_greedy_deadline_cut_leaves"]
        # it fires exactly where a reply ply would run: the root seat not last
        assert fired == (len(rnd.trick.plays) < 3)
        assert cut == (len(rg["admitted"]) * 8 if fired else 0)
        assert rg["leaf_greedy_uncached_leaves"] == 0
        seen["fired"] += fired
        seen["decisions"] += 1

    _paired_rounds((707_014, 707_001),
                   lambda s: leaf_bot(evaluator, worlds=8, seed=s, on=False, **R46_RULES),
                   lambda s: _expired(leaf_bot(evaluator, worlds=8, seed=s,
                                               leaf_greedy_deadline_ms=1, **R46_RULES)), check)
    assert seen["decisions"] >= 80 and seen["fired"] > 20


def _expired(bot):
    """``bot`` whose deadline has always passed by the finish (a 1 ms deadline
    can still be ahead of a fast endgame decision's clock)."""
    prefill = bot._greedy_prefill

    def expired_prefill(*args, **kwargs):
        bot._leaf_greedy_deadline_at = float("-inf")
        return prefill(*args, **kwargs)
    bot._greedy_prefill = expired_prefill
    return bot


def test_the_deadline_is_measured_from_the_decisions_start(monkeypatch):
    rnd = _fresh_round(707_014)
    bot = leaf_bot(HashNoiseEvaluator(), worlds=2, leaf_greedy_deadline_ms=1200, **R46_RULES)
    seen = []
    search = bot._search

    def spy(rnd_, seat, anchor, started, check_budget=None):
        out = search(rnd_, seat, anchor, started, check_budget)
        seen.append((started, bot._leaf_greedy_deadline_at))
        return out
    monkeypatch.setattr(bot, "_search", spy)
    bot.decide_play(copy.deepcopy(rnd), rnd.turn)
    (started, at), = seen
    assert at == started + 1.2


def test_a_fired_decision_completes_under_the_serving_budget():
    rnd = _fresh_round(707_014)
    seat = rnd.turn
    bot = _expired(leaf_bot(HashNoiseEvaluator(), worlds=8, budget=3.0, leaf_greedy_deadline_ms=1,
                            **R46_RULES))
    bot.scores = throw_loving_scores
    bot.decide_play(copy.deepcopy(rnd), seat)
    record = bot.last_decision_record
    assert record["schema"] != pv.FALLBACK_SCHEMA and record["work_complete"] is True
    assert record["leaf_greedy_deadline_fired"] is True
    assert record["leaf_greedy_deadline_cut_leaves"] == 8 * len(record["admitted"])
    assert bot._leaf_greedy["cache"] == {}


def test_off_by_default_name_payload_and_refusals(production_package):  # noqa: F811
    assert pv.PVSearchBot.leaf_greedy_deadline_ms == 0
    off = leaf_bot(worlds=2)
    assert "leaf_greedy_deadline_ms" not in vars(off) and "_leaf_greedy_deadline_at" not in vars(off)
    assert vars(leaf_bot(worlds=2, leaf_greedy_deadline_ms=1200))["leaf_greedy_deadline_ms"] == 1200
    lgf, = names(LGF_ENV)
    lgfx, = names(LGFX_ENV)
    for raw in ("", "0"):
        assert names({**LGFX_ENV, ENV: raw}) == [lgfx]
    on, = names({**LGF_ENV, ENV: "1.2"})
    assert "-lgf-lgfd1200-" in on and on != lgf
    onx, = names({**LGFX_ENV, ENV: "1.2"})
    assert "-lgf-lgfx-lgfd1200-" in onx
    assert names({**LGFX_ENV, ENV: "1.4"}) != [onx]
    assert pv.pv_env_recipe({**LGFX_ENV, ENV: "1.2"})["leaf_greedy_deadline_ms"] == 1200
    assert "leaf_greedy_deadline_ms" not in pv.pv_env_recipe(LGFX_ENV)
    base = pv.PVSearchConfig(checkpoint_sha256="f" * 64, leaf_greedy_finish=True)
    payload = pv.recipe_payload(base)
    assert "leaf_greedy_deadline" not in payload and "leaf_greedy_deadline_ms" not in payload
    on_payload = pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64,
                                                     leaf_greedy_finish=True,
                                                     leaf_greedy_deadline_ms=1200))
    assert on_payload["leaf_greedy_deadline"] == {"ms": 1200, "rule": pv.LEAF_GREEDY_DEADLINE_RULE_ID}
    assert {k: v for k, v in on_payload.items() if k != "leaf_greedy_deadline"} == payload
    without_lgf = {k: v for k, v in LGF_ENV.items() if k != "SHENGJI_PV_LEAF_GREEDY_FINISH"}
    for env in ({**without_lgf, ENV: "1.2"}, {**LGF_ENV, ENV: "abc"}, {**LGF_ENV, ENV: "-1"},
                {**LGF_ENV, ENV: "0.0005"}, {**LGF_ENV, ENV: "61"}, {**LGF_ENV, ENV: "nan"}):
        with pytest.raises(pv.PVSearchPolicyError, match="LEAF_GREEDY_DEADLINE|leaf_greedy_deadline"):
            pv.pv_env_recipe(env)
    for bad in (True, 1.5, -1, 60_001):
        with pytest.raises(pv.PVSearchPolicyError, match="leaf_greedy_deadline_ms"):
            pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, leaf_greedy_finish=True,
                                                leaf_greedy_deadline_ms=bad))
    with pytest.raises(pv.PVSearchPolicyError, match="requires leaf_greedy_finish"):
        leaf_bot(worlds=2, on=False, leaf_greedy_deadline_ms=1200)
