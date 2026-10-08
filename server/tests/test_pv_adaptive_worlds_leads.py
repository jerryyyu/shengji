"""The leads-only scope of the pv-search unresolved-decision evidence rule
(``adaptive_worlds_leads``, ``SHENGJI_PV_ADAPTIVE_WORLDS_LEADS``).

The same rule as ``adaptive_worlds`` (the same constants, the same
`_adaptive_worlds_decision`), run only when the acting seat leads.  On a follow
the decision takes the flag-off path: the decision, the record (no
``adaptive_worlds_*`` key) and the sampler stream are the flag-off ones.

Witnesses: (a) off == main over self-play and pinned names/digests (release 42
and the ``aw`` name); (b) on, over the same self-play: every follow
byte-identical to flag-off, every lead identical to ``aw``; (c) a follow
allocates no matrix and draws once, a lead runs the rule; (d) exclusivity, env,
name token, digest, refusals (tree, a replaced reducer), saved panels.
"""
import copy
import hashlib

import numpy as np
import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.train import pv_search_policy as pv
from shengji.train.policy_value_search import leading
from shengji.train.pv_search_policy import RECORD_SCHEMA
from test_pv_adaptive_worlds import (RELEASE42_ENV, RELEASE42_NAME, RELEASE42_RULES,
                                     RULE_KEYS, ConstantEvaluator, MainServed, ClearEvaluator)
from test_pv_admission_rules import PRODUCTION_ENV, PRODUCTION_SHA, names, predict, \
    production_package  # noqa: F401
from test_pv_small_joker_lead import (RELEASE38_ENV, RELEASE38_NAME, PointsEvaluator,
                                      _fresh_round, _strip)

FLAG = "SHENGJI_PV_ADAPTIVE_WORLDS_LEADS"
AW_FLAG = "SHENGJI_PV_ADAPTIVE_WORLDS"
AW_NAME = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-dts-aw-reba5b0fc-bury-hybrid-0fc096017bf0"
AWL_NAME = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-dts-awl-r7965ea65-bury-hybrid-ed3b15d1e9a0"
W = 8


class HashNoiseEvaluator(PointsEvaluator):
    """`PointsEvaluator` plus deterministic world-dependent noise (a hash of the
    leaf's hands): stateless, so every arm scores a leaf identically, and noisy
    enough that leads trigger the rule."""

    def score(self, leaves, seat):
        base = super().score(leaves, seat)
        noise = [int(hashlib.sha256(repr([sorted(h) for h in leaf.hands]).encode())
                     .hexdigest()[:8], 16) / 2 ** 32 - 0.5 for leaf in leaves]
        return base + 0.2 * np.asarray(noise)


def _bot(cls, seat, rules, evaluator, **flags):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=W, candidates=8, cap=4000,
                               batch_size=128, **rules, **flags)
    return cls(predict, evaluator=evaluator, version=2, config=config,
               checkpoint="/dev/null", seed=100 + seat)


def _timeless(record):
    return {k: v for k, v in record.items()
            if k not in ("seconds", "adaptive_worlds_base_seconds")}


SELF_PLAY_SEEDS = tuple(range(707001, 707005))


@pytest.mark.parametrize("rules", [RELEASE42_RULES, {}], ids=["release42", "bare"])
def test_follows_are_flag_off_and_leads_are_aw_over_self_play(rules):
    evaluator = HashNoiseEvaluator()
    leads = follows = lead_triggered = lead_changed = 0
    for seed in SELF_PLAY_SEEDS:
        rnd = _fresh_round(seed)
        off = [_bot(pv.PVSearchBot, s, rules, evaluator) for s in range(4)]
        main = [_bot(MainServed, s, rules, evaluator) for s in range(4)]
        aw = [_bot(pv.PVSearchBot, s, rules, evaluator, adaptive_worlds=True) for s in range(4)]
        awl = [_bot(pv.PVSearchBot, s, rules, evaluator, adaptive_worlds_leads=True)
               for s in range(4)]
        while rnd.phase == "play":
            seat = rnd.turn
            state = off[seat].sampler.rng.getstate()
            for bots in (aw, awl):   # every arm starts the decision on the same stream
                bots[seat].sampler.rng.setstate(state)
            is_lead = leading(rnd)
            a = off[seat].decide_play(copy.deepcopy(rnd), seat)
            b = main[seat].decide_play(copy.deepcopy(rnd), seat)
            c = aw[seat].decide_play(copy.deepcopy(rnd), seat)
            d = awl[seat].decide_play(copy.deepcopy(rnd), seat)
            off_rec, awl_rec = off[seat].last_decision_record, awl[seat].last_decision_record
            # (a) off is main
            assert a == b and _strip(off_rec) == _strip(main[seat].last_decision_record)
            assert off[seat].sampler.rng.getstate() == main[seat].sampler.rng.getstate()
            assert not RULE_KEYS & set(off_rec)
            if is_lead:
                leads += 1
                aw_rec = aw[seat].last_decision_record
                assert d == c and _timeless(awl_rec) == _timeless(aw_rec)
                assert RULE_KEYS <= set(awl_rec) and awl_rec["schema"] == RECORD_SCHEMA
                assert awl[seat].sampler.rng.getstate() == aw[seat].sampler.rng.getstate()
                lead_triggered += awl_rec["adaptive_worlds_triggered"]
                lead_changed += d != a
            else:
                follows += 1
                assert d == a and _strip(awl_rec) == _strip(off_rec)
                assert not any(k.startswith("adaptive_worlds") for k in awl_rec)
                assert awl[seat].sampler.rng.getstate() == off[seat].sampler.rng.getstate()
            rnd.play(seat, a)
    assert leads >= 25 and follows >= 75 and lead_triggered > 0
    print(f"\nadaptive_worlds_leads census [{'release42' if rules else 'bare'}]: "
          f"leads={leads} follows={follows} lead_triggered={lead_triggered} "
          f"lead_played_changed={lead_changed}")


