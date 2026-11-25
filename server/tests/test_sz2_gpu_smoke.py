import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

WORKER = Path(__file__).resolve().parents[1] / "scripts/sz2_gpu_smoke.py"


@pytest.fixture
def host(tmp_path):
    scripts = tmp_path / "server/scripts"
    scripts.mkdir(parents=True)
    root = tmp_path / "reserved"
    root.mkdir()
    launch_log = tmp_path / "events"
    config = tmp_path / "provider.toml"
    config.write_text("fixture provider config\n")
    trainer = tmp_path / "trainer.py"
    trainer.write_text(
        "import os, pathlib, sys, time\n"
        "root = pathlib.Path(sys.argv[1]).parent\n"
        "with pathlib.Path(sys.argv[1]).open('a') as f:\n"
        "    f.write(f'train {os.getpid()}\\n')\n"
        "if (root / 'sample_footprint').exists():\n"
        "    for _ in range(500):\n"
        "        count = root / 'footprint_count'\n"
        "        if count.exists() and count.read_text() == '2': break\n"
        "        time.sleep(0.01)\n"
        "if pathlib.Path(sys.argv[2]).exists(): time.sleep(120)\n"
        "if (root / 'trainer_rc').exists():\n"
        "    assert os.environ['OMP_NUM_THREADS'] == ('16' if (root / 'phase').read_text() == 'small' else '4')\n"
        "    sys.exit(int((root / 'trainer_rc').read_text()))\n"
        "sys.exit(13 if pathlib.Path(sys.argv[3]).exists() else 0)\n"
    )
    argv = [sys.executable, str(trainer), str(launch_log), str(tmp_path / "slow_trainer"),
            str(tmp_path / "failed_trainer")]
    (scripts / "sz2_joint_segment.py").write_text(
        "import sys\n"
        "from pathlib import Path\n"
        f"d = Path({str(tmp_path)!r})\n"
        "phase = (d / 'phase').read_text() if (d / 'phase').exists() else 'smoke'\n"
        "assert sys.argv[1:3] == [phase, '--root']\n"
        "if (d / 'prepare_rc').exists(): sys.exit(int((d / 'prepare_rc').read_text()))\n"
        f"assert sys.argv[-1] == {str(root)!r}\n"
        f"print({json.dumps(argv)!r})\n"
    )
    fake = tmp_path / "fake"
    fake.write_text(f"#!{sys.executable}\n" + """
from pathlib import Path
import sys
d = Path(__file__).parent
name, *args = sys.argv
service = Path(name).name
if service == "darkbloom":
    action = args[0]
    log = d / "events"
    events = log.read_text() if log.exists() else ""
    restarted = "restart" in events
    if action in ("restart", "stop"):
        with (d / "events").open("a") as f:
            f.write(action + "\\n")
        if action == "stop":
            assert args == ["stop", "--timeout", "600"]
            drain = d / "drain"
            if drain.exists():
                mode = drain.read_text()
                if mode == "interrupt":
                    import os, signal
                    os.kill(os.getppid(), signal.SIGTERM)
                if mode != "once" or "stop" not in events:
                    count = 0 if mode == "zero" else 1
                    print(f"Error: Drain did not complete: {count} unfinished request(s), coordinator acknowledgement false.", file=sys.stderr)
                    raise SystemExit(13 if mode == "other" else 64)
        if action == "restart":
            assert args == ["restart", "--timeout", "600"]
            if (d / "still_draining").exists():
                raise SystemExit(64)
        if action == "restart" or not (d / "failed_stop").exists():
            (d / "state").write_text("running" if action == "restart" else "not running")
        drift = d / "config_drift_after_restart"
        if action == "restart" and drift.exists():
            (d / "provider.toml").write_bytes(drift.read_bytes() or b"changed")
    else:
        state = (d / "state").read_text() if (d / "state").exists() else "running"
        if not restarted and "train " in events and (d / "early_provider_restart").exists():
            state = "running"
        if restarted and (d / "still_draining").exists():
            print("Daemon: running")
            print("Traffic: draining")
            print("Model switch: draining; 1 unfinished request(s)")
            raise SystemExit(0)
        print(f"Daemon: {state}\\nTraffic: eligible")
        if (d / "wrong_initial_mode").exists() or (restarted and (d / "wrong_restored_mode").exists()):
            print("Serving: Darkbloom network and local API")
        else:
            print("Serving: Darkbloom network only — this Mac has no local API")
        models = ["gemma-4-26b-qat-4bit", "gpt-oss-20b", "qwen3.5-35b-a3b",
                  "Qwen3.5-9B", "qwen3.6-35b-a3b-vl-mtp-mxfp8"]
        if (d / "inkling_enabled").exists() and not (restarted and (d / "lost_inkling").exists()):
            models.append("thinkingmachines/Inkling-2-Mini")
        if (d / "wrong_initial_filter").exists() or (restarted and (d / "wrong_restored_filter").exists()):
            models[4] = models[3]
        print("Enabled model filter: " + ", ".join(models))
elif service == "launchctl":
    print("123 0 io.darkbloom.provider")
    log = d / "events"
    restarted = log.exists() and "restart" in log.read_text()
    missing = restarted and (d / "missing_after_restart").exists()
    if not missing:
        print("124 0 io.darkbloom.watchdog")
elif service == "sysctl":
    trained = (d / "events").exists() and "train " in (d / "events").read_text()
    if args[-1] == "vm.swapusage":
        if trained and (d / "unreadable_swap").exists():
            print("unavailable")
        else:
            print("used = 8G" if trained and (d / "excess_swap").exists() else "used = 0.0M")
    else:
        print(4 if trained and (d / "pressure").exists() else 1)
else:
    print("123")
""")
    footprint = tmp_path / "footprint"
    footprint.write_text(f"#!{sys.executable}\n" + """
from pathlib import Path
import sys
import time
d = Path(__file__).parent
assert sys.argv[1] == "-p"
pid = sys.argv[2]
if (d / "footprint_unavailable").exists():
    raise SystemExit(1)
if (d / "footprint_timeout").exists():
    time.sleep(5)
counter = d / "footprint_count"
n = int(counter.read_text()) if counter.exists() else 0
value = "65 GB" if (d / "footprint_high").exists() else ("1488 KB" if n == 0 else "32 MB")
print(f"python [{pid}]: 64-bit    Footprint: {value} (16384 bytes per page)")
counter.write_text(str(n + 1))
""")
    footprint.chmod(0o755)
    fake.chmod(0o755)
    for name in ("darkbloom", "launchctl", "sysctl", "ps"):
        (tmp_path / name).symlink_to(fake)
    bootstrap = f"""
from pathlib import Path
import sys
sys.path.insert(0, {str(WORKER.parent)!r})
import sz2_gpu_smoke as w
d = Path({str(tmp_path)!r})
w.SCRIPTS = d / "server/scripts"
w.DARKBLOOM = d / "darkbloom"
w.PAUSE = d / "keepalive.pause"
w.PROVIDER_CONFIG = d / "provider.toml"
w.PROVIDER_SHA256 = {hashlib.sha256(config.read_bytes()).hexdigest()!r}
w.INKLING_CONFIG_SHA256 = {hashlib.sha256(b"inkling fixture").hexdigest()!r}
w.SYSCTL = d / "sysctl"
w.LAUNCHCTL = d / "launchctl"
w.PS = d / "ps"
w.FOOTPRINT = d / "footprint"
w.FOOTPRINT_INTERVAL = 0.01
w.FOOTPRINT_TIMEOUT = 0.2
w.POLL_SECONDS = 0.05
w.RESTORE_SECONDS = 0.2
sys.exit(w.main())
"""
    return [sys.executable, "-B", "-c", bootstrap, str(root)], tmp_path, launch_log


