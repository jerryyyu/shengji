"""Soft-target distillation in the belief trainer (``belief_seq train --soft-targets``).

Off (``--soft-weight 0``, the default) the loss is the per-copy cross-entropy
exactly.  On, it adds the weight times the cross-entropy against soft targets
(expected copies per receiver) on the rows that carry one.  The targets are
residualized as the labels are (public pins subtracted), must put no mass on an
infeasible receiver and must place exactly each row's unknown copies.  The
extracts are synthetic games run through the real label and history extraction.
"""
from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from shengji.train import belief_seq as bs  # noqa: E402
from shengji.train.belief_eval import known_counts  # noqa: E402

from tests.test_belief_seq_eval_rows import build_extract, train_args  # noqa: E402
from tests.test_belief_seq_init import SMALL, synthetic_part  # noqa: E402


def _model():
    torch.manual_seed(0)
    m = bs.build_model(**SMALL)
    with torch.no_grad():
        for p in m.parameters():
            p.add_(0.05 * torch.randn_like(p))
    m.eval()
    return m


def _batch(part):
    return bs.to_torch(bs.make_batch(part, np.arange(3), np.arange(len(part["X"]))))


def test_soft_weight_zero_is_the_cross_entropy_exactly():
    m = _model()
    part = synthetic_part(3, 20, 4, seed=1)
    plain = _batch(part)
    part["T"] = np.random.default_rng(0).random(part["Y"].shape).astype(np.float32)
    soft = _batch(part)
    with torch.no_grad():
        base, n = bs.batch_loss(m, plain)
        off, n0 = bs.batch_loss(m, soft, soft_weight=0.0)
    assert float(off) == float(base) and float(n0) == float(n)


def test_soft_weight_adds_the_weighted_soft_cross_entropy_and_its_copies():
    m = _model()
    part = synthetic_part(3, 20, 4, seed=2)
    rng = np.random.default_rng(1)
    part["T"] = (part["M"] * rng.random(part["Y"].shape)).astype(np.float32)
    tb = _batch(part)
    lam = 2.5
    with torch.no_grad():
        base, n = bs.batch_loss(m, tb)
        on, n_on = bs.batch_loss(m, tb, soft_weight=lam)
        logp = torch.log_softmax(m(tb).float().masked_fill(~tb["M"], -1e9), -1)
        want = base - lam * (tb["T"] * logp).sum()
    assert abs(float(on) - float(want)) < 1e-3 * abs(float(want))
    assert abs(float(n_on) - (float(n) + lam * float(tb["T"].sum()))) < 1e-3
    # soft targets equal to the labels: the loss is (1 + lambda) times the hard loss
    part["T"] = part["Y"].astype(np.float32)
    tb = _batch(part)
    with torch.no_grad():
        same, n_same = bs.batch_loss(m, tb, soft_weight=lam)
    assert abs(float(same) - (1 + lam) * float(base)) < 1e-3 * abs(float(base))
    assert abs(float(n_same) - (1 + lam) * float(n)) < 1e-3


def test_soft_rows_subtract_the_public_pins_and_leave_other_rows_zero():
    part = synthetic_part(1, 10, 5, seed=3)
    X = part["X"].astype(np.float32)
    at = bs._block_at("pinned_rel2")
    X[:, at:at + 54] = 0
    X[:, bs._block_at("pinned_rel1"):bs._block_at("pinned_rel1") + 54] = 0
    X[:, bs._block_at("pinned_rel3"):bs._block_at("pinned_rel3") + 54] = 0
    X[2, at + 7] = 1.0                                # one copy of code 7 pinned to the partner
    T = np.zeros((2, 54, 4), np.float32)
    T[:, 7, 1] = 1.5
    T[:, 7, 0] = 0.5
    out = bs.soft_rows((np.array([2, 4]), T), len(X), X)
    assert out.shape == (5, 54, 4)
    assert not out[[0, 1, 3]].any()
    assert out[2, 7, 1] == pytest.approx(0.5) and out[4, 7, 1] == pytest.approx(1.5)
    assert np.array_equal(known_counts(X[2:3])[0, 7], [0, 1, 0, 0])
    with pytest.raises(bs.BeliefSeqError, match="outside its chunk"):
        bs.soft_rows((np.array([5]), T[:1]), len(X), X)


def test_check_soft_refuses_infeasible_mass_and_wrong_copy_counts():
    Y = np.zeros((2, 54, 4), np.uint8)
    M = np.zeros((2, 54, 4), bool)
    Y[0, 3, 0] = 1
    M[0, 3, :2] = True
    T = np.zeros((2, 54, 4), np.float32)
    T[0, 3, 0], T[0, 3, 1] = 0.25, 0.75
    good = {"Y": Y, "M": M, "T": T.copy()}
    bs.check_soft(good)
    assert np.allclose(good["T"], T)
    bad = T.copy()
    bad[0, 3, 2] = 0.1
    bad[0, 3, 1] = 0.65
    with pytest.raises(bs.BeliefSeqError, match="outside the residual feasible mask"):
        bs.check_soft({"Y": Y, "M": M, "T": bad})
    short = T.copy()
    short[0, 3, 1] = 0.5
    with pytest.raises(bs.BeliefSeqError, match="unknown copies"):
        bs.check_soft({"Y": Y, "M": M, "T": short})


