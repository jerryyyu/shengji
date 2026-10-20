"""The OPTIONAL exact-stage guard of the doomed-throw re-select
(``doomed_throw_reselect_exact_guard``, ``SHENGJI_PV_DOOMED_THROW_RESELECT_EXACT_GUARD``,
token ``dtrx``): on a complete exact lead stage the re-select never moves to a
candidate whose exact mean is below the exact stage's selection.  Requires
``doomed_throw_reselect`` and ``exact_lead_endgame``.

Torch-free and package-free.  Witnesses: (a) on the YJQJ ballot under exact
means, the guard keeps the exact selection when every alternative is worse,
re-selects to an exact tie, skips the doomed test when nothing could replace
the selection, and keeps the first run's selection records; (b) through the
served decision at an endgame root, a complete exact stage keeps its choice,
while an abandoned or ineligible stage re-selects as ``dtr`` does; (c) with the
flag off, the bot, its record and a seeded round are exactly ``dtr``'s;
(d) env / name / digest / refusals.
"""
import copy
import hashlib

import numpy as np
import pytest

from shengji.train import policy_value_search as module
from shengji.train import pv_exact_deep
from shengji.train import pv_exact_endgame as exact
from shengji.train import pv_search_policy as pv
from shengji.train.policy_value_search import PolicyValueBot
from test_pv_admission_rules import PRODUCTION_SHA, ZeroEvaluator, names, predict, production_package  # noqa: F401
from test_pv_adaptive_worlds import RELEASE42_ENV
from test_pv_doomed_throw_reselect import (DECISIONS, DTR_RULES, RULE_KEYS, SEAT, Expire,
                                           HashNoiseEvaluator, draw, served, throw_loving_scores,
                                           yjqj)
from test_pv_finish_lead import root
from test_pv_small_joker_lead import _fresh_round
from test_release46_fly_config import RELEASE46, V92_CANDIDATE_ENV

FLAG = "SHENGJI_PV_DOOMED_THROW_RESELECT_EXACT_GUARD"
DTR_FLAG = "SHENGJI_PV_DOOMED_THROW_RESELECT"
GUARD_KEYS = {"doomed_throw_reselect_exact_guarded", "doomed_throw_reselect_exact_floor_excluded"}
#: release 46's rule env without its belief worlds (whose package this
#: package-free module cannot bind; `test_release46_fly_config` pins the served
#: name with it): release 42 without its swap, plus the combo's exact and
#: declare rules and the re-select
R46_ENV = {k: v for k, v in RELEASE42_ENV.items() if k != "SHENGJI_PV_DOOMED_THROW_SWAP"}
R46_ENV.update({k: v for k, v in V92_CANDIDATE_ENV.items()
                if "BELIEF" not in k and "HISTORY" not in k},
               **{DTR_FLAG: "1", "SHENGJI_PV_VALUE_DECLARE": "1"})
R46_NAME = ("pv-search-491ee4bf-w64-k8-div-rc-tb-ele-la-dtr-vd-vdef-ed7-xf7-xfcompactlevel-"
            "r61872ee5-bury-hybrid-04e56c74a146")
DTRX_ENV = {**R46_ENV, FLAG: "1"}
DTRX_NAME = ("pv-search-491ee4bf-w64-k8-div-rc-tb-ele-la-dtr-dtrx-vd-vdef-ed7-xf7-xfcompactlevel-"
             "rd464741c-bury-hybrid-08616a07c5d9")
#: the exact stage is on in every guard bot (the recipe requires it)
EXACT = dict(exact_lead_endgame=True)


def guard_bot(evaluator=None, worlds=64, seed=17, on=True, **rules):
    return served(evaluator, worlds=worlds, seed=seed, doomed_throw_reselect=True,
                  doomed_throw_reselect_exact_guard=on, **EXACT, **{**DTR_RULES, **rules})


