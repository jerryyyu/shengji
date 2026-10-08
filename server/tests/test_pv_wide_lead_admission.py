"""The OPTIONAL lead admission width of the pv-search bot
(``wide_lead_admission``, ``SHENGJI_PV_WIDE_LEAD_ADMISSION``): on a LEAD the
policy admission shortlist is ``WIDE_LEAD_K`` (32) instead of the served K (8),
through the same admission path; follows are unchanged.

Torch-free and package-free (except the name pins): real engine positions, the
served wrapper's own sampler, admission and selection, stub policy and value
heads.  Witnesses: (a) off == main's served path (`_search` and the harness
admission verbatim from bf4ecf6c) over self-play, no new record key, pinned
names/digests (release 38, release 42, ``aw``, ``awl``); (b) on, over the same
self-play: every follow byte-identical to flag-off (decision, record, sampler
stream) and every lead identical to a fixed ``candidates=32`` recipe (decision,
record minus the rule's own keys, stream) -- alone and with ``awl``; (c) a lead
admits 32 through the real path with diversity, lead anchor and forced extras
on; (d) the candidate-budget accounting (``k_used``) at 32; (e) the ``awl``
extra stage re-scores the wide ballot and keeps its 50% start guard; (f) the
harvest mixin captures the wide ballot; (g) refusal with ``adaptive_k``, env,
name token, digest, bad values, saved panels.
"""
import copy
import random
import time
import types

import numpy as np
import pytest

from shengji.harvest import trajectory
from shengji.train import pv_search_policy as pv
from shengji.train.policy_value_search import FORCED_EXTRA_SLOTS, PolicyValueBot, leading
from shengji.train.pv_search_policy import RECORD_SCHEMA, PVSearchPolicyError
from test_policy_world_search import state
from test_pv_adaptive_worlds import (RELEASE42_ENV, RELEASE42_NAME, RELEASE42_RULES,
                                     ClockEvaluator, ConstantEvaluator, FakeClock)
from test_pv_adaptive_worlds_leads import AW_NAME, AWL_NAME, HashNoiseEvaluator
from test_pv_admission_rules import PRODUCTION_ENV, PRODUCTION_SHA, names, predict, \
    production_package  # noqa: F401
from test_pv_small_joker_lead import RELEASE38_ENV, RELEASE38_NAME, _fresh_round, _strip

FLAG = "SHENGJI_PV_WIDE_LEAD_ADMISSION"
AWL_FLAG = "SHENGJI_PV_ADAPTIVE_WORLDS_LEADS"
WLA_KEYS = {"wide_lead_admission_k", "wide_lead_admission_applied"}
WIDE = pv.WIDE_LEAD_K
W = 8


