"""In-memory, bounded cohort training for Value-Afterstate V2.

This is deliberately a controller, not an execution or publication layer.  A
caller supplies the already sealed epoch-select scorer; the controller only
uses its integer score for the reviewed common-epoch rule.  No audit or
consumer operation is reachable from this module.
"""

from __future__ import annotations

import copy
import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

import torch

from .belief_contract import canonical_json_bytes
from .world_afterstate_v2_checkpoint import checkpoint_bytes, reopen_checkpoint
from .world_afterstate_v2_capacity import PINNED_TORCH_THREADS
from .world_afterstate_v2_diagnostics import validate_optimizer_canary_v2
from .world_afterstate_v2_model import WorldAfterstateValueV2, new_world_afterstate_v2_model
from .world_afterstate_v2_schedule import (
    BLOCK_1, BLOCK_2, EARLY_STOP_PATIENCE, MAX_EPOCHS, TrainingSeedBlockV2,
    CommonEpochDecisionV2, EpochScheduleV2, reuse_schedule_for_control,
    derive_nested_prefixes, select_common_epoch, training_epoch_batches,
    validate_common_epoch_checkpoints, validate_common_epoch_receipt,
)
from .world_afterstate_v2_training import (
    SCHEDULE_SCHEMA as TRAINING_SCHEDULE_SCHEMA,
    WorldAfterstateV2EpochReceipt, WorldAfterstateV2TrainingConfig,
    WorldAfterstateV2TrainingExample, model_state_sha256, new_optimizer,
    train_epoch,
)


# ``torch.set_num_threads`` is process-global.  The capacity-selected
# width-four schedule deliberately overlaps three cohort controllers in one
# process, so per-call save/set/restore can restore a wider value while a
# sibling is still training.  A shared lease keeps the pinned value live until
# the final overlapping controller exits without serializing model work.
_TORCH_THREAD_SCOPE_LOCK = threading.Lock()
_TORCH_THREAD_SCOPE_USERS = 0
_TORCH_THREAD_SCOPE_WIDTH: int | None = None
_TORCH_THREAD_SCOPE_PRIOR: int | None = None


def _acquire_torch_thread_scope(torch_threads: int) -> None:
    global _TORCH_THREAD_SCOPE_USERS, _TORCH_THREAD_SCOPE_WIDTH
    global _TORCH_THREAD_SCOPE_PRIOR
    with _TORCH_THREAD_SCOPE_LOCK:
        current = torch.get_num_threads()
        if _TORCH_THREAD_SCOPE_USERS == 0:
            torch.set_num_threads(torch_threads)
            _TORCH_THREAD_SCOPE_WIDTH = torch_threads
            _TORCH_THREAD_SCOPE_PRIOR = current
        elif (_TORCH_THREAD_SCOPE_WIDTH != torch_threads
              or current != torch_threads):
            raise WorldAfterstateV2TrainingControllerError(
                "concurrent Torch thread scope drift")
        _TORCH_THREAD_SCOPE_USERS += 1


def _release_torch_thread_scope(torch_threads: int) -> None:
    global _TORCH_THREAD_SCOPE_USERS, _TORCH_THREAD_SCOPE_WIDTH
    global _TORCH_THREAD_SCOPE_PRIOR
    with _TORCH_THREAD_SCOPE_LOCK:
        if (_TORCH_THREAD_SCOPE_USERS < 1
                or _TORCH_THREAD_SCOPE_WIDTH != torch_threads
                or _TORCH_THREAD_SCOPE_PRIOR is None):
            raise WorldAfterstateV2TrainingControllerError(
                "concurrent Torch thread scope drift")
        drifted = torch.get_num_threads() != torch_threads
        _TORCH_THREAD_SCOPE_USERS -= 1
        if _TORCH_THREAD_SCOPE_USERS == 0:
            prior = _TORCH_THREAD_SCOPE_PRIOR
            _TORCH_THREAD_SCOPE_WIDTH = None
            _TORCH_THREAD_SCOPE_PRIOR = None
            torch.set_num_threads(prior)
        if drifted:
            raise WorldAfterstateV2TrainingControllerError(
                "concurrent Torch thread scope drift")
from .world_afterstate_v2_selection_contract import (
    CONTROL_NAMES, EpochSelectScoreV2)
from .world_afterstate_v2_selection import EpochSelectPopulationV2
from .world_afterstate_v2_recovery import (
    WorldAfterstateV2Recovery, reopen_recovery, recovery_bytes)


MANIFEST_SCHEMA = "world-afterstate-v2-training-cohort-manifest-v1"
SINGLE_MEMBER_MANIFEST_SCHEMA = "world-afterstate-v2-training-single-member-manifest-v1"
PROGRESS_SCHEMA = "world-afterstate-v2-training-progress-v1"
AUTHORITY = {
    "data_collection_authorized": False,
    "capacity_execution_authorized": False,
    "warm_start_authorized": False,
    "training_authorized": False,
    "audit_opening_authorized": False,
    "consumer_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "retry_authorized": False,
}


class WorldAfterstateV2TrainingControllerError(ValueError):
    """A V2 cohort request or sealed in-memory build drifted."""


@dataclass(frozen=True)
class CohortTrainingBuildV2:
    manifest: dict[str, Any]
    selected_checkpoint_raws: tuple[bytes, ...]


