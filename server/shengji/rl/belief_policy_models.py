"""Authenticated, training-only R4 model loader for policy diagnostics.

The R4 terminal route did not support a scientific conclusion, but its frozen
training packages remain useful as explicitly diagnostic inputs.  This module
opens only the original freeze, admission, review marker, compact cohort
manifests, and selected target-free checkpoint bundles.  It has no path to a
capture/reference/test/terminal artifact and grants no gameplay authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .belief_artifacts import (
    reopen_checkpoint_bundle,
    reopen_epoch_receipt,
    stable_read_bytes,
)
from .belief_checkpoint import reopen_model_checkpoint
from .belief_cohort import COHORT_SEEDS
from .belief_contract import canonical_json_bytes
from .belief_training_schedule import select_common_epoch
from .belief_v2_accelerator import portable_model_state_sha256
from .belief_v2_freeze import (
    CONTROL_COHORT_ID,
    PRIMARY_COHORT_ID,
)
from .belief_v2_scoring import (
    V2CohortModelsV1,
    validate_v2_cohort_models,
)


TRAINING_STAGE_SCHEMA = "belief-v1-v2-training-stage-result-v1"
TRAINED_COHORT_SCHEMA = "belief-v1-v2-trained-cohort-artifacts-v1"


class BeliefPolicyModelsError(ValueError):
    """An R4 training package or its diagnostic authority boundary drifted."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_sha256(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _strict_json(raw: bytes, *, name: str) -> dict[str, Any]:
    if type(raw) is not bytes or not raw:
        raise BeliefPolicyModelsError(f"R4 {name} bytes are empty")

    def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in pairs:
            if key in result:
                raise BeliefPolicyModelsError(
                    f"R4 {name} contains a duplicate key")
            result[key] = value
        return result

    def reject_number(value: str) -> None:
        raise BeliefPolicyModelsError(
            f"R4 {name} contains an invalid number {value}")

    try:
        payload = json.loads(
            raw.decode("ascii"), object_pairs_hook=strict_object,
            parse_float=reject_number, parse_constant=reject_number)
    except BeliefPolicyModelsError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefPolicyModelsError(
            f"R4 {name} is not strict JSON") from exc
    if type(payload) is not dict or canonical_json_bytes(payload) != raw:
        raise BeliefPolicyModelsError(f"R4 {name} is not canonical")
    return payload


@dataclass(frozen=True)
class R4PolicyModelsV1:
    freeze_sha256: str
    admission_sha256: str
    review_marker_sha256: str
    common_calibration_sha256: str
    primary_trained_manifest_sha256: str
    control_trained_manifest_sha256: str
    primary: V2CohortModelsV1
    control: V2CohortModelsV1


_STAGE_KEYS = {
    "schema", "freeze_sha256", "admission_sha256", "cohort_id",
    "cohort_kind", "realization_sha256", "primary_realization_sha256",
    "common_calibration_sha256", "tensor_cache_stage_manifest_sha256",
    "qualification_plan_sha256", "qualification_result_sha256",
    "selected_device", "epoch_journal", "checkpoints",
    "trained_manifest_filename", "trained_manifest_byte_count",
    "trained_manifest_sha256", "resources", "truncated_by_deadline",
    "deadline_refusal", "contains_optimizer_resume_state",
    "contains_corpus_rows", "test_split_opened",
    "test_split_open_authorized", "sampler_implementation_authorized",
    "gameplay_strength_screen_authorized", "strength_claim_authorized",
    "deployment_authorized",
}

_TRAINED_KEYS = {
    "schema", "cohort_id", "cohort_kind", "realization_sha256",
    "common_calibration_sha256", "training_device",
    "initialization_seeds", "epochs", "epoch_count",
    "selected_common_epoch", "stop_epoch", "stopped_for_patience",
    "label_control_changed_cell_count_per_epoch", "checkpoints",
    "common_epoch_calibration_source",
    "human_calibration_consumed_for_common_epoch",
    "contains_optimizer_resume_state", "contains_corpus_rows",
    "test_split_opened", "test_split_open_authorized",
    "sampler_implementation_authorized",
    "gameplay_strength_screen_authorized", "strength_claim_authorized",
    "deployment_authorized", "truncated_by_deadline",
}

_CURVE_KEYS = {
    "schema", "epoch", "member_training_receipts",
    "member_calibration_loss_nanonats",
    "cohort_mean_calibration_loss_nanonats",
}


