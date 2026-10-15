"""The offline world-weighting harness (`shengji.train.world_weighting`) and the
kitty-inference rows (`shengji.train.kitty_inference`).

Synthetic games from the belief-label tests stand in for trajectory shards.
"""
from __future__ import annotations

import math
from collections import Counter

import numpy as np
import pytest

from shengji.rl.encode import N_CARDS
from shengji.train import kitty_inference as ki
from shengji.train import world_weighting as ww
from test_belief_labels import synthetic_cluster
from shengji.engine.cards import Ordering
from shengji.harvest.legal import iter_lead_actions
from shengji.rl.encode import CARD_INDEX
from test_encoder_round_compat import pinned_production_package, PACKAGE_SHA


@pytest.mark.production_package
def test_production_head_complete_state_matches_enumerated_consumer(pinned_production_package, monkeypatch):
    """Real sampler, trained head, mixed history and stored consumer outputs."""
    import shengji.harvest.legal as legal
    from shengji.train.pv_search_policy import NumpyPriorPredict
    predict = NumpyPriorPredict(str(pinned_production_package), PACKAGE_SHA)
    view = _views(synthetic_cluster(1000), picks=(30,))[0]
    fast, slow = ww.Collected(), ww.Collected()
    kwargs = dict(worlds=8, cap=4000, key='s22-local-fixture',
                  state_id=0, store_index=0, cluster_index=0)
    ww.collect_state(view, predict, int(predict.version), out=fast, **kwargs)
    original_enumerate, original_legal = legal.enumerate_legal, legal.is_legal
    def reference_enumerate(*args, **kwargs):
        with monkeypatch.context() as reference:
            reference.setattr(legal, 'is_legal', original_legal)
            rnd, seat = args
            if rnd.trick.plays:
                # Previous two-pass follow consumer, independent of the
                # optimized enumerate_legal implementation.
                hand, lead, ordering = rnd.hands[seat], rnd.trick.plays[0].cards, rnd.ordering
                count = legal.count_follow_actions(hand, lead, ordering)
                actions = []
                for action in legal.iter_follow_actions(hand, lead, ordering):
                    if kwargs['cap'] is not None and len(actions) >= kwargs['cap']:
                        break
                    actions.append(list(action))
                complete = count is not None and len(actions) == count
                for extra in kwargs['must_include']:
                    if not original_legal(rnd, seat, extra):
                        raise ValueError('must_include action is illegal')
                    key = sorted(extra)
                    if key not in actions:
                        assert not complete
                        actions.append(key)
                return legal.LegalSet('follow', actions, count, complete)
            return original_enumerate(*args, **kwargs)
    monkeypatch.setattr(legal, 'enumerate_legal', reference_enumerate)
    monkeypatch.setattr(legal, 'is_legal', lambda *args: True)
    monkeypatch.setattr(legal, 'count_lead_actions', lambda *args: None)
    ww.collect_state(view, predict, int(predict.version), out=slow, **kwargs)
    assert any(m[2] for m in fast.ev_meta) and any(not m[2] for m in fast.ev_meta)
    for field in ('counts', 'agreement', 'truth', 'meta', 'ev_meta', 'kitty_x', 'ev_state'):
        np.testing.assert_array_equal(getattr(fast, field), getattr(slow, field))
    for reading in ww.READINGS:
        np.testing.assert_array_equal(fast.ev_logp[reading], slow.ev_logp[reading])


def test_impossible_historical_follow_skips_listing_but_validates_head(monkeypatch):
    import shengji.harvest.legal as legal
    from shengji.train.cwv_prior_admission import root_clone
    view = _views(synthetic_cluster(1000), picks=(30,))[0]
    d = view.decision
    _, _, worlds, _ = ww.served_worlds(d.rnd, d.seat, d.refusals, 64, 11)
    witness = None
    for i, ev in enumerate(view.events):
        if ev.seat == d.seat or not ev.snap.trick.plays:
            continue
        since = ww.played_since(view.events, i)
        for world in worlds:
            clone = root_clone(ev.snap, ww.hands_at(ev, since, d.seat, world[0]), world[1])
            if not legal.is_legal(clone, ev.seat, ev.attempted):
                witness = ev, since, world
                break
        if witness:
            break
    assert witness, 'fixture must contain a historical follow violation'
    ev, since, world = witness
    def forbidden(*args, **kwargs):
        pytest.fail('impossible history must not enumerate actions')
    monkeypatch.setattr(legal, 'enumerate_legal', forbidden)
    got = ww.event_log_probs(lambda X: np.zeros((len(X), N_CARDS)), 2,
                            ev, since, d.seat, [world])
    assert got['legal'][0] == 0
    assert all(np.isneginf(got[r][0]) for r in ww.READINGS)
    with pytest.raises(ww.WorldWeightingError, match='finite'):
        ww.event_log_probs(lambda X: np.full((len(X), N_CARDS), np.nan), 2,
                           ev, since, d.seat, [world])


