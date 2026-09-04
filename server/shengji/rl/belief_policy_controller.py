"""Parallel, resumable execution for the opened-DEV R4 policy diagnostic.

The expensive unit is one independent round root.  Models are loaded once in
the parent and inherited by forked workers.  Workers publish immutable shards;
resume recomputes only outcome-blind root selection and skips every shard whose
bytes validate.  Terminal reconstruction reads each shard once and never
reopens a model or reruns a rollout.
"""

from __future__ import annotations

import multiprocessing
import os
import queue as queue_module
import resource
import json
import hashlib
import time
from pathlib import Path
from typing import Any, Callable

from .belief_artifacts import publish_exclusive_bytes
from .belief_artifacts import stable_read_bytes
from .belief_contract import canonical_json_bytes
from .belief_policy_artifacts import (
    build_policy_root_result,
    publish_policy_root_result,
    reopen_policy_root_result,
    reopen_policy_root_result_with_sha256,
)
from .belief_policy_evaluation import evaluate_policy_root
from .belief_policy_models import R4PolicyModelsV1
from .belief_policy_population import select_natural_policy_root
from .belief_policy_protocol import (
    POLICY_RANKS,
    SELECTED_ROUNDS_PER_RANK,
    TARGET_ROUND_COUNT,
    policy_capacity_coordinates,
    policy_rank_coordinates,
)
from .belief_policy_statistics import reduce_policy_root_results
from .belief_policy_worlds import BeliefPolicyWorldError


CAPACITY_SCHEMA = "belief-r4-policy-capacity-receipt-v1"
RANK_MANIFEST_SCHEMA = "belief-r4-policy-rank-manifest-v1"
SCIENTIFIC_MANIFEST_SCHEMA = "belief-r4-policy-scientific-manifest-v1"
CAPACITY_WORKER_ARMS = (1, 4, 8, 13, 15)
MIN_HOST_CPU_COUNT = 16
MAX_MEMORY_FRACTION_PPB = 750_000_000
ProgressCallback = Callable[[dict[str, Any]], None]


class BeliefPolicyControllerError(ValueError):
    """A capacity arm, resumable shard, deadline, or reduction drifted."""


_MODELS: R4PolicyModelsV1 | None = None
_PROGRESS_QUEUE = None


def _set_models(models: R4PolicyModelsV1) -> None:
    global _MODELS
    if type(models) is not R4PolicyModelsV1:
        raise BeliefPolicyControllerError("policy worker model input drift")
    _MODELS = models


def _models() -> R4PolicyModelsV1:
    if _MODELS is None:
        raise BeliefPolicyControllerError("policy worker models are absent")
    return _MODELS


def _worker_progress(payload: dict[str, Any]) -> None:
    if _PROGRESS_QUEUE is not None:
        _PROGRESS_QUEUE.put(payload)


def _fork_context():
    if "fork" not in multiprocessing.get_all_start_methods():
        raise BeliefPolicyControllerError(
            "policy controller requires measured fork support")
    return multiprocessing.get_context("fork")


def _max_rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports KiB; Darwin reports bytes.
    return int(value if os.uname().sysname == "Darwin" else value * 1024)


def _memory_bytes() -> int:
    try:
        return int(os.sysconf("SC_PHYS_PAGES")) \
            * int(os.sysconf("SC_PAGE_SIZE"))
    except (ValueError, OSError) as exc:
        raise BeliefPolicyControllerError(
            "policy capacity memory probe failed") from exc


def _swap_used_bytes() -> int:
    meminfo = Path("/proc/meminfo")
    if not meminfo.is_file():
        return 0
    rows = {}
    for line in meminfo.read_text(encoding="ascii").splitlines():
        key, raw = line.split(":", 1)
        rows[key] = int(raw.strip().split()[0]) * 1024
    if "SwapTotal" not in rows or "SwapFree" not in rows:
        raise BeliefPolicyControllerError("policy capacity swap probe drift")
    return rows["SwapTotal"] - rows["SwapFree"]


