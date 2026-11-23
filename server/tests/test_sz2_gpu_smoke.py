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
    trainer = tmp_path / "trainer.py"
    trainer.write_text(
        "import os, pathlib, sys, time\n"
        "with pathlib.Path(sys.argv[1]).open('a') as f:\n"
        "    f.write(f'train {os.getpid()}\\n')\n"
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
    if action in ("restart", "stop"):
        with (d / "events").open("a") as f:
            f.write(action + "\\n")
        if action == "restart" or not (d / "failed_stop").exists():
            (d / "state").write_text("running" if action == "restart" else "not running")
    else:
        state = (d / "state").read_text() if (d / "state").exists() else "running"
        print(f"Daemon: {state}\\nTraffic: eligible")
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
w.SYSCTL = d / "sysctl"
w.LAUNCHCTL = d / "launchctl"
w.PS = d / "ps"
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
    ("failed_stop", "stop could not be verified", ["stop", "restart"]),
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
