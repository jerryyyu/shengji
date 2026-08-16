"""Bounded-memory batch reconstruction for BELIEF-V1 V2 training.

The production population is too large to retain both every per-decision
NumPy surface and every padded Torch batch.  This module keeps only compact,
hash-bound schedule rows resident.  A caller supplies one authenticated
complete-round loader; each scheduled batch reopens only the round groups it
needs, verifies every selected example against the compact row, collates one
batch, and releases the round examples before advancing.

No filesystem path, corpus reader, model, optimizer, result, or execution
authority lives here.  Artifact-specific source reopening remains in the V2
controllers.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from .belief_training import BeliefTrainingBatchV1
from .belief_v2_schedule import (
    V2CalibrationScheduleV1,
    V2CohortRealizationV1,
    V2TrainingRowV1,
    calibration_row,
    training_row,
)
from .belief_v2_training import (
    V2TrainingExampleV1,
    collate_v2_label_control_examples,
    collate_v2_training_examples,
)


class BeliefV2StreamingTrainingError(ValueError):
    """A compact row, round loader, or bounded batch drifted."""


CONTROL_KIND = "hard-geometry-label-permutation"


@dataclass(frozen=True)
class V2StreamingSourceV1:
    """One complete public-information group and its durable source token."""

    round_group_key: str
    split: str
    source_kind: str
    source_token: str


@dataclass(frozen=True)
class V2StreamingTrainingIndexV1:
    """Compact resident identity; it deliberately contains no model arrays."""

    train_rows: tuple[V2TrainingRowV1, ...]
    calibration_rows: tuple[V2TrainingRowV1, ...]
    sources: tuple[V2StreamingSourceV1, ...]
    control_changed_cell_count: int


RoundLoader = Callable[[V2StreamingSourceV1],
                       tuple[V2TrainingExampleV1, ...]]


def validate_streaming_training_index(
        index: V2StreamingTrainingIndexV1) -> None:
    if type(index) is not V2StreamingTrainingIndexV1 \
            or type(index.train_rows) is not tuple or not index.train_rows \
            or type(index.calibration_rows) is not tuple \
            or not index.calibration_rows \
            or type(index.sources) is not tuple or not index.sources \
            or type(index.control_changed_cell_count) is not int \
            or index.control_changed_cell_count <= 0:
        raise BeliefV2StreamingTrainingError(
            "V2 streaming training index identity drift")
    all_rows = (*index.train_rows, *index.calibration_rows)
    keys = tuple(row.decision_key for row in all_rows)
    if len(keys) != len(set(keys)) \
            or any(type(row) is not V2TrainingRowV1 for row in all_rows):
        raise BeliefV2StreamingTrainingError(
            "V2 streaming training row population drift")
    by_group: dict[str, set[tuple[str, str]]] = {}
    for row in index.train_rows:
        by_group.setdefault(row.round_group_key, set()).add(
            (row.source_kind, "train"))
    for row in index.calibration_rows:
        by_group.setdefault(row.round_group_key, set()).add(
            (row.source_kind, "calibration"))
    source_groups = tuple(source.round_group_key for source in index.sources)
    if len(source_groups) != len(set(source_groups)) \
            or set(source_groups) != set(by_group) \
            or any(type(source) is not V2StreamingSourceV1
                   or type(source.round_group_key) is not str
                   or len(source.round_group_key) != 64
                   or type(source.source_token) is not str
                   or not source.source_token
                   or source.split not in {"train", "calibration"}
                   or source.source_kind not in {"synthetic", "human"}
                   or by_group[source.round_group_key]
                   != {(source.source_kind, source.split)}
                   for source in index.sources):
        raise BeliefV2StreamingTrainingError(
            "V2 streaming source population drift")


def _selected_examples(
        *, keys: tuple[str, ...], rows_by_key: dict[str, V2TrainingRowV1],
        sources_by_group: dict[str, V2StreamingSourceV1],
        load_round: RoundLoader, split: str) \
        -> tuple[V2TrainingExampleV1, ...]:
    if type(keys) is not tuple or not keys or len(keys) != len(set(keys)) \
            or any(key not in rows_by_key for key in keys):
        raise BeliefV2StreamingTrainingError(
            "V2 streaming batch decision population drift")
    requested = set(keys)
    groups = tuple(dict.fromkeys(
        rows_by_key[key].round_group_key for key in keys))
    loaded: dict[str, V2TrainingExampleV1] = {}
    for group in groups:
        source = sources_by_group.get(group)
        if source is None or source.split != split:
            raise BeliefV2StreamingTrainingError(
                "V2 streaming batch source binding drift")
        examples = load_round(source)
        if type(examples) is not tuple or not examples \
                or any(type(example) is not V2TrainingExampleV1
                       or example.round_group_key != group
                       or example.source_kind != source.source_kind
                       or example.split != split for example in examples):
            raise BeliefV2StreamingTrainingError(
                "V2 streaming round example population drift")
        for example in examples:
            if example.decision_key in requested:
                if example.decision_key in loaded:
                    raise BeliefV2StreamingTrainingError(
                        "V2 streaming round decision duplicate")
                row = (training_row(example) if split == "train"
                       else calibration_row(example))
                if row != rows_by_key[example.decision_key]:
                    raise BeliefV2StreamingTrainingError(
                        "V2 streaming example/row binding drift")
                loaded[example.decision_key] = example
    if set(loaded) != requested:
        raise BeliefV2StreamingTrainingError(
            "V2 streaming scheduled decision was not reopened")
    return tuple(loaded[key] for key in keys)


def iter_streaming_training_batches(
        index: V2StreamingTrainingIndexV1,
        realization: V2CohortRealizationV1, *,
        load_round: RoundLoader) -> Iterator[BeliefTrainingBatchV1]:
    """Reopen and release one exact scheduled train batch at a time."""
    validate_streaming_training_index(index)
    try:
        realization.canonical_bytes()
    except ValueError as exc:
        raise BeliefV2StreamingTrainingError(
            "V2 streaming realization refused") from exc
    rows_by_key = {row.decision_key: row for row in index.train_rows}
    if set(rows_by_key) != {row.decision_key for row in index.train_rows} \
            or any(row.decision_key not in rows_by_key
                   or rows_by_key[row.decision_key] != row
                   for row in realization.rows):
        raise BeliefV2StreamingTrainingError(
            "V2 streaming realization/index drift")
    sources = {row.round_group_key: row for row in index.sources}
    changed = 0
    for keys in realization.batches:
        selected = _selected_examples(
            keys=keys, rows_by_key=rows_by_key,
            sources_by_group=sources, load_round=load_round, split="train")
        if realization.kind == CONTROL_KIND:
            batch, dose = collate_v2_label_control_examples(selected)
            changed += dose
        else:
            batch = collate_v2_training_examples(selected)
        yield batch
    if realization.kind == CONTROL_KIND:
        if changed != index.control_changed_cell_count:
            raise BeliefV2StreamingTrainingError(
                "V2 streaming label-control dose drift")
    elif changed != 0:
        raise BeliefV2StreamingTrainingError(
            "V2 streaming natural cohort has control dose")


def iter_streaming_calibration_batches(
        index: V2StreamingTrainingIndexV1,
        schedule: V2CalibrationScheduleV1, *,
        load_round: RoundLoader) -> Iterator[BeliefTrainingBatchV1]:
    """Reopen and release one common calibration batch at a time."""
    validate_streaming_training_index(index)
    try:
        schedule.canonical_bytes()
    except ValueError as exc:
        raise BeliefV2StreamingTrainingError(
            "V2 streaming calibration schedule refused") from exc
    rows_by_key = {row.decision_key: row
                   for row in index.calibration_rows}
    if set(rows_by_key) != {row.decision_key for row in schedule.rows} \
            or any(rows_by_key.get(row.decision_key) != row
                   for row in schedule.rows):
        raise BeliefV2StreamingTrainingError(
            "V2 streaming calibration/index drift")
    sources = {row.round_group_key: row for row in index.sources}
    for keys in schedule.batches:
        yield collate_v2_training_examples(_selected_examples(
            keys=keys, rows_by_key=rows_by_key,
            sources_by_group=sources, load_round=load_round,
            split="calibration"))


def resident_array_bytes(value: Any) -> int:
    """Return NumPy/Torch payload bytes reachable from a materialized object.

    This diagnostic helper is intentionally structural and has no gate or
    execution authority.  Tests use it to prove that the compact index holds
    no model arrays and that the iterator retains at most one yielded batch.
    """
    try:
        import numpy as np
        import torch
    except ImportError:  # pragma: no cover - runtime dependencies are pinned
        return 0
    seen: set[int] = set()

    def walk(current: Any) -> int:
        identity = id(current)
        if identity in seen:
            return 0
        seen.add(identity)
        if isinstance(current, np.ndarray):
            return int(current.nbytes)
        if isinstance(current, torch.Tensor):
            return int(current.numel() * current.element_size())
        if isinstance(current, dict):
            return sum(walk(key) + walk(item)
                       for key, item in current.items())
        if isinstance(current, (tuple, list, set, frozenset)):
            return sum(walk(item) for item in current)
        fields = getattr(current, "__dataclass_fields__", None)
        if fields is not None:
            return sum(walk(getattr(current, name)) for name in fields)
        return 0

    return walk(value)
