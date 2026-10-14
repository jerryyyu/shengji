"""The OPTIONAL wide value-only bury chooser of the served pv-search bot
(``bury_wide_value``, ``SHENGJI_PV_BURY_WIDE_VALUE``, bury token ``bwv``;
#707 S15; `train.bury_wide_value`): the structured ballot widened with the
heuristic incumbent's single-card swaps (capped at ``SHENGJI_PV_BURY_WIDE_K``,
the literal incumbent at index 0), the value head's mean over the arm's
``model_worlds`` worlds choosing alone, no MC stage.

Torch-free and package-free (stub predictor and evaluators on the real engine,
the real ballot, the real sampler and the real leaf), except the served
construction, which builds the served bot on the serving test's tiny package.
Witnesses: (a) off: release 44's name, the bury identity and the bot's state
are unchanged; on the DEV bury roots the decision and the record are those of
the mixin's own `_decide_bury` (the override is a passthrough) and the chooser
is never called; (b) enumeration: count <= K, the literal incumbent at 0, every
candidate a legal eight-card bury of the hand, no duplicate multiset, the
ballot kept as a prefix, every swap one card from the incumbent, the swap set
complete; (c) the chooser picks the value argmax (lowest index on a tie) over
exactly the arm's model worlds with the arm's leaf, a winning swap included,
and the record carries ``wide_value``; (d) the budget: an expiry at each
boundary (before anything, after the enumeration, after the sampling, after
the leaf's last policy batch, after a value batch) falls back to the heuristic
incumbent with today's fallback record, ``evaluator.calls`` bounded and the
play sampler's RNG restored; (e) the name token, the identity, the env
parsing and its refusals, the registry; (f) the served construction with the
flag on builds a `PVSearchBuryBot` that decides a bury (not refused); (g) the
two-card swaps (``SHENGJI_PV_BURY_WIDE_SWAPS=2``, token ``bwv2``): the merged,
rank-sum-ordered single/two-card stream (interleaved, not two-card swaps only
after the single ones), bounded by K <= 128, legal, deduplicated, complete by
brute force, deterministic; the refusals; the name/identity change only with
swaps=2; swaps=1 byte-identical to today (a frozen tape digest of decisions and
records taken on the #974 code); the budget at the new enumeration.
"""
import copy
import hashlib
import itertools
import json
import time
from collections import Counter

import numpy as np
import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.registry import REGISTRY, make_bot, register_pv_search_policies
from shengji.train import bury_wide_value as bwv
from shengji.train import cwv_bury
from shengji.train import cwv_bury_policy as bury_policy
from shengji.train import pv_search_policy as pv
from test_cwv_leaf_policy_first_trick import (BURY, SMALL, CountingPredict, ExpireOnFourthPredict,
                                              TrickEvaluator, bury_state, fly_env,
                                              jumping_clock)  # noqa: F401
from test_pv_admission_rules import PRODUCTION_ENV, PRODUCTION_SHA, names, production_package  # noqa: F401
from test_pv_declare_first_round import RELEASE43_VD
from test_pv_search_serving import package  # noqa: F401

FLAG = "SHENGJI_PV_BURY_WIDE_VALUE"
K = "SHENGJI_PV_BURY_WIDE_K"
SWAPS = "SHENGJI_PV_BURY_WIDE_SWAPS"
HEURISTIC = HeuristicBot()
#: release 44 (fly.toml at this head), and with the flag at the default K and at K=64
RELEASE44_NAME = RELEASE43_VD
RELEASE44_BWV = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-radd86676-bury-hybrid-bwv-7143fc5bef3b"
RELEASE44_BWV64 = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-radd86676-bury-hybrid-bwv-7a73e8fbf1a8"
#: release 44 with two-card swaps at K=128
RELEASE44_BWV2_128 = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-radd86676-bury-hybrid-bwv2-7021847bece9"
#: sha256 of the decisions and records (timing aside) of `wide` at K=32 and K=64
#: on the DEV bury roots 60-71, taken on #974's code (before two-card swaps):
#: swaps=1 must reproduce it byte for byte
SWAPS1_TAPE_SHA256 = "ea1a5d3ab8c99be9c222ef446914948a57ee1353d1c09a324ee686d8af22960e"
#: the keys of today's ``cwv-bury-policy-v1`` record (frozen here: a flag-off
#: record gains none)
RECORD_KEYS = ("schema", "arm", "bury_config", "candidates", "shortlist", "picked_index",
               "candidate_count", "finalist_count", "fallback_reason", "model_means",
               "mc_evidence", "model_worlds", "selection_worlds", "world_counts",
               "elapsed_seconds", "model_seconds", "rollout_seconds", "mc_rollouts",
               "model_positions", "leaf_first_trick", "leaf_first_trick_fallbacks", "counters")
TIMING_KEYS = ("elapsed_seconds", "model_seconds", "rollout_seconds")
ROOTS = (65, 66, 67)


# ------------------------------------------------------------ builders

def served_bury(predict=None, evaluator=None, arm="hybrid", bury_budget=None, seed=17,
                bury_config=BURY, **rules):
    wide = {k: rules.pop(k) for k in ("bury_wide_value", "bury_wide_k", "bury_wide_swaps")
            if k in rules}
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, **SMALL, **rules)
    return pv.PVSearchBuryBot(predict or CountingPredict(), evaluator=evaluator or TrickEvaluator(),
                              version=2, config=config, checkpoint="/dev/null", seed=seed,
                              bury_arm=arm, bury_config=bury_config,
                              bury_serving_budget_seconds=bury_budget, **wide)


def wide(k=None, **kw):
    extra = {} if k is None else {"bury_wide_k": k}
    return served_bury(bury_wide_value=True, **extra, **kw)


def decide(bot, index):
    rnd = bury_state(index)
    return bot.decide_bury(copy.deepcopy(rnd), rnd.banker), bot.last_bury_record


def incumbent_of(index):
    rnd = bury_state(index)
    return list(HEURISTIC.decide_bury(copy.deepcopy(rnd), rnd.banker))


