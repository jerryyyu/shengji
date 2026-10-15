"""The uniform world proposal and the bury-rule kitty (`ai.uniform_worlds`;
pv-search rules ``world_uniform`` / ``kitty_bury_rule``, tokens ``-wu`` / ``-kb``).

Witnesses: on states small enough to enumerate every physical deal, the
proposal's per-card receiver frequencies match the exact uniform law under the
same constraints (a banker root and a non-banker root with a hidden kitty); the
proposal keeps the seam's contract (sizes, the unseen pool only, voids, draw
constraints, pins, caps, ``mem`` untouched, the sampler's own rng); the kitty
rule is the served bury's incumbent (`HeuristicBot.decide_bury`) and its worlds
keep the banker's constraints; the try budget is bounded and its shortfall drawn
by the fallback; off, every name, digest and world is unchanged; the flags'
requirements, tokens and record fields; the served bury's model worlds come
from the proposal when the rule is on; and the real package's serving path.
"""
import asyncio
import copy
import itertools
import random
import tomllib
from collections import Counter
from pathlib import Path

import pytest

from shengji.ai import history_legality as HL
from shengji.ai import uniform_worlds as UW
from shengji.ai.heuristic import HeuristicBot
from shengji.ai.mcbot import MCBot
from shengji.ai.memory import Memory
from shengji.engine.cards import SUITS, TRUMP
from shengji.engine.combos import decompose
from shengji.engine.game import Game
from shengji.train import bury_wide_value as bwv
from shengji.train import pv_search_policy as pv
from test_cwv_bury_wide_value import served_bury
from test_cwv_leaf_policy_first_trick import bury_state, jumping_clock  # noqa: F401
from test_encoder_round_compat import pinned_production_package  # noqa: F401
from test_refusal_constraints import (PRODUCTION_ENV, PRODUCTION_NAME, PRODUCTION_SHA,
                                      ZeroEvaluator, predict)
from test_world_history_legal import RELEASE45_ENV, RELEASE45_NAME, served, started

HISTORY = dict(world_history_legal=True, world_history_draw=True)
ENV_HISTORY = {"SHENGJI_PV_WORLD_HISTORY_LEGAL": "1", "SHENGJI_PV_WORLD_HISTORY_DRAW": "1"}
ENV_WU = {**ENV_HISTORY, "SHENGJI_PV_WORLD_UNIFORM": "1"}
ENV_KB = {**ENV_WU, "SHENGJI_PV_KITTY_BURY_RULE": "1"}
#: release 45 with the history rule and its draw form (S27, S27b), and with this
#: module's rules on top
RELEASE45_WHL_WHD = ("pv-search-491ee4bf-w64-k8-div-rc-whl-whd-tb-la-dtr-vd-r47e8901a"
                     "-bury-hybrid-bwv-85c0661e5790")
RELEASE45_WU = ("pv-search-491ee4bf-w64-k8-div-rc-whl-whd-wu-tb-la-dtr-vd-ra24d07b7"
                "-bury-hybrid-bwv-13a6fc08dbfb")
RELEASE45_WU_KB = ("pv-search-491ee4bf-w64-k8-div-rc-whl-whd-wu-kb-tb-la-dtr-vd-rd065b1b2"
                   "-bury-hybrid-bwv-9b72df9a92a4")
W = 16


# --------------------------------------------------------------- helpers

def states(n_games=8, every=3, min_trick=2):
    """Heuristic play states, some follow history in each."""
    h = HeuristicBot()
    out = []
    for game_seed in range(n_games):
        rnd, _ = started(game_seed)
        k = 0
        while rnd.phase == "play":
            if k % every == 0 and len(rnd.history) >= min_trick:
                out.append((copy.deepcopy(rnd), rnd.turn))
            rnd.play(rnd.turn, h.decide_play(rnd, rnd.turn))
            k += 1
    return out


def forbidden_of(rnd, seat):
    out = {s: set() for s in range(4)}
    for (s, _suit), codes in HL.draw_constraints(rnd, seat).items():
        out[s].update(codes)
    return out


