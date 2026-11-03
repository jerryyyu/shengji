"""The served bot's degradation telemetry counts every degraded draw and cut
of a decision, not only its first draw (``world_draws_by_stage``,
``belief_fallback_by_stage`` / ``_all_draws`` / ``_any``, the history fill
split, ``leaf_greedy_deadline_fired_lead_confirm`` / ``_any``), and a bury
record describes its own bury call.

Witnesses: (a) a belief failure on the lead confirmation's or the adaptive
stage's fresh draws is counted by stage while ``belief_fallback`` keeps
describing the base draw; (b) the history-legal draw splits
``history_fallback_worlds`` into untested source worlds and plain-draw fill,
per draw and over every draw; (c) a greedy-finish deadline cut inside the lead
confirmation is recorded as an lgfd firing; (d) a bury call that raises leaves
no earlier bury's record behind.  Decision identity is
`test_degradation_telemetry_identity`.
"""
import copy

import pytest

from shengji.ai import belief_numpy as bn
from shengji.ai import history_legality as HL
from shengji.ai.memory import Memory
from shengji.train import cwv_bury_policy as bury_policy
from shengji.train import pv_search_policy as pv
from test_cwv_bury_wide_value import served_bury
from test_cwv_leaf_policy_first_trick import bury_state
from test_pv_belief_worlds import package  # noqa: F401
from test_pv_doomed_throw_reselect import HashNoiseEvaluator
from test_pv_lead_confirm import OutsideBallotEvaluator, _lead, _prime, short_loving_scores
from test_policy_world_search import state
from test_pv_leaf_greedy_finish import R46_RULES, leaf_bot
from test_world_history_legal import W, fixture, served

WHL = dict(world_history_legal=True, world_history_draw=True)
STAGES = ("base", "lead_confirm", "adaptive_worlds")


def _belief(bot, package):
    bot.belief_model = bn.load_belief_numpy(package["path"], package["sha256"])
    return bot


def _lcc_bot(evaluator, package=None, **rules):
    extra = ({"belief_worlds": True, "belief_sha256": package["sha256"]}
             if package is not None else {})
    bot = leaf_bot(evaluator, worlds=8, lead_confirm=24, **WHL, **extra, **R46_RULES, **rules)
    bot.scores = short_loving_scores
    return _belief(bot, package) if package is not None else bot


def _fail_belief_after_first_draw(monkeypatch):
    """Every belief preparation after the decision's first `_worlds` call raises
    (the base draw is the proposal's; every later draw falls back)."""
    calls = {"worlds": 0}
    real_worlds, real_marginals = pv.PVSearchBot._worlds, bn.BeliefNumpy.marginals

    def worlds(self, *a, **kw):
        out = real_worlds(self, *a, **kw)
        calls["worlds"] += 1
        return out

    def marginals(self, inp):
        if calls["worlds"] >= 1:
            raise RuntimeError("belief down")
        return real_marginals(self, inp)
    monkeypatch.setattr(pv.PVSearchBot, "_worlds", worlds)
    monkeypatch.setattr(bn.BeliefNumpy, "marginals", marginals)
    return calls


# ------------------------------------------------------- (a) belief fallback on every draw

def test_a_lead_confirmation_draw_that_falls_back_is_counted(package, monkeypatch):
    rnd, seat = _lead()
    evaluator = OutsideBallotEvaluator(1.0)
    _prime(evaluator, rnd, seat)
    bot = _lcc_bot(evaluator, package)
    _fail_belief_after_first_draw(monkeypatch)
    bot.decide_play(copy.deepcopy(rnd), seat)
    rec = bot.last_decision_record
    assert rec["lead_confirm_worlds"] > 0, "the fixture must reach the fresh draw"
    rounds = bot.lead_confirm_rounds
    # the base-draw field keeps its meaning: the first draw was the proposal's
    assert rec["belief_fallback"] == 0 and rec["belief_proposed"] > 0
    assert rec["world_draws_by_stage"] == {"base": 1, "lead_confirm": rounds, "adaptive_worlds": 0}
    assert rec["belief_fallback_by_stage"] == {"base": 0, "lead_confirm": rounds,
                                               "adaptive_worlds": 0}
    assert rec["belief_fallback_all_draws"] == rounds and rec["belief_fallback_any"] == 1


