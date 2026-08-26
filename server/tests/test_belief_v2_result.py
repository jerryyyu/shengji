"""Closed routing and measured-integrity tests for the V2 terminal result."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import shengji.rl.belief_v2_controller as PIPELINE_STAGE
import shengji.rl.belief_v2_terminal_controller as TERMINAL_STAGE
import shengji.rl.belief_v2_training_controller as TRAINING_STAGE
import shengji.rl.belief_v2_r4_completion as R4_COMPLETION

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
from shengji.rl.belief_v2_protocol import V2_RANKS, V2_ROUND_COUNT
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
    monkeypatch.setattr(
        TERMINAL_STAGE, "_score_test_populations",
        lambda *args, **kwargs: (synthetic_rows, human_rows))
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

    def score_test(*args, **kwargs):
        assert kwargs["projection_executor"] is projection_token
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

    def reopen_inner(directory, **kwargs):
        assert kwargs["projection_executor"] is projection_token
        raw = (directory / "manifest.json").read_bytes()
        manifest = json.loads(raw)
        assert canonical_json_bytes(manifest) == raw
        inner_manifests.append(manifest)
        return manifest

    monkeypatch.setattr(
        R4_COMPLETION, "reopen_v2_terminal", reopen_inner)
    outer = R4_COMPLETION.run_r4_completion_terminal(
        root, completion_freeze, completion_admission,
        repo=Path("/unused"), review_marker=b"review")
    assert outer["terminal_route"] == PASS_B3
    assert outer["source_test_split_decision_open_count"] == 1
    assert outer["retry_count"] == 0
    assert outer["authority"]["deployment_authorized"] is False
    assert (root / "terminal" / "result.json").is_file()
    assert R4_COMPLETION.reopen_r4_completion_terminal(
        root, completion_freeze, completion_admission,
        repo=Path("/unused"), review_marker=b"review") == outer
    assert len(inner_manifests) == 2
    assert warmed == [projection_token, projection_token,
                      projection_token]

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
    result = TERMINAL_STAGE.run_v2_terminal(
        root, freeze, admission, repo=Path("/unused"),
        review_marker=b"review", inventory={}, group_split={})
    assert result["terminal_route"] == PASS_B3
    assert result["test_split_decision_open_count"] == 1
    assert result["deployment_authorized"] is False
    directory = root / "terminal"
    assert TERMINAL_STAGE.reopen_v2_terminal(
        directory, freeze=freeze, admission=admission,
        inventory={}, group_split={}) == result

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
