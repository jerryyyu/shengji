"""The OPTIONAL single small-joker lead exclusion of the pv-search bot
(``small_joker_guard``, ``SHENGJI_PV_SMALL_JOKER_GUARD``; board #707 S4, was A9).

Evidence (#676, https://github.com/jerryyyu/shengji/issues/676#issuecomment-5959697247,
ranked fix 3): production LJ leads won only 6/12 tricks, all six losses to the big
joker.  Rule: on a LEAD where the seat holds a small joker and >= 3 other trumps
while a big joker is outstanding (public play + own hand + own kitty only), the
single-LJ lead is dropped from the admission, slot 0 included.

Torch-free and package-free: real engine positions (the shared fixture deal with
the seats' hands re-dealt so the leader holds the cards each case needs), the
served wrapper's own sampler and admission, a stub policy that ranks the jokers
first and stub value heads that only read the leaf state.  Witnesses: (a) the rule
fires and the single LJ leaves the ballot and the play; (b) a slot-0 LJ is
replaced and the admission contract holds; (c) it must NOT fire with both big
jokers accounted for, < 3 other trumps, no LJ, or on a follow; (d) off == the
pre-rule admission over >= 200 self-play decisions; (e) name / env / digest;
(f) a saved panel without the field still binds.
"""
import copy
import random

import numpy as np
import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.cards import BJ, LJ, TRUMP
from shengji.engine.game import Game
from shengji.harvest.legal import enumerate_legal
from shengji.train import policy_value_search as module
from shengji.train import pv_search_policy as pv
from shengji.train.policy_value_search import PolicyValueBot, _cards_text, structure_key  # noqa: F401
from test_policy_world_search import state
from test_pv_admission_rules import PRODUCTION_ENV, PRODUCTION_SHA, ZeroEvaluator, names, predict, \
    production_package  # noqa: F401

#: release 38's four rules, as served
RELEASE38_RULES = dict(admission_diversity=True, refusal_constraints=True,
                       tiebreak_points=True, lead_anchor=True)
RULE_KEYS = {"small_joker_guard_active", "small_joker_guard_big_jokers_out",
             "small_joker_guard_other_trumps", "small_joker_guard_anchor_replaced"}


# ------------------------------------------------------- fixtures: real engine positions

def _is_trump(rnd, card):
    return rnd.ordering.eff_suit(card) == TRUMP


def redeal(rnd, seat, lj=1, bj=0, other_trumps=4):
    """Re-deal the four hands in place (the same cards, the same hand sizes, the
    kitty untouched) so ``seat`` holds ``lj`` small jokers, ``bj`` big jokers and
    exactly ``other_trumps`` trumps besides its small jokers (big jokers included
    in that count), the rest plain; the other seats get the remaining cards round
    robin."""
    pool = [c for s in range(4) for c in rnd.hands[s]]
    size = len(rnd.hands[seat])
    jokers = [LJ] * lj + [BJ] * bj
    for c in jokers:
        pool.remove(c)
    plain_trumps = [c for c in pool if _is_trump(rnd, c) and c not in (LJ, BJ)]
    extra = plain_trumps[:other_trumps - bj]
    assert len(extra) == other_trumps - bj
    for c in extra:
        pool.remove(c)
    side = [c for c in pool if not _is_trump(rnd, c)]
    fill = side[:size - len(jokers) - len(extra)]
    for c in fill:
        pool.remove(c)
    hand = jokers + extra + fill
    assert len(hand) == size
    others = [s for s in range(4) if s != seat]
    sizes = {s: len(rnd.hands[s]) for s in others}
    rnd.hands[seat] = hand
    dealt = {s: [] for s in others}
    turn = 0
    for c in pool:
        while len(dealt[others[turn % 3]]) >= sizes[others[turn % 3]]:
            turn += 1
        dealt[others[turn % 3]].append(c)
        turn += 1
    for s in others:
        assert len(dealt[s]) == sizes[s]
        rnd.hands[s] = dealt[s]


