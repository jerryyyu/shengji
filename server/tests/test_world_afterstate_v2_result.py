"""Focused tests for the pure Value-Afterstate V2 terminal boundary."""

from __future__ import annotations

import dataclasses
import hashlib
import math
from fractions import Fraction

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v2_diagnostics import (
    DELTA_MICROLEVELS, Z_ALPHA_PPM, Z_POWER_PPM,
    ModelSelectorPowerReceiptV2, OptimizerCanaryReceiptV2,
)
from shengji.rl.world_afterstate_v2_controls import (
    AUTHORITY as CONTROL_AUTHORITY, CONTROL_EVIDENCE_SCHEMA,
    MINIMUM_LABEL_EFFECTIVE_DOSE_PPM, MINIMUM_PERMUTATION_DOSE_PPM,
)
from shengji.rl.world_afterstate_v2_evaluation import (
    EvaluationMetricReceiptV2, EvaluationResultV2,
    evaluate_control_difference,
)
from shengji.rl.world_afterstate_v2_metrics import (
    deal_cluster_bootstrap_interval,
)
from shengji.rl.world_afterstate_v2_terminal_provenance import (
    COHORT_LABELS as PROVENANCE_COHORT_LABELS,
    COMPARISON_LABELS as PROVENANCE_COMPARISON_LABELS,
    DOSE_LABELS as PROVENANCE_DOSE_LABELS,
    UPSTREAM_RECEIPT_LABELS as PROVENANCE_UPSTREAM_LABELS,
    AuditProvenanceV2,
)
from shengji.rl.world_afterstate_v2_result import (
    ASSOCIATION_CONTROL, AUTHORITY, LABEL_CONTROL, WORLD_CONTROL,
    PASS_ABSOLUTE_VALUE_AND_ACTION_EDGE_TO_CONSUMER_DESIGN,
    PASS_ABSOLUTE_VALUE_LEARNING_ONLY, REFUSE_MECHANICS_OR_CONTROL,
    REFUSE_RESOURCE_INCOMPLETE, SELECT_NONE_NO_ABSOLUTE_VALUE,
    SELECT_NONE_NO_ACTION_SENSITIVITY, SELECT_NONE_NO_WORLD_SIGNAL,
    STOP_UNDERPOWERED, WorldAfterstateV2ResultError,
    WorldAfterstateV2TerminalEvidence, derive_terminal_result,
    validate_terminal_result,
)


def _sha(value):
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _mechanics_evidence(population, *, passed=True):
    match = _sha("mechanics-match")
    checks = [{"surface": surface,
               "case_sha256": _sha({"surface": surface, "index": 0,
                                     "observed": (match if passed or surface
                                                  != "transition"
                                                  else _sha("mismatch")),
                                     "expected": match}),
               "observed_sha256": (match if passed or surface != "transition"
                                    else _sha("mismatch")),
               "expected_sha256": match}
              for surface in sorted((
                  "transition", "continuation", "perspective", "symmetry"))]
    body = {"schema": "world-afterstate-v2-p0-mechanics-evidence-v1",
            "population_sha256": population, "checks": checks,
            "authority": {
                "dataset_opening_authorized": False,
                "audit_opening_authorized": False,
                "training_authorized": False,
                "gameplay_authorized": False,
                "strength_claim_authorized": False,
                "merge_authorized": False,
                "promotion_authorized": False,
                "deployment_authorized": False}}
    return {**body, "evidence_sha256": _sha(body)}


