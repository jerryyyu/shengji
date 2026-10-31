"""S17 history-input belief: the history extract (`belief_history`) and the
model/sampler pieces of `belief_seq` that can run without a trained model.

Synthetic games from ``test_belief_labels`` stand in for trajectory shards.
"""
from __future__ import annotations

import json
import copy
from collections import Counter

import numpy as np
import pytest

from shengji.rl.encode import CARD_INDEX
from shengji.train import belief_history as bh
from shengji.train import belief_labels as bl

from test_belief_labels import synthetic_cluster


@pytest.fixture(scope="module")
def chunk(tmp_path_factory):
    """Two synthetic clusters extracted as one chunk, with their history."""
    root = tmp_path_factory.mktemp("s17h")
    shards = root / "store" / "shards"
    shards.mkdir(parents=True)
    recs_by_cluster = []
    for k, seed in enumerate((1003, 1017)):
        recs = synthetic_cluster(seed)
        recs_by_cluster.append(recs)
        with open(shards / f"cluster-{k:06d}.jsonl", "w") as fh:
            for r in recs:
                fh.write(json.dumps(r) + "\n")
    paths = bl.cluster_paths(root / "store")
    parts = [bl.extract_cluster(p, store_index=0, cluster_index=i, calib=0.0, test=0.0, windows=[],
                                sampler_worlds=0, sampler_splits=()) for i, p in enumerate(paths)]
    arrays = {k: np.concatenate([p[k] for p in parts]) for k in bl.ARRAY_KEYS}
    np.savez(root / "train-x.npz", **arrays)
    hist = bh.chunk_history(str(root / "train-x.npz"), [str(p) for p in paths])
    return {"rows": arrays, "hist": hist, "records": recs_by_cluster}


def test_every_row_gets_exactly_the_plays_before_it(chunk):
    rows, hist = chunk["rows"], chunk["hist"]
    by_ref = {}
    for c, recs in enumerate(chunk["records"]):
        for r in bl.game_order(recs):
            by_ref[(c, len(by_ref))] = r
    ordered = [r for recs in chunk["records"] for r in bl.game_order(recs)]
    assert len(ordered) == len(rows["X"]) == len(hist["row_ply"])
    for i, rec in enumerate(ordered):
        rid, ply = hist["row_round"][i], hist["row_ply"][i]
        prefix = rec["plays_prefix"]
        assert ply == len(prefix)
        assert hist["row_seat"][i] == rec["seat"]
        # the row's visible history is tokens[:ply]: exactly the public prefix
        for t, play in enumerate(prefix):
            assert hist["tok_int"][rid, t, 0] == play["seat"]
            got = Counter({code: int(n) for code, n in zip(sorted(CARD_INDEX, key=CARD_INDEX.get),
                                                           hist["tok_cards"][rid, t]) if n})
            assert got == Counter(play["cards"])
        # the token AT ply is the actor's own decision (never read by its row)
        assert hist["tok_int"][rid, ply, 0] == rec["seat"]
        assert hist["tok_int"][rid, ply, 2] == rows["trick"][i] - 1


def test_refused_throws_carry_their_attempt_and_nothing_else_does(chunk):
    hist = chunk["hist"]
    failed = hist["tok_f"][..., bh.TOKEN_FLOAT.index("failed_throw")] > 0
    has_att = hist["tok_att"].sum(-1) > 0
    assert failed.any()
    assert np.array_equal(failed, has_att)
    n_refused = sum("engine_play" in r for recs in chunk["records"] for r in recs)
    assert int(failed.sum()) == n_refused
    # a refused throw is a lead, and the accepted cards are a sub-multiset of the attempt
    assert (hist["tok_int"][..., 1][failed] == 0).all()
    assert (hist["tok_cards"][failed] <= hist["tok_att"][failed]).all()


def test_card_features_follow_the_round_trump(chunk):
    cf = chunk["hist"]["card_feat"].astype(np.float32)
    assert cf.shape[1:] == (54, bh.N_CARD_FEATURES)
    # jokers are always trump; every card has exactly one effective suit
    for j in ("LJ", "BJ"):
        assert (cf[:, CARD_INDEX[j], 0] == 1).all()
    assert np.allclose(cf[:, :, 1:6].sum(-1), 1.0)