def invoke(host, *extra):
    command, _, _ = host
    return subprocess.run([*command, *extra], capture_output=True, text=True, timeout=10)


def events(log):
    return [event.split()[0] for event in log.read_text().splitlines()]


def test_restore_allows_slow_provider_restart(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(WORKER.parent))
    import sz2_gpu_smoke as worker

    started = False

    def provider(*args, timeout=5):
        nonlocal started
        if args == (worker.DARKBLOOM, "restart", "--timeout", "600"):
            if timeout < 630:
                raise subprocess.TimeoutExpired(args, timeout)
            started = True
            return ""
        if args == (worker.DARKBLOOM, "status"):
            if not started:
                return "Daemon: not running"
            return (f"Daemon: running\nTraffic: eligible\nServing: {worker.SERVING_MODE}\n"
                    f"Enabled model filter: {', '.join(sorted(worker.MODEL_FILTER))}")
        assert args == (worker.LAUNCHCTL, "list")
        return "\n".join(worker.JOBS)

    monkeypatch.setattr(worker, "command", provider)
    monkeypatch.setattr(worker, "RESTORE_SECONDS", 0)
    config = tmp_path / "provider.toml"
    config.write_text("fixture provider config\n")
    monkeypatch.setattr(worker, "PROVIDER_CONFIG", config)
    monkeypatch.setattr(worker, "PROVIDER_SHA256", hashlib.sha256(config.read_bytes()).hexdigest())
    worker.restore_darkbloom()
    assert started


def test_smoke_runs_once_and_restores(host):
    _, tmp, log = host
    result = invoke(host)
    assert result.returncode == 0, result.stderr
    assert "rss_kib=" in result.stdout
    assert "Darkbloom running and eligible" in result.stdout
    assert events(log) == ["stop", "train", "restart"]
    assert not (tmp / "keepalive.pause").exists()
    result = invoke(host)
    assert result.returncode == 1
    assert "already exists" in result.stderr
    assert events(log) == ["stop", "train", "restart"]


