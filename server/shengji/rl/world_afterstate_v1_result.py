"""Exact terminal routing for the Value V1 P0/P1 mechanism pilot."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .belief_contract import canonical_json_bytes
from .world_afterstate_v1 import validate_label_ceiling
from .world_afterstate_v1_evaluation import (
    validate_advantage_audit_result, validate_world_shuffle_delta)


RESULT_SCHEMA = "world-afterstate-advantage-terminal-result-v1"
CONTROL_NAMES = (
    "identical-successor", "action-association-permutation",
    "label-permutation",
)
DECISIONS = (
    "STOP_NO_REPRODUCIBLE_ACTION_LABEL",
    "REFUSE_MECHANICS_OR_CONTROL",
    "SELECT_NONE_NO_ACTION_ADVANTAGE",
    "PASS_ACTION_ONLY_NO_WORLD_SIGNAL",
    "PASS_TO_WORLD_TWIN_PACKET_REVIEW",
)
AUTHORITY = {
    "p2_execution_authorized": False,
    "report_extension_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "retry_authorized": False,
    "r5_authorized": False,
}


class WorldAfterstateV1ResultError(ValueError):
    """A component result, control result, terminal route, or hash drifted."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV1ResultError(f"{label} drift")
    return value


def _decision(
        *, p0_passed: bool, natural_passed: bool | None,
        controls_failed: bool | None, world_signal_passed: bool | None) -> str:
    if not p0_passed:
        if any(value is not None for value in (
                natural_passed, controls_failed, world_signal_passed)):
            raise WorldAfterstateV1ResultError(
                "P0 stop carries forbidden P1 evidence")
        return "STOP_NO_REPRODUCIBLE_ACTION_LABEL"
    if type(natural_passed) is not bool \
            or type(controls_failed) is not bool \
            or type(world_signal_passed) is not bool:
        raise WorldAfterstateV1ResultError(
            "P1 terminal evidence is incomplete")
    if not controls_failed:
        return "REFUSE_MECHANICS_OR_CONTROL"
    if not natural_passed:
        return "SELECT_NONE_NO_ACTION_ADVANTAGE"
    if world_signal_passed:
        return "PASS_TO_WORLD_TWIN_PACKET_REVIEW"
    return "PASS_ACTION_ONLY_NO_WORLD_SIGNAL"


def derive_terminal_result(
        label_ceiling: Mapping[str, Any], *,
        natural_result: Mapping[str, Any] | None = None,
        control_results: Mapping[str, Mapping[str, Any]] | None = None,
        identical_predictions_exact_zero: bool | None = None,
        world_shuffle_delta_result: Mapping[str, Any] | None = None) \
        -> dict[str, Any]:
    validate_label_ceiling(label_ceiling)
    p0_passed = label_ceiling["passed"]
    if not p0_passed:
        if any(value is not None for value in (
                natural_result, control_results,
                identical_predictions_exact_zero,
                world_shuffle_delta_result)):
            raise WorldAfterstateV1ResultError(
                "P0 stop carries forbidden P1 artifacts")
        decision = _decision(
            p0_passed=False, natural_passed=None, controls_failed=None,
            world_signal_passed=None)
        natural_sha = None
        control_shas = None
        control_passes = None
        natural_passed = None
        controls_failed = None
        world_signal = None
        world_sha = None
    else:
        if type(natural_result) is not dict \
                or type(control_results) is not dict \
                or set(control_results) != set(CONTROL_NAMES) \
                or type(identical_predictions_exact_zero) is not bool \
                or type(world_shuffle_delta_result) is not dict:
            raise WorldAfterstateV1ResultError(
                "P1 terminal component population drift")
        validate_advantage_audit_result(natural_result)
        for result in control_results.values():
            validate_advantage_audit_result(result)
        validate_world_shuffle_delta(world_shuffle_delta_result)
        natural_passed = natural_result["passed"]
        controls_failed = identical_predictions_exact_zero and all(
            not control_results[name]["passed"] for name in CONTROL_NAMES)
        control_passes = {
            name: control_results[name]["passed"] for name in CONTROL_NAMES
        }
        world_signal = world_shuffle_delta_result["passed"]
        decision = _decision(
            p0_passed=True, natural_passed=natural_passed,
            controls_failed=controls_failed,
            world_signal_passed=world_signal)
        natural_sha = natural_result["result_sha256"]
        control_shas = {
            name: control_results[name]["result_sha256"]
            for name in CONTROL_NAMES
        }
        world_sha = world_shuffle_delta_result["result_sha256"]
    body = {
        "schema": RESULT_SCHEMA,
        "label_ceiling_result_sha256": label_ceiling["result_sha256"],
        "p0_label_ceiling_passed": p0_passed,
        "natural_result_sha256": natural_sha,
        "natural_action_gates_passed": natural_passed,
        "control_result_sha256s": control_shas,
        "control_action_gates_passed": control_passes,
        "identical_predictions_exact_zero":
            identical_predictions_exact_zero,
        "negative_controls_failed_on_demand": controls_failed,
        "world_shuffle_delta_result_sha256": world_sha,
        "world_signal_passed": world_signal,
        "decision": decision,
        "world_twin_packet_review_proposal_authorized":
            decision == "PASS_TO_WORLD_TWIN_PACKET_REVIEW",
        "public_action_value_packet_review_proposal_authorized": decision in (
            "PASS_ACTION_ONLY_NO_WORLD_SIGNAL",
            "PASS_TO_WORLD_TWIN_PACKET_REVIEW"),
        "authority": dict(AUTHORITY),
    }
    return {**body, "result_sha256": _sha(body)}


