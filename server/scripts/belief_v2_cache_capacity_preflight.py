#!/usr/bin/env python3
"""Rebuild the sealed R5 train/calibration caches under a safer topology.

This is a score-free capacity proof, not a pipeline retry.  It reads only the
already-bound train/calibration schedules from a failed pre-test R5 namespace,
builds fresh scratch caches, and requires their manifests to match the
preserved failed-stage components byte-for-byte.  Neither the failed namespace
nor any test target is writable through this script.
"""

from __future__ import annotations

import sys


if not sys.flags.safe_path or not sys.dont_write_bytecode:
    raise RuntimeError("V2 cache preflight requires Python -P -B")

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Any


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent
if str(SERVER) not in sys.path:
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
    CONTROL_COHORT_ID,
    PRIMARY_COHORT_ID,
    execution_freeze_from_bytes,
    pipeline_admission_from_bytes,
)
from shengji.rl.belief_v2_input_index_controller import (  # noqa: E402
    reopen_training_input_index,
)
from shengji.rl.belief_v2_parallel_cache import (  # noqa: E402
    build_parallel_tensor_cache,
    parallel_cache_build_topology,
    parallel_cache_worker_count,
    primary_cache_last_build_order,
)
from shengji.rl.belief_v2_tensor_cache import (  # noqa: E402
    LABEL_MANIFEST_FILENAME,
    build_label_overlay,
    cached_batch_factory,
    reopen_label_overlay,
    reopen_tensor_cache,
)
from shengji.rl.belief_v2_tensor_cache_controller import (  # noqa: E402
    CALIBRATION_CACHE_ID,
    CONTROL_OVERLAY_DIRECTORY,
    MANIFEST_FILENAME,
    START_FILENAME,
    _aggregate_peak_host_memory_bytes,
    _cache_directory_name,
    _calibration_binding,
    _process_tree_cpu_time_ns,
    _realization_binding,
)
from shengji.rl.belief_v2_training import (  # noqa: E402
    label_control_batch_from_natural,
)
from scripts.belief_v2_worker import _private_inputs  # noqa: E402


SCHEMA = "belief-v2-r5-cache-capacity-preflight-v1"
FAILED_STAGE_DIRECTORY = Path("training-tensor-cache/result.partial")
_RECEIPT_KEYS = {
    "schema", "source_git", "failed_freeze_sha256",
    "failed_admission_sha256", "failed_stage_start_sha256",
    "training_input_index_sha256", "aggregate_worker_count",
    "concurrent_build_count", "workers_per_build", "wall_nanoseconds",
    "process_tree_cpu_nanoseconds", "conservative_peak_host_memory_bytes",
    "host_memory_cap_bytes", "within_host_memory_cap",
    "component_receipts", "artifact_bytes",
    "matches_preserved_failed_components_exactly",
    "scratch_artifacts_retained", "synthetic_test_targets_opened",
    "human_test_targets_opened", "outcome_fields_opened",
    "failed_admission_retried", "training_authorized",
    "test_split_open_authorized", "scientific_execution_authorized",
    "gameplay_strength_screen_authorized", "strength_claim_authorized",
    "deployment_authorized",
}


