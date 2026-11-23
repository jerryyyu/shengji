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
        assert cmd[cmd.index("--microbatch-rounds") + 1] == "4"
        assert ("--max-train-rows" in cmd) == (phase == "smoke")
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


@pytest.fixture
def cache_worker(segment):
    import sz2_cache_arm
    return sz2_cache_arm


@pytest.mark.parametrize("last", [
    "LANE DONE sz2-joint-v1 t FAIL-OFFLINE at buffer 400 rc=0",
    "LANE DONE sz2-joint-v1 t joint arms complete rc=0\nLANE PAUSED sz2-joint-v1 t operator STOP",
    "LANE DONE sz2-joint-v1 t joint arms complete rc=0 extra",
])
def test_cache_rejects_unsuccessful_joint_before_any_arm_access(cache_worker, tmp_path, last):
    (tmp_path / "launcher.status").write_text(last + "\nLANE UNLOCKED sz2-joint-v1 t /lock\n")
    with pytest.raises(ValueError, match="joint arms did not complete"):
        cache_worker.cache_partition(tmp_path, "S", 0, tmp_path / "cache", tmp_path / "absent", "")
    assert not (tmp_path / "cache").exists()


def test_joint_checkpoint_produces_weighted_cpu_cache_for_polish(cache_worker, cpu_root, data, tmp_path):
    import fcntl
    import os

    import numpy as np

    train = tmp_path / "S/train"
    train.mkdir(parents=True)
    checkpoint = train / "best.pt"
    os.link(cpu_root[0] / "train/best.pt", checkpoint)
    sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    (tmp_path / "launcher.status").write_text("LANE DONE sz2-joint-v1 t joint arms complete rc=0\n"
                                              "LANE UNLOCKED sz2-joint-v1 t /lock\n")
    recipe = tmp_path / "recipe.json"
    recipe.write_text(json.dumps({"seed": 1, "data": [str(data)], "store_map": [],
                                  "exclude_seed_window": [[123456000, 123456001]],
                                  "corpus_weight": [f"{data}=policy:2,reply:2"]}))
    recipe_sha = hashlib.sha256(recipe.read_bytes()).hexdigest()
    output = tmp_path / "cache"

    def run(worker):
        return cache_worker.cache_partition(tmp_path, "S", worker, output, recipe, recipe_sha)

    (train / "status.log").write_text(f"t UTR DONE best={checkpoint} sha256={'0' * 64}\n")
    with pytest.raises(ValueError, match="checkpoint differs"):
        run(0)
    assert not output.exists()
    (train / "status.log").write_text(f"t UTR DONE best={checkpoint} sha256={sha}\n")
    for worker in range(3):
        assert run(worker) == 0
    cache = output / "S" / f"{sha}-{recipe_sha}"
    shard_path = cache / "train-0000.npz"
    written = shard_path.stat().st_mtime_ns
    with (cache / "worker-0.lock").open("a") as peer:
        fcntl.flock(peer, fcntl.LOCK_EX)
        with pytest.raises(BlockingIOError):
            run(0)
    assert run(0) == 0 and shard_path.stat().st_mtime_ns == written
    with np.load(shard_path) as shard:
        assert (shard["leaf_w"][:, 1] == 2).all()
    from sz2_polish_arm import polish_arm

    def polish():
        return polish_arm(tmp_path, "S", output, tmp_path / "polish", recipe, recipe_sha)

    done = cache / "DONE.2"
    done.rename(cache / "held")
    with pytest.raises(FileNotFoundError):
        polish()
    (cache / "held").rename(done)
    shard_path.rename(cache / "held")
    with pytest.raises(ValueError, match="incomplete dense cache"):
        polish()
    (cache / "held").rename(shard_path)
    with (cache / "worker-1.lock").open("rb") as peer:
        fcntl.flock(peer, fcntl.LOCK_EX)
        with pytest.raises(BlockingIOError):
            polish()
    assert not (tmp_path / "polish").exists()
    assert polish() == 0
    out = tmp_path / "polish/S" / cache.name
    selected = torch.load(out / "best.pt", weights_only=False)["calib"]["polish_epoch"]
    assert (out / "selected.pt").samefile(out / "best.pt" if selected else checkpoint)
    with pytest.raises(FileExistsError):
        polish()
