#!/usr/bin/env python3
"""Purely rederive the reviewed Value V2 C1 capacity amendment."""

from __future__ import annotations

import os
import sys


if not sys.flags.safe_path or not sys.dont_write_bytecode:
    raise RuntimeError("Value V2 capacity economics requires Python -P -B")
if os.environ.get("PYTHONPATH"):
    raise RuntimeError("Value V2 capacity economics refuses PYTHONPATH")

import argparse  # noqa: E402
import hashlib  # noqa: E402
from pathlib import Path  # noqa: E402
import subprocess  # noqa: E402

SERVER = Path(__file__).resolve().parents[1]
if not sys.path or sys.path[0] != str(SERVER):
    sys.path.insert(0, str(SERVER))

from shengji.rl.belief_contract import canonical_json_bytes  # noqa: E402
from shengji.rl.world_afterstate_v2_capacity_economics import (  # noqa: E402
    ALLOWED_CARRY_FORWARD_PATHS, BASE_SOURCE_GIT, CapacityEconomicsError,
    SourceDiffV2, build_capacity_economics_amendment_v2,
    publish_capacity_economics_amendment_v2,
)
from shengji.rl.world_afterstate_v2_freeze_builder import (  # noqa: E402
    _source_closure,
)

REPO = SERVER.parent


def _git(*args: str, binary: bool = False) -> bytes | str:
    result = subprocess.run(
        ("git", "-C", str(REPO), *args), check=False,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise CapacityEconomicsError("capacity economics Git command refused")
    return result.stdout if binary else result.stdout.decode("utf-8")


def _source_sha256() -> str:
    rows = []
    for path in _source_closure(REPO):
        raw = path.read_bytes()
        rows.append({"path": path.relative_to(REPO).as_posix(),
                     "byte_count": len(raw),
                     "sha256": hashlib.sha256(raw).hexdigest()})
    return hashlib.sha256(canonical_json_bytes({
        "schema": "world-afterstate-v2-capacity-source-v2",
        "files": rows,
    })).hexdigest()


def _source_diff(head: str) -> tuple[SourceDiffV2, ...]:
    text = _git("diff", "--name-status", "--no-renames",
                BASE_SOURCE_GIT, head, "--")
    rows = []
    for line in text.splitlines():
        try:
            status, relative = line.split("\t", 1)
        except ValueError as exc:
            raise CapacityEconomicsError(
                "carry-forward Git diff parse drift") from exc
        if status not in ("A", "M") or relative not in ALLOWED_CARRY_FORWARD_PATHS:
            raise CapacityEconomicsError("carry-forward Git diff is not allowlisted")
        current = (REPO / relative).read_bytes()
        base_sha = None
        if status == "M":
            base = _git("show", f"{BASE_SOURCE_GIT}:{relative}", binary=True)
            assert isinstance(base, bytes)
            base_sha = hashlib.sha256(base).hexdigest()
        rows.append(SourceDiffV2(
            path=relative, status=status, base_sha256=base_sha,
            current_sha256=hashlib.sha256(current).hexdigest()))
    result = tuple(sorted(rows, key=lambda row: row.path))
    if not result:
        raise CapacityEconomicsError("carry-forward Git diff is empty")
    return result


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--base-failure", type=Path, required=True)
    value.add_argument("--expected-head", required=True)
    value.add_argument("--out", type=Path, required=True)
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if (len(args.expected_head) != 40
            or any(char not in "0123456789abcdef"
                   for char in args.expected_head)):
        raise CapacityEconomicsError("capacity economics expected head drift")
    if _git("rev-parse", "HEAD").strip() != args.expected_head:
        raise CapacityEconomicsError("capacity economics source head drift")
    if _git("status", "--porcelain=v1", "--untracked-files=all").strip():
        raise CapacityEconomicsError("capacity economics source tree is dirty")
    if subprocess.run(("git", "-C", str(REPO), "merge-base", "--is-ancestor",
                       BASE_SOURCE_GIT, args.expected_head), check=False).returncode:
        raise CapacityEconomicsError("capacity economics source ancestry drift")
    receipt = build_capacity_economics_amendment_v2(
        base_failure_raw=args.base_failure.read_bytes(),
        execution_git=args.expected_head, source_sha256=_source_sha256(),
        source_diff=_source_diff(args.expected_head))
    publish_capacity_economics_amendment_v2(args.out, receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
