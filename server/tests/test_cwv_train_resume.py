"""``train_cwv --resume-epoch``: a run stopped after a complete epoch continues.

1. Exact: a run stopped after epoch 2 and resumed from its state file ends
   with the SAME epoch-3 weights, EMA, epoch rows, selection and final
   metrics as the run that never stopped (CPU, deterministic algorithms).
2. Legacy (no state file, ``--resume-legacy``): the weights, the EMA, the
   step count, the selector and the epoch rows of epochs 1..2 are restored
   from the epoch checkpoints; the LR continues at the same step; the
   receipt says the optimizer moments and the data order restarted.
3. Refusals: a config that differs, a finished run, a later epoch on disk,
   a partial write, a stateless checkpoint without ``--resume-legacy``.
"""
from __future__ import annotations

import shutil

import pytest

torch = pytest.importorskip("torch")

from shengji.rl.value_model import model_state_sha256  # noqa: E402
from shengji.train import train_cwv  # noqa: E402

from test_cwv_train import (  # noqa: E402, F401  (module fixtures)
    EXPLORE, SEED0, THIRDS, WORK, _records, records, store_dir)

STOP_AFTER = 2
EPOCHS = 3


class _Stop(RuntimeError):
    pass


def _kw(store_dir):
    return dict(data=[str(store_dir)], arch="mlp", device="cpu", epochs=EPOCHS, seed=7,
                batch_size=64, n_boot=10, hidden=32, log=None, cache_workers=1,
                eval_workers=1, bench_batch=16, aux_points=True, aux_weight=1.0,
                val_rank_records=50, served_rank_deals=5, served_rank_per_bucket=2,
                select_metric="val_served_rank_regret", lr_schedule="cosine",
                lr_final_scale=0.1, weight_average="ema", ema_decay=0.9,
                select_averaged=True, patience=20, **THIRDS)


def _strip(value):
    """Drop wall-clock fields (keys ending in ``secs``) and memo paths (the two runs
    write different output directories) for an exact comparison."""
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items()
                if not str(k).endswith("secs") and k not in ("saved_to", "loaded_from")}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def _state(path):
    model, meta, aux = train_cwv.load_cwv_checkpoint(path, "cpu")
    return model, meta, aux


def _same_weights(a, b):
    ma, _m, aa = _state(a)
    mb, _m, ab = _state(b)
    sa, sb = ma.state_dict(), mb.state_dict()
    xa, xb = aa.state_dict(), ab.state_dict()
    return (list(sa) == list(sb) and all(torch.equal(sa[k], sb[k]) for k in sa)
            and all(torch.equal(xa[k], xb[k]) for k in xa))


@pytest.fixture(scope="module")
def runs(store_dir, tmp_path_factory, request):
    root = tmp_path_factory.mktemp("cwv-resume")
    kw = _kw(store_dir)
    full = train_cwv.train(out=root / "full", **kw)

    real = train_cwv.save_resume_state

    def stop_after(out_dir, epoch, **k):
        path = real(out_dir, epoch, **k)
        if epoch == STOP_AFTER:
            raise _Stop("simulated stop after a complete epoch")
        return path

    mp = pytest.MonkeyPatch()
    mp.setattr(train_cwv, "save_resume_state", stop_after)
    try:
        with pytest.raises(_Stop):
            train_cwv.train(out=root / "stopped", **kw)
    finally:
        mp.undo()
    # the stopped directory, three ways: exact resume, legacy resume, refusals
    shutil.copytree(root / "stopped", root / "legacy")
    shutil.rmtree(root / "legacy" / "resume")
    shutil.copytree(root / "stopped", root / "refuse")
    exact = train_cwv.train(out=root / "stopped", resume_epoch=STOP_AFTER, **kw)
    return root, kw, full, exact


