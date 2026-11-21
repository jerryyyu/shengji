"""`train.unified_readout --device`: the CPU path is the one it always was, an MPS run tracks it, and an MPS
checkpoint loads on the CPU.

The trainer runs its production path (`train`, `cache`, `polish` through `main`) on the synthetic store of
``test_unified_seq`` with a small scratch trunk.  ``CPU_REFERENCE`` holds the losses the CPU path gives on
this fixture; a change to the CPU path's arithmetic moves them past ``CPU_REL_TOL``.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from test_belief_labels import synthetic_cluster  # noqa: E402
from test_unified_seq import extract_dir, nt_cluster, write_store  # noqa: E402

from shengji.train import unified_readout as ur  # noqa: E402

SCRATCH = "d=32,heads=4,enc_layers=1,xattn_layers=1,x_hidden=32"
#: an MPS float32 kernel sums in another order than the CPU's.  The joint trainer's few steps stay within
#: 1e-6 of the CPU's; the polish trains on a float16 cache whose rounding can differ, and drifts to ~6e-4
MPS_REL_TOL = {"train": 1e-4, "polish": 5e-3}
#: the CPU reference is float32 arithmetic through the platform's BLAS; this covers BLAS differences and
#: no change of the computation
CPU_REL_TOL = 1e-4
CPU_REFERENCE = {
    "train": {
        "e1_train_belief": 1.368365627979476,
        "e1_train_q": 5.290364642475927,
        "e1_train_policy": 2.1168209342069404,
        "e1_train_leaf_value": 5.133941437477289,
        "e1_train_leaf_value_k0": 5.107103746990825,
        "e1_train_leaf_value_end": 5.101646378982899,
        "e1_train_reply": 2.2885687184888264,
        "e1_calib_belief": 1.357741,
        "e1_calib_q": 5.218449,
        "e1_calib_policy": 2.063665,
        "e1_calib_leaf_value": 2.258221,
        "e1_calib_leaf_value_k0": 2.271666,
        "e1_calib_leaf_value_end": 2.277499,
        "e1_calib_reply": 2.211394,
        "e1_calib_belief_ll": 1.3577414470965254,
        "e2_train_belief": 1.3438183711360898,
        "e2_train_q": 5.2106170654296875,
        "e2_train_policy": 2.1061856913012127,
        "e2_train_leaf_value": 2.3683650526889535,
        "e2_train_leaf_value_k0": 2.3980783196382744,
        "e2_train_leaf_value_end": 2.399019729259402,
        "e2_train_reply": 2.0973687578541362,
        "e2_calib_belief": 1.345586,
        "e2_calib_q": 5.18795,
        "e2_calib_policy": 2.058353,
        "e2_calib_leaf_value": 1.918716,
        "e2_calib_leaf_value_k0": 1.915047,
        "e2_calib_leaf_value_end": 1.910155,
        "e2_calib_reply": 2.177113,
        "e2_calib_belief_ll": 1.345585859482681,
        "init_calib_belief": 1.39019,
        "init_calib_q": 5.310835,
        "init_calib_policy": 2.081864,
        "init_calib_leaf_value": 5.756709,
        "init_calib_leaf_value_k0": 5.730947,
        "init_calib_leaf_value_end": 5.723396,
        "init_calib_reply": 2.264755,
        "init_calib_belief_ll": 1.3901898101139492,
    },
    "polish": {
        "polish_leaf_value": 1.658689710828993,
        "polish_leaf_value_end": 1.696860631306966,
        "polish_reply": 2.1991779186107494,
        "e1_train_leaf_value": 1.34262,
        "e1_train_leaf_value_end": 1.40496,
        "e1_train_reply": 2.07279,
        "e1_calib_leaf_value": 2.79542,
        "e1_calib_leaf_value_end": 2.8169,
        "e1_calib_reply": 2.26107,
        "e2_train_leaf_value": 0.7064,
        "e2_train_leaf_value_end": 0.73996,
        "e2_train_reply": 2.03298,
        "e2_calib_leaf_value": 1.65869,
        "e2_calib_leaf_value_end": 1.69686,
        "e2_calib_reply": 2.19918,
    },
}


def make_data(root: Path) -> Path:
    clusters = [synthetic_cluster(s) for s in (1000, 1001, 1002)] + [nt_cluster(1003)]
    store = write_store(root / "stores" / "corpus", clusters)
    return extract_dir(store, root / "x", calib=0.5, task_clusters=1)


def run_fixture(data: Path, root: Path, device: str | None = None) -> dict:
    """``train`` (2 epochs), ``cache`` and ``polish`` (2 epochs) on ``data``; returns the losses and a digest
    of every checkpoint tensor.  ``device=None`` passes no ``--device`` flag."""
    flag = [] if device is None else ["--device", device]
    out, cache, pout = root / "train", root / "cache", root / "polish"
    rc = ur.main(["train", "--data", str(data), "--out", str(out), "--scratch-arch", SCRATCH, "--epochs", "2",
                  "--threads", "1", "--loader-threads", "1", "--rounds-per-batch", "1", "--buffer-chunks", "1",
                  "--save-every", "0", "--calib-rows", "100000"] + flag)
    assert rc == 0, (out / "status.log").read_text()
    assert ur.main(["cache", "--ckpt", str(out / "best.pt"), "--data", str(data), "--out", str(cache),
                    "--threads", "1", "--group-chunks", "1", "--calib-rows", "100000"] + flag) == 0
    assert ur.main(["polish", "--ckpt", str(out / "best.pt"), "--cache", str(cache), "--out", str(pout),
                    "--epochs", "2", "--batch", "32", "--lr", "3e-4", "--threads", "1"] + flag) == 0
    ck = torch.load(out / "checkpoint.pt", weights_only=False, map_location="cpu")
    pol = torch.load(pout / "best.pt", weights_only=False, map_location="cpu")
    hist = ck["state"]["history"]
    train = {f"e{h['epoch']}_{split}_{k}": float(v) for h in hist for split in ("train", "calib")
             for k, v in h[split].items()}
    train.update({f"init_calib_{k}": float(v) for k, v in ck["state"]["init_calib"].items()})
    polish = {f"polish_{k}": float(v) for k, v in pol["calib"]["polish"].items()}
    for line in (pout / "status.log").read_text().splitlines():
        if " POLISH EPOCH " in line:
            epoch, rest = line.split(" POLISH EPOCH ")[1].split(" train ", 1)
            train_part, calib_part = rest.split(" calib ")
            for split, text in (("train", train_part), ("calib", calib_part.rsplit(" (", 1)[0])):
                polish.update({f"e{epoch}_{split}_{k}": float(v) for k, v in json.loads(text).items()})
    return {"train": train, "polish": polish, "polish_epoch": pol["calib"]["polish_epoch"],
            "digest": {name: _digest(path) for name, path in
                       (("checkpoint", out / "checkpoint.pt"), ("best", out / "best.pt"), ("polish", pout / "best.pt"))},
            "caches": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(cache.glob("*.npz"))}}


def _digest(path: Path) -> str:
    """sha256 of every tensor (model and optimizer state) of a checkpoint, in key order."""
    saved = torch.load(path, weights_only=False, map_location="cpu")
    h = hashlib.sha256()

    def walk(prefix, obj):
        if isinstance(obj, torch.Tensor):
            h.update(prefix.encode())
            h.update(obj.detach().cpu().contiguous().numpy().tobytes())
        elif isinstance(obj, dict):
            for k in sorted(obj, key=str):
                walk(f"{prefix}/{k}", obj[k])
        elif isinstance(obj, (list, tuple)):
            for i, v in enumerate(obj):
                walk(f"{prefix}/{i}", v)
    walk("model", saved["model"])
    walk("opt", saved.get("opt"))
    return h.hexdigest()


def _tensors_on_cpu(obj) -> bool:
    if isinstance(obj, torch.Tensor):
        return obj.device.type == "cpu"
    if isinstance(obj, dict):
        return all(_tensors_on_cpu(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return all(_tensors_on_cpu(v) for v in obj)
    return True


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    return make_data(tmp_path_factory.mktemp("utr-device"))


@pytest.fixture(scope="module")
def cpu_default(data, tmp_path_factory):
    return run_fixture(data, tmp_path_factory.mktemp("cpu-default"))


def _close(got, want, rel):
    assert got.keys() == want.keys()
    bad = {k: (got[k], want[k]) for k in want if abs(got[k] - want[k]) > rel * max(1.0, abs(want[k]))}
    assert not bad, bad


def test_device_cpu_is_the_default_path_bit_for_bit(data, cpu_default, tmp_path):
    cpu = run_fixture(data, tmp_path, "cpu")
    assert cpu == cpu_default
    run = json.loads((tmp_path / "train" / "run.json").read_text())
    assert "device" not in run                     # a CPU run's identity is the one existing runs resume under


def test_the_cpu_path_gives_the_reference_losses(cpu_default):
    _close(cpu_default["train"], CPU_REFERENCE["train"], CPU_REL_TOL)
    _close(cpu_default["polish"], CPU_REFERENCE["polish"], CPU_REL_TOL)


mps = pytest.mark.skipif(not torch.backends.mps.is_available(), reason="MPS is not available")


@mps
def test_an_mps_run_tracks_the_cpu_run_and_its_checkpoints_load_on_the_cpu(data, cpu_default, tmp_path):
    got = run_fixture(data, tmp_path, "mps")
    _close(got["train"], cpu_default["train"], MPS_REL_TOL["train"])
    _close(got["polish"], cpu_default["polish"], MPS_REL_TOL["polish"])
    run = json.loads((tmp_path / "train" / "run.json").read_text())
    assert run["device"] == "mps"
    for path in (tmp_path / "train" / "checkpoint.pt", tmp_path / "train" / "best.pt", tmp_path / "polish" / "best.pt"):
        assert _tensors_on_cpu(torch.load(path, weights_only=False, map_location=None)), path
    model, _ = ur.load_checkpoint(str(tmp_path / "polish" / "best.pt"))
    assert all(p.device.type == "cpu" for p in model.parameters())


@mps
@pytest.mark.parametrize("first,then", [("mps", "cpu"), ("cpu", "mps")])
def test_a_resume_refuses_another_device(data, tmp_path, first, then):
    out = tmp_path / "run"
    common = ["train", "--data", str(data), "--out", str(out), "--scratch-arch", SCRATCH, "--threads", "1",
              "--loader-threads", "1", "--rounds-per-batch", "1", "--buffer-chunks", "1", "--save-every", "0",
              "--calib-rows", "100000"]
    out.mkdir()
    (out / "STOP").touch()
    assert ur.main(common + ["--device", first]) == 3
    (out / "STOP").unlink()
    assert ur.main(common + ["--device", then]) == 1
    assert f"--device {first}" in (out / "status.log").read_text()
    assert ur.main(common + ["--device", first]) == 0


def test_mps_on_a_host_without_it_refuses(data, tmp_path, monkeypatch):
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: False)
    out = tmp_path / "run"
    assert ur.main(["train", "--data", str(data), "--out", str(out), "--scratch-arch", SCRATCH, "--device", "mps"]) == 1
    assert "MPS is not available" in (out / "status.log").read_text()
