"""Deterministic development-only training mechanics for Value V1.

Every optimizer batch contains complete root groups.  Loss is averaged first
over candidate/replicate siblings inside a root and then over roots, preventing
a wide production ballot from receiving more learning weight than a narrow
one.  Selection uses one cohort-level epoch; no member may choose its own.

This module reads no artifacts and grants no execution, audit/report opening,
gameplay, strength, merge, promotion, deployment, retry, or R5 authority.
"""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Sequence

import torch

from .belief_contract import canonical_json_bytes
from .world_afterstate_v1_dataset import JoinedAdvantageV1
from .world_afterstate_v1_model import (
    AdvantageBatchV1, WorldAfterstateAdvantageV1,
    WorldAfterstateV1ModelError, advantage_loss_rows,
    collate_advantage_examples)


BATCH_SCHEMA = "world-afterstate-advantage-training-batch-v1"
CONFIG_SCHEMA = "world-afterstate-advantage-training-config-v1"
EPOCH_SCHEMA = "world-afterstate-advantage-epoch-receipt-v1"
COMMON_EPOCH_SCHEMA = "world-afterstate-advantage-common-epoch-v1"
STATE_SCHEMA = "world-afterstate-advantage-model-state-v1"
POPULATION_SCHEMA = "world-afterstate-advantage-training-population-v1"
SCHEDULE_SCHEMA = "world-afterstate-advantage-training-schedule-v1"
LOSS_SCALE = 1_000_000_000
COHORT_SIZE = 8
TRAINING_SPLITS = ("fit", "select", "audit")
AUTHORITY = {
    "dataset_opening_authorized": False,
    "training_execution_authorized": False,
    "audit_opening_authorized": False,
    "report_opening_authorized": False,
    "world_twin_generation_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "retry_authorized": False,
    "r5_authorized": False,
}