@dataclass(frozen=True)
class SingleMemberTrainingBuildV2:
    """One natural member of the sealed 25%/50% nested data curve."""

    manifest: dict[str, Any]
    selected_checkpoint_raw: bytes

    @property
    def selected_checkpoint_raws(self) -> tuple[bytes, ...]:
        """Compatibility view; a single-member build has exactly one raw."""
        return (self.selected_checkpoint_raw,)


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(
            char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV2TrainingControllerError(f"{label} drift")
    return value


def _strict_int(value: object, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise WorldAfterstateV2TrainingControllerError(f"{label} drift")
    return value


def _block(value: object) -> TrainingSeedBlockV2:
    if isinstance(value, bool) or not isinstance(value, int) or value not in (1, 2):
        raise WorldAfterstateV2TrainingControllerError("seed block drift")
    return BLOCK_1 if value == 1 else BLOCK_2


def _validate_rows(values: Sequence[WorldAfterstateV2TrainingExample], cohort: str) -> None:
    if type(values) not in (tuple, list) or not values \
            or any(type(value) is not WorldAfterstateV2TrainingExample for value in values):
        raise WorldAfterstateV2TrainingControllerError("cohort population drift")
    if any(value.cohort != cohort for value in values):
        raise WorldAfterstateV2TrainingControllerError("cohort population binding drift")
    try:
        # The scheduler performs the complete sibling/root and key-set checks.
        training_epoch_batches(values, epoch=1, cohort=cohort,
                               control_name="natural")
    except Exception as exc:
        raise WorldAfterstateV2TrainingControllerError("cohort population refused") from exc


def _schedule_and_batches(
        values: Sequence[WorldAfterstateV2TrainingExample], *, epoch: int,
        data_order_seed: int, cohort: str, control_name: str,
        natural_values: Sequence[WorldAfterstateV2TrainingExample] | None,
        batch_example_cap: int):
    if cohort == "primary":
        return training_epoch_batches(
            values, epoch=epoch, data_order_seed=data_order_seed,
            cohort="primary", control_name="natural",
            batch_example_cap=batch_example_cap)
    if natural_values is None:
        raise WorldAfterstateV2TrainingControllerError(
            "control requires natural schedule population")
    natural_schedule, _ = training_epoch_batches(
        natural_values, epoch=epoch, data_order_seed=data_order_seed,
        cohort="primary", control_name="natural",
        batch_example_cap=batch_example_cap)
    return reuse_schedule_for_control(
        natural_schedule, values, cohort="control", control_name=control_name)


def _selection_score(
        value: object, *, model: WorldAfterstateValueV2, epoch: int,
        seed_block: int, member_index: int,
        control_name: str) -> EpochSelectScoreV2:
    if type(value) is not EpochSelectScoreV2:
        raise WorldAfterstateV2TrainingControllerError(
            "typed epoch-select score required")
    value.validate()
    if (value.epoch, value.seed_block, value.member_index,
            value.control_name, value.model_state_sha256) != (
                epoch, seed_block, member_index, control_name,
                model_state_sha256(model)):
        raise WorldAfterstateV2TrainingControllerError(
            "epoch-select score/model binding drift")
    return value


def _training_schedule_sha(schedule: EpochScheduleV2) -> str:
    """Match the receipt identity produced by ``train_epoch``."""
    return _sha({"schema": TRAINING_SCHEDULE_SCHEMA, "epoch": schedule.epoch,
                 "batch_example_keys": [list(batch)
                                         for batch in schedule.batch_example_keys]})


def _recovery_error(exc: Exception, label: str = "recovery history refused") \
        -> WorldAfterstateV2TrainingControllerError:
    return WorldAfterstateV2TrainingControllerError(label)


def _validate_recovery_history_shape(value: object, *, members: int) -> tuple:
    """Validate the deliberately strict, in-memory history envelope shape."""
    if value is None:
        value = ()
    if type(value) is not tuple:
        raise WorldAfterstateV2TrainingControllerError(
            "recovery history must be a tuple")
    # Single-member diagnostics intentionally expose one blob per epoch;
    # normalize that compact form to the common internal epoch tuple.
    if members == 1 and all(type(item) is bytes for item in value):
        value = tuple((item,) for item in value)
    for epoch in value:
        if type(epoch) is not tuple or len(epoch) != members \
                or any(type(raw) is not bytes or not raw for raw in epoch):
            raise WorldAfterstateV2TrainingControllerError(
                "recovery history member drop")
    return value


def _reopen_cohort_history(
        history: tuple, *, values: Sequence[WorldAfterstateV2TrainingExample],
        natural_values: Sequence[WorldAfterstateV2TrainingExample] | None,
        cohort: str, cohort_name: str, freeze_sha256: str,
        config: WorldAfterstateV2TrainingConfig,
        selection_population: EpochSelectPopulationV2, seed_block: int,
        block: TrainingSeedBlockV2, batch_example_cap: int
        ) -> tuple[list[WorldAfterstateValueV2], list[torch.optim.Optimizer],
                   list[list[dict[str, Any]]],
                   list[list[EpochSelectScoreV2]],
                   list[list[dict[str, torch.Tensor]]],
                   list[list[EpochScheduleV2]]]:
    """Reopen and validate every historical member/epoch before training."""
    models: list[WorldAfterstateValueV2] = []
    optimizers: list[torch.optim.Optimizer] = []
    receipts: list[list[dict[str, Any]]] = [[] for _ in range(4)]
    scores: list[list[EpochSelectScoreV2]] = [[] for _ in range(4)]
    snapshots: list[list[dict[str, torch.Tensor]]] = [[] for _ in range(4)]
    schedules: list[list[EpochScheduleV2]] = [[] for _ in range(4)]
    if not history:
        return models, optimizers, receipts, scores, snapshots, schedules
    opened: list[list[WorldAfterstateV2]] = []
    for epoch_index, epoch_raws in enumerate(history, 1):
        current: list[WorldAfterstateV2] = []
        for member, raw in enumerate(epoch_raws):
            try:
                item = reopen_recovery(
                    raw, expected_freeze_sha256=freeze_sha256,
                    expected_selection_population_sha256=
                    selection_population.population_sha256)
            except Exception as exc:
                raise _recovery_error(exc) from exc
            metadata = item.metadata
            if (metadata["completed_epoch"] != epoch_index
                    or metadata["seed_block"] != seed_block
                    or metadata["member_index"] != member
                    or metadata["control_name"] != cohort_name
                    or metadata["init_seed"] != block.initialization_seeds[member]
                    or item.config.payload() != config.payload()
                    or item.score.selection_population_sha256 !=
                    selection_population.population_sha256):
                raise WorldAfterstateV2TrainingControllerError(
                    "recovery history identity drift")
            current.append(item)
        opened.append(current)

    # Verify all common decisions and deterministic schedule identities while
    # reconstructing the exact receipt/model chains.
    for member in range(4):
        prior_state_sha = model_state_sha256(
            new_world_afterstate_v2_model(block.initialization_seeds[member]))
        for epoch_index, current in enumerate(opened, 1):
            item = current[member]
            schedule, _ = _schedule_and_batches(
                values, epoch=epoch_index,
                data_order_seed=block.data_order_seeds[member], cohort=cohort,
                control_name=cohort_name, natural_values=natural_values,
                batch_example_cap=batch_example_cap)
            if (item.receipt.model_state_sha256_before != prior_state_sha
                    or item.receipt.schedule_sha256 !=
                    _training_schedule_sha(schedule)
                    or item.receipt.population_sha256 != schedule.population_sha256
                    or item.receipt.model_state_sha256_after !=
                    model_state_sha256(item.model)
                    or item.score.model_state_sha256 !=
                    item.receipt.model_state_sha256_after):
                raise WorldAfterstateV2TrainingControllerError(
                    "recovery history state/schedule chain drift")
            if epoch_index > 1 and item.receipt.model_state_sha256_before != \
                    opened[epoch_index - 2][member].receipt.model_state_sha256_after:
                raise WorldAfterstateV2TrainingControllerError(
                    "recovery history state chain drift")
            prior_state_sha = item.receipt.model_state_sha256_after
            receipts[member].append(item.receipt.payload())
            scores[member].append(item.score)
            snapshots[member].append(copy.deepcopy(item.model.state_dict()))
            schedules[member].append(schedule)
    population_sha = receipts[0][0]["population_sha256"]
    if any(receipt["population_sha256"] != population_sha
           for member in receipts for receipt in member):
        raise WorldAfterstateV2TrainingControllerError(
            "recovery history population mixing")
    for epoch_index, current in enumerate(opened, 1):
        common = select_common_epoch(
            tuple(tuple(row.loss_nano for row in member_scores[:epoch_index])
                  for member_scores in scores), block_name=block.name)
        expected_sha = common.sha256()
        if common.stop_epoch != epoch_index or any(
                item.metadata["common_epoch_sha256"] != expected_sha
               for item in current):
            raise WorldAfterstateV2TrainingControllerError(
                "recovery history common decision drift")
    models = [opened[-1][member].model for member in range(4)]
    optimizers = [opened[-1][member].optimizer for member in range(4)]
    return models, optimizers, receipts, scores, snapshots, schedules


def _reopen_member_history(
        history: tuple, *, values: Sequence[WorldAfterstateV2TrainingExample],
        point_values: Sequence[WorldAfterstateV2TrainingExample],
        freeze_sha256: str, config: WorldAfterstateV2TrainingConfig,
        selection_population: EpochSelectPopulationV2, block: TrainingSeedBlockV2,
        batch_example_cap: int
        ) -> tuple[WorldAfterstateValueV2 | None, torch.optim.Optimizer | None,
                   list[dict[str, Any]], list[EpochSelectScoreV2],
                   list[dict[str, torch.Tensor]], list[EpochScheduleV2]]:
    if not history:
        return None, None, [], [], [], []
    opened: list[WorldAfterstateV2Recovery] = []
    for epoch_index, epoch_raws in enumerate(history, 1):
        try:
            item = reopen_recovery(
                epoch_raws[0], expected_freeze_sha256=freeze_sha256,
                expected_selection_population_sha256=
                selection_population.population_sha256)
        except Exception as exc:
            raise _recovery_error(exc) from exc
        metadata = item.metadata
        if (metadata["completed_epoch"] != epoch_index
                or metadata["seed_block"] != 1
                or metadata["member_index"] != 0
                or metadata["control_name"] != "natural"
                or metadata["init_seed"] != block.initialization_seeds[0]
                or item.config.payload() != config.payload()):
            raise WorldAfterstateV2TrainingControllerError(
                "recovery history identity drift")
        opened.append(item)
    prior_state_sha = model_state_sha256(new_world_afterstate_v2_model(
        block.initialization_seeds[0]))
    receipts: list[dict[str, Any]] = []
    scores: list[EpochSelectScoreV2] = []
    snapshots: list[dict[str, torch.Tensor]] = []
    schedules: list[EpochScheduleV2] = []
    for epoch_index, item in enumerate(opened, 1):
        schedule, _ = _schedule_and_batches(
            point_values, epoch=epoch_index,
            data_order_seed=block.data_order_seeds[0], cohort="primary",
            control_name="natural", natural_values=None,
            batch_example_cap=batch_example_cap)
        if (item.receipt.model_state_sha256_before != prior_state_sha
                or item.receipt.schedule_sha256 != _training_schedule_sha(schedule)
                or item.receipt.population_sha256 != schedule.population_sha256
                or item.receipt.model_state_sha256_after !=
                model_state_sha256(item.model)
                or item.score.model_state_sha256 !=
                item.receipt.model_state_sha256_after):
            raise WorldAfterstateV2TrainingControllerError(
                "recovery history state/schedule chain drift")
        prior_state_sha = item.receipt.model_state_sha256_after
        receipts.append(item.receipt.payload())
        scores.append(item.score)
        snapshots.append(copy.deepcopy(item.model.state_dict()))
        schedules.append(schedule)
        common = _select_member_epoch(
            tuple(score.loss_nano for score in scores), block_name=block.name)
        if common.stop_epoch != epoch_index \
                or item.metadata["common_epoch_sha256"] != common.sha256():
            raise WorldAfterstateV2TrainingControllerError(
                "recovery history common decision drift")
    return opened[-1].model, opened[-1].optimizer, receipts, scores, snapshots, schedules


def train_named_cohort(
        *, cohort_name: str,
        values: Sequence[WorldAfterstateV2TrainingExample],
        freeze_sha256: str,
        config: WorldAfterstateV2TrainingConfig,
        selection_population: EpochSelectPopulationV2,
        seed_block: int = 1,
        natural_values: Sequence[WorldAfterstateV2TrainingExample] | None = None,
        member_workers: int = 1, torch_threads: int = PINNED_TORCH_THREADS,
        wall_budget_nanoseconds: int = 6 * 60 * 60 * 1_000_000_000,
        batch_example_cap: int = 256,
        optimizer_canary: Callable[[], object] | None = None,
        clock: Callable[[], int] = time.monotonic_ns,
        progress: Callable[[dict[str, Any]], None] | None = None,
        recovery_history: tuple = (),
        recovery_callback: Callable[[tuple[bytes, ...]], None] | None = None
        ) -> CohortTrainingBuildV2:
    """Train exactly one four-member natural or matched-control cohort.

    ``selection_population`` is the only permitted epoch-select input.  Its
    exact type refuses callback injection and binds every score to one sealed
    select-only root/outcome population.
    """
    _digest(freeze_sha256, "freeze SHA-256")
    config.validate()
    block = _block(seed_block)
    if cohort_name not in CONTROL_NAMES:
        raise WorldAfterstateV2TrainingControllerError("cohort name drift")
    cohort = "primary" if cohort_name == "natural" else "control"
    _validate_rows(values, cohort)
    if cohort == "control":
        _validate_rows(natural_values or (), "primary")
    if type(selection_population) is not EpochSelectPopulationV2:
        raise WorldAfterstateV2TrainingControllerError(
            "sealed epoch-select population required")
    try:
        selection_plan = selection_population._validated_plan()
        expected_selection_population_sha = selection_plan[2]
    except Exception as exc:
        raise WorldAfterstateV2TrainingControllerError(
            "epoch-select population refused") from exc
    canary_payload = None
    if optimizer_canary is not None:
        if not callable(optimizer_canary):
            raise WorldAfterstateV2TrainingControllerError("optimizer canary drift")
        try:
            canary = optimizer_canary()
            validate_optimizer_canary_v2(canary)
            if not canary.passed:
                raise WorldAfterstateV2TrainingControllerError(
                    "optimizer canary failed")
            canary_payload = canary.payload()
        except Exception as exc:
            raise WorldAfterstateV2TrainingControllerError(
                "optimizer canary refused") from exc
    if (isinstance(member_workers, bool) or member_workers not in (1, 2, 4)
            or isinstance(torch_threads, bool) or not isinstance(torch_threads, int)
            or torch_threads != PINNED_TORCH_THREADS
            or isinstance(wall_budget_nanoseconds, bool)
            or not isinstance(wall_budget_nanoseconds, int)
            or wall_budget_nanoseconds <= 0
            or isinstance(batch_example_cap, bool)
            or not isinstance(batch_example_cap, int) or batch_example_cap < 1):
        raise WorldAfterstateV2TrainingControllerError("cohort resource request drift")

    history = _validate_recovery_history_shape(recovery_history, members=4)
    if recovery_callback is not None and not callable(recovery_callback):
        raise WorldAfterstateV2TrainingControllerError("recovery callback drift")
    (models, optimizers, receipts, selection_scores, snapshots,
     schedules) = _reopen_cohort_history(
        history, values=values, natural_values=natural_values, cohort=cohort,
        cohort_name=cohort_name, freeze_sha256=freeze_sha256, config=config,
        selection_population=selection_population, seed_block=seed_block,
        block=block, batch_example_cap=batch_example_cap)
    if not history:
        models = [new_world_afterstate_v2_model(seed)
                  for seed in block.initialization_seeds]
        optimizers = [new_optimizer(model, config) for model in models]
    recovered_epochs = len(history)
    prior_common = (select_common_epoch(
        tuple(tuple(score.loss_nano for score in row)
              for row in selection_scores), block_name=block.name)
                    if recovered_epochs else None)
    started = clock()
    deadline = started + wall_budget_nanoseconds
    truncated = False
    stop_reason = "max-epochs"
    _acquire_torch_thread_scope(torch_threads)
    try:
        if history and progress is not None:
            completed = recovered_epochs * 4
            total = config.max_epochs * 4
            progress({
                "schema": PROGRESS_SCHEMA, "cohort_name": cohort_name,
                "seed_block": seed_block, "epoch": recovered_epochs,
                "completed_units": completed, "total_units": total,
                "percent_basis_points": completed * 10_000 // total,
                "elapsed_nanoseconds": 0,
                "estimated_remaining_nanoseconds": 0,
                "active_workers": member_workers,
                "audit_rows_opened": False, "report_rows_opened": False,
                "authority": dict(AUTHORITY),
            })
        resume_stopped = bool(history and prior_common is not None
                              and prior_common.stopped_for_patience)
        if resume_stopped:
            stop_reason = "early-stopping"
        for epoch in range(recovered_epochs + 1,
                           (recovered_epochs if resume_stopped else
                            min(config.max_epochs, MAX_EPOCHS)) + 1):
            if clock() >= deadline:
                if not selection_scores[0]:
                    raise WorldAfterstateV2TrainingControllerError("deadline before epoch")
                truncated = True
                stop_reason = "deadline-truncation"
                break
            def run_member(member: int):
                # Each member uses its fixed data-order stream; the common root
                # order is otherwise identical across members by construction.
                member_schedule, member_batches = _schedule_and_batches(
                    values, epoch=epoch,
                    data_order_seed=block.data_order_seeds[member],
                    cohort=cohort, control_name=cohort_name,
                    natural_values=natural_values, batch_example_cap=batch_example_cap)
                receipt = train_epoch(
                    models[member], optimizers[member], member_batches,
                    epoch=epoch, config=config)
                score = _selection_score(
                    selection_population._score_validated(
                        models[member], epoch=epoch, seed_block=seed_block,
                        member_index=member, control_name=cohort_name,
                        sigma_pair_squared=config.sigma_pair_squared,
                        plan=selection_plan),
                    model=models[member], epoch=epoch,
                    seed_block=seed_block, member_index=member,
                    control_name=cohort_name)
                if score.selection_population_sha256 != \
                        expected_selection_population_sha:
                    raise WorldAfterstateV2TrainingControllerError(
                        "epoch-select sealed population binding drift")
                return (member_schedule, receipt, score,
                        copy.deepcopy(models[member].state_dict()))

            if member_workers == 1:
                result = [run_member(member) for member in range(4)]
            else:
                with ThreadPoolExecutor(max_workers=member_workers) as pool:
                    futures = [pool.submit(run_member, member) for member in range(4)]
                    result = [future.result() for future in futures]
            # Data-order is per member, but schedule identity is part of each
            # epoch receipt.  All roots are present and no member may disappear.
            for member, (member_schedule, receipt, score, snapshot) in enumerate(result):
                receipts[member].append(receipt.payload())
                selection_scores[member].append(score)
                snapshots[member].append(snapshot)
                schedules[member].append(member_schedule)
            common = select_common_epoch(
                tuple(tuple(score.loss_nano for score in row)
                      for row in selection_scores),
                block_name=block.name)
            if recovery_callback is not None:
                try:
                    callback_raws = tuple(
                        recovery_bytes(
                            models[member], optimizers[member], config,
                            _epoch_receipt(receipts[member][-1]),
                            selection_scores[member][-1],
                            seed_block=seed_block, member_index=member,
                            control_name=cohort_name,
                            init_seed=block.initialization_seeds[member],
                            freeze_sha256=freeze_sha256,
                            common_epoch_sha256=common.sha256())
                        for member in range(4))
                    recovery_callback(callback_raws)
                except Exception as exc:
                    raise WorldAfterstateV2TrainingControllerError(
                        "recovery callback refused") from exc
            if progress is not None:
                completed = epoch * 4
                total = config.max_epochs * 4
                elapsed = max(0, clock() - started)
                remaining = max(total - completed, 0)
                eta = (elapsed * remaining + completed - 1) // completed
                progress({
                    "schema": PROGRESS_SCHEMA, "cohort_name": cohort_name,
                    "seed_block": seed_block, "epoch": epoch,
                    "completed_units": completed, "total_units": total,
                    "percent_basis_points": completed * 10_000 // total,
                    "elapsed_nanoseconds": elapsed,
                    "estimated_remaining_nanoseconds": eta,
                    "active_workers": member_workers,
                    "audit_rows_opened": False, "report_rows_opened": False,
                    "authority": dict(AUTHORITY),
                })
            if common.stopped_for_patience:
                stop_reason = "early-stopping"
                break
            if clock() >= deadline:
                truncated = True
                stop_reason = "deadline-truncation"
                break
        else:
            common = select_common_epoch(
                tuple(tuple(score.loss_nano for score in row)
                      for row in selection_scores), block_name=block.name)
    finally:
        _release_torch_thread_scope(torch_threads)

    if not selection_scores[0]:
        raise WorldAfterstateV2TrainingControllerError("cohort produced no epoch")
    selection_population_sha = selection_scores[0][0].selection_population_sha256
    if any(score.selection_population_sha256 != selection_population_sha
           for member in selection_scores for score in member):
        raise WorldAfterstateV2TrainingControllerError(
            "epoch-select population mixing")
    common = select_common_epoch(
        tuple(tuple(score.loss_nano for score in row)
              for row in selection_scores), block_name=block.name)
    population_sha = receipts[0][0]["population_sha256"]
    if any(receipt["population_sha256"] != population_sha
           for member in receipts for receipt in member):
        raise WorldAfterstateV2TrainingControllerError("cohort population drift")
    selected = common.selected_epoch - 1
    checkpoint_raws: list[bytes] = []
    member_rows = []
    common_sha = common.sha256()
    for member, (seed, model) in enumerate(zip(block.initialization_seeds, models, strict=True)):
        model.load_state_dict(snapshots[member][selected])
        raw = checkpoint_bytes(
            model, seed_block=seed_block, member_index=member,
            control_name=cohort_name, init_seed=seed,
            selected_epoch=common.selected_epoch, freeze_sha256=freeze_sha256,
            config_sha256=config.sha256(), population_sha256=population_sha,
            schedule_sha256=_training_schedule_sha(schedules[member][selected]),
            common_epoch_sha256=common_sha)
        _model, metadata = reopen_checkpoint(raw)
        checkpoint_raws.append(raw)
        member_rows.append({
            "member_index": member, "initialization_seed": seed,
            "epoch_receipts": receipts[member],
            "selection_scores": [score.payload()
                                 for score in selection_scores[member]],
            "selected_checkpoint_external_sha256": _sha_bytes(raw),
            "selected_checkpoint_sha256": metadata["checkpoint_sha256"],
            "selected_model_state_sha256": metadata["model_state_sha256"],
        })
    elapsed = max(0, clock() - started)
    body = {
        "schema": MANIFEST_SCHEMA, "cohort_name": cohort_name,
        "seed_block": seed_block, "freeze_sha256": freeze_sha256,
        "config": config.payload(), "config_sha256": config.sha256(),
        "initialization_seeds": list(block.initialization_seeds),
        "data_order_seeds": list(block.data_order_seeds), "member_count": 4,
        "member_workers": member_workers, "torch_threads": torch_threads,
        "batch_example_cap": batch_example_cap,
        "training_population_sha256": population_sha,
        "selection_population_sha256": selection_population_sha,
        "epoch_count": common.stop_epoch,
        "optimizer_canary": canary_payload,
        "fit_schedule_receipts": [
            [schedule.payload() for schedule in member_schedules[:common.stop_epoch]]
            for member_schedules in schedules],
        "common_epoch": common.payload(), "common_epoch_sha256": common_sha,
        "wall_budget_nanoseconds": wall_budget_nanoseconds,
        "elapsed_nanoseconds": elapsed,
        "truncated_by_deadline": truncated, "stop_reason": stop_reason,
        "audit_eligible": not truncated, "members": member_rows,
        "audit_rows_opened": False, "report_rows_opened": False,
        "authority": dict(AUTHORITY),
    }
    manifest = {**body, "manifest_sha256": _sha(body)}
    validate_cohort_manifest(manifest)
    return CohortTrainingBuildV2(manifest, tuple(checkpoint_raws))


def _epoch_receipt(payload: object) -> WorldAfterstateV2EpochReceipt:
    if type(payload) is not dict:
        raise WorldAfterstateV2TrainingControllerError("epoch receipt drift")
    try:
        result = WorldAfterstateV2EpochReceipt(
            epoch=payload.get("epoch"), batch_count=payload.get("batch_count"),
            example_count=payload.get("example_count"), root_count=payload.get("root_count"),
            mean_root_loss_nano=payload.get("mean_root_loss_nano"),
            config_sha256=payload.get("config_sha256"),
            population_sha256=payload.get("population_sha256"),
            schedule_sha256=payload.get("schedule_sha256"),
            model_state_sha256_before=payload.get("model_state_sha256_before"),
            model_state_sha256_after=payload.get("model_state_sha256_after"),
            split=payload.get("split"), cohort=payload.get("cohort"),
            gradient_norm_nano=payload.get("gradient_norm_nano"),
            update_norm_nano=payload.get("update_norm_nano"),
            prediction_entropy_nano=payload.get("prediction_entropy_nano"),
            paired_target_error_nano=payload.get("paired_target_error_nano"),
            schema=payload.get("schema"))
        if result.payload() != payload:
            raise ValueError
        return result
    except Exception as exc:
        raise WorldAfterstateV2TrainingControllerError("epoch receipt reconstruction drift") from exc


def _schedule_from_payload(payload: object) -> EpochScheduleV2:
    if type(payload) is not dict:
        raise WorldAfterstateV2TrainingControllerError("schedule receipt drift")
    try:
        result = EpochScheduleV2(
            epoch=payload.get("epoch"), split=payload.get("split"),
            source=payload.get("source"), cohort=payload.get("cohort"),
            control_name=payload.get("control_name"),
            control_domain=payload.get("control_domain"),
            data_order_seed=payload.get("data_order_seed"),
            batch_example_cap=payload.get("batch_example_cap"),
            population_sha256=payload.get("population_sha256"),
            ordered_root_ids=tuple(payload.get("ordered_root_ids", ())),
            batch_root_ids=tuple(tuple(item) for item in payload.get("batch_root_ids", ())),
            batch_example_keys=tuple(tuple(item) for item in payload.get("batch_example_keys", ())),
            schema=payload.get("schema"), authority=payload.get("authority"))
        if result.payload() != payload:
            raise ValueError
        return result
    except Exception as exc:
        raise WorldAfterstateV2TrainingControllerError("schedule receipt reconstruction drift") from exc


def validate_cohort_manifest(value: object) -> None:
    if type(value) is not dict or value.get("schema") != MANIFEST_SCHEMA \
            or value.get("authority") != AUTHORITY \
            or value.get("member_count") != 4 \
            or value.get("audit_rows_opened") is not False \
            or value.get("report_rows_opened") is not False:
        raise WorldAfterstateV2TrainingControllerError("cohort manifest identity drift")
    required = {
        "schema", "cohort_name", "seed_block", "freeze_sha256", "config",
        "config_sha256", "initialization_seeds", "data_order_seeds",
        "member_count", "member_workers", "torch_threads", "batch_example_cap",
        "training_population_sha256", "selection_population_sha256",
        "epoch_count", "optimizer_canary",
        "fit_schedule_receipts",
        "common_epoch", "common_epoch_sha256", "wall_budget_nanoseconds",
        "elapsed_nanoseconds", "truncated_by_deadline", "stop_reason",
        "audit_eligible", "members", "audit_rows_opened", "report_rows_opened",
        "authority", "manifest_sha256"}
    if set(value) != required:
        raise WorldAfterstateV2TrainingControllerError("cohort manifest fields drift")
    block = _block(value["seed_block"])
    if value.get("cohort_name") not in CONTROL_NAMES \
            or value.get("initialization_seeds") != list(block.initialization_seeds) \
            or value.get("data_order_seeds") != list(block.data_order_seeds) \
            or isinstance(value.get("member_workers"), bool) \
            or value.get("member_workers") not in (1, 2, 4) \
            or isinstance(value.get("torch_threads"), bool) \
            or not isinstance(value.get("torch_threads"), int) \
            or value["torch_threads"] != PINNED_TORCH_THREADS \
            or isinstance(value.get("batch_example_cap"), bool) \
            or not isinstance(value.get("batch_example_cap"), int) \
            or value["batch_example_cap"] < 1:
        raise WorldAfterstateV2TrainingControllerError(
            "cohort resource/identity drift")
    for key in ("wall_budget_nanoseconds", "elapsed_nanoseconds"):
        _strict_int(value.get(key), f"cohort {key}",
                    1 if key == "wall_budget_nanoseconds" else 0)
    if type(value.get("truncated_by_deadline")) is not bool \
            or type(value.get("audit_eligible")) is not bool:
        raise WorldAfterstateV2TrainingControllerError(
            "cohort resource route drift")
    _digest(value["freeze_sha256"], "freeze SHA-256")
    _digest(value["training_population_sha256"], "population SHA-256")
    _digest(value["selection_population_sha256"],
            "selection population SHA-256")
    _digest(value["common_epoch_sha256"], "common epoch SHA-256")
    if value["optimizer_canary"] is not None:
        try:
            from .world_afterstate_v2_diagnostics import OptimizerCanaryReceiptV2
            canary = OptimizerCanaryReceiptV2(**{
                key: value["optimizer_canary"][key]
                for key in ("source_p0_population_sha256",
                            "root_population_sha256", "model_seed", "root_count",
                            "optimizer_steps", "early_stopping_used", "gradients_finite",
                            "weights_finite", "initial_loss_nano", "empirical_loss_nano",
                            "final_loss_nano", "normalized_progress_ppm", "passed",
                            "empirical_entropy_nano", "empirical_paired_residual_nano",
                            "schema", "authority")})
            validate_optimizer_canary_v2(canary)
            if not canary.passed:
                raise ValueError
            if canary.payload() != value["optimizer_canary"]:
                raise ValueError
        except Exception as exc:
            raise WorldAfterstateV2TrainingControllerError("optimizer canary drift") from exc
    if value["config"] != WorldAfterstateV2TrainingConfig(**{
            key: value["config"][key] for key in (
                "learning_rate_ppb", "weight_decay_ppb", "gradient_norm_milli",
                "max_epochs", "sigma_pair_squared")},
            schema=value["config"].get("schema")).payload() \
            or _sha(value["config"]) != value["config_sha256"]:
        raise WorldAfterstateV2TrainingControllerError("cohort config drift")
    common_payload = value["common_epoch"]
    if type(common_payload) is not dict:
        raise WorldAfterstateV2TrainingControllerError("common epoch drift")
    common = CommonEpochDecisionV2(
        selected_epoch=common_payload.get("selected_epoch"),
        stop_epoch=common_payload.get("stop_epoch"),
        cohort_mean_loss_nano=tuple(common_payload.get("cohort_mean_loss_nano", ())),
        stopped_for_patience=common_payload.get("stopped_for_patience"),
        block_name=common_payload.get("block_name"),
        authority=common_payload.get("authority"))
    validate_common_epoch_receipt(common)
    if common.sha256() != value["common_epoch_sha256"] \
            or value["epoch_count"] != common.stop_epoch \
            or value["audit_eligible"] != (not value["truncated_by_deadline"]):
        raise WorldAfterstateV2TrainingControllerError("common epoch binding drift")
    if tuple(value["initialization_seeds"]) != block.initialization_seeds \
            or tuple(value["data_order_seeds"]) != block.data_order_seeds \
            or type(value["fit_schedule_receipts"]) is not list \
            or len(value["fit_schedule_receipts"]) != 4 \
            or value["stop_reason"] not in ("max-epochs", "early-stopping", "deadline-truncation"):
        raise WorldAfterstateV2TrainingControllerError("cohort schedule/stop drift")
    expected_stop = ("deadline-truncation" if value["truncated_by_deadline"]
                     else ("early-stopping" if common.stopped_for_patience
                           else "max-epochs"))
    if value["stop_reason"] != expected_stop:
        raise WorldAfterstateV2TrainingControllerError(
            "cohort resource route drift")
    parsed_schedules = []
    for member, member_schedules in enumerate(value["fit_schedule_receipts"]):
        if type(member_schedules) is not list or len(member_schedules) != common.stop_epoch:
            raise WorldAfterstateV2TrainingControllerError("cohort schedule drop")
        rows = []
        for epoch, schedule in enumerate(member_schedules, 1):
            parsed = _schedule_from_payload(schedule)
            if (parsed.epoch != epoch or parsed.data_order_seed != block.data_order_seeds[member]
                    or parsed.cohort != ("primary" if value["cohort_name"] == "natural" else "control")
                    or parsed.control_name != value["cohort_name"]):
                raise WorldAfterstateV2TrainingControllerError("cohort schedule binding drift")
            rows.append(parsed)
        parsed_schedules.append(rows)
    members = value["members"]
    if type(members) is not list or len(members) != 4:
        raise WorldAfterstateV2TrainingControllerError("cohort member drop")
    losses = []
    prediction_manifests: set[str] = set()
    for member, row in enumerate(members):
        if type(row) is not dict or row.get("member_index") != member \
                or row.get("initialization_seed") != block.initialization_seeds[member] \
                or type(row.get("epoch_receipts")) is not list \
                or len(row["epoch_receipts"]) != common.stop_epoch \
                or type(row.get("selection_scores")) is not list \
                or len(row["selection_scores"]) != common.stop_epoch:
            raise WorldAfterstateV2TrainingControllerError("cohort member drift")
        parsed = [_epoch_receipt(item) for item in row["epoch_receipts"]]
        member_scores = []
        for epoch, payload in enumerate(row["selection_scores"], 1):
            if type(payload) is not dict:
                raise WorldAfterstateV2TrainingControllerError(
                    "epoch-select score receipt drift")
            try:
                score = EpochSelectScoreV2(**payload)
                score.validate()
            except (TypeError, ValueError) as exc:
                raise WorldAfterstateV2TrainingControllerError(
                    "epoch-select score receipt drift") from exc
            if score.payload() != payload \
                    or (score.epoch, score.seed_block, score.member_index,
                        score.control_name) != (
                            epoch, value["seed_block"], member,
                            value["cohort_name"]) \
                    or score.selection_population_sha256 != value[
                        "selection_population_sha256"]:
                raise WorldAfterstateV2TrainingControllerError(
                    "epoch-select score receipt binding drift")
            member_scores.append(score)
            if score.prediction_manifest_sha256 in prediction_manifests:
                raise WorldAfterstateV2TrainingControllerError(
                    "epoch-select prediction manifest reuse")
            prediction_manifests.add(score.prediction_manifest_sha256)
        losses.append(tuple(score.loss_nano for score in member_scores))
        initial = new_world_afterstate_v2_model(block.initialization_seeds[member])
        if parsed[0].model_state_sha256_before != model_state_sha256(initial) \
                or any(left.model_state_sha256_after != right.model_state_sha256_before
                       for left, right in zip(parsed, parsed[1:])) \
                or any(item.config_sha256 != value["config_sha256"]
                       or item.population_sha256 != value["training_population_sha256"]
                       or item.split != "fit"
                       or item.cohort != ("primary" if value["cohort_name"] == "natural"
                                          else "control")
                       or item.schedule_sha256 != _training_schedule_sha(
                           parsed_schedules[member][index])
                       for index, item in enumerate(parsed)):
            raise WorldAfterstateV2TrainingControllerError("cohort state chain drift")
        if any(score.model_state_sha256 != parsed[index].model_state_sha256_after
               for index, score in enumerate(member_scores)):
            raise WorldAfterstateV2TrainingControllerError(
                "epoch-select score/model state chain drift")
        for key in ("selected_checkpoint_external_sha256", "selected_checkpoint_sha256",
                    "selected_model_state_sha256"):
            _digest(row.get(key), f"member {key}")
    if select_common_epoch(tuple(losses), block_name=block.name).payload() != common.payload():
        raise WorldAfterstateV2TrainingControllerError("common epoch selection drift")
    body = {key: item for key, item in value.items() if key != "manifest_sha256"}
    if value["manifest_sha256"] != _sha(body):
        raise WorldAfterstateV2TrainingControllerError("cohort manifest reconstruction drift")


def reopen_cohort_build(value: CohortTrainingBuildV2) -> tuple[tuple[WorldAfterstateValueV2, ...], dict[str, Any]]:
    if type(value) is not CohortTrainingBuildV2:
        raise WorldAfterstateV2TrainingControllerError("cohort build type drift")
    validate_cohort_manifest(value.manifest)
    if type(value.selected_checkpoint_raws) is not tuple or len(value.selected_checkpoint_raws) != 4:
        raise WorldAfterstateV2TrainingControllerError("cohort checkpoint drop")
    models = []
    common = value.manifest["common_epoch"]["selected_epoch"]
    for member, (raw, row) in enumerate(zip(value.selected_checkpoint_raws,
                                             value.manifest["members"], strict=True)):
        if type(raw) is not bytes or _sha_bytes(raw) != row["selected_checkpoint_external_sha256"]:
            raise WorldAfterstateV2TrainingControllerError("checkpoint external binding drift")
        try:
            model, metadata = reopen_checkpoint(raw)
        except Exception as exc:
            raise WorldAfterstateV2TrainingControllerError("checkpoint reopen refused") from exc
        if metadata["member_index"] != member or metadata["seed_block"] != value.manifest["seed_block"] \
                or metadata["control_name"] != value.manifest["cohort_name"] \
                or metadata["init_seed"] != value.manifest[
                    "initialization_seeds"][member] \
                or metadata["selected_epoch"] != common \
                or metadata["freeze_sha256"] != value.manifest["freeze_sha256"] \
                or metadata["config_sha256"] != value.manifest["config_sha256"] \
                or metadata["population_sha256"] != value.manifest["training_population_sha256"] \
                or metadata["schedule_sha256"] != _training_schedule_sha(
                    _schedule_from_payload(value.manifest[
                        "fit_schedule_receipts"][member][common - 1])) \
                or metadata["common_epoch_sha256"] != value.manifest["common_epoch_sha256"] \
                or metadata["checkpoint_sha256"] != row["selected_checkpoint_sha256"] \
                or metadata["model_state_sha256"] != row["selected_model_state_sha256"]:
            raise WorldAfterstateV2TrainingControllerError("checkpoint metadata binding drift")
        selected_receipt = value.manifest["members"][member]["epoch_receipts"][common - 1]
        if selected_receipt["model_state_sha256_after"] != metadata["model_state_sha256"]:
            raise WorldAfterstateV2TrainingControllerError("selected state binding drift")
        models.append(model)
    return tuple(models), value.manifest


def _select_member_epoch(losses: Sequence[int], *, block_name: str) -> CommonEpochDecisionV2:
    """Apply the reviewed common-epoch rule to one member's losses."""
    if type(losses) not in (tuple, list) or not losses or len(losses) > MAX_EPOCHS:
        raise WorldAfterstateV2TrainingControllerError("member epoch-select metrics drift")
    if any(isinstance(loss, bool) or not isinstance(loss, int) or loss < 0
           for loss in losses):
        raise WorldAfterstateV2TrainingControllerError("member epoch-select loss drift")
    best = min(range(len(losses)), key=lambda index: (losses[index], index))
    stale = 0
    stop = len(losses)
    stopped = False
    incumbent = losses[0]
    for index in range(1, len(losses)):
        if losses[index] < incumbent:
            incumbent = losses[index]
            stale = 0
        else:
            stale += 1
            if stale == EARLY_STOP_PATIENCE:
                stop = index + 1
                stopped = True
                break
    if best >= stop:
        best = min(range(stop), key=lambda index: (losses[index], index))
    result = CommonEpochDecisionV2(
        selected_epoch=best + 1, stop_epoch=stop,
        cohort_mean_loss_nano=tuple(losses[:stop]),
        stopped_for_patience=stopped, block_name=block_name)
    try:
        result.validate()
    except Exception as exc:
        raise WorldAfterstateV2TrainingControllerError(
            "member common epoch receipt drift") from exc
    return result


def _member_fraction(value: object) -> tuple[float, int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WorldAfterstateV2TrainingControllerError("nested data fraction drift")
    if value == 0.25:
        return 0.25, 250_000
    if value == 0.5:
        return 0.5, 500_000
    raise WorldAfterstateV2TrainingControllerError(
        "single-member data fraction must be 25% or 50%")


def train_named_member(
        *, values: Sequence[WorldAfterstateV2TrainingExample],
        data_fraction: float | None = None, fraction: float | None = None,
        data_fraction_ppm: int | None = None,
        member_name: str | None = None,
        freeze_sha256: str, config: WorldAfterstateV2TrainingConfig,
        selection_population: EpochSelectPopulationV2,
        seed_block: int = 1, member_index: int = 0,
        cohort_name: str = "natural", member_workers: int = 1,
        torch_threads: int = PINNED_TORCH_THREADS,
        wall_budget_nanoseconds: int = 6 * 60 * 60 * 1_000_000_000,
        batch_example_cap: int = 256,
        clock: Callable[[], int] = time.monotonic_ns,
        progress: Callable[[dict[str, Any]], None] | None = None,
        recovery_history: tuple = (),
        recovery_callback: Callable[[bytes], None] | None = None
        ) -> SingleMemberTrainingBuildV2:
    """Train one fixed-seed natural member for the nested 25%/50% curve.

    ``values`` is the complete fit population.  The selected point is always
    rederived by the canonical, source/stratum-preserving deal-hash prefix.
    """
    _digest(freeze_sha256, "freeze SHA-256")
    config.validate()
    block = _block(seed_block)
    if seed_block != 1:
        raise WorldAfterstateV2TrainingControllerError(
            "single-member diagnostic requires primary seed block")
    if cohort_name != "natural":
        raise WorldAfterstateV2TrainingControllerError(
            "single-member natural cohort required")
    if isinstance(member_index, bool) or not isinstance(member_index, int) \
            or member_index != 0:
        raise WorldAfterstateV2TrainingControllerError("member index drift")
    if data_fraction is not None and fraction is not None:
        raise WorldAfterstateV2TrainingControllerError("nested data fraction alias drift")
    if data_fraction is None:
        data_fraction = fraction
    if data_fraction is None and data_fraction_ppm is None:
        if member_name == "nested-curve-25":
            data_fraction = 0.25
        elif member_name == "nested-curve-50":
            data_fraction = 0.5
        else:
            raise WorldAfterstateV2TrainingControllerError("nested data fraction required")
    if data_fraction is not None:
        selected_fraction, fraction_ppm = _member_fraction(data_fraction)
        if data_fraction_ppm is not None and data_fraction_ppm != fraction_ppm:
            raise WorldAfterstateV2TrainingControllerError("nested data fraction drift")
    else:
        if isinstance(data_fraction_ppm, bool) or data_fraction_ppm not in (250_000, 500_000):
            raise WorldAfterstateV2TrainingControllerError("nested data fraction drift")
        fraction_ppm = data_fraction_ppm
        selected_fraction = fraction_ppm / 1_000_000
    canonical_member_name = f"nested-curve-{fraction_ppm // 10_000}"
    if member_name is not None and member_name != canonical_member_name:
        raise WorldAfterstateV2TrainingControllerError("nested member name drift")
    if type(values) not in (tuple, list):
        raise WorldAfterstateV2TrainingControllerError("cohort population drift")
    _validate_rows(values, "primary")
    try:
        prefixes = derive_nested_prefixes(tuple(values))
        point_values = prefixes[selected_fraction]
    except Exception as exc:
        raise WorldAfterstateV2TrainingControllerError(
            "nested data prefix refused") from exc
    if type(selection_population) is not EpochSelectPopulationV2:
        raise WorldAfterstateV2TrainingControllerError(
            "sealed epoch-select population required")
    try:
        selection_plan = selection_population._validated_plan()
        expected_selection_population_sha = selection_plan[2]
    except Exception as exc:
        raise WorldAfterstateV2TrainingControllerError(
            "epoch-select population refused") from exc
    if (isinstance(member_workers, bool) or member_workers != 1
            or isinstance(torch_threads, bool) or not isinstance(torch_threads, int)
            or torch_threads != PINNED_TORCH_THREADS
            or isinstance(wall_budget_nanoseconds, bool)
            or not isinstance(wall_budget_nanoseconds, int)
            or wall_budget_nanoseconds <= 0
            or isinstance(batch_example_cap, bool)
            or not isinstance(batch_example_cap, int) or batch_example_cap < 1):
        raise WorldAfterstateV2TrainingControllerError("member resource request drift")

    initialization_seed = block.initialization_seeds[member_index]
    data_order_seed = block.data_order_seeds[member_index]
    history = _validate_recovery_history_shape(recovery_history, members=1)
    if recovery_callback is not None and not callable(recovery_callback):
        raise WorldAfterstateV2TrainingControllerError("recovery callback drift")
    (model, optimizer, receipts, selection_scores, snapshots,
     schedules) = _reopen_member_history(
        history, values=values, point_values=point_values,
        freeze_sha256=freeze_sha256, config=config,
        selection_population=selection_population, block=block,
        batch_example_cap=batch_example_cap)
    if model is None or optimizer is None:
        model = new_world_afterstate_v2_model(initialization_seed)
        optimizer = new_optimizer(model, config)
    recovered_epochs = len(history)
    prior_decision = (_select_member_epoch(
        tuple(item.loss_nano for item in selection_scores), block_name=block.name)
                      if recovered_epochs else None)
    started = clock()
    deadline = started + wall_budget_nanoseconds
    truncated = False
    stop_reason = "max-epochs"
    _acquire_torch_thread_scope(torch_threads)
    try:
        if history and progress is not None:
            completed = recovered_epochs
            total = config.max_epochs
            progress({
                "schema": PROGRESS_SCHEMA, "cohort_name": "natural",
                "data_fraction_ppm": fraction_ppm, "seed_block": seed_block,
                "member_index": member_index, "epoch": recovered_epochs,
                "completed_units": completed, "total_units": total,
                "percent_basis_points": completed * 10_000 // total,
                "elapsed_nanoseconds": 0,
                "estimated_remaining_nanoseconds": 0,
                "active_workers": member_workers,
                "audit_rows_opened": False, "report_rows_opened": False,
                "authority": dict(AUTHORITY),
            })
        resume_stopped = bool(history and prior_decision is not None
                              and prior_decision.stopped_for_patience)
        if resume_stopped:
            stop_reason = "early-stopping"
        for epoch in range(recovered_epochs + 1,
                           (recovered_epochs if resume_stopped else
                            min(config.max_epochs, MAX_EPOCHS)) + 1):
            if clock() >= deadline:
                if not selection_scores:
                    raise WorldAfterstateV2TrainingControllerError("deadline before epoch")
                truncated = True
                stop_reason = "deadline-truncation"
                break
            schedule, batches = _schedule_and_batches(
                point_values, epoch=epoch, data_order_seed=data_order_seed,
                cohort="primary", control_name="natural", natural_values=None,
                batch_example_cap=batch_example_cap)
            receipt = train_epoch(model, optimizer, batches, epoch=epoch, config=config)
            score = _selection_score(
                selection_population._score_validated(
                    model, epoch=epoch, seed_block=seed_block,
                    member_index=member_index, control_name="natural",
                    sigma_pair_squared=config.sigma_pair_squared,
                    plan=selection_plan),
                model=model, epoch=epoch, seed_block=seed_block,
                member_index=member_index, control_name="natural")
            if score.selection_population_sha256 != \
                    expected_selection_population_sha:
                raise WorldAfterstateV2TrainingControllerError(
                    "epoch-select sealed population binding drift")
            receipts.append(receipt.payload())
            selection_scores.append(score)
            snapshots.append(copy.deepcopy(model.state_dict()))
            schedules.append(schedule)
            decision = _select_member_epoch(
                tuple(item.loss_nano for item in selection_scores),
                block_name=block.name)
            if recovery_callback is not None:
                try:
                    recovery_callback(recovery_bytes(
                        model, optimizer, config, _epoch_receipt(receipts[-1]),
                        selection_scores[-1], seed_block=seed_block,
                        member_index=member_index, control_name="natural",
                        init_seed=initialization_seed,
                        freeze_sha256=freeze_sha256,
                        common_epoch_sha256=decision.sha256()))
                except Exception as exc:
                    raise WorldAfterstateV2TrainingControllerError(
                        "recovery callback refused") from exc
            if progress is not None:
                completed = epoch
                total = config.max_epochs
                elapsed = max(0, clock() - started)
                remaining = max(total - completed, 0)
                eta = (elapsed * remaining + completed - 1) // completed
                progress({
                    "schema": PROGRESS_SCHEMA, "cohort_name": "natural",
                    "data_fraction_ppm": fraction_ppm, "seed_block": seed_block,
                    "member_index": member_index, "epoch": epoch,
                    "completed_units": completed, "total_units": total,
                    "percent_basis_points": completed * 10_000 // total,
                    "elapsed_nanoseconds": elapsed,
                    "estimated_remaining_nanoseconds": eta,
                    "active_workers": member_workers,
                    "audit_rows_opened": False, "report_rows_opened": False,
                    "authority": dict(AUTHORITY),
                })
            if decision.stopped_for_patience:
                stop_reason = "early-stopping"
                break
            if clock() >= deadline:
                truncated = True
                stop_reason = "deadline-truncation"
                break
    finally:
        _release_torch_thread_scope(torch_threads)
    if not selection_scores:
        raise WorldAfterstateV2TrainingControllerError("member produced no epoch")
    decision = _select_member_epoch(
        tuple(item.loss_nano for item in selection_scores), block_name=block.name)
    population_sha = receipts[0]["population_sha256"]
    if any(item["population_sha256"] != population_sha for item in receipts):
        raise WorldAfterstateV2TrainingControllerError("member population drift")
    common_sha = decision.sha256()
    selected = decision.selected_epoch - 1
    model.load_state_dict(snapshots[selected])
    raw = checkpoint_bytes(
        model, seed_block=seed_block, member_index=member_index,
        control_name="natural", init_seed=initialization_seed,
        selected_epoch=decision.selected_epoch, freeze_sha256=freeze_sha256,
        config_sha256=config.sha256(), population_sha256=population_sha,
        schedule_sha256=_training_schedule_sha(schedules[selected]),
        common_epoch_sha256=common_sha)
    _model, metadata = reopen_checkpoint(raw)
    elapsed = max(0, clock() - started)
    body = {
        "schema": SINGLE_MEMBER_MANIFEST_SCHEMA, "cohort_name": "natural",
        "member_name": canonical_member_name,
        "data_fraction": selected_fraction, "data_fraction_ppm": fraction_ppm,
        "seed_block": seed_block, "member_index": member_index,
        "freeze_sha256": freeze_sha256, "config": config.payload(),
        "config_sha256": config.sha256(), "initialization_seed": initialization_seed,
        "data_order_seed": data_order_seed, "member_count": 1,
        "member_workers": member_workers, "torch_threads": torch_threads,
        "batch_example_cap": batch_example_cap,
        "training_population_sha256": population_sha,
        "selection_population_sha256": selection_scores[0].selection_population_sha256,
        "epoch_count": decision.stop_epoch,
        "fit_schedule_receipts": [schedule.payload() for schedule in schedules],
        "epoch_receipts": receipts,
        "selection_scores": [score.payload() for score in selection_scores],
        "common_epoch": decision.payload(), "common_epoch_sha256": common_sha,
        "wall_budget_nanoseconds": wall_budget_nanoseconds,
        "elapsed_nanoseconds": elapsed, "truncated_by_deadline": truncated,
        "stop_reason": stop_reason, "audit_eligible": False,
        "consumer_eligible": False,
        "selected_checkpoint_external_sha256": _sha_bytes(raw),
        "selected_checkpoint_sha256": metadata["checkpoint_sha256"],
        "selected_model_state_sha256": metadata["model_state_sha256"],
        "audit_rows_opened": False, "report_rows_opened": False,
        "authority": dict(AUTHORITY),
    }
    manifest = {**body, "manifest_sha256": _sha(body)}
    validate_member_manifest(manifest)
    return SingleMemberTrainingBuildV2(manifest, raw)


def validate_member_manifest(value: object) -> None:
    """Fail closed on a single-member manifest, including all receipt chains."""
    required = {
        "schema", "cohort_name", "member_name", "data_fraction", "data_fraction_ppm",
        "seed_block", "member_index", "freeze_sha256", "config",
        "config_sha256", "initialization_seed", "data_order_seed", "member_count",
        "member_workers", "torch_threads", "batch_example_cap",
        "training_population_sha256", "selection_population_sha256", "epoch_count",
        "fit_schedule_receipts", "epoch_receipts", "selection_scores", "common_epoch",
        "common_epoch_sha256", "wall_budget_nanoseconds", "elapsed_nanoseconds",
        "truncated_by_deadline", "stop_reason", "audit_eligible",
        "consumer_eligible",
        "selected_checkpoint_external_sha256", "selected_checkpoint_sha256",
        "selected_model_state_sha256", "audit_rows_opened", "report_rows_opened",
        "authority", "manifest_sha256"}
    if type(value) is not dict or set(value) != required \
            or value.get("schema") != SINGLE_MEMBER_MANIFEST_SCHEMA \
            or value.get("cohort_name") != "natural" \
            or value.get("member_name") != f"nested-curve-{value.get('data_fraction_ppm', 0) // 10_000}" \
            or value.get("authority") != AUTHORITY \
            or value.get("member_count") != 1 \
            or value.get("audit_rows_opened") is not False \
            or value.get("report_rows_opened") is not False \
            or value.get("audit_eligible") is not False \
            or value.get("consumer_eligible") is not False:
        raise WorldAfterstateV2TrainingControllerError("member manifest identity drift")
    block = _block(value["seed_block"])
    if value["seed_block"] != 1:
        raise WorldAfterstateV2TrainingControllerError(
            "single-member diagnostic requires primary seed block")
    if (value["initialization_seed"] != block.initialization_seeds[value["member_index"]]
            if isinstance(value.get("member_index"), int) and not isinstance(
                value.get("member_index"), bool) and 0 <= value["member_index"] < 4 else True):
        raise WorldAfterstateV2TrainingControllerError("member seed binding drift")
    member = value["member_index"]
    if isinstance(member, bool) or not isinstance(member, int) or member != 0 \
            or value["data_order_seed"] != block.data_order_seeds[member]:
        raise WorldAfterstateV2TrainingControllerError("member seed binding drift")
    fraction, fraction_ppm = _member_fraction(value["data_fraction"])
    if value["data_fraction_ppm"] != fraction_ppm or value["data_fraction"] != fraction:
        raise WorldAfterstateV2TrainingControllerError("nested data fraction drift")
    for key in ("initialization_seed", "data_order_seed"):
        _strict_int(value[key], f"member {key}")
    if (isinstance(value.get("member_workers"), bool)
            or value.get("member_workers") != 1
            or isinstance(value.get("torch_threads"), bool)
            or not isinstance(value.get("torch_threads"), int)
            or value["torch_threads"] != PINNED_TORCH_THREADS
            or isinstance(value.get("batch_example_cap"), bool)
            or not isinstance(value.get("batch_example_cap"), int)
            or value["batch_example_cap"] < 1):
        raise WorldAfterstateV2TrainingControllerError("member resource/identity drift")
    for key in ("wall_budget_nanoseconds", "elapsed_nanoseconds"):
        _strict_int(value.get(key), f"member {key}",
                    1 if key == "wall_budget_nanoseconds" else 0)
    if type(value["truncated_by_deadline"]) is not bool \
            or type(value["audit_eligible"]) is not bool \
            or type(value["consumer_eligible"]) is not bool:
        raise WorldAfterstateV2TrainingControllerError("member resource route drift")
    _digest(value["freeze_sha256"], "freeze SHA-256")
    _digest(value["training_population_sha256"], "member population SHA-256")
    _digest(value["selection_population_sha256"], "selection population SHA-256")
    _digest(value["common_epoch_sha256"], "common epoch SHA-256")
    try:
        config = WorldAfterstateV2TrainingConfig(**{
            key: value["config"][key] for key in (
                "learning_rate_ppb", "weight_decay_ppb", "gradient_norm_milli",
                "max_epochs", "sigma_pair_squared")},
            schema=value["config"].get("schema"))
        config.validate()
    except Exception as exc:
        raise WorldAfterstateV2TrainingControllerError("member config drift") from exc
    if value["config"] != config.payload() or value["config_sha256"] != config.sha256():
        raise WorldAfterstateV2TrainingControllerError("member config drift")
    try:
        common_payload = value["common_epoch"]
        common = CommonEpochDecisionV2(
            selected_epoch=common_payload.get("selected_epoch"),
            stop_epoch=common_payload.get("stop_epoch"),
            cohort_mean_loss_nano=tuple(common_payload.get("cohort_mean_loss_nano", ())),
            stopped_for_patience=common_payload.get("stopped_for_patience"),
            block_name=common_payload.get("block_name"),
            authority=common_payload.get("authority"))
        validate_common_epoch_receipt(common)
    except Exception as exc:
        raise WorldAfterstateV2TrainingControllerError("member common epoch drift") from exc
    if (common.payload() != value["common_epoch"]
            or common.sha256() != value["common_epoch_sha256"]
            or value["epoch_count"] != common.stop_epoch
            or value["stop_reason"] not in (
                "max-epochs", "early-stopping", "deadline-truncation")):
        raise WorldAfterstateV2TrainingControllerError("member common epoch binding drift")
    expected_stop = ("deadline-truncation" if value["truncated_by_deadline"] else
                     ("early-stopping" if common.stopped_for_patience else "max-epochs"))
    if value["stop_reason"] != expected_stop:
        raise WorldAfterstateV2TrainingControllerError("member resource route drift")
    schedules = value["fit_schedule_receipts"]
    receipts = value["epoch_receipts"]
    scores = value["selection_scores"]
    if (type(schedules) is not list or len(schedules) != common.stop_epoch
            or type(receipts) is not list or len(receipts) != common.stop_epoch
            or type(scores) is not list or len(scores) != common.stop_epoch):
        raise WorldAfterstateV2TrainingControllerError("member epoch receipt drop")
    parsed_schedules: list[EpochScheduleV2] = []
    parsed_receipts: list[WorldAfterstateV2EpochReceipt] = []
    parsed_scores: list[EpochSelectScoreV2] = []
    for epoch, payload in enumerate(schedules, 1):
        parsed = _schedule_from_payload(payload)
        try:
            parsed.validate()
        except Exception as exc:
            raise WorldAfterstateV2TrainingControllerError("member schedule receipt drift") from exc
        if (parsed.epoch != epoch or parsed.data_order_seed != value["data_order_seed"]
                or parsed.cohort != "primary" or parsed.control_name != "natural"
                or parsed.split != "fit"):
            raise WorldAfterstateV2TrainingControllerError("member schedule binding drift")
        parsed_schedules.append(parsed)
    for epoch, payload in enumerate(receipts, 1):
        parsed = _epoch_receipt(payload)
        if (parsed.epoch != epoch or parsed.config_sha256 != value["config_sha256"]
                or parsed.population_sha256 != value["training_population_sha256"]
                or parsed.split != "fit" or parsed.cohort != "primary"
                or parsed.schedule_sha256 != _training_schedule_sha(parsed_schedules[epoch - 1])):
            raise WorldAfterstateV2TrainingControllerError("member state chain drift")
        parsed_receipts.append(parsed)
    initial = new_world_afterstate_v2_model(value["initialization_seed"])
    if (parsed_receipts[0].model_state_sha256_before != model_state_sha256(initial)
            or any(left.model_state_sha256_after != right.model_state_sha256_before
                   for left, right in zip(parsed_receipts, parsed_receipts[1:]))):
        raise WorldAfterstateV2TrainingControllerError("member state chain drift")
    losses = []
    for epoch, payload in enumerate(scores, 1):
        if type(payload) is not dict:
            raise WorldAfterstateV2TrainingControllerError("epoch-select score receipt drift")
        try:
            score = EpochSelectScoreV2(**payload)
            score.validate()
        except Exception as exc:
            raise WorldAfterstateV2TrainingControllerError("epoch-select score receipt drift") from exc
        if (score.payload() != payload or
                (score.epoch, score.seed_block, score.member_index, score.control_name) !=
                (epoch, value["seed_block"], member, "natural") or
                score.selection_population_sha256 != value["selection_population_sha256"]
                or score.model_state_sha256 != parsed_receipts[epoch - 1].model_state_sha256_after):
            raise WorldAfterstateV2TrainingControllerError("epoch-select score/model state chain drift")
        parsed_scores.append(score)
        losses.append(score.loss_nano)
    if _select_member_epoch(tuple(losses), block_name=block.name).payload() != common.payload():
        raise WorldAfterstateV2TrainingControllerError("member epoch selection drift")
    for key in ("selected_checkpoint_external_sha256", "selected_checkpoint_sha256",
                "selected_model_state_sha256"):
        _digest(value[key], f"member {key}")
    body = {key: item for key, item in value.items() if key != "manifest_sha256"}
    if value["manifest_sha256"] != _sha(body):
        raise WorldAfterstateV2TrainingControllerError("member manifest reconstruction drift")


def reopen_member_build(value: SingleMemberTrainingBuildV2) -> tuple[WorldAfterstateValueV2, dict[str, Any]]:
    if type(value) is not SingleMemberTrainingBuildV2:
        raise WorldAfterstateV2TrainingControllerError("member build type drift")
    validate_member_manifest(value.manifest)
    raw = value.selected_checkpoint_raw
    if type(raw) is not bytes or _sha_bytes(raw) != value.manifest[
            "selected_checkpoint_external_sha256"]:
        raise WorldAfterstateV2TrainingControllerError("checkpoint external binding drift")
    try:
        model, metadata = reopen_checkpoint(raw)
    except Exception as exc:
        raise WorldAfterstateV2TrainingControllerError("checkpoint reopen refused") from exc
    selected = value.manifest["common_epoch"]["selected_epoch"]
    schedule = _schedule_from_payload(value.manifest["fit_schedule_receipts"][selected - 1])
    expected = {
        "member_index": value.manifest["member_index"],
        "seed_block": value.manifest["seed_block"], "control_name": "natural",
        "init_seed": value.manifest["initialization_seed"], "selected_epoch": selected,
        "freeze_sha256": value.manifest["freeze_sha256"],
        "config_sha256": value.manifest["config_sha256"],
        "population_sha256": value.manifest["training_population_sha256"],
        "schedule_sha256": _training_schedule_sha(schedule),
        "common_epoch_sha256": value.manifest["common_epoch_sha256"],
    }
    if any(metadata[key] != actual for key, actual in expected.items()) \
            or metadata["checkpoint_sha256"] != value.manifest["selected_checkpoint_sha256"] \
            or metadata["model_state_sha256"] != value.manifest["selected_model_state_sha256"]:
        raise WorldAfterstateV2TrainingControllerError("checkpoint metadata binding drift")
    if value.manifest["epoch_receipts"][selected - 1][
            "model_state_sha256_after"] != metadata["model_state_sha256"]:
        raise WorldAfterstateV2TrainingControllerError("selected state binding drift")
    return model, value.manifest


# Explicit aliases make the typed primitive discoverable without introducing a
# second implementation or an alternate control/audit route.
validate_single_member_manifest = validate_member_manifest
reopen_single_member_build = reopen_member_build
train_named_single_member = train_named_member


__all__ = [
    "AUTHORITY", "CohortTrainingBuildV2", "EpochSelectScoreV2",
    "MANIFEST_SCHEMA", "SINGLE_MEMBER_MANIFEST_SCHEMA",
    "SingleMemberTrainingBuildV2", "WorldAfterstateV2TrainingControllerError",
    "reopen_cohort_build", "reopen_member_build", "reopen_single_member_build",
    "train_named_cohort", "train_named_member", "train_named_single_member",
    "validate_cohort_manifest", "validate_member_manifest",
    "validate_single_member_manifest",
]