def select(bot, rnd, d, worlds, exact_stage, admitted=None, means=None, priors=None,
           check_budget=None):
    """The decision's tail (`_select`, then `_swap_doomed_throw`) on a logged
    ballot, as the exact lead stage runs it (``exact=True``) or the base pass."""
    admitted = d["admitted"] if admitted is None else admitted
    means = np.asarray(d["means"] if means is None else means, dtype=np.float64)
    priors = d["priors"] if priors is None else priors
    winner = bot._select(rnd, SEAT, admitted, means, worlds=worlds, check_budget=check_budget,
                         priors=priors, exact=exact_stage)
    return winner, bot._swap_doomed_throw(rnd, SEAT, admitted[winner], worlds, check_budget)


def sj_means(**overrides):
    """The YJQJ SJ ballot's means with the throw (1) and its alias (7) best;
    ``overrides`` set positions by cards text."""
    d = DECISIONS["SJ"]
    means = list(d["means"])
    for cards, value in overrides.items():
        means[d["admitted"].index(cards.split())] = value
    return means


# ------------------------------------------------- (a) the YJQJ ballot under exact means

def test_the_guard_keeps_the_exact_selection_when_every_alternative_is_worse():
    d = DECISIONS["SJ"]
    rnd = yjqj(d["plays"])
    worlds = draw(rnd, 0)
    assert max(d["means"]) == d["means"][1] == d["means"][7]      # throw and alias best
    bot = guard_bot()
    winner, played = select(bot, rnd, d, worlds, exact_stage=True)
    record = bot._doomed_throw_record()
    assert set(record) == RULE_KEYS | GUARD_KEYS
    assert winner == 1 and played == d["throw"]                  # selected, played as selected
    assert record["doomed_throw_reselect_applied"] is False
    assert record["doomed_throw_reselect_fallback_forced"] is False
    assert record["doomed_throw_reselect_to"] == record["doomed_throw_reselect_from"] == " ".join(d["throw"])
    assert record["doomed_throw_reselect_exact_guarded"] is True
    assert record["doomed_throw_reselect_exact_floor_excluded"] == 6
    # the alias ties the floor, so the doomed test ran and excluded both
    assert record["doomed_throw_reselect_doomed_candidates"] == 1
    assert record["doomed_throw_reselect_forced_excluded"] == 1
    # dtr on the same exact means discards exact value: it re-selects below the floor
    dtr = guard_bot(on=False)
    dtr_winner, dtr_played = select(dtr, rnd, d, worlds, exact_stage=True)
    assert dtr._doomed_throw_record()["doomed_throw_reselect_applied"] is True
    assert dtr_played != d["throw"] and d["means"][dtr_winner] < d["means"][1]
    # and so does the guard bot on the base pass (no exact means: no floor)
    base = guard_bot()
    base_winner, base_played = select(base, rnd, d, worlds, exact_stage=False)
    assert (base_winner, base_played) == (dtr_winner, dtr_played)
    assert base._doomed_throw_record()["doomed_throw_reselect_applied"] is True
    assert base._doomed_throw_record()["doomed_throw_reselect_exact_guarded"] is False
    assert base._doomed_throw_record()["doomed_throw_reselect_exact_floor_excluded"] == 0


def test_a_tie_at_the_floor_keeps_the_reselect():
    d = DECISIONS["SJ"]
    rnd = yjqj(d["plays"])
    worlds = draw(rnd, 0)
    means = sj_means(CA=d["means"][1])                            # CA ties the throw exactly
    bot = guard_bot()
    winner, played = select(bot, rnd, d, worlds, exact_stage=True, means=means)
    record = bot._doomed_throw_record()
    assert played == ["CA"] and means[winner] == means[1]
    assert record["doomed_throw_reselect_applied"] is True
    assert record["doomed_throw_reselect_to"] == "CA"
    assert record["doomed_throw_reselect_exact_floor_excluded"] == 5
    # a candidate just under the floor is never reached
    means = sj_means(CA=d["means"][1] - 1e-9)
    bot = guard_bot()
    winner, played = select(bot, rnd, d, worlds, exact_stage=True, means=means)
    assert winner == 1 and played == d["throw"]
    assert bot._doomed_throw_record()["doomed_throw_reselect_applied"] is False


