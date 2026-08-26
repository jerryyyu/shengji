"""Durability, separation, and admission witnesses for V2 stages."""

from __future__ import annotations

import hashlib
import io
import json
import os
import random
import shutil
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

import shengji.rl.belief_v2_cohort_training as COHORT_STAGE
import shengji.rl.belief_v2_cache_import as CACHE_IMPORT
import shengji.rl.belief_v2_calibration_controller as CALIBRATION_STAGE
import shengji.rl.belief_v2_controller as V2_CONTROLLER
import shengji.rl.belief_v2_input_index_controller as INPUT_INDEX_STAGE
import shengji.rl.belief_v2_human_reference_controller as HUMAN_REF_STAGE
import shengji.rl.belief_v2_readiness_controller as READINESS_STAGE
import shengji.rl.belief_v2_tensor_cache_controller as CACHE_STAGE
import shengji.rl.belief_v2_terminal_controller as TERMINAL_STAGE
import shengji.rl.belief_v2_training_controller as TRAINING_STAGE
from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.rl.belief_capture import CHAMPION_POLICY, _capture_with_policies
from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.belief_v2_controller import (
    BeliefV2ControllerError,
    reopen_actor_capture_lane_manifest,
    reopen_capture_lane,
    reopen_reference_lane,
    reopen_reference_lane_manifest,
    reopen_synthetic_training_lane_examples,
    run_capture_lane,
    run_reference_lane,
)
from shengji.rl.belief_v2_execution_identity import (
    V2InstalledDistributionV1,
    V2RuntimeProfileV1,
    V2SourceBindingV1,
    source_manifest_sha256,
)
from shengji.rl.belief_v2_device_qualification import (
    V2DeviceQualificationArmV1,
    build_qualification_plan,
    derive_qualification_result,
    qualification_protocol_sha256,
)
from shengji.rl.belief_v2_accelerator import V2TrainingDeviceProfileV1
from shengji.rl.belief_v2_device_controller import (
    BeliefV2DeviceControllerError,
    reopen_device_qualification,
    run_device_qualification,
)
from shengji.rl.belief_v2_deadline import (
    BeliefV2DeadlineError,
    V2DeadlineRefusalV1,
    publish_deadline_refusal,
    reopen_deadline_refusal,
)
from shengji.rl.belief_v2_freeze import (
    ALL_HUMAN_TRAIN_DECISIONS,
    ALL_SYNTHETIC_TRAIN_DECISIONS,
    MIXED_SYNTHETIC_TRAIN_DECISIONS,
    MIXED_WORK_RULE,
    NO_HUMAN_DECISIONS,
    PRIMARY_WORK_RULE,
    SCALE_SYNTHETIC_TRAIN_DECISIONS,
    SCALE_WORK_RULE,
    V2CohortPlanV1,
    V2ExecutionFreezeV1,
    V2PipelineAdmissionV1,
    V2ResourceCapsV1,
    REVIEW_PREFIX,
    expected_execution_review_claim,
    pipeline_consumption_tombstone_bytes,
)
from shengji.rl.belief_v2_human_controller import (
    BeliefV2HumanControllerError,
    reopen_human_training_group_examples,
    run_human_group_capture,
)
from shengji.rl.belief_v2_human_corpus import (
    V2HumanReplaySummaryV1,
    V2HumanGroupCaptureV1,
    capture_human_corpus_pair,
    reopen_human_actor_row,
)
from shengji.rl.belief_v2_human_reference import (
    V2HumanReferenceDecisionV1,
    V2HumanReferenceGroupV1,
)
from shengji.rl.belief_v2_human_reference_controller import (
    reopen_human_reference_group,
    reopen_human_reference_group_manifest,
    run_human_reference_group,
)
from shengji.rl.belief_v2_input_index_controller import (
    run_training_input_index,
)
from shengji.rl.belief_v2_tensor_cache_controller import (
    reopen_tensor_cache_resource_refusal,
    reopen_training_tensor_cache,
    run_training_tensor_cache,
)
from shengji.rl.belief_v2_cache_import import V2TensorCacheImportSpecV1
from shengji.rl.belief_v2_human_inventory import (
    H0_INVENTORY_SCHEMA,
    _component_digest,
    _group_digest,
    build_h0_group_split,
    group_split_bytes,
    inventory_bytes,
)
from shengji.rl.belief_v2_protocol import (
    v2_policy_seeds,
    v2_round_coordinates,
)
from shengji.rl.belief_v2_progress import (
    PROGRESS_PREFIX,
    V2ProgressReporter,
)
from shengji.rl.belief_v2_schedule import (
    realize_v2_cohorts,
    realize_v2_common_calibration,
    training_row,
)
from shengji.rl.belief_v2_scoring_controller import (
    BeliefV2ScoringControllerError,
    reopen_human_scoring_rounds,
    reopen_synthetic_scoring_round,
)
from shengji.rl.belief_v2_scoring import v2_scoring_actor
from shengji.rl.belief_v2_statistics import V2RoundScoreV1
from shengji.rl.belief_refc_capture import (
    capture_ref_c_worlds_from_bound_actor,
)
from shengji.rl.belief_v2_training import (
    build_human_training_example,
    build_synthetic_training_example,
    collate_v2_label_control_examples,
    collate_v2_training_examples,
)
from shengji.rl.belief_v2_training_controller import (
    BeliefV2TrainingControllerError,
    _resource_row,
    reopen_training_cohort,
    run_training_cohort,
)


def _sha(char: str) -> str:
    return char * 64