class Main944(pv.PVSearchBot):
    """The served wrapper as on main bf4ecf6c (#944), before this rule: `_search`
    verbatim, and the harness's own width, admission and admission record."""

    _admission_k = PolicyValueBot._admission_k
    _admission = PolicyValueBot._admission
    _admission_record = PolicyValueBot._admission_record

    def _search(self, rnd, seat, anchor, started, check_budget=None):
        legal = self._legal(rnd, seat, [anchor])
        actions = list(legal.actions)
        worlds, attempts = self._worlds(rnd, seat, check_budget)
        if check_budget is not None:
            check_budget()
        preferences = self.scores(rnd, seat, actions, worlds).mean(axis=0)
        anchor_key = tuple(sorted(anchor))
        anchor_index = next(i for i, a in enumerate(actions) if tuple(sorted(a)) == anchor_key)
        chosen = self._admission(rnd, seat, actions, preferences, anchor_index, worlds, check_budget)
        slot0 = self._effective_anchor_key(anchor_key)
        if not chosen or not 0 <= chosen[0] < len(actions) \
                or tuple(sorted(actions[chosen[0]])) != slot0 or len(set(chosen)) != len(chosen) \
                or any(not 0 <= i < len(actions) for i in chosen):
            raise PVSearchPolicyError("admission must return distinct indices into the scored set, anchor first",
                                      stage="admission_contract")
        draw_keys = getattr(self, "_draw_keys", None) or ()
        budgeted = [i for i in chosen if tuple(sorted(actions[i])) not in draw_keys]
        if len(budgeted) > self._adaptive["k_used"] + FORCED_EXTRA_SLOTS \
                or self._adaptive["k_used"] > max(self.candidates, self.candidates_lead_multi):
            raise PVSearchPolicyError("admission exceeded the candidate budget",
                                      stage="admission_budget")
        admitted = [actions[i] for i in chosen]
        if self.adaptive_worlds_leads:
            self._adaptive_worlds = None
        if self.adaptive_worlds or (self.adaptive_worlds_leads and leading(rnd)):
            means, batches, winner, played, evaluations = self._adaptive_worlds_decision(
                rnd, seat, admitted, worlds, started, check_budget,
                [float(preferences[i]) for i in chosen])
        else:
            means, batches = self._value_means(rnd, seat, admitted, worlds, check_budget)
            evaluations = len(worlds) * len(admitted)
            if check_budget is not None:
                check_budget()
            winner = self._select(rnd, seat, admitted, means, worlds=worlds,
                                  check_budget=check_budget,
                                  priors=[float(preferences[i]) for i in chosen])
            played = self._swap_doomed_throw(rnd, seat, admitted[winner], worlds, check_budget)
        self.last_decision_record = {
            "schema": RECORD_SCHEMA, "policy": getattr(self, "policy_name", None),
            "worlds": len(worlds), "sample_attempts": attempts, "actions": len(actions),
            "cap": self.cap, "legal_count": legal.count, "legal_complete": legal.complete,
            "admitted_indices": chosen, "value_means": means.tolist(),
            "admitted": [list(a) for a in admitted],
            "policy_log_odds_admitted": [float(preferences[i]) for i in chosen],
            "policy_log_odds_listing": [float(v) for v in preferences[:min(len(actions), 256)]],
            "selected_index": chosen[winner], "value_batches": batches,
            "value_evaluations": evaluations,
            "anchor_selected": winner == 0, "encoder_version": self.version,
            "played": list(played),
            "seconds": time.perf_counter() - started, "work_complete": True,
            **self._admission_record(),
            **self._sampler_record(),
            **self._tiebreak_record(),
            **self._lead_tiebreak_record(),
            **self._doomed_throw_record(),
            **self._adaptive_worlds_record(),
        }
        return list(played)


def _bot(cls, seat, rules, evaluator, candidates=8, **flags):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=W, candidates=candidates,
                               cap=4000, batch_size=128, **rules, **flags)
    return cls(predict, evaluator=evaluator, version=2, config=config,
               checkpoint="/dev/null", seed=100 + seat)


def _timeless(record):
    return {k: v for k, v in record.items()
            if k not in ("seconds", "adaptive_worlds_base_seconds")}


def _without_rule(record):
    return {k: v for k, v in _timeless(record).items() if k not in WLA_KEYS}


SELF_PLAY_SEEDS = tuple(range(707001, 707005))


# ------------------------------------------------------- (a) + (b) self-play