def test_the_reselect_never_moves_below_the_floor_over_random_exact_means():
    d = DECISIONS["SJ"]
    rnd = yjqj(d["plays"])
    worlds = draw(rnd, 0)
    rng = np.random.default_rng(51)
    kept = moved = 0
    for _ in range(40):
        # level-quantized means, as exact means are, over the logged ballot
        means = rng.integers(-3, 4, size=len(d["admitted"])) / 2.0
        means[7] = means[1]                                        # the alias shares the leaf
        bot = guard_bot()
        winner, played = select(bot, rnd, d, worlds, exact_stage=True, means=means)
        first = int(np.argmax(means))
        assert means[winner] >= means[first]
        assert played == d["admitted"][winner]
        record = bot._doomed_throw_record()
        assert record["doomed_throw_reselect_fallback_forced"] is False
        if record["doomed_throw_reselect_applied"]:
            moved += 1
            assert winner != 1 and sorted(played) != sorted(d["played"])
        else:
            kept += 1
    assert kept and moved


def test_the_doomed_test_is_skipped_when_nothing_could_replace_the_selection(monkeypatch):
    d = DECISIONS["SJ"]
    rnd = yjqj(d["plays"])
    worlds = draw(rnd, 0)
    admitted = [d["throw"], ["CA"], ["S4", "S4"]]
    means, priors = [0.9, 0.5, 0.49], [0.0, 0.0, 0.0]
    calls = []
    real = module.forced_lead
    monkeypatch.setattr(module, "forced_lead", lambda *a, **k: calls.append(1) or real(*a, **k))
    bot = guard_bot()
    winner, played = select(bot, rnd, d, worlds, exact_stage=True, admitted=admitted,
                            means=means, priors=priors)
    record = bot._doomed_throw_record()
    assert (winner, played) == (0, d["throw"]) and calls == []
    assert record["doomed_throw_reselect_applied"] is False
    assert record["doomed_throw_reselect_doomed_candidates"] == 0
    assert record["doomed_throw_reselect_exact_floor_excluded"] == 2
    # dtr spends the test (64 worlds) and re-selects to CA
    dtr = guard_bot(on=False)
    winner, played = select(dtr, rnd, d, worlds, exact_stage=True, admitted=admitted,
                            means=means, priors=priors)
    assert (winner, played) == (1, ["CA"]) and len(calls) == 64


@pytest.mark.parametrize("rules", [{"tiebreak_points": False}, {"lead_tiebreak_prior": True},
                                   {"tiebreak_points": True}], ids=["bare", "lp+tb", "tb"])
def test_a_kept_selection_keeps_the_first_runs_selection_records(rules):
    """Two doomed throws rank first and second; the single that ties them is
    the alias of the second, so the ballot at the floor empties after two
    masked runs and the first selection stands with ITS rule records."""
    d = DECISIONS["CJ"]
    rnd = yjqj(d["plays"])
    worlds = draw(rnd, 0)
    admitted = [["CA", "CJ", "CQ"], ["C3", "CJ"], ["CJ"], ["S5"]]
    means, priors = [0.5, 0.5, 0.5, 0.0], [0.0, 0.0, 0.0, 0.0]
    clean = served(doomed_throw_reselect=False, **EXACT, **{**DTR_RULES, **rules})
    clean._select(rnd, SEAT, admitted, np.asarray(means), worlds=worlds, priors=priors)
    bot = guard_bot(**rules)
    winner, played = select(bot, rnd, d, worlds, exact_stage=True, admitted=admitted,
                            means=means, priors=priors)
    record = bot._doomed_throw_record()
    assert (winner, played) == (0, admitted[0])
    assert record["doomed_throw_reselect_applied"] is False
    assert record["doomed_throw_reselect_doomed_candidates"] == 2
    assert record["doomed_throw_reselect_forced_excluded"] == 1
    assert record["doomed_throw_reselect_fallback_forced"] is False
    assert bot._tiebreak == clean._tiebreak and bot._lead_tiebreak == clean._lead_tiebreak