def _cache_derived_manifest(*, human_group_char: str = "1",
                            human_train_char: str = "2") -> dict:
    return {
        "schema": "belief-v1-v2-streaming-training-inputs-v1",
        "synthetic_train_decision_count": 10,
        "synthetic_train_population_sha256": _sha("3"),
        "synthetic_calibration_decision_count": 4,
        "synthetic_calibration_population_sha256": _sha("4"),
        "human_train_decision_count": 2,
        "human_train_population_sha256": _sha(human_train_char),
        "source_population_sha256": _sha("5"),
        "control_changed_cell_count": 8,
        "common_calibration_sha256": _sha("6"),
        "human_group_manifest_sha256s": [_sha(human_group_char)],
        "cohort_plan_set_sha256": _sha("7"),
        "cohort_realization_set_sha256": _sha("8"),
        "cohorts": [{
            "cohort_id": "synthetic-primary",
            "kind": "synthetic-primary",
            "realization_sha256": _sha("9"),
            "decision_count": 10,
            "active_label_count": 20,
        }],
        "resident_model_array_bytes": 0,
        "one_batch_at_a_time": True,
        "synthetic_test_targets_opened": False,
        "human_test_targets_opened": False,
        "training_authorized_by_this_artifact": False,
        "test_split_open_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }


def _cache_derived_sha(manifest: dict) -> str:
    return hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()


def _bindings():
    paths = sorted((
        "BELIEF_V1_SPEC.md", "BELIEF_V1_V2_DESIGN.md",
        "server/pyproject.toml", "server/setup.py", "server/uv.lock",
        "server/scripts/belief_v2_worker.py",
        "server/shengji/__init__.py"))
    return tuple(V2SourceBindingV1(
        path=path, byte_count=index + 1,
        sha256=f"{index + 1:x}" * 64)
        for index, path in enumerate(paths))


def _distribution(name, char):
    return V2InstalledDistributionV1(
        name=name, version="1.0", root=f"/runtime/{name}",
        file_count=10, payload_sha256=_sha(char))


def _runtime():
    return V2RuntimeProfileV1(
        hostname="host", operating_system="system", machine="machine",
        cpu_count=16, memory_bytes=32 * 1024**3,
        boot_identity=_sha("8"), python_executable="/runtime/python",
        python_executable_sha256=_sha("9"), python_version="3.14.4",
        torch=_distribution("torch", "a"),
        torch_config_sha256=_sha("b"),
        numpy=_distribution("numpy", "c"),
        native_path="/runtime/_fast.so", native_sha256=_sha("d"),
        required_environment=(
            ("PYTHONDONTWRITEBYTECODE", "1"),
            ("PYTHONHASHSEED", "0"),
            ("SHENGJI_FAST", "1"),
            ("SHENGJI_REQUIRE_VOIDS", "1")))


def _device_profile():
    return V2TrainingDeviceProfileV1(
        requested_device="mps", device_type="mps", device_index=None,
        hardware_name="Apple-arm64-test", total_memory_bytes=12 * 1024**3,
        runtime_version="macOS-test", compute_capability_major=None,
        compute_capability_minor=None)


def _cohorts():
    return (
        V2CohortPlanV1(
            cohort_id="synthetic-primary", kind="synthetic-primary",
            synthetic_selection_rule=ALL_SYNTHETIC_TRAIN_DECISIONS,
            synthetic_fraction_numerator=1,
            synthetic_fraction_denominator=1,
            human_selection_rule=NO_HUMAN_DECISIONS,
            work_match_rule=PRIMARY_WORK_RULE,
            comparator_cohort_id=None),
        V2CohortPlanV1(
            cohort_id="hard-geometry-label-permutation",
            kind="hard-geometry-label-permutation",
            synthetic_selection_rule=ALL_SYNTHETIC_TRAIN_DECISIONS,
            synthetic_fraction_numerator=1,
            synthetic_fraction_denominator=1,
            human_selection_rule=NO_HUMAN_DECISIONS,
            work_match_rule=PRIMARY_WORK_RULE,
            comparator_cohort_id="synthetic-primary"),
        V2CohortPlanV1(
            cohort_id="human-mixture", kind="human-mixture",
            synthetic_selection_rule=MIXED_SYNTHETIC_TRAIN_DECISIONS,
            synthetic_fraction_numerator=1,
            synthetic_fraction_denominator=1,
            human_selection_rule=ALL_HUMAN_TRAIN_DECISIONS,
            work_match_rule=MIXED_WORK_RULE,
            comparator_cohort_id="synthetic-primary"),
        V2CohortPlanV1(
            cohort_id="synthetic-scale-50", kind="synthetic-scale",
            synthetic_selection_rule=SCALE_SYNTHETIC_TRAIN_DECISIONS,
            synthetic_fraction_numerator=1,
            synthetic_fraction_denominator=2,
            human_selection_rule=NO_HUMAN_DECISIONS,
            work_match_rule=SCALE_WORK_RULE,
            comparator_cohort_id="synthetic-primary"),
    )


def _freeze(root: Path):
    bindings = _bindings()
    return V2ExecutionFreezeV1(
        execution_git="a" * 40,
        source_manifest_sha256=source_manifest_sha256("a" * 40, bindings),
        source_bindings=bindings, runtime=_runtime(),
        source_review_commit="b" * 40,
        v1_terminal_route="v1-pass-to-b3",
        v1_terminal_result_sha256=_sha("b"),
        v1_resource_receipt_sha256=_sha("c"),
        v1_resource_failure_receipt_sha256=None,
        v2_reentry_rationale_sha256=None,
        h0_inventory_sha256=_sha("d"),
        h0_source_manifest_sha256=_sha("e"),
        h0_source_digest_population_sha256=_sha("f"),
        human_group_split_sha256=_sha("0"),
        human_group_count=30, human_train_group_count=24,
        human_calibration_group_count=3, human_test_group_count=3,
        human_complete_round_count=122,
        human_eligible_decision_count=2830,
        human_train_eligible_decision_count=2240,
        human_calibration_eligible_decision_count=416,
        human_test_eligible_decision_count=174,
        preflight_result_sha256=_sha("1"),
        preflight_runtime_sha256=_sha("2"),
        deadline_estimate_receipt_sha256=_sha("a"),
        seed_registry_sha256=_sha("3"),
        seed_candidate_report_sha256=_sha("4"),
        training_candidate_device="mps",
        training_device_profile=_device_profile(),
        device_qualification_protocol_sha256=(
            qualification_protocol_sha256("mps")),
        cohorts=_cohorts(),
        resource_caps=V2ResourceCapsV1(
            capture_core_hours=64, capture_wall_seconds=14_400,
            capture_bytes=16 * 1024**3,
            reference_core_hours=16, reference_wall_seconds=7_200,
            reference_bytes=16 * 1024**3,
            training_device_hours=128, training_wall_seconds=86_400,
            training_bytes=32 * 1024**3,
            training_host_memory_bytes=24 * 1024**3,
            training_device_memory_bytes=12 * 1024**3,
            capture_next_unit_wall_estimate_nanoseconds=20_000_000_000,
            reference_next_unit_wall_estimate_nanoseconds=5_000_000_000,
            training_next_epoch_wall_estimate_nanoseconds=60_000_000_000,
            deadline_safety_reserve_nanoseconds=1_000_000_000),
        evidence_root=str(root))


def _cpu_only_freeze(root: Path):
    profile = V2TrainingDeviceProfileV1(
        requested_device="cpu", device_type="cpu", device_index=None,
        hardware_name="CPU-x86_64-test", total_memory_bytes=32 * 1024**3,
        runtime_version="Linux-test", compute_capability_major=None,
        compute_capability_minor=None)
    return replace(
        _freeze(root), training_candidate_device="cpu",
        training_device_profile=profile,
        device_qualification_protocol_sha256=(
            qualification_protocol_sha256("cpu")))


def test_stage_gate_refuses_live_accelerator_identity_drift(
        monkeypatch, tmp_path):
    root = tmp_path / "evidence"
    root.mkdir()
    freeze = _freeze(root.resolve())
    admission = V2PipelineAdmissionV1(
        freeze_sha256=freeze.sha256(), execution_git=freeze.execution_git,
        source_manifest_sha256=freeze.source_manifest_sha256,
        seed_registry_sha256=freeze.seed_registry_sha256,
        review_commit="c" * 40, canonical_remote_tip="d" * 40,
        review_marker_sha256=_sha("5"), evidence_root=str(root.resolve()))
    monkeypatch.setattr(V2_CONTROLLER, "validate_execution_freeze",
                        lambda value: None)
    monkeypatch.setattr(V2_CONTROLLER, "reauthenticate_pipeline_admission",
                        lambda *args, **kwargs: None)
    monkeypatch.setattr(V2_CONTROLLER, "validate_live_execution",
                        lambda *args, **kwargs: None)
    monkeypatch.setattr(
        V2_CONTROLLER, "build_training_device_profile",
        lambda value: replace(
            freeze.training_device_profile,
            hardware_name="different-accelerator"))
    with pytest.raises(BeliefV2ControllerError,
                       match="stage admission refused"):
        V2_CONTROLLER._stage_gate(
            root=root.resolve(), repo=tmp_path.resolve(), freeze=freeze,
            admission=admission, review_marker=b"review\n")


def _admission(freeze):
    return V2PipelineAdmissionV1(
        freeze_sha256=freeze.sha256(), execution_git=freeze.execution_git,
        source_manifest_sha256=freeze.source_manifest_sha256,
        seed_registry_sha256=freeze.seed_registry_sha256,
        review_commit="c" * 40, canonical_remote_tip="d" * 40,
        review_marker_sha256=_sha("e"), evidence_root=freeze.evidence_root)


def test_tensor_cache_import_spec_reopens_spent_source_and_tombstone(
        tmp_path, monkeypatch):
    source = (tmp_path / "spent-source").resolve()
    destination = (tmp_path / "fresh-destination").resolve()
    source.mkdir(mode=0o700)
    destination.mkdir(mode=0o700)
    old_freeze = _cpu_only_freeze(source)
    review_marker = (
        REVIEW_PREFIX.encode("ascii")
        + canonical_json_bytes(expected_execution_review_claim(old_freeze)))
    old_admission = V2PipelineAdmissionV1(
        freeze_sha256=old_freeze.sha256(),
        execution_git=old_freeze.execution_git,
        source_manifest_sha256=old_freeze.source_manifest_sha256,
        seed_registry_sha256=old_freeze.seed_registry_sha256,
        review_commit="c" * 40, canonical_remote_tip="d" * 40,
        review_marker_sha256=hashlib.sha256(review_marker).hexdigest(),
        evidence_root=str(source))
    cache_parent = source / "training-tensor-cache"
    cache_parent.mkdir(mode=0o700)
    cache_root = cache_parent / "result.partial"
    cache_root.mkdir(mode=0o700)
    for name in CACHE_IMPORT.EXPECTED_CACHE_DIRECTORIES:
        (cache_root / name).mkdir(mode=0o700)
    index_root = source / "training-input-index" / "result"
    index_root.mkdir(mode=0o700, parents=True)

    def immutable(path: Path, raw: bytes) -> str:
        path.write_bytes(raw)
        path.chmod(0o400)
        return hashlib.sha256(raw).hexdigest()

    freeze_sha = immutable(source / "freeze.json",
                           old_freeze.canonical_bytes())
    review_sha = immutable(source / "review.md", review_marker)
    admission_sha = immutable(source / "admission.json",
                              old_admission.canonical_bytes())
    tombstone_path = source.with_name(source.name + ".consumed.json")
    tombstone_raw = pipeline_consumption_tombstone_bytes(old_admission)
    tombstone_sha = immutable(tombstone_path, tombstone_raw)
    index_raw = b"index\n"
    index_sha = immutable(index_root / "index.json", index_raw)
    derived_manifest = _cache_derived_manifest()
    derived_input_sha = _cache_derived_sha(derived_manifest)
    index_manifest_sha = immutable(
        index_root / "manifest.json", canonical_json_bytes({
            "schema": "belief-v1-v2-training-input-index-stage-v1",
            "freeze_sha256": old_freeze.sha256(),
            "admission_sha256": old_admission.sha256(),
            "index_byte_count": len(index_raw),
            "index_sha256": index_sha,
            "derived_input_sha256": derived_input_sha,
            "derived_manifest": derived_manifest,
            "synthetic_test_targets_opened": False,
            "human_test_targets_opened": False,
            "training_authorized_by_this_artifact": False,
            "test_split_open_authorized": False,
            "strength_claim_authorized": False,
            "deployment_authorized": False,
        }))
    stage_start_sha = immutable(
        cache_root / "stage-start.json", canonical_json_bytes({
            "schema": "belief-v1-v2-training-tensor-cache-start-v1",
            "freeze_sha256": old_freeze.sha256(),
            "admission_sha256": old_admission.sha256(),
            "training_input_index_sha256": index_sha,
            "boot_identity": old_freeze.runtime.boot_identity,
            "started_monotonic_nanoseconds": 1,
            "retry_authorized": False,
            "test_split_open_authorized": False,
            "strength_claim_authorized": False,
            "deployment_authorized": False,
        }))
    runtime_sha = hashlib.sha256(canonical_json_bytes(
        old_freeze.runtime.to_dict())).hexdigest()
    child = {
        name: hashlib.sha256(name.encode("ascii")).hexdigest()
        for name in CACHE_IMPORT.EXPECTED_CACHE_DIRECTORIES}
    spec_payload = {
        "schema": CACHE_IMPORT.CACHE_IMPORT_SPEC_SCHEMA,
        "destination_evidence_root": str(destination),
        "source_evidence_root": str(source),
        "source_cache_root": str(cache_root),
        "source_execution_git": old_freeze.execution_git,
        "source_freeze_sha256": freeze_sha,
        "source_admission_sha256": admission_sha,
        "source_review_marker_sha256": review_sha,
        "source_consumption_tombstone_sha256": tombstone_sha,
        "source_input_index_sha256": index_sha,
        "source_input_index_manifest_sha256": index_manifest_sha,
        "source_runtime_profile_sha256": runtime_sha,
        "source_stage_start_sha256": stage_start_sha,
        "child_manifest_sha256s": child,
        "required_uid": os.getuid(),
        "authority": {
            "retry_authorized": False,
            "test_split_cached": False,
            "test_split_open_authorized": False,
            "training_authorized_by_source_artifact": False,
            "gameplay_strength_screen_authorized": False,
            "strength_claim_authorized": False,
            "deployment_authorized": False,
        },
    }
    spec_path = tmp_path / "cache-import.json"
    spec_raw = canonical_json_bytes(spec_payload)
    immutable(spec_path, spec_raw)
    import_binding = V2SourceBindingV1(
        path=CACHE_IMPORT.CACHE_IMPORT_SOURCE_PATH,
        sha256=hashlib.sha256(spec_raw).hexdigest(),
        byte_count=len(spec_raw))
    current_freeze = replace(
        old_freeze, evidence_root=str(destination),
        source_bindings=tuple(sorted(
            (*old_freeze.source_bindings, import_binding),
            key=lambda row: row.path)))
    monkeypatch.setattr(CACHE_IMPORT, "CACHE_IMPORT_SPEC_PATH", spec_path)
    reopened = CACHE_IMPORT.load_tensor_cache_import_spec(current_freeze)
    assert reopened is not None
    assert reopened.source_cache_root == cache_root
    assert reopened.source_consumption_tombstone_sha256 == tombstone_sha
    assert reopened.source_derived_input_sha256 == derived_input_sha
    assert reopened.source_cache_input_identity_sha256 \
        == CACHE_IMPORT.cache_input_identity_sha256({
            "derived_manifest": derived_manifest})
    rebooted = replace(
        current_freeze,
        runtime=replace(
            current_freeze.runtime, boot_identity="f" * 64))
    assert CACHE_IMPORT.load_tensor_cache_import_spec(rebooted) is not None
    relocated = replace(
        current_freeze,
        runtime=replace(
            current_freeze.runtime,
            native_path="/new/source/shengji/engine/_fast.so",
            torch=replace(
                current_freeze.runtime.torch,
                root="/new/venv/lib/python3.14/site-packages"),
            numpy=replace(
                current_freeze.runtime.numpy,
                root="/new/venv/lib/python3.14/site-packages")))
    assert CACHE_IMPORT.load_tensor_cache_import_spec(relocated) is not None
    native_drift = replace(
        current_freeze,
        runtime=replace(
            current_freeze.runtime, native_sha256="0" * 64))
    with pytest.raises(
            CACHE_IMPORT.BeliefV2CacheImportError,
            match="runtime/cap identity drift"):
        CACHE_IMPORT.load_tensor_cache_import_spec(native_drift)

    def rewrite_immutable(path: Path, raw: bytes) -> None:
        path.chmod(0o600)
        path.write_bytes(raw)
        path.chmod(0o400)

    def bind_spec(payload: dict) -> V2ExecutionFreezeV1:
        raw = canonical_json_bytes(payload)
        rewrite_immutable(spec_path, raw)
        binding = V2SourceBindingV1(
            path=CACHE_IMPORT.CACHE_IMPORT_SOURCE_PATH,
            sha256=hashlib.sha256(raw).hexdigest(), byte_count=len(raw))
        return replace(
            current_freeze,
            source_bindings=tuple(sorted((
                *(row for row in current_freeze.source_bindings
                  if row.path != CACHE_IMPORT.CACHE_IMPORT_SOURCE_PATH),
                binding), key=lambda row: row.path)))

    source_index_manifest_path = index_root / "manifest.json"
    source_index_manifest_raw = source_index_manifest_path.read_bytes()
    source_index_manifest = json.loads(source_index_manifest_raw)
    source_index_manifest["derived_input_sha256"] = _sha("f")
    forged_index_manifest_raw = canonical_json_bytes(source_index_manifest)
    rewrite_immutable(source_index_manifest_path, forged_index_manifest_raw)
    forged_index_spec = dict(
        spec_payload,
        source_input_index_manifest_sha256=hashlib.sha256(
            forged_index_manifest_raw).hexdigest())
    with pytest.raises(
            CACHE_IMPORT.BeliefV2CacheImportError,
            match="source index semantic binding drift"):
        CACHE_IMPORT.load_tensor_cache_import_spec(
            bind_spec(forged_index_spec))
    rewrite_immutable(source_index_manifest_path, source_index_manifest_raw)
    current_freeze = bind_spec(spec_payload)

    forged_authority = dict(spec_payload["authority"])
    forged_authority["training_authorized_by_source_artifact"] = True
    with pytest.raises(
            CACHE_IMPORT.BeliefV2CacheImportError,
            match="field/authority drift"):
        CACHE_IMPORT.load_tensor_cache_import_spec(bind_spec(dict(
            spec_payload, authority=forged_authority)))
    current_freeze = bind_spec(spec_payload)

    forged_tombstone = json.loads(tombstone_raw)
    forged_tombstone["retry_authorized"] = True
    forged_tombstone_raw = canonical_json_bytes(forged_tombstone)
    rewrite_immutable(tombstone_path, forged_tombstone_raw)
    tombstone_spec = dict(
        spec_payload,
        source_consumption_tombstone_sha256=hashlib.sha256(
            forged_tombstone_raw).hexdigest())
    tombstone_freeze = bind_spec(tombstone_spec)
    with pytest.raises(
            CACHE_IMPORT.BeliefV2CacheImportError,
            match="spent admission reopen refused"):
        CACHE_IMPORT.load_tensor_cache_import_spec(tombstone_freeze)
    rewrite_immutable(tombstone_path, tombstone_raw)

    start_payload = json.loads((cache_root / "stage-start.json").read_bytes())
    start_payload["deployment_authorized"] = True
    forged_start_raw = canonical_json_bytes(start_payload)
    rewrite_immutable(cache_root / "stage-start.json", forged_start_raw)
    start_spec = dict(
        spec_payload,
        source_stage_start_sha256=hashlib.sha256(
            forged_start_raw).hexdigest())
    start_freeze = bind_spec(start_spec)
    with pytest.raises(
            CACHE_IMPORT.BeliefV2CacheImportError,
            match="source stage start drift"):
        CACHE_IMPORT.load_tensor_cache_import_spec(start_freeze)
    rewrite_immutable(cache_root / "stage-start.json",
                      canonical_json_bytes({
                          "schema": (
                              "belief-v1-v2-training-tensor-cache-start-v1"),
                          "freeze_sha256": old_freeze.sha256(),
                          "admission_sha256": old_admission.sha256(),
                          "training_input_index_sha256": index_sha,
                          "boot_identity": old_freeze.runtime.boot_identity,
                          "started_monotonic_nanoseconds": 1,
                          "retry_authorized": False,
                          "test_split_open_authorized": False,
                          "strength_claim_authorized": False,
                          "deployment_authorized": False,
                      }))
    current_freeze = bind_spec(spec_payload)

    tombstone_path.chmod(0o600)
    tombstone_path.write_bytes(tombstone_raw + b" ")
    tombstone_path.chmod(0o400)
    with pytest.raises(
            CACHE_IMPORT.BeliefV2CacheImportError,
            match="source byte binding drift"):
        CACHE_IMPORT.load_tensor_cache_import_spec(current_freeze)
    unrelated = replace(
        current_freeze,
        evidence_root=str((tmp_path / "unrelated").resolve()))
    assert CACHE_IMPORT.load_tensor_cache_import_spec(unrelated) is None


def _coordinate(split="calibration"):
    return next(row for row in v2_round_coordinates() if row.split == split)


def _heuristic_capture(coordinate):
    seeds = v2_policy_seeds(coordinate)
    return _capture_with_policies(
        coordinate.round_seed, CHAMPION_POLICY, seeds,
        [HeuristicBot() for _ in range(4)],
        trump_rank=coordinate.trump_rank)


def _prepare(monkeypatch, tmp_path, split="calibration"):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    freeze = _freeze(root)
    admission = _admission(freeze)
    coordinate = _coordinate(split)
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    # Full 256-world mechanics are already pinned by the reference suite; this
    # controller test exercises publication/reopen wiring at a bounded count.
    monkeypatch.setattr(
        "shengji.rl.belief_refc_capture.REF_C_WORLD_COUNT", 4)
    monkeypatch.setattr(
        "shengji.rl.belief_reference.REF_C_WORLD_COUNT", 4)
    monkeypatch.setattr(
        "shengji.rl.belief_reference._WORLD_UNIT_PPB", 250_000_000)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_controller._stage_gate",
        lambda **kwargs: None)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_controller.v2_lane_coordinates",
        lambda lane: (coordinate,))
    monkeypatch.setattr(
        "shengji.rl.belief_v2_controller.capture_v2_champion_round",
        _heuristic_capture)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_reference.make_bot",
        lambda *args, **kwargs: HeuristicBot())
    return root, freeze, admission, coordinate


def test_capture_publishes_one_search_private_and_actor_only_bytes(
        tmp_path, monkeypatch):
    root, freeze, admission, coordinate = _prepare(
        monkeypatch, tmp_path)
    calls = []

    def capture(value):
        calls.append(value)
        return _heuristic_capture(value)

    monkeypatch.setattr(
        "shengji.rl.belief_v2_controller.capture_v2_champion_round",
        capture)
    progress = []
    result = run_capture_lane(
        root, freeze, admission, repo=Path("/unused"), lane=coordinate.lane,
        review_marker=b"review", progress=lambda *row: progress.append(row))
    assert calls == [coordinate]
    assert progress == [
        (0, 1, "capture-rounds"), (1, 1, "capture-rounds")]
    assert result["round_count"] == 1
    row = result["rounds"][0]
    assert row["private_bundle_sha256"] != row["actor_bundle_sha256"]
    assert row["decision_count"] > 0
    assert result["contains_round_outcomes"] is False
    assert result["actor_contains_privileged_targets"] is False
    assert reopen_capture_lane(
        root / "capture" / f"lane-{coordinate.lane:02d}",
        freeze=freeze, admission=admission, lane=coordinate.lane) == result


def test_reference_opens_no_private_capture_bundle(tmp_path, monkeypatch):
    root, freeze, admission, coordinate = _prepare(
        monkeypatch, tmp_path)
    run_capture_lane(
        root, freeze, admission, repo=Path("/unused"), lane=coordinate.lane,
        review_marker=b"review")
    import shengji.rl.belief_v2_controller as controller
    real_read = controller.stable_read_bytes

    def target_blind(path):
        if path.parent.name == "private":
            raise AssertionError("reference opened a private target bundle")
        return real_read(path)

    monkeypatch.setattr(controller, "stable_read_bytes", target_blind)
    progress = []
    result = run_reference_lane(
        root, freeze, admission, repo=Path("/unused"), lane=coordinate.lane,
        review_marker=b"review", progress=lambda *row: progress.append(row))
    assert progress == [
        (0, 2, "reference-jobs"),
        (1, 2, "reference-jobs"),
        (2, 2, "reference-jobs")]
    assert result["job_count"] == 2
    assert result["input_surface"] == "actor-only-capture-bundles"
    assert result["contains_privileged_training_targets"] is False
    assert reopen_reference_lane(
        root / "reference" / f"lane-{coordinate.lane:02d}",
        capture_directory=(
            root / "capture" / f"lane-{coordinate.lane:02d}"),
        freeze=freeze, admission=admission, lane=coordinate.lane) == result


def test_public_reference_manifest_never_opens_world_bundle(
        tmp_path, monkeypatch):
    root, freeze, admission, coordinate = _prepare(
        monkeypatch, tmp_path)
    run_capture_lane(
        root, freeze, admission, repo=Path("/unused"), lane=coordinate.lane,
        review_marker=b"review")
    result = run_reference_lane(
        root, freeze, admission, repo=Path("/unused"), lane=coordinate.lane,
        review_marker=b"review")
    import shengji.rl.belief_v2_controller as controller
    real_read = controller.stable_read_bytes

    def no_reference_world_open(path):
        if path.name.endswith(".ref.bin"):
            raise AssertionError("calibration manifest opened REF-C worlds")
        return real_read(path)

    monkeypatch.setattr(
        controller, "stable_read_bytes", no_reference_world_open)
    reopened = reopen_reference_lane_manifest(
        root / "reference" / f"lane-{coordinate.lane:02d}",
        capture_directory=(
            root / "capture" / f"lane-{coordinate.lane:02d}"),
        freeze=freeze, admission=admission, lane=coordinate.lane)
    assert reopened == result


