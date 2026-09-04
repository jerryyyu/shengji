"""Archived R4 training-package loader and authority-boundary tests."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import torch

import shengji.rl.belief_policy_models as MODELS
from shengji.rl.belief_artifacts import checkpoint_bundle_bytes
from shengji.rl.belief_checkpoint import build_model_checkpoint
from shengji.rl.belief_cohort import COHORT_SEEDS
from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.belief_model import new_from_scratch_model
from shengji.rl.belief_trainer import EpochTrainingReceiptV1, model_state_sha256
from shengji.rl.belief_v2_freeze import CONTROL_COHORT_ID, PRIMARY_COHORT_ID


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_sealed(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(0o400)


def _cohort_package(
        root: Path, *, cohort_id: str, freeze_sha: str,
        admission_sha: str, model_offset: float) -> None:
    directory = root / "training" / cohort_id
    checkpoint_rows = []
    trained_rows = []
    receipts = []
    losses = []
    for index, seed in enumerate(COHORT_SEEDS):
        model = new_from_scratch_model(seed)
        if model_offset:
            with torch.no_grad():
                next(model.parameters()).view(-1)[0].add_(
                    model_offset * (index + 1))
        state = model_state_sha256(model)
        receipt = EpochTrainingReceiptV1(
            epoch=1, batch_count=1, decision_count=1,
            active_label_count=1, mean_loss_nanonats=100 + index,
            batch_schema="batch-v1", history_transform="history-v1",
            label_transform="labels-v1", control_kind=cohort_id,
            decision_population_sha256="1" * 64,
            batch_schedule_sha256="2" * 64,
            model_state_sha256_before=state,
            model_state_sha256_after=state)
        checkpoint = build_model_checkpoint(
            model, initialization_seed=seed, selected_epoch=1,
            final_epoch_receipt=receipt)
        raw = checkpoint_bundle_bytes(checkpoint, receipt)
        filename = f"member-{index:02d}.checkpoint.bin"
        _write_sealed(directory / filename, raw)
        checkpoint_rows.append({
            "member_index": index, "filename": filename,
            "byte_count": len(raw), "sha256": _sha(raw)})
        trained_rows.append({
            "member_index": index, "initialization_seed": seed,
            "byte_count": len(raw), "bundle_sha256": _sha(raw)})
        receipts.append(receipt.to_dict())
        losses.append(100 + index)
    common = "3" * 64
    realization = "4" * 64 if cohort_id == PRIMARY_COHORT_ID else "5" * 64
    trained = {
        "schema": MODELS.TRAINED_COHORT_SCHEMA,
        "cohort_id": cohort_id, "cohort_kind": cohort_id,
        "realization_sha256": realization,
        "common_calibration_sha256": common,
        "training_device": "cpu",
        "initialization_seeds": list(COHORT_SEEDS),
        "epochs": [{
            "schema": "belief-v1-v2-training-epoch-curve-row-v1",
            "epoch": 1, "member_training_receipts": receipts,
            "member_calibration_loss_nanonats": losses,
            "cohort_mean_calibration_loss_nanonats": (
                sum(losses) // len(losses)),
        }],
        "epoch_count": 1, "selected_common_epoch": 1, "stop_epoch": 1,
        "stopped_for_patience": False,
        "label_control_changed_cell_count_per_epoch": (
            0 if cohort_id == PRIMARY_COHORT_ID else 1),
        "checkpoints": trained_rows,
        "common_epoch_calibration_source": "balanced-synthetic-only",
        "human_calibration_consumed_for_common_epoch": False,
        "contains_optimizer_resume_state": False,
        "contains_corpus_rows": False, "test_split_opened": False,
        "test_split_open_authorized": False,
        "sampler_implementation_authorized": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False, "truncated_by_deadline": False,
    }
    trained_raw = canonical_json_bytes(trained)
    _write_sealed(directory / "trained-cohort.json", trained_raw)
    stage = {
        "schema": MODELS.TRAINING_STAGE_SCHEMA,
        "freeze_sha256": freeze_sha, "admission_sha256": admission_sha,
        "cohort_id": cohort_id, "cohort_kind": cohort_id,
        "realization_sha256": realization,
        "primary_realization_sha256": "4" * 64,
        "common_calibration_sha256": common,
        "tensor_cache_stage_manifest_sha256": "6" * 64,
        "qualification_plan_sha256": "7" * 64,
        "qualification_result_sha256": "8" * 64,
        "selected_device": "cpu", "epoch_journal": {},
        "checkpoints": checkpoint_rows,
        "trained_manifest_filename": "trained-cohort.json",
        "trained_manifest_byte_count": len(trained_raw),
        "trained_manifest_sha256": _sha(trained_raw), "resources": {},
        "truncated_by_deadline": False, "deadline_refusal": None,
        "contains_optimizer_resume_state": True,
        "contains_corpus_rows": False, "test_split_opened": False,
        "test_split_open_authorized": False,
        "sampler_implementation_authorized": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }
    _write_sealed(directory / "manifest.json", canonical_json_bytes(stage))


def _package(tmp_path: Path) -> tuple[Path, str, str]:
    root = tmp_path / "r4-evidence"
    review_raw = b"authentic-review-marker\n"
    freeze = {
        "schema": "belief-v1-v2-offline-execution-freeze-v2",
        "run_id": "r4-test", "execution_git": "a" * 40,
        "source_manifest_sha256": "1" * 64, "source_bindings": [],
        "source_review_commit": "b" * 40,
        "protocol_sha256": "2" * 64, "schedule_sha256": "3" * 64,
        "seed_registry": {"registry_sha256": "4" * 64},
        "v1_route": {}, "human_inventory": {}, "population": {},
        "training_device_qualification": {}, "capacity": {},
        "cohorts": [], "gates": {}, "resource_caps": {}, "runtime": {},
        "review": {}, "evidence_root": str(root),
        "authority": {
            "design_freeze_authorized": True,
            "offline_pipeline_execution_authorized": False,
            "test_split_open_authorized": False,
            "sampler_implementation_authorized": False,
            "gameplay_strength_screen_authorized": False,
            "strength_claim_authorized": False,
            "promotion_authorized": False, "deployment_authorized": False,
        },
    }
    freeze_raw = canonical_json_bytes(freeze)
    freeze_sha = _sha(freeze_raw)
    admission = {
        "schema": "belief-v1-v2-offline-pipeline-admission-v1",
        "run_id": freeze["run_id"],
        "protocol_sha256": freeze["protocol_sha256"],
        "schedule_sha256": freeze["schedule_sha256"],
        "freeze_sha256": freeze_sha,
        "execution_git": freeze["execution_git"],
        "source_manifest_sha256": freeze["source_manifest_sha256"],
        "seed_registry_sha256": freeze["seed_registry"]["registry_sha256"],
        "review_commit": "c" * 40, "canonical_remote_tip": "c" * 40,
        "review_marker_sha256": _sha(review_raw),
        "evidence_root": str(root),
        "authority": {
            "capture_authorized": True,
            "reference_generation_authorized": True,
            "training_authorized": True,
            "one_test_split_open_authorized": True,
            "terminal_reconstruction_authorized": True,
            "retry_authorized": False,
            "sampler_implementation_authorized": False,
            "gameplay_strength_screen_authorized": False,
            "strength_claim_authorized": False,
            "promotion_authorized": False, "deployment_authorized": False,
        },
    }
    admission_raw = canonical_json_bytes(admission)
    admission_sha = _sha(admission_raw)
    _write_sealed(root / "freeze.json", freeze_raw)
    _write_sealed(root / "admission.json", admission_raw)
    _write_sealed(root / "review.md", review_raw)
    _cohort_package(
        root, cohort_id=PRIMARY_COHORT_ID, freeze_sha=freeze_sha,
        admission_sha=admission_sha, model_offset=0.0)
    _cohort_package(
        root, cohort_id=CONTROL_COHORT_ID, freeze_sha=freeze_sha,
        admission_sha=admission_sha, model_offset=0.001)
    return root, freeze_sha, admission_sha


def test_loader_opens_only_authenticated_training_packages(
        tmp_path, monkeypatch):
    root, freeze_sha, admission_sha = _package(tmp_path)
    opened = []
    original_read = MODELS.stable_read_bytes

    def recording_read(path):
        opened.append(path)
        return original_read(path)

    monkeypatch.setattr(MODELS, "stable_read_bytes", recording_read)
    value = MODELS.load_r4_policy_models(
        root, expected_freeze_sha256=freeze_sha,
        expected_admission_sha256=admission_sha)
    assert value.freeze_sha256 == freeze_sha
    assert len(value.primary.models) == len(COHORT_SEEDS)
    assert len(value.control.models) == len(COHORT_SEEDS)
    assert not set(value.primary.model_sha256s) \
        & set(value.control.model_sha256s)
    assert value.common_calibration_sha256 == "3" * 64
    relative = tuple(path.relative_to(root) for path in opened)
    assert len(relative) == 3 + 2 * (2 + len(COHORT_SEEDS))
    assert all(path.parts[0] == "training"
               or path.name in {"freeze.json", "admission.json", "review.md"}
               for path in relative)
    assert not any("test" in part.lower()
                   or "capture" in part.lower()
                   or "terminal" in part.lower()
                   for path in relative for part in path.parts)


def test_loader_refuses_checkpoint_and_manifest_rebinding(tmp_path):
    root, freeze_sha, admission_sha = _package(tmp_path)
    checkpoint = root / "training" / PRIMARY_COHORT_ID \
        / "member-00.checkpoint.bin"
    checkpoint.chmod(0o600)
    changed = bytearray(checkpoint.read_bytes())
    changed[-1] ^= 1
    checkpoint.write_bytes(bytes(changed))
    checkpoint.chmod(0o400)
    with pytest.raises(
            MODELS.BeliefPolicyModelsError,
            match="checkpoint byte binding"):
        MODELS.load_r4_policy_models(
            root, expected_freeze_sha256=freeze_sha,
            expected_admission_sha256=admission_sha)


def test_loader_refuses_review_and_authority_drift(tmp_path):
    root, freeze_sha, admission_sha = _package(tmp_path)
    review = root / "review.md"
    review.chmod(0o600)
    review.write_bytes(b"forged-review-marker\n")
    review.chmod(0o400)
    with pytest.raises(
            MODELS.BeliefPolicyModelsError,
            match="admission root binding"):
        MODELS.load_r4_policy_models(
            root, expected_freeze_sha256=freeze_sha,
            expected_admission_sha256=admission_sha)
