"""Measure one pre-admitted S151 invocation under lane_supervise, or print its command."""
import argparse
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time
from tempfile import NamedTemporaryFile

from shengji import seeds

from compare_crossover import HEADS, SEEDS, block_order
from compare_generator import read, require

LANE = "s151-generator-crossover"
HOST = "Jerrys-Mac-Studio.local"
FLEET = Path("/Users/jeryyu/fleet")
ORDER = [key for block in range(len(SEEDS)) for key in block_order(block)]


def command(tree, models, dest, seed):
    return [sys.executable, "-B", str(tree / "server/scripts/y_trajectory.py"),
            "--fly", str(tree / "fly.toml"), "--models", str(models),
            "--seed-registry", str(dest / "seed_windows.json"), "--seed", str(seed),
            "--workers", "26", "--rounds", "208", "--cap", "256", "--out", str(dest / "store")]


def publish(path, value):
    with NamedTemporaryFile(mode="w", dir=path.parent, prefix=path.name + ".", delete=False) as out:
        tmp = Path(out.name)
        json.dump(value, out, allow_nan=False)
        out.flush()
        os.fsync(out.fileno())
    os.link(tmp, path)
    tmp.unlink()


def require_supervisor():
    require(platform.node() == HOST, "capture requires the Ultra")
    owner = (FLEET / ".claude-host.lock/owner").read_text().split()
    require(len(owner) == 3 and owner[:2] == [str(os.getppid()), LANE]
            and os.environ.get("LANE_ARMED_ID") and os.getpgrp() == os.getpid(),
            "capture requires the armed lane_supervise process group under its owning launcher")


def measure(cmd, tree, dest):
    with (dest / "generator.log").open("x") as log:
        start = time.monotonic()
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        subprocess.run(cmd, cwd=tree / "server", stdout=log, stderr=subprocess.STDOUT,
                       env={k: os.environ[k] for k in ("HOME", "PATH", "TMPDIR") if k in os.environ},
                       check=True)
        wall = time.monotonic() - start
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
    return wall, after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime


def prior_timings(root, count):
    prior = []
    for i, key in enumerate(ORDER[:count]):
        receipt = read(root / f"{key[0]}-{key[1]}" / "capture.json")
        require(receipt["index"] == i and receipt["timing"][:2] == list(key)
                and receipt["head"] == HEADS["bc".index(key[1])], "wrong prior capture")
        prior.append(receipt["timing"])
    return prior


def assemble(root):
    rows = prior_timings(root, len(ORDER))
    path = root / "timings.json"
    if path.exists():
        require(read(path) == rows, "existing timings differ from the captures")
    else:
        publish(path, rows)


def capture(args):
    pair, arm = ORDER[args.index]
    tree = (args.base if arm == "b" else args.candidate).resolve()
    root = args.root.resolve()
    dest = root / f"{pair}-{arm}"
    cmd = command(tree, args.models.resolve(), dest, SEEDS[pair // 2])
    if args.print_command:
        print(json.dumps(cmd))
        return
    require_supervisor()
    head = HEADS["bc".index(arm)]
    sha = subprocess.check_output(["git", "-C", tree, "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", tree, "status", "--porcelain"], text=True)
    require(sha == head and not dirty, f"{tree}: expected a clean checkout at {head}")
    prior_timings(root, args.index)
    dest.mkdir()
    require(args.registry.is_file(), f"missing registry: {args.registry}")
    publish(dest / "seed_windows.json", seeds.load(args.registry))
    wall, cpu = measure(cmd, tree, dest)
    runtime = read(dest / "store/runtime.json")
    run = read(dest / "store/run.json")
    require(run["identity"]["git_sha"] == head and run["config"]["seed0"] == SEEDS[pair // 2]
            and runtime["workers"] == 26 and runtime["clusters"] == dict(
                requested=104, generated=list(range(104)), failed=[], reused=[]),
            f"{dest}: incomplete or unexpected workload")
    inner = runtime["wall_secs"]
    require(0 < inner <= wall and cpu > 0, "invalid measured duration")
    row = [pair, arm, wall, cpu, inner]
    publish(dest / "capture.json", dict(index=args.index, head=head, command=cmd, timing=row))
    if args.index == len(ORDER) - 1:
        assemble(root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    collect = sub.add_parser("assemble")
    collect.add_argument("--root", type=Path, required=True)
    run = sub.add_parser("capture")
    run.add_argument("index", type=int, choices=range(len(ORDER)))
    for option in ("root", "base", "candidate", "models", "registry"):
        run.add_argument("--" + option, required=True, type=Path)
    run.add_argument("--print-command", action="store_true")
    args = parser.parse_args()
    if args.action == "assemble":
        assemble(args.root)
    else:
        capture(args)
