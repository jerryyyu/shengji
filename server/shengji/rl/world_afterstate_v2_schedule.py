"""Outcome-blind, root-grouped training schedules for Value-Afterstate V2.

This module is intentionally a scheduler, not a trainer.  It consumes the
identity portion of :class:`WorldAfterstateV2TrainingExample` and delegates
the complete-sibling check and tensor collation to the existing training
contract.  Labels, tensors, audit payloads, and predictions do not influence
an order, prefix, receipt, or epoch decision.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .belief_contract import canonical_json_bytes
from .world_afterstate_v2_training import (
    COHORTS, WorldAfterstateV2TrainingBatch,
    WorldAfterstateV2TrainingError, WorldAfterstateV2TrainingExample,
    collate_training_examples,
)
from .world_afterstate_v2_protocol import STATE_SOURCES


SCHEDULE_SCHEMA = "world-afterstate-v2-root-grouped-training-schedule-v1"
RECEIPT_SCHEMA = "world-afterstate-v2-training-schedule-receipt-v1"
COMMON_EPOCH_SCHEMA = "world-afterstate-v2-common-epoch-selection-v1"
SEED_BLOCK_SCHEMA = "world-afterstate-v2-training-seed-block-v1"
PREFIX_SCHEMA = "world-afterstate-v2-canonical-deal-prefix-v1"
MAX_EPOCHS = 20
EARLY_STOP_PATIENCE = 3
DEFAULT_BATCH_EXAMPLE_CAP = 256
MAX_SEED = (1 << 63) - 1
CONTROL_DOMAIN = "world-afterstate-v2-natural-matched-v1"
AUTHORITY = {
    "training_authorized": False,
    "audit_opening_authorized": False,
    "prediction_authorized": False,
    "block_2_prediction_authorized": False,
}


class WorldAfterstateV2ScheduleError(ValueError):
    """A V2 schedule, seed block, prefix, or common epoch drifted."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(
            char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV2ScheduleError(f"{label} drift")
    return value


def _seed(label: str) -> int:
    return int.from_bytes(hashlib.sha256(
        f"{SEED_BLOCK_SCHEMA}|{label}".encode("ascii")).digest()[:8],
        "big") & MAX_SEED


def _validate_seed(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) \
            or not 0 <= value <= MAX_SEED:
        raise WorldAfterstateV2ScheduleError(f"{label} drift")


@dataclass(frozen=True)
class TrainingSeedBlockV2:
    """One independent four-member initialization/data-order block."""

    name: str
    initialization_seeds: tuple[int, ...]
    data_order_seeds: tuple[int, ...]
    prediction_authorized: bool = False
    schema: str = SEED_BLOCK_SCHEMA

    def validate(self) -> None:
        if self.schema != SEED_BLOCK_SCHEMA or self.name not in (
                "block-1-primary", "block-2-confirmatory") \
                or type(self.initialization_seeds) is not tuple \
                or type(self.data_order_seeds) is not tuple \
                or len(self.initialization_seeds) != 4 \
                or len(self.data_order_seeds) != 4 \
                or type(self.prediction_authorized) is not bool \
                or self.prediction_authorized:
            raise WorldAfterstateV2ScheduleError("seed block drift")
        for value in (*self.initialization_seeds, *self.data_order_seeds):
            _validate_seed(value, "training seed")
        if len(set(self.initialization_seeds)) != 4 \
                or len(set(self.data_order_seeds)) != 4:
            raise WorldAfterstateV2ScheduleError("seed block member overlap")

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {"schema": self.schema, "name": self.name,
                "initialization_seeds": list(self.initialization_seeds),
                "data_order_seeds": list(self.data_order_seeds),
                "prediction_authorized": self.prediction_authorized}

    def sha256(self) -> str:
        return _sha(self.payload())


def _make_blocks() -> tuple[TrainingSeedBlockV2, TrainingSeedBlockV2]:
    blocks = tuple(TrainingSeedBlockV2(
        name=f"block-{index}-{'primary' if index == 1 else 'confirmatory'}",
        initialization_seeds=tuple(_seed(f"{index}|initialization|{member}")
                                   for member in range(4)),
        data_order_seeds=tuple(_seed(f"{index}|data-order|{member}")
                               for member in range(4)))
                   for index in (1, 2))
    return blocks  # type: ignore[return-value]