def lead_position(lj=1, bj=0, other_trumps=4):
    """The shared fixture round at its first lead, re-dealt (`redeal`) for the leader."""
    rnd = state()
    seat = rnd.turn
    assert module.leading(rnd)
    redeal(rnd, seat, lj=lj, bj=bj, other_trumps=other_trumps)
    return rnd, seat


def after_big_joker_trick(bj):
    """The leader holds ``bj`` big jokers, an LJ and four other plain trumps; it
    leads its big joker(s), the table follows heuristically, and it leads again."""
    rnd, seat = lead_position(lj=1, bj=bj, other_trumps=4 + bj)
    rnd.play(seat, [BJ] * bj)
    h = HeuristicBot()
    while rnd.trick.plays:
        rnd.play(rnd.turn, h.decide_play(rnd, rnd.turn))
    assert rnd.turn == seat and module.leading(rnd)
    return rnd, seat


def follow_with_lj():
    """A FOLLOW where the follower holds LJ and four other trumps and no big
    joker: the leader opens with a plain single."""
    rnd = state()
    leader = rnd.turn
    follower = (leader + 1) % 4
    redeal(rnd, follower, lj=1, bj=0, other_trumps=4)
    lead = next(c for c in rnd.hands[leader] if not _is_trump(rnd, c))
    rnd.play(leader, [lead])
    assert rnd.turn == follower and not module.leading(rnd)
    return rnd, follower


def joker_first_scores(rnd, seat, actions, worlds):
    """A stub policy: the single LJ first, then the enumeration order."""
    prefs = np.array([-float(i) for i in range(len(actions))])
    for i, action in enumerate(actions):
        if list(action) == [LJ]:
            prefs[i] = 100.0
    return np.tile(prefs, (len(worlds), 1))


class LJLeafEvaluator:
    """A stub value head that reads only the leaf STATE: 1 when the root seat
    led the single LJ in the resolved trick, plus a small term in its points."""
    backend = "numpy"
    max_batch = 128

    def __init__(self, seat):
        self.seat = seat

    def score(self, leaves, seat):
        out = []
        for leaf in leaves:
            trick = leaf.last_trick
            mine = next(p.cards for p in trick.plays if p.seat == self.seat)
            out.append((1.0 if list(mine) == [LJ] else 0.0) + 0.001 * trick.points)
        return np.asarray(out, dtype=np.float64)


class PointsEvaluator:
    """Deterministic and state-only: the resolved trick's points signed for the
    root team, plus a small term in the number of cards the root seat put down."""
    backend = "numpy"
    max_batch = 128

    def score(self, leaves, seat):
        out = []
        for leaf in leaves:
            trick = leaf.last_trick
            ours = leaf.is_attacker(trick.winner) == leaf.is_attacker(seat)
            mine = next((p.cards for p in trick.plays if p.seat == seat), [])
            out.append((trick.points if ours else -trick.points) / 40.0 + 0.001 * len(mine))
        return np.asarray(out, dtype=np.float64)


def served(evaluator, worlds=8, seed=17, **rules):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=worlds, candidates=8,
                               cap=4000, batch_size=128, **rules)
    return pv.PVSearchBot(predict, evaluator=evaluator, version=2, config=config,
                          checkpoint="/dev/null", seed=seed)


def decide(bot, rnd, seat, scores=joker_first_scores):
    if scores is not None:
        bot.scores = scores
    played = bot.decide_play(copy.deepcopy(rnd), seat)
    return played, bot.last_decision_record


def both(rnd, seat, **kw):
    off = decide(served(LJLeafEvaluator(seat), **RELEASE38_RULES), rnd, seat, **kw)
    on = decide(served(LJLeafEvaluator(seat), small_joker_guard=True, **RELEASE38_RULES),
                rnd, seat, **kw)
    return off, on


# ------------------------------------------------------- the fixtures are what they claim

