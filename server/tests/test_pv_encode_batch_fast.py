"""The batched prefix encoder (``SHENGJI_PV_ENCODE_BATCH_FAST=1``,
`pv_encode_prefix.fused_many_batched`): the same tensors as `fused_many` byte
for byte, and the same rows kept, refused or skipped.

Torch-free and package-free.  Witnesses: (a) `fused_many_batched` is
`fused_many` byte for byte (every field, the None pattern) at encoder v1, v2
and v7 on value leaves from the root seat and open reply clones from the seat
to act, in forward and reversed order, over seeded rounds and the named leaf
scenarios; (b) it declines what `fused_many` declines (another root's prefix,
an unsupported version, an unknown card, a malformed hand); (c) `encode_leaves`
and `reply_rows` on a batched prefix return the unbatched rows; (d) paired
``lgf`` bots with the prefix cache on, the switch off and on, decide
identically over seeded rounds (cards, record, sampler state, the finish's
counters, the evaluator's counters) at v2 and v7; (e) the switch is off by
default, read from the environment like the other latency switches, and enters
no name or payload.
"""
import copy

import numpy as np
import pytest

from shengji.train import pv_encode_prefix as pe
from shengji.train import pv_search_policy as pv
from test_pv_doomed_throw_reselect import throw_loving_scores
from test_pv_doomed_throw_reselect_exact_guard import R46_ENV
from test_pv_encode_prefix import (SCENARIOS, counters, find_root, leaves_for, stub_evaluator,
                                   stub_predict_for, worlds_for)
from test_pv_leaf_greedy_finish import LEAF_KEYS, R46_RULES
from test_pv_lgf_reply_prefix import CAPPED_SEED, _roots
from test_pv_small_joker_lead import _fresh_round

FLAG = "SHENGJI_PV_ENCODE_BATCH_FAST"
FIELDS = ("public", "history", "world", "perspective")


def _same_row(a, b):
    if a is None or b is None:
        return a is None and b is None
    if type(a) is not type(b):
        return False
    for field in FIELDS:
        x, y = getattr(a, field), getattr(b, field)
        if x.dtype != y.dtype or x.shape != y.shape or x.tobytes() != y.tobytes():
            return False
    return True


def _assert_same(prefix, positions, seats, version):
    reference = pe.fused_many(prefix, positions, seats, version)
    got = pe.fused_many_batched(prefix, positions, seats, version)
    assert len(got) == len(reference)
    for index, (a, b) in enumerate(zip(got, reference)):
        assert _same_row(a, b), (version, index)
    return sum(row is not None for row in reference), sum(row is None for row in reference)


# ------------------------------------------------- (a) the same tensors

@pytest.mark.parametrize("version", [1, 2, 7])
def test_batched_rows_are_fused_many_byte_for_byte_over_seeded_rounds(version):
    rows = 0
    for rnd, seat, leaves, opened in _roots((CAPPED_SEED, 707_001, 707_002)):
        prefix = pe.HistoryPrefix.of(rnd)
        for positions, seats in ((leaves, [seat] * len(leaves)),
                                 (opened, [c.turn for c in opened])):
            for order in (slice(None), slice(None, None, -1)):
                kept, _ = _assert_same(prefix, positions[order], seats[order], version)
                rows += kept
    assert rows > 2000


@pytest.mark.parametrize("version", [1, 2, 7])
@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_batched_rows_are_fused_many_byte_for_byte_on_the_named_leaves(scenario, version):
    rnd, seat = find_root(SCENARIOS[scenario])
    leaves = leaves_for(rnd, seat, worlds_for(rnd, seat, 3, seed=len(rnd.history)))
    live = [leaf for leaf in leaves if leaf.phase == "play"]
    prefix = pe.HistoryPrefix.of(rnd)
    kept, _ = _assert_same(prefix, live, [seat] * len(live), version)
    assert kept > 0
    # every seat's perspective on the same positions
    for other in range(4):
        _assert_same(prefix, live, [other] * len(live), version)


# ------------------------------------------------- (b) the same refusals

def test_batched_rows_decline_what_fused_many_declines():
    rnd, seat, leaves, _ = next(_roots((707_001,)))
    later = next(r for i, r in enumerate(_roots((707_001,))) if i == 6)
    foreign = pe.HistoryPrefix.of(later[0])          # a longer history: not this root's
    seats = [seat] * len(leaves)
    assert pe.fused_many_batched(foreign, leaves, seats, 2) == [None] * len(leaves)
    own = pe.HistoryPrefix.of(rnd)
    assert pe.fused_many_batched(own, leaves, seats, 3) == [None] * len(leaves)    # no v3
    assert pe.fused_many_batched(own, [], [], 2) == []
    unknown = copy.copy(leaves[0])
    unknown.hands = [list(h) for h in unknown.hands]
    unknown.hands[1] = unknown.hands[1] + ["XX"]
    malformed = copy.copy(leaves[1])
    malformed.hands = [list(h) for h in malformed.hands]
    malformed.hands[2] = tuple(malformed.hands[2])
    mixed = [unknown, leaves[0], malformed, leaves[1], leaves[2]]
    for version in (1, 2, 7):
        _, refused = _assert_same(own, mixed, [seat] * len(mixed), version)
        assert refused == 2
        got = pe.fused_many_batched(own, mixed, [seat] * len(mixed), version)
        assert got[0] is None and got[2] is None and got[1] is not None


