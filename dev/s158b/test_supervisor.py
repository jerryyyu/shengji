import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

import supervisor
from seed_worker import _publish


def _fixture_seed(seed, slots, env):
    assert os.environ["OMP_NUM_THREADS"] == "1"
    directory = slots / str(seed)
    directory.mkdir()
    if seed == 101 and env.get("CRASH"):
        os._exit(33)
    if seed == 101 and env.get("FAULT"):
        raise RuntimeError("worker failed")
    digest = _publish(directory, json.dumps({"seed": seed, "status": "complete"}))
    return (seed + 1 if env.get("BAD_SEAL") else seed), digest


@pytest.fixture
def fixture_worker(monkeypatch):
    env = {"SHENGJI_BOT": "fixture", "OMP_NUM_THREADS": "1"}
    monkeypatch.setattr(supervisor, "arm_environment", lambda _: env)
    monkeypatch.setattr(supervisor, "write_seed", _fixture_seed)
    monkeypatch.setattr(supervisor, "FIRST_SEED", 100)
    monkeypatch.setattr(supervisor, "DEALS", 4)
    return env


def test_parallel_completion_binds_every_published_byte(tmp_path, fixture_worker):
    root = tmp_path / "run"
    terminal = supervisor.run_reserved(root, [], "a" * 64, workers=2)
    assert terminal == json.loads((root / "terminal.json").read_text())
    assert terminal["status"] == "LANE DONE" and terminal["dispatch_sha256"] == "a" * 64
    manifest = (root / "slot-seals.json").read_bytes()
    assert terminal["manifest_sha256"] == hashlib.sha256(manifest).hexdigest()
    seals = json.loads(manifest)
    for seed in range(100, 104):
        result = (root / "slots" / str(seed) / "result.json").read_bytes()
        assert seals[str(seed)] == hashlib.sha256(result).hexdigest()
    assert dict(line.split() for line in (root / "progress").read_text().splitlines()) == seals
    with pytest.raises(FileExistsError):
        supervisor.run_reserved(root, [], "a" * 64, workers=2)


@pytest.mark.parametrize("mode", ["FAULT", "BAD_SEAL", "CRASH"])
def test_worker_failure_never_seals_or_retries(tmp_path, fixture_worker, mode):
    fixture_worker[mode] = "1"
    root = tmp_path / "run"
    with pytest.raises((RuntimeError, ValueError)):
        supervisor.run_reserved(root, [], "a" * 64, workers=1)
    assert json.loads((root / "terminal.json").read_text())["status"] == "FAULT"
    assert not (root / "slot-seals.json").exists()
    assert not (root / "slots/102").exists()
    assert (root / "slots/100/result.json").is_file()


def test_setup_fault_without_seed_is_terminal(tmp_path, monkeypatch):
    def refuse(_):
        raise ValueError("missing package")
    monkeypatch.setattr(supervisor, "arm_environment", refuse)
    root = tmp_path / "run"
    with pytest.raises(ValueError, match="missing package"):
        supervisor.run_reserved(root, [], "a" * 64, workers=1)
    assert json.loads((root / "terminal.json").read_text())["status"] == "FAULT"
    assert not list((root / "slots").iterdir())

def _slow_seed(seed, slots, env):
    directory = slots / str(seed)
    directory.mkdir()
    (directory / str(os.getpid())).touch()
    time.sleep(30)
    return seed, _publish(directory, "{}")


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def test_workers_exit_when_only_the_supervisor_is_killed(tmp_path):
    root = tmp_path / "slow"
    parent = subprocess.Popen([sys.executable, __file__, str(root)], start_new_session=True)
    try:
        deadline = time.monotonic() + 15
        while True:
            pids = [int(p.name) for p in (root / "slots").glob("*/*") if p.name.isdigit()]
            if len(set(pids)) == 2:
                break
            assert parent.poll() is None and time.monotonic() < deadline
            time.sleep(.05)
        parent.kill()
        parent.wait(timeout=5)
        deadline = time.monotonic() + 5
        while any(_alive(pid) for pid in pids) and time.monotonic() < deadline:
            time.sleep(.05)
        assert not any(_alive(pid) for pid in pids)
        assert not list((root / "slots").glob("*/result.json"))
        assert not (root / "terminal.json").exists()
    finally:
        # This process group contains only the synthetic fixture and its children.
        try:
            os.killpg(parent.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        parent.wait(timeout=5)


if __name__ == "__main__":
    supervisor.arm_environment = lambda _: {"SHENGJI_BOT": "fixture"}
    supervisor.write_seed = _slow_seed
    supervisor.FIRST_SEED, supervisor.DEALS = 100, 4
    supervisor.run_reserved(Path(sys.argv[1]), [], "a" * 64, workers=2)
