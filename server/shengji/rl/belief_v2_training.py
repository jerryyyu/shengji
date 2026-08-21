"""Source-neutral privileged training boundary for BELIEF-V1 V2.

Synthetic and historical-human rows are independently reopened, reduced to the
same conservative public-history tensor surface, and paired with physically
separate ownership targets.  Source kind remains receipt metadata and never
enters a model tensor or batch field.

This module has no corpus enumerator, filesystem path reader, scheduler,
optimizer, model mutation, checkpoint writer, test opener, or run authority.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace

import numpy as np
import torch

from .belief_corpus import SPLITS, CorpusPairV1
from .belief_evaluation import reopen_score_pair
from .belief_input import CARD_CODES
from .belief_tensor import MAX_RECEIVERS
from .belief_training import (
    CONTROL_TRAINING_BATCH_SCHEMA,
    EXACT_TARGET_LABELS,
    GEOMETRY_PERMUTED_LABELS,
    LABEL_PERMUTATION_CONTROL,
    NATURAL_HISTORY,
    BeliefTrainingBatchV1,
    BeliefTrainingError,
    _labels,
)
from .belief_v2_common_surface import (
    V2CommonSurfaceTensorsV1,
    build_common_surface_tensors,
    validate_common_surface_tensors,
)
from .belief_v2_human_corpus import (
    UNIVERSAL_POLICY_IDS,
    validate_human_corpus_pair,
)


V2_TRAINING_EXAMPLE_SCHEMA = "belief-v1-v2-training-example-v1"
SOURCE_KINDS = ("synthetic", "human")


class BeliefV2TrainingError(ValueError):
    """A V2 source, target, common tensor, label, or batch drifted."""


@dataclass(frozen=True)
class V2TrainingExampleV1:
    decision_key: str
    round_group_key: str
    split: str
    source_kind: str
    source_actor_sha256: str
    common_surface_sha256: str
    privileged_target_sha256: str
    common: V2CommonSurfaceTensorsV1
    count_labels: np.ndarray
    active_mask: np.ndarray
    privileged_targets_consumed: bool = True
    source_identity_model_input: bool = False
    runtime_artifact: bool = False
    schema: str = V2_TRAINING_EXAMPLE_SCHEMA


def _example(
        *, decision_key: str, round_group_key: str,
        split: str, source_kind: str,
        actor, target) -> V2TrainingExampleV1:
    if type(decision_key) is not str or len(decision_key) != 64 \
            or any(char not in "0123456789abcdef" for char in decision_key) \
            or type(round_group_key) is not str \
            or len(round_group_key) != 64 \
            or any(char not in "0123456789abcdef"
                   for char in round_group_key) \
            or split not in SPLITS or source_kind not in SOURCE_KINDS:
        raise BeliefV2TrainingError("V2 training metadata drift")
    try:
        common = build_common_surface_tensors(
            actor, behavior_policy_ids=UNIVERSAL_POLICY_IDS)
        labels, active = _labels(actor, target, common.tensors)
    except (TypeError, ValueError, BeliefTrainingError) as exc:
        raise BeliefV2TrainingError(
            "V2 training common target derivation refused") from exc
    return V2TrainingExampleV1(
        decision_key=decision_key, round_group_key=round_group_key,
        split=split, source_kind=source_kind,
        source_actor_sha256=actor.sha256(),
        common_surface_sha256=common.sha256(),
        privileged_target_sha256=target.sha256(), common=common,
        count_labels=labels, active_mask=active,
    )


def build_synthetic_training_example(
        pair: CorpusPairV1) -> V2TrainingExampleV1:
    """Build one V2 example from an exact simulator actor/target pair."""
    try:
        actor, target, metadata = reopen_score_pair(pair)
    except (TypeError, ValueError) as exc:
        raise BeliefV2TrainingError(
            "V2 synthetic training pair refused") from exc
    result = _example(
        decision_key=metadata["decision_key"],
        round_group_key=hashlib.sha256(
            f"belief-v1-v2-synthetic-round|{metadata['round_seed']}".encode(
                "ascii")).hexdigest(),
        split=metadata["split"],
        source_kind="synthetic", actor=actor, target=target)
    # ``_example`` is the sole constructor and already derives the complete
    # typed surface from the reopened source.  Re-running the public validator
    # here rebuilt that same surface a second time through the same function.
    # Keep the validator for independently supplied/reopened candidates; the
    # streaming index and batch readers additionally bind this result's exact
    # identity back to the frozen schedule row.
    return result


def validate_synthetic_training_example(
        pair: CorpusPairV1, candidate: V2TrainingExampleV1) -> None:
    try:
        actor, target, metadata = reopen_score_pair(pair)
    except (TypeError, ValueError) as exc:
        raise BeliefV2TrainingError(
            "V2 synthetic training pair refused") from exc
    expected = _example(
        decision_key=metadata["decision_key"],
        round_group_key=hashlib.sha256(
            f"belief-v1-v2-synthetic-round|{metadata['round_seed']}".encode(
                "ascii")).hexdigest(),
        split=metadata["split"],
        source_kind="synthetic", actor=actor, target=target)
    _validate_example(actor, candidate, expected)


def build_human_training_example(
        actor_raw: bytes, target_raw: bytes) -> V2TrainingExampleV1:
    """Build one V2 example from separated historical-human row bytes."""
    try:
        actor, target, _, metadata = validate_human_corpus_pair(
            actor_raw, target_raw)
    except (TypeError, ValueError) as exc:
        raise BeliefV2TrainingError("V2 human training pair refused") from exc
    result = _example(
        decision_key=metadata["decision_key"],
        round_group_key=metadata["round_digest"], split=metadata["split"],
        source_kind="human", actor=actor, target=target)
    # As above, avoid immediately repeating the same full derivation.  The
    # explicit validator remains the independent boundary for any candidate
    # supplied from outside this controlled constructor.
    return result


def validate_human_training_example(
        actor_raw: bytes, target_raw: bytes,
        candidate: V2TrainingExampleV1) -> None:
    try:
        actor, target, _, metadata = validate_human_corpus_pair(
            actor_raw, target_raw)
    except (TypeError, ValueError) as exc:
        raise BeliefV2TrainingError("V2 human training pair refused") from exc
    expected = _example(
        decision_key=metadata["decision_key"],
        round_group_key=metadata["round_digest"], split=metadata["split"],
        source_kind="human", actor=actor, target=target)
    _validate_example(actor, candidate, expected)


def _validate_example(actor, candidate, expected) -> None:
    if type(candidate) is not V2TrainingExampleV1 \
            or candidate.schema != V2_TRAINING_EXAMPLE_SCHEMA \
            or candidate.source_kind not in SOURCE_KINDS \
            or candidate.split not in SPLITS \
            or candidate.privileged_targets_consumed is not True \
            or candidate.source_identity_model_input is not False \
            or candidate.runtime_artifact is not False \
            or type(candidate.count_labels) is not np.ndarray \
            or candidate.count_labels.dtype != np.int64 \
            or candidate.count_labels.shape \
            != (len(CARD_CODES), MAX_RECEIVERS) \
            or type(candidate.active_mask) is not np.ndarray \
            or candidate.active_mask.dtype != np.bool_ \
            or candidate.active_mask.shape \
            != (len(CARD_CODES), MAX_RECEIVERS):
        raise BeliefV2TrainingError(
            "V2 training example schema/authority drift")
    try:
        validate_common_surface_tensors(actor, candidate.common)
    except ValueError as exc:
        raise BeliefV2TrainingError(
            "V2 training common tensor refused") from exc
    scalar_fields = (
        "decision_key", "round_group_key", "split", "source_kind",
        "source_actor_sha256",
        "common_surface_sha256", "privileged_target_sha256",
        "privileged_targets_consumed", "source_identity_model_input",
        "runtime_artifact", "schema",
    )
    if any(getattr(candidate, field) != getattr(expected, field)
           for field in scalar_fields) \
            or candidate.common.canonical_bytes() \
            != expected.common.canonical_bytes() \
            or not np.array_equal(
                candidate.count_labels, expected.count_labels) \
            or not np.array_equal(candidate.active_mask, expected.active_mask):
        raise BeliefV2TrainingError("V2 training example derivation drift")


def collate_v2_training_examples(
        examples: tuple[V2TrainingExampleV1, ...]) \
        -> BeliefTrainingBatchV1:
    """Collate mixed sources without placing source identity in the batch."""
    if type(examples) is not tuple or not examples \
            or any(type(example) is not V2TrainingExampleV1
                   for example in examples):
        raise BeliefV2TrainingError("V2 training batch population drift")
    keys = tuple(example.decision_key for example in examples)
    if len(keys) != len(set(keys)):
        raise BeliefV2TrainingError("V2 training batch duplicate decision")
    splits = {example.split for example in examples}
    policy_ids = {example.common.behavior_policy_ids for example in examples}
    if len(splits) != 1 or len(policy_ids) != 1:
        raise BeliefV2TrainingError(
            "V2 training batch split/policy drift")
    for example in examples:
        tensors = example.common.tensors
        expected_active = tensors.unseen_mask[:, None] \
            & tensors.receiver_mask[None, :]
        if example.schema != V2_TRAINING_EXAMPLE_SCHEMA \
                or example.source_kind not in SOURCE_KINDS \
                or example.privileged_targets_consumed is not True \
                or example.source_identity_model_input is not False \
                or example.runtime_artifact is not False \
                or example.source_actor_sha256 \
                != example.common.source_actor_sha256 \
                or example.common_surface_sha256 != example.common.sha256() \
                or not np.array_equal(example.active_mask, expected_active) \
                or np.any(example.count_labels[~expected_active] != -1) \
                or np.any(example.count_labels[expected_active]
                          < tensors.count_minimums[expected_active]) \
                or np.any(example.count_labels[expected_active]
                          > tensors.count_maximums[expected_active]):
            raise BeliefV2TrainingError(
                "V2 training batch example binding drift")
    max_events = max(len(example.common.tensors.events)
                     for example in examples)
    event_width = examples[0].common.tensors.events.shape[1]
    events = np.zeros(
        (len(examples), max_events, event_width), dtype=np.float32)
    lengths = []
    for index, example in enumerate(examples):
        value = example.common.tensors.events
        if value.shape[1] != event_width:
            raise BeliefV2TrainingError(
                "V2 training event feature width drift")
        events[index, :len(value)] = value
        lengths.append(len(value))
    batch = BeliefTrainingBatchV1(
        decision_keys=keys, split=next(iter(splits)),
        events=torch.from_numpy(events),
        event_lengths=torch.tensor(lengths, dtype=torch.long),
        global_features=torch.from_numpy(np.stack([
            example.common.tensors.global_features
            for example in examples])),
        card_features=torch.from_numpy(np.stack([
            example.common.tensors.card_features for example in examples])),
        receiver_features=torch.from_numpy(np.stack([
            example.common.tensors.receiver_features
            for example in examples])),
        receiver_mask=torch.from_numpy(np.stack([
            example.common.tensors.receiver_mask for example in examples])),
        unseen_mask=torch.from_numpy(np.stack([
            example.common.tensors.unseen_mask for example in examples])),
        count_minimums=torch.from_numpy(np.stack([
            example.common.tensors.count_minimums for example in examples])),
        count_maximums=torch.from_numpy(np.stack([
            example.common.tensors.count_maximums for example in examples])),
        count_labels=torch.from_numpy(np.stack([
            example.count_labels for example in examples])),
        active_mask=torch.from_numpy(np.stack([
            example.active_mask for example in examples])),
    )
    # The returned type deliberately has no source-kind or source-completeness
    # field.  Those remain outside the model/trainer batch boundary.
    if hasattr(batch, "source_kind") or hasattr(batch, "source_identity"):
        raise BeliefV2TrainingError("V2 source identity entered model batch")
    return batch


def _geometry_permuted_labels(
        example: V2TrainingExampleV1) -> tuple[np.ndarray, int]:
    """Apply the V1 hard-geometry control to the V2 common surface."""
    labels = example.count_labels
    active = example.active_mask
    minimums = example.common.tensors.count_minimums
    maximums = example.common.tensors.count_maximums
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
                "belief-v1-b2-negative-control-example-v1|labels|"
                f"{example.decision_key}|{card}".encode("ascii")).digest(),
            card))
        sources = ordered[1:] + ordered[:1]
        for destination, source in zip(ordered, sources, strict=True):
            changed[destination] = labels[source]
    if np.any(changed[~active] != -1) \
            or np.any(changed[active] < minimums[active]) \
            or np.any(changed[active] > maximums[active]) \
            or not np.array_equal(changed.sum(axis=1), labels.sum(axis=1)) \
            or not np.array_equal(changed.sum(axis=0), labels.sum(axis=0)):
        raise BeliefV2TrainingError(
            "V2 label control violates hard geometry")
    return np.ascontiguousarray(changed), int(np.count_nonzero(
        changed != labels))


def collate_v2_label_control_examples(
        examples: tuple[V2TrainingExampleV1, ...]) \
        -> tuple[BeliefTrainingBatchV1, int]:
    """Build the exact V2 label control without changing public tensors."""
    natural = collate_v2_training_examples(examples)
    transformed = tuple(_geometry_permuted_labels(example)
                        for example in examples)
    labels = torch.from_numpy(np.stack(
        [value for value, _ in transformed]))
    changed_cells = sum(count for _, count in transformed)
    control = replace(
        natural, schema=CONTROL_TRAINING_BATCH_SCHEMA,
        count_labels=labels, history_transform=NATURAL_HISTORY,
        label_transform=GEOMETRY_PERMUTED_LABELS,
        control_kind=LABEL_PERMUTATION_CONTROL)
    if control.decision_keys != natural.decision_keys \
            or not torch.equal(control.events, natural.events) \
            or not torch.equal(control.active_mask, natural.active_mask) \
            or control.history_transform != NATURAL_HISTORY \
            or control.label_transform != GEOMETRY_PERMUTED_LABELS \
            or control.control_kind != LABEL_PERMUTATION_CONTROL \
            or control.schema != CONTROL_TRAINING_BATCH_SCHEMA \
            or natural.label_transform != EXACT_TARGET_LABELS:
        raise BeliefV2TrainingError("V2 label control batch drift")
    return control, changed_cells