@pytest.mark.parametrize("rules", [RELEASE42_RULES, {}], ids=["release42", "bare"])
def test_off_is_main_follows_are_off_and_leads_are_k32_over_self_play(rules):
    evaluator = HashNoiseEvaluator()
    leads = follows = wide_leads = lead_changed = awl_triggered = 0
    for seed in SELF_PLAY_SEEDS:
        rnd = _fresh_round(seed)
        arms = {
            "off": [_bot(pv.PVSearchBot, s, rules, evaluator) for s in range(4)],
            "main": [_bot(Main944, s, rules, evaluator) for s in range(4)],
            "wla": [_bot(pv.PVSearchBot, s, rules, evaluator, wide_lead_admission=True)
                    for s in range(4)],
            "k32": [_bot(pv.PVSearchBot, s, rules, evaluator, candidates=WIDE) for s in range(4)],
            "awl": [_bot(pv.PVSearchBot, s, rules, evaluator, adaptive_worlds_leads=True)
                    for s in range(4)],
            "wla_awl": [_bot(pv.PVSearchBot, s, rules, evaluator, wide_lead_admission=True,
                             adaptive_worlds_leads=True) for s in range(4)],
            "k32_awl": [_bot(pv.PVSearchBot, s, rules, evaluator, candidates=WIDE,
                             adaptive_worlds_leads=True) for s in range(4)],
        }
        while rnd.phase == "play":
            seat = rnd.turn
            state_ = arms["off"][seat].sampler.rng.getstate()
            for name, bots in arms.items():   # every arm starts on the same stream
                if name != "off":
                    bots[seat].sampler.rng.setstate(state_)
            is_lead = leading(rnd)
            played = {name: bots[seat].decide_play(copy.deepcopy(rnd), seat)
                      for name, bots in arms.items()}
            rec = {name: bots[seat].last_decision_record for name, bots in arms.items()}
            rng = {name: bots[seat].sampler.rng.getstate() for name, bots in arms.items()}
            # (a) off is main, and carries no rule key
            assert played["off"] == played["main"]
            assert _strip(rec["off"]) == _strip(rec["main"]) and rng["off"] == rng["main"]
            assert not WLA_KEYS & set(rec["off"])
            if is_lead:
                leads += 1
                # (b) a lead is the K=32 recipe's lead, alone and under awl
                for wide, k32 in (("wla", "k32"), ("wla_awl", "k32_awl")):
                    assert played[wide] == played[k32]
                    assert _without_rule(rec[wide]) == _timeless(rec[k32])
                    assert rng[wide] == rng[k32]
                    assert rec[wide]["schema"] == RECORD_SCHEMA
                    assert rec[wide]["wide_lead_admission_k"] == WIDE
                    assert rec[wide]["wide_lead_admission_applied"] is True
                    assert len(rec[wide]["admitted"]) <= WIDE + FORCED_EXTRA_SLOTS
                wide_leads += len(rec["wla"]["admitted"]) > 8
                lead_changed += played["wla"] != played["off"]
                awl_triggered += rec["wla_awl"]["adaptive_worlds_triggered"]
            else:
                follows += 1
                # (b) a follow is the flag-off follow, byte for byte
                assert played["wla"] == played["off"]
                assert _strip(rec["wla"]) == _strip(rec["off"]) and rng["wla"] == rng["off"]
                assert not WLA_KEYS & set(rec["wla"])
                assert played["wla_awl"] == played["awl"]
                assert _timeless(rec["wla_awl"]) == _timeless(rec["awl"])
                assert rng["wla_awl"] == rng["awl"]
            rnd.play(seat, played["off"])
    assert leads >= 25 and follows >= 75 and wide_leads > 0 and awl_triggered > 0
    print(f"\nwide_lead_admission census [{'release42' if rules else 'bare'}]: "
          f"leads={leads} follows={follows} wide_leads={wide_leads} "
          f"lead_played_changed={lead_changed} awl_triggered={awl_triggered}")


# ------------------------------------------------------- (c) the real admission path

def _served(evaluator=None, budget=None, candidates=8, worlds=W, **rules):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=worlds, candidates=candidates,
                               cap=4000, batch_size=128, serving_budget_seconds=budget, **rules)
    return pv.PVSearchBot(predict, evaluator=evaluator or HashNoiseEvaluator(), version=2,
                          config=config, checkpoint="/dev/null", seed=17)


def _decide(bot, rnd=None):
    rnd = state() if rnd is None else rnd
    played = bot.decide_play(copy.deepcopy(rnd), rnd.turn)
    return played, bot.last_decision_record


def test_bare_lead_admits_32_as_a_superset_of_the_8_in_order():
    rnd = state()
    assert leading(rnd)
    _, narrow = _decide(_served(), rnd)
    _, wide = _decide(_served(wide_lead_admission=True), rnd)
    assert len(narrow["admitted_indices"]) == 8 and len(wide["admitted_indices"]) == WIDE
    assert wide["admitted_indices"][:8] == narrow["admitted_indices"]
    assert wide["value_evaluations"] == W * WIDE
    assert len(wide["value_means"]) == len(wide["policy_log_odds_admitted"]) == WIDE
    assert wide["wide_lead_admission_k"] == WIDE and wide["wide_lead_admission_applied"] is True
    assert not WLA_KEYS & set(narrow)


@pytest.mark.parametrize("forced", [False, True], ids=["release42", "release42+fs"])
def test_lead_with_diversity_anchor_and_forced_extras_is_the_k32_ballot(forced):
    rules = {**RELEASE42_RULES, "admit_forced_single": forced, "small_joker_guard": True}
    rnd = state()
    wide_bot = _served(wide_lead_admission=True, **rules)
    k32_bot = _served(candidates=WIDE, **rules)
    p_wide, wide = _decide(wide_bot, rnd)
    p_k32, k32 = _decide(k32_bot, rnd)
    assert p_wide == p_k32 and _without_rule(wide) == _timeless(k32)
    chosen = wide["admitted_indices"]
    extras = wide.get("forced_single_added", [])
    assert len(chosen) == WIDE + len(extras) <= WIDE + FORCED_EXTRA_SLOTS
    assert "diversity_skipped" in wide and not set(wide["diversity_skipped"]) & set(chosen)
    # slot 0 is the lead anchor rule's choice, recorded as served
    assert "lead_anchor_applied" in wide
    assert sorted(wide["admitted"][0]) == sorted(wide["lead_anchor_to"].split(" "))
    if forced:
        assert chosen[WIDE:] == extras
    assert wide["wide_lead_admission_k"] == WIDE


