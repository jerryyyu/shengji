#!/usr/bin/env python3
"""Outcome-blind readiness check for the frozen Teacher-v3 Stage-B gate.

This helper never imports the teacher evaluator and never parses a gold JSON
artifact.  It answers only whether the already-running detached creators have
reached the exact publication boundary predeclared in ``HANDOFF_ACTIVE.md``.
It creates no file and grants no PASS/audit authority; a ready result permits
one invocation of the separately frozen producer gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


READINESS_SCHEMA = "teacher-v3-stage-b-outcome-blind-readiness-v1"
PRODUCER_GIT = "1a2a71333ea283784b19855e67e1ae231379ec79"
NAMESPACE = "runs/logs/teacher-v1-entry-149m-v3"
SHARD_COUNT = 8
RECORDS_PER_SHARD = 16
ORIGINAL_PIDS = tuple(range(73123, 73131))


@dataclass(frozen=True)
class ReadinessContract:
    producer_git: str
    namespace: str
    shard_count: int
    records_per_shard: int
    original_pids: tuple[int, ...]
    source_sha256s: tuple[tuple[str, str], ...]
    parent_sha256s: tuple[tuple[str, str], ...]


CONTRACT = ReadinessContract(
    producer_git=PRODUCER_GIT,
    namespace=NAMESPACE,
    shard_count=SHARD_COUNT,
    records_per_shard=RECORDS_PER_SHARD,
    original_pids=ORIGINAL_PIDS,
    source_sha256s=(
        ("scripts/teacher_v1_label.py",
         "58c833fd3707a3ce5403cf7d0e8a23aa518c332976aa7ab4dd3ceb98010386dc"),
        ("scripts/teacher_v1_gate.py",
         "0dbfd020ca323374a6eaacf07481f6951d7f51d05c87b7ff505d0fb939be1a09"),
        ("scripts/teacher_v1_states.py",
         "c967d2b610820c03432317ab1b4491a2c4cb7ba8d20b2b4fc009ddfd97e87c2b"),
        ("shengji/teacher_v1.py",
         "99848ffbf1f41bcd6aa699c2f17b1031eafee651289bbdae33e9853b5e13a250"),
    ),
    parent_sha256s=(
        (f"{NAMESPACE}/stage_b_states.json",
         "90956da86f4f03074a1b4dc2d7198a3da5958470b733eacd104e066c523b4dc6"),
        (f"{NAMESPACE}/stage_b_cheap_v2_receipt.json",
         "2adcc362a6616713ba626787b1dcfcffa90bdf8d74eb4a0b48739fe17efff816"),
        (f"{NAMESPACE}/stage_b_gold_v2_receipt.json",
         "3cc98ee8aa88adab06596bdc3d84d5b6e4b89447607752e1a909eebf6549bc8f"),
        (f"{NAMESPACE}/stage_b_cheap_v2_shard00.json",
         "4b0bf96d130a50d1d3f72e88cc739c6ea2a967552804c4d50b57f104e3654953"),
        (f"{NAMESPACE}/stage_b_cheap_v2_shard01.json",
         "7e90e3e6e2f161f7c1e3502b98634c1aba87304c9e4095c720ac76457e23b3a4"),
        (f"{NAMESPACE}/stage_b_cheap_v2_shard02.json",
         "11804592572ed60febe7994ac39a18d785806134af4280a568996c64c2b2d8fa"),
        (f"{NAMESPACE}/stage_b_cheap_v2_shard03.json",
         "28ae7dc565b012b748494fbfe90dfc9e6f1ebc9a1b1ef14031e34e4140ab6d00"),
        (f"{NAMESPACE}/stage_b_cheap_v2_shard04.json",
         "1bb4c74ea41ac9057e6d151244b052d7edb04bd571d326721899a7229a8a93ab"),
        (f"{NAMESPACE}/stage_b_cheap_v2_shard05.json",
         "22bab2af73516c55fd9141d6a9d3ecefd4511577ed8e99adfbfd26a92ce672dd"),
        (f"{NAMESPACE}/stage_b_cheap_v2_shard06.json",
         "7501655501988bbab5c43339f81a2536b10b371c82f69b7b0f235335b762fd25"),
        (f"{NAMESPACE}/stage_b_cheap_v2_shard07.json",
         "ad4ef720f5a97875b2b07d65c7f9fadebf0c200beaf0cd170ebaf2a2fc319030"),
    ),
)


class ReadinessError(RuntimeError):
    """The outcome-blind readiness check itself could not run."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_regular_unlinked(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except FileNotFoundError:
        return False


def lexists(path: Path) -> bool:
    return os.path.lexists(path)


def _option(argv: list[str], name: str) -> str | None:
    try:
        index = argv.index(name)
    except ValueError:
        return None
    if index + 1 >= len(argv):
        return None
    return argv[index + 1]


def gold_python_workers(rows: Iterable[str]) -> dict[int, str]:
    """Return actual Python gold workers, excluding caffeinate wrappers."""
    workers = {}
    for row in rows:
        stripped = row.strip()
        if not stripped:
            continue
        fields = stripped.split(maxsplit=1)
        if len(fields) != 2 or not fields[0].isdigit():
            continue
        pid = int(fields[0])
        try:
            argv = shlex.split(fields[1])
        except ValueError:
            continue
        if len(argv) < 3:
            continue
        executable = Path(argv[0]).name
        if not executable.startswith("python") \
                or argv[1] != "scripts/teacher_v1_label.py" \
                or argv[2] != "gold":
            continue
        output = _option(argv, "--out")
        workers[pid] = output or "<missing --out>"
    return workers


