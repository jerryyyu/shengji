from __future__ import annotations

import json
import hashlib
from pathlib import Path
import threading
from concurrent.futures import Future

import pytest

from shengji.rl import world_afterstate_v2_population_controller as controller
from shengji.rl import world_afterstate_v2_execution as execution
from shengji.rl import world_afterstate_v2_source_driver as source_driver
from shengji.rl.world_afterstate_v2_population_artifacts import (
    PopulationMaterialShardV2,
)
from shengji.rl.world_afterstate_v2_population import (
    PopulationCandidateV2, PopulationMaterialV2,
)
from shengji.rl.world_afterstate_v2_protocol import (
    StateCandidateV2, TIER_SPECS, attempted_deal_identity,
    build_population_slot_ledger,
)


SLOTS = build_population_slot_ledger(TIER_SPECS[0])


class _State:
    def __init__(self, slot, deal):
        self.slot_sha256 = slot.slot_sha256
        self.deal_sha256 = deal
        self.source = slot.source
        self.split = slot.split
        self.state_sha256 = slot.slot_sha256
        self.phase = slot.phase or "early"
        self.position = slot.position or "lead"
        self.role = slot.role or "attacker"
        self.trump_rank = slot.trump_rank
        self.trump_mode = slot.trump_mode
        self.select_subfold = slot.select_subfold
        self.mechanics_surfaces = (() if slot.mechanics_surface is None
                                   else (slot.mechanics_surface,))


class _Material:
    def __init__(self, slot, deal):
        self.slot_sha256 = slot.slot_sha256
        self.deal_sha256 = deal
        self.state = _State(slot, deal)
        self.state_sha256 = slot.slot_sha256
        self.candidate_set_sha256 = "b" * 64

    def validate(self):
        return None


class _Attempt:
    def __init__(self, identity, slot, accepted, material=None, reason=None):
        self.attempted_deal_identity = {
            key: identity[key] for key in (
                "schema", "population_namespace_sha256", "slot_sha256",
                "attempt_index", "deal_sha256")}
        self.deal_sha256 = identity["deal_sha256"]
        self.slot_sha256 = slot.slot_sha256
        self.attempted = True
        self.accepted = accepted
        self.rejection_reason = reason
        self.material = material
        self.decision_count = 1

    def validate(self):
        return None


def _shard(slot, deal):
    digest = ("a" * 64)
    return PopulationMaterialShardV2(
        relative_path=f"population/materials/state-{slot.slot_sha256}.json",
        tier="D256", split=slot.split, source=slot.source, ordinal=slot.ordinal,
        deal_sha256=deal, slot_sha256=slot.slot_sha256,
        state_sha256=slot.slot_sha256, candidate_set_sha256="b" * 64,
        byte_count=1, sha256=digest, material_sha256=digest)


def _typed_material(slot, deal, index):
    cell = slot.cell or ("early", "lead", "attacker")
    state = StateCandidateV2(
        deal_sha256=deal, slot_sha256=slot.slot_sha256,
        state_sha256=hashlib.sha256(f"state-{index}".encode()).hexdigest(),
        source=slot.source, split=slot.split,
        phase=cell[0], position=cell[1], role=cell[2],
        trump_rank=slot.trump_rank, trump_mode=slot.trump_mode,
        select_subfold=slot.select_subfold,
        mechanics_surfaces=(() if slot.mechanics_surface is None
                            else (slot.mechanics_surface,)),
        legal_candidate_count=2)
    candidates = tuple(PopulationCandidateV2(
        candidate_index=offset,
        action_sha256=hashlib.sha256(
            f"action-{index}-{offset}".encode()).hexdigest(),
        audit_sha256=hashlib.sha256(bytes((97 + offset,))).hexdigest(),
        successor_sha256=hashlib.sha256(
            f"successor-{index}-{offset}".encode()).hexdigest(),
        origin="production-ballot", protected_incumbent=offset == 0)
                       for offset in range(2))
    return PopulationMaterialV2(
        state=state,
        candidate_set_sha256=hashlib.sha256(
            f"candidate-set-{index}".encode()).hexdigest(),
        candidates=candidates, audit_raws=(b"a", b"b"),
        prestate={"fixture": index})


