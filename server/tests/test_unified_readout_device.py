"""`train.unified_readout --device`: the CPU path is the one it always was, an MPS run tracks it, and an MPS
checkpoint loads on the CPU.

The trainer runs its production path (`train`, `cache`, `polish` through `main`) on the synthetic store of
``test_unified_seq`` with a small scratch trunk.  ``CPU_REFERENCE`` holds the losses the CPU path gives on
this fixture; a change to the CPU path's arithmetic moves them past ``CPU_REL_TOL``.
"""
from __future__ import annotations

import errno
import hashlib
import json
import shutil
import subprocess
import sys
import time
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
#: no change of the computation.  The joint trainer's losses agree across platforms within 1e-4; the polish
#: trains on a float16 cache, where a last-bit difference in the trunk flips some roundings, and a Linux x86
#: BLAS lands ~3e-3 from the macOS arm64 reference
CPU_REL_TOL = {"train": 1e-4, "polish": 1e-2}
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
def cpu_root(data, tmp_path_factory):
    root = tmp_path_factory.mktemp("cpu-default")
    return root, run_fixture(data, root)


@pytest.fixture(scope="module")
def cpu_default(cpu_root):
    return cpu_root[1]


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
    _close(cpu_default["train"], CPU_REFERENCE["train"], CPU_REL_TOL["train"])
    _close(cpu_default["polish"], CPU_REFERENCE["polish"], CPU_REL_TOL["polish"])


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


def _cache_copy(cpu_root, tmp_path) -> Path:
    cache = tmp_path / "cache"
    shutil.copytree(cpu_root[0] / "cache", cache)
    return cache


def _shard_bytes(cache: Path) -> dict:
    return {p.name: (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(cache.glob("*.npz"))}


def _cache_argv(data, cpu_root, cache, *extra):
    return ["cache", "--ckpt", str(cpu_root[0] / "train" / "best.pt"), "--data", str(data), "--out", str(cache),
            "--threads", "1", "--group-chunks", "1", "--calib-rows", "100000", *extra]


def test_a_cpu_cache_records_its_device(cpu_root):
    cache = cpu_root[0] / "cache"
    assert json.loads((cache / ur.CACHE_DEVICE).read_text()) == {"device": "cpu"}


@pytest.mark.parametrize("record", [True, False], ids=["recorded-cpu", "metadata-free"])
def test_a_cpu_cache_refuses_an_mps_producer_and_keeps_its_shards(data, cpu_root, tmp_path, monkeypatch, record):
    cache = _cache_copy(cpu_root, tmp_path)
    if not record:
        (cache / ur.CACHE_DEVICE).unlink()          # a cache written before producers recorded a device
    (cache / "train-0000.npz").unlink()             # a shard still to make: the run would write before the fix
    before = _shard_bytes(cache)
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: True)
    with pytest.raises(ur.UnifiedReadoutError, match="cpu"):
        ur.main(_cache_argv(data, cpu_root, cache, "--device", "mps"))
    assert _shard_bytes(cache) == before
    assert (cache / ur.CACHE_DEVICE).exists() == record


@pytest.mark.parametrize("record", [True, False], ids=["recorded-cpu", "metadata-free"])
def test_a_cpu_cache_continues_on_the_cpu(data, cpu_root, tmp_path, record):
    cache = _cache_copy(cpu_root, tmp_path)
    if not record:
        (cache / ur.CACHE_DEVICE).unlink()
    want = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(cache.glob("*.npz"))}
    (cache / "train-0000.npz").unlink()
    kept = _shard_bytes(cache)
    assert ur.main(_cache_argv(data, cpu_root, cache, "--device", "cpu")) == 0
    after = _shard_bytes(cache)
    assert {k: after[k] for k in kept} == kept         # kept shards are not rewritten
    assert {k: v[1] for k, v in after.items()} == want  # the remade shard is the one the first run made
    assert json.loads((cache / ur.CACHE_DEVICE).read_text()) == {"device": "cpu"}