def test_follow_keeps_8_and_carries_no_rule_key():
    rnd = _fresh_round(707001)
    rnd.play(rnd.turn, pv.HeuristicBot().decide_play(rnd, rnd.turn))
    assert not leading(rnd)
    p_off, off = _decide(_served(**RELEASE42_RULES), rnd)
    p_on, on = _decide(_served(wide_lead_admission=True, **RELEASE42_RULES), rnd)
    assert p_on == p_off and _strip(on) == _strip(off)
    assert len(on["admitted_indices"]) <= 8 and not WLA_KEYS & set(on)


def test_no_stale_rule_state_after_a_lead():
    rnd = _fresh_round(707001)
    bot = _served(wide_lead_admission=True)
    _, lead = _decide(bot, rnd)
    assert lead["wide_lead_admission_k"] == WIDE
    rnd.play(rnd.turn, pv.HeuristicBot().decide_play(rnd, rnd.turn))
    _, follow = _decide(bot, rnd)
    assert not WLA_KEYS & set(follow) and bot._wide_lead is None


def test_k_above_the_width_is_never_shrunk():
    rnd = state()
    p_off, off = _decide(_served(candidates=64), rnd)
    p_on, on = _decide(_served(candidates=64, wide_lead_admission=True), rnd)
    assert p_on == p_off and _without_rule(on) == _timeless(off)
    assert on["wide_lead_admission_k"] == 64 and on["wide_lead_admission_applied"] is False


# ------------------------------------------------------- (d) candidate-budget accounting

def test_candidate_limit_is_32_on_a_lead_and_unchanged_elsewhere():
    lead = state()
    follow = _fresh_round(707001)
    follow.play(follow.turn, pv.HeuristicBot().decide_play(follow, follow.turn))
    on, off = _served(wide_lead_admission=True), _served()
    assert on._candidate_limit(lead) == WIDE
    assert on._candidate_limit(follow) == off._candidate_limit(lead) \
        == off._candidate_limit(follow) == max(8, off.candidates_lead_multi) == 16


def _padded(bot, extra):
    """A hook override that appends ``extra`` more legal indices after the
    production ballot (everything the budget check must count)."""
    original = bot._admit

    def _admit(rnd, seat, actions, preferences, anchor_index):
        chosen = list(original(rnd, seat, actions, preferences, anchor_index))
        rest = [i for i in range(len(actions)) if i not in chosen]
        return chosen + rest[:extra]
    bot._admit = _admit
    return bot


@pytest.mark.parametrize("extra,ok", [(FORCED_EXTRA_SLOTS, True), (FORCED_EXTRA_SLOTS + 1, False)])
def test_k_used_32_admits_32_plus_forced_slots_and_no_more(extra, ok):
    bot = _padded(_served(wide_lead_admission=True), extra)
    if ok:
        _, rec = _decide(bot)
        assert rec["schema"] == RECORD_SCHEMA and len(rec["admitted_indices"]) == WIDE + extra
        assert bot._adaptive["k_used"] == WIDE
    else:
        with pytest.raises(PVSearchPolicyError, match="candidate budget"):
            _decide(bot)
        # under a serving budget the same refusal is the heuristic fallback
        bot = _padded(_served(budget=100.0, wide_lead_admission=True), extra)
        _, rec = _decide(bot)
        assert rec["schema"] == pv.FALLBACK_SCHEMA and rec["error_stage"] == "admission_budget"


def test_a_follow_keeps_the_harness_budget():
    """On a follow the width is 8: a hook claiming a 32 width there is refused
    as before (the lead allowance does not leak to follows)."""
    rnd = _fresh_round(707001)
    rnd.play(rnd.turn, pv.HeuristicBot().decide_play(rnd, rnd.turn))
    bot = _served(wide_lead_admission=True)
    bot._admission_k = lambda rnd_, actions, prefs: (WIDE, True)
    with pytest.raises(PVSearchPolicyError, match="candidate budget"):
        _decide(bot, rnd)


