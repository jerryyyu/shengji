"""Run with the pinned joint worker checkout as the test_checkout.py source."""
import json
from pathlib import Path
import sys

import pytest


@pytest.fixture
def packet(monkeypatch):
    import shengji

    server = Path(shengji.__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(server / "scripts"))
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parent))
    import small_capacity
    return small_capacity


def test_bounded_command_changes_only_wall_budget(packet, tmp_path, monkeypatch):
    original = ["python", "-m", "trainer", "--max-seconds", "5400", "--microbatch-rounds", "4"]
    segment = tmp_path / "sz2_joint_segment.py"
    segment.write_text(f"import sys\nassert sys.argv[1:] == ['small', '--root', {str(tmp_path)!r}]\n"
                       f"print({json.dumps(original)!r})\n")
    monkeypatch.setattr(packet.worker, "SCRIPTS", tmp_path)
    assert packet.bounded_command(tmp_path, 600) == [*original[:4], "600", *original[5:]]


@pytest.mark.parametrize("mode", ["timed", "stop", "restart", "guard", "early", "missing"])
def test_capacity_supervises_child_and_checks_terminal(packet, tmp_path, monkeypatch, mode):
    worker = packet.worker
    trainer = tmp_path / "trainer.py"
    trainer.write_text("""
import os, pathlib, sys, time
root = pathlib.Path(sys.argv[1])
assert os.environ['OMP_NUM_THREADS'] == '16'
out = root / 'S/train'
out.mkdir()
(out/'status.log').write_text('t STOPPED at epoch 1 buffer 2/40 (STOP file or --max-seconds); checkpoint saved')
if sys.argv[2] != 'missing':
    (out/'checkpoint.pt').write_bytes(b'weights')
if sys.argv[2] == 'stop':
    (out/'STOP').touch()
time.sleep(0.1)
sys.exit(3)
""")
    monkeypatch.setattr(packet, "bounded_command", lambda root, seconds: [sys.executable, str(trainer), str(root), mode])
    monkeypatch.setattr(worker, "darkbloom_ready", lambda status: status == "eligible")
    monkeypatch.setattr(worker, "POLL_SECONDS", 0.01)
    monkeypatch.setattr(worker, "footprint_mib", lambda pid: 100.0)
    def command(*args):
        if args == (worker.DARKBLOOM, "status"):
            return "eligible"
        if args == (worker.LAUNCHCTL, "list"):
            pid = 999 if mode == "restart" and (tmp_path / "S").exists() else 123
            return f"{pid} 0 io.darkbloom.provider\n456 0 io.darkbloom.watchdog"
        if args == (worker.PS, "-p", "123", "-o", "rss=,comm="):
            return f"256 {packet.PROVIDER}"
        assert args[:3] == (worker.PS, "-o", "rss=")
        return "256"
    monkeypatch.setattr(worker, "command", command)
    monkeypatch.setattr(worker, "memory_sample", lambda: (0, 4 if mode == "guard" and (tmp_path / "S").exists() else 1))
    if mode == "timed":
        packet.run(tmp_path, seconds=0.05)
        with pytest.raises(ValueError, match="already claimed"):
            packet.run(tmp_path, seconds=0.05)
    else:
        with pytest.raises((ValueError, RuntimeError, FileNotFoundError)):
            packet.run(tmp_path, seconds=10 if mode == "early" else 0.05)
