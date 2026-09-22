"""The train loop attributes its epoch wall to stages (2026-09-20).

Before optimising training, measure it: each epoch's ``train.stage_secs`` splits the
train wall into batch_wait (blocked inside iter_batches: decode + gather + worker wait),
to_device, policy_wait, step, sync and the residual.  Host wall only; device work that is
not awaited lands in the next sync.  The key ends in "secs" so exact-reproducibility
comparisons strip it like every other timing.
"""
import math
import json

import pytest

from tests.test_cwv_train import store_dir, other_dir, records, other_records, luna, blocks  # noqa: F401

STAGES = ("batch_wait", "to_device", "policy_wait", "step", "sync", "other", "total")


@pytest.mark.parametrize("loader_timing", [False, True])
def test_every_epoch_reports_finite_stage_seconds_that_add_up(store_dir, luna, tmp_path,
                                                              loader_timing):
    from shengji.train import train_cwv, train_v0
    from tests.test_cwv_train import THIRDS
    luna_path, _rows = luna
    train_v0.train(data=[str(store_dir)], out=tmp_path / "public", device="cpu", epochs=1, seed=7,
                   batch_size=64, n_boot=10, log=None, cache_workers=1,
                   encoder_version=train_cwv.DEFAULTS["encoder_version"], **THIRDS)
    result = train_cwv.train(data=[str(store_dir)], out=tmp_path / "run", eval_luna=str(luna_path),
                             arch="mlp", device="cpu", epochs=2, seed=7, batch_size=64, n_boot=10,
                             hidden=32, log=None, cache_workers=1, eval_workers=1, bench_batch=32,
                             loader_stage_timing=loader_timing,
                             public_head=str(tmp_path / "public" / "best.pt"), **THIRDS)
    saved = json.loads((tmp_path / "run" / "metrics.json").read_text())
    assert saved["epochs"] == result["epochs"]
    for row in result["epochs"]:
        stage = row["train"]["stage_secs"]
        assert set(stage) == set(STAGES)
        assert all(math.isfinite(v) and v >= 0.0 for v in stage.values())
        assert stage["total"] == row["train_secs"]
        assert abs(sum(v for k, v in stage.items() if k != "total") - stage["total"]) < 0.01
        assert stage["policy_wait"] == 0.0          # no policy head in this run
        if loader_timing:
            loader = row["train"]["loader_stage_secs"]
            assert set(loader) == {"setup", "decode", "prepare", "gather", "cleanup"}
            assert all(math.isfinite(v) and v >= 0.0 for v in loader.values())
            # The loader buckets are inside next(generator), excluding the
            # consumer; permit only rounding noise from the five buckets.
            assert sum(loader.values()) <= stage["batch_wait"] + 0.01
        else:
            assert "loader_stage_secs" not in row["train"]
