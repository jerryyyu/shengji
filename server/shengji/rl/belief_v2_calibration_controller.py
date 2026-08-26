"""Durable pre-test calibration selection for BELIEF-V1 V2.

Every trained cohort is reopened from its portable checkpoint.  Synthetic and
historical-human calibration targets are scored against two independently
sampled REF-C replicates.  The human-mixture retention rule, data-scale curve,
and replicate-stability checks are sealed before any test target is opened.
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
from .belief_v2_freeze import (
    HUMAN_COHORT_ID,
    PRIMARY_COHORT_ID,
    V2ExecutionFreezeV1,
    V2PipelineAdmissionV1,
)
from .belief_v2_human_reference_controller import (
    reopen_human_reference_group,
)
from .belief_v2_protocol import v2_round_coordinates
from .belief_v2_scoring import score_v2_round
from .belief_v2_scoring_controller import (
    reopen_human_scoring_rounds,
    reopen_synthetic_scoring_round,
    reopen_trained_scoring_cohorts,
    synthetic_round_key,
)
from .belief_v2_statistics import (
    evaluate_human_mixture_selection,
    evaluate_scale_curve,
    reopen_v2_round_population,
    v2_reference_replicates_are_stable,
    v2_round_population_bytes,
)
from .belief_v2_input_index_controller import reopen_training_input_index
from .belief_v2_progress import ProgressCallback


CALIBRATION_STAGE_SCHEMA = "belief-v1-v2-calibration-selection-stage-v1"
CALIBRATION_RESOURCE_SCHEMA = "belief-v1-v2-calibration-resource-v1"
POPULATION_FILES = {
    "synthetic_ref0": "synthetic-calibration-ref-0.json",
    "synthetic_ref1": "synthetic-calibration-ref-1.json",
    "human_ref0": "human-calibration-ref-0.json",
    "human_ref1": "human-calibration-ref-1.json",
}
RESULT_FILES = {
    "human_selection": "human-selection.json",
    "scale_curve": "scale-curve.json",
}


class BeliefV2CalibrationControllerError(ValueError):
    """A calibration score, selection, resource, or artifact drifted."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _expected_synthetic_rounds() -> tuple[tuple[str, str], ...]:
    return tuple((synthetic_round_key(row.round_seed), row.trump_rank)
                 for row in v2_round_coordinates()
                 if row.split == "calibration")


def _scale_fractions(freeze: V2ExecutionFreezeV1) \
        -> tuple[tuple[str, int, int], ...]:
    return tuple((row.cohort_id, row.synthetic_fraction_numerator,
                  row.synthetic_fraction_denominator)
                 for row in freeze.cohorts
                 if row.kind == "synthetic-scale")


def _score_synthetic(
        root: Path, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1, cohorts, *, replicate: str,
        progress: ProgressCallback | None = None,
        progress_phase: str = "score-synthetic-rounds"):
    rows = []
    coordinates = tuple(
        coordinate for coordinate in v2_round_coordinates()
        if coordinate.split == "calibration")
    if progress is not None:
        progress(0, len(coordinates), progress_phase)
    for unit_index, coordinate in enumerate(coordinates):
        decisions = reopen_synthetic_scoring_round(
            root, freeze=freeze, admission=admission,
            coordinate=coordinate, replicate=replicate,
            allowed_split="calibration")
        rows.append(score_v2_round(
            round_key=synthetic_round_key(coordinate.round_seed),
            source_kind="synthetic", split="calibration",
            trump_rank=coordinate.trump_rank,
            decisions=decisions, cohorts=cohorts))
        if progress is not None:
            progress(unit_index + 1, len(coordinates), progress_phase)
    return tuple(rows)


def _score_human(
        root: Path, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1, group_split: dict[str, Any],
        cohorts, *, replicate: str,
        progress: ProgressCallback | None = None,
        progress_phase: str = "score-human-groups"):
    rows = []
    digests = tuple(sorted(
        group_split["splits"]["calibration"]["group_digests"]))
    if progress is not None:
        progress(0, len(digests), progress_phase)
    for unit_index, digest in enumerate(digests):
        rounds = reopen_human_scoring_rounds(
            root, freeze=freeze, admission=admission,
            group_digest=digest, replicate=replicate,
            allowed_split="calibration")
        for round_digest, trump_rank, decisions in rounds:
            rows.append(score_v2_round(
                round_key=round_digest, source_kind="human",
                split="calibration", trump_rank=trump_rank,
                decisions=decisions, cohorts=cohorts))
        if progress is not None:
            progress(unit_index + 1, len(digests), progress_phase)
    return tuple(sorted(rows, key=lambda row: row.round_key))


