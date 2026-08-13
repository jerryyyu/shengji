"""Adversarial tests for the read-only Pair V3 capacity result reviewer."""

from __future__ import annotations

import copy
import json
import sys
import types
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import pair_ballot_affected_capacity_result_review as R  # noqa: E402


def _runtime() -> dict:
    return {
        "host": "ubuntu-32gb-hel1-2",
        "machine": "x86_64",
        "python": "3.14.4",
        "python_executable": "/usr/bin/python3.14",
        "cpu_count": 16,
        "memory_bytes": 32 * (1 << 30),
        "fast_required": True,
        "strict_voids_required": True,
        "fast_binary_sha256": "f" * 64,
    }


def _design() -> dict:
    lane = {"states_by_band": {"early": 56, "mid": 6, "late": 2}}
    return {
        "selection": {
            "states": 1_024,
            "states_by_band": {"early": 896, "mid": 96, "late": 32},
        },
        "schedule": {"lanes": [copy.deepcopy(lane) for _ in range(16)]},
    }


def _packet() -> dict:
    return {
        "git": R.EXPECTED_GIT,
        "internal_sha256": R.EXPECTED_PACKET_INTERNAL_SHA256,
        "runtime": _runtime(),
    }


def _review() -> tuple[dict, bytes]:
    claim = R.CAPACITY.packet_review_claim(
        expected_git=R.EXPECTED_GIT,
        packet_sha256=R.EXPECTED_PACKET_SHA256,
        packet_internal_sha256=R.EXPECTED_PACKET_INTERNAL_SHA256)
    marker = R.CAPACITY._canonical_marker(
        R.CAPACITY.PACKET_REVIEW_PREFIX, claim)
    return ({
        "commit": R.PACKET_REVIEW_GIT,
        "marker_sha256": R.CAPACITY.sha256_file_from_bytes(marker),
        "claim": claim,
    }, marker)


def _admission(review: dict) -> dict:
    value = {
        "schema": R.CAPACITY.ADMISSION_SCHEMA,
        "run_id": R.CAPACITY.RUN_ID,
        "git": R.EXPECTED_GIT,
        "packet_sha256": R.EXPECTED_PACKET_SHA256,
        "packet_review_commit": R.PACKET_REVIEW_GIT,
        "packet_review_marker_sha256": review["marker_sha256"],
        "nonce": "a" * 64,
        "created_time_ns": 1_786_590_000_000_000_000,
        "systemd_invocation_id": "b" * 32,
        "one_score_free_preflight_authorized": True,
        "scored_evaluation_authorized": False,
        "report_access_authorized": False,
        "strength_claim": False,
        "production_deployment": False,
    }
    value["internal_sha256"] = R.CAPACITY.digest(value)
    return value