def _p0(**changes):
    population = _sha("p0")
    mechanics = _mechanics_evidence(
        population, passed=changes.get("mechanics_passed", True))
    body = {
        "schema": "world-afterstate-v2-p0-precision-label-v0",
        "population_sha256": population, "deal_count": 96,
        "state_count": 96, "raw_outcome_count": 96 * (2 + 1) * 8,
        "replica_count": 8, "candidate_pair_count": 96 * 2,
        "cell_counts": {"/".join((phase, position, role)): 8
                         for phase in ("early", "middle", "late")
                         for position in ("lead", "follow")
                         for role in ("attacker", "defender")},
        "directional_candidate_mean_microlevels": {"0-to-1": 1_000_000, "1-to-0": 1_000_000},
        "combined_candidate_mean_microlevels": {"mean": 1_000_000, "bootstrap_lower": 1_000_000},
        "sibling_same_nonzero_sign_ppm": 100_000,
        "sibling_advantage_correlation_ppm": 1,
        "sibling_advantage_correlation_bootstrap_lower_ppm": 1,
        "chosen_minus_incumbent_microlevels": {"0-to-1": 1_000_000, "1-to-0": 1_000_000},
        "gate_fractions": {
            "direction_0_to_1": {"numerator": 1, "denominator": 1},
            "direction_1_to_0": {"numerator": 1, "denominator": 1},
            "combined_mean": {"numerator": 1, "denominator": 1},
            "combined_bootstrap_lower": {"numerator": 1, "denominator": 1},
            "chosen_minus_incumbent_mean": {"numerator": 1, "denominator": 1},
        },
        "bootstrap_replicates": 100, "r2": {
            "action_agreement_ppm": 1, "return_mean_error_microlevels": 1,
            "intraclass_correlation_ppm": 1},
        "r4": {"action_agreement_ppm": 1, "return_mean_error_microlevels": 1,
               "intraclass_correlation_ppm": 1},
        "r8": {"action_agreement_ppm": 1, "return_mean_error_microlevels": 1,
               "intraclass_correlation_ppm": 1},
        "combined_chosen_minus_incumbent_microlevels": 1_000_000,
        "incumbent_relative_bessel_s_microlevels": 0,
        "mechanics_evidence": mechanics,
        "mechanics_evidence_sha256": mechanics["evidence_sha256"],
        "mechanics_passed": True, "statistical_gates_passed": True,
        "worthwhile_floor_passed": True, "decision": "PASS_P0_PRECISION",
        "authority": {
            "dataset_opening_authorized": False, "audit_opening_authorized": False,
            "training_authorized": False, "gameplay_authorized": False,
            "strength_claim_authorized": False, "merge_authorized": False,
            "promotion_authorized": False, "deployment_authorized": False,
        },
    }
    body.update(changes)
    return {**body, "result_sha256": _sha(body)}


def _canary(*, passed=True):
    return OptimizerCanaryReceiptV2(
        source_p0_population_sha256=_sha("p0"),
        root_population_sha256=_sha("p0"), model_seed=1, root_count=16,
        optimizer_steps=500, early_stopping_used=not passed,
        gradients_finite=passed, weights_finite=passed,
        initial_loss_nano=1_000, empirical_loss_nano=100,
        final_loss_nano=280 if passed else 900,
        normalized_progress_ppm=800_000 if passed else 111_111, passed=passed)


DEAL = _sha("deal-0")


def _metric(name, value, population, deal=DEAL):
    interval = deal_cluster_bootstrap_interval(
        ((deal, value),), population_sha256=population, metric_name=name)
    return EvaluationMetricReceiptV2(
        metric_name=name, mean=value, bootstrap=interval)


def _members(value):
    return ((value, value, value, -1) if value > 0
            else (value, value, value, value))


def _evaluation(*, control="natural", block=1, population=None,
                rps=10, absolute=10, paired=10, action=200_000,
                dose=100_000):
    population = population or _sha("audit")
    prefix = f"{control}|block-{block}"
    member_rps = _members(rps)
    member_absolute = _members(absolute)
    member_paired = _members(paired)
    member_action = _members(action)
    return EvaluationResultV2(
        population_sha256=population, seed_block=block,
        control_name=control,
        rps_improvement=_metric(f"{prefix}|rps-improvement", rps, population),
        absolute_error_improvement=_metric(
            f"{prefix}|absolute-error-improvement", absolute, population),
        paired_error_improvement=_metric(
            f"{prefix}|paired-error-improvement", paired, population),
        selected_action_utility=_metric(
            f"{prefix}|action-utility", action, population),
        cvar10_selected_utility=_metric(
            f"{prefix}|cvar10-selected-utility", action, population),
        member_rps_improvement=member_rps,
        member_absolute_error_improvement=member_absolute,
        member_paired_error_improvement=member_paired,
        member_action_utility=member_action,
        positive_rps_member_count=sum(value > 0 for value in member_rps),
        positive_absolute_error_member_count=sum(
            value > 0 for value in member_absolute),
        positive_paired_error_member_count=sum(
            value > 0 for value in member_paired),
        positive_action_utility_member_count=sum(
            value > 0 for value in member_action),
        nonincumbent_dose_ppm=dose,
        learning_gates_1_to_4=(rps > 0, absolute > 0, paired > 0,
                               sum(value > 0 for value in member_rps) >= 3),
        deal_rps_improvement=((DEAL, rps),),
        deal_absolute_error_improvement=((DEAL, absolute),),
        deal_paired_error_improvement=((DEAL, paired),),
        deal_action_utility=((DEAL, action),))


