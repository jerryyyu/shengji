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
import time
from pathlib import Path
from typing import Any

from .belief_artifacts import (
    capture_bundle_bytes,
    publish_exclusive_bytes,
    reopen_capture_bundle,
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
    b2_round_seeds,
    capture_lane,
    champion_policy_seeds,
    protocol_sha256,
)
from .belief_capture import (
    capture_champion_round,
    captured_round_artifacts,
    reopen_captured_round_artifacts,
)
from .belief_contract import canonical_json_bytes
from .belief_population import population_round_from_artifacts


CAPTURE_LANE_SCHEMA = "belief-v1-b2-capture-lane-result-v1"
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
        cpu_nanoseconds: int) -> dict[str, Any]:
    return {
        "schema": CAPTURE_LANE_SCHEMA,
        "protocol_sha256": protocol_sha256(),
        "design_sha256": design.sha256(),
        "admission_sha256": admission.sha256(),
        "lane": lane,
        "round_count": len(rows),
        "rounds": rows,
        "resources": {
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
    start_wall = time.perf_counter_ns()
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
    wall = time.perf_counter_ns() - start_wall
    cpu = time.process_time_ns() - start_cpu
    manifest = _lane_manifest(
        design, admission, lane=lane, rows=rows,
        wall_nanoseconds=wall, cpu_nanoseconds=cpu)
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
            "wall_nanoseconds", "cpu_nanoseconds", "artifact_bytes",
            "retry_count", "drop_count"} \
            or any(type(resources[name]) is not int or resources[name] < 0
                   for name in ("wall_nanoseconds", "cpu_nanoseconds",
                                "artifact_bytes", "retry_count",
                                "drop_count")) \
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
        cpu_nanoseconds=resources["cpu_nanoseconds"])
    if canonical_json_bytes(expected) != canonical_json_bytes(payload):
        raise BeliefB2ControllerError("capture lane reconstruction drift")
    return payload
