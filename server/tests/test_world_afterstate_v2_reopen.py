from __future__ import annotations

import pytest

from shengji.rl.world_afterstate_v2_reopen import (
    WorldAfterstateV2ReopenError, reopen_evaluation_result_v2,
    reopen_jeffreys_prior_v2, reopen_model_selector_power_v2,
    reopen_optimizer_canary_v2, reopen_absolute_curve_score_v2)
from test_world_afterstate_v2_evaluation import _manifest, _population
from test_world_afterstate_v2_result import _canary, _evaluation, _power


def test_typed_receipts_round_trip_exactly():
    predictions_a, outcomes_a, prior, root_a = _population()
    predictions_b, outcomes_b, _prior_b, root_b = _population(root="reopen-b")
    evaluation = _evaluation()
    canary = _canary()
    power = _power(evaluation.population_sha256)
    assert reopen_optimizer_canary_v2(canary.payload()) == canary
    assert reopen_model_selector_power_v2(power.payload()) == power
    assert reopen_jeffreys_prior_v2(prior.payload()) == prior
    assert reopen_evaluation_result_v2(evaluation.payload()) == evaluation
    from shengji.rl.world_afterstate_v2_evaluation import evaluate_absolute_curve_v2
    absolute = evaluate_absolute_curve_v2(
        _manifest((root_a, root_b), predictions_a + predictions_b),
        outcomes_a + outcomes_b, prior)
    assert reopen_absolute_curve_score_v2(absolute.payload()) == absolute


@pytest.mark.parametrize(("reopener", "payload", "field"), (
    (reopen_optimizer_canary_v2, _canary().payload(), "unknown"),
    (reopen_model_selector_power_v2,
     _power(_evaluation().population_sha256).payload(), "unknown"),
    (reopen_evaluation_result_v2, _evaluation().payload(), "unknown"),
))
def test_extra_fields_and_rehashed_payloads_are_refused(reopener, payload, field):
    forged = {**payload, field: True}
    with pytest.raises(WorldAfterstateV2ReopenError, match="field population"):
        reopener(forged)


def test_nested_evaluation_mutation_is_rederived():
    payload = _evaluation().payload()
    forged = {**payload, "rps_improvement": {
        **payload["rps_improvement"], "mean": payload["rps_improvement"]["mean"] + 1}}
    with pytest.raises(WorldAfterstateV2ReopenError,
                       match="reconstruction refused"):
        reopen_evaluation_result_v2(forged)


def test_json_lists_are_required_not_permissive_python_tuples():
    payload = _power(_evaluation().population_sha256).payload()
    forged = {**payload,
              "deal_utilities_microlevels": tuple(
                  payload["deal_utilities_microlevels"])}
    with pytest.raises(WorldAfterstateV2ReopenError,
                       match="field population"):
        reopen_model_selector_power_v2(forged)


def test_canary_empirical_evidence_fields_are_required_on_reopen():
    payload = _canary().payload()
    for field in ("empirical_entropy_nano", "empirical_paired_residual_nano"):
        forged = dict(payload)
        del forged[field]
        with pytest.raises(WorldAfterstateV2ReopenError, match="field population"):
            reopen_optimizer_canary_v2(forged)