def _power(population, *, frozen_audit_deal_count=64):
    utilities = (0, 100_000, 200_000, 300_000)
    mean = Fraction(sum(utilities), len(utilities))
    variance = sum((Fraction(value) - mean) ** 2 for value in utilities) \
        / (len(utilities) - 1)
    z_sum = Z_ALPHA_PPM + Z_POWER_PPM
    required_fraction = Fraction(z_sum * z_sum, 1_000_000**2) \
        * variance / (DELTA_MICROLEVELS**2)
    required = (required_fraction.numerator + required_fraction.denominator - 1) \
        // required_fraction.denominator
    return ModelSelectorPowerReceiptV2(
        precision_select_population_sha256=population,
        deal_utilities_microlevels=utilities,
        precision_select_deal_count=len(utilities),
        frozen_audit_deal_count=frozen_audit_deal_count,
        s_model_microlevels=math.sqrt(float(variance)), n_required=required,
        stop_underpowered=required > frozen_audit_deal_count)


def _dose(name):
    minimum_effective = (MINIMUM_LABEL_EFFECTIVE_DOSE_PPM
                         if name == LABEL_CONTROL
                         else MINIMUM_PERMUTATION_DOSE_PPM)
    body = {
        "schema": CONTROL_EVIDENCE_SCHEMA, "control_name": name,
        "name": name, "seed": 1, "row_count": 10,
        "eligible_row_count": 10, "eligible_cell_count": 10,
        "changed_row_count": 10, "changed_cell_count": 10,
        "changed_count": 10, "row_dose_ppm": 1_000_000,
        "cell_dose_ppm": 1_000_000, "dose_ppm": 1_000_000,
        "effective_changed_count": 10, "effective_dose_ppm": 1_000_000,
        "required_minimum_dose_ppm": MINIMUM_PERMUTATION_DOSE_PPM,
        "required_minimum_effective_dose_ppm": minimum_effective,
        "root_count": 1, "source_population_sha256": _sha(f"{name}-source"),
        "input_population_sha256": _sha(f"{name}-source"),
        "output_population_sha256": _sha(f"{name}-output"),
        "authority": dict(CONTROL_AUTHORITY),
    }
    return {**body, "evidence_sha256": _sha(body)}