def _resource_row(*, started: int, finished: int,
                  cpu_nanoseconds: int, artifact_bytes: int) \
        -> dict[str, Any]:
    if type(started) is not int or type(finished) is not int \
            or not 0 <= started < finished \
            or type(cpu_nanoseconds) is not int or cpu_nanoseconds < 0 \
            or type(artifact_bytes) is not int or artifact_bytes <= 0:
        raise BeliefV2CalibrationControllerError(
            "V2 calibration resource measurement drift")
    return {
        "schema": CALIBRATION_RESOURCE_SCHEMA,
        "started_monotonic_nanoseconds": started,
        "finished_monotonic_nanoseconds": finished,
        "wall_nanoseconds": finished - started,
        "cpu_nanoseconds": cpu_nanoseconds,
        "artifact_bytes": artifact_bytes,
        "retry_count": 0,
        "drop_count": 0,
        "test_split_decision_open_count": 0,
    }


def _manifest(
        freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1, *,
        training_input_sha256: str,
        qualification_plan_sha256: str,
        qualification_result_sha256: str,
        training_manifest_sha256s: tuple[tuple[str, str], ...],
        files: dict[str, bytes], synthetic_stable: bool,
        human_stable: bool, human_retained: bool,
        selected_cohort_id: str | None,
        resources: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": CALIBRATION_STAGE_SCHEMA,
        "freeze_sha256": freeze.sha256(),
        "admission_sha256": admission.sha256(),
        "training_input_sha256": training_input_sha256,
        "qualification_plan_sha256": qualification_plan_sha256,
        "qualification_result_sha256": qualification_result_sha256,
        "training_manifest_sha256s": dict(training_manifest_sha256s),
        "cohort_ids": [row.cohort_id for row in freeze.cohorts],
        "files": {
            key: {
                "filename": POPULATION_FILES.get(
                    key, RESULT_FILES.get(key)),
                "byte_count": len(raw), "sha256": _sha256(raw),
            } for key, raw in files.items()
        },
        "synthetic_reference_replicates_stable": synthetic_stable,
        "human_reference_replicates_stable": human_stable,
        "calibration_passed": synthetic_stable and human_stable,
        "human_mixture_retained": human_retained,
        "selected_cohort_id": selected_cohort_id,
        "resources": resources,
        "selection_completed_before_test_open": True,
        "test_split_opened": False,
        "test_open_authorized_by_this_artifact": False,
        "sampler_implementation_authorized": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }


def run_v2_calibration_selection(
        root: Path, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1, *, repo: Path,
        review_marker: bytes, inventory: dict[str, Any],
        group_split: dict[str, Any],
        progress: ProgressCallback | None = None) -> dict[str, Any]:
    """Score both calibration replicates and atomically seal selection."""
    _stage_gate(
        root=root, repo=repo, freeze=freeze, admission=admission,
        review_marker=review_marker)
    try:
        _, training_inputs = reopen_training_input_index(
            root / "training-input-index" / "result", freeze=freeze,
            admission=admission)
        cohorts, plan, qualification, training_hashes = (
            reopen_trained_scoring_cohorts(
                root, freeze=freeze, admission=admission,
                training_inputs=training_inputs))
    except ValueError as exc:
        raise BeliefV2CalibrationControllerError(
            "V2 calibration training population refused") from exc
    cohort_ids = tuple(row.cohort_id for row in cohorts)
    started = time.monotonic_ns()
    cpu_started = time.process_time_ns()
    if progress is not None:
        progress(0, 6, "score-calibration-populations")
    try:
        synthetic_0 = _score_synthetic(
            root, freeze, admission, cohorts,
            replicate="calibration-replicate-0", progress=progress,
            progress_phase="score-synthetic-ref0-rounds")
        if progress is not None:
            progress(1, 6, "score-calibration-populations")
        synthetic_1 = _score_synthetic(
            root, freeze, admission, cohorts,
            replicate="calibration-replicate-1", progress=progress,
            progress_phase="score-synthetic-ref1-rounds")
        if progress is not None:
            progress(2, 6, "score-calibration-populations")
        human_0 = _score_human(
            root, freeze, admission, group_split, cohorts,
            replicate="calibration-replicate-0", progress=progress,
            progress_phase="score-human-ref0-groups")
        if progress is not None:
            progress(3, 6, "score-calibration-populations")
        human_1 = _score_human(
            root, freeze, admission, group_split, cohorts,
            replicate="calibration-replicate-1", progress=progress,
            progress_phase="score-human-ref1-groups")
        if progress is not None:
            progress(4, 6, "score-calibration-populations")
    except ValueError as exc:
        raise BeliefV2CalibrationControllerError(
            "V2 calibration scoring population refused") from exc
    expected_synthetic = _expected_synthetic_rounds()
    expected_human = tuple((row.round_key, row.trump_rank)
                           for row in human_0)
    try:
        synthetic_stable = v2_reference_replicates_are_stable(
            synthetic_0, synthetic_1, cohort_ids=cohort_ids,
            expected_rounds=expected_synthetic, source_kind="synthetic")
        human_stable = v2_reference_replicates_are_stable(
            human_0, human_1, cohort_ids=cohort_ids,
            expected_rounds=expected_human, source_kind="human")
        human_selection = evaluate_human_mixture_selection(
            synthetic_0, human_0,
            expected_synthetic_rounds=expected_synthetic,
            expected_human_rounds=expected_human,
            cohort_ids=cohort_ids)
        scale_curve = evaluate_scale_curve(
            synthetic_0, expected_synthetic_rounds=expected_synthetic,
            cohort_ids=cohort_ids,
            scale_fractions=_scale_fractions(freeze))
        if progress is not None:
            progress(5, 6, "derive-calibration-statistics")
    except ValueError as exc:
        raise BeliefV2CalibrationControllerError(
            "V2 calibration statistic refused") from exc
    stable = synthetic_stable and human_stable
    selected = None if not stable else (
        HUMAN_COHORT_ID if human_selection.retained else PRIMARY_COHORT_ID)
    population_rows = {
        "synthetic_ref0": synthetic_0,
        "synthetic_ref1": synthetic_1,
        "human_ref0": human_0,
        "human_ref1": human_1,
    }
    files = {
        key: v2_round_population_bytes(
            rows, cohort_ids=cohort_ids, label=key)
        for key, rows in population_rows.items()
    }
    files.update({
        "human_selection": human_selection.canonical_bytes(),
        "scale_curve": scale_curve.canonical_bytes(),
    })
    parent = root / "calibration"
    if parent.is_symlink():
        raise BeliefV2CalibrationControllerError(
            "V2 calibration parent is a symlink")
    parent.mkdir(mode=0o700, exist_ok=True)
    final = parent / "selection"
    partial = parent / "selection.partial"
    if final.exists() or partial.exists() \
            or final.is_symlink() or partial.is_symlink():
        raise BeliefV2CalibrationControllerError(
            "V2 calibration selection slot is occupied")
    partial.mkdir(mode=0o700)
    for key, raw in files.items():
        filename = POPULATION_FILES.get(key, RESULT_FILES.get(key))
        publish_exclusive_bytes(partial / filename, raw)
    finished = time.monotonic_ns()
    resources = _resource_row(
        started=started, finished=finished,
        cpu_nanoseconds=time.process_time_ns() - cpu_started,
        artifact_bytes=sum(len(raw) for raw in files.values()))
    manifest = _manifest(
        freeze, admission,
        training_input_sha256=training_inputs.sha256(),
        qualification_plan_sha256=plan.sha256(),
        qualification_result_sha256=_sha256(
            qualification.canonical_bytes(plan)),
        training_manifest_sha256s=training_hashes,
        files=files, synthetic_stable=synthetic_stable,
        human_stable=human_stable,
        human_retained=human_selection.retained,
        selected_cohort_id=selected, resources=resources)
    publish_exclusive_bytes(
        partial / "manifest.json", canonical_json_bytes(manifest))
    os.rename(partial, final)
    descriptor = os.open(parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    reopened = reopen_v2_calibration_selection(
        final, freeze=freeze, admission=admission,
        inventory=inventory, group_split=group_split)
    if reopened != manifest:
        raise BeliefV2CalibrationControllerError(
            "V2 calibration post-publish drift")
    if progress is not None:
        progress(6, 6, "calibration-complete")
    return reopened


def _expected_human_rounds_from_references(
        root: Path, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1,
        group_split: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    rows = []
    for digest in sorted(
            group_split["splits"]["calibration"]["group_digests"]):
        manifest = reopen_human_reference_group(
            root / "human-reference" / f"group-{digest}"
            / "calibration-replicate-0",
            freeze=freeze, admission=admission)
        seen = set()
        for row in manifest["rows"]:
            key = row["round_digest"]
            if key not in seen:
                rows.append((key, row["trump_rank"]))
                seen.add(key)
    if not rows or len({key for key, _ in rows}) != len(rows):
        raise BeliefV2CalibrationControllerError(
            "V2 calibration human round identity drift")
    # Scoring emits canonical round-digest order.  Expected populations must
    # use the same order rather than source-manifest encounter order; ordinal
    # round digests are intentionally not monotone within a source group.
    return tuple(sorted(rows))


def reopen_v2_calibration_selection(
        directory: Path, *, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1,
        inventory: dict[str, Any], group_split: dict[str, Any]) \
        -> dict[str, Any]:
    """Reopen raw score populations and independently rederive selection."""
    if not isinstance(directory, Path) or directory.is_symlink() \
            or not directory.is_dir() or directory.name != "selection" \
            or {path.name for path in directory.iterdir()} != {
                "manifest.json", *POPULATION_FILES.values(),
                *RESULT_FILES.values()}:
        raise BeliefV2CalibrationControllerError(
            "V2 calibration directory population drift")
    raw_manifest = stable_read_bytes(directory / "manifest.json")
    try:
        payload = json.loads(raw_manifest)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefV2CalibrationControllerError(
            "V2 calibration manifest is not JSON") from exc
    expected_keys = {
        "schema", "freeze_sha256", "admission_sha256",
        "training_input_sha256", "qualification_plan_sha256",
        "qualification_result_sha256", "training_manifest_sha256s",
        "cohort_ids", "files",
        "synthetic_reference_replicates_stable",
        "human_reference_replicates_stable", "calibration_passed",
        "human_mixture_retained", "selected_cohort_id", "resources",
        "selection_completed_before_test_open", "test_split_opened",
        "test_open_authorized_by_this_artifact",
        "sampler_implementation_authorized",
        "gameplay_strength_screen_authorized", "strength_claim_authorized",
        "deployment_authorized",
    }
    if type(payload) is not dict or set(payload) != expected_keys \
            or canonical_json_bytes(payload) != raw_manifest \
            or payload["schema"] != CALIBRATION_STAGE_SCHEMA \
            or payload["freeze_sha256"] != freeze.sha256() \
            or payload["admission_sha256"] != admission.sha256() \
            or payload["cohort_ids"] \
            != [row.cohort_id for row in freeze.cohorts] \
            or payload["selection_completed_before_test_open"] is not True \
            or payload["test_split_opened"] is not False \
            or any(payload[key] is not False for key in (
                "test_open_authorized_by_this_artifact",
                "sampler_implementation_authorized",
                "gameplay_strength_screen_authorized",
                "strength_claim_authorized", "deployment_authorized")):
        raise BeliefV2CalibrationControllerError(
            "V2 calibration manifest identity/authority drift")
    expected_file_keys = set(POPULATION_FILES) | set(RESULT_FILES)
    if type(payload["files"]) is not dict \
            or set(payload["files"]) != expected_file_keys:
        raise BeliefV2CalibrationControllerError(
            "V2 calibration manifest file population drift")
    try:
        _, training_inputs = reopen_training_input_index(
            Path(freeze.evidence_root) / "training-input-index" / "result",
            freeze=freeze, admission=admission)
        _, plan, qualification, training_hashes = (
            reopen_trained_scoring_cohorts(
                Path(freeze.evidence_root), freeze=freeze,
                admission=admission, training_inputs=training_inputs))
    except ValueError as exc:
        raise BeliefV2CalibrationControllerError(
            "V2 calibration training reopener refused") from exc
    if payload["training_input_sha256"] != training_inputs.sha256() \
            or payload["qualification_plan_sha256"] != plan.sha256() \
            or payload["qualification_result_sha256"] != _sha256(
                qualification.canonical_bytes(plan)) \
            or payload["training_manifest_sha256s"] \
            != dict(training_hashes):
        raise BeliefV2CalibrationControllerError(
            "V2 calibration training identity drift")
    cohort_ids = tuple(payload["cohort_ids"])
    files = {}
    populations = {}
    for key, filename in {**POPULATION_FILES, **RESULT_FILES}.items():
        raw = stable_read_bytes(directory / filename)
        row = payload["files"].get(key)
        if type(row) is not dict or set(row) != {
                "filename", "byte_count", "sha256"} \
                or row["filename"] != filename \
                or row["byte_count"] != len(raw) \
                or row["sha256"] != _sha256(raw):
            raise BeliefV2CalibrationControllerError(
                "V2 calibration file byte binding drift")
        files[key] = raw
        if key in POPULATION_FILES:
            try:
                populations[key] = reopen_v2_round_population(
                    raw, cohort_ids=cohort_ids, label=key)
            except ValueError as exc:
                raise BeliefV2CalibrationControllerError(
                    "V2 calibration score population refused") from exc
    expected_synthetic = _expected_synthetic_rounds()
    expected_human = _expected_human_rounds_from_references(
        Path(freeze.evidence_root), freeze, admission, group_split)
    try:
        synthetic_stable = v2_reference_replicates_are_stable(
            populations["synthetic_ref0"],
            populations["synthetic_ref1"], cohort_ids=cohort_ids,
            expected_rounds=expected_synthetic, source_kind="synthetic")
        human_stable = v2_reference_replicates_are_stable(
            populations["human_ref0"], populations["human_ref1"],
            cohort_ids=cohort_ids, expected_rounds=expected_human,
            source_kind="human")
        human_selection = evaluate_human_mixture_selection(
            populations["synthetic_ref0"], populations["human_ref0"],
            expected_synthetic_rounds=expected_synthetic,
            expected_human_rounds=expected_human, cohort_ids=cohort_ids)
        scale_curve = evaluate_scale_curve(
            populations["synthetic_ref0"],
            expected_synthetic_rounds=expected_synthetic,
            cohort_ids=cohort_ids,
            scale_fractions=_scale_fractions(freeze))
    except ValueError as exc:
        raise BeliefV2CalibrationControllerError(
            "V2 calibration reconstruction statistic refused") from exc
    if files["human_selection"] != human_selection.canonical_bytes() \
            or files["scale_curve"] != scale_curve.canonical_bytes():
        raise BeliefV2CalibrationControllerError(
            "V2 calibration result reconstruction drift")
    stable = synthetic_stable and human_stable
    selected = None if not stable else (
        HUMAN_COHORT_ID if human_selection.retained else PRIMARY_COHORT_ID)
    resources = payload["resources"]
    if type(resources) is not dict or set(resources) != {
            "schema", "started_monotonic_nanoseconds",
            "finished_monotonic_nanoseconds", "wall_nanoseconds",
            "cpu_nanoseconds", "artifact_bytes", "retry_count",
            "drop_count", "test_split_decision_open_count"} \
            or resources["schema"] != CALIBRATION_RESOURCE_SCHEMA \
            or type(resources["started_monotonic_nanoseconds"]) is not int \
            or type(resources["finished_monotonic_nanoseconds"]) is not int \
            or not 0 <= resources["started_monotonic_nanoseconds"] \
            < resources["finished_monotonic_nanoseconds"] \
            or resources["wall_nanoseconds"] != (
                resources["finished_monotonic_nanoseconds"]
                - resources["started_monotonic_nanoseconds"]) \
            or type(resources["cpu_nanoseconds"]) is not int \
            or resources["cpu_nanoseconds"] < 0 \
            or resources["artifact_bytes"] \
            != sum(len(raw) for raw in files.values()) \
            or resources["retry_count"] != 0 \
            or resources["drop_count"] != 0 \
            or resources["test_split_decision_open_count"] != 0:
        raise BeliefV2CalibrationControllerError(
            "V2 calibration resource reconstruction drift")
    expected_manifest = _manifest(
        freeze, admission,
        training_input_sha256=training_inputs.sha256(),
        qualification_plan_sha256=plan.sha256(),
        qualification_result_sha256=_sha256(
            qualification.canonical_bytes(plan)),
        training_manifest_sha256s=training_hashes,
        files=files, synthetic_stable=synthetic_stable,
        human_stable=human_stable,
        human_retained=human_selection.retained,
        selected_cohort_id=selected, resources=resources)
    if payload != expected_manifest:
        raise BeliefV2CalibrationControllerError(
            "V2 calibration manifest reconstruction drift")
    return payload
