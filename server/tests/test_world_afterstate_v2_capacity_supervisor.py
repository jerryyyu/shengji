from __future__ import annotations

from dataclasses import dataclass

import pytest

from shengji.rl.world_afterstate_v2_capacity_supervisor import (
    FULL_DAG_MISSING_DEPENDENCY, FULL_DAG_STAGES,
    FullDAGCapacityDependencyBlocked,
    FullDAGCapacityMeasurementV2, _predict_roots_batched,
    _capacity_p0_inputs, _execute_capacity_p0,
    _verified_continuation_population,
    run_full_dag_supervisor,
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
        "reconstruction_reuses_immutable_continuations",
        "reconstruction_rederives_audit_arithmetic")}


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


def test_result_rejects_reordered_stage_witness():
    walls = tuple((stage, 1) for stage in FULL_DAG_STAGES)
    reordered = FULL_DAG_STAGES[1:] + FULL_DAG_STAGES[:1]
    result = FullDAGCapacityMeasurementV2(
        walls, 1, reordered, reconstruction_continuation_builds=0,
        admissible=True, progress_recovery=_capabilities())
    with pytest.raises(FullDAGCapacityDependencyBlocked, match="actual witness"):
        result.validate()


def test_result_validates_per_stage_representative_unit_witness():
    walls = tuple((stage, 1) for stage in FULL_DAG_STAGES)
    counts = tuple((stage, 1) for stage in FULL_DAG_STAGES)
    result = FullDAGCapacityMeasurementV2(
        walls, 1, FULL_DAG_STAGES, 0, True, _capabilities(), None, counts)
    result.validate()
    bad = FullDAGCapacityMeasurementV2(
        walls, 1, FULL_DAG_STAGES, 0, True, _capabilities(), None,
        counts[:-1])
    with pytest.raises(FullDAGCapacityDependencyBlocked, match="unit witness"):
        bad.validate()


@pytest.mark.parametrize("torch_threads", (2, 4))
def test_full_dag_measurement_refuses_cross_width_torch_layout(torch_threads):
    walls = tuple((stage, 1) for stage in FULL_DAG_STAGES)
    result = FullDAGCapacityMeasurementV2(
        tuple((stage, 1_000_000_000) for stage in FULL_DAG_STAGES), 1,
        FULL_DAG_STAGES, 0, True, _capabilities(), None,
        tuple((stage, 32) for stage in FULL_DAG_STAGES),
        tuple((stage, 1_000_000_000) for stage in FULL_DAG_STAGES),
        1, torch_threads, 32)
    with pytest.raises(FullDAGCapacityDependencyBlocked, match="layout"):
        result.validate()


def test_audit_derivation_dependency_is_explicitly_non_admissible():
    assert "AuditDerivationInputV2" in FULL_DAG_MISSING_DEPENDENCY


def test_capacity_p0_executes_real_precision_evaluator(monkeypatch):
    import shengji.rl.world_afterstate_v2_capacity_supervisor as supervisor

    inputs = _capacity_p0_inputs()
    seen = []
    monkeypatch.setattr(supervisor, "build_inference_root_v2",
                        lambda material: ("root", material))

    def evaluate(outcomes, **kwargs):
        seen.append((outcomes, kwargs))
        return {"decision": "STOP_NO_REPRODUCIBLE_VALUE_LABEL"}

    monkeypatch.setattr(supervisor, "evaluate_precision_label", evaluate)
    monkeypatch.setattr(supervisor, "validate_precision_label",
                        lambda result: seen.append(result))

    roots = _execute_capacity_p0(("material-a", "material-b"), inputs)
    assert roots == (("root", "material-a"), ("root", "material-b"))
    assert len(seen) == 2
    assert len(seen[0][0]) == 96 * 3 * 8
    assert len(seen[0][1]["natural_fit_population"]) == 128
    assert seen[1]["decision"] == "STOP_NO_REPRODUCIBLE_VALUE_LABEL"


def test_capacity_p0_fixture_passes_production_evaluator():
    from shengji.rl.world_afterstate_v2_label import (
        evaluate_precision_label, validate_precision_label)

    outcomes, required, natural, evidence = _capacity_p0_inputs()
    result = evaluate_precision_label(
        outcomes, required_slots=required,
        natural_fit_population=natural,
        tier=__import__(
            "shengji.rl.world_afterstate_v2_protocol",
            fromlist=["TIER_SPECS"]).TIER_SPECS[0],
        mechanics_evidence=evidence)
    validate_precision_label(result)
    assert result["deal_count"] == 96
    assert result["raw_outcome_count"] == 96 * 3 * 8


def test_capacity_p0_refuses_malformed_mechanics_evidence():
    from shengji.rl.world_afterstate_v2_label import WorldAfterstateV2LabelError

    outcomes, required, natural, evidence = _capacity_p0_inputs()
    malformed = dict(evidence)
    malformed["population_sha256"] = "0" * 64
    with pytest.raises(WorldAfterstateV2LabelError, match="mechanics"):
        _execute_capacity_p0((), (outcomes, required, natural, malformed))


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
    capabilities = _capabilities()
    capabilities["reconstruction_rederives_audit_arithmetic"] = False
    with pytest.raises(FullDAGCapacityDependencyBlocked, match="progress"):
        FullDAGCapacityMeasurementV2(
            walls, 1, FULL_DAG_STAGES, 0, True, capabilities).validate()


def test_batched_predictor_receives_bound_inference_cap():
    seen = {}

    def predictor(model, roots, *, seed_block, member_index, control_name,
                  batch_candidate_cap):
        seen.update(batch_candidate_cap=batch_candidate_cap,
                    model=model, roots=roots, seed_block=seed_block,
                    member_index=member_index, control_name=control_name)
        return ("prediction",)

    result = _predict_roots_batched(
        predictor, "model", ("root-a", "root-b"), seed_block=1,
        member_index=2, control_name="natural", inference_batch=64)
    assert result == ("prediction",)
    assert seen["batch_candidate_cap"] == 64
    assert seen["roots"] == ("root-a", "root-b")


def test_persisted_continuations_reopen_by_deal_not_input_order(monkeypatch,
                                                                tmp_path):
    @dataclass(frozen=True)
    class Item:
        deal_sha256: str
        bundle_sha256: str = ""

    materials = (Item("deal-b"), Item("deal-a"))
    bundles = (Item("deal-a", "bundle-a"), Item("deal-b", "bundle-b"))
    reopened = {"deal-a": Item("deal-a", "bundle-a"),
                "deal-b": Item("deal-b", "bundle-b")}
    monkeypatch.setattr(
        "shengji.rl.world_afterstate_v2_capacity_supervisor."
        "reopen_continuation_shard",
        lambda _root, material: reopened[material.deal_sha256])

    assert _verified_continuation_population(tmp_path, materials, bundles)
    assert not _verified_continuation_population(
        tmp_path, materials, (bundles[0], bundles[0]))
