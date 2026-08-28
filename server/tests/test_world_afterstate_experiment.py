from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_capacity import run_capacity
from shengji.rl.world_afterstate_experiment import (
    AUTHORITY, EXPERIMENT_RUNTIME_KEYS, EXPERIMENT_SOURCE_KEYS,
    FOLD_COUNTS, INITIALIZATION_SEEDS, SOURCE_COUNTS, SOURCE_FOLD_COUNTS,
    STATE_GROUP_COUNT, WorldAfterstateExperimentError,
    build_experiment_freeze,
    reviewed_teacher_binding, validate_experiment_freeze)
from shengji.rl.world_afterstate_population_packet import (
    PACKET_AUTHORITY, PACKET_SCHEMA)


def _capacity(monkeypatch):
    import shengji.rl.world_afterstate_capacity as capacity

    monkeypatch.setattr(capacity, "_git", lambda _repo, *args:
                        "a" * 40 if args == ("rev-parse", "HEAD") else "")
    monkeypatch.setattr(capacity, "_strict_runtime_binding", lambda: {
        "environment": dict(capacity.REQUIRED_ENVIRONMENT),
        "python_executable": "/runtime/python",
        "python_executable_sha256": "1" * 64,
        "fast_router_path": "/runtime/fast.py",
        "fast_router_sha256": "2" * 64,
        "native_path": "/runtime/_fast.so",
        "native_sha256": "3" * 64,
        "compiled_engine_active": True,
        "safe_path": True,
        "dont_write_bytecode": True,
        "pythonpath_absent": True,
    })
    snapshots = iter((
        {"method": "linux-cgroup-v2-memory.peak",
         "path": "/sys/fs/cgroup/value", "current_bytes": 1_000_000,
         "peak_bytes": 2_000_000},
        {"method": "linux-cgroup-v2-memory.peak",
         "path": "/sys/fs/cgroup/value", "current_bytes": 2_000_000,
         "peak_bytes": 4_000_000},
    ))
    monkeypatch.setattr(capacity, "_capacity_memory_snapshot",
                        lambda: next(snapshots))
    monkeypatch.setattr(capacity, "run_afterstate_continuation",
                        lambda _audit, _identity: {
                            "continuation_decisions": 2,
                            "continuation_rollouts": 3,
                            "continuation_searches": 2,
                            "terminal_state": {"public": {
                                "phase": "round_end"}},
                        })
    return run_capacity(
        repo=Path.cwd(), expected_git="a" * 40, fixture_count=13,
        worker_counts=[1, 2], worker_repetitions=1,
        batch_sizes=[2, 4], model_steps=1, device_name="cpu")


def _population_packet():
    body = {
        "schema": PACKET_SCHEMA, "source_git": "b" * 40,
        "population_manifest": {
            "external_sha256": "1" * 64, "manifest_sha256": "2" * 64,
            "group_count": STATE_GROUP_COUNT, "candidate_count": 1040,
            "fold_counts": dict(FOLD_COUNTS),
            "source_counts": dict(SOURCE_COUNTS),
            "source_fold_counts": {
                fold: dict(counts)
                for fold, counts in SOURCE_FOLD_COUNTS.items()},
        },
        "audit_manifest": {
            "external_sha256": "3" * 64, "manifest_sha256": "4" * 64,
            "audit_count": 1040, "total_bytes": 1_000_000,
        },
        "source_schedules": {
            name: {"external_sha256": digit * 64,
                   "schedule_sha256": str(int(digit) + 1) * 64,
                   "round_count": 72}
            for name, digit in (("production_policy", "5"),
                                ("mechanics_hard", "7"))},
        "pt_sol0": {
            "external_sha256": "4" * 64, "report_sha256": "5" * 64,
            "execution_git": "c" * 40, "state_source_only": True,
            "numeric_label_authority": False,
        },
        "selection_outcome_blind": True, "outcome_opened": False,
        "contains_private_complete_worlds": True,
        "world_occurrences_per_state_group": 1,
        "authority": dict(PACKET_AUTHORITY),
    }
    return canonical_json_bytes({**body, "packet_sha256": hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()})


def _freeze(capacity):
    runtime = {key: capacity["runtime"][key]
               for key in EXPERIMENT_RUNTIME_KEYS}
    return build_experiment_freeze(
        canonical_json_bytes(capacity), _population_packet(),
        source_git="b" * 40,
        experiment_source_sha256s={key: "8" * 64
                                   for key in EXPERIMENT_SOURCE_KEYS},
        experiment_runtime=runtime,
        pt_sol0_external_sha256="4" * 64,
        pt_sol0_report_sha256="5" * 64,
        pt_sol0_execution_git="c" * 40,
        pt_luna0_external_sha256="6" * 64,
        pt_luna0_report_sha256="7" * 64,
        pt_luna0_execution_git="d" * 40)