def test_the_first_producer_binds_a_cache_for_every_worker(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    ur.bind_cache_device(cache, "mps")
    ur.bind_cache_device(cache, "mps")               # another mps worker, or an mps resume, continues
    with pytest.raises(ur.UnifiedReadoutError, match="--device mps, not --device cpu"):
        ur.bind_cache_device(cache, "cpu")
    assert sorted(p.name for p in cache.iterdir()) == [ur.CACHE_DEVICE]


@pytest.mark.parametrize("device", ["mps", "cpu"])
def test_a_marker_published_after_the_first_look_is_read_before_the_output_is_classified(tmp_path, monkeypatch,
                                                                                        device):
    cache = tmp_path / "cache"
    cache.mkdir()
    real = ur._cache_has_output

    def worker_b_publishes(out):                     # B binds mps and finishes between A's two looks
        (out / ur.CACHE_DEVICE).write_text(json.dumps({"device": "mps"}))
        (out / "DONE.1").write_text("{}")
        return real(out)
    monkeypatch.setattr(ur, "_cache_has_output", worker_b_publishes)
    if device == "mps":
        ur.bind_cache_device(cache, "mps")
    else:
        with pytest.raises(ur.UnifiedReadoutError, match="--device mps, not --device cpu"):
            ur.bind_cache_device(cache, "cpu")
    assert json.loads((cache / ur.CACHE_DEVICE).read_text()) == {"device": "mps"}


@pytest.mark.parametrize("text", ["", "{\"dev", "[]"], ids=["empty", "torn", "not-an-object"])
def test_an_unreadable_marker_refuses_clearly_after_a_bounded_wait(tmp_path, monkeypatch, text):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / ur.CACHE_DEVICE).write_text(text)       # what an interrupted non-atomic publisher left behind
    monkeypatch.setattr(ur, "MARKER_WAIT_S", 0.2)
    t0 = time.monotonic()
    with pytest.raises(ur.UnifiedReadoutError, match="unreadable"):
        ur.bind_cache_device(cache, "mps")
    assert time.monotonic() - t0 < 2.0
    assert (cache / ur.CACHE_DEVICE).read_text() == text


def test_a_publisher_killed_before_its_link_leaves_a_cache_that_resumes(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / f"{ur.CACHE_DEVICE}.99999.tmp").write_text("{\"dev")   # killed while writing its private copy
    ur.bind_cache_device(cache, "mps")
    assert json.loads((cache / ur.CACHE_DEVICE).read_text()) == {"device": "mps"}
    ur.bind_cache_device(cache, "mps")


