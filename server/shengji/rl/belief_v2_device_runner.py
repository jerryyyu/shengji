"""Runnable post-capture device qualification for BELIEF-V1 V2.

Every arm starts from the same eight fixed initializations and trains exactly
one epoch over the digest-selected primary batches.  CPU and the frozen
accelerator run in the preregistered order; device clocks are synchronized,
portable checkpoint and receipt hashes must repeat within device, and no
runtime fallback is permitted.
"""

from __future__ import annotations

import gc
import resource
import sys
import time
from typing import Any, Callable

import torch

from .belief_cohort import COHORT_SEEDS
from .belief_model import new_from_scratch_model
from .belief_v2_accelerator import (
    move_models_to_device,
    new_v2_optimizer,
    portable_model_state_sha256,
    train_v2_cohort_epoch_stream,
)
from .belief_v2_cohort_training import _training_batches
from .belief_v2_device_qualification import (
    V2DeviceQualificationArmV1,
    V2DeviceQualificationPlanV1,
    V2DeviceQualificationResultV1,
    build_qualification_plan_from_primary,
    derive_qualification_result,
    validate_qualification_plan,
)
from .belief_v2_schedule import V2CohortRealizationV1
from .belief_v2_streaming_training import (
    RoundLoader,
    V2StreamingTrainingIndexV1,
    iter_streaming_training_batches,
)
from .belief_v2_training import V2TrainingExampleV1


class BeliefV2DeviceRunnerError(ValueError):
    """A qualification input, arm execution, or resource sample drifted."""


def host_peak_memory_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if type(value) not in {int, float} or value < 0:
        raise BeliefV2DeviceRunnerError(
            "V2 qualification host memory measurement drift")
    # macOS reports bytes; Linux and the other supported Unix hosts report KiB.
    result = int(value) if sys.platform == "darwin" else int(value) * 1024
    if result <= 0:
        raise BeliefV2DeviceRunnerError(
            "V2 qualification host memory measurement drift")
    return result


def synchronize_training_device(device: str) -> None:
    parsed = torch.device(device)
    if parsed.type == "cuda":
        torch.cuda.synchronize(parsed)
    elif parsed.type == "mps":
        torch.mps.synchronize()


def prepare_device_memory_measurement(device: str, cap: int) -> None:
    parsed = torch.device(device)
    if parsed.type == "cuda":
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats(parsed)
    elif parsed.type == "mps":
        torch.mps.empty_cache()
        recommended = int(torch.mps.recommended_max_memory())
        if recommended <= 0 or cap <= 0:
            raise BeliefV2DeviceRunnerError(
                "V2 qualification MPS memory identity drift")
        # The allocator limit is the fail-closed cap; the receipt separately
        # records the maximum driver allocation observed after synchronized
        # execution.  Fractions above 1 are not needed by this protocol.
        torch.mps.set_per_process_memory_fraction(min(1.0, cap / recommended))


def device_peak_memory_bytes(device: str) -> int:
    parsed = torch.device(device)
    if parsed.type == "cpu":
        return 0
    if parsed.type == "cuda":
        return int(torch.cuda.max_memory_allocated(parsed))
    if parsed.type == "mps":
        return int(torch.mps.driver_allocated_memory())
    raise BeliefV2DeviceRunnerError(
        "V2 qualification device memory type drift")


def release_training_device(device: str) -> None:
    gc.collect()
    parsed = torch.device(device)
    if parsed.type == "cuda":
        torch.cuda.empty_cache()
    elif parsed.type == "mps":
        torch.mps.empty_cache()