@pytest.fixture
def fast_primitives(monkeypatch):
    monkeypatch.setattr(controller, "PopulationAttemptResultV2", _Attempt)
    encoded_materials = {}

    def encode(material):
        raw = ("material:" + material.slot_sha256).encode("ascii")
        encoded_materials[raw] = material
        return raw

    monkeypatch.setattr(controller, "population_material_bytes", encode)
    monkeypatch.setattr(controller, "reopen_population_material",
                        lambda raw: encoded_materials[raw])
    monkeypatch.setattr(
        controller, "material_sha256",
        lambda material: hashlib.sha256(encode(material)).hexdigest())
    monkeypatch.setattr(controller, "_publish_or_verify_shard",
                        lambda *_args, **_kwargs: None)

    def publish(_root, material, **_kwargs):
        return _shard(next(s for s in SLOTS if s.slot_sha256 == material.slot_sha256),
                      material.deal_sha256)

    def verify(_root, record, slot):
        return _shard(slot, record["attempted_deal"]["deal_sha256"])

    monkeypatch.setattr(controller, "publish_population_material", publish)
    monkeypatch.setattr(controller, "_verify_record_shard", verify)
    monkeypatch.setattr(
        controller, "publish_population_manifest",
        lambda *_args, **_kwargs: {
            "manifest_sha256": "c" * 64, "population_sha256": "d" * 64})
    monkeypatch.setattr(
        controller, "reopen_population_manifest",
        lambda *_args, **_kwargs: tuple(object() for _ in range(256)))


def test_exact_ledger_and_invalid_admission_refuse(tmp_path):
    assert len(SLOTS) == 256
    with pytest.raises(controller.WorldAfterstateV2PopulationControllerError):
        controller.collect_population_v2(
            tmp_path, freeze_sha256="f" * 64,
            population_namespace_sha256="b" * 64,
            admission_sha256="bad", max_attempts_per_slot=1)


def test_population_worker_arm_32_is_frozen_and_33_is_not():
    assert controller.CONFIG_SCHEMA == "world-afterstate-v2-population-controller-config-v2"
    assert 32 in controller.WORKER_ARMS
    assert 33 not in controller.WORKER_ARMS


def test_controller_rejection_vocabulary_matches_source_driver_exactly():
    exported = {
        value for name, value in vars(source_driver).items()
        if name.startswith("REJECTION_") and type(value) is str
    }
    assert controller._REASONS == exported


def test_real_driver_uses_process_workers_and_reports_true_width(
        tmp_path, fast_primitives, monkeypatch):
    process_widths = []
    process_start_methods = []
    calls = []

    class ImmediateProcessPool:
        def __init__(self, *, max_workers, **_kwargs):
            process_widths.append(max_workers)
            process_start_methods.append(
                _kwargs["mp_context"].get_start_method())

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def submit(self, function, *args):
            future = Future()
            try:
                future.set_result(function(*args))
            except BaseException as exc:
                future.set_exception(exc)
            return future

    def real_driver(identity, slot):
        calls.append(slot.slot_sha256)
        return _Attempt(identity, slot, True,
                        _Material(slot, identity["deal_sha256"]))

    monkeypatch.setattr(controller, "ProcessPoolExecutor", ImmediateProcessPool)
    monkeypatch.setattr(controller, "drive_population_attempt_v2", real_driver)
    progress = []
    receipt = controller.collect_population_v2(
        tmp_path, freeze_sha256="f" * 64,
        population_namespace_sha256="b" * 64,
        admission_sha256="a" * 64, max_attempts_per_slot=1,
        workers=4, progress_callback=progress.append)

    assert process_widths == [4]
    assert process_start_methods == ["spawn"]
    assert len(calls) == receipt.accepted_slots == 256
    assert max(row["active_workers"] for row in progress) == 4


