from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v1_admission import (
    CAPACITY_REENTRY_AUTHENTICATION_SCHEMA,
    CAPACITY_REENTRY_V2_AUTHENTICATION_SCHEMA,
    expected_capacity_operator_reentry_claim,
    expected_capacity_operator_reentry_v2_claim)
from shengji.rl.world_afterstate_v1_capacity import (
    CAPACITY_MEMORY_LIMIT_BYTES)
from shengji.rl.world_afterstate_v1_experiment import (
    AUTHORITY, CAPACITY_FAILED_ATTEMPTS, CALIBRATION_AUDIT_COUNT,
    CALIBRATION_GROUP_COUNT,
    CALIBRATION_LABEL_PAIR_COUNT, CALIBRATION_LABEL_ROW_COUNT,
    CALIBRATION_PAIR_COUNT, SCIENTIFIC_FAILED_ATTEMPTS, SOURCE_KEYS,
    SOURCE_PATHS,
    WorldAfterstateV1ExperimentError,
    build_experiment_freeze, validate_experiment_freeze)
from shengji.rl.world_afterstate_v1_training_controller import (
    TRAINING_COHORTS)
from test_world_afterstate_v1_capacity import _build as _capacity_build


SCIENTIFIC_ROOT = "/opt/value-afterstate-v1-p1-scientific-test"


def _inputs():
    capacity = _capacity_build()
    runtime = copy.deepcopy(capacity.receipt["runtime"])
    runtime["torch_threads_at_entry"] = capacity.receipt["selection"][
        "torch_threads"]
    sources = {
        key: f"{index + 1:064x}"
        for index, key in enumerate(SOURCE_KEYS)
    }
    def authentication(claim, schema, review, marker):
        body = {
            "schema": schema,
            "review_commit": review,
            "canonical_remote_tip_at_freeze": "c" * 40,
            "claim": claim,
            "review_marker_sha256": marker,
            "review_claim_sha256": hashlib.sha256(
                canonical_json_bytes(claim)).hexdigest(),
        }
        return {**body, "authentication_sha256": hashlib.sha256(
            canonical_json_bytes(body)).hexdigest()}

    reentry = authentication(
        expected_capacity_operator_reentry_claim(),
        CAPACITY_REENTRY_AUTHENTICATION_SCHEMA, "b" * 40, "d" * 64)
    reentry_v2 = authentication(
        expected_capacity_operator_reentry_v2_claim(),
        CAPACITY_REENTRY_V2_AUTHENTICATION_SCHEMA, "e" * 40, "f" * 64)
    return capacity, runtime, sources, reentry, reentry_v2


