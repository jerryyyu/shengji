#!/usr/bin/env python3
"""Artifact-only closeout for the terminally refused RLCB-C1 supervisor.

The original supervisor admitted and completed all eight frozen shards, then
refused before aggregation because an unrelated handoff document was dirty.
The original runner's standalone aggregate command later reopened those exact
bytes under the clean frozen executable.  This closeout does not retry a shard,
generate a game, change a statistic, or weaken the frozen rule.  It binds that
specific refusal, the immutable shard population, and the already-published
aggregate into one independently reproducible terminal receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SCRIPT.parent))

import rlcb_c1 as C1  # noqa: E402


SCHEMA = "rlcb-c1-artifact-closeout-v1"
ORIGINAL_GIT = "ced1033e47bcb27b82136f72c757de40387a94f0"
FREEZE_SHA256 = (
    "02c286ed6e431ec807c4fe4040244e11c790c4a5b0ac5dd8f2ba186d275d39d0"
)
SUPERVISOR_PROGRESS_SHA256 = (
    "d3bb6aa9c2385cb57c84a5f65bd04d66bd99849570c5e913458228a6f5c1df8a"
)
AGGREGATE_SHA256 = (
    "83f5a9df2f1db1fa45d50fb005b941b776d9ecc2c9f8703d3d62efff8f5ef5ea"
)
EXPECTED_REFUSAL = (
    "ProtocolRefused: RLCB-C1 refuses a dirty tree: M HANDOFF_REVIEW.md"
)
PROGRESS_PARTIAL = "supervisor_progress.jsonl.partial"
PROGRESS_FINAL = "supervisor_progress.jsonl"
CLOSEOUT_NAME = "artifact_closeout.json"


class CloseoutRefused(RuntimeError):
    """The existing artifacts cannot support this exact closeout."""


def sha256(path: os.PathLike | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while block := fh.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def git(*args: str, binary: bool = False):
    result = subprocess.run(
        ["git", *args], cwd=REPO, check=True, capture_output=True,
        text=not binary,
    )
    return result.stdout if binary else result.stdout.strip()


def _json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CloseoutRefused(f"unreadable JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CloseoutRefused(f"JSON object required at {path}")
    return value


def load_progress(path: Path) -> list[dict]:
    try:
        lines = path.read_text().splitlines()
        rows = [json.loads(line) for line in lines]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CloseoutRefused(f"unreadable supervisor progress: {exc}") from exc
    if not rows or any(not isinstance(row, dict) for row in rows):
        raise CloseoutRefused("supervisor progress must contain JSON objects")
    return rows


def supervisor_progress_problems(rows: list[dict]) -> list[str]:
    problems = []
    statuses = [row.get("status") for row in rows]
    allowed = {
        "ADMITTED", "SHARDS_RUNNING", "HEARTBEAT", "SHARD_COMPLETE",
        "SUPERVISOR_REFUSED",
    }
    if any(status not in allowed for status in statuses):
        problems.append("supervisor progress contains an unregistered status")
    if not rows or rows[0] != {
            "clusters": C1.TOTAL_CLUSTERS,
            "freeze_receipt_sha256": FREEZE_SHA256,
            "git": ORIGINAL_GIT,
            "namespace": C1.RUN_NAMESPACE,
            "shards": C1.SHARD_COUNT,
            "status": "ADMITTED",
            "time_ns": rows[0].get("time_ns") if rows else None,
    }:
        problems.append("supervisor admission identity")
    if (len(rows) < 2 or rows[1].get("status") != "SHARDS_RUNNING"
            or rows[1].get("workers") != C1.SHARD_COUNT):
        problems.append("supervisor exact worker launch")
    completed = [row for row in rows
                 if row.get("status") == "SHARD_COMPLETE"]
    if (len(completed) != C1.SHARD_COUNT
            or sorted(row.get("shard") for row in completed)
            != list(range(C1.SHARD_COUNT))
            or sorted(row.get("complete") for row in completed)
            != list(range(1, C1.SHARD_COUNT + 1))
            or any(row.get("total") != C1.SHARD_COUNT for row in completed)):
        problems.append("supervisor exact eight-shard completion")
    if statuses.count("SUPERVISOR_REFUSED") != 1 \
            or statuses[-1:] != ["SUPERVISOR_REFUSED"]:
        problems.append("supervisor unique terminal refusal")
    elif (rows[-1].get("error") != EXPECTED_REFUSAL
          or rows[-1].get("production_promotion") is not False):
        problems.append("supervisor exact late refusal reason")
    if "COMPLETE" in statuses or "REFUSED" in statuses:
        problems.append("supervisor falsely completed or a shard refused")
    return sorted(set(problems))


def original_source_problems(freeze: dict) -> list[str]:
    problems = []
    frozen = freeze.get("source_sha256s", {})
    for name, path in C1.source_paths().items():
        relative = path.resolve().relative_to(REPO.resolve()).as_posix()
        try:
            blob = git("show", f"{ORIGINAL_GIT}:{relative}", binary=True)
        except subprocess.CalledProcessError:
            problems.append(f"original git source missing: {name}")
            continue
        if sha256_bytes(blob) != frozen.get(name):
            problems.append(f"original git source digest: {name}")
    return problems


def closeout_executable_identity() -> dict:
    head = git("rev-parse", "HEAD")
    if subprocess.run(
            ["git", "merge-base", "--is-ancestor", head, "origin/main"],
            cwd=REPO, capture_output=True).returncode:
        raise CloseoutRefused("closeout HEAD is not pushed to origin/main")
    relative = SCRIPT.relative_to(REPO).as_posix()
    try:
        committed = git("show", f"{head}:{relative}", binary=True)
    except subprocess.CalledProcessError as exc:
        raise CloseoutRefused("closeout executable is not committed") from exc
    live_sha = sha256(SCRIPT)
    if sha256_bytes(committed) != live_sha:
        raise CloseoutRefused("closeout executable differs from committed HEAD")
    return {"git": head, "script_sha256": live_sha}


def _regular_exact(path: Path, expected_sha256: str, label: str,
                   problems: list[str]) -> None:
    if path.is_symlink() or not path.is_file():
        problems.append(f"{label} missing/non-regular")
    elif sha256(path) != expected_sha256:
        problems.append(f"{label} SHA-256")


def build_payload(root: Path) -> dict:
    root = root.resolve()
    if root != C1.run_root().resolve() or root.is_symlink():
        raise CloseoutRefused("closeout requires the canonical RLCB-C1 root")
    problems = C1.protocol_problems()
    freeze = _json(C1.FREEZE_RECEIPT)
    if sha256(C1.FREEZE_RECEIPT) != FREEZE_SHA256:
        problems.append("immutable freeze receipt SHA-256")
    problems += original_source_problems(freeze)

    progress_path = root / PROGRESS_PARTIAL
    _regular_exact(
        progress_path, SUPERVISOR_PROGRESS_SHA256,
        "terminal supervisor progress", problems)
    if (root / PROGRESS_FINAL).exists():
        problems.append("supervisor falsely has a final progress artifact")
    if progress_path.is_file() and not progress_path.is_symlink():
        problems += supervisor_progress_problems(load_progress(progress_path))

    aggregate_path = C1.aggregate_path(root)
    _regular_exact(aggregate_path, AGGREGATE_SHA256, "aggregate", problems)
    if Path(str(aggregate_path) + ".partial").exists():
        problems.append("aggregate has a residual partial")
    for index in range(C1.SHARD_COUNT):
        for path in (C1.record_path(root, index), C1.manifest_path(root, index),
                     root / f"shard{index:02d}.log"):
            if path.is_symlink() or not path.is_file():
                problems.append(f"missing/non-regular final shard artifact {path.name}")
            for suffix in (".partial", ".FAILED"):
                if Path(str(path) + suffix).exists():
                    problems.append(f"residual shard artifact {path.name}{suffix}")

    try:
        fast = C1.require_environment()
        runtime = C1.runtime_identity(fast)
        stored = _json(aggregate_path)
        recomputed = C1.compute_aggregate(root, ORIGINAL_GIT, runtime)
        if stored != recomputed:
            problems.append("aggregate differs from full frozen recomputation")
    except (C1.ProtocolRefused, CloseoutRefused, OSError, ValueError) as exc:
        stored = {}
        runtime = {}
        problems.append(f"aggregate recomputation: {type(exc).__name__}: {exc}")

    if (stored.get("git_sha") != ORIGINAL_GIT
            or stored.get("decision") != "CONFIRM_REPORT_LCB"
            or stored.get("formal_confirmation") is not True
            or stored.get("complete") is not True
            or stored.get("production_promotion") is not False
            or stored.get("automatic_deployment") is not False):
        problems.append("aggregate exact terminal authority")
    if problems:
        raise CloseoutRefused("; ".join(sorted(set(problems))))

    executable = closeout_executable_identity()
    return {
        "schema": SCHEMA,
        "complete": True,
        "state": "FORMAL_CONFIRMATION_CONFIRMED_ARTIFACT_ONLY",
        "artifact_only": True,
        "original_git": ORIGINAL_GIT,
        "closeout_executable": executable,
        "freeze_receipt": {
            "path": str(C1.FREEZE_RECEIPT), "sha256": FREEZE_SHA256},
        "supervisor_progress": {
            "path": str(progress_path),
            "sha256": SUPERVISOR_PROGRESS_SHA256,
            "terminal_status": "SUPERVISOR_REFUSED",
            "terminal_reason": EXPECTED_REFUSAL,
            "all_shards_completed_before_refusal": True,
        },
        "aggregate": {
            "path": str(aggregate_path),
            "sha256": AGGREGATE_SHA256,
            "decision": stored["decision"],
            "formal_confirmation": stored["formal_confirmation"],
        },
        "runtime": runtime,
        "shard_inputs": stored["inputs"],
        "claim": C1.CLAIM,
        "claim_boundary": C1.CLAIM_BOUNDARY,
        "selection_rule": C1.SELECTION_RULE,
        "authorizes": "formal report-LCB confirmation claim only",
        "games_generated": 0,
        "shards_retried": 0,
        "statistics_changed": False,
        "production_promotion": False,
        "automatic_deployment": False,
        "s0c_reopened": False,
    }


def write_exclusive(path: Path, payload: dict) -> None:
    partial = Path(str(path) + ".partial")
    if path.exists() or partial.exists():
        raise CloseoutRefused("closeout output or partial already exists")
    with partial.open("x", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    if _json(partial) != payload:
        raise CloseoutRefused("closeout partial verification failed")
    os.replace(partial, path)


def closeout(root: Path) -> dict:
    payload = build_payload(root)
    path = root.resolve() / CLOSEOUT_NAME
    write_exclusive(path, payload)
    if _json(path) != build_payload(root):
        raise CloseoutRefused("published closeout differs from recomputation")
    return payload


def verify(root: Path) -> dict:
    path = root.resolve() / CLOSEOUT_NAME
    if path.is_symlink() or not path.is_file():
        raise CloseoutRefused("closeout receipt missing/non-regular")
    stored = _json(path)
    expected = build_payload(root)
    if stored != expected:
        raise CloseoutRefused("closeout receipt differs from recomputation")
    return stored


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=("preflight", "closeout", "verify"))
    ap.add_argument("--root", default=str(C1.run_root()))
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        root = Path(args.root)
        if args.command == "preflight":
            payload = build_payload(root)
        elif args.command == "closeout":
            payload = closeout(root)
        else:
            payload = verify(root)
        print(json.dumps({
            "command": args.command,
            "state": payload["state"],
            "aggregate_sha256": payload["aggregate"]["sha256"],
            "production_promotion": False,
            "closeout_sha256": (
                sha256(root.resolve() / CLOSEOUT_NAME)
                if (root.resolve() / CLOSEOUT_NAME).is_file() else None),
        }, sort_keys=True))
    except Exception as exc:
        print(f"REFUSING: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