def test_injected_driver_stays_in_parent_process(
        tmp_path, fast_primitives, monkeypatch):
    class ForbiddenProcessPool:
        def __init__(self, **_kwargs):
            raise AssertionError("injected driver must not cross a process boundary")

    def driver(identity, slot):
        return _Attempt(identity, slot, True,
                        _Material(slot, identity["deal_sha256"]))

    monkeypatch.setattr(controller, "ProcessPoolExecutor", ForbiddenProcessPool)
    receipt = controller.collect_population_v2(
        tmp_path, freeze_sha256="f" * 64,
        population_namespace_sha256="b" * 64,
        admission_sha256="a" * 64, max_attempts_per_slot=1,
        workers=4, attempt_driver=driver)
    assert receipt.accepted_slots == 256


def test_process_width_does_not_change_population_bytes(
        tmp_path, fast_primitives, monkeypatch):
    class ImmediateProcessPool:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def submit(self, function, *args):
            future = Future()
            try:
                future.set_result(function(*args))
            except BaseException as exc:
                future.set_exception(exc)
            return future

    def real_driver(identity, slot):
        return _Attempt(identity, slot, True,
                        _Material(slot, identity["deal_sha256"]))

    monkeypatch.setattr(controller, "ProcessPoolExecutor", ImmediateProcessPool)
    monkeypatch.setattr(controller, "drive_population_attempt_v2", real_driver)
    roots = (tmp_path / "width-1", tmp_path / "width-4")
    receipts = []
    for root, workers in zip(roots, (1, 4), strict=True):
        receipts.append(controller.collect_population_v2(
            root, freeze_sha256="f" * 64,
            population_namespace_sha256="b" * 64,
            admission_sha256="a" * 64, max_attempts_per_slot=1,
            workers=workers))

    assert [row.payload() for row in receipts[0].slots] == [
        row.payload() for row in receipts[1].slots]
    assert receipts[0].population_sha256 == receipts[1].population_sha256
    assert receipts[0].manifest_sha256 == receipts[1].manifest_sha256


def test_cap_parallel_resume_and_score_free_receipt(tmp_path, fast_primitives):
    calls = {}

    def driver(identity, slot):
        key = slot.slot_sha256
        calls[key] = calls.get(key, 0) + 1
        if calls[key] == 1:
            return _Attempt(identity, slot, False, reason="no-eligible-state")
        return _Attempt(identity, slot, True,
                        _Material(slot, identity["deal_sha256"]))

    progress = []
    receipt = controller.collect_population_v2(
        tmp_path, freeze_sha256="f" * 64,
        population_namespace_sha256="b" * 64, admission_sha256="a" * 64,
        max_attempts_per_slot=2, workers=4, attempt_driver=driver,
        progress_callback=progress.append)
    assert receipt.attempts_total == 512
    assert all(row.attempt_count == 2 for row in receipt.slots)
    assert progress[-1]["completed_slots"] == 256
    assert progress[-1]["total_slots"] == 256
    encoded = json.dumps(receipt.payload(), sort_keys=True).lower()
    assert not any(token in encoded for token in (
        "label", "outcome", "terminal", "gameplay", "result", "score"))
    before = dict(calls)
    resumed = controller.reopen_population_collection_v2(
        tmp_path, freeze_sha256="f" * 64,
        population_namespace_sha256="b" * 64, admission_sha256="a" * 64)
    assert resumed.payload() == receipt.payload()
    assert calls == before
    with pytest.raises(controller.WorldAfterstateV2PopulationControllerError):
        controller.collect_population_v2(
            tmp_path, freeze_sha256="f" * 64,
            population_namespace_sha256="b" * 64, admission_sha256="a" * 64,
            max_attempts_per_slot=3, workers=4, attempt_driver=driver)


