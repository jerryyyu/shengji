import importlib
from pathlib import Path
import sys

import pytest


@pytest.fixture
def lane(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts/lanes"))
    m = importlib.import_module("sz3_filler")
    fleet = tmp_path / "fleet"
    packet = fleet / "filler"
    packet.mkdir(parents=True)
    train = fleet / "joint/capture"
    (train / "M/train").mkdir(parents=True)
    joint = fleet / "v2"
    joint.mkdir()
    monkeypatch.setattr(m, "FLEET", fleet)
    monkeypatch.setattr(m, "TRAIN", train)
    monkeypatch.setattr(m, "JOINT", joint)
    monkeypatch.setattr(m, "PACKET", packet)
    monkeypatch.setattr(m, "CAPTURE", packet / "capture")
    (joint / "launcher.RELEASE").write_text(m.JOINT_SHA)
    lock = fleet / ".claude-host.lock"
    lock.mkdir()
    (lock / "owner").write_text("123 sz3-joint-v1 earlier")
    (train / "launcher.status").write_text(
        "LANE START sz3-joint-v1 t pid=123 host=Ultra\nLANE PHASE sz3-joint-v1 t M after buffer 0\n"
        "LANE PRODUCER sz3-joint-v1 t pgid=456 ceiling=9000s\n")
    worker = "/Users/jeryyu/Projects/shengji-wt/codex-sz3-joint-2f1c9e68/server/scripts/sz2_gpu_smoke.py"
    def output(*cmd):
        if cmd[0] == "/bin/hostname":
            return "Jerrys-Mac-Studio.local"
        if cmd[-1] == "456":
            return f"456 python -B {worker} {train} --phase M --provider-sha256 expected"
        if cmd[-1] == "123":
            return f"/bin/bash {joint}/run_joint.sh"
        pytest.fail(str(cmd))
    monkeypatch.setattr(m, "output", output)
    return m


def test_only_active_paired_producer_is_eligible(lane):
    assert lane.pairing()[0][0] == "123"
    (lane.TRAIN / "M/train/STOP").touch()
    with pytest.raises(RuntimeError, match="STOP"):
        lane.pairing()
    (lane.TRAIN / "M/train/STOP").unlink()
    with (lane.TRAIN / "launcher.status").open("a") as f:
        f.write("LANE DONE sz3-joint-v1 t done\n")
    with pytest.raises(RuntimeError, match="active M phase"):
        lane.pairing()


@pytest.mark.parametrize("trip", ["disk", "swap", "hold", "release", "size", "terminal"])
def test_capture_stops_at_guard_preserving_partial_store(lane, monkeypatch, trip):
    pin = "a" * 64
    (lane.PACKET / "launcher.RELEASE").write_text(pin)
    monkeypatch.setattr(lane.subprocess, "check_output", lambda *a, **kw: pin)
    monkeypatch.setattr(lane, "prepare_generator", lambda c: (["fixture"], {"windows": []}))
    monkeypatch.setattr(lane, "trainer_status", lambda: "")
    monkeypatch.setattr(lane, "PaceGuard", lambda *a: type("Guard", (), {
        "baseline_buffers_per_minute": 5, "check": lambda *a: None})())
    monkeypatch.setattr(lane, "resources", lambda: (0, 291 * lane.GIB))
    def produce(argv, *, guard, **kw):
        assert guard() is None and argv == ["fixture"]
        store = lane.CAPTURE / "store"
        store.mkdir()
        (store / "shard").write_bytes(b"published")
        if trip == "disk":
            monkeypatch.setattr(lane, "resources", lambda: (0, 284 * lane.GIB))
        elif trip == "swap":
            monkeypatch.setattr(lane, "resources", lambda: (2 * lane.GIB + 1, 291 * lane.GIB))
        elif trip == "hold":
            (lane.PACKET / "launcher.HOLD").touch()
        elif trip == "release":
            (lane.PACKET / "launcher.RELEASE").write_text("b" * 64)
        elif trip == "size":
            monkeypatch.setattr(lane, "capture_bytes", lambda: 3 * lane.GIB)
        else:
            with (lane.TRAIN / "launcher.status").open("a") as f:
                f.write("LANE DONE sz3-joint-v1 t completed\n")
        reason = guard()
        assert reason
        return type("Result", (), {"stop_reason": reason})
    monkeypatch.setattr(lane, "supervise", produce)
    assert lane.main("--run") == 3
    assert (lane.CAPTURE / "terminal").read_text().startswith("STOPPED")
    assert (lane.CAPTURE / "store/shard").read_bytes() == b"published"
    with pytest.raises(RuntimeError, match="already claimed"):
        lane.main("--run")


def test_resource_sample_converts_swap_and_refuses_elevated_pressure(lane, monkeypatch):
    pressure = 1
    def sample(*cmd):
        if cmd[-1] == "vm.swapusage":
            return "total = 2048.00M  used = 622.31M  free = 1425.69M  (encrypted)"
        return str(pressure)
    monkeypatch.setattr(lane, "output", sample)
    swap, free = lane.resources()
    assert swap == 622.31 * 2**20 and free > 0
    pressure = 2
    with pytest.raises(RuntimeError, match="pressure"):
        lane.resources()
