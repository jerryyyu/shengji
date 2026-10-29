"""The OPTIONAL held-out lead confirmation of the pv-search bot (``lead_confirm``,
``SHENGJI_PV_LEAD_CONFIRM=<k>``, token ``lcc<k>``): on a lead with no exact stage,
the policy's next ``k - K`` actions beyond the served ballot are screened on a
prefix of the base worlds, and a challenger replaces the final served lead only
when a FRESH draw confirms its paired advantage.

Torch-free and package-free.  Witnesses: (a) on, over self-play from identical
bot states: every follow is the flag-off decision, record and sampler stream;
every lead that is not ``applied`` plays the flag-off cards with the flag-off
record plus the rule's keys; every ``applied`` lead plays a pool action outside
the ballot whose recorded fresh delta clears ``z * se + margin``; (b) the
confirmation reads only the fresh worlds (a screen-favoured challenger the fresh
worlds do not confirm is rejected); (c) the start share, the soft deadline and a
cut greedy finish keep the base decision and its records; (d) exact-stage leads
and follows are untouched; (e) env, name token, payload and refusals.
"""
import copy
import types

import numpy as np
import pytest

from shengji.train import pv_search_policy as pv
from shengji.train.policy_value_search import leading
from test_policy_world_search import state
from test_pv_adaptive_worlds import ClockEvaluator, FakeClock, _action_value, _root_cards
from test_pv_admission_rules import PRODUCTION_ENV, names, predict, production_package  # noqa: F401
from test_pv_doomed_throw_reselect import HashNoiseEvaluator, throw_loving_scores
from test_pv_leaf_greedy_finish import R46_RULES, leaf_bot
from test_pv_small_joker_lead import _fresh_round

ENV = "SHENGJI_PV_LEAD_CONFIRM"
KEYS = {"lead_confirm_status", "lead_confirm_pool", "lead_confirm_screen_worlds",
        "lead_confirm_challengers", "lead_confirm_screen_margins", "lead_confirm_worlds",
        "lead_confirm_deltas", "lead_confirm_ses", "lead_confirm_applied", "lead_confirm_to",
        "lead_confirm_seconds"}
SEEDS = (707_014, 707_001, 707_003)


def _comparable(record, drop=()):
    return {k: v for k, v in record.items()
            if not k.endswith("seconds") and not k.endswith("_ms") and k not in drop}


def _on(bot, k=24, **params):
    """The same bot state with the rule on (a deep copy: same sampler stream,
    the same evaluator object)."""
    on = copy.deepcopy(bot)
    on.evaluator = bot.evaluator
    on.lead_confirm = k
    for name, value in params.items():
        setattr(on, name, value)
    return on


def short_loving_scores(rnd, seat, actions, worlds):
    """A stub policy that ranks short leads first (so the pool holds plain
    singles and pairs rather than doomed throws)."""
    prefs = [-10.0 * len(a) - 1e-3 * i for i, a in enumerate(actions)]
    return np.tile(np.asarray(prefs), (len(worlds), 1))


def _bot(evaluator, rules=R46_RULES, **kw):
    bot = leaf_bot(evaluator, worlds=8, **rules, **kw)
    bot.scores = short_loving_scores
    return bot


class OutsideBallotEvaluator(HashNoiseEvaluator):
    """`HashNoiseEvaluator` plus a bonus for leads outside ``ballot``: some pool
    action beats the served lead on every world, so confirmations happen."""

    def __init__(self, bonus=1.0):
        self.ballot, self.bonus = set(), bonus

    def score(self, leaves, seat):
        base = super().score(leaves, seat)
        extra = [self.bonus * (_root_cards(leaf, seat) not in self.ballot)
                 * (1.0 + _action_value(_root_cards(leaf, seat))) for leaf in leaves]
        return base + np.asarray(extra)


# ------------------------------------------------------- (a) self-play from identical states