def without_timing(record):
    return json.dumps({k: v for k, v in record.items() if k not in TIMING_KEYS}, sort_keys=True)


class FavourEvaluator:
    """1.0 for a position whose kitty is ``target``, else a small value from
    the kitty (so every other candidate is distinct and finite)."""
    backend = "numpy"
    max_batch = 128

    def __init__(self, target):
        self.target = sorted(target)
        self.calls = 0
        self.positions = 0

    def score(self, positions, seat):
        self.calls += 1
        self.positions += len(positions)
        return np.array([1.0 if sorted(p.buried) == self.target else
                         (hash(tuple(sorted(p.buried))) % 97) / 1000.0 for p in positions])


class ExpiringEvaluator(TrickEvaluator):
    """The clock jumps past every deadline the moment the ``on``-th value
    batch returns; small batches so a pass takes several."""
    max_batch = 16

    def __init__(self, clock, on=1):
        super().__init__()
        self.clock = clock
        self.on = on

    def score(self, positions, seat):
        out = super().score(positions, seat)
        if self.calls == self.on:
            self.clock["expired"] = True
        return out


# ------------------------------------------------------------ (a) off: identity

def test_release_name_identity_and_state_unchanged_when_off(production_package):
    assert names(fly_env()) == [RELEASE44_NAME]
    for raw in ("0", ""):
        assert names({**fly_env(), FLAG: raw}) == [RELEASE44_NAME]
    assert names(PRODUCTION_ENV) == names({**PRODUCTION_ENV, FLAG: "0"})
    assert pv.PVSearchBuryBot.bury_wide_value is False
    assert pv.PVSearchBuryBot.bury_wide_k == bwv.WIDE_K_DEFAULT == 32
    assert pv.BURY_WIDE_VALUE_DEFAULTS == {"bury_wide_value": False, "bury_wide_k": 32}
    for arm in ("heuristic", "mc", "hybrid", "value"):
        bot = served_bury(arm=arm)
        assert "bury_wide_value" not in vars(bot) and "bury_wide_k" not in vars(bot)
        off = served_bury(arm=arm, bury_wide_value=False)
        assert vars(bot).keys() == vars(off).keys()
    assert "bury_wide_value" not in pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: "0"})
    assert "bury_wide_value" not in pv.pv_env_recipe(PRODUCTION_ENV)


@pytest.mark.parametrize("arm", ["hybrid", "value", "mc", "heuristic"])
@pytest.mark.parametrize("index", ROOTS)
def test_off_decision_and_record_are_the_mixins_own(arm, index, monkeypatch):
    """The override is a passthrough: on a fixed DEV bury root the flag-off
    bot's bury and record (timing aside) equal those of a bot whose
    `_decide_bury` IS the mixin's, the chooser is never called, and the record
    has exactly today's keys."""
    def never(*a, **k):
        raise AssertionError("the wide chooser ran with the flag off")
    monkeypatch.setattr(pv, "decide_wide_value_bury", never)
    monkeypatch.setattr(bwv, "decide_wide_value_bury", never)

    class Mixin(pv.PVSearchBuryBot):
        _decide_bury = bury_policy.CWVBuryMixin._decide_bury

    for budget in (None, 60.0):
        ours = served_bury(arm=arm, bury_budget=budget)
        theirs = Mixin(CountingPredict(), evaluator=TrickEvaluator(), version=2,
                       config=ours.config, checkpoint="/dev/null", seed=17, bury_arm=arm,
                       bury_config=BURY, bury_serving_budget_seconds=budget)
        a, ra = decide(ours, index)
        b, rb = decide(theirs, index)
        assert a == b
        assert tuple(ra) == RECORD_KEYS and bwv.RECORD_KEY not in ra
        assert without_timing(ra) == without_timing(rb)
        assert ours.evaluator.calls == theirs.evaluator.calls


# ------------------------------------------------------------ (b) the enumeration

def brute_force_swaps(hand, incumbent):
    """Every multiset one card away from the incumbent, by brute force."""
    kept = list((Counter(hand) - Counter(incumbent)).elements())
    out = set()
    for i, card_in in itertools.product(range(len(incumbent)), kept):
        swap = list(incumbent)
        swap[i] = card_in
        key = tuple(sorted(swap))
        if key != tuple(sorted(incumbent)):
            out.add(key)
    return out


@pytest.mark.parametrize("index", range(60, 72))
@pytest.mark.parametrize("k", [2, 8, 32, 64, 500])
def test_enumeration_is_bounded_legal_deduplicated_and_incumbent_first(index, k):
    rnd = bury_state(index)
    banker = rnd.banker
    hand = Counter(rnd.hands[banker])
    incumbent = incumbent_of(index)
    bot = wide()                                            # the ballot does not depend on k
    ballot = bot._bury_candidates(rnd, incumbent)
    candidates, counts = bwv.wide_bury_candidates(rnd, banker, ballot, k)
    assert 1 <= len(candidates) <= k
    assert candidates[0] == incumbent                       # the literal incumbent
    assert candidates[0] is not incumbent
    keys = [tuple(sorted(c)) for c in candidates]
    assert len(set(keys)) == len(keys)                      # no duplicate multiset
    for candidate in candidates:
        assert len(candidate) == 8 and not Counter(candidate) - hand
    prefix = min(k, len(ballot))
    assert candidates[:prefix] == [list(c) for c in ballot[:prefix]]   # the ballot first
    swaps = candidates[prefix:]
    expected_swaps = brute_force_swaps(rnd.hands[banker], incumbent)
    for swap in swaps:
        assert tuple(sorted(swap)) in expected_swaps
        assert sum((Counter(swap) - Counter(incumbent)).values()) == 1
    assert counts == {"k": k, "ballot_count": len(ballot), "swap_count": len(swaps),
                      "swaps_enumerated": len(expected_swaps)}
    assert len(candidates) == min(k, len(ballot) + len(expected_swaps - set(keys[:prefix])))
    # the swap enumeration itself: complete, deterministic, never the incumbent
    enumerated = bwv.single_card_swaps(rnd.hands[banker], incumbent, rnd.ordering)
    assert {tuple(sorted(s)) for s in enumerated} == expected_swaps
    assert len(enumerated) == len(expected_swaps)
    assert enumerated == bwv.single_card_swaps(rnd.hands[banker], incumbent, rnd.ordering)
    if k >= 500:
        assert len(candidates) == len(set(keys[:len(ballot)]) | expected_swaps)