# ------------------------------------------------------- (e) with awl, under a budget

@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(pv, "time", types.SimpleNamespace(perf_counter=fake.perf_counter))
    return fake


def test_awl_rescores_the_wide_ballot_on_4w():
    bot = _served(ConstantEvaluator(), wide_lead_admission=True, adaptive_worlds_leads=True)
    _, rec = _decide(bot)
    n = len(rec["admitted"])
    assert n == WIDE and rec["wide_lead_admission_k"] == WIDE
    assert rec["adaptive_worlds_triggered"] is True
    assert rec["adaptive_worlds_total"] == 4 * W
    assert rec["value_evaluations"] == 4 * W * n


def test_awl_start_guard_skips_when_the_wide_base_pass_passes_half(clock):
    # the wide base pass is two batches (8 worlds x 32 = 256 leaves, batch 128):
    # 2 s + 4 s of a 10 s budget, so the extra stage is past its 50% start share
    bot = _served(ClockEvaluator(clock, [2.0, 4.0], inner=ConstantEvaluator()), budget=10.0,
                  wide_lead_admission=True, adaptive_worlds_leads=True)
    played, rec = _decide(bot)
    assert rec["schema"] == RECORD_SCHEMA and rec["work_complete"] is True
    assert rec["value_batches"] == 2 and len(rec["admitted"]) == WIDE
    assert rec["adaptive_worlds_triggered"] is True
    assert rec["adaptive_worlds_skipped_budget"] is True
    assert rec["adaptive_worlds_total"] == W and rec["value_evaluations"] == W * WIDE
    assert played == rec["played"]


def test_awl_soft_deadline_keeps_the_wide_base_decision(clock):
    # base 1 s; the first extra round's first batch runs to 9 s (soft 8 of 10)
    bot = _served(ClockEvaluator(clock, [0.5, 0.5, 7.0], inner=ConstantEvaluator()),
                  budget=10.0, wide_lead_admission=True, adaptive_worlds_leads=True)
    played, rec = _decide(bot)
    assert rec["schema"] == RECORD_SCHEMA and rec["work_complete"] is True
    assert rec["adaptive_worlds_abandoned"] is True
    assert rec["value_evaluations"] == W * WIDE and played == rec["played"]


def test_a_wide_base_pass_past_the_budget_falls_back_as_flag_off(clock):
    bot = _served(ClockEvaluator(clock, [6.0, 6.0], inner=ConstantEvaluator()), budget=10.0,
                  wide_lead_admission=True)
    before = bot.sampler.rng.getstate()
    played, rec = _decide(bot)
    assert rec["schema"] == pv.FALLBACK_SCHEMA and rec["reason"] == "budget"
    assert bot.sampler.rng.getstate() == before and played == rec["played"]


# ------------------------------------------------------- (f) harvest capture

@pytest.mark.parametrize("explore", [False, True])
def test_harvest_captures_the_wide_production_ballot(explore):
    bot = _served(wide_lead_admission=True)
    bot.__class__ = trajectory.pv_trajectory_class(type(bot))
    bot._trajectory_init(random.Random(0))
    if explore:
        bot.EXPLORE_RATE, bot.EXPLORE_K = 1.0, 1
    played, rec = _decide(bot)
    assert rec["schema"] == RECORD_SCHEMA and rec["wide_lead_admission_k"] == WIDE
    assert len(bot.last_production_ballot) == WIDE
    assert bot.last_ballot[:WIDE] == bot.last_production_ballot
    assert bot.last_ballot == rec["admitted"]
    allocation, _, values = trajectory.pv_fields_from_record(rec, bot.last_ballot)
    assert allocation["played_index"] == bot.last_ballot.index(played)
    assert len(values["means"]) == len(bot.last_ballot)


# ------------------------------------------------------- (g) names, digest, env, refusals

