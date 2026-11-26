"""Build one CPU cache partition from a completed SZ2 joint arm under its host supervisor."""
import argparse
import fcntl
import hashlib
import json
import re
import sys

from sz2_joint_segment import FLEET, RECIPE, RECIPE_SHA

JOINT = FLEET / "codex-sz2-joint-v1/capture"
WORKERS = 3
MEDIUM_ENCODE_ROUNDS = 4
GROUP_CHUNKS = 24


def arm_inputs(joint, arm, output, recipe_path, recipe_sha):
    if arm not in ("S", "M"):
        raise ValueError("invalid joint arm")
    status = (joint / "launcher.status").read_text().splitlines()
    if status and re.fullmatch(r"LANE UNLOCKED sz2-joint-v1 \S+ /\S+", status[-1]):
        status.pop()
    if not status or not re.fullmatch(r"LANE DONE sz2-joint-v1 \S+ joint arms complete rc=0", status[-1]):
        raise ValueError("joint arms did not complete")
    train = joint / arm / "train"
    checkpoint = train / "best.pt"
    terminal = (train / "status.log").read_text().splitlines()
    witness = re.fullmatch(r"\S+ UTR DONE best=(.+) sha256=([0-9a-f]{64})", terminal[-1]) if terminal else None
    if not witness or witness[1] != str(checkpoint):
        raise ValueError("expected this arm's completed checkpoint")
    with checkpoint.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != witness[2]:
            raise ValueError("checkpoint differs from trainer terminal")
    raw = recipe_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != recipe_sha:
        raise ValueError("FT500k recipe changed")
    recipe = json.loads(raw)
    identity = f"{witness[2]}-{recipe_sha}"
    if arm == "M":
        identity += f"-encode{MEDIUM_ENCODE_ROUNDS}"
    cache = output / arm / identity
    return checkpoint, cache, recipe


def cache_partition(joint, arm, worker, output, recipe_path, recipe_sha):
    if worker not in range(WORKERS):
        raise ValueError("invalid cache partition")
    checkpoint, cache, recipe = arm_inputs(joint, arm, output, recipe_path, recipe_sha)
    return write_partition(checkpoint, cache, recipe, worker,
                           encode_rounds=MEDIUM_ENCODE_ROUNDS if arm == "M" else None)


def partition_args(checkpoint, cache, recipe, worker, *, encode_rounds=None, sample_rows=None):
    if worker not in range(WORKERS):
        raise ValueError("invalid cache partition")
    args = ["cache", "--ckpt", str(checkpoint), "--data", *recipe["data"], "--out", str(cache),
            "--seed", str(recipe["seed"]), "--device", "cpu", "--threads", "8",
            "--worker", str(worker), "--workers", str(WORKERS), "--group-chunks", str(GROUP_CHUNKS),
            "--calib-rows", "180000"]
    if encode_rounds is not None:
        args.extend(["--encode-rounds-per-batch", str(encode_rounds)])
    if sample_rows is not None:
        args.extend(["--sample-train-rows", str(sample_rows)])
    for key in ("store_map", "corpus_weight"):
        for value in recipe[key]:
            args.extend(["--" + key.replace("_", "-"), value])
    for start, end in recipe["exclude_seed_window"]:
        args.extend(["--exclude-seed-window", f"{start}:{end}"])
    return args


def write_partition(checkpoint, cache, recipe, worker, *, encode_rounds=None, sample_rows=None):
    from shengji.train import unified_readout

    args = partition_args(checkpoint, cache, recipe, worker, encode_rounds=encode_rounds, sample_rows=sample_rows)
    cache.mkdir(parents=True, exist_ok=True)
    with (cache / f"worker-{worker}.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return unified_readout.main(args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arm", choices=("S", "M"))
    parser.add_argument("worker", type=int, choices=range(WORKERS))
    args = parser.parse_args()
    try:
        return cache_partition(JOINT, args.arm, args.worker, FLEET / "codex-sz2-cache-v1",
                               RECIPE, RECIPE_SHA)
    except (ValueError, KeyError, OSError) as exc:
        print(f"cache refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
