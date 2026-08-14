"""Deterministic eight-member BELIEF-V1 ownership ensemble.

The B2 design reports every fixed initialization separately and uses one
equal-weight candidate for the primary comparison.  This module combines only
already validated public-input ownership predictions.  It never accepts a
model object, checkpoint, target, score, sampler, corpus, or runtime policy.

The integer member probabilities are summed as equal positive count weights
and passed through the same exact constrained projection used by each member.
That final projection is necessary because independent rounding can otherwise
make a literal component-wise mean miss a card or receiver margin by a few
parts per billion.
"""

from __future__ import annotations

import hashlib
from typing import Any

from .belief_contract import ActorObservationV1, canonical_json_bytes
from .belief_ownership import BeliefOwnershipV1, validate_ownership
from .belief_projection import RawCountWeightV1, project_count_weights


COHORT_SCHEMA = "belief-v1-history-ownership-cohort-8-v1"
COHORT_SEEDS = (
    495023836, 847673502, 1041799603, 588875658,
    442958256, 517235703, 1114290105, 823748771,
)


class BeliefCohortError(ValueError):
    """The fixed eight-member ownership ensemble contract drifted."""


def _is_sha256(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def ensemble_identity(member_sha256s: tuple[str, ...]) -> str:
    """Return the canonical identity of the ordered fixed cohort."""
    if type(member_sha256s) is not tuple \
            or len(member_sha256s) != len(COHORT_SEEDS) \
            or len(set(member_sha256s)) != len(member_sha256s) \
            or any(not _is_sha256(value) for value in member_sha256s):
        raise BeliefCohortError("cohort member identity population drift")
    return hashlib.sha256(canonical_json_bytes({
        "schema": COHORT_SCHEMA,
        "initialization_seeds": list(COHORT_SEEDS),
        "ordered_member_sha256s": list(member_sha256s),
        "weight_numerator_by_member": [1] * len(COHORT_SEEDS),
        "weight_denominator": len(COHORT_SEEDS),
        "final_exact_projection": True,
    })).hexdigest()


def ensemble_ownership(
        actor: ActorObservationV1,
        members: tuple[BeliefOwnershipV1, ...]) -> BeliefOwnershipV1:
    """Equal-weight eight predictions and restore exact PPB conservation."""
    if type(actor) is not ActorObservationV1 \
            or type(members) is not tuple \
            or len(members) != len(COHORT_SEEDS) \
            or any(type(member) is not BeliefOwnershipV1 for member in members):
        raise BeliefCohortError("cohort prediction population drift")
    try:
        for member in members:
            validate_ownership(actor, member)
    except ValueError as exc:
        raise BeliefCohortError("cohort member ownership refused") from exc
    first = members[0]
    member_sha256s = tuple(member.model_sha256 for member in members)
    identity = ensemble_identity(member_sha256s)
    if any(member.behavior_policy_ids != first.behavior_policy_ids
           for member in members):
        raise BeliefCohortError("cohort behavior-policy identity drift")
    keys = tuple((row.card, row.receiver) for row in first.probabilities)
    if any(tuple((row.card, row.receiver) for row in member.probabilities)
           != keys for member in members):
        raise BeliefCohortError("cohort ownership population/order drift")
    raw = []
    for index, (card, receiver) in enumerate(keys):
        raw.append(RawCountWeightV1(
            card=card,
            receiver=receiver,
            count_weights=tuple(sum((
                member.probabilities[index].count_0_ppb,
                member.probabilities[index].count_1_ppb,
                member.probabilities[index].count_2_ppb,
            )[count] for member in members) for count in range(3)),
        ))
    return project_count_weights(
        actor,
        behavior_policy_ids=first.behavior_policy_ids,
        model_schema=COHORT_SCHEMA,
        model_sha256=identity,
        raw_weights=tuple(raw),
    )
