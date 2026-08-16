"""Durable, split-safe historical-human capture for BELIEF-V1 V2.

Each reviewed source-log group is replayed once into physically separate
actor and privileged-target files.  The source path and player identities are
never published.  Training readers authenticate the complete group manifest,
but accept only train/calibration groups and never read test target bytes.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from pathlib import Path
from typing import Any

from ..engine.cards import RANKS
from .belief_artifacts import publish_exclusive_bytes, stable_read_bytes
from .belief_contract import canonical_json_bytes
from .belief_v2_controller import _stage_gate
from .belief_v2_freeze import V2ExecutionFreezeV1, V2PipelineAdmissionV1
from .belief_v2_human_corpus import (
    V2HumanCorpusPairV1,
    V2HumanGroupCaptureV1,
    capture_human_source_group,
    validate_human_corpus_pair,
    validate_human_group_capture,
)
from .belief_v2_human_inventory import (
    _group_digest,
    group_split_bytes,
    inventory_bytes,
    validate_h0_group_split,
)
from .belief_v2_progress import ProgressCallback
from .belief_v2_training import (
    V2TrainingExampleV1,
    build_human_training_example,
)


HUMAN_GROUP_STAGE_SCHEMA = "belief-v1-v2-human-group-stage-result-v1"
HUMAN_GROUP_RESOURCE_SCHEMA = "belief-v1-v2-human-group-resource-v1"


class BeliefV2HumanControllerError(ValueError):
    """A frozen human source, group artifact, or split reader drifted."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_sha256(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _actor_filename(ordinal: int) -> str:
    return f"decision-{ordinal:06d}.actor.json"


def _target_filename(ordinal: int) -> str:
    return f"decision-{ordinal:06d}.target.json"


def _bind_h0_receipts(
        freeze: V2ExecutionFreezeV1, inventory: dict[str, Any],
        group_split: dict[str, Any]) -> None:
    try:
        inventory_raw = inventory_bytes(inventory)
        validate_h0_group_split(group_split, inventory=inventory)
        split_raw = group_split_bytes(group_split, inventory=inventory)
    except ValueError as exc:
        raise BeliefV2HumanControllerError(
            "V2 human H0 receipt reconstruction refused") from exc
    splits = group_split["splits"]
    if _sha256(inventory_raw) != freeze.h0_inventory_sha256 \
            or inventory["source_manifest_sha256"] \
            != freeze.h0_source_manifest_sha256 \
            or inventory["source_digest_population_sha256"] \
            != freeze.h0_source_digest_population_sha256 \
            or _sha256(split_raw) != freeze.human_group_split_sha256 \
            or inventory["group_count"] != freeze.human_group_count \
            or inventory["complete_rounds"] \
            != freeze.human_complete_round_count \
            or inventory["human_play_decisions"] \
            != freeze.human_eligible_decision_count \
            or splits["train"]["group_count"] \
            != freeze.human_train_group_count \
            or splits["calibration"]["group_count"] \
            != freeze.human_calibration_group_count \
            or splits["test"]["group_count"] \
            != freeze.human_test_group_count \
            or splits["train"]["human_play_decisions"] \
            != freeze.human_train_eligible_decision_count \
            or splits["calibration"]["human_play_decisions"] \
            != freeze.human_calibration_eligible_decision_count \
            or splits["test"]["human_play_decisions"] \
            != freeze.human_test_eligible_decision_count:
        raise BeliefV2HumanControllerError(
            "V2 human H0 receipt/freeze binding drift")


def _group_inventory_row(
        inventory: dict[str, Any], group_digest: str) -> dict[str, Any]:
    rows = [row for row in inventory["groups"]
            if row["group_digest"] == group_digest]
    if len(rows) != 1:
        raise BeliefV2HumanControllerError(
            "V2 human group is absent or duplicated in H0 inventory")
    return rows[0]


