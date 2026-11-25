"""Build the full-mix medium scratch joint-training command for the admitted worker."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

from sz2_joint_segment import joint_args
from sz3_joint_recipe import ARCHITECTURE

RECIPE = Path.home() / "fleet/claude-ut-retrain4/cand/train/run.json"
RECIPE_SHA256 = "d7778348cce3aead7f991c1683577af3f9760bab795ef4d548b721ea8bfacb48"


SMOKE = "RT4-M-A-smoke"
MICROBATCH_SMOKE = "RT4-M-A-micro4-smoke"


def recipe_inputs(root, recipe_path, *, phase="RT4-M-A"):
    if phase not in ("RT4-M-A", SMOKE, MICROBATCH_SMOKE):
        raise ValueError("unknown RT4-M phase")
    smoke = phase != "RT4-M-A"
    raw = recipe_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != RECIPE_SHA256:
        raise ValueError("RT4 joint recipe SHA mismatch")
    from shengji.train.unified_readout import _run_identity, build_parser

    recipe = json.loads(raw)
    directory = root / (phase if smoke else "A") / "train"
    args = joint_args(recipe, ["--scratch-arch", ARCHITECTURE[6]], directory, "mps", None, False)
    expected = dict(recipe, init_readout_ckpt=None, scratch_arch=ARCHITECTURE[6], device="mps")
    if smoke:
        args.extend(["--max-train-rows", "120000", "--report-buffer", "1", "--capacity-stats"])
        expected.update(max_train_rows=120000, report_buffer=1)
    if phase == MICROBATCH_SMOKE:
        args.extend(["--microbatch-rounds", "4"])
        expected["microbatch_rounds"] = 4
    if _run_identity(build_parser().parse_args(args)) != expected:
        raise ValueError("the trainer settings differ from RT4 beyond initialization and device")
    return recipe, args, expected


def command(root, recipe_path, *, phase="RT4-M-A", recover_checkpoint_sha256=None):
    _, args, expected = recipe_inputs(root, recipe_path, phase=phase)
    if recover_checkpoint_sha256 is not None and (phase != "RT4-M-A"
            or not re.fullmatch("[0-9a-f]{64}", recover_checkpoint_sha256)):
        raise ValueError("checkpoint recovery requires full Arm A and a SHA256")
    if phase != "RT4-M-A":
        if (root / phase).exists() or (root / phase).is_symlink():
            raise ValueError("capacity smoke requires a fresh output")
        return [sys.executable, "-B", "-m", "shengji.train.unified_readout", *args]
    directory = root / "A/train"
    if directory.is_symlink() or directory.parent.is_symlink():
        raise ValueError("RT4-M-A output must be inside the reserved root")
    if recover_checkpoint_sha256 is not None or directory.exists():
        checkpoint = directory / "checkpoint.pt"
        status_path = directory / "status.log"
        if (checkpoint.is_symlink() or not checkpoint.is_file() or status_path.is_symlink()
                or (directory / "STOP").exists() or (directory / "STOP").is_symlink()):
            raise ValueError("RT4-M-A requires a local checkpoint and a cleared STOP")
        status = status_path.read_text().splitlines()
        terminal = status[-1] if status else ""
        if recover_checkpoint_sha256 is not None:
            if not re.fullmatch(r"\S+ UTR ABORT \w+: .*", terminal) or any(" UTR DONE " in line for line in status):
                raise ValueError("checkpoint recovery requires a terminal trainer ABORT")
            if json.loads((directory / "run.json").read_bytes()) != expected:
                raise ValueError("aborted run settings differ from RT4-M-A")
            with checkpoint.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != recover_checkpoint_sha256:
                    raise ValueError("aborted checkpoint SHA256 mismatch")
            args.extend(["--recover-checkpoint-sha256", recover_checkpoint_sha256])
        else:
            stopped = re.fullmatch(
                r"\S+ STOPPED at epoch 1 buffer ([0-9]+)/([1-9][0-9]*) \(STOP file or --max-seconds\); checkpoint saved",
                terminal,
            )
            if not stopped or int(stopped[1]) >= int(stopped[2]):
                raise ValueError("RT4-M-A requires a fresh output or a clean checkpointed stop")
            args.extend(["--expect-resume-buffer", stopped[1]])
    return [sys.executable, "-B", "-m", "shengji.train.unified_readout", *args]


def verify_completion(root):
    directory = root / "A/train"
    status = (directory / "status.log").read_text().splitlines()
    best = directory / "best.pt"
    terminal = rf"\S+ UTR DONE best={re.escape(str(best))} sha256=([0-9a-f]{{64}})"
    match = re.fullmatch(terminal, status[-1]) if status else None
    if not match:
        raise ValueError("RT4-M-A lacks its successful trainer terminal")
    for checkpoint in (best, directory / "checkpoint.pt"):
        if not checkpoint.is_file() or checkpoint.stat().st_size == 0:
            raise ValueError(f"RT4-M-A missing checkpoint: {checkpoint}")
    return best, match[1]


def completed_inputs(root, recipe_path):
    recipe, _, expected = recipe_inputs(root, recipe_path)
    checkpoint, digest = verify_completion(root)
    if json.loads((checkpoint.parent / "run.json").read_bytes()) != expected:
        raise ValueError("RT4-M-A completed with different trainer settings")
    with checkpoint.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
            raise ValueError("RT4-M-A best checkpoint differs from the trainer terminal")
    return checkpoint, digest, recipe


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("RT4-M-A", SMOKE, MICROBATCH_SMOKE))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--recipe", type=Path, default=RECIPE)
    parser.add_argument("--recover-checkpoint-sha256")
    args = parser.parse_args(argv)
    try:
        argv = command(args.root.resolve(), args.recipe, phase=args.phase, recover_checkpoint_sha256=args.recover_checkpoint_sha256)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"invalid RT4-M-A input: {exc}\n")
    print(json.dumps(argv))


if __name__ == "__main__":
    main()
