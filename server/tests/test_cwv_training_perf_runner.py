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


@pytest.mark.parametrize("warmup", [False, True])
def test_dry_run_never_launches_or_creates_output(runner, args, monkeypatch, warmup):
    argv, out = args
    if warmup:
        argv.append("--warmup")
    def forbidden(*a, **kw):
        raise AssertionError("dry-run launched a child")
    monkeypatch.setattr(runner.subprocess, "Popen", forbidden)
    runner.main()
    assert not out.exists()


@pytest.mark.parametrize("mismatch", [False, True])
@pytest.mark.parametrize("comparison", ["batching-sync", "validation-packing"])
def test_abba_env_same_recipe_and_parity_refusal(runner, args, monkeypatch, mismatch, comparison):
    argv, out = args
    argv.append("--run")
    argv.extend(["--comparison", comparison])
    seen = []
    class Process:
        def __init__(self, cmd, **kw):
            self.args = cmd
            assert kw["start_new_session"] is True
            seen.append((kw["env"]["SHENGJI_CWV_LOSS_SYNC_EVERY"],
                         kw["env"]["SHENGJI_CWV_BATCHED_CANDIDATES"]))
            assert Path(cmd[cmd.index("--config") + 1]) == out / "recipe.json"
            dest = Path(cmd[cmd.index("--out") + 1])
            assert cmd[cmd.index("--comparison") + 1] == comparison
            assert cmd[cmd.index("--arm") + 1] == ("control" if len(seen) in (1, 4) else "optimized")
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
    assert seen == ([("1", "0"), ("32", "1"), ("32", "1"), ("1", "0")]
                    if comparison == "batching-sync" else [("32", "1")] * 4)
    summary = json.loads((out / "summary.json").read_text())
    assert summary["exact_checkpoint_and_cpu_rng_parity"] is (not mismatch)
    assert summary["control_repeatable"] is True
    assert summary["optimized_repeatable"] is (not mismatch)
    assert summary["control_mean_wall"] == 2
    assert summary["optimized_mean_wall"] == 1


@pytest.mark.parametrize("warmup", [False, True])
def test_timeout_stops_only_private_group_and_does_not_advance(runner, args, monkeypatch, warmup):
    argv, out = args
    argv.append("--run")
    if warmup:
        argv.append("--warmup")
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
    assert (out / ("warmup" if warmup else "0-control") / "run.log").exists()
    if warmup:
        assert not (out / "0-control").exists()
    assert not (out / "1-optimized").exists()
    assert not (out / "summary.json").exists()


def test_existing_output_is_never_reused(runner, args):
    argv, out = args
    argv.append("--run")
    out.mkdir()
    with pytest.raises(FileExistsError):
        runner.main()


@pytest.mark.parametrize("late_change", [False, True])
def test_full_warmup_prepares_candidate_cache_but_timed_changes_refuse(runner, args, monkeypatch, late_change):
    argv, out = args
    argv.extend(["--run", "--warmup"])
    launches = []
    cache = out.parent / "cache"
    class Process:
        def __init__(self, cmd, **kw):
            self.args = cmd
            dest = Path(cmd[cmd.index("--out") + 1])
            launches.append(dest.name)
            if dest.name == "warmup":
                assert kw["env"]["SHENGJI_CWV_BATCHED_CANDIDATES"] == "0"
                (cache / "candidates.npz").write_bytes(b"prepared")
            elif late_change and dest.name == "0-control":
                (cache / "unexpected.npz").write_bytes(b"late")
            (dest / "measurement.json").write_text(json.dumps(dict(
                wall_seconds=999 if dest.name == "warmup" else 2,
                checkpoints={"best.pt": "same"}, torch_cpu_rng_sha256="same")))
        def wait(self, timeout):
            assert timeout == 900
            return 0
    monkeypatch.setattr(runner.subprocess, "Popen", Process)
    if late_change:
        with pytest.raises(RuntimeError, match="cache changed during benchmark"):
            runner.main()
        assert launches == ["warmup", "0-control"]
        assert not (out / "summary.json").exists()
    else:
        runner.main()
        assert launches == ["warmup", "0-control", "1-optimized", "2-optimized", "3-control"]
        summary = json.loads((out / "summary.json").read_text())
        assert summary["warmup"]["wall_seconds"] == 999
        assert summary["control_mean_wall"] == summary["optimized_mean_wall"] == 2
        assert len(summary["arms"]) == 4


