"""S17 belief worlds: the NumPy runtime (`ai.belief_numpy`) and the offline
proposal pieces of `train.belief_sampler` that need no trained model.

Synthetic games from ``test_belief_labels`` stand in for trajectory shards; a
small random-weight model stands in for the trained one.
"""
from __future__ import annotations

import json
from collections import Counter

import numpy as np
import pytest

from shengji.ai import belief_numpy as bn
from shengji.train import belief_history as bh
from shengji.train import belief_labels as bl
from shengji.train import belief_sampler as bsm

from test_belief_labels import synthetic_cluster

SMALL = {"d": 16, "heads": 2, "enc_layers": 2, "xattn_layers": 2, "x_hidden": 16,
         "card_self_attn": True}


def test_runtime_widths_are_the_training_widths():
    from shengji.train import belief_seq as bs
    assert bn.DIMS == {"feature_dim": bl.FEATURE_DIM, "n_card_features": bh.N_CARD_FEATURES,
                       "n_token_float": bh.N_TOKEN_FLOAT, "n_row_card": bs.N_ROW_CARD,
                       "max_plays": bh.MAX_PLAYS}


@pytest.fixture(scope="module", params=["2", "7"], ids=["rank2", "rank7"])
def chunk(tmp_path_factory, request):
    """Synthetic clusters extracted as one chunk with their history, plus the
    replayed decisions (so a test can run the live featurizer at every row)."""
    root = tmp_path_factory.mktemp("s17s")
    shards = root / "store" / "shards"
    shards.mkdir(parents=True)
    for k, seed in enumerate((1003, 1017)):
        with open(shards / f"cluster-{k:06d}.jsonl", "w") as fh:
            for r in synthetic_cluster(seed, trump_rank=request.param):
                fh.write(json.dumps(r) + "\n")
    paths = bl.cluster_paths(root / "store")
    parts = [bl.extract_cluster(p, store_index=0, cluster_index=i, calib=0.0, test=0.0, windows=[],
                                sampler_worlds=0, sampler_splits=()) for i, p in enumerate(paths)]
    arrays = {k: np.concatenate([p[k] for p in parts]) for k in bl.ARRAY_KEYS}
    np.savez(root / "train-x.npz", **arrays)
    hist = bh.chunk_history(str(root / "train-x.npz"), [str(p) for p in paths])
    return {"rows": arrays, "hist": hist, "paths": paths, "root": root,
            "trump_rank": request.param}


def _model_batch(chunk):
    """The chunk's rows as one ``belief_seq.make_batch`` batch (all rounds)."""
    from shengji.train import belief_seq as bs
    from shengji.train.belief_eval import residualize
    part = {k: chunk["rows"][k] for k in ("X", "Y", "M", "sizes", "trick", "role")}
    part = {k: v.copy() for k, v in part.items()}
    residualize(part)
    part.update({k: chunk["hist"][k] for k in ("row_round", "row_ply", "row_seat")})
    part["_rounds"] = {k: chunk["hist"][k] for k in ("tok_int", "tok_f", "tok_cards", "tok_att",
                                                     "round_n", "card_feat", "banker")}
    rids = np.unique(part["row_round"])
    rows = np.arange(len(part["X"]))
    return bs.make_batch(part, rids, rows)


def test_the_live_featurizer_rebuilds_every_extract_row(chunk):
    from shengji.train import belief_seq as bs
    batch = _model_batch(chunk)
    i = 0
    for path in chunk["paths"]:
        recs = [r for r in bl._read_records(path) if r.get("decision_kind") == "play"]
        for d in bl.iter_decisions(recs):
            assert d.rnd.trump_rank == chunk["trump_rank"]
            inp = bn.decision_inputs(d.rnd, d.seat, d.refusals)
            ref = bsm.row_inputs(batch, i)
            for k in ("X", "row_card", "M", "card_feat", "tok_int", "tok_f", "tok_cards", "tok_att"):
                a, r = np.asarray(inp[k]), np.asarray(ref[k])
                assert a.shape == r.shape, k
                assert np.array_equal(a.astype(np.float64), r.astype(np.float64)), k
            assert inp["seat"] == ref["seat"] and inp["banker"] == ref["banker"]
            # residual bookkeeping: the unknown copies fill the unknown slots
            assert inp["n_c"].sum() == inp["sizes"].sum()
            i += 1
    assert i == len(batch["X"])
    assert batch["tok_att"].sum() > 0          # the synthetic games include refused throws


