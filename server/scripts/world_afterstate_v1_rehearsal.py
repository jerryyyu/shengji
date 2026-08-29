#!/usr/bin/env python3
"""Publish one bounded synthetic Value V1 full-path rehearsal."""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import resource
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
if not sys.flags.safe_path or not sys.dont_write_bytecode:
    raise RuntimeError("Value V1 rehearsal requires Python -P -B")
if os.environ.get("PYTHONPATH"):
    raise RuntimeError("Value V1 rehearsal refuses PYTHONPATH")
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

import torch

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v1_pipeline import (
    publish_pipeline_build, reopen_pipeline_directory)
from shengji.rl.world_afterstate_v1_rehearsal import (
    AUDIT_STATE_COUNT, AUTHORITY, TRAIN_STATE_COUNT,
    build_non_scientific_rehearsal)


RECEIPT_SCHEMA = "world-afterstate-v1-non-scientific-rehearsal-receipt-v1"


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ("git", *arguments), cwd=repo, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return result.stdout.strip()


def _write_once(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, 0o400)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    status = _git(repo, "status", "--porcelain", "--untracked-files=all")
    if status:
        raise SystemExit("rehearsal requires an exact clean Git head")
    head = _git(repo, "rev-parse", "HEAD")
    if len(head) != 40:
        raise SystemExit("rehearsal Git head is invalid")
    if args.output.exists() or args.output.is_symlink() \
            or args.receipt.exists() or args.receipt.is_symlink():
        raise SystemExit("rehearsal output namespace is occupied")

    progress_rows = []

    def progress(value):
        progress_rows.append(value)
        print(
            f"{value['cohort_name']} epoch {value['epoch']}: "
            f"{value['percent_basis_points'] / 100:.2f}%",
            flush=True)

    started_utc = datetime.now(timezone.utc).isoformat()
    started_monotonic = time.monotonic_ns()
    started_cpu = time.process_time_ns()
    build = build_non_scientific_rehearsal(progress=progress)
    publish_pipeline_build(args.output, build)
    reopened = reopen_pipeline_directory(args.output)
    finished_cpu = time.process_time_ns()
    finished_monotonic = time.monotonic_ns()
    finished_utc = datetime.now(timezone.utc).isoformat()
    if reopened != build:
        raise SystemExit("rehearsal independent reconstruction drift")
    artifact_bytes = sum(
        path.stat().st_size for path in args.output.rglob("*")
        if path.is_file())
    usage = resource.getrusage(resource.RUSAGE_SELF)
    peak_rss_bytes = int(usage.ru_maxrss)
    if sys.platform != "darwin":
        peak_rss_bytes *= 1024
    body = {
        "schema": RECEIPT_SCHEMA,
        "source_head": head,
        "source_tree_clean": True,
        "non_scientific_rehearsal": True,
        "synthetic_train_state_count": TRAIN_STATE_COUNT,
        "synthetic_audit_state_count": AUDIT_STATE_COUNT,
        "pipeline_manifest_sha256": build.manifest["manifest_sha256"],
        "pipeline_manifest_external_sha256": _file_sha256(
            args.output / "manifest.json"),
        "terminal_decision": build.manifest["terminal_decision"],
        "mechanics_rehearsal_passed": True,
        "terminal_scientific_interpretation_authorized": False,
        "pipeline_file_count": build.manifest["file_count"] + 1,
        "pipeline_artifact_bytes": artifact_bytes,
        "started_utc": started_utc,
        "finished_utc": finished_utc,
        "wall_nanoseconds": finished_monotonic - started_monotonic,
        "cpu_nanoseconds": finished_cpu - started_cpu,
        "peak_rss_bytes": peak_rss_bytes,
        "progress_event_count": len(progress_rows),
        "final_progress_by_cohort": {
            name: max(
                row["percent_basis_points"] for row in progress_rows
                if row["cohort_name"] == name)
            for name in (
                "natural", "identical-successor",
                "action-association-permutation", "label-permutation")
        },
        "runtime": {
            "python_executable": str(Path(sys.executable).resolve()),
            "python_executable_sha256": _file_sha256(
                Path(sys.executable).resolve()),
            "python_version": platform.python_version(),
            "torch_version": torch.__version__,
            "machine": platform.machine(),
            "platform": platform.platform(),
            "logical_cpu_count": os.cpu_count(),
        },
        "independent_reconstruction_passed": True,
        "calibration_labels_opened_only_after_prediction_seal": True,
        "report_rows_opened": False,
        "authority": dict(AUTHORITY),
    }
    receipt = {**body, "receipt_sha256": _sha_bytes(
        canonical_json_bytes(body))}
    _write_once(args.receipt, canonical_json_bytes(receipt))
    print(
        f"rehearsal complete: {receipt['receipt_sha256']} "
        f"({receipt['wall_nanoseconds'] / 1e9:.2f}s)",
        flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
