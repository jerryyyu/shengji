"""Fast contract tests for the score-free V2 capacity runner."""

import dataclasses
import os
import json
import hashlib
import multiprocessing
import pytest
import subprocess
import sys
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from types import SimpleNamespace

import shengji.rl.world_afterstate_v2_capacity_runner as runner
import shengji.rl.world_afterstate_v2_execution as execution
from shengji.rl.belief_contract import canonical_json_bytes

from shengji.rl.world_afterstate_v2_capacity import (
    ARM_GRIDS, COMPOSED_STAGE_NAMES, CapacityCensusAssessmentV2,
    CapacityFailureReceiptV2,
    composed_critical_path_seconds, projected_arm_wall_shares_ppm,
    CapacityArmV2)
from shengji.rl.world_afterstate_v2_capacity_runner import (
    CapacityRunnerError, FixtureV2, HostTelemetryV2, PreflightResultV2,
    RawMeasurementV2, SyntheticMeasurementBackendV2, measure_capacity_v2,
    build_receipt_v2, _arm_from_raw, _PRODUCTION_PROVENANCE,
    RealMeasurementBackendV2, FullDAGCapacityDependencyBlocked,
    RepresentativeDAGV2, _batched_prediction_identity, _composed_projection,
    _run_with_torch_threads, _scientific_stage_units, _tiers, _dag_attestation,
    _FULL_DAG_PROVENANCE, _progress_event,
    publish_capacity_failure_receipt_v2, reopen_capacity_failure_receipt_v2,
    validate_capacity_arm_census_v2,
)
from shengji.rl.world_afterstate_v2_capacity_supervisor import (
    FullDAGCapacityMeasurementV2,
    _RECOVERY_CAPABILITY_NAMES,
)


def _real_preflight_process_probe(identity, slot):
    """Pickle-safe witness that executes the real source driver in a child."""
    return os.getpid(), runner.drive_population_attempt_v2(identity, slot)


def _runtime_pool_probe():
    return os.environ.get(execution.RUNTIME_EXPECTATION_ENV)


def _preflight() -> PreflightResultV2:
    fixture = FixtureV2({"score_free": True})
    return PreflightResultV2(
        accepted_fixtures=(fixture,) * 32, attempted=32, accepted=32,
        rejection_counts=(), candidate_distribution=((2, 32),),
        stratum_distribution=(("early/lead/attacker", 32),),
        elapsed_wall_nanoseconds=1_000_000_000)


def test_score_free_preflight_parallelizes_without_eligible_surplus(
        monkeypatch):
    assert (runner._preflight_executor_type(
        runner.drive_population_attempt_v2) is runner.ProcessPoolExecutor)
    monkeypatch.setattr(runner, "PREFLIGHT_ACCEPTED", 4)
    monkeypatch.setattr(runner, "PREFLIGHT_ATTEMPT_CEILING", 12)
    monkeypatch.setattr(runner, "PREFLIGHT_WORKERS", 4)

    class FakeFixture:
        def __init__(self, _prestate, _audit_raws, *, deal_sha256, material):
            self.deal_sha256 = deal_sha256
            self.fixture_sha256 = deal_sha256
            self.material = material

    monkeypatch.setattr(runner, "FixtureV2", FakeFixture)
    slots = tuple(SimpleNamespace(slot_sha256=f"{index:064x}")
                  for index in range(12))
    active = 0
    max_active = 0
    lock = threading.Lock()
    first_batch = threading.Event()

    def attempt(identity, _slot):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
            if max_active == 4:
                first_batch.set()
        assert first_batch.wait(timeout=2)
        index = identity["attempt_index"]
        accepted = index in {0, 2, 4, 5}
        material = (SimpleNamespace(
            prestate={"index": index}, audit_raws=(), candidates=(0, 1),
            state=SimpleNamespace(
                phase="early", position="lead", role="attacker"))
                    if accepted else None)
        with lock:
            active -= 1
        return SimpleNamespace(
            accepted=accepted, rejection_reason=None if accepted else "miss",
            material=material, deal_sha256=identity["deal_sha256"])

    progress = []
    result = runner.run_score_free_preflight(
        attempt=attempt, slots=slots, progress=progress.append,
        started_ns=time.perf_counter_ns())
    assert max_active == 4
    assert result.attempted == 6
    assert result.accepted == 4
    assert result.rejection_counts == (("miss", 2),)
    assert len({fixture.deal_sha256
                for fixture in result.accepted_fixtures}) == 4
    assert [row["workers"] for row in progress] == [4, 2]
    assert progress[-1]["accepted"] == 4
    assert progress[-1]["rejection_counts"] == {"miss": 2}


def test_preflight_preserves_first_96_then_interleaves_select_and_audit():
    fit = SimpleNamespace(split="fit", slot_sha256="1" * 64)
    select_a = SimpleNamespace(
        split="select", select_subfold="epoch-select", slot_sha256="2" * 64)
    select_b = SimpleNamespace(
        split="select", select_subfold="precision-select",
        slot_sha256="3" * 64)
    audit_a = SimpleNamespace(split="audit", slot_sha256="4" * 64)
    slots = (fit, select_a, select_b, audit_a)
    assert [runner._preflight_slot(slots, index) for index in range(96)] == [
        slots[index % len(slots)] for index in range(96)]
    assert [runner._preflight_slot(slots, index) for index in range(96, 102)] == [
        select_a, select_b, audit_a, fit, select_a, select_b]

    fit_slots = tuple(SimpleNamespace(
        split="fit", slot_sha256=f"{index:064x}") for index in range(97))
    expanded = fit_slots + (select_a, select_b, audit_a)
    assert runner._preflight_slot(expanded, 96) is select_a
    assert runner._preflight_slot(expanded, 97) is select_b
    assert runner._preflight_slot(expanded, 98) is audit_a
    assert runner._preflight_slot(expanded, 99) is fit_slots[96]


def test_preflight_predeclares_eight_natural_fit_pairs():
    from shengji.rl.world_afterstate_v2_protocol import (
        TIER_SPECS, _raw_slot_ledger)
    slots = tuple(slot for slot in _raw_slot_ledger(TIER_SPECS[0])
                  if slot.group == "natural-fit")
    reserved = runner._reserved_natural_pair_slots(slots)
    assert len(reserved) == runner.PREFLIGHT_RESERVED_NATURAL_ROOTS == 16
    assert len({slot.fit_pair_id for slot in reserved}) == 8
    assert all(left.fit_pair_id == right.fit_pair_id
               for left, right in zip(reserved[::2], reserved[1::2]))


def test_preflight_refuses_neutralized_pair_reservation(monkeypatch):
    from shengji.rl.world_afterstate_v2_protocol import (
        TIER_SPECS, _raw_slot_ledger)
    slots = tuple(slot for slot in _raw_slot_ledger(TIER_SPECS[0])
                  if slot.group == "natural-fit")
    monkeypatch.setattr(runner, "_reserved_natural_pair_slots", lambda _: ())
    with pytest.raises(CapacityRunnerError, match="reservation"):
        runner.run_score_free_preflight(
            attempt=lambda *_args: None, slots=slots)


def test_preflight_retries_only_missing_reserved_pair_slots(monkeypatch):
    from shengji.rl.world_afterstate_v2_protocol import (
        TIER_SPECS, _raw_slot_ledger)

    ledger = _raw_slot_ledger(TIER_SPECS[0])
    natural = tuple(slot for slot in ledger if slot.group == "natural-fit")
    reserved = runner._reserved_natural_pair_slots(natural)
    held_out = (
        next(slot for slot in ledger
             if slot.split == "select"
             and slot.select_subfold == "epoch-select"),
        next(slot for slot in ledger
             if slot.split == "select"
             and slot.select_subfold == "precision-select"),
        next(slot for slot in ledger if slot.split == "audit"),
    )
    slots = (*reserved, *held_out)
    monkeypatch.setattr(runner, "PREFLIGHT_ACCEPTED", 19)
    monkeypatch.setattr(runner, "PREFLIGHT_ATTEMPT_CEILING", 40)
    monkeypatch.setattr(runner, "PREFLIGHT_WORKERS", 16)

    class FakeFixture:
        def __init__(self, _prestate, _audit_raws, *, deal_sha256, material):
            self.deal_sha256 = deal_sha256
            self.fixture_sha256 = deal_sha256
            self.material = material

    monkeypatch.setattr(runner, "FixtureV2", FakeFixture)
    attempts = {}

    def attempt(identity, slot):
        attempts[slot.slot_sha256] = attempts.get(slot.slot_sha256, 0) + 1
        accepted = not (slot is reserved[0]
                        and attempts[slot.slot_sha256] == 1)
        material = (SimpleNamespace(
            prestate={"slot": slot.slot_sha256}, audit_raws=(),
            candidates=(0, 1), state=slot) if accepted else None)
        return SimpleNamespace(
            accepted=accepted,
            rejection_reason=None if accepted else "first-attempt-miss",
            material=material, deal_sha256=identity["deal_sha256"])

    progress = []
    result = runner.run_score_free_preflight(
        attempt=attempt, slots=slots, progress=progress.append,
        started_ns=time.perf_counter_ns())
    assert result.accepted == 19
    assert attempts[reserved[0].slot_sha256] == 2
    assert all(attempts[slot.slot_sha256] == 1 for slot in reserved[1:])
    assert progress[0]["workers"] == 16
    assert progress[1]["workers"] == 1


