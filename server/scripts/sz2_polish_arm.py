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
    checkpoint, cache, recipe = arm_inputs(joint, arm, cache_root, recipe_path, recipe_sha)
    return polish_checkpoint(checkpoint, cache, recipe, output / arm / cache.name, epochs=2, lr=3e-4)


def polish_checkpoint(checkpoint, cache, recipe, out, *, epochs, lr, expected_sample=None, expected_encode_rounds=None,
                      finish_selection=False, device="cpu"):
    from shengji.train import unified_readout

    with ExitStack() as leases:
        for worker in range(WORKERS):
            lock = leases.enter_context((cache / f"worker-{worker}.lock").open("rb"))
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        argv = ["polish", "--ckpt", str(checkpoint), "--cache", str(cache),
                "--out", str(out), "--epochs", str(epochs), "--lr", str(lr),
                "--weight-decay", "0.01", "--reply-weight", "0.2", "--batch", "4096",
                "--threads", "16", "--seed", "1", "--device", device]
        if finish_selection:
            return finish_polish_selection(out, checkpoint, argv, epochs)
        if json.loads((cache / unified_readout.CACHE_DEVICE).read_text()) != {"device": "cpu"}:
            raise ValueError("expected a CPU cache")
        if expected_encode_rounds is not None:
            binding = json.loads((cache / unified_readout.CACHE_ENCODE).read_text())
            if binding.get("rounds_per_batch") != expected_encode_rounds:
                raise ValueError("cache encoder batch size differs from the requested polish input")
        records = [json.loads((cache / f"DONE.{i}").read_text()) for i in range(WORKERS)]
        groups, chunks = records[0]["groups"], records[0]["chunks"]
        if (type(chunks) is not int or chunks <= 0 or type(groups) is not int
                or groups != (chunks + 23) // 24 or any(r != records[0] for r in records)
                or records[0]["corpus_weight"] != recipe["corpus_weight"]):
            raise ValueError("inconsistent cache partition totals or weights")
        if expected_sample is not None and (
                records[0].get("sample") != expected_sample or chunks != expected_sample["chunks"]):
            raise ValueError("cache does not match the expected sampled training set")
        expected = {f"train-{i:04d}.npz" for i in range(groups)}
        if expected != {p.name for p in cache.glob("train-*.npz")} or not (cache / "calib-0000.npz").is_file():
            raise ValueError("incomplete dense cache")
        for name in sorted(expected):
            with ZipFile(cache / name) as shard:
                if "leaf_w.npy" not in shard.namelist():
                    raise ValueError(f"missing corpus weights in {name}")
        out.mkdir(parents=True, exist_ok=False)
        rc = unified_readout.main(argv)
        if rc:
            return rc
        terminal = (out / "status.log").read_text().splitlines()[-1]
        result = re.fullmatch(r"\S+ POLISH DONE best_epoch=([0-9]+) calib .+ sha256=[0-9a-f]{64}", terminal)
        if not result or int(result[1]) > epochs:
            raise ValueError("missing polish selection")
        # The joint checkpoint is the selected model when no polish epoch improved it.
        os.link(checkpoint if result[1] == "0" else out / "best.pt", out / "selected.pt")
        return 0


def finish_polish_selection(out, checkpoint, argv, epochs):
    from shengji.train import unified_readout
    from sz2_export_arm import file_sha

    status = (out / "status.log").read_text().splitlines()
    done = re.fullmatch(r"\S+ POLISH DONE best_epoch=([0-9]+) calib .+ sha256=([0-9a-f]{64})",
                        status[-1]) if status else None
    if not done or int(done[1]) > epochs or (out / "STOP").exists():
        raise ValueError("expected a completed polish before selection recovery")
    digest = file_sha(checkpoint)
    starts = [line for line in status if " POLISH START " in line]
    if len(starts) != 1 or f" ckpt={digest} " not in starts[0]:
        raise ValueError("polish started from a different joint checkpoint")
    best = out / "best.pt"
    if best.is_symlink() or file_sha(best) != done[2]:
        raise ValueError("best checkpoint differs from the polish terminal")
    _, saved = unified_readout.load_checkpoint(best)
    settings = vars(unified_readout.build_parser().parse_args(argv))
    if settings["device"] == "cpu":
        del settings["device"]  # CPU polish omits its default device from saved settings.
    epoch = int(done[1])
    if saved["run"]["polish"] != settings or saved["calib"]["polish_epoch"] != epoch:
        raise ValueError("completed polish settings or winning epoch differ")
    winner = best if epoch else checkpoint
    os.link(winner, out / "selected.pt")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arm", choices=("S", "M"))
    try:
        sys.exit(polish_arm(JOINT, parser.parse_args().arm, FLEET / "codex-sz2-cache-v1",
                            FLEET / "codex-sz2-polish-v1", RECIPE, RECIPE_SHA))
    except (ValueError, KeyError, OSError) as exc:
        sys.exit(f"polish refused: {exc}")
