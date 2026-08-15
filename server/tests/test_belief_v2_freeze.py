"""Exact packet-shape and causal-attribution tests for the V2 freeze."""

from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.belief_v2_freeze import (
    BeliefV2FreezeError,
    V2CohortPlanV1,
    V2ExecutionFreezeV1,
    V2ResourceCapsV1,
    execution_freeze_from_bytes,
    expected_execution_review_claim,
    validate_execution_freeze,
)


def _sha(char: str) -> str:
    return char * 64


def _cohorts():
    primary = V2CohortPlanV1(
        cohort_id="synthetic-primary", kind="synthetic-primary",
        optimizer_decisions_per_epoch=1000,
        synthetic_decisions_per_epoch=1000, human_decisions_per_epoch=0,
        synthetic_decision_manifest_sha256=_sha("1"),
        human_decision_manifest_sha256=None, comparator_cohort_id=None)
    return (
        primary,
        V2CohortPlanV1(
            cohort_id="hard-geometry-label-permutation",
            kind="hard-geometry-label-permutation",
            optimizer_decisions_per_epoch=1000,
            synthetic_decisions_per_epoch=1000,
            human_decisions_per_epoch=0,
            synthetic_decision_manifest_sha256=_sha("1"),
            human_decision_manifest_sha256=None,
            comparator_cohort_id="synthetic-primary"),
        V2CohortPlanV1(
            cohort_id="human-mixture", kind="human-mixture",
            optimizer_decisions_per_epoch=1000,
            synthetic_decisions_per_epoch=800, human_decisions_per_epoch=200,
            synthetic_decision_manifest_sha256=_sha("2"),
            human_decision_manifest_sha256=_sha("3"),
            comparator_cohort_id="synthetic-primary"),
        V2CohortPlanV1(
            cohort_id="synthetic-scale-50", kind="synthetic-scale",
            optimizer_decisions_per_epoch=500,
            synthetic_decisions_per_epoch=500, human_decisions_per_epoch=0,
            synthetic_decision_manifest_sha256=_sha("4"),
            human_decision_manifest_sha256=None,
            comparator_cohort_id="synthetic-primary"),
    )


def _freeze():
    return V2ExecutionFreezeV1(
        execution_git="a" * 40,
        source_manifest_sha256=_sha("a"),
        source_review_commit="b" * 40,
        v1_terminal_route="v1-pass-to-b3",
        v1_terminal_result_sha256=_sha("b"),
        v1_resource_receipt_sha256=_sha("c"),
        v2_reentry_rationale_sha256=None,
        h0_inventory_sha256=_sha("d"),
        h0_source_manifest_sha256=_sha("e"),
        h0_source_digest_population_sha256=_sha("f"),
        human_group_split_sha256=_sha("0"),
        human_group_count=30, human_train_group_count=24,
        human_calibration_group_count=3, human_test_group_count=3,
        human_complete_round_count=122,
        human_eligible_decision_count=2830,
        preflight_result_sha256=_sha("1"),
        preflight_runtime_sha256=_sha("2"),
        seed_registry_sha256=_sha("3"),
        seed_candidate_report_sha256=_sha("4"),
        cohorts=_cohorts(),
        resource_caps=V2ResourceCapsV1(
            capture_core_hours=64, capture_wall_seconds=14_400,
            capture_bytes=16 * 1024**3,
            reference_core_hours=16, reference_wall_seconds=7_200,
            reference_bytes=16 * 1024**3,
            training_device_hours=128, training_wall_seconds=86_400,
            training_bytes=32 * 1024**3),
        evidence_root="/tmp/belief-v2-evidence")


def test_freeze_round_trips_and_review_claim_is_bounded():
    freeze = _freeze()
    validate_execution_freeze(freeze)
    reopened = execution_freeze_from_bytes(freeze.canonical_bytes())
    assert reopened == freeze
    claim = expected_execution_review_claim(freeze)
    assert claim["bounded_capture_reference_training_and_one_test_open_authorized"] is True
    assert claim["retry_authorized"] is False
    assert claim["gameplay_strength_screen_authorized"] is False
    assert claim["deployment_authorized"] is False


@pytest.mark.parametrize(("mutation", "message"), [
    (lambda freeze: replace(
        freeze, cohorts=tuple(row for row in freeze.cohorts
                              if row.kind != "synthetic-scale")),
     "cohort kind population"),
    (lambda freeze: replace(
        freeze, cohorts=tuple(
            replace(row, optimizer_decisions_per_epoch=1100,
                    synthetic_decisions_per_epoch=900)
            if row.kind == "human-mixture" else row
            for row in freeze.cohorts)), "comparison/work binding"),
    (lambda freeze: replace(
        freeze, cohorts=tuple(
            replace(row, human_decisions_per_epoch=201,
                    synthetic_decisions_per_epoch=799)
            if row.kind == "human-mixture" else row
            for row in freeze.cohorts)), "human mixture fraction"),
    (lambda freeze: replace(
        freeze, v1_terminal_route=(
            "v1-select-none-with-named-domain-shift-reentry")),
     "lacks named reentry"),
    (lambda freeze: replace(freeze, human_test_group_count=2),
     "identity drift"),
])
def test_freeze_refuses_named_scientific_and_population_mutations(
        mutation, message):
    with pytest.raises(BeliefV2FreezeError, match=message):
        validate_execution_freeze(mutation(_freeze()))


def test_canonical_reopen_refuses_gate_or_authority_rewrite():
    payload = _freeze().to_dict()
    payload["gates"]["rank_material_regression_tolerance_ppb"] = 6_000_000
    with pytest.raises(BeliefV2FreezeError, match="reconstruction"):
        execution_freeze_from_bytes(canonical_json_bytes(payload))

    payload = _freeze().to_dict()
    payload["authority"]["gameplay_strength_screen_authorized"] = True
    with pytest.raises(BeliefV2FreezeError, match="reconstruction"):
        execution_freeze_from_bytes(canonical_json_bytes(payload))


def test_select_none_requires_and_preserves_named_reentry_evidence():
    freeze = replace(
        _freeze(),
        v1_terminal_route="v1-select-none-with-named-domain-shift-reentry",
        v2_reentry_rationale_sha256=_sha("5"))
    validate_execution_freeze(freeze)
    assert execution_freeze_from_bytes(freeze.canonical_bytes()) == freeze