def test_score_free_preflight_rejects_duplicate_retained_population_slot(
        monkeypatch):
    monkeypatch.setattr(runner, "PREFLIGHT_ACCEPTED", 2)
    monkeypatch.setattr(runner, "PREFLIGHT_ATTEMPT_CEILING", 3)
    monkeypatch.setattr(runner, "PREFLIGHT_WORKERS", 1)

    class FakeFixture:
        def __init__(self, _prestate, _audit_raws, *, deal_sha256, material):
            self.deal_sha256 = deal_sha256
            self.fixture_sha256 = deal_sha256
            self.material = material

    monkeypatch.setattr(runner, "FixtureV2", FakeFixture)
    repeated = SimpleNamespace(slot_sha256="1" * 64)
    distinct = SimpleNamespace(slot_sha256="2" * 64)

    def accept(identity, slot):
        material = SimpleNamespace(
            prestate={"index": identity["attempt_index"]}, audit_raws=(),
            candidates=(0, 1), state=SimpleNamespace(
                slot_sha256=slot.slot_sha256, phase="early",
                position="lead", role="attacker"))
        return SimpleNamespace(
            accepted=True, rejection_reason=None, material=material,
            deal_sha256=identity["deal_sha256"])

    result = runner.run_score_free_preflight(
        attempt=accept, slots=(repeated, repeated, distinct))
    assert result.attempted == 3
    assert result.accepted == 2
    assert result.rejection_counts == (("duplicate-slot", 1),)
    assert [fixture.material.state.slot_sha256
            for fixture in result.accepted_fixtures] == [
                repeated.slot_sha256, distinct.slot_sha256]


def test_preflight_early_fit_acceptance_reserves_select_and_audit_slots(
        monkeypatch):
    monkeypatch.setattr(runner, "PREFLIGHT_ACCEPTED", 5)
    monkeypatch.setattr(runner, "PREFLIGHT_ATTEMPT_CEILING", 100)
    monkeypatch.setattr(runner, "PREFLIGHT_WORKERS", 4)

    class FakeFixture:
        def __init__(self, _prestate, _audit_raws, *, deal_sha256, material):
            self.deal_sha256 = deal_sha256
            self.fixture_sha256 = deal_sha256
            self.material = material

    monkeypatch.setattr(runner, "FixtureV2", FakeFixture)
    slots = tuple(
        SimpleNamespace(split="fit", slot_sha256=f"{index:064x}")
        for index in range(96)) + (
            SimpleNamespace(split="select", select_subfold="epoch-select",
                            slot_sha256="a" * 64),
            SimpleNamespace(split="select", select_subfold="precision-select",
                            slot_sha256="b" * 64),
            SimpleNamespace(split="audit", slot_sha256="c" * 64))

    def accept(identity, slot):
        material = SimpleNamespace(
            prestate={"index": identity["attempt_index"]}, audit_raws=(),
            candidates=(0, 1), state=SimpleNamespace(
                split=slot.split, phase="early", position="lead",
                role="attacker", source="natural",
                select_subfold=getattr(slot, "select_subfold", None)))
        return SimpleNamespace(
            accepted=True, rejection_reason=None, material=material,
            deal_sha256=identity["deal_sha256"])

    result = runner.run_score_free_preflight(attempt=accept, slots=slots)
    assert result.attempted == 99 and result.accepted == 5
    assert [runner._population_category(fixture.material)
            for fixture in result.accepted_fixtures] == [
                "fit", "fit", "epoch-select", "precision-select", "audit"]
    assert result.rejection_counts == (("split-reservation", 94),)


def test_real_preflight_driver_executes_in_a_process():
    from shengji.rl.world_afterstate_v2_protocol import (
        TIER_SPECS, _raw_slot_ledger)

    slot = next(row for row in _raw_slot_ledger(TIER_SPECS[0])
                if row.source in ("natural", "mechanics"))
    identity = runner._attempt_identity(runner._namespace(), slot, 0)
    with ProcessPoolExecutor(max_workers=1) as pool:
        child_pid, result = pool.submit(
            _real_preflight_process_probe, identity, slot).result(timeout=60)
    assert child_pid != os.getpid()
    result.validate()
    assert result.deal_sha256 == identity["deal_sha256"]
    assert result.slot_sha256 == slot.slot_sha256


def test_repaired_preflight_namespace_cannot_reuse_prior_attempt_identities():
    slot = SimpleNamespace(slot_sha256="a" * 64)
    prior = runner._sha({
        "namespace": "world-afterstate-v2-capacity-preflight-v1"})
    current = runner._namespace()
    assert current != prior
    old_identity = runner._attempt_identity(prior, slot, 0)
    new_identity = runner._attempt_identity(current, slot, 0)
    assert old_identity["population_namespace_sha256"] == prior
    assert new_identity["population_namespace_sha256"] == current
    assert old_identity["deal_sha256"] != new_identity["deal_sha256"]
    assert old_identity["engine_seed"] != new_identity["engine_seed"]


def test_capacity_process_pool_worker_rechecks_inherited_runtime(monkeypatch):
    expected = hashlib.sha256(canonical_json_bytes(
        execution.live_runtime_profile())).hexdigest()
    monkeypatch.setenv(execution.RUNTIME_EXPECTATION_ENV, expected)
    with ProcessPoolExecutor(
            max_workers=1, **execution.verified_process_pool_kwargs()) as pool:
        assert pool.submit(_runtime_pool_probe).result(timeout=60) == expected


def test_pool_initializer_does_not_depend_on_predating_forkserver(tmp_path):
    if "forkserver" not in multiprocessing.get_all_start_methods():
        pytest.skip("forkserver is unavailable")
    script = tmp_path / "forkserver_runtime_probe.py"
    script.write_text("""
import hashlib
import multiprocessing
import os
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, sys.argv[1])
from shengji.rl import world_afterstate_v2_execution as execution
from shengji.rl.belief_contract import canonical_json_bytes

def probe():
    return os.environ.get(execution.RUNTIME_EXPECTATION_ENV)

def main():
    context = multiprocessing.get_context("forkserver")
    with ProcessPoolExecutor(max_workers=1, mp_context=context) as pool:
        assert pool.submit(probe).result(timeout=60) is None
    expected = hashlib.sha256(canonical_json_bytes(
        execution.live_runtime_profile())).hexdigest()
    os.environ[execution.RUNTIME_EXPECTATION_ENV] = expected
    with ProcessPoolExecutor(
            max_workers=1, mp_context=context,
            **execution.verified_process_pool_kwargs()) as pool:
        assert pool.submit(probe).result(timeout=60) == expected

if __name__ == "__main__":
    main()
""", encoding="utf-8")
    environment = os.environ.copy()
    environment.pop(execution.RUNTIME_EXPECTATION_ENV, None)
    server = os.path.dirname(os.path.dirname(os.path.dirname(
        execution.__file__)))
    completed = subprocess.run(
        (sys.executable, "-P", "-B", str(script), server),
        env=environment, capture_output=True, text=True, timeout=90)
    assert completed.returncode == 0, completed.stderr


def test_parallel_capacity_operation_wires_runtime_initializer(monkeypatch):
    expected = hashlib.sha256(canonical_json_bytes(
        execution.live_runtime_profile())).hexdigest()
    monkeypatch.setenv(execution.RUNTIME_EXPECTATION_ENV, expected)
    seen = {}

    class Pool:
        def __init__(self, **kwargs):
            seen.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def map(self, _operation, payloads):
            return tuple("a" * 64 for _ in payloads)

    monkeypatch.setattr(runner, "ProcessPoolExecutor", Pool)
    operation = runner._parallel_operation(
        "state-successor", 1, (SimpleNamespace(fixture_sha256="1" * 64),))
    assert isinstance(operation(), str)
    assert seen["initializer"] is execution._verify_inherited_runtime_expectation
    assert seen["initargs"] == (expected,)


def test_continuation_capacity_operation_has_128_units_and_fixed_32_cycle(monkeypatch):
    expected = hashlib.sha256(canonical_json_bytes(
        execution.live_runtime_profile())).hexdigest()
    monkeypatch.setenv(execution.RUNTIME_EXPECTATION_ENV, expected)
    seen = {}

    class Pool:
        def __init__(self, **kwargs):
            seen.update(kwargs)
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return None
        def map(self, _operation, payloads):
            rows = tuple(payloads)
            seen["payloads"] = rows
            return tuple("a" * 64 for _ in rows)

    monkeypatch.setattr(runner, "ProcessPoolExecutor", Pool)
    fixtures = tuple(SimpleNamespace(fixture_sha256=f"{i:064x}")
                     for i in range(32))
    operation = runner._parallel_operation("continuation-mechanics", 64, fixtures)
    assert operation.measured_unit_count == 128
    assert len(operation()) == 64
    rows = seen["payloads"]
    assert len(rows) == 128 and [row[2].fixture_sha256 for row in rows] == [
        f"{i % 32:064x}" for i in range(128)]


def _capacity_training_fixture(index, *, candidates=2, audit_salt=""):
    from shengji.rl.world_afterstate_v2_population import PopulationMaterialV2

    digest = lambda value: hashlib.sha256(value.encode("ascii")).hexdigest()
    state = SimpleNamespace(
        deal_sha256=digest(f"deal:{index}"),
        slot_sha256=digest(f"slot:{index}"),
        state_sha256=digest(f"state:{index}"),
        source="natural", role="attacker", phase="early", position="lead",
        trump_rank="2", trump_mode="S")
    successor_sha256s = tuple(
        digest(f"successor:{index}:{candidate}")
        for candidate in range(candidates))
    candidate_set_sha256 = hashlib.sha256(canonical_json_bytes({
        "schema": "world-afterstate-v2-candidate-set-v1",
        "state_sha256": state.state_sha256,
        "successor_sha256s": list(successor_sha256s),
    })).hexdigest()
    audit_raws = tuple(canonical_json_bytes({
        "fixture": index, "candidate": candidate, "salt": audit_salt,
    }) for candidate in range(candidates))
    candidate_rows = tuple(SimpleNamespace(
        candidate_index=candidate, protected_incumbent=candidate == 0,
        audit_sha256=hashlib.sha256(audit_raws[candidate]).hexdigest(),
        successor_sha256=successor_sha256s[candidate])
        for candidate in range(candidates))
    material = object.__new__(PopulationMaterialV2)
    object.__setattr__(material, "state", state)
    object.__setattr__(material, "candidate_set_sha256", candidate_set_sha256)
    object.__setattr__(material, "candidates", candidate_rows)
    object.__setattr__(material, "audit_raws", audit_raws)
    prestate = {"public": {"attacker_points": 0}, "fixture": index}
    object.__setattr__(material, "prestate", prestate)
    object.__setattr__(material, "schema", "capacity-test-material")
    return FixtureV2(
        prestate, audit_raws=audit_raws, deal_sha256=state.deal_sha256,
        material=material)


