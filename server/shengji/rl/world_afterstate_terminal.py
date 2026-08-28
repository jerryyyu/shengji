"""Closed E4 control evidence and terminal routing.

This module does not run a model or open a split.  It consumes independently
reconstructable gate results and exact control witnesses, then emits one
all-authority-false decision.  A PASS permits only a later E5a design review.
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping, Sequence

from .belief_contract import canonical_json_bytes
from .world_afterstate_controls import (
    MUTATION_NAMES, WorldAfterstateControlError,
    validate_mutation_refusal_evidence,
    validate_transform_evidence)
from .world_afterstate_evaluation import (
    validate_action_result, validate_primary_result)


CONTROL_SCHEMA = "world-afterstate-e4-control-evidence-v0"
TERMINAL_SCHEMA = "world-afterstate-e4-terminal-v0"
TERMINAL_AUTHORITY = {
    "e5a_execution_authorized": False,
    "belief_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "r5_authorized": False,
}


class WorldAfterstateTerminalError(ValueError):
    """A control witness, gate result, or terminal decision drifted."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateTerminalError(f"{label} drift")
    return value


def build_control_evidence(
        *, permutation_primary: Mapping[str, Any],
        permutation_transform: Mapping[str, Any],
        preaction_action: Mapping[str, Any],
        preaction_transform: Mapping[str, Any],
        world_shuffle_primary: Mapping[str, Any],
        world_shuffle_transform: Mapping[str, Any],
        rotation_pairs: Sequence[Mapping[str, Any]],
        mutation_evidence: Mapping[str, Any]) -> dict[str, Any]:
    validate_primary_result(permutation_primary)
    validate_action_result(preaction_action)
    validate_primary_result(world_shuffle_primary)
    for value, expected_name in (
            (permutation_transform,
             "geometry-preserving-label-permutation"),
            (preaction_transform, "preaction-state-replacement"),
            (world_shuffle_transform, "complete-world-shuffle")):
        validate_transform_evidence(value)
        if value["name"] != expected_name:
            raise WorldAfterstateTerminalError(
                "control transform identity drift")
    if type(rotation_pairs) not in (list, tuple) or not rotation_pairs:
        raise WorldAfterstateTerminalError("rotation witness population drift")
    rotation_rows = []
    for pair in rotation_pairs:
        if type(pair) is not dict or set(pair) != {
                "base_input_sha256", "rotated_input_sha256",
                "base_prediction_sha256", "rotated_prediction_sha256"}:
            raise WorldAfterstateTerminalError("rotation witness schema drift")
        for key, value in pair.items():
            _digest(value, key)
        rotation_rows.append(dict(pair))
    try:
        validate_mutation_refusal_evidence(mutation_evidence)
    except WorldAfterstateControlError as exc:
        raise WorldAfterstateTerminalError(
            "mutation evidence drift") from exc
    rotation_passed = all(
        row["base_input_sha256"] == row["rotated_input_sha256"]
        and row["base_prediction_sha256"]
        == row["rotated_prediction_sha256"] for row in rotation_rows)
    body = {
        "schema": CONTROL_SCHEMA,
        "geometry_label_permutation_informative":
            permutation_transform["informative"],
        "geometry_label_permutation_failed_primary":
            permutation_primary["passed"] is False,
        "preaction_replacement_informative":
            preaction_transform["informative"],
        "preaction_replacement_failed_action_gate":
            preaction_action["passed"] is False,
        "complete_world_shuffle_informative":
            world_shuffle_transform["informative"],
        "complete_world_shuffle_failed_hidden_primary":
            world_shuffle_primary["passed"] is False,
        "permutation_result_sha256": permutation_primary["result_sha256"],
        "permutation_transform_sha256":
            permutation_transform["transform_sha256"],
        "preaction_result_sha256": preaction_action["result_sha256"],
        "preaction_transform_sha256":
            preaction_transform["transform_sha256"],
        "world_shuffle_result_sha256":
            world_shuffle_primary["result_sha256"],
        "world_shuffle_transform_sha256":
            world_shuffle_transform["transform_sha256"],
        "rotation_pair_count": len(rotation_rows),
        "rotation_pairs_sha256": _sha(rotation_rows),
        "rotation_passed": rotation_passed,
        "mutation_evidence_sha256":
            mutation_evidence["mutation_evidence_sha256"],
        "refused_mutations": [
            row["name"] for row in mutation_evidence["rows"]],
        "all_controls_passed": (
            permutation_transform["informative"]
            and permutation_primary["passed"] is False
            and preaction_transform["informative"]
            and preaction_action["passed"] is False
            and world_shuffle_transform["informative"]
            and world_shuffle_primary["passed"] is False
            and rotation_passed),
    }
    return {**body, "control_sha256": _sha(body)}