def _live_pool_resources(pool, *, wall_nanoseconds: int) -> dict[str, int]:
    """Measure live Linux worker CPU/RSS for progress, never for gating."""
    cpu_nanoseconds = 0
    rss_bytes = 0
    clock_ticks = int(os.sysconf("SC_CLK_TCK"))
    page_size = int(os.sysconf("SC_PAGE_SIZE"))
    for process in getattr(pool, "_pool", ()):
        pid = getattr(process, "pid", None)
        if type(pid) is not int:
            continue
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(
                encoding="ascii")
            fields = stat[stat.rfind(")") + 2:].split()
            cpu_nanoseconds += (
                (int(fields[11]) + int(fields[12])) * 1_000_000_000
                // clock_ticks)
            statm = Path(f"/proc/{pid}/statm").read_text(
                encoding="ascii").split()
            rss_bytes += int(statm[1]) * page_size
        except (FileNotFoundError, IndexError, OSError, ValueError):
            continue
    return {
        "live_child_cpu_nanoseconds": cpu_nanoseconds,
        "live_aggregate_cpu_utilization_ppb": (
            0 if wall_nanoseconds <= 0 else
            cpu_nanoseconds * 1_000_000_000 // wall_nanoseconds),
        "live_worker_rss_bytes": rss_bytes,
        "live_memory_headroom_bytes": max(
            0, _memory_bytes() - rss_bytes - _max_rss_bytes()),
    }


def _scientific_eta_seconds(
        *, wall_started_monotonic_ns: int,
        scientific_wall_estimate_ns: int,
        deadline_unix_ns: int) -> int:
    """Return the capacity-derived ETA capped by the immutable deadline."""
    elapsed = max(0, time.monotonic_ns() - wall_started_monotonic_ns)
    measured_remaining = max(0, scientific_wall_estimate_ns - elapsed)
    deadline_remaining = max(0, deadline_unix_ns - time.time_ns())
    return min(measured_remaining, deadline_remaining) // 1_000_000_000


def _scientific_progress_event(
        *, phase: str, completed: int, total: int, workers: int,
        rank_progress: dict[int, dict[str, Any]],
        wall_started_monotonic_ns: int,
        scientific_wall_estimate_ns: int,
        deadline_unix_ns: int) -> dict[str, Any]:
    """Build the exact per-shard/heartbeat progress payload."""
    return {
        "phase": phase,
        "completed": completed,
        "total": total,
        "workers": workers,
        "queued_rank_lanes": total - completed,
        "scanned_rounds": sum(
            row["scanned_rounds"] for row in rank_progress.values()),
        "selected_rounds": sum(
            row["selected_rounds"] for row in rank_progress.values()),
        "immutable_shards": sum(
            row["selected_rounds"] for row in rank_progress.values()),
        "rank_scanned": {
            POLICY_RANKS[index]: row["scanned_rounds"]
            for index, row in sorted(rank_progress.items())},
        "rank_selected": {
            POLICY_RANKS[index]: row["selected_rounds"]
            for index, row in sorted(rank_progress.items())},
        "reference_attempts": sum(
            row["reference_attempts"] for row in rank_progress.values()),
        "selection_attempts": sum(
            row["selection_attempts"] for row in rank_progress.values()),
        "report_attempts": sum(
            row["report_attempts"] for row in rank_progress.values()),
        "reference_worlds": sum(
            row["reference_worlds"] for row in rank_progress.values()),
        "selection_worlds": sum(
            row["selection_worlds"] for row in rank_progress.values()),
        "report_worlds": sum(
            row["report_worlds"] for row in rank_progress.values()),
        "selection_physical_rollouts": sum(
            row["selection_physical_rollouts"]
            for row in rank_progress.values()),
        "report_physical_rollouts": sum(
            row["report_physical_rollouts"]
            for row in rank_progress.values()),
        "estimated_remaining_seconds": _scientific_eta_seconds(
            wall_started_monotonic_ns=wall_started_monotonic_ns,
            scientific_wall_estimate_ns=scientific_wall_estimate_ns,
            deadline_unix_ns=deadline_unix_ns),
    }


def _capacity_worker(index: int) -> dict[str, Any]:
    coordinate = policy_capacity_coordinates()[index]
    wall_started = time.monotonic_ns()
    cpu_started = time.process_time_ns()
    root = select_natural_policy_root(coordinate)
    if root is None:
        return {
            "coordinate_index": index,
            "qualified": False,
            "wall_nanoseconds": time.monotonic_ns() - wall_started,
            "cpu_nanoseconds": time.process_time_ns() - cpu_started,
            "max_rss_bytes": _max_rss_bytes(),
            "reference_worlds": 0,
            "selection_physical_rollouts": 0,
            "report_physical_rollouts": 0,
        }
    models = _models()
    try:
        evaluation = evaluate_policy_root(
            root, primary=models.primary, control=models.control,
            privileged_truth=False)
    except BeliefPolicyWorldError as exc:
        if str(exc) != "production world sampler underfilled exact work":
            raise
        return {
            "coordinate_index": index,
            "qualified": False,
            "wall_nanoseconds": time.monotonic_ns() - wall_started,
            "cpu_nanoseconds": time.process_time_ns() - cpu_started,
            "max_rss_bytes": _max_rss_bytes(),
            "reference_worlds": 0,
            "selection_physical_rollouts": 0,
            "report_physical_rollouts": 0,
        }
    return {
        "coordinate_index": index,
        "qualified": True,
        "wall_nanoseconds": time.monotonic_ns() - wall_started,
        "cpu_nanoseconds": time.process_time_ns() - cpu_started,
        "max_rss_bytes": _max_rss_bytes(),
        "reference_worlds": evaluation.work.reference_worlds,
        "selection_physical_rollouts": (
            evaluation.work.selection_physical_rollouts),
        "report_physical_rollouts": (
            evaluation.work.report_physical_rollouts),
    }


def _run_capacity_arm(
        workers: int, *, models: R4PolicyModelsV1,
        heartbeat: Callable[[dict[str, int]], None] | None = None) \
        -> dict[str, Any]:
    if workers not in CAPACITY_WORKER_ARMS \
            or workers > len(policy_capacity_coordinates()):
        raise BeliefPolicyControllerError("policy capacity worker arm drift")
    _set_models(models)
    swap_before = _swap_used_bytes()
    started = time.monotonic_ns()
    cpu_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    with _fork_context().Pool(processes=workers) as pool:
        pending = pool.map_async(_capacity_worker, range(workers))
        last_heartbeat = time.monotonic()
        while not pending.ready():
            pending.wait(timeout=1.0)
            if heartbeat is not None \
                    and time.monotonic() - last_heartbeat >= 60:
                heartbeat(_live_pool_resources(
                    pool, wall_nanoseconds=time.monotonic_ns() - started))
                last_heartbeat = time.monotonic()
        tasks = tuple(pending.get())
    wall = time.monotonic_ns() - started
    cpu_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = round((cpu_after.ru_utime + cpu_after.ru_stime
                 - cpu_before.ru_utime - cpu_before.ru_stime)
                * 1_000_000_000)
    max_child_rss = max(row["max_rss_bytes"] for row in tasks)
    projected_rss = max_child_rss * workers + _max_rss_bytes()
    memory = _memory_bytes()
    swap_after = _swap_used_bytes()
    passed = (
        all(row["qualified"] for row in tasks)
        and swap_after <= swap_before
        and projected_rss * 1_000_000_000
        <= memory * MAX_MEMORY_FRACTION_PPB)
    return {
        "workers": workers,
        "task_count": len(tasks),
        "tasks": list(tasks),
        "wall_nanoseconds": wall,
        "cpu_nanoseconds": cpu,
        "aggregate_cpu_utilization_ppb": (
            0 if wall == 0 else cpu * 1_000_000_000 // wall),
        "max_child_rss_bytes": max_child_rss,
        "projected_process_rss_bytes": projected_rss,
        "host_memory_bytes": memory,
        "swap_used_bytes_before": swap_before,
        "swap_used_bytes_after": swap_after,
        "passed": passed,
    }


def run_score_free_capacity(
        *, models: R4PolicyModelsV1, execution_git: str,
        source_manifest_sha256: str,
        progress: ProgressCallback | None = None) -> dict[str, Any]:
    """Measure the full root DAG without retaining actions or outcomes."""
    cpu_count = os.cpu_count()
    if type(cpu_count) is not int or cpu_count < MIN_HOST_CPU_COUNT \
            or type(execution_git) is not str or len(execution_git) != 40 \
            or type(source_manifest_sha256) is not str \
            or len(source_manifest_sha256) != 64:
        raise BeliefPolicyControllerError("policy capacity host/source drift")
    arms = []
    if progress is not None:
        progress({
            "phase": "capacity-worker-arms",
            "completed": 0,
            "total": len(CAPACITY_WORKER_ARMS),
            "workers": 0,
            "queued_arms": len(CAPACITY_WORKER_ARMS),
        })
    for ordinal, workers in enumerate(CAPACITY_WORKER_ARMS, 1):
        arms.append(_run_capacity_arm(
            workers, models=models,
            heartbeat=(None if progress is None else lambda live: progress({
                "phase": f"capacity-{workers}-workers-running",
                "completed": ordinal - 1,
                "total": len(CAPACITY_WORKER_ARMS),
                "workers": workers,
                "queued_arms": len(CAPACITY_WORKER_ARMS) - ordinal,
                **live,
            }))))
        if progress is not None:
            arm = arms[-1]
            progress({
                "phase": "capacity-worker-arms",
                "completed": ordinal,
                "total": len(CAPACITY_WORKER_ARMS),
                "workers": workers,
                "queued_arms": len(CAPACITY_WORKER_ARMS) - ordinal,
                "arm_wall_nanoseconds": arm["wall_nanoseconds"],
                "arm_cpu_nanoseconds": arm["cpu_nanoseconds"],
                "aggregate_cpu_utilization_ppb": (
                    arm["aggregate_cpu_utilization_ppb"]),
                "max_child_rss_bytes": arm["max_child_rss_bytes"],
                "memory_headroom_bytes": max(
                    0, arm["host_memory_bytes"]
                    - arm["projected_process_rss_bytes"]),
                "reference_worlds": sum(
                    row["reference_worlds"] for row in arm["tasks"]),
                "selection_physical_rollouts": sum(
                    row["selection_physical_rollouts"]
                    for row in arm["tasks"]),
                "report_physical_rollouts": sum(
                    row["report_physical_rollouts"]
                    for row in arm["tasks"]),
            })
    passing = tuple(row["workers"] for row in arms if row["passed"])
    eligible = tuple(workers for workers in passing
                     if workers <= len(POLICY_RANKS)
                     and any(larger > workers for larger in passing))
    if not eligible:
        raise BeliefPolicyControllerError(
            "policy capacity has no headroom-backed worker arm")
    selected = max(eligible)
    headroom = min(workers for workers in passing if workers > selected)
    selected_arm = next(row for row in arms if row["workers"] == selected)
    qualifying_walls = tuple(
        row["wall_nanoseconds"] for row in selected_arm["tasks"]
        if row["qualified"])
    if len(qualifying_walls) != selected:
        raise BeliefPolicyControllerError(
            "policy capacity selected arm population drift")
    receipt = {
        "schema": CAPACITY_SCHEMA,
        "execution_git": execution_git,
        "source_manifest_sha256": source_manifest_sha256,
        "cpu_count": cpu_count,
        "arms": arms,
        "selected_workers": selected,
        "headroom_workers": headroom,
        "selected_max_root_wall_nanoseconds": max(qualifying_walls),
        "scientific_wall_estimate_nanoseconds": (
            max(qualifying_walls) * SELECTED_ROUNDS_PER_RANK * max(
                2, (len(POLICY_RANKS) + selected - 1) // selected)),
        "contains_actions": False,
        "contains_outcomes": False,
        "r4_test_opened": False,
        "scientific_execution_authorized": False,
        "gameplay_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }
    return receipt


def _shard_path(root: Path, rank_index: int, selected: int) -> Path:
    return root / "shards" / f"rank-{rank_index:02d}" \
        / f"selected-{selected:02d}.json"


def _rank_worker(arguments: tuple[int, str, int, int]) -> dict[str, Any]:
    rank_index, root_text, deadline_unix_ns, next_unit_reserve_ns = arguments
    root = Path(root_text)
    rank = POLICY_RANKS[rank_index]
    selected_rows = []
    scanned = 0
    progress_totals = {
        "reference_attempts": 0,
        "selection_attempts": 0,
        "report_attempts": 0,
        "reference_worlds": 0,
        "selection_worlds": 0,
        "report_worlds": 0,
        "selection_physical_rollouts": 0,
        "report_physical_rollouts": 0,
    }
    for coordinate in policy_rank_coordinates(rank):
        if time.time_ns() + next_unit_reserve_ns >= deadline_unix_ns:
            raise BeliefPolicyControllerError(
                "policy scientific deadline exhausted")
        scanned += 1
        selected_root = select_natural_policy_root(coordinate)
        if selected_root is None:
            continue
        selected_index = len(selected_rows)
        path = _shard_path(root, rank_index, selected_index)
        if path.exists() and not path.is_symlink():
            row = reopen_policy_root_result(path)
            if row["coordinate"] != {
                    "trump_rank": coordinate.trump_rank,
                    "rank_index": coordinate.rank_index,
                    "rank_ordinal": coordinate.rank_ordinal,
                    "round_seed": coordinate.round_seed,
                    } \
                    or row["decision_index"] \
                    != selected_root.decision_index \
                    or row["actor_seat"] != selected_root.actor_seat \
                    or row["actor_sha256"] != selected_root.actor.sha256() \
                    or row["selection_key_sha256"] \
                    != selected_root.selection_key.hex() \
                    or row["candidates"] != [
                        list(candidate)
                        for candidate in selected_root.candidates]:
                raise BeliefPolicyControllerError(
                    "policy resumed shard natural-root drift")
        else:
            models = _models()
            try:
                evaluation = evaluate_policy_root(
                    selected_root, primary=models.primary,
                    control=models.control, privileged_truth=True)
            except BeliefPolicyWorldError as exc:
                if str(exc) \
                        != "production world sampler underfilled exact work":
                    raise
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            publish_policy_root_result(
                path, evaluation, primary=models.primary,
                control=models.control)
            row = build_policy_root_result(
                evaluation, primary=models.primary,
                control=models.control)
        selected_rows.append({
            "rank_ordinal": coordinate.rank_ordinal,
            "round_seed": coordinate.round_seed,
            "filename": path.relative_to(root).as_posix(),
        })
        progress_totals["reference_attempts"] += row["folds"][
            "proposal_reference"]["attempts"]
        progress_totals["selection_attempts"] += row["folds"][
            "selection"]["attempts"]
        progress_totals["report_attempts"] += row["folds"][
            "report"]["attempts"]
        for name in (
                "reference_worlds", "selection_worlds", "report_worlds",
                "selection_physical_rollouts", "report_physical_rollouts"):
            progress_totals[name] += row["work"][name]
        _worker_progress({
            "rank_index": rank_index,
            "scanned_rounds": scanned,
            "selected_rounds": len(selected_rows),
            **progress_totals,
        })
        if len(selected_rows) == SELECTED_ROUNDS_PER_RANK:
            break
    if len(selected_rows) != SELECTED_ROUNDS_PER_RANK:
        raise BeliefPolicyControllerError(
            "policy rank exhausted before complete population")
    return {
        "schema": RANK_MANIFEST_SCHEMA,
        "rank": rank,
        "rank_index": rank_index,
        "scanned_rounds": scanned,
        "selected_rounds": selected_rows,
    }


def run_scientific_diagnostic(
        root: Path, *, models: R4PolicyModelsV1, workers: int,
        deadline_unix_ns: int, next_unit_reserve_ns: int,
        scientific_wall_estimate_ns: int,
        execution_freeze_sha256: str, admission_sha256: str,
        progress: ProgressCallback | None = None) -> dict[str, Any]:
    """Run or resume the 13 rank lanes, then perform one cheap reduction."""
    if not isinstance(root, Path) or not root.is_absolute() \
            or type(workers) is not int or not 1 <= workers <= 13 \
            or type(deadline_unix_ns) is not int \
            or deadline_unix_ns <= time.time_ns() \
            or type(next_unit_reserve_ns) is not int \
            or next_unit_reserve_ns <= 0 \
            or type(scientific_wall_estimate_ns) is not int \
            or scientific_wall_estimate_ns <= 0 \
            or any(type(value) is not str or len(value) != 64
                   or any(char not in "0123456789abcdef" for char in value)
                   for value in (
                       execution_freeze_sha256, admission_sha256)):
        raise BeliefPolicyControllerError(
            "policy scientific execution input drift")
    root.mkdir(parents=True, exist_ok=True)
    _set_models(models)
    arguments = tuple((index, str(root), deadline_unix_ns,
                       next_unit_reserve_ns)
                      for index in range(len(POLICY_RANKS)))
    rank_manifests = []
    wall_started = time.monotonic_ns()
    cpu_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    if progress is not None:
        progress({
            "phase": "scientific-rank-lanes",
            "completed": 0,
            "total": len(arguments),
            "workers": workers,
            "queued_rank_lanes": len(arguments),
            "scanned_rounds": 0,
            "selected_rounds": 0,
            "immutable_shards": 0,
            "estimated_remaining_seconds": _scientific_eta_seconds(
                wall_started_monotonic_ns=wall_started,
                scientific_wall_estimate_ns=scientific_wall_estimate_ns,
                deadline_unix_ns=deadline_unix_ns),
        })
    context = _fork_context()
    global _PROGRESS_QUEUE
    progress_queue = context.Queue()
    _PROGRESS_QUEUE = progress_queue
    rank_progress: dict[int, dict[str, Any]] = {}

    def drain_progress() -> bool:
        changed = False
        while True:
            try:
                message = progress_queue.get_nowait()
            except queue_module.Empty:
                break
            rank_progress[message["rank_index"]] = message
            changed = True
        return changed

    def emit_progress(completed: int, phase: str, pool=None) -> None:
        if progress is None:
            return
        payload = _scientific_progress_event(
            phase=phase, completed=completed, total=len(arguments),
            workers=workers, rank_progress=rank_progress,
            wall_started_monotonic_ns=wall_started,
            scientific_wall_estimate_ns=scientific_wall_estimate_ns,
            deadline_unix_ns=deadline_unix_ns)
        if pool is not None:
            payload.update(_live_pool_resources(
                pool, wall_nanoseconds=time.monotonic_ns() - wall_started))
        progress(payload)

    with context.Pool(processes=workers) as pool:
        pending = [pool.apply_async(_rank_worker, (argument,))
                   for argument in arguments]
        completed = 0
        last_heartbeat = time.monotonic()
        while pending:
            shard_changed = drain_progress()
            ready = [result for result in pending if result.ready()]
            for result in ready:
                rank_manifests.append(result.get())
                pending.remove(result)
                completed += 1
                emit_progress(completed, "scientific-rank-lanes", pool)
            if shard_changed and not ready:
                emit_progress(completed, "scientific-shard-published", pool)
            if pending and not ready:
                time.sleep(1.0)
                if progress is not None \
                        and time.monotonic() - last_heartbeat >= 60:
                    emit_progress(
                        completed, "scientific-rank-lanes-running", pool)
                    last_heartbeat = time.monotonic()
        drain_progress()
        emit_progress(len(arguments), "scientific-rank-lanes", pool)
    _PROGRESS_QUEUE = None
    progress_queue.close()
    rank_manifests.sort(key=lambda row: row["rank_index"])
    wall = time.monotonic_ns() - wall_started
    cpu_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    child_cpu = round((cpu_after.ru_utime + cpu_after.ru_stime
                       - cpu_before.ru_utime - cpu_before.ru_stime)
                      * 1_000_000_000)
    rows = []
    digests = []
    files = []
    for rank_row in rank_manifests:
        for selected in rank_row["selected_rounds"]:
            path = root / selected["filename"]
            value, digest, byte_count = \
                reopen_policy_root_result_with_sha256(path)
            rows.append(value)
            digests.append(digest)
            files.append({
                "filename": selected["filename"],
                "sha256": digest,
                "byte_count": byte_count,
            })
    if len(rows) != TARGET_ROUND_COUNT:
        raise BeliefPolicyControllerError(
            "policy scientific shard population incomplete")
    terminal = reduce_policy_root_results(
        tuple(rows), shard_sha256s=tuple(digests))
    manifest = {
        "schema": SCIENTIFIC_MANIFEST_SCHEMA,
        "execution_freeze_sha256": execution_freeze_sha256,
        "admission_sha256": admission_sha256,
        "r4_model_input": {
            "freeze_sha256": models.freeze_sha256,
            "admission_sha256": models.admission_sha256,
            "primary_model_sha256s": list(models.primary.model_sha256s),
            "control_model_sha256s": list(models.control.model_sha256s),
        },
        "rank_manifests": rank_manifests,
        "files": files,
        "terminal": terminal,
        "resources": {
            "workers": workers,
            "wall_nanoseconds": wall,
            "child_cpu_nanoseconds": child_cpu,
            "aggregate_cpu_utilization_ppb": (
                0 if wall == 0 else child_cpu * 1_000_000_000 // wall),
        },
        "r4_test_opened": False,
        "r5_authorized": False,
        "gameplay_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }
    manifest_path = root / "manifest.json"
    publish_exclusive_bytes(manifest_path, canonical_json_bytes(manifest))
    return manifest


def verify_scientific_diagnostic(root: Path) -> dict[str, Any]:
    """Perform the only reconstruction: one read/shard plus cheap reduction."""
    if not isinstance(root, Path) or not root.is_absolute():
        raise BeliefPolicyControllerError(
            "policy verification root drift")
    raw = stable_read_bytes(root / "manifest.json")
    try:
        manifest = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefPolicyControllerError(
            "policy manifest is not JSON") from exc
    if type(manifest) is not dict \
            or canonical_json_bytes(manifest) != raw \
            or set(manifest) != {
                "schema", "rank_manifests", "files", "terminal",
                "resources", "execution_freeze_sha256", "admission_sha256",
                "r4_model_input",
                "r4_test_opened", "r5_authorized", "gameplay_authorized",
                "strength_claim_authorized", "deployment_authorized"} \
            or manifest["schema"] != SCIENTIFIC_MANIFEST_SCHEMA \
            or any(manifest[key] is not False for key in (
                "r4_test_opened", "r5_authorized", "gameplay_authorized",
                "strength_claim_authorized", "deployment_authorized")) \
            or type(manifest["files"]) is not list \
            or len(manifest["files"]) != TARGET_ROUND_COUNT \
            or type(manifest["resources"]) is not dict \
            or set(manifest["resources"]) != {
                "workers", "wall_nanoseconds", "child_cpu_nanoseconds",
                "aggregate_cpu_utilization_ppb"} \
            or type(manifest["r4_model_input"]) is not dict \
            or set(manifest["r4_model_input"]) != {
                "freeze_sha256", "admission_sha256",
                "primary_model_sha256s", "control_model_sha256s"} \
            or any(type(manifest["r4_model_input"][key]) is not list
                   or len(manifest["r4_model_input"][key]) != 8
                   for key in (
                       "primary_model_sha256s", "control_model_sha256s")):
        raise BeliefPolicyControllerError(
            "policy scientific manifest reconstruction drift")
    freeze_raw = stable_read_bytes(root / "freeze.json")
    admission_raw = stable_read_bytes(root / "admission.json")
    if hashlib.sha256(freeze_raw).hexdigest() \
            != manifest["execution_freeze_sha256"] \
            or hashlib.sha256(admission_raw).hexdigest() \
            != manifest["admission_sha256"]:
        raise BeliefPolicyControllerError(
            "policy manifest root input binding drift")
    rows = []
    digests = []
    for file_row in manifest["files"]:
        if type(file_row) is not dict or set(file_row) != {
                "filename", "sha256", "byte_count"} \
                or type(file_row["filename"]) is not str \
                or Path(file_row["filename"]).is_absolute() \
                or ".." in Path(file_row["filename"]).parts:
            raise BeliefPolicyControllerError(
                "policy manifest file row drift")
        path = root / file_row["filename"]
        row, digest, byte_count = reopen_policy_root_result_with_sha256(path)
        if digest != file_row["sha256"] \
                or byte_count != file_row["byte_count"]:
            raise BeliefPolicyControllerError(
                "policy manifest shard byte binding drift")
        rows.append(row)
        digests.append(digest)
    terminal = reduce_policy_root_results(
        tuple(rows), shard_sha256s=tuple(digests))
    if terminal != manifest["terminal"]:
        raise BeliefPolicyControllerError(
            "policy terminal cheap reconstruction drift")
    return manifest
