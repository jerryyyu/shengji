"""Prepare one SZ2 joint-training segment for the host supervisor. Emit argv only after checking its prerequisites."""
import argparse
import contextlib
import hashlib
import json
import re
import subprocess
from pathlib import Path
import sys

import sz2_offline_gate as gate

FLEET = Path.home() / "fleet"
RECIPE = FLEET / "claude-ft500/cand/train/run.json"
RECIPE_SHA = "69f181a3a9e838e32c9cbc9b695e7629479ca056e06274d9246abdfbbb139369"
START_SHA = {
    "S": "f16c7d304159e4d1cb2ebae966aace23ef5798e9588da39e1bc615e805672805",
    "M": "39562cd2e3761ac73edcb006f0fc04a81f5419d1fb77db886be9d2a910a6210e",
}

INIT_BELIEF_LL = {"S": 1.034334683253056, "M": 1.0289371977741781}


def predecessor_done(run):
    status = (run / "status.txt").read_text().splitlines()
    if not status or not re.fullmatch(r"\S+ RUN DONE 64 seeds rc 0", status[-1]):
        return False
    if not re.fullmatch(r"\d+ done 64/64 live \[\]\s*", (run / "heartbeat").read_text()):
        return False
    processes = subprocess.run(["ps", "-axo", "command="], check=True, text=True, capture_output=True)
    if not processes.stdout.strip():
        raise ValueError("empty process inventory")
    return not any(str(run) in line and any(name in line for name in ("run_ultra.py", "s157a.py"))
                   for line in processes.stdout.splitlines())


def train_args(recipe, init, out, device, boundary, pause):
    threads = "4" if device == "mps" else "16"
    args = ["train", "--out", str(out), "--init-readout-ckpt", str(init), "--device", device,
            "--threads", threads, "--loader-threads", "4",
            "--max-seconds", "5400", "--data", *recipe["data"], "--calib-data", *recipe["calib_data"]]
    for key in ("epochs", "lr", "head_lr", "readout_lr", "head_warmup_buffers", "weight_decay",
                "belief_weight", "q_weight", "policy_weight", "value_weight", "reply_weight",
                "seed", "buffer_chunks", "rounds_per_batch", "calib_rows"):
        args.extend(["--" + key.replace("_", "-"), str(recipe[key])])
    for key in ("store_map", "corpus_weight"):
        for value in recipe[key]:
            args.extend(["--" + key.replace("_", "-"), value])
    for start, end in recipe["exclude_seed_window"]:
        args.extend(["--exclude-seed-window", f"{start}:{end}"])
    if boundary is not None:
        args.extend(["--report-buffer", str(boundary)])
    if pause:
        args.append("--pause-at-report")
    return args


def prepare(phase, root, fleet, recipe, hashes, boundary, init_belief_ll):
    arm = "S" if phase == "small" else "M"
    out = root / ("smoke" if phase == "smoke" else arm) / "train"
    if (out / "STOP").exists():
        raise ValueError(f"{out}: operator STOP present")
    init = fleet / "claude-ut-size" / "arm" / arm / "polish/best.pt"
    with init.open("rb") as f:
        if hashlib.file_digest(f, "sha256").hexdigest() != hashes[arm]:
            raise ValueError(f"{arm}: warm-start SHA mismatch")
    if phase == "medium-prefix":
        if not (root / "S/train/best.pt").is_file():
            raise ValueError("small control has not completed")
        gate.load_arm(root / "S/train", hashes["S"], boundary)
    if phase == "medium-finish":
        if not (out / "checkpoint.pt").is_file():
            raise ValueError("missing medium resume checkpoint")
        with contextlib.redirect_stdout(sys.stderr):
            rc = gate.main(["--small", str(root / "S/train"), "--medium", str(out),
                            "--small-init-sha", hashes["S"], "--medium-init-sha", hashes["M"],
                            "--buffer", str(boundary)])
        if rc:
            return (8 if rc == 3 else rc), None
    args = train_args(recipe, init, out, "cpu" if arm == "S" else "mps", None if phase == "smoke" else boundary,
                      phase == "medium-prefix")
    args.extend(["--microbatch-rounds", "4"])
    if phase == "smoke":
        args.extend(["--max-train-rows", "120000"])
    args.extend(["--expect-init-belief-ll", str(init_belief_ll)])
    return 0, [sys.executable, "-B", "-m", "shengji.train.unified_readout", *args]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("phase", choices=("smoke", "small", "medium-prefix", "medium-finish"))
    p.add_argument("--root", type=Path, required=True, help="reserved SZ2 output root")
    args = p.parse_args(argv)
    try:
        if not predecessor_done(FLEET / "s157-stepA-ultra"):
            print("WAIT: S157 has not finished and drained", file=sys.stderr)
            return 5
        raw = RECIPE.read_bytes()
        if hashlib.sha256(raw).hexdigest() != RECIPE_SHA:
            raise ValueError("FT-500k recipe SHA mismatch")
        rc, command = prepare(args.phase, args.root.resolve(), FLEET, json.loads(raw), START_SHA, 400,
                              INIT_BELIEF_LL["S" if args.phase == "small" else "M"])
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2
    if command is not None:
        print(json.dumps(command))
    return rc


if __name__ == "__main__":
    sys.exit(main())