@pytest.mark.parametrize('field', ['seat', 'cards'])
def test_history_replay_refuses_corrupted_prefix_contents(chunk, field):
    records = copy.deepcopy(chunk['records'][0])
    rec = next(r for r in records if r.get('plays_prefix'))
    tail = rec['plays_prefix'][-1]
    if field == 'seat':
        tail['seat'] = (int(tail['seat']) + 1) % 4
    else:
        tail['cards'][0] = 'C2' if tail['cards'][0] != 'C2' else 'D2'
    with pytest.raises(bl.BeliefLabelError, match="differs from the record's prefix"):
        list(bh.replay_round_tokens(records))


def test_history_replay_accepts_prefix_card_permutations(chunk):
    records = copy.deepcopy(chunk['records'][0])
    for rec in records:
        for play in rec.get('plays_prefix', []):
            play['cards'].reverse()
    expected = list(bh.replay_round_tokens(chunk['records'][0]))
    actual = list(bh.replay_round_tokens(records))
    assert len(actual) == len(expected)
    for left, right in zip(actual, expected):
        assert left[0] == right[0] and left[3:] == right[3:]
        np.testing.assert_array_equal(left[2], right[2])
        for a, b in zip(left[1], right[1]):
            for key in a:
                np.testing.assert_array_equal(a[key], b[key])


def test_a_misaligned_chunk_is_refused(chunk, tmp_path):
    rows = dict(chunk["rows"])
    rows["trick"] = rows["trick"].copy()
    rows["trick"][7] += 1
    np.savez(tmp_path / "bad.npz", **rows)
    root_paths = None
    # reuse the fixture's shards through the records: rewrite them next to the bad chunk
    shards = tmp_path / "store" / "shards"
    shards.mkdir(parents=True)
    for k, recs in enumerate(chunk["records"]):
        with open(shards / f"cluster-{k:06d}.jsonl", "w") as fh:
            for r in recs:
                fh.write(json.dumps(r) + "\n")
    root_paths = [str(p) for p in bl.cluster_paths(tmp_path / "store")]
    with pytest.raises(bl.BeliefLabelError):
        bh.chunk_history(str(tmp_path / "bad.npz"), root_paths)


def test_sampled_worlds_are_legal():
    from shengji.train import belief_seq as bs
    rng = np.random.default_rng(0)
    for _ in range(30):
        n_c = rng.integers(0, 3, size=54)
        M = rng.random((54, 4)) < 0.7
        M[n_c == 0] = False
        M[(n_c > 0) & ~M.any(-1), 0] = True
        # sizes from one legal assignment, so the state is feasible
        true = np.zeros((54, 4), np.int64)
        for c in range(54):
            for _ in range(n_c[c]):
                true[c, rng.choice(np.flatnonzero(M[c]))] += 1
        sizes = true.sum(0)
        P = rng.random((54, 4)) * M
        P = P / np.maximum(P.sum(-1, keepdims=True), 1e-12)
        P = bs.project_sizes(P, n_c, sizes, M)
        W = bs.sample_worlds(P, n_c, M, sizes, 8, rng)
        assert (W.sum(-1) == n_c[None]).all()            # every copy placed once
        assert (W.sum(1) == sizes[None]).all()           # every receiver exactly full
        assert not (W[:, ~M] > 0).any()                  # only feasible receivers
        a = bs.world_agreement(W, true)
        assert ((a >= 0) & (a <= 1)).all()
        assert bs.world_agreement(true[None].astype(np.int16), true)[0] == 1.0


@pytest.mark.parametrize('mass', [1.0, 1e-20, np.nextafter(0.0, 1.0), 0.0])
@pytest.mark.parametrize('receiver', range(4))
@pytest.mark.parametrize('uniform', [0.0, 0.5, np.nextafter(1.0, 0.0)])
def test_sampler_numerical_boundaries_preserve_feasibility(mass, receiver, uniform):
    from shengji.train import belief_seq as bs
    class FixedRng:
        def permutation(self, n):
            return np.arange(n)
        def random(self, n):
            return np.full(n, uniform)
    copies = np.zeros(54, dtype=int)
    copies[0] = 1
    mask = np.zeros((54, 4), dtype=bool)
    mask[0, receiver] = True
    probabilities = np.ones((54, 4))  # excluded receivers may carry large mass
    probabilities[0, receiver] = mass
    sizes = np.eye(4, dtype=int)[receiver]
    worlds = bs.sample_worlds(probabilities, copies, mask, sizes, 2, FixedRng())
    np.testing.assert_array_equal(worlds[:, 0], np.tile(sizes, (2, 1)))
    assert not worlds[:, ~mask].any()


