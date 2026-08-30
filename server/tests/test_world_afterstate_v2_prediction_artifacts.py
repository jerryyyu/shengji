from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import os
from pathlib import Path

import pytest
import torch

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.douzero_micro import HISTORY_EVENT_DIM
from shengji.rl.encode import N_CARDS
from shengji.rl.world_afterstate import PUBLIC_DIM, WORLD_RECEIVERS
from shengji.rl.world_afterstate_v2_model import (
    WorldAfterstateV2Batch, new_world_afterstate_v2_model,
)
from shengji.rl import world_afterstate_v2_inference as inference
from shengji.rl.world_afterstate_v2_prediction_artifacts import (
    WorldAfterstateV2PredictionArtifactError,
    prediction_population_manifest_path,
    publish_prediction_population_manifest,
    reopen_prediction_population_manifest,
)


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _root() -> inference.ValueInferenceRootV2:
    successors = (_sha("successor-0"), _sha("successor-1"))
    state = _sha("state")
    batch = WorldAfterstateV2Batch(
        public=torch.zeros((2, PUBLIC_DIM), dtype=torch.float32),
        history=torch.zeros((2, 0, HISTORY_EVENT_DIM), dtype=torch.float32),
        history_lengths=torch.zeros(2, dtype=torch.long),
        world=torch.zeros((2, WORLD_RECEIVERS, N_CARDS), dtype=torch.float32),
        perspective=torch.tensor([[1.0, 0.0], [1.0, 0.0]],
                                 dtype=torch.float32),
    )
    return inference.ValueInferenceRootV2(
        deal_sha256=_sha("deal"), slot_sha256=_sha("slot"),
        state_sha256=state,
        candidate_set_sha256=_sha({
            "schema": "world-afterstate-v2-candidate-set-v1",
            "state_sha256": state, "successor_sha256s": list(successors)}),
        split="audit", source="natural", role="attacker", phase="early",
        position="lead", trump_rank="2", trump_mode="S",
        select_subfold=None, points_bucket="0-39",
        successor_sha256s=successors,
        tensor_sha256s=(_sha("tensor-0"), _sha("tensor-1")), tensors=batch)


@pytest.fixture
def manifest() -> dict:
    root = _root()
    rows = tuple(
        row for member in range(4)
        for row in inference.predict_root_v2(
            new_world_afterstate_v2_model(200 + member), root,
            seed_block=1, member_index=member))
    return inference.prediction_population_manifest_v2(
        [root], rows, split="audit", control_name="natural", seed_block=1)


def test_publish_round_trip_is_canonical_exclusive_and_immutable(
        tmp_path: Path, manifest: dict):
    record = publish_prediction_population_manifest(tmp_path, manifest)
    path = prediction_population_manifest_path(
        tmp_path, "natural", 1, "audit")
    assert record.relative_path == path.relative_to(tmp_path).as_posix()
    assert record.path == record.relative_path
    assert record.byte_count == path.stat().st_size
    assert record.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert record.manifest_sha256 == manifest["manifest_sha256"]
    assert path.stat().st_mode & 0o777 == 0o400
    assert path.is_file() and not path.is_symlink()
    assert not path.with_name("manifest.json.partial").exists()
    assert reopen_prediction_population_manifest(
        tmp_path, control_name="natural", seed_block=1, split="audit") == manifest

    with pytest.raises(WorldAfterstateV2PredictionArtifactError):
        publish_prediction_population_manifest(tmp_path, manifest)


def test_path_identity_binds_control_block_split_and_select_subfold(
        tmp_path: Path, manifest: dict):
    for kwargs in (
        {"control_name": "label-permutation"},
        {"seed_block": 2},
        {"split": "fit"},
        {"subfold": "precision-select"},
    ):
        with pytest.raises(WorldAfterstateV2PredictionArtifactError):
            publish_prediction_population_manifest(tmp_path, manifest, **kwargs)
    with pytest.raises(WorldAfterstateV2PredictionArtifactError):
        prediction_population_manifest_path(
            tmp_path, "../natural", 1, "audit")


def test_explicit_select_subfold_cannot_be_ignored_for_manifest_path(
        tmp_path: Path):
    root = replace(_root(), split="select",
                   select_subfold="precision-select")
    rows = tuple(
        row for member in range(4)
        for row in inference.predict_root_v2(
            new_world_afterstate_v2_model(200 + member), root,
            seed_block=1, member_index=member))
    manifest = inference.prediction_population_manifest_v2(
        [root], rows, split="select", control_name="natural", seed_block=1)
    with pytest.raises(WorldAfterstateV2PredictionArtifactError,
                       match="path identity"):
        publish_prediction_population_manifest(
            tmp_path, manifest, subfold="epoch-select")


def test_tamper_extra_field_and_symlink_are_refused(
    tmp_path: Path, manifest: dict):
    record = publish_prediction_population_manifest(tmp_path, manifest)
    path = tmp_path / record.relative_path

    forged = copy.deepcopy(manifest)
    forged["unexpected"] = True
    path.chmod(0o600)
    path.write_bytes(canonical_json_bytes(forged))
    path.chmod(0o400)
    with pytest.raises(WorldAfterstateV2PredictionArtifactError):
        reopen_prediction_population_manifest(
            tmp_path, control_name="natural", seed_block=1, split="audit")

    path.unlink()
    os.symlink("elsewhere.json", path)
    with pytest.raises(WorldAfterstateV2PredictionArtifactError):
        reopen_prediction_population_manifest(
            tmp_path, control_name="natural", seed_block=1, split="audit")


def test_missing_or_replaced_manifest_is_refused(
    tmp_path: Path, manifest: dict):
    record = publish_prediction_population_manifest(tmp_path, manifest)
    path = tmp_path / record.relative_path
    path.chmod(0o600)
    path.write_bytes(b"{}")
    path.chmod(0o400)
    with pytest.raises(WorldAfterstateV2PredictionArtifactError):
        reopen_prediction_population_manifest(
            tmp_path, control_name="natural", seed_block=1, split="audit")

    # A missing final is also not recoverable through this immutable seam.
    path.unlink()
    with pytest.raises(WorldAfterstateV2PredictionArtifactError):
        reopen_prediction_population_manifest(
            tmp_path, control_name="natural", seed_block=1, split="audit")


def test_reopen_refuses_symlinked_ancestor_directory(
        tmp_path: Path, manifest: dict):
    record = publish_prediction_population_manifest(tmp_path, manifest)
    predictions = tmp_path / "predictions"
    elsewhere = tmp_path / "elsewhere"
    predictions.rename(elsewhere)
    os.symlink(elsewhere.name, predictions)
    with pytest.raises(WorldAfterstateV2PredictionArtifactError,
                       match="symlink"):
        reopen_prediction_population_manifest(
            tmp_path, control_name="natural", seed_block=1, split="audit")
