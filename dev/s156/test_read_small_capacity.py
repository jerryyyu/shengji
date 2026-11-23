import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_small_capacity import packet


@pytest.fixture
def reader(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parent))
    return importlib.import_module("read_small_capacity")


@pytest.fixture
def log(packet, monkeypatch, tmp_path, capsys):
    worker = packet.worker
    clock = [0]
    def nap(seconds):
        clock[0] += seconds
    timer = SimpleNamespace(monotonic=lambda: clock[0], sleep=nap)
    monkeypatch.setattr(worker, "time", timer)
    monkeypatch.setattr(packet, "time", timer)
    monkeypatch.setattr(worker, "memory_sample", lambda: (100, 1))
    monkeypatch.setattr(worker, "footprint_mib", lambda pid: 2000.0)
    def command(*args):
        if args[0] == worker.DARKBLOOM:
            return "ready"
        if args[0] == worker.LAUNCHCTL:
            return "123 0 io.darkbloom.provider"
        if args[1] == "-p":
            return f"100 {packet.PROVIDER}"
        return "256"
    monkeypatch.setattr(worker, "command", command)
    monkeypatch.setattr(worker, "darkbloom_ready", lambda s: s == "ready")
    monkeypatch.setattr(packet, "bounded_command", lambda root, seconds: ["train"])
    def trainer(*args, **kwargs):
        out = tmp_path / "S/train"
        out.mkdir()
        (out / "checkpoint.pt").write_bytes(b"test")
        (out / "status.log").write_text("t STOPPED at epoch 1 buffer 25/1000 (STOP file or --max-seconds); checkpoint saved")
        return SimpleNamespace(pid=999, poll=lambda: 3 if clock[0] >= 600 else None)
    monkeypatch.setattr(packet, "subprocess", SimpleNamespace(Popen=trainer, DEVNULL=-3))
    packet.run(tmp_path)
    return capsys.readouterr().out


def test_real_monitor_format_and_exact_bars(log, reader):
    assert reader.score(log)["decision"] == "PASS"
    for field, change in [("swap_mib=100", "swap_mib=1124"), ("pressure=1", "pressure=2"),
                          ("footprint_mib=2000 footprint_", "footprint_mib=24576 footprint_")]:
        assert reader.score(log.replace(field, change, 1))["decision"] == "FAIL"
    for rss, expected in [(90, "PASS"), (89, "FAIL")]:
        assert reader.score(log.replace("provider_rss_kib=100", f"provider_rss_kib={rss}", 2)
                            .replace(f"provider_rss_kib={rss}", "provider_rss_kib=100", 1))["decision"] == expected
    before, last = log.rsplit("footprint_mib=2000 footprint_", 1)
    assert reader.score(before + "footprint_mib=2001 footprint_" + last)["decision"] == "FAIL"


def test_missing_evidence_is_inconclusive(log, reader):
    for field in ["provider_rss_kib=100", "footprint_mib=2000 footprint_", "elapsed_s=20.0", "capacity sample complete:"]:
        with pytest.raises(ValueError):
            reader.score("\n".join(line for line in log.splitlines() if field not in line))


def test_reader_requires_reviewed_terminal_before_log(tmp_path, reader, log):
    capture = tmp_path / "capture"
    capture.mkdir()
    (tmp_path / "launcher.RELEASE").write_text(reader.IDENTITY)
    status = capture / "launcher.status"
    status.write_text("LANE PAUSED")
    with pytest.raises(ValueError, match="unlocked"):
        reader.read(tmp_path)
    status.write_text(f"LANE DONE {reader.LANE} t small CPU capacity sampled rc=0\n"
                      f"LANE UNLOCKED {reader.LANE} t /Users/jeryyu/fleet/.claude-host.lock\n")
    (capture / "launcher.log").write_text(log)
    assert reader.read(tmp_path)["decision"] == "PASS"
