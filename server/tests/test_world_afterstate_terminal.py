from __future__ import annotations

import copy

import pytest

from shengji.rl.world_afterstate_terminal import (
    MUTATION_NAMES, WorldAfterstateTerminalError, build_control_evidence,
    build_terminal_result, validate_terminal_result)


def _result(schema, passed, digest="a"):
    if schema == "world-afterstate-primary-gate-v0":
        body = {
            "schema": schema, "fold": "report", "row_count": 8,
            "deal_count": 8, "mean_nll_improvement_nanonats": 10,
            "bootstrap_lower_nanonats": 1 if passed else -1,
            "bootstrap_upper_nanonats": 20, "bootstrap_replicates": 10000,
            "positive_member_count": 8 if passed else 0, "member_count": 8,
            "passed": passed,
            "authority": {
                "report_opening_authorized": False,
                "gameplay_authorized": False,
                "strength_claim_authorized": False,
                "merge_authorized": False, "promotion_authorized": False,
                "deployment_authorized": False},
        }
    else:
        metric = {"mean": 10, "bootstrap_lower": 1 if passed else -1,
                  "bootstrap_upper": 20}
        body = {
            "schema": schema, "state_group_count": 8, "deal_count": 8,
            "expected_utility_error_improvement_ppm": dict(metric),
            "simple_regret_improvement_ppm": dict(metric),
            "protected_incumbent_nonregression_ppm": {
                "mean": 0, "bootstrap_lower": 0, "bootstrap_upper": 0},
            "bootstrap_replicates": 10000, "passed": passed,
            "authority": {
                "report_opening_authorized": False,
                "gameplay_authorized": False,
                "strength_claim_authorized": False,
                "merge_authorized": False, "promotion_authorized": False,
                "deployment_authorized": False},
        }
    from shengji.rl.belief_contract import canonical_json_bytes
    import hashlib
    return {**body, "result_sha256": hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()}


def _transform(name, digit):
    from shengji.rl.belief_contract import canonical_json_bytes
    import hashlib
    body = {
        "schema": "world-afterstate-e4-control-transform-v0",
        "name": name, "row_count": 2, "changed_count": 2,
        "informative": True,
        "input_population_sha256": digit * 64,
        "output_population_sha256": str((int(digit) + 1) % 10) * 64,
        "authority": {
            "report_opening_authorized": False,
            "gameplay_authorized": False,
            "strength_claim_authorized": False,
            "deployment_authorized": False,
        },
    }
    return {**body, "transform_sha256": hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()}


def _mutations():
    from shengji.rl.belief_contract import canonical_json_bytes
    import hashlib
    rows = [{
        "name": name,
        "input_sha256": f"{index + 1}" * 64,
        "mutation_sha256": "abcde"[index] * 64,
        "refusal": f"{name} refused",
    } for index, name in enumerate(sorted(MUTATION_NAMES))]
    body = {
        "schema": "world-afterstate-e4-mutation-refusals-v0",
        "rows": rows, "all_refused": True,
        "authority": {
            "report_opening_authorized": False,
            "gameplay_authorized": False,
            "strength_claim_authorized": False,
            "deployment_authorized": False,
        },
    }
    return {**body, "mutation_evidence_sha256": hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()}


def _controls():
    primary_false = _result("world-afterstate-primary-gate-v0", False)
    action_false = _result("world-afterstate-action-gate-v0", False)
    return build_control_evidence(
        permutation_primary=primary_false,
        permutation_transform=_transform(
            "geometry-preserving-label-permutation", "1"),
        preaction_action=action_false,
        preaction_transform=_transform(
            "preaction-state-replacement", "3"),
        world_shuffle_primary=primary_false,
        world_shuffle_transform=_transform(
            "complete-world-shuffle", "5"),
        rotation_pairs=[{
            "base_input_sha256": "1" * 64,
            "rotated_input_sha256": "1" * 64,
            "base_prediction_sha256": "2" * 64,
            "rotated_prediction_sha256": "2" * 64}],
        mutation_evidence=_mutations())


def test_terminal_pass_only_routes_to_later_known_world_review():
    primary = _result("world-afterstate-primary-gate-v0", True)
    action = _result("world-afterstate-action-gate-v0", True)
    result = build_terminal_result(
        freeze_sha256="f" * 64, primary=primary, action=action,
        controls=_controls())
    validate_terminal_result(result)
    assert result["decision"] \
        == "PASS_TO_E5A_KNOWN_WORLD_MECHANISM_REVIEW"
    assert set(result["authority"].values()) == {False}


def test_controls_and_result_bindings_can_fail():
    controls = _controls()
    forged = copy.deepcopy(controls)
    forged["rotation_passed"] = False
    with pytest.raises(WorldAfterstateTerminalError,
                       match="reconstruction drift"):
        build_terminal_result(
            freeze_sha256="f" * 64,
            primary=_result("world-afterstate-primary-gate-v0", True),
            action=_result("world-afterstate-action-gate-v0", True),
            controls=forged)

    with pytest.raises(WorldAfterstateTerminalError,
                       match="mutation evidence"):
        build_control_evidence(
            permutation_primary=_result(
                "world-afterstate-primary-gate-v0", False),
            permutation_transform=_transform(
                "geometry-preserving-label-permutation", "1"),
            preaction_action=_result("world-afterstate-action-gate-v0", False),
            preaction_transform=_transform(
                "preaction-state-replacement", "3"),
            world_shuffle_primary=_result(
                "world-afterstate-primary-gate-v0", False),
            world_shuffle_transform=_transform(
                "complete-world-shuffle", "5"),
            rotation_pairs=[{
                "base_input_sha256": "1" * 64,
                "rotated_input_sha256": "1" * 64,
                "base_prediction_sha256": "2" * 64,
                "rotated_prediction_sha256": "2" * 64}],
            mutation_evidence={**_mutations(), "rows": _mutations()[
                "rows"][:-1]})


def test_uninformative_negative_control_seals_a_refusal_not_an_exception():
    from shengji.rl.belief_contract import canonical_json_bytes
    import hashlib

    transform = _transform("geometry-preserving-label-permutation", "1")
    body = {key: value for key, value in transform.items()
            if key != "transform_sha256"}
    body["changed_count"] = 0
    body["informative"] = False
    body["output_population_sha256"] = body["input_population_sha256"]
    transform = {**body, "transform_sha256": hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()}
    controls = build_control_evidence(
        permutation_primary=_result(
            "world-afterstate-primary-gate-v0", True),
        permutation_transform=transform,
        preaction_action=_result("world-afterstate-action-gate-v0", False),
        preaction_transform=_transform(
            "preaction-state-replacement", "3"),
        world_shuffle_primary=_result(
            "world-afterstate-primary-gate-v0", False),
        world_shuffle_transform=_transform(
            "complete-world-shuffle", "5"),
        rotation_pairs=[{
            "base_input_sha256": "1" * 64,
            "rotated_input_sha256": "1" * 64,
            "base_prediction_sha256": "2" * 64,
            "rotated_prediction_sha256": "2" * 64}],
        mutation_evidence=_mutations())
    result = build_terminal_result(
        freeze_sha256="f" * 64,
        primary=_result("world-afterstate-primary-gate-v0", True),
        action=_result("world-afterstate-action-gate-v0", True),
        controls=controls)
    assert result["decision"] == "REFUSE_MECHANICS_OR_NEGATIVE_CONTROL"