def hand_ok(rnd, mem, forbidden, s, hand):
    """The constraints a seat's CURRENT hand must honour (the reference check)."""
    o = rnd.ordering
    if any(o.eff_suit(c) in mem.voids[s] or c in forbidden[s] for c in hand):
        return False
    for suit in set(mem.pair_cap[s]) | set(mem.run_cap[s]):
        cards = [c for c in hand if o.eff_suit(c) == suit]
        cap = mem.pair_cap[s].get(suit)
        if cap is not None and sum(v // 2 for v in Counter(cards).values()) > cap:
            return False
        run = mem.run_cap[s].get(suit)
        if run is not None and len(cards) >= 2 and decompose(cards, o).max_pair_run() > run:
            return False
    return True


def pins(rnd, seat, mem):
    """The declarer pins as `MCBot._sample_hands` places them."""
    sizes = {s: len(rnd.hands[s]) for s in range(4) if s != seat}
    pre = {s: Counter() for s in sizes}
    for code, (dseat, copies) in mem.known.items():
        if dseat in pre:
            pre[dseat][code] += min(copies, sizes[dseat] - sum(pre[dseat].values()))
    return pre


def exact_law(rnd, seat, kitty_rule=False):
    """Every physical deal of the unseen cards honouring the constraints, as
    ``{(receiver, code): expected copies}`` over whole hands (pins included;
    the kitty is receiver 'k').  With ``kitty_rule`` the banker's hand and the
    kitty are dealt as one receiver and split by the incumbent rule, and a deal
    whose rule kitty holds a trump or leaves the banker's hand breaking its
    constraints is not one."""
    o = rnd.ordering
    mem = Memory(rnd, seat, own_kitty=True)
    forbidden = forbidden_of(rnd, seat)
    pre = pins(rnd, seat, mem)
    b = rnd.banker
    others = [s for s in range(4) if s != seat]
    free = sorted((Counter(mem.unseen) - sum(pre.values(), Counter())).elements())
    sizes = [len(rnd.hands[s]) - sum(pre[s].values()) for s in others]
    if seat != b:
        others, sizes = others + ["k"], sizes + [len(rnd.buried)]
    if kitty_rule:
        union_size = sizes[others.index(b)] + sizes[-1]
        keep = [(r, z) for r, z in zip(others, sizes) if r not in (b, "k")]
        others = [r for r, _ in keep] + ["U"]
        sizes = [z for _, z in keep] + [union_size]
    played = sorted(mem.played_by[b].elements())
    counts = Counter()
    total = 0

    def rec(i, left, hands):
        nonlocal total
        if i == len(others):
            dealt = dict(zip(others, hands))
            if kitty_rule:
                union = list(pre[b].elements()) + dealt.pop("U")
                kitty = UW.heuristic_bury_kitty(union + played, union, o, len(rnd.buried))
                hand = list((Counter(union) - Counter(kitty)).elements())
                if any(o.eff_suit(c) == TRUMP for c in kitty) or not hand_ok(
                        rnd, mem, forbidden, b, hand):
                    return
                dealt[b], dealt["k"] = hand, kitty
            for r, hand in dealt.items():
                whole = hand if r == "k" or (kitty_rule and r == b) else \
                    hand + list(pre[r].elements())
                for c in whole:
                    counts[(r, c)] += 1
            total += 1
            return
        r = others[i]
        for idx in itertools.combinations(range(len(left)), sizes[i]):
            hand = [left[j] for j in idx]
            if r not in ("k", "U") and not hand_ok(rnd, mem, forbidden, r,
                                                   hand + list(pre[r].elements())):
                continue
            rest = [c for j, c in enumerate(left) if j not in idx]
            rec(i + 1, rest, hands + [hand])
    rec(0, free, [])
    return {key: v / total for key, v in counts.items()}, total


def enumerable(banker_root, cards_each, kitty_rule=False):
    """A heuristic state small enough to enumerate, with a constrained type
    (with ``kitty_rule``: a banker with a public void)."""
    h = HeuristicBot()
    for game_seed in range(80):
        rnd, _ = started(game_seed)
        while rnd.phase == "play":
            seat = rnd.turn
            if ((seat == rnd.banker) == banker_root and not rnd.trick.plays
                    and all(len(rnd.hands[s]) == cards_each for s in range(4))):
                mem = Memory(rnd, seat, own_kitty=True)
                p = UW.UniformProposal(MCBot(seed=1), n=8)
                p(rnd, seat, mem)
                if (p.stats["uniform_constrained_types"] and not p.stats["uniform_infeasible"]
                        and (not kitty_rule or mem.voids[rnd.banker])):
                    return copy.deepcopy(rnd), seat
            rnd.play(seat, h.decide_play(rnd, seat))
    raise AssertionError("no enumerable state found")


# ------------------------------------------------------------ exactness

@pytest.mark.parametrize("banker_root, cards_each, kitty_rule",
                         [(True, 4, False), (False, 1, False), (False, 2, True)])
def test_frequencies_match_the_exact_uniform_law(banker_root, cards_each, kitty_rule):
    rnd, seat = enumerable(banker_root, cards_each, kitty_rule)
    law, deals = exact_law(rnd, seat, kitty_rule)
    assert deals >= 10 and any(p < 1 for p in law.values())
    draws = 4000
    propose = UW.UniformProposal(MCBot(seed=3), n=draws, kitty_rule=kitty_rule)
    seen = Counter()
    for _ in range(draws):
        hands, buried = propose(rnd, seat, Memory(rnd, seat, own_kitty=True))
        for s, hand in hands.items():
            for c in hand:
                seen[(s, c)] += 1
        if seat != rnd.banker:
            for c in buried:
                seen[("k", c)] += 1
    record = propose.record()
    assert record["uniform_fallback_worlds"] == 0
    if kitty_rule:
        assert record["kitty_rule_fallback_worlds"] == 0 and record["kitty_rule_worlds"] == draws
    for key, p in law.items():
        assert abs(seen[key] / draws - p) < 0.035, (key, seen[key] / draws, p)
    assert not set(seen) - set(law)


# -------------------------------------------------------------- contract

def test_the_proposal_keeps_the_seam_contract():
    checked = 0
    for rnd, seat in states():
        mem = Memory(rnd, seat, own_kitty=True)
        before = (Counter(mem.unseen), copy.deepcopy(mem.voids), dict(mem.known),
                  copy.deepcopy(mem.pair_cap), copy.deepcopy(mem.run_cap))
        sampler = MCBot(seed=4)
        rng_before = sampler.rng.getstate()
        forbidden = forbidden_of(rnd, seat)
        constraints = HL.draw_constraints(rnd, seat)
        pre = pins(rnd, seat, mem)
        for kitty_rule in (False, True):
            propose = UW.UniformProposal(sampler, n=8, kitty_rule=kitty_rule,
                                         fallback=HL.constrained_draw(sampler, constraints))
            for _ in range(8):
                fallbacks = propose.stats["uniform_fallback_worlds"]
                hands, buried = propose(rnd, seat, mem)
                fell_back = propose.stats["uniform_fallback_worlds"] > fallbacks
                assert set(hands) == {s for s in range(4) if s != seat}
                assert all(len(hands[s]) == len(rnd.hands[s]) for s in hands)
                drawn = sum((Counter(h) for h in hands.values()), Counter())
                if seat == rnd.banker:
                    assert sorted(buried) == sorted(rnd.buried)
                    assert drawn == Counter(mem.unseen)
                else:
                    assert len(buried) == len(rnd.buried)
                    assert drawn + Counter(buried) == Counter(mem.unseen)
                MCBot(seed=0)._complete_determinized_hands(rnd, seat, hands, buried=buried)
                if fell_back:
                    continue
                for s, hand in hands.items():
                    assert hand_ok(rnd, mem, forbidden, s, hand)
                    assert not pre[s] - Counter(hand) or (kitty_rule and s == rnd.banker)
                checked += 1
            if not kitty_rule:
                assert propose.stats["uniform_fallback_worlds"] == 0
        assert sampler.rng.getstate() != rng_before
        assert (Counter(mem.unseen), mem.voids, dict(mem.known), mem.pair_cap,
                mem.run_cap) == before
    assert checked > 400


def test_a_banker_root_keeps_its_own_kitty_and_a_bury_root_deals_75_cards():
    rnd = bury_state(60)
    seat = rnd.banker
    worlds, attempts, stats = UW.sample_worlds_uniform(MCBot(seed=2), rnd, seat, 8)
    assert len(worlds) == 8 and attempts == 8 and stats["uniform_constrained_types"] == 0
    for hands, buried in worlds:
        assert buried == [] and hands[seat] == sorted(rnd.hands[seat])
        assert sum(len(hands[s]) for s in range(4) if s != seat) == 75


# ------------------------------------------------------------ kitty rule

def test_the_kitty_rule_is_the_served_incumbent():
    assert pv.PVSearchBuryBot._bury_points_mult is HeuristicBot._bury_points_mult
    assert pv.PVSearchBuryBot._bury_short_bonus is HeuristicBot._bury_short_bonus
    h = HeuristicBot()
    for index in range(60):
        rnd = bury_state(index)
        b = rnd.banker
        rnd.hands[b] = sorted(rnd.hands[b])
        expected = h.decide_bury(rnd, b)
        got = UW.heuristic_bury_kitty(rnd.hands[b], rnd.hands[b], rnd.ordering, 8)
        assert got == expected


def test_kitty_rule_worlds_keep_the_banker_constraints_and_bury_like_the_banker():
    trumps = {False: [], True: []}
    rule_worlds = 0
    for rnd, seat in states():
        if seat == rnd.banker:
            continue
        b = rnd.banker
        mem = Memory(rnd, seat, own_kitty=True)
        forbidden = forbidden_of(rnd, seat)
        played = sorted(mem.played_by[b].elements())
        for kitty_rule in (False, True):
            propose = UW.UniformProposal(MCBot(seed=6), n=8, kitty_rule=kitty_rule)
            for _ in range(8):
                fallbacks = propose.stats["uniform_fallback_worlds"]
                hands, buried = propose(rnd, seat, mem)
                if propose.stats["uniform_fallback_worlds"] > fallbacks:
                    continue
                trumps[kitty_rule].append(sum(rnd.ordering.eff_suit(c) == TRUMP for c in buried))
                if not kitty_rule:
                    continue
                union = hands[b] + list(buried)
                assert buried == UW.heuristic_bury_kitty(union + played, union, rnd.ordering, 8)
                assert hand_ok(rnd, mem, forbidden, b, hands[b])
                hand, kitty = UW.kitty_rule_split(rnd, mem, union, played, forbidden[b])
                assert kitty == buried and Counter(hand) == Counter(hands[b])
            if kitty_rule:
                rule_worlds += propose.stats["kitty_rule_worlds"]
    assert rule_worlds > 100
    mean = {k: sum(v) / len(v) for k, v in trumps.items()}
    assert mean[True] < 0.25 < 1.5 < mean[False]


# ------------------------------------------------------ budget, fallback

def test_the_try_budget_is_bounded_and_its_shortfall_is_the_fallback(monkeypatch):
    rnd, seat = states()[10]
    monkeypatch.setattr(UW.UniformProposal, "_try", lambda self, mem: None)
    bot = served(**HISTORY, world_uniform=True)
    worlds, _ = bot._worlds(rnd, seat)
    stats = bot._last_sampling
    assert len(worlds) == W
    assert stats["uniform_tries"] == W * UW.TRY_FACTOR
    assert stats["uniform_fallback_worlds"] >= W
    calls = []

    def check_budget():
        calls.append(1)
        if len(calls) > 3:
            raise pv.PVSearchBudgetExceeded("expired")
    with pytest.raises(pv.PVSearchBudgetExceeded):
        served(**HISTORY, world_uniform=True)._worlds(rnd, seat, check_budget)


def test_an_infeasible_state_draws_every_world_from_the_fallback():
    rnd, seat = states()[10]
    calls = []
    sampler = MCBot(seed=1)

    def fallback(r, s, m):
        calls.append(s)
        return sampler._sample_hands(r, s, m)
    propose = UW.UniformProposal(sampler, n=4, fallback=fallback)
    mem = Memory(rnd, seat, own_kitty=True)
    # every seat void in every suit: no card may go anywhere but the kitty
    blocked = copy.copy(mem)
    blocked.voids = {s: {TRUMP, *SUITS} for s in range(4)}
    for _ in range(4):
        propose(rnd, seat, blocked)
    assert propose.stats["uniform_infeasible"] == 1
    assert propose.stats["uniform_fallback_worlds"] == 4 and len(calls) == 4


# ---------------------------------------------------------- off == before

def test_rules_off_draw_the_history_worlds_unchanged(monkeypatch):
    rnd, seat = states()[10]
    expected = HL.sample_worlds_history_legal(MCBot(seed=7), rnd, seat, W, mem=Memory(
        rnd, seat, own_kitty=True), constrain=True)[0]

    def refuse(*a, **k):
        raise AssertionError("the proposal must not run while the rule is off")
    monkeypatch.setattr(UW, "UniformProposal", refuse)
    bot = served(**HISTORY)
    assert bot.world_uniform is False and bot.kitty_bury_rule is False
    assert bot._worlds(rnd, seat)[0] == expected
    assert not set(UW.FIELDS) & set(bot._last_sampling)
    bot.decide_play(copy.deepcopy(rnd), seat)
    assert not (set(UW.FIELDS) | set(UW.KITTY_FIELDS)) & set(bot.last_decision_record)


@pytest.fixture
def production_package(monkeypatch):
    import shengji.ai.cwv_policy as cwv
    monkeypatch.setattr(cwv, "checkpoint_id", lambda path: PRODUCTION_SHA[:8])


def names(env):
    return list(pv.pv_registry_entries(**pv.pv_env_recipe(env)))


def test_names_unchanged_off_pinned_on_and_in_token_order(production_package):
    assert names(PRODUCTION_ENV) == [PRODUCTION_NAME]
    assert names(RELEASE45_ENV) == [RELEASE45_NAME]
    off = {"SHENGJI_PV_WORLD_UNIFORM": "0", "SHENGJI_PV_KITTY_BURY_RULE": "0"}
    assert names({**RELEASE45_ENV, **off}) == [RELEASE45_NAME]
    assert names({**RELEASE45_ENV, **ENV_HISTORY, **off}) == [RELEASE45_WHL_WHD]
    assert names({**RELEASE45_ENV, **ENV_WU}) == [RELEASE45_WU]
    assert names({**RELEASE45_ENV, **ENV_KB}) == [RELEASE45_WU_KB]
    config = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0)
    assert pv.recipe_digest(config) == "4a09aef5"
    payload = pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, **HISTORY,
                                                  world_uniform=True, kitty_bury_rule=True))
    assert payload["world_uniform_try_factor"] == UW.TRY_FACTOR
    assert payload["kitty_bury_rule_model"] == pv.KITTY_BURY_RULE_MODEL


