"""The OPTIONAL unresolved-decision evidence rule of the pv-search bot
(``adaptive_worlds``, ``SHENGJI_PV_ADAPTIVE_WORLDS``).

Evidence (release 42 diagnostic, smv3out-491ee4bf, W64 K8): on LEADS the top-2
value gap was within one paired SE in 35% of decisions and resampling the 64
worlds flipped the pick 18% of the time.  Rule: when the top-2 gap is below
``ADAPTIVE_WORLDS_Z`` paired SEs, score the ADMITTED candidates on three more
batches of W worlds and select on the 4W means.

Torch-free and package-free: real engine positions, the served wrapper's own
sampler, admission and selection, a stub policy and stub value heads.
Witnesses: (a) off == main's `_search` (verbatim copy) over self-play, no new
record key, pinned names/digest; (b) on: name token / digest / env; (c) the
trigger with stub evaluators; (d) the budget: not attempted past 50%, abandoned
at the soft deadline, never the fallback; (e) the combined worlds reach the
selection rules; (f) refusals (tree, a replaced `_value_means`); (g) a saved
panel without the field still binds.
"""
import copy
import hashlib
import time
import types

import numpy as np
import pytest

from shengji.train import pv_search_policy as pv
from shengji.train.pv_search_policy import (FORCED_EXTRA_SLOTS, RECORD_SCHEMA,
                                            PVSearchPolicyError)
from test_policy_world_search import state
from test_pv_admission_rules import PRODUCTION_ENV, PRODUCTION_SHA, names, predict, \
    production_package  # noqa: F401
from test_pv_small_joker_lead import (RELEASE38_ENV, RELEASE38_NAME, RELEASE38_RULES,
                                      PointsEvaluator, _fresh_round, _strip)

RELEASE42_ENV = {**RELEASE38_ENV, "SHENGJI_PV_DOOMED_THROW_SWAP": "1"}
RELEASE42_NAME = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-dts-r0f40c8b5-bury-hybrid-273fed4cd40d"
RELEASE42_RULES = {**RELEASE38_RULES, "doomed_throw_swap": True}
FLAG = "SHENGJI_PV_ADAPTIVE_WORLDS"
RULE_KEYS = {"adaptive_worlds_triggered", "adaptive_worlds_total", "adaptive_worlds_margin",
             "adaptive_worlds_se", "adaptive_worlds_skipped_budget",
             "adaptive_worlds_abandoned", "adaptive_worlds_changed",
             "adaptive_worlds_played_changed", "adaptive_worlds_sampler_advanced",
             "adaptive_worlds_base_seconds"}
W = 8


# ------------------------------------------------------- stub value heads

def _root_cards(leaf, seat):
    trick = leaf.last_trick
    return tuple(sorted(next(p.cards for p in trick.plays if p.seat == seat)))


def _action_value(cards):
    """A distinct, world-independent value per card multiset."""
    return int(hashlib.sha256(" ".join(cards).encode()).hexdigest()[:8], 16) / 2 ** 32


class ClearEvaluator:
    """World-independent and distinct per action: SE 0, margin > 0 -> resolved."""
    backend = "numpy"
    max_batch = 128

    def score(self, leaves, seat):
        return np.asarray([_action_value(_root_cards(leaf, seat)) for leaf in leaves])


class ConstantEvaluator:
    """Every leaf 0.5: margin 0 and SE 0 -> unresolved (the zero/zero case)."""
    backend = "numpy"
    max_batch = 128

    def score(self, leaves, seat):
        return np.full(len(leaves), 0.5)


class NoisyEvaluator:
    """A tiny action term under large leaf noise (seeded): a near-tie."""
    backend = "numpy"
    max_batch = 128

    def __init__(self, seed=5):
        self.rng = np.random.default_rng(seed)

    def score(self, leaves, seat):
        base = np.asarray([1e-4 * _action_value(_root_cards(leaf, seat)) for leaf in leaves])
        return base + self.rng.normal(0.0, 1.0, len(leaves))


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def perf_counter(self):
        return self.now