@pytest.mark.parametrize("scores", [throw_loving_scores, short_loving_scores], ids=["throws", "short"])
@pytest.mark.parametrize("bonus", [0.0, 1.0], ids=["noise", "outside-favoured"])
def test_follows_are_off_unapplied_leads_are_off_and_applied_leads_are_confirmed(bonus, scores):
    evaluator = OutsideBallotEvaluator(bonus)
    seen = {"follows": 0, "leads": 0, "applied": 0, "statuses": set()}
    for seed in SEEDS:
        rnd = _fresh_round(seed)
        bots = [leaf_bot(evaluator, worlds=8, seed=100 + s, **R46_RULES) for s in range(4)]
        for bot in bots:
            bot.scores = scores
        while rnd.phase == "play":
            seat = rnd.turn
            off = bots[seat]
            on = _on(off)
            # the ballot is the policy's (no value call decides it): read it on a
            # scratch copy, then both bots price the same evaluator
            scratch = copy.deepcopy(off)
            scratch.decide_play(copy.deepcopy(rnd), seat)
            evaluator.ballot = {tuple(sorted(x)) for x in scratch.last_decision_record["admitted"]}
            a = off.decide_play(copy.deepcopy(rnd), seat)
            ro = off.last_decision_record
            b = on.decide_play(copy.deepcopy(rnd), seat)
            rn = on.last_decision_record
            if not leading(rnd):
                seen["follows"] += 1
                assert a == b and _comparable(ro) == _comparable(rn)
                assert not KEYS & set(rn)
                assert off.sampler.rng.getstate() == on.sampler.rng.getstate()
            else:
                seen["leads"] += 1
                assert KEYS <= set(rn)
                status = rn["lead_confirm_status"]
                seen["statuses"].add(status)
                if status != "applied":
                    assert a == b, status
                    diff = {k for k in set(ro) | set(rn) - KEYS
                            if _comparable(ro).get(k) != _comparable(rn, KEYS).get(k)}
                    assert not diff, (status, {k: (ro.get(k), rn.get(k)) for k in diff})
                    assert rn["lead_confirm_applied"] is False and rn["lead_confirm_to"] is None
                else:
                    seen["applied"] += 1
                    assert sorted(b) == sorted(rn["lead_confirm_to"])
                    assert tuple(sorted(b)) not in {tuple(sorted(x)) for x in ro["admitted"]}
                    assert rn["admitted"][:-1] == ro["admitted"] and sorted(rn["admitted"][-1]) == sorted(b)
                    assert rn["selected_index"] == rn["admitted_indices"][-1]
                    assert rn["value_means"][:-1] == ro["value_means"] and rn["value_means"][-1] is None
                    assert rn["played"] == list(b) and rn["work_complete"] is True
                    i = [sorted(c) for c in rn["lead_confirm_challengers"]].index(sorted(b))
                    assert rn["lead_confirm_deltas"][i] > pv.LEAD_CONFIRM_PARAMS["z"] * rn["lead_confirm_ses"][i]
                    assert rn["lead_confirm_worlds"] == pv.LEAD_CONFIRM_PARAMS["rounds"] * 8
                    # the base pass's records are the flag-off ones
                    for key in ("leaf_greedy_reply_plays", "doomed_throw_reselect_from", "tiebreak_near_set"):
                        assert rn.get(key) == ro.get(key)
                if status in ("no_pool", "no_challenger", "exact", "override", "single_candidate"):
                    # nothing was drawn
                    assert off.sampler.rng.getstate() == on.sampler.rng.getstate()
            rnd.play(seat, a)
    assert seen["follows"] > 100 and seen["leads"] > 30
    assert "exact" in seen["statuses"]
    if bonus and scores is short_loving_scores:
        assert seen["applied"] >= 5
    else:
        assert {"no_challenger", "rejected"} & seen["statuses"]


def test_off_has_no_record_key_and_no_attribute_state():
    bot = leaf_bot(HashNoiseEvaluator(), worlds=8, **R46_RULES)
    assert bot.lead_confirm == 0 and "lead_confirm" not in vars(bot)
    rnd = state()
    bot.decide_play(copy.deepcopy(rnd), rnd.turn)
    assert not KEYS & set(bot.last_decision_record)


# ------------------------------------------------------- (b) only the fresh worlds confirm

def _lead():
    rnd = state()
    assert leading(rnd) and max(map(len, rnd.hands)) > 7
    return rnd, rnd.turn


def _prime(evaluator, rnd, seat, rules=R46_RULES):
    """Point ``evaluator``'s bonus at the leads outside the served ballot (the
    ballot is the policy's; no value call decides it)."""
    scratch = _bot(HashNoiseEvaluator(), rules)
    scratch.decide_play(copy.deepcopy(rnd), seat)
    evaluator.ballot = {tuple(sorted(x)) for x in scratch.last_decision_record["admitted"]}


