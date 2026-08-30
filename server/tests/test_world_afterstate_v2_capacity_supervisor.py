from __future__ import annotations

from dataclasses import dataclass

import pytest

from shengji.rl.world_afterstate_v2_capacity_supervisor import (
    FULL_DAG_MISSING_DEPENDENCY, FULL_DAG_STAGES,
    FullDAGCapacityDependencyBlocked,
    FullDAGCapacityMeasurementV2, run_full_dag_supervisor,
)


def _capabilities():
    return {name: True for name in (
        "reports_stage_counts", "reports_active_workers_and_cpu",
        "reports_elapsed_eta_headroom", "reports_current_peak_cgroup_memory",
        "reports_immutable_shard_checkpoint_count", "resumes_verified_shards_only",
        "resume_same_admission", "resume_cannot_regenerate_replace_select",
        "checkpoints_each_common_epoch", "deadline_truncation_keeps_complete_epoch",
        "audit_requires_complete_upstream", "audit_attempt_fsynced_before_open",
        "one_audit_open", "reconstruction_without_retraining",
        "reconstruction_reuses_immutable_continuations")}


@dataclass
class _Fixture:
    fixture_sha256: str
    material: object | None = None


@dataclass
class _Synthetic:
    synthetic: bool = True


def test_supervisor_refuses_synthetic_or_hash_only_backends():
    fixtures = tuple(_Fixture(f"{index:064x}") for index in range(32))
    with pytest.raises(FullDAGCapacityDependencyBlocked, match="synthetic"):
        run_full_dag_supervisor(fixtures, backend=_Synthetic())


def test_supervisor_refuses_fixture_without_retained_material():
    fixtures = tuple(_Fixture(f"{index:064x}") for index in range(32))
    with pytest.raises(FullDAGCapacityDependencyBlocked, match="PopulationMaterialV2"):
        run_full_dag_supervisor(fixtures, backend=object())


def test_result_requires_every_actual_stage_and_no_reconstruction_replay():
    walls = tuple((stage, 1) for stage in FULL_DAG_STAGES)
    result = FullDAGCapacityMeasurementV2(
        walls, artifact_bytes=1, actual_stage_witnesses=FULL_DAG_STAGES,
        reconstruction_continuation_builds=0, admissible=True,
        progress_recovery=_capabilities())
    result.validate()
    for dropped in (FULL_DAG_STAGES[:-1], FULL_DAG_STAGES[1:]):
        bad = FullDAGCapacityMeasurementV2(
            tuple((stage, 1) for stage in dropped), 1, dropped, 0, True,
            _capabilities())
        with pytest.raises(FullDAGCapacityDependencyBlocked):
            bad.validate()


def test_result_rejects_any_continuation_reconstruction_count():
    result = FullDAGCapacityMeasurementV2(
        tuple((stage, 1) for stage in FULL_DAG_STAGES), 1,
        FULL_DAG_STAGES, reconstruction_continuation_builds=1, admissible=True,
        progress_recovery=_capabilities())
    with pytest.raises(FullDAGCapacityDependencyBlocked, match="reconstruction"):
        result.validate()


def test_audit_derivation_dependency_is_explicitly_non_admissible():
    assert "AuditDerivationInputV2" in FULL_DAG_MISSING_DEPENDENCY


def test_default_or_false_recovery_capability_witness_is_not_admissible():
    walls = tuple((stage, 1) for stage in FULL_DAG_STAGES)
    with pytest.raises(FullDAGCapacityDependencyBlocked, match="progress"):
        FullDAGCapacityMeasurementV2(
            walls, 1, FULL_DAG_STAGES, 0, True).validate()
    capabilities = _capabilities()
    capabilities["resume_same_admission"] = False
    with pytest.raises(FullDAGCapacityDependencyBlocked, match="progress"):
        FullDAGCapacityMeasurementV2(
            walls, 1, FULL_DAG_STAGES, 0, True, capabilities).validate()