SEED_BLOCKS = _make_blocks()
BLOCK_1 = SEED_BLOCKS[0]
BLOCK_2 = SEED_BLOCKS[1]
INITIALIZATION_SEEDS_BLOCK_1 = BLOCK_1.initialization_seeds
INITIALIZATION_SEEDS_BLOCK_2 = BLOCK_2.initialization_seeds
DATA_ORDER_SEEDS_BLOCK_1 = BLOCK_1.data_order_seeds
DATA_ORDER_SEEDS_BLOCK_2 = BLOCK_2.data_order_seeds
# Concise aliases for callers serializing the two frozen four-member blocks.
INITIALIZATION_SEEDS = (
    *INITIALIZATION_SEEDS_BLOCK_1, *INITIALIZATION_SEEDS_BLOCK_2)
DATA_ORDER_SEEDS = (*DATA_ORDER_SEEDS_BLOCK_1, *DATA_ORDER_SEEDS_BLOCK_2)


def validate_seed_blocks(
        blocks: Sequence[TrainingSeedBlockV2] = SEED_BLOCKS) -> None:
    if type(blocks) not in (tuple, list) or len(blocks) != 2 \
            or any(type(block) is not TrainingSeedBlockV2 for block in blocks):
        raise WorldAfterstateV2ScheduleError("exactly two seed blocks required")
    if tuple(blocks) != SEED_BLOCKS:
        raise WorldAfterstateV2ScheduleError("fixed seed tuple drift")
    for block in blocks:
        block.validate()
    all_seeds = [seed for block in blocks for seed in (
        *block.initialization_seeds, *block.data_order_seeds)]
    if len(set(all_seeds)) != len(all_seeds):
        raise WorldAfterstateV2ScheduleError("seed blocks overlap")
    if blocks[0].name != "block-1-primary" \
            or blocks[1].name != "block-2-confirmatory":
        raise WorldAfterstateV2ScheduleError("seed block order drift")


validate_seed_blocks()


def _identity(value: WorldAfterstateV2TrainingExample) -> dict[str, Any]:
    """Return only public immutable row identity (never target/tensor data)."""
    return {"deal_sha256": value.deal_sha256, "slot_sha256": value.slot_sha256,
            "state_sha256": value.state_sha256,
            "candidate_set_sha256": value.candidate_set_sha256,
            "candidate_index": value.candidate_index,
            "protected_incumbent": value.protected_incumbent,
            "successor_sha256": value.successor_sha256,
            "continuation_sha256": value.continuation_sha256,
            "replica": value.replica, "source": value.source,
            "split": value.split, "role": value.role, "phase": value.phase,
            "position": value.position, "trump_rank": value.trump_rank,
            "trump_mode": value.trump_mode, "cohort": value.cohort}


def _population_sha(rows: Sequence[WorldAfterstateV2TrainingExample]) -> str:
    return _sha({"schema": PREFIX_SCHEMA, "rows": sorted(
        (_identity(row) for row in rows),
        key=lambda row: (row["deal_sha256"], row["candidate_index"],
                         row["replica"]))})


def _validate_rows(values: Sequence[WorldAfterstateV2TrainingExample], *,
                  cohort: str | None = None,
                  allow_source_mix: bool = False) -> tuple[dict[str, list[WorldAfterstateV2TrainingExample]], str, str, str]:
    if type(values) not in (tuple, list) or not values \
            or any(type(value) is not WorldAfterstateV2TrainingExample
                   for value in values):
        raise WorldAfterstateV2ScheduleError("training schedule population drift")
    roots: dict[str, list[WorldAfterstateV2TrainingExample]] = {}
    seen: set[str] = set()
    splits: set[str] = set()
    sources: set[str] = set()
    cohorts: set[str] = set()
    for value in values:
        # An exact dataclass instance prevents injecting an audit/target field
        # through a foreign row type.  The standard validator then authenticates
        # every identity field before collating complete roots.
        if set(getattr(value, "__dict__", {})) != {
                "deal_sha256", "slot_sha256", "state_sha256",
                "candidate_set_sha256", "candidate_index",
                "protected_incumbent", "successor_sha256",
                "continuation_sha256", "replica", "source", "split",
                "role", "phase", "position", "trump_rank", "trump_mode",
                "tensors",
                "signed_level_category", "cohort", "schema"}:
            raise WorldAfterstateV2ScheduleError("audit field injection")
        try:
            value.validate()
        except WorldAfterstateV2TrainingError as exc:
            raise WorldAfterstateV2ScheduleError("training example refused") from exc
        if value.example_key in seen:
            raise WorldAfterstateV2ScheduleError("duplicate training example")
        seen.add(value.example_key)
        splits.add(value.split); sources.add(value.source); cohorts.add(value.cohort)
        roots.setdefault(value.root_key, []).append(value)
    if len(splits) != 1 or len(cohorts) != 1 \
            or (not allow_source_mix and len(sources) != 1):
        raise WorldAfterstateV2ScheduleError("split/source/cohort populations cannot mix")
    active_cohort = next(iter(cohorts))
    if cohort is not None and cohort != active_cohort:
        raise WorldAfterstateV2ScheduleError("cohort binding drift")
    # Collation invokes WorldAfterstateV2TrainingBatch.validate, which checks
    # candidate contiguity, all eight replicas, CRN bindings, and model-input
    # identity.  This is deliberately done once per root before batching.
    for rows in roots.values():
        try:
            batch = collate_training_examples(rows, cohort=active_cohort)
            batch.validate()
        except (WorldAfterstateV2TrainingError, ValueError) as exc:
            raise WorldAfterstateV2ScheduleError(
                "incomplete sibling root or duplicate/drop") from exc
    return roots, next(iter(splits)), (next(iter(sources)) if len(sources) == 1
                                       else "mixed"), active_cohort