class ClockEvaluator:
    """Advances the fake clock by ``steps[i]`` on its i-th call (0 after)."""
    backend = "numpy"
    max_batch = 128

    def __init__(self, clock, steps, inner=None):
        self.clock, self.steps, self.calls = clock, list(steps), 0
        self.inner = inner or NoisyEvaluator()

    def score(self, leaves, seat):
        out = self.inner.score(leaves, seat)
        if self.calls < len(self.steps):
            self.clock.now += self.steps[self.calls]
        self.calls += 1
        return out


def served(evaluator, worlds=W, seed=17, budget=None, **rules):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=worlds, candidates=8,
                               cap=4000, batch_size=128, serving_budget_seconds=budget, **rules)
    return pv.PVSearchBot(predict, evaluator=evaluator, version=2, config=config,
                          checkpoint="/dev/null", seed=seed)


def spy(bot):
    """Count `_worlds` draws and record every `_score_leaves`, `_select` and
    `_swap_doomed_throw` call's evidence."""
    log = {"worlds": 0, "scored": [], "select_worlds": [], "swap_worlds": []}
    orig_worlds, orig_score = bot._worlds, bot._score_leaves
    orig_select, orig_swap = bot._select, bot._swap_doomed_throw

    def _worlds(*a, **kw):
        log["worlds"] += 1
        return orig_worlds(*a, **kw)

    def _score_leaves(rnd, seat, actions, worlds, *a, **kw):
        log["scored"].append(([list(x) for x in actions], len(worlds)))
        return orig_score(rnd, seat, actions, worlds, *a, **kw)

    def _select(*a, worlds=None, **kw):
        log["select_worlds"].append(len(worlds))
        return orig_select(*a, worlds=worlds, **kw)

    def _swap(rnd, seat, action, worlds, *a, **kw):
        log["swap_worlds"].append(len(worlds))
        return orig_swap(rnd, seat, action, worlds, *a, **kw)
    bot._worlds, bot._score_leaves = _worlds, _score_leaves
    bot._select, bot._swap_doomed_throw = _select, _swap
    return log


def decide(bot, rnd=None, seat=None):
    if rnd is None:
        rnd = state()
        seat = rnd.turn
    played = bot.decide_play(copy.deepcopy(rnd), seat)
    return played, bot.last_decision_record


# ------------------------------------------------------- (a) off == main

class MainServed(pv.PVSearchBot):
    """The served wrapper with `_search` verbatim from main 95026dc2 (before the rule)."""

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
        means, batches = self._value_means(rnd, seat, admitted, worlds, check_budget)
        if check_budget is not None:
            check_budget()
        winner = self._select(rnd, seat, admitted, means, worlds=worlds, check_budget=check_budget,
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
            "value_evaluations": len(worlds) * len(admitted),
            "anchor_selected": winner == 0, "encoder_version": self.version,
            "played": list(played),
            "seconds": time.perf_counter() - started, "work_complete": True,
            **self._admission_record(),
            **self._sampler_record(),
            **self._tiebreak_record(),
            **self._lead_tiebreak_record(),
            **self._doomed_throw_record(),
        }
        return list(played)


def _bot(cls, seat, rules, **flags):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=4, candidates=8, cap=4000,
                               batch_size=128, **rules, **flags)
    return cls(predict, evaluator=PointsEvaluator(), version=2, config=config,
               checkpoint="/dev/null", seed=100 + seat)


SELF_PLAY_SEEDS = tuple(range(707001, 707005))


@pytest.mark.parametrize("rules", [RELEASE42_RULES, {}], ids=["release42", "bare"])
def test_off_is_mains_decision_over_self_play(rules):
    decisions = triggered = changed = 0
    for seed in SELF_PLAY_SEEDS:
        rnd = _fresh_round(seed)
        off = [_bot(pv.PVSearchBot, s, rules) for s in range(4)]
        main = [_bot(MainServed, s, rules) for s in range(4)]
        on = [_bot(pv.PVSearchBot, s, rules, adaptive_worlds=True) for s in range(4)]
        while rnd.phase == "play":
            seat = rnd.turn
            a = off[seat].decide_play(copy.deepcopy(rnd), seat)
            b = main[seat].decide_play(copy.deepcopy(rnd), seat)
            assert a == b
            assert _strip(off[seat].last_decision_record) == _strip(main[seat].last_decision_record)
            assert not RULE_KEYS & set(off[seat].last_decision_record)
            assert off[seat].sampler.rng.getstate() == main[seat].sampler.rng.getstate()
            # the counterfactual on-arm on the same position (census only)
            c = on[seat].decide_play(copy.deepcopy(rnd), seat)
            rec = on[seat].last_decision_record
            assert rec["schema"] == RECORD_SCHEMA and RULE_KEYS <= set(rec)
            decisions += 1
            triggered += rec["adaptive_worlds_triggered"]
            changed += c != a
            on[seat].sampler.rng.setstate(off[seat].sampler.rng.getstate())
            rnd.play(seat, a)
    assert decisions >= 100
    print(f"\nadaptive_worlds census [{'release42' if rules else 'bare'}]: "
          f"decisions={decisions} triggered={triggered} played_changed={changed}")


