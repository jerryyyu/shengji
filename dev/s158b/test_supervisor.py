import hashlib
import json
import os

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