def _order_key(root: str, *, epoch: int, data_order_seed: int,
               cohort: str, control_name: str, control_domain: str) -> bytes:
    return hashlib.sha256(canonical_json_bytes({
        "schema": SCHEDULE_SCHEMA, "root": root, "epoch": epoch,
        "data_order_seed": data_order_seed, "cohort": cohort,
        "control_name": control_name, "control_domain": control_domain,
    })).digest()


def ordered_root_ids_for_epoch(
        root_ids: Sequence[str], *, epoch: int,
        data_order_seed: int = DATA_ORDER_SEEDS_BLOCK_1[0],
        cohort: str = "primary", control_name: str = "natural",
        control_domain: str = CONTROL_DOMAIN) -> tuple[str, ...]:
    if type(root_ids) not in (tuple, list) or not root_ids \
            or any(type(root) is not str for root in root_ids) \
            or len(set(root_ids)) != len(root_ids):
        raise WorldAfterstateV2ScheduleError("root population drift")
    if isinstance(epoch, bool) or not isinstance(epoch, int) \
            or not 1 <= epoch <= MAX_EPOCHS:
        raise WorldAfterstateV2ScheduleError("training epoch is invalid")
    _validate_seed(data_order_seed, "data-order seed")
    if cohort not in COHORTS or type(control_name) is not str \
            or not control_name or type(control_domain) is not str \
            or not control_domain:
        raise WorldAfterstateV2ScheduleError("control/order identity drift")
    return tuple(sorted(root_ids, key=lambda root: _order_key(
        root, epoch=epoch, data_order_seed=data_order_seed, cohort=cohort,
        control_name=control_name, control_domain=control_domain)))


@dataclass(frozen=True)
class EpochScheduleV2:
    epoch: int
    split: str
    source: str
    cohort: str
    control_name: str
    control_domain: str
    data_order_seed: int
    batch_example_cap: int
    population_sha256: str
    ordered_root_ids: tuple[str, ...]
    batch_root_ids: tuple[tuple[str, ...], ...]
    batch_example_keys: tuple[tuple[str, ...], ...]
    schema: str = SCHEDULE_SCHEMA
    authority: Mapping[str, bool] = field(default_factory=lambda: dict(AUTHORITY))

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {"schema": self.schema, "epoch": self.epoch,
                "split": self.split, "source": self.source,
                "cohort": self.cohort, "control_name": self.control_name,
                "control_domain": self.control_domain,
                "data_order_seed": self.data_order_seed,
                "batch_example_cap": self.batch_example_cap,
                "population_sha256": self.population_sha256,
                "ordered_root_ids": list(self.ordered_root_ids),
                "batch_root_ids": [list(batch) for batch in self.batch_root_ids],
                "batch_example_keys": [list(batch) for batch in self.batch_example_keys],
                "authority": dict(self.authority)}

    def validate(self) -> None:
        if self.schema != SCHEDULE_SCHEMA or self.authority != AUTHORITY \
                or self.split != "fit" \
                or self.source not in (*STATE_SOURCES, "mixed") \
                or self.cohort not in COHORTS \
                or not self.source or type(self.control_name) is not str \
                or not self.control_name or type(self.control_domain) is not str \
                or not self.control_domain:
            raise WorldAfterstateV2ScheduleError("schedule identity/authority drift")
        if isinstance(self.epoch, bool) or not 1 <= self.epoch <= MAX_EPOCHS \
                or isinstance(self.batch_example_cap, bool) \
                or not isinstance(self.batch_example_cap, int) \
                or self.batch_example_cap < 1:
            raise WorldAfterstateV2ScheduleError("schedule cap/epoch drift")
        _validate_seed(self.data_order_seed, "schedule data-order seed")
        _digest(self.population_sha256, "schedule population SHA-256")
        if type(self.ordered_root_ids) is not tuple or not self.ordered_root_ids \
                or len(set(self.ordered_root_ids)) != len(self.ordered_root_ids) \
                or any(type(root) is not str for root in self.ordered_root_ids):
            raise WorldAfterstateV2ScheduleError("schedule root order drift")
        if type(self.batch_root_ids) is not tuple \
                or type(self.batch_example_keys) is not tuple \
                or not self.batch_root_ids \
                or len(self.batch_root_ids) != len(self.batch_example_keys):
            raise WorldAfterstateV2ScheduleError("schedule batch drift")
        flat_roots = tuple(root for batch in self.batch_root_ids for root in batch)
        if flat_roots != self.ordered_root_ids or len(set(flat_roots)) != len(flat_roots):
            raise WorldAfterstateV2ScheduleError("schedule root drop/duplicate")
        if any(type(batch) is not tuple or not batch for batch in self.batch_root_ids) \
                or any(type(batch) is not tuple or not batch
                       for batch in self.batch_example_keys):
            raise WorldAfterstateV2ScheduleError("schedule empty batch")
        if any(len(batch) > self.batch_example_cap
               for batch in self.batch_example_keys):
            raise WorldAfterstateV2ScheduleError("schedule batch cap drift")

    def sha256(self) -> str:
        return _sha(self.payload())