def test_enumeration_refusals():
    rnd = bury_state(65)
    incumbent = incumbent_of(65)
    for bad in (1, 0, -3, 2.0, "32", True, None):
        with pytest.raises(bury_policy.BuryPolicyError, match="int >= 2"):
            bwv.check_wide_k(bad)
    assert bwv.check_wide_k(2) == 2
    with pytest.raises(bury_policy.BuryPolicyError, match="incumbent"):
        bwv.wide_bury_candidates(rnd, rnd.banker, [], 32)
    with pytest.raises(bury_policy.BuryPolicyError, match="duplicates"):
        bwv.wide_bury_candidates(rnd, rnd.banker, [incumbent, list(incumbent)], 32)
    with pytest.raises(bury_policy.BuryPolicyError, match="outside"):
        bwv.single_card_swaps(rnd.hands[rnd.banker], ["XX"] * 8, rnd.ordering)
    assert set(bwv.__all__) == {"WIDE_K_DEFAULT", "WIDE_K_MAX", "WIDE_SWAPS_DEFAULT", "WIDE_SWAPS",
                                "RECORD_KEY", "CHOOSER", "TOKEN", "TOKEN_TWO_SWAPS", "check_wide_k",
                                "check_wide_swaps", "single_card_swaps", "ranked_swaps",
                                "wide_bury_candidates", "decide_wide_value_bury"}


# ------------------------------------------------------------ (c) the chooser

@pytest.mark.parametrize("arm", ["hybrid", "value"])
@pytest.mark.parametrize("index", ROOTS)
@pytest.mark.parametrize("lpft", [False, True])
def test_the_value_argmax_over_the_arms_worlds_with_the_arms_leaf_decides(arm, index, lpft):
    rules = {"leaf_policy_first_trick": True} if lpft else {}
    bot = wide(k=64, arm=arm, bury_budget=60.0, **rules)
    chosen, record = decide(bot, index)
    rnd = bury_state(index)
    assert len(chosen) == 8 and not Counter(chosen) - Counter(rnd.hands[rnd.banker])
    assert record["schema"] == "cwv-bury-policy-v1" and record["arm"] == arm
    assert record["fallback_reason"] is None
    # the same positions a manual value pass scores: the arm's model worlds
    # (the seeded model helper), the widened set, the arm's leaf
    model_bot = make_bot("mc-s0-report-lcb", seed=bury_policy._seed("model", bot.seed))
    worlds, attempts = bury_policy._worlds(model_bot, rnd, rnd.banker, BURY.model_worlds, "model")
    candidates, _ = bwv.wide_bury_candidates(rnd, rnd.banker,
                                             bot._bury_candidates(rnd, incumbent_of(index)), 64)
    leaf = bot._leaf_first_trick(model_bot.rollout_policy)
    first_trick = ({"first_trick_policy": model_bot.rollout_policy} if leaf is None
                   else {"first_trick_batch": leaf.play_first_tricks})
    values = cwv_bury.score_bury_candidates(rnd, candidates, worlds, TrickEvaluator(), **first_trick)
    means = values.mean(axis=0)
    expected = min(range(len(candidates)), key=lambda i: (-float(means[i]), i))
    assert record["candidates"] == candidates
    assert record["model_means"] == means.tolist()
    assert record["picked_index"] == expected and chosen == candidates[expected]
    assert record["world_counts"] == {"model": BURY.model_worlds, "selection": 0,
                                      "model_attempts": attempts, "selection_attempts": 0}
    assert record["model_worlds"] == BURY.model_worlds and record["selection_worlds"] == 0
    assert record["model_positions"] == len(candidates) * BURY.model_worlds
    assert len(bot.evaluator.positions) == record["model_positions"]
    # no MC stage: the MC fields are the ``value`` arm's empties
    assert record["mc_evidence"] is None and record["mc_rollouts"] == 0
    assert record["finalist_count"] == 0 and record["shortlist"] == [0]
    assert record["rollout_seconds"] == 0.0
    assert record["counters"]["mc_before"] is None and record["counters"]["mc_after"] is None
    assert record["leaf_first_trick"] == ("policy" if lpft else "heuristic")
    assert record["leaf_first_trick_fallbacks"] == 0
    assert (bot.predict.calls > 0) is lpft
    # the telemetry a screen reader asserts
    wv = record[bwv.RECORD_KEY]
    assert set(wv) == {"candidates", "worlds", "chosen_index", "chosen_is_incumbent", "seconds",
                       "k", "ballot_count", "swap_count", "swaps_enumerated"}
    assert wv["candidates"] == len(candidates) == record["candidate_count"]
    assert wv["worlds"] == BURY.model_worlds
    assert wv["chosen_index"] == expected
    assert wv["chosen_is_incumbent"] is (expected == 0)
    assert 0.0 < wv["seconds"] <= record["elapsed_seconds"]
    assert wv["k"] == 64 and wv["ballot_count"] + wv["swap_count"] == wv["candidates"]
    assert wv["swap_count"] > 0                             # the set WAS widened
    assert tuple(record) == RECORD_KEYS + (bwv.RECORD_KEY,)
    assert json.dumps(record)                                # serialisable for the screen