def test_fixture_positions():
    rnd, seat = lead_position()
    hand = rnd.hands[seat]
    assert hand.count(LJ) == 1 and BJ not in hand
    assert sum(_is_trump(rnd, c) for c in hand) - 1 == 4
    assert module.big_jokers_outstanding(rnd, seat) == 2
    assert [LJ] in [list(a) for a in enumerate_legal(rnd, seat, cap=4000).actions]
    rnd, seat = after_big_joker_trick(2)
    assert module.big_jokers_outstanding(rnd, seat) == 0
    rnd, seat = after_big_joker_trick(1)
    assert module.big_jokers_outstanding(rnd, seat) == 1
    rnd, seat = follow_with_lj()
    assert LJ in rnd.hands[seat] and sum(_is_trump(rnd, c) for c in rnd.hands[seat]) >= 4


def test_outstanding_reads_only_public_play_and_own_holdings():
    rnd, seat = lead_position(lj=1, bj=1, other_trumps=4)
    assert module.big_jokers_outstanding(rnd, seat) == 1
    # moving the other big joker between OTHER hands changes nothing
    holder = next(s for s in range(4) if BJ in rnd.hands[s] and s != seat)
    target = next(s for s in range(4) if s not in (seat, holder))
    swap = rnd.hands[target][0]
    rnd.hands[holder].remove(BJ)
    rnd.hands[holder].append(swap)
    rnd.hands[target].remove(swap)
    rnd.hands[target].append(BJ)
    assert module.big_jokers_outstanding(rnd, seat) == 1
    # a big joker in the banker's own kitty is accounted for -- by the banker only
    rnd2, seat2 = lead_position(lj=1, bj=0, other_trumps=4)
    assert rnd2.banker == seat2
    rnd2.buried = list(rnd2.buried[:-1]) + [BJ]
    assert module.big_jokers_outstanding(rnd2, seat2) == 1
    assert module.big_jokers_outstanding(rnd2, (seat2 + 1) % 4) == 2 - rnd2.hands[(seat2 + 1) % 4].count(BJ)


# ------------------------------------------------------- (a) the rule fires

@pytest.mark.parametrize("case", ["both-out", "one-played-one-out", "holds-one-bj"])
def test_rule_drops_the_single_small_joker_lead(case):
    rnd, seat = {"both-out": lambda: lead_position(),
                 "one-played-one-out": lambda: after_big_joker_trick(1),
                 "holds-one-bj": lambda: lead_position(lj=1, bj=1, other_trumps=4)}[case]()
    (off_played, off), (on_played, on) = both(rnd, seat)
    assert off_played == [LJ]
    assert [LJ] in off["admitted"]
    assert on_played != [LJ] and [LJ] not in on["admitted"]
    assert on["schema"] == pv.RECORD_SCHEMA and on["work_complete"] is True
    # K unchanged: the policy back-fills the slot
    assert len(on["admitted"]) == len(off["admitted"])
    assert on["small_joker_guard_active"] is True
    assert on["small_joker_guard_big_jokers_out"] == {"both-out": 2, "one-played-one-out": 1,
                                                       "holds-one-bj": 1}[case]
    assert on["small_joker_guard_other_trumps"] >= 3
    assert on["small_joker_guard_anchor_replaced"] is False
    assert RULE_KEYS <= set(on) and not RULE_KEYS & set(off)
    assert all(type(on[k]) in (bool, int) for k in RULE_KEYS)    # scalars only
    # multi-card leads holding an LJ are untouched
    rnd2, seat2 = lead_position(lj=2, other_trumps=4)
    (_, off2), (_, on2) = both(rnd2, seat2)
    assert [LJ, LJ] in on2["admitted"] or [LJ, LJ] not in off2["admitted"]


def test_harness_bot_applies_the_same_rule():
    rnd, seat = lead_position()
    out = {}
    for flag in (False, True):
        bot = PolicyValueBot(predict, evaluator=LJLeafEvaluator(seat), worlds=8, candidates=8,
                             cap=4000, seed=17, small_joker_guard=flag, admission_diversity=True,
                             tiebreak_points=True, lead_anchor=True)
        out[flag] = decide(bot, rnd, seat)
    assert out[False][0] == [LJ] and out[True][0] != [LJ]
    assert out[True][1]["small_joker_guard_active"] is True


