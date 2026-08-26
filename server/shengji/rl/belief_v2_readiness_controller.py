"""Durable pre-test proof that calibration and saved training curves reopen.

Calibration scoring needs only the selected checkpoint bytes.  Re-evaluating
every saved epoch before and after every later stage is expensive and adds no
new evidence.  This controller performs that full proof exactly once after the
calibration selection is sealed, then publishes a hash-bound receipt.  Test
scoring may authenticate the receipt and exact checkpoint identities cheaply;
it may not mint or bypass the receipt.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .belief_artifacts import publish_exclusive_bytes, stable_read_bytes
from .belief_contract import canonical_json_bytes
from .belief_v2_calibration_controller import (
    reopen_v2_calibration_selection,
    reopen_v2_calibration_selection_checkpoint_identity,
)
from .belief_v2_freeze import V2ExecutionFreezeV1, V2PipelineAdmissionV1
from .belief_v2_input_index_controller import reopen_training_input_index
from .belief_v2_progress import ProgressCallback
from .belief_v2_scoring import V2CohortModelsV1
from .belief_v2_scoring_controller import (
    reopen_checkpoint_scoring_cohorts,
)


READINESS_SCHEMA = "belief-v1-v2-calibration-readiness-v1"
READINESS_FILENAME = "receipt.json"


class BeliefV2ReadinessControllerError(ValueError):
    """The durable pre-test training/calibration proof drifted."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _model_rows(cohorts: tuple[V2CohortModelsV1, ...]) \
        -> list[dict[str, Any]]:
    return [{
        "cohort_id": cohort.cohort_id,
        "model_state_sha256s": list(cohort.model_sha256s),
    } for cohort in cohorts]


def _receipt(
        freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1, *,
        calibration: dict[str, Any],
        cohorts: tuple[V2CohortModelsV1, ...],
        training_input_sha256: str,
        qualification_plan_sha256: str,
        qualification_result_sha256: str,
        training_hashes: tuple[tuple[str, str], ...]) -> dict[str, Any]:
    expected_ids = tuple(row.cohort_id for row in freeze.cohorts)
    selected = calibration.get("selected_cohort_id") \
        if type(calibration) is dict else None
    if type(calibration) is not dict \
            or (calibration.get("calibration_passed") is True
                and selected not in expected_ids) \
            or (calibration.get("calibration_passed") is not True
                and selected is not None) \
            or tuple(row.cohort_id for row in cohorts) != expected_ids \
            or tuple(key for key, _ in training_hashes) != expected_ids \
            or calibration.get("training_manifest_sha256s") \
            != dict(training_hashes):
        raise BeliefV2ReadinessControllerError(
            "V2 readiness source population drift")
    return {
        "schema": READINESS_SCHEMA,
        "freeze_sha256": freeze.sha256(),
        "admission_sha256": admission.sha256(),
        "calibration_manifest_sha256": _sha256(
            canonical_json_bytes(calibration)),
        "selected_cohort_id": calibration["selected_cohort_id"],
        "training_input_sha256": training_input_sha256,
        "qualification_plan_sha256": qualification_plan_sha256,
        "qualification_result_sha256": qualification_result_sha256,
        "training_manifest_sha256s": dict(training_hashes),
        "cohort_model_state_sha256s": _model_rows(cohorts),
        "full_saved_epoch_curve_reopen_completed": True,
        "calibration_selection_reconstructed": True,
        "published_before_test_open": True,
        "test_split_opened": False,
        "retry_authorized": False,
        "sampler_implementation_authorized": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }


def _checkpoint_inputs(
        root: Path, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1):
    try:
        input_manifest, training_inputs = reopen_training_input_index(
            root / "training-input-index" / "result", freeze=freeze,
            admission=admission)
        cohorts, plan, qualification, training_hashes = (
            reopen_checkpoint_scoring_cohorts(
                root, freeze=freeze, admission=admission,
                training_inputs=training_inputs))
    except ValueError as exc:
        raise BeliefV2ReadinessControllerError(
            "V2 readiness checkpoint population refused") from exc
    return (input_manifest, training_inputs, cohorts, plan, qualification,
            training_hashes)


def _refuse_open_test_namespace(root: Path) -> None:
    for name in ("terminal", "terminal.partial"):
        path = root / name
        if path.exists() or path.is_symlink():
            raise BeliefV2ReadinessControllerError(
                "V2 readiness refuses an occupied test namespace")


