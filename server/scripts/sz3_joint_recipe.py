"""Emit a trainer command for the matched scratch control, challenger prefix or capacity smoke."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

from sz2_joint_segment import RECIPE, RECIPE_SHA, joint_args


def command(phase, root, recipe_path):
    raw = recipe_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != RECIPE_SHA:
        raise ValueError("FT-500k recipe SHA mismatch")
    recipe = json.loads(raw)
    smoke = phase == "L-smoke"
    depth = 6 if phase == "M" else 8
    architecture = f"d={48 * depth},heads={depth},enc_layers={depth},xattn_layers={depth},x_hidden=256"
    directory = "L" if phase == "L-prefix" else phase
    args = joint_args(recipe, ["--scratch-arch", architecture], root / directory / "train", "mps",
                      None if smoke else 400, phase == "L-prefix")
    args.extend(["--microbatch-rounds", "4"])
    if smoke:
        args.extend(["--max-train-rows", "120000"])
    return [sys.executable, "-B", "-m", "shengji.train.unified_readout", *args]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("L-smoke", "M", "L-prefix"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--recipe", type=Path, default=RECIPE)
    args = parser.parse_args()
    try:
        argv = command(args.phase, args.root.resolve(), args.recipe)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"invalid recipe: {exc}\n")
    print(json.dumps(argv))


if __name__ == "__main__":
    main()