def test_a_winning_swap_is_chosen_and_the_evaluator_saw_every_candidate_once_per_world():
    """A swap outside the ballot can win: the evaluator favours one swap's
    kitty and the chooser picks it (the hybrid today could not: it is not in
    the ballot)."""
    index = 65
    rnd = bury_state(index)
    probe = wide(k=64)
    candidates, counts = bwv.wide_bury_candidates(
        rnd, rnd.banker, probe._bury_candidates(rnd, incumbent_of(index)), 64)
    assert counts["swap_count"] > 0
    target_index = counts["ballot_count"]                   # the first swap
    target = candidates[target_index]
    bot = wide(k=64, evaluator=FavourEvaluator(target))
    chosen, record = decide(bot, index)
    assert chosen == target and record["picked_index"] == target_index
    assert record[bwv.RECORD_KEY]["chosen_is_incumbent"] is False
    assert record["model_means"][target_index] == 1.0
    assert bot.evaluator.positions == len(candidates) * BURY.model_worlds
    # the ballot alone (today's hybrid or value arm) cannot reach it
    assert tuple(sorted(target)) not in {tuple(sorted(c)) for c in candidates[:target_index]}
    narrow = served_bury(arm="value", evaluator=FavourEvaluator(target))
    assert decide(narrow, index)[0] != target
    # ties: the lowest index wins (a constant evaluator keeps the incumbent)
    class Flat(TrickEvaluator):
        def score(self, positions, seat):
            self.calls += 1
            return np.zeros(len(positions))
    flat = wide(k=64, evaluator=Flat())
    chosen, record = decide(flat, index)
    assert chosen == incumbent_of(index) and record["picked_index"] == 0
    assert record[bwv.RECORD_KEY]["chosen_is_incumbent"] is True


def test_the_wide_chooser_does_not_consume_the_play_sampler_and_the_incumbent_is_literal():
    bot = wide(k=64)
    before = bot.sampler.rng.getstate()
    chosen, record = decide(bot, 66)
    assert bot.sampler.rng.getstate() == before
    assert record["candidates"][0] == incumbent_of(66)
    assert record["counters"]["model_before"] is not None
    # k below the ballot: the ballot is cut, the chooser still runs
    small = wide(k=2)
    chosen, record = decide(small, 66)
    assert record["candidate_count"] == 2 and record[bwv.RECORD_KEY]["swap_count"] == 0
    assert chosen in record["candidates"]


# ------------------------------------------------------------ (d) the budget

def assert_fallback(bot, index, before, *, evaluator_calls):
    chosen = bot.decide_bury(bury_state(index), bury_state(index).banker)
    assert chosen == incumbent_of(index)
    record = bot.last_bury_record
    assert record["schema"] == "cwv-bury-fallback-v1" and record["arm"] == bot.bury_arm
    assert record["reason"] == record["fallback_reason"] == "budget"
    assert record["error_class"] == "BuryBudgetExceeded"
    assert record["action"] == chosen and record["work_complete"] is False
    assert record["budget_seconds"] == bot.bury_serving_budget_seconds
    assert {"candidate_count", "finalist_count", "mc_rollouts", "model_positions",
            "leaf_first_trick", "leaf_first_trick_fallbacks"} <= set(record)
    assert bwv.RECORD_KEY not in record
    assert bot.evaluator.calls == evaluator_calls
    assert bot.sampler.rng.getstate() == before
    return record


def test_an_already_expired_budget_falls_back_before_any_work():
    bot = wide(k=64, bury_budget=1e-9)
    record = assert_fallback(bot, 65, bot.sampler.rng.getstate(), evaluator_calls=0)
    assert record["candidate_count"] is None and record["model_positions"] == 0


def test_expiry_after_the_enumeration_starts_no_sampling_and_no_value_batch(jumping_clock, monkeypatch):
    real = bwv.wide_bury_candidates

    def enumerate_then_expire(*a, **k):
        out = real(*a, **k)
        jumping_clock["expired"] = True
        return out
    monkeypatch.setattr(bwv, "wide_bury_candidates", enumerate_then_expire)
    sampled = []
    real_worlds = bwv._worlds
    monkeypatch.setattr(bwv, "_worlds", lambda *a, **k: sampled.append(1) or real_worlds(*a, **k))
    bot = wide(k=64, bury_budget=0.5)
    record = assert_fallback(bot, 65, bot.sampler.rng.getstate(), evaluator_calls=0)
    assert record["candidate_count"] > 0 and not sampled
    assert record["model_positions"] == 0


def test_expiry_after_the_sampling_starts_no_value_batch(jumping_clock, monkeypatch):
    real_worlds = bwv._worlds

    def sample_then_expire(*a, **k):
        out = real_worlds(*a, **k)
        jumping_clock["expired"] = True
        return out
    monkeypatch.setattr(bwv, "_worlds", sample_then_expire)
    bot = wide(k=64, bury_budget=0.5)
    record = assert_fallback(bot, 65, bot.sampler.rng.getstate(), evaluator_calls=0)
    assert record["candidate_count"] > 0 and record["model_positions"] is None


def test_expiry_on_the_leafs_last_policy_batch_starts_no_value_batch(jumping_clock):
    """#972's witness on this consumer: the leaf's final check, after the
    trick's last play and before the value batch."""
    bot = wide(k=64, predict=ExpireOnFourthPredict(jumping_clock), bury_budget=0.5,
               leaf_policy_first_trick=True)
    record = assert_fallback(bot, 65, bot.sampler.rng.getstate(), evaluator_calls=0)
    assert bot.predict.calls == 4
    assert record["leaf_first_trick"] == "policy" and record["leaf_first_trick_fallbacks"] == 0


@pytest.mark.parametrize("on", [1, 2])
def test_expiry_after_a_value_batch_starts_no_further_batch(jumping_clock, on):
    """The post-score check of `score_bury_candidates.flush`: the batch that
    expired is the last one scored, the argmax never runs."""
    bot = wide(k=64, evaluator=ExpiringEvaluator(jumping_clock, on=on), bury_budget=0.5)
    probe = wide(k=64, evaluator=ExpiringEvaluator({"expired": False}, on=10 ** 6))
    decide(probe, 65)
    assert probe.evaluator.calls > on                        # the full pass needs more batches
    assert_fallback(bot, 65, bot.sampler.rng.getstate(), evaluator_calls=on)