@pytest.mark.parametrize(("fault", "diagnostic", "want"), [
    ("failed_stop", "Darkbloom is not confirmed stopped", ["stop", "restart"]),
    ("failed_trainer", "trainer exited 13", ["stop", "train", "restart"]),
    ("unreadable_swap", "unreadable swap", ["stop", "train", "restart"]),
    ("excess_swap", "memory guard exceeded", ["stop", "train", "restart"]),
    ("pressure", "memory guard exceeded", ["stop", "train", "restart"]),
])
def test_guard_or_failed_producer_restores(host, fault, diagnostic, want):
    _, tmp, log = host
    (tmp / fault).touch()
    if fault in ("unreadable_swap", "excess_swap", "pressure"):
        (tmp / "slow_trainer").touch()
    result = invoke(host)
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert diagnostic in result.stderr
    assert events(log) == want
    assert not (tmp / "keepalive.pause").exists()


def test_foreign_pause_is_preserved(host):
    _, tmp, log = host
    pause = tmp / "keepalive.pause"
    pause.write_text("foreign")
    result = invoke(host)
    assert result.returncode == 1
    assert pause.read_text() == "foreign"
    assert not log.exists()


def test_sigterm_stops_trainer_and_restores(host):
    command, tmp, log = host
    (tmp / "slow_trainer").touch()
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as worker:
        deadline = time.monotonic() + 5
        while not log.exists() or "train " not in log.read_text():
            assert worker.poll() is None and time.monotonic() < deadline
            time.sleep(0.02)
        worker.terminate()
        _, err = worker.communicate(timeout=10)
    assert worker.returncode == 1
    assert "SIGTERM" in err
    assert events(log) == ["stop", "train", "restart"]
    assert not (tmp / "keepalive.pause").exists()


def test_unverified_restore_fails_and_releases_owned_pause(host):
    _, tmp, log = host
    (tmp / "missing_after_restart").touch()
    result = invoke(host)
    assert result.returncode == 9
    assert "restoration could not be verified" in result.stderr
    assert events(log) == ["stop", "train", "restart"]
    assert not (tmp / "keepalive.pause").exists()


def test_valid_footprint_samples_log_mib_and_slope(host):
    _, tmp, log = host
    (tmp / "sample_footprint").touch()
    result = invoke(host)
    assert result.returncode == 0, result.stderr
    assert "footprint_mib=1.45312 footprint_slope_mib_per_min=-" in result.stdout
    assert "footprint_mib=32 footprint_slope_mib_per_min=" in result.stdout
    assert events(log) == ["stop", "train", "restart"]


@pytest.mark.parametrize(("fault", "diagnostic"), [
    ("footprint_high", "footprint exceeds 65536 MiB"),
    ("footprint_unavailable", "footprint unavailable for three consecutive samples"),
    ("footprint_timeout", "footprint unavailable for three consecutive samples"),
])
def test_bad_live_footprint_stops_trainer_and_restores(host, fault, diagnostic):
    _, tmp, log = host
    (tmp / "slow_trainer").touch()
    (tmp / fault).touch()
    result = invoke(host)
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert diagnostic in result.stderr
    if fault != "footprint_high":
        assert result.stdout.count("footprint_mib=NA") == 3
    assert events(log) == ["stop", "train", "restart"]
    assert not (tmp / "keepalive.pause").exists()


def test_short_trainer_can_exit_before_footprint_is_available(host):
    _, tmp, log = host
    (tmp / "footprint_unavailable").touch()
    result = invoke(host)
    assert result.returncode == 0, result.stderr
    assert events(log) == ["stop", "train", "restart"]


@pytest.mark.parametrize(("fault", "diagnostic"), [
    ("wrong_initial_mode", "serving mode differs"),
    ("wrong_initial_filter", "model filter differs"),
    ("provider.toml", "provider.toml SHA differs"),
])
def test_start_requires_reviewed_provider_identity(host, fault, diagnostic):
    _, tmp, log = host
    (tmp / fault).write_text("mismatch")
    result = invoke(host)
    assert result.returncode == 1
    assert diagnostic in result.stderr
    assert not log.exists()
    assert not (tmp / "keepalive.pause").exists()


@pytest.mark.parametrize(("fault", "diagnostic"), [
    ("wrong_restored_mode", "serving mode differs"),
    ("wrong_restored_filter", "model filter differs"),
    ("config_drift_after_restart", "provider.toml SHA differs"),
])
def test_restart_requires_reviewed_provider_identity(host, fault, diagnostic):
    _, tmp, log = host
    (tmp / fault).touch()
    result = invoke(host)
    assert result.returncode == 9
    assert diagnostic in result.stderr
    assert events(log) == ["stop", "train", "restart"]
    assert not (tmp / "keepalive.pause").exists()


@pytest.mark.parametrize("restore_drift", [False, True])
def test_full_segment_verifies_explicit_config_at_both_ends(host, restore_drift):
    _, tmp, log = host
    config = tmp / "provider.toml"
    if restore_drift:
        (tmp / "config_drift_after_restart").write_bytes(config.read_bytes())
    config.write_text("alternate reviewed provider config\n")
    digest = hashlib.sha256(config.read_bytes()).hexdigest()
    (tmp / "phase").write_text("medium-prefix")
    (tmp / "trainer_rc").write_text("7")

    result = invoke(host, "--phase", "medium-prefix", "--provider-sha256", digest)

    assert events(log) == ["stop", "train", "restart"]
    assert not (tmp / "keepalive.pause").exists()
    if restore_drift:
        assert result.returncode == 9, result.stderr
        assert "provider.toml SHA differs" in result.stderr
    else:
        assert result.returncode == 7, result.stderr
        assert f"provider_sha256={digest}" in result.stdout