@pytest.mark.parametrize("rules, match", [
    (dict(world_uniform=True), "world_uniform requires"),
    (dict(world_history_legal=True, world_uniform=True), "world_uniform requires"),
    (dict(**HISTORY, kitty_bury_rule=True), "kitty_bury_rule requires"),
])
def test_requirements_are_refused(rules, match):
    with pytest.raises(pv.PVSearchPolicyError, match=match):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, **rules))
    with pytest.raises(pv.PVSearchPolicyError):
        served(**rules)


@pytest.mark.parametrize("flag", ["SHENGJI_PV_WORLD_UNIFORM", "SHENGJI_PV_KITTY_BURY_RULE"])
@pytest.mark.parametrize("bad", ["2", "true", " 1"])
def test_env_flags_refuse_anything_but_0_or_1(flag, bad):
    with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
        pv.pv_env_recipe({**PRODUCTION_ENV, **ENV_KB, flag: bad})


# ----------------------------------------------------------------- record

@pytest.mark.parametrize("kitty_rule", [False, True])
def test_decision_record_carries_the_proposal_fields(kitty_rule):
    rnd, seat = next((r, s) for r, s in states() if s != r.banker)
    bot = served(**HISTORY, world_uniform=True, kitty_bury_rule=kitty_rule)
    bot.decide_play(copy.deepcopy(rnd), seat)
    record = bot.last_decision_record
    assert set(UW.FIELDS) <= set(record)
    assert (set(UW.KITTY_FIELDS) <= set(record)) == kitty_rule
    constraints = HL.draw_constraints(rnd, seat)
    assert record["uniform_tries"] >= W
    assert record["uniform_draw_constraints"] == len(constraints)
    assert record["uniform_draw_forbidden"] == sum(sum(c.values()) for c in constraints.values())
    if kitty_rule:
        assert record["kitty_rule_worlds"] >= W - record["uniform_fallback_worlds"]


