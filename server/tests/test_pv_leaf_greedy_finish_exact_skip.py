"""The OPTIONAL exact-stage yield of the greedy-finished value leaf
(``leaf_greedy_finish_exact_skip``, ``SHENGJI_PV_LEAF_GREEDY_FINISH_EXACT_SKIP``,
token ``lgfx``; requires ``lgf`` and an exact stage): on a decision an exact
stage is eligible for (the stage's own gate) the value pass scores the plain
heuristic leaf, so the base pass costs what it does without ``lgf`` and the
exact stage keeps its start share of the serving budget; elsewhere ``lgf``
applies unchanged.

Torch-free and package-free except the name tests.  Witnesses: (a) flag off,
the bot, its config and payload are the ``lgf`` bot's; (b) over seeded rounds
with release 46's exact lead stage and the exact follow stage, a skipped
decision is the flag-off decision record for record, a non-skipped one is the
``lgf`` decision record for record, and "skipped" is exactly "an exact stage
started"; (c) the gates reproduce the exact lead stage's statuses; (d) env /
name / digest / refusals.
"""
import copy
import re

import pytest

from shengji.train import pv_search_policy as pv
from test_pv_admission_rules import ZeroEvaluator, names, predict, production_package  # noqa: F401
from test_pv_doomed_throw_reselect import HashNoiseEvaluator, throw_loving_scores
from test_pv_leaf_greedy_finish import LEAF_KEYS, LGF_ENV, R46_RULES, leaf_bot
from test_pv_small_joker_lead import _fresh_round
from test_pv_tree_search import endgame

FLAG = "SHENGJI_PV_LEAF_GREEDY_FINISH_EXACT_SKIP"
SKIP_KEY = "leaf_greedy_finish_exact_skipped"
LGFX_ENV = {**LGF_ENV, FLAG: "1"}
#: release 46's rules plus the exact follow stage (the reference solver, its
#: default card bound), so both exact stages are exercised package-free
EXACT_RULES = dict(R46_RULES, exact_follow=True)


def skip_bot(evaluator=None, worlds=2, seed=17, **rules):
    return leaf_bot(evaluator, worlds=worlds, seed=seed, leaf_greedy_finish_exact_skip=True,
                    **rules)


def _comparable(record):
    return {k: v for k, v in record.items() if not k.endswith("seconds")}


# ------------------------------------------------- (a) flag off is the lgf bot

def test_flag_off_is_the_lgf_bot():
    lgf = leaf_bot(worlds=8, **EXACT_RULES)
    off = leaf_bot(worlds=8, leaf_greedy_finish_exact_skip=False, **EXACT_RULES)
    assert off.leaf_greedy_finish_exact_skip is False
    assert "leaf_greedy_finish_exact_skip" not in vars(off)
    assert "_leaf_greedy_exact_skipped" not in vars(off)
    assert set(vars(off)) == set(vars(lgf)) and off.config == lgf.config
    assert pv.PVSearchBot.leaf_greedy_finish_exact_skip is False
    assert pv.PVSearchBot._leaf_greedy_exact_skipped is False
    assert pv.LEAF_GREEDY_EXACT_SKIP_DEFAULTS == {"leaf_greedy_finish_exact_skip": False}
    on = skip_bot(worlds=8, **EXACT_RULES)
    assert vars(on)["leaf_greedy_finish_exact_skip"] is True
    assert on.config.leaf_greedy_finish_exact_skip is True


def test_flag_off_decisions_carry_no_field():
    rnd = _fresh_round(707_201); seat = rnd.turn
    bot = leaf_bot(HashNoiseEvaluator(), worlds=4, **EXACT_RULES)
    bot.decide_play(copy.deepcopy(rnd), seat)
    assert SKIP_KEY not in bot.last_decision_record
    assert "_leaf_greedy_exact_skipped" not in vars(bot)


# ------------------------------------------------- (b) seeded rounds