@pytest.mark.parametrize(("digest", "diagnostic"), [
    ("0" * 64, "provider.toml SHA differs"),
    ("0" * 63, "requires 64 lowercase hexadecimal digits"),
    ("A" * 64, "requires 64 lowercase hexadecimal digits"),
])
def test_full_segment_refuses_wrong_or_malformed_explicit_config(host, digest, diagnostic):
    _, tmp, log = host
    (tmp / "phase").write_text("medium-prefix")
    (tmp / "trainer_rc").write_text("7")

    result = invoke(host, "--phase", "medium-prefix", "--provider-sha256", digest)

    assert result.returncode == 1
    assert diagnostic in result.stderr
    assert not log.exists()
    assert not (tmp / "keepalive.pause").exists()


def test_trainer_stops_if_provider_reappears_during_smoke(host):
    _, tmp, log = host
    (tmp / "slow_trainer").touch()
    (tmp / "early_provider_restart").touch()
    result = invoke(host)
    assert result.returncode == 1
    assert "Darkbloom is not confirmed stopped" in result.stderr
    assert events(log) == ["stop", "train", "restart"]
    assert not (tmp / "keepalive.pause").exists()

@pytest.mark.parametrize(("mode", "returncode", "want"), [
    ("once", 0, ["stop", "stop", "train", "restart"]),
    ("persistent", 1, ["stop", "stop", "restart"]),
    ("zero", 1, ["stop", "restart"]),
    ("other", 1, ["stop", "restart"]),
    ("interrupt", 1, ["stop", "restart"]),
])
def test_only_an_unfinished_drain_can_get_a_second_graceful_stop(host, mode, returncode, want):
    _, tmp, log = host
    (tmp / "drain").write_text(mode)
    result = invoke(host)
    assert result.returncode == returncode, result.stderr
    assert events(log) == want
    assert not (tmp / "keepalive.pause").exists()

def test_persistent_drain_reports_live_state_for_operator(host):
    _, tmp, log = host
    (tmp / "drain").write_text("persistent")
    (tmp / "still_draining").touch()
    result = invoke(host)
    assert result.returncode == 9
    for expected in ("Daemon: running", "Traffic: draining", "Model switch: draining", "operator action needed"):
        assert expected in result.stderr
    assert events(log) == ["stop", "stop", "restart"]
    assert not (tmp / "keepalive.pause").exists()

@pytest.mark.parametrize("phase,trainer_rc,prepare_rc,expected,actions", [
    ("small", 0, 0, 0, ["train"]),
    ("medium-prefix", 7, 0, 7, ["stop", "train", "restart"]),
    ("medium-prefix", 0, 0, 1, ["stop", "train", "restart"]),
    ("medium-finish", 3, 0, 3, ["stop", "train", "restart"]),
    ("medium-finish", 0, 8, 8, []),
])
def test_full_segment_protocol(host, phase, trainer_rc, prepare_rc, expected, actions):
    command, directory, log = host
    (directory / "phase").write_text(phase)
    (directory / "trainer_rc").write_text(str(trainer_rc))
    if prepare_rc:
        (directory / "prepare_rc").write_text(str(prepare_rc))
    result = subprocess.run([*command, "--phase", phase], capture_output=True, text=True, timeout=10)
    assert result.returncode == expected, result.stderr
    assert (events(log) if log.exists() else []) == actions


def test_large_smoke_uses_scratch_emitter_and_preserves_partial_output(host):
    command, directory, log = host
    scripts = directory / "server/scripts"
    (scripts / "sz2_joint_segment.py").rename(scripts / "sz3_joint_recipe.py")
    (directory / "phase").write_text("L-smoke")
    (directory / "trainer_rc").write_text("3")
    refused = invoke(host, "--phase", "L-smoke")
    assert refused.returncode == 1 and "positive --min-free-gib" in refused.stderr
    refused = invoke(host, "--phase", "L-smoke", "--min-free-gib", "999999999")
    assert refused.returncode == 1 and "disk guard:" in refused.stderr
    assert not log.exists() and not (directory / "reserved/L-smoke").exists()
    args = [*command, "--phase", "L-smoke", "--min-free-gib", "1"]
    stopped = subprocess.run(args, capture_output=True, text=True, timeout=10)
    assert stopped.returncode == 1 and "L-smoke trainer exited 3" in stopped.stderr
    assert events(log) == ["stop", "train", "restart"]
    partial = directory / "reserved/L-smoke"
    assert partial.is_dir()
    (partial / "progress").write_text("partial")
    refused = subprocess.run(args, capture_output=True, text=True, timeout=10)
    assert refused.returncode == 1 and "already exists" in refused.stderr
    assert (partial / "progress").read_text() == "partial"
    assert events(log) == ["stop", "train", "restart"]