def execute_qualification_arm(
        plan: V2DeviceQualificationPlanV1, *, arm_index: int,
        selected_batches: tuple[object, ...]) \
        -> V2DeviceQualificationArmV1:
    """Execute one exact fresh-model arm from the frozen order."""
    validate_qualification_plan(plan)
    if type(arm_index) is not int or not 0 <= arm_index < len(plan.arm_order) \
            or type(selected_batches) is not tuple \
            or len(selected_batches) != len(plan.selected_batch_indices):
        raise BeliefV2DeviceRunnerError(
            "V2 qualification arm input population drift")
    device, warmup, pair_index = plan.arm_order[arm_index]
    models = tuple(new_from_scratch_model(seed) for seed in COHORT_SEEDS)
    try:
        move_models_to_device(models, device=device)
        optimizers = tuple(new_v2_optimizer(model) for model in models)
        prepare_device_memory_measurement(
            device, plan.device_memory_cap_bytes)
        synchronize_training_device(device)
        started = time.perf_counter_ns()
        receipts = train_v2_cohort_epoch_stream(
            models, optimizers, iter(selected_batches),
            epoch=1, device=device)
        synchronize_training_device(device)
        finished = time.perf_counter_ns()
        checkpoints = tuple(portable_model_state_sha256(model)
                            for model in models)
        host_peak = host_peak_memory_bytes()
        device_peak = device_peak_memory_bytes(device)
    except (RuntimeError, ValueError) as exc:
        raise BeliefV2DeviceRunnerError(
            "V2 qualification arm execution refused") from exc
    finally:
        # No exception path is converted into CPU fallback.
        release_training_device(device)
    wall = finished - started
    if wall <= 0 or host_peak > plan.host_memory_cap_bytes \
            or device_peak > plan.device_memory_cap_bytes:
        raise BeliefV2DeviceRunnerError(
            "V2 qualification arm resource cap drift")
    arm = V2DeviceQualificationArmV1(
        arm_index=arm_index, device=device, warmup=warmup,
        pair_index=pair_index, plan_sha256=plan.sha256(),
        batch_population_sha256=plan.selected_population_sha256,
        batch_schedule_sha256=plan.selected_schedule_sha256,
        decision_count=plan.decision_count,
        active_label_count=plan.active_label_count,
        member_checkpoint_sha256s=checkpoints,
        member_loss_nanonats=tuple(
            receipt.mean_loss_nanonats for receipt in receipts),
        member_epoch_receipt_sha256s=tuple(
            receipt.sha256() for receipt in receipts),
        wall_nanoseconds=wall,
        peak_host_memory_bytes=host_peak,
        peak_device_memory_bytes=device_peak,
        actual_device=device, fallback_used=False, completed=True)
    # derive_qualification_result will run the module's exact arm validator;
    # a one-arm tuple cannot satisfy the complete population here.
    return arm


def _run_qualification_plan(
        plan: V2DeviceQualificationPlanV1, *,
        selected_batches: tuple[object, ...],
        deadline_check: Callable[[str, int], None] | None,
        progress: Callable[[int, int, str], None] | None = None) \
        -> V2DeviceQualificationResultV1:
    if type(selected_batches) is not tuple \
            or len(selected_batches) != len(plan.selected_batch_indices):
        raise BeliefV2DeviceRunnerError(
            "V2 qualification selected batch population drift")
    arms = []
    if progress is not None:
        progress(0, len(plan.arm_order), "qualification-arms")
    for index in range(len(plan.arm_order)):
        if deadline_check is not None:
            deadline_check("before-unit", index)
        arms.append(execute_qualification_arm(
            plan, arm_index=index, selected_batches=selected_batches))
        if deadline_check is not None:
            deadline_check("after-unit", index + 1)
        if progress is not None:
            progress(index + 1, len(plan.arm_order), "qualification-arms")
    if deadline_check is not None:
        deadline_check("before-seal", len(arms))
    try:
        return derive_qualification_result(plan, tuple(arms))
    except ValueError as exc:
        raise BeliefV2DeviceRunnerError(
            "V2 qualification terminal derivation refused") from exc


def _qualification_plan(
        *, execution_git: str, candidate_device: str,
        primary: V2CohortRealizationV1, host_memory_cap_bytes: int,
        device_memory_cap_bytes: int) -> V2DeviceQualificationPlanV1:
    return build_qualification_plan_from_primary(
        execution_git=execution_git, candidate_device=candidate_device,
        primary=primary, host_memory_cap_bytes=host_memory_cap_bytes,
        device_memory_cap_bytes=device_memory_cap_bytes)


