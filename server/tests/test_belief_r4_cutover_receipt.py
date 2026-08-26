"""Can-fail witnesses for the two-host R4 cutover receipt."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import stat

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "belief_r4_cutover_receipt.py"
SPEC = importlib.util.spec_from_file_location("belief_r4_cutover_receipt", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
CUTOVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CUTOVER)


def _observation(spec, *, calibration):
    return {
        "hostname": spec["hostname"],
        "boot_identity": "a" * 36,
        "observed_utc": "2026-08-26T17:00:00+00:00",
        "source_git": spec["source_git"],
        "source_clean": True,
        "root_exists": True,
        "root_is_directory": True,
        "root_is_symlink": False,
        "freeze_sha256": spec["freeze_sha256"],
        "admission_sha256": spec["admission_sha256"],
        "review_sha256": spec["review_sha256"],
        "launch_sha256": spec["launch_sha256"],
        "unit_load_state": "not-found",
        "unit_active_state": "inactive",
        "unit_sub_state": "dead",
        "unit_main_pid": 0,
        "unit_n_restarts": 0,
        "unit_exec_main_status": 0,
        "matching_worker_pids": [],
        "forbidden_paths_present": {
            name: False for name in CUTOVER.FORBIDDEN},
        "calibration_completion_exists": calibration,
        "calibration_selection_manifest_exists": calibration,
        "calibration_partial_present": False,
        "calibration_completion_sha256": "b" * 64 if calibration else None,
        "calibration_selection_manifest_sha256": (
            "e" * 64 if calibration else None),
    }


def _readiness():
    return {
        "schema": "belief-v1-v2-r4-completion-pretest-readiness-v1",
        "completion_execution_git": CUTOVER.OPTIMIZED["source_git"],
        "completion_freeze_sha256": CUTOVER.OPTIMIZED["freeze_sha256"],
        "completion_admission_sha256": CUTOVER.OPTIMIZED[
            "admission_sha256"],
        "source_spec_sha256": CUTOVER.SOURCE_SPEC_SHA256,
        "source_freeze_sha256": CUTOVER.SOURCE_FREEZE_SHA256,
        "source_admission_sha256": CUTOVER.SOURCE_ADMISSION_SHA256,
        "source_calibration_manifest_sha256": "e" * 64,
        "synthetic_test_expected_round_count": (
            CUTOVER.SYNTHETIC_TEST_EXPECTED_ROUND_COUNT),
        "calibration_independently_reopened": True,
        "test_population_metadata_opened": False,
        "test_attempt_file_absent": True,
        "terminal_population_absent": True,
        "source_test_split_decision_open_count": 0,
        "test_opening_executed": False,
        "execution_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }


def _receipt():
    execution_git = "c" * 40
    return CUTOVER.build_receipt(
        execution_git=execution_git, review_commit="d" * 40,
        review_marker=CUTOVER.expected_review_marker(execution_git),
        optimized_pre_observation=_observation(
            CUTOVER.OPTIMIZED, calibration=True),
        serial_pre_observation=_observation(
            CUTOVER.SERIAL, calibration=False),
        optimized_observation=_observation(
            CUTOVER.OPTIMIZED, calibration=True),
        serial_observation=_observation(CUTOVER.SERIAL, calibration=False),
        readiness=_readiness())


def test_review_claim_is_exact_two_lane_receipt_and_authorizes_nothing():
    claim = CUTOVER.expected_review_claim("c" * 40)
    assert claim["optimized_lane"]["root"] == CUTOVER.OPTIMIZED["root"]
    assert claim["serial_lane"]["root"] == CUTOVER.SERIAL["root"]
    assert claim["required_observations"][
        "both_services_inactive_and_workerless"] is True
    assert claim["receipt_only"] is True
    assert not any(claim["authority"].values())


def test_receipt_binds_quiescent_services_absent_tests_and_full_readiness():
    receipt = _receipt()
    assert receipt["both_services_inactive_and_workerless"] is True
    assert receipt["both_test_namespaces_absent"] is True
    assert receipt["optimized_test_open_preconditions_met"] is True
    assert receipt["source_test_split_decision_open_count"] == 0
    assert receipt["test_opening_executed"] is False
    assert not any(receipt["authority"].values())


@pytest.mark.parametrize("mutate", [
    lambda opt, _serial, _ready: opt.update(
        calibration_completion_exists=False),
    lambda _opt, serial, _ready: serial.update(
        unit_active_state="active", unit_sub_state="running",
        unit_main_pid=123),
    lambda _opt, serial, _ready: serial.update(
        matching_worker_pids=[123]),
    lambda _opt, serial, _ready: serial[
        "forbidden_paths_present"].update(terminal=True),
    lambda _opt, _serial, ready: ready.update(
        calibration_independently_reopened=False),
    lambda _opt, _serial, ready: ready.update(
        source_test_split_decision_open_count=1),
    lambda _opt, _serial, ready: ready.update(
        source_calibration_manifest_sha256="f" * 64),
])
def test_each_cutover_precondition_can_refuse(mutate):
    execution_git = "c" * 40
    optimized = _observation(CUTOVER.OPTIMIZED, calibration=True)
    serial = _observation(CUTOVER.SERIAL, calibration=False)
    ready = _readiness()
    mutate(optimized, serial, ready)
    with pytest.raises(CUTOVER.R4CutoverError):
        CUTOVER.build_receipt(
            execution_git=execution_git, review_commit="d" * 40,
            review_marker=CUTOVER.expected_review_marker(execution_git),
            optimized_pre_observation=copy.deepcopy(optimized),
            serial_pre_observation=copy.deepcopy(serial),
            optimized_observation=optimized,
            serial_observation=serial, readiness=ready)


def test_receipt_publication_is_exclusive_and_read_only(tmp_path):
    output = tmp_path / "receipt.json"
    raw = CUTOVER.canonical_json_bytes(_receipt())
    CUTOVER._publish(output, raw)
    assert output.read_bytes() == raw
    assert stat.S_IMODE(output.stat().st_mode) == 0o400
    with pytest.raises(CUTOVER.R4CutoverError, match="output path drift"):
        CUTOVER._publish(output, raw)


def test_review_marker_and_receipt_tamper_are_detected():
    execution_git = "c" * 40
    with pytest.raises(CUTOVER.R4CutoverError, match="review binding"):
        CUTOVER.build_receipt(
            execution_git=execution_git, review_commit="d" * 40,
            review_marker=b"forged\n",
            optimized_pre_observation=_observation(
                CUTOVER.OPTIMIZED, calibration=True),
            serial_pre_observation=_observation(
                CUTOVER.SERIAL, calibration=False),
            optimized_observation=_observation(
                CUTOVER.OPTIMIZED, calibration=True),
            serial_observation=_observation(CUTOVER.SERIAL, calibration=False),
            readiness=_readiness())
    altered = copy.deepcopy(_observation(CUTOVER.SERIAL, calibration=False))
    altered["freeze_sha256"] = "f" * 64
    with pytest.raises(CUTOVER.R4CutoverError, match="not quiescent"):
        CUTOVER._validate_lane(
            altered, CUTOVER.SERIAL, calibration_required=False)
