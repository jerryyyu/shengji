"""Target-blind transcript-replayed REF-C driver for BELIEF-V1 V2.

This module intentionally imports no full-capture type, corpus-pair type,
target constructor, or target artifact reopener.  It accepts one separately
sealed actor-only round, reconstructs its states from public attempted plays,
and draws the unchanged V1 sound-constraint reference distribution.
"""

from __future__ import annotations

from ..ai.registry import make_bot
from .belief_b2_protocol import (
    B2_REFERENCE_REPLICATES,
    reference_sampler_seed,
)
from .belief_capture import (
    CHAMPION_POLICY,
    CapturedActorRoundV1,
)
from .belief_corpus import reopen_actor_row, split_for_round_seed
from .belief_refc_capture import (
    BeliefRefCCaptureError,
    ReferenceCapturedRoundV1,
    capture_ref_c_worlds,
    validate_reference_captured_round,
)
from .belief_refc_replay import replay_actor_round
from .belief_v2_protocol import (
    V2RoundCoordinate,
    v2_policy_seeds,
    v2_round_coordinate,
)


class BeliefV2ReferenceError(ValueError):
    """A V2 target-blind reference identity or population drifted."""


def _validate_coordinate(coordinate: V2RoundCoordinate) -> None:
    if type(coordinate) is not V2RoundCoordinate \
            or coordinate != v2_round_coordinate(
                coordinate.trump_rank, coordinate.rank_ordinal):
        raise BeliefV2ReferenceError(
            "V2 reference coordinate derivation drift")


def capture_v2_ref_c_from_replay(
        coordinate: V2RoundCoordinate, sealed: CapturedActorRoundV1, *,
        replicate: str) -> ReferenceCapturedRoundV1:
    """Draw V2 REF-C worlds while replaying sealed plays, never searching."""
    _validate_coordinate(coordinate)
    split = split_for_round_seed(coordinate.round_seed)
    if replicate not in B2_REFERENCE_REPLICATES \
            or (split == "calibration"
                and not replicate.startswith("calibration-replicate-")) \
            or (split == "test" and replicate != "test-primary") \
            or split == "train":
        raise BeliefV2ReferenceError("V2 REF-C replicate/split drift")
    policy_seeds = v2_policy_seeds(coordinate)
    if type(sealed) is not CapturedActorRoundV1 \
            or sealed.round_seed != coordinate.round_seed \
            or sealed.policy_name != CHAMPION_POLICY \
            or sealed.policy_seeds != policy_seeds:
        raise BeliefV2ReferenceError("V2 REF-C sealed identity drift")
    batches = []

    def observe(rnd, seat, transcript, actor_row):
        try:
            actor, metadata = reopen_actor_row(actor_row)
            batch = capture_ref_c_worlds(
                rnd, seat, transcript,
                sampler_seed=reference_sampler_seed(
                    metadata["decision_key"], replicate))
        except (ValueError, BeliefRefCCaptureError) as exc:
            raise BeliefV2ReferenceError(
                "V2 REF-C replay decision refused") from exc
        if batch.actor.canonical_bytes() != actor.canonical_bytes():
            raise BeliefV2ReferenceError(
                "V2 REF-C replay actor reconstruction drift")
        batches.append(batch)

    policies = [make_bot(CHAMPION_POLICY, seed=seed)
                for seed in policy_seeds]
    replayed = replay_actor_round(
        round_seed=coordinate.round_seed,
        policy_name=CHAMPION_POLICY,
        policy_seeds=policy_seeds,
        policies=policies,
        sealed=sealed,
        decision_observer=observe,
        trump_rank=coordinate.trump_rank)
    result = ReferenceCapturedRoundV1(
        captured=replayed, replicate=replicate, batches=tuple(batches))
    try:
        validate_reference_captured_round(result)
    except BeliefRefCCaptureError as exc:
        raise BeliefV2ReferenceError(
            "V2 REF-C round validation refused") from exc
    if result.captured != sealed \
            or len(result.batches) != len(sealed.actor_rows):
        raise BeliefV2ReferenceError("V2 REF-C replay population drift")
    return result
