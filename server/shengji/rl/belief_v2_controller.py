"""Durable, no-retry capture and reference stages for BELIEF-V1 V2.

One champion search trajectory publishes two physically separated artifacts:
the full private label bundle and a target-blind actor-only replay bundle.
Reference generation opens only the latter.  Every stage reauthenticates the
external review and exact live source/runtime before its first write.
"""

from __future__ import annotations

import hashlib
import os
import stat
import time
from pathlib import Path
from typing import Any

from .belief_artifacts import (
    actor_capture_bundle_bytes,
    capture_bundle_bytes,
    publish_exclusive_bytes,
    reference_round_bundle_bytes,
    reopen_actor_capture_bundle,
    reopen_capture_bundle,
    reopen_reference_round_bundle,
    stable_read_bytes,
)
from .belief_b2_protocol import B2_REFERENCE_REPLICATES
from .belief_capture import (
    CapturedActorRoundV1,
    captured_actor_round_artifacts,
    captured_round_artifacts,
    public_transcript_bytes,
    reopen_captured_actor_round_artifacts,
    reopen_captured_round_artifacts,
    validate_actor_round,
)
from .belief_contract import canonical_json_bytes
from .belief_corpus import reopen_actor_row
from .belief_v2_capture import capture_v2_champion_round
from .belief_v2_accelerator import build_training_device_profile
from .belief_v2_execution_identity import (
    BeliefV2ExecutionIdentityError,
    validate_live_execution,
)
from .belief_v2_deadline import (
    BeliefV2DeadlineError,
    deadline_refusal_paths,
    publish_deadline_refusal,
    reopen_deadline_refusal,
    stage_deadline,
)
from .belief_v2_freeze import (
    V2ExecutionFreezeV1,
    V2PipelineAdmissionV1,
    BeliefV2FreezeError,
    reauthenticate_pipeline_admission,
    validate_execution_freeze,
)
from .belief_v2_protocol import (
    V2_CAPTURE_LANES,
    V2RoundCoordinate,
    protocol_sha256,
    schedule_sha256,
    v2_lane_coordinates,
    v2_policy_seeds,
)
from .belief_v2_reference import capture_v2_ref_c_from_replay
from .belief_v2_training import (
    V2TrainingExampleV1,
    build_synthetic_training_example,
)


CAPTURE_LANE_SCHEMA = "belief-v1-v2-capture-lane-result-v1"
REFERENCE_LANE_SCHEMA = "belief-v1-v2-reference-lane-result-v1"
NS_PER_HOUR = 3_600_000_000_000
NS_PER_SECOND = 1_000_000_000


