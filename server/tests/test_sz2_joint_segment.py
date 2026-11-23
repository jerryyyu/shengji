import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from test_unified_readout_device import cpu_root, data, mps, torch, ur


@pytest.fixture
def segment(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import sz2_joint_segment
    return sz2_joint_segment


def test_waits_for_the_actual_terminal_and_worker_drain(segment, monkeypatch, tmp_path):
    status, heartbeat = tmp_path / "status.txt", tmp_path / "heartbeat"
    status.write_text("t RUN DONE 64 seeds rc 0\nt start seed 1 pid 12\n")
    heartbeat.write_text("123 done 64/64 live []\n")
    assert not segment.predecessor_done(tmp_path)
    status.write_text("t RUN DONE 64 seeds rc 0\n")
    heartbeat.write_text("123 done 63/64 live [1]\n")
    assert not segment.predecessor_done(tmp_path)
    heartbeat.write_text("123 done 64/64 live []\n")
    inventory = subprocess.CompletedProcess([], 0, stdout=f"python {tmp_path}/code/s157a.py\n")
    monkeypatch.setattr(segment.subprocess, "run", lambda *a, **kw: inventory)
    assert not segment.predecessor_done(tmp_path)
    inventory.stdout = "/sbin/launchd\n"
    assert segment.predecessor_done(tmp_path)


@mps
def test_joint_commands_gate_the_real_medium_resume(segment, data, cpu_root, tmp_path):
    fleet, out = tmp_path / "fleet", tmp_path / "sz2"
    original = cpu_root[0] / "train/best.pt"
    weights = torch.load(original, weights_only=False, map_location="cpu")
    hashes = {}
    for arm in ("S", "M"):
        init = fleet / "claude-ut-size/arm" / arm / "polish/best.pt"
        init.parent.mkdir(parents=True)
        torch.save({**weights, "arm": arm}, init)
        hashes[arm] = hashlib.sha256(init.read_bytes()).hexdigest()
    recipe = json.loads((cpu_root[0] / "train/run.json").read_text())
    recipe.update(calib_data=[str(data)], epochs=1, corpus_weight=[f"{data}=policy:2,reply:2"])
    for phase, expected in (("smoke", 0), ("small", 0), ("medium-prefix", 7), ("medium-prefix", 7)):
        rc, cmd = segment.prepare(phase, out, fleet, recipe, hashes, 1, weights["calib"]["belief_ll"])
        assert rc == 0
        if phase == "smoke":
            assert "--report-buffer" not in cmd and cmd[cmd.index("--max-train-rows")+1] == "120000"
        assert ur.main(cmd[4:]) == expected

    assert segment.prepare("medium-finish", out, fleet, recipe, hashes, 1, weights["calib"]["belief_ll"]) == (8, None)
    report = out / "M/train/epoch-1-buffer-1.json"
    record = json.loads(report.read_text())
    record["train"]["policy"] = 0.0
    report.write_text(json.dumps(record))
    rc, cmd = segment.prepare("medium-finish", out, fleet, recipe, hashes, 1, weights["calib"]["belief_ll"])
    assert rc == 0 and "--pause-at-report" not in cmd
    assert ur.main(cmd[4:]) == 0
    assert (out / "M/train/best.pt").is_file()