def test_a_search_error_falls_back_with_the_error_reason():
    class Broken(TrickEvaluator):
        def score(self, positions, seat):
            self.calls += 1
            raise RuntimeError("value head failed")
    bot = wide(k=64, evaluator=Broken(), bury_budget=5.0)
    before = bot.sampler.rng.getstate()
    assert bot.decide_bury(bury_state(65), bury_state(65).banker) == incumbent_of(65)
    record = bot.last_bury_record
    assert record["schema"] == "cwv-bury-fallback-v1"
    assert record["reason"] == record["fallback_reason"] == "search-error"
    assert record["error_class"] == "RuntimeError" and bot.evaluator.calls == 1
    assert bot.sampler.rng.getstate() == before
    # without a budget the error propagates, as the mixin's search does
    with pytest.raises(RuntimeError, match="value head failed"):
        decide(wide(k=64, evaluator=Broken()), 65)


# ------------------------------------------------------------ (e) names, identity, env, registry

def test_the_token_sits_in_the_bury_segment_and_the_identity_carries_the_chooser(production_package):
    assert names({**fly_env(), FLAG: "1"}) == [RELEASE44_BWV]
    assert names({**fly_env(), FLAG: "1", K: "32"}) == [RELEASE44_BWV]
    assert names({**fly_env(), FLAG: "1", K: "64"}) == [RELEASE44_BWV64]
    play = RELEASE44_NAME[:RELEASE44_NAME.index("-bury-")]
    assert RELEASE44_BWV.startswith(play + "-bury-hybrid-bwv-")   # the play digest is untouched
    assert len(RELEASE44_BWV) == len(play) + len("-bury-hybrid-bwv-") + 12
    value, = names({**fly_env(), "SHENGJI_PV_BURY_ARM": "value", FLAG: "1"})
    assert value.startswith(play + "-bury-value-bwv-")
    lpft, = names({**fly_env(), FLAG: "1", "SHENGJI_PV_LEAF_POLICY_FIRST_TRICK": "1"})
    assert "-lpft-r" in lpft and "-bury-hybrid-bwv-" in lpft
    assert len({RELEASE44_NAME, RELEASE44_BWV, RELEASE44_BWV64, value, lpft}) == 5
    assert bwv.TOKEN == "bwv" and bwv.CHOOSER == "value-argmax-over-model-worlds"


def test_env_parses_the_flag_and_refuses_bad_values():
    recipe = pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: "1"})
    assert recipe["bury_wide_value"] is True and "bury_wide_k" not in recipe
    recipe = pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: "1", K: "64"})
    assert recipe["bury_wide_value"] is True and recipe["bury_wide_k"] == 64
    for bad in ("2", "true", "yes", " 1"):
        with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
            pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: bad})
    with pytest.raises(pv.PVSearchPolicyError, match="needs SHENGJI_PV_BURY_WIDE_VALUE=1"):
        pv.pv_env_recipe({**PRODUCTION_ENV, K: "64"})
    with pytest.raises(pv.PVSearchPolicyError, match="needs SHENGJI_PV_BURY_WIDE_VALUE=1"):
        pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: "0", K: "64"})
    for bad in ("1", "0", "-4", "x", "32.0"):
        with pytest.raises(pv.PVSearchPolicyError, match="int"):
            pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: "1", K: bad})
    no_bury = {k: v for k, v in PRODUCTION_ENV.items() if not k.startswith("SHENGJI_PV_BURY")}
    with pytest.raises(pv.PVSearchPolicyError, match="needs SHENGJI_PV_BURY_ARM"):
        pv.pv_env_recipe({**no_bury, FLAG: "1"})
    assert "bury_wide_value" not in pv.pv_env_recipe({**no_bury, FLAG: "0"})


def test_the_flag_refuses_an_arm_it_cannot_change(production_package):
    for arm in ("mc", "heuristic"):
        with pytest.raises(pv.PVSearchPolicyError, match="needs a model bury arm"):
            names({**PRODUCTION_ENV, "SHENGJI_PV_BURY_ARM": arm, FLAG: "1"})
        with pytest.raises(pv.PVSearchPolicyError, match="needs a model bury arm"):
            served_bury(arm=arm, bury_wide_value=True)
    for arm in ("hybrid", "value"):
        assert names({**PRODUCTION_ENV, "SHENGJI_PV_BURY_ARM": arm, FLAG: "1"})
        bot = served_bury(arm=arm, bury_wide_value=True)
        assert bot.bury_wide_value is True and bot.bury_wide_k == 32
        assert vars(bot)["bury_wide_k"] == 32
    with pytest.raises(pv.PVSearchPolicyError, match="must be a bool"):
        served_bury(bury_wide_value=1)
    with pytest.raises(pv.PVSearchPolicyError, match="int >= 2"):
        served_bury(bury_wide_value=True, bury_wide_k=1)
    with pytest.raises(pv.PVSearchPolicyError, match="needs bury_wide_value"):
        served_bury(bury_wide_k=64)
    with pytest.raises(pv.PVSearchPolicyError, match="needs bury_wide_value"):
        pv.pv_registry_entries("/dev/null", sha256=PRODUCTION_SHA, bury_arm="hybrid", bury_wide_k=64)
    # the leaf rule still needs a leaf; the wide chooser IS one
    assert names({**PRODUCTION_ENV, FLAG: "1", "SHENGJI_PV_LEAF_POLICY_FIRST_TRICK": "1"})


# ------------------------------------------------------------ (f) the served construction

