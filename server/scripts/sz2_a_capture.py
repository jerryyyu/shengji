"""Reserve and seal the SZ2-A adapter output under the supervising launcher's lock."""
import argparse
import hashlib
import json
import re
from pathlib import Path
from datetime import datetime, timezone

from sz2_a_recipe import LANE
from sz2_duel_decision import ARM, DEALS, SEED0, TIMESTAMP, _pinned_json


OUTPUTS = ("duel.jsonl", "duel.jsonl.resume.json", "duel.time", "run.log")


def event(kind, detail):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"UTD {kind} {now} {detail}\n"


def destination(recipe, lane):
    arm = recipe["arms"][ARM]
    root, status = lane / "out" / ARM, lane / f"{ARM}.status"
    if (set(recipe["arms"]) != {ARM} or (arm["seed0"], arm["deals"]) != (SEED0, DEALS)
            or arm["out_root"] != str(root) or arm["status"] != str(status)):
        raise ValueError("unexpected SZ2-A reservation")
    if any(path.is_symlink() for path in (lane, root.parent, root, status)):
        raise ValueError("symlinked SZ2-A reservation")
    return root, status


def reserve(recipe, digest, lane, pid, workers):
    root, status = destination(recipe, lane)
    if pid <= 0 or workers <= 0 or root.exists() or status.exists():
        raise ValueError("invalid or occupied SZ2-A reservation")
    root.parent.mkdir(exist_ok=True)
    with status.open("x") as stream:
        root.mkdir()
        stream.write(event("START", f"mode={ARM} arm={ARM} pid={pid} seed0={SEED0} "
                                    f"deals={DEALS} workers={workers} recipe={digest}"))


def seal(recipe, digest, lane, producer_rc):
    root, status = destination(recipe, lane)
    if producer_rc != 0:
        raise ValueError(f"duel producer exited {producer_rc}")
    lines = status.read_text().splitlines()
    expected = (
        rf"UTD START {TIMESTAMP} mode={ARM} arm={ARM} pid=[1-9]\d* seed0={SEED0} deals={DEALS} "
        rf"workers=[1-9]\d* recipe={digest}",
        rf"UTD LOCKED {TIMESTAMP} after \d+s.*",
        rf"UTD NAMES {TIMESTAMP} ok",
        rf"UTD PRODUCER {TIMESTAMP} .+",
    )
    if len(lines) != len(expected) or any(not re.fullmatch(form, line) for form, line in zip(expected, lines)):
        raise ValueError("capture has no matching active producer")
    if {p.name for p in root.iterdir()} != set(OUTPUTS):
        raise ValueError("incomplete or unexpected producer outputs")

    sums = []
    for name in OUTPUTS:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"invalid producer output: {name}")
        with path.open("rb") as stream:
            if name == "duel.jsonl":
                h = hashlib.sha256()
                rows = 0
                last = b""
                while block := stream.read(1 << 20):
                    h.update(block)
                    rows += block.count(b"\n")
                    last = block[-1:]
                if rows != 2 * DEALS or last != b"\n":
                    raise ValueError("incomplete mirror rows")
            else:
                h = hashlib.file_digest(stream, "sha256")
        sums.append(f"{h.hexdigest()}  ./{name}\n")
    manifest = dict(schema="utd-manifest-r1", mode=ARM, arm=ARM, recipe_sha256=digest,
                    seed0=SEED0, deals=DEALS, tree_head=recipe["tree_head"], rc=0)
    data = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    with (root / "manifest.json").open("xb") as out:
        out.write(data)
    sums.append(f"{hashlib.sha256(data).hexdigest()}  ./manifest.json\n")
    data = "".join(sums).encode()
    with (root / "SHA256SUMS").open("xb") as out:
        out.write(data)
    with status.open("a") as out:
        out.write(event("DONE", f"recipe={digest} rows={2 * DEALS} "
                                f"sums={hashlib.sha256(data).hexdigest()} rc=0"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--recipe-sha256", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("reserve")
    start.add_argument("--supervisor-pid", type=int, required=True)
    start.add_argument("--workers", type=int, required=True)
    finish = commands.add_parser("seal")
    finish.add_argument("--producer-rc", type=int, required=True)
    args = parser.parse_args()
    recipe = _pinned_json(args.recipe, args.recipe_sha256, "recipe")
    if args.command == "reserve":
        reserve(recipe, args.recipe_sha256, LANE, args.supervisor_pid, args.workers)
    else:
        seal(recipe, args.recipe_sha256, LANE, args.producer_rc)


if __name__ == "__main__":
    main()
