from __future__ import annotations

from dataclasses import dataclass
import hashlib
from types import SimpleNamespace
import time

import numpy as np
import pytest
import shengji.rl.world_afterstate_v2_capacity_supervisor as supervisor

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.douzero_micro import HISTORY_EVENT_DIM
from shengji.rl.encode import N_CARDS
from shengji.rl.world_afterstate import (
    PUBLIC_DIM, WORLD_RECEIVERS, WorldAfterstateTensorsV0,
)
from shengji.rl.world_afterstate_v2_capacity_supervisor import (
    FULL_DAG_MISSING_DEPENDENCY, FULL_DAG_STAGES,
    FullDAGCapacityDependencyBlocked,
    FullDAGCapacityMeasurementV2, _predict_roots_batched,
    _capacity_p0_inputs, _capacity_stage_materials,
    _capacity_training_pairs, _execute_capacity_p0,
    _build_capacity_label_population, _fail,
    _run_optimizer_canary,
    _verified_continuation_population,
    run_full_dag_supervisor,
)
from shengji.rl.world_afterstate_v2_training import (
    WorldAfterstateV2TrainingExample, collate_training_examples)


def test_label_population_uses_production_controller_with_distinct_roots(
        tmp_path, monkeypatch):
    materials = (SimpleNamespace(name="one"), SimpleNamespace(name="two"))
    bundles = tuple(SimpleNamespace(name=value.name) for value in materials)
    calls = []
    progress = []

    def build(root, values, **kwargs):
        calls.append((root, values, kwargs))
        kwargs["progress"]({"completed_deals": len(values),
                            "deadline_headroom_nanoseconds": 1})
        return SimpleNamespace(artifact_bytes=123)

    monkeypatch.setattr(supervisor, "build_continuation_population_v2", build)
    monkeypatch.setattr(supervisor, "reopen_continuation_manifest",
                        lambda _root, _values: bundles)
    monkeypatch.setattr(supervisor, "reopen_continuation_bundle_v2",
                        lambda bundle, _material: bundle)
    deadline = time.perf_counter_ns() + 10_000_000_000
    roots = []
    for name in ("p0", "fit", "precision-select", "audit"):
        reopened, artifacts, root = _build_capacity_label_population(
            tmp_path, name, materials, workers=8,
            deadline_perf_ns=deadline, progress=progress.append)
        assert reopened == bundles and artifacts == 123
        roots.append(root)
    assert len(set(roots)) == 4
    assert [call[0].name for call in calls] == [
        "labels-p0", "labels-fit", "labels-precision-select", "labels-audit"]
    assert [call[2]["split"] for call in calls] == [
        "fit-select", "fit-select", "fit-select", "audit"]
    assert all(call[1] == materials and call[2]["workers"] == 8
               and call[2]["deadline_monotonic_ns"] > time.monotonic_ns()
               for call in calls)
    assert [row["stage"] for row in progress] == [
        "p0", "fit", "precision-select", "audit"]
    assert not hasattr(supervisor, "build_continuation_bundle_v2")


def test_dependency_failure_carries_typed_stage_and_reason():
    failure = _fail("label-p0", RuntimeError("boom"))
    assert failure.stage == "label-p0"
    assert failure.reason_code == "full-dag-dependency-failed"
    assert "RuntimeError: boom" in str(failure)


def test_label_permutation_construction_failure_keeps_exact_dag_stage():
    def refuse(_examples):
        raise RuntimeError("dose")

    with pytest.raises(FullDAGCapacityDependencyBlocked,
                       match="RuntimeError: dose") as raised:
        supervisor._build_control_training_population(
            "label-permutation", 1, (), refuse)
    assert raised.value.stage == "block-1-label-permutation"
    assert raised.value.reason_code == "full-dag-dependency-failed"


def test_stage_material_partition_preserves_protocol_membership():
    def material(deal, split, *, source="natural", subfold=None):
        return SimpleNamespace(state=SimpleNamespace(
            deal_sha256=f"{deal:064x}", split=split, source=source,
            select_subfold=subfold))

    fit = tuple(material(index, "fit") for index in range(18))
    epoch = tuple(material(100 + index, "select", subfold="epoch-select")
                  for index in range(4))
    precision = tuple(material(
        200 + index, "select", subfold="precision-select")
                      for index in range(3))
    audit = tuple(material(300 + index, "audit") for index in range(2))
    p0, label_fit, fit_natural, fit_epoch, selected, heldout = \
        _capacity_stage_materials((*audit, *precision, *epoch, *fit))

    assert p0 == fit[:16]
    assert fit_natural == fit[16:]
    assert fit_epoch == epoch[:2]
    assert label_fit == fit[16:] + epoch[:2]
    assert selected == precision and heldout == audit
    assert not ({id(row) for row in p0} & {id(row) for row in label_fit})
    assert all(row.state.split == "fit" for row in p0)
    assert all(row.state.split == "select" for row in selected)
    assert all(row.state.split == "audit" for row in heldout)

    p0_bundles = tuple(SimpleNamespace(deal=row.state.deal_sha256)
                       for row in p0)
    label_fit_bundles = tuple(SimpleNamespace(deal=row.state.deal_sha256)
                              for row in label_fit)
    pairs = _capacity_training_pairs(
        p0, p0_bundles, label_fit, label_fit_bundles)
    assert tuple(row for row, _bundle in pairs) == fit
    assert len(pairs) == 18


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