def _expected_final(contract: ReadinessContract, shard: int) -> str:
    return (
        f"{contract.namespace}/stage_b_gold_v2_shard{shard:02d}.json"
    )


def _expected_log(contract: ReadinessContract, shard: int) -> str:
    return (
        f"{contract.namespace}/stage_b_gold_v2_shard{shard:02d}.log"
    )


def _success_line(contract: ReadinessContract, shard: int) -> re.Pattern[str]:
    output = re.escape(_expected_final(contract, shard))
    return re.compile(
        rf"^wrote {output}: {contract.records_per_shard} records, digest "
        rf"[0-9a-f]{{64}}, [0-9]+(?:\.[0-9]+)?s$"
    )


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, check=True,
        capture_output=True, text=True)
    return result.stdout.strip()


def process_rows() -> list[str]:
    result = subprocess.run(
        ["ps", "-axo", "pid=,command="], check=True,
        capture_output=True, text=True)
    return result.stdout.splitlines()


def readiness_problems(
        root: Path, *, contract: ReadinessContract = CONTRACT,
        git_head: str, tree_status: str,
        processes: Iterable[str]) -> list[str]:
    """Check only identities/publication mechanics; never parse gold JSON."""
    root = root.resolve()
    problems = []
    if len(contract.original_pids) != contract.shard_count \
            or len(set(contract.original_pids)) != contract.shard_count:
        problems.append("recorded creator PID population is malformed")
    if git_head != contract.producer_git:
        problems.append(
            f"producer git {git_head}, expected {contract.producer_git}")
    if tree_status:
        problems.append("producer tree is dirty")

    for relative, expected in (
            *contract.source_sha256s, *contract.parent_sha256s):
        path = root / relative
        if not is_regular_unlinked(path):
            problems.append(f"missing/nonregular frozen input {relative}")
            continue
        if sha256_file(path) != expected:
            problems.append(f"frozen input SHA drift {relative}")
        if lexists(Path(str(path) + ".partial")):
            problems.append(f"frozen input partial exists {relative}.partial")

    namespace = root / contract.namespace
    gate = namespace / "stage_b_gate_v2.json"
    if lexists(gate) or lexists(Path(str(gate) + ".partial")):
        problems.append("Stage-B gate or partial already exists")

    workers = gold_python_workers(processes)
    if workers:
        details = ", ".join(
            f"{pid}:{output}" for pid, output in sorted(workers.items()))
        problems.append(f"gold Python workers remain live: {details}")

    expected_finals = {
        (root / _expected_final(contract, shard)).resolve()
        for shard in range(contract.shard_count)
    }
    actual_finals = {
        path.resolve()
        for path in namespace.glob("stage_b_gold_v2_shard*.json")
        if not path.name.endswith(".partial")
    }
    extras = sorted(str(path) for path in actual_finals - expected_finals)
    if extras:
        problems.append(f"unexpected gold finals: {extras}")

    for shard in range(contract.shard_count):
        relative_final = _expected_final(contract, shard)
        final = root / relative_final
        partial = Path(str(final) + ".partial")
        if not is_regular_unlinked(final):
            problems.append(f"missing/nonregular gold final {relative_final}")
            continue
        if lexists(partial):
            problems.append(f"gold partial remains {partial}")

        relative_log = _expected_log(contract, shard)
        log = root / relative_log
        if not is_regular_unlinked(log):
            problems.append(f"missing/nonregular gold log {relative_log}")
            continue
        try:
            lines = log.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            problems.append(f"unreadable gold log {relative_log}: {exc}")
            continue
        if any("REFUSING:" in line for line in lines):
            problems.append(f"gold log contains refusal {relative_log}")
        if not lines or _success_line(contract, shard).fullmatch(
                lines[-1]) is None:
            problems.append(f"gold log lacks terminal success {relative_log}")

    return sorted(set(problems))


def readiness_summary(root: Path) -> dict[str, object]:
    try:
        head = _git(root, "rev-parse", "HEAD")
        status = _git(
            root, "status", "--porcelain", "--untracked-files=all")
        rows = process_rows()
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReadinessError(str(exc)) from exc
    problems = readiness_problems(
        root, git_head=head, tree_status=status, processes=rows)
    namespace = root.resolve() / CONTRACT.namespace
    finals = sum(
        is_regular_unlinked(namespace / f"stage_b_gold_v2_shard{i:02d}.json")
        for i in range(CONTRACT.shard_count)
    )
    return {
        "schema": READINESS_SCHEMA,
        "ready_for_one_shot_gate": not problems,
        "outcomes_opened": False,
        "artifact_created": False,
        "producer_git": head,
        "expected_producer_git": CONTRACT.producer_git,
        "gold_regular_finals": finals,
        "gold_expected_finals": CONTRACT.shard_count,
        "live_gold_python_workers": len(gold_python_workers(rows)),
        "problems": problems,
        "gate_authorized": False,
        "audit_authorized": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--producer-root", required=True)
    args = parser.parse_args(argv)
    try:
        summary = readiness_summary(Path(args.producer_root))
    except ReadinessError as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["ready_for_one_shot_gate"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