def _result(*, admission_sha256: str) -> dict:
    bands = [band for _split, band in R.CAPACITY.PREFLIGHT_CELLS]
    bands.extend(["early"] * 10)
    work_per_state = (
        2 * R.CAPACITY.DESIGN.POLICY_WORK_PER_STATE
        + R.CAPACITY.EVAL.REPORT_WORLDS)
    normalized = R.CAPACITY.DESIGN.MAX_WORK_PER_STATE / work_per_state
    timings = [{
        "split": ("dev" if lane % 2 == 0 else "calib"),
        "band": band,
        "lane_index": lane,
        "elapsed_seconds": 1.0,
        "observed_candidate_world_rollouts": work_per_state,
        "normalized_max_work_seconds": normalized,
    } for lane, band in enumerate(bands)]
    seconds = {band: normalized for band in R.CAPACITY.DESIGN.BANDS}
    lane_hours = [
        normalized * 64 * R.CAPACITY.THROUGHPUT_SAFETY_FACTOR / 3_600
        for _lane in range(R.CAPACITY.DESIGN.SHARD_COUNT)]
    projection = {
        "fleet_hours": (
            normalized * 1_024 * R.CAPACITY.THROUGHPUT_SAFETY_FACTOR
            / 3_600),
        "max_lane_wall_hours": max(lane_hours),
        "lane_wall_hours": lane_hours,
        "normalized_seconds_per_state_by_band": seconds,
        "target_states": 1_024,
        "safety_factor": R.CAPACITY.THROUGHPUT_SAFETY_FACTOR,
    }
    criteria = {
        "all_capacity_states_complete": True,
        "exact_evaluator_work_complete": True,
        "sampler_nonempty": True,
        "fleet_hours_le_cap": True,
        "max_lane_wall_hours_le_cap": True,
        "all": True,
    }
    accepted = R.CAPACITY.PREFLIGHT_STATES * (
        2 * (R.CAPACITY.DESIGN.SELECTION_WORLDS
             + R.CAPACITY.DESIGN.POLICY_REPORT_WORLDS)
        + R.CAPACITY.EVAL.REPORT_WORLDS)
    value = {
        "schema": R.CAPACITY.RESULT_SCHEMA,
        "run_id": R.CAPACITY.RUN_ID,
        "git": R.EXPECTED_GIT,
        "complete": True,
        "score_free": True,
        "outcomes_computed_in_memory": True,
        "outcomes_discarded": True,
        "outcomes_published": False,
        "records_discarded": R.CAPACITY.PREFLIGHT_STATES,
        "capacity_only_no_effect_estimate": True,
        "saturated_parallel_lanes": R.CAPACITY.DESIGN.SHARD_COUNT,
        "packet_internal_sha256": R.EXPECTED_PACKET_INTERNAL_SHA256,
        "runtime": _runtime(),
        "timing_rows": timings,
        "work_totals": {
            "current_policy_rollouts": (
                R.CAPACITY.PREFLIGHT_STATES
                * R.CAPACITY.DESIGN.POLICY_WORK_PER_STATE),
            "retained_policy_rollouts": (
                R.CAPACITY.PREFLIGHT_STATES
                * R.CAPACITY.DESIGN.POLICY_WORK_PER_STATE),
            "external_comparison_rollouts": (
                R.CAPACITY.PREFLIGHT_STATES
                * R.CAPACITY.EVAL.REPORT_WORLDS),
        },
        "sampler_totals": {
            "accepted_worlds": accepted,
            "sample_attempts": accepted,
            "rejected_worlds": 0,
            "failed_worlds": 0,
            "impossible_worlds": 0,
        },
        "selector_dose": {
            "policy_action_changes": 1,
            "retained_raw_winner_insertions": 2,
            "current_raw_winner_evictions": 0,
        },
        "projection": projection,
        "criteria": criteria,
        "status": "AUTHORIZE_CAPACITY_RESULT_REVIEW",
        "scored_packet_design_authorized": False,
        "scored_evaluation_authorized": False,
        "report_access_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "production_deployment": False,
        "retry_or_extension_authorized": False,
        "admission_sha256": admission_sha256,
        "packet_sha256": R.EXPECTED_PACKET_SHA256,
    }
    value["internal_sha256"] = R.CAPACITY.digest(value)
    return value


def _write(path: Path, value: dict) -> str:
    path.write_bytes(R.CAPACITY.canonical(value))
    return R.CAPACITY.sha256_file(path)


def _fixture(tmp_path: Path, monkeypatch) -> dict:
    tmp_path.mkdir(parents=True, exist_ok=True)
    packet = _packet()
    review, marker = _review()
    review_path = tmp_path / "packet-review-snapshot.md"
    review_path.write_bytes(marker)
    admission_path = tmp_path / "admission.json"
    admission_sha = _write(admission_path, _admission(review))
    result_path = tmp_path / "capacity.json"
    result_sha = _write(
        result_path, _result(admission_sha256=admission_sha))
    monkeypatch.setattr(
        R.CAPACITY, "load_packet", lambda *_args, **_kwargs: packet)
    monkeypatch.setattr(
        R.CAPACITY, "canonical_review_record",
        lambda **_kwargs: (copy.deepcopy(review), marker))
    monkeypatch.setattr(R.DESIGN, "verify_design", lambda *_args: _design())
    return {
        "population_path": tmp_path / "population.json",
        "design_path": tmp_path / "design.json",
        "packet_path": tmp_path / "packet.json",
        "packet_review_snapshot_path": review_path,
        "admission_path": admission_path,
        "expected_admission_sha256": admission_sha,
        "result_path": result_path,
        "expected_result_sha256": result_sha,
    }


def test_verified_claim_authorizes_design_only(tmp_path, monkeypatch):
    args = _fixture(tmp_path, monkeypatch)
    claim = R.verify(**args)
    assert claim["verdict"] == "PASS"
    assert claim["score_free_capacity_pass"] is True
    assert claim["scored_packet_design_authorized"] is True
    assert claim["scored_packet_freeze_authorized"] is False
    assert claim["scored_packet_run_authorized"] is False
    assert claim["scored_evaluation_authorized"] is False
    assert claim["report_access_authorized"] is False
    assert claim["strength_claim"] is False
    assert claim["retry_authorized"] is False
    assert claim["extension_authorized"] is False
    assert claim["result_reviewer_script_sha256"] == (
        R.CAPACITY.sha256_file(Path(R.__file__)))
    assert claim["reviewer_dependency_sha256s"] == (
        R.EXPECTED_DEPENDENCY_SHA256S)