def test_off_allocates_no_matrix_and_draws_once():
    bot = served(NoisyEvaluator(), **RELEASE42_RULES)
    calls = []
    orig = bot._score_leaves

    def _score_leaves(*a, capture=None, **kw):
        calls.append(capture)
        return orig(*a, capture=capture, **kw)
    bot._score_leaves = _score_leaves
    log_worlds = []
    orig_worlds = bot._worlds
    bot._worlds = lambda *a, **kw: log_worlds.append(1) or orig_worlds(*a, **kw)
    _, rec = decide(bot)
    assert calls == [None] and len(log_worlds) == 1
    assert not RULE_KEYS & set(rec) and rec["worlds"] == W


def test_release_names_unchanged_when_off(production_package):
    assert names(RELEASE38_ENV) == [RELEASE38_NAME]
    assert names(RELEASE42_ENV) == [RELEASE42_NAME]
    for raw in ("0", ""):
        assert names({**RELEASE42_ENV, FLAG: raw}) == [RELEASE42_NAME]
        assert names({**RELEASE38_ENV, FLAG: raw}) == [RELEASE38_NAME]
    config = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0)
    assert pv.recipe_digest(config) == "4a09aef5"
    assert not any(k.startswith("adaptive_worlds") for k in pv.recipe_payload(config))


# ------------------------------------------------------- (b) on: name, digest, env

def test_aw_token_last_and_digest_when_on(production_package):
    on, = names({**RELEASE42_ENV, FLAG: "1"})
    assert on.startswith("pv-search-491ee4bf-w64-k8-div-rc-tb-la-dts-aw-r") and "-bury-hybrid-" in on
    every, = names({**RELEASE42_ENV, FLAG: "1", "SHENGJI_PV_SMALL_JOKER_GUARD": "1"})
    assert every.startswith("pv-search-491ee4bf-w64-k8-div-rc-tb-la-dts-sjg-aw-r")
    assert pv.RULE_TOKENS[-3] == ("adaptive_worlds", "aw")   # then its leads-only awl, dtr
    assert pv.RULE_FLAGS["ADAPTIVE_WORLDS"] == "adaptive_worlds"
    base = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0)
    aw = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                           adaptive_worlds=True)
    payload = pv.recipe_payload(aw)
    assert payload["adaptive_worlds"] is True
    assert payload["adaptive_worlds_z"] == pv.ADAPTIVE_WORLDS_Z == 2.0
    assert payload["adaptive_worlds_extra_rounds"] == pv.ADAPTIVE_WORLDS_EXTRA_ROUNDS == 3
    assert payload["adaptive_worlds_start_fraction"] == 0.5
    assert payload["adaptive_worlds_soft_fraction"] == 0.8
    assert pv.recipe_digest(aw) != pv.recipe_digest(base)
    assert pv.ADAPTIVE_WORLDS_DEFAULTS["adaptive_worlds"] is False
    assert pv.PVSearchBot.adaptive_worlds is False     # the class-level off default


@pytest.mark.parametrize("bad", ["2", "true", "yes", "on", " 1"])
def test_env_flag_refuses_anything_but_0_or_1(bad):
    with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
        pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: bad})
    assert "adaptive_worlds" not in pv.pv_env_recipe(PRODUCTION_ENV)
    assert "adaptive_worlds" not in pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: "0"})
    assert pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: "1"})["adaptive_worlds"] is True


