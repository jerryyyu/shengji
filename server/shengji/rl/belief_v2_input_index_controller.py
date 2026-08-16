"""Durable bounded-memory training-input index for BELIEF-V1 V2.

The complete non-test corpus is authenticated exactly once after capture.
One round/group at a time is reduced to compact schedule rows and immutable
source locators under an in-loop deadline.  Later device, training,
calibration, and terminal stages reopen the canonical compact artifact rather
than rebuilding every model tensor before their own deadlines begin.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from .belief_artifacts import publish_exclusive_bytes, stable_read_bytes
from .belief_contract import canonical_json_bytes
from .belief_v2_controller import _stage_gate
from .belief_v2_deadline import (
    BeliefV2DeadlineError,
    publish_deadline_refusal,
    stage_deadline,
)
from .belief_v2_device_runner import host_peak_memory_bytes
from .belief_v2_freeze import V2ExecutionFreezeV1, V2PipelineAdmissionV1
from .belief_v2_progress import ProgressCallback
from .belief_v2_protocol import V2_SPLIT_COUNTS
from .belief_v2_streaming_inputs import (
    V2StreamingTrainingInputsV1,
    reopen_streaming_training_inputs,
    reopen_streaming_training_inputs_bytes,
    streaming_training_inputs_bytes,
)


INPUT_INDEX_STAGE_SCHEMA = "belief-v1-v2-training-input-index-stage-v1"
INPUT_INDEX_RESOURCE_SCHEMA = (
    "belief-v1-v2-training-input-index-resource-v1")


class BeliefV2InputIndexControllerError(ValueError):
    """An input-index slot, byte population, deadline, or resource drifted."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _resources(
        freeze: V2ExecutionFreezeV1, *, started: int, finished: int,
        cpu_nanoseconds: int, artifact_bytes: int,
        peak_host_memory_bytes: int) -> dict[str, Any]:
    wall = finished - started
    caps = freeze.resource_caps
    if type(started) is not int or type(finished) is not int \
            or not 0 <= started < finished \
            or type(cpu_nanoseconds) is not int or cpu_nanoseconds < 0 \
            or type(artifact_bytes) is not int or artifact_bytes <= 0 \
            or artifact_bytes > caps.training_bytes \
            or type(peak_host_memory_bytes) is not int \
            or peak_host_memory_bytes <= 0 \
            or peak_host_memory_bytes > caps.training_host_memory_bytes \
            or wall > caps.training_wall_seconds * 1_000_000_000:
        raise BeliefV2InputIndexControllerError(
            "V2 training input index resource cap drift")
    return {
        "schema": INPUT_INDEX_RESOURCE_SCHEMA,
        "boot_identity": freeze.runtime.boot_identity,
        "started_monotonic_nanoseconds": started,
        "finished_monotonic_nanoseconds": finished,
        "wall_nanoseconds": wall,
        "cpu_nanoseconds": cpu_nanoseconds,
        "artifact_bytes": artifact_bytes,
        "peak_host_memory_bytes": peak_host_memory_bytes,
        "retry_count": 0,
        "drop_count": 0,
    }


