"""Strict payload reopeners for Value-Afterstate V2 terminal inputs.

These functions turn canonical JSON payload objects back into the existing
typed receipts.  They perform no filesystem I/O and grant no authority.  A
terminal supervisor can therefore stable-read bytes once, parse canonical
JSON, and use this module instead of accepting caller-constructed metrics.
"""

from __future__ import annotations

from typing import Any, Mapping

from .world_afterstate_v2_diagnostics import (
    ModelSelectorPowerReceiptV2, OptimizerCanaryReceiptV2,
    validate_model_selector_power_v2, validate_optimizer_canary_v2)
from .world_afterstate_v2_evaluation import (
    EvaluationMetricReceiptV2, EvaluationResultV2)
from .world_afterstate_v2_metrics import BootstrapIntervalV2, JeffreysPriorV2


class WorldAfterstateV2ReopenError(ValueError):
    """A serialized V2 terminal input did not exactly reconstruct."""


def _mapping(value: object, label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise WorldAfterstateV2ReopenError(f"{label} payload type drift")
    return value


def _exact(rebuilt: object, payload: Mapping[str, Any], label: str) -> None:
    try:
        actual = rebuilt.payload()  # type: ignore[attr-defined]
    except Exception as exc:
        raise WorldAfterstateV2ReopenError(
            f"{label} typed validation refused") from exc
    if actual != payload:
        raise WorldAfterstateV2ReopenError(
            f"{label} payload reconstruction drift")


def reopen_optimizer_canary_v2(
        value: Mapping[str, Any]) -> OptimizerCanaryReceiptV2:
    payload = _mapping(value, "optimizer canary")
    required = {
        "schema", "source_p0_population_sha256", "root_population_sha256",
        "model_seed", "root_count", "optimizer_steps",
        "early_stopping_used", "gradients_finite", "weights_finite",
        "initial_loss_nano", "empirical_loss_nano", "final_loss_nano",
        "normalized_progress_ppm", "passed", "authority",
    }
    if set(payload) != required:
        raise WorldAfterstateV2ReopenError(
            "optimizer canary field population drift")
    try:
        result = OptimizerCanaryReceiptV2(**payload)
        validate_optimizer_canary_v2(result)
    except Exception as exc:
        raise WorldAfterstateV2ReopenError(
            "optimizer canary reconstruction refused") from exc
    _exact(result, payload, "optimizer canary")
    return result


def reopen_model_selector_power_v2(
        value: Mapping[str, Any]) -> ModelSelectorPowerReceiptV2:
    payload = _mapping(value, "model-selector power")
    required = {
        "schema", "precision_select_population_sha256",
        "deal_utilities_microlevels", "precision_select_deal_count",
        "frozen_audit_deal_count", "s_model_microlevels", "n_required",
        "stop_underpowered", "z_alpha_ppm", "z_power_ppm",
        "delta_microlevels", "replica_count", "estimand_identity",
        "authority",
    }
    if set(payload) != required or type(
            payload["deal_utilities_microlevels"]) is not list:
        raise WorldAfterstateV2ReopenError(
            "model-selector power field population drift")
    kwargs = dict(payload)
    kwargs["deal_utilities_microlevels"] = tuple(
        payload["deal_utilities_microlevels"])
    try:
        result = ModelSelectorPowerReceiptV2(**kwargs)
        validate_model_selector_power_v2(result)
    except Exception as exc:
        raise WorldAfterstateV2ReopenError(
            "model-selector power reconstruction refused") from exc
    _exact(result, payload, "model-selector power")
    return result


def reopen_jeffreys_prior_v2(value: Mapping[str, Any]) -> JeffreysPriorV2:
    payload = _mapping(value, "Jeffreys prior")
    required = {
        "schema", "global_probability_ppb", "strata_probability_ppb",
        "natural_fit_row_count", "authority",
    }
    if set(payload) != required \
            or type(payload["global_probability_ppb"]) is not list \
            or type(payload["strata_probability_ppb"]) is not list:
        raise WorldAfterstateV2ReopenError(
            "Jeffreys prior field population drift")
    strata = []
    for row in payload["strata_probability_ppb"]:
        if type(row) is not list or len(row) != 2 or type(row[1]) is not list:
            raise WorldAfterstateV2ReopenError("Jeffreys prior stratum drift")
        strata.append((row[0], tuple(row[1])))
    try:
        result = JeffreysPriorV2(
            global_probability_ppb=tuple(payload["global_probability_ppb"]),
            strata_probability_ppb=tuple(strata),
            natural_fit_row_count=payload["natural_fit_row_count"],
            schema=payload["schema"], authority=payload["authority"])
        result.validate()
    except Exception as exc:
        raise WorldAfterstateV2ReopenError(
            "Jeffreys prior reconstruction refused") from exc
    _exact(result, payload, "Jeffreys prior")
    return result


def _bootstrap(value: object) -> BootstrapIntervalV2:
    payload = _mapping(value, "evaluation bootstrap")
    required = {
        "schema", "population_sha256", "metric_name", "seed", "replicates",
        "mean", "lower_5th", "upper_95th",
    }
    if set(payload) != required:
        raise WorldAfterstateV2ReopenError(
            "evaluation bootstrap field population drift")
    try:
        result = BootstrapIntervalV2(**payload)
        result.validate()
    except Exception as exc:
        raise WorldAfterstateV2ReopenError(
            "evaluation bootstrap reconstruction refused") from exc
    _exact(result, payload, "evaluation bootstrap")
    return result


def _metric(value: object) -> EvaluationMetricReceiptV2:
    payload = _mapping(value, "evaluation metric")
    required = {"schema", "metric_name", "mean", "bootstrap", "authority"}
    if set(payload) != required:
        raise WorldAfterstateV2ReopenError(
            "evaluation metric field population drift")
    try:
        result = EvaluationMetricReceiptV2(
            metric_name=payload["metric_name"], mean=payload["mean"],
            bootstrap=_bootstrap(payload["bootstrap"]),
            schema=payload["schema"], authority=payload["authority"])
        result.validate()
    except Exception as exc:
        raise WorldAfterstateV2ReopenError(
            "evaluation metric reconstruction refused") from exc
    _exact(result, payload, "evaluation metric")
    return result


def _integer_tuple(payload: Mapping[str, Any], key: str) -> tuple[int, ...]:
    value = payload[key]
    if type(value) is not list:
        raise WorldAfterstateV2ReopenError(f"evaluation {key} drift")
    return tuple(value)


def _deal_tuple(payload: Mapping[str, Any], key: str) \
        -> tuple[tuple[str, int], ...]:
    value = payload[key]
    if type(value) is not list or any(
            type(row) is not list or len(row) != 2 for row in value):
        raise WorldAfterstateV2ReopenError(f"evaluation {key} drift")
    return tuple((row[0], row[1]) for row in value)


def reopen_evaluation_result_v2(
        value: Mapping[str, Any]) -> EvaluationResultV2:
    payload = _mapping(value, "evaluation result")
    required = {
        "schema", "population_sha256", "seed_block", "control_name",
        "rps_improvement", "absolute_error_improvement",
        "paired_error_improvement", "selected_action_utility",
        "cvar10_selected_utility", "member_rps_improvement",
        "member_absolute_error_improvement", "member_paired_error_improvement",
        "member_action_utility", "positive_rps_member_count",
        "positive_absolute_error_member_count", "positive_paired_error_member_count",
        "positive_action_utility_member_count", "nonincumbent_dose_ppm",
        "learning_gates_1_to_4", "deal_rps_improvement",
        "deal_absolute_error_improvement", "deal_paired_error_improvement",
        "deal_action_utility", "authority",
    }
    if set(payload) != required or type(payload["learning_gates_1_to_4"]) is not list:
        raise WorldAfterstateV2ReopenError(
            "evaluation result field population drift")
    try:
        result = EvaluationResultV2(
            population_sha256=payload["population_sha256"],
            seed_block=payload["seed_block"], control_name=payload["control_name"],
            rps_improvement=_metric(payload["rps_improvement"]),
            absolute_error_improvement=_metric(
                payload["absolute_error_improvement"]),
            paired_error_improvement=_metric(payload["paired_error_improvement"]),
            selected_action_utility=_metric(payload["selected_action_utility"]),
            cvar10_selected_utility=_metric(payload["cvar10_selected_utility"]),
            member_rps_improvement=_integer_tuple(
                payload, "member_rps_improvement"),
            member_absolute_error_improvement=_integer_tuple(
                payload, "member_absolute_error_improvement"),
            member_paired_error_improvement=_integer_tuple(
                payload, "member_paired_error_improvement"),
            member_action_utility=_integer_tuple(payload, "member_action_utility"),
            positive_rps_member_count=payload["positive_rps_member_count"],
            positive_absolute_error_member_count=payload[
                "positive_absolute_error_member_count"],
            positive_paired_error_member_count=payload[
                "positive_paired_error_member_count"],
            positive_action_utility_member_count=payload[
                "positive_action_utility_member_count"],
            nonincumbent_dose_ppm=payload["nonincumbent_dose_ppm"],
            learning_gates_1_to_4=tuple(payload["learning_gates_1_to_4"]),
            deal_rps_improvement=_deal_tuple(payload, "deal_rps_improvement"),
            deal_absolute_error_improvement=_deal_tuple(
                payload, "deal_absolute_error_improvement"),
            deal_paired_error_improvement=_deal_tuple(
                payload, "deal_paired_error_improvement"),
            deal_action_utility=_deal_tuple(payload, "deal_action_utility"),
            schema=payload["schema"], authority=payload["authority"])
        result.validate()
    except Exception as exc:
        raise WorldAfterstateV2ReopenError(
            "evaluation result reconstruction refused") from exc
    _exact(result, payload, "evaluation result")
    return result


__all__ = [
    "WorldAfterstateV2ReopenError", "reopen_evaluation_result_v2",
    "reopen_jeffreys_prior_v2", "reopen_model_selector_power_v2",
    "reopen_optimizer_canary_v2",
]