def test_budget_expiry_abandons_the_guarded_reselect_as_dtr():
    d = DECISIONS["SJ"]
    rnd = yjqj(d["plays"])
    worlds = draw(rnd, 0)
    admitted = [d["throw"], ["CA"], ["S4", "S4"]]
    means, priors = [0.9, 0.9, 0.49], [0.0, 0.0, 0.0]
    # no points rule: the throw's doomed test makes checks 1-4, the publish the 5th
    bot = guard_bot(tiebreak_points=False)
    winner, played = select(bot, rnd, d, worlds, exact_stage=True, admitted=admitted,
                            means=means, priors=priors, check_budget=Expire(5))
    record = bot._doomed_throw_record()
    assert (winner, played) == (0, d["throw"])
    assert record["doomed_throw_reselect_abandoned"] == "budget"
    assert record["doomed_throw_reselect_applied"] is False
    bot = guard_bot(tiebreak_points=False)
    winner, played = select(bot, rnd, d, worlds, exact_stage=True, admitted=admitted,
                            means=means, priors=priors, check_budget=Expire(6))
    assert (winner, played) == (1, ["CA"])
    assert bot._doomed_throw_record()["doomed_throw_reselect_applied"] is True


def test_the_all_excluded_fallback_is_unchanged():
    d = DECISIONS["SJ"]
    rnd = yjqj(d["plays"])
    worlds = draw(rnd, 0)
    admitted = [["S4", "S4", "SJ"], ["SJ"]]
    for on in (False, True):
        bot = guard_bot(on=on)
        winner, played = select(bot, rnd, d, worlds, exact_stage=True, admitted=admitted,
                                means=[0.5, 0.5], priors=[0.0, 0.0])
        record = bot._doomed_throw_record()
        assert winner == 0 and played == d["played"]
        assert record["doomed_throw_reselect_fallback_forced"] is True
        assert record["doomed_throw_reselect_applied"] is False


# ------------------------------------------------- (b) the served decision at an endgame root

THROW = ["D6", "LJ"]          # root(2): seat 3 holds LJ D6; the ballot is D6, LJ and D6 LJ
#: exact means: the throw best; the admission-first alias D6 is set under it so the
#: exact argmax is the throw (a real alias ties it and wins the argmax by order,
#: in which case nothing is doomed and no re-select runs), LJ a level under that
EXACT_MEANS = {"D6 LJ": 1.5, "D6": 1.0, "LJ": 0.5}
#: base means: the throw best, so the base pass selects it and re-selects to LJ
BASE_MEANS = {"D6 LJ": 0.2, "D6": 0.0, "LJ": 0.1}


def by_cards(table, default=0.0):
    """Means keyed by sorted cards text, in the ballot's own order."""
    if callable(table):
        return table
    return lambda actions: [table.get(" ".join(sorted(a)), default) for a in actions]


def mean_of(rec, cards):
    pos = [sorted(a) for a in rec["admitted"]].index(sorted(cards))
    return rec["value_means"][pos]


