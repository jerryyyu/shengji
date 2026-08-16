"""Closed selection and adversarial gates for V2 device qualification."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.belief_v2_device_qualification import (
    BeliefV2DeviceQualificationError,
    V2DeviceQualificationArmV1,
    build_qualification_plan,
    derive_qualification_result,
    qualification_protocol_sha256,
    reopen_qualification_plan,
    reopen_qualification_result,
    validate_qualification_plan,
    validate_qualification_result,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _schedule(count: int = 40):
    return tuple(tuple(_sha(f"decision-{batch}-{index}")
                       for index in range(2 + batch % 3))
                 for batch in range(count))


def _plan():
    rows = _schedule()
    return build_qualification_plan(
        execution_git="a" * 40,
        candidate_device="mps",
        batch_decision_keys=rows,
        batch_active_label_counts=tuple(
            100 + index for index in range(len(rows))),
        host_memory_cap_bytes=16 * 1024**3,
        device_memory_cap_bytes=8 * 1024**3,
    )


def _arms(candidate_wall: int = 80, cpu_wall: int = 100):
    plan = _plan()
    rows = []
    for index, (device, warmup, pair_index) in enumerate(plan.arm_order):
        checkpoint = tuple(_sha(f"{device}-checkpoint-{member}")
                           for member in range(8))
        losses = tuple(10_000 + member + (0 if device == "cpu" else 100)
                       for member in range(8))
        receipts = tuple(_sha(f"{device}-receipt-{member}")
                         for member in range(8))
        rows.append(V2DeviceQualificationArmV1(
            arm_index=index, device=device, warmup=warmup,
            pair_index=pair_index, plan_sha256=plan.sha256(),
            batch_population_sha256=plan.selected_population_sha256,
            batch_schedule_sha256=plan.selected_schedule_sha256,
            decision_count=plan.decision_count,
            active_label_count=plan.active_label_count,
            member_checkpoint_sha256s=checkpoint,
            member_loss_nanonats=losses,
            member_epoch_receipt_sha256s=receipts,
            wall_nanoseconds=(50 if warmup else (
                cpu_wall if device == "cpu" else candidate_wall)),
            peak_host_memory_bytes=1024,
            peak_device_memory_bytes=0 if device == "cpu" else 2048,
            actual_device=device,
        ))
    return plan, tuple(rows)


def _cpu_only_arms(cpu_wall: int = 100):
    rows = _schedule()
    plan = build_qualification_plan(
        execution_git="a" * 40, candidate_device="cpu",
        batch_decision_keys=rows,
        batch_active_label_counts=tuple(
            100 + index for index in range(len(rows))),
        host_memory_cap_bytes=16 * 1024**3,
        device_memory_cap_bytes=0)
    checkpoint = tuple(_sha(f"cpu-checkpoint-{member}")
                       for member in range(8))
    losses = tuple(10_000 + member for member in range(8))
    receipts = tuple(_sha(f"cpu-receipt-{member}")
                     for member in range(8))
    arms = tuple(V2DeviceQualificationArmV1(
        arm_index=index, device=device, warmup=warmup,
        pair_index=pair_index, plan_sha256=plan.sha256(),
        batch_population_sha256=plan.selected_population_sha256,
        batch_schedule_sha256=plan.selected_schedule_sha256,
        decision_count=plan.decision_count,
        active_label_count=plan.active_label_count,
        member_checkpoint_sha256s=checkpoint,
        member_loss_nanonats=losses,
        member_epoch_receipt_sha256s=receipts,
        wall_nanoseconds=50 if warmup else cpu_wall,
        peak_host_memory_bytes=1024, peak_device_memory_bytes=0,
        actual_device="cpu")
                 for index, (device, warmup, pair_index)
                 in enumerate(plan.arm_order))
    return plan, arms


def test_plan_is_digest_selected_closed_and_authorizes_nothing():
    plan = _plan()
    validate_qualification_plan(plan)
    assert len(plan.selected_batch_indices) == 32
    assert plan.selected_batch_indices == tuple(
        sorted(plan.selected_batch_indices))
    payload = plan.to_dict()
    assert payload["warmup_uses_same_batch_population"] is True
    assert payload["training_authorized"] is False
    assert payload["test_open_authorized"] is False
    assert payload["strength_claim_authorized"] is False

    rows = _schedule()
    changed = build_qualification_plan(
        execution_git="a" * 40, candidate_device="mps",
        batch_decision_keys=tuple(reversed(rows)),
        batch_active_label_counts=tuple(
            reversed(tuple(100 + index for index in range(len(rows))))),
        host_memory_cap_bytes=16 * 1024**3,
        device_memory_cap_bytes=8 * 1024**3)
    assert changed.full_schedule_sha256 != plan.full_schedule_sha256
    assert changed.sha256() != plan.sha256()
    assert len(qualification_protocol_sha256("mps")) == 64
    assert qualification_protocol_sha256("mps") \
        != qualification_protocol_sha256("cuda:0")
    assert qualification_protocol_sha256("cpu") \
        != qualification_protocol_sha256("mps")


def test_protocol_hash_binds_cpu_member_worker_topology(monkeypatch):
    expected = qualification_protocol_sha256("cpu")
    monkeypatch.setattr(
        "shengji.rl.belief_v2_device_qualification.CPU_MEMBER_WORKERS", 1)
    assert qualification_protocol_sha256("cpu") != expected


def test_three_paired_positive_20_percent_runs_retain_accelerator():
    plan, arms = _arms(candidate_wall=80, cpu_wall=100)
    result = derive_qualification_result(plan, arms)
    assert result.accelerator_retained is True
    assert result.selected_device == "mps"
    assert result.aggregate_cpu_wall_nanoseconds == 300
    assert result.aggregate_candidate_wall_nanoseconds == 240
    assert result.wall_reduction_ppb == 200_000_000
    assert result.canonical_bytes(plan).endswith(b"\n")
    assert result.to_dict()["deployment_authorized"] is False


@pytest.mark.parametrize(("candidate_wall", "retained"), [
    (85, True),
    (86, False),
])
def test_exact_fifteen_percent_boundary(candidate_wall, retained):
    plan, arms = _arms(candidate_wall=candidate_wall, cpu_wall=100)
    result = derive_qualification_result(plan, arms)
    assert result.accelerator_retained is retained
    assert result.selected_device == ("mps" if retained else "cpu")


def test_every_pair_must_be_positive_even_if_aggregate_is_fast():
    plan, arms = _arms(candidate_wall=40, cpu_wall=100)
    measured_candidate = [index for index, arm in enumerate(arms)
                          if not arm.warmup and arm.device == "mps"]
    arms = list(arms)
    arms[measured_candidate[0]] = replace(
        arms[measured_candidate[0]], wall_nanoseconds=101)
    result = derive_qualification_result(plan, tuple(arms))
    assert result.accelerator_retained is False
    assert result.selected_device == "cpu"


def test_checkpoint_nondeterminism_memory_fallback_and_result_rewrite_refuse():
    plan, arms = _arms()
    candidate = [index for index, arm in enumerate(arms)
                 if not arm.warmup and arm.device == "mps"]

    mutated = list(arms)
    mutated[candidate[-1]] = replace(
        mutated[candidate[-1]],
        member_checkpoint_sha256s=("f" * 64,)
        + mutated[candidate[-1]].member_checkpoint_sha256s[1:])
    with pytest.raises(BeliefV2DeviceQualificationError,
                       match="determinism"):
        derive_qualification_result(plan, tuple(mutated))

    mutated = list(arms)
    mutated[candidate[-1]] = replace(
        mutated[candidate[-1]],
        member_epoch_receipt_sha256s=("e" * 64,)
        + mutated[candidate[-1]].member_epoch_receipt_sha256s[1:])
    with pytest.raises(BeliefV2DeviceQualificationError,
                       match="determinism"):
        derive_qualification_result(plan, tuple(mutated))

    mutated = list(arms)
    mutated[candidate[0]] = replace(
        mutated[candidate[0]],
        peak_device_memory_bytes=plan.device_memory_cap_bytes + 1)
    with pytest.raises(BeliefV2DeviceQualificationError, match="arm drift"):
        derive_qualification_result(plan, tuple(mutated))

    mutated = list(arms)
    mutated[candidate[0]] = replace(
        mutated[candidate[0]], fallback_used=True)
    with pytest.raises(BeliefV2DeviceQualificationError, match="arm drift"):
        derive_qualification_result(plan, tuple(mutated))

    result = derive_qualification_result(plan, arms)
    with pytest.raises(BeliefV2DeviceQualificationError,
                       match="derivation"):
        validate_qualification_result(
            plan, replace(result, selected_device="cpu"))


def test_plan_refuses_duplicate_decisions_and_accepts_cpu_candidate():
    rows = list(_schedule())
    rows[1] = rows[0]
    with pytest.raises(BeliefV2DeviceQualificationError,
                       match="schedule"):
        build_qualification_plan(
            execution_git="a" * 40, candidate_device="mps",
            batch_decision_keys=tuple(rows),
            batch_active_label_counts=tuple(100 for _ in rows),
            host_memory_cap_bytes=1024,
            device_memory_cap_bytes=1024)
    cpu = build_qualification_plan(
        execution_git="a" * 40, candidate_device="cpu",
        batch_decision_keys=_schedule(),
        batch_active_label_counts=tuple(100 for _ in _schedule()),
        host_memory_cap_bytes=1024,
        device_memory_cap_bytes=1)
    assert cpu.candidate_device == "cpu"


def test_cpu_only_plan_runs_three_deterministic_arms_and_selects_cpu():
    plan, arms = _cpu_only_arms()
    assert plan.to_dict()["cpu_only_no_accelerator_candidate"] is True
    assert plan.to_dict()["minimum_wall_reduction_percent"] == 0
    assert len(plan.arm_order) == 4
    result = derive_qualification_result(plan, arms)
    assert result.selected_device == "cpu"
    assert result.accelerator_retained is False
    assert result.aggregate_cpu_wall_nanoseconds == 300
    assert result.aggregate_candidate_wall_nanoseconds == 0
    assert result.wall_reduction_ppb == 0
    assert reopen_qualification_plan(plan.canonical_bytes()) == plan
    assert reopen_qualification_result(
        plan, result.canonical_bytes(plan)) == result

    mutated = list(arms)
    mutated[-1] = replace(
        mutated[-1], member_checkpoint_sha256s=("f" * 64,)
        + mutated[-1].member_checkpoint_sha256s[1:])
    with pytest.raises(BeliefV2DeviceQualificationError,
                       match="CPU determinism"):
        derive_qualification_result(plan, tuple(mutated))


def test_canonical_result_has_closed_authority_population():
    plan, arms = _arms()
    result = derive_qualification_result(plan, arms)
    payload = __import__("json").loads(result.canonical_bytes(plan))
    assert set(payload) == {
        "schema", "plan_sha256", "arms", "selected_device",
        "accelerator_retained", "aggregate_cpu_wall_nanoseconds",
        "aggregate_candidate_wall_nanoseconds", "wall_reduction_ppb",
        "training_authorized", "test_open_authorized",
        "strength_claim_authorized", "deployment_authorized",
    }
    assert canonical_json_bytes(payload) == result.canonical_bytes(plan)
    assert reopen_qualification_plan(plan.canonical_bytes()) == plan
    assert reopen_qualification_result(
        plan, result.canonical_bytes(plan)) == result
