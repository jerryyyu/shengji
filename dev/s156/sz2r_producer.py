"""Emit SZ2-R adapter argv for the supervising launcher. Does not execute the command."""
import argparse
import json
from pathlib import Path
import sys


def run_inputs(recipe, mode, lane):
    here = Path(__file__).resolve().parent
    screen = json.loads((here / "sz2r_checkpoint_exposure.json").read_bytes())
    preflight = json.loads((here / "sz2r_preflight_exposure.json").read_bytes())
    for actual, bound in (("arm", "arm"), ("head", "deployment"), ("round_plan", "round_plan"),
                          ("defender_words", "defender"), ("exploiter_words", "challenger"),
                          ("seed0", "seed0"), ("deals", "deals")):
        if recipe[actual] != screen[bound]:
            raise ValueError(f"screen differs from cleared exposure: {actual}")
    arm = recipe["arm"]
    if mode == "screen":
        block, dest = screen, lane / "out" / arm
    else:
        block, dest = preflight[mode], lane / (mode + arm)
    return block["seed0"], block["deals"], dest


def argv(recipe, mode, workers, lane):
    seed0, deals, dest = run_inputs(recipe, mode, lane)
    if workers < 1:
        raise ValueError("expected a positive worker count")
    if mode == "timing" and workers != 1:
        raise ValueError("timing uses one worker")
    args = [sys.executable, "-B", recipe["adapter"], "--arm", "identity",
            "--seed0", str(seed0), "--deals", str(deals),
            "--workers", str(workers), "--round-plan", recipe["round_plan"],
            "--out", str(dest / "duel.jsonl")]
    for side in ("defender", "exploiter"):
        for word in recipe[side + "_words"]:
            args.extend(["--" + side + "-env", word])
    return args


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recipe", type=Path)
    parser.add_argument("mode", choices=("screen", "pilot", "timing"))
    parser.add_argument("--workers", type=int, required=True)
    parser.add_argument("--lane", type=Path, required=True)
    a = parser.parse_args()
    print(json.dumps(argv(json.loads(a.recipe.read_bytes()), a.mode, a.workers, a.lane)))