def endgame_bot(monkeypatch, on, exact_means=EXACT_MEANS, base_means=BASE_MEANS, abandon=False,
                deep=0, doomed=None, alias_refill=False):
    """A served bot at the xmtj endgame root with controlled base and exact
    means (by cards, or a function of the ballot) and a controlled doomed
    verdict: every multi-card lead is doomed with its first card forced."""
    exact_means, base_means = by_cards(exact_means), by_cards(base_means)
    cards = 6 if deep else 2
    rnd = root(cards)
    config = dict(worlds=2, candidates=8, cap=4000, doomed_throw_reselect=True,
                  doomed_throw_reselect_exact_guard=on, exact_lead_endgame=True,
                  exact_deep_cards=deep, lead_alias_refill=alias_refill)
    bot = pv.PVSearchBot(predict, evaluator=ZeroEvaluator(), version=2,
                         config=pv.PVSearchConfig(checkpoint_sha256="f" * 64, **config),
                         checkpoint="/dev/null", seed=7)
    bot.scores = lambda rnd, seat, actions, worlds: np.tile(
        np.asarray([-float(i) for i in range(len(actions))]), (len(worlds), 1))
    doomed = doomed or (lambda action: [action[0]] if len(action) > 1 else None)
    monkeypatch.setattr(bot, "_doomed_component",
                        lambda rnd, seat, action, worlds, check_budget=None: doomed(list(action)))
    monkeypatch.setattr(bot, "_value_means", lambda rnd, seat, actions, worlds, check_budget=None:
                        (np.asarray(base_means(actions), dtype=np.float64), 1))

    def exact_fn(rnd, seat, admitted, worlds, leaf_fn, guard, **kw):
        if abandon:
            raise RuntimeError("partial exact pass")
        return (np.asarray(exact_means(admitted), dtype=np.float64),
                dict(worlds_completed=len(worlds), nodes=3, cache_hits=0))
    monkeypatch.setattr(pv_exact_deep if deep else exact,
                        "exact_root_means" if deep else "exact_lead_means", exact_fn)
    return bot, rnd


def decide(bot, rnd):
    played = bot.decide_play(copy.deepcopy(rnd), rnd.turn)
    rec = bot.last_decision_record
    assert rec["played"] == played
    return played, rec


def test_root_ballot_is_the_documented_one(monkeypatch):
    bot, rnd = endgame_bot(monkeypatch, True)
    _, rec = decide(bot, rnd)
    assert sorted(sorted(a) for a in rec["admitted"]) == [["D6"], sorted(THROW), ["LJ"]]
    assert [mean_of(rec, c.split()) for c in ("D6 LJ", "D6", "LJ")] == [1.5, 1.0, 0.5]


@pytest.mark.parametrize("guard", [False, True])
@pytest.mark.parametrize("abandon", [False, True])
def test_alias_refill_preserves_exact_tail_ballot(monkeypatch, guard, abandon):
    from shengji.train import lead_alias_refill

    def forbidden(*args, **kwargs):
        pytest.fail("alias refill entered the exact-tail ballot")

    monkeypatch.setattr(lead_alias_refill, "refill_indices", forbidden)
    records = []
    for enabled in (False, True):
        bot, rnd = endgame_bot(monkeypatch, guard, deep=7, abandon=abandon,
                              alias_refill=enabled)
        _, record = decide(bot, rnd)
        records.append(record)
        assert not any(key.startswith("lead_alias_refill") for key in record)
    for key in ("admitted", "admitted_indices", "value_means", "played",
                "exact_lead_status", "doomed_throw_reselect_applied"):
        assert records[0][key] == records[1][key]


