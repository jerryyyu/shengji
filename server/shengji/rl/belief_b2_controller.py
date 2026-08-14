"""Durable stage mechanics for the reviewed BELIEF-V1 B2 controller.

Each capture lane owns exactly 256 frozen rounds.  It publishes into a fresh
partial directory, seals each separated compact round bundle, seals a closed
lane manifest, then atomically renames the directory.  Reopening validates the
entire file population and every nested actor/target byte before accepting the
lane.  There is no retry, result scoring, test opening, sampler, training,
strength claim, or deployment surface in this stage.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

import torch

from .belief_artifacts import (
    capture_bundle_bytes,
    publish_exclusive_bytes,
    reopen_capture_bundle,
    reference_round_bundle_bytes,
    reopen_reference_round_bundle,
    checkpoint_bundle_bytes,
    reopen_checkpoint_bundle,
    reopen_epoch_receipt,
    stable_read_bytes,
)
from .belief_b2_execution import (
    B2ExecutionDesignV1,
    B2PipelineAdmissionV1,
    BeliefB2ExecutionError,
    validate_execution_design,
    validate_pipeline_admission,
)
from .belief_b2_protocol import (
    B2_CAPTURE_LANES,
    B2_ROUNDS_PER_LANE,
    CAPTURE_BYTE_CAP,
    CAPTURE_CORE_HOUR_CAP,
    CAPTURE_WALL_SECOND_CAP,
    REFERENCE_BYTE_CAP,
    REFERENCE_CORE_HOUR_CAP,
    REFERENCE_WALL_SECOND_CAP,
    B2_REFERENCE_REPLICATES,
    TRAIN_BATCH_DECISION_CAP,
    TRAIN_BYTE_CAP,
    TRAIN_DEVICE_HOUR_CAP,
    TRAIN_MAX_EPOCHS,
    TRAIN_WALL_SECOND_CAP,
    b2_split_round_seeds,
    b2_round_seeds,
    capture_lane,
    champion_policy_seeds,
    protocol_sha256,
)
from .belief_capture import (
    CHAMPION_POLICY,
    capture_champion_round,
    captured_round_artifacts,
    public_transcript_bytes,
    reopen_captured_round_artifacts,
)
from .belief_checkpoint import (
    build_model_checkpoint,
    reopen_model_checkpoint,
)
from .belief_cohort import COHORT_SEEDS
from .belief_contract import canonical_json_bytes
from .belief_corpus import split_for_round_seed
from .belief_population import population_round_from_artifacts
from .belief_refc_capture import capture_champion_round_with_ref_c
from .belief_controls import (
    LABEL_PERMUTATION_CONTROL,
    build_control_example,
    collate_control_examples,
)
from .belief_model import new_from_scratch_model
from .belief_trainer import (
    evaluate_calibration_cohort_stream_nanonats,
    model_state_sha256,
    new_b2_optimizer,
    train_cohort_epoch_stream,
)
from .belief_training import (
    build_training_example,
    collate_training_examples,
)
from .belief_training_schedule import (
    ordered_round_seeds_for_epoch,
    select_common_epoch,
)


CAPTURE_LANE_SCHEMA = "belief-v1-b2-capture-lane-result-v1"
REFERENCE_LANE_SCHEMA = "belief-v1-b2-reference-lane-result-v1"
TRAINING_COHORT_SCHEMA = "belief-v1-b2-training-cohort-result-v1"
TRAINING_KINDS = ("candidate", LABEL_PERMUTATION_CONTROL)
NS_PER_SECOND = 1_000_000_000
NS_PER_HOUR = 3600 * NS_PER_SECOND


class BeliefB2ControllerError(ValueError):
    """A B2 stage namespace, workload, or output artifact drifted."""


def _reject_number(value: str) -> None:
    raise BeliefB2ControllerError(
        f"controller artifact contains invalid number {value}")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise BeliefB2ControllerError(
                "controller artifact has duplicate JSON key")
        result[key] = value
    return result


def _strict_json(raw: bytes, *, label: str) -> dict[str, Any]:
    if type(raw) is not bytes or not raw:
        raise BeliefB2ControllerError(f"{label} bytes are empty")
    try:
        payload = json.loads(
            raw.decode("ascii"), object_pairs_hook=_strict_object,
            parse_float=_reject_number, parse_constant=_reject_number)
    except BeliefB2ControllerError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefB2ControllerError(f"{label} is not strict JSON") from exc
    if type(payload) is not dict or canonical_json_bytes(payload) != raw:
        raise BeliefB2ControllerError(f"{label} is not canonical JSON")
    return payload


def _is_sha256(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _byte_stream_sha256(rows: tuple[bytes, ...]) -> str:
    if type(rows) is not tuple or not rows:
        raise BeliefB2ControllerError("controller byte stream is empty")
    digest = hashlib.sha256()
    for raw in rows:
        if type(raw) is not bytes or not raw:
            raise BeliefB2ControllerError("controller byte stream drift")
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def capture_lane_seeds(lane: int) -> tuple[int, ...]:
    if type(lane) is not int or lane not in range(B2_CAPTURE_LANES):
        raise BeliefB2ControllerError("capture lane is invalid")
    result = tuple(seed for seed in b2_round_seeds()
                   if capture_lane(seed) == lane)
    if len(result) != B2_ROUNDS_PER_LANE:
        raise BeliefB2ControllerError("capture lane population drift")
    return result


def _round_filename(seed: int) -> str:
    return f"round-{seed}.bin"


def _fsync_parent(path: Path) -> None:
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _lane_manifest(
        design: B2ExecutionDesignV1,
        admission: B2PipelineAdmissionV1, *, lane: int,
        rows: list[dict[str, Any]], wall_nanoseconds: int,
        cpu_nanoseconds: int, started_monotonic_nanoseconds: int,
        finished_monotonic_nanoseconds: int) -> dict[str, Any]:
    return {
        "schema": CAPTURE_LANE_SCHEMA,
        "protocol_sha256": protocol_sha256(),
        "design_sha256": design.sha256(),
        "admission_sha256": admission.sha256(),
        "lane": lane,
        "round_count": len(rows),
        "rounds": rows,
        "resources": {
            "boot_identity": design.runtime.boot_identity,
            "started_monotonic_nanoseconds": started_monotonic_nanoseconds,
            "finished_monotonic_nanoseconds": finished_monotonic_nanoseconds,
            "wall_nanoseconds": wall_nanoseconds,
            "cpu_nanoseconds": cpu_nanoseconds,
            "artifact_bytes": sum(row["byte_count"] for row in rows),
            "retry_count": 0,
            "drop_count": 0,
        },
        "contains_round_outcomes": False,
        "contains_privileged_targets": True,
        "runtime_input": False,
        "reference_generation_authorized": False,
        "training_authorized": False,
        "test_split_open_authorized": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }


def run_capture_lane(
        root: Path, design: B2ExecutionDesignV1,
        admission: B2PipelineAdmissionV1, *, lane: int,
        review_marker: bytes) -> dict[str, Any]:
    """Execute and atomically publish one exact no-retry capture lane."""
    validate_execution_design(design)
    try:
        validate_pipeline_admission(
            design, admission, review_marker=review_marker)
    except BeliefB2ExecutionError as exc:
        raise BeliefB2ControllerError("capture admission refused") from exc
    if not isinstance(root, Path) or root != Path(design.evidence_root) \
            or root.is_symlink() or not root.is_dir():
        raise BeliefB2ControllerError("capture evidence root drift")
    seeds = capture_lane_seeds(lane)
    parent = root / "capture"
    if parent.is_symlink():
        raise BeliefB2ControllerError("capture parent is a symlink")
    parent.mkdir(mode=0o700, exist_ok=True)
    if not parent.is_dir():
        raise BeliefB2ControllerError("capture parent shape drift")
    final = parent / f"lane-{lane:02d}"
    partial = parent / f"lane-{lane:02d}.partial"
    if final.exists() or partial.exists() \
            or final.is_symlink() or partial.is_symlink():
        raise BeliefB2ControllerError("capture lane slot is occupied")
    partial.mkdir(mode=0o700)
    start_wall = time.monotonic_ns()
    start_cpu = time.process_time_ns()
    rows = []
    for seed in seeds:
        captured = capture_champion_round(
            seed, champion_policy_seeds(seed))
        artifacts = captured_round_artifacts(captured)
        raw = capture_bundle_bytes(artifacts)
        digest = publish_exclusive_bytes(
            partial / _round_filename(seed), raw)
        binding = population_round_from_artifacts(artifacts)
        rows.append({
            "round_seed": seed,
            "filename": _round_filename(seed),
            "byte_count": len(raw),
            "bundle_sha256": digest,
            "capture_manifest_sha256": (
                binding.capture_manifest_sha256),
            "public_transcript_sha256": (
                binding.public_transcript_sha256),
            "actor_stream_sha256": binding.actor_stream_sha256,
            "privileged_target_stream_sha256": (
                binding.privileged_target_stream_sha256),
            "decision_count": binding.decision_count,
        })
    finish_wall = time.monotonic_ns()
    wall = finish_wall - start_wall
    cpu = time.process_time_ns() - start_cpu
    manifest = _lane_manifest(
        design, admission, lane=lane, rows=rows,
        wall_nanoseconds=wall, cpu_nanoseconds=cpu,
        started_monotonic_nanoseconds=start_wall,
        finished_monotonic_nanoseconds=finish_wall)
    publish_exclusive_bytes(
        partial / "manifest.json", canonical_json_bytes(manifest))
    os.rename(partial, final)
    _fsync_parent(final)
    reopened = reopen_capture_lane(
        final, design=design, admission=admission, lane=lane)
    if reopened != manifest:
        raise BeliefB2ControllerError("capture lane post-publish drift")
    return reopened


def reopen_capture_lane(
        directory: Path, *, design: B2ExecutionDesignV1,
        admission: B2PipelineAdmissionV1, lane: int) -> dict[str, Any]:
    """Reopen all 256 separated round bundles and the closed lane manifest."""
    validate_execution_design(design)
    if type(admission) is not B2PipelineAdmissionV1 \
            or not isinstance(directory, Path) or directory.is_symlink() \
            or not directory.is_dir() or directory.name != f"lane-{lane:02d}":
        raise BeliefB2ControllerError("capture lane directory drift")
    seeds = capture_lane_seeds(lane)
    expected_names = {"manifest.json", *(_round_filename(seed)
                                          for seed in seeds)}
    if {path.name for path in directory.iterdir()} != expected_names:
        raise BeliefB2ControllerError("capture lane file population drift")
    payload = _strict_json(
        stable_read_bytes(directory / "manifest.json"),
        label="capture lane manifest")
    expected_keys = {
        "schema", "protocol_sha256", "design_sha256",
        "admission_sha256", "lane", "round_count", "rounds",
        "resources", "contains_round_outcomes",
        "contains_privileged_targets", "runtime_input",
        "reference_generation_authorized", "training_authorized",
        "test_split_open_authorized",
        "gameplay_strength_screen_authorized", "strength_claim_authorized",
        "deployment_authorized"}
    if set(payload) != expected_keys \
            or payload["schema"] != CAPTURE_LANE_SCHEMA \
            or payload["protocol_sha256"] != protocol_sha256() \
            or payload["design_sha256"] != design.sha256() \
            or payload["admission_sha256"] != admission.sha256() \
            or payload["lane"] != lane \
            or payload["round_count"] != B2_ROUNDS_PER_LANE \
            or type(payload["rounds"]) is not list \
            or len(payload["rounds"]) != B2_ROUNDS_PER_LANE \
            or payload["contains_round_outcomes"] is not False \
            or payload["contains_privileged_targets"] is not True \
            or payload["runtime_input"] is not False \
            or any(payload[key] is not False for key in (
                "reference_generation_authorized", "training_authorized",
                "test_split_open_authorized",
                "gameplay_strength_screen_authorized",
                "strength_claim_authorized", "deployment_authorized")):
        raise BeliefB2ControllerError("capture lane manifest identity drift")
    actual_rows = []
    for seed, row in zip(seeds, payload["rounds"], strict=True):
        if type(row) is not dict or set(row) != {
                "round_seed", "filename", "byte_count", "bundle_sha256",
                "capture_manifest_sha256", "public_transcript_sha256",
                "actor_stream_sha256", "privileged_target_stream_sha256",
                "decision_count"} \
                or row["round_seed"] != seed \
                or row["filename"] != _round_filename(seed):
            raise BeliefB2ControllerError("capture round row drift")
        raw = stable_read_bytes(directory / row["filename"])
        if row["byte_count"] != len(raw) \
                or row["bundle_sha256"] != hashlib.sha256(raw).hexdigest():
            raise BeliefB2ControllerError("capture round byte binding drift")
        artifacts = reopen_capture_bundle(raw)
        captured = reopen_captured_round_artifacts(artifacts)
        binding = population_round_from_artifacts(artifacts)
        if captured.round_seed != seed:
            raise BeliefB2ControllerError("capture round seed drift")
        actual_rows.append({
            "round_seed": seed, "filename": row["filename"],
            "byte_count": len(raw),
            "bundle_sha256": hashlib.sha256(raw).hexdigest(),
            "capture_manifest_sha256": binding.capture_manifest_sha256,
            "public_transcript_sha256": binding.public_transcript_sha256,
            "actor_stream_sha256": binding.actor_stream_sha256,
            "privileged_target_stream_sha256": (
                binding.privileged_target_stream_sha256),
            "decision_count": binding.decision_count,
        })
    resources = payload["resources"]
    if type(resources) is not dict or set(resources) != {
            "boot_identity", "started_monotonic_nanoseconds",
            "finished_monotonic_nanoseconds", "wall_nanoseconds",
            "cpu_nanoseconds", "artifact_bytes",
            "retry_count", "drop_count"} \
            or resources["boot_identity"] != design.runtime.boot_identity \
            or any(type(resources[name]) is not int or resources[name] < 0
                   for name in ("wall_nanoseconds", "cpu_nanoseconds",
                                "artifact_bytes", "retry_count",
                                "drop_count", "started_monotonic_nanoseconds",
                                "finished_monotonic_nanoseconds")) \
            or resources["finished_monotonic_nanoseconds"] \
            - resources["started_monotonic_nanoseconds"] \
            != resources["wall_nanoseconds"] \
            or resources["wall_nanoseconds"] <= 0 \
            or resources["cpu_nanoseconds"] <= 0 \
            or resources["artifact_bytes"] != sum(
                row["byte_count"] for row in actual_rows) \
            or resources["retry_count"] != 0 \
            or resources["drop_count"] != 0 \
            or resources["wall_nanoseconds"] \
            > CAPTURE_WALL_SECOND_CAP * NS_PER_SECOND \
            or resources["cpu_nanoseconds"] \
            > CAPTURE_CORE_HOUR_CAP * NS_PER_HOUR \
            or resources["artifact_bytes"] > CAPTURE_BYTE_CAP:
        raise BeliefB2ControllerError("capture lane resource drift")
    expected = _lane_manifest(
        design, admission, lane=lane, rows=actual_rows,
        wall_nanoseconds=resources["wall_nanoseconds"],
        cpu_nanoseconds=resources["cpu_nanoseconds"],
        started_monotonic_nanoseconds=resources[
            "started_monotonic_nanoseconds"],
        finished_monotonic_nanoseconds=resources[
            "finished_monotonic_nanoseconds"])
    if canonical_json_bytes(expected) != canonical_json_bytes(payload):
        raise BeliefB2ControllerError("capture lane reconstruction drift")
    return payload


def reopen_capture_lane_public_manifest(
        directory: Path, *, design: B2ExecutionDesignV1,
        admission: B2PipelineAdmissionV1, lane: int) -> dict[str, Any]:
    """Authenticate a sealed lane without opening any round bundle bytes."""
    validate_execution_design(design)
    seeds = capture_lane_seeds(lane)
    expected_names = {"manifest.json", *(_round_filename(seed)
                                          for seed in seeds)}
    if type(admission) is not B2PipelineAdmissionV1 \
            or directory.is_symlink() or not directory.is_dir() \
            or directory.name != f"lane-{lane:02d}" \
            or {path.name for path in directory.iterdir()} != expected_names:
        raise BeliefB2ControllerError(
            "public capture lane population drift")
    for seed in seeds:
        path = directory / _round_filename(seed)
        info = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(info.st_mode) \
                or info.st_nlink != 1 or info.st_mode & 0o222:
            raise BeliefB2ControllerError(
                "public capture bundle shape drift")
    payload = _strict_json(stable_read_bytes(
        directory / "manifest.json"), label="public capture lane manifest")
    if set(payload) != {
            "schema", "protocol_sha256", "design_sha256",
            "admission_sha256", "lane", "round_count", "rounds",
            "resources", "contains_round_outcomes",
            "contains_privileged_targets", "runtime_input",
            "reference_generation_authorized", "training_authorized",
            "test_split_open_authorized",
            "gameplay_strength_screen_authorized",
            "strength_claim_authorized", "deployment_authorized"} \
            or payload["schema"] != CAPTURE_LANE_SCHEMA \
            or payload["protocol_sha256"] != protocol_sha256() \
            or payload["design_sha256"] != design.sha256() \
            or payload["admission_sha256"] != admission.sha256() \
            or payload["lane"] != lane \
            or payload["round_count"] != len(seeds) \
            or type(payload["rounds"]) is not list \
            or len(payload["rounds"]) != len(seeds) \
            or payload["contains_round_outcomes"] is not False \
            or payload["contains_privileged_targets"] is not True \
            or payload["runtime_input"] is not False \
            or any(payload[key] is not False for key in (
                "reference_generation_authorized", "training_authorized",
                "test_split_open_authorized",
                "gameplay_strength_screen_authorized",
                "strength_claim_authorized", "deployment_authorized")):
        raise BeliefB2ControllerError("public capture manifest drift")
    for seed, row in zip(seeds, payload["rounds"], strict=True):
        if type(row) is not dict or set(row) != {
                "round_seed", "filename", "byte_count", "bundle_sha256",
                "capture_manifest_sha256", "public_transcript_sha256",
                "actor_stream_sha256", "privileged_target_stream_sha256",
                "decision_count"} \
                or row["round_seed"] != seed \
                or row["filename"] != _round_filename(seed) \
                or type(row["byte_count"]) is not int \
                or row["byte_count"] <= 0 \
                or type(row["decision_count"]) is not int \
                or not 1 <= row["decision_count"] <= 128 \
                or any(not _is_sha256(row[key]) for key in (
                    "bundle_sha256", "capture_manifest_sha256",
                    "public_transcript_sha256", "actor_stream_sha256",
                    "privileged_target_stream_sha256")):
            raise BeliefB2ControllerError("public capture round row drift")
    resources = payload["resources"]
    if type(resources) is not dict or set(resources) != {
            "boot_identity", "started_monotonic_nanoseconds",
            "finished_monotonic_nanoseconds", "wall_nanoseconds",
            "cpu_nanoseconds", "artifact_bytes", "retry_count",
            "drop_count"} \
            or resources["boot_identity"] != design.runtime.boot_identity \
            or any(type(resources[name]) is not int or resources[name] < 0
                   for name in resources if name != "boot_identity") \
            or resources["finished_monotonic_nanoseconds"] \
            - resources["started_monotonic_nanoseconds"] \
            != resources["wall_nanoseconds"] \
            or resources["artifact_bytes"] != sum(
                row["byte_count"] for row in payload["rounds"]) \
            or resources["retry_count"] != 0 \
            or resources["drop_count"] != 0:
        raise BeliefB2ControllerError("public capture resource drift")
    return payload


def reference_lane_jobs(lane: int) -> tuple[tuple[int, str], ...]:
    """Return the exact ordered calibration×2 and test×1 lane jobs."""
    seeds = capture_lane_seeds(lane)
    jobs = []
    for seed in seeds:
        split = split_for_round_seed(seed)
        if split == "calibration":
            jobs.extend((seed, replicate)
                        for replicate in B2_REFERENCE_REPLICATES[:2])
        elif split == "test":
            jobs.append((seed, B2_REFERENCE_REPLICATES[2]))
    if not jobs:
        raise BeliefB2ControllerError("reference lane population is empty")
    return tuple(jobs)


def _reference_filename(seed: int, replicate: str) -> str:
    return f"round-{seed}.{replicate}.bin"


def _reference_lane_manifest(
        design: B2ExecutionDesignV1,
        admission: B2PipelineAdmissionV1, *, lane: int,
        rows: list[dict[str, Any]], wall_nanoseconds: int,
        cpu_nanoseconds: int, started_monotonic_nanoseconds: int,
        finished_monotonic_nanoseconds: int) -> dict[str, Any]:
    return {
        "schema": REFERENCE_LANE_SCHEMA,
        "protocol_sha256": protocol_sha256(),
        "design_sha256": design.sha256(),
        "admission_sha256": admission.sha256(),
        "lane": lane,
        "job_count": len(rows),
        "jobs": rows,
        "resources": {
            "boot_identity": design.runtime.boot_identity,
            "started_monotonic_nanoseconds": started_monotonic_nanoseconds,
            "finished_monotonic_nanoseconds": finished_monotonic_nanoseconds,
            "wall_nanoseconds": wall_nanoseconds,
            "cpu_nanoseconds": cpu_nanoseconds,
            "artifact_bytes": sum(row["byte_count"] for row in rows),
            "retry_count": 0,
            "drop_count": 0,
        },
        "contains_sampled_hidden_worlds": True,
        "contains_round_outcomes": False,
        "runtime_input": False,
        "training_authorized": False,
        "test_split_open_authorized": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }


def run_reference_lane(
        root: Path, design: B2ExecutionDesignV1,
        admission: B2PipelineAdmissionV1, *, lane: int,
        review_marker: bytes) -> dict[str, Any]:
    """Generate and atomically publish one exact REF-C lane."""
    try:
        validate_pipeline_admission(
            design, admission, review_marker=review_marker)
    except BeliefB2ExecutionError as exc:
        raise BeliefB2ControllerError("reference admission refused") from exc
    if not isinstance(root, Path) or root != Path(design.evidence_root) \
            or root.is_symlink() or not root.is_dir():
        raise BeliefB2ControllerError("reference evidence root drift")
    capture_directory = root / "capture" / f"lane-{lane:02d}"
    capture_manifest = reopen_capture_lane_public_manifest(
        capture_directory, design=design, admission=admission, lane=lane)
    capture_rows = {row["round_seed"]: row
                    for row in capture_manifest["rounds"]}
    jobs = reference_lane_jobs(lane)
    parent = root / "reference"
    if parent.is_symlink():
        raise BeliefB2ControllerError("reference parent is a symlink")
    parent.mkdir(mode=0o700, exist_ok=True)
    final = parent / f"lane-{lane:02d}"
    partial = parent / f"lane-{lane:02d}.partial"
    if final.exists() or partial.exists() \
            or final.is_symlink() or partial.is_symlink():
        raise BeliefB2ControllerError("reference lane slot is occupied")
    partial.mkdir(mode=0o700)
    start_wall = time.monotonic_ns()
    start_cpu = time.process_time_ns()
    rows = []
    for seed, replicate in jobs:
        result = capture_champion_round_with_ref_c(
            seed, replicate=replicate)
        capture_row = capture_rows[seed]
        if _byte_stream_sha256(result.captured.actor_rows) \
                != capture_row["actor_stream_sha256"] \
                or hashlib.sha256(public_transcript_bytes(
                result.captured.public_transcript)).hexdigest() \
                != capture_row["public_transcript_sha256"] \
                or len(result.captured.actor_rows) \
                != capture_row["decision_count"]:
            raise BeliefB2ControllerError(
                "reference replay differs from captured public population")
        raw = reference_round_bundle_bytes(result)
        filename = _reference_filename(seed, replicate)
        digest = publish_exclusive_bytes(partial / filename, raw)
        manifest = result.manifest_dict()
        rows.append({
            "round_seed": seed, "replicate": replicate,
            "filename": filename, "byte_count": len(raw),
            "bundle_sha256": digest,
            "reference_manifest_sha256": result.manifest_sha256(),
            "reference_actor_capture_manifest_sha256": (
                result.captured.manifest_sha256()),
            "capture_actor_stream_sha256":
                capture_row["actor_stream_sha256"],
            "capture_public_transcript_sha256":
                capture_row["public_transcript_sha256"],
            "decision_count": manifest["decision_count"],
            "accepted_world_count": manifest["accepted_world_count"],
            "attempt_count": manifest["attempt_count"],
        })
    finish_wall = time.monotonic_ns()
    wall = finish_wall - start_wall
    cpu = time.process_time_ns() - start_cpu
    manifest = _reference_lane_manifest(
        design, admission, lane=lane, rows=rows,
        wall_nanoseconds=wall, cpu_nanoseconds=cpu,
        started_monotonic_nanoseconds=start_wall,
        finished_monotonic_nanoseconds=finish_wall)
    publish_exclusive_bytes(
        partial / "manifest.json", canonical_json_bytes(manifest))
    os.rename(partial, final)
    _fsync_parent(final)
    reopened = reopen_reference_lane(
        final, capture_directory=capture_directory,
        design=design, admission=admission, lane=lane)
    if reopened != manifest:
        raise BeliefB2ControllerError("reference lane post-publish drift")
    return reopened


def reopen_reference_lane(
        directory: Path, *, capture_directory: Path,
        design: B2ExecutionDesignV1,
        admission: B2PipelineAdmissionV1, lane: int) -> dict[str, Any]:
    """Reopen every compact world block and compare the capture replay."""
    if type(admission) is not B2PipelineAdmissionV1 \
            or not isinstance(directory, Path) or directory.is_symlink() \
            or not directory.is_dir() \
            or directory.name != f"lane-{lane:02d}":
        raise BeliefB2ControllerError("reference lane directory drift")
    capture_manifest = reopen_capture_lane_public_manifest(
        capture_directory, design=design, admission=admission, lane=lane)
    capture_rows = {row["round_seed"]: row
                    for row in capture_manifest["rounds"]}
    jobs = reference_lane_jobs(lane)
    expected_names = {"manifest.json", *(
        _reference_filename(seed, replicate) for seed, replicate in jobs)}
    if {path.name for path in directory.iterdir()} != expected_names:
        raise BeliefB2ControllerError("reference lane file population drift")
    payload = _strict_json(stable_read_bytes(
        directory / "manifest.json"), label="reference lane manifest")
    expected_keys = {
        "schema", "protocol_sha256", "design_sha256",
        "admission_sha256", "lane", "job_count", "jobs", "resources",
        "contains_sampled_hidden_worlds", "contains_round_outcomes",
        "runtime_input", "training_authorized",
        "test_split_open_authorized",
        "gameplay_strength_screen_authorized", "strength_claim_authorized",
        "deployment_authorized"}
    if set(payload) != expected_keys \
            or payload["schema"] != REFERENCE_LANE_SCHEMA \
            or payload["protocol_sha256"] != protocol_sha256() \
            or payload["design_sha256"] != design.sha256() \
            or payload["admission_sha256"] != admission.sha256() \
            or payload["lane"] != lane \
            or payload["job_count"] != len(jobs) \
            or type(payload["jobs"]) is not list \
            or len(payload["jobs"]) != len(jobs) \
            or payload["contains_sampled_hidden_worlds"] is not True \
            or payload["contains_round_outcomes"] is not False \
            or payload["runtime_input"] is not False \
            or any(payload[key] is not False for key in (
                "training_authorized", "test_split_open_authorized",
                "gameplay_strength_screen_authorized",
                "strength_claim_authorized", "deployment_authorized")):
        raise BeliefB2ControllerError("reference lane manifest identity drift")
    actual_rows = []
    for (seed, replicate), row in zip(
            jobs, payload["jobs"], strict=True):
        filename = _reference_filename(seed, replicate)
        if type(row) is not dict or set(row) != {
                "round_seed", "replicate", "filename", "byte_count",
                "bundle_sha256", "reference_manifest_sha256",
                "reference_actor_capture_manifest_sha256",
                "capture_actor_stream_sha256",
                "capture_public_transcript_sha256", "decision_count",
                "accepted_world_count", "attempt_count"} \
                or row["round_seed"] != seed \
                or row["replicate"] != replicate \
                or row["filename"] != filename:
            raise BeliefB2ControllerError("reference job row drift")
        raw = stable_read_bytes(directory / filename)
        if row["byte_count"] != len(raw) \
                or row["bundle_sha256"] != hashlib.sha256(raw).hexdigest():
            raise BeliefB2ControllerError("reference job byte binding drift")
        result = reopen_reference_round_bundle(raw)
        manifest = result.manifest_dict()
        capture_row = capture_rows[seed]
        if result.captured.round_seed != seed \
                or result.replicate != replicate \
                or _byte_stream_sha256(result.captured.actor_rows) \
                != capture_row["actor_stream_sha256"] \
                or hashlib.sha256(public_transcript_bytes(
                    result.captured.public_transcript)).hexdigest() \
                != capture_row["public_transcript_sha256"]:
            raise BeliefB2ControllerError(
                "reference job capture/replicate drift")
        actual_rows.append({
            "round_seed": seed, "replicate": replicate,
            "filename": filename, "byte_count": len(raw),
            "bundle_sha256": hashlib.sha256(raw).hexdigest(),
            "reference_manifest_sha256": result.manifest_sha256(),
            "reference_actor_capture_manifest_sha256": (
                result.captured.manifest_sha256()),
            "capture_actor_stream_sha256":
                capture_row["actor_stream_sha256"],
            "capture_public_transcript_sha256":
                capture_row["public_transcript_sha256"],
            "decision_count": manifest["decision_count"],
            "accepted_world_count": manifest["accepted_world_count"],
            "attempt_count": manifest["attempt_count"],
        })
    resources = payload["resources"]
    if type(resources) is not dict or set(resources) != {
            "boot_identity", "started_monotonic_nanoseconds",
            "finished_monotonic_nanoseconds", "wall_nanoseconds",
            "cpu_nanoseconds", "artifact_bytes",
            "retry_count", "drop_count"} \
            or resources["boot_identity"] != design.runtime.boot_identity \
            or any(type(resources[name]) is not int or resources[name] < 0
                   for name in resources if name != "boot_identity") \
            or resources["finished_monotonic_nanoseconds"] \
            - resources["started_monotonic_nanoseconds"] \
            != resources["wall_nanoseconds"] \
            or min(resources["wall_nanoseconds"],
                   resources["cpu_nanoseconds"]) <= 0 \
            or resources["artifact_bytes"] != sum(
                row["byte_count"] for row in actual_rows) \
            or resources["retry_count"] != 0 \
            or resources["drop_count"] != 0 \
            or resources["wall_nanoseconds"] \
            > REFERENCE_WALL_SECOND_CAP * NS_PER_SECOND \
            or resources["cpu_nanoseconds"] \
            > REFERENCE_CORE_HOUR_CAP * NS_PER_HOUR \
            or resources["artifact_bytes"] > REFERENCE_BYTE_CAP:
        raise BeliefB2ControllerError("reference lane resource drift")
    expected = _reference_lane_manifest(
        design, admission, lane=lane, rows=actual_rows,
        wall_nanoseconds=resources["wall_nanoseconds"],
        cpu_nanoseconds=resources["cpu_nanoseconds"],
        started_monotonic_nanoseconds=resources[
            "started_monotonic_nanoseconds"],
        finished_monotonic_nanoseconds=resources[
            "finished_monotonic_nanoseconds"])
    if canonical_json_bytes(expected) != canonical_json_bytes(payload):
        raise BeliefB2ControllerError("reference lane reconstruction drift")
    return payload


def _capture_path(root: Path, seed: int) -> Path:
    lane = capture_lane(seed)
    return root / "capture" / f"lane-{lane:02d}" / _round_filename(seed)


def _round_examples(
        root: Path, seed: int, *, split: str, kind: str):
    if split not in {"train", "calibration"} \
            or split_for_round_seed(seed) != split:
        raise BeliefB2ControllerError(
            "training capture split boundary drift")
    raw = stable_read_bytes(_capture_path(root, seed))
    artifacts = reopen_capture_bundle(raw)
    captured = reopen_captured_round_artifacts(artifacts)
    if captured.round_seed != seed:
        raise BeliefB2ControllerError("training capture seed drift")
    if kind == "candidate":
        return tuple(build_training_example(
            pair, behavior_policy_ids=(CHAMPION_POLICY,))
                     for pair in captured.pairs)
    if kind == LABEL_PERMUTATION_CONTROL:
        return tuple(build_control_example(
            pair, behavior_policy_ids=(CHAMPION_POLICY,),
            control_kind=LABEL_PERMUTATION_CONTROL)
                     for pair in captured.pairs)
    raise BeliefB2ControllerError("training cohort kind drift")


def _iter_corpus_batches(
        root: Path, *, split: str, kind: str, epoch: int | None = None):
    """Yield exact complete-round-grouped batches from immutable bundles."""
    seeds = b2_split_round_seeds(split)
    if split == "train":
        if epoch is None:
            raise BeliefB2ControllerError("training batch epoch is missing")
        seeds = ordered_round_seeds_for_epoch(seeds, epoch=epoch)
    elif split != "calibration" or epoch is not None:
        raise BeliefB2ControllerError("training batch split/epoch drift")
    if kind not in TRAINING_KINDS:
        raise BeliefB2ControllerError("training cohort kind drift")
    pending = []
    for seed in seeds:
        rows = _round_examples(root, seed, split=split, kind=kind)
        if not rows or len(rows) > TRAIN_BATCH_DECISION_CAP:
            raise BeliefB2ControllerError(
                "training round decision population drift")
        if pending and len(pending) + len(rows) > TRAIN_BATCH_DECISION_CAP:
            yield (collate_training_examples(tuple(pending))
                   if kind == "candidate"
                   else collate_control_examples(tuple(pending)))
            pending = []
        pending.extend(rows)
    if pending:
        yield (collate_training_examples(tuple(pending))
               if kind == "candidate"
               else collate_control_examples(tuple(pending)))


def _training_manifest(
        design: B2ExecutionDesignV1,
        admission: B2PipelineAdmissionV1, *, kind: str,
        epochs: list[dict[str, Any]], selected_epoch: int, stop_epoch: int,
        stopped_for_patience: bool, checkpoints: list[dict[str, Any]],
        wall_nanoseconds: int, device_nanoseconds: int,
        started_monotonic_nanoseconds: int,
        finished_monotonic_nanoseconds: int) -> dict[str, Any]:
    return {
        "schema": TRAINING_COHORT_SCHEMA,
        "protocol_sha256": protocol_sha256(),
        "design_sha256": design.sha256(),
        "admission_sha256": admission.sha256(),
        "cohort_kind": kind,
        "initialization_seeds": list(COHORT_SEEDS),
        "epoch_count": len(epochs),
        "epochs": epochs,
        "selected_common_epoch": selected_epoch,
        "stop_epoch": stop_epoch,
        "stopped_for_patience": stopped_for_patience,
        "checkpoints": checkpoints,
        "resources": {
            "boot_identity": design.runtime.boot_identity,
            "started_monotonic_nanoseconds": started_monotonic_nanoseconds,
            "finished_monotonic_nanoseconds": finished_monotonic_nanoseconds,
            "wall_nanoseconds": wall_nanoseconds,
            "device_nanoseconds": device_nanoseconds,
            "artifact_bytes": sum(row["byte_count"] for row in checkpoints),
            "retry_count": 0,
        },
        "test_split_opened": False,
        "contains_optimizer_resume_state": False,
        "contains_privileged_targets": False,
        "runtime_research_package": True,
        "test_split_open_authorized": False,
        "sampler_implementation_authorized": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }


def run_training_cohort(
        root: Path, design: B2ExecutionDesignV1,
        admission: B2PipelineAdmissionV1, *, kind: str,
        review_marker: bytes) -> dict[str, Any]:
    """Train all eight members from one streamed batch pass per epoch."""
    try:
        validate_pipeline_admission(
            design, admission, review_marker=review_marker)
    except BeliefB2ExecutionError as exc:
        raise BeliefB2ControllerError("training admission refused") from exc
    if kind not in TRAINING_KINDS or root != Path(design.evidence_root) \
            or root.is_symlink() or not root.is_dir():
        raise BeliefB2ControllerError("training cohort input drift")
    for lane in range(B2_CAPTURE_LANES):
        reopen_capture_lane_public_manifest(
            root / "capture" / f"lane-{lane:02d}", design=design,
            admission=admission, lane=lane)
    parent = root / "training"
    if parent.is_symlink():
        raise BeliefB2ControllerError("training parent is a symlink")
    parent.mkdir(mode=0o700, exist_ok=True)
    final = parent / kind
    partial = parent / f"{kind}.partial"
    if final.exists() or partial.exists() \
            or final.is_symlink() or partial.is_symlink():
        raise BeliefB2ControllerError("training cohort slot is occupied")
    partial.mkdir(mode=0o700)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    if torch.get_num_threads() != 1 \
            or not torch.are_deterministic_algorithms_enabled():
        raise BeliefB2ControllerError("training numerical mode drift")
    models = tuple(new_from_scratch_model(seed) for seed in COHORT_SEEDS)
    optimizers = tuple(new_b2_optimizer(model) for model in models)
    losses: list[list[int]] = [[] for _ in models]
    epochs = []
    selected_states = None
    selected_receipts = None
    start_wall = time.monotonic_ns()
    start_device = time.process_time_ns()
    decision = None
    for epoch in range(1, TRAIN_MAX_EPOCHS + 1):
        receipts = train_cohort_epoch_stream(
            models, optimizers,
            _iter_corpus_batches(
                root, split="train", kind=kind, epoch=epoch),
            epoch=epoch)
        calibration = evaluate_calibration_cohort_stream_nanonats(
            models, _iter_corpus_batches(
                root, split="calibration", kind=kind))
        for row, value in zip(losses, calibration, strict=True):
            row.append(value)
        decision = select_common_epoch(tuple(tuple(row) for row in losses))
        epochs.append({
            "epoch": epoch,
            "member_training_receipts": [
                receipt.to_dict() for receipt in receipts],
            "member_calibration_loss_nanonats": list(calibration),
            "cohort_mean_calibration_loss_nanonats": (
                sum(calibration) // len(calibration)),
        })
        if decision.selected_epoch == epoch:
            selected_states = tuple(deepcopy(model.state_dict())
                                    for model in models)
            selected_receipts = receipts
        if decision.stopped_for_patience:
            break
    if decision is None or selected_states is None \
            or selected_receipts is None \
            or decision.stop_epoch != len(epochs):
        raise BeliefB2ControllerError("training common epoch drift")
    for model, state in zip(models, selected_states, strict=True):
        model.load_state_dict(state, strict=True)
    checkpoint_rows = []
    for index, (seed, model, receipt) in enumerate(zip(
            COHORT_SEEDS, models, selected_receipts, strict=True)):
        if receipt.epoch != decision.selected_epoch \
                or receipt.model_state_sha256_after \
                != model_state_sha256(model):
            raise BeliefB2ControllerError(
                "training selected model/receipt drift")
        checkpoint = build_model_checkpoint(
            model, initialization_seed=seed,
            selected_epoch=decision.selected_epoch,
            final_epoch_receipt=receipt)
        raw = checkpoint_bundle_bytes(checkpoint, receipt)
        filename = f"member-{index:02d}.bin"
        digest = publish_exclusive_bytes(partial / filename, raw)
        checkpoint_rows.append({
            "member_index": index, "initialization_seed": seed,
            "filename": filename, "byte_count": len(raw),
            "bundle_sha256": digest,
            "checkpoint_sha256": checkpoint.sha256(),
            "model_state_sha256": model_state_sha256(model),
            "final_epoch_receipt_sha256": receipt.sha256(),
        })
    finish_wall = time.monotonic_ns()
    wall = finish_wall - start_wall
    device = time.process_time_ns() - start_device
    manifest = _training_manifest(
        design, admission, kind=kind, epochs=epochs,
        selected_epoch=decision.selected_epoch,
        stop_epoch=decision.stop_epoch,
        stopped_for_patience=decision.stopped_for_patience,
        checkpoints=checkpoint_rows, wall_nanoseconds=wall,
        device_nanoseconds=device,
        started_monotonic_nanoseconds=start_wall,
        finished_monotonic_nanoseconds=finish_wall)
    publish_exclusive_bytes(
        partial / "manifest.json", canonical_json_bytes(manifest))
    os.rename(partial, final)
    _fsync_parent(final)
    reopened = reopen_training_cohort(
        final, design=design, admission=admission, kind=kind)
    if reopened != manifest:
        raise BeliefB2ControllerError("training cohort post-publish drift")
    return reopened


def reopen_training_cohort(
        directory: Path, *, design: B2ExecutionDesignV1,
        admission: B2PipelineAdmissionV1, kind: str) -> dict[str, Any]:
    """Reopen the complete curve and all eight selected checkpoints."""
    if kind not in TRAINING_KINDS or directory.is_symlink() \
            or not directory.is_dir() or directory.name != kind:
        raise BeliefB2ControllerError("training cohort directory drift")
    expected_names = {"manifest.json", *(
        f"member-{index:02d}.bin" for index in range(len(COHORT_SEEDS)))}
    if {path.name for path in directory.iterdir()} != expected_names:
        raise BeliefB2ControllerError("training cohort file population drift")
    payload = _strict_json(stable_read_bytes(
        directory / "manifest.json"), label="training cohort manifest")
    expected_keys = {
        "schema", "protocol_sha256", "design_sha256",
        "admission_sha256", "cohort_kind", "initialization_seeds",
        "epoch_count", "epochs", "selected_common_epoch", "stop_epoch",
        "stopped_for_patience", "checkpoints", "resources",
        "test_split_opened", "contains_optimizer_resume_state",
        "contains_privileged_targets", "runtime_research_package",
        "test_split_open_authorized", "sampler_implementation_authorized",
        "gameplay_strength_screen_authorized", "strength_claim_authorized",
        "deployment_authorized"}
    if set(payload) != expected_keys \
            or payload["schema"] != TRAINING_COHORT_SCHEMA \
            or payload["protocol_sha256"] != protocol_sha256() \
            or payload["design_sha256"] != design.sha256() \
            or payload["admission_sha256"] != admission.sha256() \
            or payload["cohort_kind"] != kind \
            or payload["initialization_seeds"] != list(COHORT_SEEDS) \
            or type(payload["epoch_count"]) is not int \
            or not 1 <= payload["epoch_count"] <= TRAIN_MAX_EPOCHS \
            or payload["stop_epoch"] != payload["epoch_count"] \
            or type(payload["epochs"]) is not list \
            or len(payload["epochs"]) != payload["epoch_count"] \
            or type(payload["checkpoints"]) is not list \
            or len(payload["checkpoints"]) != len(COHORT_SEEDS) \
            or payload["test_split_opened"] is not False \
            or payload["contains_optimizer_resume_state"] is not False \
            or payload["contains_privileged_targets"] is not False \
            or payload["runtime_research_package"] is not True \
            or any(payload[key] is not False for key in (
                "test_split_open_authorized",
                "sampler_implementation_authorized",
                "gameplay_strength_screen_authorized",
                "strength_claim_authorized", "deployment_authorized")):
        raise BeliefB2ControllerError("training cohort manifest identity drift")
    member_losses = [[] for _ in COHORT_SEEDS]
    receipt_rows = []
    for epoch, row in enumerate(payload["epochs"], 1):
        if type(row) is not dict or set(row) != {
                "epoch", "member_training_receipts",
                "member_calibration_loss_nanonats",
                "cohort_mean_calibration_loss_nanonats"} \
                or row["epoch"] != epoch \
                or type(row["member_training_receipts"]) is not list \
                or len(row["member_training_receipts"]) != len(COHORT_SEEDS) \
                or type(row["member_calibration_loss_nanonats"]) is not list \
                or len(row["member_calibration_loss_nanonats"]) \
                != len(COHORT_SEEDS) \
                or any(type(value) is not int or value < 0
                       for value in row[
                           "member_calibration_loss_nanonats"]):
            raise BeliefB2ControllerError("training epoch curve drift")
        receipts = tuple(reopen_epoch_receipt(canonical_json_bytes(value))
                         for value in row["member_training_receipts"])
        if any(receipt.epoch != epoch for receipt in receipts) \
                or row["cohort_mean_calibration_loss_nanonats"] != sum(
                    row["member_calibration_loss_nanonats"]) \
                // len(COHORT_SEEDS):
            raise BeliefB2ControllerError(
                "training epoch receipt/loss drift")
        receipt_rows.append(receipts)
        for losses, value in zip(
                member_losses, row["member_calibration_loss_nanonats"],
                strict=True):
            losses.append(value)
    decision = select_common_epoch(tuple(
        tuple(row) for row in member_losses))
    if payload["selected_common_epoch"] != decision.selected_epoch \
            or payload["stop_epoch"] != decision.stop_epoch \
            or payload["stopped_for_patience"] \
            is not decision.stopped_for_patience:
        raise BeliefB2ControllerError(
            "training common epoch reconstruction drift")
    checkpoint_rows = []
    selected_receipts = receipt_rows[decision.selected_epoch - 1]
    for index, (seed, row, receipt) in enumerate(zip(
            COHORT_SEEDS, payload["checkpoints"], selected_receipts,
            strict=True)):
        expected_filename = f"member-{index:02d}.bin"
        if type(row) is not dict or set(row) != {
                "member_index", "initialization_seed", "filename",
                "byte_count", "bundle_sha256", "checkpoint_sha256",
                "model_state_sha256", "final_epoch_receipt_sha256"} \
                or row["member_index"] != index \
                or row["initialization_seed"] != seed \
                or row["filename"] != expected_filename:
            raise BeliefB2ControllerError("training checkpoint row drift")
        raw = stable_read_bytes(directory / expected_filename)
        checkpoint, reopened_receipt = reopen_checkpoint_bundle(raw)
        model = reopen_model_checkpoint(
            checkpoint, final_epoch_receipt=reopened_receipt)
        actual = {
            "member_index": index, "initialization_seed": seed,
            "filename": expected_filename, "byte_count": len(raw),
            "bundle_sha256": hashlib.sha256(raw).hexdigest(),
            "checkpoint_sha256": checkpoint.sha256(),
            "model_state_sha256": model_state_sha256(model),
            "final_epoch_receipt_sha256": reopened_receipt.sha256(),
        }
        if reopened_receipt != receipt or actual != row:
            raise BeliefB2ControllerError(
                "training checkpoint reconstruction drift")
        checkpoint_rows.append(actual)
    resources = payload["resources"]
    if type(resources) is not dict or set(resources) != {
            "boot_identity", "started_monotonic_nanoseconds",
            "finished_monotonic_nanoseconds", "wall_nanoseconds",
            "device_nanoseconds", "artifact_bytes",
            "retry_count"} \
            or resources["boot_identity"] != design.runtime.boot_identity \
            or any(type(resources[name]) is not int or resources[name] < 0
                   for name in resources if name != "boot_identity") \
            or resources["finished_monotonic_nanoseconds"] \
            - resources["started_monotonic_nanoseconds"] \
            != resources["wall_nanoseconds"] \
            or min(resources["wall_nanoseconds"],
                   resources["device_nanoseconds"]) <= 0 \
            or resources["artifact_bytes"] != sum(
                row["byte_count"] for row in checkpoint_rows) \
            or resources["retry_count"] != 0 \
            or resources["wall_nanoseconds"] \
            > TRAIN_WALL_SECOND_CAP * NS_PER_SECOND \
            or resources["device_nanoseconds"] \
            > TRAIN_DEVICE_HOUR_CAP * NS_PER_HOUR \
            or resources["artifact_bytes"] > TRAIN_BYTE_CAP:
        raise BeliefB2ControllerError("training cohort resource drift")
    expected = _training_manifest(
        design, admission, kind=kind, epochs=payload["epochs"],
        selected_epoch=decision.selected_epoch,
        stop_epoch=decision.stop_epoch,
        stopped_for_patience=decision.stopped_for_patience,
        checkpoints=checkpoint_rows,
        wall_nanoseconds=resources["wall_nanoseconds"],
        device_nanoseconds=resources["device_nanoseconds"],
        started_monotonic_nanoseconds=resources[
            "started_monotonic_nanoseconds"],
        finished_monotonic_nanoseconds=resources[
            "finished_monotonic_nanoseconds"])
    if canonical_json_bytes(expected) != canonical_json_bytes(payload):
        raise BeliefB2ControllerError("training cohort reconstruction drift")
    return payload