def test_large_smoke_losing_disk_headroom_restores_provider(host):
    supervisor, directory, log = host
    scripts = directory / "server/scripts"
    (scripts / "sz2_joint_segment.py").rename(scripts / "sz3_joint_recipe.py")
    (directory / "phase").write_text("L-smoke")
    (directory / "slow_trainer").touch()
    bootstrap = supervisor.index("-c") + 1
    supervisor[bootstrap] = supervisor[bootstrap].replace("sys.exit(w.main())", """
from types import SimpleNamespace
w.shutil.disk_usage = lambda path: SimpleNamespace(
    free=0 if (d / "events").exists() and "train " in (d / "events").read_text() else 2**32)
sys.exit(w.main())
""")
    cp = invoke(host, "--phase", "L-smoke", "--min-free-gib", "1")
    assert cp.returncode == 1 and "disk guard: 0 bytes" in cp.stderr
    assert events(log) == ["stop", "train", "restart"]
    assert (directory / "reserved/L-smoke").is_dir()


@pytest.fixture
def mps_worker_recipe(host):
    torch = pytest.importorskip("torch")
    if not torch.backends.mps.is_available():
        pytest.skip("the worker runs the trainer on MPS")
    from test_unified_readout_device import SCRATCH, make_data

    supervisor, directory, log = host
    data = make_data(directory / "data")
    recipe = directory / "recipe.json"
    recipe.write_text(json.dumps(dict(
        init=None, init_ckpt=None, init_sha256=None, init_readout_ckpt="previous.pt", scratch_arch=None,
        max_train_rows=None, data=[str(data)], calib_data=[str(data)], epochs=1, lr=3e-5, head_lr=9e-5,
        readout_lr=1.5e-4, head_warmup_buffers=0, weight_decay=0.01, belief_weight=1,
        q_weight=1, policy_weight=1, value_weight=1, reply_weight=1, seed=1,
        buffer_chunks=1, rounds_per_batch=1, calib_rows=10000, store_map=[],
        corpus_weight=[f"{data}=policy:2,reply:2"], exclude_seed_window=[],
    )))
    return supervisor, directory, log, recipe, SCRATCH