def test_synthetic_scoring_reader_opens_only_named_calibration_bytes(
        tmp_path, monkeypatch):
    root, freeze, admission, coordinate = _prepare(
        monkeypatch, tmp_path)
    run_capture_lane(
        root, freeze, admission, repo=Path("/unused"), lane=coordinate.lane,
        review_marker=b"review")
    run_reference_lane(
        root, freeze, admission, repo=Path("/unused"), lane=coordinate.lane,
        review_marker=b"review")
    decisions = reopen_synthetic_scoring_round(
        root, freeze=freeze, admission=admission, coordinate=coordinate,
        replicate="calibration-replicate-0",
        allowed_split="calibration")
    assert decisions
    assert all(row.source_actor.trump_rank == coordinate.trump_rank
               for row in decisions)
    with pytest.raises(BeliefV2ScoringControllerError,
                       match="split/replicate"):
        reopen_synthetic_scoring_round(
            root, freeze=freeze, admission=admission,
            coordinate=coordinate, replicate="test-primary",
            allowed_split="test")


def test_training_reader_authenticates_lane_without_opening_test_targets(
        tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    freeze = _freeze(root)
    admission = _admission(freeze)
    coordinates = v2_round_coordinates()
    train = next(row for row in coordinates if row.split == "train")
    test = next(row for row in coordinates
                if row.lane == train.lane and row.split == "test")
    lane_coordinates = (train, test)
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(
        "shengji.rl.belief_v2_controller._stage_gate",
        lambda **kwargs: None)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_controller.v2_lane_coordinates",
        lambda lane: lane_coordinates)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_controller.capture_v2_champion_round",
        _heuristic_capture)
    result = run_capture_lane(
        root, freeze, admission, repo=Path("/unused"), lane=train.lane,
        review_marker=b"review")
    test_filename = next(
        row["private_filename"] for row in result["rounds"]
        if row["split"] == "test")
    import shengji.rl.belief_v2_controller as controller
    real_read = controller.stable_read_bytes

    def test_target_tripwire(path):
        if path.name == test_filename:
            raise AssertionError("training opened a test target bundle")
        return real_read(path)

    monkeypatch.setattr(controller, "stable_read_bytes", test_target_tripwire)
    examples = reopen_synthetic_training_lane_examples(
        root / "capture" / f"lane-{train.lane:02d}",
        freeze=freeze, admission=admission, lane=train.lane,
        split="train")
    assert examples
    assert {example.split for example in examples} == {"train"}
    with pytest.raises(BeliefV2ControllerError,
                       match="split is not train/calibration"):
        reopen_synthetic_training_lane_examples(
            root / "capture" / f"lane-{train.lane:02d}",
            freeze=freeze, admission=admission, lane=train.lane,
            split="test")


def test_public_capture_reopen_requires_private_file_population(
        tmp_path, monkeypatch):
    root, freeze, admission, coordinate = _prepare(
        monkeypatch, tmp_path)
    result = run_capture_lane(
        root, freeze, admission, repo=Path("/unused"), lane=coordinate.lane,
        review_marker=b"review")
    directory = root / "capture" / f"lane-{coordinate.lane:02d}"
    row = result["rounds"][0]
    (directory / "private" / row["private_filename"]).unlink()
    with pytest.raises(BeliefV2ControllerError,
                       match="private file population drift"):
        reopen_actor_capture_lane_manifest(
            directory, freeze=freeze, admission=admission,
            lane=coordinate.lane)


def test_capture_refuses_before_write_when_stage_gate_fails(
        tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    freeze = _freeze(root)
    admission = _admission(freeze)

    def refuse(**kwargs):
        raise BeliefV2ControllerError("gate refused")

    monkeypatch.setattr(
        "shengji.rl.belief_v2_controller._stage_gate", refuse)
    with pytest.raises(BeliefV2ControllerError, match="gate refused"):
        run_capture_lane(
            root, freeze, admission, repo=Path("/unused"), lane=0,
            review_marker=b"review")
    assert not (root / "capture").exists()


def test_capture_and_reference_deadlines_stop_before_next_unit_and_seal(
        tmp_path, monkeypatch):
    real_monotonic = V2_CONTROLLER.time.monotonic_ns
    root, freeze, admission, coordinate = _prepare(
        monkeypatch, tmp_path)
    capture_calls = []
    monkeypatch.setattr(
        V2_CONTROLLER, "capture_v2_champion_round",
        lambda value: capture_calls.append(value))
    capture_hard = (1_000_000_000
                    + freeze.resource_caps.capture_wall_seconds
                    * 1_000_000_000)
    capture_times = iter((1_000_000_000, capture_hard - 20_000_000_000))
    monkeypatch.setattr(
        V2_CONTROLLER.time, "monotonic_ns", lambda: next(capture_times))
    with pytest.raises(BeliefV2ControllerError,
                       match="deadline exhausted and recorded"):
        run_capture_lane(
            root, freeze, admission, repo=Path("/unused"),
            lane=coordinate.lane, review_marker=b"review")
    assert capture_calls == []
    capture_partial = (
        root / "capture" / f"lane-{coordinate.lane:02d}.partial")
    assert (capture_partial / "deadline-refusal.json").is_file()
    assert not (root / "capture" / f"lane-{coordinate.lane:02d}").exists()

    # Use a separate exact root to witness the reference loop at the same
    # altitude without deleting or retrying the spent capture slot above.
    reference_case = tmp_path / "reference-case"
    reference_case.mkdir()
    root2, freeze2, admission2, coordinate2 = _prepare(
        monkeypatch, reference_case)
    monkeypatch.setattr(
        V2_CONTROLLER.time, "monotonic_ns", real_monotonic)
    run_capture_lane(
        root2, freeze2, admission2, repo=Path("/unused"),
        lane=coordinate2.lane, review_marker=b"review")
    reference_hard = (1_000_000_000
                      + freeze2.resource_caps.reference_wall_seconds
                      * 1_000_000_000)
    reference_times = iter((
        1_000_000_000, reference_hard - 5_000_000_000))
    monkeypatch.setattr(
        V2_CONTROLLER.time, "monotonic_ns", lambda: next(reference_times))
    with pytest.raises(BeliefV2ControllerError,
                       match="deadline exhausted and recorded"):
        run_reference_lane(
            root2, freeze2, admission2, repo=Path("/unused"),
            lane=coordinate2.lane, review_marker=b"review")
    reference_partial = (
        root2 / "reference" / f"lane-{coordinate2.lane:02d}.partial")
    assert {path.name for path in reference_partial.iterdir()} \
        == {"deadline-refusal.json"}
    assert not (root2 / "reference"
                / f"lane-{coordinate2.lane:02d}").exists()


def test_capture_reopen_refuses_mutated_exact_bundle(tmp_path, monkeypatch):
    root, freeze, admission, coordinate = _prepare(
        monkeypatch, tmp_path)
    result = run_capture_lane(
        root, freeze, admission, repo=Path("/unused"), lane=coordinate.lane,
        review_marker=b"review")
    row = result["rounds"][0]
    path = (root / "capture" / f"lane-{coordinate.lane:02d}"
            / "actor-only" / row["actor_filename"])
    path.chmod(0o600)
    path.write_bytes(path.read_bytes() + b"x")
    path.chmod(0o400)
    with pytest.raises(BeliefV2ControllerError,
                       match="bundle byte binding"):
        reopen_capture_lane(
            root / "capture" / f"lane-{coordinate.lane:02d}",
            freeze=freeze, admission=admission, lane=coordinate.lane)


def test_capture_slot_is_no_retry(tmp_path, monkeypatch):
    root, freeze, admission, coordinate = _prepare(
        monkeypatch, tmp_path)
    run_capture_lane(
        root, freeze, admission, repo=Path("/unused"), lane=coordinate.lane,
        review_marker=b"review")
    with pytest.raises(BeliefV2ControllerError, match="slot is occupied"):
        run_capture_lane(
            root, freeze, admission, repo=Path("/unused"),
            lane=coordinate.lane, review_marker=b"review")


def _human_state(seed=12101):
    rnd = Game(random.Random(seed)).start_round()
    bot = HeuristicBot()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = bot.decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = bot.decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
    for _ in range(9):
        seat = rnd.turn
        rnd.play(seat, bot.decide_play(rnd, seat))
    return rnd


def _human_receipts():
    source_raws = tuple(f"source-{index:02d}".encode("ascii")
                        for index in range(10))
    source_shas = tuple(hashlib.sha256(raw).hexdigest()
                        for raw in source_raws)
    rnd = _human_state()
    groups = [{
        "group_digest": _group_digest(source_sha),
        "source_bytes": len(raw),
        "complete_rounds": 1,
        "incomplete_rounds": 0,
        "human_play_decisions": 1,
        "trump_rank_counts": {rnd.trump_rank: 1},
        "attempted_channel_counts": {"absent": 1},
    } for raw, source_sha in zip(source_raws, source_shas, strict=True)]
    components = []
    for group in groups:
        component_digest = _component_digest((group["group_digest"],))
        group["component_digest"] = component_digest
        components.append({
            "component_digest": component_digest,
            "group_digests": [group["group_digest"]],
        })
    population_sha = hashlib.sha256(canonical_json_bytes({
        "schema": "belief-v1-v2-human-source-digest-population-v1",
        "sha256s": sorted(source_shas),
    })).hexdigest()
    inventory = {
        "schema": H0_INVENTORY_SCHEMA,
        "source_manifest_sha256": _sha("5"),
        "source_file_count": 10,
        "source_digest_population_sha256": population_sha,
        "group_count": 10,
        "groups": sorted(groups, key=lambda row: row["group_digest"]),
        "component_count": 10,
        "components": sorted(
            components, key=lambda row: row["component_digest"]),
        "rounds_seen": 10,
        "complete_rounds": 10,
        "incomplete_rounds": 0,
        "human_play_decisions": 10,
        "trump_rank_counts": {rnd.trump_rank: 10},
        "attempted_channel_counts": {"absent": 10},
        "hidden_ownership_labels_reconstructable_for_complete_rounds": True,
        "group_split_unit": "cross-file-human-player-component",
        "raw_player_identity_published": False,
        "model_rows_published": False,
        "training_authorized": False,
        "test_open_authorized": False,
        "strength_claim_authorized": False,
    }
    group_split = build_h0_group_split(inventory)
    return source_raws, source_shas, rnd, inventory, group_split


def _captured_human_group(source_raw, source_sha, rnd, split):
    group_digest = _group_digest(source_sha)
    round_digest = hashlib.sha256(
        f"test-human-round|{group_digest}".encode("ascii")).hexdigest()
    pair = capture_human_corpus_pair(
        rnd, rnd.turn, group_digest=group_digest,
        round_digest=round_digest, decision_index=9, split=split)
    return V2HumanGroupCaptureV1(
        source_sha256=source_sha, group_digest=group_digest, split=split,
        complete_round_count=1, incomplete_round_count=0,
        human_decision_count=1,
        trump_rank_counts=((rnd.trump_rank, 1),),
        attempted_channel_counts=(("absent", 1),), pairs=(pair,))


def test_human_group_stage_persists_separate_rows_and_training_is_test_blind(
        tmp_path, monkeypatch):
    source_raws, source_shas, rnd, inventory, group_split = _human_receipts()
    split_by_digest = {
        digest: split for split, row in group_split["splits"].items()
        for digest in row["group_digests"]}
    selected = {}
    for raw, digest in zip(source_raws, source_shas, strict=True):
        split = split_by_digest[_group_digest(digest)]
        if split in {"train", "test"} and split not in selected:
            selected[split] = (raw, digest)
    assert set(selected) == {"train", "test"}
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    base = _freeze(root)
    splits = group_split["splits"]
    freeze = replace(
        base,
        h0_inventory_sha256=hashlib.sha256(
            inventory_bytes(inventory)).hexdigest(),
        h0_source_manifest_sha256=inventory["source_manifest_sha256"],
        h0_source_digest_population_sha256=(
            inventory["source_digest_population_sha256"]),
        human_group_split_sha256=hashlib.sha256(
            group_split_bytes(group_split, inventory=inventory)).hexdigest(),
        human_group_count=inventory["group_count"],
        human_train_group_count=splits["train"]["group_count"],
        human_calibration_group_count=splits["calibration"]["group_count"],
        human_test_group_count=splits["test"]["group_count"],
        human_complete_round_count=inventory["complete_rounds"],
        human_eligible_decision_count=inventory["human_play_decisions"],
        human_train_eligible_decision_count=(
            splits["train"]["human_play_decisions"]),
        human_calibration_eligible_decision_count=(
            splits["calibration"]["human_play_decisions"]),
        human_test_eligible_decision_count=(
            splits["test"]["human_play_decisions"]),
    )
    admission = _admission(freeze)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_human_controller._stage_gate",
        lambda **kwargs: None)

    captures = {}
    for split, (raw, digest) in selected.items():
        source = tmp_path / f"{split}.jsonl"
        source.write_bytes(raw)
        source.chmod(0o400)
        captured = _captured_human_group(raw, digest, rnd, split)
        monkeypatch.setattr(
            "shengji.rl.belief_v2_human_controller."
            "capture_human_source_group",
            lambda *args, value=captured, **kwargs: value)
        progress = []
        manifest = run_human_group_capture(
            root, freeze, admission, repo=Path("/unused"),
            source_path=source, inventory=inventory,
            group_split=group_split, review_marker=b"review",
            progress=lambda *row: progress.append(row))
        assert progress == [
            (0, 1, "replay-human-decisions"),
            (1, 1, "publish-human-decisions")]
        assert manifest["split"] == split
        assert manifest["actor_target_files_separate"] is True
        captures[split] = root / "human-capture" / (
            f"group-{captured.group_digest}")

    import shengji.rl.belief_v2_human_controller as human_controller
    real_read = human_controller.stable_read_bytes
    test_targets = captures["test"] / "private-targets"

    def test_target_tripwire(path):
        if path.parent == test_targets:
            raise AssertionError("human training opened test targets")
        return real_read(path)

    monkeypatch.setattr(
        human_controller, "stable_read_bytes", test_target_tripwire)
    examples = reopen_human_training_group_examples(
        captures["train"], freeze=freeze, admission=admission,
        split="train")
    assert len(examples) == 1
    assert examples[0].source_kind == "human"
    with pytest.raises(BeliefV2HumanControllerError,
                       match="split is not train/calibration"):
        reopen_human_training_group_examples(
            captures["test"], freeze=freeze, admission=admission,
            split="test")


