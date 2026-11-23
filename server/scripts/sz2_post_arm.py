"""Run the cache partitions, polish and export serially under the admitted arm's host lock."""
import argparse
import os
import subprocess
import sys

import sz2_gpu_smoke as host
from sz2_cache_arm import FLEET, WORKERS


def run(arm, expected_sha=None):
    from small_capacity import provider_sample

    expected_sha = host.provider_digest(expected_sha)
    if arm == "M" and any((FLEET / "codex-sz2-cache-v1/S").glob("*/*.npz")):
        raise ValueError("S cache must be offloaded before M cache")
    if not host.darkbloom_ready(host.command(host.DARKBLOOM, "status"), expected_sha):
        raise ValueError("Darkbloom must be eligible at entry")
    pid = provider_sample()
    baseline, pressure = host.memory_sample()
    if pressure != 1:
        raise ValueError("memory pressure above normal at admission")
    steps = [("sz2_cache_arm.py", [arm, str(i)], "8") for i in range(WORKERS)]
    steps += [("sz2_polish_arm.py", [arm], "16"), ("sz2_export_arm.py", [arm], "2")]
    for script, args, threads in steps:
        provider_sample(pid)
        swap, pressure = host.memory_sample()
        if pressure != 1 or swap - baseline >= 1024:
            raise ValueError("resident-provider memory budget exceeded")
        print(f"starting {script} {' '.join(args)} OMP_NUM_THREADS={threads}", flush=True)
        child = subprocess.Popen([sys.executable, "-B", host.SCRIPTS / script, *args],
                                 cwd=host.SCRIPTS.parent, stdin=subprocess.DEVNULL,
                                 env={**os.environ, "OMP_NUM_THREADS": threads})
        rc = host.monitor(child, baseline, lambda: None, lambda: provider_sample(pid),
                          pressure_limit=2, swap_limit=1024, footprint_limit=24576)
        if rc:
            raise RuntimeError(f"{script} {' '.join(args)} rc={rc}")
    provider_sample(pid)
    if not host.darkbloom_ready(host.command(host.DARKBLOOM, "status"), expected_sha):
        raise ValueError("Darkbloom ineligible after export")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arm", choices=("S", "M"))
    parser.add_argument("--provider-sha256", required=True)
    args = parser.parse_args()
    run(args.arm, args.provider_sha256)
