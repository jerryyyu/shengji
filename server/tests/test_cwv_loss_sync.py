"""Issue #342 finding 2: the training loop pulls its loss sums to the host every N
batches instead of four times per batch.  Same weights, same selection; the epoch's
logged train metrics must agree with the per-batch cadence."""
import numpy as np


def test_loss_sync_cadence_does_not_change_training(store_dir, luna, tmp_path, monkeypatch):
    from shengji.train import train_cwv
    from tests.test_cwv_train import THIRDS, train_v0

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