def _complete_evidence(*, natural1=None, natural2=None,
                       association=None, label=None, world1=None, world2=None,
                       audit_opened_count=1, mechanics_failure=False,
                       mechanics_stage=None, resource_incomplete=False,
                       resource_stage=None):
    audit_population = _sha("audit")
    select_population = _sha("select")
    natural1 = natural1 or _evaluation(population=audit_population, block=1)
    natural2 = natural2 or _evaluation(population=audit_population, block=2)
    association = association or _evaluation(
        control=ASSOCIATION_CONTROL, block=1, population=audit_population,
        rps=-10, absolute=-10, paired=-10, action=-10)
    label = label or _evaluation(
        control=LABEL_CONTROL, block=1, population=audit_population,
        rps=-10, absolute=-10, paired=-10, action=-10)
    world1 = world1 or _evaluation(
        control=WORLD_CONTROL, block=1, population=audit_population,
        rps=1, absolute=1, paired=1, action=1)
    world2 = world2 or _evaluation(
        control=WORLD_CONTROL, block=2, population=audit_population,
        rps=1, absolute=1, paired=1, action=1)
    controls = {
        ASSOCIATION_CONTROL: {1: association},
        LABEL_CONTROL: {1: label},
        WORLD_CONTROL: {1: world1, 2: world2},
    }
    comparisons = tuple(
        evaluate_control_difference(natural, controls[name][block])
        for name, block, natural in (
            (ASSOCIATION_CONTROL, 1, natural1),
            (LABEL_CONTROL, 1, natural1),
            (WORLD_CONTROL, 1, natural1),
            (WORLD_CONTROL, 2, natural2)))
    precision = _evaluation(population=select_population, block=1)
    p0 = _p0()
    canary = _canary()
    power = _power(select_population)
    doses = {name: _dose(name) for name in (
        ASSOCIATION_CONTROL, LABEL_CONTROL, WORLD_CONTROL)}
    evaluations = {
        "natural:block-1": natural1,
        "action-association-permutation:block-1": association,
        "label-permutation:block-1": label,
        "complete-world-shuffle:block-1": world1,
        "natural:block-2": natural2,
        "complete-world-shuffle:block-2": world2,
    }
    comparison_values = dict(zip(PROVENANCE_COMPARISON_LABELS,
                                 comparisons, strict=True))
    provenance = None
    if audit_opened_count == 1:
        provenance = AuditProvenanceV2(
            freeze_sha256=_sha("freeze"), admission_sha256=_sha("admission"),
            audit_attempt_sha256=_sha("attempt"),
            audit_opened_count=audit_opened_count,
            continuation_manifest_sha256=_sha("continuations"),
            prediction_manifest_sha256s=tuple(
                (name, _sha(f"prediction:{name}"))
                for name in PROVENANCE_COHORT_LABELS),
            checkpoint_manifest_sha256s=tuple(
                (name, _sha(f"checkpoint:{name}"))
                for name in PROVENANCE_COHORT_LABELS),
            cohort_manifest_sha256s=tuple(
                (name, _sha(f"cohort:{name}"))
                for name in PROVENANCE_COHORT_LABELS),
            evaluation_result_sha256s=tuple(
                (name, evaluations[name].sha256())
                for name in PROVENANCE_COHORT_LABELS),
            upstream_receipt_sha256s=tuple((name, {
                "p0": p0["result_sha256"],
                "optimizer_canary": canary.sha256(),
                "precision_select": precision.sha256(),
                "model_selector_power": power.sha256(),
            }[name]) for name in PROVENANCE_UPSTREAM_LABELS),
            comparison_sha256s=tuple(
                (name, comparison_values[name].sha256())
                for name in PROVENANCE_COMPARISON_LABELS),
            dose_sha256s=tuple((name, _sha({
                "association": doses[ASSOCIATION_CONTROL],
                "label": doses[LABEL_CONTROL],
                "world": doses[WORLD_CONTROL],
            }[name])) for name in PROVENANCE_DOSE_LABELS),
        )
    return WorldAfterstateV2TerminalEvidence(
        p0_report=p0, optimizer_canary=canary,
        precision_select_result=precision,
        model_selector_power=power,
        audit_natural_results={1: natural1, 2: natural2},
        audit_control_results=controls,
        control_comparisons=comparisons,
        control_dose_evidence=doses, audit_provenance=provenance,
        audit_opened_count=audit_opened_count,
        mechanics_failure=mechanics_failure,
        mechanics_stage=mechanics_stage,
        resource_incomplete=resource_incomplete,
        resource_stage=resource_stage)


def test_p0_missing_is_resource_stop_and_has_no_authority():
    result = derive_terminal_result(WorldAfterstateV2TerminalEvidence())
    assert result.decision == "REFUSE_RESOURCE_INCOMPLETE"
    assert result.stage_reached == "p0"
    assert result.audit_opened_count == 0
    assert dict(result.authority) == AUTHORITY
    validate_terminal_result(WorldAfterstateV2TerminalEvidence(), result)