def _canary_digest(value):
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _canary_rows(root, candidates):
    deal = _canary_digest((root, "deal"))
    slot = _canary_digest((root, "slot"))
    state = _canary_digest((root, "state"))
    successors = tuple(_canary_digest((root, "successor", index))
                       for index in range(candidates))
    candidate_set = _canary_digest({
        "schema": "world-afterstate-v2-candidate-set-v1",
        "state_sha256": state, "successor_sha256s": list(successors)})
    rows = []
    for candidate, successor in enumerate(successors):
        for replica in range(8):
            public = np.zeros(PUBLIC_DIM, dtype=np.float32)
            public[candidate % PUBLIC_DIM] = 1.0
            world = np.zeros((WORLD_RECEIVERS, N_CARDS), dtype=np.float32)
            world[0, candidate % N_CARDS] = 1.0
            tensors = WorldAfterstateTensorsV0(
                public, np.zeros((0, HISTORY_EVENT_DIM), dtype=np.float32),
                world, np.asarray([1., 0.], dtype=np.float32))
            rows.append(WorldAfterstateV2TrainingExample(
                deal, slot, state, candidate_set, candidate,
                candidate == 0, successor,
                _canary_digest((root, "continuation", replica)), replica,
                "natural", "fit", "attacker", "early", "lead", "2", "S",
                "0-39", tensors, (candidate + replica) % 204))
    return rows


def test_supervisor_refuses_synthetic_or_hash_only_backends():
    fixtures = tuple(_Fixture(f"{index:064x}") for index in range(32))
    with pytest.raises(FullDAGCapacityDependencyBlocked, match="synthetic"):
        run_full_dag_supervisor(fixtures, backend=_Synthetic())


def test_supervisor_refuses_fixture_without_retained_material():
    fixtures = tuple(_Fixture(f"{index:064x}") for index in range(32))
    with pytest.raises(FullDAGCapacityDependencyBlocked, match="PopulationMaterialV2"):
        run_full_dag_supervisor(fixtures, backend=object())


def test_optimizer_canary_accepts_mixed_candidate_widths_at_wiring_boundary():
    rows = tuple(
        row for index in range(16)
        for row in _canary_rows(f"root-{index:02d}",
                                2 if index < 8 else 5))
    seen = {}

    def training_cost(selected, steps):
        seen["steps"] = steps
        seen["batch"] = collate_training_examples(selected)

    _run_optimizer_canary(rows, training_cost)
    assert seen["steps"] == 500
    assert seen["batch"].root_count == 16
    assert seen["batch"].size == (8 * 2 + 8 * 5) * 8


def test_optimizer_canary_attributes_incomplete_sibling_to_its_stage():
    rows = [
        row for index in range(16)
        for row in _canary_rows(f"root-{index:02d}",
                                2 if index < 8 else 5)]
    rows.pop()

    def training_cost(selected, steps):
        assert steps == 500
        collate_training_examples(selected)

    with pytest.raises(FullDAGCapacityDependencyBlocked,
                       match="V2 incomplete sibling root") as raised:
        _run_optimizer_canary(rows, training_cost)
    assert raised.value.stage == "optimizer-canary"


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


def test_full_dag_measurement_refuses_missing_reconstruction_layout():
    result = FullDAGCapacityMeasurementV2(
        tuple((stage, 1_000_000_000) for stage in FULL_DAG_STAGES), 1,
        FULL_DAG_STAGES, 0, True, _capabilities(), None,
        tuple((stage, 32) for stage in FULL_DAG_STAGES),
        tuple((stage, 1_000_000_000) for stage in FULL_DAG_STAGES),
        1, 1, 32, 0)
    with pytest.raises(FullDAGCapacityDependencyBlocked, match="layout"):
        result.validate()


def test_audit_derivation_dependency_is_explicitly_non_admissible():
    assert "AuditDerivationInputV2" in FULL_DAG_MISSING_DEPENDENCY


def test_capacity_p0_wires_all_materials_and_real_precision_evaluator(monkeypatch):
    import shengji.rl.world_afterstate_v2_capacity_supervisor as supervisor

    inputs = _capacity_p0_inputs()
    built = []
    evaluated = []
    validated = []
    monkeypatch.setattr(supervisor, "build_inference_root_v2",
                        lambda material: built.append(material) or
                        ("root", material))
    real_evaluate = supervisor.evaluate_precision_label
    real_validate = supervisor.validate_precision_label

    def evaluate(*args, **kwargs):
        result = real_evaluate(*args, **kwargs)
        evaluated.append(result)
        return result

    def validate(result):
        real_validate(result)
        validated.append(result)

    monkeypatch.setattr(supervisor, "evaluate_precision_label", evaluate)
    monkeypatch.setattr(supervisor, "validate_precision_label", validate)

    materials = tuple(f"material-{index}" for index in range(32))
    roots = _execute_capacity_p0(materials, inputs)
    assert roots == tuple(("root", material) for material in materials)
    assert tuple(built) == materials
    assert len(evaluated) == 1
    assert validated == evaluated


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
