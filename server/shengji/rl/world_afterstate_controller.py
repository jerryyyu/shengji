"""Staged execution mechanics for the reviewed E3/E4 experiment.

This controller keeps outcome generation, train/calibration consumption, and
report opening as separate filesystem stages.  The first implemented stage
generates each engine continuation, immediately reconstructs it once, and
publishes a split-bound immutable dataset.  Later stages can open only named
folds through the public manifest before touching private row bytes.
"""

from __future__ import annotations

import json
import hashlib
import os
import stat
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .belief_contract import canonical_json_bytes
from .world_afterstate_dataset import (
    build_dataset_manifest, build_dataset_row, reopen_dataset_manifest,
    validate_dataset_manifest, validate_dataset_row_static)
from .world_afterstate_label import (
    continuation_identity, run_afterstate_continuation)
from .world_afterstate_population import (
    reopen_population_audit_manifest, validate_population_audit_manifest,
    validate_population_manifest)


DATASET_MANIFEST_NAME = "manifest.json"
DATASET_ROOT_SCHEMA = "world-afterstate-e3-dataset-root-v0"
DATASET_STAGE_AUTHORITY = {
    "scientific_training_authorized": False,
    "report_opening_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "deployment_authorized": False,
}


class WorldAfterstateControllerError(ValueError):
    """A stage request, split boundary, publication, or row drifted."""


@dataclass(frozen=True)
class DatasetBuildV0:
    manifest: dict[str, Any]
    rows: tuple[dict[str, Any], ...]


def _canonical(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("ascii"))
    except (AttributeError, UnicodeDecodeError, ValueError) as exc:
        raise WorldAfterstateControllerError(
            f"{label} is not canonical JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise WorldAfterstateControllerError(f"{label} is not canonical JSON")
    return value


def _label_task(arguments: tuple[
        str, dict[str, Any], int, int, bytes]) -> dict[str, Any]:
    freeze_sha256, group, candidate_index, replicate, audit_raw = arguments
    audit = _canonical(audit_raw, "label audit")
    identity = continuation_identity(
        experiment_id=freeze_sha256,
        state_group_id=group["state_group_id"], fold=group["fold"],
        world_occurrence=0, replicate=replicate)
    continuation = run_afterstate_continuation(audit, identity)
    return build_dataset_row(
        freeze_sha256=freeze_sha256, group=group,
        candidate_index=candidate_index, world_occurrence=0,
        replicate=replicate, audit_raw=audit_raw,
        continuation_raw=canonical_json_bytes(continuation))


def build_scientific_dataset(
        *, freeze_sha256: str,
        population_manifest: Mapping[str, Any],
        audit_materials: Mapping[str, Sequence[bytes]],
        repetitions_by_fold: Mapping[str, int], workers: int,
        wall_budget_nanoseconds: int,
        progress: Callable[[int, int], None] | None = None) -> DatasetBuildV0:
    validate_population_manifest(population_manifest)
    if type(audit_materials) is not dict \
            or isinstance(workers, bool) or not isinstance(workers, int) \
            or not 1 <= workers <= 16 \
            or isinstance(wall_budget_nanoseconds, bool) \
            or not isinstance(wall_budget_nanoseconds, int) \
            or wall_budget_nanoseconds <= 0:
        raise WorldAfterstateControllerError(
            "dataset generation request drift")
    tasks = []
    for group in population_manifest["groups"]:
        raws = audit_materials.get(group["state_group_id"])
        if type(raws) not in (list, tuple) \
                or len(raws) != group["candidate_count"]:
            raise WorldAfterstateControllerError(
                "dataset audit population drift")
        repetitions = repetitions_by_fold.get(group["fold"])
        if isinstance(repetitions, bool) or not isinstance(repetitions, int) \
                or repetitions <= 0:
            raise WorldAfterstateControllerError(
                "dataset repetition schedule drift")
        for candidate_index, audit_raw in enumerate(raws):
            if type(audit_raw) is not bytes:
                raise WorldAfterstateControllerError(
                    "dataset audit byte type drift")
            for replicate in range(repetitions):
                tasks.append((freeze_sha256, dict(group), candidate_index,
                              replicate, audit_raw))
    total = len(tasks)
    if total <= 0:
        raise WorldAfterstateControllerError("dataset task population drift")
    deadline = time.monotonic_ns() + wall_budget_nanoseconds
    rows_by_index: dict[int, dict[str, Any]] = {}
    completed = 0
    if workers == 1:
        for index, task in enumerate(tasks):
            if time.monotonic_ns() >= deadline:
                raise WorldAfterstateControllerError(
                    "dataset generation deadline expired")
            rows_by_index[index] = _label_task(task)
            completed += 1
            if time.monotonic_ns() >= deadline and completed < total:
                raise WorldAfterstateControllerError(
                    "dataset generation deadline expired")
            if progress is not None:
                progress(completed, total)
    else:
        executor = ProcessPoolExecutor(max_workers=workers)
        pending = {}
        next_index = 0
        try:
            while next_index < min(workers, total):
                future = executor.submit(_label_task, tasks[next_index])
                pending[future] = next_index
                next_index += 1
            while pending:
                remaining_ns = deadline - time.monotonic_ns()
                if remaining_ns <= 0:
                    raise WorldAfterstateControllerError(
                        "dataset generation deadline expired")
                done, _ = wait(
                    pending, timeout=remaining_ns / 1_000_000_000,
                    return_when=FIRST_COMPLETED)
                if not done:
                    raise WorldAfterstateControllerError(
                        "dataset generation deadline expired")
                for future in sorted(done, key=lambda item: pending[item]):
                    index = pending.pop(future)
                    rows_by_index[index] = future.result()
                    completed += 1
                    if progress is not None:
                        progress(completed, total)
                    if next_index < total:
                        replacement = executor.submit(
                            _label_task, tasks[next_index])
                        pending[replacement] = next_index
                        next_index += 1
        finally:
            for future in pending:
                future.cancel()
            executor.shutdown(wait=True, cancel_futures=True)
    if completed != total or time.monotonic_ns() >= deadline:
        raise WorldAfterstateControllerError(
            "dataset generation deadline expired")
    rows = [rows_by_index[index] for index in range(total)]
    manifest = build_dataset_manifest(
        freeze_sha256=freeze_sha256,
        population_manifest=population_manifest, rows=rows,
        repetitions_by_fold=repetitions_by_fold)
    return DatasetBuildV0(manifest=manifest, rows=tuple(rows))


def _write_once(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, 0o400)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish_scientific_dataset(
        target: Path, build: DatasetBuildV0, *,
        population_manifest: Mapping[str, Any]) -> None:
    if not isinstance(target, Path) or type(build) is not DatasetBuildV0:
        raise WorldAfterstateControllerError(
            "dataset publication request drift")
    validate_dataset_manifest(
        build.manifest, population_manifest=population_manifest)
    groups = {group["state_group_id"]: group
              for group in population_manifest["groups"]}
    parent = target.resolve().parent
    resolved = parent / target.name
    partial = parent / f".{target.name}.partial"
    parent.mkdir(parents=True, exist_ok=True)
    if resolved.exists() or resolved.is_symlink() \
            or partial.exists() or partial.is_symlink():
        raise WorldAfterstateControllerError(
            "dataset publication namespace occupied")
    partial.mkdir(mode=0o700)
    by_key = {(row["state_group_id"], row["candidate_index"],
               row["replicate"]): row for row in build.rows}
    try:
        for binding in build.manifest["rows"]:
            key = (binding["state_group_id"], binding["candidate_index"],
                   binding["replicate"])
            row = by_key.get(key)
            if row is None:
                raise WorldAfterstateControllerError(
                    "dataset publication row population drift")
            raw = canonical_json_bytes(row)
            if validate_dataset_row_static(
                    row, group=groups[binding["state_group_id"]]) \
                    != binding["row_sha256"] \
                    or len(raw) != binding["byte_count"] \
                    or hashlib.sha256(raw).hexdigest() \
                    != binding["external_sha256"]:
                raise WorldAfterstateControllerError(
                    "dataset publication row byte count drift")
            _write_once(partial / binding["relative_path"], raw)
        _write_once(partial / DATASET_MANIFEST_NAME,
                    canonical_json_bytes(build.manifest))
        for directory in sorted(
                (path for path in partial.rglob("*") if path.is_dir()),
                key=lambda path: len(path.parts), reverse=True):
            os.chmod(directory, 0o500)
            _fsync_directory(directory)
        _fsync_directory(partial)
        os.rename(partial, resolved)
        os.chmod(resolved, 0o500)
        _fsync_directory(resolved)
        _fsync_directory(parent)
    except BaseException:
        raise


def _sealed_manifest(path: Path) -> bytes:
    if path.is_symlink():
        raise WorldAfterstateControllerError(
            "dataset manifest path is a symlink")
    with path.open("rb") as handle:
        before = os.fstat(handle.fileno())
        raw = handle.read()
        after = os.fstat(handle.fileno())
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
            before.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
            after.st_ctime_ns) or before.st_size != len(raw) \
            or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o400 \
            or not stat.S_ISREG(before.st_mode):
        raise WorldAfterstateControllerError(
            "dataset manifest is mutable or changed while read")
    return raw