@pytest.mark.parametrize("comparison,arm", [("batching-sync", "optimized"),
                                           ("validation-packing", "control"),
                                           ("validation-packing", "optimized")])
def test_real_child_produces_checkpoint_and_measurement(runner, store_dir, tmp_path, comparison, arm):
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
    runner.child(str(config), out, comparison=comparison, arm=arm)
    report = json.loads((out / "measurement.json").read_text())
    assert report["wall_seconds"] > 0
    assert report["cpu_seconds_including_reaped_children"] > 0
    assert report["parent_peak_rss_bytes"] > 0
    assert len(report["epoch_train_seconds"]) == 1
    assert len(report["epoch_loop_seconds"]) == 1
    assert report["epoch_validation_stages"][0]["outcome_eval"] > 0
    assert report["comparison"] == comparison
    assert report["arm"] == arm
    assert report["candidate_report_seconds"] > 0
    assert set(report["checkpoints"]) == {"best.pt", "checkpoints/epoch-01.pt"}
    assert report["checkpoints"]["best.pt"] == runner.checkpoint_fingerprint(out / "train" / "best.pt")


def test_packing_recipe_changes_only_treatment_flag(runner, args):
    argv, _ = args
    config = argv[argv.index("--config") + 1]
    original = runner.recipe(config)
    for arm in ("control", "optimized"):
        kw = runner.arm_recipe(config, "validation-packing", arm)
        assert kw.pop("pack_validation_shards") is (arm == "optimized")
        assert kw == original
    assert runner.recipe(config) == original


@pytest.mark.parametrize("extra", [{"arch": "history"}, {"pack_validation_shards": True}])
def test_packing_invalid_recipe_refused_in_dry_run(runner, args, extra):
    argv, out = args
    config = Path(argv[argv.index("--config") + 1])
    config.write_text(json.dumps(dict(runner.recipe(config), **extra)))
    argv.extend(["--comparison", "validation-packing"])
    with pytest.raises(ValueError):
        runner.main()
    assert not out.exists()


def test_policy_budget_counts_decompressed_arrays_even_with_row_limit(runner, tmp_path, monkeypatch):
    import zipfile
    prefix = tmp_path/'rows'
    Path(str(prefix)+'.meta.jsonl').write_text('{}\n')
    with zipfile.ZipFile(str(prefix)+'.npz', 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('X.npy', b'0'*10000)
    assert Path(str(prefix)+'.npz').stat().st_size < 1000
    monkeypatch.setattr(runner, 'POLICY_INPUT_BYTES', 1000)
    with pytest.raises(ValueError, match='byte budget'):
        runner.check_policy_input_budget(dict(policy_rows=str(prefix), policy_rows_limit=1))


def test_policy_budget_refuses_full_manifest_without_opening_chunks(runner, tmp_path):
    (tmp_path/'manifest.json').write_text(json.dumps({'chunks': [{'file': 'absent.npz'}]*17}))
    with pytest.raises(ValueError, match='1..16'):
        runner.check_policy_input_budget(dict(policy_rows=str(tmp_path)))


def test_policy_budget_small_chunked_and_eval_inputs(runner, tmp_path):
    import zipfile
    rows = tmp_path/'chunks'
    rows.mkdir()
    with zipfile.ZipFile(rows/'one.npz', 'w') as archive:
        archive.writestr('X.npy', b'fixture')
    (rows/'manifest.json').write_text(json.dumps({'chunks': [{'file': 'one.npz'}]}))
    evaluation = tmp_path/'eval'
    with zipfile.ZipFile(str(evaluation)+'.npz', 'w') as archive:
        archive.writestr('X.npy', b'fixture')
    Path(str(evaluation)+'.meta.jsonl').write_text('{}\n')
    runner.check_policy_input_budget(dict(policy_rows=str(rows), policy_eval=str(evaluation)))
    (rows/'manifest.json').write_text(json.dumps({'chunks': [{'file': '../eval.npz'}]}))
    with pytest.raises(ValueError, match='directly inside'):
        runner.check_policy_input_budget(dict(policy_rows=str(rows)))
