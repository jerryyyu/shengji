"""Issue #342 finding 2: the training loop pulls its loss sums to the host every N
batches instead of four times per batch.  Same weights, same selection; the epoch's
logged train metrics must agree with the per-batch cadence."""
import numpy as np
import pytest
import torch

# the fixture family is module-local to test_cwv_train; importing registers it here
from tests.test_cwv_train import store_dir,other_dir,records,other_records,luna,blocks  # noqa: F401
from tests.test_cwv_train import THIRDS, train_v0


def test_loss_sync_cadence_does_not_change_training(store_dir, luna, tmp_path, monkeypatch):
    from shengji.train import train_cwv

    luna_path, _rows = luna
    train_v0.train(data=[str(store_dir)], out=tmp_path / "public", device="cpu", epochs=1,
                   seed=7, batch_size=64, n_boot=10, log=None, cache_workers=1,
                   encoder_version=train_cwv.DEFAULTS["encoder_version"], **THIRDS)
    kw = dict(data=[str(store_dir)], eval_luna=str(luna_path), arch="mlp", device="cpu",
              epochs=2, seed=7, batch_size=64, n_boot=20, hidden=32, log=None,
              cache_workers=1, eval_workers=1, bench_batch=32,
              public_head=str(tmp_path / "public" / "best.pt"), **THIRDS)
    monkeypatch.setenv("SHENGJI_CWV_LOSS_SYNC_EVERY", "1")
    per_batch = train_cwv.train(out=tmp_path / "every1", **kw)
    monkeypatch.setenv("SHENGJI_CWV_LOSS_SYNC_EVERY", "32")
    every32 = train_cwv.train(out=tmp_path / "every32", **kw)
    assert per_batch["selection"]["best_loss"] == every32["selection"]["best_loss"]
    assert len(per_batch["epochs"]) == len(every32["epochs"]) == 2
    for a, b in zip(per_batch["epochs"], every32["epochs"]):
        for key in ("loss", "cross_entropy", "rows", "batches"):
            assert np.isclose(a["train"][key], b["train"][key], rtol=1e-6, atol=0), key
        # timing fields differ run to run; every number does not
        strip = lambda d: {k: v for k, v in d.items() if not k.endswith("secs")}
        assert strip(a["val"]) == strip(b["val"])


@pytest.mark.parametrize("where,window", [
    ("first", "wide"),     # bad batch first, flush only at the end of the epoch (partial window)
    ("middle", "wide"),
    ("last", "wide"),
    ("first", "2"),        # bad batch first, a mid-window flush must refuse before the epoch ends
])
def test_an_early_non_finite_loss_is_refused_at_the_next_flush_even_after_finite_batches(
        store_dir, luna, tmp_path, monkeypatch, where, window):
    """Actual training loop (Codex, PR #347): a NaN loss followed by finite losses must
    still raise at the next flush, including when the window ends partway (the final
    partial-window flush).  The flag is a logical AND over the window, never a sum.
    Only TRAINING-mode cross-entropy calls are poisoned; run_eval also calls it."""
    from shengji.train import train_cwv
    from torch import nn

    luna_path, _rows = luna
    train_v0.train(data=[str(store_dir)], out=tmp_path / "public", device="cpu", epochs=1,
                   seed=7, batch_size=64, n_boot=10, log=None, cache_workers=1,
                   encoder_version=train_cwv.DEFAULTS["encoder_version"], **THIRDS)
    kw = dict(data=[str(store_dir)], eval_luna=str(luna_path), arch="mlp", device="cpu",
              epochs=1, seed=7, batch_size=64, n_boot=20, hidden=32, log=None,
              cache_workers=1, eval_workers=1, bench_batch=32,
              public_head=str(tmp_path / "public" / "best.pt"), **THIRDS)
    clean = train_cwv.train(out=tmp_path / "clean", **kw)
    n_train = int(clean["epochs"][0]["train"]["batches"])
    assert n_train >= 2
    bad = {"first": 0, "middle": n_train // 2, "last": n_train - 1}[where]
    real_ce = nn.functional.cross_entropy
    seen = {"train_calls": 0}

    def poisoned(logits, target, *a, **k):
        value = real_ce(logits, target, *a, **k)
        if logits.requires_grad:              # training forward; run_eval runs under no_grad
            k_ = seen["train_calls"]; seen["train_calls"] += 1
            if k_ == bad:
                # TRANSIENT: NaN value, zero gradient, so the weights stay finite and
                # every later batch is finite. A summed flag hides exactly this case;
                # a NaN that poisons the weights would be caught by accident.
                return value * 0.0 + float("nan")
        return value
    monkeypatch.setattr(nn.functional, "cross_entropy", poisoned)
    monkeypatch.setenv("SHENGJI_CWV_LOSS_SYNC_EVERY", str(n_train + 5) if window == "wide" else window)
    with pytest.raises(train_cwv.TrainError, match="non-finite"):
        train_cwv.train(out=tmp_path / "poisoned", **kw)
    assert seen["train_calls"] > bad
    if window == "2":
        # refused at the first flush after the bad batch, not at the end of the epoch
        assert seen["train_calls"] <= bad + 2