@pytest.mark.parametrize("interrupt", [False, True], ids=["clean-stop", "trainer-abort"])
def test_full_mix_scratch_worker_resumes_and_feeds_the_polish_cache(mps_worker_recipe, monkeypatch, interrupt, capsys):
    supervisor, directory, log, recipe, scratch = mps_worker_recipe
    settings = json.loads(recipe.read_bytes())
    settings["rounds_per_batch"] = 16
    recipe.write_text(json.dumps(settings))
    fault_script = directory / "fail_training.py"
    fault_script.write_text(
        "from shengji.train import unified_readout as trainer\n"
        "def fail_objective(*args):\n"
        "    raise RuntimeError('fixture fault')\n"
        "trainer.objective = fail_objective\n"
        "raise SystemExit(trainer.main())\n"
    )
    emitter = directory / "server/scripts/rt4m_joint.py"
    emitter.write_text(
        "import json, sys\nfrom pathlib import Path\n"
        f"sys.path.insert(0, {str(WORKER.parent)!r})\n"
        "import rt4m_joint as arm\n"
        f"arm.RECIPE_SHA256 = {hashlib.sha256(recipe.read_bytes()).hexdigest()!r}\n"
        f"arm.ARCHITECTURE[6] = {scratch!r}\n"
        "root = Path(sys.argv[sys.argv.index('--root') + 1])\n"
        "digest = sys.argv[-1] if '--recover-checkpoint-sha256' in sys.argv else None\n"
        f"argv = arm.command(root, Path({str(recipe)!r}), recover_checkpoint_sha256=digest)\n"
        "if '--expect-resume-buffer' not in argv and digest is None: argv.extend(['--max-seconds','0.0001'])\n"
        "if (root / 'inject-fault').exists():\n"
        f"    argv[2:4] = [{str(fault_script)!r}]\n"
        "print(json.dumps(argv))\n"
    )
    worker = [*supervisor, "--phase", "RT4-M-A", "--min-free-gib", "1"]
    env = {**os.environ, "PYTHONPATH": str(WORKER.parents[1])}

    def run(*extra):
        return subprocess.run([*worker, *extra], env=env, capture_output=True, text=True, timeout=60)

    first = run()
    assert first.returncode == 3, (first.stdout, first.stderr)
    out = directory / "reserved/A/train"
    assert "STOPPED at epoch 1 buffer 1/" in (out / "status.log").read_text()
    actual = json.loads((out / "run.json").read_bytes())
    assert (actual["lr"], actual["head_lr"], actual["readout_lr"]) == (3e-4, 1e-3, 1e-3)
    assert actual["microbatch_rounds"] == 4 and actual["rounds_per_batch"] == 16
    recovery = []
    if interrupt:
        root = directory / "reserved"
        fault = root / "inject-fault"
        fault.touch()
        assert run().returncode != 0
        assert " UTR ABORT RuntimeError: fixture fault" in (out / "status.log").read_text().splitlines()[-1]
        fault.unlink()
        assert run().returncode != 0
        assert run("--recover-checkpoint-sha256", "0" * 64).returncode != 0
        digest = hashlib.sha256((out / "checkpoint.pt").read_bytes()).hexdigest()
        recovery = ["--recover-checkpoint-sha256", digest]
        (out / "STOP").touch()
        assert run(*recovery).returncode != 0
        (out / "STOP").unlink()
        assert events(log) == ["stop", "restart"] * 2
    second = run(*recovery)
    assert second.returncode == 0, (second.stdout, second.stderr)
    status = (out / "status.log").read_text()
    assert " RESUME epoch 0 buffer 1 device=mps" in status and " UTR DONE " in status.splitlines()[-1]
    assert (out / "best.pt").is_file()
    assert run().returncode != 0
    if interrupt:
        assert run(*recovery).returncode != 0
    assert events(log) == ["stop", "restart"] * (3 if interrupt else 2)

    monkeypatch.syspath_prepend(str(WORKER.parent))
    import rt4m_cache
    import rt4m_joint

    monkeypatch.setattr(rt4m_joint, "RECIPE_SHA256", hashlib.sha256(recipe.read_bytes()).hexdigest())
    monkeypatch.setitem(rt4m_joint.ARCHITECTURE, 6, scratch)
    run_path = out / "run.json"
    old_identity = dict(actual)
    del old_identity["microbatch_rounds"]
    run_path.write_text(json.dumps(old_identity))
    with pytest.raises(ValueError, match="different trainer settings"):
        rt4m_joint.completed_inputs(directory / "reserved", recipe)
    run_path.write_text(json.dumps(actual))
    cache_root = directory / "cache"
    cache_options = {"encode_rounds": 4} if interrupt else {}
    for worker_id in range(rt4m_cache.WORKERS):
        assert rt4m_cache.partition(directory / "reserved", cache_root, worker_id, recipe, **cache_options) == 0
    cache, = (cache_root / "A").iterdir()
    assert cache.name.endswith("-encode4") == interrupt
    marker = cache / "cache_encode.json"
    binding = json.loads(marker.read_text())
    assert binding["rounds_per_batch"] == (4 if interrupt else 32)
    marker.write_text(json.dumps(dict(binding, rounds_per_batch=32 if interrupt else 4)))
    with pytest.raises(ValueError, match="encoder batch size"):
        rt4m_cache.polish(directory / "reserved", cache_root, recipe, **cache_options)
    marker.write_text(json.dumps(binding))
    assert (cache / "train-0000.npz").is_file()
    with pytest.raises(ValueError, match="expected sampled training set"):
        rt4m_cache.polish(directory / "reserved", cache_root, recipe, **cache_options)
    sample = json.loads((cache / "DONE.0").read_text())["sample"]
    assert sample["rows"] == 344 and sample["chunks"] == 2
    monkeypatch.setattr(rt4m_cache, "RT4_SAMPLE", sample)
    if interrupt:
        import sz2_polish_arm
        original_link = sz2_polish_arm.os.link

        def interrupt_selection(source, target):
            if Path(target).name == "selected.pt":
                raise InterruptedError("interrupted winner publication")
            return original_link(source, target)

        with monkeypatch.context() as fault:
            fault.setattr(sz2_polish_arm.os, "link", interrupt_selection)
            with pytest.raises(InterruptedError, match="winner publication"):
                rt4m_cache.polish(directory / "reserved", cache_root, recipe, **cache_options)
        out_dir = directory / "reserved/A/polish"
        log_path = out_dir / "status.log"
        saved_log = log_path.read_bytes()
        assert b" POLISH DONE " in saved_log and not (out_dir / "selected.pt").exists()
        log_path.write_bytes(saved_log + b"stopped\n")
        with pytest.raises(ValueError, match="completed polish"):
            rt4m_cache.polish(directory / "reserved", cache_root, recipe, finish_selection=True, **cache_options)
        log_path.write_bytes(saved_log[:saved_log.rfind(b"sha256=")] + b"sha256=" + b"0" * 64 + b"\n")
        with pytest.raises(ValueError, match="differs from the polish terminal"):
            rt4m_cache.polish(directory / "reserved", cache_root, recipe, finish_selection=True, **cache_options)
        assert not (out_dir / "selected.pt").exists()
        log_path.write_bytes(saved_log)
        monkeypatch.setattr(rt4m_joint, "RECIPE", recipe)
        monkeypatch.setattr(sys, "argv", ["rt4m_cache.py", "--root", str(directory / "reserved"),
                                          "--cache-root", str(cache_root), "--encode-rounds-per-batch", "4",
                                          "--finish-selection"])
        assert rt4m_cache.main() == 0
        assert log_path.read_bytes() == saved_log
    else:
        assert rt4m_cache.polish(directory / "reserved", cache_root, recipe, **cache_options) == 0
    assert (directory / "reserved/A/polish/selected.pt").is_file()
    import rt4m_export

    root = directory / "reserved"
    assert rt4m_export.export(root, recipe, directory / "data/x", 132) == 0
    exported = root / "A/export"
    parity = json.loads((exported / "parity.json").read_text())
    assert set(parity["max_abs_diff"]) == {"belief", "outcome", "policy", "value", "reply"}
    monkeypatch.setattr(rt4m_joint, "RECIPE", recipe)
    monkeypatch.setattr(rt4m_export, "PARITY_ROWS", 132)
    monkeypatch.setattr(sys, "argv", ["rt4m_export.py", "--root", str(root), "--duel-words"])
    capsys.readouterr()
    assert rt4m_export.main() == 0
    assert json.loads(capsys.readouterr().out) == [
        f"SHENGJI_PV_BELIEF_CKPT={exported / 'cand-belief.npz'}",
        f"SHENGJI_PV_BELIEF_SHA256={parity['belief_sha256']}",
        f"SHENGJI_PV_UNIFIED_CKPT={exported / 'cand.npz'}",
        f"SHENGJI_PV_UNIFIED_SHA256={parity['package']}",
    ]
    for altered, error in [
            (dict(parity, selected_checkpoint_sha256="0" * 64), "selected checkpoint"),
            (dict(parity, max_abs_diff={"belief": 0, "value": 0, "reply": 0}), "parity errors")]:
        (exported / "parity.json").write_text(json.dumps(altered))
        with pytest.raises(ValueError, match=error):
            rt4m_export.duel_words(root, recipe, 132)
    (exported / "parity.json").write_text(json.dumps(parity))
    bad_cache = directory / "unreserved"
    status_path = out / "status.log"
    status_path.write_text(status[:status.rfind("sha256=")] + "sha256=" + "0" * 64 + "\n")
    with pytest.raises(ValueError, match="checkpoint differs"):
        rt4m_cache.partition(directory / "reserved", bad_cache, 0, recipe)
    assert not bad_cache.exists()



