"""The OPTIONAL refusal-aware world sampling of the pv-search bot (#676 B,
the sampler side only): ``refusal_constraints``.

Torch-free: a stub predictor (fixed log-odds) and a stub evaluator (zeros) on
the real fixture round, production's sampler and the real engine.

Witnesses: on the fixture deal the engine refuses seat 0's throw (single- and
pair-forced variants); every world the constrained sampler returns, with the
thrower an opponent or the acting seat itself, during the notice and after it
expired, makes the REAL engine refuse that throw and force the same component
(``validate_lead`` and a replayed ``Round.play``), while production's
unconstrained draw does not; the rule off, and the rule on with no refusal
this round, draw exactly production's worlds for the same seed and add no
record keys; the attempt cap is the sampler's own and a shortfall is filled
unconstrained; the production registry name is unchanged with the rule off
and distinct with it on; the env flag accepts only 0/1; the record fields.
"""
import copy
import pickle
import random

import numpy as np
import pytest

from shengji.ai import refusal as R
from shengji.ai.cwv_policy import sample_worlds
from shengji.ai.heuristic import HeuristicBot
from shengji.ai.mcbot import MCBot
from shengji.ai.memory import Memory
from shengji.engine.combos import decompose
from shengji.engine.game import Game
from shengji.engine.legal import IllegalPlay, validate_lead
from shengji.harvest.legal import enumerate_legal
from shengji.train import pv_search_policy as pv
from test_policy_world_search import state

PRODUCTION_NAME = "pv-search-491ee4bf-w64-k8-r4a09aef5-bury-hybrid-355958b4db25"
PRODUCTION_SHA = "491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670"
PRODUCTION_ENV = {   # fly.toml, release 36
    "SHENGJI_PV_CKPT": "/data/models/smv3out-491ee4bf.npz",
    "SHENGJI_PV_SHA256": PRODUCTION_SHA,
    "SHENGJI_PV_WORLDS": "64", "SHENGJI_PV_CANDIDATES": "8", "SHENGJI_PV_CAP": "4000",
    "SHENGJI_PV_BATCH_SIZE": "128", "SHENGJI_PV_SERVING_BUDGET_SECONDS": "3",
    "SHENGJI_PV_BURY_ARM": "hybrid", "SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS": "2",
}
RULE_KEYS = {"refusal_observations", "refusal_rejections", "refusal_fallback_worlds",
             "refusal_pinned_codes"}
W = 16


class ZeroEvaluator:
    backend = "numpy"
    max_batch = 128

    def score(self, leaves, seat):
        return np.zeros(len(leaves))


def predict(X):
    return np.tile(np.arange(54, dtype=np.float64), (len(X), 1))


def served(seed=5, worlds=W, **rules):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=worlds, candidates=4,
                               cap=400, batch_size=16, **rules)
    return pv.PVSearchBot(predict, evaluator=ZeroEvaluator(), version=2, config=config,
                          checkpoint="/dev/null", seed=seed)


def refused_throw(rnd, seat, pair_len):
    """The first legal lead of ``seat`` the engine refuses whose FORCED component
    has ``pair_len`` (0: a single, 1: a pair) and which the NEXT seat alone could
    not refuse (the beater sits further round the table, unseen by the next
    seat's sampler), with what it forces."""
    others = [rnd.hands[s] for s in range(4) if s != seat]
    nxt = rnd.hands[(seat + 1) % 4]
    for action in enumerate_legal(rnd, seat, cap=4000).actions:
        if len(decompose(list(action), rnd.ordering).components) < 2:
            continue
        forced, message = validate_lead(list(action), rnd.hands[seat], others, rnd.ordering)
        if message is None:
            continue
        if validate_lead(list(action), rnd.hands[seat], [nxt], rnd.ordering)[1] is not None:
            continue
        if decompose(forced, rnd.ordering).components[0].pair_len == pair_len:
            return list(action), forced
    raise AssertionError(f"no refused throw with a {pair_len}-pair forced component")