def test_the_served_construction_with_the_flag_on_builds_a_bot_that_decides(package):
    path, sha = package
    small = dict(worlds=3, candidates=4, cap=400, batch_size=16)
    bot = pv.make_pv_search_bot(path, sha256=sha, seed=5, bury_arm="hybrid", bury_config=BURY,
                                bury_serving_budget_seconds=30, bury_wide_value=True,
                                bury_wide_k=48, **small)
    assert isinstance(bot, pv.PVSearchBuryBot)
    assert bot.bury_wide_value is True and bot.bury_wide_k == 48
    chosen, record = decide(bot, 65)
    assert record["schema"] == "cwv-bury-policy-v1" and record[bwv.RECORD_KEY]["k"] == 48
    assert len(chosen) == 8
    # the registry: the name carries the token, the factory binds the identity
    registered = register_pv_search_policies(path, sha256=sha, bury_arm="hybrid", bury_config=BURY,
                                             bury_serving_budget_seconds=2, bury_wide_value=True,
                                             bury_wide_k=48, **small)
    try:
        name, = registered
        play = pv.pv_policy_name(sha[:8], pv.PVSearchConfig(checkpoint_sha256=sha, **small))
        assert name.startswith(play + "-bury-hybrid-bwv-")
        built = make_bot(name, seed=3)
        assert isinstance(built, pv.PVSearchBuryBot) and built.policy_name == name
        assert built.bury_wide_value is True and built.bury_wide_k == 48
        assert built.bury_recipe_identity["wide_value"] == {"chooser": bwv.CHOOSER, "k": 48}
        assert built.bury_recipe_identity["arm"] == "hybrid"
        plain, = pv.pv_registry_entries(path, sha256=sha, bury_arm="hybrid", bury_config=BURY,
                                        bury_serving_budget_seconds=2, **small)
        assert plain.startswith(play + "-bury-hybrid-") and "-bwv-" not in plain
        # a flag-off factory is called exactly as before (no wide keywords)
        seen = {}

        class Probe(pv.PVSearchBuryBot):
            def __init__(self, *a, **kw):
                seen.update(kw)
                super().__init__(*a, **kw)
        pv.make_pv_search_bot(path, sha256=sha, bury_arm="hybrid", bury_config=BURY,
                              bot_factory=Probe, **small)
        assert "bury_wide_value" not in seen and "bury_wide_k" not in seen
        pv.make_pv_search_bot(path, sha256=sha, bury_arm="hybrid", bury_config=BURY,
                              bot_factory=Probe, bury_wide_value=True, **small)
        assert seen["bury_wide_value"] is True and seen["bury_wide_k"] == 32
        # the bot survives the screen's deep copy and pickle with its state
        import pickle
        again = pickle.loads(pickle.dumps(copy.deepcopy(built)))
        assert again.bury_wide_value is True and again.bury_wide_k == 48
    finally:
        for n in registered:
            REGISTRY.pop(n, None)


# ------------------------------------------------------------ (g) two-card swaps

def brute_force_two_swaps(hand, incumbent):
    """Every multiset exactly two cards away from the incumbent."""
    kept = list((Counter(hand) - Counter(incumbent)).elements())
    out = set()
    for (i, j), (a, b) in itertools.product(itertools.combinations(range(len(incumbent)), 2),
                                            itertools.combinations(kept, 2)):
        swap = list(incumbent)
        swap[i], swap[j] = a, b
        if sum((Counter(swap) - Counter(incumbent)).values()) == 2:
            out.add(tuple(sorted(swap)))
    return out


def rank_score(swap, incumbent, ordering, hand):
    """An independent restatement of the stream's order key: (rank sum,
    moved, in-rank sum, in-ranks, out-ranks)."""
    kept = sorted((Counter(hand) - Counter(incumbent)).elements(),
                  key=lambda c: bwv._swap_key(c, ordering))
    outs = sorted(range(8), key=lambda i: bwv._swap_key(incumbent[i], ordering), reverse=True)
    moved_out = [i for i in range(8) if swap[i] != incumbent[i]]
    out_ranks = sorted(outs.index(i) for i in moved_out)
    in_ranks, taken = [], set()
    # each card in sits at the lowest kept rank not yet used by an equal card
    for card in sorted((swap[i] for i in moved_out), key=lambda c: bwv._swap_key(c, ordering)):
        r = next(r for r, c in enumerate(kept) if c == card and r not in taken)
        taken.add(r)
        in_ranks.append(r)
    return (sum(in_ranks) + sum(out_ranks), len(moved_out), sum(in_ranks), tuple(sorted(in_ranks)),
            tuple(out_ranks))


@pytest.mark.parametrize("index", range(60, 72))
@pytest.mark.parametrize("k", [2, 8, 32, 64, 128])
def test_two_swap_enumeration_is_bounded_legal_deduplicated_interleaved_and_deterministic(index, k):
    rnd = bury_state(index)
    banker, hand = rnd.banker, rnd.hands[rnd.banker]
    incumbent = incumbent_of(index)
    ballot = wide()._bury_candidates(rnd, incumbent)
    candidates, counts = bwv.wide_bury_candidates(rnd, banker, ballot, k, swaps=2)
    assert candidates == bwv.wide_bury_candidates(rnd, banker, ballot, k, swaps=2)[0]
    assert 1 <= len(candidates) <= k
    assert candidates[0] == incumbent
    keys = [tuple(sorted(c)) for c in candidates]
    assert len(set(keys)) == len(keys)
    for candidate in candidates:
        assert len(candidate) == 8 and not Counter(candidate) - Counter(hand)
    prefix = min(k, len(ballot))
    assert candidates[:prefix] == [list(c) for c in ballot[:prefix]]
    singles = brute_force_swaps(hand, incumbent)
    doubles = brute_force_two_swaps(hand, incumbent)
    tail = candidates[prefix:]
    moved = [sum((Counter(c) - Counter(incumbent)).values()) for c in tail]
    for candidate, m in zip(tail, moved):
        assert m in (1, 2)
        assert tuple(sorted(candidate)) in (singles if m == 1 else doubles)
    assert counts == {"k": k, "ballot_count": len(ballot), "swap_count": moved.count(1),
                      "swaps_enumerated": len(singles), "swaps": 2,
                      "two_swap_count": moved.count(2)}
    # the set is filled: ~150-200 single and thousands of two-card swaps exist
    assert len(candidates) == k
    # the tail follows the stream's order: rank sum, a single before a two-card swap
    scores = [rank_score(c, incumbent, rnd.ordering, hand) for c in tail]
    assert scores == sorted(scores)
    if k == 128:
        # INTERLEAVED: two-card swaps enter while single swaps remain unused
        assert counts["two_swap_count"] > 0 and 0 < counts["swap_count"] < len(singles)
    if k <= len(ballot):
        # no free slot: exactly today's set
        assert candidates == bwv.wide_bury_candidates(rnd, banker, ballot, k)[0]