def test_bad_values_are_refused():
    with pytest.raises(pv.PVSearchPolicyError, match="must be a bool"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, adaptive_worlds=1))
    with pytest.raises(pv.PVSearchPolicyError, match="adaptive_worlds must be a bool"):
        served(ClearEvaluator(), adaptive_worlds="1")


# ------------------------------------------------------- (c) the trigger

@pytest.mark.parametrize("evaluator", [ConstantEvaluator, NoisyEvaluator], ids=["zero-zero", "noisy"])
def test_near_tie_triggers_and_scores_only_the_admitted_on_4w(evaluator):
    bot = served(evaluator(), adaptive_worlds=True)
    log = spy(bot)
    played, rec = decide(bot)
    assert rec["schema"] == RECORD_SCHEMA and rec["work_complete"] is True
    assert rec["adaptive_worlds_triggered"] is True and rec["adaptive_worlds_abandoned"] is False
    assert rec["adaptive_worlds_total"] == 4 * W and rec["worlds"] == W
    k = len(rec["admitted"])
    assert k >= 2
    assert rec["value_evaluations"] == 4 * W * k
    assert log["worlds"] == 1 + pv.ADAPTIVE_WORLDS_EXTRA_ROUNDS
    # base + three extra rounds, every one on exactly the admitted candidates
    assert [n for _, n in log["scored"]] == [W] * 4
    assert all(actions == rec["admitted"] for actions, _ in log["scored"])
    # the base decision is finalized first, then re-selected on the 4W evidence
    assert log["select_worlds"] == [W, 4 * W] and log["swap_worlds"] == [W, 4 * W]
    assert rec["adaptive_worlds_sampler_advanced"] is True
    assert rec["adaptive_worlds_margin"] < pv.ADAPTIVE_WORLDS_Z * rec["adaptive_worlds_se"] \
        or rec["adaptive_worlds_margin"] == rec["adaptive_worlds_se"] == 0.0
    assert all(type(rec[key]) is bool for key in ("adaptive_worlds_triggered",
                                                  "adaptive_worlds_abandoned",
                                                  "adaptive_worlds_changed"))
    assert rec["played"] == played


def test_clear_winner_does_not_trigger_or_draw():
    bot = served(ClearEvaluator(), adaptive_worlds=True)
    log = spy(bot)
    _, on = decide(bot)
    _, off = decide(served(ClearEvaluator()))
    assert on["adaptive_worlds_triggered"] is False
    assert on["adaptive_worlds_se"] == 0.0 and on["adaptive_worlds_margin"] > 0.0
    assert on["adaptive_worlds_total"] == W and log["worlds"] == 1
    assert [n for _, n in log["scored"]] == [W] and log["select_worlds"] == [W]
    for key in ("admitted", "value_means", "selected_index", "played", "value_evaluations"):
        assert on[key] == off[key]


def test_means_are_the_combined_sums_over_4w():
    """Selection uses (base sums + extra sums) / 4W, reproduced from the captured
    per-round sums."""
    bot = served(NoisyEvaluator(seed=11), adaptive_worlds=True)
    sums = []
    orig = bot._score_leaves

    def _score_leaves(*a, **kw):
        s, b = orig(*a, **kw)
        sums.append(s.copy())
        return s, b
    bot._score_leaves = _score_leaves
    _, rec = decide(bot)
    assert rec["adaptive_worlds_triggered"] is True and len(sums) == 4
    total = sums[0].copy()
    for s in sums[1:]:
        total = total + s
    assert rec["value_means"] == (total / (4 * W)).tolist()
    assert rec["adaptive_worlds_changed"] == (int(np.argmax(total)) != int(np.argmax(sums[0])))


def test_single_admitted_candidate_never_triggers(monkeypatch):
    bot = served(ConstantEvaluator(), adaptive_worlds=True)
    log = spy(bot)
    orig = bot._admit
    monkeypatch.setattr(bot, "_admit", lambda *a: orig(*a)[:1])
    _, rec = decide(bot)
    assert rec["adaptive_worlds_triggered"] is False and log["worlds"] == 1
    assert rec["adaptive_worlds_se"] is None


# ------------------------------------------------------- (d) the budget

@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(pv, "time", types.SimpleNamespace(perf_counter=fake.perf_counter))
    return fake