def _adaptive_bot(package):
    bot = _belief(served(worlds=8, adaptive_worlds=True, belief_worlds=True,
                         belief_sha256=package["sha256"], **WHL), package)
    bot.evaluator = HashNoiseEvaluator()
    return bot


def _adaptive_root(package):
    """The first state of the self-play from ``state()`` whose decision runs
    the adaptive stage's draws."""
    rnd = state()
    while rnd.phase == "play":
        seat = rnd.turn
        bot = _adaptive_bot(package)
        cards = bot.decide_play(copy.deepcopy(rnd), seat)
        if bot.last_decision_record.get("adaptive_worlds_total", 0) > 8:
            return rnd, seat
        rnd.play(seat, cards)
    pytest.fail("no decision of the self-play runs the adaptive stage")


def test_an_adaptive_worlds_draw_that_falls_back_is_counted(package, monkeypatch):
    now, seat = _adaptive_root(package)
    bot = _adaptive_bot(package)
    _fail_belief_after_first_draw(monkeypatch)
    bot.decide_play(copy.deepcopy(now), seat)
    rec = bot.last_decision_record
    assert rec["adaptive_worlds_triggered"] and rec.get("adaptive_worlds_total", 0) > 8, \
        "the fixture must reach the adaptive stage's draws"
    extra = rec["world_draws_by_stage"]["adaptive_worlds"]
    assert extra == pv.ADAPTIVE_WORLDS_EXTRA_ROUNDS and rec["belief_fallback"] == 0
    assert rec["belief_fallback_by_stage"] == {"base": 0, "lead_confirm": 0,
                                               "adaptive_worlds": extra}
    assert rec["belief_fallback_any"] == 1


def test_a_base_draw_fallback_is_counted_in_both_fields(package, monkeypatch):
    _, now, seat = fixture()
    bot = _belief(served(belief_worlds=True, belief_sha256=package["sha256"], **WHL), package)
    monkeypatch.setattr(bn.BeliefNumpy, "marginals",
                        lambda self, inp: (_ for _ in ()).throw(RuntimeError("boom")))
    bot.decide_play(copy.deepcopy(now), seat)
    rec = bot.last_decision_record
    assert rec["belief_fallback"] == 1 and rec["belief_fallback_any"] == 1
    assert rec["belief_fallback_by_stage"]["base"] == 1 == rec["belief_fallback_all_draws"]


def test_a_clean_decision_counts_zero_and_the_tally_resets(package):
    _, now, seat = fixture()
    bot = _belief(served(belief_worlds=True, belief_sha256=package["sha256"], **WHL), package)
    for _ in range(2):
        bot.decide_play(copy.deepcopy(now), seat)
        rec = bot.last_decision_record
        assert rec["world_draws_by_stage"] == {"base": 1, "lead_confirm": 0, "adaptive_worlds": 0}
        assert rec["belief_fallback_any"] == 0 and rec["belief_fallback_all_draws"] == 0


def test_off_the_records_carry_no_tally():
    _, now, seat = fixture()
    off = served()
    off.decide_play(copy.deepcopy(now), seat)
    assert not {"world_draws_by_stage", "belief_fallback_any", "history_fill_worlds",
                "leaf_greedy_deadline_fired_lead_confirm"} & set(off.last_decision_record)
    assert "_draw_tally" not in vars(off)
    whl = served(**WHL)
    whl.decide_play(copy.deepcopy(now), seat)
    assert "world_draws_by_stage" in whl.last_decision_record
    assert "belief_fallback_any" not in whl.last_decision_record


# ------------------------------------------------------- (b) history fill vs unchecked worlds

def test_the_plain_fill_and_the_untested_source_worlds_are_separate(monkeypatch):
    _, now, seat = fixture()
    bot = served(**WHL)
    mem = Memory(now, seat, own_kitty=True)
    # a source that never yields: every world is the plain production fill
    _, _, stats = HL.sample_worlds_history_legal(bot.sampler, now, seat, W, mem=mem,
                                                 propose=lambda r, s, m: None)
    assert stats["history_fill_worlds"] == W and stats["history_unchecked_worlds"] == 0
    assert stats["history_fallback_worlds"] == W
    # no history budget: every world is the source's, kept untested
    monkeypatch.setattr(HL, "HISTORY_ATTEMPT_FACTOR", 0)
    _, _, stats = HL.sample_worlds_history_legal(bot.sampler, now, seat, W, mem=mem)
    assert HL.follow_events(now, seat)
    assert stats["history_unchecked_worlds"] == W and stats["history_fill_worlds"] == 0
    assert stats["history_fallback_worlds"] == W


