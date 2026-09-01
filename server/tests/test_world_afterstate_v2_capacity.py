import dataclasses
import hashlib

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v2_capacity import (
    ARM_GRIDS, AUTHORITY, CAPACITY_ARM_TO_PRODUCTION_STAGE,
    CAPACITY_STAGE_TO_PRODUCTION_STAGE,
    COMPOSED_DAG_EDGES, COMPOSED_STAGE_NAMES, PRODUCTION_STAGE_NAMES,
    MEMORY_LIMIT_BYTES, SCIENTIFIC_DAG_EDGES,
    TRAINING_RESOURCE_SERIALIZATION_EDGES, CapacityArmV2,
    CapacityCensusAssessmentV2,
    CapacityFailureReceiptV2, CapacityReceiptV2, ComposedProjectionV2,
    ProgressRecoveryV2,
    TierProjectionV2, WorldAfterstateV2CapacityError,
    PINNED_TORCH_THREADS, choose_capacity_tier_v2,
    composed_critical_path_seconds, projected_arm_wall_shares_ppm,
    derive_all_core_gate_passed, ARM_SCHEMA, SCHEMA, FAILURE_SCHEMA,
    arm_has_immediate_next_slower,
    validate_capacity_arm_census_v2,
    reopen_capacity_failure_receipt_v2,
)
from shengji.rl.world_afterstate_v2_capacity_runner import (
    CapacityRunnerError, reopen_capacity_receipt_v2,
)


def _sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _arms(*, memory=None, command_tasks=1, low_cpu=False, byte_suffix="same"):
    values = []
    for stage, variants in ARM_GRIDS.items():
        for variant in variants:
            wall = 100 + variant
            if variant == min(variants):
                wall = 10
            # Keep a subsecond witness while preserving ceil display seconds.
            wall_ns = wall * 1_000_000_000 - 1
            utilization = (800_000 if low_cpu and variant == min(variants)
                           else 900_000)
            busy_ns = wall_ns * 16 * utilization // 1_000_000
            values.append(CapacityArmV2(
                stage=stage, variant=variant, wall_seconds=wall,
                busy_core_seconds=(busy_ns + 999_999_999) // 1_000_000_000,
                mean_cpu_utilization_ppm=busy_ns * 1_000_000
                // (wall_ns * 16),
                p50_cpu_utilization_ppm=800_000 if low_cpu and variant == min(variants)
                else 900_000,
                p95_cpu_utilization_ppm=900_000,
                scaling_efficiency_ppm=900_000, queue_depth=0,
                wall_share_ppm=0,
                peak_memory_bytes=memory or 20 * 1024**3,
                swap_bytes=0, task_count=command_tasks,
                byte_identity_sha256=_sha(f"{stage}:{byte_suffix}"),
                cpu_bound=low_cpu, wall_ns=wall_ns, busy_core_ns=busy_ns,
                measured_unit_count=(128 if stage == "continuation-mechanics"
                                     else 32 if stage in ("state-successor",
                                                           "reconstruction")
                                     else 1)))
    return tuple(values)


def _composed(**changes):
    values = {name: 100 for name in COMPOSED_STAGE_NAMES}
    values.update(changes.pop("stage_walls_seconds", {}))
    body = dict(stage_walls_seconds=tuple(values.items()),
                composed_wall_seconds=composed_critical_path_seconds(values),
                peak_memory_bytes=20 * 1024**3,
                composed_artifact_bytes=75,
                free_disk_bytes_before=100,
                stage_unit_counts=tuple(
                    (name, 1, 1) for name in COMPOSED_STAGE_NAMES),
                measured_stage_walls_seconds=tuple(values.items()),
                stage_cpu_seconds=tuple(
                    (name, value * 14) for name, value in values.items()),
                measured_stage_cpu_seconds=tuple(
                    (name, value * 14) for name, value in values.items()),
                measured_stage_wall_nanoseconds=tuple(
                    (name, value * 1_000_000_000) for name, value in values.items()),
                measured_stage_cpu_nanoseconds=tuple(
                    (name, value * 1_000_000_000 * 14
                     ) for name, value in values.items()))
    body.update(changes)
    return ComposedProjectionV2(**body)


def _progress(**changes):
    body = dict(
        progress_interval_seconds=60, progress_interval_fraction_ppm=10_000,
        reports_stage_counts=True, reports_active_workers_and_cpu=True,
        reports_elapsed_eta_headroom=True,
        reports_current_peak_cgroup_memory=True,
        reports_immutable_shard_checkpoint_count=True,
        resumes_verified_shards_only=True, resume_same_admission=True,
        resume_cannot_regenerate_replace_select=True,
        checkpoints_each_common_epoch=True,
        deadline_truncation_keeps_complete_epoch=True,
        audit_requires_complete_upstream=True,
        audit_attempt_fsynced_before_open=True, one_audit_open=True,
        reconstruction_without_retraining=True,
        reconstruction_reuses_immutable_continuations=True)
    body.update(changes)
    return ProgressRecoveryV2(**body)