# ------------------------------------------------------- serving deadline

def constrained_attacker_state():
    """A state whose proposal builds count arrays, at a seat that is not the banker."""
    for rnd, seat in states():
        if seat == rnd.banker:
            continue
        p = UW.UniformProposal(MCBot(seed=1), n=4, kitty_rule=True)
        p(rnd, seat, Memory(rnd, seat, own_kitty=True))
        if p.stats["uniform_constrained_types"] and p.state.get("suffix"):
            return rnd, seat
    raise AssertionError("no state with count arrays")


def test_an_expired_deadline_at_entry_prepares_and_draws_nothing(monkeypatch):
    rnd, seat = constrained_attacker_state()

    def expired():
        raise pv.PVSearchBudgetExceeded("expired")

    def forbidden(*a, **k):
        pytest.fail("an expired proposal must not prepare, try or fall back")
    monkeypatch.setattr(UW.UniformProposal, "_prepare", forbidden)
    for kitty_rule in (False, True):
        sampler = MCBot(seed=2)
        before = sampler.rng.getstate()
        propose = UW.UniformProposal(sampler, n=4, kitty_rule=kitty_rule, fallback=forbidden,
                                     check_budget=expired)
        with pytest.raises(pv.PVSearchBudgetExceeded):
            propose(rnd, seat, Memory(rnd, seat, own_kitty=True))
        assert sampler.rng.getstate() == before


