"""M11 infoset-Q and S25 human-seat helpers (`shengji.train.infoset_q`,
`shengji.train.human_seat`): ballot filtering, the tie-aware agreement metric,
trick buckets, actor-view privacy of the history and candidate features, and the
label-free action support with its normalised NLL.  No package is loaded."""
from __future__ import annotations

import copy
import random
import sys
from pathlib import Path

import numpy as np
import pytest

from shengji.train import human_seat as hs
from shengji.train import infoset_q as iq
from shengji.train.belief_labels import iter_decisions

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_belief_labels import synthetic_cluster  # noqa: E402


def test_production_ballot_drops_exploration_draws():
    rec = {"ballot": [["S2"], ["H3", "H3"], ["D4"], ["C5"]],
           "exploration": {"added": [["C5"], ["H3", "H3"]]}}
    cands, idx = iq.production_ballot(rec)
    assert cands == [["S2"], ["D4"]]
    assert idx == [0, 2]
    with pytest.raises(iq.InfosetQError):
        iq.production_ballot({"ballot": [["S2"]], "exploration": {"added": [["D4"]]}})


def test_agreement_counts_ties_and_regret_is_in_value_units():
    T = np.asarray([[1.0, 1.0, 0.5, 0.0], [0.2, 0.9, 0.3, 0.0]], np.float32)
    M = np.asarray([[True, True, True, False], [True, True, True, False]])
    agree, regret = iq.outcome(np.asarray([1, 2]), T, M)
    assert agree.tolist() == [True, False]
    assert np.allclose(regret, [0.0, 0.6])
    # a padded slot never wins the argmax
    assert iq.choose(np.asarray([[0.0, -1.0, -2.0, 5.0]]), M[:1]).tolist() == [0]


def test_trick_buckets_match_labels():
    got = iq.trick_bucket(np.asarray([1, 5, 6, 10, 11, 15, 16, 20, 21, 25]))
    assert got.tolist() == [0, 0, 1, 1, 2, 2, 3, 3, 4, 4]
    assert len(iq.TRICK_BUCKETS) == 5


def _shuffle_hidden(rnd, seat, rng):
    other = [s for s in range(4) if s != seat]
    pool = [c for s in other for c in rnd.hands[s]] + list(rnd.buried)
    rng.shuffle(pool)
    out = copy.deepcopy(rnd)
    at = 0
    for s in other:
        out.hands[s] = pool[at:at + len(rnd.hands[s])]
        at += len(rnd.hands[s])
    out.buried = pool[at:]
    return out


def test_history_and_candidate_features_read_no_hidden_cards():
    rng = random.Random(7)
    seen = 0
    for d in iter_decisions(synthetic_cluster(3)):
        if d.decision_index % 7:
            continue
        h = iq.history_summary(d.rnd, d.seat)
        assert h.shape == (iq.HIST_DIM,) and np.isfinite(h).all()
        action = list(d.record["action"])
        c = iq.candidate_features(d.rnd, d.seat, action)
        assert c.shape == (iq.CAND_DIM,)
        other = _shuffle_hidden(d.rnd, d.seat, rng)
        assert np.array_equal(h, iq.history_summary(other, d.seat))
        assert np.array_equal(c, iq.candidate_features(other, d.seat, action))
        seen += 1
    assert seen > 5


def test_normalized_nll_is_the_softmax_on_a_complete_support():
    logits = np.asarray([1.0, 2.0, 0.5, -1.0, 3.0])
    offsets = np.asarray([0, 3, 5])
    flat, seg, _ = hs._segments(offsets, np.arange(2))
    nll = hs.normalized_nll(logits[flat], seg, 2, np.asarray([1, 0]), np.asarray([0, 0]))
    a, b = logits[:3], logits[3:]
    want = [-(a[1] - np.log(np.exp(a).sum())), -(b[0] - np.log(np.exp(b).sum()))]
    assert np.allclose(nll, want)


def test_normalized_nll_prices_the_remainder_at_the_support_floor():
    logits = np.asarray([2.0, 0.0, 1.0])
    seg = np.zeros(3, int)
    rem = np.asarray([4])
    total = 0.0
    for chosen in (0, 1, 2):
        total += float(np.exp(-hs.normalized_nll(logits, seg, 1, np.asarray([chosen]), rem)[0]))
    outside = float(np.exp(-hs.normalized_nll(logits, seg, 1, np.asarray([-1]), rem)[0]))
    assert np.isclose(outside, np.exp(0.0) / (np.exp(logits).sum() + 4 * np.exp(0.0)))
    assert np.isclose(total + 4 * outside, 1.0)


def _lead_state(cards_wanted=3):
    """A live lead decision whose actor holds three plain cards of one non-trump
    suit and no trump-rank card: seven legal leads (three singles, three
    two-card throws, one three-card throw)."""
    for d in iter_decisions(synthetic_cluster(5)):
        if d.rnd.trick.plays:
            continue
        rnd = copy.deepcopy(d.rnd)
        o = rnd.ordering
        for suit in "SHCD":
            ranks = [r for r in ("3", "4", "5", "6", "7", "8", "9")
                     if r != rnd.trump_rank]
            cards = [suit + r for r in ranks[:cards_wanted]]
            if all(o.eff_suit(c) == suit for c in cards):
                rnd.hands[d.seat] = cards
                return rnd, d.seat, cards
    raise AssertionError("no lead state")


@pytest.mark.parametrize("cap", [None, 2])
def test_producer_support_is_label_free_and_the_likelihood_sums_to_one(cap):
    from itertools import combinations
    from shengji.harvest.legal import enumerate_legal
    rnd, seat, cards = _lead_state()
    full = enumerate_legal(rnd, seat, cap=None)
    assert full.complete and full.count == 7
    legal = [sorted(c) for k in (1, 2, 3) for c in combinations(cards, k)]
    assert sorted(map(tuple, full.actions)) == sorted(map(tuple, legal))
    anchor = [cards[0]]
    support, remainder = hs.action_support(rnd, seat, anchor, cap)
    assert len(support) + remainder == 7
    if cap is not None:
        assert remainder > 0
    keys = [tuple(sorted(a)) for a in support]
    logits = np.zeros(len(support))            # the witness: all-equal scores
    seg = np.zeros(len(support), int)
    total = 0.0
    for observed in legal:
        # the producer takes no observed action: the support is the same object
        again, again_rem = hs.action_support(rnd, seat, anchor, cap)
        assert [tuple(sorted(a)) for a in again] == keys and again_rem == remainder
        k = tuple(sorted(observed))
        chosen = keys.index(k) if k in keys else -1
        p = float(np.exp(-hs.normalized_nll(logits, seg, 1, np.asarray([chosen]),
                                            np.asarray([remainder]))[0]))
        assert np.isclose(p, 1 / 7)
        total += p
    assert np.isclose(total, 1.0)


def test_fitted_temperature_recovers_a_sharpened_softmax():
    rng = np.random.default_rng(0)
    lens = rng.integers(2, 9, 3000)
    offsets = np.concatenate([[0], np.cumsum(lens)])
    pref = rng.normal(size=offsets[-1])
    chosen = []
    for i, n in enumerate(lens):
        p = np.exp(2.0 * pref[offsets[i]:offsets[i + 1]])
        chosen.append(rng.choice(n, p=p / p.sum()))
    chosen = np.asarray(chosen)
    flat, seg, _ = hs._segments(offsets, np.arange(len(lens)))
    t = hs.fit_temperature(pref[flat], seg, len(lens), chosen, np.zeros(len(lens), int))
    assert 1.7 < t < 2.3