def _group_split(
        group_split: dict[str, Any], group_digest: str) -> str:
    matches = [split for split, row in group_split["splits"].items()
               if group_digest in row["group_digests"]]
    if len(matches) != 1:
        raise BeliefV2HumanControllerError(
            "V2 human group split membership drift")
    return matches[0]


def _resource_row(
        freeze: V2ExecutionFreezeV1, *, started: int, finished: int,
        cpu_nanoseconds: int, artifact_bytes: int) -> dict[str, Any]:
    if type(started) is not int or type(finished) is not int \
            or not 0 <= started < finished \
            or type(cpu_nanoseconds) is not int or cpu_nanoseconds < 0 \
            or type(artifact_bytes) is not int or artifact_bytes < 0:
        raise BeliefV2HumanControllerError(
            "V2 human group resource measurement drift")
    return {
        "schema": HUMAN_GROUP_RESOURCE_SCHEMA,
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
        freeze: V2ExecutionFreezeV1, admission: V2PipelineAdmissionV1,
        captured: V2HumanGroupCaptureV1, rows: list[dict[str, Any]],
        resources: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": HUMAN_GROUP_STAGE_SCHEMA,
        "freeze_sha256": freeze.sha256(),
        "admission_sha256": admission.sha256(),
        "h0_inventory_sha256": freeze.h0_inventory_sha256,
        "human_group_split_sha256": freeze.human_group_split_sha256,
        "source_sha256": captured.source_sha256,
        "group_digest": captured.group_digest,
        "split": captured.split,
        "capture_manifest_sha256": _sha256(captured.manifest_bytes()),
        "complete_round_count": captured.complete_round_count,
        "incomplete_round_count": captured.incomplete_round_count,
        "human_decision_count": captured.human_decision_count,
        "trump_rank_counts": dict(captured.trump_rank_counts),
        "attempted_channel_counts": dict(
            captured.attempted_channel_counts),
        "rows": rows,
        "resources": resources,
        "source_bytes_published": False,
        "source_path_published": False,
        "raw_player_identity_published": False,
        "actor_target_files_separate": True,
        "training_authorized_by_this_artifact": False,
        "test_open_authorized_by_this_artifact": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }


def run_human_group_capture(
        root: Path, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1, *, repo: Path,
        source_path: Path, inventory: dict[str, Any],
        group_split: dict[str, Any], review_marker: bytes,
        progress: ProgressCallback | None = None) -> dict[str, Any]:
    """Replay and atomically publish one exact H0 source group."""
    _stage_gate(
        root=root, repo=repo, freeze=freeze, admission=admission,
        review_marker=review_marker)
    started = time.monotonic_ns()
    cpu_started = time.process_time_ns()
    _bind_h0_receipts(freeze, inventory, group_split)
    if not isinstance(source_path, Path) or source_path.is_symlink() \
            or not source_path.is_file():
        raise BeliefV2HumanControllerError(
            "V2 human source file shape drift")
    source_raw = stable_read_bytes(source_path)
    source_sha = _sha256(source_raw)
    group_digest = _group_digest(source_sha)
    expected_inventory = _group_inventory_row(inventory, group_digest)
    total = expected_inventory["human_play_decisions"]
    if progress is not None:
        progress(0, total, "replay-human-decisions")
    candidate = capture_human_source_group(
        source_raw, source_sha256=source_sha,
        split=_group_split(group_split, group_digest))
    validate_human_group_capture(candidate)
    if expected_inventory["source_bytes"] != len(source_raw) \
            or expected_inventory["complete_rounds"] \
            != candidate.complete_round_count \
            or expected_inventory["incomplete_rounds"] \
            != candidate.incomplete_round_count \
            or expected_inventory["human_play_decisions"] \
            != candidate.human_decision_count \
            or expected_inventory["trump_rank_counts"] \
            != dict(candidate.trump_rank_counts) \
            or expected_inventory["attempted_channel_counts"] \
            != dict(candidate.attempted_channel_counts) \
            or _group_split(group_split, candidate.group_digest) \
            != candidate.split:
        raise BeliefV2HumanControllerError(
            "V2 human captured group differs from H0 inventory/split")

    parent = root / "human-capture"
    if parent.is_symlink():
        raise BeliefV2HumanControllerError(
            "V2 human capture parent is a symlink")
    parent.mkdir(mode=0o700, exist_ok=True)
    name = f"group-{candidate.group_digest}"
    final = parent / name
    partial = parent / f"{name}.partial"
    if final.exists() or partial.exists() \
            or final.is_symlink() or partial.is_symlink():
        raise BeliefV2HumanControllerError(
            "V2 human group slot is occupied")
    partial.mkdir(mode=0o700)
    actor_directory = partial / "actor-only"
    target_directory = partial / "private-targets"
    actor_directory.mkdir(mode=0o700)
    target_directory.mkdir(mode=0o700)
    rows = []
    if len(candidate.pairs) != total:
        raise BeliefV2HumanControllerError(
            "V2 human progress population differs from H0 inventory")
    for ordinal, pair in enumerate(candidate.pairs):
        _, _, _, metadata = validate_human_corpus_pair(
            pair.actor_bytes, pair.target_bytes)
        actor_name = _actor_filename(ordinal)
        target_name = _target_filename(ordinal)
        actor_sha = publish_exclusive_bytes(
            actor_directory / actor_name, pair.actor_bytes)
        target_sha = publish_exclusive_bytes(
            target_directory / target_name, pair.target_bytes)
        rows.append({
            "ordinal": ordinal,
            "decision_key": metadata["decision_key"],
            "round_digest": metadata["round_digest"],
            "actor_filename": actor_name,
            "actor_byte_count": len(pair.actor_bytes),
            "actor_sha256": actor_sha,
            "target_filename": target_name,
            "target_byte_count": len(pair.target_bytes),
            "target_sha256": target_sha,
        })
        if progress is not None:
            progress(ordinal + 1, total, "publish-human-decisions")
    finished = time.monotonic_ns()
    resources = _resource_row(
        freeze, started=started, finished=finished,
        cpu_nanoseconds=time.process_time_ns() - cpu_started,
        artifact_bytes=sum(row["actor_byte_count"]
                           + row["target_byte_count"] for row in rows))
    manifest = _manifest(freeze, admission, candidate, rows, resources)
    publish_exclusive_bytes(
        partial / "manifest.json", canonical_json_bytes(manifest))
    os.rename(partial, final)
    descriptor = os.open(parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    reopened = reopen_human_group_manifest(
        final, freeze=freeze, admission=admission)
    if reopened != manifest:
        raise BeliefV2HumanControllerError(
            "V2 human group post-publish drift")
    return reopened


_ROW_KEYS = {
    "ordinal", "decision_key", "round_digest", "actor_filename",
    "actor_byte_count", "actor_sha256", "target_filename",
    "target_byte_count", "target_sha256",
}


def reopen_human_group_manifest(
        directory: Path, *, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1) -> dict[str, Any]:
    """Authenticate a complete group without opening actor/target bytes."""
    if not isinstance(directory, Path) or directory.is_symlink() \
            or not directory.is_dir() \
            or not directory.name.startswith("group-"):
        raise BeliefV2HumanControllerError(
            "V2 human group directory drift")
    raw = stable_read_bytes(directory / "manifest.json")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefV2HumanControllerError(
            "V2 human group manifest is not JSON") from exc
    expected_keys = {
        "schema", "freeze_sha256", "admission_sha256",
        "h0_inventory_sha256", "human_group_split_sha256",
        "source_sha256", "group_digest", "split",
        "capture_manifest_sha256", "complete_round_count",
        "incomplete_round_count", "human_decision_count",
        "trump_rank_counts", "attempted_channel_counts", "rows",
        "resources", "source_bytes_published", "source_path_published",
        "raw_player_identity_published", "actor_target_files_separate",
        "training_authorized_by_this_artifact",
        "test_open_authorized_by_this_artifact",
        "gameplay_strength_screen_authorized", "strength_claim_authorized",
        "deployment_authorized",
    }
    if type(payload) is not dict or set(payload) != expected_keys \
            or canonical_json_bytes(payload) != raw \
            or payload["schema"] != HUMAN_GROUP_STAGE_SCHEMA \
            or payload["freeze_sha256"] != freeze.sha256() \
            or payload["admission_sha256"] != admission.sha256() \
            or payload["h0_inventory_sha256"] \
            != freeze.h0_inventory_sha256 \
            or payload["human_group_split_sha256"] \
            != freeze.human_group_split_sha256 \
            or not _is_sha256(payload["source_sha256"]) \
            or not _is_sha256(payload["group_digest"]) \
            or _group_digest(payload["source_sha256"]) \
            != payload["group_digest"] \
            or directory.name != f"group-{payload['group_digest']}" \
            or payload["split"] not in {"train", "calibration", "test"} \
            or not _is_sha256(payload["capture_manifest_sha256"]) \
            or type(payload["complete_round_count"]) is not int \
            or payload["complete_round_count"] < 0 \
            or type(payload["incomplete_round_count"]) is not int \
            or payload["incomplete_round_count"] < 0 \
            or type(payload["human_decision_count"]) is not int \
            or payload["human_decision_count"] < 0 \
            or type(payload["trump_rank_counts"]) is not dict \
            or any(key not in RANKS
                   or type(value) is not int or value <= 0
                   for key, value in payload[
                       "trump_rank_counts"].items()) \
            or sum(payload["trump_rank_counts"].values()) \
            != payload["complete_round_count"] \
            or type(payload["attempted_channel_counts"]) is not dict \
            or any(key not in {"complete", "absent"}
                   or type(value) is not int or value <= 0
                   for key, value in payload[
                       "attempted_channel_counts"].items()) \
            or sum(payload["attempted_channel_counts"].values()) \
            != payload["human_decision_count"] \
            or type(payload["rows"]) is not list \
            or len(payload["rows"]) != payload["human_decision_count"] \
            or payload["actor_target_files_separate"] is not True \
            or any(payload[key] is not False for key in (
                "source_bytes_published", "source_path_published",
                "raw_player_identity_published",
                "training_authorized_by_this_artifact",
                "test_open_authorized_by_this_artifact",
                "gameplay_strength_screen_authorized",
                "strength_claim_authorized", "deployment_authorized")):
        raise BeliefV2HumanControllerError(
            "V2 human group manifest identity drift")
    actor_directory = directory / "actor-only"
    target_directory = directory / "private-targets"
    if {path.name for path in directory.iterdir()} \
            != {"manifest.json", "actor-only", "private-targets"} \
            or actor_directory.is_symlink() or not actor_directory.is_dir() \
            or target_directory.is_symlink() \
            or not target_directory.is_dir():
        raise BeliefV2HumanControllerError(
            "V2 human group file population drift")
    actor_names = set()
    target_names = set()
    decisions = set()
    artifact_bytes = 0
    for ordinal, row in enumerate(payload["rows"]):
        if type(row) is not dict or set(row) != _ROW_KEYS \
                or row["ordinal"] != ordinal \
                or row["actor_filename"] != _actor_filename(ordinal) \
                or row["target_filename"] != _target_filename(ordinal) \
                or not _is_sha256(row["decision_key"]) \
                or not _is_sha256(row["round_digest"]) \
                or not _is_sha256(row["actor_sha256"]) \
                or not _is_sha256(row["target_sha256"]) \
                or type(row["actor_byte_count"]) is not int \
                or row["actor_byte_count"] <= 0 \
                or type(row["target_byte_count"]) is not int \
                or row["target_byte_count"] <= 0 \
                or row["decision_key"] in decisions:
            raise BeliefV2HumanControllerError(
                "V2 human group row drift")
        decisions.add(row["decision_key"])
        actor_names.add(row["actor_filename"])
        target_names.add(row["target_filename"])
        artifact_bytes += row["actor_byte_count"] + row["target_byte_count"]
        for path, size in (
                (actor_directory / row["actor_filename"],
                 row["actor_byte_count"]),
                (target_directory / row["target_filename"],
                 row["target_byte_count"])):
            info = path.lstat()
            if path.is_symlink() or not stat.S_ISREG(info.st_mode) \
                    or info.st_nlink != 1 or info.st_mode & 0o222 \
                    or info.st_size != size:
                raise BeliefV2HumanControllerError(
                    "V2 human group file shape drift")
    if {path.name for path in actor_directory.iterdir()} != actor_names \
            or {path.name for path in target_directory.iterdir()} \
            != target_names:
        raise BeliefV2HumanControllerError(
            "V2 human group row file population drift")
    resources = payload["resources"]
    if type(resources) is not dict or set(resources) != {
            "schema", "boot_identity", "started_monotonic_nanoseconds",
            "finished_monotonic_nanoseconds", "wall_nanoseconds",
            "cpu_nanoseconds", "artifact_bytes", "retry_count",
            "drop_count"} \
            or resources["schema"] != HUMAN_GROUP_RESOURCE_SCHEMA \
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
        raise BeliefV2HumanControllerError(
            "V2 human group resource drift")
    return payload


def reopen_human_training_group_examples(
        directory: Path, *, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1,
        split: str) -> tuple[V2TrainingExampleV1, ...]:
    """Open one authenticated train/calibration group, never a test group."""
    if type(split) is not str or split not in {"train", "calibration"}:
        raise BeliefV2HumanControllerError(
            "V2 human training reader split is not train/calibration")
    payload = reopen_human_group_manifest(
        directory, freeze=freeze, admission=admission)
    if payload["split"] != split:
        raise BeliefV2HumanControllerError(
            "V2 human training group split drift")
    examples = []
    pairs = []
    for row in payload["rows"]:
        actor_raw = stable_read_bytes(
            directory / "actor-only" / row["actor_filename"])
        target_raw = stable_read_bytes(
            directory / "private-targets" / row["target_filename"])
        if len(actor_raw) != row["actor_byte_count"] \
                or _sha256(actor_raw) != row["actor_sha256"] \
                or len(target_raw) != row["target_byte_count"] \
                or _sha256(target_raw) != row["target_sha256"]:
            raise BeliefV2HumanControllerError(
                "V2 human training row byte binding drift")
        try:
            example = build_human_training_example(actor_raw, target_raw)
        except ValueError as exc:
            raise BeliefV2HumanControllerError(
                "V2 human training example derivation refused") from exc
        if example.decision_key != row["decision_key"] \
                or example.round_group_key != row["round_digest"] \
                or example.split != split:
            raise BeliefV2HumanControllerError(
                "V2 human training example identity drift")
        examples.append(example)
        pairs.append(V2HumanCorpusPairV1(
            actor_bytes=actor_raw, target_bytes=target_raw))
    captured = V2HumanGroupCaptureV1(
        source_sha256=payload["source_sha256"],
        group_digest=payload["group_digest"], split=payload["split"],
        complete_round_count=payload["complete_round_count"],
        incomplete_round_count=payload["incomplete_round_count"],
        human_decision_count=payload["human_decision_count"],
        trump_rank_counts=tuple(sorted(
            payload["trump_rank_counts"].items())),
        attempted_channel_counts=tuple(sorted(
            payload["attempted_channel_counts"].items())),
        pairs=tuple(pairs))
    try:
        validate_human_group_capture(captured)
    except ValueError as exc:
        raise BeliefV2HumanControllerError(
            "V2 human training group reconstruction refused") from exc
    if _sha256(captured.manifest_bytes()) \
            != payload["capture_manifest_sha256"]:
        raise BeliefV2HumanControllerError(
            "V2 human training capture manifest drift")
    return tuple(examples)