class BeliefV2CacheCapacityPreflightError(ValueError):
    """A source, non-test population, parity, or capacity check drifted."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_sha256(value: object) -> bool:
    return type(value) is str and len(value) == 64 \
        and all(char in "0123456789abcdef" for char in value)


def _is_git_sha(value: object) -> bool:
    return type(value) is str and len(value) == 40 \
        and all(char in "0123456789abcdef" for char in value)


def _clean_git_head(expected: str) -> None:
    try:
        head = subprocess.run(
            ("git", "rev-parse", "HEAD"), cwd=REPO, check=True,
            capture_output=True, text=True).stdout.strip()
        status = subprocess.run(
            ("git", "status", "--porcelain", "--untracked-files=all"),
            cwd=REPO, check=True, capture_output=True, text=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BeliefV2CacheCapacityPreflightError(
            "V2 cache preflight Git probe failed") from exc
    if not _is_git_sha(expected) or head != expected or status:
        raise BeliefV2CacheCapacityPreflightError(
            "V2 cache preflight source identity drift")


def _strict_json(path: Path) -> dict[str, Any]:
    raw = stable_read_bytes(path)
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefV2CacheCapacityPreflightError(
            "V2 cache preflight receipt is not JSON") from exc
    if type(payload) is not dict or canonical_json_bytes(payload) != raw:
        raise BeliefV2CacheCapacityPreflightError(
            "V2 cache preflight receipt is not canonical")
    return payload


def _context(root: Path):
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise BeliefV2CacheCapacityPreflightError(
            "V2 cache preflight failed root drift")
    freeze = execution_freeze_from_bytes(stable_read_bytes(
        root / "freeze.json"))
    admission = pipeline_admission_from_bytes(
        stable_read_bytes(root / "admission.json"), freeze=freeze,
        review_marker=stable_read_bytes(root / "review.md"))
    _private_inputs(
        stable_read_bytes(root / "inventory.json"),
        stable_read_bytes(root / "group-split.json"), freeze)
    index_manifest, inputs = reopen_training_input_index(
        root / "training-input-index" / "result",
        freeze=freeze, admission=admission)
    partial = root / FAILED_STAGE_DIRECTORY
    control = tuple(row for row in inputs.realizations
                    if row.cohort_id == CONTROL_COHORT_ID)
    primary = tuple(row for row in inputs.realizations
                    if row.cohort_id == PRIMARY_COHORT_ID)
    downstream_paths = tuple(root / name for name in (
        "device-qualification", "references", "training", "calibration",
        "terminal", "terminal.partial"))
    if len(control) != 1 or len(primary) != 1 \
            or (root / "training-tensor-cache" / "result").exists() \
            or not partial.is_dir() or partial.is_symlink() \
            or any(path.exists() or path.is_symlink()
                   for path in downstream_paths):
        raise BeliefV2CacheCapacityPreflightError(
            "V2 cache preflight failed-stage boundary drift")
    expected_partial = {
        START_FILENAME, CONTROL_OVERLAY_DIRECTORY,
        _cache_directory_name(CALIBRATION_CACHE_ID),
        *(_cache_directory_name(row.cohort_id)
          for row in inputs.realizations
          if row.cohort_id != CONTROL_COHORT_ID),
    }
    if {path.name for path in partial.iterdir()} != expected_partial:
        raise BeliefV2CacheCapacityPreflightError(
            "V2 cache preflight failed component population drift")
    return freeze, admission, index_manifest, inputs, partial, \
        primary[0], control[0]


def _direct_specs(freeze, index_sha256: str, inputs):
    return primary_cache_last_build_order(tuple(
        (row.cohort_id, row, "train", _realization_binding(
            freeze, index_sha256, row))
        for row in inputs.realizations
        if row.cohort_id != CONTROL_COHORT_ID) + ((
            CALIBRATION_CACHE_ID, inputs.common_calibration, "calibration",
            _calibration_binding(
                freeze, index_sha256, inputs.common_calibration)),),
        PRIMARY_COHORT_ID)


def _receipt_row(cache_id: str, kind: str,
                 receipt: dict[str, Any]) -> dict[str, Any]:
    expected_keys = {
        "manifest_sha256", "batch_count", "decision_count",
        "artifact_bytes",
    }
    if type(cache_id) is not str or not cache_id \
            or kind not in {"train", "calibration", "control-overlay"} \
            or type(receipt) is not dict \
            or set(receipt) != expected_keys \
            or not _is_sha256(receipt["manifest_sha256"]) \
            or any(type(receipt[key]) is not int or receipt[key] <= 0
                   for key in ("batch_count", "decision_count",
                               "artifact_bytes")):
        raise BeliefV2CacheCapacityPreflightError(
            "V2 cache preflight component receipt drift")
    return {"cache_id": cache_id, "kind": kind, **receipt}


def _reopen_components(parent: Path, *, freeze, index_sha256: str,
                       inputs, primary, control,
                       allow_stage_start: bool = False) \
        -> tuple[dict[str, Any], ...]:
    expected_directories = {
        CONTROL_OVERLAY_DIRECTORY,
        _cache_directory_name(CALIBRATION_CACHE_ID),
        *(_cache_directory_name(row.cohort_id)
          for row in inputs.realizations
          if row.cohort_id != CONTROL_COHORT_ID),
    }
    if type(allow_stage_start) is not bool:
        raise BeliefV2CacheCapacityPreflightError(
            "V2 cache preflight stage-start allowance drift")
    if allow_stage_start:
        expected_directories.add(START_FILENAME)
    if not parent.is_dir() or parent.is_symlink() \
            or {path.name for path in parent.iterdir()} \
            != expected_directories:
        raise BeliefV2CacheCapacityPreflightError(
            "V2 cache preflight reopened component population drift")
    rows = []
    primary_receipt = None
    primary_binding = _realization_binding(freeze, index_sha256, primary)
    for cache_id, _, mode, binding in _direct_specs(
            freeze, index_sha256, inputs):
        directory = parent / _cache_directory_name(cache_id)
        manifest_sha256 = _sha256(stable_read_bytes(
            directory / MANIFEST_FILENAME))
        receipt = reopen_tensor_cache(
            directory, expected_manifest_sha256=manifest_sha256,
            binding=binding)
        rows.append(_receipt_row(cache_id, mode, receipt))
        if cache_id == PRIMARY_COHORT_ID:
            primary_receipt = receipt
    if primary_receipt is None:
        raise BeliefV2CacheCapacityPreflightError(
            "V2 cache preflight primary receipt drift")
    overlay_directory = parent / CONTROL_OVERLAY_DIRECTORY
    overlay_sha256 = _sha256(stable_read_bytes(
        overlay_directory / LABEL_MANIFEST_FILENAME))
    overlay = reopen_label_overlay(
        overlay_directory, expected_manifest_sha256=overlay_sha256,
        actor_manifest_sha256=primary_receipt["manifest_sha256"],
        binding=primary_binding)
    rows.append(_receipt_row(
        control.cohort_id, "control-overlay", overlay))
    return tuple(sorted(rows, key=lambda row: row["cache_id"]))


def _validate_exact_args(args, *, freeze, admission,
                         index_manifest: dict[str, Any],
                         build_count: int) -> tuple[int, int, int]:
    worker_count = parallel_cache_worker_count(
        freeze.runtime, freeze.resource_caps.training_host_memory_bytes)
    concurrency, workers_per_build = parallel_cache_build_topology(
        freeze.runtime, freeze.resource_caps.training_host_memory_bytes,
        build_count)
    if freeze.sha256() != args.expected_failed_freeze_sha256 \
            or admission.sha256() != args.expected_failed_admission_sha256 \
            or index_manifest.get("index_sha256") \
            != args.expected_index_sha256 \
            or worker_count != args.expected_worker_count \
            or concurrency != args.expected_build_concurrency \
            or workers_per_build != args.expected_workers_per_build:
        raise BeliefV2CacheCapacityPreflightError(
            "V2 cache preflight exact input/topology drift")
    return worker_count, concurrency, workers_per_build


def run(args: argparse.Namespace) -> dict[str, Any]:
    _clean_git_head(args.expected_source_git)
    root = Path(args.root).resolve()
    scratch = Path(args.scratch).resolve()
    output = Path(args.out).resolve()
    if scratch.exists() or scratch.is_symlink() \
            or output.exists() or output.is_symlink() \
            or scratch.parent != output.parent \
            or scratch == root or root in scratch.parents:
        raise BeliefV2CacheCapacityPreflightError(
            "V2 cache preflight output boundary drift")
    freeze, admission, index_manifest, inputs, failed_partial, \
        primary, control = _context(root)
    specs = _direct_specs(freeze, index_manifest["index_sha256"], inputs)
    worker_count, concurrency, workers_per_build = _validate_exact_args(
        args, freeze=freeze, admission=admission,
        index_manifest=index_manifest, build_count=len(specs))
    expected = _reopen_components(
        failed_partial, freeze=freeze,
        index_sha256=index_manifest["index_sha256"], inputs=inputs,
        primary=primary, control=control, allow_stage_start=True)

    scratch.mkdir(mode=0o700)
    progress_lock = threading.Lock()
    progress_by_cache = {cache_id: 0 for cache_id, *_ in specs}
    direct_total = sum(len(schedule.batches)
                       for _, schedule, _, _ in specs)
    last_report = [-1]

    def progress(completed: int, total: int, cache_id: str) -> None:
        with progress_lock:
            if cache_id not in progress_by_cache \
                    or type(completed) is not int or not 0 <= completed <= total:
                raise BeliefV2CacheCapacityPreflightError(
                    "V2 cache preflight progress drift")
            progress_by_cache[cache_id] = completed
            done = sum(progress_by_cache.values())
            percent = done * 10_000 // direct_total
            if percent // 100 != last_report[0] or done == direct_total:
                last_report[0] = percent // 100
                print(
                    f"BELIEF_V2_CACHE_PREFLIGHT direct={done}/{direct_total} "
                    f"percent={percent / 100:.2f}",
                    file=sys.stderr, flush=True)

    def build_one(spec):
        cache_id, schedule, mode, binding = spec
        receipt = build_parallel_tensor_cache(
            scratch / _cache_directory_name(cache_id), root=root,
            freeze=freeze, admission=admission, index=inputs.index,
            schedule=schedule, mode=mode, binding=binding,
            worker_count=workers_per_build, progress=progress)
        return cache_id, receipt

    started = time.monotonic_ns()
    cpu_started = _process_tree_cpu_time_ns()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        direct_receipts = dict(executor.map(build_one, specs))

    primary_binding = _realization_binding(
        freeze, index_manifest["index_sha256"], primary)

    def control_batches():
        factory = cached_batch_factory(
            scratch / _cache_directory_name(PRIMARY_COHORT_ID),
            expected_manifest_sha256=direct_receipts[
                PRIMARY_COHORT_ID]["manifest_sha256"],
            binding=primary_binding)
        for natural in factory():
            transformed, _ = label_control_batch_from_natural(natural)
            yield transformed

    overlay_total = len(control.batches)

    def overlay_progress(completed: int, total: int, cache_id: str) -> None:
        if cache_id != control.sha256() or total != overlay_total:
            raise BeliefV2CacheCapacityPreflightError(
                "V2 cache preflight overlay progress drift")
        if completed % 250 == 0 or completed == total:
            percent = completed * 10_000 // total
            print(
                f"BELIEF_V2_CACHE_PREFLIGHT overlay={completed}/{total} "
                f"percent={percent / 100:.2f}",
                file=sys.stderr, flush=True)

    build_label_overlay(
        scratch / CONTROL_OVERLAY_DIRECTORY, batches=control_batches,
        actor_directory=(
            scratch / _cache_directory_name(PRIMARY_COHORT_ID)),
        actor_manifest_sha256=direct_receipts[
            PRIMARY_COHORT_ID]["manifest_sha256"],
        binding=primary_binding, overlay_id=control.sha256(),
        progress=overlay_progress)
    finished = time.monotonic_ns()
    cpu_nanoseconds = _process_tree_cpu_time_ns() - cpu_started
    peak = _aggregate_peak_host_memory_bytes(worker_count)
    actual = _reopen_components(
        scratch, freeze=freeze,
        index_sha256=index_manifest["index_sha256"], inputs=inputs,
        primary=primary, control=control)
    if actual != expected \
            or peak > freeze.resource_caps.training_host_memory_bytes:
        raise BeliefV2CacheCapacityPreflightError(
            "V2 cache preflight parity/capacity failure")
    artifact_bytes = sum(row["artifact_bytes"] for row in actual)
    receipt = {
        "schema": SCHEMA,
        "source_git": args.expected_source_git,
        "failed_freeze_sha256": freeze.sha256(),
        "failed_admission_sha256": admission.sha256(),
        "failed_stage_start_sha256": _sha256(stable_read_bytes(
            failed_partial / START_FILENAME)),
        "training_input_index_sha256": index_manifest["index_sha256"],
        "aggregate_worker_count": worker_count,
        "concurrent_build_count": concurrency,
        "workers_per_build": workers_per_build,
        "wall_nanoseconds": finished - started,
        "process_tree_cpu_nanoseconds": cpu_nanoseconds,
        "conservative_peak_host_memory_bytes": peak,
        "host_memory_cap_bytes": (
            freeze.resource_caps.training_host_memory_bytes),
        "within_host_memory_cap": True,
        "component_receipts": list(actual),
        "artifact_bytes": artifact_bytes,
        "matches_preserved_failed_components_exactly": True,
        "scratch_artifacts_retained": True,
        "synthetic_test_targets_opened": False,
        "human_test_targets_opened": False,
        "outcome_fields_opened": False,
        "failed_admission_retried": False,
        "training_authorized": False,
        "test_split_open_authorized": False,
        "scientific_execution_authorized": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }
    receipt_sha256 = publish_exclusive_bytes(
        output, canonical_json_bytes(receipt))
    return {"receipt": receipt, "receipt_path": str(output),
            "receipt_sha256": receipt_sha256}


def verify(args: argparse.Namespace) -> dict[str, Any]:
    _clean_git_head(args.expected_source_git)
    root = Path(args.root).resolve()
    scratch = Path(args.scratch).resolve()
    receipt_path = Path(args.receipt).resolve()
    raw = stable_read_bytes(receipt_path)
    if _sha256(raw) != args.expected_receipt_sha256:
        raise BeliefV2CacheCapacityPreflightError(
            "V2 cache preflight receipt SHA drift")
    receipt = _strict_json(receipt_path)
    freeze, admission, index_manifest, inputs, failed_partial, \
        primary, control = _context(root)
    specs = _direct_specs(freeze, index_manifest["index_sha256"], inputs)
    worker_count = parallel_cache_worker_count(
        freeze.runtime, freeze.resource_caps.training_host_memory_bytes)
    concurrency, workers_per_build = parallel_cache_build_topology(
        freeze.runtime, freeze.resource_caps.training_host_memory_bytes,
        len(specs))
    expected = _reopen_components(
        failed_partial, freeze=freeze,
        index_sha256=index_manifest["index_sha256"], inputs=inputs,
        primary=primary, control=control, allow_stage_start=True)
    actual = _reopen_components(
        scratch, freeze=freeze,
        index_sha256=index_manifest["index_sha256"], inputs=inputs,
        primary=primary, control=control)
    authority_keys = (
        "failed_admission_retried", "training_authorized",
        "test_split_open_authorized", "scientific_execution_authorized",
        "gameplay_strength_screen_authorized", "strength_claim_authorized",
        "deployment_authorized")
    if set(receipt) != _RECEIPT_KEYS \
            or receipt.get("schema") != SCHEMA \
            or receipt.get("source_git") != args.expected_source_git \
            or receipt.get("failed_freeze_sha256") != freeze.sha256() \
            or receipt.get("failed_admission_sha256") != admission.sha256() \
            or receipt.get("failed_stage_start_sha256") != _sha256(
                stable_read_bytes(failed_partial / START_FILENAME)) \
            or receipt.get("training_input_index_sha256") \
            != index_manifest["index_sha256"] \
            or receipt.get("aggregate_worker_count") != worker_count \
            or receipt.get("concurrent_build_count") != concurrency \
            or receipt.get("workers_per_build") != workers_per_build \
            or type(receipt.get("wall_nanoseconds")) is not int \
            or receipt["wall_nanoseconds"] <= 0 \
            or type(receipt.get("process_tree_cpu_nanoseconds")) is not int \
            or receipt["process_tree_cpu_nanoseconds"] < 0 \
            or type(receipt.get("conservative_peak_host_memory_bytes")) \
            is not int \
            or not 0 < receipt["conservative_peak_host_memory_bytes"] \
            <= freeze.resource_caps.training_host_memory_bytes \
            or receipt.get("host_memory_cap_bytes") \
            != freeze.resource_caps.training_host_memory_bytes \
            or receipt.get("within_host_memory_cap") is not True \
            or receipt.get("component_receipts") != list(actual) \
            or actual != expected \
            or receipt.get("artifact_bytes") \
            != sum(row["artifact_bytes"] for row in actual) \
            or receipt.get("matches_preserved_failed_components_exactly") \
            is not True \
            or receipt.get("scratch_artifacts_retained") is not True \
            or receipt.get("synthetic_test_targets_opened") is not False \
            or receipt.get("human_test_targets_opened") is not False \
            or receipt.get("outcome_fields_opened") is not False \
            or any(receipt.get(key) is not False for key in authority_keys):
        raise BeliefV2CacheCapacityPreflightError(
            "V2 cache preflight verification drift")
    return {
        "verified": True,
        "receipt_sha256": _sha256(raw),
        "source_git": args.expected_source_git,
        "aggregate_worker_count": worker_count,
        "concurrent_build_count": concurrency,
        "workers_per_build": workers_per_build,
        "component_count": len(actual),
        "test_split_opened": False,
        "scientific_execution_authorized": False,
    }


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", required=True)
    parser.add_argument("--scratch", required=True)
    parser.add_argument("--expected-source-git", required=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run")
    _common(run_parser)
    run_parser.add_argument("--out", required=True)
    run_parser.add_argument("--expected-failed-freeze-sha256", required=True)
    run_parser.add_argument(
        "--expected-failed-admission-sha256", required=True)
    run_parser.add_argument("--expected-index-sha256", required=True)
    run_parser.add_argument("--expected-worker-count", required=True, type=int)
    run_parser.add_argument(
        "--expected-build-concurrency", required=True, type=int)
    run_parser.add_argument(
        "--expected-workers-per-build", required=True, type=int)
    verify_parser = commands.add_parser("verify")
    _common(verify_parser)
    verify_parser.add_argument("--receipt", required=True)
    verify_parser.add_argument("--expected-receipt-sha256", required=True)
    args = parser.parse_args()
    configure_numerical_runtime()
    result = run(args) if args.command == "run" else verify(args)
    print(canonical_json_bytes(result).decode("ascii"), end="")


if __name__ == "__main__":
    main()