def _lead_and_follow(seed=707001):
    rnd = _fresh_round(seed)
    lead = copy.deepcopy(rnd)
    assert leading(lead)
    seat = rnd.turn
    rnd.play(seat, HeuristicBot().decide_play(rnd, seat))
    assert not leading(rnd)
    return lead, rnd


def _served(evaluator, budget=None, **rules):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=W, candidates=8, cap=4000,
                               batch_size=128, serving_budget_seconds=budget, **rules)
    return pv.PVSearchBot(predict, evaluator=evaluator, version=2, config=config,
                          checkpoint="/dev/null", seed=17)


def _instrument(bot):
    log = {"worlds": 0, "capture": []}
    orig_worlds, orig_score = bot._worlds, bot._score_leaves

    def _worlds(*a, **kw):
        log["worlds"] += 1
        return orig_worlds(*a, **kw)

    def _score_leaves(*a, capture=None, **kw):
        log["capture"].append(capture is not None)
        return orig_score(*a, capture=capture, **kw)
    bot._worlds, bot._score_leaves = _worlds, _score_leaves
    return log


def test_a_follow_allocates_no_matrix_and_draws_once():
    _, follow = _lead_and_follow()
    seat = follow.turn
    off = _served(ConstantEvaluator(), **RELEASE42_RULES)
    on = _served(ConstantEvaluator(), adaptive_worlds_leads=True, **RELEASE42_RULES)
    log = _instrument(on)
    a = off.decide_play(copy.deepcopy(follow), seat)
    b = on.decide_play(copy.deepcopy(follow), seat)
    assert a == b and log == {"worlds": 1, "capture": [False]}
    assert _strip(on.last_decision_record) == _strip(off.last_decision_record)
    assert on.sampler.rng.getstate() == off.sampler.rng.getstate()


def test_a_lead_runs_the_rule_and_a_later_follow_carries_no_stale_state():
    lead, follow = _lead_and_follow()
    bot = _served(ConstantEvaluator(), adaptive_worlds_leads=True)
    log = _instrument(bot)
    bot.decide_play(copy.deepcopy(lead), lead.turn)
    rec = bot.last_decision_record
    # the zero/zero tie: triggered, 4W on the admitted set
    assert rec["adaptive_worlds_triggered"] is True and rec["adaptive_worlds_total"] == 4 * W
    assert log["worlds"] == 1 + pv.ADAPTIVE_WORLDS_EXTRA_ROUNDS and log["capture"][0] is True
    bot.decide_play(copy.deepcopy(follow), follow.turn)
    assert not any(k.startswith("adaptive_worlds") for k in bot.last_decision_record)
    assert bot._adaptive_worlds is None


def test_a_budgeted_follow_is_flag_off():
    _, follow = _lead_and_follow()
    off = _served(ConstantEvaluator(), budget=100.0)
    on = _served(ConstantEvaluator(), budget=100.0, adaptive_worlds_leads=True)
    a = off.decide_play(copy.deepcopy(follow), follow.turn)
    b = on.decide_play(copy.deepcopy(follow), follow.turn)
    assert a == b and _strip(on.last_decision_record) == _strip(off.last_decision_record)
    assert on.sampler.rng.getstate() == off.sampler.rng.getstate()


# ------------------------------------------------------- names, digest, env

def test_existing_names_unchanged_when_off(production_package):
    for raw in (None, "0", ""):
        extra = {} if raw is None else {FLAG: raw}
        assert names({**RELEASE38_ENV, **extra}) == [RELEASE38_NAME]
        assert names({**RELEASE42_ENV, **extra}) == [RELEASE42_NAME]
        assert names({**RELEASE42_ENV, AW_FLAG: "1", **extra}) == [AW_NAME]
    config = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0)
    assert pv.recipe_digest(config) == "4a09aef5"
    assert "adaptive_worlds_leads" not in pv.recipe_payload(config)
    aw = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                           adaptive_worlds=True)
    assert "adaptive_worlds_leads" not in pv.recipe_payload(aw)