@pytest.mark.parametrize("stage", ["arrays", "prepared", "tries"])
@pytest.mark.parametrize("error", [pv.PVSearchBudgetExceeded, pv._AdaptiveWorldsExpired])
@pytest.mark.parametrize("kitty_rule", [False, True])
def test_an_expired_deadline_stops_the_served_play_draw(monkeypatch, stage, error, kitty_rule):
    """Through the served consumer (`PVSearchBot._worlds`): the deadline expires
    inside the count arrays, right after preparation, or after the first try;
    nothing further is tried, no fallback draws, and the expiry propagates."""
    rnd, seat = constrained_attacker_state()
    state = {"expired": False, "arrays": False}
    calls = Counter()
    real_prepare, real_arrays = UW.UniformProposal._prepare, UW.UniformProposal._count_arrays

    def check():
        if state["expired"] or (stage == "arrays" and state["arrays"]):
            raise error("expired")

    def prepare(self, *a, **k):
        calls["prepare"] += 1
        real_prepare(self, *a, **k)
        if stage == "prepared":
            state["expired"] = True

    def arrays(self, *a, **k):
        calls["arrays"] += 1
        state["arrays"] = True
        return real_arrays(self, *a, **k)

    def one_try(self, mem):
        calls["try"] += 1
        state["expired"] = stage == "tries"
        return None

    def forbidden(*a, **k):
        pytest.fail("no draw may follow an expired deadline")
    monkeypatch.setattr(UW.UniformProposal, "_prepare", prepare)
    monkeypatch.setattr(UW.UniformProposal, "_count_arrays", arrays)
    monkeypatch.setattr(UW.UniformProposal, "_try", one_try)
    bot = served(**HISTORY, world_uniform=True, kitty_bury_rule=kitty_rule)
    monkeypatch.setattr(bot.sampler, "_sample_hands", forbidden)
    with pytest.raises(error):
        bot._worlds(copy.deepcopy(rnd), seat, check)
    assert calls["prepare"] == 1 and calls["arrays"] == 1
    assert calls["try"] == {"arrays": 0, "prepared": 0, "tries": 1}[stage]


