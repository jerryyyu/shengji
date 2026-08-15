"""Target-blind historical-human REF-C replay for BELIEF-V1 V2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .belief_b2_protocol import (
    B2_REFERENCE_REPLICATES,
    reference_sampler_seed,
)
from .belief_contract import build_actor_observation
from .belief_refc_capture import (
    ReferenceWorldBatchV1,
    capture_ref_c_worlds_from_bound_actor,
    validate_reference_world_batch,
)
from .belief_v2_human_corpus import (
    V2HumanReplaySummaryV1,
    human_decision_key,
    replay_human_source_decisions,
)
from .belief_v2_scoring import v2_scoring_actor


class BeliefV2HumanReferenceError(ValueError):
    """A human public replay or target-blind reference batch drifted."""


def _is_sha256(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


@dataclass(frozen=True)
class V2HumanReferenceDecisionV1:
    decision_key: str
    round_digest: str
    trump_rank: str
    batch: ReferenceWorldBatchV1


@dataclass(frozen=True)
class V2HumanReferenceGroupV1:
    replay: V2HumanReplaySummaryV1
    split: str
    replicate: str
    decisions: tuple[V2HumanReferenceDecisionV1, ...]


def validate_human_reference_group(
        value: V2HumanReferenceGroupV1) -> None:
    if type(value) is not V2HumanReferenceGroupV1 \
            or type(value.replay) is not V2HumanReplaySummaryV1 \
            or value.split not in {"calibration", "test"} \
            or value.replicate not in B2_REFERENCE_REPLICATES \
            or (value.split == "calibration"
                and value.replicate not in B2_REFERENCE_REPLICATES[:2]) \
            or (value.split == "test"
                and value.replicate != B2_REFERENCE_REPLICATES[2]) \
            or type(value.decisions) is not tuple \
            or len(value.decisions) != value.replay.human_decision_count:
        raise BeliefV2HumanReferenceError(
            "V2 human reference group population drift")
    keys = []
    for row in value.decisions:
        if type(row) is not V2HumanReferenceDecisionV1 \
                or not _is_sha256(row.decision_key) \
                or not _is_sha256(row.round_digest) \
                or type(row.trump_rank) is not str \
                or type(row.batch) is not ReferenceWorldBatchV1:
            raise BeliefV2HumanReferenceError(
                "V2 human reference decision identity drift")
        try:
            validate_reference_world_batch(row.batch)
        except ValueError as exc:
            raise BeliefV2HumanReferenceError(
                "V2 human reference batch refused") from exc
        keys.append(row.decision_key)
    if len(keys) != len(set(keys)):
        raise BeliefV2HumanReferenceError(
            "V2 human reference decision duplicate")


def capture_human_ref_c_source_group(
        source_raw: bytes, *, source_sha256: str,
        split: str, replicate: str) -> V2HumanReferenceGroupV1:
    """Replay one source group and draw REF-C without target construction."""
    if split not in {"calibration", "test"} \
            or replicate not in B2_REFERENCE_REPLICATES \
            or (split == "calibration"
                and replicate not in B2_REFERENCE_REPLICATES[:2]) \
            or (split == "test"
                and replicate != B2_REFERENCE_REPLICATES[2]):
        raise BeliefV2HumanReferenceError(
            "V2 human reference split/replicate drift")
    decisions = []

    def observe(rnd, seat, group_digest, round_digest, decision_index):
        source_actor = build_actor_observation(rnd, seat)
        if source_actor.declaration_history_complete is not False \
                or source_actor.attempted_play_history_complete is not False:
            raise BeliefV2HumanReferenceError(
                "V2 human reference source channel drift")
        actor = v2_scoring_actor(source_actor)
        key = human_decision_key(
            group_digest, round_digest, decision_index, seat)
        try:
            batch = capture_ref_c_worlds_from_bound_actor(
                rnd, seat, actor,
                sampler_seed=reference_sampler_seed(key, replicate))
        except ValueError as exc:
            raise BeliefV2HumanReferenceError(
                "V2 human reference draw refused") from exc
        decisions.append(V2HumanReferenceDecisionV1(
            decision_key=key, round_digest=round_digest,
            trump_rank=rnd.trump_rank, batch=batch))

    try:
        replay = replay_human_source_decisions(
            source_raw, source_sha256=source_sha256,
            decision_observer=observe)
    except ValueError as exc:
        if isinstance(exc, BeliefV2HumanReferenceError):
            raise
        raise BeliefV2HumanReferenceError(
            "V2 human reference replay refused") from exc
    result = V2HumanReferenceGroupV1(
        replay=replay, split=split, replicate=replicate,
        decisions=tuple(decisions))
    validate_human_reference_group(result)
    return result