def _soft_file(path, entries, frac=0.5, seed=0, noise=0.3):
    """Soft targets on part of each chunk's rows: the labels mixed with feasible noise
    (the pins added back, as the files carry targets before residualization)."""
    rng = np.random.default_rng(seed)
    chunks, rows, Ts = [], [], []
    for e in entries:
        with np.load(e["path"]) as z:
            X, Y, M, sizes = z["X"], z["Y"].astype(np.float32), z["M"], z["sizes"]
        part = {"X": X, "Y": Y.astype(np.uint8), "M": M.copy(), "sizes": sizes.copy()}
        K = known_counts(X).astype(np.float32)
        bs.residualize(part)
        R, Mr = part["Y"].astype(np.float32), part["M"]
        for r in np.flatnonzero(rng.random(len(X)) < frac):
            n = R[r].sum(-1, keepdims=True)
            u = np.where(Mr[r], rng.random(Mr[r].shape), 0.0)
            u = np.where(n > 0, u / np.maximum(u.sum(-1, keepdims=True), 1e-12) * n, 0.0)
            chunks.append(e["path"]); rows.append(r)
            Ts.append(((1 - noise) * R[r] + noise * u + K[r]).astype(np.float32))
    np.savez(path, chunk=np.asarray(chunks), row=np.asarray(rows, np.int32), T=np.stack(Ts))
    return len(Ts)


@pytest.fixture(scope="module")
def extract(tmp_path_factory):
    return build_extract(tmp_path_factory.mktemp("soft"), sampler=False)


def test_training_with_soft_targets_runs_logs_the_soft_eval_and_keeps_epochs(extract, tmp_path):
    d = [str(extract)]
    train = bs.extract_entries(d, "train")
    calib = bs.extract_entries(d, "calib")
    st, se = tmp_path / "soft_train.npz", tmp_path / "soft_eval.npz"
    assert _soft_file(st, train) and _soft_file(se, calib, seed=1)
    chunks = tmp_path / "chunks.txt"
    chunks.write_text("".join(e["path"] + "\n" for e in train[:3]))
    with pytest.raises(bs.BeliefSeqError, match="not a training chunk"):
        bs.main(train_args(extract, tmp_path / "x", "--eval-rows", "all", "--train-chunks", str(chunks),
                           "--soft-targets", str(st), "--soft-weight", "2"))
    out = tmp_path / "on"
    assert bs.main(train_args(extract, out, "--eval-rows", "all", "--soft-targets", str(st),
                              "--soft-weight", "2", "--soft-eval", str(se), "--keep-epochs")) == 0
    hist = torch.load(out / "checkpoint.pt", weights_only=False)["state"]["history"]
    ev = hist[0]["soft_eval"]
    assert ev["rows"] > 0 and ev["soft_kl"] >= -1e-6 and ev["soft_ce"] >= ev["soft_kl"]
    assert (out / "epoch-1.pt").exists() and (out / "best.pt").exists()
    assert "soft_eval" in (out / "status.log").read_text()


def test_soft_weight_zero_trains_exactly_as_without_soft_targets(extract, tmp_path):
    d = [str(extract)]
    st = tmp_path / "soft_train.npz"
    _soft_file(st, bs.extract_entries(d, "train"))
    a, b = tmp_path / "plain", tmp_path / "soft0"
    one = ["--eval-rows", "all", "--seed", "3", "--threads", "1", "--loader-threads", "1"]
    assert bs.main(train_args(extract, a, *one)) == 0
    assert bs.main(train_args(extract, b, *one, "--soft-targets", str(st))) == 0
    sa = torch.load(a / "best.pt", weights_only=False)["model"]
    sb = torch.load(b / "best.pt", weights_only=False)["model"]
    assert sa.keys() == sb.keys() and all(torch.equal(sa[k], sb[k]) for k in sa)


def test_train_chunks_restricts_the_training_entries(extract, tmp_path):
    d = [str(extract)]
    train = bs.extract_entries(d, "train")
    chunks = tmp_path / "chunks.txt"
    chunks.write_text(train[0]["path"] + "\n")
    out = tmp_path / "one"
    assert bs.main(train_args(extract, out, "--eval-rows", "all", "--train-chunks", str(chunks))) == 0
    start = (out / "status.log").read_text().splitlines()[0]
    assert "chunks=1 " in start and f"cached_train_rows={train[0]['rows']} " in start
    chunks.write_text("/nowhere/train-00000.npz\n")
    with pytest.raises(bs.BeliefSeqError, match="outside the train split"):
        bs.main(train_args(extract, tmp_path / "none", "--eval-rows", "all", "--train-chunks", str(chunks)))


def test_soft_target_files_refuse_duplicate_rows(tmp_path):
    p = tmp_path / "dup.npz"
    np.savez(p, chunk=np.asarray(["a", "a"]), row=np.asarray([1, 1], np.int32),
             T=np.zeros((2, 54, 4), np.float32))
    with pytest.raises(bs.BeliefSeqError, match="two soft targets"):
        bs.load_soft_targets(str(p))