def test_exact_resume_reproduces_the_uninterrupted_run(runs):
    root, kw, full, exact = runs
    assert exact["resume"]["mode"] == "exact"
    assert exact["resume"]["optimizer"] == "restored"
    assert [r["epoch"] for r in exact["epochs"]] == list(range(1, EPOCHS + 1))
    assert _strip(exact["epochs"]) == _strip(full["epochs"])
    for name in ("epoch-03.pt", "epoch-03.avg.pt"):
        assert _same_weights(root / "full" / "checkpoints" / name,
                             root / "stopped" / "checkpoints" / name), name
    assert _same_weights(root / "full" / "best.pt", root / "stopped" / "best.pt")
    assert exact["best_epoch"] == full["best_epoch"]
    assert _strip(exact["selection"]) == _strip(full["selection"])
    assert _strip(exact["final"]) == _strip(full["final"])
    assert exact["config_sha256"] == full["config_sha256"]
    assert (root / "stopped" / "resume" / "epoch-03.state.pt").is_file()


def test_legacy_resume_restores_weights_ema_steps_and_selection(runs):
    root, kw, full, _exact = runs
    with pytest.raises(train_cwv.TrainError, match="--resume-legacy"):
        train_cwv.train(out=root / "legacy", resume_epoch=STOP_AFTER, resume_check=True, **kw)
    check = train_cwv.train(out=root / "legacy", resume_epoch=STOP_AFTER, resume_legacy=True,
                            resume_check=True, **kw)["resume_check"]
    ck = root / "legacy" / "checkpoints"
    raw, _m, _a = _state(ck / f"epoch-{STOP_AFTER:02d}.pt")
    avg, _m, _a = _state(ck / f"epoch-{STOP_AFTER:02d}.avg.pt")
    assert check["mode"] == "legacy"
    assert check["weights_state_sha256"] == model_state_sha256(raw)
    assert check["averaged_state_sha256"] == model_state_sha256(avg)
    assert check["step_count"] == full["epochs"][STOP_AFTER - 1]["train"]["steps"]
    assert check["epochs_restored"] == list(range(1, STOP_AFTER + 1))

    got = train_cwv.train(out=root / "legacy", resume_epoch=STOP_AFTER, resume_legacy=True, **kw)
    res = got["resume"]
    assert res["mode"] == "legacy" and res["optimizer"].startswith("re-initialised")
    assert res["data_order"].startswith("fresh streams")
    assert [r["epoch"] for r in got["epochs"]] == list(range(1, EPOCHS + 1))
    for mine, ref in zip(got["epochs"][:STOP_AFTER], full["epochs"][:STOP_AFTER]):
        assert _strip(mine["val"]) == _strip(ref["val"])
        assert mine["train"]["steps"] == ref["train"]["steps"]
        assert mine["train"]["lr_end"] == pytest.approx(ref["train"]["lr_end"], rel=1e-12)
    last, ref = got["epochs"][-1]["train"], full["epochs"][-1]["train"]
    if last["batches"] == ref["batches"]:
        # the schedule is a function of the step count alone
        assert last["steps"] == ref["steps"] and last["lr_end"] == ref["lr_end"]
    replay = res["selection_replay"]
    assert [r["epoch"] for r in replay] == list(range(1, STOP_AFTER + 1))
    assert got["selection"]["metric"] == full["selection"]["metric"]


def test_resume_refusals(runs):
    root, kw, _full, _exact = runs
    with pytest.raises(train_cwv.TrainError, match="config differs"):
        train_cwv.train(out=root / "refuse", resume_epoch=STOP_AFTER,
                        **{**kw, "lr": kw.get("lr", 3e-4) * 2})
    with pytest.raises(train_cwv.TrainError, match="the run finished"):
        train_cwv.train(out=root / "full", resume_epoch=STOP_AFTER, **kw)
    with pytest.raises(train_cwv.TrainError, match="later epoch"):
        train_cwv.train(out=root / "refuse", resume_epoch=1, **kw)
    (root / "refuse" / "checkpoints" / "epoch-03.pt.tmp").write_bytes(b"")
    with pytest.raises(train_cwv.TrainError, match="partial"):
        train_cwv.train(out=root / "refuse", resume_epoch=STOP_AFTER, **kw)
    with pytest.raises(train_cwv.TrainError, match="need --resume-epoch"):
        train_cwv.train(out=root / "refuse", resume_legacy=True, **kw)