@pytest.mark.parametrize("on", [False, True])
def test_complete_exact_stage_keeps_its_choice_only_with_the_guard(monkeypatch, on):
    bot, rnd = endgame_bot(monkeypatch, on)
    played, rec = decide(bot, rnd)
    assert rec["exact_lead_status"] == "complete"
    assert mean_of(rec, THROW) == 1.5 and mean_of(rec, ["LJ"]) == 0.5
    sel = rec["admitted_indices"].index(rec["selected_index"])
    assert rec["admitted"][sel] == played
    if on:
        assert sorted(played) == sorted(THROW)
        assert rec["doomed_throw_reselect_applied"] is False
        assert rec["doomed_throw_reselect_exact_guarded"] is True
        assert rec["doomed_throw_reselect_exact_floor_excluded"] == 2
        assert rec["doomed_throw_reselect_doomed_candidates"] == 0   # the test was skipped
        # the base pass selected the throw and its unguarded re-select moved to LJ
        assert rec["exact_lead_base_played"] == ["LJ"]
        assert rec["exact_lead_change_kind"] == "higher"
    else:
        # dtr: the exact-best throw is dropped for LJ, 1.0 exact levels lower
        assert played == ["LJ"]
        assert rec["doomed_throw_reselect_applied"] is True
        assert rec["doomed_throw_reselect_from"] == " ".join(THROW)
        assert not GUARD_KEYS & set(rec)
        # the base pass re-selected to LJ too, so the exact stage changed nothing
        assert rec["exact_lead_base_played"] == ["LJ"]
        assert rec["exact_lead_change_kind"] == "unchanged"


def test_complete_deep_exact_stage_keeps_its_choice(monkeypatch):
    """The ``ed<n>`` path (release 46 is ``ed7``) runs the same guarded selection."""
    def exact_means(admitted):      # every multi-card lead at 2.0, singles at 0.0
        return [2.0 if len(a) > 1 else 0.0 for a in admitted]

    def base_means(actions):
        return [1.0 if len(a) > 1 else 0.0 for a in actions]
    out = {}
    for on in (False, True):
        bot, rnd = endgame_bot(monkeypatch, on, exact_means, base_means, deep=6)
        played, rec = decide(bot, rnd)
        assert rec["exact_lead_status"] == "complete"
        out[on] = (played, rec)
    played, rec = out[True]
    assert len(played) > 1 and rec["doomed_throw_reselect_applied"] is False
    assert rec["doomed_throw_reselect_exact_guarded"] is True
    sel = rec["admitted_indices"].index(rec["selected_index"])
    assert rec["value_means"][sel] == 2.0
    played, rec = out[False]
    assert len(played) == 1 and rec["doomed_throw_reselect_applied"] is True


def test_abandoned_exact_stage_reselects_as_dtr(monkeypatch):
    for on in (False, True):
        bot, rnd = endgame_bot(monkeypatch, on, abandon=True)
        played, rec = decide(bot, rnd)
        assert rec["exact_lead_status"] == "abandoned"
        assert rec["exact_lead_abandon_error"] == "RuntimeError"
        # the base pass selected the throw (0.2) and its re-select moved to LJ
        assert played == ["LJ"] and rec["doomed_throw_reselect_applied"] is True
        assert rec["doomed_throw_reselect_from"] == " ".join(THROW)
        assert mean_of(rec, THROW) == 0.2 and mean_of(rec, ["LJ"]) == 0.1
        if on:
            assert rec["doomed_throw_reselect_exact_guarded"] is False
            assert rec["doomed_throw_reselect_exact_floor_excluded"] == 0


def test_ineligible_lead_reselects_as_dtr(monkeypatch):
    """root(5): five cards exceed the exact lead's four, so no exact stage runs."""
    def base_means(actions):
        return [1.0 if len(a) > 1 else 0.0 for a in actions]
    out = {}
    for on in (False, True):
        bot, _ = endgame_bot(monkeypatch, on, None, base_means)
        rnd = root(5)
        played, rec = decide(bot, rnd)
        assert rec["exact_lead_status"] == "ineligible"
        assert played == ["SA"] and rec["doomed_throw_reselect_applied"] is True
        out[on] = {k: v for k, v in _comparable(rec).items() if k not in GUARD_KEYS}
    assert out[False] == out[True]


# ------------------------------------------------- (c) flag off: exactly dtr