@pytest.fixture(scope="module")
def small_package(tmp_path_factory):
    torch = pytest.importorskip("torch")
    from shengji.train import belief_seq as bs
    torch.manual_seed(3)
    model = bs.build_model(**SMALL).eval()
    # move the zero-initialised null slot so the parity test exercises it
    with torch.no_grad():
        model.null_kv.normal_(0, 0.5)
    root = tmp_path_factory.mktemp("pkg")
    ck = root / "best.pt"
    torch.save({"model": model.state_dict(), "config": model.config, "args": {"no_history": False},
                "epoch": 1, "calib_ll": 1.0}, ck)
    info = bsm.export(str(ck), str(root / "s17.npz"), temperature=1.1)
    return {"model": model, "path": str(root / "s17.npz"), "sha256": info["sha256"]}


@pytest.mark.parametrize("dtype,logit_tol", [(np.float64, 1e-5), (np.float32, 2e-5)])
def test_numpy_forward_matches_torch(chunk, small_package, dtype, logit_tol):
    torch = pytest.importorskip("torch")
    from shengji.train import belief_seq as bs
    from shengji.train.belief_eval import masked_softmax
    batch = _model_batch(chunk)
    with torch.no_grad():
        ref = small_package["model"](bs.to_torch(batch)).numpy().astype(np.float64)
    model = bn.load_belief_numpy(small_package["path"], small_package["sha256"], dtype=dtype)
    assert model.temperature == pytest.approx(1.1)
    plies = set()
    for j in range(len(batch["X"])):
        inp = bsm.row_inputs(batch, j)
        M = inp["M"]
        got = model.logits(inp).astype(np.float64)
        assert np.abs(got - ref[j])[M].max(initial=0.0) <= logit_tol
        want = masked_softmax(ref[j][None], M[None], 1.1)[0]
        assert np.abs(model.marginals(inp) - want).max() <= 1e-5
        plies.add(int(batch["ply"][j]))
    assert 0 in plies and max(plies) > 50


def test_a_package_with_other_bytes_or_widths_is_refused(small_package, tmp_path):
    with pytest.raises(bn.BeliefNumpyError):
        bn.load_belief_numpy(small_package["path"], "0" * 64)
    with np.load(small_package["path"]) as z:
        arrays = {k: z[k] for k in z.files}
    meta = json.loads(str(arrays["metadata"]))
    meta["dims"] = dict(meta["dims"], feature_dim=1)
    arrays["metadata"] = np.asarray(json.dumps(meta))
    np.savez(tmp_path / "bad.npz", **arrays)
    with pytest.raises(bn.BeliefNumpyError):
        bn.load_belief_numpy(tmp_path / "bad.npz")
    arrays.pop("w:card_id")
    arrays["metadata"] = np.asarray(json.dumps(dict(meta, dims=bn.DIMS)))
    np.savez(tmp_path / "short.npz", **arrays)
    with pytest.raises(bn.BeliefNumpyError):
        bn.load_belief_numpy(tmp_path / "short.npz")


