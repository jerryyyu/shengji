"""Offline action-aware reranker prototype (scripts/policy_reranker_proto.py, board C7)."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "policy_reranker_proto.py"


@pytest.fixture(scope="module")
def rp():
    spec = importlib.util.spec_from_file_location("policy_reranker_proto", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ballot(cands, B=4, C=4):
    ball = np.full((B, C), -1, np.int8)
    for j, c in enumerate(cands):
        ball[j, :len(c)] = c
    mask = np.zeros(B, bool); mask[:len(cands)] = True
    return ball, mask


def _root(trump_suit=2, trump_rank=0, lead=True):
    x = np.zeros(833, np.float32)
    x[486 + trump_suit] = 1.0
    x[491 + trump_rank] = 1.0
    if not lead:
        x[270 + 5] = 1.0            # a card in trick plane 0: someone already led
    return x


def test_ballot_counts_and_baseline_match_score_candidates(rp):
    from shengji.train.policy_prior import score_candidates
    cands = [[0], [18, 18], [2, 2, 3, 3], [52, 53]]
    ball, mask = _ballot(cands)
    counts = rp.ballot_counts(ball[None])
    assert counts.shape == (1, 4, 54)
    assert counts[0, 1, 18] == 2 and counts[0, 2].sum() == 4 and counts[0, 3, 52] == 1
    rng = np.random.default_rng(0)
    lo = rng.normal(size=(1, 54)).astype(np.float32)
    base = rp.baseline_scores(lo, counts, mask[None])
    want = score_candidates(lo[0], cands)
    np.testing.assert_allclose(base[0, :4], want, rtol=1e-5, atol=1e-5)


def test_structure_features(rp):
    # trump = D (suit 2), trump rank 2 (index 0): S2 is a trump-rank card
    cands = [[13 + 3], [18, 18], [2, 2, 3, 3], [52, 53]]       # H5 single, H7 pair, S4S4S5S5 tractor, joker pair
    ball, mask = _ballot(cands)
    counts = rp.ballot_counts(ball[None])
    f = rp.structure_features(counts, _root()[None])
    names = rp.FEAT_NAMES
    g = lambda j, n: float(f[0, j, names.index(n)])
    assert g(0, "n_cards") == 1 and g(0, "single_plain") == 1 and g(0, "n_pairs") == 0
    assert g(1, "n_pairs") == 1 and g(1, "tractor_len") == 0 and g(1, "single_plain") == 1
    assert g(2, "n_pairs") == 2 and g(2, "tractor_len") == 2 and g(2, "mixed_throw") == 0
    assert g(3, "all_trump") == 1 and g(3, "has_joker") == 1
    assert all(f[0, :, names.index("is_lead")] == 1)
    # a throw mixing two plain suits, on a follow row
    ball2, mask2 = _ballot([[1, 14], [0]])                        # S3 + H3 ; S2 (trump rank)
    f2 = rp.structure_features(rp.ballot_counts(ball2[None]), _root(lead=False)[None])
    assert float(f2[0, 0, names.index("mixed_throw")]) == 1 and float(f2[0, 0, names.index("n_suits_plain")]) == 2
    assert float(f2[0, 1, names.index("all_trump")]) == 1 and float(f2[0, 1, names.index("n_trump_rank")]) == 1
    assert float(f2[0, 0, names.index("is_lead")]) == 0


def _synthetic(rp, n=256, seed=0):
    rng = np.random.default_rng(seed)
    feat = rng.normal(size=(n, 16)).astype(np.float32)
    cands = [[0], [1, 1], [2, 2, 3, 3], [4, 5]]
    ball, mask = _ballot(cands)
    counts = np.repeat(rp.ballot_counts(ball[None]), n, axis=0)
    X = np.repeat(_root()[None], n, axis=0)
    sf = rp.structure_features(counts, X)
    lo = rng.normal(size=(n, 54)).astype(np.float32)
    maskn = np.repeat(mask[None], n, axis=0)
    base = rp.baseline_scores(lo, counts, maskn)
    # the search prefers the tractor whenever feat[:, 0] > 0, else the single: a structure x root interaction
    vals = np.where(maskn, 0.0, np.nan).astype(np.float32)
    vals[:, 2] = np.where(feat[:, 0] > 0, 5.0, 0.0); vals[:, 0] = np.where(feat[:, 0] > 0, 0.0, 5.0)
    tgt = np.where(feat[:, 0] > 0, 2, 0).astype(np.int64)
    return {"feat": feat, "lo": lo, "counts": counts, "mask": maskn, "vals": vals, "sf": sf, "tgt": tgt, "base": base,
            "deal": np.asarray([f"d{i % 32}" for i in range(n)]), "lead": np.ones(n, bool), "multi": np.ones(n, bool)}


def test_zero_init_reranker_is_the_baseline(rp):
    d = _synthetic(rp)
    for m in (rp.Reranker(16, use_base=True), rp.Factorised(16)):
        s = rp.predict(m, d)
        np.testing.assert_allclose(np.where(d["mask"], s, -1e9), d["base"], atol=1e-5)


def test_row_metrics_and_training_improve_on_structure_interaction(rp):
    d = _synthetic(rp)
    st = rp.strata(d)
    base = rp.row_metrics(d["base"], d)
    assert set(base) == {"top1", "ce", "regret"} and base["top1"].shape == (256,)
    m = rp.train_reranker(d, np.arange(256), use_base=True, epochs=30, lr=1e-2, batch=64, seed=1)
    after = rp.row_metrics(rp.predict(m, d), d)
    assert after["top1"].mean() > base["top1"].mean() + 0.3
    assert after["ce"].mean() < base["ce"].mean()
    boot = rp.paired_bootstrap(base, after, st, d["deal"], n_boot=50)
    lo, hi = boot["all"]["d_top1_ci"]
    assert lo <= boot["all"]["d_top1"] <= hi and lo > 0


def test_trump_features_use_multiplicity_d3d3d4d4(rp):
    # Codex's case: trump D (suit 2), trump rank 2.  D3 D3 D4 D4 = indices 27, 27, 28, 28: four trump cards,
    # two pairs in a run -- all_trump, never mixed_throw, and never "two distinct trump cards".
    ball, mask = _ballot([[27, 27, 28, 28], [27, 28], [0, 0]], B=3, C=4)       # also D3 D4 (two singles), S2 S2 (trump-rank pair)
    f = rp.structure_features(rp.ballot_counts(ball[None]), _root(trump_suit=2, trump_rank=0)[None])
    names = rp.FEAT_NAMES
    g = lambda j, n: float(f[0, j, names.index(n)])
    assert g(0, "n_cards") == 4 and g(0, "n_pairs") == 2 and g(0, "tractor_len") == 2
    assert g(0, "all_trump") == 1 and g(0, "mixed_throw") == 0 and g(0, "single_plain") == 0
    assert g(1, "n_cards") == 2 and g(1, "all_trump") == 1 and g(1, "n_pairs") == 0
    assert g(2, "n_trump_rank") == 2 and g(2, "all_trump") == 1 and g(2, "n_pairs") == 1


def test_extra_heldout_overlap_guard(rp):
    d = _synthetic(rp, n=64)                      # deals d0..d31, two rows each
    kept, dropped = rp.exclude_deals_from(d, frozenset({"d0", "d1", "d2"}), "extra")
    assert dropped == 6 and len(kept["tgt"]) == 58 and not (set(kept["deal"]) & {"d0", "d1", "d2"})
    for k in ("feat", "counts", "mask", "vals", "sf", "base", "lead", "multi"):
        assert len(kept[k]) == 58
    with pytest.raises(ValueError):
        rp.exclude_deals_from(d, frozenset(d["deal"].tolist()), "extra")
