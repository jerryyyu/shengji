"""Admit a one-shot CPU trajectory capture beside the reviewed SZ3 M segment."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone

from sz3_filler_generator import GENERATOR_TREE, generator_environment, prepare_generator, validate_completion
from sz3_filler_pace import PaceGuard
from sz3_filler_process import supervise

GIB = 2**30
FLEET = Path("/Users/jeryyu/fleet")
PACKET = FLEET / "codex-sz3-cpu-filler-v1"
CAPTURE = PACKET / "capture"
TRAIN = FLEET / "codex-sz3-joint-v1/capture"
JOINT = FLEET / "codex-sz3-joint-v2"
JOINT_SHA = "405fb26930bb9b0846ee9ef9ae02e916287acf17314b2455dff349a53ff26129"
ENV = {"HOME": str(FLEET.parent), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "PYTHONNOUSERSITE": "1",
       "PYTHONDONTWRITEBYTECODE": "1"}


def output(*args):
    return subprocess.check_output(args, text=True, timeout=5).strip()


def pairing():
    if (JOINT / "launcher.RELEASE").read_text().split()[0] != JOINT_SHA:
        raise RuntimeError("SZ3 release changed")
    holds = [PACKET / "launcher.HOLD", JOINT / "launcher.HOLD", TRAIN.parent / "launcher.HOLD",
             FLEET / "claude_ut_gen2.HOLD", TRAIN / "M/train/STOP"]
    if any(os.path.lexists(path) for path in holds):
        raise RuntimeError("operator HOLD or STOP")
    owner = (FLEET / ".claude-host.lock/owner").read_text().split()
    lines = (TRAIN / "launcher.status").read_text().splitlines()
    if len(owner) != 3 or owner[1] != "sz3-joint-v1" or not owner[0].isdigit():
        raise RuntimeError("SZ3 lock owner changed")
    if (len(lines) < 3 or not re.match(rf"^LANE START sz3-joint-v1 \S+ pid={owner[0]} ", lines[0])
            or not re.fullmatch(r"LANE PHASE sz3-joint-v1 \S+ M after buffer \d+", lines[-2])):
        raise RuntimeError("SZ3 is outside its active M phase")
    producer = re.fullmatch(r"LANE PRODUCER sz3-joint-v1 \S+ pgid=([1-9]\d*) ceiling=\d+s", lines[-1])
    if not producer:
        raise RuntimeError("SZ3 producer is no longer active")
    pid = producer[1]
    command = output("/bin/ps", "-o", "pgid=,command=", "-p", pid).split()
    worker = "/Users/jeryyu/Projects/shengji-wt/codex-sz3-joint-2f1c9e68/server/scripts/sz2_gpu_smoke.py"
    if (len(command) < 8 or command[0] != pid or command[2:7] != ["-B", worker, str(TRAIN), "--phase", "M"]
            or output("/bin/ps", "-o", "command=", "-p", owner[0]) != f"/bin/bash {JOINT}/run_joint.sh"):
        raise RuntimeError("SZ3 live handles differ")
    return owner, lines[-1]


def resources():
    pressure = int(output("/usr/sbin/sysctl", "-n", "kern.memorystatus_vm_pressure_level"))
    swap = re.search(r"\bused\s*=\s*(\d+(?:\.\d+)?)([KMGT])\b",
                     output("/usr/sbin/sysctl", "-n", "vm.swapusage"))
    if pressure != 1 or not swap:
        raise RuntimeError("memory pressure elevated or swap unavailable")
    return float(swap[1]) * 1024 ** ("KMGT".index(swap[2]) + 1), shutil.disk_usage(FLEET).free


def trainer_status():
    path = TRAIN / "M/train/status.log"
    if path.stat().st_size > 2**20:
        raise RuntimeError("SZ3 status exceeds bounded sample")
    return path.read_text()


def capture_bytes():
    total = 0
    for directory, _, names in os.walk(CAPTURE):
        for name in names:
            try:
                total += (Path(directory) / name).stat().st_size
            except FileNotFoundError:
                continue  # temporary files are atomically published under their final names
    return total


def main(mode):
    if mode not in ("--run", "--preflight") or output("/bin/hostname") != "Jerrys-Mac-Studio.local":
        raise RuntimeError("invalid filler host or mode")
    if os.path.lexists(CAPTURE):
        raise RuntimeError("filler capture already claimed")
    paired = pairing()
    swap, free = resources()
    if free < 290 * GIB:
        raise RuntimeError("admission requires 290 GiB free")
    command, registry = prepare_generator(CAPTURE)
    baseline = PaceGuard(trainer_status(), datetime.now(timezone.utc))
    print(f"baseline_buffers_per_min={baseline.baseline_buffers_per_minute:.4f} free_gib={free/GIB:.2f}"
          f" swap_mib={swap/2**20:.2f}", flush=True)
    if mode == "--preflight":
        return 0
    token = subprocess.check_output(["/bin/bash", str(PACKET / "filler.sh"), "--admit"],
                                    env=ENV, text=True, timeout=20).strip()
    if not re.fullmatch(r"[a-f0-9]{64}", token):
        raise RuntimeError("invalid filler admission digest")
    CAPTURE.mkdir()

    def check():
        if (paired != pairing() or (PACKET / "launcher.RELEASE").is_symlink()
                or (PACKET / "launcher.RELEASE").read_text().split()[0] != token):
            return "paired run or filler release changed"
        current, available = resources()
        if current - swap > 2 * GIB or available < 285 * GIB:
            return "swap growth or disk floor"
        if capture_bytes() >= 3 * GIB:
            return "capture size budget"
        baseline.check(trainer_status(), datetime.now(timezone.utc))
        return None

    def guard():
        try:
            return check()
        except (RuntimeError, ValueError, OSError, IndexError, subprocess.SubprocessError) as exc:
            return str(exc) or type(exc).__name__

    try:
        (CAPTURE / "seed_windows.json").write_text(json.dumps(registry))
        with (CAPTURE / "generator.log").open("xb") as log:
            result = supervise(command, cwd=GENERATOR_TREE / "server",
                               env=generator_environment(), log=log, guard=guard, wall_seconds=7200,
                               max_rss_bytes=6 * GIB)
        if result.stop_reason:
            (CAPTURE / "terminal").write_text(f"STOPPED {result.stop_reason}\n")
            return 3
        if result.returncode:
            raise RuntimeError(f"generator exit {result.returncode}")
        validate_completion(CAPTURE / "store")
    except Exception as exc:
        (CAPTURE / "terminal").write_text(f"ERROR {exc}\n")
        raise
    (CAPTURE / "terminal").write_text("DONE rounds=2000 clusters=1000\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
