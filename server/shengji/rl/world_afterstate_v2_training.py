"""Bounded, deterministic training mechanics for Value-Afterstate V2.

Rows in this module are deliberately richer than the model input: all
identity and terminal-category information remains in the training contract,
while ``WorldAfterstateV2Batch`` is the target-free object handed to the
model.  This module performs no population selection, filesystem I/O, epoch
selection, controls, or training launch.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import math
from typing import Any, Sequence

import torch

from .belief_contract import canonical_json_bytes
from .world_afterstate import (
    OUTCOME_CLASSES, WorldAfterstateError, WorldAfterstateTensorsV0,
    category_signed_level,
)
from .world_afterstate_v2_model import (
    WorldAfterstateV2Batch, WorldAfterstateValueV2,
    absolute_cross_entropy_rows, collate_world_afterstate_tensors,
    expected_signed_utility,
)
from .world_afterstate_v2_protocol import (
    PRIOR_POINTS_BUCKETS, STATE_SOURCES, TRUMP_MODES,
)


BATCH_SCHEMA = "world-afterstate-v2-absolute-training-batch-v1"
EXAMPLE_SCHEMA = "world-afterstate-v2-absolute-training-example-v1"
CONFIG_SCHEMA = "world-afterstate-v2-absolute-training-config-v1"
EPOCH_SCHEMA = "world-afterstate-v2-absolute-training-epoch-v1"
STATE_SCHEMA = "world-afterstate-v2-absolute-training-state-v1"
POPULATION_SCHEMA = "world-afterstate-v2-absolute-training-population-v1"
SCHEDULE_SCHEMA = "world-afterstate-v2-absolute-training-schedule-v1"
LOSS_SCALE = 1_000_000_000
REPLICATES = tuple(range(8))
TRAINING_SPLITS = ("fit",)
COHORTS = ("primary", "control")


class WorldAfterstateV2TrainingError(WorldAfterstateError):
    """A V2 training row, batch, objective, or receipt violated its contract."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(
            char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV2TrainingError(f"{label} drift")
    return value