def test_early_p0_stop_rejects_downstream_artifacts():
    report = _p0(mechanics_passed=False,
                 worthwhile_floor_passed=False,
                 decision="REFUSE_MECHANICS_OR_CONTROL",
                 gate_fractions={
                     **_p0()["gate_fractions"],
                     "chosen_minus_incumbent_mean": {"numerator": 0, "denominator": 1}},
                 chosen_minus_incumbent_microlevels={"0-to-1": 0, "1-to-0": 0},
                 combined_chosen_minus_incumbent_microlevels=0)
    evidence = WorldAfterstateV2TerminalEvidence(p0_report=report,
                                                  optimizer_canary=_canary())
    with pytest.raises(WorldAfterstateV2ResultError, match="downstream"):
        derive_terminal_result(evidence)


@pytest.mark.parametrize("passed, decision", [
    (False, "REFUSE_TRAINING_RECIPE"),
    (True, "REFUSE_RESOURCE_INCOMPLETE"),
])
def test_canary_route_and_later_absence_are_stage_aware(passed, decision):
    result = derive_terminal_result(WorldAfterstateV2TerminalEvidence(
        p0_report=_p0(), optimizer_canary=_canary(passed=passed)))
    assert result.decision == decision
    assert result.stage_reached == ("training" if not passed else "precision-select")


def test_result_revalidation_rederives_hash_and_route():
    evidence = WorldAfterstateV2TerminalEvidence(p0_report=_p0())
    result = derive_terminal_result(evidence)
    forged = dataclasses.replace(result, decision="PASS_ABSOLUTE_VALUE_LEARNING_ONLY")
    with pytest.raises(WorldAfterstateV2ResultError):
        validate_terminal_result(evidence, forged)


def test_complete_audit_reaches_strong_pass_and_reconstructs_every_control():
    evidence = _complete_evidence()
    result = derive_terminal_result(evidence)
    assert result.decision == \
        PASS_ABSOLUTE_VALUE_AND_ACTION_EDGE_TO_CONSUMER_DESIGN
    assert result.stage_reached == "audit"
    assert result.audit_opened_count == 1
    assert len(result.input_receipt_hashes) == 19
    assert ("audit_provenance", evidence.audit_provenance.sha256()) in \
        result.input_receipt_hashes
    validate_terminal_result(evidence, result)


def test_complete_audit_requires_typed_provenance_receipt():
    evidence = dataclasses.replace(_complete_evidence(), audit_provenance=None)
    assert derive_terminal_result(evidence).decision == REFUSE_RESOURCE_INCOMPLETE


@pytest.mark.parametrize("field", (
    "upstream_receipt_sha256s", "evaluation_result_sha256s",
    "comparison_sha256s", "dose_sha256s",
))
def test_terminal_crossbinds_every_visible_provenance_population(field):
    evidence = _complete_evidence()
    rows = list(getattr(evidence.audit_provenance, field))
    rows[0] = (rows[0][0], _sha(f"foreign:{field}"))
    forged_provenance = dataclasses.replace(
        evidence.audit_provenance, **{field: tuple(rows)})
    forged = dataclasses.replace(evidence, audit_provenance=forged_provenance)
    assert derive_terminal_result(forged).decision == REFUSE_MECHANICS_OR_CONTROL


def test_world_signal_precedes_action_usefulness_in_frozen_route_order():
    population = _sha("audit")
    natural1 = _evaluation(
        population=population, block=1, action=0, dose=0)
    # Matching world control makes the natural-minus-world signal exactly
    # zero.  Action usefulness also fails; route 11 must win over route 12.
    world1 = _evaluation(
        control=WORLD_CONTROL, population=population, block=1,
        rps=10, absolute=10, paired=10, action=0, dose=0)
    evidence = _complete_evidence(natural1=natural1, world1=world1)
    assert derive_terminal_result(evidence).decision == SELECT_NONE_NO_WORLD_SIGNAL


def test_action_usefulness_can_fail_after_world_signal_passes():
    population = _sha("audit")
    natural1 = _evaluation(
        population=population, block=1, action=0, dose=0)
    evidence = _complete_evidence(natural1=natural1)
    assert derive_terminal_result(evidence).decision == \
        PASS_ABSOLUTE_VALUE_LEARNING_ONLY


