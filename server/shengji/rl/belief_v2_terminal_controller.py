"""One-shot test opening and independently reopenable BELIEF-V1 V2 terminal."""

from __future__ import annotations

from concurrent.futures import Executor, ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .belief_artifacts import publish_exclusive_bytes, stable_read_bytes
from .belief_cohort import COHORT_SEEDS
from .belief_contract import canonical_json_bytes
from .belief_v2_calibration_controller import (
    POPULATION_FILES as CALIBRATION_POPULATION_FILES,
    reopen_v2_calibration_selection,
    _expected_human_rounds_from_references,
    _expected_synthetic_rounds,
    _scale_fractions,
)
from .belief_v2_controller import (
    _stage_gate,
    reopen_capture_lane,
    reopen_reference_lane,
)
from .belief_v2_device_qualification import training_host_memory_upper_bound
from .belief_v2_freeze import (
    CONTROL_COHORT_ID,
    HUMAN_COHORT_ID,
    PRIMARY_COHORT_ID,
    V2ExecutionFreezeV1,
    V2PipelineAdmissionV1,
)
from .belief_v2_human_controller import reopen_human_group_manifest
from .belief_v2_human_reference_controller import (
    reopen_human_reference_group,
)
from .belief_v2_protocol import (
    V2_CAPTURE_LANES,
    V2_ROUND_COUNT,
    V2_SPLIT_COUNTS,
    v2_round_coordinates,
)
from .belief_v2_result import (
    V2IntegrityResourceReceiptV1,
    derive_terminal_result,
    expected_reference_job_count,
    validate_terminal_result,
)
from .belief_v2_progress import ProgressCallback
from .belief_v2_scoring import V2DecisionScoringPool, score_v2_round
from .belief_v2_scoring_controller import (
    reopen_human_scoring_rounds,
    reopen_synthetic_scoring_round,
    reopen_trained_scoring_cohorts,
    synthetic_round_key,
)
from .belief_v2_statistics import (
    evaluate_human_mixture_selection,
    evaluate_human_transfer_test,
    evaluate_label_control_test,
    evaluate_primary_test,
    evaluate_scale_curve,
    reopen_v2_round_population,
    v2_round_population_bytes,
)
from .belief_v2_input_index_controller import reopen_training_input_index
from .belief_v2_tensor_cache_controller import reopen_training_tensor_cache


TERMINAL_ATTEMPT_SCHEMA = "belief-v1-v2-test-opening-attempt-v1"
TERMINAL_STAGE_SCHEMA = "belief-v1-v2-terminal-stage-v1"
TEST_POPULATION_FILES = {
    "synthetic_test": "synthetic-test-scores.json",
    "human_test": "human-test-scores.json",
}
STATISTIC_FILES = {
    "human_selection": "human-selection.json",
    "scale_curve": "scale-curve.json",
    "primary_test": "primary-test.json",
    "label_control_test": "label-control-test.json",
    "human_transfer": "human-transfer.json",
    "integrity_receipt": "integrity-receipt.json",
    "terminal_result": "result.json",
}