@pytest.mark.parametrize('trump', ['H', None])
@pytest.mark.parametrize('scale', [0, 1, 1000, -1000])
def test_complete_lead_partition_matches_enumeration(trump, scale):
    hand = ['C3', 'C3', 'C4', 'D7', 'H7', 'S7', 'HJ', 'SJ', 'HA']
    ordering = Ordering(trump, '7')
    logits = np.random.default_rng(7).normal(size=N_CARDS) if scale == 1 else np.full(N_CARDS, scale)
    actions = list(iter_lead_actions(hand, ordering))
    scores = [sum(logits[CARD_INDEX[c]] for c in action) for action in actions]
    expected = np.logaddexp.reduce(scores)
    assert ww._lead_log_partition(hand, ordering, logits) == pytest.approx(expected, abs=1e-10)


def test_lead_likelihood_consumer_matches_old_path_and_skips_listing(cluster, monkeypatch):
    import shengji.harvest.legal as legal
    view = _views(cluster, picks=(30,))[0]
    events = [(i, ev) for i, ev in enumerate(view.events) if not ev.snap.trick.plays]
    assert events
    i, event = events[0]
    rnd, actor = view.decision.rnd, view.decision.seat
    worlds = [([list(h) for h in rnd.hands], sorted(rnd.buried))]
    since = ww.played_since(view.events, i)
    logits = np.random.default_rng(11).normal(size=N_CARDS)
    predict = lambda X: np.tile(logits, (len(X), 1))
    original = legal.enumerate_legal
    original_count = legal.count_lead_actions
    calls = []
    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(legal, 'enumerate_legal', counted)
    fast = ww.event_log_probs(predict, 2, event, since, actor, worlds, cap=None)
    assert not calls
    monkeypatch.setattr(legal, 'count_lead_actions', lambda *args: None)
    slow = ww.event_log_probs(predict, 2, event, since, actor, worlds, cap=None)
    assert calls
    for key in fast:
        np.testing.assert_allclose(fast[key], slow[key], atol=1e-12)
    calls.clear()
    monkeypatch.setattr(legal, 'count_lead_actions', original_count)
    capped = ww.event_log_probs(predict, 2, event, since, actor, worlds, cap=1)
    assert calls and capped['legal'][0] <= 2


@pytest.fixture(scope="module")
def cluster():
    for seed in range(1000, 1100):
        recs = synthetic_cluster(seed)
        if sum("engine_play" in r for r in recs) >= 1 and recs[0]["setup"]["declarations"]:
            return recs
    pytest.fail("no synthetic seed produced a failed throw")


def _views(cluster, picks=(9, 30, 47)):
    return list(ww.iter_states(cluster, want=lambda d: d.round_index == 0
                               and d.decision_index in picks))


def test_the_true_world_rebuilds_every_earlier_hand(cluster):
    views = _views(cluster)
    assert views
    for v in views:
        rnd, seat = v.decision.rnd, v.decision.seat
        assert len(v.events) == v.decision.decision_index
        for i, ev in enumerate(v.events):
            since = ww.played_since(v.events, i)
            hands = ww.hands_at(ev, since, seat, rnd.hands)
            assert [Counter(h) for h in hands] == [Counter(h) for h in ev.snap.hands]


def test_uniform_head_gives_the_uniform_legal_probability(cluster):
    v = _views(cluster, picks=(30,))[0]
    rnd, seat = v.decision.rnd, v.decision.seat
    _, _, worlds, _ = ww.served_worlds(rnd, seat, v.decision.refusals, 6, 3)
    worlds = worlds + [([list(h) for h in rnd.hands], sorted(rnd.buried))]
    zero = lambda X: np.zeros((len(X), N_CARDS))
    for i, ev in enumerate(v.events):
        if ev.seat == seat:
            continue
        got = ww.event_log_probs(zero, 2, ev, ww.played_since(v.events, i), seat, worlds)
        legal = got["legal"]
        # the true world never contradicts a play that happened
        assert legal[-1] > 0 and np.isfinite(got[ww.LISTWISE][-1])
        ok = legal > 0
        np.testing.assert_allclose(got[ww.LISTWISE][ok], -np.log(legal[ok]))
        assert np.all(np.isneginf(got[ww.LISTWISE][~ok]))
        # sigmoid(0) = 1/2 per copy in the hand
        hand = len(ev.snap.hands[ev.seat])
        np.testing.assert_allclose(got[ww.BERNOULLI][-1], hand * math.log(0.5))