def test_human_reference_stage_reopens_against_actor_only_capture(
        tmp_path, monkeypatch):
    source_raws, source_shas, rnd, inventory, group_split = _human_receipts()
    split_by_digest = {
        digest: split for split, row in group_split["splits"].items()
        for digest in row["group_digests"]}
    raw, digest = next(
        (raw, digest) for raw, digest in zip(
            source_raws, source_shas, strict=True)
        if split_by_digest[_group_digest(digest)] == "calibration")
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    base = _freeze(root)
    splits = group_split["splits"]
    freeze = replace(
        base,
        h0_inventory_sha256=hashlib.sha256(
            inventory_bytes(inventory)).hexdigest(),
        h0_source_manifest_sha256=inventory["source_manifest_sha256"],
        h0_source_digest_population_sha256=(
            inventory["source_digest_population_sha256"]),
        human_group_split_sha256=hashlib.sha256(
            group_split_bytes(group_split, inventory=inventory)).hexdigest(),
        human_group_count=inventory["group_count"],
        human_train_group_count=splits["train"]["group_count"],
        human_calibration_group_count=splits["calibration"]["group_count"],
        human_test_group_count=splits["test"]["group_count"],
        human_complete_round_count=inventory["complete_rounds"],
        human_eligible_decision_count=inventory["human_play_decisions"],
        human_train_eligible_decision_count=(
            splits["train"]["human_play_decisions"]),
        human_calibration_eligible_decision_count=(
            splits["calibration"]["human_play_decisions"]),
        human_test_eligible_decision_count=(
            splits["test"]["human_play_decisions"]),
    )
    admission = _admission(freeze)
    source = tmp_path / "calibration.jsonl"
    source.write_bytes(raw)
    source.chmod(0o400)
    captured = _captured_human_group(
        raw, digest, rnd, "calibration")
    monkeypatch.setattr(
        "shengji.rl.belief_v2_human_controller._stage_gate",
        lambda **kwargs: None)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_human_controller.capture_human_source_group",
        lambda *args, **kwargs: captured)
    run_human_group_capture(
        root, freeze, admission, repo=Path("/unused"),
        source_path=source, inventory=inventory,
        group_split=group_split, review_marker=b"review")
    actor, _, metadata = reopen_human_actor_row(
        captured.pairs[0].actor_bytes)
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(
        "shengji.rl.belief_refc_capture.REF_C_WORLD_COUNT", 4)
    monkeypatch.setattr(
        "shengji.rl.belief_reference.REF_C_WORLD_COUNT", 4)
    monkeypatch.setattr(
        "shengji.rl.belief_reference._WORLD_UNIT_PPB", 250_000_000)
    batch = capture_ref_c_worlds_from_bound_actor(
        rnd, rnd.turn, v2_scoring_actor(actor), sampler_seed=19001)
    replay = V2HumanReplaySummaryV1(
        source_sha256=digest, group_digest=captured.group_digest,
        complete_round_count=1, incomplete_round_count=0,
        human_decision_count=1,
        trump_rank_counts=captured.trump_rank_counts,
        attempted_channel_counts=captured.attempted_channel_counts)
    reference = V2HumanReferenceGroupV1(
        replay=replay, split="calibration",
        replicate="calibration-replicate-0",
        decisions=(V2HumanReferenceDecisionV1(
            decision_key=metadata["decision_key"],
            round_digest=metadata["round_digest"],
            trump_rank=rnd.trump_rank, batch=batch),))
    monkeypatch.setattr(
        "shengji.rl.belief_v2_human_reference_controller._stage_gate",
        lambda **kwargs: None)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_human_reference_controller."
        "capture_human_ref_c_source_group",
        lambda *args, **kwargs: reference)
    progress = []
    manifest = run_human_reference_group(
        root, freeze, admission, repo=Path("/unused"),
        source_path=source, inventory=inventory, group_split=group_split,
        replicate="calibration-replicate-0", review_marker=b"review",
        progress=lambda *row: progress.append(row))
    assert progress == [
        (0, 1, "replay-human-reference"),
        (1, 1, "publish-human-reference")]
    reference_directory = (
        root / "human-reference" / f"group-{captured.group_digest}"
        / "calibration-replicate-0")
    reference_file = reference_directory / "decision-000000.json"
    real_read = HUMAN_REF_STAGE.stable_read_bytes

    def refuse_reference_bytes(path):
        if Path(path) == reference_file:
            raise AssertionError("manifest recovery opened human REF-C bytes")
        return real_read(path)

    monkeypatch.setattr(
        HUMAN_REF_STAGE, "stable_read_bytes", refuse_reference_bytes)
    manifest_only = reopen_human_reference_group_manifest(
        reference_directory, freeze=freeze, admission=admission)
    assert manifest_only == manifest
    monkeypatch.setattr(HUMAN_REF_STAGE, "stable_read_bytes", real_read)
    reopened = reopen_human_reference_group(
        reference_directory,
        freeze=freeze, admission=admission)
    assert reopened == manifest
    assert manifest["contains_privileged_training_targets"] is False
    rounds = reopen_human_scoring_rounds(
        root, freeze=freeze, admission=admission,
        group_digest=captured.group_digest,
        replicate="calibration-replicate-0",
        allowed_split="calibration")
    assert len(rounds) == 1
    assert rounds[0][0] == metadata["round_digest"]
    assert len(rounds[0][2]) == 1


def test_zero_decision_human_group_progress_completes_at_stage_boundary(
        tmp_path, monkeypatch):
    source_raws, source_shas, _, inventory, group_split = _human_receipts()
    split_by_digest = {
        digest: split for split, row in group_split["splits"].items()
        for digest in row["group_digests"]}
    raw, source_sha = next(
        (raw, digest) for raw, digest in zip(
            source_raws, source_shas, strict=True)
        if split_by_digest[_group_digest(digest)] == "calibration")
    group_digest = _group_digest(source_sha)
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    base = _freeze(root)
    splits = group_split["splits"]
    freeze = replace(
        base,
        h0_inventory_sha256=hashlib.sha256(
            inventory_bytes(inventory)).hexdigest(),
        h0_source_manifest_sha256=inventory["source_manifest_sha256"],
        h0_source_digest_population_sha256=(
            inventory["source_digest_population_sha256"]),
        human_group_split_sha256=hashlib.sha256(
            group_split_bytes(group_split, inventory=inventory)).hexdigest(),
        human_group_count=inventory["group_count"],
        human_train_group_count=splits["train"]["group_count"],
        human_calibration_group_count=splits["calibration"]["group_count"],
        human_test_group_count=splits["test"]["group_count"],
        human_complete_round_count=inventory["complete_rounds"],
        human_eligible_decision_count=inventory["human_play_decisions"],
        human_train_eligible_decision_count=(
            splits["train"]["human_play_decisions"]),
        human_calibration_eligible_decision_count=(
            splits["calibration"]["human_play_decisions"]),
        human_test_eligible_decision_count=(
            splits["test"]["human_play_decisions"]),
    )
    admission = _admission(freeze)
    source = tmp_path / "empty-calibration.jsonl"
    source.write_bytes(raw)
    source.chmod(0o400)
    captured = V2HumanGroupCaptureV1(
        source_sha256=source_sha, group_digest=group_digest,
        split="calibration", complete_round_count=0,
        incomplete_round_count=1, human_decision_count=0,
        trump_rank_counts=(), attempted_channel_counts=(), pairs=())
    monkeypatch.setattr(
        "shengji.rl.belief_v2_human_controller._stage_gate",
        lambda **kwargs: None)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_human_controller.capture_human_source_group",
        lambda *args, **kwargs: captured)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_human_controller._group_inventory_row",
        lambda *args: {
            "source_bytes": len(raw), "complete_rounds": 0,
            "incomplete_rounds": 1, "human_play_decisions": 0,
            "trump_rank_counts": {}, "attempted_channel_counts": {}})
    progress = []
    run_human_group_capture(
        root, freeze, admission, repo=Path("/unused"),
        source_path=source, inventory=inventory, group_split=group_split,
        review_marker=b"review", progress=lambda *row: progress.append(row))
    assert progress == [
        (0, 1, "replay-human-group"),
        (1, 1, "human-group-complete")]

    replay = V2HumanReplaySummaryV1(
        source_sha256=source_sha, group_digest=group_digest,
        complete_round_count=0, incomplete_round_count=1,
        human_decision_count=0, trump_rank_counts=(),
        attempted_channel_counts=())
    reference = V2HumanReferenceGroupV1(
        replay=replay, split="calibration",
        replicate="calibration-replicate-0", decisions=())
    monkeypatch.setattr(
        "shengji.rl.belief_v2_human_reference_controller._stage_gate",
        lambda **kwargs: None)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_human_reference_controller."
        "capture_human_ref_c_source_group",
        lambda *args, **kwargs: reference)
    reference_progress = []
    run_human_reference_group(
        root, freeze, admission, repo=Path("/unused"),
        source_path=source, inventory=inventory, group_split=group_split,
        replicate="calibration-replicate-0", review_marker=b"review",
        progress=lambda *row: reference_progress.append(row))
    assert reference_progress == [
        (0, 1, "replay-human-reference-group"),
        (1, 1, "human-reference-group-complete")]
    assert reopen_human_scoring_rounds(
        root, freeze=freeze, admission=admission,
        group_digest=group_digest,
        replicate="calibration-replicate-0",
        allowed_split="calibration") == ()


def test_expected_human_rounds_use_scoring_canonical_digest_order(
        tmp_path, monkeypatch):
    group = _sha("a")
    encounter_order = [
        {"round_digest": _sha("f"), "trump_rank": "A"},
        {"round_digest": _sha("0"), "trump_rank": "2"},
    ]
    monkeypatch.setattr(
        CALIBRATION_STAGE, "reopen_human_reference_group",
        lambda *args, **kwargs: {"rows": encounter_order})
    monkeypatch.setattr(
        TERMINAL_STAGE, "reopen_human_reference_group",
        lambda *args, **kwargs: {"rows": encounter_order})
    group_split = {"splits": {
        "calibration": {"group_digests": [group]},
        "test": {"group_digests": [group]},
    }}
    expected = ((_sha("0"), "2"), (_sha("f"), "A"))
    assert CALIBRATION_STAGE._expected_human_rounds_from_references(
        tmp_path, object(), object(), group_split) == expected
    assert TERMINAL_STAGE._expected_test_human_rounds(
        tmp_path, object(), object(), group_split) == expected


def _cpu_fallback_qualification(freeze):
    batches = tuple((_sha256_text(f"qualification-{index}"),)
                    for index in range(40))
    plan = build_qualification_plan(
        execution_git=freeze.execution_git,
        candidate_device=freeze.training_candidate_device,
        batch_decision_keys=batches,
        batch_active_label_counts=tuple(100 for _ in batches),
        host_memory_cap_bytes=(
            freeze.resource_caps.training_host_memory_bytes),
        device_memory_cap_bytes=(
            freeze.resource_caps.training_device_memory_bytes))
    arms = []
    for index, (device, warmup, pair_index) in enumerate(plan.arm_order):
        arms.append(V2DeviceQualificationArmV1(
            arm_index=index, device=device, warmup=warmup,
            pair_index=pair_index, plan_sha256=plan.sha256(),
            batch_population_sha256=plan.selected_population_sha256,
            batch_schedule_sha256=plan.selected_schedule_sha256,
            decision_count=plan.decision_count,
            active_label_count=plan.active_label_count,
            member_checkpoint_sha256s=tuple(
                _sha256_text(f"{device}-checkpoint-{member}")
                for member in range(8)),
            member_loss_nanonats=tuple(
                1000 + member for member in range(8)),
            member_epoch_receipt_sha256s=tuple(
                _sha256_text(f"{device}-receipt-{member}")
                for member in range(8)),
            wall_nanoseconds=50 if warmup else (
                100 if device == "cpu" else 120),
            peak_host_memory_bytes=1024,
            peak_device_memory_bytes=0 if device == "cpu" else 2048,
            actual_device=device))
    return plan, derive_qualification_result(plan, tuple(arms))


def _sha256_text(value):
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _tiny_training_population(freeze):
    train_capture = _heuristic_capture(_coordinate("train"))
    synthetic = tuple(build_synthetic_training_example(pair)
                      for pair in train_capture.pairs[:5])
    source_raw = b"training-human-source"
    source_sha = hashlib.sha256(source_raw).hexdigest()
    human_capture = _captured_human_group(
        source_raw, source_sha, _human_state(), "train")
    human = tuple(build_human_training_example(
        pair.actor_bytes, pair.target_bytes)
        for pair in human_capture.pairs)
    realizations = realize_v2_cohorts(
        freeze.cohorts,
        synthetic_rows=tuple(training_row(row) for row in synthetic),
        human_rows=tuple(training_row(row) for row in human))
    primary = next(row for row in realizations
                   if row.kind == "synthetic-primary")
    by_key = {row.decision_key: row for row in (*synthetic, *human)}
    training_examples = tuple(
        by_key[row.decision_key] for row in primary.rows)
    calibration = tuple(build_synthetic_training_example(pair)
                        for pair in _heuristic_capture(
                            _coordinate("calibration")).pairs[:2])
    calibration_schedule = realize_v2_common_calibration(calibration)
    return primary, training_examples, calibration, calibration_schedule


def test_device_qualification_stage_publishes_raw_reopenable_cpu_fallback(
        tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    freeze = _freeze(root)
    admission = _admission(freeze)
    primary, training_examples, _, _ = _tiny_training_population(freeze)
    plan, result = _cpu_fallback_qualification(freeze)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_device_controller._stage_gate",
        lambda **kwargs: None)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_device_controller._expected_plan",
        lambda *args, **kwargs: plan)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_device_controller."
        "run_device_qualification_in_memory",
        lambda **kwargs: (plan, result))
    manifest = run_device_qualification(
        root, freeze, admission, repo=Path("/unused"),
        review_marker=b"review", primary=primary,
        primary_examples=training_examples)
    reopened, reopened_plan, reopened_result = reopen_device_qualification(
        root / "device-qualification" / "result",
        freeze=freeze, admission=admission, primary=primary)
    assert reopened == manifest
    assert reopened_plan == plan
    assert reopened_result == result
    assert manifest["selected_device"] == "cpu"
    assert manifest["accelerator_retained"] is False
    assert manifest["fallback_arm_count"] == 0
    assert manifest["training_authorized_by_this_artifact"] is False


