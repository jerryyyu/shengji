from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v1_admission import (
    CAPACITY_REENTRY_AUTHENTICATION_SCHEMA,
    expected_capacity_operator_reentry_claim)
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
    claim = expected_capacity_operator_reentry_claim()
    body = {
        "schema": CAPACITY_REENTRY_AUTHENTICATION_SCHEMA,
        "review_commit": "b" * 40,
        "canonical_remote_tip_at_freeze": "c" * 40,
        "claim": claim,
        "review_marker_sha256": "d" * 64,
        "review_claim_sha256": hashlib.sha256(
            canonical_json_bytes(claim)).hexdigest(),
    }
    reentry = {**body, "authentication_sha256": hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()}
    return capacity, runtime, sources, reentry


def test_experiment_freeze_is_capacity_derived_and_authorizes_nothing():
    capacity, runtime, sources, reentry = _inputs()
    freeze = build_experiment_freeze(
        capacity, source_git="a" * 40,
        source_sha256s=sources, experiment_runtime=runtime,
        capacity_operator_reentry=reentry)
    validate_experiment_freeze(freeze, capacity)

    assert freeze["capacity"]["receipt_sha256"] \
        == capacity.receipt["receipt_sha256"]
    assert freeze["capacity_operator_reentry"] == reentry
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
    capacity, runtime, sources, reentry = _inputs()
    freeze = build_experiment_freeze(
        capacity, source_git="a" * 40,
        source_sha256s=sources, experiment_runtime=runtime,
        capacity_operator_reentry=reentry)

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
            source_sha256s=sources, experiment_runtime=runtime,
            capacity_operator_reentry=reentry)

    forged = copy.deepcopy(reentry)
    forged["claim"]["train_row_bytes_opened"] = True
    with pytest.raises(WorldAfterstateV1ExperimentError,
                       match="capacity operator reentry drift"):
        build_experiment_freeze(
            capacity, source_git="a" * 40,
            source_sha256s=sources, experiment_runtime=copy.deepcopy(
                capacity.receipt["runtime"]),
            capacity_operator_reentry=forged)