class BeliefV2TerminalControllerError(ValueError):
    """A one-shot opening, score, receipt, or terminal byte drifted."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _run_independent_terminal_statistics(primary_call, control_call,
                                         human_call):
    """Evaluate the three independently seeded terminal reports in parallel."""
    if not all(callable(value) for value in (
            primary_call, control_call, human_call)):
        raise BeliefV2TerminalControllerError(
            "V2 terminal statistic callable population drift")
    with ThreadPoolExecutor(
            max_workers=3,
            thread_name_prefix="belief-v2-terminal-statistic") as executor:
        futures = tuple(executor.submit(value) for value in (
            primary_call, control_call, human_call))
        return tuple(future.result() for future in futures)


def _human_group_digests(
        group_split: dict[str, Any], split: str) -> tuple[str, ...]:
    try:
        values = tuple(sorted(group_split["splits"][split]["group_digests"]))
    except (KeyError, TypeError) as exc:
        raise BeliefV2TerminalControllerError(
            "V2 terminal human group split drift") from exc
    if not values or len(set(values)) != len(values) \
            or any(type(value) is not str or len(value) != 64
                   or any(char not in "0123456789abcdef" for char in value)
                   for value in values):
        raise BeliefV2TerminalControllerError(
            "V2 terminal human group population drift")
    return values


def _expected_test_synthetic_rounds() -> tuple[tuple[str, str], ...]:
    return tuple((synthetic_round_key(row.round_seed), row.trump_rank)
                 for row in v2_round_coordinates() if row.split == "test")


def _expected_test_human_rounds(
        root: Path, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1,
        group_split: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    rows = []
    seen = set()
    for digest in _human_group_digests(group_split, "test"):
        manifest = reopen_human_reference_group(
            root / "human-reference" / f"group-{digest}" / "test-primary",
            freeze=freeze, admission=admission)
        for row in manifest["rows"]:
            key = row["round_digest"]
            if key not in seen:
                rows.append((key, row["trump_rank"]))
                seen.add(key)
    if not rows:
        raise BeliefV2TerminalControllerError(
            "V2 terminal human test rounds are empty")
    return tuple(sorted(rows))


def _score_test_populations(
        root: Path, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1,
        group_split: dict[str, Any], cohorts, *,
        projection_executor: Executor | None = None,
        decision_pool: V2DecisionScoringPool | None = None,
        progress: ProgressCallback | None = None,
        progress_phase_prefix: str = "score-test"):
    if type(progress_phase_prefix) is not str \
            or not progress_phase_prefix.isascii() \
            or not progress_phase_prefix \
            or any(not (char.isalnum() or char in "-_.")
                   for char in progress_phase_prefix):
        raise BeliefV2TerminalControllerError(
            "V2 terminal progress phase identity drift")
    synthetic_phase = f"{progress_phase_prefix}-synthetic-rounds"
    human_phase = f"{progress_phase_prefix}-human-groups"
    synthetic = []
    synthetic_coordinates = tuple(
        coordinate for coordinate in v2_round_coordinates()
        if coordinate.split == "test")
    for index, coordinate in enumerate(synthetic_coordinates):
        if progress is not None:
            progress(index, len(synthetic_coordinates), synthetic_phase)
        decisions = reopen_synthetic_scoring_round(
            root, freeze=freeze, admission=admission,
            coordinate=coordinate, replicate="test-primary",
            allowed_split="test")
        synthetic.append(score_v2_round(
            round_key=synthetic_round_key(coordinate.round_seed),
            source_kind="synthetic", split="test",
            trump_rank=coordinate.trump_rank,
            decisions=decisions, cohorts=cohorts,
            projection_executor=projection_executor,
            decision_pool=decision_pool))
    if progress is not None:
        progress(len(synthetic_coordinates), len(synthetic_coordinates),
                 synthetic_phase)
    human = []
    human_groups = _human_group_digests(group_split, "test")
    for index, digest in enumerate(human_groups):
        if progress is not None:
            progress(index, len(human_groups), human_phase)
        rounds = reopen_human_scoring_rounds(
            root, freeze=freeze, admission=admission,
            group_digest=digest, replicate="test-primary",
            allowed_split="test")
        for round_digest, trump_rank, decisions in rounds:
            human.append(score_v2_round(
                round_key=round_digest, source_kind="human", split="test",
                trump_rank=trump_rank, decisions=decisions,
                cohorts=cohorts,
                projection_executor=projection_executor,
                decision_pool=decision_pool))
    if progress is not None:
        progress(len(human_groups), len(human_groups), human_phase)
    if not synthetic or not human:
        raise BeliefV2TerminalControllerError(
            "V2 terminal test score population is empty")
    return (tuple(synthetic),
            tuple(sorted(human, key=lambda row: row.round_key)))


def _calibration_statistics(
        root: Path, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1,
        inventory: dict[str, Any], group_split: dict[str, Any], *,
        calibration_directory: Path | None = None,
        legacy_tensor_cache_manifest_sha256: str | None = None):
    directory = (root / "calibration" / "selection"
                 if calibration_directory is None
                 else calibration_directory)
    manifest = reopen_v2_calibration_selection(
        directory, freeze=freeze,
        admission=admission, inventory=inventory, group_split=group_split,
        legacy_tensor_cache_manifest_sha256=(
            legacy_tensor_cache_manifest_sha256))
    if manifest["calibration_passed"] is not True \
            or manifest["selected_cohort_id"] not in {
                PRIMARY_COHORT_ID, HUMAN_COHORT_ID}:
        raise BeliefV2TerminalControllerError(
            "V2 terminal test opening lacks stable calibration selection")
    cohort_ids = tuple(manifest["cohort_ids"])
    try:
        synthetic = reopen_v2_round_population(
            stable_read_bytes(directory / CALIBRATION_POPULATION_FILES[
                "synthetic_ref0"]),
            cohort_ids=cohort_ids, label="synthetic_ref0")
        human = reopen_v2_round_population(
            stable_read_bytes(directory / CALIBRATION_POPULATION_FILES[
                "human_ref0"]),
            cohort_ids=cohort_ids, label="human_ref0")
        human_selection = evaluate_human_mixture_selection(
            synthetic, human,
            expected_synthetic_rounds=_expected_synthetic_rounds(),
            expected_human_rounds=_expected_human_rounds_from_references(
                root, freeze, admission, group_split),
            cohort_ids=cohort_ids)
        scale_curve = evaluate_scale_curve(
            synthetic,
            expected_synthetic_rounds=_expected_synthetic_rounds(),
            cohort_ids=cohort_ids,
            scale_fractions=_scale_fractions(freeze))
    except ValueError as exc:
        raise BeliefV2TerminalControllerError(
            "V2 terminal calibration reconstruction refused") from exc
    selected = HUMAN_COHORT_ID if human_selection.retained \
        else PRIMARY_COHORT_ID
    if selected != manifest["selected_cohort_id"]:
        raise BeliefV2TerminalControllerError(
            "V2 terminal calibration selection drift")
    return manifest, human_selection, scale_curve


def _parallel_span(resources: tuple[dict[str, Any], ...]) -> int:
    if not resources:
        raise BeliefV2TerminalControllerError(
            "V2 terminal resource population is empty")
    return (max(row["finished_monotonic_nanoseconds"] for row in resources)
            - min(row["started_monotonic_nanoseconds"] for row in resources))


def _derive_integrity_receipt(
        root: Path, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1,
        group_split: dict[str, Any], *, plan, qualification,
        input_index_manifest: dict[str, Any],
        training_hashes: tuple[tuple[str, str], ...],
        synthetic_test_count: int, human_test_decision_count: int,
        legacy_tensor_cache_manifest_sha256: str | None = None):
    expected_training_ids = tuple(row.cohort_id for row in freeze.cohorts)
    if type(training_hashes) is not tuple \
            or tuple(key for key, _ in training_hashes) \
            != expected_training_ids \
            or any(type(value) is not str or len(value) != 64
                   or any(char not in "0123456789abcdef" for char in value)
                   for _, value in training_hashes):
        raise BeliefV2TerminalControllerError(
            "V2 terminal training manifest population drift")
    capture_manifests = tuple(reopen_capture_lane(
        root / "capture" / f"lane-{lane:02d}", freeze=freeze,
        admission=admission, lane=lane) for lane in range(V2_CAPTURE_LANES))
    reference_manifests = tuple(reopen_reference_lane(
        root / "reference" / f"lane-{lane:02d}",
        capture_directory=root / "capture" / f"lane-{lane:02d}",
        freeze=freeze, admission=admission, lane=lane)
        for lane in range(V2_CAPTURE_LANES))
    all_human = tuple(
        digest for split in ("train", "calibration", "test")
        for digest in _human_group_digests(group_split, split))
    if len(set(all_human)) != len(all_human):
        raise BeliefV2TerminalControllerError(
            "V2 terminal human group split overlap")
    human_capture = tuple(reopen_human_group_manifest(
        root / "human-capture" / f"group-{digest}",
        freeze=freeze, admission=admission) for digest in all_human)
    human_reference = []
    for split, replicates in (
            ("calibration", ("calibration-replicate-0",
                             "calibration-replicate-1")),
            ("test", ("test-primary",))):
        for digest in _human_group_digests(group_split, split):
            for replicate in replicates:
                human_reference.append(reopen_human_reference_group(
                    root / "human-reference" / f"group-{digest}"
                    / replicate, freeze=freeze, admission=admission))
    training_manifests = []
    for cohort_id, expected_sha in training_hashes:
        raw = stable_read_bytes(
            root / "training" / cohort_id / "manifest.json")
        if _sha256(raw) != expected_sha:
            raise BeliefV2TerminalControllerError(
                "V2 terminal training manifest hash drift")
        try:
            training_manifests.append(json.loads(raw))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BeliefV2TerminalControllerError(
                "V2 terminal training manifest is not JSON") from exc
    capture_resources = tuple(row["resources"] for row in (
        *capture_manifests, *human_capture))
    reference_resources = tuple(row["resources"] for row in (
        *reference_manifests, *human_reference))
    training_resources = tuple(row["resources"] for row in training_manifests)
    input_index_resources = input_index_manifest["resources"]
    try:
        cache_manifest, _, _, _, _ = reopen_training_tensor_cache(
            root / "training-tensor-cache" / "result",
            freeze=freeze, admission=admission,
            legacy_manifest_sha256=legacy_tensor_cache_manifest_sha256)
    except ValueError as exc:
        raise BeliefV2TerminalControllerError(
            "V2 terminal tensor cache refused") from exc
    cache_resources = cache_manifest["resources"]
    try:
        qualification_process_count, qualification_host_memory = (
            training_host_memory_upper_bound(
                max(arm.peak_host_memory_bytes for arm in qualification.arms
                    if not arm.warmup
                    and arm.device == qualification.selected_device),
                selected_device=qualification.selected_device,
                cpu_cohort_process_count=len(freeze.cohorts)))
        training_host_memory = []
        for resources in training_resources:
            process_count, aggregate = training_host_memory_upper_bound(
                resources["peak_host_memory_bytes"],
                selected_device=qualification.selected_device,
                cpu_cohort_process_count=len(freeze.cohorts))
            if resources.get("selected_device") \
                    != qualification.selected_device \
                    or resources.get("host_memory_process_count") \
                    != process_count \
                    or resources.get(
                        "aggregate_peak_host_memory_upper_bound_bytes") \
                    != aggregate:
                raise BeliefV2TerminalControllerError(
                    "V2 terminal training host memory reconstruction drift")
            training_host_memory.append(aggregate)
    except (KeyError, TypeError, ValueError) as exc:
        raise BeliefV2TerminalControllerError(
            "V2 terminal training host memory reconstruction drift") from exc
    expected_process_count = (
        len(freeze.cohorts)
        if qualification.selected_device == "cpu" else 1)
    if qualification_process_count != expected_process_count \
            or max(qualification_host_memory, *training_host_memory) \
            > freeze.resource_caps.training_host_memory_bytes:
        raise BeliefV2TerminalControllerError(
            "V2 terminal aggregate host memory cap exceeded")
    qualification_compute = sum(row.wall_nanoseconds
                                for row in qualification.arms)
    qualification_bytes = len(plan.canonical_bytes()) \
        + len(qualification.canonical_bytes(plan))
    capture_rounds = sum(row["round_count"] for row in capture_manifests)
    reference_jobs = sum(row["job_count"] for row in reference_manifests)
    return V2IntegrityResourceReceiptV1(
        freeze_sha256=freeze.sha256(),
        device_qualification_plan_sha256=plan.sha256(),
        device_qualification_result_sha256=_sha256(
            qualification.canonical_bytes(plan)),
        training_device=qualification.selected_device,
        capture_expected_round_count=V2_ROUND_COUNT,
        capture_reopened_round_count=capture_rounds,
        reference_expected_round_count=expected_reference_job_count(),
        reference_reopened_round_count=reference_jobs,
        training_expected_cohort_count=len(freeze.cohorts),
        training_reopened_cohort_count=len(training_manifests),
        training_expected_checkpoint_count=(
            len(freeze.cohorts) * len(COHORT_SEEDS)),
        training_reopened_checkpoint_count=(
            len(training_manifests) * len(COHORT_SEEDS)),
        synthetic_test_expected_round_count=dict(V2_SPLIT_COUNTS)["test"],
        synthetic_test_reopened_round_count=synthetic_test_count,
        human_test_expected_decision_count=(
            freeze.human_test_eligible_decision_count),
        human_test_reopened_decision_count=human_test_decision_count,
        capture_cpu_nanoseconds=sum(
            row["cpu_nanoseconds"] for row in capture_resources),
        capture_wall_nanoseconds=_parallel_span(capture_resources),
        capture_artifact_bytes=sum(
            row["artifact_bytes"] for row in capture_resources),
        reference_cpu_nanoseconds=sum(
            row["cpu_nanoseconds"] for row in reference_resources),
        reference_wall_nanoseconds=_parallel_span(reference_resources),
        reference_artifact_bytes=sum(
            row["artifact_bytes"] for row in reference_resources),
        training_device_nanoseconds=(
            input_index_resources["wall_nanoseconds"]
            + cache_resources["wall_nanoseconds"]
            + qualification_compute + sum(
                row["training_compute_nanoseconds"]
                for row in training_resources)),
        training_wall_nanoseconds=(
            input_index_resources["wall_nanoseconds"]
            + cache_resources["wall_nanoseconds"]
            + qualification_compute + _parallel_span(training_resources)),
        training_artifact_bytes=(
            input_index_resources["artifact_bytes"]
            + cache_resources["artifact_bytes"]
            + qualification_bytes + sum(
                row["artifact_bytes"] for row in training_resources)),
        training_peak_host_memory_bytes=max(
            input_index_resources["peak_host_memory_bytes"],
            cache_resources["peak_host_memory_bytes"],
            qualification_host_memory,
            max(training_host_memory)),
        training_peak_device_memory_bytes=max(
            max(row["peak_device_memory_bytes"] for row in training_resources),
            max(arm.peak_device_memory_bytes for arm in qualification.arms)),
        capture_failure_count=0, reference_failure_count=0,
        training_failure_count=0, mechanics_failure_count=0,
        resource_cap_violation_count=0,
        retry_count=(input_index_resources["retry_count"]
                     + cache_resources["retry_count"] + sum(
            row["retry_count"] for row in (
                *capture_resources, *reference_resources,
                *training_resources))),
        drop_count=(input_index_resources["drop_count"]
                    + cache_resources["drop_count"] + sum(
            row["drop_count"] for row in (
                *capture_resources, *reference_resources,
                *training_resources))),
        test_split_decision_open_count=1)


def _attempt(
        freeze: V2ExecutionFreezeV1, admission: V2PipelineAdmissionV1,
        calibration: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": TERMINAL_ATTEMPT_SCHEMA,
        "freeze_sha256": freeze.sha256(),
        "admission_sha256": admission.sha256(),
        "calibration_manifest_sha256": _sha256(
            canonical_json_bytes(calibration)),
        "selected_cohort_id": calibration["selected_cohort_id"],
        "test_split_decision_open_count": 1,
        "retry_count": 0,
        "published_before_test_target_read": True,
        "sampler_implementation_authorized": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }


def _stage_manifest(
        freeze: V2ExecutionFreezeV1, admission: V2PipelineAdmissionV1,
        calibration: dict[str, Any], attempt: dict[str, Any],
        files: dict[str, bytes], terminal_route: str) -> dict[str, Any]:
    return {
        "schema": TERMINAL_STAGE_SCHEMA,
        "freeze_sha256": freeze.sha256(),
        "admission_sha256": admission.sha256(),
        "calibration_manifest_sha256": _sha256(
            canonical_json_bytes(calibration)),
        "attempt_sha256": _sha256(canonical_json_bytes(attempt)),
        "selected_cohort_id": calibration["selected_cohort_id"],
        "terminal_route": terminal_route,
        "files": {key: {
            "filename": (TEST_POPULATION_FILES | STATISTIC_FILES)[key],
            "byte_count": len(raw), "sha256": _sha256(raw),
        } for key, raw in files.items()},
        "test_split_decision_open_count": 1,
        "retry_count": 0,
        "test_result_reconstruction_authorized": True,
        "sampler_implementation_authorized": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "promotion_authorized": False,
        "deployment_authorized": False,
    }


def run_v2_terminal(
        root: Path, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1, *, repo: Path,
        review_marker: bytes, inventory: dict[str, Any],
        group_split: dict[str, Any],
        progress: ProgressCallback | None = None) -> dict[str, Any]:
    """Consume the sole test opening after durable attempt publication."""
    _stage_gate(root=root, repo=repo, freeze=freeze, admission=admission,
                review_marker=review_marker)
    if progress is not None:
        progress(0, 5, "prepare-test-opening")
    calibration, human_selection, scale_curve = _calibration_statistics(
        root, freeze, admission, inventory, group_split)
    attempt = _attempt(freeze, admission, calibration)
    partial = root / "terminal.partial"
    final = root / "terminal"
    if final.exists() or partial.exists() or final.is_symlink() \
            or partial.is_symlink():
        raise BeliefV2TerminalControllerError(
            "V2 terminal result slot is occupied")
    partial.mkdir(mode=0o700)
    publish_exclusive_bytes(
        partial / "attempt.json", canonical_json_bytes(attempt))
    descriptor = os.open(root, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if progress is not None:
        progress(1, 5, "test-opening-recorded")
    try:
        input_index_manifest, training_inputs = reopen_training_input_index(
            root / "training-input-index" / "result", freeze=freeze,
            admission=admission)
        cohorts, plan, qualification, training_hashes = (
            reopen_trained_scoring_cohorts(
                root, freeze=freeze, admission=admission,
                training_inputs=training_inputs))
        if progress is not None:
            progress(2, 5, "test-inputs-reopened")
        synthetic, human = _score_test_populations(
            root, freeze, admission, group_split, cohorts,
            progress=progress)
        if progress is not None:
            progress(3, 5, "test-populations-scored")
        cohort_ids = tuple(row.cohort_id for row in cohorts)
        expected_synthetic = _expected_test_synthetic_rounds()
        expected_human = _expected_test_human_rounds(
            root, freeze, admission, group_split)
        primary, control, human_transfer = (
            _run_independent_terminal_statistics(
                lambda: evaluate_primary_test(
                    synthetic,
                    selected_cohort_id=calibration["selected_cohort_id"],
                    expected_synthetic_rounds=expected_synthetic,
                    cohort_ids=cohort_ids),
                lambda: evaluate_label_control_test(
                    synthetic,
                    expected_synthetic_rounds=expected_synthetic,
                    cohort_ids=cohort_ids),
                lambda: evaluate_human_transfer_test(
                    human,
                    selected_cohort_id=calibration["selected_cohort_id"],
                    expected_human_rounds=expected_human,
                    cohort_ids=cohort_ids)))
        receipt = _derive_integrity_receipt(
            root, freeze, admission, group_split, plan=plan,
            qualification=qualification,
            input_index_manifest=input_index_manifest,
            training_hashes=training_hashes,
            synthetic_test_count=len(synthetic),
            human_test_decision_count=sum(row.decision_count for row in human))
        result = derive_terminal_result(
            freeze, plan, qualification, receipt, human_selection,
            scale_curve, primary, control, human_transfer)
        if progress is not None:
            progress(4, 5, "terminal-statistics-derived")
    except ValueError as exc:
        raise BeliefV2TerminalControllerError(
            "V2 terminal test derivation refused after durable attempt") from exc
    files = {
        "synthetic_test": v2_round_population_bytes(
            synthetic, cohort_ids=cohort_ids, label="synthetic_test"),
        "human_test": v2_round_population_bytes(
            human, cohort_ids=cohort_ids, label="human_test"),
        "human_selection": human_selection.canonical_bytes(),
        "scale_curve": scale_curve.canonical_bytes(),
        "primary_test": primary.canonical_bytes(),
        "label_control_test": control.canonical_bytes(),
        "human_transfer": human_transfer.canonical_bytes(),
        "integrity_receipt": receipt.canonical_bytes(),
        "terminal_result": result.canonical_bytes(),
    }
    for key, raw in files.items():
        publish_exclusive_bytes(
            partial / (TEST_POPULATION_FILES | STATISTIC_FILES)[key], raw)
    manifest = _stage_manifest(
        freeze, admission, calibration, attempt, files,
        result.terminal_route)
    publish_exclusive_bytes(
        partial / "manifest.json", canonical_json_bytes(manifest))
    os.rename(partial, final)
    descriptor = os.open(root, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    reopened = reopen_v2_terminal(
        final, freeze=freeze, admission=admission,
        inventory=inventory, group_split=group_split,
        progress=progress)
    if reopened != manifest:
        raise BeliefV2TerminalControllerError(
            "V2 terminal post-publish reconstruction drift")
    if progress is not None:
        progress(5, 5, "terminal-complete")
    return reopened


def reopen_v2_terminal(
        directory: Path, *, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1,
        inventory: dict[str, Any], group_split: dict[str, Any],
        projection_executor: Executor | None = None,
        decision_pool: V2DecisionScoringPool | None = None,
        parallel_decisions: bool = False,
        legacy_tensor_cache_manifest_sha256: str | None = None,
        progress: ProgressCallback | None = None,
        calibration_directory: Path | None = None) \
        -> dict[str, Any]:
    """Reopen raw score populations and rederive every terminal byte."""
    if type(parallel_decisions) is not bool \
            or parallel_decisions and (
                projection_executor is not None or decision_pool is not None):
        raise BeliefV2TerminalControllerError(
            "V2 terminal scoring mode drift")
    if progress is not None:
        progress(0, 5, "verify-terminal-controls")
    expected_names = {
        "attempt.json", "manifest.json", *TEST_POPULATION_FILES.values(),
        *STATISTIC_FILES.values()}
    if not isinstance(directory, Path) or directory.is_symlink() \
            or not directory.is_dir() or directory.name != "terminal" \
            or {path.name for path in directory.iterdir()} != expected_names:
        raise BeliefV2TerminalControllerError(
            "V2 terminal directory population drift")
    attempt_raw = stable_read_bytes(directory / "attempt.json")
    manifest_raw = stable_read_bytes(directory / "manifest.json")
    try:
        attempt = json.loads(attempt_raw)
        manifest = json.loads(manifest_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefV2TerminalControllerError(
            "V2 terminal control artifact is not JSON") from exc
    calibration, human_selection, scale_curve = _calibration_statistics(
        Path(freeze.evidence_root), freeze, admission, inventory, group_split,
        calibration_directory=calibration_directory,
        legacy_tensor_cache_manifest_sha256=(
            legacy_tensor_cache_manifest_sha256))
    if attempt != _attempt(freeze, admission, calibration) \
            or canonical_json_bytes(attempt) != attempt_raw:
        raise BeliefV2TerminalControllerError(
            "V2 terminal attempt reconstruction drift")
    expected_file_keys = set(TEST_POPULATION_FILES) | set(STATISTIC_FILES)
    if type(manifest) is not dict or set(manifest.get("files", {})) \
            != expected_file_keys or canonical_json_bytes(manifest) \
            != manifest_raw:
        raise BeliefV2TerminalControllerError(
            "V2 terminal manifest population/canonical drift")
    if progress is not None:
        progress(1, 5, "verify-terminal-controls")
    files = {}
    for key, filename in (TEST_POPULATION_FILES | STATISTIC_FILES).items():
        raw = stable_read_bytes(directory / filename)
        row = manifest["files"].get(key)
        if type(row) is not dict or set(row) != {
                "filename", "byte_count", "sha256"} \
                or row["filename"] != filename \
                or row["byte_count"] != len(raw) \
                or row["sha256"] != _sha256(raw):
            raise BeliefV2TerminalControllerError(
                "V2 terminal file byte binding drift")
        files[key] = raw
    if progress is not None:
        progress(2, 5, "verify-terminal-files")
    try:
        input_index_manifest, training_inputs = reopen_training_input_index(
            Path(freeze.evidence_root) / "training-input-index" / "result",
            freeze=freeze, admission=admission)
        cohorts, plan, qualification, training_hashes = (
            reopen_trained_scoring_cohorts(
                Path(freeze.evidence_root), freeze=freeze,
                admission=admission, training_inputs=training_inputs,
                legacy_tensor_cache_manifest_sha256=(
                    legacy_tensor_cache_manifest_sha256)))
        cohort_ids = tuple(row.cohort_id for row in cohorts)
        if progress is not None:
            progress(3, 5, "verify-terminal-cohorts")
        recorded_synthetic = reopen_v2_round_population(
            files["synthetic_test"], cohort_ids=cohort_ids,
            label="synthetic_test")
        recorded_human = reopen_v2_round_population(
            files["human_test"], cohort_ids=cohort_ids,
            label="human_test")
        if parallel_decisions:
            with V2DecisionScoringPool(cohorts) as local_pool:
                local_pool.warm()
                synthetic, human = _score_test_populations(
                    Path(freeze.evidence_root), freeze, admission,
                    group_split, cohorts, decision_pool=local_pool,
                    progress=progress,
                    progress_phase_prefix="reconstruct-test")
        else:
            synthetic, human = _score_test_populations(
                Path(freeze.evidence_root), freeze, admission, group_split,
                cohorts, projection_executor=projection_executor,
                decision_pool=decision_pool, progress=progress,
                progress_phase_prefix="reconstruct-test")
        if v2_round_population_bytes(
                recorded_synthetic, cohort_ids=cohort_ids,
                label="synthetic_test") != v2_round_population_bytes(
                    synthetic, cohort_ids=cohort_ids,
                    label="synthetic_test") \
                or v2_round_population_bytes(
                    recorded_human, cohort_ids=cohort_ids,
                    label="human_test") != v2_round_population_bytes(
                        human, cohort_ids=cohort_ids,
                        label="human_test"):
            raise BeliefV2TerminalControllerError(
                "V2 terminal persisted score population differs from "
                "source replay")
        expected_synthetic = _expected_test_synthetic_rounds()
        expected_human = _expected_test_human_rounds(
            Path(freeze.evidence_root), freeze, admission, group_split)
        primary, control, human_transfer = (
            _run_independent_terminal_statistics(
                lambda: evaluate_primary_test(
                    synthetic,
                    selected_cohort_id=calibration["selected_cohort_id"],
                    expected_synthetic_rounds=expected_synthetic,
                    cohort_ids=cohort_ids),
                lambda: evaluate_label_control_test(
                    synthetic,
                    expected_synthetic_rounds=expected_synthetic,
                    cohort_ids=cohort_ids),
                lambda: evaluate_human_transfer_test(
                    human,
                    selected_cohort_id=calibration["selected_cohort_id"],
                    expected_human_rounds=expected_human,
                    cohort_ids=cohort_ids)))
        receipt = _derive_integrity_receipt(
            Path(freeze.evidence_root), freeze, admission, group_split,
            plan=plan, qualification=qualification,
            input_index_manifest=input_index_manifest,
            training_hashes=training_hashes,
            synthetic_test_count=len(synthetic),
            human_test_decision_count=sum(row.decision_count for row in human),
            legacy_tensor_cache_manifest_sha256=(
                legacy_tensor_cache_manifest_sha256))
        result = derive_terminal_result(
            freeze, plan, qualification, receipt, human_selection,
            scale_curve, primary, control, human_transfer)
        validate_terminal_result(
            freeze, plan, qualification, receipt, human_selection,
            scale_curve, primary, control, human_transfer, result)
    except BeliefV2TerminalControllerError:
        raise
    except ValueError as exc:
        raise BeliefV2TerminalControllerError(
            "V2 terminal raw reconstruction refused") from exc
    if progress is not None:
        progress(4, 5, "verify-terminal-derivation")
    expected_statistic_bytes = {
        "human_selection": human_selection.canonical_bytes(),
        "scale_curve": scale_curve.canonical_bytes(),
        "primary_test": primary.canonical_bytes(),
        "label_control_test": control.canonical_bytes(),
        "human_transfer": human_transfer.canonical_bytes(),
        "integrity_receipt": receipt.canonical_bytes(),
        "terminal_result": result.canonical_bytes(),
    }
    if any(files[key] != raw for key, raw in expected_statistic_bytes.items()):
        raise BeliefV2TerminalControllerError(
            "V2 terminal result reconstruction drift")
    expected = _stage_manifest(
        freeze, admission, calibration, attempt, files,
        result.terminal_route)
    if manifest != expected:
        raise BeliefV2TerminalControllerError(
            "V2 terminal manifest reconstruction drift")
    if progress is not None:
        progress(5, 5, "verify-terminal-complete")
    return manifest