def test_expired_partial_run_reuses_shards_under_fresh_bounded_watchdog(
        tmp_path, fast_primitives, monkeypatch):
    clock = {"now": 100}
    calls = []
    positions = {slot.slot_sha256: index for index, slot in enumerate(SLOTS)}

    monkeypatch.setattr(controller.time, "time", lambda: clock["now"])

    def driver(identity, slot):
        position = positions[slot.slot_sha256]
        calls.append((position, identity["attempt_index"]))
        if position == 255 and identity["attempt_index"] == 0:
            clock["now"] = 102
            return _Attempt(
                identity, slot, False, reason="no-eligible-state")
        return _Attempt(identity, slot, True,
                        _Material(slot, identity["deal_sha256"]))

    with pytest.raises(
            controller.WorldAfterstateV2PopulationControllerError,
            match="population deadline expired before new work"):
        controller.collect_population_v2(
            tmp_path, freeze_sha256="f" * 64,
            population_namespace_sha256="b" * 64,
            admission_sha256="a" * 64, max_attempts_per_slot=2,
            workers=1, deadline_seconds=1, attempt_driver=driver)

    config_path = tmp_path / controller.CONTROLLER_DIRNAME / controller.CONFIG_NAME
    config_before = config_path.read_bytes()
    assert calls == [(ordinal, 0) for ordinal in range(256)]
    retained = controller._read_records(
        tmp_path, SLOTS, freeze="f" * 64, namespace="b" * 64,
        admission="a" * 64, cap=2)
    assert sum(bool(rows and rows[-1]["accepted"])
               for rows in retained.values()) == 255

    clock["now"] = 200
    receipt = controller.collect_population_v2(
        tmp_path, freeze_sha256="f" * 64,
        population_namespace_sha256="b" * 64,
        admission_sha256="a" * 64, max_attempts_per_slot=2,
        workers=1, deadline_seconds=1, attempt_driver=driver)

    assert config_path.read_bytes() == config_before
    assert calls == [
        *((ordinal, 0) for ordinal in range(256)),
        (255, 1),
    ]
    assert receipt.accepted_slots == 256
    assert receipt.attempts_total == 257
    assert all(row.attempt_count == 1 for row in receipt.slots[:-1])
    assert receipt.slots[-1].attempt_count == 2


