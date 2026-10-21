"""The batched prefix encoding under ``SHENGJI_PV_ENCODE_PREFIX_CACHE=1``:
`pv_encode_prefix.fused_many` (the value leaves of one decision root, the
prefix laid down once per batch) and `pv_encode_prefix.reply_rows` (the
``lgf`` greedy finish's reply policy rows on the same prefix).

Torch-free and package-free.  Witnesses: (a) every row `fused_many` builds is
`HistoryPrefix.fused` + `_widened`'s and the static route's tensor byte for
byte at encoder v1, v2 and v7, and it declines exactly the rows ``fused``
declines; (b) `reply_rows` is ``flat_input(root_tensors(...))`` byte for byte,
on the prefix, past rows the prefix does not cover and when the batch check
fails; (c) paired ``lgf`` bots over seeded rounds decide identically with the
switch on (cards, record, sampler state, the finish's counters).  The served
bot on the pinned packages is `test_pv_leaf_greedy_stream` (d), which runs
this encoding with the switch on.
"""
import copy

import numpy as np
import pytest

from shengji.ai.cwv_policy import afterstate
from shengji.ai.cwv_static_encoding import tensors_from_round_static
from shengji.ai.heuristic import HeuristicBot
from shengji.harvest.legal import enumerate_legal
from shengji.train import pv_encode_prefix as pe
from shengji.train.policy_prior import flat_input, root_tensors
from test_pv_doomed_throw_reselect import HashNoiseEvaluator, throw_loving_scores
from test_pv_leaf_greedy_finish import LEAF_KEYS, R46_RULES, leaf_bot
from test_pv_small_joker_lead import _fresh_round

#: a heuristic round with a capped (4000) follow listing on its first trick
CAPPED_SEED = 707_014


def _comparable(record):
    return {k: v for k, v in record.items() if not k.endswith("seconds") and not k.endswith("_ms")}


def _roots(seeds):
    """``(root, seat, value leaves, open clones)`` at every decision of
    heuristic-played rounds: the root's first legal actions applied in the
    true deal, as the finished value leaves and as the clones whose trick is
    still open (the reply ply's)."""
    helper = HeuristicBot()
    for seed in seeds:
        rnd = _fresh_round(seed)
        while rnd.phase == "play":
            seat = rnd.turn
            actions = [list(a) for a in enumerate_legal(rnd, seat, cap=12).actions[:12]]
            clones = [afterstate(rnd, seat, rnd.hands, rnd.buried, a) for a in actions]
            leaves = [afterstate(rnd, seat, rnd.hands, rnd.buried, a, finish_trick=True)
                      for a in actions]
            opened = [c for c in clones if c.phase == "play" and len(c.history) == len(rnd.history)]
            yield rnd, seat, [leaf for leaf in leaves if leaf.phase == "play"], opened
            rnd.play(seat, helper.decide_play(rnd, seat))


def _same(a, b):
    return a.dtype == b.dtype and a.shape == b.shape and a.tobytes() == b.tobytes()


# ------------------------------------------------------- (a) fused_many

@pytest.mark.parametrize("version", [1, 2, 7])
def test_fused_many_is_fused_and_the_static_route_byte_for_byte(version):
    rows = declined = 0
    for rnd, seat, leaves, opened in _roots((CAPPED_SEED, 707_001)):
        prefix = pe.HistoryPrefix.of(rnd)
        # the value leaves from the root seat; the open clones from the seat to act
        for positions, seats in ((leaves, [seat] * len(leaves)),
                                 (opened, [c.turn for c in opened])):
            many = pe.fused_many(prefix, positions, seats, version)
            assert len(many) == len(positions)
            for position, s, got in zip(positions, seats, many):
                parts = prefix.fused(position, s)
                if parts is None:
                    assert got is None
                    declined += 1
                    continue
                one = pe._widened(version, *parts, position, s)
                ref = tensors_from_round_static(position, s, version=version)
                assert type(got) is type(one)
                for field in ("public", "world", "perspective", "history"):
                    assert _same(getattr(got, field), getattr(one, field)), field
                for field in ("public", "world", "perspective"):
                    assert _same(getattr(got, field), getattr(ref, field)), field
                rows += 1
    assert rows > 1000