def publish_v2_calibration_readiness(
        root: Path, *, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1,
        inventory: dict[str, Any], group_split: dict[str, Any],
        expected_calibration: dict[str, Any] | None = None,
        progress: ProgressCallback | None = None) \
        -> dict[str, Any]:
    """Run the full proof and atomically publish its pre-test receipt."""
    if not isinstance(root, Path) or root != Path(freeze.evidence_root):
        raise BeliefV2ReadinessControllerError(
            "V2 readiness evidence root drift")
    parent = root / "calibration"
    final = parent / "readiness"
    partial = parent / "readiness.partial"
    if final.exists() or partial.exists() or final.is_symlink() \
            or partial.is_symlink():
        raise BeliefV2ReadinessControllerError(
            "V2 readiness slot is occupied")
    _refuse_open_test_namespace(root)
    # This is the only expensive proof in the R5 pre-test path.  It re-scores
    # every persisted saved-epoch curve and independently reconstructs all
    # calibration result bytes before any readiness artifact can exist.
    try:
        calibration = reopen_v2_calibration_selection(
            parent / "selection", freeze=freeze, admission=admission,
            inventory=inventory, group_split=group_split,
            progress=progress)
    except ValueError as exc:
        raise BeliefV2ReadinessControllerError(
            "V2 readiness full calibration proof refused") from exc
    if expected_calibration is not None and calibration != expected_calibration:
        raise BeliefV2ReadinessControllerError(
            "V2 readiness expected calibration drift")
    (_input_manifest, training_inputs, cohorts, plan, qualification,
     training_hashes) = _checkpoint_inputs(root, freeze, admission)
    receipt = _receipt(
        freeze, admission, calibration=calibration, cohorts=cohorts,
        training_input_sha256=training_inputs.sha256(),
        qualification_plan_sha256=plan.sha256(),
        qualification_result_sha256=_sha256(
            qualification.canonical_bytes(plan)),
        training_hashes=training_hashes)
    # This is the load-bearing witness behind published_before_test_open.
    # Recheck after the full proof so the receipt cannot be minted around an
    # already consumed or concurrently occupied test-opening slot.
    _refuse_open_test_namespace(root)
    partial.mkdir(mode=0o700)
    publish_exclusive_bytes(
        partial / READINESS_FILENAME, canonical_json_bytes(receipt))
    os.rename(partial, final)
    descriptor = os.open(parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    reopened = reopen_v2_calibration_readiness(
        final, freeze=freeze, admission=admission,
        inventory=inventory, group_split=group_split)
    if reopened[0] != receipt:
        raise BeliefV2ReadinessControllerError(
            "V2 readiness post-publish drift")
    return receipt


def reopen_v2_calibration_readiness(
        directory: Path, *, freeze: V2ExecutionFreezeV1,
        admission: V2PipelineAdmissionV1,
        inventory: dict[str, Any], group_split: dict[str, Any]):
    """Authenticate readiness and return exact target-blind scoring inputs."""
    if not isinstance(directory, Path) or directory.is_symlink() \
            or not directory.is_dir() or directory.name != "readiness" \
            or {path.name for path in directory.iterdir()} \
            != {READINESS_FILENAME}:
        raise BeliefV2ReadinessControllerError(
            "V2 readiness directory population drift")
    raw = stable_read_bytes(directory / READINESS_FILENAME)
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefV2ReadinessControllerError(
            "V2 readiness receipt is not JSON") from exc
    if type(payload) is not dict or canonical_json_bytes(payload) != raw:
        raise BeliefV2ReadinessControllerError(
            "V2 readiness receipt is not canonical")
    root = Path(freeze.evidence_root)
    try:
        calibration = reopen_v2_calibration_selection_checkpoint_identity(
            root / "calibration" / "selection", freeze=freeze,
            admission=admission, inventory=inventory,
            group_split=group_split)
    except ValueError as exc:
        raise BeliefV2ReadinessControllerError(
            "V2 readiness calibration identity refused") from exc
    (input_manifest, training_inputs, cohorts, plan, qualification,
     training_hashes) = _checkpoint_inputs(root, freeze, admission)
    expected = _receipt(
        freeze, admission, calibration=calibration, cohorts=cohorts,
        training_input_sha256=training_inputs.sha256(),
        qualification_plan_sha256=plan.sha256(),
        qualification_result_sha256=_sha256(
            qualification.canonical_bytes(plan)),
        training_hashes=training_hashes)
    if payload != expected:
        raise BeliefV2ReadinessControllerError(
            "V2 readiness receipt reconstruction drift")
    return (payload, calibration, input_manifest, training_inputs, cohorts,
            plan, qualification, training_hashes)