def run_device_qualification_in_memory(
        *, execution_git: str, candidate_device: str,
        primary: V2CohortRealizationV1,
        primary_examples: tuple[V2TrainingExampleV1, ...],
        host_memory_cap_bytes: int,
        device_memory_cap_bytes: int,
        deadline_check: Callable[[str, int], None] | None = None,
        progress: Callable[[int, int, str], None] | None = None) \
        -> tuple[V2DeviceQualificationPlanV1,
                 V2DeviceQualificationResultV1]:
    """Execute the frozen order from a small materialized population."""
    plan = _qualification_plan(
        execution_git=execution_git, candidate_device=candidate_device,
        primary=primary, host_memory_cap_bytes=host_memory_cap_bytes,
        device_memory_cap_bytes=device_memory_cap_bytes)
    try:
        batches, control_dose = _training_batches(
            primary, primary_examples)
    except ValueError as exc:
        raise BeliefV2DeviceRunnerError(
            "V2 qualification primary batches refused") from exc
    if control_dose != 0 or len(batches) <= max(plan.selected_batch_indices):
        raise BeliefV2DeviceRunnerError(
            "V2 qualification primary batch population drift")
    selected = tuple(batches[index] for index in plan.selected_batch_indices)
    return plan, _run_qualification_plan(
        plan, selected_batches=selected, deadline_check=deadline_check,
        progress=progress)


def run_device_qualification_streaming(
        *, execution_git: str, candidate_device: str,
        primary: V2CohortRealizationV1,
        streaming_index: V2StreamingTrainingIndexV1,
        load_round: RoundLoader, host_memory_cap_bytes: int,
        device_memory_cap_bytes: int,
        deadline_check: Callable[[str, int], None] | None = None,
        progress: Callable[[int, int, str], None] | None = None) \
        -> tuple[V2DeviceQualificationPlanV1,
                 V2DeviceQualificationResultV1]:
    """Reopen only batches needed by qualification, then execute its arms."""
    plan = _qualification_plan(
        execution_git=execution_git, candidate_device=candidate_device,
        primary=primary, host_memory_cap_bytes=host_memory_cap_bytes,
        device_memory_cap_bytes=device_memory_cap_bytes)
    wanted = set(plan.selected_batch_indices)
    selected_by_index = {}
    try:
        for index, batch in enumerate(iter_streaming_training_batches(
                streaming_index, primary, load_round=load_round)):
            if index in wanted:
                selected_by_index[index] = batch
            if index >= max(wanted):
                break
    except ValueError as exc:
        raise BeliefV2DeviceRunnerError(
            "V2 qualification streaming batches refused") from exc
    if set(selected_by_index) != wanted:
        raise BeliefV2DeviceRunnerError(
            "V2 qualification streaming batch population drift")
    selected = tuple(selected_by_index[index]
                     for index in plan.selected_batch_indices)
    return plan, _run_qualification_plan(
        plan, selected_batches=selected, deadline_check=deadline_check,
        progress=progress)


def run_device_qualification_from_batch_factory(
        *, execution_git: str, candidate_device: str,
        primary: V2CohortRealizationV1,
        batch_factory: Callable[[], Any], host_memory_cap_bytes: int,
        device_memory_cap_bytes: int,
        deadline_check: Callable[[str, int], None] | None = None,
        progress: Callable[[int, int, str], None] | None = None) \
        -> tuple[V2DeviceQualificationPlanV1,
                 V2DeviceQualificationResultV1]:
    """Select the frozen qualification batches from a bound reusable cache."""
    if not callable(batch_factory):
        raise BeliefV2DeviceRunnerError(
            "V2 qualification batch factory drift")
    plan = _qualification_plan(
        execution_git=execution_git, candidate_device=candidate_device,
        primary=primary, host_memory_cap_bytes=host_memory_cap_bytes,
        device_memory_cap_bytes=device_memory_cap_bytes)
    wanted = set(plan.selected_batch_indices)
    selected_by_index = {}
    try:
        for index, batch in enumerate(batch_factory()):
            if index in wanted:
                selected_by_index[index] = batch
            if index >= max(wanted):
                break
    except ValueError as exc:
        raise BeliefV2DeviceRunnerError(
            "V2 qualification cached batches refused") from exc
    if set(selected_by_index) != wanted:
        raise BeliefV2DeviceRunnerError(
            "V2 qualification cached batch population drift")
    selected = tuple(selected_by_index[index]
                     for index in plan.selected_batch_indices)
    return plan, _run_qualification_plan(
        plan, selected_batches=selected, deadline_check=deadline_check,
        progress=progress)