@pytest.mark.parametrize(("phase", "module", "pin", "depth"), [
    ("L-smoke", "sz3_joint_recipe", "RECIPE_SHA", 8),
    ("RT4-M-A-smoke", "rt4m_joint", "RECIPE_SHA256", 6),
    ("RT4-M-A-micro4-smoke", "rt4m_joint", "RECIPE_SHA256", 6),
])
def test_split_smoke_resumes_the_real_trainer_and_consumes_its_capacity(
        mps_worker_recipe, phase, module, pin, depth):
    supervisor, directory, log, recipe, scratch = mps_worker_recipe
    if module == "rt4m_joint":
        from test_belief_labels import synthetic_cluster
        from test_unified_seq import extract_dir, write_store

        store = write_store(directory / "batch-store", [synthetic_cluster(s) for s in range(2000, 2009)], seed0=2000)
        data = extract_dir(store, directory / "batch-data", task_clusters=1)
        settings = json.loads(recipe.read_bytes())
        settings.update(data=[str(data)], buffer_chunks=8, rounds_per_batch=16,
                        corpus_weight=[f"{data}=policy:2,reply:2"])
        recipe.write_text(json.dumps(settings))
    emitter = directory / f"server/scripts/{module}.py"
    emitter.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(WORKER.parent)!r})\n"
        f"import {module} as arm\n"
        f"arm.{pin} = {hashlib.sha256(recipe.read_bytes()).hexdigest()!r}\n"
        f"arm.ARCHITECTURE[{depth}] = {scratch!r}\n"
        f"arm.main([*sys.argv[1:], '--recipe', {str(recipe)!r}])\n"
    )
    cp = subprocess.run([*supervisor, "--phase", phase, "--min-free-gib", "1"],
                        env={**os.environ, "PYTHONPATH": str(WORKER.parents[1])},
                        capture_output=True, text=True, timeout=60)
    assert cp.returncode == 0, (cp.stdout, cp.stderr)
    result = json.loads(cp.stdout.splitlines()[-1])
    assert result["capacity"]["post_step_max_driver_bytes"] > 0
    if module == "rt4m_joint":
        assert result["capacity"]["max_batch_rounds"] == 16
        assert result["capacity"]["steps"] == 2
        assert not (directory / "reserved/A").exists()
    else:
        assert result["capacity"]["rows"] == 344 and result["capacity"]["steps"] == 4
    training = directory / "reserved" / phase / "train"
    if module == "rt4m_joint":
        actual = json.loads((training / "run.json").read_bytes())
        assert (actual["lr"], actual["head_lr"], actual["readout_lr"]) == (3e-4, 1e-3, 1e-3)
        assert actual.get("microbatch_rounds") == (4 if phase == "RT4-M-A-micro4-smoke" else None)
    status = (training / "status.log").read_text()
    assert " UTR PAUSED at epoch 1 buffer 1/" in status
    assert " RESUME epoch 0 buffer 1 device=mps" in status
    assert " UTR DONE " in status.splitlines()[-1]
    assert events(log) == ["stop", "restart"]


