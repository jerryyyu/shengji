"""Durable target-blind historical-human REF-C stage for BELIEF-V1 V2."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from pathlib import Path
from typing import Any

from .belief_artifacts import (
    publish_exclusive_bytes,
    reference_external_actor_batch_bundle_bytes,
    reopen_reference_external_actor_batch_bundle,
    stable_read_bytes,
)
from .belief_contract import canonical_json_bytes
from .belief_v2_controller import _stage_gate
from .belief_v2_freeze import V2ExecutionFreezeV1, V2PipelineAdmissionV1
from .belief_v2_human_controller import (
    _bind_h0_receipts,
    _group_digest,
    _group_split,
    reopen_human_group_manifest,
)
from .belief_v2_human_corpus import reopen_human_actor_row
from .belief_v2_human_reference import (
    capture_human_ref_c_source_group,
)
from .belief_v2_progress import ProgressCallback
from .belief_v2_scoring import v2_scoring_actor


HUMAN_REFERENCE_STAGE_SCHEMA = (
    "belief-v1-v2-human-reference-group-stage-result-v1")
HUMAN_REFERENCE_RESOURCE_SCHEMA = (
    "belief-v1-v2-human-reference-group-resource-v1")
NS_PER_HOUR = 3_600_000_000_000
NS_PER_SECOND = 1_000_000_000


class BeliefV2HumanReferenceControllerError(ValueError):
    """A human REF-C source, artifact, resource, or actor binding drifted."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_sha256(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _filename(ordinal: int) -> str:
    return f"decision-{ordinal:06d}.ref.bin"


def _resource_row(
        freeze: V2ExecutionFreezeV1, *, started: int, finished: int,
        cpu_nanoseconds: int, artifact_bytes: int) -> dict[str, Any]:
    caps = freeze.resource_caps
    if type(started) is not int or type(finished) is not int \
            or not 0 <= started < finished \
            or type(cpu_nanoseconds) is not int or cpu_nanoseconds < 0 \
            or type(artifact_bytes) is not int or artifact_bytes < 0 \
            or cpu_nanoseconds > caps.reference_core_hours * NS_PER_HOUR \
            or finished - started \
            > caps.reference_wall_seconds * NS_PER_SECOND \
            or artifact_bytes > caps.reference_bytes:
        raise BeliefV2HumanReferenceControllerError(
            "V2 human reference resource cap drift")
    return {
        "schema": HUMAN_REFERENCE_RESOURCE_SCHEMA,
        "boot_identity": freeze.runtime.boot_identity,
        "started_monotonic_nanoseconds": started,
        "finished_monotonic_nanoseconds": finished,
        "wall_nanoseconds": finished - started,
        "cpu_nanoseconds": cpu_nanoseconds,
        "artifact_bytes": artifact_bytes,
        "retry_count": 0,
        "drop_count": 0,
    }


def _manifest(
        freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1, *, capture: dict[str, Any],
        replicate: str, rows: list[dict[str, Any]],
        resources: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": HUMAN_REFERENCE_STAGE_SCHEMA,
        "freeze_sha256": freeze.sha256(),
        "admission_sha256": admission.sha256(),
        "human_capture_manifest_sha256": _sha256(
            canonical_json_bytes(capture)),
        "source_sha256": capture["source_sha256"],
        "group_digest": capture["group_digest"],
        "split": capture["split"],
        "replicate": replicate,
        "decision_count": len(rows),
        "rows": rows,
        "resources": resources,
        "source_bytes_published": False,
        "source_path_published": False,
        "raw_player_identity_published": False,
        "contains_sampled_hidden_worlds": True,
        "contains_privileged_training_targets": False,
        "training_authorized_by_this_artifact": False,
        "test_open_authorized_by_this_artifact": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }


