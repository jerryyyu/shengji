"""Score the saved confirmation read against the sealed C arm using the pinned RT3FS stage-2 rule."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


STAGE_SHA = "adabc4bd7eb07c4c9fb35e06542019fb1a0c36c71cf19c83538aca3b30e816f3"
DEALS = 7840


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def validate(recipe_bytes, recipe_sha, result):
    require(sha(recipe_bytes) == recipe_sha, "recipe digest")
    recipe = json.loads(recipe_bytes)
    arm = recipe["arms"]["C"]
    require(recipe["schema"] == "rt3fs-recipe-r1" and recipe["duel"] == "RT3FS"
            and arm["deals"] == DEALS, "confirmation recipe")
    require(result["schema"] == "rt3fs-read-r1" and result["duel"] == "RT3FS"
            and result["arm"] == "C", "expected a C-arm read")
    require(result["reader_sha256"] == recipe["reader_sha256"], "reader identity")
    binding = result["binding"]
    require(binding["recipe_sha256"] == recipe_sha and
            binding["predeclare_sha256"] == recipe["predeclare_sha256"], "read binding")
    for side, prefix in (("exploiter", "ex"), ("defender", "def")):
        require(result[side] == {"name": arm[f"{side}_name"],
                                 "package_sha256": arm[f"{prefix}_package_sha256"],
                                 "belief_sha256": arm[f"{prefix}_belief_sha256"]}, f"{side} identity")
    require(result["outcome"]["levels"]["n"] == DEALS, "expected 7840 paired deals")
    root = Path(arm["out_root"])
    sums = (root / "SHA256SUMS").read_bytes()
    require(binding["sums_sha256"] == sha(sums), "seal digest")
    entries = [line.split("  ", 1) for line in sums.decode().splitlines()]
    hashes = {name: digest for digest, name in entries}
    require(len(hashes) == len(entries) and hashes["./duel.jsonl"] == binding["duel_jsonl_sha256"],
            "sealed duel digest")
    manifest = (root / "manifest.json").read_bytes()
    require(sha(manifest) == hashes["./manifest.json"] and json.loads(manifest) == {
        "schema": "utd-manifest-r1", "mode": "C", "arm": "C", "recipe_sha256": recipe_sha,
        "seed0": arm["seed0"], "deals": DEALS, "tree_head": recipe["tree_head"], "rc": 0,
    }, "sealed confirmation manifest")
    lines = Path(arm["status"]).read_text().strip().splitlines()
    terminal = binding["terminal"]
    require(len(lines) >= 2 and lines[-1].startswith("UTD UNLOCKED ") and lines[-2] == terminal
            and re.fullmatch(rf"UTD DONE \S+ recipe={recipe_sha} rows={2 * DEALS} sums={sha(sums)} rc=0",
                             terminal), "confirmation terminal")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lane", type=Path)
    parser.add_argument("recipe_sha")
    args = parser.parse_args()
    readout = args.lane / "readout"
    stage = args.lane / "stage2.py"
    try:
        require((readout / "C.read.rc").read_text().strip() == "0", "reader return code")
        data = (readout / "C.read.json").read_bytes()
        validate((args.lane / "recipe.json").read_bytes(), args.recipe_sha, json.loads(data))
        require(sha(stage.read_bytes()) == STAGE_SHA, "stage-2 implementation")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"STAGE2 NOREAD {exc}")
        return 3
    return subprocess.run([sys.executable, "-I", "-B", str(stage), "/dev/stdin"], input=data).returncode


if __name__ == "__main__":
    sys.exit(main())