def test_a_screen_favoured_challenger_must_be_confirmed_on_the_fresh_worlds(monkeypatch):
    rnd, seat = _lead()
    evaluator = OutsideBallotEvaluator(1.0)
    _prime(evaluator, rnd, seat)
    off = _bot(evaluator)
    base = off.decide_play(copy.deepcopy(rnd), seat)
    calls = []
    real = pv.PVSearchBot._lead_confirm_matrix
    real_draw = pv.PVSearchBot._lead_confirm_draw
    drawn = []

    def draw(self, rnd, seat, check_budget):
        out = real_draw(self, rnd, seat, check_budget)
        drawn.append(out)
        return out

    def matrix(self, rnd, seat, actions, worlds, check_budget):
        calls.append((len(actions), worlds))
        m = real(self, rnd, seat, actions, worlds, check_budget)
        if len(calls) == 2:
            # the fresh worlds say the challenger is no better than the served lead
            m[:, 1:] = m[:, [0]] - 1e-3
        return m

    monkeypatch.setattr(pv.PVSearchBot, "_lead_confirm_draw", draw)
    monkeypatch.setattr(pv.PVSearchBot, "_lead_confirm_matrix", matrix)
    on = _on(_bot(evaluator))
    played = on.decide_play(copy.deepcopy(rnd), seat)
    rec = on.last_decision_record
    assert rec["lead_confirm_status"] == "rejected" and played == base
    assert len(calls) == 2 and calls[0][1] != calls[1][1]
    assert calls[1][1] is drawn[0] and len(drawn[0]) == 16
    assert len(calls[0][1]) == 8      # the screen: the base worlds' prefix (all 8 here)
    assert rec["lead_confirm_challengers"] and all(m > 0 for m in rec["lead_confirm_screen_margins"])


def test_screen_prefix_challenger_count_and_margin_are_honoured(monkeypatch):
    rnd, seat = _lead()
    evaluator = OutsideBallotEvaluator(1.0)
    _prime(evaluator, rnd, seat)
    on = _on(_bot(evaluator), lead_confirm_screen_worlds=3,
             lead_confirm_challengers=1, lead_confirm_rounds=1)
    on.decide_play(copy.deepcopy(rnd), seat)
    rec = on.last_decision_record
    assert rec["lead_confirm_screen_worlds"] == 3 and len(rec["lead_confirm_challengers"]) == 1
    assert rec["lead_confirm_worlds"] == 8 and rec["lead_confirm_status"] == "applied"
    huge = _on(_bot(evaluator), lead_confirm_margin=1e6)
    huge.decide_play(copy.deepcopy(rnd), seat)
    assert huge.last_decision_record["lead_confirm_status"] == "rejected"


# ------------------------------------------------------- (c) budget and the greedy finish deadline

@pytest.fixture
def clock(monkeypatch):
    import types
    fake = FakeClock()
    monkeypatch.setattr(pv, "time", types.SimpleNamespace(perf_counter=fake.perf_counter))
    return fake


def _budget_bot(evaluator, budget=10.0):
    return _on(_bot(evaluator, budget=budget))


def test_not_attempted_past_the_start_share(clock):
    rnd, seat = _lead()
    inner = OutsideBallotEvaluator(1.0)
    _prime(inner, rnd, seat)
    bot = _budget_bot(ClockEvaluator(clock, [5.0], inner=inner))
    bot.decide_play(copy.deepcopy(rnd), seat)
    rec = bot.last_decision_record
    assert rec["lead_confirm_status"] == "skipped_budget" and rec["work_complete"] is True