@pytest.mark.parametrize("index", [60, 65, 71])
def test_the_ranked_stream_is_complete_and_lazy(index):
    """Drained, the stream covers every one- and two-card neighbour by brute
    force; consumed to K it generates only about K swaps (lazy, bounded by
    K, not by the ~8400 pairs)."""
    rnd = bury_state(index)
    hand, incumbent = rnd.hands[rnd.banker], incumbent_of(index)
    drained = list(bwv.ranked_swaps(hand, incumbent, rnd.ordering))
    by_moved = {m: {tuple(sorted(s)) for mm, s in drained if mm == m} for m in (1, 2)}
    assert by_moved[1] == brute_force_swaps(hand, incumbent)
    assert by_moved[2] == brute_force_two_swaps(hand, incumbent)
    assert len(by_moved[2]) > 1000
    pulled = 0
    stream = bwv.ranked_swaps(hand, incumbent, rnd.ordering)
    seen = {tuple(sorted(incumbent))}
    while len(seen) <= 128:
        _, swap = next(stream)
        pulled += 1
        seen.add(tuple(sorted(swap)))
    assert pulled < 2 * 128
    with pytest.raises(bury_policy.BuryPolicyError, match="outside"):
        list(bwv.ranked_swaps(hand, ["XX"] * 8, rnd.ordering))


def test_swaps_refusals_and_the_k_ceiling(production_package):
    for bad in (0, 3, 2.0, "2", True, None):
        with pytest.raises(bury_policy.BuryPolicyError, match="1 or 2"):
            bwv.check_wide_swaps(bad)
    assert bwv.check_wide_swaps(2) == 2 and bwv.WIDE_K_MAX == 128
    # env: needs the flag, 1 or 2 only
    for env in ({**PRODUCTION_ENV, SWAPS: "2"}, {**PRODUCTION_ENV, FLAG: "0", SWAPS: "2"},
                {**PRODUCTION_ENV, SWAPS: "1"}):
        with pytest.raises(pv.PVSearchPolicyError, match="needs SHENGJI_PV_BURY_WIDE_VALUE=1"):
            pv.pv_env_recipe(env)
    for bad in ("0", "3", "x", " 2", "2.0"):
        with pytest.raises(pv.PVSearchPolicyError, match="must be 1 or 2"):
            pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: "1", SWAPS: bad})
    assert pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: "1", SWAPS: "2"})["bury_wide_swaps"] == 2
    assert "bury_wide_swaps" not in pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: "1"})
    # K: up to 128
    assert pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: "1", K: "128"})["bury_wide_k"] == 128
    for bad in ("129", "256", "500"):
        with pytest.raises(pv.PVSearchPolicyError, match="<= 128"):
            pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: "1", K: bad})
    with pytest.raises(pv.PVSearchPolicyError, match="<= 128"):
        wide(k=129)
    assert wide(k=128, bury_wide_swaps=2).bury_wide_k == 128
    # constructor and registry
    with pytest.raises(pv.PVSearchPolicyError, match="needs bury_wide_value"):
        served_bury(bury_wide_swaps=2)
    with pytest.raises(pv.PVSearchPolicyError, match="needs bury_wide_value"):
        served_bury(bury_wide_swaps=True)
    with pytest.raises(pv.PVSearchPolicyError, match="needs bury_wide_value"):
        pv.pv_registry_entries("/dev/null", sha256=PRODUCTION_SHA, bury_arm="hybrid",
                               bury_wide_swaps=2)
    for bad in (0, 3, 2.0, True):
        with pytest.raises(pv.PVSearchPolicyError, match="1 or 2"):
            wide(bury_wide_swaps=bad)
    with pytest.raises(pv.PVSearchPolicyError, match="needs a model bury arm"):
        served_bury(arm="mc", bury_wide_value=True, bury_wide_swaps=2)


def test_the_name_and_identity_change_only_with_two_swaps(production_package):
    assert names({**fly_env(), FLAG: "1", SWAPS: "1"}) == [RELEASE44_BWV]
    assert names({**fly_env(), FLAG: "1", K: "64", SWAPS: "1"}) == [RELEASE44_BWV64]
    two, = names({**fly_env(), FLAG: "1", K: "128", SWAPS: "2"})
    assert two == RELEASE44_BWV2_128
    play = RELEASE44_NAME[:RELEASE44_NAME.index("-bury-")]
    assert two.startswith(play + "-bury-hybrid-bwv2-")             # the play digest is untouched
    two64, = names({**fly_env(), FLAG: "1", K: "64", SWAPS: "2"})
    assert two64.startswith(play + "-bury-hybrid-bwv2-") and two64 not in (two, RELEASE44_BWV64)
    assert bwv.TOKEN_TWO_SWAPS == "bwv2"


def test_swaps_one_is_byte_identical_to_today():
    """The fixed tape: decisions and records (timing aside) of the chooser at
    K=32 and K=64 on the DEV roots 60-71, default and explicit swaps=1, hash to
    the digest taken on #974's code; a swaps=1 bot carries no new state."""
    for explicit in (False, True):
        extra = {"bury_wide_swaps": 1} if explicit else {}
        tape = []
        for index in range(60, 72):
            for k in (32, 64):
                bot = wide(k=k, bury_budget=60.0, **extra)
                assert "bury_wide_swaps" not in vars(bot)
                chosen, record = decide(bot, index)
                wv = {key: v for key, v in record[bwv.RECORD_KEY].items() if key != "seconds"}
                assert "two_swap_count" not in wv and "swaps" not in wv
                tape.append([index, k, chosen, without_timing({**record, bwv.RECORD_KEY: wv})])
        digest = hashlib.sha256(json.dumps(tape, sort_keys=True).encode()).hexdigest()
        assert digest == SWAPS1_TAPE_SHA256
    assert pv.PVSearchBuryBot.bury_wide_swaps == bwv.WIDE_SWAPS_DEFAULT == 1
    assert vars(wide(k=64)).keys() == vars(wide(k=64, bury_wide_swaps=1)).keys()
    assert "bury_wide_swaps" not in pv.BURY_WIDE_VALUE_DEFAULTS