def test_awl_token_last_and_digest_when_on(production_package):
    on, = names({**RELEASE42_ENV, FLAG: "1"})
    assert on == AWL_NAME
    every, = names({**RELEASE42_ENV, FLAG: "1", "SHENGJI_PV_SMALL_JOKER_GUARD": "1"})
    assert every.startswith("pv-search-491ee4bf-w64-k8-div-rc-tb-la-dts-sjg-awl-r")
    assert pv.RULE_TOKENS[-2] == ("adaptive_worlds_leads", "awl")   # then dtr
    assert pv.RULE_FLAGS["ADAPTIVE_WORLDS_LEADS"] == "adaptive_worlds_leads"
    base = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0)
    aw = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                           adaptive_worlds=True)
    awl = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                            adaptive_worlds_leads=True)
    payload = pv.recipe_payload(awl)
    assert payload["adaptive_worlds_leads"] is True and "adaptive_worlds" not in payload
    assert payload["adaptive_worlds_z"] == pv.ADAPTIVE_WORLDS_Z == 2.0
    assert payload["adaptive_worlds_extra_rounds"] == pv.ADAPTIVE_WORLDS_EXTRA_ROUNDS == 3
    assert payload["adaptive_worlds_start_fraction"] == 0.5
    assert payload["adaptive_worlds_soft_fraction"] == 0.8
    digests = {pv.recipe_digest(c) for c in (base, aw, awl)}
    assert len(digests) == 3
    assert pv.ADAPTIVE_WORLDS_DEFAULTS["adaptive_worlds_leads"] is False
    assert pv.PVSearchBot.adaptive_worlds_leads is False   # the class-level off default


@pytest.mark.parametrize("bad", ["2", "true", "yes", "on", " 1"])
def test_env_flag_refuses_anything_but_0_or_1(bad):
    with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
        pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: bad})
    assert "adaptive_worlds_leads" not in pv.pv_env_recipe(PRODUCTION_ENV)
    assert "adaptive_worlds_leads" not in pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: "0"})
    assert pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: "1"})["adaptive_worlds_leads"] is True


def test_bad_values_are_refused():
    with pytest.raises(pv.PVSearchPolicyError, match="must be a bool"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, adaptive_worlds_leads=1))
    with pytest.raises(pv.PVSearchPolicyError, match="adaptive_worlds_leads must be a bool"):
        _served(ClearEvaluator(), adaptive_worlds_leads="1")


# ------------------------------------------------------- refusals

def test_both_flags_are_exclusive(production_package):
    both = pv.PVSearchConfig(checkpoint_sha256="f" * 64, adaptive_worlds=True,
                             adaptive_worlds_leads=True)
    with pytest.raises(pv.PVSearchPolicyError, match="are exclusive"):
        pv.recipe_payload(both)
    with pytest.raises(pv.PVSearchPolicyError, match="are exclusive"):
        _served(ClearEvaluator(), adaptive_worlds=True, adaptive_worlds_leads=True)
    with pytest.raises(pv.PVSearchPolicyError, match="are exclusive"):
        names({**RELEASE42_ENV, AW_FLAG: "1", FLAG: "1"})


def test_tree_is_refused():
    from shengji.train.pv_tree_config import PVTreeConfig
    from shengji.train.pv_tree_search import PVTreeSearchBot
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, tree=PVTreeConfig(sims=8),
                               adaptive_worlds_leads=True)
    with pytest.raises(pv.PVSearchPolicyError,
                       match="adaptive_worlds_leads does not combine with the tree"):
        pv.recipe_payload(config)
    with pytest.raises(pv.PVSearchPolicyError, match="replaces it"):
        PVTreeSearchBot(predict, evaluator=ClearEvaluator(), version=2, config=config,
                        checkpoint="/dev/null")


def test_a_replaced_value_reducer_is_refused():
    class Weighted(pv.PVSearchBot):
        def _value_means(self, *a, **kw):
            return super()._value_means(*a, **kw)
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, adaptive_worlds_leads=True)
    with pytest.raises(pv.PVSearchPolicyError, match="adaptive_worlds_leads needs serving"):
        Weighted(predict, evaluator=ClearEvaluator(), version=2, config=config,
                 checkpoint="/dev/null")


# ------------------------------------------------------- saved panels predating the field

def test_saved_panel_without_the_field_still_binds():
    from test_panel_rank_root import inputs
    from shengji.eval import panel_rank_root
    panel, fixture, bot = inputs()
    for field in ("doomed_throw_swap", "small_joker_guard", "adaptive_worlds",
                  "adaptive_worlds_leads"):
        del panel['config'][field]
    root = panel_rank_root.bind_panel_rank_root(panel, fixture, bot)
    assert root.turn == fixture.seat


@pytest.mark.parametrize("damage", ["config_true", "bot_true"])
def test_saved_panel_without_the_field_refuses_the_rule_on(damage):
    from dataclasses import replace
    from test_panel_rank_root import inputs
    from shengji.eval import panel_rank_root
    panel, fixture, bot = inputs()
    del panel['config']['adaptive_worlds_leads']
    if damage == "config_true":
        bot.config = replace(bot.config, adaptive_worlds_leads=True)
    else:
        bot.adaptive_worlds_leads = True
    with pytest.raises(ValueError, match="config mismatch"):
        panel_rank_root.bind_panel_rank_root(panel, fixture, bot)