def test_soft_expiry_keeps_the_base_decision_and_records(clock, monkeypatch):
    rnd, seat = _lead()
    inner = OutsideBallotEvaluator(1.0)
    _prime(inner, rnd, seat)
    clock.now = 1000.0
    ref = _bot(ClockEvaluator(clock, [0.1], inner=inner), budget=10.0)
    base = ref.decide_play(copy.deepcopy(rnd), seat)
    ref_rec = ref.last_decision_record
    clock.now = 1000.0
    # the base pass 0.1 s; the screen runs to 8.6 s of 10 (soft 8)
    real = pv.PVSearchBot._lead_confirm_matrix

    def slow(self, *a, **kw):
        clock.now += 8.5
        return real(self, *a, **kw)
    monkeypatch.setattr(pv.PVSearchBot, "_lead_confirm_matrix", slow)
    bot = _budget_bot(ClockEvaluator(clock, [0.1], inner=inner))
    played = bot.decide_play(copy.deepcopy(rnd), seat)
    rec = bot.last_decision_record
    assert rec["lead_confirm_status"] == "abandoned"
    assert rec["lead_confirm_abandon_reason"] == "soft_budget"
    assert played == base and rec["schema"] == pv.RECORD_SCHEMA and rec["work_complete"] is True
    assert _comparable(rec, KEYS | {"lead_confirm_abandon_reason", "lead_confirm_abandon_error"}) \
        == _comparable(ref_rec)


@pytest.mark.parametrize("unexpected", [False, True])
def test_a_cut_greedy_finish_abandons_to_the_base(monkeypatch, unexpected):
    rnd, seat = _lead()
    evaluator = OutsideBallotEvaluator(1.0)
    _prime(evaluator, rnd, seat)
    off = _bot(evaluator)
    base = off.decide_play(copy.deepcopy(rnd), seat)
    on = _on(_bot(evaluator))
    prefill = pv.PVSearchBot._greedy_prefill
    calls = []

    def cut(self, *a, **kw):
        calls.append(1)
        prefill(self, *a, **kw)
        if len(calls) == 2:
            if unexpected:
                raise RuntimeError("unexpected leaf failure")
            self._leaf_greedy["deadline_cut"] = 1
    monkeypatch.setattr(pv.PVSearchBot, "_greedy_prefill", cut)
    played = on.decide_play(copy.deepcopy(rnd), seat)
    rec = on.last_decision_record
    assert rec["lead_confirm_status"] == "abandoned"
    assert rec["lead_confirm_abandon_reason"] == ("error" if unexpected else "leaf_deadline")
    assert rec["lead_confirm_abandon_error"] == ("RuntimeError" if unexpected else "_LeadConfirmLeafCut")
    assert played == base
    assert rec["leaf_greedy_reply_plays"] == off.last_decision_record["leaf_greedy_reply_plays"]


# ------------------------------------------------------- (e) env, name, payload, refusals

def test_env_name_payload(production_package):
    base, = names(PRODUCTION_ENV)
    assert names({**PRODUCTION_ENV, ENV: "0"}) == [base]
    assert names({**PRODUCTION_ENV, ENV: ""}) == [base]
    on, = names({**PRODUCTION_ENV, ENV: "24"})
    assert on != base and "-lcc24-r" in on
    assert pv.pv_env_recipe({**PRODUCTION_ENV, ENV: "24"})["lead_confirm"] == 24
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, lead_confirm=24)
    payload = pv.recipe_payload(config)
    assert payload["lead_confirm"] == {"k": 24, "rule": pv.LEAD_CONFIRM_RULE_ID, **pv.LEAD_CONFIRM_PARAMS}
    assert "lead_confirm" not in pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64))


@pytest.mark.parametrize("raw", ["x", "8", "65", "-1", "2.5"])
def test_env_refuses_bad_values(raw, production_package):
    with pytest.raises(pv.PVSearchPolicyError):
        names({**PRODUCTION_ENV, ENV: raw})


@pytest.mark.parametrize("bad", [dict(lead_confirm=8), dict(lead_confirm=True), dict(lead_confirm=65),
                                 dict(lead_confirm=24, adaptive_worlds=True),
                                 dict(lead_confirm=24, adaptive_worlds_leads=True),
                                 dict(lead_confirm=12, candidates=12)])
def test_config_refusals(bad):
    with pytest.raises(pv.PVSearchPolicyError):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, **bad))


# ------------------------------------------------------- (f) numeric-value consumers refuse an lcc bot

def _lcc_bot():
    return _on(_bot(OutsideBallotEvaluator(1.0)))


def test_require_value_means_refuses_lead_confirm_and_keeps_the_single_candidate_refusal():
    with pytest.raises(pv.PVSearchPolicyError, match="lead_confirm \\(lcc24\\).*confirmed challenger.*None \\(unpriced\\)"):
        pv.require_value_means(_lcc_bot(), "a consumer")
    with pytest.raises(pv.PVSearchPolicyError, match="SHENGJI_PV_SINGLE_CANDIDATE_FAST"):
        pv.require_value_means(types.SimpleNamespace(single_candidate_fast=True, lead_confirm=32), "a consumer")
    off = _bot(OutsideBallotEvaluator(1.0))
    assert pv.require_value_means(off, "a consumer") is off


