"""Belief trainer speed options (``belief_seq train --grouped-xattn/--bf16/--compile``).

Every option keeps the weights, state_dict keys, config and export schema; the
grouped cross-attention and the compiled forward compute the same function as
the per-row eager forward (fp32, up to summation order), and bf16 autocast
stays within a stated loss tolerance with fp32 parameters and optimizer state.
"""
from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from shengji.train import belief_sampler as bsm  # noqa: E402
from shengji.train import belief_seq as bs  # noqa: E402
from shengji.train.belief_history import N_CARD_FEATURES, N_TOKEN_FLOAT  # noqa: E402
from shengji.train.belief_labels import FEATURE_DIM, N_RECV  # noqa: E402

SMALL = dict(d=32, heads=4, enc_layers=2, xattn_layers=2, x_hidden=32, card_self_attn=True)
FP32_REL = 1e-5
BF16_LOSS_REL = 1e-2


def synthetic_batch(R: int, T: int, B: int, seed: int = 0):
    """Rows in arbitrary frame order, at least one empty frame and a ply-0 row."""
    rng = np.random.default_rng(seed)
    b = {"tok_int": np.stack([rng.integers(0, 4, (R, T)), rng.integers(0, 4, (R, T)),
                              rng.integers(0, 25, (R, T)), rng.integers(0, 5, (R, T))], -1),
         "tok_f": rng.random((R, T, N_TOKEN_FLOAT), dtype=np.float32),
         "tok_cards": (rng.random((R, T, 54)) < 0.05).astype(np.float32),
         "tok_att": (rng.random((R, T, 54)) < 0.02).astype(np.float32),
         "card_feat": rng.random((R, 54, N_CARD_FEATURES), dtype=np.float32),
         "banker": rng.integers(0, 4, R),
         "X": rng.random((B, FEATURE_DIM + 4), dtype=np.float32),
         "row_card": rng.random((B, 54, bs.N_ROW_CARD), dtype=np.float32),
         "M": rng.random((B, 54, N_RECV)) < 0.6,
         "rr": rng.integers(0, R, B), "seat": rng.integers(0, 4, B), "ply": rng.integers(0, T, B)}
    b["seat"][b["rr"] == 0] = rng.integers(1, 4, int((b["rr"] == 0).sum()))  # frame 0 is empty
    b["ply"][0] = 0
    b["M"][..., 0] = True
    b["Y"] = (b["M"] & (rng.random((B, 54, N_RECV)) < 0.2)).astype(np.float32)
    return bs.to_torch(b)


@pytest.fixture()
def model():
    torch.manual_seed(0)
    m = bs.build_model(**SMALL)
    with torch.no_grad():
        m.null_kv.normal_(0, 0.5)       # the zero-initialised null slot must matter
    return m


def loss_and_grads(model, fwd, tb, *, bf16=False):
    model.zero_grad()
    loss, n = bs.batch_loss(fwd, tb, bf16=bf16)
    (loss / n).backward()
    return float(loss.detach() / n), {k: p.grad.clone() for k, p in model.named_parameters()}


def max_rel(a, b):
    return float((a - b).abs().max() / b.abs().max().clamp_min(1e-30))


def assert_grads_close(got, ref, tol):
    assert got.keys() == ref.keys()
    for k in ref:
        assert max_rel(got[k], ref[k]) <= tol, k


def test_speed_flags_default_off():
    a = bs.build_parser().parse_args(["train", "--data", "d", "--out", "o"])
    assert (a.grouped_xattn, a.bf16, a.compile) == (False, False, False)
    m = bs.build_model(**SMALL)
    fwd, bf16 = bs.apply_speed_flags(m, a)
    assert fwd is m and bf16 is False and m.grouped_xattn is False


def test_grouped_xattn_matches_the_per_row_forward_and_grads(model):
    tb = synthetic_batch(4, 20, 60)
    assert int(torch.bincount(tb["rr"] * 4 + tb["seat"], minlength=16)[0]) == 0
    with torch.no_grad():
        ref = model(tb)
        model.grouped_xattn = True
        got = model(tb)
        model.grouped_xattn = False
    assert max_rel(got, ref) <= FP32_REL
    l0, g0 = loss_and_grads(model, model, tb)
    model.grouped_xattn = True
    l1, g1 = loss_and_grads(model, model, tb)
    assert abs(l1 - l0) <= FP32_REL * abs(l0)
    assert_grads_close(g1, g0, FP32_REL)