@pytest.mark.parametrize('bad', [np.nan, np.inf, -1.0])
def test_sampler_refuses_invalid_probabilities(bad):
    from shengji.train import belief_seq as bs
    probabilities = np.ones((54, 4))
    probabilities[0, 0] = bad
    with pytest.raises(bs.BeliefSeqError, match='finite and nonnegative'):
        bs.sample_worlds(probabilities, np.ones(54, dtype=int),
                        np.ones((54, 4), dtype=bool), np.array([14,14,13,13]),
                        2, np.random.default_rng(0))


def test_the_model_reads_only_plays_before_the_row():
    torch = pytest.importorskip("torch")
    from shengji.train import belief_seq as bs
    from shengji.train.belief_labels import FEATURE_DIM
    torch.manual_seed(0)
    model = bs.build_model(d=16, heads=2, x_hidden=16).eval()
    rng = np.random.default_rng(1)
    R, T, B = 2, 12, 4
    b = {"tok_int": np.stack([rng.integers(0, 4, (R, T)), rng.integers(0, 4, (R, T)),
                              rng.integers(0, 25, (R, T)), rng.integers(0, 5, (R, T))], -1),
         "tok_f": rng.random((R, T, bh.N_TOKEN_FLOAT)).astype(np.float32),
         "tok_cards": (rng.random((R, T, 54)) < 0.05).astype(np.float32),
         "tok_att": np.zeros((R, T, 54), np.float32),
         "card_feat": rng.random((R, 54, bh.N_CARD_FEATURES)).astype(np.float32),
         "banker": np.array([0, 2]),
         "X": rng.random((B, FEATURE_DIM + 4)).astype(np.float32),
         "row_card": rng.random((B, 54, bs.N_ROW_CARD)).astype(np.float32),
         "M": np.ones((B, 54, 4), bool), "Y": np.zeros((B, 54, 4), np.float32),
         "rr": np.array([0, 0, 1, 1]), "seat": np.array([1, 2, 0, 3]), "ply": np.array([3, 7, 0, 5])}
    with torch.no_grad():
        base = model(bs.to_torch(b)).numpy()
        later = {k: v.copy() for k, v in b.items()}
        # rewrite every token at or after each row's ply (rows 0/1 share round 0: from ply 3)
        later["tok_cards"][0, 3:] = 1 - later["tok_cards"][0, 3:]
        later["tok_f"][0, 3:] += 1.0
        later["tok_cards"][1, 0:] = 1 - later["tok_cards"][1, 0:]
        got = model(bs.to_torch(later)).numpy()
        assert np.allclose(got[0], base[0], atol=1e-5)    # ply 3 sees tokens 0..2 only
        assert np.allclose(got[2], base[2], atol=1e-5)    # ply 0 sees nothing
        assert not np.allclose(got[1], base[1], atol=1e-5)  # ply 7 sees the rewritten 3..6
        # an earlier token does move a row that can see it
        earlier = {k: v.copy() for k, v in b.items()}
        earlier["tok_cards"][1, 2] = 1 - earlier["tok_cards"][1, 2]
        assert not np.allclose(model(bs.to_torch(earlier)).numpy()[3], base[3], atol=1e-6)

@pytest.mark.parametrize("mode", ["close", "complete", "error"])
def test_stream_releases_producer_on_close_completion_or_error(monkeypatch, mode):
    import threading
    from shengji.train import belief_seq as bs

    threads = []
    original_thread = threading.Thread

    def track_thread(*args, **kwargs):
        thread = original_thread(*args, **kwargs)
        threads.append(thread)
        return thread

    monkeypatch.setattr(bs.threading, "Thread", track_thread)
    monkeypatch.setattr(bs, "load_part", lambda *args, **kwargs: {})
    monkeypatch.setattr(bs, "concat_parts", lambda parts: {})
    monkeypatch.setattr(bs, "round_batches",
                        lambda *args: ((i, i) for i in range(20)))

    def make_batch(part, round_ids, rows, no_history):
        if mode == "error" and rows == 2:
            raise ValueError("synthetic loader error")
        return {"row": rows}

    monkeypatch.setattr(bs, "make_batch", make_batch)
    stream = bs.Stream([{"rows": 20}], verified=bs._Verified(), threads=1,
                       buffer_chunks=1, rounds_per_batch=1, row_frac=1,
                       no_history=False, permute=False)
    batches = stream.batches(1, 0, prefetch=1)
    assert next(batches) == (0, {"row": 0})
    if mode == "close":
        batches.close()
    elif mode == "error":
        with pytest.raises(ValueError, match="synthetic loader error"):
            list(batches)
    else:
        assert [batch["row"] for _, batch in batches] == list(range(1, 20))
    assert threads and all(not thread.is_alive() for thread in threads)
