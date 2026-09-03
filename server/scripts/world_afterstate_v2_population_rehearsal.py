#!/usr/bin/env python3
"""Run one fresh, score-free full-D256 population rehearsal."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


if not sys.flags.safe_path or not sys.dont_write_bytecode:
    raise RuntimeError("Value V2 population rehearsal requires Python -P -B")
if os.environ.get("PYTHONPATH"):
    raise RuntimeError("Value V2 population rehearsal refuses PYTHONPATH")
SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent


def _require_runtime_environment() -> None:
    if (os.environ.get("SHENGJI_FAST") != "1"
            or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1"):
        raise RuntimeError(
            "Value V2 requires SHENGJI_FAST=1 and SHENGJI_REQUIRE_VOIDS=1")


def _preimport_bytecode_scan() -> None:
    """Refuse ignored Python bytecode before importing project modules."""
    for prefix in (SERVER / "scripts", SERVER / "shengji"):
        if not prefix.is_dir() or prefix.is_symlink():
            raise RuntimeError("Value V2 rehearsal source root drift")
        for _current, dirs, files in os.walk(
                prefix, topdown=True, followlinks=False):
            if "__pycache__" in dirs or any(name.endswith(".pyc")
                                              for name in files):
                raise RuntimeError(
                    "Value V2 rehearsal refuses source bytecode artifacts")


if __name__ == "__main__":
    _require_runtime_environment()
    _preimport_bytecode_scan()

if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from shengji.rl.world_afterstate_v2_population_rehearsal import (  # noqa: E402
    PopulationRehearsalError, run_population_rehearsal_v2,
)


def _clean_exact_head(expected_head: str) -> None:
    if (len(expected_head) != 40
            or any(char not in "0123456789abcdef" for char in expected_head)):
        raise PopulationRehearsalError("expected source head drift")
    head = subprocess.run(
        ("git", "-C", str(REPO), "rev-parse", "HEAD"), check=False,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode().strip()
    if head != expected_head:
        raise PopulationRehearsalError("source head drift")
    status = subprocess.run(
        ("git", "-C", str(REPO), "status", "--porcelain=v1",
         "--untracked-files=all"), check=False,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode()
    if status.strip():
        raise PopulationRehearsalError("source tree is dirty")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--capacity", type=Path, required=True)
    value.add_argument("--root", type=Path, required=True)
    value.add_argument("--receipt", type=Path, required=True)
    value.add_argument("--expected-head", required=True)
    value.add_argument("--progress", "--progress-path", dest="progress", type=Path)
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    _clean_exact_head(args.expected_head)
    result = run_population_rehearsal_v2(
        args.capacity, args.root, args.receipt,
        expected_head=args.expected_head, progress=args.progress,
        clean_repo=REPO)
    print(json.dumps(result.payload(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
