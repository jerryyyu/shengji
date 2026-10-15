"""M11 infoset-Q and S25 human-seat helpers (`shengji.train.infoset_q`,
`shengji.train.human_seat`): ballot filtering, the tie-aware agreement metric,
trick buckets, actor-view privacy of the history and candidate features, and the
segment NLL arithmetic.  No package is loaded."""
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


def test_segment_nll_matches_a_direct_softmax():
    logits = np.asarray([1.0, 2.0, 0.5, -1.0, 3.0])
    offsets = np.asarray([0, 3, 5])
    chosen = np.asarray([1, 0])
    flat, seg, _ = hs._segments(offsets, np.arange(2))
    nll = hs.nll_from_logits(logits[flat], seg, 2, hs._local(seg, chosen))
    a = logits[:3]
    b = logits[3:]
    want = [-(a[1] - np.log(np.exp(a).sum())), -(b[0] - np.log(np.exp(b).sum()))]
    assert np.allclose(nll, want)
    # a subset keeps its chosen positions local to its own layout
    flat1, seg1, _ = hs._segments(offsets, np.asarray([1]))
    one = hs.nll_from_logits(logits[flat1], seg1, 1, hs._local(seg1, chosen[1:]))
    assert np.allclose(one, want[1:])


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
    t = hs.fit_temperature(pref[flat], seg, len(lens), hs._local(seg, chosen))
    assert 1.7 < t < 2.3