def test_flag_off_is_the_dtr_bot():
    off = guard_bot(on=False)
    dtr = served(doomed_throw_reselect=True, **EXACT, **DTR_RULES)
    assert off.doomed_throw_reselect_exact_guard is False
    assert "doomed_throw_reselect_exact_guard" not in vars(off)       # class-level off, as dtr's bot
    assert set(vars(off)) == set(vars(dtr)) and off.config == dtr.config
    assert PolicyValueBot.doomed_throw_reselect_exact_guard is False
    assert module.DOOMED_THROW_RESELECT_EXACT_GUARD_DEFAULTS == {"doomed_throw_reselect_exact_guard": False}
    on = guard_bot()
    assert vars(on)["doomed_throw_reselect_exact_guard"] is True


def _comparable(record):
    return {k: v for k, v in record.items() if not k.endswith("seconds")}


def test_flag_off_and_on_over_a_seeded_round_differ_only_on_complete_exact_reselects():
    """Paired bots on one trajectory (dtr's): the flag-off bot is dtr decision
    for decision; the flag-on bot differs only where a complete exact stage
    re-selected, and there its exact mean is never below dtr's first selection."""
    evaluator = HashNoiseEvaluator()
    decisions = complete = guarded = 0
    for seed in range(707001, 707004):
        rnd = _fresh_round(seed)
        dtr = [served(evaluator, worlds=8, seed=100 + s, doomed_throw_reselect=True, **EXACT,
                      **DTR_RULES) for s in range(4)]
        off = [guard_bot(evaluator, worlds=8, seed=100 + s, on=False) for s in range(4)]
        on = [guard_bot(evaluator, worlds=8, seed=100 + s) for s in range(4)]
        for bot in dtr + off + on:
            bot.scores = throw_loving_scores
        while rnd.phase == "play":
            seat = rnd.turn
            state = dtr[seat].sampler.rng.getstate()
            off[seat].sampler.rng.setstate(state)
            on[seat].sampler.rng.setstate(state)
            a = dtr[seat].decide_play(copy.deepcopy(rnd), seat)
            b = off[seat].decide_play(copy.deepcopy(rnd), seat)
            c = on[seat].decide_play(copy.deepcopy(rnd), seat)
            ra, rb, rc = (x[seat].last_decision_record for x in (dtr, off, on))
            decisions += 1
            assert a == b and _comparable(ra) == _comparable(rb)
            assert not GUARD_KEYS & set(rb)
            if "doomed_throw_reselect_applied" in rc:
                assert GUARD_KEYS <= set(rc)
            stripped = {k: v for k, v in _comparable(rc).items() if k not in GUARD_KEYS}
            if ra.get("exact_lead_status") == "complete":
                complete += 1
            if ra.get("exact_lead_status") == "complete" and ra.get("doomed_throw_reselect_applied"):
                guarded += 1
                first = ra["admitted_indices"].index(ra["selected_index"])
                mine = rc["admitted_indices"].index(rc["selected_index"])
                assert rc["value_means"] == ra["value_means"]
                assert rc["value_means"][mine] >= ra["value_means"][first]
                assert rc["doomed_throw_reselect_exact_guarded"] is True
            else:
                assert c == a and stripped == _comparable(ra)
            rnd.play(seat, a)
    print(f"\ndtrx parity: decisions={decisions} complete_exact={complete} "
          f"dtr_reselected_on_complete={guarded}")
    assert decisions >= 70 and complete > 0


# ------------------------------------------------- (d) env, name, digest, refusals

def test_release46_rule_name_unchanged_when_off_and_dtrx_token_after_dtr(production_package):
    assert names(R46_ENV) == [R46_NAME]
    for raw in ("0", ""):
        assert names({**R46_ENV, FLAG: raw}) == [R46_NAME]
    assert names(DTRX_ENV) == [DTRX_NAME]
    assert "-la-dtr-dtrx-vd-" in DTRX_NAME and "-la-dtr-vd-" in R46_NAME and "-la-dtr-vd-" in RELEASE46
    assert DTRX_NAME.split("-r")[0] == R46_NAME.split("-r")[0].replace("-dtr-", "-dtr-dtrx-")
    tokens = [t for _, t in pv.RULE_TOKENS]
    assert tokens.index("dtrx") == tokens.index("dtr") + 1
    assert pv.RULE_FLAGS["DOOMED_THROW_RESELECT_EXACT_GUARD"] == "doomed_throw_reselect_exact_guard"