def test_typed_capacity_failure_reopens_and_is_not_a_success_receipt():
    from shengji.rl.world_afterstate_v2_capacity import (
        reopen_capacity_failure_receipt_v2)

    source, input_sha = "1" * 64, "2" * 64
    runtime = "3" * 64
    namespace = hashlib.sha256(canonical_json_bytes({
        "source_sha256": source, "input_sha256": input_sha,
        "runtime_sha256": runtime})).hexdigest()
    failure = CapacityFailureReceiptV2(
        stage="runner", reason="capacity-runner-refused", elapsed_seconds=4,
        source_sha256=source, input_sha256=input_sha,
        runtime_sha256=runtime,
        namespace_sha256=namespace,
        detail_sha256=hashlib.sha256(canonical_json_bytes({
            "message": "typed failure",
            "assessments": []})).hexdigest(),
        detail_message="typed failure")
    payload = failure.payload()
    assert payload["schema"] == FAILURE_SCHEMA
    assert reopen_capacity_failure_receipt_v2(payload) == failure
    assert payload["status"] == "failure"
    assert set(payload["authority"].values()) == {False}
    with pytest.raises(CapacityRunnerError):
        reopen_capacity_receipt_v2(payload)
    tampered = dict(payload, namespace_sha256="5" * 64)
    with pytest.raises(WorldAfterstateV2CapacityError):
        reopen_capacity_failure_receipt_v2(tampered)


def _receipt(**changes):
    tiers = tuple(TierProjectionV2(
        tier=name, exact_source_supply=True,
        label_wall_seconds=10_000, label_cpu_seconds=170_000,
        complete_dag_wall_seconds=20_000,
        peak_memory_bytes=20 * 1024**3,
        composed_artifact_bytes=75, free_disk_bytes_before=100)
                   for name in ("D256", "D512", "D1024"))
    body = dict(
        host_logical_cpus=16, command_wall_seconds=1,
        memory_limit_bytes=MEMORY_LIMIT_BYTES, swap_bytes=0, task_count=1,
        arms=_arms(), selected_arms=tuple(), composed=_composed(), tiers=tiers,
        progress_recovery=_progress(), source_sha256="a" * 64,
        runtime_sha256="b" * 64, model_parameter_count=1,
        candidate_distribution=((2, 1),), per_epoch_wall_seconds=1,
        peak_task_count=1)
    body.update(changes)
    if "selected_arms" not in changes:
        body["selected_arms"] = tuple(min(
            (arm for arm in body["arms"] if arm.stage == stage
             and arm.peak_memory_bytes * 100
             <= MEMORY_LIMIT_BYTES * 85),
            key=lambda arm: (arm.wall_ns, arm.variant))
            for stage in ARM_GRIDS)
    selected = {arm.stage: arm.variant for arm in body["selected_arms"]}
    body.setdefault("member_workers", selected["member-concurrency"])
    body.setdefault("continuation_workers", selected["continuation-mechanics"])
    body.setdefault("torch_threads", 1)
    body.setdefault("inference_batch", selected["inference-batch"])
    body.setdefault("reconstruction_workers", selected["reconstruction"])
    shares = projected_arm_wall_shares_ppm(
        dict(body["composed"].stage_walls_seconds))
    body["arms"] = tuple(dataclasses.replace(arm, wall_share_ppm=shares[arm.stage])
                          for arm in body["arms"])
    body["selected_arms"] = tuple(
        next(arm for arm in body["arms"] if arm.stage == selected_arm.stage
             and arm.variant == selected_arm.variant)
        for selected_arm in body["selected_arms"])
    body.setdefault("all_core_gate_passed", derive_all_core_gate_passed(
        body["arms"], dict(body["composed"].stage_walls_seconds),
        dict(body["composed"].measured_stage_wall_nanoseconds),
        dict(body["composed"].measured_stage_cpu_nanoseconds)))
    if "peak_task_count" not in changes:
        body["peak_task_count"] = max(
            arm.peak_task_count or arm.task_count for arm in body["arms"])
    if "task_count" not in changes:
        body["task_count"] = body["peak_task_count"]
    if "command_wall_seconds" not in changes:
        body["command_wall_seconds"] = (
            sum(arm.wall_seconds for arm in body["arms"])
            + sum(value for _, value in
                  body["composed"].measured_stage_walls_seconds))
    return CapacityReceiptV2(**body)