# ------------------------------------------------------- (b) slot 0

def test_slot0_small_joker_is_replaced_and_the_contract_holds(monkeypatch):
    rnd, seat = lead_position()
    original = HeuristicBot.decide_play

    def lj_anchor(self, rnd_, seat_):
        if module.leading(rnd_) and LJ in rnd_.hands[seat_]:
            return [LJ]
        return original(self, rnd_, seat_)
    monkeypatch.setattr(HeuristicBot, "decide_play", lj_anchor)
    (off_played, off), (on_played, on) = both(rnd, seat)
    assert off["admitted"][0] == [LJ] and off_played == [LJ]
    assert on["schema"] == pv.RECORD_SCHEMA          # no admission-contract fallback
    assert on["admitted"][0] != [LJ] and [LJ] not in on["admitted"] and on_played != [LJ]
    assert on["small_joker_guard_anchor_replaced"] is True
    assert on["small_joker_guard_anchor_to"] == _cards_text(on["admitted"][0])


# ------------------------------------------------------- (c) where it must not fire

def no_fire_cases():
    return {
        "both-bj-in-hand": lambda: lead_position(lj=1, bj=2, other_trumps=4),
        "both-bj-played": lambda: after_big_joker_trick(2),
        "two-other-trumps": lambda: lead_position(lj=1, bj=0, other_trumps=2),
        "no-small-joker": lambda: lead_position(lj=0, bj=0, other_trumps=4),
        "follow": follow_with_lj,
    }


@pytest.mark.parametrize("case", list(no_fire_cases()))
def test_rule_does_not_fire(case):
    rnd, seat = no_fire_cases()[case]()
    (off_played, off), (on_played, on) = both(rnd, seat)
    assert on_played == off_played
    for key in ("admitted", "admitted_indices", "value_means", "selected_index"):
        assert on[key] == off[key]
    assert on["small_joker_guard_active"] is False
    assert on["small_joker_guard_anchor_replaced"] is False
    if case in ("both-bj-in-hand", "two-other-trumps"):
        assert off_played == [LJ]      # the LJ was there to drop, and stays
    if case == "two-other-trumps":
        assert on["small_joker_guard_other_trumps"] == 2
    if case.startswith("both-bj"):
        assert on["small_joker_guard_big_jokers_out"] == 0


# ------------------------------------------------------- (d) off == before, over self-play

class LegacyServed(pv.PVSearchBot):
    """The served wrapper with the admission exactly as it was before the rule
    (verbatim copies of `PolicyValueBot._admit` / `_effective_anchor_key` /
    `_admission` / `_admission_record` at main 9763d686)."""

    def _admit(self, rnd, seat, actions, preferences, anchor_index):
        worlds, check_budget = self._admission_context
        ranked = sorted(range(len(actions)), key=lambda i: (-preferences[i], i))
        if self.lead_anchor:
            anchor_index = self._lead_anchor_index(rnd, seat, actions, preferences,
                                                   anchor_index, ranked)
        k, applied = self._admission_k(rnd, actions, preferences)
        self._adaptive = {'adaptive_k_applied': applied, 'k_used': int(k)}
        self._diversity_skipped = []
        self._forced_added, self._forced_detail = [], []
        if not self.admission_diversity:
            chosen = [anchor_index]
            chosen.extend(i for i in ranked if i != anchor_index)
            chosen = chosen[:k]
        else:
            chosen = self._admit_diverse(rnd, actions, ranked, anchor_index, k)
        if self.admit_forced_single:
            extras, detail = self._forced_extras(rnd, seat, actions, chosen, worlds,
                                                 check_budget=check_budget)
            self._forced_added, self._forced_detail = extras, detail
            chosen = list(chosen) + extras
        return chosen

    def _effective_anchor_key(self, anchor_key):
        if self.lead_anchor and self._lead_anchor is not None:
            return tuple(sorted(self._lead_anchor["lead_anchor_to"].split(" ")))
        return anchor_key

    def _admission(self, rnd, seat, actions, preferences, anchor_index, worlds,
                   check_budget=None):
        self._admission_context = (worlds, check_budget)
        self._lead_anchor = None
        try:
            return [int(i) for i in self._admit(rnd, seat, actions, preferences, anchor_index)]
        finally:
            self._admission_context = (None, None)

    def _admission_record(self):
        record = {}
        if self.admission_diversity:
            record["diversity_skipped"] = [int(i) for i in self._diversity_skipped]
        if self.admit_forced_single:
            record["forced_single_added"] = [int(i) for i in self._forced_added]
            record["forced_single_detail"] = list(self._forced_detail)
        if self.adaptive_k:
            record.update(self._adaptive)
        if self.lead_anchor and self._lead_anchor is not None:
            record.update(self._lead_anchor)
        return record