def reopen_scientific_dataset(
        root: Path, *, population_manifest: Mapping[str, Any],
        allowed_folds: Sequence[str],
        reconstruct_continuations: bool = False,
        reconstruction_workers: int = 1,
        deadline_monotonic_ns: int | None = None,
        progress=None):
    if not isinstance(root, Path) or not root.is_dir() or root.is_symlink():
        raise WorldAfterstateControllerError("dataset root identity drift")
    manifest = _canonical(
        _sealed_manifest(root / DATASET_MANIFEST_NAME), "dataset manifest")
    validate_dataset_manifest(
        manifest, population_manifest=population_manifest)
    return manifest, reopen_dataset_manifest(
        manifest, population_manifest=population_manifest,
        row_root=root, allowed_folds=allowed_folds,
        reconstruct_continuations=reconstruct_continuations,
        reconstruction_workers=reconstruction_workers,
        deadline_monotonic_ns=deadline_monotonic_ns,
        progress=progress)


def population_materials_for_dataset(population_root: Path):
    """Reopen the public/audit inputs once before any outcome generation."""
    public = _canonical(
        (population_root / "population.json").read_bytes(),
        "population manifest")
    audit = _canonical(
        (population_root / "audit-manifest.json").read_bytes(),
        "population audit manifest")
    validate_population_manifest(public)
    validate_population_audit_manifest(audit, public)
    materials = reopen_population_audit_manifest(
        audit, public, population_root / "audits")
    return public, audit, materials


__all__ = [
    "DATASET_STAGE_AUTHORITY", "DatasetBuildV0",
    "WorldAfterstateControllerError", "build_scientific_dataset",
    "population_materials_for_dataset", "publish_scientific_dataset",
    "reopen_scientific_dataset",
]