def test_skipped_decisions_are_flag_off_and_others_are_lgf_over_seeded_rounds():
    """Paired bots on one trajectory (the flag-off bot's): plain (``lgf`` off),
    ``lgf`` and ``lgf`` + ``lgfx``, every seat's sampler stream synchronised.
    On a decision an exact stage started, ``lgfx`` is the plain bot record for
    record (its value pass scored `_leaf`, no reply ply ran, the exact stage
    saw the same base); on every other decision it is the ``lgf`` bot."""
    evaluator = HashNoiseEvaluator()
    decisions = skipped = applied = lead_skips = follow_skips = 0
    for seed in range(707_001, 707_003):
        rnd = _fresh_round(seed)
        plain = [leaf_bot(evaluator, worlds=8, seed=100 + s, on=False, **EXACT_RULES)
                 for s in range(4)]
        lgf = [leaf_bot(evaluator, worlds=8, seed=100 + s, **EXACT_RULES) for s in range(4)]
        lgfx = [skip_bot(evaluator, worlds=8, seed=100 + s, **EXACT_RULES) for s in range(4)]
        for bot in plain + lgf + lgfx:
            bot.scores = throw_loving_scores
        while rnd.phase == "play":
            seat = rnd.turn
            state = plain[seat].sampler.rng.getstate()
            lgf[seat].sampler.rng.setstate(state)
            lgfx[seat].sampler.rng.setstate(state)
            a = plain[seat].decide_play(copy.deepcopy(rnd), seat)
            b = lgf[seat].decide_play(copy.deepcopy(rnd), seat)
            c = lgfx[seat].decide_play(copy.deepcopy(rnd), seat)
            ra, rb, rc = (x[seat].last_decision_record for x in (plain, lgf, lgfx))
            decisions += 1
            assert rc["schema"] == pv.RECORD_SCHEMA and type(rc[SKIP_KEY]) is bool
            assert SKIP_KEY not in ra and SKIP_KEY not in rb
            started = (ra.get("exact_lead_status") not in (None, "ineligible", "single_candidate")
                       or "exact_follow_attempted" in ra)
            # "skipped" is exactly the exact stages' own gate
            assert rc[SKIP_KEY] is started
            mine = {k: v for k, v in _comparable(rc).items() if k != SKIP_KEY}
            if rc[SKIP_KEY]:
                skipped += 1
                lead_skips += "exact_follow_attempted" not in ra
                follow_skips += "exact_follow_attempted" in ra
                assert c == a
                assert rc["leaf_greedy_finish_applied"] is False
                assert rc["leaf_greedy_reply_plays"] == rc["leaf_greedy_reply_evaluations"] == 0
                assert rc["leaf_greedy_uncached_leaves"] == 0
                assert {k: v for k, v in mine.items() if k not in LEAF_KEYS} == _comparable(ra)
                if "exact_lead_base_value_means" in ra:
                    # the value pass is the flag-off pass
                    assert rc["exact_lead_base_value_means"] == ra["exact_lead_base_value_means"]
            else:
                applied += rc["leaf_greedy_finish_applied"]
                assert c == b and mine == _comparable(rb)
            rnd.play(seat, a)
    print(f"\nlgfx parity: decisions={decisions} skipped={skipped} (leads={lead_skips} "
          f"follows={follow_skips}) lgf_applied={applied}")
    assert decisions >= 40 and lead_skips > 0 and follow_skips > 0 and applied > 0


def test_a_skipped_decision_runs_no_finish_at_all(monkeypatch):
    """On an exact-eligible endgame lead the greedy finish is never called."""
    from shengji.train import pv_tree_search as tree
    calls = []
    real = tree.greedy_finish_current_trick

    def spy(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)
    monkeypatch.setattr(tree, "greedy_finish_current_trick", spy)
    rnd = endgame(3); seat = rnd.turn
    assert not rnd.trick.plays and max(map(len, rnd.hands)) <= 4
    bot = skip_bot(HashNoiseEvaluator(), worlds=4, **EXACT_RULES)
    bot.decide_play(copy.deepcopy(rnd), seat)
    record = bot.last_decision_record
    assert record[SKIP_KEY] is True and record["exact_lead_status"] == "complete"
    assert calls == []
    lgf = leaf_bot(HashNoiseEvaluator(), worlds=4, **EXACT_RULES)
    lgf.decide_play(copy.deepcopy(rnd), seat)
    assert calls and lgf.last_decision_record["leaf_greedy_finish_applied"] is True


# ------------------------------------------------- (c) the gates

def test_the_gates_are_the_exact_stages_own():
    rnd = endgame(3); seat = rnd.turn
    bot = skip_bot(**EXACT_RULES)
    assert bot._exact_lead_gate(rnd, [["D8"], ["DQ"]]) is None
    assert bot._exact_follow_eligible(rnd, [["D8"], ["DQ"]]) is False      # a lead
    deep = skip_bot(exact_deep_cards=7, **EXACT_RULES)
    assert deep._exact_lead_gate(rnd, [["D8"]]) == "single_candidate"
    assert bot._exact_lead_gate(rnd, [["D8"]]) is None                    # 4-card rule
    early = _fresh_round(707_202)
    assert bot._exact_lead_gate(early, [["D8"], ["DQ"]]) == "ineligible"
    rnd.play(seat, ["D8"])
    assert bot._exact_lead_gate(rnd, [["SA"], ["SQ"]]) == "ineligible"     # a follow
    assert bot._exact_follow_eligible(rnd, [["SA"], ["SQ"]]) is True
    assert bot._exact_follow_eligible(rnd, [["SA"]]) is False
    nofollow = skip_bot(**R46_RULES)
    assert nofollow._exact_follow_eligible(rnd, [["SA"], ["SQ"]]) is False


