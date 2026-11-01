"""Warm-starting the belief trainer from a served package (``belief_seq train --init``).

The loader is the inverse of ``belief_sampler.export``: a package's weights
rebuild a torch model whose logits match the NumPy serving runtime, an export
of that model reproduces the package's arrays, and a run from ``--init``
starts from exactly the loaded model's loss.  The architecture comes from the
package (a conflicting flag is refused) and a package whose input widths or
features are not the training data's is refused.  Packages here are small
synthetic models.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from shengji.ai import belief_numpy as bn  # noqa: E402
from shengji.train import belief_sampler as bsm  # noqa: E402
from shengji.train import belief_seq as bs  # noqa: E402
from shengji.train.belief_eval import fit_scalar, masked_softmax, mean_ll  # noqa: E402
from shengji.train.belief_history import MAX_PLAYS, N_CARD_FEATURES, N_TOKEN_FLOAT  # noqa: E402
from shengji.train.belief_labels import FEATURE_BLOCKS, FEATURE_DIM, N_RECV  # noqa: E402
from shengji.train.belief_labels import SCHEMA as LABELS_SCHEMA  # noqa: E402

SMALL = dict(d=32, heads=4, enc_layers=2, xattn_layers=2, x_hidden=32, card_self_attn=True)
SMALL_FLAGS = ["--d", "32", "--heads", "4", "--enc-layers", "2", "--xattn-layers", "2",
               "--x-hidden", "32"]
TEMPERATURE = 1.23
PARITY_TOL = 1e-5


def synthetic_part(R: int, T: int, rows_per_round: int, seed: int = 0) -> dict:
    """A loaded-part-shaped dict (``load_part``/``concat_parts`` keys) of ``R`` rounds."""
    rng = np.random.default_rng(seed)
    B = R * rows_per_round
    M = rng.random((B, 54, N_RECV)) < 0.6
    M[..., 0] = True
    Y = (M & (rng.random((B, 54, N_RECV)) < 0.2)).astype(np.float32)
    rounds = {
        "tok_int": np.stack([rng.integers(0, 4, (R, MAX_PLAYS)), rng.integers(0, 4, (R, MAX_PLAYS)),
                             rng.integers(0, 25, (R, MAX_PLAYS)), rng.integers(0, 5, (R, MAX_PLAYS))],
                            -1).astype(np.int8),
        "tok_f": rng.random((R, MAX_PLAYS, N_TOKEN_FLOAT)).astype(np.float16),
        "tok_cards": (rng.random((R, MAX_PLAYS, 54)) < 0.05).astype(np.int8),
        "tok_att": (rng.random((R, MAX_PLAYS, 54)) < 0.02).astype(np.int8),
        "round_n": np.full(R, T, np.int16),
        "card_feat": rng.random((R, 54, N_CARD_FEATURES)).astype(np.float16),
        "banker": rng.integers(0, 4, R).astype(np.int8)}
    return {"X": rng.random((B, FEATURE_DIM)).astype(np.float16), "Y": Y, "M": M,
            "sizes": rng.integers(1, 13, (B, N_RECV)).astype(np.int8),
            "trick": rng.integers(1, 26, B), "role": rng.integers(0, 4, B),
            "deal": np.repeat(np.arange(R), rows_per_round),
            "row_round": np.repeat(np.arange(R), rows_per_round),
            "row_ply": np.r_[0, rng.integers(0, T, B - 1)], "row_seat": rng.integers(0, 4, B),
            "_rounds": rounds}


@pytest.fixture()
def package(tmp_path):
    """A small exported package (and the torch model it came from)."""
    torch.manual_seed(0)
    m = bs.build_model(**SMALL)
    with torch.no_grad():
        m.null_kv.normal_(0, 0.5)       # the zero-initialised null slot must matter
        for p in m.parameters():
            p.add_(0.05 * torch.randn_like(p))
    ck = tmp_path / "src.pt"
    torch.save({"model": m.state_dict(), "config": m.config, "args": {"no_history": False},
                "epoch": 1, "calib_ll": 1.0}, ck)
    info = bsm.export(str(ck), str(tmp_path / "pkg.npz"), temperature=TEMPERATURE)
    return tmp_path / "pkg.npz", info, m


def model_from(path) -> object:
    init = bs.load_init(str(path))
    m = bs.build_model(**init["config"])
    bs.apply_init(m, init)
    m.eval()
    return m, init


def batch_of(part, rows_per_round: int = 6):
    rids = np.unique(part["row_round"])
    return bs.make_batch(part, rids, np.arange(len(part["X"])))


def test_package_init_matches_the_numpy_runtime(package):
    path, info, _ = package
    m, init = model_from(path)
    assert init["kind"] == "package" and init["sha256"] == info["sha256"]
    assert init["temperature"] == pytest.approx(TEMPERATURE) and init["config"] == SMALL
    b = batch_of(synthetic_part(4, 30, 6, seed=1))
    with torch.no_grad():
        ref = m(bs.to_torch(b)).numpy().astype(np.float64)
    worst = {}
    for dtype in (np.float64, np.float32):
        pkg = bn.load_belief_numpy(path, info["sha256"], dtype=dtype)
        diffs = []
        for j in range(len(b["X"])):
            inp = bsm.row_inputs(b, j)
            diffs.append(np.abs(pkg.logits(inp).astype(np.float64) - ref[j])[inp["M"]].max())
            if j < 3:
                pr = masked_softmax(ref[j][None], inp["M"][None], pkg.temperature)[0]
                assert np.abs(pkg.marginals(inp) - pr).max() <= PARITY_TOL
        worst[np.dtype(dtype).name] = max(diffs)
    print("parity max abs logit diff", worst)
    assert max(worst.values()) <= PARITY_TOL, worst
    assert (b["ply"] == 0).any() and (b["ply"] > 5).any()


def test_export_of_the_loaded_model_reproduces_the_package(package, tmp_path):
    path, _, src = package
    m, init = model_from(path)
    for k, v in src.state_dict().items():           # float32 both ways: exact
        assert torch.equal(m.state_dict()[k], v), k
    ck = tmp_path / "re.pt"
    torch.save({"model": m.state_dict(), "config": m.config, "args": {"no_history": False}}, ck)
    bsm.export(str(ck), str(tmp_path / "re.npz"), temperature=init["temperature"])
    with np.load(path) as a, np.load(tmp_path / "re.npz") as b:
        assert set(a.files) == set(b.files)
        for k in a.files:
            if k != "metadata":
                assert a[k].dtype == b[k].dtype and np.array_equal(a[k], b[k]), k
        ma, mb = json.loads(str(a["metadata"])), json.loads(str(b["metadata"]))
        assert ma["temperature"] == mb["temperature"] and ma["dims"] == mb["dims"]
    # a checkpoint the trainer writes is an init too, with the same weights
    ck_init = bs.load_init(str(ck))
    assert ck_init["kind"] == "checkpoint" and ck_init["temperature"] is None
    assert all(np.array_equal(ck_init["weights"][k], init["weights"][k]) for k in init["weights"])


def test_architecture_comes_from_the_package_and_conflicts_are_refused(package):
    path, _, _ = package
    init = bs.load_init(str(path))
    args = bs.build_parser().parse_args(["train", "--data", "d", "--out", "o", "--init", str(path)])
    assert bs.resolve_arch(args, init["config"]) == SMALL
    assert (args.d, args.heads, args.x_hidden, args.no_card_self_attn) == (32, 4, 32, False)
    same = bs.build_parser().parse_args(["train", "--data", "d", "--out", "o"] + SMALL_FLAGS)
    assert bs.resolve_arch(same, init["config"]) == SMALL
    for flags in (["--d", "64"], ["--enc-layers", "1"], ["--no-card-self-attn"]):
        bad = bs.build_parser().parse_args(["train", "--data", "d", "--out", "o"] + flags)
        with pytest.raises(bs.BeliefSeqError, match="conflict with --init"):
            bs.resolve_arch(bad, init["config"])


def test_default_architecture_is_unchanged_without_init():
    args = bs.build_parser().parse_args(["train", "--data", "d", "--out", "o"])
    assert args.init is None
    assert bs.resolve_arch(args, None) == dict(d=64, heads=4, enc_layers=1, xattn_layers=2,
                                               x_hidden=256, card_self_attn=True)
    assert (args.d, args.heads, args.enc_layers, args.xattn_layers, args.x_hidden,
            args.no_card_self_attn) == (64, 4, 1, 2, 256, False)
    args = bs.build_parser().parse_args(["train", "--data", "d", "--out", "o", "--d", "48",
                                         "--no-card-self-attn"])
    assert bs.resolve_arch(args, None)["d"] == 48 and args.no_card_self_attn is True


def write_manifest(d, **over):
    d.mkdir(parents=True, exist_ok=True)
    man = {"schema": LABELS_SCHEMA, "feature_dim": FEATURE_DIM, "feature_blocks": FEATURE_BLOCKS,
           "chunks": []}
    man.update(over)
    (d / "manifest.json").write_text(json.dumps(man))
    return d


def test_identity_mismatches_are_refused(package, tmp_path, monkeypatch):
    path, _, _ = package
    init = bs.load_init(str(path))
    good = write_manifest(tmp_path / "good")
    bs.check_init_identity(init, [str(good)])
    for name, over in (("schema", {"schema": "other"}), ("width", {"feature_dim": FEATURE_DIM + 1}),
                       ("blocks", {"feature_blocks": list(FEATURE_BLOCKS)[::-1]})):
        with pytest.raises(bs.BeliefSeqError, match="not the features"):
            bs.check_init_identity(init, [str(good), str(write_manifest(tmp_path / name, **over))])
    wider = dict(bs.trainer_dims(), feature_dim=FEATURE_DIM + 1)
    monkeypatch.setattr(bs, "trainer_dims", lambda: wider)
    with pytest.raises(bs.BeliefSeqError, match="input widths"):
        bs.check_init_identity(init, [str(good)])
    monkeypatch.undo()
    with pytest.raises(bs.BeliefSeqError, match="not a belief package"):
        not_pkg = tmp_path / "x.npz"
        np.savez(not_pkg, a=np.zeros(3))
        bs.load_init(str(not_pkg))


class _PartStream:
    """The train split as one synthetic part, two buffers of whole rounds per epoch."""
    part: dict = {}

    def __init__(self, entries, **kw):
        self.entries = list(entries)
        self.rows = len(self.part["X"])
        self.no_history = kw.get("no_history", False)

    def batches(self, seed, epoch, start_buffer=0, prefetch=6):
        rng = np.random.default_rng(seed + epoch)
        batches = list(bs.round_batches(self.part, 3, rng))
        half = len(batches) // 2
        for gi, chunk in enumerate((batches[:half], batches[half:])):
            if gi < start_buffer:
                continue
            for rids, rows in chunk:
                yield gi, bs.make_batch(self.part, rids, rows, self.no_history)


def _patch_data(monkeypatch, train_part, calib):
    _PartStream.part = train_part
    monkeypatch.setattr(bs, "extract_entries", lambda dirs, split: [{"rows": 1}, {"rows": 1}])
    monkeypatch.setattr(bs, "Stream", _PartStream)
    monkeypatch.setattr(bs, "load_eval", lambda *a, **k: calib)


def test_training_from_init_starts_at_the_loaded_models_loss(package, tmp_path, monkeypatch):
    path, info, _ = package
    data = write_manifest(tmp_path / "data")
    train_part, calib = synthetic_part(8, 30, 5, seed=2), synthetic_part(4, 30, 5, seed=3)
    _patch_data(monkeypatch, train_part, calib)
    first = []
    real_loss = bs.batch_loss

    def spy(model, tb, **kw):
        loss, n = real_loss(model, tb, **kw)
        if not first:
            first.append((float(loss.detach() / n), {k: v.clone() for k, v in tb.items()}))
        return loss, n
    monkeypatch.setattr(bs, "batch_loss", spy)
    out = tmp_path / "ft"
    base = ["train", "--data", str(data), "--out", str(out), "--epochs", "1", "--buffer-chunks", "1",
            "--save-every", "1e9", "--threads", str(torch.get_num_threads()), "--lr", "1e-3"]
    assert bs.main(base + ["--init", str(path)]) == 0
    loss0, tb = first[0]
    ref, _ = model_from(path)
    ref.train()
    with torch.no_grad():
        want, n = real_loss(ref, tb)
    assert loss0 == pytest.approx(float(want / n), rel=1e-6)
    # the same first batch through the NumPy package (float64)
    pkg = bn.load_belief_numpy(path, info["sha256"], dtype=np.float64)
    b = {k: v.numpy() for k, v in tb.items()}
    tot = 0.0
    for j in range(len(b["X"])):
        inp = bsm.row_inputs(b, j)
        z = np.where(inp["M"], pkg.logits(inp), -1e9)
        z = z - z.max(-1, keepdims=True)
        logp = z - np.log(np.exp(z).sum(-1, keepdims=True))
        tot -= float((b["Y"][j] * logp).sum())
    assert tot / float(b["Y"].sum()) == pytest.approx(loss0, rel=1e-5)
    # the run records the warm start and the package temperature
    best = torch.load(out / "best.pt", weights_only=False)
    assert best["init"]["sha256"] == info["sha256"] and best["init"]["kind"] == "package"
    assert best["init"]["temperature"] == pytest.approx(TEMPERATURE)
    lc = bs.predict_logits(ref, calib, no_history=False)
    assert best["init"]["calib_ll"] == pytest.approx(mean_ll(masked_softmax(lc, calib["M"]),
                                                             calib["Y"]), rel=1e-6)
    assert best["config"] == SMALL and best["args"]["d"] == 32
    assert "INIT " in (out / "status.log").read_text()
    # weights moved, and the existing temperature refit + export path still works
    tuned, saved = bs.load_trained(str(out / "best.pt"))
    assert not torch.equal(tuned.state_dict()["x_logits.weight"], ref.state_dict()["x_logits.weight"])
    lt = bs.predict_logits(tuned, calib, no_history=False)
    T = fit_scalar(lambda t: mean_ll(masked_softmax(lt, calib["M"], t), calib["Y"]), 0.25, 4.0)
    res = bsm.export(str(out / "best.pt"), str(tmp_path / "tuned.npz"), temperature=T)
    assert bn.load_belief_numpy(tmp_path / "tuned.npz", res["sha256"]).temperature == pytest.approx(T)

    # without --init the same run starts elsewhere (the weights were not reinitialised)
    first.clear()
    assert bs.main(["train", "--data", str(data), "--out", str(tmp_path / "fresh"), "--epochs", "1",
                    "--buffer-chunks", "1", "--save-every", "1e9",
                    "--threads", str(torch.get_num_threads())] + SMALL_FLAGS) == 0
    assert abs(first[0][0] - loss0) > 1e-3


def test_resume_refuses_a_different_init(package, tmp_path, monkeypatch):
    path, _, _ = package
    data = write_manifest(tmp_path / "data")
    _patch_data(monkeypatch, synthetic_part(6, 20, 4, seed=4), synthetic_part(2, 20, 4, seed=5))
    out = tmp_path / "ft"
    out.mkdir()
    (out / "STOP").touch()
    base = ["train", "--data", str(data), "--out", str(out), "--epochs", "1", "--buffer-chunks", "1",
            "--save-every", "1e9", "--threads", str(torch.get_num_threads())]
    assert bs.main(base + ["--init", str(path)]) == 3
    (out / "STOP").unlink()
    with pytest.raises(bs.BeliefSeqError, match="differs from the run's"):
        bs.main(base + SMALL_FLAGS)
    assert bs.main(base + ["--init", str(path)]) == 0


def test_kitty_weight_scales_only_the_kitty_copies(package):
    _, _, m = package
    part = synthetic_part(3, 20, 4, seed=5)
    rows = np.arange(len(part["X"]))
    tb = bs.to_torch(bs.make_batch(part, np.arange(3), rows))
    m.eval()
    with torch.no_grad():
        base, n = bs.batch_loss(m, tb)
        same, n1 = bs.batch_loss(m, tb, kitty_weight=1.0)
        heavy, n4 = bs.batch_loss(m, tb, kitty_weight=4.0)
        logp = torch.log_softmax(m(tb).float().masked_fill(~tb["M"], -1e9), -1)
    assert float(same) == float(base) and float(n1) == float(n)
    per = -(tb["Y"] * logp)
    want = per[..., :3].sum() + 4.0 * per[..., 3].sum()
    assert float(heavy) == pytest.approx(float(want), rel=1e-6)
    assert float(n4) == pytest.approx(float(tb["Y"][..., :3].sum() + 4.0 * tb["Y"][..., 3].sum()))
    assert float(tb["Y"][..., 3].sum()) > 0
