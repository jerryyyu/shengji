"""In-memory privileged training boundary for BELIEF-V1 ownership.

This module is the sole bridge from a separately held target into supervised
count labels.  It keeps actor-derived tensors and privileged labels explicitly
tagged, validates them against the original actor/target pair, and batches a
preordered single-split decision population.  It has no filesystem, corpus
enumerator, checkpoint writer, epoch scheduler, RNG, sampler, policy, gameplay,
or run surface.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch

from .belief_contract import ActorObservationV1, BeliefTargetsV1
from .belief_corpus import (SPLITS, CorpusPairV1, decision_key,
                            split_for_round_seed)
from .belief_evaluation import reopen_score_pair, target_count_population
from .belief_input import CARD_CODES
from .belief_model import (HistoryOwnershipModelV1,
                           masked_count_cross_entropy)
from .belief_tensor import (MAX_RECEIVERS, HistoryOwnershipTensorsV1,
                            build_history_ownership_tensors,
                            validate_history_ownership_tensors)


TRAINING_EXAMPLE_SCHEMA = "belief-v1-privileged-training-example-v1"
TRAINING_BATCH_SCHEMA = "belief-v1-privileged-training-batch-v1"


class BeliefTrainingError(ValueError):
    """A privileged training example or batch violated its closed boundary."""


@dataclass(frozen=True)
class BeliefTrainingExampleV1:
    round_seed: int
    decision_index: int
    actor_seat: int
    decision_key: str
    split: str
    actor_observation_sha256: str
    privileged_target_sha256: str
    tensors: HistoryOwnershipTensorsV1
    count_labels: np.ndarray
    active_mask: np.ndarray
    privileged_targets_consumed: bool = True
    runtime_artifact: bool = False
    schema: str = TRAINING_EXAMPLE_SCHEMA


@dataclass(frozen=True)
class BeliefTrainingBatchV1:
    decision_keys: tuple[str, ...]
    split: str
    events: torch.Tensor
    event_lengths: torch.Tensor
    global_features: torch.Tensor
    card_features: torch.Tensor
    receiver_features: torch.Tensor
    receiver_mask: torch.Tensor
    unseen_mask: torch.Tensor
    count_minimums: torch.Tensor
    count_maximums: torch.Tensor
    count_labels: torch.Tensor
    active_mask: torch.Tensor
    privileged_targets_consumed: bool = True
    runtime_artifact: bool = False
    schema: str = TRAINING_BATCH_SCHEMA


def _labels(
        actor: ActorObservationV1, target: BeliefTargetsV1,
        tensors: HistoryOwnershipTensorsV1) -> tuple[np.ndarray, np.ndarray]:
    counts = target_count_population(actor, target)
    labels = np.full(
        (len(CARD_CODES), MAX_RECEIVERS), -1, dtype=np.int64)
    active = tensors.unseen_mask[:, None] & tensors.receiver_mask[None, :]
    receivers = ("seat-relative-1", "seat-relative-2", "seat-relative-3",
                 "hidden-kitty")
    for card_index, card in enumerate(CARD_CODES):
        for receiver_index, receiver in enumerate(receivers):
            if active[card_index, receiver_index]:
                labels[card_index, receiver_index] = counts[(card, receiver)]
    if np.any(labels[active] < tensors.count_minimums[active]) \
            or np.any(labels[active] > tensors.count_maximums[active]) \
            or np.any(labels[~active] != -1):
        raise BeliefTrainingError("training labels violate actor hard bounds")
    return labels, np.ascontiguousarray(active)


def _build_training_example(
        pair: CorpusPairV1, *,
        behavior_policy_ids: tuple[str, ...]) -> BeliefTrainingExampleV1:
    actor, target, metadata = reopen_score_pair(pair)
    round_seed = metadata["round_seed"]
    decision_index = metadata["decision_index"]
    actor_seat = metadata["actor_seat"]
    split = metadata["split"]
    key = metadata["decision_key"]
    tensors = build_history_ownership_tensors(
        actor, behavior_policy_ids=behavior_policy_ids)
    labels, active = _labels(actor, target, tensors)
    return BeliefTrainingExampleV1(
        round_seed=round_seed, decision_index=decision_index,
        actor_seat=actor_seat, decision_key=key, split=split,
        actor_observation_sha256=actor.sha256(),
        privileged_target_sha256=target.sha256(), tensors=tensors,
        count_labels=labels, active_mask=active)


def build_training_example(
        pair: CorpusPairV1, *,
        behavior_policy_ids: tuple[str, ...]) -> BeliefTrainingExampleV1:
    """Build and rederive one example from an exact hash-bound corpus pair."""
    result = _build_training_example(
        pair, behavior_policy_ids=behavior_policy_ids)
    validate_training_example(pair, result)
    return result


def validate_training_example(
        pair: CorpusPairV1,
        example: BeliefTrainingExampleV1) -> None:
    if type(example) is not BeliefTrainingExampleV1 \
            or example.schema != TRAINING_EXAMPLE_SCHEMA \
            or example.privileged_targets_consumed is not True \
            or example.runtime_artifact is not False \
            or example.split not in SPLITS \
            or type(example.count_labels) is not np.ndarray \
            or example.count_labels.dtype != np.int64 \
            or type(example.active_mask) is not np.ndarray \
            or example.active_mask.dtype != np.bool_:
        raise BeliefTrainingError("training example schema/authority drift")
    actor, _, _ = reopen_score_pair(pair)
    validate_history_ownership_tensors(actor, example.tensors)
    expected = _build_training_example(
        pair,
        behavior_policy_ids=example.tensors.behavior_policy_ids)
    scalar_fields = (
        "round_seed", "decision_index", "actor_seat", "decision_key",
        "split", "actor_observation_sha256", "privileged_target_sha256",
        "privileged_targets_consumed", "runtime_artifact", "schema",
    )
    if any(getattr(example, field) != getattr(expected, field)
           for field in scalar_fields) \
            or not np.array_equal(example.count_labels,
                                  expected.count_labels) \
            or not np.array_equal(example.active_mask,
                                  expected.active_mask):
        raise BeliefTrainingError("training example derivation drift")


def collate_training_examples(
        examples: tuple[BeliefTrainingExampleV1, ...]) \
        -> BeliefTrainingBatchV1:
    """Collate one preordered, duplicate-free, single-split batch."""
    if type(examples) is not tuple or not examples \
            or any(type(example) is not BeliefTrainingExampleV1
                   for example in examples):
        raise BeliefTrainingError("training batch population is malformed")
    for example in examples:
        tensors = example.tensors
        if example.schema != TRAINING_EXAMPLE_SCHEMA \
                or example.privileged_targets_consumed is not True \
                or example.runtime_artifact is not False \
                or example.decision_key != decision_key(
                    example.round_seed, example.decision_index,
                    example.actor_seat) \
                or example.split != split_for_round_seed(example.round_seed) \
                or example.actor_observation_sha256 \
                != tensors.actor_observation_sha256 \
                or type(example.privileged_target_sha256) is not str \
                or len(example.privileged_target_sha256) != 64 \
                or any(char not in "0123456789abcdef"
                       for char in example.privileged_target_sha256) \
                or type(example.count_labels) is not np.ndarray \
                or example.count_labels.dtype != np.int64 \
                or example.count_labels.shape \
                != (len(CARD_CODES), MAX_RECEIVERS) \
                or type(example.active_mask) is not np.ndarray \
                or example.active_mask.dtype != np.bool_ \
                or example.active_mask.shape \
                != (len(CARD_CODES), MAX_RECEIVERS):
            raise BeliefTrainingError("training batch example binding drift")
        expected_active = (tensors.unseen_mask[:, None]
                           & tensors.receiver_mask[None, :])
        if not np.array_equal(example.active_mask, expected_active) \
                or np.any(example.count_labels[~expected_active] != -1) \
                or np.any(example.count_labels[expected_active]
                          < tensors.count_minimums[expected_active]) \
                or np.any(example.count_labels[expected_active]
                          > tensors.count_maximums[expected_active]):
            raise BeliefTrainingError("training batch label/bound drift")
    keys = tuple(example.decision_key for example in examples)
    if len(set(keys)) != len(keys):
        raise BeliefTrainingError("training batch has duplicate decisions")
    splits = {example.split for example in examples}
    if len(splits) != 1:
        raise BeliefTrainingError("training batch crosses data splits")
    if any(example.privileged_targets_consumed is not True
           or example.runtime_artifact is not False for example in examples):
        raise BeliefTrainingError("training batch authority drift")
    max_events = max(len(example.tensors.events) for example in examples)
    events = np.zeros(
        (len(examples), max_events,
         examples[0].tensors.events.shape[1]), dtype=np.float32)
    lengths = []
    for index, example in enumerate(examples):
        length = len(example.tensors.events)
        events[index, :length] = example.tensors.events
        lengths.append(length)
    return BeliefTrainingBatchV1(
        decision_keys=keys, split=next(iter(splits)),
        events=torch.from_numpy(events),
        event_lengths=torch.tensor(lengths, dtype=torch.long),
        global_features=torch.from_numpy(np.stack([
            example.tensors.global_features for example in examples])),
        card_features=torch.from_numpy(np.stack([
            example.tensors.card_features for example in examples])),
        receiver_features=torch.from_numpy(np.stack([
            example.tensors.receiver_features for example in examples])),
        receiver_mask=torch.from_numpy(np.stack([
            example.tensors.receiver_mask for example in examples])),
        unseen_mask=torch.from_numpy(np.stack([
            example.tensors.unseen_mask for example in examples])),
        count_minimums=torch.from_numpy(np.stack([
            example.tensors.count_minimums for example in examples])),
        count_maximums=torch.from_numpy(np.stack([
            example.tensors.count_maximums for example in examples])),
        count_labels=torch.from_numpy(np.stack([
            example.count_labels for example in examples])),
        active_mask=torch.from_numpy(np.stack([
            example.active_mask for example in examples])),
    )


def training_batch_loss(
        model: HistoryOwnershipModelV1,
        batch: BeliefTrainingBatchV1) -> torch.Tensor:
    """Compute the sole supervised ownership loss for one frozen batch."""
    if type(model) is not HistoryOwnershipModelV1 \
            or type(batch) is not BeliefTrainingBatchV1 \
            or batch.schema != TRAINING_BATCH_SCHEMA \
            or batch.privileged_targets_consumed is not True \
            or batch.runtime_artifact is not False:
        raise BeliefTrainingError("training batch model/schema drift")
    logits = model(
        batch.events, batch.event_lengths, batch.global_features,
        batch.card_features, batch.receiver_features, batch.receiver_mask,
        batch.unseen_mask, batch.count_minimums, batch.count_maximums)
    return masked_count_cross_entropy(
        logits, batch.count_labels, batch.active_mask,
        batch.count_minimums, batch.count_maximums)