def test_existing_names_unchanged_when_off(production_package):
    for raw in (None, "0", ""):
        extra = {} if raw is None else {FLAG: raw}
        assert names({**RELEASE38_ENV, **extra}) == [RELEASE38_NAME]
        assert names({**RELEASE42_ENV, **extra}) == [RELEASE42_NAME]
        assert names({**RELEASE42_ENV, "SHENGJI_PV_ADAPTIVE_WORLDS": "1", **extra}) == [AW_NAME]
        assert names({**RELEASE42_ENV, AWL_FLAG: "1", **extra}) == [AWL_NAME]
    config = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0)
    assert pv.recipe_digest(config) == "4a09aef5"
    assert not {"wide_lead_admission", "wide_lead_k"} & set(pv.recipe_payload(config))


def test_wla_token_in_the_width_slot_and_digest_when_on(production_package):
    on, = names({**RELEASE42_ENV, FLAG: "1"})
    assert on.startswith("pv-search-491ee4bf-w64-k8-div-rc-tb-wla-la-dts-r") and "-bury-hybrid-" in on
    both, = names({**RELEASE42_ENV, FLAG: "1", AWL_FLAG: "1"})
    assert both.startswith("pv-search-491ee4bf-w64-k8-div-rc-tb-wla-la-dts-awl-r")
    assert len({on, both, RELEASE42_NAME, AWL_NAME}) == 4
    tokens = [t for _, t in pv.RULE_TOKENS]
    assert tokens.index("wla") == tokens.index("ak16") + 1 == tokens.index("la") - 1
    assert pv.RULE_FLAGS["WIDE_LEAD_ADMISSION"] == "wide_lead_admission"
    base = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0)
    wla = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                            wide_lead_admission=True)
    k32 = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                            candidates=WIDE)
    payload = pv.recipe_payload(wla)
    assert payload["wide_lead_admission"] is True and payload["wide_lead_k"] == WIDE == 32
    assert len({pv.recipe_digest(c) for c in (base, wla, k32)}) == 3
    assert pv.WIDE_LEAD_DEFAULTS["wide_lead_admission"] is False
    assert pv.PVSearchBot.wide_lead_admission is False   # the class-level off default


@pytest.mark.parametrize("bad", ["2", "true", "yes", "on", " 1"])
def test_env_flag_refuses_anything_but_0_or_1(bad):
    with pytest.raises(PVSearchPolicyError, match="must be 0 or 1"):
        pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: bad})
    assert "wide_lead_admission" not in pv.pv_env_recipe(PRODUCTION_ENV)
    assert "wide_lead_admission" not in pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: "0"})
    assert pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: "1"})["wide_lead_admission"] is True


def test_bad_values_are_refused():
    with pytest.raises(PVSearchPolicyError, match="must be a bool"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, wide_lead_admission=1))
    with pytest.raises(PVSearchPolicyError, match="wide_lead_admission must be a bool"):
        _served(wide_lead_admission="1")


def test_adaptive_k_is_refused(production_package):
    both = pv.PVSearchConfig(checkpoint_sha256="f" * 64, wide_lead_admission=True,
                             adaptive_k=True)
    with pytest.raises(PVSearchPolicyError, match="are exclusive"):
        pv.recipe_payload(both)
    with pytest.raises(PVSearchPolicyError, match="are exclusive"):
        _served(wide_lead_admission=True, adaptive_k=True)
    with pytest.raises(PVSearchPolicyError, match="are exclusive"):
        names({**RELEASE42_ENV, FLAG: "1", "SHENGJI_PV_ADAPTIVE_K": "1"})


def test_saved_panel_without_the_field_still_binds():
    from test_panel_rank_root import inputs
    from shengji.eval import panel_rank_root
    panel, fixture, bot = inputs()
    for field in ("doomed_throw_swap", "small_joker_guard", "adaptive_worlds",
                  "adaptive_worlds_leads", "wide_lead_admission"):
        del panel['config'][field]
    root = panel_rank_root.bind_panel_rank_root(panel, fixture, bot)
    assert root.turn == fixture.seat


@pytest.mark.parametrize("damage", ["config_true", "bot_true"])
def test_saved_panel_without_the_field_refuses_the_rule_on(damage):
    from dataclasses import replace
    from test_panel_rank_root import inputs
    from shengji.eval import panel_rank_root
    panel, fixture, bot = inputs()
    del panel['config']['wide_lead_admission']
    if damage == "config_true":
        bot.config = replace(bot.config, wide_lead_admission=True)
    else:
        bot.wide_lead_admission = True
    with pytest.raises(ValueError, match="config mismatch"):
        panel_rank_root.bind_panel_rank_root(panel, fixture, bot)