def training_epoch_batches(
        examples: Sequence[WorldAfterstateV2TrainingExample], *, epoch: int,
        data_order_seed: int = DATA_ORDER_SEEDS_BLOCK_1[0],
        batch_example_cap: int = DEFAULT_BATCH_EXAMPLE_CAP,
        batch_cap: int | None = None,
        cohort: str | None = None, control_name: str = "natural",
        control_domain: str = CONTROL_DOMAIN) -> tuple[EpochScheduleV2,
                                                        tuple[WorldAfterstateV2TrainingBatch, ...]]:
    if batch_cap is not None:
        if batch_example_cap != DEFAULT_BATCH_EXAMPLE_CAP:
            raise WorldAfterstateV2ScheduleError("duplicate batch cap")
        batch_example_cap = batch_cap
    if isinstance(batch_example_cap, bool) or not isinstance(batch_example_cap, int) \
            or batch_example_cap < 1:
        raise WorldAfterstateV2ScheduleError("training batch cap is invalid")
    # The reviewed fit population deliberately combines natural, diverse, and
    # mechanics-hard sources.  Source is a bound per-root stratum, not a reason
    # to split one optimizer epoch into separately weighted sub-epochs.
    roots, split, source, active_cohort = _validate_rows(
        examples, cohort=cohort, allow_source_mix=True)
    ordered = ordered_root_ids_for_epoch(
        tuple(roots), epoch=epoch, data_order_seed=data_order_seed,
        cohort=active_cohort, control_name=control_name,
        control_domain=control_domain)
    batches_rows: list[list[WorldAfterstateV2TrainingExample]] = []
    batches_roots: list[list[str]] = []
    pending_rows: list[WorldAfterstateV2TrainingExample] = []
    pending_roots: list[str] = []
    for root in ordered:
        rows = roots[root]
        if len(rows) > batch_example_cap:
            raise WorldAfterstateV2ScheduleError("complete root exceeds batch cap")
        if pending_rows and len(pending_rows) + len(rows) > batch_example_cap:
            batches_rows.append(pending_rows); batches_roots.append(pending_roots)
            pending_rows, pending_roots = [], []
        pending_rows.extend(rows); pending_roots.append(root)
    if pending_rows:
        batches_rows.append(pending_rows); batches_roots.append(pending_roots)
    batches = tuple(collate_training_examples(rows, split=split,
                                               cohort=active_cohort)
                    for rows in batches_rows)
    schedule = EpochScheduleV2(
        epoch=epoch, split=split, source=source, cohort=active_cohort,
        control_name=control_name, control_domain=control_domain,
        data_order_seed=data_order_seed, batch_example_cap=batch_example_cap,
        population_sha256=_population_sha(examples),
        ordered_root_ids=ordered,
        batch_root_ids=tuple(tuple(batch) for batch in batches_roots),
        batch_example_keys=tuple(tuple(batch.example_keys) for batch in batches))
    schedule.validate()
    if tuple(key for batch in schedule.batch_example_keys for key in batch) \
            != tuple(key for batch in batches for key in batch.example_keys):
        raise WorldAfterstateV2ScheduleError("schedule example order drift")
    return schedule, batches