def test_experiment_freeze_is_capacity_derived_and_authorizes_nothing():
    capacity, runtime, sources, reentry, reentry_v2 = _inputs()
    freeze = build_experiment_freeze(
        capacity, source_git="a" * 40,
        source_sha256s=sources, experiment_runtime=runtime,
        scientific_root=SCIENTIFIC_ROOT,
        capacity_operator_reentry=reentry,
        capacity_operator_reentry_v2=reentry_v2)
    validate_experiment_freeze(freeze, capacity)

    assert freeze["capacity"]["receipt_sha256"] \
        == capacity.receipt["receipt_sha256"]
    assert freeze["capacity_operator_reentry"] == reentry
    assert freeze["capacity_operator_reentry_v2"] == reentry_v2
    lineage = freeze["capacity_attempt_lineage"]
    assert lineage["failed_attempt_count"] == 4
    assert lineage["failed_attempts"] == [
        dict(row) for row in CAPACITY_FAILED_ATTEMPTS]
    assert [row["ordinal"] for row in lineage["failed_attempts"]] \
        == [1, 2, 3, 4]
    assert [row["train_population_opened"]
            for row in lineage["failed_attempts"]] \
        == [False, False, True, False]
    assert all(row["output_published"] is False
               and row["heldout_rows_opened"] is False
               for row in lineage["failed_attempts"])
    assert lineage["successful_attempt_count"] == 1
    assert lineage["successful_source_git"] \
        == capacity.receipt["source_git"]
    assert lineage["successful_receipt_sha256"] \
        == capacity.receipt["receipt_sha256"]
    assert lineage["successful_terminal_route"] == "PASS_TO_P1_CAPACITY"
    scientific_lineage = freeze["scientific_attempt_lineage"]
    assert scientific_lineage == {
        "failed_attempt_count": 1,
        "failed_attempts": [dict(row)
                            for row in SCIENTIFIC_FAILED_ATTEMPTS],
        "next_attempt_ordinal": 2,
        "fresh_exact_head_freeze_review_required": True,
        "prior_admission_retry_authorized": False,
    }
    assert scientific_lineage["failed_attempts"][0][
        "calibration_labels_opened"] is False
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
    capacity, runtime, sources, reentry, reentry_v2 = _inputs()
    freeze = build_experiment_freeze(
        capacity, source_git="a" * 40,
        source_sha256s=sources, experiment_runtime=runtime,
        scientific_root=SCIENTIFIC_ROOT,
        capacity_operator_reentry=reentry,
        capacity_operator_reentry_v2=reentry_v2)

    forged = copy.deepcopy(freeze)
    forged["resources"]["training_wall_cap_nanoseconds"] += 1
    with pytest.raises(WorldAfterstateV1ExperimentError,
                       match="freeze reconstruction drift"):
        validate_experiment_freeze(forged, capacity)

    with pytest.raises(WorldAfterstateV1ExperimentError,
                       match="scientific root drift"):
        build_experiment_freeze(
            capacity, source_git="a" * 40,
            source_sha256s=sources, experiment_runtime=runtime,
            scientific_root="relative/root",
            capacity_operator_reentry=reentry,
            capacity_operator_reentry_v2=reentry_v2)

    forged = copy.deepcopy(freeze)
    forged["capacity_attempt_lineage"]["failed_attempts"][2][
        "train_population_opened"] = False
    with pytest.raises(WorldAfterstateV1ExperimentError,
                       match="freeze reconstruction drift"):
        validate_experiment_freeze(forged, capacity)

    forged = copy.deepcopy(freeze)
    forged["scientific_attempt_lineage"]["failed_attempts"][0][
        "calibration_labels_opened"] = True
    with pytest.raises(WorldAfterstateV1ExperimentError,
                       match="freeze reconstruction drift"):
        validate_experiment_freeze(forged, capacity)

    runtime["native_sha256"] = "f" * 64
    with pytest.raises(WorldAfterstateV1ExperimentError,
                       match="runtime differs"):
        build_experiment_freeze(
            capacity, source_git="a" * 40,
            source_sha256s=sources, experiment_runtime=runtime,
            scientific_root=SCIENTIFIC_ROOT,
            capacity_operator_reentry=reentry,
            capacity_operator_reentry_v2=reentry_v2)

    forged = copy.deepcopy(reentry)
    forged["claim"]["train_row_bytes_opened"] = True
    with pytest.raises(WorldAfterstateV1ExperimentError,
                       match="capacity operator reentry drift"):
        build_experiment_freeze(
            capacity, source_git="a" * 40,
            source_sha256s=sources, experiment_runtime=copy.deepcopy(
                capacity.receipt["runtime"]),
            scientific_root=SCIENTIFIC_ROOT,
            capacity_operator_reentry=forged,
            capacity_operator_reentry_v2=reentry_v2)

    forged_v2 = copy.deepcopy(reentry_v2)
    forged_v2["claim"]["train_row_bytes_opened"] = True
    with pytest.raises(WorldAfterstateV1ExperimentError,
                       match="capacity operator reentry drift"):
        build_experiment_freeze(
            capacity, source_git="a" * 40,
            source_sha256s=sources, experiment_runtime=copy.deepcopy(
                capacity.receipt["runtime"]),
            scientific_root=SCIENTIFIC_ROOT,
            capacity_operator_reentry=reentry,
            capacity_operator_reentry_v2=forged_v2)