class WorldAfterstateV1TrainingError(ValueError):
    """A V1 batch, optimizer, epoch, selection, or state drifted."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV1TrainingError(f"{label} drift")
    return value


@dataclass(frozen=True)
class AdvantageTrainingConfigV1:
    learning_rate_ppb: int
    weight_decay_ppb: int
    gradient_norm_milli: int
    max_epochs: int
    early_stop_patience: int
    minimum_improvement_nanoloss: int
    schema: str = CONFIG_SCHEMA

    def validate(self) -> None:
        values = (
            self.learning_rate_ppb, self.weight_decay_ppb,
            self.gradient_norm_milli, self.max_epochs,
            self.early_stop_patience, self.minimum_improvement_nanoloss,
        )
        if self.schema != CONFIG_SCHEMA \
                or any(isinstance(value, bool) or not isinstance(value, int)
                       for value in values) \
                or not 1 <= self.learning_rate_ppb <= LOSS_SCALE \
                or not 0 <= self.weight_decay_ppb <= LOSS_SCALE \
                or not 1 <= self.gradient_norm_milli <= 1_000_000 \
                or not 1 <= self.max_epochs <= 10_000 \
                or not 1 <= self.early_stop_patience <= self.max_epochs \
                or not 0 <= self.minimum_improvement_nanoloss \
                <= 203 * LOSS_SCALE:
            raise WorldAfterstateV1TrainingError(
                "advantage training config drift")

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": self.schema,
            "learning_rate_ppb": self.learning_rate_ppb,
            "weight_decay_ppb": self.weight_decay_ppb,
            "gradient_norm_milli": self.gradient_norm_milli,
            "max_epochs": self.max_epochs,
            "early_stop_patience": self.early_stop_patience,
            "minimum_improvement_nanoloss":
                self.minimum_improvement_nanoloss,
        }

    def sha256(self) -> str:
        return _sha(self.payload())


@dataclass(frozen=True)
class AdvantageTrainingBatchV1:
    pair_keys: tuple[str, ...]
    state_group_ids: tuple[str, ...]
    candidate_indexes: tuple[int, ...]
    replicates: tuple[int, ...]
    incumbent_row_sha256s: tuple[str, ...]
    candidate_row_sha256s: tuple[str, ...]
    split: str
    tensors: AdvantageBatchV1
    schema: str = BATCH_SCHEMA

    def validate(self) -> None:
        count = len(self.pair_keys)
        fields = (
            self.state_group_ids, self.candidate_indexes, self.replicates,
            self.incumbent_row_sha256s, self.candidate_row_sha256s,
        )
        if self.schema != BATCH_SCHEMA or count <= 0 \
                or type(self.pair_keys) is not tuple \
                or any(type(value) is not tuple or len(value) != count
                       for value in fields) \
                or len(set(self.pair_keys)) != count \
                or any(type(key) is not str or not key or not key.isascii()
                       for key in self.pair_keys) \
                or self.split not in TRAINING_SPLITS \
                or type(self.tensors) is not AdvantageBatchV1:
            raise WorldAfterstateV1TrainingError(
                "advantage training batch identity drift")
        self.tensors.validate()
        if self.tensors.targets.device.type != "cpu" \
                or self.tensors.incumbent.public.device.type != "cpu" \
                or self.tensors.candidate.public.device.type != "cpu" \
                or self.tensors.incumbent.size != count:
            raise WorldAfterstateV1TrainingError(
                "advantage training batch device/tensor drift")
        for digest in (*self.state_group_ids, *self.incumbent_row_sha256s,
                       *self.candidate_row_sha256s):
            _digest(digest, "advantage training batch digest")
        if any(isinstance(index, bool) or not isinstance(index, int)
               or index < 1 for index in self.candidate_indexes) \
                or any(isinstance(value, bool) or not isinstance(value, int)
                       or value not in (0, 1) for value in self.replicates):
            raise WorldAfterstateV1TrainingError(
                "advantage training batch sibling identity drift")
        groups: dict[str, list[tuple[int, int]]] = defaultdict(list)
        seen_after = set()
        previous_state = None
        for index, (state, candidate, replicate) in enumerate(zip(
                self.state_group_ids, self.candidate_indexes,
                self.replicates, strict=True)):
            if self.pair_keys[index] != f"{state}:{candidate}:{replicate}" \
                    or self.incumbent_row_sha256s[index] \
                    == self.candidate_row_sha256s[index]:
                raise WorldAfterstateV1TrainingError(
                    "advantage training batch sibling binding drift")
            if previous_state is not None and state != previous_state:
                seen_after.add(previous_state)
                if state in seen_after:
                    raise WorldAfterstateV1TrainingError(
                        "advantage training batch split root")
            groups[state].append((candidate, replicate))
            previous_state = state
        for siblings in groups.values():
            candidates = sorted({candidate for candidate, _ in siblings})
            expected = [(candidate, replicate) for candidate in candidates
                        for replicate in (0, 1)]
            if candidates != list(range(1, len(candidates) + 1)) \
                    or siblings != expected:
                raise WorldAfterstateV1TrainingError(
                    "advantage training batch incomplete root")

    @property
    def root_count(self) -> int:
        self.validate()
        return len(set(self.state_group_ids))


def collate_training_pairs(
        values: Sequence[JoinedAdvantageV1], *,
        split: str) -> AdvantageTrainingBatchV1:
    if type(values) not in (list, tuple) or not values \
            or split not in TRAINING_SPLITS \
            or any(type(value) is not JoinedAdvantageV1 for value in values):
        raise WorldAfterstateV1TrainingError(
            "advantage training pair population drift")
    expected_fold = "calibration" if split == "audit" else "train"
    keys = []
    states = []
    candidates = []
    replicates = []
    incumbent_rows = []
    candidate_rows = []
    examples = []
    for value in values:
        value.validate()
        if value.pair.fold != expected_fold:
            raise WorldAfterstateV1TrainingError(
                "advantage training source-fold drift")
        key = value.key()
        keys.append(f"{key[0]}:{key[1]}:{key[2]}")
        states.append(key[0])
        candidates.append(key[1])
        replicates.append(key[2])
        incumbent_rows.append(value.incumbent_row_sha256)
        candidate_rows.append(value.candidate_row_sha256)
        examples.append(value.example)
    result = AdvantageTrainingBatchV1(
        pair_keys=tuple(keys), state_group_ids=tuple(states),
        candidate_indexes=tuple(candidates), replicates=tuple(replicates),
        incumbent_row_sha256s=tuple(incumbent_rows),
        candidate_row_sha256s=tuple(candidate_rows), split=split,
        tensors=collate_advantage_examples(examples))
    result.validate()
    return result


def model_state_sha256(model: WorldAfterstateAdvantageV1) -> str:
    if type(model) is not WorldAfterstateAdvantageV1 \
            or any(parameter.device.type != "cpu"
                   or parameter.dtype != torch.float32
                   for parameter in model.parameters()):
        raise WorldAfterstateV1TrainingError(
            "advantage model state device/dtype drift")
    digest = hashlib.sha256(canonical_json_bytes({
        "schema": STATE_SCHEMA,
        "parameter_names": [name for name, _ in model.named_parameters()],
    }))
    for name, parameter in model.named_parameters():
        array = parameter.detach().contiguous().numpy().astype("<f4", copy=False)
        raw = array.tobytes(order="C")
        header = canonical_json_bytes({
            "name": name, "shape": list(array.shape),
            "dtype": "little-endian-float32", "byte_count": len(raw),
        })
        digest.update(len(header).to_bytes(8, "big"))
        digest.update(header)
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def new_optimizer(
        model: WorldAfterstateAdvantageV1,
        config: AdvantageTrainingConfigV1) -> torch.optim.AdamW:
    config.validate()
    _ = model_state_sha256(model)
    return torch.optim.AdamW(
        model.parameters(), lr=config.learning_rate_ppb / LOSS_SCALE,
        weight_decay=config.weight_decay_ppb / LOSS_SCALE,
        foreach=False, fused=False)


def _validate_optimizer(
        model: WorldAfterstateAdvantageV1,
        optimizer: torch.optim.Optimizer,
        config: AdvantageTrainingConfigV1) -> None:
    config.validate()
    if type(optimizer) is not torch.optim.AdamW \
            or len(optimizer.param_groups) != 1:
        raise WorldAfterstateV1TrainingError(
            "advantage optimizer identity drift")
    group = optimizer.param_groups[0]
    if group["lr"] != config.learning_rate_ppb / LOSS_SCALE \
            or group["weight_decay"] != config.weight_decay_ppb / LOSS_SCALE \
            or group["foreach"] is not False or group["fused"] is not False \
            or len(group["params"]) != len(tuple(model.parameters())) \
            or any(left is not right for left, right in zip(
                group["params"], model.parameters(), strict=True)):
        raise WorldAfterstateV1TrainingError(
            "advantage optimizer configuration drift")


def _batch_bindings(
        batches: tuple[AdvantageTrainingBatchV1, ...], *,
        epoch: int, required_split: str) -> tuple[str, str, int, int]:
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch <= 0 \
            or type(batches) is not tuple or not batches \
            or required_split not in TRAINING_SPLITS \
            or any(type(batch) is not AdvantageTrainingBatchV1
                   for batch in batches):
        raise WorldAfterstateV1TrainingError(
            "advantage epoch batch population drift")
    pair_keys = []
    states = set()
    population = []
    schedule = []
    for batch in batches:
        batch.validate()
        if batch.split != required_split:
            raise WorldAfterstateV1TrainingError(
                "advantage epoch split drift")
        pair_keys.extend(batch.pair_keys)
        states.update(batch.state_group_ids)
        population.extend({
            "pair_key": key,
            "incumbent_row_sha256": incumbent,
            "candidate_row_sha256": candidate,
        } for key, incumbent, candidate in zip(
            batch.pair_keys, batch.incumbent_row_sha256s,
            batch.candidate_row_sha256s, strict=True))
        schedule.append(list(batch.pair_keys))
    if len(pair_keys) != len(set(pair_keys)):
        raise WorldAfterstateV1TrainingError(
            "advantage epoch duplicate pair")
    return (
        _sha({"schema": POPULATION_SCHEMA, "pairs": sorted(
            population, key=lambda row: row["pair_key"])}),
        _sha({"schema": SCHEDULE_SCHEMA, "epoch": epoch,
              "batch_pair_keys": schedule}),
        len(pair_keys), len(states),
    )


def root_balanced_loss(
        predictions: torch.Tensor, batch: AdvantageTrainingBatchV1) \
        -> torch.Tensor:
    rows = advantage_loss_rows(predictions, batch.tensors.targets)
    indexes: dict[str, list[int]] = defaultdict(list)
    for index, state in enumerate(batch.state_group_ids):
        indexes[state].append(index)
    result = torch.stack([
        rows[torch.as_tensor(locations, dtype=torch.long)].mean()
        for locations in indexes.values()
    ]).mean()
    if result.ndim != 0 or not bool(torch.isfinite(result)):
        raise WorldAfterstateV1TrainingError(
            "advantage root-balanced loss drift")
    return result


@dataclass(frozen=True)
class AdvantageEpochReceiptV1:
    epoch: int
    batch_count: int
    pair_count: int
    root_count: int
    mean_root_loss_nano: int
    config_sha256: str
    population_sha256: str
    schedule_sha256: str
    model_state_sha256_before: str
    model_state_sha256_after: str
    schema: str = EPOCH_SCHEMA

    def validate(self) -> None:
        integers = (
            self.epoch, self.batch_count, self.pair_count, self.root_count,
            self.mean_root_loss_nano,
        )
        digests = (
            self.config_sha256, self.population_sha256,
            self.schedule_sha256, self.model_state_sha256_before,
            self.model_state_sha256_after,
        )
        if self.schema != EPOCH_SCHEMA \
                or any(isinstance(value, bool) or not isinstance(value, int)
                       for value in integers) \
                or any(value <= 0 for value in integers[:4]) \
                or self.mean_root_loss_nano < 0 \
                or self.root_count > self.pair_count \
                or any(_digest(value, "advantage epoch digest") != value
                       for value in digests) \
                or self.model_state_sha256_before \
                == self.model_state_sha256_after:
            raise WorldAfterstateV1TrainingError(
                "advantage epoch receipt drift")

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": self.schema, "epoch": self.epoch,
            "batch_count": self.batch_count, "pair_count": self.pair_count,
            "root_count": self.root_count,
            "mean_root_loss_nano": self.mean_root_loss_nano,
            "config_sha256": self.config_sha256,
            "population_sha256": self.population_sha256,
            "schedule_sha256": self.schedule_sha256,
            "model_state_sha256_before": self.model_state_sha256_before,
            "model_state_sha256_after": self.model_state_sha256_after,
            "authority": dict(AUTHORITY),
        }


def train_epoch(
        model: WorldAfterstateAdvantageV1,
        optimizer: torch.optim.Optimizer,
        batches: tuple[AdvantageTrainingBatchV1, ...], *, epoch: int,
        config: AdvantageTrainingConfigV1) -> AdvantageEpochReceiptV1:
    if not 1 <= epoch <= config.max_epochs:
        raise WorldAfterstateV1TrainingError("advantage training epoch drift")
    _validate_optimizer(model, optimizer, config)
    population_sha, schedule_sha, pair_count, root_count = _batch_bindings(
        batches, epoch=epoch, required_split="fit")
    before = model_state_sha256(model)
    model.train(True)
    total = 0.0
    total_roots = 0
    for batch in batches:
        optimizer.zero_grad(set_to_none=True)
        prediction = model(batch.tensors.incumbent, batch.tensors.candidate)
        loss = root_balanced_loss(prediction, batch)
        loss.backward()
        norm = torch.nn.utils.clip_grad_norm_(
            model.parameters(), config.gradient_norm_milli / 1000,
            error_if_nonfinite=True)
        if not bool(torch.isfinite(norm)):
            raise WorldAfterstateV1TrainingError(
                "advantage training gradient drift")
        optimizer.step()
        total += float(loss.detach()) * batch.root_count
        total_roots += batch.root_count
    mean = round(total / total_roots * LOSS_SCALE)
    if total_roots != root_count or not math.isfinite(total) \
            or isinstance(mean, bool) or not isinstance(mean, int) or mean < 0:
        raise WorldAfterstateV1TrainingError(
            "advantage training loss receipt drift")
    receipt = AdvantageEpochReceiptV1(
        epoch=epoch, batch_count=len(batches), pair_count=pair_count,
        root_count=root_count, mean_root_loss_nano=mean,
        config_sha256=config.sha256(), population_sha256=population_sha,
        schedule_sha256=schedule_sha,
        model_state_sha256_before=before,
        model_state_sha256_after=model_state_sha256(model))
    receipt.validate()
    return receipt


def evaluate_selection_loss_nano(
        model: WorldAfterstateAdvantageV1,
        batches: tuple[AdvantageTrainingBatchV1, ...]) -> int:
    _, _, _, root_count = _batch_bindings(
        batches, epoch=1, required_split="select")
    before = model_state_sha256(model)
    was_training = model.training
    total = 0.0
    total_roots = 0
    model.eval()
    try:
        with torch.no_grad():
            for batch in batches:
                prediction = model(
                    batch.tensors.incumbent, batch.tensors.candidate)
                loss = root_balanced_loss(prediction, batch)
                total += float(loss) * batch.root_count
                total_roots += batch.root_count
    finally:
        model.train(was_training)
    if model_state_sha256(model) != before or total_roots != root_count \
            or not math.isfinite(total):
        raise WorldAfterstateV1TrainingError(
            "advantage selection mutated model")
    result = round(total / total_roots * LOSS_SCALE)
    if isinstance(result, bool) or not isinstance(result, int) or result < 0:
        raise WorldAfterstateV1TrainingError(
            "advantage selection receipt drift")
    return result


@dataclass(frozen=True)
class AdvantageCommonEpochV1:
    selected_epoch: int
    stop_epoch: int
    cohort_mean_loss_nano: tuple[int, ...]
    stopped_for_patience: bool
    config_sha256: str
    schema: str = COMMON_EPOCH_SCHEMA

    def validate(self) -> None:
        if self.schema != COMMON_EPOCH_SCHEMA \
                or isinstance(self.selected_epoch, bool) \
                or not isinstance(self.selected_epoch, int) \
                or isinstance(self.stop_epoch, bool) \
                or not isinstance(self.stop_epoch, int) \
                or not 1 <= self.selected_epoch <= self.stop_epoch \
                or type(self.cohort_mean_loss_nano) is not tuple \
                or len(self.cohort_mean_loss_nano) != self.stop_epoch \
                or any(isinstance(value, bool) or not isinstance(value, int)
                       or value < 0 for value in self.cohort_mean_loss_nano) \
                or type(self.stopped_for_patience) is not bool:
            raise WorldAfterstateV1TrainingError(
                "advantage common epoch receipt drift")
        _digest(self.config_sha256, "advantage common epoch config SHA-256")

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": self.schema,
            "selected_epoch": self.selected_epoch,
            "stop_epoch": self.stop_epoch,
            "cohort_mean_loss_nano": list(self.cohort_mean_loss_nano),
            "stopped_for_patience": self.stopped_for_patience,
            "config_sha256": self.config_sha256,
            "authority": dict(AUTHORITY),
        }


def select_common_epoch(
        loss_by_member: tuple[tuple[int, ...], ...], *,
        config: AdvantageTrainingConfigV1) -> AdvantageCommonEpochV1:
    config.validate()
    if type(loss_by_member) is not tuple \
            or len(loss_by_member) != COHORT_SIZE \
            or any(type(row) is not tuple for row in loss_by_member):
        raise WorldAfterstateV1TrainingError(
            "advantage selection cohort drift")
    lengths = {len(row) for row in loss_by_member}
    if len(lengths) != 1:
        raise WorldAfterstateV1TrainingError(
            "advantage selection epoch-count drift")
    epoch_count = next(iter(lengths))
    if not 1 <= epoch_count <= config.max_epochs \
            or any(isinstance(value, bool) or not isinstance(value, int)
                   or value < 0 for row in loss_by_member for value in row):
        raise WorldAfterstateV1TrainingError(
            "advantage selection loss drift")
    sums = tuple(sum(row[index] for row in loss_by_member)
                 for index in range(epoch_count))
    means = tuple(value // COHORT_SIZE for value in sums)
    selected = 1
    best = sums[0]
    stale = 0
    stop = epoch_count
    stopped = False
    threshold = config.minimum_improvement_nanoloss * COHORT_SIZE
    for index in range(1, epoch_count):
        if best - sums[index] >= threshold:
            best = sums[index]
            selected = index + 1
            stale = 0
        else:
            stale += 1
            if stale == config.early_stop_patience:
                stop = index + 1
                stopped = True
                break
    result = AdvantageCommonEpochV1(
        selected_epoch=selected, stop_epoch=stop,
        cohort_mean_loss_nano=means[:stop],
        stopped_for_patience=stopped, config_sha256=config.sha256())
    result.validate()
    return result


__all__ = [
    "AUTHORITY", "COHORT_SIZE", "AdvantageCommonEpochV1",
    "AdvantageEpochReceiptV1", "AdvantageTrainingBatchV1",
    "AdvantageTrainingConfigV1", "WorldAfterstateV1TrainingError",
    "collate_training_pairs", "evaluate_selection_loss_nano",
    "model_state_sha256", "new_optimizer", "select_common_epoch",
    "root_balanced_loss", "train_epoch",
]
