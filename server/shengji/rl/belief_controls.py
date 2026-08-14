"""Mechanically valid negative-control examples for BELIEF-V1 B2.

The chronology control deterministically permutes the existing public event
rows within each decision while preserving every event byte and all non-event
fact tensors.  The label control permutes whole card-label rows only inside an
exact actor-hard-geometry class, preserving each card multiplicity, receiver
size, cell bound, and privileged target population.  Neither control can be
reopened as a natural candidate example or batch.

This module is in-memory only.  It has no RNG, filesystem, model, trainer,
sampler, policy, outcome, or execution surface.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace

import numpy as np
import torch

from .belief_corpus import CorpusPairV1
from .belief_training import (
    CONTROL_TRAINING_BATCH_SCHEMA,
    EXACT_TARGET_LABELS,
    GEOMETRY_PERMUTED_LABELS,
    HISTORY_ABLATION_CONTROL,
    LABEL_PERMUTATION_CONTROL,
    NATURAL_HISTORY,
    PERMUTED_HISTORY,
    BeliefTrainingBatchV1,
    BeliefTrainingExampleV1,
    build_training_example,
    collate_training_examples,
    validate_training_example,
)


CONTROL_EXAMPLE_SCHEMA = "belief-v1-b2-negative-control-example-v1"
CONTROL_KINDS = (HISTORY_ABLATION_CONTROL, LABEL_PERMUTATION_CONTROL)


class BeliefControlError(ValueError):
    """A B2 chronology or label negative control drifted."""


@dataclass(frozen=True)
class ControlTrainingExampleV1:
    pair: CorpusPairV1
    source: BeliefTrainingExampleV1
    control_kind: str
    transformed_events: np.ndarray
    transformed_count_labels: np.ndarray
    changed_event_rows: int
    changed_label_cells: int
    schema: str = CONTROL_EXAMPLE_SCHEMA


def _event_permutation(key: str, event_count: int) -> tuple[int, ...]:
    order = tuple(sorted(range(event_count), key=lambda index: (
        hashlib.sha256(
            f"{CONTROL_EXAMPLE_SCHEMA}|history|{key}|{index}".encode(
                "ascii")).digest(), index)))
    if event_count > 1 and order == tuple(range(event_count)):
        return (order[1], order[0], *order[2:])
    return order


def _history_events(source: BeliefTrainingExampleV1) -> tuple[np.ndarray, int]:
    events = source.tensors.events
    order = _event_permutation(source.decision_key, len(events))
    changed = np.ascontiguousarray(events[np.array(order, dtype=np.int64)])
    changed_rows = sum(
        not np.array_equal(changed[index], events[index])
        for index in range(len(events)))
    if len(events) > 1 and changed_rows == 0:
        raise BeliefControlError("history control permutation has zero dose")
    return changed, changed_rows


def _geometry_permuted_labels(
        source: BeliefTrainingExampleV1) -> tuple[np.ndarray, int]:
    labels = source.count_labels
    active = source.active_mask
    minimums = source.tensors.count_minimums
    maximums = source.tensors.count_maximums
    groups: dict[tuple[int, ...], list[int]] = {}
    for card in range(labels.shape[0]):
        if not bool(active[card].any()):
            continue
        key = (*tuple(int(value) for value in minimums[card]),
               *tuple(int(value) for value in maximums[card]),
               int(labels[card][active[card]].sum()))
        groups.setdefault(key, []).append(card)
    changed = labels.copy()
    for cards in groups.values():
        if len(cards) < 2:
            continue
        ordered = sorted(cards, key=lambda card: (
            hashlib.sha256(
                f"{CONTROL_EXAMPLE_SCHEMA}|labels|"
                f"{source.decision_key}|{card}".encode("ascii")).digest(),
            card))
        sources = ordered[1:] + ordered[:1]
        for destination, source_card in zip(ordered, sources, strict=True):
            changed[destination] = labels[source_card]
    if np.any(changed[~active] != -1) \
            or np.any(changed[active] < minimums[active]) \
            or np.any(changed[active] > maximums[active]) \
            or not np.array_equal(changed.sum(axis=1), labels.sum(axis=1)) \
            or not np.array_equal(changed.sum(axis=0), labels.sum(axis=0)):
        raise BeliefControlError("label control violates hard geometry")
    changed_cells = int(np.count_nonzero(changed != labels))
    return np.ascontiguousarray(changed), changed_cells


def _build_control_example(
        pair: CorpusPairV1, *, behavior_policy_ids: tuple[str, ...],
        control_kind: str) -> ControlTrainingExampleV1:
    if control_kind not in CONTROL_KINDS:
        raise BeliefControlError("negative control kind is invalid")
    source = build_training_example(
        pair, behavior_policy_ids=behavior_policy_ids)
    if control_kind == HISTORY_ABLATION_CONTROL:
        events, changed_events = _history_events(source)
        labels = source.count_labels.copy()
        changed_labels = 0
    else:
        events = source.tensors.events.copy()
        changed_events = 0
        labels, changed_labels = _geometry_permuted_labels(source)
    return ControlTrainingExampleV1(
        pair=pair, source=source, control_kind=control_kind,
        transformed_events=np.ascontiguousarray(events),
        transformed_count_labels=np.ascontiguousarray(labels),
        changed_event_rows=changed_events,
        changed_label_cells=changed_labels,
    )


def build_control_example(
        pair: CorpusPairV1, *, behavior_policy_ids: tuple[str, ...],
        control_kind: str) -> ControlTrainingExampleV1:
    result = _build_control_example(
        pair, behavior_policy_ids=behavior_policy_ids,
        control_kind=control_kind)
    validate_control_example(result)
    return result


def validate_control_example(example: ControlTrainingExampleV1) -> None:
    if type(example) is not ControlTrainingExampleV1 \
            or example.schema != CONTROL_EXAMPLE_SCHEMA \
            or example.control_kind not in CONTROL_KINDS \
            or type(example.pair) is not CorpusPairV1 \
            or type(example.source) is not BeliefTrainingExampleV1 \
            or type(example.transformed_events) is not np.ndarray \
            or example.transformed_events.dtype != np.float32 \
            or type(example.transformed_count_labels) is not np.ndarray \
            or example.transformed_count_labels.dtype != np.int64 \
            or type(example.changed_event_rows) is not int \
            or type(example.changed_label_cells) is not int \
            or min(example.changed_event_rows,
                   example.changed_label_cells) < 0:
        raise BeliefControlError("negative control example schema drift")
    try:
        validate_training_example(example.pair, example.source)
    except ValueError as exc:
        raise BeliefControlError("negative control source refused") from exc
    expected = _build_control_example(
        example.pair,
        behavior_policy_ids=example.source.tensors.behavior_policy_ids,
        control_kind=example.control_kind)
    scalar_fields = ("schema", "control_kind", "changed_event_rows",
                     "changed_label_cells")
    if any(getattr(example, field) != getattr(expected, field)
           for field in scalar_fields) \
            or example.pair != expected.pair \
            or not np.array_equal(
                example.transformed_events, expected.transformed_events) \
            or not np.array_equal(
                example.transformed_count_labels,
                expected.transformed_count_labels):
        raise BeliefControlError("negative control derivation drift")


def collate_control_examples(
        examples: tuple[ControlTrainingExampleV1, ...]) \
        -> BeliefTrainingBatchV1:
    if type(examples) is not tuple or not examples \
            or any(type(example) is not ControlTrainingExampleV1
                   for example in examples):
        raise BeliefControlError("negative control batch population drift")
    for example in examples:
        validate_control_example(example)
    kinds = {example.control_kind for example in examples}
    if len(kinds) != 1:
        raise BeliefControlError("negative control batch mixes controls")
    source_batch = collate_training_examples(tuple(
        example.source for example in examples))
    max_events = source_batch.events.shape[1]
    events = np.zeros(tuple(source_batch.events.shape), dtype=np.float32)
    for index, example in enumerate(examples):
        length = len(example.transformed_events)
        events[index, :length] = example.transformed_events
    labels = torch.from_numpy(np.stack([
        example.transformed_count_labels for example in examples]))
    kind = next(iter(kinds))
    if kind == HISTORY_ABLATION_CONTROL:
        history_transform = PERMUTED_HISTORY
        label_transform = EXACT_TARGET_LABELS
    else:
        history_transform = NATURAL_HISTORY
        label_transform = GEOMETRY_PERMUTED_LABELS
    return replace(
        source_batch, schema=CONTROL_TRAINING_BATCH_SCHEMA,
        events=torch.from_numpy(events), count_labels=labels,
        history_transform=history_transform,
        label_transform=label_transform, control_kind=kind)
