"""Polish one completed, densely populated SZ2 CPU cache under its host supervisor."""
import argparse
from contextlib import ExitStack
import fcntl
import json
import os
import re
import sys
from zipfile import ZipFile

from sz2_cache_arm import FLEET, JOINT, RECIPE, RECIPE_SHA, WORKERS, arm_inputs


def polish_arm(joint, arm, cache_root, output, recipe_path, recipe_sha):
    from shengji.train import unified_readout

    checkpoint, cache, recipe = arm_inputs(joint, arm, cache_root, recipe_path, recipe_sha)
    with ExitStack() as leases:
        for worker in range(WORKERS):
            lock = leases.enter_context((cache / f"worker-{worker}.lock").open("rb"))
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if json.loads((cache / unified_readout.CACHE_DEVICE).read_text()) != {"device": "cpu"}:
            raise ValueError("expected a CPU cache")
        records = [json.loads((cache / f"DONE.{i}").read_text()) for i in range(WORKERS)]
        groups, chunks = records[0]["groups"], records[0]["chunks"]
        if (type(chunks) is not int or chunks <= 0 or type(groups) is not int
                or groups != (chunks + 23) // 24 or any(r != records[0] for r in records)
                or records[0]["corpus_weight"] != recipe["corpus_weight"]):
            raise ValueError("inconsistent cache partition totals or weights")
        expected = {f"train-{i:04d}.npz" for i in range(groups)}
        if expected != {p.name for p in cache.glob("train-*.npz")} or not (cache / "calib-0000.npz").is_file():
            raise ValueError("incomplete dense cache")
        for name in sorted(expected):
            with ZipFile(cache / name) as shard:
                if "leaf_w.npy" not in shard.namelist():
                    raise ValueError(f"missing corpus weights in {name}")
        out = output / arm / cache.name
        out.mkdir(parents=True, exist_ok=False)
        rc = unified_readout.main(["polish", "--ckpt", str(checkpoint), "--cache", str(cache),
                                   "--out", str(out), "--epochs", "2", "--lr", "3e-4",
                                   "--weight-decay", "0.01", "--reply-weight", "0.2", "--batch", "4096",
                                   "--threads", "16", "--seed", "1", "--device", "cpu"])
        if rc:
            return rc
        terminal = (out / "status.log").read_text().splitlines()[-1]
        result = re.fullmatch(r"\S+ POLISH DONE best_epoch=([012]) calib .+ sha256=[0-9a-f]{64}", terminal)
        if not result:
            raise ValueError("missing polish selection")
        # The joint checkpoint is the selected model when neither pass improved it.
        os.link(checkpoint if result[1] == "0" else out / "best.pt", out / "selected.pt")
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arm", choices=("S", "M"))
    try:
        sys.exit(polish_arm(JOINT, parser.parse_args().arm, FLEET / "codex-sz2-cache-v1",
                            FLEET / "codex-sz2-polish-v1", RECIPE, RECIPE_SHA))
    except (ValueError, KeyError, OSError) as exc:
        sys.exit(f"polish refused: {exc}")
