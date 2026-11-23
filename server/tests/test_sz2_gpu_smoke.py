import hashlib
import json
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
        "sys.exit(13 if pathlib.Path(sys.argv[3]).exists() else 0)\n"
    )
    argv = [sys.executable, str(trainer), str(launch_log), str(tmp_path / "slow_trainer"),
            str(tmp_path / "failed_trainer")]
    (scripts / "sz2_joint_segment.py").write_text(
        "import sys\n"
        "assert sys.argv[1:3] == ['smoke', '--root']\n"
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
        if action == "restart" or not (d / "failed_stop").exists():
            (d / "state").write_text("running" if action == "restart" else "not running")
        if action == "restart" and (d / "config_drift_after_restart").exists():
            (d / "provider.toml").write_text("changed")
    else:
        state = (d / "state").read_text() if (d / "state").exists() else "running"
        if not restarted and "train " in events and (d / "early_provider_restart").exists():
            state = "running"
        print(f"Daemon: {state}\\nTraffic: eligible")
        if (d / "wrong_initial_mode").exists() or (restarted and (d / "wrong_restored_mode").exists()):
            print("Serving: Darkbloom network and local API")
        else:
            print("Serving: Darkbloom network only — this Mac has no local API")
        models = ["gemma-4-26b-qat-4bit", "gpt-oss-20b", "qwen3.5-35b-a3b",
                  "Qwen3.5-9B", "qwen3.6-35b-a3b-vl-mtp-mxfp8"]
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


def invoke(host):
    command, _, _ = host
    return subprocess.run(command, capture_output=True, text=True, timeout=10)


def events(log):
    return [event.split()[0] for event in log.read_text().splitlines()]


def test_restore_allows_slow_provider_restart(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(WORKER.parent))
    import sz2_gpu_smoke as worker

    started = False

    def provider(*args, timeout=5):
        nonlocal started
        if args == (worker.DARKBLOOM, "restart"):
            if timeout < 148:
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
    assert result.returncode == 1
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
    assert result.returncode == 1
    assert diagnostic in result.stderr
    assert events(log) == ["stop", "train", "restart"]
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