def _bot(cls, seat, rules, **flags):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=4, candidates=8, cap=4000,
                               batch_size=128, **rules, **flags)
    return cls(predict, evaluator=PointsEvaluator(), version=2, config=config,
               checkpoint="/dev/null", seed=100 + seat)


def _fresh_round(seed):
    rnd = Game(random.Random(seed)).start_round()
    h = HeuristicBot()
    while rnd.phase == 'deal':
        seat, _, _ = rnd.deal_next()
        c = h.decide_declare(rnd, seat)
        if c:
            rnd.declare(seat, c)
    for seat in range(4):
        c = h.decide_declare(rnd, seat, final=True)
        if c:
            rnd.declare(seat, c)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, h.decide_bury(rnd, rnd.banker))
    return rnd


def _strip(record):
    return {k: v for k, v in record.items() if k != "seconds"}


#: fixed self-play seeds; eight rounds give about 490 decisions
SELF_PLAY_SEEDS = tuple(range(707001, 707009))


@pytest.mark.parametrize("rules", [RELEASE38_RULES, {}], ids=["release38", "bare"])
def test_off_is_the_pre_rule_decision_over_self_play(rules):
    decisions = leads = active = changed = 0
    for seed in SELF_PLAY_SEEDS:
        rnd = _fresh_round(seed)
        off = [_bot(pv.PVSearchBot, s, rules) for s in range(4)]
        legacy = [_bot(LegacyServed, s, rules) for s in range(4)]
        on = [_bot(pv.PVSearchBot, s, rules, small_joker_guard=True) for s in range(4)]
        while rnd.phase == "play":
            seat = rnd.turn
            a = off[seat].decide_play(copy.deepcopy(rnd), seat)
            b = legacy[seat].decide_play(copy.deepcopy(rnd), seat)
            assert a == b
            assert _strip(off[seat].last_decision_record) == _strip(legacy[seat].last_decision_record)
            assert not RULE_KEYS & set(off[seat].last_decision_record)
            assert off[seat].sampler.rng.getstate() == legacy[seat].sampler.rng.getstate()
            # the counterfactual on-arm on the same position (census only)
            c = on[seat].decide_play(copy.deepcopy(rnd), seat)
            rec = on[seat].last_decision_record
            decisions += 1
            leads += bool(module.leading(rnd))
            active += bool(rec.get("small_joker_guard_active"))
            changed += c != a
            # keep the on-arm sampler in step with the trajectory it is shown
            on[seat].sampler.rng.setstate(off[seat].sampler.rng.getstate())
            rnd.play(seat, a)
    assert decisions >= 200
    # a firing rule only ever acts on leads
    assert active <= leads
    print(f"\nsmall_joker_guard census [{'release38' if rules else 'bare'}]: "
          f"decisions={decisions} leads={leads} active={active} played_changed={changed}")


# ------------------------------------------------------- (e) name / env / digest

RELEASE38_ENV = {**PRODUCTION_ENV, "SHENGJI_PV_ADMISSION_DIVERSITY": "1",
                 "SHENGJI_PV_REFUSAL_CONSTRAINTS": "1", "SHENGJI_PV_TIEBREAK_POINTS": "1",
                 "SHENGJI_PV_LEAD_ANCHOR": "1"}