def test_capacity_training_batch_uses_128_complete_rows_and_binds_all_materials(
        monkeypatch):
    import numpy as np
    import shengji.rl.world_afterstate as afterstate
    from shengji.rl.douzero_micro import HISTORY_EVENT_DIM
    from shengji.rl.encode import N_CARDS
    from shengji.rl.world_afterstate import (
        PERSPECTIVE_DIM, PUBLIC_DIM, WORLD_RECEIVERS,
        WorldAfterstateTensorsV0)

    monkeypatch.setattr(
        runner.PopulationMaterialV2, "validate", lambda _self: None)

    def tensors(_audit):
        return WorldAfterstateTensorsV0(
            np.zeros(PUBLIC_DIM, dtype=np.float32),
            np.zeros((0, HISTORY_EVENT_DIM), dtype=np.float32),
            np.zeros((WORLD_RECEIVERS, N_CARDS), dtype=np.float32),
            np.array([1.0, 0.0], dtype=np.float32))

    monkeypatch.setattr(afterstate, "build_afterstate_tensors", tensors)
    fixtures = tuple(_capacity_training_fixture(index) for index in range(32))
    first = runner._capacity_training_batch(fixtures)
    first.validate()
    assert first.size == runner.CAPACITY_TRAINING_EXAMPLES == 128
    assert first.root_count == 8
    unselected = next(index for index, fixture in enumerate(fixtures)
                      if fixture.deal_sha256 not in first.deal_sha256s)

    # An unselected retained material must still bind the workload through the
    # complete 32-material population digest.
    changed = list(fixtures)
    changed[unselected] = _capacity_training_fixture(
        unselected, audit_salt="changed")
    second = runner._capacity_training_batch(changed)
    assert second.example_keys == first.example_keys
    assert second.continuation_sha256s != first.continuation_sha256s
    assert not __import__("torch").equal(
        second.target_categories, first.target_categories)


def test_capacity_training_batch_refuses_when_complete_roots_cannot_total_128(
        monkeypatch):
    import numpy as np
    import shengji.rl.world_afterstate as afterstate
    from shengji.rl.douzero_micro import HISTORY_EVENT_DIM
    from shengji.rl.encode import N_CARDS
    from shengji.rl.world_afterstate import (
        PERSPECTIVE_DIM, PUBLIC_DIM, WORLD_RECEIVERS,
        WorldAfterstateTensorsV0)

    monkeypatch.setattr(
        runner.PopulationMaterialV2, "validate", lambda _self: None)
    monkeypatch.setattr(afterstate, "build_afterstate_tensors", lambda _audit:
        WorldAfterstateTensorsV0(
            np.zeros(PUBLIC_DIM, dtype=np.float32),
            np.zeros((0, HISTORY_EVENT_DIM), dtype=np.float32),
            np.zeros((WORLD_RECEIVERS, N_CARDS), dtype=np.float32),
            np.array([1.0, 0.0], dtype=np.float32)))
    fixtures = tuple(_capacity_training_fixture(index, candidates=3)
                     for index in range(32))
    with pytest.raises(CapacityRunnerError, match="complete 128-example"):
        runner._capacity_training_batch(fixtures)


def test_capacity_training_batch_reaches_real_optimizer_and_model_state(
        monkeypatch):
    import numpy as np
    import shengji.rl.world_afterstate as afterstate
    from shengji.rl.douzero_micro import HISTORY_EVENT_DIM
    from shengji.rl.encode import N_CARDS
    from shengji.rl.world_afterstate import (
        PERSPECTIVE_DIM, PUBLIC_DIM, WORLD_RECEIVERS,
        WorldAfterstateTensorsV0)

    monkeypatch.setattr(
        runner.PopulationMaterialV2, "validate", lambda _self: None)
    monkeypatch.setattr(afterstate, "build_afterstate_tensors", lambda _audit:
        WorldAfterstateTensorsV0(
            np.zeros(PUBLIC_DIM, dtype=np.float32),
            np.zeros((0, HISTORY_EVENT_DIM), dtype=np.float32),
            np.zeros((WORLD_RECEIVERS, N_CARDS), dtype=np.float32),
            np.array([1.0, 0.0], dtype=np.float32)))
    fixtures = tuple(_capacity_training_fixture(index) for index in range(32))
    operation = runner._model_operation("member-concurrency", 4, fixtures)
    assert operation.measured_unit_count == 4
    result = runner._run_with_torch_threads(operation, 1)
    assert len(result) == 64 and result != runner._ordered_fixture_identity(fixtures)


@pytest.mark.parametrize(("stage", "width", "member_count"), (
    ("member-concurrency", 4, 4),
    ("cohort-concurrency", 4, 16),
))
def test_training_capacity_operations_wire_real_128_row_batch_and_population(
        monkeypatch, stage, width, member_count):
    """Witness the repaired workload at the timed-operation boundary."""
    import numpy as np
    import shengji.rl.world_afterstate as afterstate
    import shengji.rl.world_afterstate_v2_model as model_module
    import shengji.rl.world_afterstate_v2_training as training_module
    from shengji.rl.douzero_micro import HISTORY_EVENT_DIM
    from shengji.rl.encode import N_CARDS
    from shengji.rl.world_afterstate import (
        PUBLIC_DIM, WORLD_RECEIVERS, WorldAfterstateTensorsV0)

    monkeypatch.setattr(
        runner.PopulationMaterialV2, "validate", lambda _self: None)
    monkeypatch.setattr(afterstate, "build_afterstate_tensors", lambda _audit:
        WorldAfterstateTensorsV0(
            np.zeros(PUBLIC_DIM, dtype=np.float32),
            np.zeros((0, HISTORY_EVENT_DIM), dtype=np.float32),
            np.zeros((WORLD_RECEIVERS, N_CARDS), dtype=np.float32),
            np.array([1.0, 0.0], dtype=np.float32)))

    class FakeModel:
        state_sha256 = "0" * 64

    calls = []

    def train_epoch(model, _optimizer, batches, *, epoch, config):
        assert len(batches) == 1
        batch = batches[0]
        batch.validate()
        assert batch.size == runner.CAPACITY_TRAINING_EXAMPLES == 128
        assert batch.root_count == 8
        state_sha256 = hashlib.sha256(canonical_json_bytes({
            "example_keys": list(batch.example_keys),
            "continuation_sha256s": list(batch.continuation_sha256s),
            "target_categories": batch.target_categories.tolist(),
        })).hexdigest()
        model.state_sha256 = state_sha256
        calls.append((batch.size, batch.root_count, epoch))

    monkeypatch.setattr(model_module, "new_world_afterstate_v2_model",
                        lambda _seed: FakeModel())
    monkeypatch.setattr(training_module, "new_optimizer",
                        lambda _model, _config: object())
    monkeypatch.setattr(training_module, "train_epoch", train_epoch)
    monkeypatch.setattr(training_module, "model_state_sha256",
                        lambda model: model.state_sha256)

    fixtures = tuple(_capacity_training_fixture(index) for index in range(32))
    selected = runner._capacity_training_batch(fixtures)
    unselected = next(index for index, fixture in enumerate(fixtures)
                      if fixture.deal_sha256 not in selected.deal_sha256s)
    first = runner._run_with_torch_threads(
        runner._model_operation(stage, width, fixtures), 1)

    changed = list(fixtures)
    changed[unselected] = _capacity_training_fixture(
        unselected, audit_salt="operation-changed")
    second = runner._run_with_torch_threads(
        runner._model_operation(stage, width, changed), 1)

    assert calls == [(128, 8, 1)] * (member_count * 2)
    assert first != second


def test_score_free_preflight_refuses_expired_batch_and_worker_failure(
        monkeypatch):
    monkeypatch.setattr(runner, "PREFLIGHT_ACCEPTED", 1)
    monkeypatch.setattr(runner, "PREFLIGHT_ATTEMPT_CEILING", 1)
    monkeypatch.setattr(runner, "PREFLIGHT_WORKERS", 1)
    slot = SimpleNamespace(slot_sha256="1" * 64)

    def slow_rejection(_identity, _slot):
        time.sleep(.02)
        return SimpleNamespace(
            accepted=False, rejection_reason="miss", material=None,
            deal_sha256="2" * 64)

    with pytest.raises(CapacityRunnerError, match="deadline"):
        runner.run_score_free_preflight(
            attempt=slow_rejection, slots=(slot,),
            deadline_ns=time.perf_counter_ns() + 5_000_000)

    def broken_worker(_identity, _slot):
        raise RuntimeError("worker exploded")

    with pytest.raises(CapacityRunnerError, match="preflight worker failed"):
        runner.run_score_free_preflight(
            attempt=broken_worker, slots=(slot,))


def test_score_free_preflight_guards_aggregate_child_memory(monkeypatch):
    monkeypatch.setattr(runner, "PREFLIGHT_ACCEPTED", 1)
    monkeypatch.setattr(runner, "PREFLIGHT_ATTEMPT_CEILING", 1)
    monkeypatch.setattr(runner, "PREFLIGHT_WORKERS", 1)
    monkeypatch.setattr(runner, "_rss_bytes", lambda: 1)
    memory_samples = iter((1, 1, runner.MEMORY_LIMIT_BYTES))
    monkeypatch.setattr(
        runner, "_cgroup_memory_bytes",
        lambda: next(memory_samples, runner.MEMORY_LIMIT_BYTES))
    slot = SimpleNamespace(slot_sha256="3" * 64)

    def rejection(_identity, _slot):
        return SimpleNamespace(
            accepted=False, rejection_reason="miss", material=None,
            deal_sha256="4" * 64)

    with pytest.raises(CapacityRunnerError, match="memory headroom"):
        runner.run_score_free_preflight(attempt=rejection, slots=(slot,))


def _backend(fixture: FixtureV2, **changes):
    values = {}
    for stage, variants in ARM_GRIDS.items():
        for variant in variants:
            values[(stage, variant)] = RawMeasurementV2(
                elapsed_ns=(variant + 1) * 1_000_000_000,
                process_cpu_ns=(variant + 1) * 14_400_000_000,
                peak_rss_bytes=1_000_000, task_count=1,
                sample_utilization_ppm=(900_000,),
                byte_identity_sha256=fixture.fixture_sha256)
    values.update(changes)
    return SyntheticMeasurementBackendV2(values)