def test_capacity_derives_one_closed_eight_seed_experiment(monkeypatch):
    capacity = _capacity(monkeypatch)
    raw = canonical_json_bytes(capacity)
    freeze = _freeze(capacity)
    validate_experiment_freeze(freeze, raw, _population_packet())
    assert freeze["population_packet"]["selection_outcome_blind"] is True
    assert freeze["population"]["state_group_count"] == STATE_GROUP_COUNT
    assert freeze["population"]["required_axes"]["trump_ranks"] == 13
    assert "NT" in freeze["population"]["required_axes"]["trump_suits"]
    assert freeze["population"]["human_target_rows"] == 0
    assert freeze["population"]["world_occurrences_per_state_group"] == 1
    assert "REF-C" in freeze["population"]["world_source"]
    assert freeze["population"][
        "continuation_repetitions_with_replacement"] is True
    assert freeze["population"]["source_fold_counts"]["report"] == {
        "production-policy": 31, "reviewed-pt-sol0": 16,
        "mechanics-hard": 5}
    assert freeze["learner"]["initialization_seeds"] \
        == list(INITIALIZATION_SEEDS)
    assert len(set(INITIALIZATION_SEEDS)) == 8
    assert freeze["gates"]["belief_required"] is False
    assert freeze["gates"]["search_final_authority"] is True
    assert freeze["labels"]["wall_cap_seconds"] == 8 * 60 * 60
    assert freeze["learner"]["soft_deadline_seconds"] == 8 * 60 * 60
    assert freeze["learner"]["hard_wall_cap_seconds"] == 12 * 60 * 60
    assert freeze["gates"]["report_wall_cap_seconds"] == 2 * 60 * 60
    assert freeze["gates"][
        "independent_verification_reconstructs_all_continuations"] is True
    assert freeze["authority"] == AUTHORITY


def test_freeze_wiring_and_all_false_authority_are_load_bearing(monkeypatch):
    capacity = _capacity(monkeypatch)
    raw = canonical_json_bytes(capacity)
    freeze = _freeze(capacity)

    forged = copy.deepcopy(freeze)
    forged["negative_controls"].pop("complete_world_shuffle")
    with pytest.raises(WorldAfterstateExperimentError,
                       match="reconstruction drift"):
        validate_experiment_freeze(forged, raw, _population_packet())

    forged = copy.deepcopy(freeze)
    forged["authority"]["scientific_training_authorized"] = True
    with pytest.raises(WorldAfterstateExperimentError,
                       match="authority drift"):
        validate_experiment_freeze(forged, raw, _population_packet())


def test_capacity_receipt_and_minimum_population_feasibility_can_fail(
        monkeypatch):
    capacity = _capacity(monkeypatch)
    forged = copy.deepcopy(capacity)
    forged["runtime"]["native_sha256"] = "z" * 64
    with pytest.raises(Exception, match="runtime identity drift"):
        _freeze(forged)

    forged = copy.deepcopy(capacity)
    forged["composed_measurement"]["complete_continuation"][
        "wall_nanoseconds"] = 10**13
    with pytest.raises(WorldAfterstateExperimentError,
                       match="cannot fit"):
        _freeze(forged)


def test_scientific_runtime_may_relocate_but_not_change_capacity_bytes(
        monkeypatch):
    capacity = _capacity(monkeypatch)
    runtime = {key: capacity["runtime"][key]
               for key in EXPERIMENT_RUNTIME_KEYS}
    runtime["python_executable"] = "/scientific/python"
    runtime["fast_router_path"] = "/scientific/fast.py"
    runtime["native_path"] = "/scientific/_fast.so"
    freeze = build_experiment_freeze(
        canonical_json_bytes(capacity), _population_packet(),
        source_git="b" * 40,
        experiment_source_sha256s={key: "8" * 64
                                   for key in EXPERIMENT_SOURCE_KEYS},
        experiment_runtime=runtime,
        pt_sol0_external_sha256="4" * 64,
        pt_sol0_report_sha256="5" * 64,
        pt_sol0_execution_git="c" * 40,
        pt_luna0_external_sha256="6" * 64,
        pt_luna0_report_sha256="7" * 64,
        pt_luna0_execution_git="d" * 40)
    assert freeze["runtime"]["python_executable"] == "/scientific/python"

    runtime["native_sha256"] = "9" * 64
    with pytest.raises(WorldAfterstateExperimentError,
                       match="runtime differs"):
        build_experiment_freeze(
            canonical_json_bytes(capacity), _population_packet(),
            source_git="b" * 40,
            experiment_source_sha256s={key: "8" * 64
                                       for key in EXPERIMENT_SOURCE_KEYS},
            experiment_runtime=runtime,
            pt_sol0_external_sha256="4" * 64,
            pt_sol0_report_sha256="5" * 64,
            pt_sol0_execution_git="c" * 40,
            pt_luna0_external_sha256="6" * 64,
            pt_luna0_report_sha256="7" * 64,
            pt_luna0_execution_git="d" * 40)


def test_teacher_binding_requires_complete_canonical_reviewed_report():
    authority = {"training_authorized": False,
                 "deployment_authorized": False}
    body = {
        "schema": "privileged-teacher-sol0-open-dev-v1",
        "status": "COMPLETE", "completed_record_count": 52,
        "incomplete_record_count": 0,
        "design": {"model": "gpt-5.6-sol",
                   "execution_git": "a" * 40},
        "authority": authority,
    }
    value = {**body, "report_sha256": hashlib.sha256(
        canonical_json_bytes(body)).hexdigest()}
    raw = canonical_json_bytes(value)
    binding = reviewed_teacher_binding(raw, model="gpt-5.6-sol")
    assert binding["external_sha256"] == hashlib.sha256(raw).hexdigest()

    forged = json.loads(raw)
    forged["completed_record_count"] = 51
    with pytest.raises(WorldAfterstateExperimentError,
                       match="identity drift"):
        reviewed_teacher_binding(
            canonical_json_bytes(forged), model="gpt-5.6-sol")