def _toy(S=3, W=8):
    rng = np.random.default_rng(0)
    data = {"agreement": rng.random((S, W)).astype(np.float32),
            "meta": np.zeros((S, len(ww.META_COLS)), np.int64),
            "ev_state": np.asarray([0, 0, 1]), "ev_row": np.asarray([0, 0, 1]),
            "ev_meta": np.asarray([[0, 1, 0, 0, 5, 2], [3, 0, 1, 0, 9, 1], [1, 0, 0, 0, 2, 3]])}
    data["meta"][:, ww.META_COLS.index("trick")] = [2, 8, 20]
    lp = np.log(rng.uniform(0.001, 1.0, (3, W)))
    lp[1, 0] = ww.ILLEGAL
    data["ev_listwise"] = lp.astype(np.float16)
    data["ev_bernoulli"] = lp.astype(np.float16)
    return data


def test_uniform_weights_score_the_plain_mean_at_full_ess():
    data = _toy()
    S, W = data["agreement"].shape
    rep = ww.score(data, np.zeros((S, W)), resample=W)
    assert rep["gain"]["mean"] == pytest.approx(0.0, abs=1e-12)
    assert rep["ess_median"] == pytest.approx(W)


def test_variants_floor_filter_and_zero_illegal_worlds():
    data = _toy()
    floor = ww.variant_log_weights(data, ww.Variant("f", eps_partner=0.5, eps_opponent=0.5))
    assert np.all(floor[0] >= 2 * math.log(0.5) - 1e-9)       # two events, both floored
    assert np.all(floor[2] == 0.0)                              # no events: uniform
    zi = ww.variant_log_weights(data, ww.Variant("z", zero_illegal=True))
    assert np.isneginf(zi[0, 0]) and np.isfinite(zi[0, 1:]).all()
    legal = ww.variant_log_weights(data, ww.Variant("l", legality_only=True))
    assert np.isneginf(legal[0, 0]) and np.all(legal[0, 1:] == 0.0)
    recent = ww.variant_log_weights(data, ww.Variant("r", max_offset=1, zero_illegal=True))
    assert np.isfinite(recent[0]).all()                        # the illegal event is 3 tricks back
    kept = ww.variant_log_weights(data, ww.Variant("k", filter=True, eps_partner=0.5,
                                                   eps_opponent=0.5, min_keep=3))
    assert np.isfinite(kept[0]).sum() >= 3


def test_marginal_weights_vanish_when_the_model_is_the_proposal():
    rng = np.random.default_rng(1)
    counts = rng.integers(0, 3, (16, 4, N_CARDS)).astype(np.uint8)
    tot = counts.sum(axis=(0, 1)).astype(np.float64)
    base = np.where(tot > 0, counts.sum(axis=0) / np.maximum(tot, 1), 0.0)
    np.testing.assert_allclose(ww.marginal_log_weights(counts, base), 0.0, atol=1e-9)


def test_kitty_rows_hold_the_declared_width_and_consistent_labels(cluster):
    from shengji.harvest.rebuild import round_from_setup
    rec = cluster[0]
    start = round_from_setup(list(rec["deck"]), rec["setup"])
    for seat in range(4):
        if seat == start.banker:
            continue
        x = ki.features(start, seat, rec["setup"])
        assert x.shape == (ki.FEATURE_DIM,)
        lab = ki.labels(start, seat)
        h = lab["hidden"].astype(np.float64)
        assert lab["kitty"].sum() == 8 and lab["banker"].sum() == len(start.hands[start.banker])
        # the sampler marginal places exactly the kitty's and the banker's copies
        assert (h * lab["p_sampler_kitty"]).sum() == pytest.approx(8, rel=1e-5)
        assert (h * lab["p_sampler_banker"]).sum() == pytest.approx(lab["banker"].sum(), rel=1e-5)
        uni = ki.uniform_p(h[None], np.asarray([8.0]))
        assert (h[None] * uni).sum() == pytest.approx(8.0)
        # the head's loss at the uniform marginal is the uniform baseline
        assert ki.copy_log_loss(uni, lab["kitty"][None], lab["hidden"][None])[0] > 0


def test_collected_states_replay_to_the_same_decisions(cluster, tmp_path):
    import json
    shards = tmp_path / "store" / "shards"
    shards.mkdir(parents=True)
    with open(shards / "cluster-000000.jsonl", "w") as fh:
        for rec in cluster:
            fh.write(json.dumps(rec) + "\n")
    meta = np.zeros((2, len(ww.META_COLS)), np.int64)
    for i, (sid, dec) in enumerate(((7, 12), (9, 33))):
        meta[i, ww.META_COLS.index("state")] = sid
        meta[i, ww.META_COLS.index("decision")] = dec
    got = {sid: view.decision.decision_index
           for sid, view in ww.iter_collected_states([str(tmp_path / "store")], meta)}
    assert got == {7: 12, 9: 33}
