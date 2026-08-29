from __future__ import annotations

import copy
from pathlib import Path

import pytest

from shengji.rl.world_afterstate_v1_capacity import (
    CAPACITY_MEMORY_LIMIT_BYTES)
from shengji.rl.world_afterstate_v1_experiment import (
    AUTHORITY, CALIBRATION_AUDIT_COUNT, CALIBRATION_GROUP_COUNT,
    CALIBRATION_LABEL_PAIR_COUNT, CALIBRATION_LABEL_ROW_COUNT,
    CALIBRATION_PAIR_COUNT, SOURCE_KEYS, SOURCE_PATHS,
    WorldAfterstateV1ExperimentError,
    build_experiment_freeze, validate_experiment_freeze)
from shengji.rl.world_afterstate_v1_training_controller import (
    TRAINING_COHORTS)
from test_world_afterstate_v1_capacity import _build as _capacity_build


def _inputs():
    capacity = _capacity_build()
    runtime = copy.deepcopy(capacity.receipt["runtime"])
    runtime["torch_threads_at_entry"] = capacity.receipt["selection"][
        "torch_threads"]
    sources = {
        key: f"{index + 1:064x}"
        for index, key in enumerate(SOURCE_KEYS)
    }
    return capacity, runtime, sources


def test_experiment_freeze_is_capacity_derived_and_authorizes_nothing():
    capacity, runtime, sources = _inputs()
    freeze = build_experiment_freeze(
        capacity, source_git="a" * 40,
        source_sha256s=sources, experiment_runtime=runtime)
    validate_experiment_freeze(freeze, capacity)

    assert freeze["capacity"]["receipt_sha256"] \
        == capacity.receipt["receipt_sha256"]
    assert freeze["population"]["pair_count"] \
        == capacity.receipt["train_population"]["pair_count"]
    assert freeze["learner"]["member_workers"] \
        == capacity.receipt["selection"]["member_workers"]
    assert freeze["learner"]["torch_threads"] \
        == capacity.receipt["selection"]["torch_threads"]
    assert freeze["learner"]["cohorts"] == list(TRAINING_COHORTS)
    assert freeze["population"]["calibration_group_count"] \
        == CALIBRATION_GROUP_COUNT
    assert freeze["population"]["calibration_audit_count"] \
        == CALIBRATION_AUDIT_COUNT
    assert freeze["population"]["calibration_pair_count"] \
        == CALIBRATION_PAIR_COUNT
    assert freeze["population"]["calibration_label_row_count"] \
        == CALIBRATION_LABEL_ROW_COUNT
    assert freeze["population"]["calibration_label_pair_count"] \
        == CALIBRATION_LABEL_PAIR_COUNT
    assert freeze["resources"]["memory_limit_bytes"] \
        == CAPACITY_MEMORY_LIMIT_BYTES
    assert set(freeze["authority"].values()) == {False}
    assert freeze["authority"] == AUTHORITY
    assert SOURCE_KEYS == tuple(SOURCE_PATHS)
    repo = Path(__file__).resolve().parents[2]
    assert all((repo / relative).is_file()
               for relative in SOURCE_PATHS.values())


def test_experiment_freeze_reconstruction_and_runtime_checks_have_teeth():
    capacity, runtime, sources = _inputs()
    freeze = build_experiment_freeze(
        capacity, source_git="a" * 40,
        source_sha256s=sources, experiment_runtime=runtime)

    forged = copy.deepcopy(freeze)
    forged["resources"]["training_wall_cap_nanoseconds"] += 1
    with pytest.raises(WorldAfterstateV1ExperimentError,
                       match="freeze reconstruction drift"):
        validate_experiment_freeze(forged, capacity)

    runtime["native_sha256"] = "f" * 64
    with pytest.raises(WorldAfterstateV1ExperimentError,
                       match="runtime differs"):
        build_experiment_freeze(
            capacity, source_git="a" * 40,
            source_sha256s=sources, experiment_runtime=runtime)