def test_an_expiry_mid_proposal_commits_the_play_anchor(monkeypatch, jumping_clock):
    rnd, seat = constrained_attacker_state()
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=W, candidates=4, cap=400,
                               batch_size=16, serving_budget_seconds=1.0, **HISTORY,
                               world_uniform=True, kitty_bury_rule=True)
    bot = pv.PVSearchBot(predict, evaluator=ZeroEvaluator(), version=2, config=config,
                         checkpoint="/dev/null", seed=7)
    tries = []
    real_try = UW.UniformProposal._try

    def one_try(self, mem):
        tries.append(1)
        if len(tries) == 3:
            jumping_clock["expired"] = True
            return None          # rejected: only the deadline may end this call
        return real_try(self, mem)
    monkeypatch.setattr(UW.UniformProposal, "_try", one_try)
    before = bot.sampler.rng.getstate()
    anchor = HeuristicBot.decide_play(bot, copy.deepcopy(rnd), seat)
    played = bot.decide_play(copy.deepcopy(rnd), seat)
    record = bot.last_decision_record
    assert played == list(anchor)
    assert record["schema"] == pv.FALLBACK_SCHEMA and record["reason"] == "budget"
    assert len(tries) == 3 and bot.sampler.rng.getstate() == before


def test_an_expiry_mid_proposal_commits_the_bury_incumbent(monkeypatch, jumping_clock):
    rnd = bury_state(65)
    incumbent = HeuristicBot().decide_bury(copy.deepcopy(rnd), rnd.banker)
    bot = served_bury(bury_wide_value=True, bury_budget=1.0, **HISTORY, world_uniform=True)
    tries = []
    real_try = UW.UniformProposal._try

    def one_try(self, mem):
        tries.append(1)
        if len(tries) == 2:
            jumping_clock["expired"] = True
            return None          # rejected: only the deadline may end this call
        return real_try(self, mem)
    monkeypatch.setattr(UW.UniformProposal, "_try", one_try)
    assert bot.decide_bury(copy.deepcopy(rnd), rnd.banker) == list(incumbent)
    record = bot.last_bury_record
    assert record["schema"] == "cwv-bury-fallback-v1" and record["reason"] == "budget"
    assert len(tries) == 2 and bot.evaluator.calls == 0