def test_not_attempted_past_half_the_budget(clock):
    # the base value pass (one batch) takes 6 of a 10 s budget
    bot = served(ClockEvaluator(clock, [6.0]), budget=10.0, adaptive_worlds=True)
    log = spy(bot)
    _, rec = decide(bot)
    assert rec["schema"] == RECORD_SCHEMA and rec["work_complete"] is True
    assert rec["adaptive_worlds_triggered"] is True
    assert rec["adaptive_worlds_skipped_budget"] is True
    assert rec["adaptive_worlds_total"] == W and log["worlds"] == 1
    assert log["select_worlds"] == [W]


def test_soft_expiry_abandons_and_plays_the_base_selection(clock):
    # base pass 1 s; the first extra round's scoring runs to 8.5 s of 10 (soft 8)
    bot = served(ClockEvaluator(clock, [1.0, 7.5]), budget=10.0, adaptive_worlds=True)
    log = spy(bot)
    played, rec = decide(bot)
    clock.now = 1000.0
    ref = served(ClockEvaluator(clock, [1.0]), budget=10.0)
    ref_played, base = decide(ref)
    assert rec["schema"] == RECORD_SCHEMA and rec["schema"] != pv.FALLBACK_SCHEMA
    assert rec["work_complete"] is True
    assert rec["adaptive_worlds_triggered"] is True and rec["adaptive_worlds_abandoned"] is True
    assert rec["adaptive_worlds_abandon_reason"] == "soft_budget"
    assert rec["adaptive_worlds_total"] == W and rec["adaptive_worlds_changed"] is False
    assert log["select_worlds"] == [W] and log["swap_worlds"] == [W]
    assert rec["value_means"] == base["value_means"]
    assert rec["selected_index"] == base["selected_index"] and played == ref_played
    # completed scoring passes only: the abandoned round never completed
    assert rec["value_evaluations"] == W * len(rec["admitted"])
    assert rec["adaptive_worlds_abandoned_evaluations"] == 0
    assert _comparable(rec) == _comparable(base)


def test_extra_stage_error_abandons_without_fallback():
    bot = served(NoisyEvaluator(), adaptive_worlds=True)
    orig = bot._worlds
    calls = []

    def _worlds(*a, **kw):
        calls.append(1)
        if len(calls) > 1:
            raise pv.PVSearchPolicyError("short", stage="world_sampling_short")
        return orig(*a, **kw)
    bot._worlds = _worlds
    _, rec = decide(bot)
    assert rec["schema"] == RECORD_SCHEMA and rec["work_complete"] is True
    assert rec["adaptive_worlds_abandoned"] is True
    assert rec["adaptive_worlds_abandon_reason"] == "error"
    assert rec["adaptive_worlds_abandon_error"] == "PVSearchPolicyError"


def test_sampler_record_describes_the_base_draw():
    bot = served(ConstantEvaluator(), adaptive_worlds=True, refusal_constraints=True)
    marker = {"refusal_observations": 7}
    orig = bot._worlds
    calls = []

    def _worlds(*a, **kw):
        out = orig(*a, **kw)
        bot._last_sampling = dict(marker) if not calls else {"refusal_observations": 99}
        calls.append(1)
        return out
    bot._worlds = _worlds
    _, rec = decide(bot)
    assert len(calls) == 4 and rec["refusal_observations"] == 7


# ------------------------------------------------------- (d2) the cached base decision (#936 HOLD)
# Optional work must never cost the completed base search: the base decision is
# finalized and cached before the extra stage, and ANY expiry or error in that
# stage plays it.  Codex's witness (review comment 6050486577) is the first test.

def _comparable(record):
    """A decision record without its timing, the rule's own fields and the
    sampler's cumulative-counter deltas (telemetry an abandoned draw moves)."""
    return {k: v for k, v in record.items()
            if k not in ("seconds", "elapsed_seconds") and not k.startswith("adaptive_worlds")
            and not k.endswith("_delta")}