def test_the_record_carries_the_split_for_the_base_draw_and_every_draw(monkeypatch):
    _, now, seat = fixture()
    bot = served(**WHL)
    real = HL.sample_worlds_history_legal

    def starved(sampler, rnd, seat_, n, refusals=(), **kw):
        # the source yields nothing: the attempt cap runs out and the fill draws all n
        return real(sampler, rnd, seat_, n, refusals, **{**kw, "propose": lambda r, s, m: None})
    monkeypatch.setattr(pv, "sample_worlds_history_legal", starved)
    bot.decide_play(copy.deepcopy(now), seat)
    rec = bot.last_decision_record
    assert rec["history_fill_worlds"] == W and rec["history_unchecked_worlds"] == 0
    assert rec["history_fallback_worlds"] == W
    assert rec["history_fill_worlds_by_stage"] == {"base": W, "lead_confirm": 0, "adaptive_worlds": 0}
    assert rec["history_fill_worlds_all_draws"] == W
    assert rec["history_unchecked_worlds_all_draws"] == 0


# ------------------------------------------------------- (c) lgfd inside the lead confirmation

def test_a_deadline_cut_inside_the_lead_confirmation_is_an_lgfd_firing(monkeypatch):
    rnd, seat = _lead()
    evaluator = OutsideBallotEvaluator(1.0)
    _prime(evaluator, rnd, seat)
    bot = _lcc_bot(evaluator, leaf_greedy_deadline_ms=60_000)
    prefill = pv.PVSearchBot._greedy_prefill
    calls = []

    def cut(self, *a, **kw):
        calls.append(1)
        prefill(self, *a, **kw)
        if len(calls) == 2:
            # the confirmation's screen pass: the finish passes its deadline
            self._leaf_greedy["deadline_cut"] = 1
    monkeypatch.setattr(pv.PVSearchBot, "_greedy_prefill", cut)
    bot.decide_play(copy.deepcopy(rnd), seat)
    rec = bot.last_decision_record
    assert rec["lead_confirm_abandon_reason"] == "leaf_deadline"
    # the base pass's field keeps its meaning; the cut is recorded beside it
    assert rec["leaf_greedy_deadline_fired"] is False
    assert rec["leaf_greedy_deadline_fired_lead_confirm"] is True
    assert rec["leaf_greedy_deadline_fired_any"] is True


def test_an_unreached_deadline_records_no_firing():
    rnd, seat = _lead()
    bot = _lcc_bot(HashNoiseEvaluator(), leaf_greedy_deadline_ms=60_000)
    bot.decide_play(copy.deepcopy(rnd), seat)
    rec = bot.last_decision_record
    assert rec["leaf_greedy_deadline_fired_lead_confirm"] is False
    assert rec["leaf_greedy_deadline_fired_any"] is False
    # no confirmation stage: the base pass's two fields only
    plain = leaf_bot(HashNoiseEvaluator(), worlds=8, leaf_greedy_deadline_ms=60_000, **R46_RULES)
    plain.decide_play(copy.deepcopy(rnd), seat)
    assert "leaf_greedy_deadline_fired" in plain.last_decision_record
    assert not {"leaf_greedy_deadline_fired_lead_confirm",
                "leaf_greedy_deadline_fired_any"} & set(plain.last_decision_record)


# ------------------------------------------------------- (d) the bury record is per call

@pytest.mark.parametrize("budget", [None, 5.0])
def test_a_raising_bury_call_leaves_no_earlier_record(budget):
    bot = served_bury(bury_wide_value=True, bury_wide_k=16, bury_budget=budget)
    rnd = bury_state(0)
    bot.decide_bury(copy.deepcopy(rnd), rnd.banker)
    assert bot.last_bury_record is not None
    played = copy.deepcopy(rnd)
    played.phase = "play"
    with pytest.raises(bury_policy.BuryPolicyError):
        bot.decide_bury(played, rnd.banker)
    assert bot.last_bury_record is None