def test_world_shuffled_action_utility_is_a_required_usefulness_gate():
    population = _sha("audit")
    world1 = _evaluation(
        control=WORLD_CONTROL, population=population, block=1,
        rps=1, absolute=1, paired=1, action=200_000)
    evidence = _complete_evidence(world1=world1)
    assert derive_terminal_result(evidence).decision == \
        PASS_ABSOLUTE_VALUE_LEARNING_ONLY


@pytest.mark.parametrize("changes, expected", [
    ({"rps": 0}, SELECT_NONE_NO_ABSOLUTE_VALUE),
    ({"paired": 0}, SELECT_NONE_NO_ACTION_SENSITIVITY),
])
def test_primary_audit_routes_are_first_match_witnessed(changes, expected):
    population = _sha("audit")
    natural1 = _evaluation(population=population, block=1, **changes)
    assert derive_terminal_result(
        _complete_evidence(natural1=natural1)).decision == expected


def test_association_or_label_learning_is_a_mechanics_refusal():
    population = _sha("audit")
    learned_control = _evaluation(
        control=ASSOCIATION_CONTROL, population=population, block=1,
        rps=1, absolute=1, paired=1, action=1)
    result = derive_terminal_result(
        _complete_evidence(association=learned_control))
    assert result.decision == REFUSE_MECHANICS_OR_CONTROL


def test_resource_precedes_mechanics_at_the_same_reached_stage():
    evidence = _complete_evidence(
        resource_incomplete=True, resource_stage="audit",
        mechanics_failure=True, mechanics_stage="audit")
    assert derive_terminal_result(evidence).decision == REFUSE_RESOURCE_INCOMPLETE
    with pytest.raises(WorldAfterstateV2ResultError,
                       match="resource failure/stage"):
        derive_terminal_result(WorldAfterstateV2TerminalEvidence(
            resource_stage="audit"))


def test_audit_count_and_downstream_opening_are_not_asserted_constants():
    evidence = _complete_evidence(audit_opened_count=2)
    assert derive_terminal_result(evidence).decision == REFUSE_MECHANICS_OR_CONTROL
    early = dataclasses.replace(
        _complete_evidence(), audit_opened_count=0)
    assert derive_terminal_result(early).decision == REFUSE_MECHANICS_OR_CONTROL


def test_underpowered_precision_stop_refuses_any_audit_artifacts():
    evidence = _complete_evidence()
    underpowered = dataclasses.replace(
        evidence.model_selector_power,
        frozen_audit_deal_count=2,
        stop_underpowered=evidence.model_selector_power.n_required > 2)
    evidence = dataclasses.replace(evidence, model_selector_power=underpowered)
    assert underpowered.stop_underpowered
    with pytest.raises(WorldAfterstateV2ResultError, match="downstream"):
        derive_terminal_result(evidence)


def test_control_block_population_is_exact_not_superset_tolerant():
    evidence = _complete_evidence()
    extra = _evaluation(
        control=ASSOCIATION_CONTROL, population=_sha("audit"), block=2,
        rps=-10, absolute=-10, paired=-10, action=-10)
    controls = dict(evidence.audit_control_results)
    controls[ASSOCIATION_CONTROL] = {
        **controls[ASSOCIATION_CONTROL], 2: extra}
    evidence = dataclasses.replace(evidence, audit_control_results=controls)
    assert derive_terminal_result(evidence).decision == REFUSE_RESOURCE_INCOMPLETE


def test_canary_binds_source_p0_population_not_canary_subset_population():
    canary = dataclasses.replace(
        _canary(), source_p0_population_sha256=_sha("wrong-p0"))
    with pytest.raises(WorldAfterstateV2ResultError, match="canary/P0"):
        derive_terminal_result(WorldAfterstateV2TerminalEvidence(
            p0_report=_p0(), optimizer_canary=canary))


def test_coordinated_control_comparison_rehash_cannot_change_the_route():
    evidence = _complete_evidence()
    comparisons = list(evidence.control_comparisons)
    comparisons[-1] = dataclasses.replace(
        comparisons[-1], positive_rps_member_count=0,
        positive_paired_member_count=0)
    forged = dataclasses.replace(evidence, control_comparisons=tuple(comparisons))
    assert derive_terminal_result(forged).decision == REFUSE_MECHANICS_OR_CONTROL
