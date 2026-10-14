"""S17 step 1: the belief evaluator (`shengji.train.belief_eval`).

The metric and baseline arithmetic on hand-built arrays, the permuted-label
control on synthetic data (a learnable signal must be learned; the same model on
permuted labels must not beat the label-free prior), and one end-to-end run on
a tiny synthetic extract through the real replay and the real sampler.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from shengji.train import belief_eval as be   # noqa: E402
from shengji.train import belief_labels as bl  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_belief_labels import synthetic_cluster  # noqa: E402


def test_masked_softmax_respects_the_mask():
    logits = np.random.default_rng(0).normal(size=(3, 54, 4)).astype(np.float32)
    mask = np.ones((3, 54, 4), bool)
    mask[:, :, 3] = False
    mask[0, 5] = False                       # a card with no hidden copy
    p = be.masked_softmax(logits, mask, 1.5)
    assert np.allclose(p[:, :, 3], 0)
    assert np.allclose(p[0, 5], 0)
    s = p.sum(-1)
    assert np.allclose(s[mask.any(-1)], 1.0)


def test_sampler_probs_smooth_only_feasible_receivers():
    S = np.zeros((1, 54, 4), np.uint16)
    S[0, 0, 0] = 512                         # 2 copies x 256 worlds, all with "next"
    M = np.zeros((1, 54, 4), bool)
    M[0, 0, :3] = True
    p = be.sampler_probs(S, np.array([256]), M, alpha=1.0)
    assert p[0, 0, 3] == 0
    assert math.isclose(p[0, 0].sum(), 1.0)
    assert p[0, 0, 0] == pytest.approx(513 / 515)
    p0 = be.sampler_probs(S, np.array([256]), M, alpha=0.0)
    assert p0[0, 0, 1] == 0                  # the unsmoothed marginal can be zero on a truth


def test_uniform_weights_by_cards_held():
    M = np.zeros((1, 54, 4), bool)
    M[0, 0] = [True, True, False, True]
    p = be.uniform_probs(np.array([[10, 20, 30, 8]]), M)
    assert p[0, 0] == pytest.approx([10 / 38, 20 / 38, 0, 8 / 38])


def test_copy_terms_subsets():
    P = np.zeros((1, 54, 4))
    Y = np.zeros((1, 54, 4), np.uint8)
    P[0, 0] = [0.5, 0.25, 0.0, 0.25]
    Y[0, 0, 0] = 1                           # in "next"
    P[0, 1] = [0.2, 0.2, 0.2, 0.4]
    Y[0, 1, 3] = 2                           # both copies in the kitty
    t = be.copy_terms(P, Y)
    assert t["all_n"][0] == 3 and t["hands_n"][0] == 1 and t["kitty_n"][0] == 2
    assert t["hands_raw_ll"][0] == pytest.approx(-math.log(0.5))
    assert t["hands_ll"][0] == pytest.approx(-math.log(0.5 / 0.75))     # kitty mass renormalized out
    assert t["kitty_ll"][0] == pytest.approx(-2 * math.log(0.4))
    assert t["all_mass"][0] == pytest.approx(0.5 + 0.8)


def test_permutation_stays_inside_each_stratum():
    strata = np.array([0, 0, 1, 1, 1, 2, 0, 2])
    perm = be.permute_within_strata(strata, 3)
    assert sorted(perm.tolist()) == list(range(len(strata)))
    assert np.array_equal(strata[perm], strata)


def _synthetic(n, rng):
    """Every card's holder is the argmax of x[:3] (a learnable channel); the
    kitty is never feasible; one copy per card."""
    X = rng.normal(size=(n, 12)).astype(np.float32)
    holder = X[:, :3].argmax(1)
    Y = np.zeros((n, 54, 4), np.uint8)
    Y[np.arange(n), :, :] = 0
    for r in range(3):
        Y[holder == r, :, r] = 1
    M = np.zeros((n, 54, 4), bool)
    M[:, :, :3] = True
    return X, Y, M


def test_the_permuted_control_does_not_learn_what_the_model_learns():
    rng = np.random.default_rng(0)
    X, Y, M = _synthetic(3000, rng)
    Xc, Yc, Mc = _synthetic(600, rng)
    Xt, Yt, Mt = _synthetic(600, rng)
    model, _ = be.train_model(X, Y, M, Xc, Yc.astype(np.float32), Mc, hidden=16, epochs=4,
                              lr=1e-2, batch=256, seed=0, log=lambda *a, **k: None)
    perm = be.permute_within_strata(np.zeros(len(X), int), 1)
    control, _ = be.train_model(X, Y[perm], M[perm], Xc, Yc.astype(np.float32), Mc, hidden=16,
                                epochs=4, lr=1e-2, batch=256, seed=0, log=lambda *a, **k: None)
    prior = math.log(3)                      # the label-free answer: uniform over three seats
    ll_model = be.mean_ll(be.masked_softmax(be.predict_logits(model, Xt), Mt), Yt)
    ll_control = be.mean_ll(be.masked_softmax(be.predict_logits(control, Xt), Mt), Yt)
    assert ll_model < 0.5 * prior
    assert ll_control > 0.97 * prior


def test_fit_scalar_finds_a_minimum():
    t = be.fit_scalar(lambda x: (math.log(x) - math.log(1.7)) ** 2, 0.25, 4.0)
    assert t == pytest.approx(1.7, rel=1e-3)


def test_deal_bootstrap_is_zero_for_identical_losses():
    deal = np.repeat(np.arange(20), 5)
    den = np.ones(100)
    (lo, hi), = be.deal_bootstrap(deal, [den.copy()], den, reps=50)
    assert lo == hi == 0.0


def test_end_to_end_on_a_tiny_synthetic_extract(tmp_path, monkeypatch):
    # 14 deals as one store; small sampler; a 1-epoch model -- the plumbing, not the science
    store = tmp_path / "store" / "shards"
    store.mkdir(parents=True)
    for i, seed in enumerate(range(2000, 2014)):
        with open(store / f"cluster-{i:06d}.jsonl", "w") as fh:
            for r in synthetic_cluster(seed, throw_rate=0.2):
                fh.write(json.dumps(r) + "\n")
    monkeypatch.setattr(bl, "excluded_windows", lambda registry=None: [])
    out = tmp_path / "extract"
    m = bl.extract([str(tmp_path / "store")], str(out), cluster_stride=1, cluster_offset=0,
                   max_clusters_per_store=None, calib=0.3, test=0.3, sampler_worlds=8,
                   sampler_splits=("calib", "test"), sampler_stride=3, workers=1,
                   task_clusters=7, log=lambda *a, **k: None)
    assert not m["failed_clusters"]
    splits = {s for c in m["chunks"] for s in c["files"]}
    if splits != {"train", "calib", "test"}:
        pytest.skip(f"synthetic deals did not fill every split: {sorted(splits)}")
    md, res = be.run(str(out), hidden=8, epochs=1, lr=1e-3, batch=128, seed=0, threads=1,
                     weight_decay=0.0, max_train_rows=None, log=lambda *a, **k: None)
    assert "verdict" in md and res["stop_rule"]["verdict"] in ("PASS", "STOP")
    for name in ("overall", "early", "mid", "late"):
        assert set(res["tables"][name]) == {"model", "sampler", "control", "uniform"}
    assert res["tables"]["overall"]["sampler"]["all"]["copies"] > 0


# ---------------------------------------------------------------- public pins (Codex HOLD on #1002)

def _pinned_codes(cluster_records, tmp_path):
    """Producer output for one synthetic cluster, plus per-row public pin
    sources: declared codes and failed-throw codes (the throw_unplayed blocks)."""
    path = tmp_path / "store" / "shards"
    path.mkdir(parents=True, exist_ok=True)
    f = path / "cluster-000000.jsonl"
    with open(f, "w") as fh:
        for r in cluster_records:
            fh.write(json.dumps(r) + "\n")
    got = bl.extract_cluster(f, store_index=0, cluster_index=0, calib=0.0, test=0.0, windows=[],
                             sampler_worlds=8, sampler_splits=("train",))
    return got


def _block(name):
    at = 0
    for block, width in bl.FEATURE_BLOCKS:
        if block == name:
            return slice(at, at + width)
        at += width


def _fully_known(part, source):
    """(row, code) pairs whose every hidden copy is publicly pinned, by source."""
    K = be.known_counts(part["X"])
    hidden = part["Y"].sum(-1)
    full = (K.sum(-1) == hidden) & (hidden > 0)
    X = np.asarray(part["X"], np.float32)
    declared = X[:, _block("declared_cards")] > 0
    thrown = sum(X[:, _block(f"throw_unplayed_rel{r}")] for r in (1, 2, 3)) > 0
    pick = declared if source == "declared" else (thrown & ~declared)
    return np.argwhere(full & pick)


@pytest.fixture(scope="module")
def pinned_part(tmp_path_factory):
    for seed in range(1000, 1200):
        recs = synthetic_cluster(seed)
        got = _pinned_codes(recs, tmp_path_factory.mktemp(f"pin{seed}"))
        part = {k: got[k] for k in ("X", "Y", "M", "S", "S_n", "sizes")}
        if len(_fully_known(part, "declared")) and len(_fully_known(part, "throw")):
            return part
    pytest.fail("no synthetic cluster with both a declared and a failed-throw pin")


@pytest.mark.parametrize("source", ["declared", "throw"])
def test_no_gain_can_be_earned_on_a_fully_known_copy(pinned_part, source):
    part = {k: v.copy() for k, v in pinned_part.items()}
    cells = _fully_known(part, source)
    K = be.known_counts(part["X"])
    rows, codes = cells[:, 0], cells[:, 1]
    # producer: the sampler already puts every pinned copy with its holder
    assert np.array_equal(part["S"][rows, codes].astype(np.int64),
                          K[rows, codes] * part["S_n"][rows, None].astype(np.int64))
    # before the repair, smoothing moved mass off the known holder (Codex's witness)
    before = be.sampler_probs(part["S"], part["S_n"], part["M"], 1.0)
    assert (before[rows, codes] * (K[rows, codes] > 0)).sum(-1).min() < 1.0
    be.residualize(part)
    assert not part["Y"][rows, codes].any()
    assert not part["M"][rows, codes].any()
    assert not part["S"][rows, codes].any()
    # metric: any probabilities at all on the known codes change nothing
    P = be.sampler_probs(part["S"], part["S_n"], part["M"], 1.0)
    Q = P.copy()
    Q[rows, codes] = [0.0, 0.0, 0.0, 1.0]
    tp, tq = be.copy_terms(P, part["Y"]), be.copy_terms(Q, part["Y"])
    for key in tp:
        assert np.allclose(tp[key], tq[key])


def test_a_partly_pinned_duplicate_keeps_its_other_copy():
    X = np.zeros((1, bl.FEATURE_DIM), np.float16)
    X[0, _block("pinned_rel2")][7] = 1          # one copy of code 7 pinned to the partner
    Y = np.zeros((1, 54, 4), np.uint8)
    Y[0, 7, 1] = 1                               # the pinned copy, with the partner
    Y[0, 7, 0] = 1                               # the other copy, with next
    M = np.zeros((1, 54, 4), bool)
    M[0, 7] = True
    S = np.zeros((1, 54, 4), np.uint16)
    S[0, 7] = [3, 8 + 2, 3, 0]                   # 8 worlds: the pin, plus the free copy spread
    part = {"X": X, "Y": Y, "M": M, "S": S, "S_n": np.array([8]), "sizes": np.array([[5, 5, 5, 8]])}
    out = be.residualize(part)
    assert out == {"known_copies": 1, "residual_copies": 1}
    assert part["Y"][0, 7].tolist() == [1, 0, 0, 0]
    assert part["M"][0, 7].tolist() == [True, True, True, True]   # the free copy may also be with the partner
    assert part["S"][0, 7].tolist() == [3, 2, 3, 0]
    assert part["sizes"][0].tolist() == [5, 4, 5, 8]


def test_a_pin_outside_its_holders_hand_is_refused():
    X = np.zeros((1, bl.FEATURE_DIM), np.float16)
    X[0, _block("pinned_rel1")][3] = 1
    part = {"X": X, "Y": np.zeros((1, 54, 4), np.uint8), "M": np.zeros((1, 54, 4), bool)}
    with pytest.raises(be.BeliefEvalError):
        be.residualize(part)