def thrown(pair_len):
    """``(before, after, attempted, forced)``: the fixture round before and after
    seat 0's refused throw."""
    before = state()
    assert before.turn == 0
    attempted, forced = refused_throw(before, 0, pair_len)
    # trump S/2 on this deal: the thrower's S2 / SK-pair are beaten only by the
    # jokers in seat 2's hand, which seat 1 cannot see
    assert [attempted, forced] == ([["D2", "D2", "S2"], ["S2"]],
                                   [["D2", "D2", "SK", "SK"], ["SK", "SK"]])[pair_len]
    after = copy.deepcopy(before)
    after.play(0, attempted)
    assert after.notice == {"id": 1, "kind": "failed_throw", "seat": 0,
                            "attempted": attempted, "forced": forced}
    assert after.trick.plays[0].cards == forced and after.turn == 1
    return before, after, attempted, forced


def engine_refuses(before, now, world_hands, refusal):
    """Drive the REAL engine: the pre-throw round with this world's hands as
    they were at throw time; does ``Round.play`` refuse and force the same?"""
    clone = copy.deepcopy(before)
    clone.hands = R.throw_time_hands(now, world_hands, refusal.trick_index)
    try:
        clone.play(refusal.seat, list(refusal.attempted))
    except IllegalPlay:
        return False       # this world does not even give the thrower the throw
    return (clone.message is not None and clone.message.startswith("Throw failed")
            and clone.trick.plays[0].cards == list(refusal.forced)
            and clone.notice["forced"] == list(refusal.forced))


def heuristic_until(rnd, stop):
    h = HeuristicBot()
    while not stop(rnd):
        rnd.play(rnd.turn, h.decide_play(rnd, rnd.turn))


# ------------------------------------------------------------- the fixture

@pytest.mark.parametrize("pair_len", [0, 1])
def test_fixture_throw_is_refused_and_observed(pair_len):
    before, after, attempted, forced = thrown(pair_len)
    seen = R.observe_refusal(after)
    assert seen == R.Refusal(0, tuple(attempted), tuple(forced), 0)
    assert R.on_record(after, seen)
    assert R.observe_refusal(before) is None
    # the true deal is consistent with its own refusal, by construction
    assert R.refusal_consistent(after, after.hands, seen)
    assert engine_refuses(before, after, after.hands, seen)


# ------------------------------------------------------------- soundness

@pytest.mark.parametrize("pair_len", [0, 1])
def test_every_constrained_world_is_refused_by_the_real_engine(pair_len):
    before, after, attempted, forced = thrown(pair_len)
    refusal = R.observe_refusal(after)
    # (a) the next seat, following in the throw trick: the thrower is an opponent
    bot = served(refusal_constraints=True)
    worlds, attempts = bot._worlds(after, 1)
    assert len(worlds) == W
    for hands, _ in worlds:
        assert R.refusal_consistent(after, hands, refusal)
        assert engine_refuses(before, after, hands, refusal)
    stats = bot._last_sampling
    assert stats["refusal_observations"] == 1 and stats["refusal_fallback_worlds"] == 0
    assert attempts >= W + stats["refusal_rejections"]
    assert stats["refusal_rejections"] >= 1      # a joker (pair) elsewhere: rejected
    # production's unconstrained draw, same seed, does NOT satisfy the engine
    plain, _ = served(refusal_constraints=False)._worlds(after, 1)
    assert any(not R.refusal_consistent(after, hands, refusal) for hands, _ in plain)
    assert any(not engine_refuses(before, after, hands, refusal) for hands, _ in plain)
    # the pin: every attempted card the thrower has not played is in its hand
    unplayed = [c for c in attempted if c not in forced]
    assert unplayed and all(c in after.hands[0] for c in unplayed)
    assert all(all(hands[0].count(c) >= unplayed.count(c) for c in set(unplayed))
               for hands, _ in worlds)