def validate_terminal_result(value: object) -> None:
    required = {
        "schema", "label_ceiling_result_sha256", "p0_label_ceiling_passed",
        "natural_result_sha256", "natural_action_gates_passed",
        "control_result_sha256s", "control_action_gates_passed",
        "identical_predictions_exact_zero",
        "negative_controls_failed_on_demand",
        "world_shuffle_delta_result_sha256", "world_signal_passed",
        "decision", "world_twin_packet_review_proposal_authorized",
        "public_action_value_packet_review_proposal_authorized",
        "authority", "result_sha256",
    }
    if type(value) is not dict or set(value) != required \
            or value.get("schema") != RESULT_SCHEMA \
            or type(value.get("p0_label_ceiling_passed")) is not bool \
            or value.get("decision") not in DECISIONS \
            or value.get("authority") != AUTHORITY \
            or type(value.get(
                "world_twin_packet_review_proposal_authorized")) is not bool \
            or type(value.get(
                "public_action_value_packet_review_proposal_authorized")) \
            is not bool:
        raise WorldAfterstateV1ResultError("terminal result schema drift")
    _digest(value.get("label_ceiling_result_sha256"),
            "terminal label ceiling SHA-256")
    _digest(value.get("result_sha256"), "terminal result SHA-256")
    p0 = value["p0_label_ceiling_passed"]
    if not p0:
        nullable = (
            "natural_result_sha256", "natural_action_gates_passed",
            "control_result_sha256s", "control_action_gates_passed",
            "identical_predictions_exact_zero",
            "negative_controls_failed_on_demand",
            "world_shuffle_delta_result_sha256", "world_signal_passed",
        )
        if any(value[key] is not None for key in nullable):
            raise WorldAfterstateV1ResultError(
                "terminal P0 stop evidence drift")
        natural = controls = world = None
    else:
        for key in (
                "natural_action_gates_passed",
                "identical_predictions_exact_zero",
                "negative_controls_failed_on_demand",
                "world_signal_passed"):
            if type(value.get(key)) is not bool:
                raise WorldAfterstateV1ResultError(
                    "terminal P1 boolean evidence drift")
        _digest(value.get("natural_result_sha256"),
                "terminal natural result SHA-256")
        _digest(value.get("world_shuffle_delta_result_sha256"),
                "terminal world-shuffle result SHA-256")
        controls_sha = value.get("control_result_sha256s")
        control_passes = value.get("control_action_gates_passed")
        if type(controls_sha) is not dict \
                or set(controls_sha) != set(CONTROL_NAMES) \
                or type(control_passes) is not dict \
                or set(control_passes) != set(CONTROL_NAMES) \
                or any(type(item) is not bool
                       for item in control_passes.values()):
            raise WorldAfterstateV1ResultError(
                "terminal control result population drift")
        for item in controls_sha.values():
            _digest(item, "terminal control result SHA-256")
        natural = value["natural_action_gates_passed"]
        controls = value["identical_predictions_exact_zero"] and all(
            not control_passes[name] for name in CONTROL_NAMES)
        if controls is not value["negative_controls_failed_on_demand"]:
            raise WorldAfterstateV1ResultError(
                "terminal control gate reconstruction drift")
        world = value["world_signal_passed"]
    expected = _decision(
        p0_passed=p0, natural_passed=natural,
        controls_failed=controls, world_signal_passed=world)
    body = {key: item for key, item in value.items()
            if key != "result_sha256"}
    if value["decision"] != expected \
            or value["world_twin_packet_review_proposal_authorized"] \
            is not (expected == "PASS_TO_WORLD_TWIN_PACKET_REVIEW") \
            or value["public_action_value_packet_review_proposal_authorized"] \
            is not (expected in (
                "PASS_ACTION_ONLY_NO_WORLD_SIGNAL",
                "PASS_TO_WORLD_TWIN_PACKET_REVIEW")) \
            or value["result_sha256"] != _sha(body):
        raise WorldAfterstateV1ResultError(
            "terminal result reconstruction drift")


def terminal_result_bytes(value: Mapping[str, Any]) -> bytes:
    validate_terminal_result(value)
    return canonical_json_bytes(value)


def reopen_terminal_result_bytes(raw: bytes) -> dict[str, Any]:
    if type(raw) is not bytes:
        raise WorldAfterstateV1ResultError("terminal result byte type drift")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WorldAfterstateV1ResultError(
            "terminal result is not canonical JSON") from exc
    if canonical_json_bytes(value) != raw:
        raise WorldAfterstateV1ResultError(
            "terminal result is not canonical JSON")
    validate_terminal_result(value)
    return value


__all__ = [
    "AUTHORITY", "CONTROL_NAMES", "DECISIONS", "WorldAfterstateV1ResultError",
    "derive_terminal_result", "reopen_terminal_result_bytes",
    "terminal_result_bytes", "validate_terminal_result",
]