def _full_dag_measurement(*, capabilities=None, member_workers=2,
                          torch_threads=1, inference_batch=128,
                          reconstruction_workers=1, continuation_workers=1,
                          wall_seconds=1, cpu_seconds=14):
    capabilities = ({name: True for name in _RECOVERY_CAPABILITY_NAMES}
                    if capabilities is None else capabilities)
    walls = tuple((name, wall_seconds) for name in COMPOSED_STAGE_NAMES)
    units = tuple((name, 32) for name in COMPOSED_STAGE_NAMES)
    cpu = tuple((name, cpu_seconds * 1_000_000_000)
                for name in COMPOSED_STAGE_NAMES)
    return FullDAGCapacityMeasurementV2(
        tuple((name, value * 1_000_000_000) for name, value in walls), 1,
        COMPOSED_STAGE_NAMES, 0, True, capabilities, _FULL_DAG_PROVENANCE,
        units, cpu, member_workers, continuation_workers, torch_threads,
        inference_batch, reconstruction_workers)


def _selected_arms(fixture: FixtureV2):
    arms = []
    for stage, variants in ARM_GRIDS.items():
        for variant in variants:
            seconds = (1 if stage == "cohort-concurrency" and variant == 4
                       else variant + 1)
            raw = RawMeasurementV2(
                elapsed_ns=seconds * 1_000_000_000,
                process_cpu_ns=seconds * 14_400_000_000,
                peak_rss_bytes=1_000_000, task_count=1,
                sample_utilization_ppm=(900_000,),
                byte_identity_sha256=fixture.fixture_sha256)
            arms.append(_arm_from_raw(
                stage, variant, raw, fixture.fixture_sha256, raw.elapsed_ns,
                measured_unit_count=(128 if stage == "continuation-mechanics"
                                     else 32 if stage in ("state-successor",
                                                           "reconstruction")
                                     else 1)))
    return tuple(arms)


def test_arm_selection_uses_exact_nanoseconds_not_rounded_display_seconds():
    fixture = FixtureV2({"score_free": True})
    arms = list(_selected_arms(fixture))
    stage = "state-successor"
    for variant, wall_ns in ((1, 1_900_000_000), (2, 1_100_000_000)):
        index = next(index for index, arm in enumerate(arms)
                     if arm.stage == stage and arm.variant == variant)
        busy_ns = wall_ns * 14
        arms[index] = dataclasses.replace(
            arms[index], wall_ns=wall_ns, wall_seconds=2,
            busy_core_ns=busy_ns, busy_core_seconds=16 if variant == 2 else 27,
            mean_cpu_utilization_ppm=875_000)
    assert runner._select_arms(arms)[stage].variant == 2


def test_projected_wall_shares_are_bound_at_arm_wiring_site():
    fixture = FixtureV2({"score_free": True})
    arms = _selected_arms(fixture)
    stage_walls = {name: index + 1
                   for index, name in enumerate(COMPOSED_STAGE_NAMES)}
    expected = projected_arm_wall_shares_ppm(stage_walls)
    bound = runner._bind_projected_arm_shares(arms, stage_walls)
    assert {arm.stage: arm.wall_share_ppm for arm in bound} == expected


def test_every_frozen_arm_runs_and_synthetic_cannot_publish():
    preflight = _preflight()
    fixture = preflight.accepted_fixtures[0]
    events = []
    result = measure_capacity_v2(
        preflight=preflight, backend=_backend(fixture),
        host=HostTelemetryV2(16, free_disk_bytes=10**9),
        progress=events.append, production=False)
    assert {(arm.stage, arm.variant) for arm in result.arms} == {
        (stage, variant) for stage, variants in ARM_GRIDS.items()
        for variant in variants}
    assert result.synthetic is True
    with pytest.raises(CapacityRunnerError, match="synthetic"):
        result.production_receipt()
    with pytest.raises(CapacityRunnerError, match="synthetic"):
        build_receipt_v2(
            result.arms, host=HostTelemetryV2(16), preflight=preflight,
            source_sha256="a" * 64, runtime_sha256="b" * 64)
    assert events[0]["completed_units"] == 1
    assert events[-1]["completed_units"] == len(ARM_GRIDS[events[-1]["stage"]])


def test_member_concurrency_trains_four_members_and_only_changes_executor_width(
        monkeypatch):
    import torch
    import shengji.rl.world_afterstate_v2_capacity_runner as runner
    import shengji.rl.world_afterstate_v2_model as model_module
    import shengji.rl.world_afterstate_v2_training as training_module

    model_count = []
    train_calls = []

    class FakeModel:
        def __init__(self, index):
            self.index = index

    def make_model(_seed):
        index = len(model_count) % 4
        model_count.append(index)
        value = FakeModel(index)
        return value

    class FakeOptimizer:
        pass

    widths = []

    class SpyExecutor(ThreadPoolExecutor):
        def __init__(self, *args, **kwargs):
            widths.append(kwargs.get("max_workers", args[0] if args else None))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(runner, "_capacity_training_batch", lambda values: object())
    monkeypatch.setattr(model_module, "new_world_afterstate_v2_model", make_model)
    monkeypatch.setattr(training_module, "new_optimizer",
                        lambda model, config: FakeOptimizer())
    monkeypatch.setattr(training_module, "train_epoch",
                        lambda model, optimizer, batches, **kwargs: train_calls.append(
                            (model.index, batches, kwargs)) or object())
    monkeypatch.setattr(training_module, "model_state_sha256",
                        lambda model: f"{model.index + 1:064x}")
    monkeypatch.setattr(runner, "ThreadPoolExecutor", SpyExecutor)
    fixture = FixtureV2({"score_free": True})

    digests = []
    for width in (1, 2, 4):
        operation = runner._model_operation("member-concurrency", width,
                                           (fixture,))
        digests.append(runner._run_with_torch_threads(operation, 1))

    assert widths == [1, 2, 4]
    assert len(model_count) == 12
    assert len(train_calls) == 12
    assert all(call[1] == (object,) or len(call[1]) == 1 for call in train_calls)
    assert len(set(digests)) == 1


def test_cohort_concurrency_trains_four_complete_cohorts_at_fixed_member_width(
        monkeypatch):
    import shengji.rl.world_afterstate_v2_capacity_runner as runner
    import shengji.rl.world_afterstate_v2_model as model_module
    import shengji.rl.world_afterstate_v2_training as training_module

    models = []
    trained = []
    widths = []

    class FakeModel:
        def __init__(self, index):
            self.index = index

    class SpyExecutor(ThreadPoolExecutor):
        def __init__(self, *args, **kwargs):
            widths.append(kwargs.get("max_workers", args[0] if args else None))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(runner, "_capacity_training_batch",
                        lambda _values: object())
    monkeypatch.setattr(
        model_module, "new_world_afterstate_v2_model",
        lambda _seed: models.append(FakeModel(len(models) % 16)) or models[-1])
    monkeypatch.setattr(training_module, "new_optimizer",
                        lambda _model, _config: object())
    monkeypatch.setattr(
        training_module, "train_epoch",
        lambda model, *_args, **_kwargs: trained.append(model.index))
    monkeypatch.setattr(training_module, "model_state_sha256",
                        lambda model: f"{model.index + 1:064x}")
    monkeypatch.setattr(runner, "ThreadPoolExecutor", SpyExecutor)
    fixture = FixtureV2({"score_free": True})

    digests = tuple(runner._run_with_torch_threads(
        runner._model_operation("cohort-concurrency", width, (fixture,)), 1)
        for width in (1, 2, 4))

    assert len(models) == len(trained) == 48
    assert sorted(trained) == sorted(list(range(16)) * 3)
    assert widths.count(1) == 1 and widths.count(2) == 1
    # Twelve inner four-member executors plus the width-four outer arm.
    assert widths.count(4) == 13
    assert len(set(digests)) == 1