@pytest.mark.parametrize("pair_len", [0, 1])
def test_constraint_holds_after_plays_since_the_throw_and_for_the_thrower_itself(pair_len):
    before, after, attempted, forced = thrown(pair_len)
    refusal = R.observe_refusal(after)
    bot = served(seed=9, refusal_constraints=True)
    assert bot._refusals.observe(after) == [refusal]       # seen while posted
    # the throw trick resolves; cards have left hands since the throw
    now = copy.deepcopy(after)
    heuristic_until(now, lambda r: len(r.history) == 1 and r.turn is not None)
    assert R.plays_since(now, 0)[1] and R.plays_since(now, 0)[0]
    for seat in range(4):
        if now.turn != seat:
            continue
        worlds, _ = bot._worlds(now, seat)
        assert len(worlds) == W and bot._last_sampling["refusal_observations"] == 1
        for hands, _ in worlds:
            assert R.refusal_consistent(now, hands, refusal)
            assert engine_refuses(before, now, hands, refusal)
    # the THROWER's own later decision (seat 0 to act again): same constraint,
    # nothing pinned (its own hand), still every world refusable
    heuristic_until(now, lambda r: r.turn == 0)
    worlds, _ = bot._worlds(now, 0)
    assert len(worlds) == W
    assert bot._last_sampling["refusal_observations"] == 1
    assert bot._last_sampling["refusal_pinned_codes"] == 0
    for hands, _ in worlds:
        assert R.refusal_consistent(now, hands, refusal)
        assert engine_refuses(before, now, hands, refusal)
    # (the banker-thrower knows its kitty, so here every joker is provably in an
    # opponent hand and production's draw happens to satisfy the rule as well;
    # the seat-1 witnesses above are where the rule rejects)
    # the notice expires (NOTICE_PLAYS accepted plays); the ledger keeps it
    heuristic_until(now, lambda r: r.notice is None)
    assert now.phase == "play"
    seat = now.turn
    worlds, _ = bot._worlds(now, seat)
    assert bot._last_sampling["refusal_observations"] == 1
    assert R.on_record(now, refusal)
    for hands, _ in worlds:
        assert R.refusal_consistent(now, hands, refusal)
        assert engine_refuses(before, now, hands, refusal)
    # a bot that never saw the notice has nothing to apply: production's draw
    late = served(seed=9, refusal_constraints=True)
    assert late._refusals.observe(now) == []
    assert late._worlds(now, seat)[0] == served(seed=9)._worlds(now, seat)[0]


def test_consistency_is_exactly_the_engine_rule_on_crafted_hands():
    """Hand-built worlds at the throw position: beatable by a higher single in
    one hand -> consistent; the beater moved to the thrower -> not; a world that
    makes a LOWER component beatable instead forces a different component -> not."""
    before, after, attempted, forced = thrown(0)
    refusal = R.observe_refusal(after)
    o = after.ordering
    suit = o.eff_suit(forced[0])
    truth = [list(h) for h in after.hands]
    assert R.refusal_consistent(after, truth, refusal)
    # move every card of the suit that beats the forced single out of the
    # opponents' hands into the thrower's: nothing beats it any more
    top = o.level(forced[0])
    moved = [list(h) for h in truth]
    for s in (1, 2, 3):
        for c in list(moved[s]):
            if o.eff_suit(c) == suit and o.level(c) > top:
                moved[s].remove(c)
                moved[0].append(c)
    assert not R.refusal_consistent(after, moved, refusal)
    assert not engine_refuses(before, after, moved, refusal)


# --------------------------------------------------------- off == before