def test_full_sz3_worker_consumes_the_real_trainer(mps_worker_recipe):
    supervisor, directory, log, recipe, scratch = mps_worker_recipe
    emitter = directory / "server/scripts/sz3_joint_recipe.py"
    emitter.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(WORKER.parent)!r})\n"
        "import sz3_joint_recipe as sz3\n"
        f"sz3.RECIPE_SHA = {hashlib.sha256(recipe.read_bytes()).hexdigest()!r}\n"
        f"sz3.ARCHITECTURE = {{6: {scratch!r}, 8: {scratch!r}}}\n"
        "sz3.BOUNDARY = 1\n"
        f"sz3.main([*sys.argv[1:], '--recipe', {str(recipe)!r}])\n"
    )
    def run(phase):
        return subprocess.run([*supervisor, "--phase", phase, "--min-free-gib", "1"],
                              env={**os.environ, "PYTHONPATH": str(WORKER.parents[1])},
                              capture_output=True, text=True, timeout=60)

    assert run("M").returncode == 0
    assert run("L-prefix").returncode == 7
    result = run("L-finish")
    assert result.returncode == 8, (result.stdout, result.stderr)
    assert events(log) == ["stop", "restart"] * 2
    root = directory / "reserved"
    report = root / "M/train/epoch-1-buffer-1.json"
    prefix = json.loads(report.read_bytes())
    prefix["train"]["leaf_value"] += 0.01
    report.write_text(json.dumps(prefix))
    assert run("L-finish").returncode == 0
    status = (root / "L/train/status.log").read_text()
    assert " RESUME epoch 0 buffer 1 device=mps" in status and " UTR DONE " in status.splitlines()[-1]
    assert run("M").returncode != 0
    assert events(log) == ["stop", "restart"] * 3


@pytest.mark.parametrize("failed", [None, "M 0", "M 1", "M 2", "polish", "export", "disk"])
def test_serial_post_training_stops_on_first_incomplete_stage(tmp_path, monkeypatch, failed):
    import types

    monkeypatch.syspath_prepend(str(WORKER.parent))
    import sz2_post_arm as post

    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for stage in ("cache", "polish", "export"):
        (scripts / f"sz2_{stage}_arm.py").write_text(
            "import os, sys\nfrom pathlib import Path\n"
            f"step = ' '.join(sys.argv[1:]) if '{stage}' == 'cache' else '{stage}'\n"
            "with Path('calls').open('a') as stream:\n"
            "    print(step, os.environ['OMP_NUM_THREADS'], file=stream)\n"
            f"sys.exit(17 if step == {failed!r} else 0)\n"
        )
    monkeypatch.setattr(post.host, "SCRIPTS", scripts)
    monkeypatch.setattr(post, "FLEET", tmp_path)
    monkeypatch.setattr(post.host, "command", lambda *args: "")
    digests = []

    def ready(status, expected_sha=None):
        digests.append(expected_sha)
        return True

    monkeypatch.setattr(post.host, "darkbloom_ready", ready)
    monkeypatch.setattr(post.host, "memory_sample", lambda: (0, 1))
    monkeypatch.setitem(sys.modules, "small_capacity", types.SimpleNamespace(provider_sample=lambda pid=42: 42))

    def monitor(child, baseline, check, verify, **limits):
        verify()
        assert limits == dict(pressure_limit=2, swap_limit=1024, footprint_limit=24576)
        return child.wait(timeout=10)

    monkeypatch.setattr(post.host, "monitor", monitor)
    if failed == "disk":
        small = tmp_path / "codex-sz2-cache-v1/S/identity"
        small.mkdir(parents=True)
        (small / "train-0000.npz").touch()
        with pytest.raises(ValueError, match="offloaded"):
            post.run("M", expected_sha="a" * 64)
        assert not (tmp_path / "calls").exists()
        assert not digests
        return
    calls = ["M 0 8", "M 1 8", "M 2 8", "polish 16", "export 2"]
    if failed:
        with pytest.raises(RuntimeError, match="rc=17"):
            post.run("M", expected_sha="a" * 64)
        calls = calls[:next(i for i, line in enumerate(calls) if line.startswith(failed)) + 1]
    else:
        post.run("M", expected_sha="a" * 64)
    assert (tmp_path / "calls").read_text().splitlines() == calls
    assert digests == ["a" * 64] * (1 if failed else 2)

@pytest.mark.parametrize("lose_filter", [False, True])
def test_inkling_config_binds_the_same_filter_at_preflight_and_restore(host, lose_filter):
    _, tmp, log = host
    config = tmp / "provider.toml"
    old_sha = hashlib.sha256(config.read_bytes()).hexdigest()
    config.write_bytes(b"inkling fixture")
    sha = hashlib.sha256(config.read_bytes()).hexdigest()
    args = ["--provider-sha256", sha]
    assert invoke(host, *args, "--check-provider").returncode == 1
    (tmp / "inkling_enabled").touch()
    assert invoke(host, "--provider-sha256", old_sha, "--check-provider").returncode == 1
    assert invoke(host, *args, "--check-provider").returncode == 0
    assert not log.exists() and not (tmp / "keepalive.pause").exists()
    if lose_filter:
        (tmp / "lost_inkling").touch()
    result = invoke(host, *args)
    assert result.returncode == (9 if lose_filter else 0), result.stderr
    assert events(log) == ["stop", "train", "restart"]