# ------------------------------------------------- (c) the callers

def test_encode_leaves_and_reply_rows_on_a_batched_prefix_are_the_unbatched_rows():
    ev = stub_evaluator(2)
    leaves_checked = replies_checked = 0
    for rnd, seat, leaves, opened in _roots((CAPPED_SEED, 707_001)):
        plain, batched = pe.HistoryPrefix.of(rnd), pe.HistoryPrefix.of(rnd, batched=True)
        assert batched.batched and not plain.batched
        if leaves:
            a = pe.encode_leaves(ev, leaves, seat, plain)
            b = pe.encode_leaves(ev, leaves, seat, batched)
            assert a is not None and b is not None
            assert a[2] == b[2] and a[3] == b[3] and a[0][[]].shape == b[0][[]].shape
            assert all(_same_row(x, y) for x, y in zip(a[1], b[1]))
            leaves_checked += len(leaves)
        if opened:
            turn = opened[0].turn
            a = pe.reply_rows(opened, turn, 2, plain)
            b = pe.reply_rows(opened, turn, 2, batched)
            assert all(x.dtype == y.dtype and x.tobytes() == y.tobytes() for x, y in zip(a, b))
            replies_checked += len(opened)
    assert leaves_checked > 500 and replies_checked > 200


# ------------------------------------------------- (d) paired lgf bots

def lgf_bot(version, batched, seed):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=8, candidates=8, cap=4000,
                               batch_size=16, leaf_greedy_finish=True, **R46_RULES)
    bot = pv.PVSearchBot(stub_predict_for(version), evaluator=stub_evaluator(version),
                         version=version, config=config, checkpoint="/dev/null", seed=seed)
    bot.encode_prefix_cache = True
    bot.leaf_greedy_stream = True
    if batched:
        bot.encode_batch_fast = True
    bot.scores = throw_loving_scores
    return bot


def _comparable(record):
    return {k: v for k, v in record.items() if not k.endswith("seconds") and not k.endswith("_ms")}


@pytest.mark.parametrize("version", [2, 7])
def test_the_batched_lgf_bot_decides_exactly_as_the_unbatched_one(version, monkeypatch):
    calls = []
    real = pe.fused_many_batched
    monkeypatch.setattr(pe, "fused_many_batched", lambda *a: calls.append(1) or real(*a))
    decisions = applied = 0
    for seed in (CAPPED_SEED, 707_001):
        rnd = _fresh_round(seed)
        plain = [lgf_bot(version, False, 100 + s) for s in range(4)]
        fast = [lgf_bot(version, True, 100 + s) for s in range(4)]
        while rnd.phase == "play":
            seat = rnd.turn
            a = plain[seat].decide_play(copy.deepcopy(rnd), seat)
            b = fast[seat].decide_play(copy.deepcopy(rnd), seat)
            ra, rb = plain[seat].last_decision_record, fast[seat].last_decision_record
            assert a == b and _comparable(ra) == _comparable(rb), (seed, len(rnd.history))
            assert LEAF_KEYS <= set(rb)
            assert plain[seat].sampler.rng.getstate() == fast[seat].sampler.rng.getstate()
            assert plain[seat]._leaf_greedy["stats"] == fast[seat]._leaf_greedy["stats"]
            assert counters(plain[seat].evaluator) == counters(fast[seat].evaluator)
            decisions += 1
            applied += bool(ra["leaf_greedy_finish_applied"])
            rnd.play(seat, a)
    assert decisions >= 80 and applied > 20 and calls
    assert np.isfinite(rb["value_means"]).all()


# ------------------------------------------------- (e) env, default and name

def test_the_switch_is_off_by_default_and_enters_no_name():
    assert pv.PVSearchBot.encode_batch_fast is False
    assert pv.LATENCY_SWITCH_ENV["encode_batch_fast"] == FLAG
    assert pv.latency_switches({})["encode_batch_fast"] is False
    assert pv.latency_switches({FLAG: "1"})["encode_batch_fast"] is True
    assert pv.latency_switches({FLAG: "0"})["encode_batch_fast"] is False
    with pytest.raises(pv.PVSearchPolicyError, match=FLAG):
        pv.latency_switches({FLAG: "yes"})
    env = {**R46_ENV, "SHENGJI_PV_CKPT": "/x.npz", "SHENGJI_PV_SHA256": "f" * 64}
    assert pv.pv_env_recipe({**env, FLAG: "1"}) == pv.pv_env_recipe(env)
    with pytest.raises(pv.PVSearchPolicyError, match=FLAG):
        pv.pv_env_recipe({**env, FLAG: "2"})
    assert "encode_batch_fast" not in vars(lgf_bot(2, False, 1))
    assert pe.HistoryPrefix.of(_fresh_round(707_001)).batched is False