RELEASE38_NAME = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-r7092480e-bury-hybrid-5517ddbd7457"


def test_release38_name_unchanged_when_off_and_sjg_when_on(production_package):
    assert names(RELEASE38_ENV) == [RELEASE38_NAME]
    assert names({**RELEASE38_ENV, "SHENGJI_PV_SMALL_JOKER_GUARD": "0"}) == [RELEASE38_NAME]
    assert names({**RELEASE38_ENV, "SHENGJI_PV_SMALL_JOKER_GUARD": ""}) == [RELEASE38_NAME]
    on, = names({**RELEASE38_ENV, "SHENGJI_PV_SMALL_JOKER_GUARD": "1"})
    assert on.startswith("pv-search-491ee4bf-w64-k8-div-rc-tb-la-sjg-r") and "-bury-hybrid-" in on
    assert on != RELEASE38_NAME
    every, = names({**RELEASE38_ENV, "SHENGJI_PV_DOOMED_THROW_SWAP": "1",
                    "SHENGJI_PV_SMALL_JOKER_GUARD": "1"})
    assert every.startswith("pv-search-491ee4bf-w64-k8-div-rc-tb-la-dts-sjg-r")
    config = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0)
    assert pv.recipe_digest(config) == "4a09aef5"
    assert "small_joker_guard" not in pv.recipe_payload(config)
    guard = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                              small_joker_guard=True)
    assert pv.recipe_payload(guard)["small_joker_guard"] is True
    assert pv.recipe_digest(guard) != pv.recipe_digest(config)
    assert pv.RULE_FLAGS["SMALL_JOKER_GUARD"] == "small_joker_guard"
    assert module.SMALL_JOKER_GUARD_DEFAULTS["small_joker_guard"] is False


@pytest.mark.parametrize("bad", ["2", "true", "yes", "on", " 1"])
def test_env_flag_refuses_anything_but_0_or_1(bad):
    with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
        pv.pv_env_recipe({**PRODUCTION_ENV, "SHENGJI_PV_SMALL_JOKER_GUARD": bad})
    assert "small_joker_guard" not in pv.pv_env_recipe({**PRODUCTION_ENV,
                                                        "SHENGJI_PV_SMALL_JOKER_GUARD": "0"})
    assert pv.pv_env_recipe({**PRODUCTION_ENV,
                             "SHENGJI_PV_SMALL_JOKER_GUARD": "1"})["small_joker_guard"] is True


def test_bad_values_are_refused():
    with pytest.raises(ValueError, match="small_joker_guard must be a bool"):
        PolicyValueBot(predict, evaluator=ZeroEvaluator(), small_joker_guard=1)
    with pytest.raises(pv.PVSearchPolicyError, match="must be a bool"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, small_joker_guard="1"))


# ------------------------------------------------------- (f) saved panels predating the field

@pytest.mark.parametrize("drop", [("small_joker_guard",), ("doomed_throw_swap", "small_joker_guard")])
def test_saved_panel_without_the_field_still_binds(drop):
    from test_panel_rank_root import inputs
    from shengji.eval import panel_rank_root
    panel, fixture, bot = inputs()
    for field in drop:
        del panel['config'][field]
    root = panel_rank_root.bind_panel_rank_root(panel, fixture, bot)
    assert root.turn == fixture.seat


@pytest.mark.parametrize("damage", ["config_true", "bot_true"])
def test_saved_panel_without_the_field_refuses_a_guard_that_is_on(damage):
    from dataclasses import replace
    from test_panel_rank_root import inputs
    from shengji.eval import panel_rank_root
    panel, fixture, bot = inputs()
    del panel['config']['small_joker_guard']
    if damage == "config_true":
        bot.config = replace(bot.config, small_joker_guard=True)
    else:
        bot.small_joker_guard = True
    with pytest.raises(ValueError, match="config mismatch"):
        panel_rank_root.bind_panel_rank_root(panel, fixture, bot)