def _checkpoint_rows(
        rows: Any, *, cohort_dir: Path) -> tuple[bytes, ...]:
    if type(rows) is not list or len(rows) != len(COHORT_SEEDS):
        raise BeliefPolicyModelsError("R4 checkpoint row population drift")
    bundles = []
    for index, row in enumerate(rows):
        filename = f"member-{index:02d}.checkpoint.bin"
        if type(row) is not dict or set(row) != {
                "member_index", "filename", "byte_count", "sha256"} \
                or row["member_index"] != index \
                or row["filename"] != filename \
                or type(row["byte_count"]) is not int \
                or row["byte_count"] <= 0 \
                or not _is_sha256(row["sha256"]):
            raise BeliefPolicyModelsError("R4 checkpoint row drift")
        raw = stable_read_bytes(cohort_dir / filename)
        if len(raw) != row["byte_count"] or _sha256(raw) != row["sha256"]:
            raise BeliefPolicyModelsError("R4 checkpoint byte binding drift")
        bundles.append(raw)
    return tuple(bundles)


def _load_cohort(
        cohort_dir: Path, *, cohort_id: str, freeze_sha256: str,
        admission_sha256: str) \
        -> tuple[V2CohortModelsV1, str, str]:
    stage_raw = stable_read_bytes(cohort_dir / "manifest.json")
    stage = _strict_json(stage_raw, name=f"{cohort_id} stage manifest")
    if set(stage) != _STAGE_KEYS \
            or stage["schema"] != TRAINING_STAGE_SCHEMA \
            or stage["freeze_sha256"] != freeze_sha256 \
            or stage["admission_sha256"] != admission_sha256 \
            or stage["cohort_id"] != cohort_id \
            or stage["cohort_kind"] != cohort_id \
            or stage["trained_manifest_filename"] != "trained-cohort.json" \
            or stage["selected_device"] != "cpu" \
            or stage["truncated_by_deadline"] is not False \
            or stage["deadline_refusal"] is not None \
            or stage["contains_optimizer_resume_state"] is not True \
            or any(stage[key] is not False for key in (
                "contains_corpus_rows", "test_split_opened",
                "test_split_open_authorized",
                "sampler_implementation_authorized",
                "gameplay_strength_screen_authorized",
                "strength_claim_authorized", "deployment_authorized")):
        raise BeliefPolicyModelsError("R4 training stage identity drift")

    trained_raw = stable_read_bytes(cohort_dir / "trained-cohort.json")
    if type(stage["trained_manifest_byte_count"]) is not int \
            or len(trained_raw) != stage["trained_manifest_byte_count"] \
            or _sha256(trained_raw) != stage["trained_manifest_sha256"]:
        raise BeliefPolicyModelsError("R4 trained manifest binding drift")
    trained = _strict_json(
        trained_raw, name=f"{cohort_id} trained manifest")
    if set(trained) != _TRAINED_KEYS \
            or trained["schema"] != TRAINED_COHORT_SCHEMA \
            or trained["cohort_id"] != cohort_id \
            or trained["cohort_kind"] != cohort_id \
            or trained["realization_sha256"] != stage["realization_sha256"] \
            or trained["common_calibration_sha256"] \
            != stage["common_calibration_sha256"] \
            or trained["training_device"] != "cpu" \
            or trained["initialization_seeds"] != list(COHORT_SEEDS) \
            or trained["common_epoch_calibration_source"] \
            != "balanced-synthetic-only" \
            or trained["human_calibration_consumed_for_common_epoch"] \
            is not False \
            or trained["truncated_by_deadline"] is not False \
            or any(trained[key] is not False for key in (
                "contains_optimizer_resume_state", "contains_corpus_rows",
                "test_split_opened", "test_split_open_authorized",
                "sampler_implementation_authorized",
                "gameplay_strength_screen_authorized",
                "strength_claim_authorized", "deployment_authorized")):
        raise BeliefPolicyModelsError("R4 trained cohort identity drift")

    epochs = trained["epochs"]
    if type(epochs) is not list or not epochs \
            or trained["epoch_count"] != len(epochs) \
            or trained["stop_epoch"] != len(epochs) \
            or type(trained["selected_common_epoch"]) is not int \
            or not 1 <= trained["selected_common_epoch"] <= len(epochs) \
            or type(trained["stopped_for_patience"]) is not bool \
            or type(trained[
                "label_control_changed_cell_count_per_epoch"]) is not int \
            or trained[
                "label_control_changed_cell_count_per_epoch"] < 0:
        raise BeliefPolicyModelsError("R4 trained epoch population drift")

    receipts_by_epoch = []
    losses_by_member: list[list[int]] = [list() for _ in COHORT_SEEDS]
    for epoch, row in enumerate(epochs, 1):
        if type(row) is not dict or set(row) != _CURVE_KEYS \
                or row["schema"] \
                != "belief-v1-v2-training-epoch-curve-row-v1" \
                or row["epoch"] != epoch \
                or type(row["member_training_receipts"]) is not list \
                or len(row["member_training_receipts"]) \
                != len(COHORT_SEEDS) \
                or type(row["member_calibration_loss_nanonats"]) is not list \
                or len(row["member_calibration_loss_nanonats"]) \
                != len(COHORT_SEEDS) \
                or any(type(value) is not int or value < 0
                       for value in row[
                           "member_calibration_loss_nanonats"]) \
                or row["cohort_mean_calibration_loss_nanonats"] \
                != sum(row["member_calibration_loss_nanonats"]) \
                // len(COHORT_SEEDS):
            raise BeliefPolicyModelsError("R4 training curve row drift")
        try:
            receipts = tuple(reopen_epoch_receipt(
                canonical_json_bytes(receipt))
                for receipt in row["member_training_receipts"])
        except ValueError as exc:
            raise BeliefPolicyModelsError(
                "R4 training receipt reopen refused") from exc
        if any(receipt.epoch != epoch for receipt in receipts):
            raise BeliefPolicyModelsError("R4 training receipt epoch drift")
        receipts_by_epoch.append(receipts)
        for losses, value in zip(
                losses_by_member,
                row["member_calibration_loss_nanonats"], strict=True):
            losses.append(value)
    if any(left[index].model_state_sha256_after
           != right[index].model_state_sha256_before
           for left, right in zip(
               receipts_by_epoch, receipts_by_epoch[1:])
           for index in range(len(COHORT_SEEDS))):
        raise BeliefPolicyModelsError("R4 training receipt chain drift")
    decision = select_common_epoch(
        tuple(tuple(losses) for losses in losses_by_member))
    if trained["selected_common_epoch"] != decision.selected_epoch \
            or trained["stop_epoch"] != decision.stop_epoch \
            or trained["stopped_for_patience"] \
            is not decision.stopped_for_patience:
        raise BeliefPolicyModelsError("R4 common epoch decision drift")

    bundles = _checkpoint_rows(stage["checkpoints"], cohort_dir=cohort_dir)
    trained_checkpoints = trained["checkpoints"]
    if type(trained_checkpoints) is not list \
            or len(trained_checkpoints) != len(COHORT_SEEDS):
        raise BeliefPolicyModelsError(
            "R4 trained checkpoint population drift")
    selected_receipts = receipts_by_epoch[
        trained["selected_common_epoch"] - 1]
    models = []
    model_sha256s = []
    for index, (raw, row, expected_receipt) in enumerate(zip(
            bundles, trained_checkpoints, selected_receipts, strict=True)):
        if type(row) is not dict or set(row) != {
                "member_index", "initialization_seed", "byte_count",
                "bundle_sha256"} \
                or row["member_index"] != index \
                or row["initialization_seed"] != COHORT_SEEDS[index] \
                or row["byte_count"] != len(raw) \
                or row["bundle_sha256"] != _sha256(raw):
            raise BeliefPolicyModelsError(
                "R4 trained checkpoint row drift")
        try:
            checkpoint, receipt = reopen_checkpoint_bundle(raw)
            model = reopen_model_checkpoint(
                checkpoint, final_epoch_receipt=receipt)
        except ValueError as exc:
            raise BeliefPolicyModelsError(
                "R4 selected checkpoint reopen refused") from exc
        digest = portable_model_state_sha256(model)
        if receipt != expected_receipt \
                or digest != receipt.model_state_sha256_after:
            raise BeliefPolicyModelsError(
                "R4 selected checkpoint receipt drift")
        model.eval()
        models.append(model)
        model_sha256s.append(digest)
    result = V2CohortModelsV1(
        cohort_id=cohort_id, models=tuple(models),
        model_sha256s=tuple(model_sha256s))
    try:
        validate_v2_cohort_models(result)
    except ValueError as exc:
        raise BeliefPolicyModelsError("R4 scoring cohort refused") from exc
    return result, stage["common_calibration_sha256"], _sha256(trained_raw)


