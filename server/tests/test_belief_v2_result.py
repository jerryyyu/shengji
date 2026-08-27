"""Closed routing and measured-integrity tests for the V2 terminal result."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from dataclasses import replace
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

import shengji.rl.belief_v2_controller as PIPELINE_STAGE
import shengji.rl.belief_v2_terminal_controller as TERMINAL_STAGE
import shengji.rl.belief_v2_training_controller as TRAINING_STAGE
import shengji.rl.belief_v2_r4_completion as R4_COMPLETION
import shengji.rl.belief_v2_r4_terminal_parallel as R4_PARALLEL

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.belief_v2_device_qualification import (
    V2DeviceQualificationArmV1,
    build_qualification_plan,
    derive_qualification_result,
    qualification_protocol_sha256,
    training_host_memory_upper_bound,
)
from shengji.rl.belief_v2_accelerator import V2TrainingDeviceProfileV1
from shengji.rl.belief_v2_execution_identity import (
    V2InstalledDistributionV1,
    V2RuntimeProfileV1,
    V2SourceBindingV1,
    source_manifest_sha256,
)
from shengji.rl.belief_v2_freeze import (
    ALL_HUMAN_TRAIN_DECISIONS,
    ALL_SYNTHETIC_TRAIN_DECISIONS,
    MIXED_SYNTHETIC_TRAIN_DECISIONS,
    MIXED_WORK_RULE,
    NO_HUMAN_DECISIONS,
    PRIMARY_WORK_RULE,
    SCALE_SYNTHETIC_TRAIN_DECISIONS,
    SCALE_WORK_RULE,
    V2CohortPlanV1,
    V2ExecutionFreezeV1,
    V2PipelineAdmissionV1,
    V2ResourceCapsV1,
)
from shengji.rl.belief_v2_protocol import (
    V2_RANKS,
    V2_ROUND_COUNT,
    V2_SPLIT_COUNTS,
)
from shengji.rl.belief_v2_progress import V2ProgressReporter
from shengji.rl.belief_v2_controller import reference_lane_jobs
from shengji.rl.belief_v2_result import (
    PASS_B3,
    REFUSE_CONTROL,
    REFUSE_INTEGRITY,
    SELECT_NONE,
    SELECT_REENTRY,
    BeliefV2ResultError,
    V2IntegrityResourceReceiptV1,
    derive_terminal_result,
    expected_reference_job_count,
    validate_terminal_result,
)
from shengji.rl.belief_v2_statistics import (
    V2HumanSelectionResultV1,
    V2HumanTransferCohortV1,
    V2HumanTransferResultV1,
    V2LabelControlTestResultV1,
    V2PrimaryTestResultV1,
    V2RoundScoreV1,
    V2ScaleCurveResultV1,
    V2ScaleCurveRowV1,
    v2_round_population_bytes,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _bindings():
    paths = (
        "BELIEF_V1_SPEC.md", "BELIEF_V1_V2_DESIGN.md",
        "server/pyproject.toml", "server/setup.py", "server/uv.lock",
        "server/scripts/belief_v2_worker.py", "server/shengji/__init__.py",
    )
    return tuple(sorted((V2SourceBindingV1(
        path=path, byte_count=index + 1, sha256=_sha(path))
        for index, path in enumerate(paths)), key=lambda row: row.path))


def _distribution(name: str):
    return V2InstalledDistributionV1(
        name=name, version="1", root=f"/runtime/{name}", file_count=1,
        payload_sha256=_sha(name))


def _runtime():
    return V2RuntimeProfileV1(
        hostname="host", operating_system="os", machine="machine",
        cpu_count=16, memory_bytes=32 * 1024**3,
        boot_identity=_sha("boot"), python_executable="/runtime/python",
        python_executable_sha256=_sha("python"), python_version="3.14",
        torch=_distribution("torch"), torch_config_sha256=_sha("config"),
        numpy=_distribution("numpy"), native_path="/runtime/_fast.so",
        native_sha256=_sha("native"), required_environment=(
            ("PYTHONDONTWRITEBYTECODE", "1"),
            ("PYTHONHASHSEED", "0"),
            ("SHENGJI_FAST", "1"),
            ("SHENGJI_REQUIRE_VOIDS", "1")))


def _device_profile():
    return V2TrainingDeviceProfileV1(
        requested_device="mps", device_type="mps", device_index=None,
        hardware_name="Apple-arm64-test", total_memory_bytes=12 * 1024**3,
        runtime_version="macOS-test", compute_capability_major=None,
        compute_capability_minor=None)


def _cohorts():
    return (
        V2CohortPlanV1(
            cohort_id="synthetic-primary", kind="synthetic-primary",
            synthetic_selection_rule=ALL_SYNTHETIC_TRAIN_DECISIONS,
            synthetic_fraction_numerator=1,
            synthetic_fraction_denominator=1,
            human_selection_rule=NO_HUMAN_DECISIONS,
            work_match_rule=PRIMARY_WORK_RULE,
            comparator_cohort_id=None),
        V2CohortPlanV1(
            cohort_id="hard-geometry-label-permutation",
            kind="hard-geometry-label-permutation",
            synthetic_selection_rule=ALL_SYNTHETIC_TRAIN_DECISIONS,
            synthetic_fraction_numerator=1,
            synthetic_fraction_denominator=1,
            human_selection_rule=NO_HUMAN_DECISIONS,
            work_match_rule=PRIMARY_WORK_RULE,
            comparator_cohort_id="synthetic-primary"),
        V2CohortPlanV1(
            cohort_id="human-mixture", kind="human-mixture",
            synthetic_selection_rule=MIXED_SYNTHETIC_TRAIN_DECISIONS,
            synthetic_fraction_numerator=1,
            synthetic_fraction_denominator=1,
            human_selection_rule=ALL_HUMAN_TRAIN_DECISIONS,
            work_match_rule=MIXED_WORK_RULE,
            comparator_cohort_id="synthetic-primary"),
        V2CohortPlanV1(
            cohort_id="synthetic-scale-50", kind="synthetic-scale",
            synthetic_selection_rule=SCALE_SYNTHETIC_TRAIN_DECISIONS,
            synthetic_fraction_numerator=1,
            synthetic_fraction_denominator=2,
            human_selection_rule=NO_HUMAN_DECISIONS,
            work_match_rule=SCALE_WORK_RULE,
            comparator_cohort_id="synthetic-primary"),
    )


def _freeze():
    bindings = _bindings()
    return V2ExecutionFreezeV1(
        execution_git="a" * 40,
        source_manifest_sha256=source_manifest_sha256("a" * 40, bindings),
        source_bindings=bindings, runtime=_runtime(),
        source_review_commit="b" * 40,
        v1_terminal_route="v1-pass-to-b3",
        v1_terminal_result_sha256=_sha("v1-result"),
        v1_resource_receipt_sha256=_sha("v1-resource"),
        v1_resource_failure_receipt_sha256=None,
        v2_reentry_rationale_sha256=None,
        h0_inventory_sha256=_sha("inventory"),
        h0_source_manifest_sha256=_sha("source"),
        h0_source_digest_population_sha256=_sha("population"),
        human_group_split_sha256=_sha("split"),
        human_group_count=30, human_train_group_count=24,
        human_calibration_group_count=3, human_test_group_count=3,
        human_complete_round_count=122,
        human_eligible_decision_count=2_830,
        human_train_eligible_decision_count=2_240,
        human_calibration_eligible_decision_count=416,
        human_test_eligible_decision_count=174,
        preflight_result_sha256=_sha("preflight"),
        preflight_runtime_sha256=_sha("preflight-runtime"),
        deadline_estimate_receipt_sha256=_sha("deadline"),
        seed_registry_sha256=_sha("registry"),
        seed_candidate_report_sha256=_sha("candidate-report"),
        training_candidate_device="mps",
        training_device_profile=_device_profile(),
        device_qualification_protocol_sha256=(
            qualification_protocol_sha256("mps")),
        cohorts=_cohorts(),
        resource_caps=V2ResourceCapsV1(
            capture_core_hours=64, capture_wall_seconds=14_400,
            capture_bytes=16 * 1024**3,
            reference_core_hours=16, reference_wall_seconds=7_200,
            reference_bytes=16 * 1024**3,
            training_device_hours=128, training_wall_seconds=86_400,
            training_bytes=32 * 1024**3,
            training_host_memory_bytes=24 * 1024**3,
            training_device_memory_bytes=12 * 1024**3,
            capture_next_unit_wall_estimate_nanoseconds=20_000_000_000,
            reference_next_unit_wall_estimate_nanoseconds=5_000_000_000,
            training_next_epoch_wall_estimate_nanoseconds=60_000_000_000,
            deadline_safety_reserve_nanoseconds=1_000_000_000),
        evidence_root="/tmp/belief-v2-result-test")


def _qualification(freeze):
    schedule = tuple((_sha(f"batch-{index}"),) for index in range(40))
    plan = build_qualification_plan(
        execution_git=freeze.execution_git, candidate_device="mps",
        batch_decision_keys=schedule,
        batch_active_label_counts=tuple(10 for _ in schedule),
        host_memory_cap_bytes=(
            freeze.resource_caps.training_host_memory_bytes),
        device_memory_cap_bytes=(
            freeze.resource_caps.training_device_memory_bytes))
    arms = []
    for index, (device, warmup, pair) in enumerate(plan.arm_order):
        arms.append(V2DeviceQualificationArmV1(
            arm_index=index, device=device, warmup=warmup, pair_index=pair,
            plan_sha256=plan.sha256(),
            batch_population_sha256=plan.selected_population_sha256,
            batch_schedule_sha256=plan.selected_schedule_sha256,
            decision_count=plan.decision_count,
            active_label_count=plan.active_label_count,
            member_checkpoint_sha256s=tuple(
                _sha(f"{device}-checkpoint-{member}")
                for member in range(8)),
            member_loss_nanonats=tuple(
                100 + member + (10 if device == "mps" else 0)
                for member in range(8)),
            member_epoch_receipt_sha256s=tuple(
                _sha(f"{device}-receipt-{member}") for member in range(8)),
            wall_nanoseconds=50 if warmup else (
                80 if device == "mps" else 100),
            peak_host_memory_bytes=1024,
            peak_device_memory_bytes=2048 if device == "mps" else 0,
            actual_device=device))
    return plan, derive_qualification_result(plan, tuple(arms))


def _receipt(freeze, plan, qualification):
    return V2IntegrityResourceReceiptV1(
        freeze_sha256=freeze.sha256(),
        device_qualification_plan_sha256=plan.sha256(),
        device_qualification_result_sha256=_sha_bytes(
            qualification.canonical_bytes(plan)),
        training_device=qualification.selected_device,
        capture_expected_round_count=V2_ROUND_COUNT,
        capture_reopened_round_count=V2_ROUND_COUNT,
        reference_expected_round_count=expected_reference_job_count(),
        reference_reopened_round_count=expected_reference_job_count(),
        training_expected_cohort_count=len(freeze.cohorts),
        training_reopened_cohort_count=len(freeze.cohorts),
        training_expected_checkpoint_count=len(freeze.cohorts) * 8,
        training_reopened_checkpoint_count=len(freeze.cohorts) * 8,
        synthetic_test_expected_round_count=1_339,
        synthetic_test_reopened_round_count=1_339,
        human_test_expected_decision_count=174,
        human_test_reopened_decision_count=174,
        capture_cpu_nanoseconds=1_000,
        capture_wall_nanoseconds=1_000,
        capture_artifact_bytes=1_000,
        reference_cpu_nanoseconds=1_000,
        reference_wall_nanoseconds=1_000,
        reference_artifact_bytes=1_000,
        training_device_nanoseconds=1_000,
        training_wall_nanoseconds=1_000,
        training_artifact_bytes=1_000,
        training_peak_host_memory_bytes=1_000,
        training_peak_device_memory_bytes=1_000,
        capture_failure_count=0, reference_failure_count=0,
        training_failure_count=0, mechanics_failure_count=0,
        resource_cap_violation_count=0, retry_count=0, drop_count=0,
        test_split_decision_open_count=1)


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _statistics(*, selected="synthetic-primary", primary_passed=True,
                control_passed=True, scale_positive=False,
                rank_signal=False):
    retained = selected == "human-mixture"
    rank_counts = tuple((rank, 103) for rank in V2_RANKS)
    rank_values = tuple((rank, -1 if rank_signal else 0)
                        for rank in V2_RANKS)
    human_selection = V2HumanSelectionResultV1(
        synthetic_round_count=1_326, human_round_count=10,
        human_mean_brier_improvement_ppb=1,
        human_bootstrap_lower_improvement_ppb=1 if retained else 0,
        synthetic_mean_regression_ppb=0,
        synthetic_bootstrap_upper_regression_ppb=0,
        rank_round_counts=tuple((rank, 102) for rank in V2_RANKS),
        rank_mean_regression_ppb=tuple((rank, 0) for rank in V2_RANKS),
        rank_familywise_upper_regression_ppb=tuple(
            (rank, 0) for rank in V2_RANKS),
        retained=retained,
        refusal_reasons=() if retained else (
            "human-domain-lower-bound-not-positive",))
    scale = V2ScaleCurveResultV1(
        synthetic_round_count=1_326,
        rows=(V2ScaleCurveRowV1(
            cohort_id="synthetic-scale-50",
            decision_fraction_numerator=1,
            decision_fraction_denominator=2,
            primary_mean_improvement_ppb=1 if scale_positive else 0,
            bootstrap_lower_improvement_ppb=1 if scale_positive else 0,
            positive_lower_bound=scale_positive),),
        any_positive_data_scaling_signal=scale_positive)
    primary = V2PrimaryTestResultV1(
        selected_cohort_id=selected, round_count=1_339,
        reference_mean_brier_ppb=100, candidate_mean_brier_ppb=90,
        mean_brier_improvement_ppb=10,
        relative_brier_improvement_ppb=100_000_000,
        bootstrap_lower_improvement_ppb=1,
        member_mean_improvement_ppb=(1,) * 8,
        positive_member_count=8,
        mean_log_loss_improvement_nanonats=1,
        rank_round_counts=rank_counts,
        rank_mean_regression_ppb=rank_values,
        rank_familywise_upper_regression_ppb=rank_values,
        passed=primary_passed,
        refusal_reasons=() if primary_passed else (
            "mean-relative-brier-floor-not-met",))
    control = V2LabelControlTestResultV1(
        round_count=1_339, mean_brier_improvement_ppb=0,
        bootstrap_lower_improvement_ppb=(1 if not control_passed else 0),
        unexpectedly_positive_lower_bound=not control_passed,
        passed=control_passed)
    cohort_rows = tuple(V2HumanTransferCohortV1(
        cohort_id=cohort_id, reference_mean_brier_ppb=100,
        candidate_mean_brier_ppb=90,
        mean_brier_improvement_ppb=10,
        bootstrap_lower_improvement_ppb=1,
        bootstrap_upper_improvement_ppb=20,
        mean_log_loss_improvement_nanonats=1)
                        for cohort_id in (
                            "synthetic-primary", "human-mixture"))
    human = V2HumanTransferResultV1(
        round_count=3, decision_count=174, selected_cohort_id=selected,
        cohorts=cohort_rows,
        mixed_minus_primary_mean_improvement_ppb=0,
        mixed_minus_primary_bootstrap_lower_ppb=0,
        mixed_minus_primary_bootstrap_upper_ppb=0)
    return human_selection, scale, primary, control, human


def _inputs(**statistics):
    freeze = _freeze()
    plan, qualification = _qualification(freeze)
    receipt = _receipt(freeze, plan, qualification)
    return (freeze, plan, qualification, receipt,
            *_statistics(**statistics))


def test_clean_primary_pass_routes_only_to_sampler_implementation_review():
    inputs = _inputs(primary_passed=True, scale_positive=True,
                     rank_signal=True)
    result = derive_terminal_result(*inputs)
    assert result.terminal_route == PASS_B3
    assert result.reentry_signals == ()
    assert result.integrity_failure_reasons == ()
    payload = result.to_dict()
    assert set(value for key, value in payload.items()
               if key.endswith("_authorized")) == {False}
    assert canonical_json_bytes(payload) == result.canonical_bytes()
    assert expected_reference_job_count() == 3_991
    assert expected_reference_job_count() == sum(
        len(reference_lane_jobs(lane)) for lane in range(16))


def test_null_reentry_and_negative_control_routes_have_fixed_precedence():
    result = derive_terminal_result(*_inputs(primary_passed=False))
    assert result.terminal_route == SELECT_NONE
    assert result.reentry_signals == ()

    result = derive_terminal_result(*_inputs(
        primary_passed=False, scale_positive=True, rank_signal=True))
    assert result.terminal_route == SELECT_REENTRY
    assert result.reentry_signals == ("data-scale", "rank-stratified")

    result = derive_terminal_result(*_inputs(
        primary_passed=True, control_passed=False,
        scale_positive=True, rank_signal=True))
    assert result.terminal_route == REFUSE_CONTROL
    assert result.reentry_signals == ()


@pytest.mark.parametrize(("field", "value", "reason"), [
    ("capture_reopened_round_count", V2_ROUND_COUNT - 1,
     "reopened-population-incomplete"),
    ("capture_failure_count", 1,
     "measured-stage-or-mechanics-failure"),
    ("retry_count", 1, "retry-or-drop-observed"),
    ("test_split_decision_open_count", 2,
     "test-split-decision-open-count-drift"),
    ("training_peak_device_memory_bytes", 13 * 1024**3,
     "recomputed-resource-cap-exceeded"),
])
def test_measured_integrity_wiring_routes_failures(field, value, reason):
    inputs = list(_inputs(primary_passed=True))
    inputs[3] = replace(inputs[3], **{field: value})
    result = derive_terminal_result(*inputs)
    assert result.terminal_route == REFUSE_INTEGRITY
    assert reason in result.integrity_failure_reasons


def test_selection_and_terminal_rewrite_are_independently_refused():
    inputs = _inputs(selected="human-mixture")
    broken = list(inputs)
    broken[-1] = replace(broken[-1], selected_cohort_id="synthetic-primary")
    with pytest.raises(BeliefV2ResultError, match="coherence"):
        derive_terminal_result(*broken)

    result = derive_terminal_result(*inputs)
    with pytest.raises(BeliefV2ResultError, match="derivation"):
        validate_terminal_result(*inputs, replace(result, terminal_route=SELECT_NONE))


def test_qualification_and_receipt_cross_binding_cannot_be_rehashed_away():
    inputs = list(_inputs())
    inputs[3] = replace(
        inputs[3], device_qualification_result_sha256=_sha("forged"))
    with pytest.raises(BeliefV2ResultError, match="receipt drift"):
        derive_terminal_result(*inputs)


def _admission(freeze):
    return V2PipelineAdmissionV1(
        freeze_sha256=freeze.sha256(), execution_git=freeze.execution_git,
        source_manifest_sha256=freeze.source_manifest_sha256,
        seed_registry_sha256=freeze.seed_registry_sha256,
        review_commit="c" * 40, canonical_remote_tip="d" * 40,
        review_marker_sha256=_sha("review-marker"),
        evidence_root=freeze.evidence_root)


def _completion_admission(freeze):
    return R4_COMPLETION.R4CompletionAdmissionV1(
        freeze_sha256=freeze.sha256(), execution_git=freeze.execution_git,
        source_manifest_sha256=freeze.source_manifest_sha256,
        seed_registry_sha256=freeze.seed_registry_sha256,
        source_spec_sha256=_sha("completion-spec"),
        review_commit="c" * 40, canonical_remote_tip="d" * 40,
        review_marker_sha256=_sha("completion-review-marker"),
        evidence_root=freeze.evidence_root)


def _completion_source_spec(destination: Path, source: Path):
    return R4_COMPLETION.R4CompletionSourceSpecV1(
        destination_evidence_root=destination,
        source_evidence_root=source,
        source_execution_git="a" * 40,
        source_freeze_sha256=_sha("source-freeze"),
        source_admission_sha256=_sha("source-admission"),
        source_review_marker_sha256=_sha("source-review"),
        source_consumption_tombstone_sha256=_sha("source-consumption"),
        source_inventory_sha256=_sha("source-inventory"),
        source_group_split_sha256=_sha("source-split"),
        source_input_index_manifest_sha256=_sha("source-index"),
        source_tensor_cache_manifest_sha256=_sha("source-cache"),
        source_device_qualification_manifest_sha256=_sha("source-device"),
        source_training_manifest_sha256s=tuple(
            (cohort_id, _sha(cohort_id))
            for cohort_id in R4_COMPLETION.SOURCE_COHORT_IDS))


def _calibration_import(root: Path, source_spec):
    return R4_PARALLEL.R4TerminalCalibrationImportV1(
        calibration_evidence_root=root,
        calibration_execution_git="b" * 40,
        calibration_freeze_sha256=_sha("calibration-freeze"),
        calibration_admission_sha256=_sha("calibration-admission"),
        calibration_review_marker_sha256=_sha("calibration-review"),
        calibration_consumption_tombstone_sha256=_sha(
            "calibration-consumption"),
        calibration_source_spec_sha256=source_spec.sha256(),
        calibration_reconstructed_outer_sha256=_sha("calibration-outer"),
        calibration_selection_manifest_sha256=_sha(
            "calibration-selection"))


def _terminal_capacity_context(tmp_path: Path):
    destination = (tmp_path / "terminal").resolve()
    source_freeze = _freeze()
    cohorts = tuple(SimpleNamespace(
        cohort_id=row.cohort_id,
        model_sha256s=tuple(
            _sha(f"{row.cohort_id}-model-{index}") for index in range(8)))
        for row in source_freeze.cohorts)
    terminal_spec = SimpleNamespace(
        destination_evidence_root=destination,
        sha256=lambda: _sha("terminal-source-spec"))
    calibration_import = SimpleNamespace(
        sha256=lambda: _sha("calibration-import"))
    return R4_PARALLEL._CapacityContext(
        terminal_spec=terminal_spec,
        calibration_import=calibration_import,
        calibration={"schema": "sealed-calibration"},
        source=SimpleNamespace(freeze=source_freeze),
        source_bindings=_bindings(), runtime=_runtime(), cohorts=cohorts,
        coordinates=R4_PARALLEL._parity_coordinates(),
        decision_counts=tuple(4 for _ in V2_RANKS))


def _terminal_capacity_receipt(context):
    expected_git = "a" * 40
    serial_wall = 2_000_000_000
    parallel_wall = 1_000_000_000
    control_reopen_wall = 3_000_000_000
    decision_count = sum(context.decision_counts)
    test_rounds = dict(V2_SPLIT_COUNTS)["test"]
    human_test = context.source.freeze.human_test_eligible_decision_count
    maximum_test_decisions = (
        test_rounds * R4_PARALLEL.MAXIMUM_SYNTHETIC_DECISIONS_PER_ROUND
        + human_test)
    one_pass = (
        parallel_wall * maximum_test_decisions + decision_count - 1
    ) // decision_count
    caps = context.source.freeze.resource_caps
    return {
        "schema": R4_PARALLEL.CAPACITY_SCHEMA,
        "execution_git": expected_git,
        "source_manifest_sha256": source_manifest_sha256(
            expected_git, context.source_bindings),
        "runtime_sha256": _sha_bytes(canonical_json_bytes(
            context.runtime.to_dict())),
        "terminal_source_spec_sha256": context.terminal_spec.sha256(),
        "calibration_import_sha256": context.calibration_import.sha256(),
        "calibration_manifest_sha256": _sha_bytes(canonical_json_bytes(
            context.calibration)),
        "hostname": context.runtime.hostname,
        "machine": context.runtime.machine,
        "rank_count": len(V2_RANKS),
        "trump_ranks": [row.trump_rank for row in context.coordinates],
        "round_keys": [R4_PARALLEL.synthetic_round_key(row.round_seed)
                       for row in context.coordinates],
        "decision_count": decision_count,
        "population_sha256": _sha("capacity-population"),
        "exact_serial_parallel_parity": True,
        "measurement_order": R4_PARALLEL.CAPACITY_MEASUREMENT_ORDER,
        "serial_wall_nanoseconds": serial_wall,
        "parallel_wall_nanoseconds": parallel_wall,
        "serial_cpu_nanoseconds": 1_900_000_000,
        "parallel_cpu_nanoseconds": 15_000_000_000,
        "speedup_ppb": serial_wall * 1_000_000_000 // parallel_wall,
        "aggregate_peak_host_memory_upper_bound_bytes": 8 * 1024**3,
        "host_memory_cap_bytes": caps.training_host_memory_bytes,
        "host_memory_within_cap": True,
        "worker_count": R4_PARALLEL.V2_DECISION_WORKERS,
        "worker_cohort_identity": [[
            row.cohort_id, list(row.model_sha256s)]
            for row in context.cohorts],
        "synthetic_test_round_count": test_rounds,
        "human_test_decision_count": human_test,
        "maximum_synthetic_decisions_per_round": (
            R4_PARALLEL.MAXIMUM_SYNTHETIC_DECISIONS_PER_ROUND),
        "projected_maximum_test_decision_count": maximum_test_decisions,
        "scientific_unit_scoring_pass_count": (
            R4_PARALLEL.SCIENTIFIC_UNIT_SCORING_PASSES),
        "independent_verifier_scoring_pass_count": (
            R4_PARALLEL.INDEPENDENT_VERIFIER_SCORING_PASSES),
        "control_reopen_wall_nanoseconds": control_reopen_wall,
        "scientific_unit_control_reopen_count": (
            R4_PARALLEL.SCIENTIFIC_UNIT_CONTROL_REOPENS),
        "independent_verifier_control_reopen_count": (
            R4_PARALLEL.INDEPENDENT_VERIFIER_CONTROL_REOPENS),
        "projected_scientific_control_wall_nanoseconds": (
            control_reopen_wall
            * R4_PARALLEL.SCIENTIFIC_UNIT_CONTROL_REOPENS),
        "projected_independent_verifier_control_wall_nanoseconds": (
            control_reopen_wall
            * R4_PARALLEL.INDEPENDENT_VERIFIER_CONTROL_REOPENS),
        "projected_one_pass_wall_nanoseconds": one_pass,
        "projected_scientific_unit_wall_nanoseconds": (
            one_pass * R4_PARALLEL.SCIENTIFIC_UNIT_SCORING_PASSES
            + control_reopen_wall
            * R4_PARALLEL.SCIENTIFIC_UNIT_CONTROL_REOPENS),
        "projected_independent_verifier_wall_nanoseconds": (
            one_pass * R4_PARALLEL.INDEPENDENT_VERIFIER_SCORING_PASSES
            + control_reopen_wall
            * R4_PARALLEL.INDEPENDENT_VERIFIER_CONTROL_REOPENS),
        "terminal_wall_cap_nanoseconds": (
            caps.training_wall_seconds * 1_000_000_000),
        "deadline_safety_reserve_nanoseconds": (
            caps.deadline_safety_reserve_nanoseconds),
        "projected_within_wall_cap": True,
        "test_split_decision_open_count": 0,
        "test_opening_executed": False,
        "execution_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }


def _terminal_score(source: str, cohort_ids: tuple[str, ...]):
    return V2RoundScoreV1(
        round_key=_sha(f"{source}-test-round"), source_kind=source,
        split="test", trump_rank="2", decision_count=8,
        reference_brier_ppb=100, reference_log_loss_nanonats=100,
        cohort_brier_ppb=tuple((value, 90 + index)
                               for index, value in enumerate(cohort_ids)),
        cohort_log_loss_nanonats=tuple((value, 90 + index)
                                      for index, value in enumerate(cohort_ids)),
        cohort_member_brier_ppb=tuple(
            (value, (90 + index,) * 8)
            for index, value in enumerate(cohort_ids)))


def _stub_terminal_dependencies(monkeypatch, freeze):
    plan, qualification = _qualification(freeze)
    receipt = _receipt(freeze, plan, qualification)
    human_selection, scale, primary, control, human = _statistics()
    cohort_ids = tuple(row.cohort_id for row in freeze.cohorts)
    cohorts = tuple(SimpleNamespace(cohort_id=value) for value in cohort_ids)
    synthetic_rows = (_terminal_score("synthetic", cohort_ids),)
    human_rows = (_terminal_score("human", cohort_ids),)
    calibration = {
        "schema": "test-calibration", "cohort_ids": list(cohort_ids),
        "calibration_passed": True,
        "selected_cohort_id": "synthetic-primary"}
    monkeypatch.setattr(TERMINAL_STAGE, "_stage_gate", lambda **kwargs: None)
    monkeypatch.setattr(
        TERMINAL_STAGE, "_calibration_statistics",
        lambda *args, **kwargs: (calibration, human_selection, scale))
    monkeypatch.setattr(
        TERMINAL_STAGE, "reopen_training_input_index",
        lambda *args, **kwargs: ({}, SimpleNamespace()))
    monkeypatch.setattr(
        TERMINAL_STAGE, "reopen_trained_scoring_cohorts",
        lambda *args, **kwargs: (
            cohorts, plan, qualification,
            tuple((value, _sha(value)) for value in cohort_ids)))
    def score_test_populations(*args, progress=None,
                               progress_phase_prefix="score-test", **kwargs):
        if progress is not None:
            progress(0, 1, f"{progress_phase_prefix}-synthetic-rounds")
            progress(1, 1, f"{progress_phase_prefix}-synthetic-rounds")
            progress(0, 1, f"{progress_phase_prefix}-human-groups")
            progress(1, 1, f"{progress_phase_prefix}-human-groups")
        return synthetic_rows, human_rows

    monkeypatch.setattr(
        TERMINAL_STAGE, "_score_test_populations",
        score_test_populations)
    monkeypatch.setattr(
        TERMINAL_STAGE, "_expected_test_synthetic_rounds",
        lambda: ((synthetic_rows[0].round_key, "2"),))
    monkeypatch.setattr(
        TERMINAL_STAGE, "_expected_test_human_rounds",
        lambda *args, **kwargs: ((human_rows[0].round_key, "2"),))
    monkeypatch.setattr(
        TERMINAL_STAGE, "evaluate_primary_test",
        lambda *args, **kwargs: primary)
    monkeypatch.setattr(
        TERMINAL_STAGE, "evaluate_label_control_test",
        lambda *args, **kwargs: control)
    monkeypatch.setattr(
        TERMINAL_STAGE, "evaluate_human_transfer_test",
        lambda *args, **kwargs: human)
    monkeypatch.setattr(
        TERMINAL_STAGE, "_derive_integrity_receipt",
        lambda *args, **kwargs: receipt)
    return calibration


def test_r4_completion_source_spec_is_canonical_and_authorizes_no_retry():
    raw = R4_COMPLETION.SOURCE_SPEC_PATH.read_bytes()
    spec = R4_COMPLETION.load_r4_completion_source_spec(raw)
    assert spec.canonical_bytes() == raw
    assert spec.source_evidence_root == Path(
        "/opt/belief-r4-evidence-d2d466f-r1")
    assert spec.destination_evidence_root == Path(
        "/opt/belief-r4-parallel-completion-v1-r1")
    assert R4_COMPLETION.COMPLETION_AUTHORITY == {
        "calibration_open_authorized": True,
        "one_test_split_open_authorized": True,
        "training_authorized": False,
        "retry_authorized": False,
        "sampler_implementation_authorized": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "promotion_authorized": False,
        "deployment_authorized": False,
        "merge_authorized": False,
    }
    forged = json.loads(raw)
    forged["authority"]["retry_authorized"] = True
    with pytest.raises(
            R4_COMPLETION.BeliefV2R4CompletionError,
            match="field/authority drift"):
        R4_COMPLETION.load_r4_completion_source_spec(
            canonical_json_bytes(forged))


def test_r4_terminal_calibration_import_is_canonical_and_narrow(tmp_path):
    source_spec = _completion_source_spec(
        (tmp_path / "old-completion").resolve(),
        (tmp_path / "source").resolve())
    value = _calibration_import(
        source_spec.destination_evidence_root, source_spec)
    raw = value.canonical_bytes()
    assert R4_PARALLEL.load_calibration_import(raw) == value
    assert value.to_dict()["authority"] == {
        "calibration_generation_authorized": False,
        "calibration_import_authorized": True,
        "one_test_split_open_authorized": False,
        "terminal_reconstruction_authorized": True,
        "retry_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }
    forged = json.loads(raw)
    forged["authority"]["one_test_split_open_authorized"] = True
    with pytest.raises(
            R4_PARALLEL.BeliefV2R4TerminalParallelError,
            match="field drift"):
        R4_PARALLEL.load_calibration_import(
            canonical_json_bytes(forged))


def test_r4_terminal_builds_import_only_from_reopened_sealed_selection(
        tmp_path, monkeypatch):
    old_root = (tmp_path / "old-completion").resolve()
    source_root = (tmp_path / "source").resolve()
    destination = (tmp_path / "terminal").resolve()
    old_root.mkdir()
    source_root.mkdir()
    destination.mkdir()
    old_spec = _completion_source_spec(old_root, source_root)
    terminal_spec = _completion_source_spec(destination, source_root)
    spec_path = tmp_path / "old-spec.json"
    spec_path.write_bytes(old_spec.canonical_bytes())
    spec_path.chmod(0o400)
    monkeypatch.setattr(
        R4_PARALLEL, "ORIGINAL_COMPLETION_SOURCE_SPEC_PATH", spec_path)
    for name in R4_PARALLEL.CALIBRATION_ROOT_POPULATION:
        path = old_root / name
        if name == "calibration":
            (path / "selection").mkdir(parents=True)
            (path / "selection" / "manifest.json").write_bytes(
                b"sealed-selection\n")
            (path / "selection" / "manifest.json").chmod(0o400)
        else:
            path.write_bytes(f"{name}\n".encode("ascii"))
            path.chmod(0o400)
    tombstone = old_root.with_name(old_root.name + ".consumed.json")
    tombstone.write_bytes(b"consumed\n")
    tombstone.chmod(0o400)
    old_freeze = SimpleNamespace(execution_git="e" * 40)
    old_admission = object()
    source = SimpleNamespace(
        spec=old_spec, freeze=object(), admission=object(),
        review_marker=b"source-review", inventory={}, group_split={})
    calibration = {"schema": "sealed-calibration"}
    monkeypatch.setattr(
        R4_PARALLEL, "execution_freeze_from_bytes",
        lambda raw: old_freeze)
    monkeypatch.setattr(
        R4_PARALLEL, "r4_completion_admission_from_bytes",
        lambda *args, **kwargs: old_admission)
    monkeypatch.setattr(
        R4_PARALLEL, "validate_r4_completion_consumption_tombstone",
        lambda *args, **kwargs: None)
    monkeypatch.setattr(
        R4_PARALLEL, "reauthenticate_r4_completion_admission",
        lambda *args, **kwargs: None)
    monkeypatch.setattr(
        R4_PARALLEL, "reopen_r4_completion_source",
        lambda *args, **kwargs: source)
    legacy_calls = []

    def reopen_selection(directory, **kwargs):
        assert directory == old_root / "calibration" / "selection"
        legacy_calls.append(kwargs["legacy_tensor_cache_manifest_sha256"])
        return calibration

    monkeypatch.setattr(
        R4_PARALLEL, "reopen_v2_calibration_selection", reopen_selection)
    monkeypatch.setattr(
        R4_PARALLEL, "_calibration_outer_manifest",
        lambda **kwargs: {"schema": "reconstructed-outer"})
    monkeypatch.setattr(
        R4_PARALLEL, "load_terminal_source_spec", lambda: terminal_spec)

    imported = R4_PARALLEL.build_r4_terminal_calibration_import(
        repo=tmp_path.resolve())
    assert imported.calibration_evidence_root == old_root
    assert imported.calibration_execution_git == "e" * 40
    assert imported.calibration_source_spec_sha256 == old_spec.sha256()
    assert imported.calibration_reconstructed_outer_sha256 == _sha_bytes(
        canonical_json_bytes({"schema": "reconstructed-outer"}))
    assert legacy_calls == [old_spec.source_tensor_cache_manifest_sha256]
    assert R4_PARALLEL.load_calibration_import(
        imported.canonical_bytes()) == imported

    reopened, rebound, selection = R4_PARALLEL.reopen_imported_calibration(
        terminal_spec, imported, repo=tmp_path.resolve())
    assert reopened is calibration
    assert rebound.spec is terminal_spec
    assert selection == old_root / "calibration" / "selection"
    assert legacy_calls == [
        old_spec.source_tensor_cache_manifest_sha256,
        old_spec.source_tensor_cache_manifest_sha256,
    ]


def test_r4_terminal_source_spec_is_exact_fresh_destination_successor():
    terminal = R4_PARALLEL.load_terminal_source_spec()
    original = R4_COMPLETION.load_r4_completion_source_spec()

    assert terminal.destination_evidence_root == Path(
        "/opt/belief-r4-terminal-parallel-v1-r1")
    assert terminal.destination_evidence_root \
        != original.destination_evidence_root
    assert replace(
        terminal,
        destination_evidence_root=original.destination_evidence_root,
    ) == original


def test_r4_terminal_import_refuses_consumed_prior_test_namespace(
        tmp_path, monkeypatch):
    old_root = (tmp_path / "old-completion").resolve()
    source_root = (tmp_path / "source").resolve()
    destination = (tmp_path / "terminal").resolve()
    old_root.mkdir()
    source_root.mkdir()
    for name in R4_PARALLEL.CALIBRATION_ROOT_POPULATION:
        path = old_root / name
        if "." in name:
            path.write_bytes(b"placeholder\n")
        else:
            path.mkdir()
    (old_root / "terminal").mkdir()
    old_spec = _completion_source_spec(old_root, source_root)
    spec_path = tmp_path / "old-spec.json"
    spec_path.write_bytes(old_spec.canonical_bytes())
    spec_path.chmod(0o400)
    monkeypatch.setattr(
        R4_PARALLEL, "ORIGINAL_COMPLETION_SOURCE_SPEC_PATH", spec_path)
    terminal_spec = _completion_source_spec(destination, source_root)
    imported = _calibration_import(old_root, old_spec)
    with pytest.raises(
            R4_PARALLEL.BeliefV2R4TerminalParallelError,
            match="namespace drift"):
        R4_PARALLEL.reopen_imported_calibration(
            terminal_spec, imported, repo=tmp_path.resolve())


def test_r4_terminal_readiness_warms_workers_without_test_open(
        tmp_path, monkeypatch):
    root = (tmp_path / "terminal").resolve()
    source_root = (tmp_path / "source").resolve()
    calibration_root = (tmp_path / "calibration").resolve()
    root.mkdir()
    source_root.mkdir()
    calibration_root.mkdir()
    terminal_spec = _completion_source_spec(root, source_root)
    imported = _calibration_import(calibration_root, terminal_spec)
    freeze = replace(_freeze(), evidence_root=str(root))
    admission = _completion_admission(freeze)
    calibration = {"schema": "sealed-calibration"}
    cohorts = (SimpleNamespace(cohort_id="cohort"),)
    source = SimpleNamespace(
        spec=terminal_spec, freeze=freeze, admission=_admission(freeze),
        inventory={}, group_split={})
    monkeypatch.setattr(
        R4_PARALLEL, "_stage", lambda *args, **kwargs: (
            terminal_spec, imported))
    monkeypatch.setattr(
        R4_PARALLEL, "reopen_imported_calibration",
        lambda *args, **kwargs: (
            calibration, source, calibration_root / "selection"))
    monkeypatch.setattr(
        R4_PARALLEL, "reopen_training_input_index",
        lambda *args, **kwargs: ({}, SimpleNamespace()))
    monkeypatch.setattr(
        R4_PARALLEL, "reopen_trained_scoring_cohorts",
        lambda *args, **kwargs: (cohorts, None, None, ()))
    warmed = []

    class Pool:
        cohort_identity = (("cohort", (_sha("model"),)),)

        def __init__(self, population):
            assert population == cohorts

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def warm(self):
            warmed.append(True)

    monkeypatch.setattr(R4_PARALLEL, "V2DecisionScoringPool", Pool)
    readiness = R4_PARALLEL.r4_terminal_parallel_readiness(
        root, freeze, admission, repo=tmp_path.resolve(),
        review_marker=b"review")
    assert readiness["worker_startup_passed"] is True
    assert readiness["test_attempt_absent"] is True
    assert readiness["test_opening_executed"] is False
    assert warmed == [True]
    assert set(root.iterdir()) == set()

    (root / "r4-completion-test-attempt.json").write_bytes(b"spent\n")
    with pytest.raises(
            R4_PARALLEL.BeliefV2R4TerminalParallelError,
            match="namespace is occupied"):
        R4_PARALLEL.r4_terminal_parallel_readiness(
            root, freeze, admission, repo=tmp_path.resolve(),
            review_marker=b"review")
    assert warmed == [True]


def test_r4_terminal_parity_coordinates_cover_every_rank_without_test():
    coordinates = R4_PARALLEL._parity_coordinates()
    assert tuple(row.trump_rank for row in coordinates) == V2_RANKS
    assert all(row.split == "calibration" for row in coordinates)
    assert len({row.round_seed for row in coordinates}) == len(V2_RANKS)


def test_r4_terminal_capacity_runs_candidate_cold_before_warm_control(
        tmp_path, monkeypatch):
    context = _terminal_capacity_context(tmp_path)
    context.source.spec = SimpleNamespace(
        source_evidence_root=(tmp_path / "source").resolve())
    context.source.admission = object()
    context.calibration_import.calibration_evidence_root = (
        tmp_path / "calibration").resolve()
    context.calibration_import.calibration_evidence_root.mkdir()
    monkeypatch.setattr(
        R4_PARALLEL, "_capacity_context", lambda **kwargs: context)

    events = []
    identity = tuple((row.cohort_id, row.model_sha256s)
                     for row in context.cohorts)

    class DecisionPool:
        cohort_identity = identity

        def __init__(self, cohorts):
            assert cohorts == context.cohorts

        def __enter__(self):
            events.append("parallel-enter")
            return self

        def __exit__(self, *args):
            events.append("parallel-exit")
            return False

        def warm(self):
            events.append("parallel-warm")

    class ProjectionPool:
        def __enter__(self):
            events.append("serial-enter")
            return self

        def __exit__(self, *args):
            events.append("serial-exit")
            return False

    monkeypatch.setattr(
        R4_PARALLEL, "V2DecisionScoringPool", DecisionPool)
    monkeypatch.setattr(
        R4_PARALLEL, "_projection_pool", ProjectionPool)
    monkeypatch.setattr(
        R4_PARALLEL, "_warm_projection_pool",
        lambda pool: events.append("serial-warm"))
    monkeypatch.setattr(
        R4_PARALLEL, "reopen_synthetic_scoring_round",
        lambda *args, **kwargs: ("decision",) * 4)

    def score(**kwargs):
        mode = "parallel" if kwargs.get("decision_pool") is not None \
            else "serial"
        events.append(mode)
        return SimpleNamespace(decision_count=len(kwargs["decisions"]))

    monkeypatch.setattr(R4_PARALLEL, "score_v2_round", score)
    monkeypatch.setattr(
        R4_PARALLEL, "v2_round_population_bytes",
        lambda *args, **kwargs: b"byte-identical-population\n")
    times = iter((1, 101, 201, 301, 401, 601))
    cpu_times = iter((10, 50, 100, 150))
    monkeypatch.setattr(
        R4_PARALLEL.time, "monotonic_ns", lambda: next(times))
    monkeypatch.setattr(
        R4_PARALLEL, "_process_tree_cpu_time_ns",
        lambda: next(cpu_times))
    monkeypatch.setattr(
        R4_PARALLEL, "_aggregate_peak_host_memory_bytes",
        lambda workers: 1024**3)

    progress_events = []
    receipt = R4_PARALLEL.r4_terminal_parallel_capacity(
        repo=tmp_path.resolve(), expected_git="a" * 40,
        progress=lambda completed, total, phase: progress_events.append(
            (completed, total, phase)))

    assert events[:3] == [
        "parallel-enter", "parallel-warm", "parallel"]
    assert events.index("parallel-exit") < events.index("serial-enter")
    assert receipt["exact_serial_parallel_parity"] is True
    assert receipt["measurement_order"] \
        == "parallel-cold-then-serial-warm"
    assert receipt["parallel_wall_nanoseconds"] == 100
    assert receipt["serial_wall_nanoseconds"] == 200
    assert receipt["control_reopen_wall_nanoseconds"] == 100
    assert receipt["projected_scientific_control_wall_nanoseconds"] \
        == 100 * R4_PARALLEL.SCIENTIFIC_UNIT_CONTROL_REOPENS
    assert receipt["test_opening_executed"] is False
    assert progress_events[0] == (
        0, 2 * len(V2_RANKS), "measure-terminal-capacity-ranks")
    assert progress_events[-1] == (
        2 * len(V2_RANKS), 2 * len(V2_RANKS),
        "measure-terminal-capacity-ranks")


def test_r4_terminal_capacity_receipt_binds_parity_deadline_and_authority(
        tmp_path):
    context = _terminal_capacity_context(tmp_path)
    receipt = _terminal_capacity_receipt(context)
    raw = canonical_json_bytes(receipt)
    assert R4_PARALLEL._validate_capacity_receipt(
        raw, context=context, expected_git="a" * 40) == receipt

    mutations = (
        ("projected_scientific_unit_wall_nanoseconds", 0),
        ("scientific_unit_control_reopen_count", 1),
        ("projected_scientific_control_wall_nanoseconds", 1),
        ("decision_count", 0),
        ("exact_serial_parallel_parity", False),
        ("measurement_order", "serial-cold-then-parallel-warm"),
        ("aggregate_peak_host_memory_upper_bound_bytes",
         context.source.freeze.resource_caps.training_host_memory_bytes + 1),
        ("execution_authorized", True),
    )
    for key, value in mutations:
        forged = dict(receipt)
        forged[key] = value
        with pytest.raises(
                R4_PARALLEL.BeliefV2R4TerminalParallelError,
                match="reconstruction drift"):
            R4_PARALLEL._validate_capacity_receipt(
                canonical_json_bytes(forged), context=context,
                expected_git="a" * 40)


def test_r4_terminal_freeze_builder_binds_live_source_capacity_and_root(
        tmp_path, monkeypatch):
    context = _terminal_capacity_context(tmp_path)
    capacity_raw = canonical_json_bytes(_terminal_capacity_receipt(context))
    monkeypatch.setattr(
        R4_PARALLEL, "_capacity_context", lambda **kwargs: context)
    monkeypatch.setattr(
        R4_PARALLEL, "build_training_device_profile",
        lambda candidate: _device_profile())

    freeze = R4_PARALLEL.build_r4_terminal_parallel_freeze(
        repo=tmp_path.resolve(), expected_git="a" * 40,
        source_review_commit="c" * 40, capacity_raw=capacity_raw)

    assert freeze.execution_git == "a" * 40
    assert freeze.source_review_commit == "c" * 40
    assert freeze.evidence_root == str(
        context.terminal_spec.destination_evidence_root)
    assert freeze.preflight_result_sha256 == _sha_bytes(capacity_raw)
    assert freeze.deadline_estimate_receipt_sha256 == _sha_bytes(capacity_raw)
    assert freeze.preflight_runtime_sha256 == _sha_bytes(
        canonical_json_bytes(context.runtime.to_dict()))
    assert freeze.h0_inventory_sha256 \
        == context.source.freeze.h0_inventory_sha256
    assert freeze.cohorts == context.source.freeze.cohorts
    assert freeze.resource_caps == context.source.freeze.resource_caps

    with pytest.raises(
            R4_PARALLEL.BeliefV2R4TerminalParallelError,
            match="source review commit drift"):
        R4_PARALLEL.build_r4_terminal_parallel_freeze(
            repo=tmp_path.resolve(), expected_git="a" * 40,
            source_review_commit="not-a-commit", capacity_raw=capacity_raw)


def test_r4_terminal_runner_refuses_unexpected_root_entry_before_read(
        tmp_path, monkeypatch):
    """The fresh terminal root is a closed population, not a subset gate."""
    script = Path(__file__).parents[1] / "scripts" / (
        "belief_v2_r4_terminal_parallel.py")
    spec = importlib.util.spec_from_file_location(
        "belief_v2_r4_terminal_parallel_runner_test", script)
    assert spec is not None and spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    root = (tmp_path / "terminal").resolve()
    root.mkdir()
    for name in runner.ROOT_POPULATION:
        (root / name).write_bytes(b"placeholder\n")
    (root / "smuggled.json").write_bytes(b"{}\n")
    monkeypatch.setattr(
        runner, "load_terminal_source_spec",
        lambda: SimpleNamespace(destination_evidence_root=root))
    monkeypatch.setattr(runner, "load_calibration_import", lambda: object())

    with pytest.raises(ValueError, match="evidence root shape drift"):
        runner._load_root(root)


def test_r4_terminal_runner_refuses_foreign_import_root(
        tmp_path, monkeypatch):
    """A foreign venv injected by .pth must fail before scientific imports."""
    script = Path(__file__).parents[1] / "scripts" / (
        "belief_v2_r4_terminal_parallel.py")
    spec = importlib.util.spec_from_file_location(
        "belief_v2_r4_terminal_parallel_package_root_test", script)
    assert spec is not None and spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    foreign = tmp_path / "foreign-venv" / "lib" / "python3.14" / (
        "site-packages")
    monkeypatch.setattr(runner.sys, "path", [*runner.sys.path, str(foreign)])
    with pytest.raises(RuntimeError, match="refuses foreign import roots"):
        runner._refuse_foreign_import_roots()


def test_r4_terminal_runner_reopens_capacity_at_stage_gate(
        tmp_path, monkeypatch):
    """Witness the capacity verifier wiring, not only its pure helper."""
    script = Path(__file__).parents[1] / "scripts" / (
        "belief_v2_r4_terminal_parallel.py")
    spec = importlib.util.spec_from_file_location(
        "belief_v2_r4_terminal_parallel_capacity_gate_test", script)
    assert spec is not None and spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    root = (tmp_path / "terminal").resolve()
    root.mkdir()
    capacity_raw = canonical_json_bytes({"schema": "capacity-witness"})
    capacity_sha = _sha_bytes(capacity_raw)
    for name in runner.ROOT_POPULATION:
        path = root / name
        path.write_bytes(
            capacity_raw if name == "capacity.json" else b"placeholder\n")
        path.chmod(0o400)
    tombstone = root.with_name(root.name + ".consumed.json")
    tombstone.write_bytes(b"spent\n")
    tombstone.chmod(0o400)
    freeze = SimpleNamespace(
        evidence_root=str(root), preflight_result_sha256=capacity_sha,
        deadline_estimate_receipt_sha256=capacity_sha,
        preflight_runtime_sha256=_sha("runtime"), execution_git="a" * 40,
        source_bindings=(), runtime=object())
    monkeypatch.setattr(
        runner, "load_terminal_source_spec",
        lambda: SimpleNamespace(destination_evidence_root=root))
    monkeypatch.setattr(runner, "load_calibration_import", lambda: object())
    monkeypatch.setattr(
        runner, "execution_freeze_from_bytes", lambda raw: freeze)
    monkeypatch.setattr(
        runner, "r4_completion_admission_from_bytes",
        lambda *args, **kwargs: object())
    monkeypatch.setattr(
        runner, "validate_r4_completion_consumption_tombstone",
        lambda *args, **kwargs: None)
    monkeypatch.setattr(
        runner, "_validate_private_inputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        runner, "reauthenticate_r4_completion_admission",
        lambda *args, **kwargs: None)
    monkeypatch.setattr(
        runner, "validate_live_execution", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        runner, "reopen_r4_terminal_parallel_capacity",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ValueError("capacity verifier wiring witness")))

    with pytest.raises(ValueError, match="capacity verifier wiring witness"):
        runner._load_root(root)


def test_r4_terminal_runner_wires_sealed_result_recovery(tmp_path, monkeypatch):
    """The actual command reaches recovery, not scientific test scoring."""
    script = Path(__file__).parents[1] / "scripts" / (
        "belief_v2_r4_terminal_parallel.py")
    spec = importlib.util.spec_from_file_location(
        "belief_v2_r4_terminal_parallel_recovery_test", script)
    assert spec is not None and spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    root = (tmp_path / "terminal").resolve()
    root.mkdir()
    freeze = object()
    admission = object()
    marker = b"review"
    terminal_spec = object()
    imported = object()
    calibration = {"schema": "sealed-calibration"}
    source = object()
    selection = (tmp_path / "calibration" / "selection").resolve()
    monkeypatch.setattr(
        runner, "_load_root",
        lambda candidate: (freeze, admission, marker))
    monkeypatch.setattr(
        R4_PARALLEL, "_stage",
        lambda *args, **kwargs: (terminal_spec, imported))
    monkeypatch.setattr(
        R4_PARALLEL, "reopen_imported_calibration",
        lambda *args, **kwargs: (calibration, source, selection))
    calls = []

    def recover(*args, **kwargs):
        calls.append((args, kwargs))
        return {"schema": "recovered-outer"}

    monkeypatch.setattr(
        R4_PARALLEL, "_recover_r4_completion_terminal_reopened", recover)
    outputs = []
    monkeypatch.setattr(runner, "_output", outputs.append)
    parsed = runner.parser().parse_args([
        "recover-terminal-binding", "--root", str(root)])
    assert parsed.function is runner.recover_terminal
    parsed.function(parsed)

    assert outputs == [{"schema": "recovered-outer"}]
    assert len(calls) == 1
    assert calls[0][0] == (root, freeze, admission)
    assert calls[0][1]["calibration"] is calibration
    assert calls[0][1]["source"] is source
    assert calls[0][1]["calibration_directory"] == selection
    assert callable(calls[0][1]["progress"])


def test_test_scorer_reports_exact_outcome_blind_population_progress(
        monkeypatch):
    coordinates = (
        SimpleNamespace(split="train", round_seed=1, trump_rank="2"),
        SimpleNamespace(split="test", round_seed=2, trump_rank="3"),
        SimpleNamespace(split="test", round_seed=3, trump_rank="4"),
    )
    monkeypatch.setattr(
        TERMINAL_STAGE, "v2_round_coordinates", lambda: coordinates)
    monkeypatch.setattr(
        TERMINAL_STAGE, "reopen_synthetic_scoring_round",
        lambda *args, **kwargs: ("decision",))
    monkeypatch.setattr(
        TERMINAL_STAGE, "_human_group_digests",
        lambda *args, **kwargs: ("group-a", "group-b"))
    monkeypatch.setattr(
        TERMINAL_STAGE, "reopen_human_scoring_rounds",
        lambda *args, group_digest, **kwargs: ((
            f"round-{group_digest}", "5", ("decision",)),))
    monkeypatch.setattr(
        TERMINAL_STAGE, "score_v2_round",
        lambda **kwargs: SimpleNamespace(round_key=kwargs["round_key"]))
    progress = []

    synthetic, human = TERMINAL_STAGE._score_test_populations(
        Path("/unused"), object(), object(), {}, (object(),),
        progress=lambda completed, total, phase: progress.append(
            (completed, total, phase)))

    assert len(synthetic) == 2
    assert len(human) == 2
    assert progress == [
        (0, 2, "score-test-synthetic-rounds"),
        (1, 2, "score-test-synthetic-rounds"),
        (2, 2, "score-test-synthetic-rounds"),
        (0, 2, "score-test-human-groups"),
        (1, 2, "score-test-human-groups"),
        (2, 2, "score-test-human-groups"),
    ]
    with pytest.raises(
            TERMINAL_STAGE.BeliefV2TerminalControllerError,
            match="progress phase identity drift"):
        TERMINAL_STAGE._score_test_populations(
            Path("/unused"), object(), object(), {}, (object(),),
            progress_phase_prefix="not a token")


def test_terminal_statistics_use_independent_parallel_workers():
    barrier = threading.Barrier(3)

    def result(value):
        barrier.wait(timeout=2)
        return value

    assert TERMINAL_STAGE._run_independent_terminal_statistics(
        lambda: result("primary"),
        lambda: result("control"),
        lambda: result("human"),
    ) == ("primary", "control", "human")


def test_r4_completion_admission_is_narrow_and_round_trips():
    spec = R4_COMPLETION.load_r4_completion_source_spec()
    freeze = replace(_freeze(), evidence_root=str(
        spec.destination_evidence_root))
    marker = R4_COMPLETION.expected_r4_completion_review_marker(
        freeze, spec)
    claim = R4_COMPLETION.expected_r4_completion_review_claim(freeze, spec)
    assert claim["execution_mode"] == \
        "r4-calibration-test-terminal-only"
    assert "bounded_capture_reference_training_and_one_test_open_authorized" \
        not in claim
    assert claim["authority"] == \
        R4_COMPLETION.COMPLETION_ADMISSION_AUTHORITY
    admission = R4_COMPLETION.R4CompletionAdmissionV1(
        freeze_sha256=freeze.sha256(),
        execution_git=freeze.execution_git,
        source_manifest_sha256=freeze.source_manifest_sha256,
        seed_registry_sha256=freeze.seed_registry_sha256,
        source_spec_sha256=spec.sha256(), review_commit="c" * 40,
        canonical_remote_tip="d" * 40,
        review_marker_sha256=hashlib.sha256(marker).hexdigest(),
        evidence_root=freeze.evidence_root)
    raw = admission.canonical_bytes()
    reopened = R4_COMPLETION.r4_completion_admission_from_bytes(
        raw, freeze=freeze, review_marker=marker, spec=spec)
    assert reopened == admission
    authority = reopened.to_dict()["authority"]
    assert authority["calibration_open_authorized"] is True
    assert authority["one_test_split_open_authorized"] is True
    assert authority["terminal_reconstruction_authorized"] is True
    assert authority["capture_authorized"] is False
    assert authority["reference_generation_authorized"] is False
    assert authority["training_authorized"] is False
    tombstone = R4_COMPLETION.r4_completion_consumption_tombstone_bytes(
        admission)
    R4_COMPLETION.validate_r4_completion_consumption_tombstone(
        tombstone, admission=admission)
    forged = json.loads(raw)
    forged["authority"]["training_authorized"] = True
    with pytest.raises(
            R4_COMPLETION.BeliefV2R4CompletionError,
            match="field/authority drift"):
        R4_COMPLETION.r4_completion_admission_from_bytes(
            canonical_json_bytes(forged), freeze=freeze,
            review_marker=marker, spec=spec)


def test_r4_completion_admission_cannot_enter_generic_work_stages(tmp_path):
    root = tmp_path.resolve()
    freeze = replace(_freeze(), evidence_root=str(root))
    admission = R4_COMPLETION.R4CompletionAdmissionV1(
        freeze_sha256=freeze.sha256(),
        execution_git=freeze.execution_git,
        source_manifest_sha256=freeze.source_manifest_sha256,
        seed_registry_sha256=freeze.seed_registry_sha256,
        source_spec_sha256=_sha("completion spec"),
        review_commit="c" * 40, canonical_remote_tip="d" * 40,
        review_marker_sha256=_sha("review"), evidence_root=str(root))
    with pytest.raises(
            PIPELINE_STAGE.BeliefV2ControllerError,
            match="stage admission refused"):
        PIPELINE_STAGE.run_capture_lane(
            root, freeze, admission, repo=root, lane=0,
            review_marker=b"review")
    with pytest.raises(
            PIPELINE_STAGE.BeliefV2ControllerError,
            match="stage admission refused"):
        PIPELINE_STAGE.run_reference_lane(
            root, freeze, admission, repo=root, lane=0,
            review_marker=b"review")
    with pytest.raises(
            PIPELINE_STAGE.BeliefV2ControllerError,
            match="stage admission refused"):
        TRAINING_STAGE.run_training_cohort(
            root, freeze, admission, repo=root, review_marker=b"review",
            primary=None, realization=None, training_examples=None,
            calibration=None, calibration_examples=None,
            qualification_plan=None, qualification_result=None)
    assert not (root / "capture").exists()
    assert not (root / "reference").exists()
    assert not (root / "training").exists()


def test_r4_completion_calibration_writes_only_fresh_namespace(
        tmp_path, monkeypatch):
    root = (tmp_path / "completion").resolve()
    source_root = (tmp_path / "source").resolve()
    root.mkdir()
    source_root.mkdir()
    completion_freeze = replace(_freeze(), evidence_root=str(root))
    completion_admission = _completion_admission(completion_freeze)
    source_freeze = replace(_freeze(), evidence_root=str(source_root))
    source_admission = _admission(source_freeze)
    plan, qualification = _qualification(source_freeze)
    human_selection, scale, _, _, _ = _statistics()
    cohort_ids = tuple(row.cohort_id for row in source_freeze.cohorts)
    cohorts = tuple(SimpleNamespace(cohort_id=value) for value in cohort_ids)
    synthetic_rows = (_terminal_score("synthetic", cohort_ids),)
    human_rows = (_terminal_score("human", cohort_ids),)
    spec = SimpleNamespace(
        source_evidence_root=source_root,
        destination_evidence_root=root,
        source_tensor_cache_manifest_sha256=_sha("legacy tensor cache"),
        sha256=lambda: _sha("R4 source spec"))
    source = SimpleNamespace(
        spec=spec, freeze=source_freeze, admission=source_admission,
        inventory={}, group_split={})
    monkeypatch.setattr(
        R4_COMPLETION, "load_r4_completion_source_spec", lambda: spec)
    monkeypatch.setattr(
        R4_COMPLETION, "_completion_stage_gate",
        lambda *args, **kwargs: None)
    monkeypatch.setattr(
        R4_COMPLETION, "reopen_r4_completion_source",
        lambda *args, **kwargs: source)
    training_inputs = SimpleNamespace(sha256=lambda: _sha("inputs"))
    monkeypatch.setattr(
        R4_COMPLETION, "reopen_training_input_index",
        lambda *args, **kwargs: ({}, training_inputs))
    training_hashes = tuple((value, _sha(value)) for value in cohort_ids)
    monkeypatch.setattr(
        R4_COMPLETION, "reopen_trained_scoring_cohorts",
        lambda *args, **kwargs: (
            cohorts, plan, qualification, training_hashes))
    projection_token = object()
    warmed = []

    class Pool:
        def __enter__(self):
            return projection_token

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(R4_COMPLETION, "_projection_pool", Pool)
    monkeypatch.setattr(
        R4_COMPLETION, "_warm_projection_pool",
        lambda executor: warmed.append(executor))

    def synthetic_score(*args, **kwargs):
        assert kwargs["projection_executor"] is projection_token
        return synthetic_rows

    def human_score(*args, **kwargs):
        assert kwargs["projection_executor"] is projection_token
        return human_rows

    monkeypatch.setattr(
        R4_COMPLETION, "_score_synthetic", synthetic_score)
    monkeypatch.setattr(
        R4_COMPLETION, "_score_human", human_score)
    monkeypatch.setattr(
        R4_COMPLETION, "_expected_synthetic_rounds",
        lambda: ((synthetic_rows[0].round_key, "2"),))
    monkeypatch.setattr(
        R4_COMPLETION, "v2_reference_replicates_are_stable",
        lambda *args, **kwargs: True)
    monkeypatch.setattr(
        R4_COMPLETION, "evaluate_human_mixture_selection",
        lambda *args, **kwargs: human_selection)
    monkeypatch.setattr(
        R4_COMPLETION, "evaluate_scale_curve",
        lambda *args, **kwargs: scale)

    reopened_manifests = []

    def reopen_selection(directory, **kwargs):
        assert kwargs["legacy_tensor_cache_manifest_sha256"] \
            == spec.source_tensor_cache_manifest_sha256
        raw = (directory / "manifest.json").read_bytes()
        value = json.loads(raw)
        assert canonical_json_bytes(value) == raw
        reopened_manifests.append(value)
        return value

    monkeypatch.setattr(
        R4_COMPLETION, "reopen_v2_calibration_selection",
        reopen_selection)
    outer = R4_COMPLETION.run_r4_completion_calibration(
        root, completion_freeze, completion_admission,
        repo=Path("/unused"), review_marker=b"review")
    assert outer["calibration_completed_before_test_open"] is True
    assert outer["source_test_split_opened"] is False
    assert outer["authority"]["one_test_split_open_authorized"] is True
    assert not tuple(source_root.iterdir())
    assert (root / "calibration" / "selection" / "manifest.json").is_file()
    assert not (root / "r4-completion-test-attempt.json").exists()
    assert warmed == [projection_token]
    inner, reopened_source = R4_COMPLETION.reopen_r4_completion_calibration(
        root, completion_freeze, completion_admission,
        repo=Path("/unused"), review_marker=b"review")
    assert reopened_source is source
    assert inner == reopened_manifests[0]
    assert len(reopened_manifests) == 2


def test_r4_pretest_readiness_reopens_calibration_and_refuses_consumed_slot(
        tmp_path, monkeypatch):
    root = (tmp_path / "completion").resolve()
    source_root = (tmp_path / "source").resolve()
    root.mkdir()
    source_root.mkdir()
    freeze = replace(_freeze(), evidence_root=str(root))
    admission = _completion_admission(freeze)
    source_freeze = replace(_freeze(), evidence_root=str(source_root))
    source = SimpleNamespace(
        spec=SimpleNamespace(sha256=lambda: _sha("source spec")),
        freeze=source_freeze, admission=_admission(source_freeze),
        group_split={})
    calibration = {"schema": "calibration", "decision": "selected"}
    monkeypatch.setattr(
        R4_COMPLETION, "reopen_r4_completion_calibration",
        lambda *args, **kwargs: (calibration, source))
    monkeypatch.setattr(
        R4_COMPLETION, "_expected_test_synthetic_rounds",
        lambda: ((_sha("synthetic-a"), "2"),
                 (_sha("synthetic-b"), "A")))
    readiness = R4_COMPLETION.r4_completion_pretest_readiness(
        root, freeze, admission, repo=Path("/unused"),
        review_marker=b"review")
    assert readiness["source_calibration_manifest_sha256"] == hashlib.sha256(
        canonical_json_bytes(calibration)).hexdigest()
    assert readiness["synthetic_test_expected_round_count"] == 2
    assert readiness["test_population_metadata_opened"] is False
    assert readiness["source_test_split_decision_open_count"] == 0
    assert readiness["test_opening_executed"] is False
    assert readiness["execution_authorized"] is False

    (root / "r4-completion-test-attempt.json").write_bytes(b"occupied\n")
    with pytest.raises(
            R4_COMPLETION.BeliefV2R4CompletionError,
            match="pretest namespace is already consumed"):
        R4_COMPLETION.r4_completion_pretest_readiness(
            root, freeze, admission, repo=Path("/unused"),
            review_marker=b"review")


def test_terminal_attempt_is_durable_before_test_scorer_failure(
        tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    freeze = replace(_freeze(), evidence_root=str(root))
    admission = _admission(freeze)
    _stub_terminal_dependencies(monkeypatch, freeze)

    def fail_after_attempt(*args, **kwargs):
        assert (root / "terminal.partial" / "attempt.json").is_file()
        raise ValueError("injected test scorer failure")

    monkeypatch.setattr(
        TERMINAL_STAGE, "_score_test_populations", fail_after_attempt)
    with pytest.raises(
            TERMINAL_STAGE.BeliefV2TerminalControllerError,
            match="after durable attempt"):
        TERMINAL_STAGE.run_v2_terminal(
            root, freeze, admission, repo=Path("/unused"),
            review_marker=b"review", inventory={}, group_split={})
    assert {path.name for path in (root / "terminal.partial").iterdir()} \
        == {"attempt.json"}
    with pytest.raises(
            TERMINAL_STAGE.BeliefV2TerminalControllerError,
            match="slot is occupied"):
        TERMINAL_STAGE.run_v2_terminal(
            root, freeze, admission, repo=Path("/unused"),
            review_marker=b"review", inventory={}, group_split={})


def test_r4_completion_attempt_is_durable_before_original_test_read(
        tmp_path, monkeypatch):
    root = (tmp_path / "completion").resolve()
    source_root = (tmp_path / "source").resolve()
    root.mkdir()
    source_root.mkdir()
    completion_freeze = replace(_freeze(), evidence_root=str(root))
    completion_admission = _completion_admission(completion_freeze)
    source_freeze = replace(_freeze(), evidence_root=str(source_root))
    source_admission = _admission(source_freeze)
    calibration = {
        "schema": "test-calibration",
        "cohort_ids": [row.cohort_id for row in source_freeze.cohorts],
        "calibration_passed": True,
        "selected_cohort_id": "synthetic-primary",
    }
    spec = SimpleNamespace(
        source_evidence_root=source_root,
        source_tensor_cache_manifest_sha256=_sha("legacy tensor cache"),
        sha256=lambda: _sha("R4 source spec"))
    source = SimpleNamespace(
        spec=spec, freeze=source_freeze, admission=source_admission,
        inventory={}, group_split={})
    monkeypatch.setattr(
        R4_COMPLETION, "load_r4_completion_source_spec", lambda: spec)
    monkeypatch.setattr(
        R4_COMPLETION, "_completion_stage_gate",
        lambda *args, **kwargs: None)
    monkeypatch.setattr(
        R4_COMPLETION, "reopen_r4_completion_calibration",
        lambda *args, **kwargs: (calibration, source))
    monkeypatch.setattr(
        R4_COMPLETION, "reopen_training_input_index",
        lambda *args, **kwargs: ({}, SimpleNamespace()))
    monkeypatch.setattr(
        R4_COMPLETION, "reopen_trained_scoring_cohorts",
        lambda *args, **kwargs: ((), None, None, ()))

    class DecisionPool:
        def __init__(self, cohort_population):
            assert cohort_population == ()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def warm(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(
        R4_COMPLETION, "V2DecisionScoringPool", DecisionPool)

    test_reads = 0

    def test_read_sentinel(*args, **kwargs):
        nonlocal test_reads
        test_reads += 1
        raise AssertionError("test scorer must not run before calibration gate")

    monkeypatch.setattr(
        R4_COMPLETION, "_calibration_statistics",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ValueError("injected unstable calibration")))
    monkeypatch.setattr(
        R4_COMPLETION, "_score_test_populations", test_read_sentinel)
    with pytest.raises(
            R4_COMPLETION.BeliefV2R4CompletionError,
            match="not eligible for test opening"):
        R4_COMPLETION.run_r4_completion_terminal(
            root, completion_freeze, completion_admission,
            repo=Path("/unused"), review_marker=b"review")
    assert test_reads == 0
    assert not (root / "r4-completion-test-attempt.json").exists()
    assert not (root / "terminal.partial").exists()
    monkeypatch.setattr(
        R4_COMPLETION, "_calibration_statistics",
        lambda *args, **kwargs: (calibration, None, None))

    def fail_pool_startup(_cohorts):
        raise ValueError("injected worker startup failure")

    monkeypatch.setattr(
        R4_COMPLETION, "V2DecisionScoringPool", fail_pool_startup)
    with pytest.raises(
            R4_COMPLETION.BeliefV2R4CompletionError,
            match="preflight refused before test attempt"):
        R4_COMPLETION.run_r4_completion_terminal(
            root, completion_freeze, completion_admission,
            repo=Path("/unused"), review_marker=b"review")
    assert not (root / "r4-completion-test-attempt.json").exists()
    assert not (root / "terminal.partial").exists()
    monkeypatch.setattr(
        R4_COMPLETION, "V2DecisionScoringPool", DecisionPool)

    calls = 0

    def fail_at_original_test_read(*args, **kwargs):
        nonlocal calls
        calls += 1
        assert (root / "r4-completion-test-attempt.json").is_file()
        assert (root / "terminal.partial" / "attempt.json").is_file()
        raise ValueError("injected original R4 test read failure")

    monkeypatch.setattr(
        R4_COMPLETION, "_score_test_populations",
        fail_at_original_test_read)
    with pytest.raises(
            R4_COMPLETION.BeliefV2R4CompletionError,
            match="after durable attempt"):
        R4_COMPLETION.run_r4_completion_terminal(
            root, completion_freeze, completion_admission,
            repo=Path("/unused"), review_marker=b"review")
    assert calls == 1
    assert {path.name for path in (root / "terminal.partial").iterdir()} \
        == {"attempt.json"}
    with pytest.raises(
            R4_COMPLETION.BeliefV2R4CompletionError,
            match="namespace is already occupied"):
        R4_COMPLETION.run_r4_completion_terminal(
            root, completion_freeze, completion_admission,
            repo=Path("/unused"), review_marker=b"review")
    assert calls == 1


def test_r4_completion_terminal_round_trip_binds_fresh_and_source_runs(
        tmp_path, monkeypatch):
    root = (tmp_path / "completion").resolve()
    source_root = (tmp_path / "source").resolve()
    root.mkdir()
    source_root.mkdir()
    completion_freeze = replace(_freeze(), evidence_root=str(root))
    completion_admission = _completion_admission(completion_freeze)
    source_freeze = replace(_freeze(), evidence_root=str(source_root))
    source_admission = _admission(source_freeze)
    plan, qualification = _qualification(source_freeze)
    receipt = _receipt(source_freeze, plan, qualification)
    human_selection, scale, primary, control, human = _statistics()
    cohort_ids = tuple(row.cohort_id for row in source_freeze.cohorts)
    cohorts = tuple(SimpleNamespace(cohort_id=value) for value in cohort_ids)
    synthetic_rows = (_terminal_score("synthetic", cohort_ids),)
    human_rows = (_terminal_score("human", cohort_ids),)
    calibration = {
        "schema": "test-calibration", "cohort_ids": list(cohort_ids),
        "calibration_passed": True,
        "selected_cohort_id": "synthetic-primary",
    }
    spec = SimpleNamespace(
        source_evidence_root=source_root,
        source_tensor_cache_manifest_sha256=_sha("legacy tensor cache"),
        sha256=lambda: _sha("R4 source spec"))
    source = SimpleNamespace(
        spec=spec, freeze=source_freeze, admission=source_admission,
        inventory={}, group_split={})
    monkeypatch.setattr(
        R4_COMPLETION, "load_r4_completion_source_spec", lambda: spec)
    monkeypatch.setattr(
        R4_COMPLETION, "_completion_stage_gate",
        lambda *args, **kwargs: None)
    monkeypatch.setattr(
        R4_COMPLETION, "reopen_r4_completion_calibration",
        lambda *args, **kwargs: (calibration, source))
    monkeypatch.setattr(
        R4_COMPLETION, "reopen_training_input_index",
        lambda *args, **kwargs: ({}, SimpleNamespace()))
    training_hashes = tuple((value, _sha(value)) for value in cohort_ids)
    monkeypatch.setattr(
        R4_COMPLETION, "reopen_trained_scoring_cohorts",
        lambda *args, **kwargs: (
            cohorts, plan, qualification, training_hashes))
    decision_token = object()
    warmed = []

    class DecisionPool:
        def __init__(self, cohort_population):
            assert cohort_population == cohorts

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def warm(self):
            warmed.append(decision_token)

        def close(self):
            pass

    monkeypatch.setattr(
        R4_COMPLETION, "V2DecisionScoringPool", DecisionPool)

    def score_test(*args, **kwargs):
        assert isinstance(kwargs["decision_pool"], DecisionPool)
        return synthetic_rows, human_rows

    monkeypatch.setattr(
        R4_COMPLETION, "_score_test_populations", score_test)
    monkeypatch.setattr(
        R4_COMPLETION, "_expected_test_synthetic_rounds",
        lambda: ((synthetic_rows[0].round_key, "2"),))
    monkeypatch.setattr(
        R4_COMPLETION, "_expected_test_human_rounds",
        lambda *args, **kwargs: ((human_rows[0].round_key, "2"),))
    monkeypatch.setattr(
        R4_COMPLETION, "evaluate_primary_test",
        lambda *args, **kwargs: primary)
    monkeypatch.setattr(
        R4_COMPLETION, "evaluate_label_control_test",
        lambda *args, **kwargs: control)
    monkeypatch.setattr(
        R4_COMPLETION, "evaluate_human_transfer_test",
        lambda *args, **kwargs: human)
    monkeypatch.setattr(
        R4_COMPLETION, "_derive_integrity_receipt",
        lambda *args, **kwargs: receipt)
    monkeypatch.setattr(
        R4_COMPLETION, "_calibration_statistics",
        lambda *args, **kwargs: (calibration, human_selection, scale))

    inner_manifests = []
    progress_events = []

    def progress(completed, total, phase):
        progress_events.append((completed, total, phase))

    def reopen_inner(directory, **kwargs):
        assert kwargs["parallel_decisions"] is True
        assert kwargs["progress"] is (
            progress if len(inner_manifests) < 2 else None)
        raw = (directory / "manifest.json").read_bytes()
        manifest = json.loads(raw)
        assert canonical_json_bytes(manifest) == raw
        inner_manifests.append(manifest)
        if len(inner_manifests) == 1:
            raise RuntimeError("injected immediate reconstruction failure")
        return manifest

    monkeypatch.setattr(
        R4_COMPLETION, "reopen_v2_terminal", reopen_inner)
    with pytest.raises(
            RuntimeError, match="injected immediate reconstruction failure"):
        R4_COMPLETION.run_r4_completion_terminal(
            root, completion_freeze, completion_admission,
            repo=Path("/unused"), review_marker=b"review", progress=progress)
    assert (root / "r4-completion-test-attempt.json").is_file()
    assert (root / "terminal").is_dir()
    assert not (root / "terminal.partial").exists()
    assert not (root / "r4-completion-terminal.json").exists()
    with pytest.raises(
            R4_COMPLETION.BeliefV2R4CompletionError,
            match="namespace is already occupied"):
        R4_COMPLETION.run_r4_completion_terminal(
            root, completion_freeze, completion_admission,
            repo=Path("/unused"), review_marker=b"review")
    outer = R4_COMPLETION.recover_r4_completion_terminal(
        root, completion_freeze, completion_admission,
        repo=Path("/unused"), review_marker=b"review", progress=progress)
    assert outer["terminal_route"] == PASS_B3
    assert outer["source_test_split_decision_open_count"] == 1
    assert outer["retry_count"] == 0
    assert outer["authority"]["deployment_authorized"] is False
    assert (root / "terminal" / "result.json").is_file()
    assert R4_COMPLETION.reopen_r4_completion_terminal(
        root, completion_freeze, completion_admission,
        repo=Path("/unused"), review_marker=b"review") == outer
    with pytest.raises(
            R4_COMPLETION.BeliefV2R4CompletionError,
            match="not recovery-eligible"):
        R4_COMPLETION.recover_r4_completion_terminal(
            root, completion_freeze, completion_admission,
            repo=Path("/unused"), review_marker=b"review")
    assert len(inner_manifests) == 3
    assert warmed == [decision_token]
    assert (5, 6, "r4-terminal-immediate-reconstruction") \
        in progress_events
    assert (0, 1, "r4-terminal-recovery-reconstruction") \
        in progress_events
    assert progress_events[-1] == (1, 1, "r4-terminal-recovery-complete")

    outer_path = root / "r4-completion-terminal.json"
    forged = json.loads(outer_path.read_bytes())
    forged["terminal_route"] = SELECT_NONE
    outer_path.chmod(0o600)
    outer_path.write_bytes(canonical_json_bytes(forged))
    outer_path.chmod(0o400)
    with pytest.raises(
            R4_COMPLETION.BeliefV2R4CompletionError,
            match="outer binding drift"):
        R4_COMPLETION.reopen_r4_completion_terminal(
            root, completion_freeze, completion_admission,
            repo=Path("/unused"), review_marker=b"review")


def test_terminal_round_trip_and_coordinated_result_rehash_refuse(
        tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    freeze = replace(_freeze(), evidence_root=str(root))
    admission = _admission(freeze)
    _stub_terminal_dependencies(monkeypatch, freeze)
    progress_stream = io.StringIO()
    progress = V2ProgressReporter(
        stage="terminal-round-trip-test", worker="all-cohorts",
        stream=progress_stream)
    result = TERMINAL_STAGE.run_v2_terminal(
        root, freeze, admission, repo=Path("/unused"),
        review_marker=b"review", inventory={}, group_split={},
        progress=progress.update)
    assert result["terminal_route"] == PASS_B3
    assert result["test_split_decision_open_count"] == 1
    assert result["deployment_authorized"] is False
    progress_output = progress_stream.getvalue()
    assert '"phase":"score-test-synthetic-rounds"' in progress_output
    assert '"phase":"reconstruct-test-synthetic-rounds"' \
        in progress_output
    directory = root / "terminal"
    assert TERMINAL_STAGE.reopen_v2_terminal(
        directory, freeze=freeze, admission=admission,
        inventory={}, group_split={}) == result

    warmed = []

    class DecisionPool:
        def __init__(self, cohorts):
            assert cohorts

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def warm(self):
            warmed.append(True)

    monkeypatch.setattr(
        TERMINAL_STAGE, "V2DecisionScoringPool", DecisionPool)
    parallel_stream = io.StringIO()
    parallel_progress = V2ProgressReporter(
        stage="parallel-terminal-reopen-test", worker="all-cohorts",
        stream=parallel_stream)
    assert TERMINAL_STAGE.reopen_v2_terminal(
        directory, freeze=freeze, admission=admission,
        inventory={}, group_split={}, parallel_decisions=True,
        progress=parallel_progress.update) == result
    assert warmed == [True]
    assert '"phase":"reconstruct-test-synthetic-rounds"' \
        in parallel_stream.getvalue()

    result_path = directory / "result.json"
    forged = json.loads(result_path.read_bytes())
    forged["terminal_route"] = SELECT_NONE
    forged_raw = canonical_json_bytes(forged)
    result_path.chmod(0o600)
    result_path.write_bytes(forged_raw)
    result_path.chmod(0o400)
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["files"]["terminal_result"]["byte_count"] = len(forged_raw)
    manifest["files"]["terminal_result"]["sha256"] = hashlib.sha256(
        forged_raw).hexdigest()
    manifest_path.chmod(0o600)
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    manifest_path.chmod(0o400)
    with pytest.raises(
            TERMINAL_STAGE.BeliefV2TerminalControllerError,
            match="result reconstruction"):
        TERMINAL_STAGE.reopen_v2_terminal(
            directory, freeze=freeze, admission=admission,
            inventory={}, group_split={})


def test_terminal_source_replay_refuses_self_consistent_score_substitution(
        tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    freeze = replace(_freeze(), evidence_root=str(root))
    admission = _admission(freeze)
    _stub_terminal_dependencies(monkeypatch, freeze)
    TERMINAL_STAGE.run_v2_terminal(
        root, freeze, admission, repo=Path("/unused"),
        review_marker=b"review", inventory={}, group_split={})

    directory = root / "terminal"
    cohort_ids = tuple(row.cohort_id for row in freeze.cohorts)
    substituted = replace(
        _terminal_score("synthetic", cohort_ids),
        reference_brier_ppb=101)
    population_raw = v2_round_population_bytes(
        (substituted,), cohort_ids=cohort_ids, label="synthetic_test")
    population_path = directory / "synthetic-test-scores.json"
    population_path.chmod(0o600)
    population_path.write_bytes(population_raw)
    population_path.chmod(0o400)

    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["files"]["synthetic_test"].update({
        "byte_count": len(population_raw),
        "sha256": hashlib.sha256(population_raw).hexdigest(),
    })
    manifest_path.chmod(0o600)
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    manifest_path.chmod(0o400)

    with pytest.raises(
            TERMINAL_STAGE.BeliefV2TerminalControllerError,
            match="persisted score population differs from source replay"):
        TERMINAL_STAGE.reopen_v2_terminal(
            directory, freeze=freeze, admission=admission,
            inventory={}, group_split={})


def test_terminal_resource_receipt_wires_parallel_spans_and_gpu_work(
        tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    freeze = replace(_freeze(), evidence_root=str(root))
    admission = _admission(freeze)
    plan, qualification = _qualification(freeze)

    def resource(start, finish, *, artifact=10, training=False,
                 cohort=False, host_peak=1_500, device_peak=2_500):
        row = {
            "started_monotonic_nanoseconds": start,
            "finished_monotonic_nanoseconds": finish,
            "wall_nanoseconds": finish - start,
            "cpu_nanoseconds": finish - start,
            "artifact_bytes": artifact,
            "retry_count": 0, "drop_count": 0,
        }
        if training:
            row.update({
                "training_compute_nanoseconds": finish - start,
                "peak_host_memory_bytes": host_peak,
                "peak_device_memory_bytes": device_peak,
            })
        if cohort:
            process_count, aggregate = training_host_memory_upper_bound(
                host_peak, selected_device=qualification.selected_device,
                cpu_cohort_process_count=len(freeze.cohorts))
            row.update({
                "selected_device": qualification.selected_device,
                "host_memory_process_count": process_count,
                "aggregate_peak_host_memory_upper_bound_bytes": aggregate,
            })
        return row

    monkeypatch.setattr(
        TERMINAL_STAGE, "reopen_capture_lane",
        lambda *args, lane, **kwargs: {
            "round_count": V2_ROUND_COUNT // 16,
            "resources": resource(100 + lane, 200 + lane)})
    monkeypatch.setattr(
        TERMINAL_STAGE, "reopen_reference_lane",
        lambda *args, lane, **kwargs: {
            "job_count": len(reference_lane_jobs(lane)),
            "resources": resource(300 + lane, 400 + lane)})
    digests = {
        "train": _sha("human-train"),
        "calibration": _sha("human-calibration"),
        "test": _sha("human-test"),
    }
    monkeypatch.setattr(
        TERMINAL_STAGE, "_human_group_digests",
        lambda group_split, split: (digests[split],))
    monkeypatch.setattr(
        TERMINAL_STAGE, "reopen_human_group_manifest",
        lambda *args, **kwargs: {"resources": resource(90, 250)})
    monkeypatch.setattr(
        TERMINAL_STAGE, "reopen_human_reference_group",
        lambda *args, **kwargs: {"resources": resource(290, 450)})
    input_index_manifest = {"resources": resource(
        450, 480, artifact=10, training=True,
        host_peak=1_400, device_peak=0)}
    cache_resources = resource(
        480, 490, artifact=30, training=True,
        host_peak=1_401, device_peak=0)
    monkeypatch.setattr(
        TERMINAL_STAGE, "reopen_training_tensor_cache",
        lambda *args, **kwargs: (
            {"resources": cache_resources}, {}, lambda: iter(()), 1,
            _sha("tensor-cache")))

    training_hashes = []
    for index, cohort in enumerate(freeze.cohorts):
        directory = root / "training" / cohort.cohort_id
        directory.mkdir(parents=True)
        payload = {"resources": resource(
            500 + index, 600 + index, artifact=20, training=True,
            cohort=True,
            host_peak=1_500 + index, device_peak=2_500 + index)}
        raw = canonical_json_bytes(payload)
        manifest_path = directory / "manifest.json"
        manifest_path.write_bytes(raw)
        manifest_path.chmod(0o400)
        training_hashes.append((cohort.cohort_id, _sha_bytes(raw)))

    receipt = TERMINAL_STAGE._derive_integrity_receipt(
        root, freeze, admission, {}, plan=plan,
        qualification=qualification,
        input_index_manifest=input_index_manifest,
        training_hashes=tuple(training_hashes),
        synthetic_test_count=1_339, human_test_decision_count=174)
    qualification_work = sum(
        row.wall_nanoseconds for row in qualification.arms)
    assert receipt.capture_reopened_round_count == V2_ROUND_COUNT
    assert receipt.reference_reopened_round_count \
        == expected_reference_job_count()
    assert receipt.capture_wall_nanoseconds == 160
    assert receipt.reference_wall_nanoseconds == 160
    assert receipt.training_device_nanoseconds \
        == qualification_work + 4 * 100 + 30 + 10
    assert receipt.training_wall_nanoseconds \
        == qualification_work + 103 + 30 + 10
    assert receipt.training_peak_host_memory_bytes == 1_503
    assert receipt.training_peak_device_memory_bytes == 2_503
    assert receipt.test_split_decision_open_count == 1
    assert derive_terminal_result(
        freeze, plan, qualification, receipt, *_statistics()
    ).terminal_route == PASS_B3

    first_id, _ = training_hashes[0]
    first_path = root / "training" / first_id / "manifest.json"
    first = json.loads(first_path.read_bytes())
    first["resources"][
        "aggregate_peak_host_memory_upper_bound_bytes"] += 1
    first_raw = canonical_json_bytes(first)
    first_path.chmod(0o600)
    first_path.write_bytes(first_raw)
    first_path.chmod(0o400)
    corrupted_hashes = (
        (first_id, _sha_bytes(first_raw)), *training_hashes[1:])
    with pytest.raises(
            TERMINAL_STAGE.BeliefV2TerminalControllerError,
            match="host memory reconstruction"):
        TERMINAL_STAGE._derive_integrity_receipt(
            root, freeze, admission, {}, plan=plan,
            qualification=qualification,
            input_index_manifest=input_index_manifest,
            training_hashes=corrupted_hashes,
            synthetic_test_count=1_339, human_test_decision_count=174)