# ------------------------------------------------- (d) env, name, digest, refusals

def _rules_prefix(name):
    return re.sub(r"-r[0-9a-f]{8}-bury-.*$", "", name)


def test_lgf_name_unchanged_when_off_and_lgfx_token_after_lgf(production_package):
    lgf_name, = names(LGF_ENV)
    for raw in ("0", ""):
        assert names({**LGF_ENV, FLAG: raw}) == [lgf_name]
    on, = names(LGFX_ENV)
    assert on != lgf_name and "-vdef-lgf-lgfx-ed7-" in on
    assert _rules_prefix(on) == _rules_prefix(lgf_name).replace("-lgf-", "-lgf-lgfx-")
    tokens = [t for _, t in pv.RULE_TOKENS]
    assert tokens.index("lgfx") == tokens.index("lgf") + 1 and tokens[-1] == "orc"
    assert pv.RULE_FLAGS["LEAF_GREEDY_FINISH_EXACT_SKIP"] == "leaf_greedy_finish_exact_skip"
    assert pv.pv_env_recipe(LGFX_ENV)["leaf_greedy_finish_exact_skip"] is True
    assert "leaf_greedy_finish_exact_skip" not in pv.pv_env_recipe({**LGF_ENV, FLAG: "0"})


def test_payload_carries_the_rule_only_when_on():
    base = pv.PVSearchConfig(checkpoint_sha256="f" * 64, serving_budget_seconds=3.0,
                             leaf_greedy_finish=True, **R46_RULES)
    off = pv.recipe_payload(base)
    assert "leaf_greedy_finish_exact_skip" not in off and "leaf_finish_exact_rule" not in off
    on = pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64,
                                             serving_budget_seconds=3.0, leaf_greedy_finish=True,
                                             leaf_greedy_finish_exact_skip=True, **R46_RULES))
    assert on["leaf_greedy_finish_exact_skip"] is True
    assert on["leaf_finish_exact_rule"] == pv.LEAF_GREEDY_EXACT_SKIP_RULE_ID
    assert {k: v for k, v in on.items()
            if k not in ("leaf_greedy_finish_exact_skip", "leaf_finish_exact_rule")} == off


@pytest.mark.parametrize("rules", [
    dict(R46_RULES),                                                   # no lgf
    dict(leaf_greedy_finish=True),                                     # no exact stage
    dict({k: v for k, v in R46_RULES.items() if k != "exact_lead_endgame"},
         leaf_greedy_finish=True),
])
def test_the_rule_refuses_without_lgf_or_an_exact_stage(rules):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, leaf_greedy_finish_exact_skip=True,
                               **rules)
    with pytest.raises(pv.PVSearchPolicyError, match="requires leaf_greedy_finish and an exact"):
        pv.recipe_payload(config)
    with pytest.raises(pv.PVSearchPolicyError, match="requires leaf_greedy_finish and an exact"):
        pv.PVSearchBot(predict, evaluator=ZeroEvaluator(), version=2, config=config,
                       checkpoint="/dev/null", seed=1)


def test_the_follow_stage_alone_is_an_exact_stage():
    rules = {k: v for k, v in R46_RULES.items() if k != "exact_lead_endgame"}
    rules.pop("doomed_throw_reselect_exact_guard", None)
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, leaf_greedy_finish=True,
                               leaf_greedy_finish_exact_skip=True, exact_follow=True, **rules)
    assert pv.recipe_payload(config)["leaf_finish_exact_rule"] == pv.LEAF_GREEDY_EXACT_SKIP_RULE_ID


def test_env_flag_refuses_bad_values_and_a_missing_lgf(production_package):
    for bad in ("2", "true", "yes", " 1"):
        with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
            pv.pv_env_recipe({**LGF_ENV, FLAG: bad})
    without_lgf = {k: v for k, v in LGFX_ENV.items() if k != "SHENGJI_PV_LEAF_GREEDY_FINISH"}
    with pytest.raises(pv.PVSearchPolicyError, match="requires leaf_greedy_finish"):
        names(without_lgf)
    with pytest.raises(pv.PVSearchPolicyError, match="requires leaf_greedy_finish"):
        names({**without_lgf, "SHENGJI_PV_LEAF_GREEDY_FINISH": "0"})
    with pytest.raises(pv.PVSearchPolicyError, match="must be a bool"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, leaf_greedy_finish=True,
                                            exact_lead_endgame=True,
                                            leaf_greedy_finish_exact_skip=1))
