#!/usr/bin/env python3
"""Bounded, score-free parent-phase profile for the BELIEF R5 cache.

This diagnostic intentionally cannot prove full-population capacity.  It
reopens the authenticated pre-test R5 train index, selects a deterministic
quantile sample of the primary training schedule, builds only that sample,
and publishes parent-thread phase timings plus a hash-bound cache receipt.
No calibration/test target, model, loss, score, or outcome is opened.
"""

from __future__ import annotations

import sys


if not sys.flags.safe_path or not sys.dont_write_bytecode:
    raise RuntimeError("V2 parent profile requires Python -P -B")

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Sequence


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from shengji.rl.belief_artifacts import (  # noqa: E402
    publish_exclusive_bytes,
    stable_read_bytes,
)
from shengji.rl.belief_contract import canonical_json_bytes  # noqa: E402
from shengji.rl.belief_v2_freeze import PRIMARY_COHORT_ID  # noqa: E402
from shengji.rl.belief_v2_parallel_cache import (  # noqa: E402
    build_profiled_parallel_tensor_cache,
    parallel_cache_worker_count,
)
from shengji.rl.belief_v2_schedule import (  # noqa: E402
    V2CohortRealizationV1,
    _row_population_sha256,
    _schedule_sha256,
)
from shengji.rl.belief_v2_tensor_cache import (  # noqa: E402
    MANIFEST_FILENAME,
    reopen_tensor_cache,
)
from shengji.rl.belief_v2_tensor_cache_controller import (  # noqa: E402
    _process_tree_cpu_time_ns,
    _realization_binding,
)
from scripts.belief_v2_cache_capacity_preflight import (  # noqa: E402
    _clean_git_head,
    _context,
)


SCHEMA = "belief-v2-r5-cache-parent-profile-v1"
AUTHORITY = {
    "full_capacity_proven": False,
    "freeze_authorized": False,
    "scientific_execution_authorized": False,
    "training_authorized": False,
    "test_split_open_authorized": False,
    "gameplay_strength_screen_authorized": False,
    "strength_claim_authorized": False,
    "deployment_authorized": False,
}
PHASES = {
    "executor-construction", "submit", "wait", "future-result", "emit",
    "executor-shutdown", "direct-seal",
}


