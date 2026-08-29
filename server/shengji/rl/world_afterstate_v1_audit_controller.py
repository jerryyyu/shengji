"""Target-free prediction seal and label-gated Value V1 audit.

The first stage accepts models and an outcome-blind inference batch, then
returns canonical prediction bytes.  It cannot receive audit labels.  The
second stage accepts those already-sealed bytes plus calibration pairs.  This
literal API ordering prevents prediction after outcome inspection.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from .belief_contract import canonical_json_bytes
from .world_afterstate_v1_controls import (
    complete_world_shuffle, validate_control_evidence)
from .world_afterstate_v1_dataset import JoinedAdvantageV1
from .world_afterstate_v1_evaluation import (
    AdvantageInferenceBatchV1, AdvantagePredictionV1,
    evaluate_advantage_audit, evaluate_world_shuffle_delta,
    inference_population_sha256, predict_advantages,
    prediction_population_sha256, validate_advantage_audit_result,
    validate_world_shuffle_delta)
from .world_afterstate_v1_model import WorldAfterstateAdvantageV1
from .world_afterstate_v1_training import COHORT_SIZE, model_state_sha256
from .world_afterstate_v1_training_controller import (
    TRAINING_COHORTS, validate_cohort_manifest)


PREDICTION_ARTIFACT_SCHEMA = (
    "world-afterstate-advantage-prediction-artifact-v1")
AUDIT_RESULT_SCHEMA = "world-afterstate-advantage-sealed-audit-result-v1"
AUTHORITY = {
    "report_opening_authorized": False,
    "world_twin_generation_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "retry_authorized": False,
    "r5_authorized": False,
}


class WorldAfterstateV1AuditControllerError(ValueError):
    """A prediction seal, model cohort, control, or label join drifted."""


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV1AuditControllerError(f"{label} drift")
    return value


def _prediction_rows(
        models: Sequence[WorldAfterstateAdvantageV1],
        batch: AdvantageInferenceBatchV1) -> tuple[AdvantagePredictionV1, ...]:
    return tuple(row for member, model in enumerate(models)
                 for row in predict_advantages(
                     model, batch, member_index=member))


def build_prediction_artifact_bytes(
        *, models: Sequence[WorldAfterstateAdvantageV1],
        batch: AdvantageInferenceBatchV1,
        cohort_manifest: Mapping[str, Any]) -> bytes:
    """Seal predictions without accepting any target or outcome argument."""
    validate_cohort_manifest(cohort_manifest)
    if type(models) not in (list, tuple) or len(models) != COHORT_SIZE \
            or any(type(model) is not WorldAfterstateAdvantageV1
                   for model in models) \
            or type(batch) is not AdvantageInferenceBatchV1:
        raise WorldAfterstateV1AuditControllerError(
            "prediction artifact request drift")
    expected_states = tuple(
        row["selected_model_state_sha256"]
        for row in cohort_manifest["members"])
    measured_states = tuple(model_state_sha256(model) for model in models)
    if measured_states != expected_states:
        raise WorldAfterstateV1AuditControllerError(
            "prediction model cohort binding drift")
    batch.validate()
    natural = _prediction_rows(models, batch)
    natural_sha = prediction_population_sha256(natural)
    apply_world_shuffle = cohort_manifest["cohort_name"] == "natural"
    shuffle_evidence = None
    shuffled_input_sha = None
    shuffled_predictions: tuple[AdvantagePredictionV1, ...] = ()
    shuffled_prediction_sha = None
    if apply_world_shuffle:
        shuffled_batch, shuffle_evidence = complete_world_shuffle(batch)
        validate_control_evidence(shuffle_evidence)
        shuffled_input_sha = inference_population_sha256(shuffled_batch)
        if shuffled_input_sha == inference_population_sha256(batch):
            raise WorldAfterstateV1AuditControllerError(
                "world-shuffle target-free input did not change")
        shuffled_predictions = _prediction_rows(models, shuffled_batch)
        shuffled_prediction_sha = prediction_population_sha256(
            shuffled_predictions)
    body = {
        "schema": PREDICTION_ARTIFACT_SCHEMA,
        "freeze_sha256": cohort_manifest["freeze_sha256"],
        "cohort_name": cohort_manifest["cohort_name"],
        "cohort_manifest_sha256": cohort_manifest["manifest_sha256"],
        "selected_checkpoint_external_sha256s": [
            row["selected_checkpoint_external_sha256"]
            for row in cohort_manifest["members"]],
        "selected_model_state_sha256s": list(measured_states),
        "input_row_count": len(batch.state_group_ids),
        "input_population_sha256": inference_population_sha256(batch),
        "natural_prediction_population_sha256": natural_sha,
        "natural_predictions": [row.payload() for row in natural],
        "world_shuffle_applied": apply_world_shuffle,
        "world_shuffle_control_evidence": shuffle_evidence,
        "world_shuffle_input_population_sha256": shuffled_input_sha,
        "world_shuffle_prediction_population_sha256":
            shuffled_prediction_sha,
        "world_shuffle_predictions": [
            row.payload() for row in shuffled_predictions],
        "audit_labels_opened": False,
        "report_rows_opened": False,
        "authority": dict(AUTHORITY),
    }
    return canonical_json_bytes({
        **body, "artifact_sha256": _sha(body),
    })


def _parse_predictions(value: object) -> tuple[AdvantagePredictionV1, ...]:
    if type(value) is not list:
        raise WorldAfterstateV1AuditControllerError(
            "prediction row population drift")
    rows = []
    for payload in value:
        if type(payload) is not dict:
            raise WorldAfterstateV1AuditControllerError(
                "prediction row drift")
        try:
            row = AdvantagePredictionV1(
                state_group_id=payload.get("state_group_id"),
                candidate_index=payload.get("candidate_index"),
                incumbent_successor_sha256=payload.get(
                    "incumbent_successor_sha256"),
                candidate_successor_sha256=payload.get(
                    "candidate_successor_sha256"),
                member_index=payload.get("member_index"),
                model_state_sha256=payload.get("model_state_sha256"),
                advantage_microlevels=payload.get("advantage_microlevels"),
                schema=payload.get("schema"))
        except (TypeError, ValueError) as exc:
            raise WorldAfterstateV1AuditControllerError(
                "prediction row drift") from exc
        if row.payload() != payload:
            raise WorldAfterstateV1AuditControllerError(
                "prediction row reconstruction drift")
        rows.append(row)
    return tuple(rows)


def reopen_prediction_artifact_bytes(raw: bytes) -> tuple[
        tuple[AdvantagePredictionV1, ...],
        tuple[AdvantagePredictionV1, ...], dict[str, Any]]:
    if type(raw) is not bytes:
        raise WorldAfterstateV1AuditControllerError(
            "prediction artifact byte type drift")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WorldAfterstateV1AuditControllerError(
            "prediction artifact is not canonical JSON") from exc
    required = {
        "schema", "freeze_sha256", "cohort_name",
        "cohort_manifest_sha256",
        "selected_checkpoint_external_sha256s",
        "selected_model_state_sha256s", "input_row_count",
        "input_population_sha256", "natural_prediction_population_sha256",
        "natural_predictions", "world_shuffle_applied",
        "world_shuffle_control_evidence",
        "world_shuffle_input_population_sha256",
        "world_shuffle_prediction_population_sha256",
        "world_shuffle_predictions", "audit_labels_opened",
        "report_rows_opened", "authority", "artifact_sha256",
    }
    if type(value) is not dict or set(value) != required \
            or canonical_json_bytes(value) != raw \
            or value.get("schema") != PREDICTION_ARTIFACT_SCHEMA \
            or value.get("cohort_name") not in TRAINING_COHORTS \
            or value.get("audit_labels_opened") is not False \
            or value.get("report_rows_opened") is not False \
            or value.get("authority") != AUTHORITY \
            or type(value.get("world_shuffle_applied")) is not bool:
        raise WorldAfterstateV1AuditControllerError(
            "prediction artifact schema drift")
    for key in (
            "freeze_sha256", "cohort_manifest_sha256",
            "input_population_sha256",
            "natural_prediction_population_sha256", "artifact_sha256"):
        _digest(value.get(key), f"prediction artifact {key}")
    checkpoints = value.get("selected_checkpoint_external_sha256s")
    model_states = value.get("selected_model_state_sha256s")
    count = value.get("input_row_count")
    if type(checkpoints) is not list or len(checkpoints) != COHORT_SIZE \
            or type(model_states) is not list \
            or len(model_states) != COHORT_SIZE \
            or len(set(model_states)) != COHORT_SIZE \
            or any(_digest(item, "prediction checkpoint SHA-256") != item
                   for item in checkpoints) \
            or any(_digest(item, "prediction model state SHA-256") != item
                   for item in model_states) \
            or isinstance(count, bool) or not isinstance(count, int) \
            or count <= 0:
        raise WorldAfterstateV1AuditControllerError(
            "prediction artifact cohort/population drift")
    natural = _parse_predictions(value.get("natural_predictions"))
    if len(natural) != count * COHORT_SIZE \
            or prediction_population_sha256(natural) \
            != value["natural_prediction_population_sha256"] \
            or tuple(sorted({row.model_state_sha256 for row in natural})) \
            != tuple(sorted(model_states)):
        raise WorldAfterstateV1AuditControllerError(
            "natural prediction population binding drift")
    shuffled = _parse_predictions(value.get("world_shuffle_predictions"))
    applied = value["world_shuffle_applied"]
    if applied:
        validate_control_evidence(value.get(
            "world_shuffle_control_evidence"))
        _digest(value.get("world_shuffle_input_population_sha256"),
                "world-shuffle input population SHA-256")
        _digest(value.get("world_shuffle_prediction_population_sha256"),
                "world-shuffle prediction population SHA-256")
        if value["cohort_name"] != "natural" or len(shuffled) != len(natural) \
                or prediction_population_sha256(shuffled) \
                != value["world_shuffle_prediction_population_sha256"] \
                or value["world_shuffle_input_population_sha256"] \
                == value["input_population_sha256"]:
            raise WorldAfterstateV1AuditControllerError(
                "world-shuffle prediction population binding drift")
    elif value["cohort_name"] == "natural" \
            or value["world_shuffle_control_evidence"] is not None \
            or value["world_shuffle_input_population_sha256"] is not None \
            or value["world_shuffle_prediction_population_sha256"] is not None \
            or shuffled:
        raise WorldAfterstateV1AuditControllerError(
            "world-shuffle absence binding drift")
    body = {key: item for key, item in value.items()
            if key != "artifact_sha256"}
    if value["artifact_sha256"] != _sha(body):
        raise WorldAfterstateV1AuditControllerError(
            "prediction artifact reconstruction drift")
    return natural, shuffled, value


def evaluate_sealed_predictions(
        prediction_raw: bytes,
        audit_pairs: Sequence[JoinedAdvantageV1]) -> dict[str, Any]:
    """Open labels only after an immutable prediction byte stream exists."""
    natural, shuffled, artifact = reopen_prediction_artifact_bytes(
        prediction_raw)
    natural_result = evaluate_advantage_audit(audit_pairs, natural)
    validate_advantage_audit_result(natural_result)
    shuffled_result = None
    world_shuffle_delta = None
    if artifact["world_shuffle_applied"]:
        shuffled_result = evaluate_advantage_audit(audit_pairs, shuffled)
        validate_advantage_audit_result(shuffled_result)
        world_shuffle_delta = evaluate_world_shuffle_delta(
            audit_pairs, natural, shuffled)
        validate_world_shuffle_delta(world_shuffle_delta)
    audit_bindings = []
    for value in audit_pairs:
        if type(value) is not JoinedAdvantageV1:
            raise WorldAfterstateV1AuditControllerError(
                "sealed audit pair type drift")
        value.validate()
        audit_bindings.append(value.binding())
    body = {
        "schema": AUDIT_RESULT_SCHEMA,
        "prediction_artifact_external_sha256": _sha_bytes(prediction_raw),
        "prediction_artifact_sha256": artifact["artifact_sha256"],
        "cohort_name": artifact["cohort_name"],
        "audit_population_sha256": _sha(sorted(
            audit_bindings, key=lambda row: (
                row["state_group_id"], row["candidate_index"],
                row["replicate"]))),
        "natural_result": natural_result,
        "world_shuffle_applied": artifact["world_shuffle_applied"],
        "world_shuffle_result": shuffled_result,
        "world_shuffle_delta_result": world_shuffle_delta,
        "audit_labels_opened": True,
        "report_rows_opened": False,
        "authority": dict(AUTHORITY),
    }
    return {**body, "result_sha256": _sha(body)}


def validate_sealed_audit_result(value: object) -> None:
    required = {
        "schema", "prediction_artifact_external_sha256",
        "prediction_artifact_sha256", "cohort_name",
        "audit_population_sha256", "natural_result",
        "world_shuffle_applied", "world_shuffle_result",
        "world_shuffle_delta_result",
        "audit_labels_opened", "report_rows_opened", "authority",
        "result_sha256",
    }
    if type(value) is not dict or set(value) != required \
            or value.get("schema") != AUDIT_RESULT_SCHEMA \
            or value.get("cohort_name") not in TRAINING_COHORTS \
            or value.get("audit_labels_opened") is not True \
            or value.get("report_rows_opened") is not False \
            or value.get("authority") != AUTHORITY \
            or type(value.get("world_shuffle_applied")) is not bool:
        raise WorldAfterstateV1AuditControllerError(
            "sealed audit result schema drift")
    for key in (
            "prediction_artifact_external_sha256",
            "prediction_artifact_sha256", "audit_population_sha256",
            "result_sha256"):
        _digest(value.get(key), f"sealed audit {key}")
    validate_advantage_audit_result(value.get("natural_result"))
    if value["world_shuffle_applied"]:
        validate_advantage_audit_result(value.get("world_shuffle_result"))
        validate_world_shuffle_delta(value.get(
            "world_shuffle_delta_result"))
        if value["cohort_name"] != "natural":
            raise WorldAfterstateV1AuditControllerError(
                "sealed audit world-shuffle cohort drift")
    elif value["world_shuffle_result"] is not None \
            or value["world_shuffle_delta_result"] is not None \
            or value["cohort_name"] == "natural":
        raise WorldAfterstateV1AuditControllerError(
            "sealed audit world-shuffle absence drift")
    body = {key: item for key, item in value.items()
            if key != "result_sha256"}
    if value["result_sha256"] != _sha(body):
        raise WorldAfterstateV1AuditControllerError(
            "sealed audit result reconstruction drift")


def sealed_audit_result_bytes(value: Mapping[str, Any]) -> bytes:
    validate_sealed_audit_result(value)
    return canonical_json_bytes(value)


def reopen_sealed_audit_result_bytes(raw: bytes) -> dict[str, Any]:
    if type(raw) is not bytes:
        raise WorldAfterstateV1AuditControllerError(
            "sealed audit result byte type drift")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WorldAfterstateV1AuditControllerError(
            "sealed audit result is not canonical JSON") from exc
    if canonical_json_bytes(value) != raw:
        raise WorldAfterstateV1AuditControllerError(
            "sealed audit result is not canonical JSON")
    validate_sealed_audit_result(value)
    return value


__all__ = [
    "AUTHORITY", "WorldAfterstateV1AuditControllerError",
    "build_prediction_artifact_bytes", "evaluate_sealed_predictions",
    "reopen_prediction_artifact_bytes", "reopen_sealed_audit_result_bytes",
    "sealed_audit_result_bytes", "validate_sealed_audit_result",
]