def test_grouped_xattn_keeps_the_causal_history_mask(model):
    model.grouped_xattn = True
    model.eval()
    tb = synthetic_batch(2, 12, 16, seed=4)
    with torch.no_grad():
        base = model(tb)
        later = {k: v.clone() for k, v in tb.items()}
        later["tok_f"] += torch.arange(12)[None, :, None] >= 6       # rewrite plies 6..
        got = model(later)
    early = tb["ply"] <= 6
    assert early.any() and (~early).any()
    assert torch.allclose(got[early], base[early], atol=1e-6)
    assert not torch.allclose(got[~early], base[~early], atol=1e-6)


def test_bf16_loss_is_close_to_fp32_and_state_stays_fp32(model):
    tb = synthetic_batch(4, 20, 60, seed=1)
    l0, _ = loss_and_grads(model, model, tb)
    for grouped in (False, True):
        model.grouped_xattn = grouped
        lb, gb = loss_and_grads(model, model, tb, bf16=True)
        assert abs(lb - l0) <= BF16_LOSS_REL * abs(l0)
        assert all(torch.isfinite(g).all() and g.dtype == torch.float32 for g in gb.values())
    with torch.autocast("cpu", dtype=torch.bfloat16):
        assert model(tb).dtype == torch.float32          # the output heads stay fp32
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3)
    opt.step()
    assert all(p.dtype == torch.float32 for p in model.parameters())
    assert all(v.dtype == torch.float32 for s in opt.state.values() for v in s.values()
               if torch.is_tensor(v) and v.is_floating_point())


def test_compiled_forward_matches_eager_across_shapes(model):
    model.grouped_xattn = True
    fwd = bs.compile_forward(model)
    for R, T, B, seed in ((4, 20, 60, 0), (5, 23, 71, 3)):     # a second shape: dynamic, no error
        tb = synthetic_batch(R, T, B, seed)
        l0, g0 = loss_and_grads(model, model, tb)
        l1, g1 = loss_and_grads(model, fwd, tb)
        assert abs(l1 - l0) <= FP32_REL * abs(l0)
        assert_grads_close(g1, g0, FP32_REL)
    assert set(fwd.state_dict()) == {"_orig_mod." + k for k in model.state_dict()}


def test_state_dict_keys_and_checkpoints_are_shared_by_every_mode(model, tmp_path):
    keys = list(model.state_dict())
    ref = synthetic_batch(3, 10, 20, seed=2)
    with torch.no_grad():
        want = model(ref)
    ck = tmp_path / "plain.pt"
    torch.save({"model": model.state_dict(), "config": model.config}, ck)
    for grouped in (False, True):
        m = bs.build_model(**SMALL)
        m.grouped_xattn = grouped
        m.load_state_dict(torch.load(ck, weights_only=False)["model"])     # strict
        assert list(m.state_dict()) == keys and m.config == model.config
        with torch.no_grad():
            assert max_rel(m(ref), want) <= FP32_REL


def test_export_schema_is_unchanged_by_the_flags(model, tmp_path):
    def export(m, name):
        ck = tmp_path / f"{name}.pt"
        torch.save({"model": m.state_dict(), "config": m.config, "args": {"no_history": False},
                    "epoch": 1, "calib_ll": 1.0}, ck)
        bsm.export(str(ck), str(tmp_path / f"{name}.npz"), temperature=1.0)
        with np.load(tmp_path / f"{name}.npz") as z:
            return {k: (z[k].shape, z[k].dtype) for k in z.files}, str(z["config"])
    plain = export(model, "plain")
    args = bs.build_parser().parse_args(["train", "--data", "d", "--out", "o", "--grouped-xattn",
                                         "--bf16"])
    fwd, bf16 = bs.apply_speed_flags(model, args)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3)
    loss, n = bs.batch_loss(fwd, synthetic_batch(3, 10, 20), bf16=bf16)
    (loss / n).backward()
    opt.step()
    assert export(model, "flags") == plain