def test_an_applied_record_is_unpriced_and_serving_still_plays_it():
    """The producer side: an applied lead's record carries the challenger's None (never a fabricated
    number), and the bot itself -- serving, the duel adapter -- plays it without any numeric consumer."""
    rnd, seat = _lead()
    evaluator = OutsideBallotEvaluator(1.0)
    _prime(evaluator, rnd, seat)
    bot = _on(_bot(evaluator))
    played = bot.decide_play(copy.deepcopy(rnd), seat)
    rec = bot.last_decision_record
    assert rec["lead_confirm_status"] == "applied" and rec["value_means"][-1] is None
    assert sorted(played) == sorted(rec["lead_confirm_to"]) and rec["work_complete"] is True


def test_the_trajectory_harvest_refuses_an_lcc_bot(monkeypatch):
    import random
    from shengji.harvest import trajectory
    on = _lcc_bot()
    on.__class__ = trajectory.pv_trajectory_class(type(on))
    with pytest.raises(trajectory.TrajectoryError, match="lead_confirm"):
        on._trajectory_init(random.Random(0))
    monkeypatch.setattr(trajectory, "make_bot", lambda *a, **kw: _lcc_bot())
    with pytest.raises(trajectory.TrajectoryError, match="lead_confirm"):
        trajectory.make_trajectory_bot({"policy": "pv-search-x", "explore_rate": 0.0, "explore_k": 0, "cap": 256},
                                       seed=0, explore_rng=random.Random(0))
    # the consumer itself also refuses the unpriced entry of an applied record
    rnd, seat = _lead()
    evaluator = OutsideBallotEvaluator(1.0)
    _prime(evaluator, rnd, seat)
    bot = _on(_bot(evaluator))
    bot.decide_play(copy.deepcopy(rnd), seat)
    rec = bot.last_decision_record
    with pytest.raises(trajectory.TrajectoryError, match="unpriced"):
        trajectory.pv_fields_from_record(rec, rec["admitted"])


def test_the_m9_panel_and_the_value_diagnostic_refuse_an_lcc_bot(monkeypatch):
    from shengji.eval import m9_panel_worker
    from shengji.train import cf_value_diagnostic
    rnd, seat = _lead()
    with pytest.raises(cf_value_diagnostic.AuditError, match="lead_confirm"):
        cf_value_diagnostic.admission_under(_lcc_bot(), rnd, seat, [])
    # the panel's own factory wrapper refuses the built bot before any panel is collected
    job = dict(fixture_id=m9_panel_worker.ROOTS[0], seed=7, control_ballot=[], treatment_ballot=[], mode="m",
               fill_seed=0, expected_legal_count=1, require_m9_replay_match=False)
    monkeypatch.setattr(m9_panel_worker, "build_m9_panel_plan", lambda analysis: [job])
    collected = []

    def panel(factory, fixture, *a, **kw):
        factory()
        collected.append(fixture)
    monkeypatch.setattr(m9_panel_worker, "collect_public_fixture_panel", panel)
    fixtures = [types.SimpleNamespace(id=r) for r in m9_panel_worker.ROOTS]
    with pytest.raises(ValueError, match="lead_confirm"):
        m9_panel_worker.collect_m9_panels({}, fixtures, lambda seed: _lcc_bot(), on_panel=lambda p: None)
    assert collected == []
    from shengji.eval.m9_panel_plan import _validated_ballot
    evaluator = OutsideBallotEvaluator(1.0)
    _prime(evaluator, rnd, seat)
    bot = _on(_bot(evaluator))
    bot.decide_play(copy.deepcopy(rnd), seat)
    with pytest.raises(ValueError, match="finite"):
        _validated_ballot(bot.last_decision_record, "decision", len(bot.last_decision_record["admitted"]))


def test_the_tactical_spread_is_unknown_with_an_unpriced_entry():
    from shengji.eval.tactical import value_spread
    assert value_spread([0.25, -0.5, 0.0]) == 0.75
    assert value_spread([0.1, None]) is None and value_spread([None]) is None and value_spread([]) is None