def validate_control_evidence(value: Mapping[str, Any]) -> None:
    required = {
        "schema", "geometry_label_permutation_failed_primary",
        "geometry_label_permutation_informative",
        "preaction_replacement_informative",
        "preaction_replacement_failed_action_gate",
        "complete_world_shuffle_informative",
        "complete_world_shuffle_failed_hidden_primary",
        "permutation_result_sha256", "preaction_result_sha256",
        "world_shuffle_result_sha256", "permutation_transform_sha256",
        "preaction_transform_sha256", "world_shuffle_transform_sha256",
        "rotation_pair_count",
        "rotation_pairs_sha256", "rotation_passed",
        "mutation_evidence_sha256", "refused_mutations",
        "all_controls_passed", "control_sha256",
    }
    if type(value) is not dict or set(value) != required \
            or value.get("schema") != CONTROL_SCHEMA:
        raise WorldAfterstateTerminalError("control evidence schema drift")
    for key in (
            "permutation_result_sha256", "preaction_result_sha256",
            "world_shuffle_result_sha256", "permutation_transform_sha256",
            "preaction_transform_sha256", "world_shuffle_transform_sha256",
            "rotation_pairs_sha256",
            "mutation_evidence_sha256",
            "control_sha256"):
        _digest(value[key], key)
    if value["refused_mutations"] != sorted(MUTATION_NAMES) \
            or type(value["rotation_pair_count"]) is not int \
            or value["rotation_pair_count"] <= 0 \
            or any(type(value[key]) is not bool for key in (
                "geometry_label_permutation_failed_primary",
                "geometry_label_permutation_informative",
                "preaction_replacement_informative",
                "preaction_replacement_failed_action_gate",
                "complete_world_shuffle_informative",
                "complete_world_shuffle_failed_hidden_primary",
                "rotation_passed", "all_controls_passed")):
        raise WorldAfterstateTerminalError("control evidence identity drift")
    expected_pass = all(value[key] for key in (
        "geometry_label_permutation_informative",
        "geometry_label_permutation_failed_primary",
        "preaction_replacement_informative",
        "preaction_replacement_failed_action_gate",
        "complete_world_shuffle_informative",
        "complete_world_shuffle_failed_hidden_primary",
        "rotation_passed"))
    body = {key: item for key, item in value.items()
            if key != "control_sha256"}
    if value["all_controls_passed"] is not expected_pass \
            or value["control_sha256"] != _sha(body):
        raise WorldAfterstateTerminalError(
            "control evidence reconstruction drift")


def build_terminal_result(
        *, freeze_sha256: str, primary: Mapping[str, Any],
        action: Mapping[str, Any], controls: Mapping[str, Any]) \
        -> dict[str, Any]:
    _digest(freeze_sha256, "terminal freeze SHA-256")
    validate_primary_result(primary)
    validate_action_result(action)
    validate_control_evidence(controls)
    if not controls["all_controls_passed"]:
        decision = "REFUSE_MECHANICS_OR_NEGATIVE_CONTROL"
    elif not primary["passed"]:
        decision = "SELECT_NONE_HELD_OUT_VALUE_LEARNING"
    elif not action["passed"]:
        decision = "SELECT_NONE_ACTION_USEFULNESS"
    else:
        decision = "PASS_TO_E5A_KNOWN_WORLD_MECHANISM_REVIEW"
    body = {
        "schema": TERMINAL_SCHEMA,
        "freeze_sha256": freeze_sha256,
        "primary_result_sha256": primary["result_sha256"],
        "action_result_sha256": action["result_sha256"],
        "control_sha256": controls["control_sha256"],
        "decision": decision,
        "search_remains_final_authority": True,
        "belief_required": False,
        "authority": dict(TERMINAL_AUTHORITY),
    }
    return {**body, "terminal_sha256": _sha(body)}


def validate_terminal_result(value: Mapping[str, Any]) -> None:
    required = {
        "schema", "freeze_sha256", "primary_result_sha256",
        "action_result_sha256", "control_sha256", "decision",
        "search_remains_final_authority", "belief_required", "authority",
        "terminal_sha256",
    }
    if type(value) is not dict or set(value) != required \
            or value.get("schema") != TERMINAL_SCHEMA \
            or value.get("authority") != TERMINAL_AUTHORITY \
            or value.get("search_remains_final_authority") is not True \
            or value.get("belief_required") is not False \
            or value.get("decision") not in (
                "REFUSE_MECHANICS_OR_NEGATIVE_CONTROL",
                "SELECT_NONE_HELD_OUT_VALUE_LEARNING",
                "SELECT_NONE_ACTION_USEFULNESS",
                "PASS_TO_E5A_KNOWN_WORLD_MECHANISM_REVIEW"):
        raise WorldAfterstateTerminalError("terminal result schema drift")
    for key in (
            "freeze_sha256", "primary_result_sha256", "action_result_sha256",
            "control_sha256", "terminal_sha256"):
        _digest(value[key], key)
    body = {key: item for key, item in value.items()
            if key != "terminal_sha256"}
    if value["terminal_sha256"] != _sha(body):
        raise WorldAfterstateTerminalError(
            "terminal result reconstruction drift")


__all__ = [
    "CONTROL_SCHEMA", "MUTATION_NAMES", "TERMINAL_AUTHORITY",
    "TERMINAL_SCHEMA", "WorldAfterstateTerminalError",
    "build_control_evidence", "build_terminal_result",
    "validate_control_evidence", "validate_terminal_result",
]
