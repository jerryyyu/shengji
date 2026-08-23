#!/usr/bin/env python3
"""Measure the exact non-test input index under its production memory guard."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

if not sys.flags.safe_path or not sys.dont_write_bytecode \
        or os.environ.get("PYTHONPATH"):
    raise RuntimeError("V2 input preflight requires Python -P -B")

SERVER = Path(__file__).resolve().parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SERVER))

from shengji.rl.belief_artifacts import (  # noqa: E402
    publish_exclusive_bytes,
    stable_read_bytes,
)
from shengji.rl.belief_contract import canonical_json_bytes  # noqa: E402
from shengji.rl.belief_v2_execution_identity import (  # noqa: E402
    configure_numerical_runtime,
)
from shengji.rl.belief_v2_freeze import (  # noqa: E402
    execution_freeze_from_bytes,
    pipeline_admission_from_bytes,
)
from shengji.rl.belief_v2_input_index_controller import (  # noqa: E402
    _aggregate_peak_host_memory_bytes,
    _process_tree_cpu_time_ns,
)
from shengji.rl.belief_v2_parallel_inputs import (  # noqa: E402
    parallel_input_worker_count,
    scan_parallel_synthetic_training_inputs,
)
from shengji.rl.belief_v2_streaming_inputs import (  # noqa: E402
    reopen_streaming_training_inputs,
    streaming_training_inputs_bytes,
)
from scripts.belief_v2_worker import _private_inputs  # noqa: E402


SCHEMA = "belief-v2-r5-input-index-memory-preflight-v1"


def _git_head() -> str:
    result = subprocess.run(
        ("git", "rev-parse", "HEAD"), cwd=REPO,
        check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _is_sha256(value: object) -> bool:
    return type(value) is str and len(value) == 64 \
        and all(char in "0123456789abcdef" for char in value)


def run(args: argparse.Namespace) -> dict:
    root = Path(args.root).resolve()
    output = Path(args.out).resolve()
    if not root.is_dir() or output.exists() or output.is_symlink() \
            or not _is_sha256(args.expected_index_sha256) \
            or type(args.expected_index_bytes) is not int \
            or args.expected_index_bytes <= 0 \
            or type(args.expected_worker_count) is not int \
            or args.expected_worker_count <= 0 \
            or _git_head() != args.expected_source_git:
        raise ValueError("V2 input preflight arguments drift")
    freeze = execution_freeze_from_bytes(stable_read_bytes(
        root / "freeze.json"))
    admission = pipeline_admission_from_bytes(
        stable_read_bytes(root / "admission.json"), freeze=freeze,
        review_marker=stable_read_bytes(root / "review.md"))
    inventory, group_split = _private_inputs(
        stable_read_bytes(root / "inventory.json"),
        stable_read_bytes(root / "group-split.json"), freeze)
    worker_count = parallel_input_worker_count(
        freeze.runtime, freeze.resource_caps.training_host_memory_bytes)
    if worker_count != args.expected_worker_count:
        raise ValueError("V2 input preflight worker topology drift")

    total_units = 12_003

    def progress(phase: str, unit: int) -> None:
        if phase == "after-unit" \
                and (unit % 1000 == 0 or unit == total_units):
            print(f"BELIEF_V2_INPUT_PREFLIGHT {unit}/{total_units}",
                  file=sys.stderr, flush=True)

    started = time.monotonic_ns()
    cpu_started = _process_tree_cpu_time_ns()
    inputs = reopen_streaming_training_inputs(
        root, freeze=freeze, admission=admission,
        inventory=inventory, group_split=group_split,
        deadline_check=progress,
        synthetic_scan=lambda **kwargs:
            scan_parallel_synthetic_training_inputs(
                **kwargs, worker_count=worker_count))
    raw = streaming_training_inputs_bytes(inputs, freeze)
    finished = time.monotonic_ns()
    cpu_nanoseconds = _process_tree_cpu_time_ns() - cpu_started
    peak = _aggregate_peak_host_memory_bytes(worker_count)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != args.expected_index_sha256 \
            or len(raw) != args.expected_index_bytes \
            or peak > freeze.resource_caps.training_host_memory_bytes:
        raise ValueError("V2 bounded input preflight did not reproduce safely")
    receipt = {
        "schema": SCHEMA,
        "source_git": args.expected_source_git,
        "failed_freeze_sha256": freeze.sha256(),
        "failed_admission_sha256": admission.sha256(),
        "worker_count": worker_count,
        "host_memory_cap_bytes": (
            freeze.resource_caps.training_host_memory_bytes),
        "conservative_peak_host_memory_bytes": peak,
        "within_memory_cap": True,
        "wall_nanoseconds": finished - started,
        "process_tree_cpu_nanoseconds": cpu_nanoseconds,
        "index_sha256": digest,
        "index_bytes": len(raw),
        "matches_failed_index": True,
        "synthetic_test_targets_opened": False,
        "human_test_targets_opened": False,
        "outcome_fields_opened": False,
        "artifact_retained": False,
        "retry_authorized": False,
        "scientific_execution_authorized": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }
    receipt_sha256 = publish_exclusive_bytes(
        output, canonical_json_bytes(receipt))
    return {
        "receipt": receipt,
        "receipt_path": str(output),
        "receipt_sha256": receipt_sha256,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--expected-source-git", required=True)
    parser.add_argument("--expected-index-sha256", required=True)
    parser.add_argument("--expected-index-bytes", required=True, type=int)
    parser.add_argument("--expected-worker-count", required=True, type=int)
    args = parser.parse_args()
    configure_numerical_runtime()
    print(canonical_json_bytes(run(args)).decode("ascii"), end="")


if __name__ == "__main__":
    main()
