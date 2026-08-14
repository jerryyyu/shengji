"""Deterministic round-grouped schedule and common-epoch selection for B2.

The scheduler authenticates every privileged training example against its
exact paired corpus bytes, never splits one round across batches, and derives
epoch order without mutable RNG state.  Common-epoch selection consumes only
integer cohort calibration losses.  It does not train a model, read files,
write checkpoints, open the test split, or authorize execution.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .belief_b2_protocol import (
    TRAIN_BATCH_DECISION_CAP,
    TRAIN_EARLY_STOP_PATIENCE,
    TRAIN_MAX_EPOCHS,
    TRAIN_MIN_IMPROVEMENT_NANONATS,
    protocol_sha256,
)
from .belief_cohort import COHORT_SEEDS
from .belief_corpus import CorpusPairV1
from .belief_training import (
    BeliefTrainingBatchV1,
    BeliefTrainingError,
    BeliefTrainingExampleV1,
    collate_training_examples,
    validate_training_example,
)


SCHEDULE_SCHEMA = "belief-v1-b2-round-grouped-training-schedule-v1"
EARLY_STOP_SCHEMA = "belief-v1-b2-common-epoch-selection-v1"


class BeliefTrainingScheduleError(ValueError):
    """The fixed B2 batch schedule or common-epoch decision drifted."""


@dataclass(frozen=True)
class BoundTrainingExampleV1:
    pair: CorpusPairV1
    example: BeliefTrainingExampleV1


@dataclass(frozen=True)
class EpochScheduleV1:
    epoch: int
    ordered_round_seeds: tuple[int, ...]
    batch_decision_keys: tuple[tuple[str, ...], ...]
    schema: str = SCHEDULE_SCHEMA


@dataclass(frozen=True)
class CommonEpochDecisionV1:
    selected_epoch: int
    stop_epoch: int
    cohort_mean_loss_nanonats: tuple[int, ...]
    stopped_for_patience: bool
    schema: str = EARLY_STOP_SCHEMA


def _round_order_key(epoch: int, round_seed: int) -> bytes:
    return hashlib.sha256(
        f"{protocol_sha256()}|epoch-{epoch}|{round_seed}".encode("ascii")
    ).digest()


def ordered_round_seeds_for_epoch(
        round_seeds: tuple[int, ...], *, epoch: int) -> tuple[int, ...]:
    """Return the frozen epoch order without loading decision tensors."""
    if type(epoch) is not int or not 1 <= epoch <= TRAIN_MAX_EPOCHS:
        raise BeliefTrainingScheduleError("training epoch is invalid")
    if type(round_seeds) is not tuple or not round_seeds \
            or any(type(seed) is not int or seed < 0 for seed in round_seeds) \
            or len(round_seeds) != len(set(round_seeds)):
        raise BeliefTrainingScheduleError(
            "training schedule round population is malformed")
    return tuple(sorted(
        round_seeds, key=lambda seed: (_round_order_key(epoch, seed), seed)))


def training_epoch_batches(
        bound_examples: tuple[BoundTrainingExampleV1, ...], *,
        epoch: int) -> tuple[EpochScheduleV1,
                             tuple[BeliefTrainingBatchV1, ...]]:
    """Authenticate, group, order, and collate one deterministic train epoch."""
    if type(epoch) is not int or not 1 <= epoch <= TRAIN_MAX_EPOCHS:
        raise BeliefTrainingScheduleError("training epoch is invalid")
    if type(bound_examples) is not tuple or not bound_examples \
            or any(type(item) is not BoundTrainingExampleV1
                   for item in bound_examples):
        raise BeliefTrainingScheduleError(
            "training schedule population is malformed")
    groups: dict[int, list[BeliefTrainingExampleV1]] = {}
    seen = set()
    for item in bound_examples:
        try:
            validate_training_example(item.pair, item.example)
        except (BeliefTrainingError, ValueError) as exc:
            raise BeliefTrainingScheduleError(
                "training schedule example refused") from exc
        example = item.example
        if example.split != "train":
            raise BeliefTrainingScheduleError(
                "training schedule contains a non-train example")
        if example.decision_key in seen:
            raise BeliefTrainingScheduleError(
                "training schedule has a duplicate decision")
        seen.add(example.decision_key)
        groups.setdefault(example.round_seed, []).append(example)
    for round_seed, rows in groups.items():
        rows.sort(key=lambda row: row.decision_index)
        if tuple(row.decision_index for row in rows) != tuple(
                range(len(rows))):
            raise BeliefTrainingScheduleError(
                "training schedule round decision sequence drift")
        if len(rows) > TRAIN_BATCH_DECISION_CAP:
            raise BeliefTrainingScheduleError(
                "training round exceeds batch decision cap")
    round_order = ordered_round_seeds_for_epoch(
        tuple(groups), epoch=epoch)
    grouped_batches: list[tuple[BeliefTrainingExampleV1, ...]] = []
    pending: list[BeliefTrainingExampleV1] = []
    for seed in round_order:
        rows = groups[seed]
        if pending and len(pending) + len(rows) > TRAIN_BATCH_DECISION_CAP:
            grouped_batches.append(tuple(pending))
            pending = []
        pending.extend(rows)
    if pending:
        grouped_batches.append(tuple(pending))
    batches = tuple(collate_training_examples(rows)
                    for rows in grouped_batches)
    schedule = EpochScheduleV1(
        epoch=epoch, ordered_round_seeds=round_order,
        batch_decision_keys=tuple(batch.decision_keys for batch in batches))
    if tuple(key for batch in schedule.batch_decision_keys for key in batch) \
            != tuple(example.decision_key for rows in grouped_batches
                     for example in rows):
        raise BeliefTrainingScheduleError("training batch schedule drift")
    return schedule, batches


def select_common_epoch(
        loss_nanonats_by_member: tuple[tuple[int, ...], ...]) \
        -> CommonEpochDecisionV1:
    """Apply one common cohort-mean early-stop epoch to all eight members."""
    if type(loss_nanonats_by_member) is not tuple \
            or len(loss_nanonats_by_member) != len(COHORT_SEEDS) \
            or any(type(row) is not tuple for row in loss_nanonats_by_member):
        raise BeliefTrainingScheduleError(
            "calibration loss cohort population drift")
    lengths = {len(row) for row in loss_nanonats_by_member}
    if len(lengths) != 1:
        raise BeliefTrainingScheduleError("calibration loss epoch count drift")
    epoch_count = next(iter(lengths))
    if not 1 <= epoch_count <= TRAIN_MAX_EPOCHS \
            or any(type(value) is not int or value < 0
                   for row in loss_nanonats_by_member for value in row):
        raise BeliefTrainingScheduleError("calibration loss value drift")
    mean_losses = tuple(
        sum(row[epoch] for row in loss_nanonats_by_member)
        // len(COHORT_SEEDS) for epoch in range(epoch_count))
    selected = 1
    best_sum = sum(row[0] for row in loss_nanonats_by_member)
    stale = 0
    stop = epoch_count
    stopped_for_patience = False
    for epoch_index in range(1, epoch_count):
        current_sum = sum(row[epoch_index]
                          for row in loss_nanonats_by_member)
        if best_sum - current_sum >= (
                TRAIN_MIN_IMPROVEMENT_NANONATS * len(COHORT_SEEDS)):
            best_sum = current_sum
            selected = epoch_index + 1
            stale = 0
        else:
            stale += 1
            if stale == TRAIN_EARLY_STOP_PATIENCE:
                stop = epoch_index + 1
                stopped_for_patience = True
                break
    return CommonEpochDecisionV1(
        selected_epoch=selected, stop_epoch=stop,
        cohort_mean_loss_nanonats=mean_losses[:stop],
        stopped_for_patience=stopped_for_patience)