class BeliefV2CacheParentProfileError(ValueError):
    """The bounded profile or its evidence drifted."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sample_indices(total: int, count: int) -> tuple[int, ...]:
    if (type(total) is not int or total <= 1
            or type(count) is not int or not 2 <= count <= total):
        raise BeliefV2CacheParentProfileError(
            "V2 parent profile sample inputs drift")
    result = tuple(
        (index * (total - 1)) // (count - 1) for index in range(count))
    if (len(result) != count or len(set(result)) != count
            or result[0] != 0 or result[-1] != total - 1):
        raise BeliefV2CacheParentProfileError(
            "V2 parent profile sample derivation drift")
    return result


def _sample_realization(
        source: V2CohortRealizationV1, count: int) \
        -> tuple[V2CohortRealizationV1, tuple[int, ...]]:
    if type(source) is not V2CohortRealizationV1 \
            or source.cohort_id != PRIMARY_COHORT_ID:
        raise BeliefV2CacheParentProfileError(
            "V2 parent profile requires the primary realization")
    indices = _sample_indices(len(source.batches), count)
    batches = tuple(source.batches[index] for index in indices)
    selected = {key for batch in batches for key in batch}
    rows = tuple(row for row in source.rows if row.decision_key in selected)
    if len(rows) != len(selected):
        raise BeliefV2CacheParentProfileError(
            "V2 parent profile decision selection drift")
    result = replace(
        source,
        cohort_id=f"{source.cohort_id}-parent-profile-{count}",
        comparator_cohort_id=None,
        rows=rows,
        removed_synthetic_decision_keys=(),
        batches=batches,
        synthetic_decision_count=sum(
            row.source_kind == "synthetic" for row in rows),
        human_decision_count=sum(row.source_kind == "human" for row in rows),
        active_label_count=sum(row.active_label_count for row in rows),
        decision_population_sha256=_row_population_sha256(rows),
        batch_schedule_sha256=_schedule_sha256(batches),
    )
    try:
        result.canonical_bytes()
    except ValueError as exc:
        raise BeliefV2CacheParentProfileError(
            "V2 parent profile sampled realization drift") from exc
    return result, indices


def _phase_summary(events: Sequence[dict[str, Any]]) \
        -> tuple[dict[str, Any], ...]:
    if not events:
        raise BeliefV2CacheParentProfileError(
            "V2 parent profile has no phase events")
    rows = []
    for phase in sorted(PHASES):
        selected = [row for row in events if row["phase"] == phase]
        if not selected:
            continue
        maximum = max(
            selected,
            key=lambda row: (row["wall_nanoseconds"], -row["unit_index"]))
        rows.append({
            "phase": phase,
            "event_count": len(selected),
            "wall_nanoseconds": sum(
                row["wall_nanoseconds"] for row in selected),
            "thread_cpu_nanoseconds": sum(
                row["thread_cpu_nanoseconds"] for row in selected),
            "maximum_wall_nanoseconds": maximum["wall_nanoseconds"],
            "maximum_wall_unit_index": maximum["unit_index"],
        })
    return tuple(rows)


def _validate_events(events: object, batch_count: int) \
        -> tuple[dict[str, Any], ...]:
    if type(events) is not list:
        raise BeliefV2CacheParentProfileError(
            "V2 parent profile event population drift")
    rows = tuple(events)
    if (any(type(row) is not dict or set(row) != {
                "phase", "unit_index", "wall_nanoseconds",
                "thread_cpu_nanoseconds"}
            or row["phase"] not in PHASES
            or type(row["unit_index"]) is not int
            or not 0 <= row["unit_index"] <= batch_count
            or type(row["wall_nanoseconds"]) is not int
            or row["wall_nanoseconds"] < 0
            or type(row["thread_cpu_nanoseconds"]) is not int
            or row["thread_cpu_nanoseconds"] < 0
            for row in rows)
            or sum(row["phase"] == "submit" for row in rows) != batch_count
            or sum(row["phase"] == "future-result" for row in rows)
            != batch_count
            or sum(row["phase"] == "emit" for row in rows) != batch_count
            or sum(row["phase"] == "executor-construction" for row in rows)
            != 1
            or sum(row["phase"] == "executor-shutdown" for row in rows) != 1
            or sum(row["phase"] == "direct-seal" for row in rows) != 1):
        raise BeliefV2CacheParentProfileError(
            "V2 parent profile event population drift")
    return rows


def _context_and_sample(root: Path, sample_count: int):
    freeze, admission, index_manifest, inputs, _, primary, _ = _context(root)
    sample, indices = _sample_realization(primary, sample_count)
    binding = replace(
        _realization_binding(freeze, index_manifest["index_sha256"], primary),
        cache_id=sample.cohort_id,
        decision_population_sha256=sample.decision_population_sha256,
        batch_schedule_sha256=sample.batch_schedule_sha256,
        expected_decision_count=len(sample.rows),
        expected_batch_count=len(sample.batches),
    )
    return freeze, admission, index_manifest, inputs, primary, sample, \
        indices, binding


def run(args: argparse.Namespace) -> dict[str, Any]:
    _clean_git_head(args.expected_source_git)
    root = Path(args.root).resolve()
    scratch = Path(args.scratch).resolve()
    output = Path(args.out).resolve()
    if (scratch.exists() or scratch.is_symlink()
            or output.exists() or output.is_symlink()
            or scratch.parent != output.parent
            or scratch == root or root in scratch.parents):
        raise BeliefV2CacheParentProfileError(
            "V2 parent profile output boundary drift")
    (freeze, admission, index_manifest, _inputs, primary, sample, indices,
     binding) = _context_and_sample(root, args.sample_batch_count)
    worker_count = parallel_cache_worker_count(
        freeze.runtime, freeze.resource_caps.training_host_memory_bytes)
    if (freeze.sha256() != args.expected_failed_freeze_sha256
            or admission.sha256() != args.expected_failed_admission_sha256
            or index_manifest.get("index_sha256")
            != args.expected_index_sha256
            or worker_count != args.expected_worker_count):
        raise BeliefV2CacheParentProfileError(
            "V2 parent profile exact input/topology drift")

    scratch.mkdir(mode=0o700)
    cache = scratch / "sample-cache"
    events: list[dict[str, Any]] = []

    def observe(phase: str, unit_index: int, wall: int, cpu: int) -> None:
        events.append({
            "phase": phase,
            "unit_index": unit_index,
            "wall_nanoseconds": wall,
            "thread_cpu_nanoseconds": cpu,
        })

    def progress(completed: int, total: int, _cache_id: str) -> None:
        if completed == 0 or completed == total or completed % 8 == 0:
            print(
                f"BELIEF_V2_PARENT_PROFILE completed={completed}/{total} "
                f"percent={(completed * 100) / total:.2f}",
                file=sys.stderr, flush=True)

    started = time.monotonic_ns()
    cpu_started = _process_tree_cpu_time_ns()
    cache_receipt = build_profiled_parallel_tensor_cache(
        cache, root=root, freeze=freeze, admission=admission,
        index=_inputs.index, schedule=sample, mode="train",
        binding=binding, worker_count=worker_count,
        parent_phase_observer=observe, progress=progress)
    wall_nanoseconds = time.monotonic_ns() - started
    process_tree_cpu_nanoseconds = _process_tree_cpu_time_ns() - cpu_started
    rows = _validate_events(events, len(sample.batches))
    manifest_sha256 = _sha(stable_read_bytes(cache / MANIFEST_FILENAME))
    reopened = reopen_tensor_cache(
        cache, expected_manifest_sha256=manifest_sha256, binding=binding)
    if reopened != cache_receipt:
        raise BeliefV2CacheParentProfileError(
            "V2 parent profile cache reopen drift")
    receipt = {
        "schema": SCHEMA,
        "source_git": args.expected_source_git,
        "failed_freeze_sha256": freeze.sha256(),
        "failed_admission_sha256": admission.sha256(),
        "training_input_index_sha256": index_manifest["index_sha256"],
        "source_primary_realization_sha256": primary.sha256(),
        "source_primary_batch_count": len(primary.batches),
        "sample_batch_count": len(sample.batches),
        "sample_original_batch_indices": list(indices),
        "sample_decision_count": len(sample.rows),
        "sample_decision_population_sha256": (
            sample.decision_population_sha256),
        "sample_batch_schedule_sha256": sample.batch_schedule_sha256,
        "worker_count": worker_count,
        "wall_nanoseconds": wall_nanoseconds,
        "process_tree_cpu_nanoseconds": process_tree_cpu_nanoseconds,
        "phase_events": list(rows),
        "phase_summary": list(_phase_summary(rows)),
        "sample_cache_receipt": cache_receipt,
        "sample_cache_reopened": True,
        "sample_cache_retained": True,
        "quantile_sample_is_not_full_capacity_evidence": True,
        "synthetic_test_targets_opened": False,
        "human_test_targets_opened": False,
        "outcome_fields_opened": False,
        "authority": AUTHORITY,
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
    try:
        receipt = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefV2CacheParentProfileError(
            "V2 parent profile receipt is not JSON") from exc
    if type(receipt) is not dict or canonical_json_bytes(receipt) != raw \
            or receipt.get("schema") != SCHEMA \
            or receipt.get("source_git") != args.expected_source_git \
            or receipt.get("authority") != AUTHORITY \
            or receipt.get("quantile_sample_is_not_full_capacity_evidence") \
            is not True \
            or receipt.get("synthetic_test_targets_opened") is not False \
            or receipt.get("human_test_targets_opened") is not False \
            or receipt.get("outcome_fields_opened") is not False:
        raise BeliefV2CacheParentProfileError(
            "V2 parent profile receipt identity/authority drift")
    sample_count = receipt.get("sample_batch_count")
    (freeze, admission, index_manifest, _inputs, primary, sample, indices,
     binding) = _context_and_sample(root, sample_count)
    if (receipt.get("failed_freeze_sha256") != freeze.sha256()
            or receipt.get("failed_admission_sha256") != admission.sha256()
            or receipt.get("training_input_index_sha256")
            != index_manifest["index_sha256"]
            or receipt.get("source_primary_realization_sha256")
            != primary.sha256()
            or receipt.get("source_primary_batch_count")
            != len(primary.batches)
            or receipt.get("sample_original_batch_indices") != list(indices)
            or receipt.get("sample_decision_count") != len(sample.rows)
            or receipt.get("sample_decision_population_sha256")
            != sample.decision_population_sha256
            or receipt.get("sample_batch_schedule_sha256")
            != sample.batch_schedule_sha256
            or receipt.get("worker_count") != parallel_cache_worker_count(
                freeze.runtime,
                freeze.resource_caps.training_host_memory_bytes)):
        raise BeliefV2CacheParentProfileError(
            "V2 parent profile frozen sample reconstruction drift")
    events = _validate_events(receipt.get("phase_events"), sample_count)
    if receipt.get("phase_summary") != list(_phase_summary(events)):
        raise BeliefV2CacheParentProfileError(
            "V2 parent profile phase summary reconstruction drift")
    expected_root_population = {"sample-cache"}
    if (not scratch.is_dir() or scratch.is_symlink()
            or {path.name for path in scratch.iterdir()}
            != expected_root_population):
        raise BeliefV2CacheParentProfileError(
            "V2 parent profile scratch population drift")
    cache = scratch / "sample-cache"
    manifest_sha256 = _sha(stable_read_bytes(cache / MANIFEST_FILENAME))
    reopened = reopen_tensor_cache(
        cache, expected_manifest_sha256=manifest_sha256, binding=binding)
    if reopened != receipt.get("sample_cache_receipt") \
            or receipt.get("sample_cache_reopened") is not True \
            or receipt.get("sample_cache_retained") is not True:
        raise BeliefV2CacheParentProfileError(
            "V2 parent profile cache evidence drift")
    return {"status": "VERIFIED_SCORE_FREE_PARENT_PROFILE",
            "receipt_sha256": _sha(raw), "authority": AUTHORITY}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--root", required=True)
    run_parser.add_argument("--scratch", required=True)
    run_parser.add_argument("--out", required=True)
    run_parser.add_argument("--expected-source-git", required=True)
    run_parser.add_argument("--expected-failed-freeze-sha256", required=True)
    run_parser.add_argument("--expected-failed-admission-sha256", required=True)
    run_parser.add_argument("--expected-index-sha256", required=True)
    run_parser.add_argument("--expected-worker-count", required=True, type=int)
    run_parser.add_argument("--sample-batch-count", required=True, type=int)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--root", required=True)
    verify_parser.add_argument("--scratch", required=True)
    verify_parser.add_argument("--receipt", required=True)
    verify_parser.add_argument("--expected-source-git", required=True)
    args = parser.parse_args(argv)
    try:
        result = run(args) if args.command == "run" else verify(args)
    except (BeliefV2CacheParentProfileError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