# ------------------------------------------------------------ served bury

def test_the_served_bury_draws_its_model_worlds_from_the_proposal(monkeypatch):
    calls = []
    real = bwv.sample_worlds_uniform

    def spy(bot, rnd, seat, n, **kw):
        calls.append((type(bot).__name__, seat, n))
        return real(bot, rnd, seat, n, **kw)
    monkeypatch.setattr(bwv, "sample_worlds_uniform", spy)
    rnd = bury_state(65)
    off = served_bury(bury_wide_value=True, **HISTORY)
    off.decide_bury(copy.deepcopy(rnd), rnd.banker)
    assert calls == [] and "uniform" not in off.last_bury_record["wide_value"]
    on = served_bury(bury_wide_value=True, **HISTORY, world_uniform=True)
    on.decide_bury(copy.deepcopy(rnd), rnd.banker)
    record = on.last_bury_record
    assert [c[1:] for c in calls] == [(rnd.banker, on.bury_config.model_worlds)]
    assert record["schema"] == "cwv-bury-policy-v1"
    assert record["wide_value"]["uniform"]["uniform_fallback_worlds"] == 0


# ------------------------------------------------------- the real package

def test_pinned_serving_factory_snapshot_and_commit(pinned_production_package, tmp_path):
    """No stub model or sampler: the enabled env recipe reaches the live consumer."""
    from shengji.api import server as srv
    env = tomllib.loads((Path(__file__).resolve().parents[2] / "fly.toml").read_text())["env"]
    env.update(SHENGJI_PV_CKPT=str(pinned_production_package), **ENV_KB)
    entries = pv.pv_registry_entries(**pv.pv_env_recipe(env))
    name, = entries
    bot = entries[name](seed=7)
    assert bot.world_uniform and bot.kitty_bury_rule and "-whd-wu-kb-" in name
    rnd, seat = next((r, s) for r, s in states() if s != r.banker)

    async def scenario():
        game = Game(random.Random(0))
        game.round = rnd
        room = srv.Room(code="WUKB", game=game, bot=bot,
                        seats=[srv.Seat(str(s), is_bot=True) for s in range(4)], log_dir=tmp_path)
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        room.log_event = lambda kind, **data: None
        before = list(rnd.hands[seat])
        rng_before = bot.sampler.rng.getstate()
        prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
        assert prepared is not None
        assert room.bot is bot and bot.sampler.rng.getstate() == rng_before
        record = prepared.decision.snapshot.bot_copy.last_decision_record
        assert record["schema"] == pv.RECORD_SCHEMA and record["work_complete"]
        assert record["worlds"] == 64 and record["kitty_rule_worlds"] > 0
        assert record["played"] == list(prepared.decision.cards)
        assert srv._commit_bot_turn(room, prepared)
        assert len(rnd.hands[seat]) == len(before) - len(record["played"])
    asyncio.run(scenario())
    broot = bury_state(66)
    bot.decide_bury(copy.deepcopy(broot), broot.banker)
    assert bot.last_bury_record["schema"] == "cwv-bury-policy-v1"
    assert bot.last_bury_record["wide_value"]["uniform"]["uniform_tries"] == 32