@pytest.mark.parametrize("index", ROOTS)
def test_the_two_swap_chooser_scores_the_widened_set_and_records_it(index):
    bot = wide(k=128, bury_wide_swaps=2, bury_budget=60.0)
    assert bot.bury_wide_swaps == 2 and vars(bot)["bury_wide_swaps"] == 2
    chosen, record = decide(bot, index)
    rnd = bury_state(index)
    candidates, counts = bwv.wide_bury_candidates(
        rnd, rnd.banker, bot._bury_candidates(rnd, incumbent_of(index)), 128, swaps=2)
    assert record["candidates"] == candidates and len(candidates) == 128
    assert chosen == candidates[record["picked_index"]]
    assert record["model_positions"] == 128 * BURY.model_worlds == len(bot.evaluator.positions)
    wv = record[bwv.RECORD_KEY]
    assert set(wv) == {"candidates", "worlds", "chosen_index", "chosen_is_incumbent", "seconds",
                       "k", "ballot_count", "swap_count", "swaps_enumerated", "swaps",
                       "two_swap_count"}
    assert wv["swaps"] == 2 and wv["two_swap_count"] == counts["two_swap_count"] > 0
    assert wv["ballot_count"] + wv["swap_count"] + wv["two_swap_count"] == wv["candidates"] == 128
    assert tuple(record) == RECORD_KEYS + (bwv.RECORD_KEY,)
    assert json.dumps(record)


def test_a_winning_two_card_swap_is_chosen():
    index = 65
    rnd = bury_state(index)
    candidates, counts = bwv.wide_bury_candidates(
        rnd, rnd.banker, wide()._bury_candidates(rnd, incumbent_of(index)), 128, swaps=2)
    incumbent = Counter(candidates[0])
    target_index = next(i for i, c in enumerate(candidates)
                        if sum((Counter(c) - incumbent).values()) == 2 and i >= counts["ballot_count"])
    target = candidates[target_index]
    bot = wide(k=128, bury_wide_swaps=2, evaluator=FavourEvaluator(target))
    chosen, record = decide(bot, index)
    assert chosen == target and record["picked_index"] == target_index
    # swaps=1 at the same K cannot reach it
    assert decide(wide(k=128, evaluator=FavourEvaluator(target)), index)[0] != target


def test_expiry_inside_the_two_swap_enumeration_falls_back_before_any_work(jumping_clock,
                                                                            monkeypatch):
    """The new boundary: the clock expires while the merged stream yields its
    first two-card swap; the check after the enumeration catches it before
    any world is sampled or any value batch runs."""
    real = bwv.ranked_swaps
    pulled = []

    def stream_then_expire(*a, **k):
        for moved, swap in real(*a, **k):
            pulled.append(moved)
            if moved == 2:
                jumping_clock["expired"] = True
            yield moved, swap
    monkeypatch.setattr(bwv, "ranked_swaps", stream_then_expire)
    sampled = []
    real_worlds = bwv._worlds
    monkeypatch.setattr(bwv, "_worlds", lambda *a, **k: sampled.append(1) or real_worlds(*a, **k))
    bot = wide(k=128, bury_wide_swaps=2, bury_budget=0.5)
    record = assert_fallback(bot, 65, bot.sampler.rng.getstate(), evaluator_calls=0)
    assert 2 in pulled and not sampled
    assert record["candidate_count"] == 128 and record["model_positions"] == 0


def test_an_already_expired_budget_falls_back_with_two_swaps():
    bot = wide(k=128, bury_wide_swaps=2, bury_budget=1e-9)
    record = assert_fallback(bot, 65, bot.sampler.rng.getstate(), evaluator_calls=0)
    assert record["candidate_count"] is None


def test_the_served_construction_with_two_swaps(package):
    path, sha = package
    small = dict(worlds=3, candidates=4, cap=400, batch_size=16)
    bot = pv.make_pv_search_bot(path, sha256=sha, seed=5, bury_arm="hybrid", bury_config=BURY,
                                bury_serving_budget_seconds=30, bury_wide_value=True,
                                bury_wide_k=128, bury_wide_swaps=2, **small)
    assert bot.bury_wide_swaps == 2 and bot.bury_wide_k == 128
    chosen, record = decide(bot, 65)
    assert record[bwv.RECORD_KEY]["two_swap_count"] > 0 and len(chosen) == 8
    registered = register_pv_search_policies(path, sha256=sha, bury_arm="hybrid", bury_config=BURY,
                                             bury_serving_budget_seconds=2, bury_wide_value=True,
                                             bury_wide_k=128, bury_wide_swaps=2, **small)
    try:
        name, = registered
        assert "-bury-hybrid-bwv2-" in name
        built = make_bot(name, seed=3)
        assert built.bury_wide_swaps == 2
        assert built.bury_recipe_identity["wide_value"] == {"chooser": bwv.CHOOSER, "k": 128,
                                                            "swaps": 2}
        one, = pv.pv_registry_entries(path, sha256=sha, bury_arm="hybrid", bury_config=BURY,
                                      bury_serving_budget_seconds=2, bury_wide_value=True,
                                      bury_wide_k=128, bury_wide_swaps=1, **small)
        assert "-bury-hybrid-bwv-" in one and one != name
        # the factory sees the swaps keyword only when it is 2
        seen = {}

        class Probe(pv.PVSearchBuryBot):
            def __init__(self, *a, **kw):
                seen.clear()
                seen.update(kw)
                super().__init__(*a, **kw)
        pv.make_pv_search_bot(path, sha256=sha, bury_arm="hybrid", bury_config=BURY,
                              bot_factory=Probe, bury_wide_value=True, bury_wide_swaps=1, **small)
        assert "bury_wide_swaps" not in seen
        pv.make_pv_search_bot(path, sha256=sha, bury_arm="hybrid", bury_config=BURY,
                              bot_factory=Probe, bury_wide_value=True, bury_wide_swaps=2, **small)
        assert seen["bury_wide_swaps"] == 2
        import pickle
        again = pickle.loads(pickle.dumps(copy.deepcopy(built)))
        assert again.bury_wide_swaps == 2
    finally:
        for n in registered:
            REGISTRY.pop(n, None)