def run_human_reference_group(
        root: Path, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1, *, repo: Path,
        source_path: Path, inventory: dict[str, Any],
        group_split: dict[str, Any], replicate: str,
        review_marker: bytes,
        progress: ProgressCallback | None = None) -> dict[str, Any]:
    """Replay and publish one calibration/test human REF-C group."""
    _stage_gate(
        root=root, repo=repo, freeze=freeze, admission=admission,
        review_marker=review_marker)
    _bind_h0_receipts(freeze, inventory, group_split)
    if not isinstance(source_path, Path) or source_path.is_symlink() \
            or not source_path.is_file():
        raise BeliefV2HumanReferenceControllerError(
            "V2 human reference source shape drift")
    source_raw = stable_read_bytes(source_path)
    source_sha = _sha256(source_raw)
    group_digest = _group_digest(source_sha)
    split = _group_split(group_split, group_digest)
    if split not in {"calibration", "test"}:
        raise BeliefV2HumanReferenceControllerError(
            "V2 human reference source split is not evaluable")
    capture_directory = root / "human-capture" / f"group-{group_digest}"
    capture = reopen_human_group_manifest(
        capture_directory, freeze=freeze, admission=admission)
    total = capture["human_decision_count"]
    progress_total = max(1, total)
    if progress is not None:
        progress(0, progress_total, (
            "replay-human-reference" if total
            else "replay-human-reference-group"))
    started = time.monotonic_ns()
    cpu_started = time.process_time_ns()
    try:
        result = capture_human_ref_c_source_group(
            source_raw, source_sha256=source_sha,
            split=split, replicate=replicate)
    except ValueError as exc:
        raise BeliefV2HumanReferenceControllerError(
            "V2 human reference replay refused") from exc
    if result.replay.group_digest != group_digest \
            or result.replay.complete_round_count \
            != capture["complete_round_count"] \
            or result.replay.incomplete_round_count \
            != capture["incomplete_round_count"] \
            or result.replay.human_decision_count \
            != capture["human_decision_count"] \
            or dict(result.replay.trump_rank_counts) \
            != capture["trump_rank_counts"] \
            or dict(result.replay.attempted_channel_counts) \
            != capture["attempted_channel_counts"]:
        raise BeliefV2HumanReferenceControllerError(
            "V2 human reference differs from captured population")
    parent = root / "human-reference" / f"group-{group_digest}"
    if parent.is_symlink():
        raise BeliefV2HumanReferenceControllerError(
            "V2 human reference parent is a symlink")
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    final = parent / replicate
    partial = parent / f"{replicate}.partial"
    if final.exists() or partial.exists() \
            or final.is_symlink() or partial.is_symlink():
        raise BeliefV2HumanReferenceControllerError(
            "V2 human reference slot is occupied")
    partial.mkdir(mode=0o700)
    rows = []
    if len(result.decisions) != total:
        raise BeliefV2HumanReferenceControllerError(
            "V2 human reference progress population drift")
    for ordinal, (capture_row, decision) in enumerate(zip(
            capture["rows"], result.decisions, strict=True)):
        raw = reference_external_actor_batch_bundle_bytes(decision.batch)
        filename = _filename(ordinal)
        digest = publish_exclusive_bytes(partial / filename, raw)
        if decision.decision_key != capture_row["decision_key"] \
                or decision.round_digest != capture_row["round_digest"]:
            raise BeliefV2HumanReferenceControllerError(
                "V2 human reference decision/capture order drift")
        rows.append({
            "ordinal": ordinal,
            "decision_key": decision.decision_key,
            "round_digest": decision.round_digest,
            "trump_rank": decision.trump_rank,
            "filename": filename,
            "byte_count": len(raw),
            "bundle_sha256": digest,
            "actor_observation_sha256": decision.batch.actor.sha256(),
            "reference_manifest_sha256": decision.batch.manifest_sha256(),
            "accepted_world_count": len(decision.batch.worlds),
            "attempt_count": decision.batch.attempts,
        })
        if progress is not None:
            progress(ordinal + 1, total, "publish-human-reference")
    finished = time.monotonic_ns()
    resources = _resource_row(
        freeze, started=started, finished=finished,
        cpu_nanoseconds=time.process_time_ns() - cpu_started,
        artifact_bytes=sum(row["byte_count"] for row in rows))
    manifest = _manifest(
        freeze, admission, capture=capture, replicate=replicate,
        rows=rows, resources=resources)
    publish_exclusive_bytes(
        partial / "manifest.json", canonical_json_bytes(manifest))
    os.rename(partial, final)
    descriptor = os.open(parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    reopened = reopen_human_reference_group(
        final, freeze=freeze, admission=admission)
    if reopened != manifest:
        raise BeliefV2HumanReferenceControllerError(
            "V2 human reference post-publish drift")
    if progress is not None and total == 0:
        progress(1, 1, "human-reference-group-complete")
    return reopened


_ROW_KEYS = {
    "ordinal", "decision_key", "round_digest", "trump_rank", "filename",
    "byte_count", "bundle_sha256", "actor_observation_sha256",
    "reference_manifest_sha256", "accepted_world_count", "attempt_count",
}


def reopen_human_reference_group(
        directory: Path, *, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1) -> dict[str, Any]:
    """Reopen all human REF-C bytes and rebind each to actor-only capture."""
    if not isinstance(directory, Path) or directory.is_symlink() \
            or not directory.is_dir() or directory.parent.parent.name \
            != "human-reference" or not directory.parent.name.startswith(
                "group-"):
        raise BeliefV2HumanReferenceControllerError(
            "V2 human reference directory drift")
    raw = stable_read_bytes(directory / "manifest.json")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefV2HumanReferenceControllerError(
            "V2 human reference manifest is not JSON") from exc
    expected_keys = {
        "schema", "freeze_sha256", "admission_sha256",
        "human_capture_manifest_sha256", "source_sha256", "group_digest",
        "split", "replicate", "decision_count", "rows", "resources",
        "source_bytes_published", "source_path_published",
        "raw_player_identity_published", "contains_sampled_hidden_worlds",
        "contains_privileged_training_targets",
        "training_authorized_by_this_artifact",
        "test_open_authorized_by_this_artifact",
        "gameplay_strength_screen_authorized", "strength_claim_authorized",
        "deployment_authorized",
    }
    if type(payload) is not dict or set(payload) != expected_keys \
            or canonical_json_bytes(payload) != raw \
            or payload["schema"] != HUMAN_REFERENCE_STAGE_SCHEMA \
            or payload["freeze_sha256"] != freeze.sha256() \
            or payload["admission_sha256"] != admission.sha256() \
            or not _is_sha256(payload["source_sha256"]) \
            or not _is_sha256(payload["group_digest"]) \
            or _group_digest(payload["source_sha256"]) \
            != payload["group_digest"] \
            or directory.parent.name != f"group-{payload['group_digest']}" \
            or directory.name != payload["replicate"] \
            or payload["split"] not in {"calibration", "test"} \
            or type(payload["rows"]) is not list \
            or payload["decision_count"] != len(payload["rows"]) \
            or payload["decision_count"] < 0 \
            or payload["contains_sampled_hidden_worlds"] is not True \
            or payload["contains_privileged_training_targets"] is not False \
            or any(payload[key] is not False for key in (
                "source_bytes_published", "source_path_published",
                "raw_player_identity_published",
                "training_authorized_by_this_artifact",
                "test_open_authorized_by_this_artifact",
                "gameplay_strength_screen_authorized",
                "strength_claim_authorized", "deployment_authorized")):
        raise BeliefV2HumanReferenceControllerError(
            "V2 human reference manifest identity drift")
    capture_directory = (
        Path(freeze.evidence_root) / "human-capture"
        / f"group-{payload['group_digest']}")
    capture = reopen_human_group_manifest(
        capture_directory, freeze=freeze, admission=admission)
    if payload["human_capture_manifest_sha256"] \
            != _sha256(canonical_json_bytes(capture)) \
            or payload["source_sha256"] != capture["source_sha256"] \
            or payload["split"] != capture["split"] \
            or payload["decision_count"] != capture["human_decision_count"]:
        raise BeliefV2HumanReferenceControllerError(
            "V2 human reference/capture manifest drift")
    expected_files = {"manifest.json", *(
        _filename(index) for index in range(payload["decision_count"]))}
    if {path.name for path in directory.iterdir()} != expected_files:
        raise BeliefV2HumanReferenceControllerError(
            "V2 human reference file population drift")
    artifact_bytes = 0
    for ordinal, (row, capture_row) in enumerate(zip(
            payload["rows"], capture["rows"], strict=True)):
        if type(row) is not dict or set(row) != _ROW_KEYS \
                or row["ordinal"] != ordinal \
                or row["filename"] != _filename(ordinal) \
                or row["decision_key"] != capture_row["decision_key"] \
                or row["round_digest"] != capture_row["round_digest"] \
                or any(not _is_sha256(row[key]) for key in (
                    "decision_key", "round_digest", "bundle_sha256",
                    "actor_observation_sha256",
                    "reference_manifest_sha256")) \
                or type(row["byte_count"]) is not int \
                or row["byte_count"] <= 0 \
                or type(row["accepted_world_count"]) is not int \
                or row["accepted_world_count"] <= 0 \
                or type(row["attempt_count"]) is not int \
                or row["attempt_count"] < row["accepted_world_count"]:
            raise BeliefV2HumanReferenceControllerError(
                "V2 human reference row drift")
        path = directory / row["filename"]
        info = path.lstat()
        raw_batch = stable_read_bytes(path)
        if path.is_symlink() or not stat.S_ISREG(info.st_mode) \
                or info.st_nlink != 1 or info.st_mode & 0o222 \
                or info.st_size != row["byte_count"] \
                or len(raw_batch) != row["byte_count"] \
                or _sha256(raw_batch) != row["bundle_sha256"]:
            raise BeliefV2HumanReferenceControllerError(
                "V2 human reference selected byte drift")
        try:
            source_actor, _, metadata = reopen_human_actor_row(
                stable_read_bytes(
                    capture_directory / "actor-only"
                    / capture_row["actor_filename"]))
            scoring_actor = v2_scoring_actor(source_actor)
            batch = reopen_reference_external_actor_batch_bundle(
                raw_batch, actor=scoring_actor)
        except ValueError as exc:
            raise BeliefV2HumanReferenceControllerError(
                "V2 human reference typed reopen refused") from exc
        if metadata["decision_key"] != row["decision_key"] \
                or batch.actor.canonical_bytes() \
                != scoring_actor.canonical_bytes() \
                or batch.actor.sha256() != row["actor_observation_sha256"] \
                or batch.manifest_sha256() \
                != row["reference_manifest_sha256"] \
                or len(batch.worlds) != row["accepted_world_count"] \
                or batch.attempts != row["attempt_count"]:
            raise BeliefV2HumanReferenceControllerError(
                "V2 human reference actor/reconstruction drift")
        artifact_bytes += len(raw_batch)
    resources = payload["resources"]
    if type(resources) is not dict or set(resources) != {
            "schema", "boot_identity", "started_monotonic_nanoseconds",
            "finished_monotonic_nanoseconds", "wall_nanoseconds",
            "cpu_nanoseconds", "artifact_bytes", "retry_count",
            "drop_count"} \
            or resources["schema"] != HUMAN_REFERENCE_RESOURCE_SCHEMA \
            or resources["boot_identity"] != freeze.runtime.boot_identity \
            or type(resources["started_monotonic_nanoseconds"]) is not int \
            or type(resources["finished_monotonic_nanoseconds"]) is not int \
            or not 0 <= resources["started_monotonic_nanoseconds"] \
            < resources["finished_monotonic_nanoseconds"] \
            or resources["wall_nanoseconds"] != (
                resources["finished_monotonic_nanoseconds"]
                - resources["started_monotonic_nanoseconds"]) \
            or type(resources["cpu_nanoseconds"]) is not int \
            or resources["cpu_nanoseconds"] < 0 \
            or resources["artifact_bytes"] != artifact_bytes \
            or resources["retry_count"] != 0 \
            or resources["drop_count"] != 0:
        raise BeliefV2HumanReferenceControllerError(
            "V2 human reference resource reconstruction drift")
    caps = freeze.resource_caps
    if resources["cpu_nanoseconds"] \
            > caps.reference_core_hours * NS_PER_HOUR \
            or resources["wall_nanoseconds"] \
            > caps.reference_wall_seconds * NS_PER_SECOND \
            or resources["artifact_bytes"] > caps.reference_bytes:
        raise BeliefV2HumanReferenceControllerError(
            "V2 human reference resource cap drift")
    return payload
