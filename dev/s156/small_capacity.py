"""Measure one bounded slice of the full small CPU arm with its provider resident."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import sz2_gpu_smoke as worker

PROVIDER = Path.home() / ".darkbloom/Darkbloom.app/Contents/MacOS/darkbloom"
SECONDS = 600


def provider_sample(expected_pid=None):
    rows = []
    for line in worker.command(worker.PS, "-axo", "pid=,rss=,comm=").splitlines():
        fields = line.split(None, 2)
        if len(fields) == 3 and fields[2] == str(PROVIDER):
            rows.append((int(fields[0]), int(fields[1])))
    if len(rows) != 1 or rows[0][1] <= 0 or (expected_pid is not None and rows[0][0] != expected_pid):
        raise ValueError("resident Darkbloom process missing, ambiguous or replaced")
    pid, rss = rows[0]
    print(f"provider_pid={pid} provider_rss_kib={rss}", flush=True)
    return pid


def bounded_command(root, seconds):
    raw = worker.command(sys.executable, "-B", worker.SCRIPTS / "sz2_joint_segment.py",
                         "small", "--root", root, timeout=60)
    argv = json.loads(raw)
    if argv.count("--max-seconds") != 1 or argv[argv.index("--max-seconds") + 1] != "5400":
        raise ValueError("unexpected joint worker time limit")
    argv[argv.index("--max-seconds") + 1] = str(seconds)
    return argv


def run(root, *, preflight=False, seconds=SECONDS):
    train = root / "S/train"
    if os.path.lexists(train.parent):
        raise ValueError("small capacity output already claimed")
    argv = bounded_command(root, seconds)
    if not worker.darkbloom_ready(worker.command(worker.DARKBLOOM, "status")):
        raise ValueError("Darkbloom not eligible")
    pid = provider_sample()
    baseline, pressure = worker.memory_sample()
    if pressure >= 4:
        raise ValueError("memory pressure high at admission")
    if preflight:
        return
    footprint = worker.footprint_mib(pid)
    if footprint is None:
        raise ValueError("initial provider footprint unavailable")
    print(f"provider_pid={pid} provider_initial_footprint_mib={footprint:g}", flush=True)
    train.parent.mkdir()
    started = time.monotonic()
    child = subprocess.Popen(argv, cwd=worker.SCRIPTS.parent, stdin=subprocess.DEVNULL,
                             env={**os.environ, "OMP_NUM_THREADS": "16"})
    rc = worker.monitor(child, baseline, lambda: None, lambda: provider_sample(pid))
    if rc != 3 or time.monotonic() - started < seconds or os.path.lexists(train / "STOP"):
        raise ValueError(f"trainer did not reach timed checkpoint, rc={rc}")
    last = (train / "status.log").read_text().splitlines()[-1]
    if not re.fullmatch(r"\S+ STOPPED at epoch 1 buffer [1-9]\d*/[1-9]\d* "
                        r"\(STOP file or --max-seconds\); checkpoint saved", last):
        raise ValueError("missing timed trainer boundary")
    if (train / "checkpoint.pt").stat().st_size == 0:
        raise ValueError("empty trainer checkpoint")
    provider_sample(pid)
    if not worker.darkbloom_ready(worker.command(worker.DARKBLOOM, "status")):
        raise ValueError("Darkbloom not eligible after training")
    print(f"capacity sample complete: {last}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--preflight", action="store_true")
    options = parser.parse_args()
    run(options.root, preflight=options.preflight)