@pytest.mark.parametrize("pair_len", [0, 1])
def test_rule_off_draws_production_worlds_and_adds_no_record_keys(pair_len):
    before, after, attempted, forced = thrown(pair_len)
    off = served(seed=21)
    assert off.refusal_constraints is False
    worlds, attempts = off._worlds(after, 1)
    mem = Memory(after, 1, own_kitty=True)
    expected, expected_attempts = sample_worlds(MCBot(seed=21), after, 1, W, mem=mem)
    assert worlds == expected and attempts == expected_attempts
    # a decision: the same record as before the rule existed
    bot = served(seed=21)
    bot.decide_play(copy.deepcopy(after), 1)
    record = bot.last_decision_record
    assert record["schema"] == pv.RECORD_SCHEMA and not RULE_KEYS & set(record)
    # on, with no refusal this round (before the throw): production's worlds too
    assert served(seed=21, refusal_constraints=True)._worlds(before, 0)[0] == \
        served(seed=21)._worlds(before, 0)[0]
    on = served(seed=21, refusal_constraints=True)
    on.decide_play(copy.deepcopy(before), 0)
    assert on.last_decision_record["refusal_observations"] == 0
    assert on.last_decision_record["refusal_rejections"] == 0


# ----------------------------------------------------- bounded attempts

def test_attempts_are_capped_and_the_shortfall_is_filled_unconstrained(monkeypatch):
    before, after, attempted, forced = thrown(0)
    monkeypatch.setattr(R, "refusal_consistent", lambda rnd, hands, refusal: False)
    bot = served(seed=3, refusal_constraints=True)
    sampler = bot.sampler
    worlds, attempts = bot._worlds(after, 1)
    stats = bot._last_sampling
    cap = W * sampler.SAMPLE_ATTEMPT_FACTOR
    assert len(worlds) == W                         # never short
    assert stats["refusal_fallback_worlds"] == W     # all from the unconstrained fill
    assert stats["refusal_rejections"] <= cap
    assert cap < attempts <= 2 * cap
    assert stats["refusal_rejections"] + (cap - stats["refusal_rejections"]) == cap
    # the serving deadline is honoured between attempts
    calls = []

    def check_budget():
        calls.append(1)
        if len(calls) > 5:
            raise pv.PVSearchBudgetExceeded("expired")
    with pytest.raises(pv.PVSearchBudgetExceeded):
        served(seed=3, refusal_constraints=True)._worlds(after, 1, check_budget)
    assert len(calls) == 6


def test_a_served_decision_under_budget_falls_back_to_the_anchor(monkeypatch):
    before, after, attempted, forced = thrown(0)
    monkeypatch.setattr(R, "refusal_consistent", lambda rnd, hands, refusal: False)
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=W, candidates=4, cap=400,
                               batch_size=16, serving_budget_seconds=1e-9,
                               refusal_constraints=True)
    bot = pv.PVSearchBot(predict, evaluator=ZeroEvaluator(), version=2, config=config,
                         checkpoint="/dev/null", seed=3)
    played = bot.decide_play(copy.deepcopy(after), 1)
    assert bot.last_decision_record["schema"] == pv.FALLBACK_SCHEMA
    assert bot.last_decision_record["reason"] == "budget"
    assert played == HeuristicBot().decide_play(after, 1)


# ------------------------------------------------------ name / env / record

@pytest.fixture
def production_package(monkeypatch):
    import shengji.ai.cwv_policy as cwv
    monkeypatch.setattr(cwv, "checkpoint_id", lambda path: PRODUCTION_SHA[:8])


def names(env):
    return list(pv.pv_registry_entries(**pv.pv_env_recipe(env)))