def validate_control_schedule_match(
        natural: EpochScheduleV2, matched: EpochScheduleV2) -> None:
    """Check that a sealed control transform reused exactly one root order."""
    if type(natural) is not EpochScheduleV2 or type(matched) is not EpochScheduleV2:
        raise WorldAfterstateV2ScheduleError("control schedule type drift")
    natural.validate(); matched.validate()
    if (natural.epoch, natural.batch_example_cap,
            natural.ordered_root_ids, natural.batch_root_ids,
            natural.batch_example_keys, natural.data_order_seed,
            natural.control_domain) != (
                matched.epoch, matched.batch_example_cap,
                matched.ordered_root_ids, matched.batch_root_ids,
                matched.batch_example_keys, matched.data_order_seed,
                matched.control_domain):
        raise WorldAfterstateV2ScheduleError("control/natural order mismatch")


def reuse_schedule_for_control(
        natural_schedule: EpochScheduleV2,
        control_examples: Sequence[WorldAfterstateV2TrainingExample], *,
        cohort: str = "control", control_name: str | None = None) -> tuple[
            EpochScheduleV2, tuple[WorldAfterstateV2TrainingBatch, ...]]:
    """Apply a sealed natural root/order schedule to a transformed control."""
    if type(natural_schedule) is not EpochScheduleV2:
        raise WorldAfterstateV2ScheduleError("natural schedule type drift")
    natural_schedule.validate()
    roots, split, source, active = _validate_rows(
        control_examples, cohort=cohort, allow_source_mix=True)
    if split != natural_schedule.split or source != natural_schedule.source \
            or active != cohort or set(roots) != set(natural_schedule.ordered_root_ids):
        raise WorldAfterstateV2ScheduleError("control schedule natural binding drift")
    by_key = {row.example_key: row for rows in roots.values() for row in rows}
    batches_rows = []
    for keys in natural_schedule.batch_example_keys:
        if any(key not in by_key for key in keys):
            raise WorldAfterstateV2ScheduleError("control schedule example drift")
        rows = [by_key[key] for key in keys]
        if len(rows) > natural_schedule.batch_example_cap:
            raise WorldAfterstateV2ScheduleError("control schedule batch cap drift")
        batches_rows.append(rows)
    batches = tuple(collate_training_examples(rows, split=split, cohort=cohort)
                    for rows in batches_rows)
    if tuple(key for batch in batches for key in batch.example_keys) \
            != tuple(key for batch in natural_schedule.batch_example_keys for key in batch):
        raise WorldAfterstateV2ScheduleError("control schedule output drift")
    control_schedule = EpochScheduleV2(
        epoch=natural_schedule.epoch, split=split, source=source,
        cohort=cohort, control_name=(control_name or natural_schedule.control_name),
        control_domain=natural_schedule.control_domain,
        data_order_seed=natural_schedule.data_order_seed,
        batch_example_cap=natural_schedule.batch_example_cap,
        population_sha256=_population_sha(control_examples),
        ordered_root_ids=natural_schedule.ordered_root_ids,
        batch_root_ids=natural_schedule.batch_root_ids,
        batch_example_keys=natural_schedule.batch_example_keys)
    control_schedule.validate()
    validate_control_schedule_match(natural_schedule, control_schedule)
    return control_schedule, batches


@dataclass(frozen=True)
class CommonEpochDecisionV2:
    selected_epoch: int
    stop_epoch: int
    cohort_mean_loss_nano: tuple[int, ...]
    stopped_for_patience: bool
    block_name: str
    schema: str = COMMON_EPOCH_SCHEMA
    authority: Mapping[str, bool] = field(default_factory=lambda: dict(AUTHORITY))

    def validate(self) -> None:
        if self.schema != COMMON_EPOCH_SCHEMA or self.block_name not in (
                "block-1-primary", "block-2-confirmatory") \
                or self.authority != AUTHORITY or type(self.cohort_mean_loss_nano) is not tuple \
                or not 1 <= self.selected_epoch <= self.stop_epoch <= MAX_EPOCHS \
                or len(self.cohort_mean_loss_nano) != self.stop_epoch \
                or any(isinstance(value, bool) or not isinstance(value, int)
                       or value < 0 for value in self.cohort_mean_loss_nano) \
                or type(self.stopped_for_patience) is not bool:
            raise WorldAfterstateV2ScheduleError("common epoch receipt drift")

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {"schema": self.schema, "selected_epoch": self.selected_epoch,
                "stop_epoch": self.stop_epoch,
                "cohort_mean_loss_nano": list(self.cohort_mean_loss_nano),
                "stopped_for_patience": self.stopped_for_patience,
                "block_name": self.block_name, "authority": dict(self.authority)}

    def sha256(self) -> str:
        return _sha(self.payload())


