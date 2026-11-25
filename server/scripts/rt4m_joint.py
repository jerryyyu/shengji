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


def recipe_inputs(root, recipe_path, *, smoke=False):
    raw = recipe_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != RECIPE_SHA256:
        raise ValueError("RT4 joint recipe SHA mismatch")
    from shengji.train.unified_readout import _run_identity, build_parser

    recipe = json.loads(raw)
    directory = root / ("RT4-M-A-smoke" if smoke else "A") / "train"
    args = joint_args(recipe, ["--scratch-arch", ARCHITECTURE[6]], directory, "mps", None, False)
    expected = dict(recipe, init_readout_ckpt=None, scratch_arch=ARCHITECTURE[6], device="mps")
    if smoke:
        args.extend(["--max-train-rows", "120000", "--report-buffer", "1", "--capacity-stats"])
        expected.update(max_train_rows=120000, report_buffer=1)
    if _run_identity(build_parser().parse_args(args)) != expected:
        raise ValueError("the trainer settings differ from RT4 beyond initialization and device")
    return recipe, args, expected


def command(root, recipe_path, *, smoke=False):
    _, args, _ = recipe_inputs(root, recipe_path, smoke=smoke)
    if smoke:
        if (root / "RT4-M-A-smoke").exists() or (root / "RT4-M-A-smoke").is_symlink():
            raise ValueError("capacity smoke requires a fresh output")
        return [sys.executable, "-B", "-m", "shengji.train.unified_readout", *args]
    directory = root / "A/train"
    if directory.is_symlink() or directory.parent.is_symlink():
        raise ValueError("RT4-M-A output must be inside the reserved root")
    if directory.exists():
        status = (directory / "status.log").read_text().splitlines()
        stopped = re.fullmatch(
            r"\S+ STOPPED at epoch 1 buffer ([0-9]+)/([1-9][0-9]*) \(STOP file or --max-seconds\); checkpoint saved",
            status[-1] if status else "",
        )
        if (not stopped or int(stopped[1]) >= int(stopped[2]) or not (directory / "checkpoint.pt").is_file()
                or (directory / "STOP").exists() or (directory / "STOP").is_symlink()):
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
    parser.add_argument("phase", choices=("RT4-M-A", "RT4-M-A-smoke"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--recipe", type=Path, default=RECIPE)
    args = parser.parse_args(argv)
    try:
        argv = command(args.root.resolve(), args.recipe, smoke=args.phase == "RT4-M-A-smoke")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"invalid RT4-M-A input: {exc}\n")
    print(json.dumps(argv))


if __name__ == "__main__":
    main()