def _assert_base_played(played, rec, ref_played, base, reason, error):
    assert rec["schema"] == RECORD_SCHEMA and rec["schema"] != pv.FALLBACK_SCHEMA, rec
    assert rec["work_complete"] is True and played == ref_played == rec["played"]
    assert rec["adaptive_worlds_triggered"] is True and rec["adaptive_worlds_abandoned"] is True
    assert rec["adaptive_worlds_abandon_reason"] == reason
    assert rec["adaptive_worlds_abandon_error"] == error
    assert rec["adaptive_worlds_total"] == W and rec["adaptive_worlds_changed"] is False
    assert rec["adaptive_worlds_played_changed"] is False
    assert rec["adaptive_worlds_sampler_advanced"] is True
    # exactly the record the flag-off decision published, rule records included
    assert _comparable(rec) == _comparable(base)


@pytest.mark.parametrize("rules", [{}, RELEASE42_RULES], ids=["bare", "release42"])
def test_optional_score_crossing_hard_deadline_keeps_completed_base(clock, rules):
    base_bot = served(ClockEvaluator(clock, [1.0]), budget=10.0, **rules)
    expected, base_record = decide(base_bot)
    assert base_record["schema"] == RECORD_SCHEMA
    clock.now = 1000.0
    # base 1 s; the first extra score takes 10 s: past the soft AND hard deadline
    adaptive = served(ClockEvaluator(clock, [1.0, 10.0]), budget=10.0, adaptive_worlds=True,
                      **rules)
    actual, record = decide(adaptive)
    _assert_base_played(actual, record, expected, base_record, "hard_budget",
                        "PVSearchBudgetExceeded")
    assert record["value_means"] == base_record["value_means"]
    assert record["seconds"] == 11.0 and record["adaptive_worlds_base_seconds"] == 1.0
    # the round's post-score check raised: it never completed, nothing is counted
    assert record["adaptive_worlds_abandoned_evaluations"] == 0
    assert record["value_evaluations"] == base_record["value_evaluations"]
    # the abandoned draw advanced the sampler stream (and the record says so)
    assert adaptive.sampler.rng.getstate() != base_bot.sampler.rng.getstate()


def test_sampling_call_crossing_hard_deadline_keeps_completed_base(clock, monkeypatch):
    ref = served(ClockEvaluator(clock, [1.0]), budget=10.0)
    ref_played, base = decide(ref)
    clock.now = 1000.0
    orig, calls = pv.sample_worlds, []

    def sample_worlds(*a, **kw):
        calls.append(1)
        if len(calls) == 2:
            clock.now += 10.0   # the first EXTRA draw runs past the hard deadline
        return orig(*a, **kw)
    monkeypatch.setattr(pv, "sample_worlds", sample_worlds)
    bot = served(ClockEvaluator(clock, [1.0]), budget=10.0, adaptive_worlds=True)
    log = spy(bot)
    played, rec = decide(bot)
    assert len(calls) == 2 and [n for _, n in log["scored"]] == [W]
    _assert_base_played(played, rec, ref_played, base, "hard_budget", "PVSearchBudgetExceeded")
    assert rec["adaptive_worlds_abandoned_evaluations"] == 0


def test_hard_expiry_inside_the_4w_tiebreak_keeps_completed_base(clock):
    """The tie-break catches a hard expiry and returns its argmax; inside the
    re-selection that degraded result is never published."""
    rules = dict(tiebreak_points=True, doomed_throw_swap=True)
    ref = served(ClockEvaluator(clock, [1.0], inner=ConstantEvaluator()), budget=10.0, **rules)
    ref_played, base = decide(ref)
    assert len(base["tiebreak_near_set"]) >= 2 and "tiebreak_abandoned" not in base
    clock.now = 1000.0
    bot = served(ClockEvaluator(clock, [1.0], inner=ConstantEvaluator()), budget=10.0,
                 adaptive_worlds=True, **rules)
    fired = []
    orig = bot._trick_points

    def _trick_points(rnd, seat, hands, buried, action, world_index):
        if world_index >= W and not fired:   # an EXTRA world: the 4W rebuild
            fired.append(1)
            clock.now += 10.0
        return orig(rnd, seat, hands, buried, action, world_index)
    bot._trick_points = _trick_points
    log = spy(bot)
    played, rec = decide(bot)
    assert fired and log["select_worlds"] == [W, 4 * W]
    _assert_base_played(played, rec, ref_played, base, "hard_budget", "PVSearchBudgetExceeded")
    # the restored records are the base finalization's, not the absorbed 4W ones
    assert "tiebreak_abandoned" not in rec and rec["doomed_throw_swap_worlds"] == W