def load_r4_policy_models(
        root: Path, *, expected_freeze_sha256: str,
        expected_admission_sha256: str) -> R4PolicyModelsV1:
    """Open only the named R4 training packages needed by the diagnostic."""
    if not isinstance(root, Path) or not root.is_absolute() \
            or not _is_sha256(expected_freeze_sha256) \
            or not _is_sha256(expected_admission_sha256):
        raise BeliefPolicyModelsError("R4 model root/identity drift")
    freeze_raw = stable_read_bytes(root / "freeze.json")
    review_raw = stable_read_bytes(root / "review.md")
    admission_raw = stable_read_bytes(root / "admission.json")
    if _sha256(freeze_raw) != expected_freeze_sha256 \
            or _sha256(admission_raw) != expected_admission_sha256:
        raise BeliefPolicyModelsError("R4 freeze/admission byte drift")
    # The archived R4 freeze predates fields added to the live V2 parser.  Its
    # exact bytes are the contract: reopen the canonical archival schema here
    # instead of silently interpreting it through a newer mutable schema.
    freeze = _strict_json(freeze_raw, name="archived freeze")
    admission = _strict_json(admission_raw, name="archived admission")
    freeze_authority = freeze.get("authority")
    admission_authority = admission.get("authority")
    if set(freeze) != {
            "schema", "run_id", "execution_git", "source_manifest_sha256",
            "source_bindings", "source_review_commit", "protocol_sha256",
            "schedule_sha256", "seed_registry", "v1_route",
            "human_inventory", "population", "training_device_qualification",
            "capacity", "cohorts", "gates", "resource_caps", "runtime",
            "review", "evidence_root", "authority"} \
            or freeze["schema"] \
            != "belief-v1-v2-offline-execution-freeze-v2" \
            or freeze["evidence_root"] != str(root) \
            or type(freeze_authority) is not dict \
            or freeze_authority != {
                "design_freeze_authorized": True,
                "offline_pipeline_execution_authorized": False,
                "test_split_open_authorized": False,
                "sampler_implementation_authorized": False,
                "gameplay_strength_screen_authorized": False,
                "strength_claim_authorized": False,
                "promotion_authorized": False,
                "deployment_authorized": False}:
        raise BeliefPolicyModelsError("R4 archived freeze identity drift")
    if set(admission) != {
            "schema", "run_id", "protocol_sha256", "schedule_sha256",
            "freeze_sha256", "execution_git", "source_manifest_sha256",
            "seed_registry_sha256", "review_commit",
            "canonical_remote_tip", "review_marker_sha256",
            "evidence_root", "authority"} \
            or admission["schema"] \
            != "belief-v1-v2-offline-pipeline-admission-v1" \
            or admission["freeze_sha256"] != expected_freeze_sha256 \
            or admission["evidence_root"] != str(root) \
            or admission["review_marker_sha256"] != _sha256(review_raw) \
            or admission["run_id"] != freeze["run_id"] \
            or admission["execution_git"] != freeze["execution_git"] \
            or admission["protocol_sha256"] != freeze["protocol_sha256"] \
            or admission["schedule_sha256"] != freeze["schedule_sha256"] \
            or admission["source_manifest_sha256"] \
            != freeze["source_manifest_sha256"] \
            or admission["seed_registry_sha256"] \
            != freeze["seed_registry"]["registry_sha256"] \
            or type(admission_authority) is not dict \
            or admission_authority != {
                "capture_authorized": True,
                "reference_generation_authorized": True,
                "training_authorized": True,
                "one_test_split_open_authorized": True,
                "terminal_reconstruction_authorized": True,
                "retry_authorized": False,
                "sampler_implementation_authorized": False,
                "gameplay_strength_screen_authorized": False,
                "strength_claim_authorized": False,
                "promotion_authorized": False,
                "deployment_authorized": False}:
        raise BeliefPolicyModelsError("R4 admission root binding drift")
    primary, primary_common, primary_manifest = _load_cohort(
        root / "training" / PRIMARY_COHORT_ID,
        cohort_id=PRIMARY_COHORT_ID,
        freeze_sha256=expected_freeze_sha256,
        admission_sha256=expected_admission_sha256)
    control, control_common, control_manifest = _load_cohort(
        root / "training" / CONTROL_COHORT_ID,
        cohort_id=CONTROL_COHORT_ID,
        freeze_sha256=expected_freeze_sha256,
        admission_sha256=expected_admission_sha256)
    if primary_common != control_common \
            or set(primary.model_sha256s) & set(control.model_sha256s):
        raise BeliefPolicyModelsError(
            "R4 primary/control training package drift")
    result = R4PolicyModelsV1(
        freeze_sha256=expected_freeze_sha256,
        admission_sha256=expected_admission_sha256,
        review_marker_sha256=_sha256(review_raw),
        common_calibration_sha256=primary_common,
        primary_trained_manifest_sha256=primary_manifest,
        control_trained_manifest_sha256=control_manifest,
        primary=primary, control=control)
    if any(getattr(result, name) is None for name in (
            "primary", "control")):
        raise BeliefPolicyModelsError("R4 loaded model package drift")
    return result
