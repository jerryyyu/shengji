"""Single terminal-decision tests for the BELIEF-V1 B2 experiment."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from shengji.rl.belief_b2_protocol import CAPTURE_CORE_HOUR_CAP
from shengji.rl.belief_b2_result import (
    NO_BEHAVIOR,
    NO_LIFT,
    PASS,
    REFUSE_INCOMPLETE,
    REFUSE_MECHANICS,
    NS_PER_HOUR,
    B2ArtifactInventoryV1,
    B2MechanicsResultV1,
    B2ResourceReceiptV1,
    B2TerminalEvidenceV1,
    BeliefB2ResultError,
    evaluate_b2_terminal,
    validate_b2_terminal,
)
from shengji.rl.belief_b2_statistics import (
    C1CalibrationResultV1,
    N2PermutedLabelResultV1,
)
from shengji.rl.belief_behavioral_evaluation import (
    POOLED_STRATUM,
    BehavioralStratumResultV1,
    C2BehavioralResultV1,
)
from shengji.rl.belief_cohort import COHORT_SCHEMA, ensemble_identity
from shengji.rl.belief_reliability import (
    CountReliabilityReportV1,
    LinearExpectationReliabilityV1,
    ReliabilityBinV1,
    ReliabilityStratumV1,
)
from shengji.rl.belief_synthetic import (
    C4_CONTEXT_IDS,
    C4_MODEL_SEED,
    C4_POLICY,
    C4_TRAIN_ROW_COUNT,
    C4ExactPosteriorResultV1,
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _c1(passed=True):
    return C1CalibrationResultV1(
        round_count=410,
        reference_mean_brier_ppb=100_000_000,
        candidate_mean_brier_ppb=90_000_000,
        mean_brier_improvement_ppb=10_000_000,
        relative_brier_improvement_ppb=100_000_000,
        bootstrap_lower_brier_improvement_ppb=(1 if passed else -1),
        member_mean_improvement_ppb=(1,) * 8,
        positive_member_count=8,
        mean_log_loss_improvement_nanonats=1,
        passed=passed,
        refusal_reasons=() if passed else (
            "paired-round-bootstrap-lower-bound-not-positive",),
    )


def _c2(passed=True):
    pooled = BehavioralStratumResultV1(
        stratum=POOLED_STRATUM,
        eligible_round_count=410,
        confirmed_receiver_decision_count=600,
        candidate_mean_brier_improvement_ppb=10,
        candidate_bootstrap_lower_improvement_ppb=(1 if passed else -1),
        history_ablated_mean_brier_improvement_ppb=0,
        history_retained_fraction_ppb=0,
        underpowered=False,
        candidate_lift_supported=passed,
        history_ablation_collapsed=passed,
    )
    return C2BehavioralResultV1(
        strata=(pooled,), pooled_behavioral_claim_passed=passed)


def _c3(model_sha):
    bin_row = ReliabilityBinV1(
        lower_probability_ppb=0, upper_probability_ppb=100_000_000,
        probability_cell_count=1, predicted_probability_sum_ppb=1,
        observed_probability_sum_ppb=0)
    stratum = ReliabilityStratumV1(
        name="all", decision_count=100, probability_cell_count=1000,
        brier_numerator=1, brier_denominator=1,
        ece_ppb=1, reliability_slope_numerator=1,
        reliability_slope_denominator=1,
        reliability_slope_defined=True, underpowered=False,
        bins=(bin_row,))
    linear = LinearExpectationReliabilityV1(
        metric="effective-suit-length", stratum="all",
        decision_count=100, receiver_metric_count=300,
        mean_signed_error_count_ppb=0,
        mean_absolute_error_count_ppb=1,
        squared_error_numerator=1, squared_error_denominator=1,
        reliability_slope_numerator=1,
        reliability_slope_denominator=1,
        reliability_slope_defined=True, underpowered=False)
    return CountReliabilityReportV1(
        split="test", model_schema=COHORT_SCHEMA, model_sha256=model_sha,
        behavior_policy_ids=("mc-s0-report-lcb",), decision_count=100,
        strata=(stratum,), linear_expectations=(linear,))


def _n2(passed=True):
    return N2PermutedLabelResultV1(
        round_count=410, mean_brier_improvement_ppb=0,
        bootstrap_lower_brier_improvement_ppb=(0 if passed else 1),
        unexpectedly_positive_lower_bound=not passed, passed=passed)


def _c4(passed=True):
    return C4ExactPosteriorResultV1(
        context_ids=C4_CONTEXT_IDS, known_policy=C4_POLICY,
        compatible_worlds_per_context=2, prior_weights=(1, 1),
        observed_action_likelihood_weights=(3, 1),
        posterior_world_weights=(3, 1), posterior_denominator=4,
        train_row_count=C4_TRAIN_ROW_COUNT, batch_size=16,
        batch_count=256, epoch_count=30, model_seed=C4_MODEL_SEED,
        model_state_sha256=_sha("c4-model"),
        training_receipts_sha256=_sha("c4-receipts"),
        candidate_ownership_sha256s=tuple(
            _sha(f"c4-candidate-{index}") for index in range(4)),
        probability_row_count=100, event_probability_count=300,
        max_event_probability_error_ppb=(10 if passed else 30_000_000),
        max_row_total_variation_ppb=(10 if passed else 30_000_000),
        mean_row_total_variation_ppb=1, passed=passed)


def _evidence():
    source = _sha("source")
    mechanics = B2MechanicsResultV1(
        prediction_count=100, conservation_rows_checked=100,
        hard_fact_rows_checked=100, public_twin_cases_checked=4,
        rotation_cases_checked=4, target_isolation_cases_checked=100,
        duplicate_decision_count=0, cross_split_round_count=0,
        source_manifest_sha256=source, conservation_passed=True,
        hard_facts_passed=True, public_twins_passed=True,
        rotation_passed=True, target_isolation_passed=True)
    resources = B2ResourceReceiptV1(
        source_manifest_sha256=source,
        runtime_profile_sha256=_sha("runtime"),
        capture_cpu_nanoseconds=1, capture_wall_nanoseconds=1,
        capture_artifact_bytes=1, training_device_nanoseconds=1,
        training_wall_nanoseconds=1, training_artifact_bytes=1,
        capture_retry_count=0, training_retry_count=0,
        test_split_open_count=1)
    candidate_models = tuple(_sha(f"candidate-model-{i}") for i in range(8))
    control_models = tuple(_sha(f"control-model-{i}") for i in range(8))
    c1, c2, n2, c4 = _c1(), _c2(), _n2(), _c4()
    c3 = _c3(ensemble_identity(candidate_models))
    inventory = B2ArtifactInventoryV1(
        source_manifest_sha256=source,
        population_sha256=_sha("population"),
        actor_corpus_manifest_sha256=_sha("actors"),
        privileged_target_manifest_sha256=_sha("targets"),
        split_seed_manifest_sha256=_sha("splits"),
        reference_world_manifest_sha256=_sha("reference"),
        training_curve_sha256=_sha("curves"),
        population_round_count=4096, population_decision_count=300_000,
        test_round_count=410,
        candidate_member_model_sha256s=candidate_models,
        candidate_checkpoint_sha256s=tuple(
            _sha(f"candidate-checkpoint-{i}") for i in range(8)),
        control_member_model_sha256s=control_models,
        control_checkpoint_sha256s=tuple(
            _sha(f"control-checkpoint-{i}") for i in range(8)),
        selected_epoch=12,
        mechanics_result_sha256=mechanics.sha256(),
        resource_receipt_sha256=resources.sha256(),
        c1_result_sha256=c1.sha256(), c2_result_sha256=c2.sha256(),
        c3_result_sha256=c3.sha256(), n2_result_sha256=n2.sha256(),
        c4_result_sha256=c4.sha256())
    return B2TerminalEvidenceV1(
        mechanics=mechanics, resources=resources, inventory=inventory,
        c1=c1, c2=c2, c3=c3, n2=n2, c4=c4,
        reference_replicates_stable=True)


def _rebind(evidence, **changes):
    changed = replace(evidence, **changes)
    inventory = replace(
        changed.inventory,
        source_manifest_sha256=changed.mechanics.source_manifest_sha256,
        mechanics_result_sha256=changed.mechanics.sha256(),
        resource_receipt_sha256=changed.resources.sha256(),
        c1_result_sha256=changed.c1.sha256(),
        c2_result_sha256=changed.c2.sha256(),
        c3_result_sha256=changed.c3.sha256(),
        n2_result_sha256=changed.n2.sha256(),
        c4_result_sha256=changed.c4.sha256())
    return replace(changed, inventory=inventory)


def test_all_gates_pass_only_to_b3_implementation_review():
    evidence = _evidence()
    result = evaluate_b2_terminal(evidence)
    assert result.decision == PASS
    validate_b2_terminal(evidence, result)
    payload = result.to_dict()
    assert payload["b3_sampler_implementation_review_may_be_requested"] \
        is True
    assert not any(payload[key] for key in (
        "b3_sampler_implementation_authorized", "sampler_run_authorized",
        "gameplay_authorized", "strength_claim_authorized",
        "promotion_authorized", "deployment_authorized"))


def test_terminal_precedence_and_named_nulls():
    base = _evidence()
    mechanics = replace(base.mechanics, public_twins_passed=False)
    assert evaluate_b2_terminal(_rebind(
        base, mechanics=mechanics)).decision == REFUSE_MECHANICS
    assert evaluate_b2_terminal(replace(
        base, reference_replicates_stable=False)).decision == REFUSE_MECHANICS
    assert evaluate_b2_terminal(_rebind(
        base, c4=_c4(False))).decision == REFUSE_MECHANICS

    resources = replace(
        base.resources,
        capture_cpu_nanoseconds=(CAPTURE_CORE_HOUR_CAP + 1) * NS_PER_HOUR)
    assert evaluate_b2_terminal(_rebind(
        base, resources=resources)).decision == REFUSE_INCOMPLETE
    assert evaluate_b2_terminal(_rebind(
        base, c1=_c1(False))).decision == NO_LIFT
    assert evaluate_b2_terminal(_rebind(
        base, c2=_c2(False))).decision == NO_BEHAVIOR
    assert evaluate_b2_terminal(_rebind(
        base, n2=_n2(False))).decision == NO_BEHAVIOR


def test_inventory_and_terminal_rehashes_cannot_bless_drift():
    evidence = _evidence()
    with pytest.raises(BeliefB2ResultError, match="inventory drift"):
        evaluate_b2_terminal(replace(
            evidence, inventory=replace(
                evidence.inventory,
                candidate_member_model_sha256s=(True,) * 8)))
    result = evaluate_b2_terminal(evidence)
    with pytest.raises(BeliefB2ResultError, match="derivation drift"):
        validate_b2_terminal(evidence, replace(
            result, mechanics_passed=False, decision=REFUSE_MECHANICS))
