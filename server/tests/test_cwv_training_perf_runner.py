"""Cheap orchestration tests; these do not train or measure throughput."""
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

from tests.test_cwv_train import store_dir, other_dir, records, other_records, luna, blocks  # noqa: F401
from tests.test_cwv_train import THIRDS, train_v0, train_cwv


@pytest.fixture
def runner():
    path = Path(__file__).parents[1] / "scripts" / "qualify_cwv_training_perf.py"
    spec = importlib.util.spec_from_file_location("training_perf_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def args(tmp_path, runner, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    config = tmp_path / "config.json"
    config.write_text(json.dumps(dict(epochs=1, limit_clusters=32,
                                    cache_dir=str(cache), public_head="head")))
    out = tmp_path / "out"
    argv = ["runner", "--config", str(config), "--out", str(out)]
    monkeypatch.setattr(runner.sys, "argv", argv)
    return argv, out


def test_dry_run_never_launches_or_creates_output(runner, args, monkeypatch):
    _, out = args
    def forbidden(*a, **kw):
        raise AssertionError("dry-run launched a child")
    monkeypatch.setattr(runner.subprocess, "Popen", forbidden)
    runner.main()
    assert not out.exists()


@pytest.mark.parametrize("mismatch", [False, True])
def test_abba_env_same_recipe_and_parity_refusal(runner, args, monkeypatch, mismatch):
    argv, out = args
    argv.append("--run")
    seen = []
    class Process:
        def __init__(self, cmd, **kw):
            self.args = cmd
            assert kw["start_new_session"] is True
            seen.append((kw["env"]["SHENGJI_CWV_LOSS_SYNC_EVERY"],
                         kw["env"]["SHENGJI_CWV_BATCHED_CANDIDATES"]))
            assert Path(cmd[cmd.index("--config") + 1]) == out / "recipe.json"
            dest = Path(cmd[cmd.index("--out") + 1])
            changed = mismatch and len(seen) == 2
            report = dict(wall_seconds=2 if len(seen) in (1, 4) else 1,
                          checkpoints={"best.pt": {"tensor_sha256": "different" if changed else "same", "epoch": 1}},
                          torch_cpu_rng_sha256="rng")
            (dest / "measurement.json").write_text(json.dumps(report))
        def wait(self, timeout):
            return 0
    monkeypatch.setattr(runner.subprocess, "Popen", Process)
    if mismatch:
        with pytest.raises(RuntimeError, match="checkpoint/RNG mismatch"):
            runner.main()
    else:
        runner.main()
    assert seen == [("1", "0"), ("32", "1"), ("32", "1"), ("1", "0")]
    summary = json.loads((out / "summary.json").read_text())
    assert summary["exact_checkpoint_and_cpu_rng_parity"] is (not mismatch)
    assert summary["control_mean_wall"] == 2
    assert summary["optimized_mean_wall"] == 1


def test_timeout_stops_only_private_group_and_does_not_advance(runner, args, monkeypatch):
    argv, out = args
    argv.append("--run")
    launches, signals = [], []
    class Process:
        pid = 876543
        def __init__(self, cmd, **kw):
            launches.append(cmd)
            self.calls = 0
        def wait(self, timeout):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired("benchmark", timeout)
            return -15
    monkeypatch.setattr(runner.subprocess, "Popen", Process)
    monkeypatch.setattr(runner.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    with pytest.raises(subprocess.TimeoutExpired):
        runner.main()
    assert len(launches) == 1
    assert len(signals) == 1 and signals[0][0] == Process.pid
    assert (out / "0-control" / "run.log").exists()
    assert not (out / "1-optimized").exists()
    assert not (out / "summary.json").exists()


def test_existing_output_is_never_reused(runner, args):
    argv, out = args
    argv.append("--run")
    out.mkdir()
    with pytest.raises(FileExistsError):
        runner.main()


def test_real_child_produces_checkpoint_and_measurement(runner, store_dir, tmp_path):
    """Exercise the actual child entry point on the small engine-generated fixture.

    This is a transport smoke, not a speed measurement or new research data.
    """
    train_v0.train(data=[str(store_dir)], out=tmp_path / "public", device="cpu",
                   epochs=1, seed=7, batch_size=64, n_boot=10, log=None,
                   cache_workers=1, encoder_version=train_cwv.DEFAULTS["encoder_version"],
                   **THIRDS)
    config = tmp_path / "recipe.json"
    config.write_text(json.dumps(dict(data=[str(store_dir)], device="cpu",
        epochs=1, limit_clusters=32, seed=7, batch_size=64, n_boot=10,
        hidden=32, cache_workers=1, eval_workers=1, bench_batch=32,
        cache_dir=str(tmp_path / "cache"), public_head=str(tmp_path / "public" / "best.pt"),
        **THIRDS)))
    out = tmp_path / "child"
    out.mkdir()
    runner.child(str(config), out)
    report = json.loads((out / "measurement.json").read_text())
    assert report["wall_seconds"] > 0
    assert report["cpu_seconds_including_reaped_children"] > 0
    assert report["parent_peak_rss_bytes"] > 0
    assert len(report["epoch_train_seconds"]) == 1
    assert set(report["checkpoints"]) == {"best.pt", "checkpoints/epoch-01.pt"}
    assert report["checkpoints"]["best.pt"] == runner.checkpoint_fingerprint(out / "train" / "best.pt")
