#!/usr/bin/env python3
"""Publish one reviewed train-only Value V1 P0/capacity packet."""

from __future__ import annotations

import sys


if not sys.flags.safe_path or not sys.dont_write_bytecode:
    raise RuntimeError("Value V1 capacity requires Python -P -B")

import argparse
import os
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent


def _refuse_import_shadows() -> None:
    if os.environ.get("PYTHONPATH"):
        raise RuntimeError("Value V1 capacity refuses PYTHONPATH")
    try:
        tracked_raw = subprocess.run(
            ("git", "ls-files", "-z"), cwd=REPO, check=True,
            capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("Value V1 capacity bootstrap Git probe failed") \
            from exc
    tracked = {value.decode("utf-8") for value in tracked_raw.split(b"\0")
               if value}
    loadable = {".py", ".pyc", ".pyo", ".so", ".pyd", ".dylib"}
    candidates = set()
    for root in (SERVER / "shengji", SERVER / "scripts"):
        candidates.update(path for path in root.rglob("*")
                          if path.is_file() and path.suffix in loadable)
    natives = []
    for path in sorted(candidates):
        relative = path.relative_to(REPO).as_posix()
        if path.suffix in {".pyc", ".pyo"}:
            raise RuntimeError("Value V1 capacity refuses bytecode shadows")
        if path.suffix in {".so", ".pyd", ".dylib"} \
                and path.parent == SERVER / "shengji" / "engine" \
                and path.name.startswith("_fast."):
            natives.append(path)
            continue
        if relative not in tracked:
            raise RuntimeError(
                "Value V1 capacity refuses untracked import shadows")
    if len(natives) != 1:
        raise RuntimeError("Value V1 capacity native population drift")


_refuse_import_shadows()
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from shengji.rl.world_afterstate_v1_capacity import (  # noqa: E402
    publish_capacity_build, reopen_capacity_directory, run_capacity)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--expected-git", required=True)
    value.add_argument("--population", type=Path, required=True)
    value.add_argument("--dataset-manifest", type=Path, required=True)
    value.add_argument("--freeze", type=Path, required=True)
    value.add_argument("--row-root", type=Path, required=True)
    value.add_argument("--output", type=Path, required=True)
    return value


def main() -> None:
    args = parser().parse_args()
    last: dict[str, int | str] = {"stage": "", "basis": -1}

    def progress(value):
        stage = value["stage"]
        basis = value["percent_basis_points"]
        if stage != last["stage"] or basis == 10_000 \
                or basis >= int(last["basis"]) + 500:
            detail = " ".join(
                f"{key}={item}" for key, item in sorted(value.items())
                if key not in {
                    "stage", "completed", "total",
                    "percent_basis_points"})
            suffix = f" {detail}" if detail else ""
            print(
                f"{stage}: {basis / 100:.2f}% "
                f"({value['completed']}/{value['total']}){suffix}",
                flush=True)
            last["stage"] = stage
            last["basis"] = basis

    build = run_capacity(
        repo=REPO, expected_git=args.expected_git,
        population_path=args.population,
        dataset_manifest_path=args.dataset_manifest,
        freeze_path=args.freeze, row_root=args.row_root,
        progress=progress)
    publish_capacity_build(args.output, build)
    reopened = reopen_capacity_directory(args.output)
    if reopened != build:
        raise RuntimeError("Value V1 capacity independent reopen drift")
    print(
        "VALUE_V1_CAPACITY_COMPLETE "
        f"receipt_sha256={build.receipt['receipt_sha256']} "
        f"row_workers={build.receipt['selection']['row_workers']} "
        f"member_workers={build.receipt['selection']['member_workers']} "
        f"torch_threads={build.receipt['selection']['torch_threads']}",
        flush=True)


if __name__ == "__main__":
    main()