def test_compile_with_bf16_runs_and_stays_close_to_fp32(model):
    tb = synthetic_batch(4, 20, 60, seed=5)
    l0, _ = loss_and_grads(model, model, tb)
    model.grouped_xattn = True
    lb, gb = loss_and_grads(model, bs.compile_forward(model), tb, bf16=True)
    assert abs(lb - l0) <= BF16_LOSS_REL * abs(l0)
    assert all(torch.isfinite(g).all() and g.dtype == torch.float32 for g in gb.values())


def test_numpy_package_predicts_like_torch_after_a_flagged_update(model, tmp_path):
    from shengji.ai import belief_numpy as bn
    args = bs.build_parser().parse_args(["train", "--data", "d", "--out", "o", "--grouped-xattn",
                                         "--bf16"])
    fwd, bf16 = bs.apply_speed_flags(model, args)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-2)
    loss, n = bs.batch_loss(fwd, synthetic_batch(3, 10, 20), bf16=bf16)
    (loss / n).backward()
    opt.step()
    ck = tmp_path / "flags.pt"
    torch.save({"model": model.state_dict(), "config": model.config, "args": vars(args),
                "epoch": 1, "calib_ll": 1.0}, ck)
    info = bsm.export(str(ck), str(tmp_path / "flags.npz"), temperature=1.0)
    pkg = bn.load_belief_numpy(tmp_path / "flags.npz", info["sha256"], dtype=np.float64)
    tb = synthetic_batch(3, 14, 24, seed=6)
    batch = {k: v.numpy() for k, v in tb.items()}
    with torch.no_grad():
        model.eval()
        ref = model(tb).numpy().astype(np.float64)        # fp32 eager, as served parity reads it
    for j in range(len(batch["X"])):
        inp = bsm.row_inputs(batch, j)
        assert np.abs(pkg.logits(inp) - ref[j])[inp["M"]].max() <= 1e-4


class _FakeStream:
    """Two one-batch buffers per epoch of synthetic batches (no files)."""

    def __init__(self, entries, **kw):
        self.entries = list(entries)
        self.rows = 40

    def batches(self, seed, epoch, start_buffer=0, prefetch=6):
        for gi in range(start_buffer, len(self.entries)):
            yield gi, {k: v.numpy() for k, v in synthetic_batch(2, 9, 20, seed=10 * epoch + gi).items()}


def test_a_resume_with_other_speed_flags_records_both_segments(tmp_path, monkeypatch):
    calib = {"M": np.ones((5, 54, N_RECV), bool), "Y": np.zeros((5, 54, N_RECV), np.float32),
             "trick": np.ones(5, int), "role": np.zeros(5, int)}
    calib["Y"][:, :, 0] = 1.0
    monkeypatch.setattr(bs, "extract_entries", lambda dirs, split: [{"rows": 20}, {"rows": 20}])
    monkeypatch.setattr(bs, "Stream", _FakeStream)
    monkeypatch.setattr(bs, "load_eval", lambda *a, **k: calib)
    monkeypatch.setattr(bs, "predict_logits",
                        lambda model, part, **k: np.zeros((len(part["M"]), 54, N_RECV), np.float32))
    out = tmp_path / "train"
    base = ["train", "--data", "d", "--out", str(out), "--epochs", "1", "--save-every", "1e9",
            "--threads", str(torch.get_num_threads()), "--d", "16", "--heads", "2", "--enc-layers", "1",
            "--xattn-layers", "1", "--x-hidden", "16"]
    out.mkdir()
    (out / "STOP").touch()
    assert bs.main(base) == 3                                # fp32 per-row, stopped after buffer 0
    (out / "STOP").unlink()
    assert bs.main(base + ["--grouped-xattn", "--bf16"]) == 0
    want = [(0, 0, False, False), (0, 1, True, True)]
    for f in ("checkpoint.pt", "best.pt"):
        saved = torch.load(out / f, weights_only=False)
        segs = saved["state"]["speed_segments"] if f == "checkpoint.pt" else saved["speed_segments"]
        assert [(s["start_epoch"], s["start_buffer"], s["grouped_xattn"], s["bf16"]) for s in segs] == want
        assert all(not s["compile"] and s["utc"] and "inferred" not in s for s in segs)
    log = (out / "status.log").read_text()
    assert "RESUME epoch 0 buffer 1 speed segment 2: grouped_xattn=1 bf16=1 compile=0" in log
