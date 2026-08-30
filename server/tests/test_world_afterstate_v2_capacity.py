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
    CapacityFailureReceiptV2, CapacityReceiptV2, ComposedProjectionV2,
    ProgressRecoveryV2,
    TierProjectionV2, WorldAfterstateV2CapacityError,
    PINNED_TORCH_THREADS, choose_capacity_tier_v2,
    composed_critical_path_seconds,
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
            utilization = (800_000 if low_cpu and variant == min(variants)
                           else 900_000)
            values.append(CapacityArmV2(
                stage=stage, variant=variant, wall_seconds=wall,
                busy_core_seconds=round(wall * 16 * utilization / 1_000_000),
                mean_cpu_utilization_ppm=utilization,
                p50_cpu_utilization_ppm=800_000 if low_cpu and variant == min(variants)
                else 900_000,
                p95_cpu_utilization_ppm=900_000,
                scaling_efficiency_ppm=900_000, queue_depth=0,
                wall_share_ppm=100_000 if variant == min(variants) else 10_000,
                peak_memory_bytes=memory or 20 * 1024**3,
                swap_bytes=0, task_count=command_tasks,
                byte_identity_sha256=_sha(f"{stage}:{byte_suffix}"),
                cpu_bound=low_cpu))
    return tuple(values)


def _composed(**changes):
    values = {name: 100 for name in COMPOSED_STAGE_NAMES}
    values.update(changes.pop("stage_walls_seconds", {}))
    body = dict(stage_walls_seconds=tuple(values.items()),
                composed_wall_seconds=composed_critical_path_seconds(values),
                peak_memory_bytes=20 * 1024**3,
                composed_artifact_bytes=75,
                free_disk_bytes_before=100)
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
    namespace = hashlib.sha256(canonical_json_bytes({
        "source_sha256": source, "input_sha256": input_sha})).hexdigest()
    failure = CapacityFailureReceiptV2(
        stage="runner", reason="capacity-runner-refused", elapsed_seconds=4,
        source_sha256=source, input_sha256=input_sha,
        namespace_sha256=namespace, detail_sha256="4" * 64)
    payload = failure.payload()
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
        host_logical_cpus=16, command_wall_seconds=7_200,
        memory_limit_bytes=MEMORY_LIMIT_BYTES, swap_bytes=0, task_count=0,
        arms=_arms(), selected_arms=tuple(), composed=_composed(), tiers=tiers,
        progress_recovery=_progress())
    body.update(changes)
    if "task_count" not in changes:
        body["task_count"] = sum(arm.task_count for arm in body["arms"])
    if "selected_arms" not in changes:
        body["selected_arms"] = tuple(min(
            (arm for arm in body["arms"] if arm.stage == stage
             and arm.peak_memory_bytes * 100
             <= MEMORY_LIMIT_BYTES * 85),
            key=lambda arm: (arm.wall_seconds, arm.variant))
            for stage in ARM_GRIDS)
    return CapacityReceiptV2(**body)


def test_exact_arm_grid_caps_and_fastest_byte_identical_selection():
    receipt = _receipt()
    receipt.validate()
    assert "torch-threads-per-member" not in ARM_GRIDS
    assert len(receipt.arms) == 22
    assert len(receipt.arms) == sum(len(values) for values in ARM_GRIDS.values())
    assert receipt.sha256() == receipt.sha256()
    assert choose_capacity_tier_v2(receipt).name == "D1024"
    assert AUTHORITY and not any(AUTHORITY.values())


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
    stage = "state-successor"
    maximum = max(ARM_GRIDS[stage])
    for index, arm in enumerate(arms):
        if arm.stage == stage:
            wall = 10 if arm.variant == maximum else 100 + arm.variant
            utilization = 800_000 if arm.variant == maximum else 900_000
            arms[index] = dataclasses.replace(
                arm, wall_seconds=wall,
                busy_core_seconds=round(wall * 16 * utilization / 1_000_000),
                mean_cpu_utilization_ppm=utilization,
                p50_cpu_utilization_ppm=utilization,
                cpu_bound=arm.variant == maximum,
                wall_share_ppm=100_000 if arm.variant == maximum else 10_000)
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


def test_composed_dag_disk_and_progress_recovery_bindings():
    with pytest.raises(WorldAfterstateV2CapacityError, match="composed"):
        _receipt(composed=_composed(
            stage_walls_seconds={"audit": 21_000})).validate()
    with pytest.raises(WorldAfterstateV2CapacityError, match="composed"):
        _receipt(composed=_composed(composed_artifact_bytes=76)).validate()
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
        "torch_threads": PINNED_TORCH_THREADS,
        "inference_batch": selected_by_stage["inference-batch"],
    }
    measured = tuple((name, 10) for name in COMPOSED_STAGE_NAMES)
    composed = _composed(measured_stage_walls_seconds=measured)
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