def test_final_hard_check_restores_every_rule_record(clock):
    """The 4W re-selection completes and overwrites the rule records; the final
    hard check then fails: the snapshot is restored and the base is played."""
    rules = dict(RELEASE42_RULES, lead_tiebreak_prior=True)
    ref = served(ClockEvaluator(clock, [1.0], inner=ConstantEvaluator()), budget=10.0, **rules)
    ref_played, base = decide(ref)
    assert {"tiebreak_near_set", "lead_tiebreak_leading", "doomed_throw_swap_worlds"} <= set(base)
    clock.now = 1000.0
    bot = served(ClockEvaluator(clock, [1.0], inner=ConstantEvaluator()), budget=10.0,
                 adaptive_worlds=True, **rules)
    orig_select = bot._select
    selects, seen = [], {}

    def _select(*a, **kw):
        out = orig_select(*a, **kw)
        selects.append(1)
        if len(selects) == 2:
            seen["tiebreak"] = copy.deepcopy(bot._tiebreak)
            clock.now += 10.0   # the 4W selection finished past the deadline
        return out
    bot._select = _select
    played, rec = decide(bot)
    assert len(selects) == 2
    # the 4W selection did overwrite the record state before it was restored
    assert seen["tiebreak"] != {k: base[k] for k in seen["tiebreak"]}
    _assert_base_played(played, rec, ref_played, base, "hard_budget", "PVSearchBudgetExceeded")


def test_extra_scoring_exception_keeps_completed_base():
    class Boom(NoisyEvaluator):
        calls = 0

        def score(self, leaves, seat):
            Boom.calls += 1
            if Boom.calls == 3:   # the SECOND extra round (one batch per round)
                raise RuntimeError("extra scoring failed")
            return super().score(leaves, seat)
    ref_played, base = decide(served(NoisyEvaluator()))
    bot = served(Boom(), adaptive_worlds=True)
    played, rec = decide(bot)
    _assert_base_played(played, rec, ref_played, base, "error", "RuntimeError")
    # the completed first extra round is reported as thrown away, never published
    assert rec["adaptive_worlds_abandoned_evaluations"] == W * len(rec["admitted"])
    assert rec["value_evaluations"] == base["value_evaluations"]


def test_base_interrupt_is_not_swallowed():
    class Interrupting(NoisyEvaluator):
        calls = 0

        def score(self, leaves, seat):
            Interrupting.calls += 1
            if Interrupting.calls == 2:
                raise KeyboardInterrupt
            return super().score(leaves, seat)
    with pytest.raises(KeyboardInterrupt):
        decide(served(Interrupting(), budget=100.0, adaptive_worlds=True))


@pytest.mark.parametrize("steps", [[11.0], [0.0, 0.0, 0.0]], ids=["base-score", "base-sampling"])
def test_base_failure_falls_back_exactly_as_flag_off(clock, monkeypatch, steps):
    """A budget expiry in the BASE pass is a base failure: the normal fallback,
    the sampler stream rewound, exactly as with the rule off."""
    if steps == [0.0, 0.0, 0.0]:
        orig = pv.sample_worlds

        def sample_worlds(*a, **kw):
            clock.now += 11.0
            return orig(*a, **kw)
        monkeypatch.setattr(pv, "sample_worlds", sample_worlds)
    off = served(ClockEvaluator(clock, steps), budget=10.0)
    before = off.sampler.rng.getstate()
    off_played, off_rec = decide(off)
    clock.now = 1000.0
    on = served(ClockEvaluator(clock, steps), budget=10.0, adaptive_worlds=True)
    on_played, on_rec = decide(on)
    assert off_rec["schema"] == on_rec["schema"] == pv.FALLBACK_SCHEMA
    assert on_rec["reason"] == "budget" and on_rec["work_complete"] is False
    assert on_played == off_played
    assert _comparable(on_rec) == _comparable(off_rec)
    assert on.sampler.rng.getstate() == off.sampler.rng.getstate() == before