def test_partial_d64_reopens_255_shards_after_failed_slot_and_next_start(
        tmp_path, monkeypatch):
    """The retained root's missing slot has prior failures plus one orphan start."""
    clock = {"now": 100}
    monkeypatch.setattr(controller.time, "time", lambda: clock["now"])
    # This fixture exercises the real artifact serialization/reopen boundary;
    # only the deep engine-audit validation that produced each material is
    # replaced by the already-tested typed population boundary.
    monkeypatch.setattr(PopulationMaterialV2, "validate", lambda self: None)
    positions = {slot.slot_sha256: index for index, slot in enumerate(SLOTS)}

    def driver(identity, slot):
        position = positions[slot.slot_sha256]
        if position == 255:
            clock["now"] = 102
            return source_driver.PopulationAttemptResultV2(
                attempted_deal_identity=controller._public_attempt(identity),
                deal_sha256=identity["deal_sha256"],
                slot_sha256=slot.slot_sha256, attempted=True, accepted=False,
                rejection_reason="no-eligible-state", material=None,
                decision_count=1)
        material = _typed_material(slot, identity["deal_sha256"], position)
        return source_driver.PopulationAttemptResultV2(
            attempted_deal_identity=controller._public_attempt(identity),
            deal_sha256=identity["deal_sha256"],
            slot_sha256=slot.slot_sha256, attempted=True, accepted=True,
            rejection_reason=None, material=material, decision_count=1)

    with pytest.raises(controller.WorldAfterstateV2PopulationControllerError,
                       match="deadline expired"):
        controller.collect_population_v2(
            tmp_path, freeze_sha256="f" * 64,
            population_namespace_sha256="b" * 64,
            admission_sha256="a" * 64, max_attempts_per_slot=4,
            workers=1, deadline_seconds=1, attempt_driver=driver)

    missing = SLOTS[255]
    # Model the controller stop window exactly: attempt 0 has a durable
    # rejection, and attempt 1 has a durable start but no result.
    controller._publish_started(
        tmp_path, freeze="f" * 64, namespace="b" * 64,
        admission="a" * 64, slot=missing, index=1)
    partial = controller.reopen_population_partial_coverage_v2(
        tmp_path, freeze_sha256="f" * 64,
        population_namespace_sha256="b" * 64,
        admission_sha256="a" * 64, max_attempts_per_slot=4)

    assert partial.accepted_slots == 255
    assert len(partial.selected_materials) == 64
    assert partial.missing_slots == (
        {**missing.payload(), "slot_sha256": missing.slot_sha256},)
    assert len(partial.orphan_started) == 1
    assert partial.orphan_started[0]["attempt_index"] == 1
    assert partial.orphan_started[0]["state"] \
        == "aborted-in-flight-without-result"
    assert not (tmp_path / "population" / "manifest.json").exists()
    assert not (tmp_path / controller.CONTROLLER_DIRNAME /
                controller.RECEIPT_NAME).exists()
    reopened = controller.reopen_population_partial_coverage_v2(
        tmp_path, freeze_sha256="f" * 64,
        population_namespace_sha256="b" * 64,
        admission_sha256="a" * 64, max_attempts_per_slot=4)
    assert reopened.payload() == partial.payload()


def test_real_accepted_material_shard_reopens_for_resume(tmp_path):
    slot = next(row for row in SLOTS
                if row.group == "natural-fit" and row.ordinal == 4)
    identity = attempted_deal_identity("a" * 64, slot, 0)
    result = source_driver.drive_population_attempt_v2(identity, slot)
    assert result.accepted and result.material is not None

    material = result.material
    raw = controller.population_material_bytes(material)
    shard = controller._expected_shard(tmp_path, material, slot, raw)
    assert controller.publish_population_material(
        tmp_path, material, tier="D256") == shard
    record = controller._record_payload(
        freeze="f" * 64, namespace="a" * 64, admission="b" * 64,
        slot=slot, attempt=identity, accepted=True, reason=None,
        decision_count=result.decision_count, shard=shard, material_raw=raw)

    assert controller._verify_record_shard(tmp_path, record, slot) == shard


def test_requested_trump_mode_unavailable_is_recorded_and_collection_continues(
        tmp_path, fast_primitives):
    calls = {}

    def driver(identity, slot):
        key = slot.slot_sha256
        calls[key] = calls.get(key, 0) + 1
        if calls[key] == 1:
            return _Attempt(
                identity, slot, False,
                reason="requested-trump-mode-unavailable")
        return _Attempt(identity, slot, True,
                        _Material(slot, identity["deal_sha256"]))

    receipt = controller.collect_population_v2(
        tmp_path, freeze_sha256="f" * 64,
        population_namespace_sha256="b" * 64, admission_sha256="a" * 64,
        max_attempts_per_slot=2, workers=4, attempt_driver=driver)

    assert receipt.accepted_slots == 256
    assert receipt.attempts_total == 512
    assert all(row.rejection_counts == (
        ("requested-trump-mode-unavailable", 1),) for row in receipt.slots)


def test_attempt_identity_binds_namespace_and_slot():
    slot = SLOTS[0]
    identity = attempted_deal_identity("b" * 64, slot, 0)
    assert identity["slot_sha256"] == slot.slot_sha256
    assert identity["population_namespace_sha256"] == "b" * 64