def _manifest(
        freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1, *, index_raw: bytes,
        inputs: V2StreamingTrainingInputsV1,
        resources: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": INPUT_INDEX_STAGE_SCHEMA,
        "freeze_sha256": freeze.sha256(),
        "admission_sha256": admission.sha256(),
        "index_filename": "index.json",
        "index_byte_count": len(index_raw),
        "index_sha256": _sha256(index_raw),
        "derived_input_sha256": inputs.sha256(),
        "derived_manifest": inputs.manifest(),
        "resources": resources,
        "contains_model_arrays": False,
        "synthetic_test_targets_opened": False,
        "human_test_targets_opened": False,
        "training_authorized_by_this_artifact": False,
        "test_split_open_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }


def run_training_input_index(
        root: Path, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1, *, repo: Path,
        review_marker: bytes, inventory: dict[str, Any],
        group_split: dict[str, Any],
        progress: ProgressCallback | None = None) -> dict[str, Any]:
    """Build and atomically publish the sole compact non-test input index."""
    _stage_gate(
        root=root, repo=repo, freeze=freeze, admission=admission,
        review_marker=review_marker)
    parent = root / "training-input-index"
    if parent.is_symlink():
        raise BeliefV2InputIndexControllerError(
            "V2 training input index parent is a symlink")
    parent.mkdir(mode=0o700, exist_ok=True)
    final = parent / "result"
    partial = parent / "result.partial"
    if final.exists() or partial.exists() \
            or final.is_symlink() or partial.is_symlink():
        raise BeliefV2InputIndexControllerError(
            "V2 training input index slot is occupied")
    partial.mkdir(mode=0o700)
    started = time.monotonic_ns()
    cpu_started = time.process_time_ns()
    deadline = stage_deadline(
        freeze, admission, stage="training", slot="input-index",
        started_monotonic_nanoseconds=started)
    split_counts = dict(V2_SPLIT_COUNTS)
    total_units = split_counts["train"] + split_counts["calibration"] \
        + freeze.human_train_group_count \
        + freeze.human_calibration_group_count \
        + freeze.human_test_group_count
    if progress is not None:
        progress(0, total_units, "index-input-sources")

    def deadline_check(phase: str, next_unit_index: int) -> None:
        try:
            deadline.check(
                phase=phase, next_unit_index=next_unit_index,
                observed_monotonic_nanoseconds=time.monotonic_ns())
        except BeliefV2DeadlineError as exc:
            publish_deadline_refusal(partial, exc.refusal)
            raise BeliefV2InputIndexControllerError(
                "V2 training input index deadline exhausted and recorded"
            ) from exc
        if progress is not None and phase == "after-unit":
            progress(next_unit_index, total_units, "index-input-sources")

    try:
        inputs = reopen_streaming_training_inputs(
            root, freeze=freeze, admission=admission,
            inventory=inventory, group_split=group_split,
            deadline_check=deadline_check)
        index_raw = streaming_training_inputs_bytes(inputs, freeze)
    except ValueError as exc:
        raise BeliefV2InputIndexControllerError(
            "V2 training input index construction refused") from exc
    deadline_check("before-seal", len(inputs.index.sources))
    publish_exclusive_bytes(partial / "index.json", index_raw)
    finished = time.monotonic_ns()
    resources = _resources(
        freeze, started=started, finished=finished,
        cpu_nanoseconds=time.process_time_ns() - cpu_started,
        artifact_bytes=len(index_raw),
        peak_host_memory_bytes=host_peak_memory_bytes())
    manifest = _manifest(
        freeze, admission, index_raw=index_raw, inputs=inputs,
        resources=resources)
    publish_exclusive_bytes(
        partial / "manifest.json", canonical_json_bytes(manifest))
    os.rename(partial, final)
    descriptor = os.open(parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    reopened, _ = reopen_training_input_index(
        final, freeze=freeze, admission=admission)
    if reopened != manifest:
        raise BeliefV2InputIndexControllerError(
            "V2 training input index post-publish drift")
    return manifest


def reopen_training_input_index(
        directory: Path, *, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1) \
        -> tuple[dict[str, Any], V2StreamingTrainingInputsV1]:
    """Reopen the canonical compact index without touching target artifacts."""
    if not isinstance(directory, Path) or directory.is_symlink() \
            or not directory.is_dir() or directory.name != "result" \
            or {path.name for path in directory.iterdir()} \
            != {"manifest.json", "index.json"}:
        raise BeliefV2InputIndexControllerError(
            "V2 training input index directory drift")
    manifest_raw = stable_read_bytes(directory / "manifest.json")
    index_raw = stable_read_bytes(directory / "index.json")
    try:
        manifest = json.loads(manifest_raw)
        inputs = reopen_streaming_training_inputs_bytes(
            index_raw, freeze=freeze)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise BeliefV2InputIndexControllerError(
            "V2 training input index raw reopen refused") from exc
    resources = manifest.get("resources") if type(manifest) is dict else None
    expected = _manifest(
        freeze, admission, index_raw=index_raw, inputs=inputs,
        resources=resources)
    caps = freeze.resource_caps
    resource_keys = {
        "schema", "boot_identity", "started_monotonic_nanoseconds",
        "finished_monotonic_nanoseconds", "wall_nanoseconds",
        "cpu_nanoseconds", "artifact_bytes", "peak_host_memory_bytes",
        "retry_count", "drop_count"}
    if type(manifest) is not dict \
            or canonical_json_bytes(manifest) != manifest_raw \
            or manifest != expected \
            or type(resources) is not dict or set(resources) != resource_keys \
            or resources["schema"] != INPUT_INDEX_RESOURCE_SCHEMA \
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
            or resources["artifact_bytes"] != len(index_raw) \
            or resources["artifact_bytes"] > caps.training_bytes \
            or type(resources["peak_host_memory_bytes"]) is not int \
            or not 0 < resources["peak_host_memory_bytes"] \
            <= caps.training_host_memory_bytes \
            or resources["wall_nanoseconds"] \
            > caps.training_wall_seconds * 1_000_000_000 \
            or resources["retry_count"] != 0 \
            or resources["drop_count"] != 0:
        raise BeliefV2InputIndexControllerError(
            "V2 training input index reconstruction drift")
    return manifest, inputs