def test_training_input_index_wires_deadline_around_source_units_and_seal(
        tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    freeze = _cpu_only_freeze(root)
    admission = _admission(freeze)
    phases = []
    fake = SimpleNamespace(
        index=SimpleNamespace(sources=(object(), object())),
        sha256=lambda: "7" * 64,
        manifest=lambda: {
            "resident_model_array_bytes": 0,
            "one_batch_at_a_time": True})
    monkeypatch.setattr(
        INPUT_INDEX_STAGE, "_stage_gate", lambda **kwargs: None)

    class Deadline:
        def check(self, *, phase, next_unit_index,
                  observed_monotonic_nanoseconds):
            phases.append((phase, next_unit_index))

    monkeypatch.setattr(
        INPUT_INDEX_STAGE, "stage_deadline",
        lambda *args, **kwargs: Deadline())

    def build(*args, deadline_check, **kwargs):
        deadline_check("before-unit", 0)
        deadline_check("after-unit", 1)
        return fake

    monkeypatch.setattr(
        INPUT_INDEX_STAGE, "reopen_streaming_training_inputs", build)
    monkeypatch.setattr(
        INPUT_INDEX_STAGE, "streaming_training_inputs_bytes",
        lambda value, bound_freeze: b"compact-index\n")
    monkeypatch.setattr(
        INPUT_INDEX_STAGE, "host_peak_memory_bytes", lambda: 1024)

    def reopen(directory, **kwargs):
        return json.loads((directory / "manifest.json").read_bytes()), fake

    monkeypatch.setattr(
        INPUT_INDEX_STAGE, "reopen_training_input_index", reopen)
    manifest = run_training_input_index(
        root, freeze, admission, repo=Path("/unused"),
        review_marker=b"review", inventory={}, group_split={})
    assert manifest["index_sha256"] == hashlib.sha256(
        b"compact-index\n").hexdigest()
    assert manifest["synthetic_test_targets_opened"] is False
    assert manifest["human_test_targets_opened"] is False
    assert phases == [
        ("before-unit", 0), ("after-unit", 1), ("before-seal", 2)]
    assert not (root / "training-input-index" / "result.partial").exists()


def test_training_input_index_controller_uses_cap_bounded_input_workers(
        tmp_path, monkeypatch):
    """Witness the controller wiring, not only the worker-count helper."""
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    original = _cpu_only_freeze(root)
    freeze = replace(
        original,
        resource_caps=replace(
            original.resource_caps,
            training_host_memory_bytes=16 * 1024**3))
    admission = _admission(freeze)
    fake = SimpleNamespace(
        index=SimpleNamespace(sources=(object(),)),
        sha256=lambda: "7" * 64,
        manifest=lambda: {
            "resident_model_array_bytes": 0,
            "one_batch_at_a_time": True})
    observed_worker_counts = []
    monkeypatch.setattr(
        INPUT_INDEX_STAGE, "_stage_gate", lambda **kwargs: None)

    class Deadline:
        def check(self, **kwargs):
            pass

    monkeypatch.setattr(
        INPUT_INDEX_STAGE, "stage_deadline",
        lambda *args, **kwargs: Deadline())

    def scan(**kwargs):
        observed_worker_counts.append(kwargs["worker_count"])
        return (), (), (), 1, 1

    monkeypatch.setattr(
        INPUT_INDEX_STAGE,
        "scan_parallel_synthetic_training_inputs", scan)

    def build(*args, synthetic_scan, **kwargs):
        assert synthetic_scan is not None
        assert synthetic_scan(
            capture=root / "capture", freeze=freeze,
            admission=admission, deadline_check=None) == (
                (), (), (), 1, 1)
        return fake

    monkeypatch.setattr(
        INPUT_INDEX_STAGE, "reopen_streaming_training_inputs", build)
    monkeypatch.setattr(
        INPUT_INDEX_STAGE, "streaming_training_inputs_bytes",
        lambda value, bound_freeze: b"compact-index\n")
    monkeypatch.setattr(
        INPUT_INDEX_STAGE, "_aggregate_peak_host_memory_bytes",
        lambda worker_count: 1024)

    def reopen(directory, **kwargs):
        return json.loads((directory / "manifest.json").read_bytes()), fake

    monkeypatch.setattr(
        INPUT_INDEX_STAGE, "reopen_training_input_index", reopen)
    run_training_input_index(
        root, freeze, admission, repo=Path("/unused"),
        review_marker=b"review", inventory={}, group_split={})

    # The 16 GiB frozen stage cap leaves 12 GiB after the parent reserve,
    # hence exactly six 2 GiB input workers.  The cache topology would choose
    # sixteen here and reintroduce the resource failure this test guards.
    assert observed_worker_counts == [6]


def test_training_input_index_memory_cap_refuses_before_manifest_or_seal(
        tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    freeze = _cpu_only_freeze(root)
    admission = _admission(freeze)
    fake = SimpleNamespace(
        index=SimpleNamespace(sources=(object(),)),
        sha256=lambda: "7" * 64,
        manifest=lambda: {
            "resident_model_array_bytes": 0,
            "one_batch_at_a_time": True})
    monkeypatch.setattr(
        INPUT_INDEX_STAGE, "_stage_gate", lambda **kwargs: None)
    monkeypatch.setattr(
        INPUT_INDEX_STAGE, "reopen_streaming_training_inputs",
        lambda *args, **kwargs: fake)
    monkeypatch.setattr(
        INPUT_INDEX_STAGE, "streaming_training_inputs_bytes",
        lambda value, bound_freeze: b"compact-index\n")
    monkeypatch.setattr(
        INPUT_INDEX_STAGE, "_aggregate_peak_host_memory_bytes",
        lambda worker_count:
            freeze.resource_caps.training_host_memory_bytes + 1)

    with pytest.raises(INPUT_INDEX_STAGE.BeliefV2InputIndexControllerError,
                       match="resource cap drift"):
        run_training_input_index(
            root, freeze, admission, repo=Path("/unused"),
            review_marker=b"review", inventory={}, group_split={})
    partial = root / "training-input-index" / "result.partial"
    assert {path.name for path in partial.iterdir()} == {"index.json"}
    assert not (partial / "manifest.json").exists()
    assert not (root / "training-input-index" / "result").exists()


def test_training_tensor_cache_stage_reopens_exact_wiring_and_tamper_refuses(
        tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    freeze = _cpu_only_freeze(root)
    admission = _admission(freeze)
    primary, training_examples, calibration_examples, calibration = (
        _tiny_training_population(freeze))
    plans = {row.kind: row for row in freeze.cohorts}
    plan_sha = lambda row: hashlib.sha256(  # noqa: E731
        canonical_json_bytes(row.to_dict())).hexdigest()
    realizations = (
        primary,
        replace(
            primary,
            cohort_id="hard-geometry-label-permutation",
            kind="hard-geometry-label-permutation",
            cohort_plan_sha256=plan_sha(plans[
                "hard-geometry-label-permutation"]),
            comparator_cohort_id="synthetic-primary"),
        replace(
            primary, cohort_id="human-mixture", kind="human-mixture",
            cohort_plan_sha256=plan_sha(plans["human-mixture"]),
            comparator_cohort_id="synthetic-primary"),
        replace(
            primary, cohort_id="synthetic-scale-50",
            kind="synthetic-scale",
            cohort_plan_sha256=plan_sha(plans["synthetic-scale"]),
            comparator_cohort_id="synthetic-primary"),
    )
    natural_batch = collate_v2_training_examples(training_examples)
    control_batch, changed = collate_v2_label_control_examples(
        training_examples)
    calibration_batch = collate_v2_training_examples(calibration_examples)
    inputs = SimpleNamespace(
        index=SimpleNamespace(control_changed_cell_count=changed),
        realizations=realizations, common_calibration=calibration)
    source_index_sha = _sha("7")
    current_index_sha = _sha("8")
    source_derived_manifest = _cache_derived_manifest(human_group_char="a")
    current_derived_manifest = _cache_derived_manifest(human_group_char="b")
    source_derived_input_sha = _cache_derived_sha(source_derived_manifest)
    current_derived_input_sha = _cache_derived_sha(current_derived_manifest)
    cache_input_identity_sha = CACHE_IMPORT.cache_input_identity_sha256({
        "derived_manifest": source_derived_manifest})
    assert current_derived_input_sha != source_derived_input_sha
    assert CACHE_IMPORT.cache_input_identity_sha256({
        "derived_manifest": current_derived_manifest,
    }) == cache_input_identity_sha
    index_manifest = {
        "index_sha256": source_index_sha,
        "derived_input_sha256": source_derived_input_sha,
        "derived_manifest": source_derived_manifest,
    }
    monkeypatch.setattr(CACHE_STAGE, "_stage_gate", lambda **kwargs: None)
    monkeypatch.setattr(
        CACHE_STAGE, "reopen_training_input_index",
        lambda *args, **kwargs: (index_manifest, inputs))
    monkeypatch.setattr(
        CACHE_STAGE, "V2ArtifactRoundLoader",
        lambda *args, **kwargs: object())
    monkeypatch.setattr(
        CACHE_STAGE, "parallel_cache_worker_count",
        lambda runtime, host_memory_cap_bytes: 2)
    monkeypatch.setattr(
        CACHE_STAGE, "parallel_cache_build_topology",
        lambda runtime, host_memory_cap_bytes, build_count: (1, 2))
    real_executor = CACHE_STAGE.concurrent.futures.ThreadPoolExecutor
    executor_widths = []

    def recording_executor(*, max_workers):
        executor_widths.append(max_workers)
        return real_executor(max_workers=max_workers)

    monkeypatch.setattr(
        CACHE_STAGE.concurrent.futures, "ThreadPoolExecutor",
        recording_executor)

    def training_batches(index, realization, *, load_round):
        if realization.kind == "hard-geometry-label-permutation":
            pytest.fail(
                "control overlay reparsed source rows after primary cache")
        return iter((natural_batch,))

    monkeypatch.setattr(
        CACHE_STAGE, "iter_streaming_training_batches", training_batches)
    monkeypatch.setattr(
        CACHE_STAGE, "iter_streaming_calibration_batches",
        lambda *args, **kwargs: iter((calibration_batch,)))
    monkeypatch.setattr(CACHE_STAGE, "host_peak_memory_bytes", lambda: 1024)
    built_direct = []
    combined_overlay_builds = []
    cold_overlay_builds = []
    real_build_tensor_cache = CACHE_STAGE.build_tensor_cache
    real_build_label_overlay = CACHE_STAGE.build_label_overlay

    def serial_parallel_build(
            directory, *, schedule, mode, binding, deadline_check,
            progress, **_kwargs):
        built_direct.append(directory.name)
        batches = ((calibration_batch,) if mode == "calibration"
                   else (natural_batch,))
        return real_build_tensor_cache(
            directory, batches=lambda: iter(batches), binding=binding,
            deadline_check=deadline_check, progress=progress)

    def serial_parallel_build_with_overlay(
            directory, *, control_overlay_directory,
            control_overlay_id, expected_control_changed_cell_count,
            binding, deadline_check, progress,
            control_overlay_progress, **kwargs):
        combined_overlay_builds.append(directory.name)
        if expected_control_changed_cell_count != changed:
            pytest.fail("controller passed the wrong control-label dose")
        direct = serial_parallel_build(
            directory, schedule=kwargs["schedule"], mode="train",
            binding=binding, deadline_check=deadline_check,
            progress=progress)
        overlay = real_build_label_overlay(
            control_overlay_directory,
            batches=lambda: iter((control_batch,)),
            actor_directory=directory,
            actor_manifest_sha256=direct["manifest_sha256"],
            binding=binding, overlay_id=control_overlay_id,
            deadline_check=deadline_check,
            progress=control_overlay_progress)
        return direct, overlay

    def record_cold_overlay(*args, **kwargs):
        cold_overlay_builds.append(Path(args[0]).name)
        return real_build_label_overlay(*args, **kwargs)

    monkeypatch.setattr(
        CACHE_STAGE, "build_parallel_tensor_cache", serial_parallel_build)
    monkeypatch.setattr(
        CACHE_STAGE, "build_parallel_tensor_cache_with_control_overlay",
        serial_parallel_build_with_overlay)
    monkeypatch.setattr(
        CACHE_STAGE, "build_label_overlay", record_cold_overlay)

    manifest = run_training_tensor_cache(
        root, freeze, admission, repo=Path("/unused"),
        review_marker=b"review")
    assert built_direct == [
        "cache-synthetic-primary", "cache-human-mixture",
        "cache-synthetic-scale-50", "cache-common-calibration"]
    assert executor_widths == [1]
    assert combined_overlay_builds == ["cache-synthetic-primary"]
    assert cold_overlay_builds == []
    reopened, factories, calibration_factory, dose, stage_sha = (
        reopen_training_tensor_cache(
            root / "training-tensor-cache" / "result",
            freeze=freeze, admission=admission))
    assert reopened == manifest
    assert tuple(factories) == tuple(row.cohort_id for row in realizations)
    assert stage_sha == hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()
    assert dose == changed
    primary_batch = next(factories["synthetic-primary"]())
    control_reopened = next(
        factories["hard-geometry-label-permutation"]())
    assert primary_batch.decision_keys == control_reopened.decision_keys
    assert torch.equal(primary_batch.events, control_reopened.events)
    assert torch.equal(primary_batch.active_mask, control_reopened.active_mask)
    assert torch.equal(control_reopened.count_labels,
                       control_batch.count_labels)
    assert next(calibration_factory()).decision_keys \
        == calibration_batch.decision_keys
    assert manifest["test_split_cached"] is False
    assert manifest["training_authorized_by_this_artifact"] is False
    assert manifest["resources"][
        "cpu_nanoseconds_is_conservative_upper_bound"] is False

    cache_parent = root / "training-tensor-cache"
    cache_root = cache_parent / "result"
    imported_root = (tmp_path / "imported-evidence").resolve()
    imported_root.mkdir()
    imported_freeze = replace(
        freeze, evidence_root=str(imported_root),
        runtime=replace(freeze.runtime, boot_identity="f" * 64))
    imported_admission = _admission(imported_freeze)
    child_manifests = {
        row["directory"]: row["manifest_sha256"]
        for row in manifest["cohort_caches"]
    }
    child_manifests[manifest["common_calibration_cache"]["directory"]] = (
        manifest["common_calibration_cache"]["manifest_sha256"])
    import_spec = V2TensorCacheImportSpecV1(
        destination_evidence_root=imported_root,
        source_evidence_root=root,
        source_cache_root=cache_root,
        source_execution_git=freeze.execution_git,
        source_freeze_sha256=freeze.sha256(),
        source_admission_sha256=admission.sha256(),
        source_review_marker_sha256=_sha("a"),
        source_consumption_tombstone_sha256=_sha("b"),
        source_input_index_sha256=source_index_sha,
        source_input_index_manifest_sha256=_sha("c"),
        source_derived_input_sha256=source_derived_input_sha,
        source_cache_input_identity_sha256=cache_input_identity_sha,
        source_runtime_profile_sha256=hashlib.sha256(
            canonical_json_bytes(freeze.runtime.to_dict())).hexdigest(),
        source_stage_start_sha256=_sha("e"),
        child_manifest_sha256s=tuple(sorted(child_manifests.items())),
        required_uid=0, spec_sha256=_sha("f"))
    drifted_root = (tmp_path / "semantic-drift-evidence").resolve()
    drifted_root.mkdir()
    drifted_freeze = replace(
        imported_freeze, evidence_root=str(drifted_root))
    drifted_admission = _admission(drifted_freeze)
    drifted_spec = replace(
        import_spec, destination_evidence_root=drifted_root)
    monkeypatch.setattr(
        CACHE_STAGE, "load_tensor_cache_import_spec",
        lambda candidate: ({
            str(imported_root): import_spec,
            str(drifted_root): drifted_spec,
        }.get(candidate.evidence_root)))
    # A fresh freeze changes the raw index bytes while preserving the exact
    # tensor population/schedules.  Its broader derived identity also changes
    # because human capture provenance is deliberately retained there.
    index_manifest["index_sha256"] = current_index_sha
    index_manifest["derived_input_sha256"] = _cache_derived_sha(
        _cache_derived_manifest(
            human_group_char="c", human_train_char="0"))
    index_manifest["derived_manifest"] = _cache_derived_manifest(
        human_group_char="c", human_train_char="0")
    with pytest.raises(
            CACHE_STAGE.BeliefV2TensorCacheControllerError,
            match="cache-input semantic identity drift"):
        run_training_tensor_cache(
            drifted_root, drifted_freeze, drifted_admission,
            repo=Path("/unused"), review_marker=b"review")
    drifted_partial = (
        drifted_root / "training-tensor-cache" / "result.partial")
    assert {path.name for path in drifted_partial.iterdir()} == {
        "stage-start.json"}
    assert not (
        drifted_root / "training-tensor-cache" / "result").exists()
    index_manifest["derived_input_sha256"] = current_derived_input_sha
    index_manifest["derived_manifest"] = current_derived_manifest
    imported_manifest = run_training_tensor_cache(
        imported_root, imported_freeze, imported_admission,
        repo=Path("/unused"), review_marker=b"review")
    assert executor_widths == [1]
    assert built_direct == [
        "cache-synthetic-primary", "cache-human-mixture",
        "cache-synthetic-scale-50", "cache-common-calibration"]
    assert combined_overlay_builds == ["cache-synthetic-primary"]
    assert cold_overlay_builds == []
    imported_cache_root = (
        imported_root / "training-tensor-cache" / "result")
    assert {path.name for path in imported_cache_root.iterdir()} == {
        "manifest.json", "stage-start.json", "cache-import.json"}
    assert imported_manifest["cache_storage"]["kind"] \
        == "immutable-external-cache-v1"
    assert imported_manifest["resources"]["external_cache_reused"] is True
    assert imported_manifest["resources"]["cache_worker_count"] == 0
    assert imported_manifest["cache_worker_count"] == 0
    assert imported_manifest["parallel_actor_cache_build"] is False
    assert imported_manifest["training_input_index_sha256"] \
        == current_index_sha
    import_receipt = json.loads(
        (imported_cache_root / "cache-import.json").read_bytes())
    assert import_receipt["schema"] \
        == "belief-v1-v2-tensor-cache-import-receipt-v2"
    assert import_receipt["source_input_index_sha256"] == source_index_sha
    assert import_receipt["current_input_index_sha256"] == current_index_sha
    assert import_receipt["source_derived_input_sha256"] \
        == source_derived_input_sha
    assert import_receipt["current_derived_input_sha256"] \
        == current_derived_input_sha
    assert import_receipt["source_cache_input_identity_sha256"] \
        == cache_input_identity_sha
    assert import_receipt["current_cache_input_identity_sha256"] \
        == cache_input_identity_sha
    assert all(row["binding"]["source_index_sha256"] == source_index_sha
               for row in imported_manifest["cohort_caches"])
    assert imported_manifest["common_calibration_cache"]["binding"][
        "source_index_sha256"] == source_index_sha
    imported_reopened, imported_factories, _, imported_dose, _ = (
        reopen_training_tensor_cache(
            imported_cache_root, freeze=imported_freeze,
            admission=imported_admission))
    assert imported_reopened == imported_manifest
    assert imported_dose == changed
    assert next(imported_factories["synthetic-primary"]()).decision_keys \
        == natural_batch.decision_keys
    lightweight_manifest, lightweight_factories, _, _, _ = (
        reopen_training_tensor_cache(
            imported_cache_root, freeze=imported_freeze,
            admission=imported_admission, verify_all_bytes=False))
    assert lightweight_manifest == imported_manifest
    assert next(lightweight_factories["synthetic-primary"]()).decision_keys \
        == natural_batch.decision_keys
    import_receipt_path = imported_cache_root / "cache-import.json"
    import_receipt_raw = import_receipt_path.read_bytes()
    import_receipt_path.chmod(0o600)
    import_receipt_path.write_bytes(import_receipt_raw + b" ")
    import_receipt_path.chmod(0o400)
    with pytest.raises(
            CACHE_STAGE.BeliefV2TensorCacheControllerError,
            match="import receipt reconstruction drift"):
        reopen_training_tensor_cache(
            imported_cache_root, freeze=imported_freeze,
            admission=imported_admission)
    import_receipt_path.chmod(0o600)
    import_receipt_path.write_bytes(import_receipt_raw)
    import_receipt_path.chmod(0o400)

    index_manifest["index_sha256"] = source_index_sha
    index_manifest["derived_input_sha256"] = source_derived_input_sha
    index_manifest["derived_manifest"] = source_derived_manifest

    original_primary_sha = next(
        row["manifest_sha256"] for row in manifest["cohort_caches"]
        if row["cohort_id"] == "synthetic-primary")
    partial = cache_parent / "result.partial"
    cache_root.rename(partial)
    (partial / "manifest.json").unlink()
    for name in (
            "overlay-hard-geometry-label-permutation",
            "cache-human-mixture", "cache-synthetic-scale-50",
            "cache-common-calibration"):
        shutil.rmtree(partial / name)
    manifest = run_training_tensor_cache(
        root, freeze, admission, repo=Path("/unused"),
        review_marker=b"review")
    assert executor_widths == [1, 1]
    assert combined_overlay_builds == ["cache-synthetic-primary"]
    assert cold_overlay_builds == [
        "overlay-hard-geometry-label-permutation"]
    assert manifest["resources"]["resumed_from_exact_partial"] is True
    assert manifest["resources"][
        "cpu_nanoseconds_is_conservative_upper_bound"] is True
    assert manifest["resources"]["cpu_nanoseconds"] == (
        manifest["resources"]["wall_nanoseconds"] * 3)
    assert next(
        row["manifest_sha256"] for row in manifest["cohort_caches"]
        if row["cohort_id"] == "synthetic-primary") \
        == original_primary_sha
    reopened, _, _, _, _ = reopen_training_tensor_cache(
        cache_root, freeze=freeze, admission=admission)
    assert reopened == manifest

    primary_manifest = json.loads(
        (cache_root / "cache-synthetic-primary" / "manifest.json")
        .read_bytes())
    actor_path = (cache_root / "cache-synthetic-primary"
                  / primary_manifest["batches"][0]["actor_file"])
    raw = actor_path.read_bytes()
    actor_path.chmod(0o600)
    actor_path.write_bytes(raw[:-1] + bytes((raw[-1] ^ 1,)))
    actor_path.chmod(0o400)
    with pytest.raises(
            CACHE_STAGE.BeliefV2TensorCacheControllerError,
            match="reopen refused|byte drift"):
        reopen_training_tensor_cache(
            cache_root, freeze=freeze, admission=admission)
    index_manifest["index_sha256"] = current_index_sha
    index_manifest["derived_input_sha256"] = current_derived_input_sha
    index_manifest["derived_manifest"] = current_derived_manifest
    with pytest.raises(
            CACHE_STAGE.BeliefV2TensorCacheControllerError,
            match="reopen refused|byte drift"):
        reopen_training_tensor_cache(
            imported_cache_root, freeze=imported_freeze,
            admission=imported_admission)
    _, tampered_factories, _, _, _ = reopen_training_tensor_cache(
        imported_cache_root, freeze=imported_freeze,
        admission=imported_admission, verify_all_bytes=False)
    with pytest.raises(ValueError, match="batch 0 byte drift"):
        next(tampered_factories["synthetic-primary"]())
    actor_path.chmod(0o600)
    actor_path.write_bytes(raw)
    actor_path.chmod(0o400)
    index_manifest["index_sha256"] = source_index_sha
    index_manifest["derived_input_sha256"] = source_derived_input_sha
    index_manifest["derived_manifest"] = source_derived_manifest

    # A measured cap failure after every reusable cache is complete must
    # publish a durable refusal before raising. The same admission can never
    # resume and relabel that over-cap attempt as a successful cache stage.
    cache_root.rename(partial)
    (partial / "manifest.json").unlink()
    observed_peak = freeze.resource_caps.training_host_memory_bytes + 1
    monkeypatch.setattr(
        CACHE_STAGE, "_aggregate_peak_host_memory_bytes",
        lambda worker_count: observed_peak)
    with pytest.raises(
            CACHE_STAGE.BeliefV2TensorCacheControllerError,
            match="resource cap exceeded and recorded"):
        run_training_tensor_cache(
            root, freeze, admission, repo=Path("/unused"),
            review_marker=b"review")
    refusal = reopen_tensor_cache_resource_refusal(
        partial / CACHE_STAGE.RESOURCE_REFUSAL_FILENAME,
        freeze=freeze, admission=admission,
        input_index_sha256=index_manifest["index_sha256"])
    assert refusal["exceeded_dimensions"] == ["peak_host_memory_bytes"]
    assert refusal["peak_host_memory_bytes"] == observed_peak
    assert refusal["retry_authorized"] is False
    assert refusal["stage_seal_authorized"] is False
    assert not cache_root.exists()
    with pytest.raises(
            CACHE_STAGE.BeliefV2TensorCacheControllerError,
            match="refused partial cannot resume"):
        run_training_tensor_cache(
            root, freeze, admission, repo=Path("/unused"),
            review_marker=b"review")
    refusal_path = partial / CACHE_STAGE.RESOURCE_REFUSAL_FILENAME
    refusal_raw = refusal_path.read_bytes()
    refusal_path.chmod(0o600)
    refusal_path.write_bytes(canonical_json_bytes(
        dict(refusal, stage_seal_authorized=True)))
    refusal_path.chmod(0o400)
    with pytest.raises(
            CACHE_STAGE.BeliefV2TensorCacheControllerError,
            match="resource refusal drift"):
        reopen_tensor_cache_resource_refusal(
            refusal_path, freeze=freeze, admission=admission,
            input_index_sha256=index_manifest["index_sha256"])
    refusal_path.chmod(0o600)
    refusal_path.write_bytes(refusal_raw)
    refusal_path.chmod(0o400)


def test_training_input_index_deadline_records_refusal_cannot_seal_or_retry(
        tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    freeze = _cpu_only_freeze(root)
    admission = _admission(freeze)
    monkeypatch.setattr(
        INPUT_INDEX_STAGE, "_stage_gate", lambda **kwargs: None)
    wall = freeze.resource_caps.training_wall_seconds * 1_000_000_000
    started = 1_000_000_000
    times = iter((started, started + wall - 60_000_000_000))
    monkeypatch.setattr(
        INPUT_INDEX_STAGE.time, "monotonic_ns", lambda: next(times))
    advanced = []

    def refuse_before_source(*args, deadline_check, **kwargs):
        deadline_check("before-unit", 0)
        advanced.append(True)
        raise AssertionError("expired input-index construction advanced")

    monkeypatch.setattr(
        INPUT_INDEX_STAGE, "reopen_streaming_training_inputs",
        refuse_before_source)
    kwargs = dict(
        repo=Path("/unused"), review_marker=b"review",
        inventory={}, group_split={})
    with pytest.raises(INPUT_INDEX_STAGE.BeliefV2InputIndexControllerError,
                       match="construction refused"):
        run_training_input_index(root, freeze, admission, **kwargs)
    assert advanced == []
    partial = root / "training-input-index" / "result.partial"
    assert {path.name for path in partial.iterdir()} \
        == {"deadline-refusal.json"}
    refusal = reopen_deadline_refusal(
        partial / "deadline-refusal.json",
        freeze_sha256=freeze.sha256(), admission_sha256=admission.sha256())
    assert refusal.stage == "training"
    assert refusal.slot == "input-index"
    assert refusal.phase == "before-unit"
    assert not (root / "training-input-index" / "result").exists()
    with pytest.raises(INPUT_INDEX_STAGE.BeliefV2InputIndexControllerError,
                       match="slot is occupied"):
        run_training_input_index(root, freeze, admission, **kwargs)


def test_cpu_only_device_stage_publishes_three_measured_repeats(
        tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    freeze = _cpu_only_freeze(root)
    admission = _admission(freeze)
    primary, training_examples, _, _ = _tiny_training_population(freeze)
    plan, result = _cpu_fallback_qualification(freeze)
    assert len(plan.arm_order) == 4
    assert result.selected_device == "cpu"
    monkeypatch.setattr(
        "shengji.rl.belief_v2_device_controller._stage_gate",
        lambda **kwargs: None)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_device_controller._expected_plan",
        lambda *args, **kwargs: plan)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_device_controller."
        "run_device_qualification_in_memory",
        lambda **kwargs: (plan, result))
    manifest = run_device_qualification(
        root, freeze, admission, repo=Path("/unused"),
        review_marker=b"review", primary=primary,
        primary_examples=training_examples)
    reopened, reopened_plan, reopened_result = reopen_device_qualification(
        root / "device-qualification" / "result",
        freeze=freeze, admission=admission, primary=primary)
    assert reopened == manifest
    assert reopened_plan == plan
    assert reopened_result == result
    assert manifest["arm_count"] == 4
    assert manifest["measured_arm_count"] == 3
    assert manifest["accelerator_retained"] is False
    assert manifest["selected_training_process_count"] \
        == len(freeze.cohorts)
    assert manifest["selected_process_peak_host_memory_bytes"] == 1024
    assert manifest[
        "aggregate_training_peak_host_memory_upper_bound_bytes"] \
        == 1024 * len(freeze.cohorts)


def test_cpu_device_stage_refuses_concurrent_aggregate_host_memory(
        tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    freeze = _cpu_only_freeze(root)
    admission = _admission(freeze)
    primary, training_examples, _, _ = _tiny_training_population(freeze)
    plan, original = _cpu_fallback_qualification(freeze)
    per_process_peak = (
        freeze.resource_caps.training_host_memory_bytes
        // len(freeze.cohorts) + 1)
    result = derive_qualification_result(plan, tuple(
        replace(arm, peak_host_memory_bytes=per_process_peak)
        for arm in original.arms))
    assert per_process_peak \
        < freeze.resource_caps.training_host_memory_bytes
    monkeypatch.setattr(
        "shengji.rl.belief_v2_device_controller._stage_gate",
        lambda **kwargs: None)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_device_controller._expected_plan",
        lambda *args, **kwargs: plan)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_device_controller."
        "run_device_qualification_in_memory",
        lambda **kwargs: (plan, result))
    with pytest.raises(BeliefV2DeviceControllerError,
                       match="aggregate host memory cap"):
        run_device_qualification(
            root, freeze, admission, repo=Path("/unused"),
            review_marker=b"review", primary=primary,
            primary_examples=training_examples)
    partial = root / "device-qualification" / "result.partial"
    assert partial.is_dir()
    assert tuple(partial.iterdir()) == ()
    assert not (root / "device-qualification" / "result").exists()


def test_device_stage_streaming_wiring_never_calls_materialized_runner(
        tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    freeze = _cpu_only_freeze(root)
    admission = _admission(freeze)
    primary, _, _, _ = _tiny_training_population(freeze)
    plan, result = _cpu_fallback_qualification(freeze)
    index = object()
    loader = lambda source: ()
    observed = []
    monkeypatch.setattr(
        "shengji.rl.belief_v2_device_controller._stage_gate",
        lambda **kwargs: None)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_device_controller._expected_plan",
        lambda *args, **kwargs: plan)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_device_controller."
        "run_device_qualification_in_memory",
        lambda **kwargs: pytest.fail("materialized qualification used"))

    def streamed(**kwargs):
        observed.append(kwargs)
        return plan, result

    monkeypatch.setattr(
        "shengji.rl.belief_v2_device_controller."
        "run_device_qualification_streaming", streamed)
    manifest = run_device_qualification(
        root, freeze, admission, repo=Path("/unused"),
        review_marker=b"review", primary=primary,
        primary_examples=None, streaming_index=index, load_round=loader)
    assert manifest["selected_device"] == "cpu"
    assert len(observed) == 1
    assert observed[0]["streaming_index"] is index
    assert observed[0]["load_round"] is loader


def test_device_stage_cache_wiring_never_calls_streaming_or_materialized(
        tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    freeze = _cpu_only_freeze(root)
    admission = _admission(freeze)
    primary, _, _, _ = _tiny_training_population(freeze)
    plan, result = _cpu_fallback_qualification(freeze)
    factory = lambda: iter(())
    observed = []
    monkeypatch.setattr(
        "shengji.rl.belief_v2_device_controller._stage_gate",
        lambda **kwargs: None)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_device_controller._expected_plan",
        lambda *args, **kwargs: plan)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_device_controller."
        "run_device_qualification_in_memory",
        lambda **kwargs: pytest.fail("materialized qualification used"))
    monkeypatch.setattr(
        "shengji.rl.belief_v2_device_controller."
        "run_device_qualification_streaming",
        lambda **kwargs: pytest.fail("streaming qualification used"))

    def cached(**kwargs):
        observed.append(kwargs)
        return plan, result

    monkeypatch.setattr(
        "shengji.rl.belief_v2_device_controller."
        "run_device_qualification_from_batch_factory", cached)
    manifest = run_device_qualification(
        root, freeze, admission, repo=Path("/unused"),
        review_marker=b"review", primary=primary,
        primary_examples=None, batch_factory=factory)
    assert manifest["selected_device"] == "cpu"
    assert len(observed) == 1
    assert observed[0]["batch_factory"] is factory


def test_training_stage_publishes_reopenable_cpu_fallback_checkpoints(
        tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    freeze = _freeze(root)
    admission = _admission(freeze)
    primary, training_examples, calibration, calibration_schedule = (
        _tiny_training_population(freeze))
    qualification_plan, qualification_result = (
        _cpu_fallback_qualification(freeze))
    assert qualification_result.selected_device == "cpu"
    monkeypatch.setattr(
        "shengji.rl.belief_v2_training_controller._stage_gate",
        lambda **kwargs: None)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_training_controller._validate_device_binding",
        lambda *args, **kwargs: "cpu")
    monkeypatch.setattr(COHORT_STAGE, "TRAIN_MAX_EPOCHS", 1)
    previous = torch.are_deterministic_algorithms_enabled()
    torch.use_deterministic_algorithms(True)
    try:
        progress = []
        progress_stream = io.StringIO()
        ticks = iter(range(10_000))
        real_reporter = V2ProgressReporter(
            stage="training", worker=primary.cohort_id,
            stream=progress_stream, clock=lambda: next(ticks))

        def report_progress(*row):
            progress.append(row)
            real_reporter.update(*row)

        manifest = run_training_cohort(
            root, freeze, admission, repo=Path("/unused"),
            review_marker=b"review", primary=primary,
            realization=primary, training_examples=training_examples,
            calibration=calibration_schedule,
            calibration_examples=calibration,
            qualification_plan=qualification_plan,
            qualification_result=qualification_result,
            progress=report_progress)
        directory = root / "training" / primary.cohort_id
        reopened, trained = reopen_training_cohort(
            directory, freeze=freeze, admission=admission,
            primary=primary, realization=primary,
            training_examples=training_examples,
            calibration=calibration_schedule,
            calibration_examples=calibration,
            qualification_plan=qualification_plan,
            qualification_result=qualification_result)
    finally:
        torch.use_deterministic_algorithms(previous)
    assert reopened == manifest
    assert progress[0] == (0, 1, "training-epochs")
    assert progress[1] == (0, 2, "training-batches")
    assert progress[-3:] == [
        (1, 2, "training-batches"),
        (2, 2, "training-batches"),
        (1, 1, "training-epochs")]
    progress_rows = [json.loads(line.removeprefix(PROGRESS_PREFIX))
                     for line in progress_stream.getvalue().splitlines()]
    assert [(row["completed_units"], row["total_units"], row["phase"])
            for row in progress_rows] == list(progress)
    assert trained.training_device == "cpu"
    assert manifest["resources"]["peak_host_memory_bytes"] > 0
    assert manifest["resources"]["peak_device_memory_bytes"] == 0
    assert manifest["test_split_opened"] is False
    assert manifest["deployment_authorized"] is False

    # Rehash every persisted layer that states the calibration loss.  The
    # journal, trained artifact, and stage manifest are then self-consistent;
    # only independent source re-scoring of the exact epoch model can refuse.
    journal = directory / "epoch-journal" / "epoch-0001"
    curves_path = journal / "curves.json"
    journal_manifest_path = journal / "manifest.json"
    trained_path = directory / "trained-cohort.json"
    stage_manifest_path = directory / "manifest.json"
    originals = {path: path.read_bytes() for path in (
        curves_path, journal_manifest_path, trained_path,
        stage_manifest_path)}
    curves_payload = json.loads(originals[curves_path])
    curve_row = curves_payload["epochs"][0]
    curve_row["member_calibration_loss_nanonats"] = [
        value + 1
        for value in curve_row["member_calibration_loss_nanonats"]]
    curve_row["cohort_mean_calibration_loss_nanonats"] += 1
    curves_raw = canonical_json_bytes(curves_payload)
    journal_payload = json.loads(originals[journal_manifest_path])
    journal_payload["files"]["curves.json"] = {
        "byte_count": len(curves_raw),
        "sha256": hashlib.sha256(curves_raw).hexdigest(),
    }
    journal_raw = canonical_json_bytes(journal_payload)
    trained_payload = json.loads(originals[trained_path])
    trained_payload["epochs"][0] = curve_row
    trained_raw = canonical_json_bytes(trained_payload)
    stage_payload = json.loads(originals[stage_manifest_path])
    stage_payload["trained_manifest_byte_count"] = len(trained_raw)
    stage_payload["trained_manifest_sha256"] = hashlib.sha256(
        trained_raw).hexdigest()
    stage_payload["epoch_journal"]["head_manifest_sha256"] = (
        hashlib.sha256(journal_raw).hexdigest())
    stage_raw = canonical_json_bytes(stage_payload)
    for path, raw in ((curves_path, curves_raw),
                      (journal_manifest_path, journal_raw),
                      (trained_path, trained_raw),
                      (stage_manifest_path, stage_raw)):
        path.chmod(0o600)
        path.write_bytes(raw)
        path.chmod(0o400)
    deterministic = torch.are_deterministic_algorithms_enabled()
    torch.use_deterministic_algorithms(True)
    try:
        with pytest.raises(BeliefV2TrainingControllerError,
                           match="epoch calibration loss re-score drift"):
            reopen_training_cohort(
                directory, freeze=freeze, admission=admission,
                primary=primary, realization=primary,
                training_examples=training_examples,
                calibration=calibration_schedule,
                calibration_examples=calibration,
                qualification_plan=qualification_plan,
                qualification_result=qualification_result)
    finally:
        torch.use_deterministic_algorithms(deterministic)
        for path, raw in originals.items():
            path.chmod(0o600)
            path.write_bytes(raw)
            path.chmod(0o400)

    checkpoint = directory / "member-00.checkpoint.bin"
    checkpoint.chmod(0o600)
    checkpoint.write_bytes(checkpoint.read_bytes() + b"x")
    checkpoint.chmod(0o400)
    with pytest.raises(BeliefV2TrainingControllerError,
                       match="persisted trained cohort"):
        reopen_training_cohort(
            directory, freeze=freeze, admission=admission,
            primary=primary, realization=primary,
            training_examples=training_examples,
            calibration=calibration_schedule,
            calibration_examples=calibration,
            qualification_plan=qualification_plan,
            qualification_result=qualification_result)


def test_training_stage_streaming_wiring_never_calls_materialized_trainer(
        tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    freeze = _cpu_only_freeze(root)
    admission = _admission(freeze)
    primary, training_examples, calibration, calibration_schedule = (
        _tiny_training_population(freeze))
    qualification_plan, qualification_result = (
        _cpu_fallback_qualification(freeze))
    monkeypatch.setattr(
        TRAINING_STAGE, "_stage_gate", lambda **kwargs: None)
    monkeypatch.setattr(
        TRAINING_STAGE, "_validate_device_binding",
        lambda *args, **kwargs: "cpu")
    monkeypatch.setattr(COHORT_STAGE, "TRAIN_MAX_EPOCHS", 1)
    previous = torch.are_deterministic_algorithms_enabled()
    torch.use_deterministic_algorithms(True)
    try:
        expected = COHORT_STAGE.train_v2_cohort_in_memory(
            primary, training_examples, calibration_schedule, calibration,
            device="cpu")
        observed = []
        streaming_index = SimpleNamespace(control_changed_cell_count=0)
        loader = lambda source: ()

        def streamed(realization, schedule, *, index, load_round, device,
                     deadline_check, resume_state, epoch_checkpoint,
                     progress):
            observed.append((realization, schedule, index, load_round, device))
            assert progress is None
            assert resume_state is None
            return COHORT_STAGE.train_v2_cohort_in_memory(
                primary, training_examples, calibration_schedule,
                calibration, device=device,
                deadline_check=deadline_check,
                epoch_checkpoint=epoch_checkpoint)

        monkeypatch.setattr(
            TRAINING_STAGE, "train_v2_cohort_streaming", streamed)
        monkeypatch.setattr(
            TRAINING_STAGE, "train_v2_cohort_in_memory",
            lambda *args, **kwargs: pytest.fail(
                "materialized training path used"))
        calibration_batches = COHORT_STAGE._calibration_batches(
            calibration_schedule, calibration)
        monkeypatch.setattr(
            TRAINING_STAGE, "iter_streaming_calibration_batches",
            lambda *args, **kwargs: iter(calibration_batches))
        manifest = run_training_cohort(
            root, freeze, admission, repo=Path("/unused"),
            review_marker=b"review", primary=primary,
            realization=primary, training_examples=None,
            calibration=calibration_schedule, calibration_examples=None,
            qualification_plan=qualification_plan,
            qualification_result=qualification_result,
            streaming_index=streaming_index, load_round=loader)
    finally:
        torch.use_deterministic_algorithms(previous)
    assert observed == [(
        primary, calibration_schedule, streaming_index, loader, "cpu")]
    assert manifest["realization_sha256"] == primary.sha256()
    assert manifest["test_split_opened"] is False


def test_training_stage_cache_factory_wiring_seals_and_reopens_exactly(
        tmp_path, monkeypatch):
    """Witness the production cache wiring at the controller boundary."""
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    freeze = _cpu_only_freeze(root)
    admission = _admission(freeze)
    primary, training_examples, calibration_examples, calibration = (
        _tiny_training_population(freeze))
    qualification_plan, qualification_result = (
        _cpu_fallback_qualification(freeze))
    training_batches, control_dose = COHORT_STAGE._training_batches(
        primary, training_examples)
    calibration_batches = COHORT_STAGE._calibration_batches(
        calibration, calibration_examples)
    assert control_dose == 0
    cache_manifest_sha256 = _sha("7")
    observed = []
    real_cached = COHORT_STAGE.train_v2_cohort_from_batch_factories

    monkeypatch.setattr(TRAINING_STAGE, "_stage_gate", lambda **kwargs: None)
    monkeypatch.setattr(
        TRAINING_STAGE, "_validate_device_binding",
        lambda *args, **kwargs: "cpu")
    monkeypatch.setattr(COHORT_STAGE, "TRAIN_MAX_EPOCHS", 1)
    monkeypatch.setattr(
        TRAINING_STAGE, "train_v2_cohort_streaming",
        lambda *args, **kwargs: pytest.fail("streaming training path used"))
    monkeypatch.setattr(
        TRAINING_STAGE, "train_v2_cohort_in_memory",
        lambda *args, **kwargs: pytest.fail("materialized training path used"))

    def cached(*args, training_batches, calibration_batches, **kwargs):
        train_rows = tuple(training_batches())
        calibration_rows = tuple(calibration_batches())
        observed.append((train_rows, calibration_rows))
        return real_cached(
            *args,
            training_batches=lambda: iter(train_rows),
            calibration_batches=lambda: iter(calibration_rows),
            **kwargs)

    monkeypatch.setattr(
        TRAINING_STAGE, "train_v2_cohort_from_batch_factories", cached)
    fast_reopens = []
    real_fast_reopen = (
        TRAINING_STAGE.reopen_training_cohort_checkpoint_identity)

    def fast_reopen(*args, **kwargs):
        fast_reopens.append((args, kwargs))
        return real_fast_reopen(*args, **kwargs)

    monkeypatch.setattr(
        TRAINING_STAGE, "reopen_training_cohort_checkpoint_identity",
        fast_reopen)
    monkeypatch.setattr(
        TRAINING_STAGE, "reopen_training_cohort",
        lambda *args, **kwargs: pytest.fail(
            "cached publish repeated the full saved-epoch proof"))
    previous = torch.are_deterministic_algorithms_enabled()
    torch.use_deterministic_algorithms(True)
    try:
        manifest = run_training_cohort(
            root, freeze, admission, repo=Path("/unused"),
            review_marker=b"review", primary=primary,
            realization=primary, training_examples=None,
            calibration=calibration, calibration_examples=None,
            qualification_plan=qualification_plan,
            qualification_result=qualification_result,
            training_batch_factory=lambda: iter(training_batches),
            calibration_batch_factory=lambda: iter(calibration_batches),
            cache_manifest_sha256=cache_manifest_sha256,
            cache_control_dose=0)
    finally:
        torch.use_deterministic_algorithms(previous)
    assert len(observed) == 1
    assert tuple(row.decision_keys for row in observed[0][0]) \
        == tuple(row.decision_keys for row in training_batches)
    assert tuple(row.decision_keys for row in observed[0][1]) \
        == tuple(row.decision_keys for row in calibration_batches)
    assert manifest["tensor_cache_stage_manifest_sha256"] \
        == cache_manifest_sha256
    assert manifest["test_split_opened"] is False
    assert (root / "training" / primary.cohort_id).is_dir()
    assert len(fast_reopens) == 1
    assert fast_reopens[0][1]["cache_manifest_sha256"] \
        == cache_manifest_sha256


def test_training_controller_resumes_only_latest_epoch_and_matches_clean_run(
        tmp_path, monkeypatch, request):
    previous_determinism = torch.are_deterministic_algorithms_enabled()
    torch.use_deterministic_algorithms(True)
    request.addfinalizer(lambda: torch.use_deterministic_algorithms(
        previous_determinism))
    root = (tmp_path / "resumed").resolve()
    root.mkdir()
    freeze = _cpu_only_freeze(root)
    admission = _admission(freeze)
    primary, training_examples, calibration, calibration_schedule = (
        _tiny_training_population(freeze))
    qualification_plan, qualification_result = (
        _cpu_fallback_qualification(freeze))
    monkeypatch.setattr(TRAINING_STAGE, "_stage_gate", lambda **kwargs: None)
    monkeypatch.setattr(
        TRAINING_STAGE, "_validate_device_binding",
        lambda *args, **kwargs: "cpu")
    monkeypatch.setattr(COHORT_STAGE, "TRAIN_MAX_EPOCHS", 2)
    real_publish = TRAINING_STAGE.publish_epoch_resume_state
    interrupted = []

    def publish_then_stop(*args, **kwargs):
        result = real_publish(*args, **kwargs)
        interrupted.append(result["epoch"])
        raise RuntimeError("simulated process loss after durable epoch")

    monkeypatch.setattr(
        TRAINING_STAGE, "publish_epoch_resume_state", publish_then_stop)
    kwargs = dict(
        repo=Path("/unused"), review_marker=b"review", primary=primary,
        realization=primary, training_examples=training_examples,
        calibration=calibration_schedule, calibration_examples=calibration,
        qualification_plan=qualification_plan,
        qualification_result=qualification_result)
    with pytest.raises(BeliefV2TrainingControllerError,
                       match="cohort training refused"):
        run_training_cohort(root, freeze, admission, **kwargs)
    assert interrupted == [1]
    partial = root / "training" / f"{primary.cohort_id}.partial"
    assert {path.name for path in partial.iterdir()} == {"epoch-journal"}

    monkeypatch.setattr(
        TRAINING_STAGE, "publish_epoch_resume_state", real_publish)
    resumed_manifest = run_training_cohort(
        root, freeze, admission, **kwargs)
    assert resumed_manifest["epoch_journal"]["exact_resume_count"] == 1

    clean_root = (tmp_path / "clean").resolve()
    clean_root.mkdir()
    clean_freeze = replace(freeze, evidence_root=str(clean_root))
    clean_admission = replace(
        admission, freeze_sha256=clean_freeze.sha256(),
        evidence_root=str(clean_root))
    clean_manifest = run_training_cohort(
        clean_root, clean_freeze, clean_admission, **{
            **kwargs,
            "primary": primary,
            "realization": primary,
        })
    resumed_dir = root / "training" / primary.cohort_id
    clean_dir = clean_root / "training" / primary.cohort_id
    assert [
        (resumed_dir / f"member-{index:02d}.checkpoint.bin").read_bytes()
        for index in range(8)] == [
        (clean_dir / f"member-{index:02d}.checkpoint.bin").read_bytes()
        for index in range(8)]
    assert resumed_manifest["cohort_id"] == clean_manifest["cohort_id"]


def test_training_controller_seals_deadline_truncation_and_cannot_mask_it(
        tmp_path, monkeypatch, request):
    previous_determinism = torch.are_deterministic_algorithms_enabled()
    torch.use_deterministic_algorithms(True)
    request.addfinalizer(lambda: torch.use_deterministic_algorithms(
        previous_determinism))
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    freeze = _cpu_only_freeze(root)
    admission = _admission(freeze)
    primary, training_examples, calibration, calibration_schedule = (
        _tiny_training_population(freeze))
    qualification_plan, qualification_result = (
        _cpu_fallback_qualification(freeze))
    monkeypatch.setattr(TRAINING_STAGE, "_stage_gate", lambda **kwargs: None)
    monkeypatch.setattr(
        TRAINING_STAGE, "_validate_device_binding",
        lambda *args, **kwargs: "cpu")
    monkeypatch.setattr(COHORT_STAGE, "TRAIN_MAX_EPOCHS", 3)

    class TruncateAfterOne:
        def check(self, *, phase, next_unit_index,
                  observed_monotonic_nanoseconds):
            if phase == "after-unit":
                raise BeliefV2DeadlineError(V2DeadlineRefusalV1(
                    freeze_sha256=freeze.sha256(),
                    admission_sha256=admission.sha256(), stage="training",
                    slot=primary.cohort_id, phase=phase,
                    next_unit_index=next_unit_index,
                    started_monotonic_nanoseconds=1,
                    observed_monotonic_nanoseconds=10,
                    hard_deadline_monotonic_nanoseconds=11,
                    wall_cap_nanoseconds=10,
                    next_unit_wall_estimate_nanoseconds=6,
                    safety_reserve_nanoseconds=3,
                    required_remaining_nanoseconds=3,
                    observed_remaining_nanoseconds=1))

    monkeypatch.setattr(
        TRAINING_STAGE, "stage_deadline",
        lambda *args, **kwargs: TruncateAfterOne())
    kwargs = dict(
        repo=Path("/unused"), review_marker=b"review", primary=primary,
        realization=primary, training_examples=training_examples,
        calibration=calibration_schedule, calibration_examples=calibration,
        qualification_plan=qualification_plan,
        qualification_result=qualification_result)
    manifest = run_training_cohort(root, freeze, admission, **kwargs)
    assert manifest["truncated_by_deadline"] is True
    assert manifest["deadline_refusal"]["final_artifact_sealed"] is True
    assert manifest["deadline_refusal"]["test_split_open_authorized"] \
        is False
    final = root / "training" / primary.cohort_id
    reopened_manifest, trained = reopen_training_cohort(
        final, freeze=freeze, admission=admission, primary=primary,
        realization=primary, training_examples=training_examples,
        calibration=calibration_schedule,
        calibration_examples=calibration,
        qualification_plan=qualification_plan,
        qualification_result=qualification_result)
    assert reopened_manifest == manifest
    assert trained.truncated_by_deadline is True

    monkeypatch.setattr(V2_CONTROLLER, "validate_execution_freeze",
                        lambda value: None)
    monkeypatch.setattr(V2_CONTROLLER, "reauthenticate_pipeline_admission",
                        lambda *args, **kwargs: None)
    monkeypatch.setattr(V2_CONTROLLER, "validate_live_execution",
                        lambda *args, **kwargs: None)
    monkeypatch.setattr(
        V2_CONTROLLER, "build_training_device_profile",
        lambda value: freeze.training_device_profile)
    V2_CONTROLLER._stage_gate(
        root=root, repo=tmp_path.resolve(), freeze=freeze,
        admission=admission, review_marker=b"review")

    trained_path = final / "trained-cohort.json"
    payload = json.loads(trained_path.read_bytes())
    payload["truncated_by_deadline"] = False
    trained_path.chmod(0o600)
    trained_path.write_bytes(canonical_json_bytes(payload))
    trained_path.chmod(0o400)
    with pytest.raises(BeliefV2TrainingControllerError,
                       match="manifest reconstruction"):
        reopen_training_cohort(
            final, freeze=freeze, admission=admission, primary=primary,
            realization=primary, training_examples=training_examples,
            calibration=calibration_schedule,
            calibration_examples=calibration,
            qualification_plan=qualification_plan,
            qualification_result=qualification_result)


def test_training_deadline_records_refusal_cannot_advance_seal_or_retry(
        tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    freeze = _freeze(root)
    admission = _admission(freeze)
    primary, training_examples, calibration, calibration_schedule = (
        _tiny_training_population(freeze))
    qualification_plan, qualification_result = (
        _cpu_fallback_qualification(freeze))
    monkeypatch.setattr(
        "shengji.rl.belief_v2_training_controller._stage_gate",
        lambda **kwargs: None)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_training_controller._validate_device_binding",
        lambda *args, **kwargs: "cpu")
    # The frozen next-epoch estimate plus reserve is 61 seconds.  At the first
    # callback only 60 seconds remain, so no epoch body may start.
    times = iter((1_000_000_000,
                  freeze.resource_caps.training_wall_seconds
                  * 1_000_000_000 - 59_000_000_000))
    monkeypatch.setattr(
        "shengji.rl.belief_v2_training_controller.time.monotonic_ns",
        lambda: next(times))
    advanced = []

    def refused_before_training(*args, deadline_check, **kwargs):
        deadline_check("before-unit", 0)
        advanced.append(True)
        raise AssertionError("expired training advanced")

    monkeypatch.setattr(
        "shengji.rl.belief_v2_training_controller."
        "train_v2_cohort_in_memory", refused_before_training)
    kwargs = dict(
        repo=Path("/unused"), review_marker=b"review", primary=primary,
        realization=primary, training_examples=training_examples,
        calibration=calibration_schedule, calibration_examples=calibration,
        qualification_plan=qualification_plan,
        qualification_result=qualification_result)
    with pytest.raises(BeliefV2TrainingControllerError,
                       match="cohort training refused"):
        run_training_cohort(root, freeze, admission, **kwargs)
    assert advanced == []
    partial = root / "training" / f"{primary.cohort_id}.partial"
    assert {path.name for path in partial.iterdir()} \
        == {"deadline-refusal.json"}
    refusal = reopen_deadline_refusal(
        partial / "deadline-refusal.json",
        freeze_sha256=freeze.sha256(), admission_sha256=admission.sha256())
    assert refusal.stage == "training"
    assert refusal.phase == "before-unit"
    assert not (root / "training" / primary.cohort_id).exists()
    with pytest.raises(BeliefV2TrainingControllerError,
                       match="not exactly resumable"):
        run_training_cohort(root, freeze, admission, **kwargs)


def test_deadline_refusal_blocks_calibration_and_test_before_any_input_open(
        tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    freeze = _freeze(root)
    admission = _admission(freeze)
    partial = root / "training" / "synthetic-primary.partial"
    partial.mkdir(parents=True)
    publish_deadline_refusal(partial, V2DeadlineRefusalV1(
        freeze_sha256=freeze.sha256(), admission_sha256=admission.sha256(),
        stage="training", slot="synthetic-primary", phase="before-unit",
        next_unit_index=2, started_monotonic_nanoseconds=1,
        observed_monotonic_nanoseconds=10,
        hard_deadline_monotonic_nanoseconds=11,
        wall_cap_nanoseconds=10,
        next_unit_wall_estimate_nanoseconds=6,
        safety_reserve_nanoseconds=3,
        required_remaining_nanoseconds=9,
        observed_remaining_nanoseconds=1))
    monkeypatch.setattr(V2_CONTROLLER, "validate_execution_freeze",
                        lambda value: None)
    monkeypatch.setattr(V2_CONTROLLER, "reauthenticate_pipeline_admission",
                        lambda *args, **kwargs: None)
    monkeypatch.setattr(V2_CONTROLLER, "validate_live_execution",
                        lambda *args, **kwargs: None)
    monkeypatch.setattr(
        V2_CONTROLLER, "build_training_device_profile",
        lambda value: freeze.training_device_profile)
    opened = []

    def forbidden_open(*args, **kwargs):
        opened.append(True)
        raise AssertionError("deadline-blocked split was opened")

    monkeypatch.setattr(
        CALIBRATION_STAGE, "reopen_training_input_index",
        forbidden_open)
    monkeypatch.setattr(
        TERMINAL_STAGE, "_calibration_statistics", forbidden_open)
    with pytest.raises(BeliefV2ControllerError,
                       match="prior deadline refusal"):
        CALIBRATION_STAGE.run_v2_calibration_selection(
            root, freeze, admission, repo=tmp_path.resolve(),
            review_marker=b"review", inventory={}, group_split={})
    with pytest.raises(BeliefV2ControllerError,
                       match="prior deadline refusal"):
        TERMINAL_STAGE.run_v2_terminal(
            root, freeze, admission, repo=tmp_path.resolve(),
            review_marker=b"review", inventory={}, group_split={})
    assert opened == []
    assert not (root / "calibration").exists()
    assert not (root / "terminal.partial").exists()


def test_full_training_resource_receipt_enforces_its_own_memory_peaks(
        tmp_path):
    freeze = _freeze((tmp_path / "evidence").resolve())
    caps = freeze.resource_caps
    cpu_peak = caps.training_host_memory_bytes // len(freeze.cohorts) + 1
    with pytest.raises(BeliefV2TrainingControllerError,
                       match="resource cap"):
        _resource_row(
            freeze, started=10, finished=20, cpu_nanoseconds=5,
            artifact_bytes=1, selected_device="cpu",
            peak_host_memory_bytes=cpu_peak,
            peak_device_memory_bytes=0)
    row = _resource_row(
        freeze, started=10, finished=20, cpu_nanoseconds=5,
        artifact_bytes=1, selected_device="cpu",
        peak_host_memory_bytes=1_024, peak_device_memory_bytes=0)
    assert row["host_memory_process_count"] == len(freeze.cohorts)
    assert row["aggregate_peak_host_memory_upper_bound_bytes"] \
        == 1_024 * len(freeze.cohorts)
    with pytest.raises(BeliefV2TrainingControllerError,
                       match="resource cap"):
        _resource_row(
            freeze, started=10, finished=20, cpu_nanoseconds=5,
            artifact_bytes=1, selected_device="mps",
            peak_host_memory_bytes=caps.training_host_memory_bytes + 1,
            peak_device_memory_bytes=0)
    with pytest.raises(BeliefV2TrainingControllerError,
                       match="resource cap"):
        _resource_row(
            freeze, started=10, finished=20, cpu_nanoseconds=5,
            artifact_bytes=1, selected_device="mps",
            peak_host_memory_bytes=1,
            peak_device_memory_bytes=caps.training_device_memory_bytes + 1)


def _calibration_score(*, source: str, cohort_ids: tuple[str, ...]):
    return V2RoundScoreV1(
        round_key=hashlib.sha256(f"{source}-round".encode()).hexdigest(),
        source_kind=source, split="calibration", trump_rank="2",
        decision_count=8, reference_brier_ppb=100_000_000,
        reference_log_loss_nanonats=800_000_000,
        cohort_brier_ppb=tuple(
            (cohort_id, 90_000_000 + index)
            for index, cohort_id in enumerate(cohort_ids)),
        cohort_log_loss_nanonats=tuple(
            (cohort_id, 790_000_000 + index)
            for index, cohort_id in enumerate(cohort_ids)),
        cohort_member_brier_ppb=tuple(
            (cohort_id, (90_000_000 + index,) * 8)
            for index, cohort_id in enumerate(cohort_ids)))


def _stub_calibration_dependencies(monkeypatch, freeze, *, stable=True):
    cohort_ids = tuple(row.cohort_id for row in freeze.cohorts)
    cohorts = tuple(SimpleNamespace(cohort_id=value) for value in cohort_ids)
    synthetic = (_calibration_score(
        source="synthetic", cohort_ids=cohort_ids),)
    human = (_calibration_score(source="human", cohort_ids=cohort_ids),)
    training_inputs = SimpleNamespace(sha256=lambda: _sha("7"))
    plan = SimpleNamespace(sha256=lambda: _sha("8"))
    qualification = SimpleNamespace(
        canonical_bytes=lambda ignored: b"qualification\n")
    training_hashes = tuple((cohort_id, _sha(str(index % 10)))
                            for index, cohort_id in enumerate(cohort_ids))
    human_selection = SimpleNamespace(
        retained=True,
        canonical_bytes=lambda: canonical_json_bytes({
            "schema": "test-human-selection", "retained": True}))
    scale_curve = SimpleNamespace(
        canonical_bytes=lambda: canonical_json_bytes({
            "schema": "test-scale-curve", "positive": True}))
    projection_token = object()
    warmed = []
    readiness = []

    class Pool:
        def __enter__(self):
            return projection_token

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(CALIBRATION_STAGE, "_stage_gate", lambda **kwargs: None)
    monkeypatch.setattr(CALIBRATION_STAGE, "projection_pool", Pool)
    monkeypatch.setattr(
        CALIBRATION_STAGE, "warm_projection_pool",
        lambda executor: warmed.append(executor))
    monkeypatch.setattr(
        CALIBRATION_STAGE, "reopen_training_input_index",
        lambda *args, **kwargs: ({}, training_inputs))
    monkeypatch.setattr(
        CALIBRATION_STAGE, "reopen_trained_scoring_cohorts",
        lambda *args, **kwargs: (
            cohorts, plan, qualification, training_hashes))
    monkeypatch.setattr(
        CALIBRATION_STAGE, "reopen_checkpoint_scoring_cohorts",
        lambda *args, **kwargs: (
            cohorts, plan, qualification, training_hashes))
    monkeypatch.setattr(
        READINESS_STAGE, "publish_v2_calibration_readiness",
        lambda *args, expected_calibration, **kwargs: readiness.append(
            expected_calibration) or {
                "calibration_manifest_sha256": hashlib.sha256(
                    canonical_json_bytes(expected_calibration)).hexdigest()})
    def synthetic_score(*args, **kwargs):
        assert kwargs["projection_executor"] is projection_token
        return synthetic

    def human_score(*args, **kwargs):
        assert kwargs["projection_executor"] is projection_token
        return human

    monkeypatch.setattr(
        CALIBRATION_STAGE, "_score_synthetic", synthetic_score)
    monkeypatch.setattr(
        CALIBRATION_STAGE, "_score_human", human_score)
    monkeypatch.setattr(
        CALIBRATION_STAGE, "_expected_synthetic_rounds",
        lambda: ((synthetic[0].round_key, "2"),))
    monkeypatch.setattr(
        CALIBRATION_STAGE, "_expected_human_rounds_from_references",
        lambda *args, **kwargs: ((human[0].round_key, "2"),))
    monkeypatch.setattr(
        CALIBRATION_STAGE, "v2_reference_replicates_are_stable",
        lambda *args, source_kind, **kwargs: (
            stable if source_kind == "human" else True))
    monkeypatch.setattr(
        CALIBRATION_STAGE, "evaluate_human_mixture_selection",
        lambda *args, **kwargs: human_selection)
    monkeypatch.setattr(
        CALIBRATION_STAGE, "evaluate_scale_curve",
        lambda *args, **kwargs: scale_curve)
    return human_selection, scale_curve, warmed, readiness


def test_calibration_scoring_reports_progress_inside_each_population(
        tmp_path, monkeypatch):
    """A long calibration pass must advance before its whole arm completes."""
    coordinates = tuple(SimpleNamespace(
        split="calibration", round_seed=seed, trump_rank="2", lane=0)
        for seed in (7101, 7102))
    monkeypatch.setattr(
        CALIBRATION_STAGE, "v2_round_coordinates", lambda: coordinates)
    monkeypatch.setattr(
        CALIBRATION_STAGE, "reopen_synthetic_scoring_round",
        lambda *args, **kwargs: ("decision",))
    monkeypatch.setattr(
        CALIBRATION_STAGE, "reopen_human_scoring_rounds",
        lambda *args, group_digest, **kwargs: ((
            hashlib.sha256(group_digest.encode()).hexdigest(), "2",
            ("decision",)),))
    monkeypatch.setattr(
        CALIBRATION_STAGE, "score_v2_round",
        lambda **kwargs: SimpleNamespace(round_key=kwargs["round_key"]))
    progress = []
    callback = lambda completed, total, phase: progress.append(
        (completed, total, phase))

    synthetic = CALIBRATION_STAGE._score_synthetic(
        tmp_path, SimpleNamespace(), SimpleNamespace(), (),
        replicate="calibration-replicate-0", progress=callback,
        progress_phase="synthetic-inner")
    human = CALIBRATION_STAGE._score_human(
        tmp_path, SimpleNamespace(), SimpleNamespace(), {
            "splits": {"calibration": {
                "group_digests": ["group-b", "group-a"]}}}, (),
        replicate="calibration-replicate-0", progress=callback,
        progress_phase="human-inner")

    assert len(synthetic) == 2 and len(human) == 2
    assert progress == [
        (0, 2, "synthetic-inner"), (1, 2, "synthetic-inner"),
        (2, 2, "synthetic-inner"), (0, 2, "human-inner"),
        (1, 2, "human-inner"), (2, 2, "human-inner"),
    ]


def test_calibration_selection_wires_stability_and_selected_cohort(
        tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    freeze = _freeze(root)
    admission = _admission(freeze)
    _, _, warmed, readiness = _stub_calibration_dependencies(
        monkeypatch, freeze)
    result = CALIBRATION_STAGE.run_v2_calibration_selection(
        root, freeze, admission, repo=Path("/unused"),
        review_marker=b"review", inventory={}, group_split={})
    assert result["calibration_passed"] is True
    assert result["human_mixture_retained"] is True
    assert result["selected_cohort_id"] == "human-mixture"
    assert result["test_split_opened"] is False
    assert result["strength_claim_authorized"] is False
    assert set(result["files"]) == (
        set(CALIBRATION_STAGE.POPULATION_FILES)
        | set(CALIBRATION_STAGE.RESULT_FILES))
    assert len(warmed) == 1
    assert readiness == [result]
    assert CALIBRATION_STAGE.reopen_v2_calibration_selection(
        root / "calibration" / "selection", freeze=freeze,
        admission=admission, inventory={}, group_split={}) == result


def test_calibration_selection_refuses_instability_and_coordinated_rehash(
        tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    freeze = _freeze(root)
    admission = _admission(freeze)
    _, _, warmed, readiness = _stub_calibration_dependencies(
        monkeypatch, freeze, stable=False)
    result = CALIBRATION_STAGE.run_v2_calibration_selection(
        root, freeze, admission, repo=Path("/unused"),
        review_marker=b"review", inventory={}, group_split={})
    assert result["human_reference_replicates_stable"] is False
    assert result["calibration_passed"] is False
    assert result["selected_cohort_id"] is None
    assert len(warmed) == 1
    assert readiness == [result]

    directory = root / "calibration" / "selection"
    result_path = directory / CALIBRATION_STAGE.RESULT_FILES[
        "human_selection"]
    forged = canonical_json_bytes({"schema": "forged-human-selection"})
    result_path.chmod(0o600)
    result_path.write_bytes(forged)
    result_path.chmod(0o400)
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["files"]["human_selection"]["byte_count"] = len(forged)
    manifest["files"]["human_selection"]["sha256"] = hashlib.sha256(
        forged).hexdigest()
    manifest_path.chmod(0o600)
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    manifest_path.chmod(0o400)
    with pytest.raises(
            CALIBRATION_STAGE.BeliefV2CalibrationControllerError,
            match="result reconstruction"):
        CALIBRATION_STAGE.reopen_v2_calibration_selection(
            directory, freeze=freeze, admission=admission,
            inventory={}, group_split={})