class BeliefV2ControllerError(ValueError):
    """A V2 stage identity, workload, artifact, or resource drifted."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_sha256(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _byte_stream_sha256(rows: tuple[bytes, ...]) -> str:
    if type(rows) is not tuple or not rows:
        raise BeliefV2ControllerError("V2 byte stream is empty")
    digest = hashlib.sha256()
    for raw in rows:
        if type(raw) is not bytes or not raw:
            raise BeliefV2ControllerError("V2 byte stream row drift")
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def _stage_gate(
        *, root: Path, repo: Path, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1, review_marker: bytes) -> None:
    try:
        validate_execution_freeze(freeze)
        reauthenticate_pipeline_admission(
            freeze, admission, repo=repo, review_marker=review_marker)
        validate_live_execution(
            repo=repo, execution_git=freeze.execution_git,
            source_bindings=freeze.source_bindings, runtime=freeze.runtime)
        if build_training_device_profile(
                freeze.training_candidate_device) \
                != freeze.training_device_profile:
            raise BeliefV2ExecutionIdentityError(
                "V2 live training device identity drift")
    except (BeliefV2FreezeError, BeliefV2ExecutionIdentityError) as exc:
        raise BeliefV2ControllerError("V2 stage admission refused") from exc
    if not isinstance(root, Path) or root != Path(freeze.evidence_root) \
            or not root.is_absolute() or root.is_symlink() \
            or not root.is_dir():
        raise BeliefV2ControllerError("V2 evidence root drift")
    try:
        refusals = deadline_refusal_paths(root)
        for path in refusals:
            reopen_deadline_refusal(
                path, freeze_sha256=freeze.sha256(),
                admission_sha256=admission.sha256())
    except ValueError as exc:
        raise BeliefV2ControllerError(
            "V2 deadline refusal evidence drift") from exc
    if refusals:
        raise BeliefV2ControllerError(
            "V2 stage blocked by a prior deadline refusal")


def _deadline_check(
        partial: Path, guard, *, phase: str, next_unit_index: int) -> None:
    try:
        guard.check(
            phase=phase, next_unit_index=next_unit_index,
            observed_monotonic_nanoseconds=time.monotonic_ns())
    except BeliefV2DeadlineError as exc:
        publish_deadline_refusal(partial, exc.refusal)
        raise BeliefV2ControllerError(
            "V2 stage deadline exhausted and recorded") from exc


def _coordinate_stem(coordinate: V2RoundCoordinate) -> str:
    return (f"rank-{coordinate.rank_index:02d}-ordinal-"
            f"{coordinate.rank_ordinal:04d}-seed-{coordinate.round_seed}")


def _private_filename(coordinate: V2RoundCoordinate) -> str:
    return _coordinate_stem(coordinate) + ".private.bin"


def _actor_filename(coordinate: V2RoundCoordinate) -> str:
    return _coordinate_stem(coordinate) + ".actor.bin"


def _reference_filename(
        coordinate: V2RoundCoordinate, replicate: str) -> str:
    return _coordinate_stem(coordinate) + f".{replicate}.ref.bin"


def _actor_capture(captured) -> CapturedActorRoundV1:
    actor = CapturedActorRoundV1(
        round_seed=captured.round_seed, policy_name=captured.policy_name,
        policy_seeds=captured.policy_seeds,
        actor_rows=tuple(pair.actor_bytes for pair in captured.pairs),
        public_transcript=captured.public_transcript)
    try:
        validate_actor_round(actor)
    except ValueError as exc:
        raise BeliefV2ControllerError(
            "V2 actor-only derivation refused") from exc
    return actor


def _capture_binding(captured) -> dict[str, Any]:
    if not captured.pairs:
        raise BeliefV2ControllerError("V2 captured decision stream is empty")
    return {
        "capture_manifest_sha256": captured.manifest_sha256(),
        "public_transcript_sha256": _sha256(
            public_transcript_bytes(captured.public_transcript)),
        "actor_stream_sha256": _byte_stream_sha256(tuple(
            pair.actor_bytes for pair in captured.pairs)),
        "privileged_target_stream_sha256": _byte_stream_sha256(tuple(
            pair.target_bytes for pair in captured.pairs)),
        "decision_count": len(captured.pairs),
    }


def _resource_row(
        freeze: V2ExecutionFreezeV1, *, started: int, finished: int,
        cpu_nanoseconds: int, artifact_bytes: int) -> dict[str, Any]:
    return {
        "boot_identity": freeze.runtime.boot_identity,
        "started_monotonic_nanoseconds": started,
        "finished_monotonic_nanoseconds": finished,
        "wall_nanoseconds": finished - started,
        "cpu_nanoseconds": cpu_nanoseconds,
        "artifact_bytes": artifact_bytes,
        "retry_count": 0,
        "drop_count": 0,
    }


def _validate_resources(
        resources: Any, *, freeze: V2ExecutionFreezeV1,
        expected_bytes: int, kind: str) -> None:
    if type(resources) is not dict or set(resources) != {
            "boot_identity", "started_monotonic_nanoseconds",
            "finished_monotonic_nanoseconds", "wall_nanoseconds",
            "cpu_nanoseconds", "artifact_bytes", "retry_count",
            "drop_count"} \
            or resources["boot_identity"] != freeze.runtime.boot_identity \
            or any(type(resources[key]) is not int or resources[key] < 0
                   for key in resources if key != "boot_identity") \
            or resources["finished_monotonic_nanoseconds"] \
            - resources["started_monotonic_nanoseconds"] \
            != resources["wall_nanoseconds"] \
            or min(resources["wall_nanoseconds"],
                   resources["cpu_nanoseconds"]) <= 0 \
            or resources["artifact_bytes"] != expected_bytes \
            or resources["retry_count"] != 0 \
            or resources["drop_count"] != 0:
        raise BeliefV2ControllerError(f"V2 {kind} resource drift")
    caps = freeze.resource_caps
    if kind == "capture":
        over = (resources["wall_nanoseconds"]
                > caps.capture_wall_seconds * NS_PER_SECOND
                or resources["cpu_nanoseconds"]
                > caps.capture_core_hours * NS_PER_HOUR
                or resources["artifact_bytes"] > caps.capture_bytes)
    elif kind == "reference":
        over = (resources["wall_nanoseconds"]
                > caps.reference_wall_seconds * NS_PER_SECOND
                or resources["cpu_nanoseconds"]
                > caps.reference_core_hours * NS_PER_HOUR
                or resources["artifact_bytes"] > caps.reference_bytes)
    else:
        raise BeliefV2ControllerError("V2 resource kind drift")
    if over:
        raise BeliefV2ControllerError(f"V2 {kind} resource cap exceeded")


def _capture_manifest(
        freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1, *, lane: int,
        rows: list[dict[str, Any]], resources: dict[str, Any]) \
        -> dict[str, Any]:
    return {
        "schema": CAPTURE_LANE_SCHEMA,
        "protocol_sha256": protocol_sha256(),
        "schedule_sha256": schedule_sha256(),
        "freeze_sha256": freeze.sha256(),
        "admission_sha256": admission.sha256(),
        "lane": lane,
        "round_count": len(rows),
        "rounds": rows,
        "resources": resources,
        "private_and_actor_bundles_derived_from_one_search": True,
        "contains_round_outcomes": False,
        "private_contains_privileged_targets": True,
        "actor_contains_privileged_targets": False,
        "reference_authorized_by_this_artifact": False,
        "training_authorized_by_this_artifact": False,
        "test_open_authorized_by_this_artifact": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }


def run_capture_lane(
        root: Path, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1, *, repo: Path, lane: int,
        review_marker: bytes) -> dict[str, Any]:
    """Capture and atomically publish one exact balanced V2 lane."""
    _stage_gate(
        root=root, repo=repo, freeze=freeze, admission=admission,
        review_marker=review_marker)
    coordinates = v2_lane_coordinates(lane)
    parent = root / "capture"
    if parent.is_symlink():
        raise BeliefV2ControllerError("V2 capture parent is a symlink")
    parent.mkdir(mode=0o700, exist_ok=True)
    final = parent / f"lane-{lane:02d}"
    partial = parent / f"lane-{lane:02d}.partial"
    if final.exists() or partial.exists() \
            or final.is_symlink() or partial.is_symlink():
        raise BeliefV2ControllerError("V2 capture lane slot is occupied")
    partial.mkdir(mode=0o700)
    private = partial / "private"
    public = partial / "actor-only"
    private.mkdir(mode=0o700)
    public.mkdir(mode=0o700)
    started = time.monotonic_ns()
    cpu_started = time.process_time_ns()
    deadline = stage_deadline(
        freeze, admission, stage="capture", slot=f"lane-{lane:02d}",
        started_monotonic_nanoseconds=started)
    rows = []
    for unit_index, coordinate in enumerate(coordinates):
        _deadline_check(
            partial, deadline, phase="before-unit",
            next_unit_index=unit_index)
        captured = capture_v2_champion_round(coordinate)
        private_artifacts = captured_round_artifacts(captured)
        private_raw = capture_bundle_bytes(private_artifacts)
        actor = _actor_capture(captured)
        actor_artifacts = captured_actor_round_artifacts(actor)
        actor_raw = actor_capture_bundle_bytes(actor_artifacts)
        if actor.actor_rows != tuple(
                pair.actor_bytes for pair in captured.pairs) \
                or actor.public_transcript != captured.public_transcript:
            raise BeliefV2ControllerError(
                "V2 one-search actor/private derivation drift")
        private_name = _private_filename(coordinate)
        actor_name = _actor_filename(coordinate)
        private_sha = publish_exclusive_bytes(
            private / private_name, private_raw)
        actor_sha = publish_exclusive_bytes(public / actor_name, actor_raw)
        binding = _capture_binding(captured)
        rows.append({
            "lane": coordinate.lane,
            "rank_index": coordinate.rank_index,
            "rank_ordinal": coordinate.rank_ordinal,
            "round_seed": coordinate.round_seed,
            "split": coordinate.split,
            "trump_rank": coordinate.trump_rank,
            "policy_seeds": list(v2_policy_seeds(coordinate)),
            "private_filename": private_name,
            "private_byte_count": len(private_raw),
            "private_bundle_sha256": private_sha,
            "actor_filename": actor_name,
            "actor_byte_count": len(actor_raw),
            "actor_bundle_sha256": actor_sha,
            "private_capture_manifest_sha256": (
                binding["capture_manifest_sha256"]),
            "actor_capture_manifest_sha256": actor.manifest_sha256(),
            "public_transcript_sha256": binding["public_transcript_sha256"],
            "actor_stream_sha256": binding["actor_stream_sha256"],
            "privileged_target_stream_sha256": (
                binding["privileged_target_stream_sha256"]),
            "decision_count": binding["decision_count"],
        })
        _deadline_check(
            partial, deadline, phase="after-unit",
            next_unit_index=unit_index + 1)
    _deadline_check(
        partial, deadline, phase="before-seal",
        next_unit_index=len(coordinates))
    finished = time.monotonic_ns()
    resources = _resource_row(
        freeze, started=started, finished=finished,
        cpu_nanoseconds=time.process_time_ns() - cpu_started,
        artifact_bytes=sum(row["private_byte_count"]
                           + row["actor_byte_count"] for row in rows))
    manifest = _capture_manifest(
        freeze, admission, lane=lane, rows=rows, resources=resources)
    publish_exclusive_bytes(
        partial / "manifest.json", canonical_json_bytes(manifest))
    os.rename(partial, final)
    descriptor = os.open(parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    reopened = reopen_capture_lane(
        final, freeze=freeze, admission=admission, lane=lane)
    if reopened != manifest:
        raise BeliefV2ControllerError("V2 capture post-publish drift")
    return reopened


_CAPTURE_ROW_KEYS = {
    "lane", "rank_index", "rank_ordinal", "round_seed", "split",
    "trump_rank", "policy_seeds", "private_filename",
    "private_byte_count", "private_bundle_sha256", "actor_filename",
    "actor_byte_count", "actor_bundle_sha256",
    "private_capture_manifest_sha256", "actor_capture_manifest_sha256",
    "public_transcript_sha256", "actor_stream_sha256",
    "privileged_target_stream_sha256", "decision_count",
}


def _reopen_capture_row(
        directory: Path, coordinate: V2RoundCoordinate,
        row: dict[str, Any]) -> dict[str, Any]:
    if type(row) is not dict or set(row) != _CAPTURE_ROW_KEYS \
            or any(row[key] != getattr(coordinate, key) for key in (
                "lane", "rank_index", "rank_ordinal", "round_seed",
                "split", "trump_rank")) \
            or row["policy_seeds"] != list(v2_policy_seeds(coordinate)) \
            or row["private_filename"] != _private_filename(coordinate) \
            or row["actor_filename"] != _actor_filename(coordinate):
        raise BeliefV2ControllerError("V2 capture round row drift")
    private_raw = stable_read_bytes(
        directory / "private" / row["private_filename"])
    actor_raw = stable_read_bytes(
        directory / "actor-only" / row["actor_filename"])
    if row["private_byte_count"] != len(private_raw) \
            or row["private_bundle_sha256"] != _sha256(private_raw) \
            or row["actor_byte_count"] != len(actor_raw) \
            or row["actor_bundle_sha256"] != _sha256(actor_raw):
        raise BeliefV2ControllerError("V2 capture bundle byte binding drift")
    try:
        private_artifacts = reopen_capture_bundle(private_raw)
        captured = reopen_captured_round_artifacts(private_artifacts)
        actor_artifacts = reopen_actor_capture_bundle(actor_raw)
        actor = reopen_captured_actor_round_artifacts(actor_artifacts)
    except ValueError as exc:
        raise BeliefV2ControllerError("V2 capture typed reopen refused") \
            from exc
    if captured.round_seed != coordinate.round_seed \
            or captured.policy_seeds != v2_policy_seeds(coordinate) \
            or actor.round_seed != coordinate.round_seed \
            or actor.policy_seeds != captured.policy_seeds \
            or actor.actor_rows != tuple(
                pair.actor_bytes for pair in captured.pairs) \
            or actor.public_transcript != captured.public_transcript:
        raise BeliefV2ControllerError("V2 capture typed identity drift")
    typed_actors = [reopen_actor_row(raw)[0] for raw in actor.actor_rows]
    if not typed_actors \
            or any(value.trump_rank != coordinate.trump_rank
                   for value in typed_actors):
        raise BeliefV2ControllerError("V2 capture trump-rank drift")
    binding = _capture_binding(captured)
    expected = {
        **{key: getattr(coordinate, key) for key in (
            "lane", "rank_index", "rank_ordinal", "round_seed", "split",
            "trump_rank")},
        "policy_seeds": list(v2_policy_seeds(coordinate)),
        "private_filename": _private_filename(coordinate),
        "private_byte_count": len(private_raw),
        "private_bundle_sha256": _sha256(private_raw),
        "actor_filename": _actor_filename(coordinate),
        "actor_byte_count": len(actor_raw),
        "actor_bundle_sha256": _sha256(actor_raw),
        "private_capture_manifest_sha256": binding[
            "capture_manifest_sha256"],
        "actor_capture_manifest_sha256": actor.manifest_sha256(),
        "public_transcript_sha256": binding["public_transcript_sha256"],
        "actor_stream_sha256": binding["actor_stream_sha256"],
        "privileged_target_stream_sha256": (
            binding["privileged_target_stream_sha256"]),
        "decision_count": binding["decision_count"],
    }
    if expected != row:
        raise BeliefV2ControllerError("V2 capture row reconstruction drift")
    return expected


def reopen_capture_lane(
        directory: Path, *, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1, lane: int) -> dict[str, Any]:
    """Reopen every private/actor byte and reconstruct the exact lane."""
    validate_execution_freeze(freeze)
    coordinates = v2_lane_coordinates(lane)
    if type(admission) is not V2PipelineAdmissionV1 \
            or not isinstance(directory, Path) or directory.is_symlink() \
            or not directory.is_dir() or directory.name != f"lane-{lane:02d}":
        raise BeliefV2ControllerError("V2 capture lane directory drift")
    expected_private = {_private_filename(row) for row in coordinates}
    expected_actor = {_actor_filename(row) for row in coordinates}
    if {path.name for path in directory.iterdir()} \
            != {"manifest.json", "private", "actor-only"} \
            or {path.name for path in (directory / "private").iterdir()} \
            != expected_private \
            or {path.name for path in (directory / "actor-only").iterdir()} \
            != expected_actor:
        raise BeliefV2ControllerError(
            "V2 capture lane file population drift")
    import json
    raw_manifest = stable_read_bytes(directory / "manifest.json")
    try:
        payload = json.loads(raw_manifest)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefV2ControllerError("V2 capture manifest is not JSON") \
            from exc
    if type(payload) is not dict \
            or canonical_json_bytes(payload) != raw_manifest \
            or payload.get("schema") != CAPTURE_LANE_SCHEMA \
            or payload.get("protocol_sha256") != protocol_sha256() \
            or payload.get("schedule_sha256") != schedule_sha256() \
            or payload.get("freeze_sha256") != freeze.sha256() \
            or payload.get("admission_sha256") != admission.sha256() \
            or payload.get("lane") != lane \
            or payload.get("round_count") != len(coordinates) \
            or type(payload.get("rounds")) is not list \
            or len(payload["rounds"]) != len(coordinates) \
            or payload.get(
                "private_and_actor_bundles_derived_from_one_search") is not True \
            or payload.get("contains_round_outcomes") is not False \
            or payload.get("private_contains_privileged_targets") is not True \
            or payload.get("actor_contains_privileged_targets") is not False \
            or any(payload.get(key) is not False for key in (
                "reference_authorized_by_this_artifact",
                "training_authorized_by_this_artifact",
                "test_open_authorized_by_this_artifact",
                "gameplay_strength_screen_authorized",
                "strength_claim_authorized", "deployment_authorized")):
        raise BeliefV2ControllerError("V2 capture manifest identity drift")
    rows = [_reopen_capture_row(directory, coordinate, row)
            for coordinate, row in zip(
                coordinates, payload["rounds"], strict=True)]
    _validate_resources(
        payload.get("resources"), freeze=freeze,
        expected_bytes=sum(row["private_byte_count"]
                           + row["actor_byte_count"] for row in rows),
        kind="capture")
    expected = _capture_manifest(
        freeze, admission, lane=lane, rows=rows,
        resources=payload["resources"])
    if expected != payload:
        raise BeliefV2ControllerError(
            "V2 capture manifest reconstruction drift")
    return payload


def reopen_actor_capture_lane_manifest(
        directory: Path, *, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1, lane: int) -> dict[str, Any]:
    """Authenticate actor-only file identities without opening private bytes."""
    validate_execution_freeze(freeze)
    coordinates = v2_lane_coordinates(lane)
    if not isinstance(directory, Path) or directory.is_symlink() \
            or not directory.is_dir() \
            or directory.name != f"lane-{lane:02d}":
        raise BeliefV2ControllerError(
            "V2 public capture lane directory drift")
    raw = stable_read_bytes(directory / "manifest.json")
    import json
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefV2ControllerError(
            "V2 public capture manifest is not JSON") from exc
    expected_keys = {
        "schema", "protocol_sha256", "schedule_sha256", "freeze_sha256",
        "admission_sha256", "lane", "round_count", "rounds", "resources",
        "private_and_actor_bundles_derived_from_one_search",
        "contains_round_outcomes", "private_contains_privileged_targets",
        "actor_contains_privileged_targets",
        "reference_authorized_by_this_artifact",
        "training_authorized_by_this_artifact",
        "test_open_authorized_by_this_artifact",
        "gameplay_strength_screen_authorized", "strength_claim_authorized",
        "deployment_authorized"}
    if type(payload) is not dict or set(payload) != expected_keys \
            or canonical_json_bytes(payload) != raw \
            or payload.get("schema") != CAPTURE_LANE_SCHEMA \
            or payload.get("protocol_sha256") != protocol_sha256() \
            or payload.get("schedule_sha256") != schedule_sha256() \
            or payload.get("freeze_sha256") != freeze.sha256() \
            or payload.get("admission_sha256") != admission.sha256() \
            or payload.get("lane") != lane \
            or payload.get("round_count") != len(coordinates) \
            or type(payload.get("rounds")) is not list \
            or len(payload["rounds"]) != len(coordinates) \
            or payload.get(
                "private_and_actor_bundles_derived_from_one_search") is not True \
            or payload.get("contains_round_outcomes") is not False \
            or payload.get("private_contains_privileged_targets") is not True \
            or payload.get("actor_contains_privileged_targets") is not False \
            or any(payload.get(key) is not False for key in (
                "reference_authorized_by_this_artifact",
                "training_authorized_by_this_artifact",
                "test_open_authorized_by_this_artifact",
                "gameplay_strength_screen_authorized",
                "strength_claim_authorized", "deployment_authorized")):
        raise BeliefV2ControllerError("V2 public capture manifest drift")
    actor_directory = directory / "actor-only"
    private_directory = directory / "private"
    if actor_directory.is_symlink() or not actor_directory.is_dir() \
            or {path.name for path in actor_directory.iterdir()} \
            != {_actor_filename(row) for row in coordinates}:
        raise BeliefV2ControllerError(
            "V2 actor-only file population drift")
    if private_directory.is_symlink() or not private_directory.is_dir() \
            or {path.name for path in private_directory.iterdir()} \
            != {_private_filename(row) for row in coordinates}:
        raise BeliefV2ControllerError(
            "V2 private file population drift")
    for coordinate, row in zip(coordinates, payload["rounds"], strict=True):
        if type(row) is not dict or set(row) != _CAPTURE_ROW_KEYS \
                or any(row[key] != getattr(coordinate, key) for key in (
                    "lane", "rank_index", "rank_ordinal", "round_seed",
                    "split", "trump_rank")) \
                or row["policy_seeds"] != list(v2_policy_seeds(coordinate)) \
                or row["private_filename"] != _private_filename(coordinate) \
                or row["actor_filename"] != _actor_filename(coordinate) \
                or type(row["private_byte_count"]) is not int \
                or row["private_byte_count"] <= 0 \
                or type(row["actor_byte_count"]) is not int \
                or row["actor_byte_count"] <= 0 \
                or type(row["decision_count"]) is not int \
                or not 1 <= row["decision_count"] <= 128 \
                or any(not _is_sha256(row[key]) for key in (
                    "private_bundle_sha256",
                    "private_capture_manifest_sha256",
                    "privileged_target_stream_sha256",
                    "actor_bundle_sha256", "actor_capture_manifest_sha256",
                    "actor_stream_sha256", "public_transcript_sha256")):
            raise BeliefV2ControllerError(
                "V2 actor-only capture row drift")
        actor_path = actor_directory / row["actor_filename"]
        info = actor_path.lstat()
        if actor_path.is_symlink() or not stat.S_ISREG(info.st_mode) \
                or info.st_nlink != 1 or info.st_mode & 0o222 \
                or info.st_size != row["actor_byte_count"]:
            raise BeliefV2ControllerError(
                "V2 actor-only capture file shape drift")
        private_path = private_directory / row["private_filename"]
        private_info = private_path.lstat()
        if private_path.is_symlink() \
                or not stat.S_ISREG(private_info.st_mode) \
                or private_info.st_nlink != 1 \
                or private_info.st_mode & 0o222 \
                or private_info.st_size != row["private_byte_count"]:
            raise BeliefV2ControllerError(
                "V2 private capture file shape drift")
    _validate_resources(
        payload.get("resources"), freeze=freeze,
        expected_bytes=sum(row["private_byte_count"]
                           + row["actor_byte_count"]
                           for row in payload["rounds"]), kind="capture")
    return payload


def _reopen_synthetic_training_round_examples(
        directory: Path, *, coordinate: V2RoundCoordinate,
        row: dict[str, Any], split: str) \
        -> tuple[V2TrainingExampleV1, ...]:
    """Reopen one manifest-bound non-test round into bounded examples."""
    if type(split) is not str or split not in {"train", "calibration"} \
            or type(coordinate) is not V2RoundCoordinate \
            or coordinate.split != split \
            or type(row) is not dict or set(row) != _CAPTURE_ROW_KEYS:
        raise BeliefV2ControllerError(
            "V2 training round population/split drift")
    private_raw = stable_read_bytes(
        directory / "private" / row["private_filename"])
    if len(private_raw) != row["private_byte_count"] \
            or _sha256(private_raw) != row["private_bundle_sha256"]:
        raise BeliefV2ControllerError(
            "V2 training private bundle byte binding drift")
    try:
        artifacts = reopen_capture_bundle(private_raw)
        captured = reopen_captured_round_artifacts(artifacts)
    except ValueError as exc:
        raise BeliefV2ControllerError(
            "V2 training private bundle typed reopen refused") from exc
    typed_actors = tuple(
        reopen_actor_row(pair.actor_bytes)[0] for pair in captured.pairs)
    binding = _capture_binding(captured)
    if captured.round_seed != coordinate.round_seed \
            or captured.policy_seeds != v2_policy_seeds(coordinate) \
            or not typed_actors \
            or any(actor.trump_rank != coordinate.trump_rank
                   for actor in typed_actors) \
            or row["private_capture_manifest_sha256"] \
            != binding["capture_manifest_sha256"] \
            or row["public_transcript_sha256"] \
            != binding["public_transcript_sha256"] \
            or row["actor_stream_sha256"] \
            != binding["actor_stream_sha256"] \
            or row["privileged_target_stream_sha256"] \
            != binding["privileged_target_stream_sha256"] \
            or row["decision_count"] != binding["decision_count"]:
        raise BeliefV2ControllerError(
            "V2 training private capture identity drift")
    try:
        examples = tuple(
            build_synthetic_training_example(pair) for pair in captured.pairs)
    except ValueError as exc:
        raise BeliefV2ControllerError(
            "V2 synthetic training example derivation refused") from exc
    if not examples or any(example.split != split for example in examples):
        raise BeliefV2ControllerError(
            "V2 synthetic training example split drift")
    keys = tuple(example.decision_key for example in examples)
    if len(keys) != len(set(keys)):
        raise BeliefV2ControllerError(
            "V2 training round decision duplicate")
    return examples


def iter_synthetic_training_lane_round_examples(
        directory: Path, *, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1, lane: int,
        split: str, deadline_check=None, unit_index_start: int = 0):
    """Yield one authenticated round at a time without retaining a lane."""
    if type(split) is not str or split not in {"train", "calibration"} \
            or type(unit_index_start) is not int or unit_index_start < 0 \
            or (deadline_check is not None and not callable(deadline_check)):
        raise BeliefV2ControllerError(
            "V2 training reader split is not train/calibration")
    payload = reopen_actor_capture_lane_manifest(
        directory, freeze=freeze, admission=admission, lane=lane)
    coordinates = v2_lane_coordinates(lane)
    emitted = 0
    for index, (coordinate, row) in enumerate(zip(
            coordinates, payload["rounds"], strict=True)):
        if coordinate.split != split:
            continue
        if deadline_check is not None:
            deadline_check("before-unit", unit_index_start + emitted)
        emitted += 1
        yield index, _reopen_synthetic_training_round_examples(
            directory, coordinate=coordinate, row=row, split=split)
        if deadline_check is not None:
            deadline_check("after-unit", unit_index_start + emitted)
    if emitted == 0:
        raise BeliefV2ControllerError(
            "V2 training lane split population is empty")


def reopen_synthetic_training_lane_examples(
        directory: Path, *, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1, lane: int,
        split: str) -> tuple[V2TrainingExampleV1, ...]:
    """Compatibility reader that materializes one authenticated lane split."""
    examples = [example
                for _, round_examples
                in iter_synthetic_training_lane_round_examples(
                    directory, freeze=freeze, admission=admission,
                    lane=lane, split=split)
                for example in round_examples]
    if not examples:
        raise BeliefV2ControllerError(
            "V2 training lane split population is empty")
    keys = tuple(example.decision_key for example in examples)
    if len(keys) != len(set(keys)):
        raise BeliefV2ControllerError(
            "V2 training lane split decision duplicate")
    return tuple(examples)


def reference_lane_jobs(
        lane: int) -> tuple[tuple[V2RoundCoordinate, str], ...]:
    jobs = []
    for coordinate in v2_lane_coordinates(lane):
        if coordinate.split == "calibration":
            jobs.extend((coordinate, replicate)
                        for replicate in B2_REFERENCE_REPLICATES[:2])
        elif coordinate.split == "test":
            jobs.append((coordinate, B2_REFERENCE_REPLICATES[2]))
    if not jobs:
        raise BeliefV2ControllerError("V2 reference lane is empty")
    return tuple(jobs)


def _reference_manifest(
        freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1, *, lane: int,
        rows: list[dict[str, Any]], resources: dict[str, Any]) \
        -> dict[str, Any]:
    return {
        "schema": REFERENCE_LANE_SCHEMA,
        "protocol_sha256": protocol_sha256(),
        "schedule_sha256": schedule_sha256(),
        "freeze_sha256": freeze.sha256(),
        "admission_sha256": admission.sha256(),
        "lane": lane,
        "job_count": len(rows),
        "jobs": rows,
        "resources": resources,
        "input_surface": "actor-only-capture-bundles",
        "contains_sampled_hidden_worlds": True,
        "contains_round_outcomes": False,
        "contains_privileged_training_targets": False,
        "training_authorized_by_this_artifact": False,
        "test_target_open_authorized_by_this_artifact": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }


def run_reference_lane(
        root: Path, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1, *, repo: Path, lane: int,
        review_marker: bytes) -> dict[str, Any]:
    """Replay actor-only capture and publish one exact REF-C lane."""
    _stage_gate(
        root=root, repo=repo, freeze=freeze, admission=admission,
        review_marker=review_marker)
    capture_directory = root / "capture" / f"lane-{lane:02d}"
    capture_manifest = reopen_actor_capture_lane_manifest(
        capture_directory, freeze=freeze, admission=admission, lane=lane)
    capture_rows = {row["round_seed"]: row
                    for row in capture_manifest["rounds"]}
    jobs = reference_lane_jobs(lane)
    parent = root / "reference"
    if parent.is_symlink():
        raise BeliefV2ControllerError("V2 reference parent is a symlink")
    parent.mkdir(mode=0o700, exist_ok=True)
    final = parent / f"lane-{lane:02d}"
    partial = parent / f"lane-{lane:02d}.partial"
    if final.exists() or partial.exists() \
            or final.is_symlink() or partial.is_symlink():
        raise BeliefV2ControllerError("V2 reference lane slot is occupied")
    partial.mkdir(mode=0o700)
    started = time.monotonic_ns()
    cpu_started = time.process_time_ns()
    deadline = stage_deadline(
        freeze, admission, stage="reference", slot=f"lane-{lane:02d}",
        started_monotonic_nanoseconds=started)
    rows = []
    for unit_index, (coordinate, replicate) in enumerate(jobs):
        _deadline_check(
            partial, deadline, phase="before-unit",
            next_unit_index=unit_index)
        capture_row = capture_rows[coordinate.round_seed]
        actor_raw = stable_read_bytes(
            capture_directory / "actor-only"
            / capture_row["actor_filename"])
        if len(actor_raw) != capture_row["actor_byte_count"] \
                or _sha256(actor_raw) != capture_row["actor_bundle_sha256"]:
            raise BeliefV2ControllerError(
                "V2 reference actor byte binding drift")
        actor_artifacts = reopen_actor_capture_bundle(actor_raw)
        actor = reopen_captured_actor_round_artifacts(actor_artifacts)
        result = capture_v2_ref_c_from_replay(
            coordinate, actor, replicate=replicate)
        raw = reference_round_bundle_bytes(result)
        filename = _reference_filename(coordinate, replicate)
        digest = publish_exclusive_bytes(partial / filename, raw)
        manifest = result.manifest_dict()
        rows.append({
            "rank_index": coordinate.rank_index,
            "rank_ordinal": coordinate.rank_ordinal,
            "round_seed": coordinate.round_seed,
            "split": coordinate.split,
            "trump_rank": coordinate.trump_rank,
            "replicate": replicate,
            "filename": filename,
            "byte_count": len(raw),
            "bundle_sha256": digest,
            "reference_manifest_sha256": result.manifest_sha256(),
            "actor_capture_manifest_sha256": (
                actor.manifest_sha256()),
            "actor_bundle_sha256": capture_row["actor_bundle_sha256"],
            "actor_stream_sha256": capture_row["actor_stream_sha256"],
            "public_transcript_sha256": (
                capture_row["public_transcript_sha256"]),
            "decision_count": manifest["decision_count"],
            "accepted_world_count": manifest["accepted_world_count"],
            "attempt_count": manifest["attempt_count"],
        })
        _deadline_check(
            partial, deadline, phase="after-unit",
            next_unit_index=unit_index + 1)
    _deadline_check(
        partial, deadline, phase="before-seal",
        next_unit_index=len(jobs))
    finished = time.monotonic_ns()
    resources = _resource_row(
        freeze, started=started, finished=finished,
        cpu_nanoseconds=time.process_time_ns() - cpu_started,
        artifact_bytes=sum(row["byte_count"] for row in rows))
    manifest = _reference_manifest(
        freeze, admission, lane=lane, rows=rows, resources=resources)
    publish_exclusive_bytes(
        partial / "manifest.json", canonical_json_bytes(manifest))
    os.rename(partial, final)
    descriptor = os.open(parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    reopened = reopen_reference_lane(
        final, capture_directory=capture_directory,
        freeze=freeze, admission=admission, lane=lane)
    if reopened != manifest:
        raise BeliefV2ControllerError("V2 reference post-publish drift")
    return reopened


_REFERENCE_ROW_KEYS = {
    "rank_index", "rank_ordinal", "round_seed", "split", "trump_rank",
    "replicate", "filename", "byte_count", "bundle_sha256",
    "reference_manifest_sha256", "actor_capture_manifest_sha256",
    "actor_bundle_sha256", "actor_stream_sha256",
    "public_transcript_sha256", "decision_count", "accepted_world_count",
    "attempt_count",
}


def reopen_reference_lane(
        directory: Path, *, capture_directory: Path,
        freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1, lane: int) -> dict[str, Any]:
    """Reopen all reference bytes and rebind them to actor-only capture."""
    jobs = reference_lane_jobs(lane)
    capture_manifest = reopen_actor_capture_lane_manifest(
        capture_directory, freeze=freeze, admission=admission, lane=lane)
    capture_rows = {row["round_seed"]: row
                    for row in capture_manifest["rounds"]}
    if not isinstance(directory, Path) or directory.is_symlink() \
            or not directory.is_dir() or directory.name != f"lane-{lane:02d}" \
            or {path.name for path in directory.iterdir()} != {
                "manifest.json",
                *(_reference_filename(coordinate, replicate)
                  for coordinate, replicate in jobs)}:
        raise BeliefV2ControllerError(
            "V2 reference lane file population drift")
    import json
    raw_manifest = stable_read_bytes(directory / "manifest.json")
    try:
        payload = json.loads(raw_manifest)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefV2ControllerError("V2 reference manifest is not JSON") \
            from exc
    if type(payload) is not dict \
            or canonical_json_bytes(payload) != raw_manifest \
            or payload.get("schema") != REFERENCE_LANE_SCHEMA \
            or payload.get("protocol_sha256") != protocol_sha256() \
            or payload.get("schedule_sha256") != schedule_sha256() \
            or payload.get("freeze_sha256") != freeze.sha256() \
            or payload.get("admission_sha256") != admission.sha256() \
            or payload.get("lane") != lane \
            or payload.get("job_count") != len(jobs) \
            or type(payload.get("jobs")) is not list \
            or payload.get("input_surface") \
            != "actor-only-capture-bundles" \
            or payload.get("contains_sampled_hidden_worlds") is not True \
            or payload.get("contains_round_outcomes") is not False \
            or payload.get("contains_privileged_training_targets") is not False \
            or any(payload.get(key) is not False for key in (
                "training_authorized_by_this_artifact",
                "test_target_open_authorized_by_this_artifact",
                "gameplay_strength_screen_authorized",
                "strength_claim_authorized", "deployment_authorized")):
        raise BeliefV2ControllerError("V2 reference manifest identity drift")
    rows = []
    for (coordinate, replicate), row in zip(
            jobs, payload["jobs"], strict=True):
        if type(row) is not dict or set(row) != _REFERENCE_ROW_KEYS \
                or any(row[key] != getattr(coordinate, key) for key in (
                    "rank_index", "rank_ordinal", "round_seed", "split",
                    "trump_rank")) \
                or row["replicate"] != replicate \
                or row["filename"] != _reference_filename(
                    coordinate, replicate):
            raise BeliefV2ControllerError("V2 reference row drift")
        raw = stable_read_bytes(directory / row["filename"])
        if row["byte_count"] != len(raw) \
                or row["bundle_sha256"] != _sha256(raw):
            raise BeliefV2ControllerError(
                "V2 reference bundle byte binding drift")
        try:
            result = reopen_reference_round_bundle(raw)
        except ValueError as exc:
            raise BeliefV2ControllerError(
                "V2 reference typed reopen refused") from exc
        capture_row = capture_rows[coordinate.round_seed]
        actor_raw = stable_read_bytes(
            capture_directory / "actor-only"
            / capture_row["actor_filename"])
        if len(actor_raw) != capture_row["actor_byte_count"] \
                or _sha256(actor_raw) != capture_row["actor_bundle_sha256"]:
            raise BeliefV2ControllerError(
                "V2 reference input actor byte binding drift")
        try:
            input_actor = reopen_captured_actor_round_artifacts(
                reopen_actor_capture_bundle(actor_raw))
        except ValueError as exc:
            raise BeliefV2ControllerError(
                "V2 reference input actor reopen refused") from exc
        actor = result.captured
        manifest = result.manifest_dict()
        expected = {
            **{key: getattr(coordinate, key) for key in (
                "rank_index", "rank_ordinal", "round_seed", "split",
                "trump_rank")},
            "replicate": replicate,
            "filename": _reference_filename(coordinate, replicate),
            "byte_count": len(raw), "bundle_sha256": _sha256(raw),
            "reference_manifest_sha256": result.manifest_sha256(),
            "actor_capture_manifest_sha256": actor.manifest_sha256(),
            "actor_bundle_sha256": capture_row["actor_bundle_sha256"],
            "actor_stream_sha256": capture_row["actor_stream_sha256"],
            "public_transcript_sha256": (
                capture_row["public_transcript_sha256"]),
            "decision_count": manifest["decision_count"],
            "accepted_world_count": manifest["accepted_world_count"],
            "attempt_count": manifest["attempt_count"],
        }
        if actor.round_seed != coordinate.round_seed \
                or actor.policy_seeds != v2_policy_seeds(coordinate) \
                or actor != input_actor \
                or _byte_stream_sha256(actor.actor_rows) \
                != capture_row["actor_stream_sha256"] \
                or _sha256(public_transcript_bytes(actor.public_transcript)) \
                != capture_row["public_transcript_sha256"] \
                or expected != row:
            raise BeliefV2ControllerError(
                "V2 reference reconstruction drift")
        rows.append(expected)
    _validate_resources(
        payload.get("resources"), freeze=freeze,
        expected_bytes=sum(row["byte_count"] for row in rows),
        kind="reference")
    expected_manifest = _reference_manifest(
        freeze, admission, lane=lane, rows=rows,
        resources=payload["resources"])
    if expected_manifest != payload:
        raise BeliefV2ControllerError(
            "V2 reference manifest reconstruction drift")
    return payload


def reopen_reference_lane_manifest(
        directory: Path, *, capture_directory: Path,
        freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1, lane: int) -> dict[str, Any]:
    """Authenticate every REF-C file without reading any world bundle.

    Calibration selection uses this boundary to verify the complete immutable
    reference population while opening only calibration replicates.  The sole
    test bundle remains physically unopened until the terminal attempt exists.
    """
    jobs = reference_lane_jobs(lane)
    capture_manifest = reopen_actor_capture_lane_manifest(
        capture_directory, freeze=freeze, admission=admission, lane=lane)
    capture_rows = {row["round_seed"]: row
                    for row in capture_manifest["rounds"]}
    expected_files = {
        "manifest.json",
        *(_reference_filename(coordinate, replicate)
          for coordinate, replicate in jobs),
    }
    if not isinstance(directory, Path) or directory.is_symlink() \
            or not directory.is_dir() \
            or directory.name != f"lane-{lane:02d}" \
            or {path.name for path in directory.iterdir()} != expected_files:
        raise BeliefV2ControllerError(
            "V2 public reference lane file population drift")
    import json
    raw = stable_read_bytes(directory / "manifest.json")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefV2ControllerError(
            "V2 public reference manifest is not JSON") from exc
    expected_keys = {
        "schema", "protocol_sha256", "schedule_sha256", "freeze_sha256",
        "admission_sha256", "lane", "job_count", "jobs", "resources",
        "input_surface", "contains_sampled_hidden_worlds",
        "contains_round_outcomes", "contains_privileged_training_targets",
        "training_authorized_by_this_artifact",
        "test_target_open_authorized_by_this_artifact",
        "gameplay_strength_screen_authorized", "strength_claim_authorized",
        "deployment_authorized",
    }
    if type(payload) is not dict or set(payload) != expected_keys \
            or canonical_json_bytes(payload) != raw \
            or payload["schema"] != REFERENCE_LANE_SCHEMA \
            or payload["protocol_sha256"] != protocol_sha256() \
            or payload["schedule_sha256"] != schedule_sha256() \
            or payload["freeze_sha256"] != freeze.sha256() \
            or payload["admission_sha256"] != admission.sha256() \
            or payload["lane"] != lane \
            or payload["job_count"] != len(jobs) \
            or type(payload["jobs"]) is not list \
            or len(payload["jobs"]) != len(jobs) \
            or payload["input_surface"] != "actor-only-capture-bundles" \
            or payload["contains_sampled_hidden_worlds"] is not True \
            or payload["contains_round_outcomes"] is not False \
            or payload["contains_privileged_training_targets"] is not False \
            or any(payload[key] is not False for key in (
                "training_authorized_by_this_artifact",
                "test_target_open_authorized_by_this_artifact",
                "gameplay_strength_screen_authorized",
                "strength_claim_authorized", "deployment_authorized")):
        raise BeliefV2ControllerError(
            "V2 public reference manifest identity drift")
    for (coordinate, replicate), row in zip(
            jobs, payload["jobs"], strict=True):
        capture_row = capture_rows[coordinate.round_seed]
        if type(row) is not dict or set(row) != _REFERENCE_ROW_KEYS \
                or any(row[key] != getattr(coordinate, key) for key in (
                    "rank_index", "rank_ordinal", "round_seed", "split",
                    "trump_rank")) \
                or row["replicate"] != replicate \
                or row["filename"] != _reference_filename(
                    coordinate, replicate) \
                or any(not _is_sha256(row[key]) for key in (
                    "bundle_sha256", "reference_manifest_sha256",
                    "actor_capture_manifest_sha256", "actor_bundle_sha256",
                    "actor_stream_sha256", "public_transcript_sha256")) \
                or row["actor_bundle_sha256"] \
                != capture_row["actor_bundle_sha256"] \
                or row["actor_capture_manifest_sha256"] \
                != capture_row["actor_capture_manifest_sha256"] \
                or row["actor_stream_sha256"] \
                != capture_row["actor_stream_sha256"] \
                or row["public_transcript_sha256"] \
                != capture_row["public_transcript_sha256"] \
                or row["decision_count"] != capture_row["decision_count"] \
                or type(row["byte_count"]) is not int \
                or row["byte_count"] <= 0 \
                or type(row["accepted_world_count"]) is not int \
                or row["accepted_world_count"] <= 0 \
                or row["accepted_world_count"] % row["decision_count"] != 0 \
                or type(row["attempt_count"]) is not int \
                or row["attempt_count"] < row["accepted_world_count"]:
            raise BeliefV2ControllerError(
                "V2 public reference row drift")
        path = directory / row["filename"]
        info = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(info.st_mode) \
                or info.st_nlink != 1 or info.st_mode & 0o222 \
                or info.st_size != row["byte_count"]:
            raise BeliefV2ControllerError(
                "V2 public reference file shape drift")
    _validate_resources(
        payload["resources"], freeze=freeze,
        expected_bytes=sum(row["byte_count"] for row in payload["jobs"]),
        kind="reference")
    return payload