def _metric_rows(value: object) -> tuple[tuple[int, ...], ...]:
    if type(value) is tuple and any(
            isinstance(row, Mapping) and "audit" in row for row in value):
        raise WorldAfterstateV2ScheduleError("audit input injection")
    if type(value) is not tuple or len(value) != 4 \
            or any(type(row) is not tuple for row in value):
        raise WorldAfterstateV2ScheduleError(
            "complete four-member epoch-select metrics required")
    if any("audit" in getattr(row, "__dict__", {}) for row in value):
        raise WorldAfterstateV2ScheduleError("audit input injection")
    if any(any(isinstance(item, bool) or not isinstance(item, int) or item < 0
               for item in row) for row in value):
        raise WorldAfterstateV2ScheduleError("epoch-select loss value drift")
    lengths = {len(row) for row in value}
    if len(lengths) != 1 or not lengths or next(iter(lengths)) > MAX_EPOCHS:
        raise WorldAfterstateV2ScheduleError("epoch-select epoch count drift")
    if next(iter(lengths)) < 1:
        raise WorldAfterstateV2ScheduleError("epoch-select metrics are empty")
    return value  # type: ignore[return-value]


def select_common_epoch(
        loss_nano_by_member: tuple[tuple[int, ...], ...], *,
        block_name: str = "block-1-primary") -> CommonEpochDecisionV2:
    """Select one earliest-minimum epoch from complete epoch-select metrics."""
    rows = _metric_rows(loss_nano_by_member)
    if block_name not in ("block-1-primary", "block-2-confirmatory"):
        raise WorldAfterstateV2ScheduleError("seed block identity drift")
    count = len(rows[0])
    sums = tuple(sum(row[index] for row in rows) for index in range(count))
    means = tuple(value // 4 for value in sums)
    best_index = min(range(count), key=lambda index: (sums[index], index))
    # Patience is evaluated chronologically and does not change the earliest
    # minimum tie rule.  A common checkpoint is admitted only through stop_epoch.
    stale = 0
    stop = count
    stopped = False
    incumbent = sums[0]
    for index in range(1, count):
        if sums[index] < incumbent:
            incumbent = sums[index]; stale = 0
        else:
            stale += 1
            if stale == EARLY_STOP_PATIENCE:
                stop = index + 1; stopped = True; break
    if best_index >= stop:
        # A minimum after a patience stop is not a complete admitted epoch.
        best_index = min(range(stop), key=lambda index: (sums[index], index))
    result = CommonEpochDecisionV2(
        selected_epoch=best_index + 1, stop_epoch=stop,
        cohort_mean_loss_nano=means[:stop], stopped_for_patience=stopped,
        block_name=block_name)
    result.validate()
    return result


def validate_common_epoch_receipt(value: CommonEpochDecisionV2) -> None:
    if type(value) is not CommonEpochDecisionV2:
        raise WorldAfterstateV2ScheduleError("common epoch receipt type drift")
    value.validate()


def validate_common_epoch_checkpoints(
        checkpoint_epochs: Sequence[int], *, selected_epoch: int) -> None:
    """Require all four members to provide the selected complete checkpoint."""
    if type(checkpoint_epochs) not in (tuple, list) or len(checkpoint_epochs) != 4 \
            or any(isinstance(epoch, bool) or not isinstance(epoch, int)
                   or epoch < selected_epoch for epoch in checkpoint_epochs):
        raise WorldAfterstateV2ScheduleError("truncated member")
    if isinstance(selected_epoch, bool) or not isinstance(selected_epoch, int) \
            or not 1 <= selected_epoch <= MAX_EPOCHS:
        raise WorldAfterstateV2ScheduleError("selected epoch drift")


def canonical_deal_hash_prefix(
        examples: Sequence[WorldAfterstateV2TrainingExample], fraction: float) \
        -> tuple[WorldAfterstateV2TrainingExample, ...]:
    """Select a source/stratum-preserving canonical prefix of complete deals."""
    if isinstance(fraction, bool) or not isinstance(fraction, (int, float)) \
            or not math.isfinite(fraction) or not 0 < fraction <= 1:
        raise WorldAfterstateV2ScheduleError("prefix fraction drift")
    _validate_rows(examples, allow_source_mix=True)
    groups: dict[tuple[str, str, str, str, str, str, str], dict[str, list[WorldAfterstateV2TrainingExample]]] = {}
    for row in examples:
        key = (row.split, row.source, row.phase, row.position, row.role,
               row.trump_rank, row.trump_mode)
        groups.setdefault(key, {}).setdefault(row.deal_sha256, []).append(row)
    selected: list[WorldAfterstateV2TrainingExample] = []
    for key in sorted(groups):
        deals = groups[key]
        ordered = sorted(deals)
        count = max(1, math.ceil(len(ordered) * float(fraction)))
        for deal in ordered[:count]:
            selected.extend(deals[deal])
    result = tuple(sorted(selected, key=lambda row: (
        row.deal_sha256, row.root_key, row.candidate_index, row.replica)))
    if not result or fraction == 1 and len(result) != len(examples):
        raise WorldAfterstateV2ScheduleError("prefix derivation drift")
    _validate_rows(result, allow_source_mix=True)
    return result


def derive_nested_prefixes(
        examples: Sequence[WorldAfterstateV2TrainingExample],
        fractions: Sequence[float] = (0.25, 0.50, 1.0)) \
        -> dict[float, tuple[WorldAfterstateV2TrainingExample, ...]]:
    if type(fractions) not in (tuple, list) or tuple(fractions) != (0.25, 0.5, 1.0):
        raise WorldAfterstateV2ScheduleError("canonical prefix schedule drift")
    result = {fraction: canonical_deal_hash_prefix(examples, fraction)
              for fraction in fractions}
    keys = lambda rows: {row.example_key for row in rows}
    if not (keys(result[0.25]).issubset(keys(result[0.5]))
            and keys(result[0.5]).issubset(keys(result[1.0]))):
        raise WorldAfterstateV2ScheduleError("nested prefix order drift")
    return result


def validate_nested_prefixes(
        examples: Sequence[WorldAfterstateV2TrainingExample],
        prefixes: Mapping[float, Sequence[WorldAfterstateV2TrainingExample]]) -> None:
    if type(prefixes) is not dict or set(prefixes) != {0.25, 0.5, 1.0}:
        raise WorldAfterstateV2ScheduleError("canonical prefix receipt drift")
    expected = derive_nested_prefixes(examples)
    for fraction in (0.25, 0.5, 1.0):
        value = prefixes[fraction]
        if type(value) not in (tuple, list) \
                or tuple(row.example_key for row in value) \
                != tuple(row.example_key for row in expected[fraction]):
            raise WorldAfterstateV2ScheduleError("canonical prefix rederivation drift")


# Compatibility spellings used by controller code and artifact readers.  A
# schedule itself is the immutable receipt: its canonical payload binds the
# cap, population, order, authority map, and control identity.
ScheduleReceiptV2 = EpochScheduleV2
CommonEpochReceiptV2 = CommonEpochDecisionV2


def validate_schedule_receipt(value: EpochScheduleV2) -> None:
    if type(value) is EpochScheduleV2:
        value.validate()
        return
    if type(value) is not dict or value.get("schema") != RECEIPT_SCHEMA \
            or value.get("authority") != AUTHORITY \
            or value.get("root_groups_never_split") is not True:
        raise WorldAfterstateV2ScheduleError("schedule receipt type/schema drift")
    required = {"schema", "split", "source", "cohort", "control_name",
                "control_domain", "data_order_seed", "batch_example_cap",
                "population_sha256", "ordered_root_ids", "batch_root_ids",
                "batch_example_keys", "root_groups_never_split", "authority",
                "schedule_sha256"}
    if set(value) != required:
        raise WorldAfterstateV2ScheduleError("schedule receipt fields drift")
    for name in ("population_sha256", "schedule_sha256"):
        _digest(value[name], f"receipt {name}")
    if value["split"] != "fit" or value["cohort"] not in COHORTS \
            or value["source"] not in (*STATE_SOURCES, "mixed") \
            or type(value["control_name"]) is not str or not value["control_name"] \
            or type(value["control_domain"]) is not str or not value["control_domain"] \
            or isinstance(value["data_order_seed"], bool) \
            or not isinstance(value["data_order_seed"], int) \
            or not 0 <= value["data_order_seed"] <= MAX_SEED \
            or type(value["batch_example_cap"]) is not int \
            or value["batch_example_cap"] < 1 \
            or type(value["ordered_root_ids"]) is not list \
            or type(value["batch_root_ids"]) is not list \
            or type(value["batch_example_keys"]) is not list:
        raise WorldAfterstateV2ScheduleError("schedule receipt population drift")
    flat = [root for batch in value["batch_root_ids"] for root in batch]
    if flat != value["ordered_root_ids"] \
            or len(flat) != len(set(flat)) \
            or len(value["batch_root_ids"]) != len(value["batch_example_keys"]):
        raise WorldAfterstateV2ScheduleError("schedule receipt root drift")
    if any(type(batch) is not list or not batch
           or len(batch) > value["batch_example_cap"]
           for batch in value["batch_example_keys"]):
        raise WorldAfterstateV2ScheduleError("schedule receipt batch cap drift")
    body = {key: item for key, item in value.items() if key != "schedule_sha256"}
    if value["schedule_sha256"] != _sha(body):
        raise WorldAfterstateV2ScheduleError("schedule receipt reconstruction drift")


def schedule_sha256(value: EpochScheduleV2 | Mapping[str, Any]) -> str:
    validate_schedule_receipt(value)  # type: ignore[arg-type]
    return value.sha256() if type(value) is EpochScheduleV2 \
        else value["schedule_sha256"]


def _receipt_dict(schedule: EpochScheduleV2) -> dict[str, Any]:
    body = {"schema": RECEIPT_SCHEMA, "split": schedule.split,
            "source": schedule.source, "cohort": schedule.cohort,
            "control_name": schedule.control_name,
            "control_domain": schedule.control_domain,
            "data_order_seed": schedule.data_order_seed,
            "batch_example_cap": schedule.batch_example_cap,
            "population_sha256": schedule.population_sha256,
            "ordered_root_ids": list(schedule.ordered_root_ids),
            "batch_root_ids": [list(batch) for batch in schedule.batch_root_ids],
            "batch_example_keys": [list(batch)
                                   for batch in schedule.batch_example_keys],
            "root_groups_never_split": True, "authority": dict(AUTHORITY)}
    return {**body, "schedule_sha256": _sha(body)}


def build_training_batches(
        examples: Sequence[WorldAfterstateV2TrainingExample], *, epoch: int,
        data_order_seed: int = DATA_ORDER_SEEDS_BLOCK_1[0],
        batch_example_cap: int = DEFAULT_BATCH_EXAMPLE_CAP,
        batch_cap: int | None = None,
        cohort: str | None = None, control_name: str = "natural",
        control_domain: str = CONTROL_DOMAIN) -> tuple[
            tuple[WorldAfterstateV2TrainingBatch, ...], dict[str, Any]]:
    schedule, batches = training_epoch_batches(
        examples, epoch=epoch, data_order_seed=data_order_seed,
        batch_example_cap=batch_example_cap, batch_cap=batch_cap, cohort=cohort,
        control_name=control_name, control_domain=control_domain)
    return batches, _receipt_dict(schedule)


canonical_prefix_schedule = derive_nested_prefixes
select_canonical_deal_prefix = canonical_deal_hash_prefix
build_control_training_batches = reuse_schedule_for_control


__all__ = [
    "AUTHORITY", "BLOCK_1", "BLOCK_2", "COMMON_EPOCH_SCHEMA",
    "CONTROL_DOMAIN", "DATA_ORDER_SEEDS_BLOCK_1", "DATA_ORDER_SEEDS_BLOCK_2",
    "DEFAULT_BATCH_EXAMPLE_CAP", "EARLY_STOP_PATIENCE",
    "EpochScheduleV2", "CommonEpochDecisionV2", "TrainingSeedBlockV2",
    "INITIALIZATION_SEEDS", "INITIALIZATION_SEEDS_BLOCK_1",
    "INITIALIZATION_SEEDS_BLOCK_2", "DATA_ORDER_SEEDS", "MAX_EPOCHS",
    "SEED_BLOCKS", "WorldAfterstateV2ScheduleError",
    "canonical_deal_hash_prefix", "canonical_prefix_schedule",
    "build_training_batches",
    "derive_nested_prefixes", "select_canonical_deal_prefix",
    "reuse_schedule_for_control", "build_control_training_batches",
    "ordered_root_ids_for_epoch", "select_common_epoch",
    "training_epoch_batches", "validate_common_epoch_checkpoints",
    "validate_control_schedule_match", "validate_schedule_receipt",
    "validate_common_epoch_receipt", "validate_seed_blocks", "schedule_sha256", "ScheduleReceiptV2",
    "CommonEpochReceiptV2",
    "validate_nested_prefixes",
]