def test_cohort_concurrency_constructs_cohorts_inside_outer_wave(monkeypatch):
    import shengji.rl.world_afterstate_v2_capacity_runner as runner
    import shengji.rl.world_afterstate_v2_model as model_module
    import shengji.rl.world_afterstate_v2_training as training_module

    barrier = threading.Barrier(4)
    constructor_threads = set()
    lock = threading.Lock()
    thread_calls = {}

    class FakeModel:
        pass

    def make_model(_seed):
        thread = threading.get_ident()
        with lock:
            constructor_threads.add(thread)
            count = thread_calls.get(thread, 0)
            thread_calls[thread] = count + 1
        if count == 0:
            barrier.wait(timeout=2)
        return FakeModel()

    monkeypatch.setattr(runner, "_capacity_training_batch",
                        lambda _values: object())
    monkeypatch.setattr(model_module, "new_world_afterstate_v2_model", make_model)
    monkeypatch.setattr(training_module, "new_optimizer",
                        lambda _model, _config: object())
    monkeypatch.setattr(training_module, "train_epoch",
                        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(training_module, "model_state_sha256",
                        lambda _model: "a" * 64)

    operation = runner._model_operation(
        "cohort-concurrency", 4, (FixtureV2({"score_free": True}),))
    runner._run_with_torch_threads(operation, 1)
    assert len(constructor_threads) == 4


def test_torch_training_operation_runs_real_model_step_at_pinned_width(
        monkeypatch):
    import torch
    import shengji.rl.world_afterstate_v2_capacity_runner as runner
    import shengji.rl.world_afterstate_v2_model as model_module
    import shengji.rl.world_afterstate_v2_training as training_module

    class FakeModel:
        pass

    seen_widths = []
    monkeypatch.setattr(runner, "_capacity_training_batch", lambda values: object())
    monkeypatch.setattr(model_module, "new_world_afterstate_v2_model",
                        lambda _seed: FakeModel())
    monkeypatch.setattr(training_module, "new_optimizer",
                        lambda model, config: object())
    monkeypatch.setattr(
        training_module, "train_epoch",
        lambda *args, **kwargs: seen_widths.append(torch.get_num_threads()))
    monkeypatch.setattr(training_module, "model_state_sha256",
                        lambda model: "a" * 64)

    operation = runner._model_operation(
        "member-concurrency", 1, (FixtureV2({"score_free": True}),))
    assert runner._run_with_torch_threads(operation, 1) \
        == runner._sha(["a" * 64] * 4)
    assert seen_widths == [1] * 4


@pytest.mark.parametrize("width", (2, 4))
def test_torch_width_helper_refuses_cross_width_training(width):
    with pytest.raises(CapacityRunnerError, match="pinned to 1"):
        _run_with_torch_threads(lambda: "a" * 64, width)


def test_selected_layout_is_frozen_before_supervisor_and_bound_to_receipt(
        monkeypatch):
    import shengji.rl.world_afterstate_v2_capacity_runner as runner
    import shengji.rl.world_afterstate_v2_capacity_supervisor as supervisor
    import shengji.rl.world_afterstate_v2_model as model_module

    preflight = _preflight()
    target = {"member-concurrency": 2, "cohort-concurrency": 4,
              "inference-batch": 128}

    class Backend:
        synthetic = False

        def measure(self, stage, variant, fixture, operation):
            seconds = 1 if target.get(stage) == variant else 2
            return RawMeasurementV2(
                elapsed_ns=seconds * 1_000_000_000,
                process_cpu_ns=seconds * 14_400_000_000,
                peak_rss_bytes=1_000_000, task_count=1,
                sample_utilization_ppm=(900_000,),
                byte_identity_sha256="a" * 64)

    seen = {}

    def run_supervisor(fixtures, **kwargs):
        seen.update(kwargs)
        return _full_dag_measurement(
            member_workers=kwargs["member_workers"],
            torch_threads=kwargs["torch_threads"],
            inference_batch=kwargs["inference_batch"])

    monkeypatch.setattr(runner, "run_score_free_preflight",
                        lambda **kwargs: preflight)
    monkeypatch.setattr(runner, "observe_host",
                        lambda: HostTelemetryV2(16, free_disk_bytes=10**12))
    monkeypatch.setattr(runner, "RealMeasurementBackendV2",
                        lambda **kwargs: Backend())
    monkeypatch.setattr(runner, "_model_operation",
                        lambda stage, variant, fixtures: lambda: "a" * 64)
    monkeypatch.setattr(runner, "_parallel_operation",
                        lambda stage, variant, fixtures: lambda: "a" * 64)
    monkeypatch.setattr(supervisor, "run_full_dag_supervisor", run_supervisor)
    monkeypatch.setattr(model_module, "count_trainable_parameters",
                        lambda model: 123)
    monkeypatch.setattr(model_module, "new_world_afterstate_v2_model",
                        lambda seed: object())

    result = runner.measure_capacity_v2(
        production=True, source_sha256="a" * 64,
        runtime_sha256="b" * 64)
    receipt = result.production_receipt()
    assert (seen["member_workers"], seen["torch_threads"],
            seen["inference_batch"], seen["reconstruction_workers"]) \
        == (2, 1, 128, 1)
    assert seen["continuation_workers"] == 1
    assert (receipt.member_workers, receipt.torch_threads,
            receipt.inference_batch, receipt.reconstruction_workers) \
        == (2, 1, 128, 1)
    assert receipt.continuation_workers == 1
    assert receipt.command_wall_seconds == (
        sum(arm.wall_seconds for arm in result.arms)
        + len(COMPOSED_STAGE_NAMES) + 1)

    from dataclasses import replace
    bad = RepresentativeDAGV2(
        1, 1, 1, 1, 1, 1, 1, 1, admissible=True,
        stage_walls_seconds=tuple((name, 1) for name in COMPOSED_STAGE_NAMES),
        stage_wall_nanoseconds=tuple(
            (name, 1_000_000_000) for name in COMPOSED_STAGE_NAMES),
        progress_recovery=_full_dag_measurement().progress_recovery,
        provenance_token=_FULL_DAG_PROVENANCE,
        stage_source_unit_counts=tuple((name, 32) for name in COMPOSED_STAGE_NAMES),
        stage_process_cpu_nanoseconds=tuple(
            (name, 1_000_000_000) for name in COMPOSED_STAGE_NAMES),
        member_workers=2, continuation_workers=32, torch_threads=1,
        inference_batch=128,
        reconstruction_workers=1)
    bad = replace(bad, attestation_sha256=_dag_attestation(bad))
    with pytest.raises(FullDAGCapacityDependencyBlocked, match="layout"):
        build_receipt_v2(
            result.arms, host=HostTelemetryV2(16, free_disk_bytes=10**12),
            preflight=preflight, source_sha256="a" * 64,
            runtime_sha256="b" * 64,
            representative_dag=bad,
            _provenance=_PRODUCTION_PROVENANCE)


def test_capacity_binds_fastest_measured_cohort_width_into_full_dag(monkeypatch):
    import shengji.rl.world_afterstate_v2_capacity_supervisor as supervisor
    import shengji.rl.world_afterstate_v2_model as model_module

    preflight = _preflight()

    class Backend:
        synthetic = False

        def measure(self, stage, variant, fixture, operation):
            del operation
            seconds = (1 if stage == "cohort-concurrency" and variant == 2
                       else 2)
            return RawMeasurementV2(
                elapsed_ns=seconds * 1_000_000_000,
                process_cpu_ns=seconds * 14_400_000_000,
                peak_rss_bytes=1_000_000, task_count=1,
                sample_utilization_ppm=(900_000,),
                byte_identity_sha256="a" * 64)

    reached_full_dag = False
    seen = {}

    def run_supervisor(*_args, **kwargs):
        nonlocal reached_full_dag
        reached_full_dag = True
        seen.update(kwargs)
        return _full_dag_measurement(
            member_workers=kwargs["member_workers"],
            torch_threads=kwargs["torch_threads"],
            inference_batch=kwargs["inference_batch"])

    monkeypatch.setattr(runner, "run_score_free_preflight",
                        lambda **_kwargs: preflight)
    monkeypatch.setattr(runner, "observe_host",
                        lambda: HostTelemetryV2(16, free_disk_bytes=10**12))
    monkeypatch.setattr(runner, "RealMeasurementBackendV2",
                        lambda **_kwargs: Backend())
    monkeypatch.setattr(runner, "_model_operation",
                        lambda *_args: lambda: "a" * 64)
    monkeypatch.setattr(runner, "_parallel_operation",
                        lambda *_args: lambda: "a" * 64)
    monkeypatch.setattr(supervisor, "run_full_dag_supervisor", run_supervisor)
    monkeypatch.setattr(model_module, "count_trainable_parameters",
                        lambda _model: 123)
    monkeypatch.setattr(model_module, "new_world_afterstate_v2_model",
                        lambda _seed: object())

    result = runner.measure_capacity_v2(
        production=True, source_sha256="a" * 64,
        runtime_sha256="b" * 64)
    assert reached_full_dag is True
    assert seen["member_workers"] == 1
    receipt = result.production_receipt()
    selected = {arm.stage: arm.variant for arm in receipt.selected_arms}
    assert selected["cohort-concurrency"] == 2


def test_census_collects_two_simultaneous_gate_violations():
    fixture = _preflight().accepted_fixtures[0]
    arms = list(_selected_arms(fixture))
    selected = runner._select_arms(arms)
    # Keep both mutated categories material in the selected-arm budget.
    selected_keys = {(stage, value.variant) for stage, value in selected.items()}
    for index, arm in enumerate(arms):
        if (arm.stage, arm.variant) in selected_keys:
            arms[index] = dataclasses.replace(
                arm, wall_ns=1_000_000_000, wall_seconds=1,
                busy_core_ns=14_000_000_000, busy_core_seconds=14,
                mean_cpu_utilization_ppm=875_000,
                p50_cpu_utilization_ppm=875_000)
    selected = runner._select_arms(arms)
    for stage in ("state-successor", "member-concurrency"):
        index = next(i for i, arm in enumerate(arms)
                     if arm.stage == stage and arm.variant == 1)
        arm = arms[index]
        wall_ns = 1_000_000_000
        busy_ns = wall_ns * 16 * 800_000 // 1_000_000
        arms[index] = dataclasses.replace(
            arm, wall_ns=wall_ns, wall_seconds=1, busy_core_ns=busy_ns,
            busy_core_seconds=13, mean_cpu_utilization_ppm=800_000,
            p50_cpu_utilization_ppm=800_000, cpu_bound=True)
        next_index = next(i for i, value in enumerate(arms)
                          if value.stage == stage and value.variant == 2)
        next_arm = arms[next_index]
        arms[next_index] = dataclasses.replace(
            next_arm, wall_ns=wall_ns, wall_seconds=1,
            busy_core_ns=next_arm.wall_ns * 14,
            busy_core_seconds=14, mean_cpu_utilization_ppm=875_000,
            p50_cpu_utilization_ppm=875_000)
        selected[stage] = arms[index]
    with pytest.raises(CapacityRunnerError) as caught:
        validate_capacity_arm_census_v2(
            tuple(arms), selected,
            {name: 100 for name in COMPOSED_STAGE_NAMES})
    bad = {row.category for row in caught.value.assessments if row.violates_gate}
    assert {"state-successor", "member-concurrency"} <= bad
    assert len(caught.value.assessments) == len(ARM_GRIDS)


def test_exact_32_unit_arm_projection_does_not_multiply_wall_by_32():
    fixture = _preflight().accepted_fixtures[0]
    selected = runner._select_arms(_selected_arms(fixture))
    selected["state-successor"] = dataclasses.replace(
        selected["state-successor"], measured_unit_count=32,
        wall_ns=1_000_000_000, wall_seconds=1)
    mapping = {stage: (arm.measured_unit_count, 32)
               for stage, arm in selected.items()}
    composed = _composed_projection(
        selected, 32, 10**9, arm_target_units=mapping)
    assert dict(composed.stage_walls_seconds)["nested-curve-100"] == 1


def test_nanosecond_utilization_threshold_is_exact():
    fixture = FixtureV2({"score_free": True})
    for utilization in (849_999, 850_000):
        elapsed_ns = 1_000_000_000
        process_cpu_ns = elapsed_ns * 16 * utilization // 1_000_000
        arm = _arm_from_raw(
            "state-successor", 1,
            RawMeasurementV2(
                elapsed_ns=elapsed_ns, process_cpu_ns=process_cpu_ns,
                peak_rss_bytes=1_000_000, task_count=1,
                sample_utilization_ppm=(utilization,),
                byte_identity_sha256=fixture.fixture_sha256),
            fixture.fixture_sha256, elapsed_ns)
        assert arm.mean_cpu_utilization_ppm == utilization


def test_low_fastest_32_refuses_before_supervisor(monkeypatch):
    preflight = _preflight()
    fixture = preflight.accepted_fixtures[0]
    calls = []

    class Backend:
        synthetic = False

        def measure(self, stage, variant, fixture, operation):
            wall = 1 if stage == "state-successor" and variant == 32 else 2
            utilization = 800_000 if stage == "state-successor" and variant == 32 else 900_000
            elapsed_ns = wall * 1_000_000_000
            cpu_ns = elapsed_ns * 16 * utilization // 1_000_000
            return RawMeasurementV2(
                elapsed_ns=elapsed_ns, process_cpu_ns=cpu_ns,
                peak_rss_bytes=1_000_000, task_count=1,
                sample_utilization_ppm=(utilization,),
                byte_identity_sha256="a" * 64)

    import shengji.rl.world_afterstate_v2_capacity_supervisor as supervisor
    monkeypatch.setattr(runner, "run_score_free_preflight",
                        lambda **kwargs: preflight)
    monkeypatch.setattr(runner, "observe_host",
                        lambda: HostTelemetryV2(16, free_disk_bytes=10**12))
    monkeypatch.setattr(runner, "RealMeasurementBackendV2",
                        lambda **kwargs: Backend())
    monkeypatch.setattr(runner, "_model_operation",
                        lambda stage, variant, fixtures: lambda: "a" * 64)
    monkeypatch.setattr(runner, "_parallel_operation",
                        lambda stage, variant, fixtures: lambda: "a" * 64)
    monkeypatch.setattr(supervisor, "run_full_dag_supervisor",
                        lambda *args, **kwargs: calls.append(True))
    with pytest.raises(CapacityRunnerError):
        runner.measure_capacity_v2(
            production=True, source_sha256="a" * 64,
            runtime_sha256="b" * 64)
    assert calls == []


def test_refuses_byte_mismatch_and_preflight_not_32():
    preflight = _preflight()
    fixture = preflight.accepted_fixtures[0]
    bad = RawMeasurementV2(
        elapsed_ns=1_000_000_000, process_cpu_ns=14_400_000_000,
        peak_rss_bytes=1_000_000, task_count=1,
        byte_identity_sha256="0" * 64)
    with pytest.raises(CapacityRunnerError, match="byte-identical"):
        values = {(stage, variant): value
                  for (stage, variant), value in _backend(fixture).measurements.items()}
        values[("state-successor", 1)] = bad
        measure_capacity_v2(
            preflight=preflight, backend=SyntheticMeasurementBackendV2(values),
            host=HostTelemetryV2(16), production=False)
    with pytest.raises(CapacityRunnerError, match="32"):
        PreflightResultV2(
            accepted_fixtures=(fixture,) * 31, attempted=31, accepted=31,
            rejection_counts=(), candidate_distribution=((2, 31),),
            stratum_distribution=(("early/lead/attacker", 31),),
            elapsed_wall_nanoseconds=1_000_000_000).validate()


def test_production_altitude_refuses_fixture_input_identity(monkeypatch):
    preflight = _preflight()
    fixture = preflight.accepted_fixtures[0]

    class Backend:
        synthetic = False

        def measure(self, stage, variant, fixture, operation):
            output = operation()
            return RawMeasurementV2(
                elapsed_ns=1_000_000_000, process_cpu_ns=14_400_000_000,
                peak_rss_bytes=1_000_000, task_count=1,
                sample_utilization_ppm=(900_000,),
                byte_identity_sha256=output)

    monkeypatch.setattr(runner, "run_score_free_preflight",
                        lambda **kwargs: preflight)
    monkeypatch.setattr(runner, "observe_host",
                        lambda: HostTelemetryV2(16, free_disk_bytes=10**12))
    monkeypatch.setattr(runner, "RealMeasurementBackendV2",
                        lambda **kwargs: Backend())
    monkeypatch.setattr(
        runner, "_parallel_operation",
        lambda stage, variant, fixtures: lambda: fixture.fixture_sha256)
    monkeypatch.setattr(
        runner, "_model_operation",
        lambda stage, variant, fixtures: lambda: fixture.fixture_sha256)
    with pytest.raises(CapacityRunnerError, match="input identity"):
        runner.measure_capacity_v2(
            production=True, source_sha256="a" * 64,
            runtime_sha256="b" * 64)


def test_receipt_reopens_exactly_and_host_caps_refuse():
    preflight = _preflight()
    fixture = preflight.accepted_fixtures[0]
    arms = tuple(_arm_from_raw(
        stage, variant, RawMeasurementV2(
            elapsed_ns=1_000_000_000,
            process_cpu_ns=14_400_000_000,
            peak_rss_bytes=1_000_000, task_count=1,
            sample_utilization_ppm=(900_000,),
            byte_identity_sha256=fixture.fixture_sha256), fixture.fixture_sha256,
        1, synthetic=False,
        measured_unit_count=(128 if stage == "continuation-mechanics"
                             else 32 if stage in ("state-successor",
                                                   "reconstruction") else 1))
                  for stage, variants in ARM_GRIDS.items() for variant in variants)
    with pytest.raises(FullDAGCapacityDependencyBlocked, match="full-DAG"):
        build_receipt_v2(
            arms, host=HostTelemetryV2(16, free_disk_bytes=10**9),
            preflight=preflight, source_sha256="a" * 64,
            runtime_sha256="b" * 64,
            _provenance=_PRODUCTION_PROVENANCE)
    with pytest.raises(CapacityRunnerError, match="16 logical"):
        HostTelemetryV2(8).validate()
    with pytest.raises(CapacityRunnerError, match="zero swap"):
        HostTelemetryV2(16, swap_bytes=1).validate()


def test_real_monitor_witnesses_samples_and_child_cpu():
    backend = RealMeasurementBackendV2()
    before = backend.measure("state-successor", 1, FixtureV2({"x": 1}),
                             lambda: subprocess.run(
                                 ["sh", "-c", "python3 -c 'sum(i*i for i in range(1000000))'"],
                                 check=True))
    before.validate()
    assert before.process_cpu_ns > 0
    assert before.sample_memory_bytes
    assert before.sample_task_counts
    assert before.sample_free_disk_bytes


def test_real_deadline_interrupts_hung_operation():
    backend = RealMeasurementBackendV2(
        deadline_ns=time.perf_counter_ns() + 20_000_000)
    with pytest.raises(CapacityRunnerError, match="deadline"):
        backend.measure("state-successor", 1, FixtureV2({"x": 1}),
                        lambda: time.sleep(.2))


def test_operation_outputs_are_domain_separated_and_input_identity_refused(
        monkeypatch):
    monkeypatch.setattr(
        runner.PopulationMaterialV2, "validate", lambda self: None)
    material = object.__new__(runner.PopulationMaterialV2)
    object.__setattr__(material, "prestate", {"score_free": True})
    object.__setattr__(material, "audit_raws", (
        b'{"successor": {}, "root_seat": 0}',))
    object.__setattr__(material, "state", SimpleNamespace(deal_sha256=""))
    fixture = FixtureV2(
        {"score_free": True}, audit_raws=(
            b'{"successor": {}, "root_seat": 0}',),
        material=material)
    fixtures = (fixture,) * 32
    ordered_input = runner._ordered_fixture_identity(fixtures)
    fake_round = SimpleNamespace(phase="deal", trick=None, turn=0)
    successor = {"schema": "world-afterstate-successor-v0",
                 "output": "replayed-operation"}
    monkeypatch.setattr(runner, "replay_canonical_successor",
                        lambda snapshot: fake_round)
    monkeypatch.setattr(runner, "canonical_successor",
                        lambda value, root_seat: successor)
    import shengji.rl.world_afterstate as world_afterstate
    import shengji.rl.world_afterstate_v2_continuation as continuation
    monkeypatch.setattr(world_afterstate, "reopen_afterstate_audit",
                        lambda record: fake_round)
    monkeypatch.setattr(
        continuation, "run_continuation_capacity_probe_v2",
        lambda material: runner._sha("continuation-probe"))

    for stage in ("state-successor", "continuation-mechanics",
                  "reconstruction"):
        population_identities = []
        for variant in (1, 2, 4):
            outputs = tuple(runner._process_fixture((stage, variant, item))
                            for item in fixtures)
            population_identities.append(runner._sha(outputs))
        assert len(set(population_identities)) == 1
        assert population_identities[0] != ordered_input

    monkeypatch.setattr(
        runner, "_operation",
        lambda stage, variant, value: lambda: fixture.fixture_sha256)
    with pytest.raises(CapacityRunnerError, match="input identity"):
        runner._process_fixture(("state-successor", 1, fixture))


def test_torch_thread_arm_preserves_output_digest_and_restores_width():
    import torch
    before = torch.get_num_threads()
    assert _run_with_torch_threads(lambda: "a" * 64, 1) == "a" * 64
    assert torch.get_num_threads() == before


def test_inference_output_identity_is_batch_partition_invariant():
    import torch
    from shengji.rl.world_afterstate import OUTCOME_CLASSES
    rows = torch.linspace(
        -1, 1, 6 * OUTCOME_CLASSES, dtype=torch.float32).reshape(
            6, OUTCOME_CLASSES)
    assert _batched_prediction_identity((rows[:2], rows[2:])) \
        == _batched_prediction_identity((rows[:1], rows[1:4], rows[4:]))


def test_inference_identity_uses_sealed_probability_not_raw_logit_ulps():
    import torch
    from shengji.rl.world_afterstate import OUTCOME_CLASSES
    baseline = torch.zeros((2, OUTCOME_CLASSES), dtype=torch.float32)
    baseline[0, :4] = torch.tensor([0.25, -0.5, 1.0, 0.0])
    baseline[1, :4] = torch.tensor([-0.75, 0.125, 0.5, 1.25])
    subcanonical = baseline.clone()
    subcanonical[0, 0] += torch.finfo(torch.float32).eps
    material = baseline.clone()
    material[0, 0] += 0.01

    # The failed Perf census compared the first two identities at raw-logit
    # altitude.  Production seals the canonical PPB prediction instead.
    assert runner._tensor_identity(baseline) != runner._tensor_identity(subcanonical)
    assert _batched_prediction_identity((baseline,)) \
        == _batched_prediction_identity((subcanonical,))
    assert _batched_prediction_identity((baseline,)) \
        != _batched_prediction_identity((material,))


def test_model_inference_arm_wires_sealed_prediction_identity(monkeypatch):
    import torch
    import shengji.rl.world_afterstate as afterstate
    import shengji.rl.world_afterstate_v2_model as model_module
    from shengji.rl.world_afterstate import OUTCOME_CLASSES

    fixture = FixtureV2(
        {"score_free": True},
        audit_raws=(b'{"successor":{},"root_seat":0}',) * 65)
    monkeypatch.setattr(afterstate, "build_afterstate_tensors", lambda _value: object())
    monkeypatch.setattr(
        model_module, "collate_world_afterstate_tensors",
        lambda values: SimpleNamespace(size=len(values)))

    class FakeModel:
        def __call__(self, batch):
            return torch.arange(
                batch.size * OUTCOME_CLASSES, dtype=torch.float32).reshape(
                    batch.size, OUTCOME_CLASSES)

    monkeypatch.setattr(model_module, "new_world_afterstate_v2_model", lambda _seed: FakeModel())
    calls = []
    original = runner._batched_prediction_identity

    def witnessed(values):
        calls.append(tuple(value.shape[0] for value in values))
        return original(values)

    monkeypatch.setattr(runner, "_batched_prediction_identity", witnessed)
    left = runner._model_operation("inference-batch", 32, (fixture,))()
    right = runner._model_operation("inference-batch", 64, (fixture,))()
    assert left == right
    assert calls == [(32, 32, 1), (64, 1)]


def test_composed_projection_counts_epochs_and_scales_tiers_by_stage():
    preflight = _preflight()
    fixture = preflight.accepted_fixtures[0]
    selected = {}
    for stage, variants in ARM_GRIDS.items():
        raw = RawMeasurementV2(
            elapsed_ns=1_000_000_000, process_cpu_ns=1_000_000_000,
            peak_rss_bytes=1_000_000, task_count=1,
            sample_utilization_ppm=(62_500,),
            byte_identity_sha256=fixture.fixture_sha256)
        selected[stage] = _arm_from_raw(
            stage, variants[0], raw, fixture.fixture_sha256, raw.elapsed_ns,
            measured_unit_count=(128 if stage == "continuation-mechanics"
                                 else 32 if stage in ("state-successor",
                                                       "reconstruction") else 1))
    dag = RepresentativeDAGV2(
        1, 1, 1, 1, 1, 1, 1, 1, admissible=True,
        stage_walls_seconds=tuple((name, 1) for name in COMPOSED_STAGE_NAMES))
    composed = _composed_projection(selected, 32, 10**9, dag)
    units = {name: (measured, projected)
             for name, measured, projected in composed.stage_unit_counts}
    assert units["optimizer-canary"] == (8_000, 8_000)
    assert units["nested-curve-25"] == (20, 848)
    assert units["nested-curve-50"] == (24, 1648)
    assert units["nested-curve-100"] == (16, 208)
    assert units["p0"] == (32, 96)
    assert units["label-p0"] == (32, 96)
    assert units["label-fit"] == (32, 88)
    assert units["label-precision-select"] == (32, 24)
    assert units["label-audit"] == (32, 48)
    assert sum(units[name][1] for name in (
        "label-p0", "label-fit", "label-precision-select", "label-audit")) == 256
    assert units["block-1-natural"] == (32, 3_200)
    tiers = _tiers(composed, preflight_wall_nanoseconds=1_000_000_000)
    assert tiers[0].population_wall_seconds == 8
    assert tiers[0].complete_dag_wall_seconds == 8 \
        + composed_critical_path_seconds(dict(composed.stage_walls_seconds))
    assert tiers[1].complete_dag_wall_seconds \
        > tiers[0].complete_dag_wall_seconds * 2
    assert [tier.exact_source_supply for tier in tiers] == [True, False, False]


def test_projected_label_cpu_uses_measured_stage_cpu_not_wall_times_sixteen():
    fixture = _preflight().accepted_fixtures[0]
    selected = {stage: _arm_from_raw(
        stage, variants[0], RawMeasurementV2(
            elapsed_ns=1_000_000_000, process_cpu_ns=14_400_000_000,
            peak_rss_bytes=1_000_000, task_count=1,
            sample_utilization_ppm=(900_000,),
            byte_identity_sha256=fixture.fixture_sha256),
        fixture.fixture_sha256, 1,
        measured_unit_count=(128 if stage == "continuation-mechanics"
                             else 32 if stage in ("state-successor",
                                                   "reconstruction") else 1))
        for stage, variants in ARM_GRIDS.items()}
    cpu_seconds = {name: 1 for name in COMPOSED_STAGE_NAMES}
    cpu_seconds.update({"label-p0": 2, "label-fit": 3,
                        "label-precision-select": 1, "label-audit": 4})
    dag = RepresentativeDAGV2(
        10, 10, 10, 10, 10, 10, 10, 1, admissible=True,
        stage_walls_seconds=tuple((name, 10) for name in COMPOSED_STAGE_NAMES),
        stage_wall_nanoseconds=tuple(
            (name, 10_000_000_000) for name in COMPOSED_STAGE_NAMES),
        stage_source_unit_counts=tuple((name, 32) for name in COMPOSED_STAGE_NAMES),
        stage_process_cpu_nanoseconds=tuple(
            (name, value * 1_000_000_000)
            for name, value in cpu_seconds.items()),
        member_workers=1, torch_threads=1, inference_batch=32,
        reconstruction_workers=1,
        progress_recovery={name: True for name in _RECOVERY_CAPABILITY_NAMES})
    composed = _composed_projection(selected, 32, 10**12, dag)
    tiers = _tiers(composed, preflight_wall_nanoseconds=1_000_000_000)
    assert dict(composed.measured_stage_cpu_seconds)["label-p0"] == 2
    assert dict(composed.stage_cpu_seconds)["label-p0"] == 6
    assert tiers[0].label_cpu_seconds == 22
    assert tiers[0].label_cpu_seconds != tiers[0].label_wall_seconds * 16


def test_underfilled_parallel_label_projection_uses_cpu_not_deal_linear_wall():
    fixture = _preflight().accepted_fixtures[0]
    selected = {stage: _arm_from_raw(
        stage, variants[0], RawMeasurementV2(
            elapsed_ns=1_000_000_000,
            process_cpu_ns=14_400_000_000,
            peak_rss_bytes=1_000_000, task_count=1,
            sample_utilization_ppm=(900_000,),
            byte_identity_sha256=fixture.fixture_sha256),
        fixture.fixture_sha256, 1,
        measured_unit_count=(128 if stage == "continuation-mechanics"
                             else 32 if stage in ("state-successor",
                                                   "reconstruction") else 1))
        for stage, variants in ARM_GRIDS.items()}
    source_units = {name: 32 for name in COMPOSED_STAGE_NAMES}
    source_units["label-fit"] = 2
    stage_cpu_ns = {name: 1_000_000_000 for name in COMPOSED_STAGE_NAMES}
    # The two representative deals occupied two aggregate cores for 100 s.
    # D256's 88 deals are 44x the CPU work, not 44x an underfilled makespan.
    stage_cpu_ns["label-fit"] = 200_000_000_000
    dag = RepresentativeDAGV2(
        100, 100, 100, 100, 100, 100, 100, 1, admissible=True,
        stage_walls_seconds=tuple(
            (name, 100) for name in COMPOSED_STAGE_NAMES),
        stage_wall_nanoseconds=tuple(
            (name, 100_000_000_000) for name in COMPOSED_STAGE_NAMES),
        stage_source_unit_counts=tuple(source_units.items()),
        stage_process_cpu_nanoseconds=tuple(stage_cpu_ns.items()),
        member_workers=1, continuation_workers=1,
        torch_threads=1, inference_batch=32,
        reconstruction_workers=1,
        progress_recovery={name: True for name in _RECOVERY_CAPABILITY_NAMES})
    composed = _composed_projection(selected, 32, 10**12, dag)
    label_fit_wall = dict(composed.stage_walls_seconds)["label-fit"]
    assert label_fit_wall == 612
    assert label_fit_wall != 100 * 88 // 2


def test_projected_label_wall_keeps_representative_floor_when_cpu_is_lower():
    fixture = _preflight().accepted_fixtures[0]
    selected = {stage: _arm_from_raw(
        stage, variants[0], RawMeasurementV2(
            elapsed_ns=1_000_000_000,
            process_cpu_ns=14_400_000_000,
            peak_rss_bytes=1_000_000, task_count=1,
            sample_utilization_ppm=(900_000,),
            byte_identity_sha256=fixture.fixture_sha256),
        fixture.fixture_sha256, 1,
        measured_unit_count=(128 if stage == "continuation-mechanics"
                             else 32 if stage in ("state-successor",
                                                   "reconstruction") else 1))
        for stage, variants in ARM_GRIDS.items()}
    source_units = {name: 32 for name in COMPOSED_STAGE_NAMES}
    source_units["label-fit"] = 2
    dag = RepresentativeDAGV2(
        100, 100, 100, 100, 100, 100, 100, 1, admissible=True,
        stage_walls_seconds=tuple(
            (name, 100) for name in COMPOSED_STAGE_NAMES),
        stage_wall_nanoseconds=tuple(
            (name, 100_000_000_000) for name in COMPOSED_STAGE_NAMES),
        stage_source_unit_counts=tuple(source_units.items()),
        stage_process_cpu_nanoseconds=tuple(
            (name, 1_000_000_000) for name in COMPOSED_STAGE_NAMES),
        member_workers=1, continuation_workers=1,
        torch_threads=1, inference_batch=32,
        reconstruction_workers=1,
        progress_recovery={name: True for name in _RECOVERY_CAPABILITY_NAMES})

    composed = _composed_projection(selected, 32, 10**12, dag)
    # CPU scaling predicts only a few seconds for the 88 projected units;
    # the exact representative 100-second wall remains the floor.
    assert dict(composed.stage_walls_seconds)["label-fit"] == 100


def test_progress_event_uses_measured_interval_and_monotonic_headroom():
    started_ns = 10_000_000_000
    events = []
    for elapsed_ns in (3_000_000_000, 7_000_000_000):
        _progress_event(
            "state-successor", 1, 2, 1, started_ns, 1, 500_000,
            events.append, now_ns=started_ns + elapsed_ns)

    assert [event["elapsed_seconds"] for event in events] == [3, 7]
    assert [event["headroom_seconds"] for event in events] == [
        runner.MAX_COMMAND_WALL_SECONDS - 3,
        runner.MAX_COMMAND_WALL_SECONDS - 7,
    ]
    assert events[1]["headroom_seconds"] < events[0]["headroom_seconds"]


def test_progress_event_refuses_exact_command_cap_expiry():
    events = []
    started_ns = 10_000_000_000
    with pytest.raises(CapacityRunnerError, match="wall cap expired"):
        _progress_event(
            "state-successor", 1, 2, 1, started_ns, 1, 500_000,
            events.append,
            now_ns=started_ns + runner.MAX_COMMAND_WALL_SECONDS * 1_000_000_000)
    assert events == []


def test_build_receipt_cannot_promote_false_measured_progress_probe():
    preflight = _preflight()
    fixture = preflight.accepted_fixtures[0]
    capabilities = {name: True for name in _RECOVERY_CAPABILITY_NAMES}
    capabilities["reports_stage_counts"] = False
    dag = RepresentativeDAGV2(
        1, 1, 1, 1, 1, 1, 1, 1, admissible=True,
        stage_walls_seconds=tuple((name, 1) for name in COMPOSED_STAGE_NAMES),
        stage_wall_nanoseconds=tuple(
            (name, 1_000_000_000) for name in COMPOSED_STAGE_NAMES),
        stage_source_unit_counts=tuple((name, 32) for name in COMPOSED_STAGE_NAMES),
        stage_process_cpu_nanoseconds=tuple(
            (name, 1_000_000_000) for name in COMPOSED_STAGE_NAMES),
        member_workers=1, continuation_workers=1,
        torch_threads=1, inference_batch=32,
        reconstruction_workers=1,
        progress_recovery=capabilities)
    dag = __import__("dataclasses").replace(
        dag, provenance_token=_FULL_DAG_PROVENANCE)
    dag = __import__("dataclasses").replace(dag,
        attestation_sha256=_dag_attestation(dag))
    with pytest.raises(FullDAGCapacityDependencyBlocked, match="progress"):
        build_receipt_v2(
            _selected_arms(fixture),
            host=HostTelemetryV2(16, free_disk_bytes=10**12),
            preflight=preflight, source_sha256="a" * 64,
            runtime_sha256="b" * 64,
            representative_dag=dag,
            _provenance=_PRODUCTION_PROVENANCE)


def test_build_receipt_cannot_hardcode_all_core_pass_over_full_dag_counters():
    preflight = _preflight()
    fixture = preflight.accepted_fixtures[0]
    dag = RepresentativeDAGV2(
        1, 1, 1, 1, 1, 1, 1, 1, admissible=True,
        stage_walls_seconds=tuple(
            (name, 1) for name in COMPOSED_STAGE_NAMES),
        stage_wall_nanoseconds=tuple(
            (name, 1_000_000_000) for name in COMPOSED_STAGE_NAMES),
        stage_source_unit_counts=tuple(
            (name, 32) for name in COMPOSED_STAGE_NAMES),
        stage_process_cpu_nanoseconds=tuple(
            (name, 1_000_000_000) for name in COMPOSED_STAGE_NAMES),
        member_workers=1, continuation_workers=1, torch_threads=1,
        inference_batch=32, reconstruction_workers=1,
        progress_recovery={name: True for name in _RECOVERY_CAPABILITY_NAMES},
        provenance_token=_FULL_DAG_PROVENANCE)
    dag = dataclasses.replace(dag, attestation_sha256=_dag_attestation(dag))
    with pytest.raises(CapacityRunnerError, match="all-core gate did not pass"):
        build_receipt_v2(
            _selected_arms(fixture),
            host=HostTelemetryV2(16, free_disk_bytes=10**12),
            preflight=preflight, source_sha256="a" * 64,
            runtime_sha256="b" * 64, representative_dag=dag,
            _provenance=_PRODUCTION_PROVENANCE)


def test_build_receipt_surfaces_exact_rejected_projection(monkeypatch):
    preflight = _preflight()
    fixture = preflight.accepted_fixtures[0]
    arms = _selected_arms(fixture)
    selected = runner._select_arms(arms)
    dag = RepresentativeDAGV2(
        1, 1, 1, 1, 1, 1, 1, 1, admissible=True,
        stage_walls_seconds=tuple(
            (name, 1) for name in COMPOSED_STAGE_NAMES),
        stage_wall_nanoseconds=tuple(
            (name, 1_000_000_000) for name in COMPOSED_STAGE_NAMES),
        stage_source_unit_counts=tuple(
            (name, 32) for name in COMPOSED_STAGE_NAMES),
        stage_process_cpu_nanoseconds=tuple(
            (name, 14_000_000_000) for name in COMPOSED_STAGE_NAMES),
        member_workers=selected["member-concurrency"].variant,
        continuation_workers=selected["continuation-mechanics"].variant,
        torch_threads=1,
        inference_batch=selected["inference-batch"].variant,
        reconstruction_workers=selected["reconstruction"].variant,
        progress_recovery={name: True for name in _RECOVERY_CAPABILITY_NAMES},
        provenance_token=_FULL_DAG_PROVENANCE)
    dag = dataclasses.replace(dag, attestation_sha256=_dag_attestation(dag))

    # Prove the fixture itself reaches and passes the real receipt wiring.
    receipt = build_receipt_v2(
        arms, host=HostTelemetryV2(16, free_disk_bytes=10**12),
        preflight=preflight, source_sha256="a" * 64,
        runtime_sha256="b" * 64, representative_dag=dag,
        _provenance=_PRODUCTION_PROVENANCE)
    assert receipt.composed.composed_wall_seconds > 0

    original = runner._composed_projection

    def over_cap(selected_arms, fixture_count, free_disk_bytes,
                 representative_dag=None, **kwargs):
        value = original(
            selected_arms, fixture_count, free_disk_bytes,
            representative_dag, **kwargs)
        if representative_dag is None:
            return value
        walls = dict(value.stage_walls_seconds)
        walls["label-p0"] = 100_000
        return dataclasses.replace(
            value, stage_walls_seconds=tuple(walls.items()),
            composed_wall_seconds=composed_critical_path_seconds(walls))

    monkeypatch.setattr(runner, "_composed_projection", over_cap)
    with pytest.raises(CapacityRunnerError,
                       match="composed projection cap drift") as caught:
        build_receipt_v2(
            arms, host=HostTelemetryV2(16, free_disk_bytes=10**12),
            preflight=preflight, source_sha256="a" * 64,
            runtime_sha256="b" * 64, representative_dag=dag,
            _provenance=_PRODUCTION_PROVENANCE)
    assert caught.value.stage == "full-dag"
    assert caught.value.reason_code == "composed-projection-cap-drift"
    diagnostic = caught.value.projection_diagnostic
    assert diagnostic is not None
    assert dict(diagnostic.stage_walls_seconds)["label-p0"] == 100_000
    assert "complete-dag-wall" in diagnostic.violations


def test_all_tiers_account_for_each_label_bucket_once():
    from shengji.rl.world_afterstate_v2_protocol import TIER_SPECS
    for spec in TIER_SPECS:
        units = _scientific_stage_units(spec)
        labels = sum(units[name] for name in (
            "label-p0", "label-fit", "label-precision-select", "label-audit"))
        assert labels == spec.total
        assert units["label-p0"] == 96
        assert units["label-fit"] == spec.fit - 96 + spec.select // 2
        assert units["label-precision-select"] == spec.select // 2
        assert units["label-audit"] == spec.audit


def test_production_refuses_unimplemented_full_dag_dependency():
    preflight = _preflight()
    fixture = preflight.accepted_fixtures[0]
    backend = _backend(fixture)
    with pytest.raises(CapacityRunnerError, match="production capacity refuses"):
        measure_capacity_v2(preflight=preflight, backend=backend,
                            host=HostTelemetryV2(16))
    assert FullDAGCapacityDependencyBlocked.dependency


def test_failure_receipt_publishes_once_at_distinct_sibling_path(tmp_path):
    success = tmp_path / "capacity.json"
    failure_path = tmp_path / "capacity-failure.json"
    source, input_sha = "1" * 64, "2" * 64
    runtime_sha = "3" * 64
    namespace = hashlib.sha256(canonical_json_bytes({
        "source_sha256": source, "input_sha256": input_sha,
        "runtime_sha256": runtime_sha})).hexdigest()
    failure = CapacityFailureReceiptV2(
        stage="runner", reason="capacity-runner-refused", elapsed_seconds=1,
        source_sha256=source, input_sha256=input_sha,
        runtime_sha256=runtime_sha,
        namespace_sha256=namespace,
        detail_sha256=hashlib.sha256(canonical_json_bytes({
            "message": "runner failure", "assessments": [],
            "projection_diagnostic": None})).hexdigest(),
        detail_message="runner failure")
    publish_capacity_failure_receipt_v2(failure_path, failure)
    assert not success.exists()
    assert reopen_capacity_failure_receipt_v2(
        json.loads(failure_path.read_text())) == failure
    with pytest.raises(CapacityRunnerError, match="occupied"):
        publish_capacity_failure_receipt_v2(failure_path, failure)

    target = tmp_path / "real"
    target.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(target, target_is_directory=True)
    with pytest.raises(CapacityRunnerError, match="aliased"):
        publish_capacity_failure_receipt_v2(linked / "failure.json", failure)
