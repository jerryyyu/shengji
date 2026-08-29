from __future__ import annotations

import copy

import pytest

from shengji.rl.world_afterstate_v1 import (
    build_advantage_pairs, evaluate_label_ceiling)
from shengji.rl.world_afterstate_v1_evaluation import (
    evaluate_advantage_audit, evaluate_world_shuffle_delta)
from shengji.rl.world_afterstate_v1_result import (
    CONTROL_NAMES, WorldAfterstateV1ResultError, derive_terminal_result,
    validate_terminal_result)

from test_world_afterstate_v1 import _population
from test_world_afterstate_v1_evaluation import _calibration, _predictions


def _p0(*, passed=True):
    return evaluate_label_ceiling(
        build_advantage_pairs(_population(contradictory=not passed)),
        bootstrap_replicates=200)


def _components(*, natural_pass=True, control_pass=False, world_pass=True):
    joined = _calibration()
    positive = _predictions(joined)
    zero = _predictions(joined, positive=False)
    natural = evaluate_advantage_audit(
        joined, positive if natural_pass else zero,
        bootstrap_replicates=10_000)
    control = evaluate_advantage_audit(
        joined, positive if control_pass else zero,
        bootstrap_replicates=10_000)
    controls = {name: copy.deepcopy(control) for name in CONTROL_NAMES}
    world = evaluate_world_shuffle_delta(
        joined, positive if world_pass else zero,
        zero if world_pass else positive, bootstrap_replicates=10_000)
    return natural, controls, world


def test_p0_failure_stops_without_constructing_any_p1_evidence():
    result = derive_terminal_result(_p0(passed=False))
    validate_terminal_result(result)
    assert result["decision"] == "STOP_NO_REPRODUCIBLE_ACTION_LABEL"
    assert result["natural_result_sha256"] is None
    with pytest.raises(WorldAfterstateV1ResultError,
                       match="forbidden P1 artifacts"):
        derive_terminal_result(_p0(passed=False), natural_result={})


@pytest.mark.parametrize(("natural_pass", "control_pass", "world_pass",
                          "expected"), (
    (True, True, True, "REFUSE_MECHANICS_OR_CONTROL"),
    (False, False, False, "SELECT_NONE_NO_ACTION_ADVANTAGE"),
    (True, False, False, "PASS_ACTION_ONLY_NO_WORLD_SIGNAL"),
    (True, False, True, "PASS_TO_WORLD_TWIN_PACKET_REVIEW"),
))
def test_all_p1_terminal_routes_are_exact(
        natural_pass, control_pass, world_pass, expected):
    natural, controls, world = _components(
        natural_pass=natural_pass, control_pass=control_pass,
        world_pass=world_pass)
    result = derive_terminal_result(
        _p0(), natural_result=natural, control_results=controls,
        identical_predictions_exact_zero=True,
        world_shuffle_delta_result=world)
    validate_terminal_result(result)
    assert result["decision"] == expected
    assert result["world_twin_packet_review_proposal_authorized"] \
        is (expected == "PASS_TO_WORLD_TWIN_PACKET_REVIEW")


def test_identical_nonzero_prediction_forces_control_refusal():
    natural, controls, world = _components()
    result = derive_terminal_result(
        _p0(), natural_result=natural, control_results=controls,
        identical_predictions_exact_zero=False,
        world_shuffle_delta_result=world)
    assert result["decision"] == "REFUSE_MECHANICS_OR_CONTROL"
    forged = copy.deepcopy(result)
    forged["negative_controls_failed_on_demand"] = True
    with pytest.raises(WorldAfterstateV1ResultError,
                       match="control gate reconstruction drift"):
        validate_terminal_result(forged)


def test_terminal_decision_and_authority_mutations_are_refused():
    natural, controls, world = _components()
    result = derive_terminal_result(
        _p0(), natural_result=natural, control_results=controls,
        identical_predictions_exact_zero=True,
        world_shuffle_delta_result=world)
    forged = copy.deepcopy(result)
    forged["decision"] = "PASS_ACTION_ONLY_NO_WORLD_SIGNAL"
    with pytest.raises(WorldAfterstateV1ResultError,
                       match="reconstruction drift"):
        validate_terminal_result(forged)
    forged = copy.deepcopy(result)
    forged["authority"]["deployment_authorized"] = True
    with pytest.raises(WorldAfterstateV1ResultError, match="schema drift"):
        validate_terminal_result(forged)