def test_unresolved_past_half_after_finalization_is_skipped(clock):
    """The start share is read AFTER the base finalization: a base tie-break that
    runs the decision past 50% leaves the base decision standing."""
    bot = served(ClockEvaluator(clock, [1.0], inner=ConstantEvaluator()), budget=10.0,
                 adaptive_worlds=True, tiebreak_points=True)
    orig = bot._trick_points

    def _trick_points(*a):
        clock.now += 0.1
        return orig(*a)
    bot._trick_points = _trick_points
    log = spy(bot)
    played, rec = decide(bot)
    assert rec["adaptive_worlds_triggered"] is True and rec["adaptive_worlds_skipped_budget"] is True
    assert rec["adaptive_worlds_base_seconds"] >= 5.0 and log["worlds"] == 1
    assert rec["adaptive_worlds_sampler_advanced"] is False
    assert played == rec["played"]


# ------------------------------------------------------- (e) later rules see the combined worlds

def test_tiebreak_points_rebuild_over_the_combined_worlds():
    bot = served(ConstantEvaluator(), adaptive_worlds=True, tiebreak_points=True,
                 doomed_throw_swap=True)
    log = spy(bot)
    seen = []
    orig = bot._trick_points

    def _trick_points(rnd, seat, hands, buried, action, world_index):
        seen.append(world_index)
        return orig(rnd, seat, hands, buried, action, world_index)
    bot._trick_points = _trick_points
    _, rec = decide(bot)
    assert rec["adaptive_worlds_total"] == 4 * W
    assert log["select_worlds"] == [W, 4 * W] and log["swap_worlds"] == [W, 4 * W]
    near = rec["tiebreak_near_set"]
    # the constant head puts every admitted candidate in both near-sets: the
    # base finalization rebuilds W worlds each, the re-selection 4W
    assert len(near) == len(rec["admitted"]) >= 2 and len(seen) == 5 * W * len(near)
    assert max(seen) == 4 * W - 1
    assert rec["doomed_throw_swap_worlds"] == 4 * W


# ------------------------------------------------------- (f) refusals

def test_tree_is_refused():
    from shengji.train.pv_tree_config import PVTreeConfig
    from shengji.train.pv_tree_search import PVTreeSearchBot
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, tree=PVTreeConfig(sims=8),
                               adaptive_worlds=True)
    with pytest.raises(pv.PVSearchPolicyError, match="does not combine with the tree"):
        pv.recipe_payload(config)
    with pytest.raises(pv.PVSearchPolicyError, match="replaces it"):
        PVTreeSearchBot(predict, evaluator=ClearEvaluator(), version=2, config=config,
                        checkpoint="/dev/null")
    # the tree alone is unaffected
    PVTreeSearchBot(predict, evaluator=ClearEvaluator(), version=2,
                    config=pv.PVSearchConfig(checkpoint_sha256="f" * 64, tree=PVTreeConfig(sims=8)),
                    checkpoint="/dev/null")


def test_a_replaced_value_reducer_is_refused():
    class Weighted(pv.PVSearchBot):
        def _value_means(self, *a, **kw):
            return super()._value_means(*a, **kw)
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, adaptive_worlds=True)
    with pytest.raises(pv.PVSearchPolicyError, match="replaces it"):
        Weighted(predict, evaluator=ClearEvaluator(), version=2, config=config,
                 checkpoint="/dev/null")


# ------------------------------------------------------- (g) saved panels predating the field

def test_saved_panel_without_the_field_still_binds():
    from test_panel_rank_root import inputs
    from shengji.eval import panel_rank_root
    panel, fixture, bot = inputs()
    for field in ("doomed_throw_swap", "small_joker_guard", "adaptive_worlds"):
        del panel['config'][field]
    root = panel_rank_root.bind_panel_rank_root(panel, fixture, bot)
    assert root.turn == fixture.seat


@pytest.mark.parametrize("damage", ["config_true", "bot_true"])
def test_saved_panel_without_the_field_refuses_the_rule_on(damage):
    from dataclasses import replace
    from test_panel_rank_root import inputs
    from shengji.eval import panel_rank_root
    panel, fixture, bot = inputs()
    del panel['config']['adaptive_worlds']
    if damage == "config_true":
        bot.config = replace(bot.config, adaptive_worlds=True)
    else:
        bot.adaptive_worlds = True
    with pytest.raises(ValueError, match="config mismatch"):
        panel_rank_root.bind_panel_rank_root(panel, fixture, bot)