def test_s17_worlds_honour_sizes_pins_and_the_actor(chunk, small_package):
    model = bn.load_belief_numpy(small_package["path"], small_package["sha256"])
    seen_pins = 0
    for path in chunk["paths"][:1]:
        recs = [r for r in bl._read_records(path) if r.get("decision_kind") == "play"]
        for n, d in enumerate(bl.iter_decisions(recs)):
            if n % 7:
                continue
            keep: dict = {}
            draw = bsm.s17_draw(model, keep=keep)
            sampler, mem, worlds, _ = draw(d.rnd, d.seat, d.refusals, 16, 11 + n)
            inp = bn.decision_inputs(d.rnd, d.seat, d.refusals)
            seen_pins += int(inp["K"].sum())
            hidden = Counter(mem.unseen)
            for hands, buried in worlds:
                assert hands[d.seat] == list(d.rnd.hands[d.seat])
                placed = Counter()
                for s in range(4):
                    assert len(hands[s]) == len(d.rnd.hands[s])
                    if s != d.seat:
                        placed.update(hands[s])
                    if s != d.seat and s in mem.voids:
                        o = d.rnd.ordering
                        assert not any(o.eff_suit(c) in mem.voids[s] for c in hands[s])
                if mem.own_kitty_known:
                    assert Counter(buried) == Counter(d.rnd.buried)
                else:
                    placed.update(buried)
                    assert len(buried) == len(d.rnd.buried)
                assert placed == hidden
                for rel in (1, 2, 3):
                    have = Counter(hands[(d.seat + rel) % 4])
                    for c in np.flatnonzero(inp["K"][:, rel - 1]):
                        assert have[bsm._CODES[c]] >= inp["K"][c, rel - 1]
            assert keep["P"].shape == (54, 4)
            assert 1 <= bsm.distinct_worlds(worlds) <= len(worlds)
            assert bsm.distinct_worlds(worlds + worlds) == bsm.distinct_worlds(worlds)
    assert seen_pins > 0


def test_the_follow_check_flags_a_world_that_breaks_an_earlier_follow(chunk):
    from shengji.train import world_weighting as ww
    path = chunk["paths"][0]
    recs = [r for r in bl._read_records(path) if r.get("decision_kind") == "play"]
    for view in ww.iter_states(recs):
        d = view.decision
        truth = [(list(d.rnd.hands), list(d.rnd.buried))]
        assert not bsm.follow_illegal(view, truth).any()     # the true deal is always legal
    # a world that gives a follower a card of the led suit it showed void in
    for view in ww.iter_states(recs):
        d = view.decision
        o = d.rnd.ordering
        for i, ev in enumerate(view.events):
            if ev.seat == d.seat or not ev.snap.trick.plays:
                continue
            lead_eff = o.eff_suit(ev.snap.trick.plays[0].cards[0])
            if all(o.eff_suit(c) == lead_eff for c in ev.played):
                continue
            # the follower was short; hand it a led-suit card someone else holds now
            donor = next((s for s in range(4) if s not in (d.seat, ev.seat)
                          and any(o.eff_suit(c) == lead_eff for c in d.rnd.hands[s])), None)
            if donor is None or not d.rnd.hands[ev.seat]:
                continue
            hands = [list(h) for h in d.rnd.hands]
            give = next(c for c in hands[donor] if o.eff_suit(c) == lead_eff)
            take = hands[ev.seat][0]
            hands[donor].remove(give)
            hands[donor].append(take)
            hands[ev.seat].remove(take)
            hands[ev.seat].append(give)
            assert bsm.follow_illegal(view, [(hands, list(d.rnd.buried))]).all()
            return
    pytest.skip("no short follow with a donor in this game")


def test_history_legal_draws_match_the_served_paths(small_package):
    from shengji.ai import history_legality as HL
    from test_world_history_legal import fixture
    _, now, seat = fixture()
    model = bn.load_belief_numpy(small_package["path"], small_package["sha256"])
    for m in (None, model):
        keep: dict = {}
        _, _, worlds, stats = bsm.history_legal_draw(keep=keep, model=m)(now, seat, (), 16, 3)
        assert len(worlds) == 16 and keep["worlds"] is worlds
        if not stats["history_fallback_worlds"]:
            assert all(HL.history_legal(now, seat, hands) for hands, _ in worlds)