def test_storage_without_hard_links_is_refused_before_a_marker_exists(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()

    def no_links(src, dst):
        raise OSError(errno.ENOTSUP, "Operation not supported")
    monkeypatch.setattr(ur.os, "link", no_links)
    with pytest.raises(ur.UnifiedReadoutError, match="hard links"):
        ur.bind_cache_device(cache, "mps")
    assert list(cache.iterdir()) == []


def test_an_mps_cache_refuses_a_cpu_worker_through_main(data, cpu_root, tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    ur.bind_cache_device(cache, "mps")
    with pytest.raises(ur.UnifiedReadoutError, match="--device mps"):
        ur.main(_cache_argv(data, cpu_root, cache, "--worker", "1", "--workers", "2"))
    assert sorted(p.name for p in cache.iterdir()) == [ur.CACHE_DEVICE]


BENCH = Path(__file__).resolve().parents[1] / "scripts" / "bench_unified_readout_device.py"


def _bench(*argv, timeout=120):
    return subprocess.run([sys.executable, str(BENCH), *argv], capture_output=True, text=True, timeout=timeout)


def _empty_shard(path: Path) -> None:
    z = {"S": np.zeros((0, 1), np.float16), "c": np.zeros((0, 1), np.float16), "leaf_row": np.zeros(0, np.int32)}
    np.savez(path, **z)


@pytest.mark.parametrize("shards", ["none", "empty"])
def test_the_polish_bench_fails_on_a_cache_with_no_batch(cpu_root, tmp_path, shards):
    cache = tmp_path / "cache"
    cache.mkdir()
    if shards == "empty":
        _empty_shard(cache / "train-0000.npz")
        _empty_shard(cache / "train-0001.npz")
    try:
        res = _bench("polish", "--ckpt", str(cpu_root[0] / "train" / "best.pt"), "--cache", str(cache), "--steps", "2",
                     "--warmup", "0", timeout=60)
    except subprocess.TimeoutExpired:
        pytest.fail("the bench spun without a batch")
    assert res.returncode != 0
    assert ("no train-*.npz shards" if shards == "none" else "yielded no batch") in res.stderr, res.stderr


@pytest.mark.parametrize("flag", [("--steps", "0"), ("--warmup", "-1"), ("--batch", "0")])
def test_the_polish_bench_refuses_bad_counts(cpu_root, tmp_path, flag):
    res = _bench("polish", "--ckpt", str(cpu_root[0] / "train" / "best.pt"), "--cache", str(cpu_root[0] / "cache"), *flag)
    assert res.returncode == 2 and flag[0] in res.stderr, res.stderr


def test_the_polish_bench_wall_interval_covers_the_load_it_reports(cpu_root, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("bench_unified_readout_device", BENCH)
    bench = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bench)
    real_load = np.load

    def slow_load(path, *a, **k):
        if Path(path).name.startswith("train-"):
            time.sleep(0.3)
        return real_load(path, *a, **k)
    monkeypatch.setattr(np, "load", slow_load)
    args = bench.build_parser().parse_args(["polish", "--ckpt", str(cpu_root[0] / "train" / "best.pt"),
                                            "--cache", str(cpu_root[0] / "cache"), "--batch", "1000000",
                                            "--warmup", "0", "--steps", "1", "--threads", "1"])
    out = bench.bench_polish(args)
    assert out["steps"] == 1 and out["share"]["shard_load"] > 0
    assert out["wall_s"] >= out["step_s_median"] >= 0.3       # the one timed step, its shard load included
    assert out["recipe"] == bench.POLISH_RECIPE


def test_buffer_report_matches_the_full_prefix_after_resume(tmp_path):
    clusters = [synthetic_cluster(s) for s in range(1000, 1012)]
    data = extract_dir(write_store(tmp_path / "store", clusters), tmp_path / "data",
                       calib=0.25, task_clusters=1)
    common = ["train", "--data", str(data), "--scratch-arch", SCRATCH, "--threads", "1",
              "--loader-threads", "1", "--rounds-per-batch", "1", "--buffer-chunks", "1",
              "--report-buffer", "2", "--save-every", "999999"]
    baseline, split = tmp_path / "baseline", tmp_path / "split"
    assert ur.main(common + ["--out", str(baseline)]) == 0
    split.mkdir()
    stop = split / "STOP"
    stop.touch()
    assert ur.main(common + ["--out", str(split)]) == 3
    report = "epoch-1-buffer-2.json"
    assert not (split / report).exists()
    stop.unlink()
    assert ur.main(common + ["--out", str(split)]) == 0
    actual = json.loads((split / report).read_text())
    assert actual["epoch"] == 1 and actual["completed_buffers"] == 2
    assert actual["rows"] > 0 and actual["leaves"] > 0
    assert actual["train"]["leaf_value"] > 0 and actual["train"]["policy"] > 0
    assert actual == json.loads((baseline / report).read_text())


def test_size_stop_rule_consumes_warm_trainer_reports(cpu_root, data, tmp_path):
    # Equal weights with distinct checkpoint bytes give an exact zero-delta control.
    original = cpu_root[0] / "train" / "best.pt"
    saved = torch.load(original, weights_only=False, map_location="cpu")
    saved["fixture_arm"] = "medium"
    other = tmp_path / "medium-init.pt"
    torch.save(saved, other)
    gate = [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts" / "sz2_offline_gate.py"),
            "--buffer", "1"]
    for arm, init in (("small", original), ("medium", other)):
        out = tmp_path / arm
        assert ur.main(["train", "--data", str(data), "--out", str(out), "--init-readout-ckpt", str(init),
                        "--threads", "1", "--loader-threads", "1", "--rounds-per-batch", "1",
                        "--buffer-chunks", "1", "--report-buffer", "1"]) == 0
        gate.extend([f"--{arm}", str(out), f"--{arm}-init-sha", hashlib.sha256(init.read_bytes()).hexdigest()])

    def decision(expected_rc, expected_text):
        result = subprocess.run(gate, capture_output=True, text=True)
        assert result.returncode == expected_rc, (result.stdout, result.stderr)
        assert expected_text in result.stdout + result.stderr

    decision(3, "FAIL-OFFLINE")
    for name, threshold in (("leaf_value", 0.002), ("policy", 0.015)):
        for arm, loss in (("small", threshold), ("medium", 0)):
            path = tmp_path / arm / "epoch-1-buffer-1.json"
            report = json.loads(path.read_text())
            report["train"].update(leaf_value=0, policy=0)
            report["train"][name] = loss
            path.write_text(json.dumps(report))
        decision(0, "CONTINUE")
    settings = tmp_path / "medium" / "run.json"
    original_settings = settings.read_text()
    settings.write_text(json.dumps({**json.loads(original_settings), "seed": 9}))
    decision(2, "training settings")
    settings.write_text(original_settings)
    report["rows"] += 1
    path.write_text(json.dumps(report))
    decision(2, "prefix counts differ")
    path.unlink()
    decision(2, "INVALID")
    gate[-1] = "0" * 64
    decision(2, "expected warm start")