@pytest.mark.parametrize("mutation, expected", [
    (lambda value: value.__setitem__("score", 1), "forbidden outcome field"),
    (lambda value: value["runtime"].__setitem__("host", "other"),
     "runtime differs"),
    (lambda value: value["work_totals"].__setitem__(
        "current_policy_rollouts", 1), "work totals"),
    (lambda value: value["projection"].__setitem__(
        "fleet_hours", 0.1), "projection math"),
    (lambda value: value.__setitem__(
        "scored_evaluation_authorized", True), "authority escalation"),
])
def test_result_mutations_refuse_even_with_reforged_hashes(
        tmp_path, monkeypatch, mutation, expected):
    args = _fixture(tmp_path, monkeypatch)
    value = json.loads(args["result_path"].read_bytes())
    mutation(value)
    value.pop("internal_sha256")
    value["internal_sha256"] = R.CAPACITY.digest(value)
    args["expected_result_sha256"] = _write(args["result_path"], value)
    with pytest.raises(R.CapacityResultReviewRefused, match=expected):
        R.verify(**args)


def test_admission_and_review_snapshot_mutations_refuse(tmp_path, monkeypatch):
    args = _fixture(tmp_path, monkeypatch)
    admission = json.loads(args["admission_path"].read_bytes())
    admission["packet_review_commit"] = "0" * 40
    admission.pop("internal_sha256")
    admission["internal_sha256"] = R.CAPACITY.digest(admission)
    args["expected_admission_sha256"] = _write(
        args["admission_path"], admission)
    with pytest.raises(R.CapacityResultReviewRefused, match="identity"):
        R.verify(**args)

    args = _fixture(tmp_path / "second", monkeypatch)
    args["packet_review_snapshot_path"].write_bytes(b"forged\n")
    with pytest.raises(
            R.CapacityResultReviewRefused, match="snapshot drift"):
        R.verify(**args)


def test_file_hash_and_self_hash_both_fail_closed(tmp_path, monkeypatch):
    args = _fixture(tmp_path, monkeypatch)
    with pytest.raises(R.CapacityResultReviewRefused, match="file SHA-256"):
        R.verify(**{**args, "expected_result_sha256": "0" * 64})

    value = json.loads(args["result_path"].read_bytes())
    value["internal_sha256"] = "0" * 64
    args["expected_result_sha256"] = _write(args["result_path"], value)
    with pytest.raises(R.CapacityResultReviewRefused, match="internal digest"):
        R.verify(**args)


@pytest.mark.parametrize("payload", [
    b'{"schema":"x","schema":"y"}',
    b'{"schema":"x","elapsed":NaN}',
    b'{"schema":"x","elapsed":Infinity}',
])
def test_strict_json_refuses_duplicates_and_nonfinite(
        tmp_path, payload):
    path = tmp_path / "hostile.json"
    path.write_bytes(payload)
    expected = R.CAPACITY.sha256_file(path)
    with pytest.raises(R.CapacityResultReviewRefused, match="unreadable"):
        R._load_exact_json(path, expected, label="hostile artifact")


def test_dependency_source_and_loaded_module_identity_fail_closed(monkeypatch):
    name = "pair_ballot_affected_capacity_preflight.py"
    monkeypatch.setitem(R.EXPECTED_DEPENDENCY_SHA256S, name, "0" * 64)
    with pytest.raises(R.CapacityResultReviewRefused, match="dependency identity"):
        R._require_dependency_sources()

    monkeypatch.undo()
    original = R.DEPENDENCY_MODULES[name]
    forged = types.ModuleType(original.__name__)
    forged.__file__ = original.__file__
    monkeypatch.setitem(R.DEPENDENCY_MODULES, name, forged)
    with pytest.raises(R.CapacityResultReviewRefused, match="dependency identity"):
        R._require_dependency_sources()


def test_reviewer_source_has_no_writer_or_launcher_surface():
    source = Path(R.__file__).read_text()
    for forbidden in (
            "write_exclusive", "write_bytes_exclusive", "measure_preflight",
            "run_command", "systemd-run", "evaluate_state", "REPORT_PATH"):
        assert forbidden not in source
