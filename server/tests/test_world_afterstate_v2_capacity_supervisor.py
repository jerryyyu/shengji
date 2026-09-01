from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from dataclasses import replace
import hashlib
import random
from types import SimpleNamespace
import time

import numpy as np
import pytest
import shengji.rl.world_afterstate_v2_capacity_supervisor as supervisor

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.douzero_micro import HISTORY_EVENT_DIM
from shengji.rl.encode import N_CARDS
from shengji.ai.registry import make_bot
from shengji.engine.round import Round
from shengji.rl.actions import enumerate_actions
from shengji.rl.world_afterstate import (
    PUBLIC_DIM, WORLD_RECEIVERS, WorldAfterstateTensorsV0, canonical_successor,
)
from shengji.rl.world_afterstate_v2_capacity_supervisor import (
    FULL_DAG_MISSING_DEPENDENCY, FULL_DAG_STAGES,
    FullDAGCapacityDependencyBlocked,
    FullDAGCapacityMeasurementV2, _predict_roots_batched,
    _capacity_p0_inputs, _capacity_stage_materials,
    _capacity_training_pairs, _execute_capacity_p0,
    _build_capacity_label_population, _fail,
    _open_capacity_audit_once,
    _rederive_capacity_audit_from_sealed,
    _run_optimizer_canary,
    _verified_continuation_population,
    run_full_dag_supervisor,
)
from shengji.rl.world_afterstate_v2_protocol import (
    TIER_SPECS, attempted_deal_identity,
    build_population_slot_ledger,
)
from shengji.rl.world_afterstate_v2_population import (
    build_population_material_v2,
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


def test_capacity_audit_marker_survives_and_refuses_second_label_open(tmp_path):
    payload = canonical_json_bytes({"schema": "capacity-audit-test-v1"})
    opens = []

    def labels():
        opens.append("opened")
        return ("bundle",)

    bundles, reopened = _open_capacity_audit_once(tmp_path, payload, labels)
    marker = tmp_path / "audit-attempt.json"
    assert bundles == ("bundle",)
    assert reopened == payload
    assert marker.read_bytes() == payload
    assert marker.stat().st_mode & 0o777 == 0o400
    assert opens == ["opened"]

    with pytest.raises(FullDAGCapacityDependencyBlocked,
                       match="audit attempt already consumed"):
        _open_capacity_audit_once(tmp_path, payload, labels)
    assert opens == ["opened"]

    interrupted = tmp_path / "interrupted"
    interrupted.mkdir()
    with pytest.raises(RuntimeError, match="label interruption"):
        _open_capacity_audit_once(
            interrupted, payload,
            lambda: (_ for _ in ()).throw(RuntimeError("label interruption")))
    assert (interrupted / "audit-attempt.json").read_bytes() == payload
    with pytest.raises(FullDAGCapacityDependencyBlocked,
                       match="audit attempt already consumed"):
        _open_capacity_audit_once(interrupted, payload, labels)
    assert opens == ["opened"]


def test_reconstruction_rederivation_reopens_each_prediction_artifact(
        tmp_path, monkeypatch):
    keys = (
        ("action-association-permutation", 1),
        ("complete-world-shuffle", 1),
        ("complete-world-shuffle", 2),
        ("label-permutation", 1),
        ("natural", 1),
        ("natural", 2),
    )
    receipts = {
        key: SimpleNamespace(
            sha256=_canary_digest(("bytes", key)),
            manifest_sha256=_canary_digest(("manifest", key)))
        for key in keys}
    reopened = []

    def reopen(_root, *, control_name, seed_block, split,
               expected_sha256, expected_manifest_sha256):
        key = (control_name, seed_block)
        assert split == "audit"
        assert expected_sha256 == receipts[key].sha256
        assert expected_manifest_sha256 == receipts[key].manifest_sha256
        reopened.append(key)
        return {"control_name": control_name, "seed_block": seed_block,
                "split": split}

    @dataclass(frozen=True)
    class Row:
        split: str = "fit"

    def evaluate(manifest, outcomes, _prior):
        assert outcomes and all(row.split == "audit" for row in outcomes)
        return SimpleNamespace(
            control_name=manifest["control_name"],
            seed_block=manifest["seed_block"],
            sha256=lambda: _canary_digest(("evaluation", manifest)))

    monkeypatch.setattr(supervisor, "reopen_prediction_population_manifest",
                        reopen)
    monkeypatch.setattr(supervisor, "evaluate_v2", evaluate)
    monkeypatch.setattr(
        supervisor, "evaluate_control_difference",
        lambda _natural, control: SimpleNamespace(
            sha256=lambda: _canary_digest(
                ("comparison", control.control_name, control.seed_block))))

    by_cohort, digest = _rederive_capacity_audit_from_sealed(
        tmp_path, receipts,
        (SimpleNamespace(candidates=(Row(),)),), object())
    assert tuple(reopened) == keys
    assert tuple(sorted(by_cohort)) == keys
    assert digest == _canary_digest({
        "evaluations": [[name, block, by_cohort[(name, block)].sha256()]
                        for name, block in keys],
        "control_comparisons": [
            _canary_digest(("comparison", name, block))
            for name, block in (
                ("action-association-permutation", 1),
                ("label-permutation", 1),
                ("complete-world-shuffle", 1),
                ("complete-world-shuffle", 2))],
    })


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
    def material(deal, split, *, source="natural", subfold=None,
                 slot_sha256=None):
        return SimpleNamespace(state=SimpleNamespace(
            deal_sha256=f"{deal:064x}", split=split, source=source,
            select_subfold=subfold,
            slot_sha256=slot_sha256 or f"{deal + 10_000:064x}"))

    all_fit_slots = tuple(
        slot for slot in build_population_slot_ledger(TIER_SPECS[0])
        if slot.group == "natural-fit")
    fit_slots = all_fit_slots[:17]
    fit = tuple(material(index, "fit", slot_sha256=slot.slot_sha256)
                for index, slot in enumerate(fit_slots))
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
    assert len(pairs) == 17

    # Seven complete pairs plus three singletons have the same 17-root count
    # but cannot satisfy the reviewed eight-pair world-control geometry.
    unpaired_slots = (*all_fit_slots[:14],
                      all_fit_slots[14], all_fit_slots[16], all_fit_slots[18])
    unpaired = tuple(material(
        400 + index, "fit", slot_sha256=slot.slot_sha256)
        for index, slot in enumerate(unpaired_slots))
    with pytest.raises(FullDAGCapacityDependencyBlocked,
                       match="pair/fit/select/audit"):
        _capacity_stage_materials((*unpaired, *epoch, *precision, *audit))


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


def test_supervisor_progress_utilization_uses_exact_cpu_and_wall_ns():
    assert supervisor._exact_cpu_utilization_ppm(
        wall_ns=2_000_000_000, process_cpu_ns=16_000_000_000) == 500_000


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


def test_full_dag_measurement_round_trips_32_continuation_and_reconstruction():
    result = FullDAGCapacityMeasurementV2(
        tuple((stage, 1_000_000_000) for stage in FULL_DAG_STAGES), 1,
        FULL_DAG_STAGES, 0, True, _capabilities(), None,
        tuple((stage, 32) for stage in FULL_DAG_STAGES),
        tuple((stage, 1_000_000_000) for stage in FULL_DAG_STAGES),
        1, 32, 1, 32, 32)
    result.validate()
    bad = replace(result, continuation_workers=33)
    with pytest.raises(FullDAGCapacityDependencyBlocked, match="layout"):
        bad.validate()


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


def _snapshot_for_slot(slot, seed):
    """Play a deterministic root state whose stratum matches ``slot``."""
    rnd = Round(slot.trump_rank, None, random.Random(seed))
    bots = [make_bot("smart", seed=seed + 10 + seat) for seat in range(4)]
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = bots[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = bots[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    assert rnd.banker is not None
    rnd.bury(rnd.banker, bots[rnd.banker].decide_bury(rnd, rnd.banker))
    completed_tricks = {"early": 0, "middle": 6, "late": 14}[slot.phase]
    while len(rnd.history) < completed_tricks:
        rnd.play(rnd.turn, enumerate_actions(rnd, rnd.turn)[0])
    if slot.position == "follow":
        rnd.play(rnd.turn, enumerate_actions(rnd, rnd.turn)[0])
    return canonical_successor(rnd, rnd.turn)


def _snapshot_matches_slot(snapshot, slot):
    public = snapshot["public"]
    phase = ("early" if not public["completed_tricks"] else
             ("middle" if len(public["completed_tricks"]) < 14 else "late"))
    position = "lead" if not public["current_trick"]["plays"] else "follow"
    mode = "NT" if public["trump_is_nt"] else public["trump_suit"]
    return ((phase, position, snapshot["root_role"]) == slot.cell
            and public["trump_rank"] == slot.trump_rank
            and mode == slot.trump_mode)


def _production_material(slot, snapshot, index):
    attempt = attempted_deal_identity("a" * 64, slot, index)
    material = build_population_material_v2(attempt, slot, snapshot)
    material.validate()
    return material


@dataclass
class _BoundedMeasurementBackend:
    identity: str
    calls: list[str]

    synthetic: bool = False

    def measure(self, stage, _workers, _fixture, operation):
        self.calls.append(stage)
        operation()
        return SimpleNamespace(
            elapsed_ns=1_000_000_000, process_cpu_ns=1_000_000_000,
            sample_utilization_ppm=(1,), sample_memory_bytes=(1,),
            sample_task_counts=(1,), sample_free_disk_bytes=(1,),
            byte_identity_sha256=self.identity, mean_cpu_utilization_ppm=1)


def test_full_dag_supervisor_wires_adjacent_pair_world_control(
        monkeypatch, tmp_path):
    ledger = build_population_slot_ledger(TIER_SPECS[0])
    natural_slots = tuple(slot for slot in ledger if slot.group == "natural-fit")
    slots_by_pair = {}
    for slot in natural_slots:
        slots_by_pair.setdefault(slot.fit_pair_id, []).append(slot)
    pair_snapshots = {}
    target_pairs = tuple(f"D256:natural-fit:{ordinal}"
                         for ordinal in (1, 2, 4, 5, 6, 7, 8, 9, 10))
    for pair_id in target_pairs:
        slot = slots_by_pair[pair_id][0]
        matched = None
        for offset in range(60):
            snapshot = _snapshot_for_slot(
                slot, 100_000 + slot.ordinal + offset)
            if _snapshot_matches_slot(snapshot, slot):
                matched = snapshot
                break
        if matched is None:
            continue
        pair_snapshots[slot.fit_pair_id] = (slot, matched)
        if len(pair_snapshots) == 9:
            break
    assert len(pair_snapshots) == 9
    natural = []
    fixture_index = 0
    for pair_id, (slot, snapshot) in tuple(pair_snapshots.items())[:8]:
        pair = tuple(value for value in natural_slots
                     if value.fit_pair_id == pair_id)
        assert len(pair) == 2
        for pair_slot in pair:
            natural.append(_production_material(
                pair_slot, snapshot, fixture_index))
            fixture_index += 1
    singleton_slot, singleton_snapshot = tuple(pair_snapshots.items())[8][1]
    natural.append(_production_material(
        singleton_slot, singleton_snapshot, fixture_index))
    fixture_index += 1
    natural = tuple(natural)
    pair_counts = Counter(
        next(slot.fit_pair_id for slot in natural_slots
             if slot.slot_sha256 == material.state.slot_sha256)
        for material in natural)
    assert len(pair_counts) == 9
    assert sorted(pair_counts.values()) == [1] + [2] * 8
    assert len({len(material.candidates) for material in natural}) >= 2
    axis_slot, axis_snapshot = tuple(pair_snapshots.values())[0]
    epoch_slot = next(slot for slot in ledger
                      if slot.group == "natural-select"
                      and slot.select_subfold == "epoch-select"
                      and slot.cell == axis_slot.cell
                      and slot.trump_rank == axis_slot.trump_rank
                      and slot.trump_mode == axis_slot.trump_mode)
    precision_slot = next(slot for slot in ledger
                          if slot.group == "natural-select"
                          and slot.select_subfold == "precision-select"
                          and slot.cell == axis_slot.cell
                          and slot.trump_rank == axis_slot.trump_rank
                          and slot.trump_mode == axis_slot.trump_mode)
    audit_slot = next(slot for slot in ledger
                      if slot.group == "natural-audit"
                      and slot.cell == axis_slot.cell
                      and slot.trump_rank == axis_slot.trump_rank
                      and slot.trump_mode == axis_slot.trump_mode)
    heldout = tuple(
        _production_material(slot, axis_snapshot, fixture_index + offset)
        for offset, slot in enumerate(
            (epoch_slot, epoch_slot, *([precision_slot] * 11),
             audit_slot, audit_slot)))
    materials = (*natural, *heldout)
    slots = tuple(next(slot for slot in ledger
                       if slot.slot_sha256 == material.state.slot_sha256)
                  for material in materials)
    assert len(slots) == 32
    epoch = (epoch_slot,)
    precision = (precision_slot,)
    audit = (audit_slot,)
    assert all(slot.select_subfold == "epoch-select" for slot in epoch)
    assert all(slot.select_subfold == "precision-select" for slot in precision)
    assert all(slot.split == "audit" for slot in audit)
    fixtures = tuple(_Fixture(_canary_digest(("fixture", index)), material)
                     for index, material in enumerate(materials))
    identity = _canary_digest([fixture.fixture_sha256 for fixture in fixtures])
    backend = _BoundedMeasurementBackend(identity, [])
    training_calls = []

    @dataclass(frozen=True)
    class Bundle:
        deal_sha256: str
        bundle_sha256: str
        canonical_bytes: bytes = b"bounded-label-bundle"
        candidates: tuple = ()

    bundles_by_deal = {
        material.deal_sha256: Bundle(
            material.deal_sha256, _canary_digest(("bundle", material.deal_sha256)))
        for material in materials}

    def label_population(_root, _name, values, **_kwargs):
        bundles = tuple(bundles_by_deal[value.deal_sha256] for value in values)
        return bundles, len(bundles), _root

    monkeypatch.setattr(supervisor, "_build_capacity_label_population",
                        label_population)

    def training_rows(material, _bundle):
        width = len(material.candidates)
        root_rows = _canary_rows(material.state.state_sha256, width)
        successors = tuple(root_rows[candidate * 8].successor_sha256
                           for candidate in range(width))
        candidate_set = _canary_digest({
            "schema": "world-afterstate-v2-candidate-set-v1",
            "state_sha256": material.state.state_sha256,
            "successor_sha256s": list(successors)})
        world_marker = slots.index(next(
            slot for slot in slots
            if slot.slot_sha256 == material.state.slot_sha256)) % N_CARDS
        return tuple(replace(
            row, deal_sha256=material.state.deal_sha256,
            slot_sha256=material.state.slot_sha256,
            state_sha256=material.state.state_sha256,
            candidate_set_sha256=candidate_set,
            role=material.state.role, phase=material.state.phase,
            position=material.state.position,
            trump_rank=material.state.trump_rank,
            trump_mode=material.state.trump_mode,
            tensors=WorldAfterstateTensorsV0(
                row.tensors.public, row.tensors.history,
                np.where(
                    np.indices(row.tensors.world.shape)[1] == world_marker,
                    1.0, 0.0).astype(np.float32), row.tensors.perspective))
            for row in root_rows)

    monkeypatch.setattr(supervisor, "build_training_examples_v2",
                        training_rows)
    class Selection:
        def __init__(self, _roots, _outcomes):
            pass

        def validate(self):
            return None

        def score(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(supervisor, "EpochSelectPopulationV2", Selection)
    monkeypatch.setattr(supervisor, "new_world_afterstate_v2_model",
                        lambda _seed: object())
    monkeypatch.setattr(supervisor, "new_optimizer", lambda *_args: object())
    monkeypatch.setattr(supervisor, "train_epoch", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(supervisor, "collate_training_examples",
                        lambda rows: SimpleNamespace(root_count=16,
                                                     size=len(rows)))

    @dataclass(frozen=True)
    class Build:
        manifest: dict
        selected_checkpoint_raws: tuple = (b"checkpoint-0", b"checkpoint-1",
                                            b"checkpoint-2", b"checkpoint-3")

    def train_cohort(*, cohort_name, seed_block, **_kwargs):
        training_calls.append((cohort_name, seed_block))
        return Build({"cohort_name": cohort_name, "seed_block": seed_block,
                      "common_epoch": {"selected_epoch": 1}})

    def train_member(*, member_name, **_kwargs):
        training_calls.append((member_name, "member"))
        return Build({"member_index": 0, "member_name": member_name})

    monkeypatch.setattr(supervisor, "train_named_cohort", train_cohort)
    monkeypatch.setattr(supervisor, "train_named_member", train_member)
    monkeypatch.setattr(supervisor, "publish_checkpoint_shard",
                        lambda *_args, **_kwargs: SimpleNamespace(byte_count=1))
    monkeypatch.setattr(supervisor, "reopen_checkpoint_shard",
                        lambda *_args, **_kwargs: (object(), {"selected_epoch": 1}))
    monkeypatch.setattr(
        "shengji.rl.world_afterstate_v2_checkpoint.reopen_checkpoint",
        lambda _raw: (object(), {}))
    monkeypatch.setattr(supervisor, "reopen_cohort_build",
                        lambda _build: ([object()] * 4,
                                        {"cohort_name": "natural",
                                         "common_epoch": {"selected_epoch": 1},
                                         "truncated_by_deadline": True,
                                         "stop_reason": "deadline-truncation",
                                         "audit_eligible": False,
                                         "members": [{"epoch_receipts": [1]}] * 4}))
    monkeypatch.setattr(supervisor, "reopen_member_build",
                        lambda _build: (object(), {"member_index": 0}))

    def predict(_model, _roots, **_kwargs):
        return ()

    monkeypatch.setattr(
        "shengji.rl.world_afterstate_v2_inference.predict_roots_v2", predict)
    monkeypatch.setattr(
        supervisor, "prediction_population_manifest_v2",
        lambda _roots, _rows, **kwargs: dict(kwargs))
    prediction_store = {}

    def publish_prediction(_root, manifest, *, control_name, seed_block,
                           split, subfold=None):
        key = (control_name, seed_block, split)
        prediction_store[key] = manifest
        return SimpleNamespace(
            byte_count=1, sha256=_canary_digest(("bytes", key)),
            manifest_sha256=_canary_digest(("manifest", key)))

    prediction_reopens = []

    def reopen_prediction(_root, *, control_name, seed_block, split,
                          expected_sha256, expected_manifest_sha256):
        key = (control_name, seed_block, split)
        assert expected_sha256 == _canary_digest(("bytes", key))
        assert expected_manifest_sha256 == _canary_digest(("manifest", key))
        prediction_reopens.append(key)
        return prediction_store[key]

    monkeypatch.setattr(supervisor, "publish_prediction_population_manifest",
                        publish_prediction)
    monkeypatch.setattr(supervisor, "reopen_prediction_population_manifest",
                        reopen_prediction)
    monkeypatch.setattr(
        supervisor, "evaluate_v2",
        lambda _manifest, _outcomes, _prior: SimpleNamespace(
            control_name=_manifest["control_name"],
            seed_block=_manifest["seed_block"],
            sha256=lambda: _canary_digest(("evaluation", _manifest))))
    monkeypatch.setattr(
        supervisor, "evaluate_control_difference",
        lambda _natural, control: SimpleNamespace(
            sha256=lambda: _canary_digest(("comparison", control.control_name,
                                           control.seed_block))))
    monkeypatch.setattr(
        supervisor, "reopen_continuation_shard",
        lambda _root, material: bundles_by_deal[material.deal_sha256])
    monkeypatch.setattr(
        supervisor, "reopen_continuation_manifest",
        lambda _root, values, **_kwargs: tuple(
            bundles_by_deal[value.deal_sha256] for value in values))

    def reopen_bundle(bundle, material):
        if bundle.deal_sha256 != material.deal_sha256:
            from shengji.rl.world_afterstate_v2_continuation import (
                WorldAfterstateV2ContinuationError)
            raise WorldAfterstateV2ContinuationError("wrong material")
        return bundle

    monkeypatch.setattr(supervisor, "reopen_continuation_bundle_v2",
                        reopen_bundle)
    monkeypatch.setattr(
        supervisor, "publish_continuation_shard",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            supervisor.WorldAfterstateV2ArtifactError("immutable")))

    reconstruction_rederivations = []
    real_rederive = supervisor._rederive_capacity_audit_from_sealed

    def witnessed_rederive(*args, **kwargs):
        reconstruction_rederivations.append(True)
        return real_rederive(*args, **kwargs)

    monkeypatch.setattr(supervisor, "_rederive_capacity_audit_from_sealed",
                        witnessed_rederive)

    output_root = tmp_path / "capacity-work"
    result = run_full_dag_supervisor(
        fixtures, backend=backend, member_workers=1, continuation_workers=1,
        torch_threads=1, inference_batch=32, reconstruction_workers=1,
        output_root=output_root)
    assert backend.synthetic is False
    assert backend.calls.index("block-1-complete-world-shuffle") < \
        backend.calls.index("block-2-complete-world-shuffle")
    assert result.actual_stage_witnesses == FULL_DAG_STAGES
    assert reconstruction_rederivations == [True]
    assert prediction_reopens == [
        (name, block, "audit") for name, block in sorted({
            ("natural", 1), ("natural", 2),
            (supervisor.CONTROL_NAMES[0], 1),
            (supervisor.CONTROL_NAMES[1], 1),
            (supervisor.CONTROL_NAMES[2], 1),
            (supervisor.CONTROL_NAMES[2], 2),
        })]
    assert (output_root / "audit-attempt.json").is_file()
    assert (output_root / "audit-attempt.json").stat().st_mode & 0o777 == 0o400
    stage_units = dict(result.stage_source_unit_counts)
    for stage in (
            "block-1-natural", "block-1-action-association-permutation",
            "block-1-label-permutation", "block-1-complete-world-shuffle",
            "block-2-natural", "block-2-complete-world-shuffle"):
        assert stage_units[stage] == 17
    assert all(material.state.source == "natural" for material in materials)
    assert len({len(training_rows(material, None))
                for material in materials[:17]}) >= 2

    wrong_rank = next(rank for rank in "23456789TJQKA"
                      if rank != materials[0].state.trump_rank)
    bad_material = replace(materials[0], state=replace(
        materials[0].state, trump_rank=wrong_rank))
    bad_fixtures = (_Fixture(fixtures[0].fixture_sha256, bad_material),
                     *fixtures[1:])
    bad_backend = _BoundedMeasurementBackend(identity, [])
    training_before = len(training_calls)
    with pytest.raises(FullDAGCapacityDependencyBlocked,
                       match="canonical fit slot binding drift"):
        run_full_dag_supervisor(
            bad_fixtures, backend=bad_backend, member_workers=1,
            continuation_workers=1, torch_threads=1, inference_batch=32,
            reconstruction_workers=1)
    assert bad_backend.calls == []
    assert len(training_calls) == training_before