def test_wrong_full_stratum_and_heartbeat_schema_refuse():
    slot = SLOTS[0]
    material = _Material(slot, "c" * 64)
    material.state.role = "defender" if slot.role == "attacker" else "attacker"
    with pytest.raises(controller.WorldAfterstateV2PopulationControllerError):
        controller._validate_material_stratum(material, slot)
    events = []

    def supervisor_boundary(event):
        # This is the closed production contract that the old ``attempt``
        # top-level stage violated only after its first timed callback.
        assert event["stage"] in execution.STAGE_ORDER
        events.append(event)

    progress = controller._Progress(
        supervisor_boundary, 256, 0, 0, 1,
        int(__import__("time").time()) + 10)
    progress.attempt_started(slot, 3)

    class OneHeartbeat:
        calls = 0

        def wait(self, _interval):
            self.calls += 1
            return self.calls > 1

    progress.heartbeat_loop(
        OneHeartbeat(), slot, 3, 60,
        int(__import__("time").time()) + 10)
    event = events[-1]
    assert event["stage"] == "population"
    assert event["substage"] == f"attempt/slot-{slot.ordinal}-attempt-3"
    assert {"stage", "substage", "completed_slots", "total_slots",
            "active_workers", "cpu_utilization", "current_memory_bytes",
            "peak_memory_bytes", "deadline_headroom_seconds",
            "immutable_shards", "elapsed_seconds", "eta_seconds",
            "authority"} <= set(event)
    assert all(value is False for value in event["authority"].values())


def test_first_worker_failure_cancels_queued_slots(
        tmp_path, fast_primitives):
    calls = []

    def driver(_identity, slot):
        calls.append(slot.slot_sha256)
        if len(calls) == 2:
            # Give the collector deterministic time to observe the first
            # failed future and cancel the still-queued population.
            threading.Event().wait(0.2)
        raise RuntimeError("injected population worker failure")

    with pytest.raises(controller.WorldAfterstateV2PopulationControllerError):
        controller.collect_population_v2(
            tmp_path, freeze_sha256="f" * 64,
            population_namespace_sha256="b" * 64,
            admission_sha256="a" * 64, max_attempts_per_slot=1,
            workers=1, attempt_driver=driver)
    assert len(calls) <= 2


def test_persisted_acceptance_is_reused_after_publication_crash(
        tmp_path, fast_primitives, monkeypatch):
    slot = SLOTS[0]
    config = controller._config_payload(
        freeze="f" * 64, namespace="b" * 64, admission="a" * 64,
        slots=SLOTS, cap=1, workers=1, deadline_seconds=100,
        deadline_unix_seconds=__import__("time").time().__floor__() + 100,
        heartbeat_seconds=60)
    calls = []

    def driver(identity, target):
        calls.append(identity["attempt_index"])
        return _Attempt(identity, target, True,
                        _Material(target, identity["deal_sha256"]))

    def crash_once(*_args, **_kwargs):
        raise RuntimeError("publication crash window")

    monkeypatch.setattr(controller, "_publish_or_verify_shard", crash_once)
    with pytest.raises(controller.WorldAfterstateV2PopulationControllerError):
        controller._run_slot(
            tmp_path, slot, (), freeze="f" * 64, namespace="b" * 64,
            admission="a" * 64, cap=1, config=config,
            progress=controller._Progress(None, 256, 0, 0, 1), driver=driver)
    rows = controller._read_records(
        tmp_path, SLOTS, freeze="f" * 64, namespace="b" * 64,
        admission="a" * 64, cap=1)[slot.slot_sha256]
    assert len(rows) == 1 and rows[0]["accepted"] and calls == [0]
    monkeypatch.setattr(controller, "_publish_or_verify_shard",
                        lambda *_args, **_kwargs: None)
    resumed = controller._run_slot(
        tmp_path, slot, rows, freeze="f" * 64, namespace="b" * 64,
        admission="a" * 64, cap=1, config=config,
        progress=controller._Progress(None, 256, 1, 1, 1), driver=driver)
    assert resumed.records == tuple(rows)
    assert calls == [0]
