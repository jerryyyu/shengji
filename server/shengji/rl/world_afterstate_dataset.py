"""Private, hash-bound E3 continuation rows for E4 training and evaluation.

Population manifests remain outcome-blind.  This module binds one exact audit
and one deterministically reopened continuation to the reviewed freeze and
population group.  Split-specific readers must name the folds they are allowed
to open before any row bytes are parsed.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .belief_contract import canonical_json_bytes
from .world_afterstate import (
    WorldAfterstateExampleV0, bind_outcome_to_afterstate,
    bind_outcome_to_preaction,
    reopen_afterstate_audit)
from .world_afterstate_evaluation import (
    EvaluationOutcomeV0, build_evaluation_outcome)
from .world_afterstate_label import reopen_afterstate_continuation
from .world_afterstate_population import (
    validate_population_group, validate_population_manifest)


DATASET_ROW_SCHEMA = "world-afterstate-e3-dataset-row-v0"
DATASET_MANIFEST_SCHEMA = "world-afterstate-e3-dataset-manifest-v0"
ALLOWED_FOLDS = ("train", "calibration", "report", "provider-audit")
DATASET_AUTHORITY = {
    "training_authorized": False,
    "report_opening_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "deployment_authorized": False,
}


class WorldAfterstateDatasetError(ValueError):
    """A private row, split, audit, continuation, or manifest drifted."""


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateDatasetError(f"{label} drift")
    return value


def _canonical_object(raw: bytes, label: str) -> dict[str, Any]:
    if type(raw) is not bytes:
        raise WorldAfterstateDatasetError(f"{label} byte type drift")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WorldAfterstateDatasetError(
            f"{label} is not canonical JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise WorldAfterstateDatasetError(f"{label} is not canonical JSON")
    return value


@dataclass(frozen=True)
class ReopenedDatasetRowV0:
    example: WorldAfterstateExampleV0
    evaluation_outcome: EvaluationOutcomeV0
    row_sha256: str
    preaction_example: WorldAfterstateExampleV0 | None = None
    row: dict[str, Any] | None = None


def build_dataset_row(
        *, freeze_sha256: str, group: Mapping[str, Any],
        candidate_index: int, world_occurrence: int, replicate: int,
        audit_raw: bytes, continuation_raw: bytes) -> dict[str, Any]:
    """Bind one raw engine terminal outcome to one reviewed successor."""
    _digest(freeze_sha256, "dataset freeze SHA-256")
    validate_population_group(group)
    if isinstance(candidate_index, bool) or not isinstance(candidate_index, int) \
            or not 0 <= candidate_index < group["candidate_count"] \
            or isinstance(world_occurrence, bool) \
            or not isinstance(world_occurrence, int) or world_occurrence != 0 \
            or isinstance(replicate, bool) or not isinstance(replicate, int) \
            or replicate < 0:
        raise WorldAfterstateDatasetError("dataset row identity drift")
    candidate = group["candidates"][candidate_index]
    audit = _canonical_object(audit_raw, "dataset audit")
    continuation = _canonical_object(
        continuation_raw, "dataset continuation")
    if _sha_bytes(audit_raw) != candidate["audit_sha256"]:
        raise WorldAfterstateDatasetError("dataset audit byte binding drift")
    _ = reopen_afterstate_audit(audit)
    if audit["successor_sha256"] != candidate["successor_sha256"] \
            or audit["attempted_action"] is None:
        raise WorldAfterstateDatasetError(
            "dataset audit successor binding drift")
    rebuilt = reopen_afterstate_continuation(audit, continuation)
    identity = rebuilt["continuation_identity"]
    if identity != {
            "schema": identity.get("schema"),
            "experiment_id": freeze_sha256,
            "state_group_id": group["state_group_id"],
            "fold": group["fold"],
            "world_occurrence": world_occurrence,
            "replicate": replicate}:
        raise WorldAfterstateDatasetError(
            "dataset continuation identity drift")
    example = bind_outcome_to_afterstate(audit, rebuilt["outcome"])
    evaluation = build_evaluation_outcome(
        group, candidate_index=candidate_index, replicate=replicate,
        outcome=rebuilt["outcome"])
    # Keep raw mechanics private and self-contained.  The public population
    # manifest sees only this row's digest.
    body = {
        "schema": DATASET_ROW_SCHEMA,
        "freeze_sha256": freeze_sha256,
        "group_sha256": group["group_sha256"],
        "state_group_id": group["state_group_id"],
        "fold": group["fold"],
        "candidate_index": candidate_index,
        "world_occurrence": world_occurrence,
        "replicate": replicate,
        "audit": audit,
        "audit_sha256": _sha_bytes(audit_raw),
        "continuation": rebuilt,
        "continuation_sha256": _sha_bytes(continuation_raw),
        "successor_sha256": example.successor_sha256,
        "signed_level_category": example.signed_level_category,
        "authority": dict(DATASET_AUTHORITY),
    }
    return {**body, "row_sha256": _sha(body)}


def reopen_dataset_row(
        value: Mapping[str, Any], *, group: Mapping[str, Any],
        allowed_folds: Sequence[str]) -> ReopenedDatasetRowV0:
    """Validate the split before parsing embedded private mechanics."""
    if type(value) is not dict or type(group) is not dict \
            or type(allowed_folds) not in (list, tuple) \
            or not allowed_folds \
            or any(fold not in ALLOWED_FOLDS for fold in allowed_folds):
        raise WorldAfterstateDatasetError("dataset reopen request drift")
    # This check intentionally precedes all access to audit/continuation.
    if value.get("fold") not in allowed_folds:
        raise WorldAfterstateDatasetError(
            "dataset split refused before private row opening")
    required = {
        "schema", "freeze_sha256", "group_sha256", "state_group_id",
        "fold", "candidate_index", "world_occurrence", "replicate",
        "audit", "audit_sha256", "continuation",
        "continuation_sha256", "successor_sha256",
        "signed_level_category", "authority", "row_sha256",
    }
    if set(value) != required or value.get("schema") != DATASET_ROW_SCHEMA \
            or value.get("authority") != DATASET_AUTHORITY:
        raise WorldAfterstateDatasetError("dataset row schema drift")
    validate_population_group(group)
    if value["group_sha256"] != group["group_sha256"] \
            or value["state_group_id"] != group["state_group_id"] \
            or value["fold"] != group["fold"]:
        raise WorldAfterstateDatasetError("dataset group binding drift")
    audit_raw = canonical_json_bytes(value["audit"])
    continuation_raw = canonical_json_bytes(value["continuation"])
    if _sha_bytes(audit_raw) != value["audit_sha256"] \
            or _sha_bytes(continuation_raw) != value["continuation_sha256"]:
        raise WorldAfterstateDatasetError("dataset embedded byte binding drift")
    expected = build_dataset_row(
        freeze_sha256=value["freeze_sha256"], group=group,
        candidate_index=value["candidate_index"],
        world_occurrence=value["world_occurrence"],
        replicate=value["replicate"], audit_raw=audit_raw,
        continuation_raw=continuation_raw)
    if canonical_json_bytes(expected) != canonical_json_bytes(value):
        raise WorldAfterstateDatasetError(
            "dataset row reconstruction drift")
    example = bind_outcome_to_afterstate(
        value["audit"], value["continuation"]["outcome"])
    preaction_example = bind_outcome_to_preaction(
        value["audit"], value["continuation"]["outcome"])
    evaluation = build_evaluation_outcome(
        group, candidate_index=value["candidate_index"],
        replicate=value["replicate"],
        outcome=value["continuation"]["outcome"])
    return ReopenedDatasetRowV0(
        example=example, preaction_example=preaction_example,
        evaluation_outcome=evaluation, row_sha256=value["row_sha256"],
        row=dict(value))


def reopen_dataset_row_static(
        value: Mapping[str, Any], *, group: Mapping[str, Any],
        allowed_folds: Sequence[str]) -> ReopenedDatasetRowV0:
    """Reopen sealed row bytes without rerunning the costly continuation.

    Dataset generation already reruns and byte-compares each engine
    continuation before publication.  Training and held-out scoring consume
    the resulting immutable, manifest-bound row through this path.  A named
    independent verifier can still call :func:`reopen_dataset_row` to rerun
    the complete continuation later.
    """
    if type(value) is not dict or type(group) is not dict \
            or type(allowed_folds) not in (list, tuple) \
            or not allowed_folds \
            or any(fold not in ALLOWED_FOLDS for fold in allowed_folds):
        raise WorldAfterstateDatasetError("dataset reopen request drift")
    if value.get("fold") not in allowed_folds:
        raise WorldAfterstateDatasetError(
            "dataset split refused before private row opening")
    validate_dataset_row_static(value, group=group)
    outcome = value["continuation"]["outcome"]
    example = bind_outcome_to_afterstate(value["audit"], outcome)
    preaction_example = bind_outcome_to_preaction(value["audit"], outcome)
    evaluation = build_evaluation_outcome(
        group, candidate_index=value["candidate_index"],
        replicate=value["replicate"], outcome=outcome)
    return ReopenedDatasetRowV0(
        example=example, preaction_example=preaction_example,
        evaluation_outcome=evaluation, row_sha256=value["row_sha256"],
        row=dict(value))


def validate_dataset_row_static(
        value: Mapping[str, Any], *, group: Mapping[str, Any]) -> str:
    """Validate a just-built row without rerunning its costly continuation."""
    required = {
        "schema", "freeze_sha256", "group_sha256", "state_group_id",
        "fold", "candidate_index", "world_occurrence", "replicate",
        "audit", "audit_sha256", "continuation", "continuation_sha256",
        "successor_sha256", "signed_level_category", "authority",
        "row_sha256",
    }
    if type(value) is not dict or set(value) != required \
            or value.get("schema") != DATASET_ROW_SCHEMA \
            or value.get("authority") != DATASET_AUTHORITY:
        raise WorldAfterstateDatasetError("dataset row schema drift")
    validate_population_group(group)
    candidate = value.get("candidate_index")
    replicate = value.get("replicate")
    if value.get("group_sha256") != group["group_sha256"] \
            or value.get("state_group_id") != group["state_group_id"] \
            or value.get("fold") != group["fold"] \
            or isinstance(candidate, bool) or not isinstance(candidate, int) \
            or not 0 <= candidate < group["candidate_count"] \
            or value.get("world_occurrence") != 0 \
            or isinstance(replicate, bool) or not isinstance(replicate, int) \
            or replicate < 0:
        raise WorldAfterstateDatasetError("dataset row identity drift")
    audit_raw = canonical_json_bytes(value.get("audit"))
    continuation_raw = canonical_json_bytes(value.get("continuation"))
    if _sha_bytes(audit_raw) != value.get("audit_sha256") \
            or _sha_bytes(continuation_raw) \
            != value.get("continuation_sha256") \
            or value["audit_sha256"] \
            != group["candidates"][candidate]["audit_sha256"] \
            or value.get("successor_sha256") \
            != group["candidates"][candidate]["successor_sha256"] \
            or value.get("signed_level_category") \
            != value.get("continuation", {}).get(
                "outcome", {}).get("signed_level_category"):
        raise WorldAfterstateDatasetError(
            "dataset row static byte binding drift")
    identity = value.get("continuation", {}).get("continuation_identity")
    if identity != {
            "schema": identity.get("schema") if type(identity) is dict else None,
            "experiment_id": value.get("freeze_sha256"),
            "state_group_id": group["state_group_id"],
            "fold": group["fold"], "world_occurrence": 0,
            "replicate": replicate}:
        raise WorldAfterstateDatasetError(
            "dataset row static continuation identity drift")
    body = {key: item for key, item in value.items()
            if key != "row_sha256"}
    if value.get("row_sha256") != _sha(body):
        raise WorldAfterstateDatasetError(
            "dataset row static reconstruction drift")
    return value["row_sha256"]


def build_dataset_manifest(
        *, freeze_sha256: str, population_manifest: Mapping[str, Any],
        rows: Sequence[Mapping[str, Any]],
        repetitions_by_fold: Mapping[str, int]) -> dict[str, Any]:
    _digest(freeze_sha256, "dataset manifest freeze SHA-256")
    validate_population_manifest(population_manifest)
    if type(rows) not in (list, tuple) or type(repetitions_by_fold) is not dict \
            or set(repetitions_by_fold) != set(ALLOWED_FOLDS) \
            or any(isinstance(value, bool) or not isinstance(value, int)
                   or value <= 0 for value in repetitions_by_fold.values()):
        raise WorldAfterstateDatasetError("dataset manifest population drift")
    group_map = {group["state_group_id"]: group
                 for group in population_manifest["groups"]}
    expected_keys = {
        (group["state_group_id"], candidate, replicate)
        for group in population_manifest["groups"]
        for candidate in range(group["candidate_count"])
        for replicate in range(repetitions_by_fold[group["fold"]])
    }
    seen = set()
    row_bindings = []
    fold_counts = Counter()
    for row in rows:
        if type(row) is not dict:
            raise WorldAfterstateDatasetError("dataset manifest row type drift")
        group = group_map.get(row.get("state_group_id"))
        if group is None:
            raise WorldAfterstateDatasetError("dataset manifest foreign group")
        row_sha256 = validate_dataset_row_static(row, group=group)
        key = (group["state_group_id"], row["candidate_index"],
               row["replicate"])
        if row["freeze_sha256"] != freeze_sha256 or key in seen:
            raise WorldAfterstateDatasetError(
                "dataset manifest duplicate/freeze drift")
        seen.add(key)
        fold_counts[group["fold"]] += 1
        row_bindings.append({
            "state_group_id": group["state_group_id"],
            "fold": group["fold"],
            "candidate_index": row["candidate_index"],
            "replicate": row["replicate"],
            "relative_path": (
                f"rows/{group['fold']}/{group['state_group_id']}/"
                f"{row['candidate_index']:03d}/{row['replicate']:03d}.json"),
            "byte_count": len(canonical_json_bytes(dict(row))),
            "external_sha256": _sha_bytes(
                canonical_json_bytes(dict(row))),
            "row_sha256": row_sha256,
        })
    if seen != expected_keys:
        raise WorldAfterstateDatasetError(
            "dataset manifest incomplete row population")
    ordered = sorted(row_bindings, key=lambda row: (
        row["state_group_id"], row["candidate_index"], row["replicate"]))
    body = {
        "schema": DATASET_MANIFEST_SCHEMA,
        "freeze_sha256": freeze_sha256,
        "population_manifest_sha256": population_manifest["manifest_sha256"],
        "row_count": len(ordered),
        "fold_row_counts": dict(sorted(fold_counts.items())),
        "repetitions_by_fold": dict(repetitions_by_fold),
        "rows": ordered,
        "contains_private_complete_worlds": True,
        "outcomes_opened": True,
        "authority": dict(DATASET_AUTHORITY),
    }
    return {**body, "manifest_sha256": _sha(body)}


def validate_dataset_manifest(
        value: Mapping[str, Any], *,
        population_manifest: Mapping[str, Any]) -> None:
    validate_population_manifest(population_manifest)
    required = {
        "schema", "freeze_sha256", "population_manifest_sha256",
        "row_count", "fold_row_counts", "repetitions_by_fold", "rows",
        "contains_private_complete_worlds", "outcomes_opened", "authority",
        "manifest_sha256",
    }
    if type(value) is not dict or set(value) != required \
            or value.get("schema") != DATASET_MANIFEST_SCHEMA \
            or value.get("population_manifest_sha256") \
            != population_manifest["manifest_sha256"] \
            or value.get("contains_private_complete_worlds") is not True \
            or value.get("outcomes_opened") is not True \
            or value.get("authority") != DATASET_AUTHORITY:
        raise WorldAfterstateDatasetError("dataset manifest identity drift")
    _digest(value.get("freeze_sha256"), "dataset freeze SHA-256")
    _digest(value.get("manifest_sha256"), "dataset manifest SHA-256")
    repetitions = value.get("repetitions_by_fold")
    rows = value.get("rows")
    if type(repetitions) is not dict or set(repetitions) != set(ALLOWED_FOLDS) \
            or any(isinstance(item, bool) or not isinstance(item, int)
                   or item <= 0 for item in repetitions.values()) \
            or type(rows) is not list:
        raise WorldAfterstateDatasetError(
            "dataset manifest population drift")
    groups = {group["state_group_id"]: group
              for group in population_manifest["groups"]}
    seen = set()
    fold_counts = Counter()
    previous = None
    for row in rows:
        if type(row) is not dict or set(row) != {
                "state_group_id", "fold", "candidate_index", "replicate",
                "relative_path", "byte_count", "external_sha256",
                "row_sha256"}:
            raise WorldAfterstateDatasetError("dataset manifest row drift")
        group = groups.get(row["state_group_id"])
        candidate = row["candidate_index"]
        replicate = row["replicate"]
        key = (row["state_group_id"], candidate, replicate)
        expected_path = (
            f"rows/{group['fold']}/{row['state_group_id']}/"
            f"{candidate:03d}/{replicate:03d}.json") if group else None
        if group is None or row["fold"] != group["fold"] \
                or isinstance(candidate, bool) \
                or not isinstance(candidate, int) \
                or not 0 <= candidate < group["candidate_count"] \
                or isinstance(replicate, bool) \
                or not isinstance(replicate, int) \
                or not 0 <= replicate < repetitions[group["fold"]] \
                or key in seen or (previous is not None and key <= previous) \
                or row["relative_path"] != expected_path \
                or isinstance(row["byte_count"], bool) \
                or not isinstance(row["byte_count"], int) \
                or row["byte_count"] <= 0:
            raise WorldAfterstateDatasetError(
                "dataset manifest row identity drift")
        _digest(row["external_sha256"], "dataset external SHA-256")
        _digest(row["row_sha256"], "dataset row SHA-256")
        seen.add(key)
        previous = key
        fold_counts[group["fold"]] += 1
    expected = {
        (group["state_group_id"], candidate, replicate)
        for group in population_manifest["groups"]
        for candidate in range(group["candidate_count"])
        for replicate in range(repetitions[group["fold"]])
    }
    body = {key: item for key, item in value.items()
            if key != "manifest_sha256"}
    if seen != expected or value.get("row_count") != len(rows) \
            or value.get("fold_row_counts") \
            != dict(sorted(fold_counts.items())) \
            or value["manifest_sha256"] != _sha(body):
        raise WorldAfterstateDatasetError(
            "dataset manifest reconstruction drift")


def _sealed_row_read(path: Path) -> bytes:
    if path.is_symlink():
        raise WorldAfterstateDatasetError("dataset row path is a symlink")
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            raw = handle.read()
            after = os.fstat(handle.fileno())
    except OSError as exc:
        raise WorldAfterstateDatasetError("dataset row cannot be read") from exc
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
            before.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
            after.st_ctime_ns) or before.st_size != len(raw) \
            or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o400 \
            or not stat.S_ISREG(before.st_mode):
        raise WorldAfterstateDatasetError(
            "dataset row is mutable or changed while read")
    return raw


def _reopen_row_task(arguments):
    row, group, allowed_folds = arguments
    return reopen_dataset_row(
        row, group=group, allowed_folds=allowed_folds)


def reopen_dataset_manifest(
        value: Mapping[str, Any], *, population_manifest: Mapping[str, Any],
        row_root: Path, allowed_folds: Sequence[str],
        reconstruct_continuations: bool = False,
        reconstruction_workers: int = 1,
        deadline_monotonic_ns: int | None = None,
        progress=None) \
        -> tuple[tuple[dict[str, Any], ReopenedDatasetRowV0], ...]:
    """Check each fold in the public manifest before opening selected rows."""
    validate_dataset_manifest(value, population_manifest=population_manifest)
    if type(allowed_folds) not in (list, tuple) or not allowed_folds \
            or len(set(allowed_folds)) != len(allowed_folds) \
            or any(fold not in ALLOWED_FOLDS for fold in allowed_folds) \
            or not isinstance(row_root, Path) or not row_root.is_dir() \
            or row_root.is_symlink() \
            or type(reconstruct_continuations) is not bool \
            or isinstance(reconstruction_workers, bool) \
            or not isinstance(reconstruction_workers, int) \
            or not 1 <= reconstruction_workers <= 16 \
            or deadline_monotonic_ns is not None and (
                isinstance(deadline_monotonic_ns, bool)
                or not isinstance(deadline_monotonic_ns, int)
                or deadline_monotonic_ns <= 0):
        raise WorldAfterstateDatasetError(
            "dataset manifest reopen request drift")
    groups = {group["state_group_id"]: group
              for group in population_manifest["groups"]}
    selected = [binding for binding in value["rows"]
                if binding["fold"] in allowed_folds]

    def load(index):
        if deadline_monotonic_ns is not None \
                and time.monotonic_ns() >= deadline_monotonic_ns:
            raise WorldAfterstateDatasetError(
                "dataset reconstruction deadline expired")
        binding = selected[index]
        # This public fold check intentionally happens before path resolution,
        # stat, read, JSON parse, or access to the private row payload.
        path = row_root / binding["relative_path"]
        raw = _sealed_row_read(path)
        if len(raw) != binding["byte_count"] \
                or _sha_bytes(raw) != binding["external_sha256"]:
            raise WorldAfterstateDatasetError(
                "dataset manifest row byte binding drift")
        row = _canonical_object(raw, "dataset row")
        return binding, row, groups[binding["state_group_id"]]

    total = len(selected)
    if not reconstruct_continuations or reconstruction_workers == 1:
        result = []
        for index in range(total):
            binding, row, group = load(index)
            opener = (reopen_dataset_row if reconstruct_continuations
                      else reopen_dataset_row_static)
            reopened = opener(
                row, group=group, allowed_folds=allowed_folds)
            result.append((dict(binding), reopened))
            if progress is not None:
                progress(len(result), total)
        return tuple(result)

    rows_by_index = {}
    executor = ProcessPoolExecutor(max_workers=reconstruction_workers)
    pending = {}
    next_index = 0
    try:
        while next_index < min(reconstruction_workers, total):
            binding, row, group = load(next_index)
            future = executor.submit(
                _reopen_row_task, (row, group, tuple(allowed_folds)))
            pending[future] = (next_index, binding)
            next_index += 1
        while pending:
            timeout = None
            if deadline_monotonic_ns is not None:
                remaining = deadline_monotonic_ns - time.monotonic_ns()
                if remaining <= 0:
                    raise WorldAfterstateDatasetError(
                        "dataset reconstruction deadline expired")
                timeout = remaining / 1_000_000_000
            done, _ = wait(
                pending, timeout=timeout, return_when=FIRST_COMPLETED)
            if not done:
                raise WorldAfterstateDatasetError(
                    "dataset reconstruction deadline expired")
            for future in sorted(done, key=lambda item: pending[item][0]):
                index, binding = pending.pop(future)
                rows_by_index[index] = (dict(binding), future.result())
                if progress is not None:
                    progress(len(rows_by_index), total)
                if next_index < total:
                    next_binding, row, group = load(next_index)
                    replacement = executor.submit(
                        _reopen_row_task,
                        (row, group, tuple(allowed_folds)))
                    pending[replacement] = (next_index, next_binding)
                    next_index += 1
    finally:
        for future in pending:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)
    if len(rows_by_index) != total:
        raise WorldAfterstateDatasetError(
            "dataset reconstruction row population drift")
    return tuple(rows_by_index[index] for index in range(total))


__all__ = [
    "ALLOWED_FOLDS", "DATASET_AUTHORITY", "DATASET_MANIFEST_SCHEMA",
    "DATASET_ROW_SCHEMA", "ReopenedDatasetRowV0",
    "WorldAfterstateDatasetError", "build_dataset_manifest",
    "build_dataset_row", "reopen_dataset_manifest", "reopen_dataset_row",
    "reopen_dataset_row_static", "validate_dataset_manifest",
    "validate_dataset_row_static",
]