def test_fused_many_declines_what_fused_declines():
    rnd, seat, leaves, _ = next(_roots((707_001,)))
    later = next(r for i, r in enumerate(_roots((707_001,))) if i == 6)
    prefix = pe.HistoryPrefix.of(later[0])          # a longer history: not this root's
    assert all(prefix.fused(leaf, seat) is None for leaf in leaves)
    assert pe.fused_many(prefix, leaves, [seat] * len(leaves), 2) == [None] * len(leaves)
    own = pe.HistoryPrefix.of(rnd)
    assert pe.fused_many(own, leaves, [seat] * len(leaves), 3) == [None] * len(leaves)  # no v3
    assert pe.fused_many(own, [], [], 2) == []
    bad = copy.copy(leaves[0])
    bad.hands = [list(h) for h in bad.hands]
    bad.hands[1] = bad.hands[1] + ["XX"]             # an unknown card
    assert own.fused(bad, seat) is None
    assert pe.fused_many(own, [bad, leaves[0]], [seat, seat], 2)[0] is None


# ------------------------------------------------------ (b) reply_rows

def test_reply_rows_are_the_reference_policy_rows_byte_for_byte(monkeypatch):
    rows = 0
    for rnd, _, _, opened in _roots((CAPPED_SEED, 707_001, 707_002)):
        if not opened:
            continue
        seat = opened[0].turn
        prefix = pe.HistoryPrefix.of(rnd)
        reference = [flat_input(root_tensors(c, seat, 2), 2) for c in opened]
        got = pe.reply_rows(opened, seat, 2, prefix)
        assert len(got) == len(reference)
        assert all(_same(a, b) for a, b in zip(got, reference))
        rows += len(got)
    assert rows > 500
    # rows the prefix does not cover take the reference, row by row
    rnd, _, _, opened = next(r for r in _roots((707_001,)) if r[3] and len(r[0].history) >= 2)
    seat = opened[0].turn
    other = pe.HistoryPrefix.of(next(r for i, r in enumerate(_roots((707_002,))) if i == 4)[0])
    reference = [flat_input(root_tensors(c, seat, 2), 2) for c in opened]
    assert all(_same(a, b) for a, b in zip(pe.reply_rows(opened, seat, 2, other), reference))
    assert all(_same(a, b) for a, b in zip(pe.reply_rows(opened, seat, 2, None), reference))
    # a failed batch check re-encodes the whole call by the reference
    calls = []
    monkeypatch.setattr(pe, "_valid_batch", lambda built, version: calls.append(len(built)) or False)
    got = pe.reply_rows(opened, seat, 2, pe.HistoryPrefix.of(rnd))
    assert calls and all(_same(a, b) for a, b in zip(got, reference))


# ------------------------------------- (c) paired lgf bots, switch on/off

def test_the_prefix_encoded_lgf_bot_is_the_plain_one_over_seeded_rounds(monkeypatch):
    calls = []
    real = pe.reply_rows
    monkeypatch.setattr(pe, "reply_rows", lambda *a: calls.append(1) or real(*a))
    evaluator = HashNoiseEvaluator()
    decisions = applied = 0
    for seed in (CAPPED_SEED, 707_001):
        rnd = _fresh_round(seed)
        plain = [leaf_bot(evaluator, worlds=8, seed=100 + s, **R46_RULES) for s in range(4)]
        fast = [leaf_bot(evaluator, worlds=8, seed=100 + s, **R46_RULES) for s in range(4)]
        for bot in fast:
            bot.encode_prefix_cache = True
            bot.leaf_greedy_stream = True
        for bot in plain + fast:
            bot.scores = throw_loving_scores
        while rnd.phase == "play":
            seat = rnd.turn
            a = plain[seat].decide_play(copy.deepcopy(rnd), seat)
            b = fast[seat].decide_play(copy.deepcopy(rnd), seat)
            ra, rb = plain[seat].last_decision_record, fast[seat].last_decision_record
            assert a == b and _comparable(ra) == _comparable(rb), (seed, len(rnd.history))
            assert LEAF_KEYS <= set(rb)
            assert plain[seat].sampler.rng.getstate() == fast[seat].sampler.rng.getstate()
            assert plain[seat]._leaf_greedy["stats"] == fast[seat]._leaf_greedy["stats"]
            decisions += 1
            applied += bool(ra["leaf_greedy_finish_applied"])
            rnd.play(seat, a)
    assert decisions >= 80 and applied > 20 and calls


def test_without_the_switch_the_ply_encodes_by_the_reference(monkeypatch):
    monkeypatch.setattr(pe, "reply_rows", lambda *a: pytest.fail("reply_rows without the switch"))
    rnd = _fresh_round(CAPPED_SEED)
    bot = leaf_bot(HashNoiseEvaluator(), worlds=4, **R46_RULES)
    bot.decide_play(copy.deepcopy(rnd), rnd.turn)
    assert bot.last_decision_record["leaf_greedy_finish_applied"]
    assert np.isfinite(bot.last_decision_record["value_means"]).all()
