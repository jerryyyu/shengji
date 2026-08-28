from __future__ import annotations

import copy

import pytest

from shengji.rl.world_afterstate_dataset import ReopenedDatasetRowV0
from shengji.rl.world_afterstate_training_controller import (
    WorldAfterstateTrainingControllerError, publish_training_build,
    reopen_training_build, train_eight_seed_cohort,
    validate_training_manifest)

from test_world_afterstate_training import _example


def _rows(split, offset):
    result = []
    for index in range(2):
        digest = f"{offset + index:064x}"
        binding = {
            "fold": split, "external_sha256": digest,
            "row_sha256": digest,
        }
        reopened = ReopenedDatasetRowV0(
            example=_example(offset + index), evaluation_outcome=None,
            row_sha256=digest)
        result.append((binding, reopened))
    return tuple(result)


def _freeze():
    return {
        "freeze_sha256": "f" * 64,
        "learner": {
            "member_count": 8, "fresh_initialization": True,
            "common_epoch_selection": True, "member_drop_allowed": False,
            "shape": "small", "batch_size": 2,
            "initialization_seeds": list(range(101, 109)),
            "config": {
                "schema": "world-afterstate-training-config-v0",
                "learning_rate_ppb": 1_000_000,
                "weight_decay_ppb": 10_000_000,
                "gradient_norm_milli": 1_000,
                "max_epochs": 2, "early_stop_patience": 2,
                "minimum_improvement_nanonats": 1,
            },
        },
    }


def test_eight_seed_controller_selects_publishes_and_reopens(tmp_path):
    progress = []
    build = train_eight_seed_cohort(
        freeze=_freeze(), dataset_manifest_sha256="d" * 64,
        train_rows=_rows("train", 0),
        calibration_rows=_rows("calibration", 10),
        wall_budget_nanoseconds=10**18,
        progress=lambda epoch, completed, total:
            progress.append((epoch, completed, total)))
    validate_training_manifest(build.manifest)
    assert len(build.selected_checkpoint_raws) == 8
    assert progress[-1] == (2, 16, 16)
    assert build.manifest["report_rows_opened"] is False

    root = tmp_path / "training"
    publish_training_build(root, build)
    manifest, models = reopen_training_build(root)
    assert manifest == build.manifest
    assert len(models) == 8

    forged = copy.deepcopy(manifest)
    forged["authority"]["gameplay_authorized"] = True
    with pytest.raises(WorldAfterstateTrainingControllerError,
                       match="identity drift"):
        validate_training_manifest(forged)


def test_deadline_seals_last_complete_common_epoch_as_truncated(monkeypatch):
    readings = iter((0, 2, 2))
    monkeypatch.setattr(
        "shengji.rl.world_afterstate_training_controller.time.monotonic_ns",
        lambda: next(readings))
    build = train_eight_seed_cohort(
        freeze=_freeze(), dataset_manifest_sha256="d" * 64,
        train_rows=_rows("train", 0),
        calibration_rows=_rows("calibration", 10),
        wall_budget_nanoseconds=1)
    assert build.manifest["epoch_count"] == 1
    assert build.manifest["truncated_by_deadline"] is True
    assert build.manifest["stop_reason"] == "deadline-truncation"

    forged = copy.deepcopy(build.manifest)
    forged["truncated_by_deadline"] = False
    forged["manifest_sha256"] = "0" * 64
    with pytest.raises(WorldAfterstateTrainingControllerError,
                       match="stop reason drift"):
        validate_training_manifest(forged)