def test_exact_arm_grid_caps_and_fastest_byte_identical_selection():
    receipt = _receipt()
    receipt.validate()
    assert receipt.schema == SCHEMA
    assert "torch-threads-per-member" not in ARM_GRIDS
    assert len(receipt.arms) == 26
    assert len(receipt.arms) == sum(len(values) for values in ARM_GRIDS.values())
    assert receipt.sha256() == receipt.sha256()
    assert choose_capacity_tier_v2(receipt).name == "D1024"
    assert AUTHORITY and not any(AUTHORITY.values())


def test_exact_arm_nanoseconds_bind_display_and_mean_utilization():
    arm = _arms()[0]
    assert arm.schema == ARM_SCHEMA
    assert arm.wall_seconds == (arm.wall_ns + 999_999_999) // 1_000_000_000
    assert arm.busy_core_seconds == (
        arm.busy_core_ns + 999_999_999) // 1_000_000_000
    assert arm.mean_cpu_utilization_ppm == (
        arm.busy_core_ns * 1_000_000 // (arm.wall_ns * 16))
    with pytest.raises(WorldAfterstateV2CapacityError, match="binding"):
        dataclasses.replace(arm, wall_seconds=arm.wall_seconds + 1).validate()
    with pytest.raises((TypeError, WorldAfterstateV2CapacityError)):
        CapacityArmV2(**{key: value for key, value in arm.payload().items()
                         if key not in {"wall_ns", "busy_core_ns"}})


def test_v6_receipt_requires_complete_full_dag_exact_witnesses():
    composed = dataclasses.replace(
        _composed(), stage_unit_counts=(), measured_stage_walls_seconds=(),
        measured_stage_cpu_seconds=(), measured_stage_wall_nanoseconds=(),
        measured_stage_cpu_nanoseconds=())
    with pytest.raises(WorldAfterstateV2CapacityError, match="exact witness"):
        _receipt(composed=composed, all_core_gate_passed=True).validate()


def test_full_dag_display_seconds_bind_exact_wall_and_cpu_counters():
    composed = _composed()
    wall_rows = list(composed.measured_stage_walls_seconds)
    wall_rows[0] = (wall_rows[0][0], wall_rows[0][1] + 1)
    with pytest.raises(WorldAfterstateV2CapacityError,
                       match="wall display binding"):
        _receipt(composed=dataclasses.replace(
            composed, measured_stage_walls_seconds=tuple(wall_rows))).validate()
    cpu_rows = list(composed.measured_stage_cpu_seconds)
    cpu_rows[0] = (cpu_rows[0][0], cpu_rows[0][1] + 1)
    with pytest.raises(WorldAfterstateV2CapacityError,
                       match="CPU display binding"):
        _receipt(composed=dataclasses.replace(
            composed, measured_stage_cpu_seconds=tuple(cpu_rows))).validate()


def test_receipt_refuses_missing_reconstruction_layout():
    receipt = _receipt()
    with pytest.raises(WorldAfterstateV2CapacityError, match="layout"):
        __import__("dataclasses").replace(
            receipt, reconstruction_workers=0).validate()


@pytest.mark.parametrize("torch_threads", (2, 4))
def test_receipt_refuses_cross_width_torch_layout(torch_threads):
    with pytest.raises(WorldAfterstateV2CapacityError, match="resource layout"):
        _receipt(member_workers=1, torch_threads=torch_threads,
                 inference_batch=32).validate()


def test_old_capacity_wire_schema_is_refused():
    payload = _receipt().payload()
    payload["schema"] = "world-afterstate-v2-post-implementation-capacity-v2"
    with pytest.raises(CapacityRunnerError, match="reconstruction refused"):
        reopen_capacity_receipt_v2(payload)
    payload = _receipt().payload()
    payload["arms"][0]["schema"] = "world-afterstate-v2-capacity-arm-v1"
    with pytest.raises(CapacityRunnerError, match="reconstruction refused"):
        reopen_capacity_receipt_v2(payload)


@pytest.mark.parametrize("field,value", [
    ("command_wall_seconds", 7_201),
    ("memory_limit_bytes", MEMORY_LIMIT_BYTES - 1),
    ("swap_bytes", 1),
    ("task_count", 4_097),
])
def test_command_resource_caps_fail_closed(field, value):
    with pytest.raises(WorldAfterstateV2CapacityError, match="cap"):
        _receipt(**{field: value}).validate()


def test_arm_grid_missing_duplicate_and_slow_selection_refuse():
    arms = _arms()
    with pytest.raises(WorldAfterstateV2CapacityError, match="arm grid"):
        _receipt(arms=arms[:-1]).validate()
    duplicate = arms[:-1] + (arms[0],)
    with pytest.raises(WorldAfterstateV2CapacityError, match="arm grid"):
        _receipt(arms=duplicate).validate()
    chosen = list(_receipt().selected_arms)
    chosen[0] = next(arm for arm in _receipt().arms
                     if arm.stage == "state-successor" and arm.variant == 2)
    with pytest.raises(WorldAfterstateV2CapacityError, match="fastest"):
        _receipt(selected_arms=tuple(chosen)).validate()
    altered = list(_receipt().arms)
    altered[0] = dataclasses.replace(altered[0], byte_identity_sha256=_sha("other"))
    with pytest.raises(WorldAfterstateV2CapacityError, match="byte-identical"):
        _receipt(arms=tuple(altered)).validate()


def test_arm_over_85_percent_is_reported_but_ineligible_for_selection():
    arms = list(_arms())
    first = next(index for index, arm in enumerate(arms)
                 if arm.stage == "state-successor" and arm.variant == 1)
    arms[first] = dataclasses.replace(arms[first], peak_memory_bytes=29 * 1024**3)
    receipt = _receipt(arms=tuple(arms))
    chosen = next(arm for arm in receipt.selected_arms
                  if arm.stage == "state-successor")
    assert chosen.variant == 2
    receipt.validate()


def test_command_accounting_and_low_cpu_without_a_larger_arm_refuse():
    with pytest.raises(WorldAfterstateV2CapacityError, match="accounting"):
        _receipt(command_wall_seconds=1).validate()
    arms = list(_arms())
    stage = "continuation-mechanics"
    maximum = max(ARM_GRIDS[stage])
    for index, arm in enumerate(arms):
        if arm.stage == stage:
            wall = 10 if arm.variant == maximum else 100 + arm.variant
            utilization = 800_000 if arm.variant == maximum else 900_000
            arms[index] = dataclasses.replace(
                arm, wall_seconds=wall, wall_ns=wall * 1_000_000_000,
                busy_core_ns=(wall * 1_000_000_000 * 16 * utilization
                              // 1_000_000),
                busy_core_seconds=(wall * 16 * utilization
                                   + 999_999) // 1_000_000,
                mean_cpu_utilization_ppm=utilization,
                p50_cpu_utilization_ppm=utilization,
                cpu_bound=arm.variant == maximum,
                wall_share_ppm=100_000 if arm.variant == maximum else 10_000)
    with pytest.raises(WorldAfterstateV2CapacityError, match="next-arm"):
        _receipt(arms=tuple(arms)).validate()


def test_receipt_replays_pre_dag_state_successor_saturation_gate():
    arms = list(_arms())
    stage = "state-successor"
    maximum = max(ARM_GRIDS[stage])
    for index, arm in enumerate(arms):
        if arm.stage != stage:
            continue
        wall_ns = (10 if arm.variant == maximum else 100 + arm.variant) \
            * 1_000_000_000
        utilization = 800_000 if arm.variant == maximum else 900_000
        busy_ns = wall_ns * 16 * utilization // 1_000_000
        arms[index] = dataclasses.replace(
            arm, wall_ns=wall_ns,
            wall_seconds=(wall_ns + 999_999_999) // 1_000_000_000,
            busy_core_ns=busy_ns,
            busy_core_seconds=(busy_ns + 999_999_999) // 1_000_000_000,
            mean_cpu_utilization_ppm=utilization,
            p50_cpu_utilization_ppm=utilization,
            cpu_bound=arm.variant == maximum)
    with pytest.raises(WorldAfterstateV2CapacityError, match="next-arm"):
        _receipt(arms=tuple(arms)).validate()


def test_cpu_bound_five_percent_requires_utilization_or_next_identical_arm():
    arms = list(_arms(low_cpu=True))
    # Every stage's next measured arm is slower and byte-identical, satisfying
    # the low-utilization exception.
    _receipt(arms=tuple(arms)).validate()
    broken = tuple(arm for arm in arms
                   if not (arm.stage == "state-successor" and arm.variant > 1))
    with pytest.raises(WorldAfterstateV2CapacityError, match="arm grid"):
        _receipt(arms=broken).validate()


def test_max16_low_utilization_is_saved_by_immediate_slower_32():
    arms = [arm for arm in _arms() if arm.stage == "continuation-mechanics"]
    low = next(arm for arm in arms if arm.variant == 16)
    slower = next(arm for arm in arms if arm.variant == 32)
    low = dataclasses.replace(
        low, wall_ns=1_000_000_000, wall_seconds=1,
        busy_core_ns=1_000_000_000 * 16 * 800_000 // 1_000_000,
        busy_core_seconds=13, mean_cpu_utilization_ppm=800_000,
        p50_cpu_utilization_ppm=800_000, cpu_bound=True)
    slower = dataclasses.replace(
        slower, wall_ns=2_000_000_000, wall_seconds=2,
        busy_core_ns=2_000_000_000 * 16 * 900_000 // 1_000_000,
        busy_core_seconds=29, mean_cpu_utilization_ppm=900_000)
    assert arm_has_immediate_next_slower(low, (low, slower))


def test_immediate_next_saturation_witness_must_be_memory_eligible():
    arms = [arm for arm in _arms() if arm.stage == "continuation-mechanics"]
    low = dataclasses.replace(
        next(arm for arm in arms if arm.variant == 16),
        cpu_bound=True)
    slower = dataclasses.replace(
        next(arm for arm in arms if arm.variant == 32),
        wall_ns=low.wall_ns + 1_000_000_000,
        wall_seconds=(low.wall_ns + 1_999_999_999) // 1_000_000_000,
        peak_memory_bytes=MEMORY_LIMIT_BYTES)
    assert not arm_has_immediate_next_slower(low, (low, slower))


def test_immediate_next_must_be_slower_not_any_later_arm():
    arms = list(_arms())
    stage = "continuation-mechanics"
    selected = next(arm for arm in arms if arm.stage == stage and arm.variant == 1)
    next_arm = next(arm for arm in arms if arm.stage == stage and arm.variant == 2)
    later = next(arm for arm in arms if arm.stage == stage and arm.variant == 4)
    arms[arms.index(selected)] = dataclasses.replace(
        selected, cpu_bound=True,
        busy_core_ns=selected.wall_ns * 16 * 800_000 // 1_000_000,
        busy_core_seconds=(selected.wall_ns * 16 * 800_000 // 1_000_000
                           + 999_999_999) // 1_000_000_000,
        mean_cpu_utilization_ppm=(selected.wall_ns * 16 * 800_000 // 1_000_000
                                  * 1_000_000 // (selected.wall_ns * 16)),
        p50_cpu_utilization_ppm=800_000)
    arms[arms.index(next_arm)] = dataclasses.replace(
        next_arm, wall_ns=selected.wall_ns // 2,
        wall_seconds=(selected.wall_ns // 2 + 999_999_999)
        // 1_000_000_000,
        busy_core_ns=(selected.wall_ns // 2) * 16 * 900_000 // 1_000_000,
        busy_core_seconds=((selected.wall_ns // 2) * 16 * 900_000
                           // 1_000_000 + 999_999_999) // 1_000_000_000,
        mean_cpu_utilization_ppm=((selected.wall_ns // 2) * 16 * 900_000
                                  // 1_000_000 * 1_000_000
                                  // (selected.wall_ns // 2 * 16)),
        peak_memory_bytes=29 * 1024**3)
    assert later.wall_ns > selected.wall_ns
    with pytest.raises(WorldAfterstateV2CapacityError, match="next-arm"):
        _receipt(arms=tuple(arms)).validate()


def test_continuation_grid_adds_64_and_current_arms_prove_128_units():
    assert ARM_GRIDS["continuation-mechanics"][-1] == 64
    assert all(arm.measured_unit_count >= 128
               for arm in _arms() if arm.stage == "continuation-mechanics")
    reduced = tuple(dataclasses.replace(arm, measured_unit_count=32)
                    if arm.stage == "continuation-mechanics" else arm
                    for arm in _arms())
    with pytest.raises(WorldAfterstateV2CapacityError, match="population"):
        _receipt(arms=reduced).validate()


def _census_with_selected_32(*, next_wall=2_000_000_000,
                             next_memory=20 * 1024**3,
                             next_byte=True, selected_variant=32):
    arms = list(_arms())
    stage = "continuation-mechanics"
    selected = {name: next(arm for arm in arms if arm.stage == name
                           and arm.variant == variants[0])
                for name, variants in ARM_GRIDS.items()}
    low = next(arm for arm in arms if arm.stage == stage and arm.variant == selected_variant)
    low = dataclasses.replace(
        low, wall_ns=1_000_000_000, wall_seconds=1,
        busy_core_ns=12_800_000_000, busy_core_seconds=13,
        mean_cpu_utilization_ppm=800_000, p50_cpu_utilization_ppm=800_000,
        cpu_bound=True)
    following = next(arm for arm in arms if arm.stage == stage and arm.variant == 64)
    following = dataclasses.replace(
        following, wall_ns=next_wall, wall_seconds=(next_wall + 999_999_999) // 1_000_000_000,
        busy_core_ns=next_wall * 14, busy_core_seconds=(next_wall * 14 + 999_999_999) // 1_000_000_000,
        mean_cpu_utilization_ppm=875_000, p50_cpu_utilization_ppm=875_000,
        peak_memory_bytes=next_memory,
        byte_identity_sha256=low.byte_identity_sha256 if next_byte else _sha("different"))
    arms[arms.index(next(arm for arm in arms if arm.stage == stage and arm.variant == selected_variant))] = low
    arms[arms.index(next(arm for arm in arms if arm.stage == stage and arm.variant == 64))] = following
    selected[stage] = low
    return tuple(arms), selected


def test_census_selected_32_only_passes_with_eligible_identical_slower_64():
    stages = {name: 100 for name in COMPOSED_STAGE_NAMES}
    arms, selected = _census_with_selected_32()
    rows = validate_capacity_arm_census_v2(arms, selected, stages)
    row = next(value for value in rows if value.category == "continuation-mechanics")
    assert row.immediate_next_variant == 64 and row.next_strictly_slower
    for kwargs in ({"next_wall": 500_000_000}, {"next_wall": 1_000_000_000},
                   {"next_wall": 2_000_000_000, "next_memory": MEMORY_LIMIT_BYTES},
                   {"next_wall": 2_000_000_000, "next_byte": False}):
        arms, selected = _census_with_selected_32(**kwargs)
        with pytest.raises(WorldAfterstateV2CapacityError):
            validate_capacity_arm_census_v2(arms, selected, stages)


def test_census_low_fastest_64_without_next_refuses():
    stages = {name: 100 for name in COMPOSED_STAGE_NAMES}
    arms, selected = _census_with_selected_32()
    low64 = next(arm for arm in arms
                 if arm.stage == "continuation-mechanics" and arm.variant == 64)
    low64 = dataclasses.replace(
        low64, wall_ns=1_000_000_000, wall_seconds=1,
        busy_core_ns=12_800_000_000, busy_core_seconds=13,
        mean_cpu_utilization_ppm=800_000, p50_cpu_utilization_ppm=800_000,
        cpu_bound=True)
    arms = tuple(low64 if arm.stage == low64.stage and arm.variant == 64 else arm
                 for arm in arms)
    selected["continuation-mechanics"] = low64
    with pytest.raises(WorldAfterstateV2CapacityError):
        validate_capacity_arm_census_v2(arms, selected, stages)


def test_census_assessment_binds_cpu_bound_and_tampering_refuses():
    stages = {name: 100 for name in COMPOSED_STAGE_NAMES}
    arms, selected = _census_with_selected_32()
    rows = validate_capacity_arm_census_v2(arms, selected, stages)
    row = next(value for value in rows if value.category == "continuation-mechanics")
    with pytest.raises(WorldAfterstateV2CapacityError):
        dataclasses.replace(row, cpu_bound=False, violates_gate=True).validate()
    with pytest.raises(WorldAfterstateV2CapacityError):
        dataclasses.replace(row, exact_wall_ns=2_000_000_000).validate()


def test_assessment_next_slower_requires_exact_successor_eligibility():
    arms, selected = _census_with_selected_32()
    rows = validate_capacity_arm_census_v2(
        arms, selected, {name: 100 for name in COMPOSED_STAGE_NAMES})
    row = next(value for value in rows if value.category == "continuation-mechanics")
    for changes in ({"next_memory_eligible": False},
                    {"next_byte_identical": False},
                    {"immediate_next_variant": 12}):
        tampered = dataclasses.replace(row, **changes)
        with pytest.raises(WorldAfterstateV2CapacityError):
            tampered.validate()
        payload = dict(row.payload())
        payload.update(changes)
        with pytest.raises(WorldAfterstateV2CapacityError):
            CapacityCensusAssessmentV2.reopen(payload)


def test_failure_detail_and_assessment_rows_are_strictly_bound():
    source, input_sha, runtime = "1" * 64, "2" * 64, "3" * 64
    namespace = hashlib.sha256(canonical_json_bytes({
        "source_sha256": source, "input_sha256": input_sha,
        "runtime_sha256": runtime})).hexdigest()
    arms, selected = _census_with_selected_32(next_wall=500_000_000)
    with pytest.raises(WorldAfterstateV2CapacityError) as caught:
        validate_capacity_arm_census_v2(
            arms, selected, {name: 100 for name in COMPOSED_STAGE_NAMES})
    assessments = caught.value.assessments
    detail = hashlib.sha256(canonical_json_bytes({
        "message": "census refused", "assessments": [row.payload()
                                                         for row in assessments]})).hexdigest()
    failure = CapacityFailureReceiptV2(
        stage="measurement", reason="arm-census-low-utilization",
        elapsed_seconds=1, source_sha256=source, input_sha256=input_sha,
        runtime_sha256=runtime, namespace_sha256=namespace,
        detail_sha256=detail, detail_message="census refused",
        assessments=assessments)
    payload = failure.payload()
    assert len(payload["assessments"]) == len(ARM_GRIDS)
    for field in ("exact_wall_ns", "category", "projected_share_ppm",
                  "next_strictly_slower"):
        tampered_row = dict(payload["assessments"][1])
        tampered_row[field] = ("other" if field == "category"
                               else not tampered_row[field]
                               if field == "next_strictly_slower"
                               else tampered_row[field] + 1)
        tampered = dict(payload, assessments=[
            tampered_row if index == 1 else row
            for index, row in enumerate(payload["assessments"])])
        with pytest.raises(WorldAfterstateV2CapacityError):
            reopen_capacity_failure_receipt_v2(tampered)
    with pytest.raises(WorldAfterstateV2CapacityError):
        CapacityFailureReceiptV2(
            stage="runner", reason="capacity-runner-refused", elapsed_seconds=0,
            source_sha256=source, input_sha256=input_sha, runtime_sha256=runtime,
            namespace_sha256=namespace, detail_sha256="4" * 64).payload()


def test_projected_share_boundary_and_derived_full_dag_gate():
    stage_walls = {name: 1 for name in COMPOSED_STAGE_NAMES}
    stage_walls["p0"] = 49_999
    stage_walls["label-p0"] = 50_000
    shares = projected_arm_wall_shares_ppm(stage_walls)
    assert sum(shares.values()) <= 1_000_000
    wall_ns = {name: value * 1_000_000_000
               for name, value in stage_walls.items()}
    cpu_ns = {name: value * 14 * 1_000_000_000
              for name, value in stage_walls.items()}
    assert derive_all_core_gate_passed(_arms(), stage_walls, wall_ns, cpu_ns)
    cpu_ns["p0"] = 1_000_000_000
    assert not derive_all_core_gate_passed(_arms(), stage_walls, wall_ns, cpu_ns)


def test_receipt_cannot_hardcode_all_core_pass_over_exact_stage_counters():
    composed = _composed()
    cpu_rows = tuple(
        (name, 1_000_000_000 if name == "p0" else value)
        for name, value in composed.measured_stage_cpu_nanoseconds)
    cpu_seconds = tuple(
        (name, 1 if name == "p0" else value)
        for name, value in composed.measured_stage_cpu_seconds)
    composed = dataclasses.replace(
        composed, measured_stage_cpu_nanoseconds=cpu_rows,
        measured_stage_cpu_seconds=cpu_seconds)
    with pytest.raises(WorldAfterstateV2CapacityError,
                       match="all-core gate binding"):
        _receipt(composed=composed, all_core_gate_passed=True).validate()


def test_composed_dag_disk_and_progress_recovery_bindings():
    with pytest.raises(WorldAfterstateV2CapacityError, match="composed"):
        _composed(stage_walls_seconds={"audit": 21_000}).validate()
    with pytest.raises(WorldAfterstateV2CapacityError, match="composed"):
        _composed(composed_artifact_bytes=76).validate()
    with pytest.raises(WorldAfterstateV2CapacityError, match="progress"):
        _receipt(progress_recovery=_progress(
            progress_interval_seconds=61)).validate()
    with pytest.raises(WorldAfterstateV2CapacityError, match="progress"):
        _receipt(progress_recovery=_progress(
            progress_interval_fraction_ppm=10_001)).validate()
    with pytest.raises(WorldAfterstateV2CapacityError, match="proven"):
        _progress(one_audit_open=False).validate()


def test_serialized_nested_100_cost_is_counted_on_the_critical_path():
    base = _composed()
    sibling_below = _composed(
        stage_walls_seconds={"nested-curve-100": 50})
    sibling_above = _composed(
        stage_walls_seconds={"nested-curve-100": 2_000})
    assert sibling_below.composed_wall_seconds \
        == base.composed_wall_seconds - 50
    assert sibling_above.composed_wall_seconds > base.composed_wall_seconds
    base.validate()
    sibling_below.validate()
    sibling_above.validate()


def test_capacity_substage_mapping_is_closed_over_production_stages():
    assert tuple(CAPACITY_STAGE_TO_PRODUCTION_STAGE) == COMPOSED_STAGE_NAMES
    assert set(CAPACITY_STAGE_TO_PRODUCTION_STAGE.values()) == (
        set(PRODUCTION_STAGE_NAMES) - {"population"})
    assert CAPACITY_ARM_TO_PRODUCTION_STAGE["state-successor"] == "population"
    assert CAPACITY_STAGE_TO_PRODUCTION_STAGE["audit"] == "terminal"
    assert CAPACITY_STAGE_TO_PRODUCTION_STAGE["reconstruction"] == "reconstruction"
    with pytest.raises(WorldAfterstateV2CapacityError, match="mapping"):
        dataclasses.replace(
            _composed(),
            capacity_stage_to_production_stage=tuple(
                CAPACITY_STAGE_TO_PRODUCTION_STAGE.items())[:-1]).validate()


def test_dag_edge_contract_and_wrong_wall_receipts_refuse():
    composed = _composed()
    with pytest.raises(WorldAfterstateV2CapacityError, match="DAG"):
        dataclasses.replace(
            composed, dag_edges=COMPOSED_DAG_EDGES[:-1]).validate()
    with pytest.raises(WorldAfterstateV2CapacityError, match="scientific DAG"):
        dataclasses.replace(
            composed, scientific_dag_edges=COMPOSED_DAG_EDGES[:-1]).validate()
    with pytest.raises(WorldAfterstateV2CapacityError, match="composed"):
        dataclasses.replace(
            composed,
            composed_wall_seconds=composed.composed_wall_seconds + 1,
        ).validate()


def test_staged_label_dependencies_cannot_move_or_double_spend_label_work():
    assert ("label-p0", "p0") in SCIENTIFIC_DAG_EDGES
    assert ("p0", "optimizer-canary") in SCIENTIFIC_DAG_EDGES
    assert ("optimizer-canary", "label-fit") in SCIENTIFIC_DAG_EDGES
    assert ("label-fit", "p0") not in SCIENTIFIC_DAG_EDGES
    assert ("precision-select-inference", "label-precision-select") \
        in SCIENTIFIC_DAG_EDGES
    assert ("label-precision-select", "precision-select") in SCIENTIFIC_DAG_EDGES
    assert ("precision-select", "label-audit") in SCIENTIFIC_DAG_EDGES
    assert ("label-audit", "audit") in SCIENTIFIC_DAG_EDGES
    assert ("audit", "reconstruction") in SCIENTIFIC_DAG_EDGES
    assert COMPOSED_STAGE_NAMES.index("precision-select") \
        < COMPOSED_STAGE_NAMES.index("label-audit") \
        < COMPOSED_STAGE_NAMES.index("audit") \
        < COMPOSED_STAGE_NAMES.index("reconstruction")
    assert ("nested-curve-50", "nested-curve-100") \
        in TRAINING_RESOURCE_SERIALIZATION_EDGES
    assert ("nested-curve-100", "block-1-action-association-permutation") \
        in TRAINING_RESOURCE_SERIALIZATION_EDGES


def test_production_command_wall_binds_sequential_arms_plus_dag():
    arms = _arms()
    selected = tuple(min((arm for arm in arms if arm.stage == stage),
                         key=lambda arm: (arm.wall_seconds, arm.variant))
                    for stage in ARM_GRIDS)
    selected_by_stage = {arm.stage: arm.variant for arm in selected}
    layout = {
        "member_workers": selected_by_stage["member-concurrency"],
        "continuation_workers": selected_by_stage["continuation-mechanics"],
        "torch_threads": PINNED_TORCH_THREADS,
        "inference_batch": selected_by_stage["inference-batch"],
    }
    composed = _composed()
    measured = composed.measured_stage_walls_seconds
    with pytest.raises(WorldAfterstateV2CapacityError, match="accounting"):
        _receipt(
            arms=arms, selected_arms=selected,
            command_wall_seconds=sum(arm.wall_seconds for arm in arms)
            + sum(value for _, value in measured) - 1,
            task_count=1, peak_task_count=1, composed=composed,
            **layout).validate()
    _receipt(
        arms=arms, selected_arms=selected,
        command_wall_seconds=sum(arm.wall_seconds for arm in arms)
        + sum(value for _, value in measured),
        task_count=1, peak_task_count=1, composed=composed,
        **layout).validate()
    with pytest.raises(WorldAfterstateV2CapacityError, match="accounting"):
        _receipt(
            arms=arms, selected_arms=selected,
            command_wall_seconds=sum(arm.wall_seconds for arm in arms)
            + sum(value for _, value in measured) + 1,
            task_count=1, peak_task_count=1, composed=composed,
            **layout).validate()


def test_tier_selection_is_outcome_blind_and_uses_protocol_thresholds():
    receipt = _receipt(tiers=tuple(
        dataclasses.replace(tier, exact_source_supply=(tier.tier != "D1024"))
        for tier in _receipt().tiers))
    assert choose_capacity_tier_v2(receipt).name == "D512"
    with pytest.raises(WorldAfterstateV2CapacityError, match="outcomes"):
        tiers = tuple(dataclasses.replace(tier, outcomes_opened=True)
                      if tier.tier == "D512" else tier for tier in receipt.tiers)
        choose_capacity_tier_v2(_receipt(tiers=tiers))
