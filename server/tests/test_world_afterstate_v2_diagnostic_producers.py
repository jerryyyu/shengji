from __future__ import annotations

import hashlib
import dataclasses
import math

import pytest

from shengji.rl.world_afterstate_v2_diagnostic_producers import (
    DiagnosticProducerDependencyBlocked, NestedCurveInputV2, _empirical_floor,
    OptimizerCanaryInputV2,
    produce_model_selector_power_v2, produce_nested_curve_v2,
    produce_optimizer_canary_v2, produce_primary_stability_v2,
)
from shengji.rl.world_afterstate_v2_training_controller import CohortTrainingBuildV2
from shengji.rl.world_afterstate_v2_evaluation import (
    evaluate_absolute_curve_v2, evaluate_v2,
)
from test_world_afterstate_v2_evaluation import _manifest, _population
from test_world_afterstate_v2_result import _evaluation
from test_world_afterstate_v2_training_controller import _build
from test_world_afterstate_v2_training import _rows


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def test_model_selector_power_is_rederived_from_sealed_deal_utilities():
    predictions_a, outcomes_a, prior, root_a = _population(root="power-a")
    predictions_b, outcomes_b, _prior, root_b = _population(
        root="power-b", predicted_categories=(100, 100))
    value = evaluate_v2(
        _manifest((root_a, root_b), predictions_a + predictions_b),
        outcomes_a + outcomes_b, prior)
    receipt = produce_model_selector_power_v2(value, frozen_audit_deal_count=64)
    receipt.validate()
    assert receipt.precision_select_population_sha256 == value.population_sha256
    assert len(receipt.deal_utilities_microlevels) == 2


def test_absolute_curve_score_is_not_an_improvement_metric():
    predictions, outcomes, prior, root = _population(root="absolute-a")
    predictions_b, outcomes_b, _prior, root_b = _population(root="absolute-b")
    score = evaluate_absolute_curve_v2(
        _manifest((root, root_b), predictions + predictions_b),
        outcomes + outcomes_b, prior)
    score.validate()
    assert score.rps_nano >= 0
    assert score.paired_target_error_nano >= 0


def test_absolute_curve_source_binding_changes_with_sealed_outcome_mutation():
    predictions, outcomes, prior, root = _population(root="absolute-binding")
    predictions_b, outcomes_b, _prior_b, root_b = _population(root="absolute-binding-b")
    score = evaluate_absolute_curve_v2(
        _manifest((root, root_b), predictions + predictions_b),
        outcomes + outcomes_b, prior)
    mutated = list(outcomes + outcomes_b)
    mutated[0] = dataclasses.replace(
        mutated[0], signed_level_category=(mutated[0].signed_level_category + 1) % 204)
    changed = evaluate_absolute_curve_v2(
        _manifest((root, root_b), predictions + predictions_b), mutated, prior)
    assert score.source_binding_sha256 != changed.source_binding_sha256


def test_model_selector_power_wrong_binding_refuses():
    value = _evaluation(control="complete-world-shuffle", population=_sha("p"))
    with pytest.raises(DiagnosticProducerDependencyBlocked, match="identity"):
        produce_model_selector_power_v2(value, frozen_audit_deal_count=64)


def test_nested_curve_rederives_slopes_and_checkpoint_bindings(monkeypatch):
    builds = []
    for index in range(3):
        builds.append(CohortTrainingBuildV2({"id": index}, ()))
    digests = [_sha(f"checkpoint-{index}") for index in range(3)]
    monkeypatch.setattr(
        "shengji.rl.world_afterstate_v2_diagnostic_producers.reopen_cohort_build",
        lambda build: ((), {"members": [{
            "selected_checkpoint_external_sha256": digests[builds.index(build)]
        }]}))
    inputs = tuple(NestedCurveInputV2(
        independent_deal_count=count,
        fit=_evaluation(population=_sha(f"fit-{count}"), action=100_000),
        select=_evaluation(population=_sha(f"select-{count}"), action=90_000),
        checkpoint_build=builds[index],
        ensemble_member_eligible=(count == 100))
        for index, count in enumerate((25, 50, 100)))
    with pytest.raises(DiagnosticProducerDependencyBlocked, match="absolute"):
        produce_nested_curve_v2(
            inputs, full_fit_population_sha256=_sha("fit-100"),
            primary_member0_checkpoint_sha256=digests[2])


def test_canary_and_stability_do_not_relabel_epoch_receipts():
    for producer, marker, value in ((produce_optimizer_canary_v2, "population", object()),
                                    (produce_primary_stability_v2, "cohort build", object())):
        with pytest.raises(DiagnosticProducerDependencyBlocked, match=marker):
            producer(value)


def test_canary_requires_complete_typed_p0_material_population():
    with pytest.raises(DiagnosticProducerDependencyBlocked, match="complete D256"):
        produce_optimizer_canary_v2(OptimizerCanaryInputV2((), ()))


def test_canary_empirical_floor_is_root_and_candidate_balanced():
    rows = tuple(row for index in range(16) for row in _rows(f"floor-{index}"))
    entropy, paired = _empirical_floor(rows)
    assert entropy == round(math.log(8) / math.log(204) * 1_000_000_000)
    assert paired == 0


def test_primary_stability_uses_actual_epoch_telemetry():
    receipt = produce_primary_stability_v2(_build())
    receipt.validate()
    assert all(row.gradient_norm_nano > 0
               for member in receipt.members for row in member)
    assert all(row.update_norm_nano > 0
               for member in receipt.members for row in member)


def test_primary_stability_rejects_rehashed_epoch_telemetry_mutation():
    build = _build()
    forged = dict(build.manifest)
    forged["members"] = [dict(row) for row in forged["members"]]
    forged["members"][0]["epoch_receipts"] = [
        dict(item) for item in forged["members"][0]["epoch_receipts"]]
    forged["members"][0]["epoch_receipts"][0]["gradient_norm_nano"] += 1
    with pytest.raises(DiagnosticProducerDependencyBlocked, match="reopened"):
        produce_primary_stability_v2(dataclasses.replace(build, manifest=forged))
