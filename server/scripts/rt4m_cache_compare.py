"""Time two RT4-M cache partitions with one or two concurrent CPU workers."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import subprocess
import sys
from time import monotonic
from zipfile import ZipFile

from rt4m_cache import RT4_SAMPLE
import rt4m_joint
import sz2_cache_arm as cache_arm

# A six-group prefix gives workers 1 and 2 two groups each. Worker 0 owns calibration.
GROUPS = 6
WORKER_IDS = (1, 2)
ARRAYS = {"S", "c", "leaf_row", "leaf_planes", "leaf_scalars", "leaf_target", "leaf_reply",
          "leaf_reply_hand", "leaf_has_reply", "leaf_w"}


def run_leg(checkpoint, recipe, out, concurrency):
    if concurrency not in (1, 2):
        raise ValueError("expected one or two concurrent workers")
    out = out.resolve()
    checkpoint = checkpoint.resolve()
    out.mkdir(parents=True, exist_ok=False)

    def run_worker(worker):
        args = cache_arm.partition_args(checkpoint, out, recipe, worker, encode_rounds=cache_arm.MEDIUM_ENCODE_ROUNDS,
                              sample_rows=RT4_SAMPLE["cap_rows"])
        subprocess.run([sys.executable, "-B", "-m", "shengji.train.unified_readout", *args,
                        "--max-groups", str(GROUPS)], check=True, cwd=Path(__file__).resolve().parents[1])

    start = monotonic()
    if concurrency == 1:
        for worker in WORKER_IDS:
            run_worker(worker)
    else:
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(run_worker, WORKER_IDS))
    elapsed = monotonic() - start
    (out / "timing.json").write_text(json.dumps(dict(workers=concurrency, seconds=elapsed)))


def compare(serial, parallel):
    records = []
    shards = {f"train-{n:04d}.npz" for n in range(GROUPS) if n % 3 in WORKER_IDS}
    for out, workers in ((serial, 1), (parallel, 2)):
        timing = json.loads((out / "timing.json").read_text())
        if timing["workers"] != workers or not math.isfinite(timing["seconds"]) or timing["seconds"] <= 0:
            raise ValueError("invalid cache leg timing")
        if {p.name for p in out.glob("*.npz")} != shards or {p.name for p in out.glob("DONE.*")} != {"DONE.1", "DONE.2"}:
            raise ValueError("incomplete cache partitions")
        device, encode, first, second = [json.loads((out / name).read_text()) for name in
                                         ("cache_device.json", "cache_encode.json", "DONE.1", "DONE.2")]
        if (device != {"device": "cpu"} or encode["rounds_per_batch"] != cache_arm.MEDIUM_ENCODE_ROUNDS
                or encode["sample"]["max_groups"] != GROUPS or encode["sample"]["workers"] != 3
                or encode["sample"]["group_chunks"] != cache_arm.GROUP_CHUNKS
                or first != second or first["groups"] != GROUPS or not first["corpus_weight"]
                or first["sample"] != RT4_SAMPLE or first["sample"] != encode["sample"]["receipt"]):
            raise ValueError("wrong cache selection or layout")
        records.append((encode, first, timing["seconds"]))
    if records[0][:2] != records[1][:2]:
        raise ValueError("cache legs used different inputs")
    for name in sorted(shards):
        with ZipFile(serial / name) as a, ZipFile(parallel / name) as b:
            members = sorted(f"{key}.npy" for key in ARRAYS)
            if sorted(a.namelist()) != members or sorted(b.namelist()) != members:
                raise ValueError(f"{name}: different or missing arrays")
            for key in a.namelist():
                with a.open(key) as left, b.open(key) as right:
                    while True:
                        chunk = left.read(1 << 20)
                        if chunk != right.read(1 << 20):
                            raise ValueError(f"{name}: {key} differs")
                        if not chunk:
                            break
    return dict(serial_seconds=records[0][2], parallel_seconds=records[1][2],
                speedup=records[0][2] / records[1][2], equal_shards=len(shards))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    leg = commands.add_parser("leg")
    leg.add_argument("joint_root", type=Path)
    leg.add_argument("output", type=Path)
    leg.add_argument("--concurrency", type=int, choices=(1, 2), required=True)
    read = commands.add_parser("compare")
    read.add_argument("serial", type=Path)
    read.add_argument("parallel", type=Path)
    args = parser.parse_args()
    if args.command == "leg":
        checkpoint, _, recipe = rt4m_joint.completed_inputs(args.joint_root, rt4m_joint.RECIPE)
        run_leg(checkpoint, recipe, args.output, args.concurrency)
    else:
        print(json.dumps(compare(args.serial, args.parallel), allow_nan=False))