def _strict_int(value: object, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise WorldAfterstateV2TrainingError(f"{label} drift")
    return value


@dataclass(frozen=True)
class WorldAfterstateV2TrainingExample:
    """One explicit labelled row bound to a candidate and CRN continuation."""

    deal_sha256: str
    slot_sha256: str
    state_sha256: str
    candidate_set_sha256: str
    candidate_index: int
    protected_incumbent: bool
    successor_sha256: str
    continuation_sha256: str
    replica: int
    source: str
    split: str
    role: str
    phase: str
    position: str
    trump_rank: str
    trump_mode: str
    points_bucket: str
    tensors: WorldAfterstateTensorsV0
    signed_level_category: int
    cohort: str = "primary"
    schema: str = EXAMPLE_SCHEMA

    def validate(self) -> None:
        for label, value in (
                ("deal SHA-256", self.deal_sha256),
                ("slot SHA-256", self.slot_sha256),
                ("state SHA-256", self.state_sha256),
                ("candidate-set SHA-256", self.candidate_set_sha256),
                ("successor SHA-256", self.successor_sha256),
                ("continuation SHA-256", self.continuation_sha256)):
            _digest(value, label)
        if self.schema != EXAMPLE_SCHEMA or self.source not in STATE_SOURCES \
                or self.cohort not in COHORTS \
                or self.role not in ("attacker", "defender") \
                or self.phase not in ("early", "middle", "late") \
                or self.position not in ("lead", "follow") \
                or self.trump_rank not in tuple("23456789TJQKA") \
                or self.trump_mode not in TRUMP_MODES \
                or self.points_bucket not in PRIOR_POINTS_BUCKETS:
            raise WorldAfterstateV2TrainingError("V2 training row identity drift")
        if self.split not in TRAINING_SPLITS:
            raise WorldAfterstateV2TrainingError("V2 training split refused")
        _strict_int(self.candidate_index, "candidate index")
        _strict_int(self.replica, "continuation replica")
        if self.replica not in REPLICATES or type(self.protected_incumbent) is not bool \
                or self.protected_incumbent != (self.candidate_index == 0):
            raise WorldAfterstateV2TrainingError("V2 incumbent/replica binding drift")
        self.tensors.validate()
        _strict_int(self.signed_level_category, "terminal category")
        # Avoid importing a second copy of the category table: the model's
        # loss validates the range, and this check keeps malformed rows out of
        # a batch before tensors are assembled.
        if self.signed_level_category >= OUTCOME_CLASSES:
            raise WorldAfterstateV2TrainingError("terminal category drift")

    @property
    def target_category(self) -> int:
        self.validate()
        return self.signed_level_category

    @property
    def target_terminal_category(self) -> int:
        return self.target_category

    @property
    def continuation_replica(self) -> int:
        self.validate()
        return self.replica

    @property
    def root_key(self) -> str:
        self.validate()
        return _sha({
            "deal_sha256": self.deal_sha256,
            "slot_sha256": self.slot_sha256,
            "state_sha256": self.state_sha256,
            "candidate_set_sha256": self.candidate_set_sha256,
        })

    @property
    def example_key(self) -> str:
        self.validate()
        return f"{self.root_key}:{self.candidate_index}:{self.replica}"


@dataclass(frozen=True)
class WorldAfterstateV2TrainingConfig:
    """Explicit optimizer values; sigma is frozen before an epoch starts."""

    learning_rate_ppb: int
    weight_decay_ppb: int
    gradient_norm_milli: int
    max_epochs: int
    sigma_pair_squared: float
    schema: str = CONFIG_SCHEMA

    def validate(self) -> None:
        if self.schema != CONFIG_SCHEMA \
                or isinstance(self.learning_rate_ppb, bool) \
                or not isinstance(self.learning_rate_ppb, int) \
                or not 1 <= self.learning_rate_ppb <= LOSS_SCALE \
                or isinstance(self.weight_decay_ppb, bool) \
                or not isinstance(self.weight_decay_ppb, int) \
                or not 0 <= self.weight_decay_ppb <= LOSS_SCALE \
                or isinstance(self.gradient_norm_milli, bool) \
                or not isinstance(self.gradient_norm_milli, int) \
                or not 1 <= self.gradient_norm_milli <= LOSS_SCALE \
                or isinstance(self.max_epochs, bool) \
                or not isinstance(self.max_epochs, int) \
                or not 1 <= self.max_epochs <= 20 \
                or isinstance(self.sigma_pair_squared, bool) \
                or not isinstance(self.sigma_pair_squared, (int, float)) \
                or not math.isfinite(self.sigma_pair_squared) \
                or self.sigma_pair_squared < 0:
            raise WorldAfterstateV2TrainingError("V2 training config drift")

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {"schema": self.schema,
                "learning_rate_ppb": self.learning_rate_ppb,
                "weight_decay_ppb": self.weight_decay_ppb,
                "gradient_norm_milli": self.gradient_norm_milli,
                "max_epochs": self.max_epochs,
                "sigma_pair_squared": self.sigma_pair_squared}

    def sha256(self) -> str:
        return _sha(self.payload())


@dataclass(frozen=True)
class WorldAfterstateV2TrainingBatch:
    """Complete roots plus target-free tensors and labels kept out of them."""

    example_keys: tuple[str, ...]
    root_ids: tuple[str, ...]
    candidate_indexes: tuple[int, ...]
    replicates: tuple[int, ...]
    deal_sha256s: tuple[str, ...]
    slot_sha256s: tuple[str, ...]
    state_sha256s: tuple[str, ...]
    candidate_set_sha256s: tuple[str, ...]
    successor_sha256s: tuple[str, ...]
    continuation_sha256s: tuple[str, ...]
    sources: tuple[str, ...]
    roles: tuple[str, ...]
    phases: tuple[str, ...]
    positions: tuple[str, ...]
    trump_ranks: tuple[str, ...]
    trump_modes: tuple[str, ...]
    points_buckets: tuple[str, ...]
    target_categories: torch.Tensor
    split: str
    cohort: str
    tensors: WorldAfterstateV2Batch
    schema: str = BATCH_SCHEMA

    def validate(self) -> None:
        count = len(self.example_keys)
        fields = (self.root_ids, self.candidate_indexes, self.replicates,
                  self.deal_sha256s, self.slot_sha256s, self.state_sha256s,
                  self.candidate_set_sha256s, self.successor_sha256s,
                  self.continuation_sha256s, self.sources, self.roles,
                  self.phases, self.positions, self.trump_ranks,
                  self.trump_modes, self.points_buckets)
        if self.schema != BATCH_SCHEMA or count < 1 \
                or type(self.example_keys) is not tuple \
                or len(set(self.example_keys)) != count \
                or any(type(value) is not tuple or len(value) != count
                       for value in fields) \
                or self.split not in TRAINING_SPLITS \
                or self.cohort not in COHORTS \
                or type(self.tensors) is not WorldAfterstateV2Batch \
                or self.target_categories.device.type != "cpu" \
                or self.target_categories.dtype != torch.long \
                or self.target_categories.shape != (count,):
            raise WorldAfterstateV2TrainingError("V2 training batch identity drift")
        self.tensors.validate()
        if self.tensors.size != count:
            raise WorldAfterstateV2TrainingError("V2 model/target row count drift")
        if any(type(key) is not str or not key for key in self.example_keys) \
                or any(type(root) is not str or not root for root in self.root_ids):
            raise WorldAfterstateV2TrainingError("V2 training key drift")
        for digest in (*self.deal_sha256s, *self.slot_sha256s,
                       *self.state_sha256s, *self.candidate_set_sha256s,
                       *self.successor_sha256s, *self.continuation_sha256s):
            _digest(digest, "V2 training batch digest")
        if bool(torch.any(self.target_categories < 0)) \
                or bool(torch.any(self.target_categories >= OUTCOME_CLASSES)):
            raise WorldAfterstateV2TrainingError("V2 training target drift")
        groups: dict[str, list[tuple[int, int]]] = defaultdict(list)
        metadata: dict[str, tuple[str, ...]] = {}
        successors: dict[str, dict[int, str]] = defaultdict(dict)
        continuations: dict[str, dict[int, str]] = defaultdict(dict)
        for index in range(count):
            root = self.root_ids[index]
            expected = f"{root}:{self.candidate_indexes[index]}:{self.replicates[index]}"
            if self.example_keys[index] != expected:
                raise WorldAfterstateV2TrainingError("V2 training example key drift")
            _strict_int(self.candidate_indexes[index], "batch candidate index")
            if self.replicates[index] not in REPLICATES:
                raise WorldAfterstateV2TrainingError("V2 training replica drift")
            if self.sources[index] not in STATE_SOURCES \
                    or self.roles[index] not in ("attacker", "defender") \
                    or self.phases[index] not in ("early", "middle", "late") \
                    or self.positions[index] not in ("lead", "follow") \
                    or self.trump_ranks[index] not in tuple("23456789TJQKA") \
                    or self.trump_modes[index] not in TRUMP_MODES \
                    or self.points_buckets[index] not in PRIOR_POINTS_BUCKETS:
                raise WorldAfterstateV2TrainingError(
                    "V2 batch public stratum drift")
            identity = (self.deal_sha256s[index], self.slot_sha256s[index],
                        self.state_sha256s[index], self.candidate_set_sha256s[index],
                        self.sources[index], self.roles[index],
                        self.phases[index], self.positions[index],
                        self.trump_ranks[index], self.trump_modes[index],
                        self.points_buckets[index],
                        self.split, self.cohort)
            prior = metadata.setdefault(root, identity)
            if prior != identity:
                raise WorldAfterstateV2TrainingError("V2 root identity drift")
            pair = (self.candidate_indexes[index], self.replicates[index])
            if pair in groups[root]:
                raise WorldAfterstateV2TrainingError("duplicate V2 training example")
            groups[root].append(pair)
            candidate = self.candidate_indexes[index]
            replica = self.replicates[index]
            if replica in continuations[root] and continuations[root][replica] \
                    != self.continuation_sha256s[index]:
                raise WorldAfterstateV2TrainingError("V2 CRN continuation binding drift")
            continuations[root][replica] = self.continuation_sha256s[index]
            if candidate in successors[root] and successors[root][candidate] \
                    != self.successor_sha256s[index]:
                raise WorldAfterstateV2TrainingError("V2 successor replica binding drift")
            successors[root][candidate] = self.successor_sha256s[index]
        for root, pairs in groups.items():
            candidates = sorted({candidate for candidate, _ in pairs})
            if candidates != list(range(len(candidates))) or len(candidates) < 2 \
                    or sorted(pairs) != [(c, r) for c in candidates for r in REPLICATES]:
                raise WorldAfterstateV2TrainingError("V2 incomplete sibling root")
            if len(set(successors[root].values())) != len(candidates):
                raise WorldAfterstateV2TrainingError("V2 duplicate successor identity")
            if set(continuations[root]) != set(REPLICATES):
                raise WorldAfterstateV2TrainingError("V2 incomplete CRN replicas")
            expected_set = _sha({
                "schema": "world-afterstate-v2-candidate-set-v1",
                "state_sha256": metadata[root][2],
                "successor_sha256s": [successors[root][candidate]
                                       for candidate in candidates],
            })
            if metadata[root][3] != expected_set:
                raise WorldAfterstateV2TrainingError(
                    "V2 candidate-set reconstruction drift")
            for candidate in candidates:
                replica_rows = [index for index in range(count)
                                if self.root_ids[index] == root
                                and self.candidate_indexes[index] == candidate]
                first = replica_rows[0]
                for index in replica_rows[1:]:
                    if (self.tensors.history_lengths[index]
                            != self.tensors.history_lengths[first]
                            or not all(torch.equal(tensor[index], tensor[first])
                                       for tensor in (
                                           self.tensors.public,
                                           self.tensors.history,
                                           self.tensors.world,
                                           self.tensors.perspective))):
                        raise WorldAfterstateV2TrainingError(
                            "V2 continuation changed model input")

    @property
    def size(self) -> int:
        self.validate()
        return len(self.example_keys)

    @property
    def root_count(self) -> int:
        self.validate()
        return len(set(self.root_ids))

    @property
    def labels(self) -> torch.Tensor:
        """Compatibility spelling; labels remain outside ``tensors``."""
        self.validate()
        return self.target_categories


def collate_training_examples(
        values: Sequence[WorldAfterstateV2TrainingExample], *,
        split: str = "fit", cohort: str = "primary") \
        -> WorldAfterstateV2TrainingBatch:
    if type(values) not in (list, tuple) or not values \
            or split not in TRAINING_SPLITS or cohort not in COHORTS \
            or any(type(value) is not WorldAfterstateV2TrainingExample
                   for value in values):
        raise WorldAfterstateV2TrainingError("V2 training example population drift")
    rows = []
    for value in values:
        value.validate()
        if value.split != split or value.cohort != cohort:
            raise WorldAfterstateV2TrainingError(
                "V2 training split/cohort binding drift")
        rows.append(value)
    # Stable root/candidate/replica order is part of the training receipt.
    rows.sort(key=lambda value: (value.root_key, value.candidate_index, value.replica))
    tensors = collate_world_afterstate_tensors([value.tensors for value in rows])
    result = WorldAfterstateV2TrainingBatch(
        example_keys=tuple(value.example_key for value in rows),
        root_ids=tuple(value.root_key for value in rows),
        candidate_indexes=tuple(value.candidate_index for value in rows),
        replicates=tuple(value.replica for value in rows),
        deal_sha256s=tuple(value.deal_sha256 for value in rows),
        slot_sha256s=tuple(value.slot_sha256 for value in rows),
        state_sha256s=tuple(value.state_sha256 for value in rows),
        candidate_set_sha256s=tuple(value.candidate_set_sha256 for value in rows),
        successor_sha256s=tuple(value.successor_sha256 for value in rows),
        continuation_sha256s=tuple(value.continuation_sha256 for value in rows),
        sources=tuple(value.source for value in rows),
        roles=tuple(value.role for value in rows),
        phases=tuple(value.phase for value in rows),
        positions=tuple(value.position for value in rows),
        trump_ranks=tuple(value.trump_rank for value in rows),
        trump_modes=tuple(value.trump_mode for value in rows),
        points_buckets=tuple(value.points_bucket for value in rows),
        target_categories=torch.as_tensor(
            [value.signed_level_category for value in rows], dtype=torch.long),
        split=split, cohort=cohort, tensors=tensors)
    result.validate()
    return result


def model_state_sha256(model: WorldAfterstateValueV2) -> str:
    if type(model) is not WorldAfterstateValueV2 \
            or any(parameter.device.type != "cpu" or parameter.dtype != torch.float32
                   for parameter in model.parameters()):
        raise WorldAfterstateV2TrainingError("V2 model state device/dtype drift")
    digest = hashlib.sha256(canonical_json_bytes({
        "schema": STATE_SCHEMA,
        "parameter_names": [name for name, _ in model.named_parameters()],
    }))
    for name, parameter in model.named_parameters():
        array = parameter.detach().contiguous().numpy().astype("<f4", copy=False)
        raw = array.tobytes(order="C")
        header = canonical_json_bytes({"name": name, "shape": list(array.shape),
                                       "dtype": "little-endian-float32",
                                       "byte_count": len(raw)})
        digest.update(len(header).to_bytes(8, "big")); digest.update(header)
        digest.update(len(raw).to_bytes(8, "big")); digest.update(raw)
    return digest.hexdigest()


def new_optimizer(model: WorldAfterstateValueV2,
                  config: WorldAfterstateV2TrainingConfig) -> torch.optim.AdamW:
    config.validate(); _ = model_state_sha256(model)
    return torch.optim.AdamW(model.parameters(),
                             lr=config.learning_rate_ppb / LOSS_SCALE,
                             weight_decay=config.weight_decay_ppb / LOSS_SCALE,
                             foreach=False, fused=False)


def _validate_optimizer(model: WorldAfterstateValueV2, optimizer: torch.optim.Optimizer,
                        config: WorldAfterstateV2TrainingConfig) -> None:
    config.validate()
    if type(optimizer) is not torch.optim.AdamW or len(optimizer.param_groups) != 1:
        raise WorldAfterstateV2TrainingError("V2 optimizer identity drift")
    group = optimizer.param_groups[0]
    if group["lr"] != config.learning_rate_ppb / LOSS_SCALE \
            or group["weight_decay"] != config.weight_decay_ppb / LOSS_SCALE \
            or group["foreach"] is not False or group["fused"] is not False \
            or len(group["params"]) != len(tuple(model.parameters())) \
            or any(left is not right for left, right in zip(
                group["params"], model.parameters(), strict=True)):
        raise WorldAfterstateV2TrainingError("V2 optimizer configuration drift")


def root_balanced_loss(logits: torch.Tensor,
                       batch: WorldAfterstateV2TrainingBatch,
                       sigma_pair_squared: float | torch.Tensor = 1.0) -> torch.Tensor:
    """Absolute and paired terms, each root-balanced and weighted 1:1."""
    batch.validate()
    if logits.shape != (batch.size, OUTCOME_CLASSES) \
            or logits.dtype != torch.float32 \
            or not bool(torch.all(torch.isfinite(logits))):
        raise WorldAfterstateV2TrainingError("V2 training logits drift")
    if isinstance(sigma_pair_squared, torch.Tensor):
        if sigma_pair_squared.ndim != 0 or sigma_pair_squared.dtype \
                not in (torch.float32, torch.float64) \
                or not bool(torch.isfinite(sigma_pair_squared)) \
                or bool(sigma_pair_squared < 0):
            raise WorldAfterstateV2TrainingError("V2 frozen pair variance drift")
        sigma_value = float(sigma_pair_squared)
    elif isinstance(sigma_pair_squared, bool) \
            or not isinstance(sigma_pair_squared, (int, float)) \
            or not math.isfinite(sigma_pair_squared) or sigma_pair_squared < 0:
        raise WorldAfterstateV2TrainingError("V2 frozen pair variance drift")
    else:
        sigma_value = float(sigma_pair_squared)
    denominator = max(1.0, sigma_value)
    absolute_rows = absolute_cross_entropy_rows(logits, batch.target_categories)
    locations: dict[str, list[int]] = defaultdict(list)
    for index, root in enumerate(batch.root_ids):
        locations[root].append(index)
    root_losses = []
    for root in sorted(locations):
        indices = locations[root]
        absolute = absolute_rows[torch.as_tensor(indices)].mean()
        by_pair = {(batch.candidate_indexes[i], batch.replicates[i]): i
                   for i in indices}
        pair_rows = []
        for candidate in sorted({batch.candidate_indexes[i] for i in indices}):
            if candidate == 0:
                continue
            candidate_rows = [by_pair[(candidate, replica)]
                              for replica in REPLICATES]
            incumbent_rows = [by_pair[(0, replica)]
                              for replica in REPLICATES]
            prediction = expected_signed_utility(logits[candidate_rows]).mean() \
                - expected_signed_utility(logits[incumbent_rows]).mean()
            target = sum(
                category_signed_level(int(batch.target_categories[candidate_row]))
                - category_signed_level(
                    int(batch.target_categories[incumbent_row]))
                for candidate_row, incumbent_row in zip(
                    candidate_rows, incumbent_rows, strict=True)
            ) / len(REPLICATES)
            pair_rows.append((prediction - target).square() / denominator)
        pair = torch.stack(pair_rows).mean()
        root_losses.append(absolute + pair)
    result = torch.stack(root_losses).mean()
    if result.ndim != 0 or not bool(torch.isfinite(result)):
        raise WorldAfterstateV2TrainingError("V2 root-balanced loss drift")
    return result


@dataclass(frozen=True)
class WorldAfterstateV2EpochReceipt:
    epoch: int
    batch_count: int
    example_count: int
    root_count: int
    mean_root_loss_nano: int
    config_sha256: str
    population_sha256: str
    schedule_sha256: str
    model_state_sha256_before: str
    model_state_sha256_after: str
    split: str
    cohort: str
    schema: str = EPOCH_SCHEMA

    def validate(self) -> None:
        integers = (self.epoch, self.batch_count, self.example_count,
                    self.root_count, self.mean_root_loss_nano)
        if self.schema != EPOCH_SCHEMA or any(isinstance(value, bool)
                or not isinstance(value, int) for value in integers) \
                or any(value <= 0 for value in integers[:4]) \
                or self.mean_root_loss_nano < 0 \
                or self.root_count > self.example_count \
                or self.split not in TRAINING_SPLITS or self.cohort not in COHORTS \
                or self.model_state_sha256_before == self.model_state_sha256_after:
            raise WorldAfterstateV2TrainingError("V2 epoch receipt drift")
        for value in (self.config_sha256, self.population_sha256,
                      self.schedule_sha256, self.model_state_sha256_before,
                      self.model_state_sha256_after):
            _digest(value, "V2 epoch receipt digest")

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {"schema": self.schema, "epoch": self.epoch,
                "batch_count": self.batch_count, "example_count": self.example_count,
                "root_count": self.root_count,
                "mean_root_loss_nano": self.mean_root_loss_nano,
                "config_sha256": self.config_sha256,
                "population_sha256": self.population_sha256,
                "schedule_sha256": self.schedule_sha256,
                "model_state_sha256_before": self.model_state_sha256_before,
                "model_state_sha256_after": self.model_state_sha256_after,
                "split": self.split, "cohort": self.cohort,
                "authority": {"training_launch_authorized": False,
                               "audit_opening_authorized": False}}

    def sha256(self) -> str:
        return _sha(self.payload())


def train_epoch(model: WorldAfterstateValueV2, optimizer: torch.optim.Optimizer,
                batches: tuple[WorldAfterstateV2TrainingBatch, ...], *, epoch: int,
                config: WorldAfterstateV2TrainingConfig) -> WorldAfterstateV2EpochReceipt:
    config.validate()
    if isinstance(epoch, bool) or not isinstance(epoch, int) \
            or not 1 <= epoch <= config.max_epochs \
            or type(batches) is not tuple or not batches \
            or any(type(batch) is not WorldAfterstateV2TrainingBatch for batch in batches):
        raise WorldAfterstateV2TrainingError("V2 epoch request drift")
    _validate_optimizer(model, optimizer, config)
    roots_seen: set[str] = set()
    population = []
    schedule = []
    total_loss = 0.0
    total_roots = 0
    total_examples = 0
    split = batches[0].split
    cohort = batches[0].cohort
    for batch in batches:
        batch.validate()
        if batch.split != split or batch.cohort != cohort:
            raise WorldAfterstateV2TrainingError("V2 epoch split/cohort mixing")
        if roots_seen.intersection(batch.root_ids):
            raise WorldAfterstateV2TrainingError("V2 root split across optimizer batches")
        roots_seen.update(batch.root_ids)
        population.extend({"example_key": key, "target_category": int(target),
                           "successor_sha256": successor,
                           "continuation_sha256": continuation}
                          for key, target, successor, continuation in zip(
                              batch.example_keys, batch.target_categories.tolist(),
                              batch.successor_sha256s, batch.continuation_sha256s,
                              strict=True))
        schedule.append(list(batch.example_keys))
    before = model_state_sha256(model)
    model.train(True)
    for batch in batches:
        optimizer.zero_grad(set_to_none=True)
        logits = model(batch.tensors)
        loss = root_balanced_loss(logits, batch, config.sigma_pair_squared)
        loss.backward()
        norm = torch.nn.utils.clip_grad_norm_(
            model.parameters(), config.gradient_norm_milli / 1000,
            error_if_nonfinite=True)
        if not bool(torch.isfinite(norm)):
            raise WorldAfterstateV2TrainingError("V2 non-finite gradient")
        optimizer.step()
        if not math.isfinite(float(loss.detach())):
            raise WorldAfterstateV2TrainingError("V2 non-finite loss")
        total_loss += float(loss.detach()) * batch.root_count
        total_roots += batch.root_count
        total_examples += batch.size
    mean = round(total_loss / total_roots * LOSS_SCALE)
    if total_roots != len(roots_seen) or total_examples != len(population) \
            or not math.isfinite(total_loss) or mean < 0:
        raise WorldAfterstateV2TrainingError("V2 epoch aggregate drift")
    receipt = WorldAfterstateV2EpochReceipt(
        epoch=epoch, batch_count=len(batches), example_count=total_examples,
        root_count=total_roots, mean_root_loss_nano=mean,
        config_sha256=config.sha256(),
        population_sha256=_sha({"schema": POPULATION_SCHEMA,
                                "rows": sorted(population, key=lambda row: row["example_key"])}),
        schedule_sha256=_sha({"schema": SCHEDULE_SCHEMA, "epoch": epoch,
                              "batch_example_keys": schedule}),
        model_state_sha256_before=before,
        model_state_sha256_after=model_state_sha256(model),
        split=split, cohort=cohort)
    receipt.validate()
    return receipt


__all__ = [
    "REPLICATES", "TRAINING_SPLITS", "COHORTS",
    "WorldAfterstateV2TrainingError", "WorldAfterstateV2TrainingExample",
    "WorldAfterstateV2TrainingBatch", "WorldAfterstateV2TrainingConfig",
    "WorldAfterstateV2EpochReceipt",
    "collate_training_examples", "model_state_sha256",
    "new_optimizer", "root_balanced_loss", "train_epoch",
]