def test_production_name_unchanged_off_and_distinct_on(production_package):
    assert names(PRODUCTION_ENV) == [PRODUCTION_NAME]
    assert names({**PRODUCTION_ENV, "SHENGJI_PV_REFUSAL_CONSTRAINTS": "0"}) == [PRODUCTION_NAME]
    on, = names({**PRODUCTION_ENV, "SHENGJI_PV_REFUSAL_CONSTRAINTS": "1"})
    assert on != PRODUCTION_NAME
    assert on.startswith("pv-search-491ee4bf-w64-k8-rc-r") and "-bury-hybrid-" in on
    config = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0)
    assert pv.recipe_digest(config) == "4a09aef5"
    assert "refusal_constraints" not in pv.recipe_payload(config)
    rc = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                           refusal_constraints=True)
    assert pv.recipe_payload(rc)["refusal_constraints"] is True
    assert pv.recipe_digest(rc) != "4a09aef5"
    with pytest.raises(pv.PVSearchPolicyError, match="must be a bool"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA,
                                            refusal_constraints=1))
    assert pv.pv_env_recipe({**PRODUCTION_ENV, "SHENGJI_PV_REFUSAL_CONSTRAINTS": "1"}
                            )["refusal_constraints"] is True
    assert "refusal_constraints" not in pv.pv_env_recipe(PRODUCTION_ENV)


@pytest.mark.parametrize("bad", ["2", "true", "yes", "on", " 1"])
def test_env_flag_refuses_anything_but_0_or_1(bad):
    with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
        pv.pv_env_recipe({**PRODUCTION_ENV, "SHENGJI_PV_REFUSAL_CONSTRAINTS": bad})


@pytest.mark.parametrize("pair_len", [0, 1])
def test_decision_record_carries_the_rule_fields_when_on(pair_len):
    before, after, attempted, forced = thrown(pair_len)
    bot = served(seed=5, refusal_constraints=True)
    played = bot.decide_play(copy.deepcopy(after), 1)
    record = bot.last_decision_record
    assert record["schema"] == pv.RECORD_SCHEMA and record["worlds"] == W
    assert RULE_KEYS <= set(record)
    assert record["refusal_observations"] == 1
    assert record["refusal_rejections"] >= 1
    assert record["refusal_fallback_worlds"] == 0
    unplayed = {c for c in attempted if c not in forced}
    assert record["refusal_pinned_codes"] == len(unplayed)
    assert record["sample_attempts"] >= W + record["refusal_rejections"]
    assert played in [list(a) for a in enumerate_legal(after, 1, cap=400).actions]


# ------------------------------------------------------------- the ledger

def test_ledger_persists_across_the_server_snapshot_and_resets_per_round():
    before, after, attempted, forced = thrown(0)
    refusal = R.observe_refusal(after)
    bot = served(seed=5, refusal_constraints=True)
    bot._worlds(after, 1)
    assert bot._refusals.refusals == [refusal]
    # the server's per-turn snapshot deep-copies the bot; the screen pickles it
    assert copy.deepcopy(bot)._refusals.refusals == [refusal]
    assert pickle.loads(pickle.dumps(bot))._refusals.refusals == [refusal]
    # another deal: an empty ledger
    other = Game(random.Random(7)).start_round()
    assert tuple(other.deck) != tuple(after.deck)
    other_round = state()
    other_round.deck = list(other.deck)
    assert bot._refusals.observe(other_round) == []
    # back on the fixture deal
    assert bot._refusals.observe(after) == [refusal]
    # the same deal replayed with a different lead in that trick: the record no
    # longer supports the entry and it is dropped (a lead of exactly the forced
    # cards would be publicly indistinguishable, and is kept)
    rewound = copy.deepcopy(before)
    other_lead = next(c for c in before.hands[0] if c not in attempted)
    rewound.play(0, [other_lead])
    rewound.notice = None
    assert bot._refusals.observe(rewound) == []


def test_throw_trick_is_located_in_the_current_and_resolved_tricks():
    before, after, attempted, forced = thrown(0)
    assert R.throw_trick_index(after, 0, forced) == 0
    now = copy.deepcopy(after)
    heuristic_until(now, lambda r: len(r.history) == 1)
    assert R.throw_trick_index(now, 0, forced) == 0
    assert R.observe_refusal(now).trick_index == 0
    assert R.throw_trick_index(now, 1, forced) is None