def test_payload_carries_the_rule_only_when_on():
    base = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                             doomed_throw_reselect=True, exact_lead_endgame=True)
    on = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                           doomed_throw_reselect=True, exact_lead_endgame=True,
                           doomed_throw_reselect_exact_guard=True)
    off_payload = pv.recipe_payload(base)
    assert "doomed_throw_reselect_exact_guard" not in off_payload
    assert "doomed_throw_reselect_exact_rule" not in off_payload
    on_payload = pv.recipe_payload(on)
    assert on_payload["doomed_throw_reselect_exact_guard"] is True
    assert on_payload["doomed_throw_reselect_exact_rule"] == pv.DOOMED_THROW_RESELECT_EXACT_RULE
    assert {k: v for k, v in on_payload.items()
            if k not in ("doomed_throw_reselect_exact_guard", "doomed_throw_reselect_exact_rule")} \
        == off_payload
    assert pv.recipe_digest(base) != pv.recipe_digest(on)


@pytest.mark.parametrize("missing", ["doomed_throw_reselect", "exact_lead_endgame"])
def test_the_guard_requires_the_reselect_and_the_exact_stage(missing):
    flags = {"doomed_throw_reselect": True, "exact_lead_endgame": True, missing: False}
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, doomed_throw_reselect_exact_guard=True,
                               **flags)
    with pytest.raises(pv.PVSearchPolicyError, match="requires"):
        pv.recipe_payload(config)
    with pytest.raises((pv.PVSearchPolicyError, ValueError), match="requires"):
        pv.PVSearchBot(predict, evaluator=ZeroEvaluator(), version=2, config=config,
                       checkpoint="/dev/null")
    with pytest.raises(ValueError, match="requires doomed_throw_reselect"):
        PolicyValueBot(predict, evaluator=ZeroEvaluator(), doomed_throw_reselect_exact_guard=True)


def test_env_flag_refuses_anything_but_0_or_1(production_package):
    for bad in ("2", "true", "yes", " 1"):
        with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
            pv.pv_env_recipe({**R46_ENV, FLAG: bad})
    assert "doomed_throw_reselect_exact_guard" not in pv.pv_env_recipe({**R46_ENV, FLAG: "0"})
    assert pv.pv_env_recipe(DTRX_ENV)["doomed_throw_reselect_exact_guard"] is True
    for without in (DTR_FLAG, "SHENGJI_PV_EXACT_LEAD_ENDGAME"):
        with pytest.raises(pv.PVSearchPolicyError, match="require"):
            names({k: v for k, v in DTRX_ENV.items() if k != without})


def test_bad_values_are_refused():
    with pytest.raises(ValueError, match="doomed_throw_reselect_exact_guard must be a bool"):
        PolicyValueBot(predict, evaluator=ZeroEvaluator(), doomed_throw_reselect=True,
                       doomed_throw_reselect_exact_guard=1)
    with pytest.raises(pv.PVSearchPolicyError, match="must be a bool"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, doomed_throw_reselect=True,
                                            exact_lead_endgame=True,
                                            doomed_throw_reselect_exact_guard="1"))


def test_exact_rule_string_is_pinned():
    assert pv.DOOMED_THROW_RESELECT_EXACT_RULE == "reselect-only-to-exact-mean-not-below-selected"
    assert hashlib.sha256(pv.DOOMED_THROW_RESELECT_EXACT_RULE.encode()).hexdigest()[:8] == \
        hashlib.sha256(b"reselect-only-to-exact-mean-not-below-selected").hexdigest()[:8]
