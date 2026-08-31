"""Pure world-weight mechanics for the opened-DEV R4 policy diagnostic.

R4 predicts receiver-count marginals, not a sampleable joint posterior.  This
module therefore implements a deliberately bounded diagnostic bridge: score
already-sampled legal production worlds by the mean per-cell log ratio between
an R4 cohort and independently sampled production-proposal marginals, then
temper both the
primary and label-control arms by one common, outcome-blind ESS rule.

It does not sample a world, run a policy, inspect a target or true hand, open a
checkpoint, or authorize gameplay.  The resulting weights are a mechanism
probe, not a claim that marginal products form the final BELIEF sampler.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any

from .belief_contract import ActorObservationV1
from .belief_ownership import (
    PROBABILITY_SCALE,
    BeliefOwnershipV1,
    validate_ownership,
)
from .belief_reference import (
    REF_C_WORLD_COUNT,
    SampledOwnershipWorldV1,
    validate_sampled_world,
)
from .belief_v2_scoring import v2_scoring_actor


PPB = PROBABILITY_SCALE
NANONATS_PER_NAT = 1_000_000_000
REFERENCE_JEFFREYS_HALF_COUNT = 0.5
MIN_CANDIDATE_PROBABILITY = 1.0e-12
MIN_ESS_FRACTION_PPB = 500_000_000
MAX_WEIGHT_MULTIPLE = 4
TEMPERATURE_ALPHA_PPBS = (
    1_000_000_000,
    500_000_000,
    250_000_000,
    125_000_000,
    62_500_000,
    31_250_000,
    15_625_000,
    7_812_500,
    3_906_250,
    0,
)


class BeliefPolicyWeightingError(ValueError):
    """A diagnostic posterior, world population, or weight vector drifted."""


def _is_int(value: Any) -> bool:
    return type(value) is int


@dataclass(frozen=True)
class TemperedWorldWeightsV1:
    alpha_ppb: int
    log_ratio_nanonats: tuple[int, ...]
    normalized_weight_ppb: tuple[int, ...]
    ess_ppb: int
    max_weight_ppb: int
    untempered_ess_ppb: int
    untempered_max_weight_ppb: int

    @property
    def world_count(self) -> int:
        return len(self.normalized_weight_ppb)


def validate_tempered_world_weights(value: TemperedWorldWeightsV1) -> None:
    if type(value) is not TemperedWorldWeightsV1 \
            or value.alpha_ppb not in TEMPERATURE_ALPHA_PPBS \
            or type(value.log_ratio_nanonats) is not tuple \
            or not value.log_ratio_nanonats \
            or any(not _is_int(item) for item in value.log_ratio_nanonats) \
            or type(value.normalized_weight_ppb) is not tuple \
            or len(value.normalized_weight_ppb) \
            != len(value.log_ratio_nanonats) \
            or any(not _is_int(item) or item <= 0
                   for item in value.normalized_weight_ppb) \
            or sum(value.normalized_weight_ppb) != PPB \
            or not all(_is_int(item) and item > 0 for item in (
                value.ess_ppb,
                value.max_weight_ppb,
                value.untempered_ess_ppb,
                value.untempered_max_weight_ppb,
            )) \
            or value.max_weight_ppb != max(value.normalized_weight_ppb):
        raise BeliefPolicyWeightingError(
            "tempered world-weight population drift")


def adapt_proposal_ownership_to_v2(
        source_actor: ActorObservationV1,
        proposal: BeliefOwnershipV1, *,
        behavior_policy_ids: tuple[str, ...]) -> BeliefOwnershipV1:
    """Rebind source-actor proposal marginals to the reviewed V2 surface."""
    if type(source_actor) is not ActorObservationV1 \
            or type(proposal) is not BeliefOwnershipV1 \
            or proposal.actor_observation_sha256 != source_actor.sha256() \
            or type(behavior_policy_ids) is not tuple \
            or not behavior_policy_ids \
            or any(type(policy) is not str or not policy
                   for policy in behavior_policy_ids):
        raise BeliefPolicyWeightingError(
            "proposal V2 adaptation input drift")
    try:
        validate_ownership(source_actor, proposal)
        scoring_actor = v2_scoring_actor(source_actor)
        result = replace(
            proposal,
            actor_observation_sha256=scoring_actor.sha256(),
            behavior_policy_ids=behavior_policy_ids,
        )
        validate_ownership(scoring_actor, result)
    except ValueError as exc:
        raise BeliefPolicyWeightingError(
            "proposal V2 adaptation refused") from exc
    return result


def _probability_rows(
        belief: BeliefOwnershipV1) -> dict[tuple[str, str], tuple[int, int, int]]:
    rows: dict[tuple[str, str], tuple[int, int, int]] = {}
    for row in belief.probabilities:
        key = (row.card, row.receiver)
        if key in rows:
            raise BeliefPolicyWeightingError(
                "belief probability row is duplicated")
        rows[key] = (
            row.count_0_ppb,
            row.count_1_ppb,
            row.count_2_ppb,
        )
    return rows


def _reference_probability(probability_ppb: int) -> float:
    # Proposal probabilities are exact multiples of 1/256. Reconstruct the
    # empirical count and apply the same finite-reference Jeffreys correction
    # used by the R4 log-score path; this prevents a zero empirical cell from
    # creating an infinite importance ratio.
    count = (probability_ppb * REF_C_WORLD_COUNT + PPB // 2) // PPB
    reconstructed = count * PPB // REF_C_WORLD_COUNT
    if not 0 <= count <= REF_C_WORLD_COUNT \
            or abs(reconstructed - probability_ppb) > 1:
        raise BeliefPolicyWeightingError(
            "reference probability is not a 256-world empirical count")
    return ((count + REFERENCE_JEFFREYS_HALF_COUNT)
            / (REF_C_WORLD_COUNT + 3 * REFERENCE_JEFFREYS_HALF_COUNT))


def world_log_ratio_nanonats(
        source_actor: ActorObservationV1,
        candidate: BeliefOwnershipV1,
        reference: BeliefOwnershipV1,
        worlds: tuple[SampledOwnershipWorldV1, ...]) -> tuple[int, ...]:
    """Score legal worlds by a bounded marginal-product likelihood ratio."""
    if type(source_actor) is not ActorObservationV1 \
            or type(candidate) is not BeliefOwnershipV1 \
            or type(reference) is not BeliefOwnershipV1 \
            or type(worlds) is not tuple or not worlds:
        raise BeliefPolicyWeightingError(
            "world log-ratio input population drift")
    scoring_actor = v2_scoring_actor(source_actor)
    try:
        validate_ownership(scoring_actor, candidate)
        validate_ownership(scoring_actor, reference)
        for world in worlds:
            validate_sampled_world(source_actor, world)
    except ValueError as exc:
        raise BeliefPolicyWeightingError(
            "world log-ratio mechanics refused") from exc
    candidate_rows = _probability_rows(candidate)
    reference_rows = _probability_rows(reference)
    if set(candidate_rows) != set(reference_rows):
        raise BeliefPolicyWeightingError(
            "candidate/reference probability population drift")

    result = []
    for world in worlds:
        receiver_counts = {
            row.receiver: dict(row.cards) for row in world.receivers
        }
        if set(receiver_counts) != {
                receiver for receiver, _ in candidate.receiver_sizes}:
            raise BeliefPolicyWeightingError(
                "world receiver population drift")
        log_ratio = 0.0
        cell_count = 0
        for key in sorted(candidate_rows):
            card, receiver = key
            count = receiver_counts[receiver].get(card, 0)
            candidate_probability = max(
                candidate_rows[key][count] / PPB,
                MIN_CANDIDATE_PROBABILITY,
            )
            reference_probability = _reference_probability(
                reference_rows[key][count])
            log_ratio += math.log(
                candidate_probability / reference_probability)
            cell_count += 1
        if cell_count == 0 or not math.isfinite(log_ratio):
            raise BeliefPolicyWeightingError(
                "world log-ratio is empty or nonfinite")
        # A mean rather than a sum makes the diagnostic temperature stable as
        # the number of unseen cells shrinks through the round.  It does not
        # assert independence among the marginal cells.
        result.append(round(
            (log_ratio / cell_count) * NANONATS_PER_NAT))
    return tuple(result)


def _quantize_normalized(values: tuple[float, ...]) -> tuple[int, ...]:
    if not values or any(not math.isfinite(value) or value < 0
                         for value in values) or sum(values) <= 0:
        raise BeliefPolicyWeightingError(
            "world-weight normalization input drift")
    count = len(values)
    if count > PPB:
        raise BeliefPolicyWeightingError("world-weight population exceeds ppb")
    total = math.fsum(values)
    remaining = PPB - count
    exact = [value / total * remaining for value in values]
    floors = [math.floor(value) for value in exact]
    weights = [1 + value for value in floors]
    residual = PPB - sum(weights)
    order = sorted(
        range(count), key=lambda index: (-(exact[index] - floors[index]), index))
    for index in order[:residual]:
        weights[index] += 1
    result = tuple(weights)
    if sum(result) != PPB or any(value <= 0 for value in result):
        raise BeliefPolicyWeightingError(
            "world-weight quantization failed conservation")
    return result


def uniform_world_weights(world_count: int) -> tuple[int, ...]:
    if type(world_count) is not int or not 1 <= world_count <= PPB:
        raise BeliefPolicyWeightingError(
            "uniform world-weight count drift")
    return _quantize_normalized(tuple(1.0 for _ in range(world_count)))


def _weights_at_alpha(
        scores: tuple[int, ...], alpha_ppb: int) -> tuple[int, ...]:
    if type(scores) is not tuple or not scores \
            or any(not _is_int(score) for score in scores) \
            or alpha_ppb not in TEMPERATURE_ALPHA_PPBS:
        raise BeliefPolicyWeightingError("world-weight temperature drift")
    if alpha_ppb == 0:
        return uniform_world_weights(len(scores))
    maximum = max(scores)
    scale = alpha_ppb / PPB / NANONATS_PER_NAT
    return _quantize_normalized(tuple(
        math.exp((score - maximum) * scale) for score in scores))


def _ess_ppb(weights: tuple[int, ...]) -> int:
    denominator = sum(weight * weight for weight in weights)
    return (PPB ** 3 + denominator // 2) // denominator


def _passes_concentration_guard(weights: tuple[int, ...]) -> bool:
    count = len(weights)
    return (
        _ess_ppb(weights) >= count * MIN_ESS_FRACTION_PPB
        and max(weights) * count <= MAX_WEIGHT_MULTIPLE * PPB
    )


def common_tempered_world_weights(
        primary_scores: tuple[int, ...],
        control_scores: tuple[int, ...]) \
        -> tuple[TemperedWorldWeightsV1, TemperedWorldWeightsV1]:
    """Apply the strongest one-axis temperature safe for both learned arms."""
    if type(primary_scores) is not tuple \
            or type(control_scores) is not tuple \
            or not primary_scores \
            or len(primary_scores) != len(control_scores) \
            or any(not _is_int(score)
                   for score in (*primary_scores, *control_scores)):
        raise BeliefPolicyWeightingError(
            "common temperature score population drift")
    primary_raw = _weights_at_alpha(primary_scores, PPB)
    control_raw = _weights_at_alpha(control_scores, PPB)
    selected = None
    primary_weights = control_weights = None
    for alpha in TEMPERATURE_ALPHA_PPBS:
        trial_primary = _weights_at_alpha(primary_scores, alpha)
        trial_control = _weights_at_alpha(control_scores, alpha)
        if (_passes_concentration_guard(trial_primary)
                and _passes_concentration_guard(trial_control)):
            selected = alpha
            primary_weights = trial_primary
            control_weights = trial_control
            break
    if selected is None or primary_weights is None or control_weights is None:
        raise BeliefPolicyWeightingError(
            "common temperature grid has no safe arm")

    def build(scores: tuple[int, ...], weights: tuple[int, ...],
              raw: tuple[int, ...]) -> TemperedWorldWeightsV1:
        value = TemperedWorldWeightsV1(
            alpha_ppb=selected,
            log_ratio_nanonats=scores,
            normalized_weight_ppb=weights,
            ess_ppb=_ess_ppb(weights),
            max_weight_ppb=max(weights),
            untempered_ess_ppb=_ess_ppb(raw),
            untempered_max_weight_ppb=max(raw),
        )
        validate_tempered_world_weights(value)
        return value

    return (
        build(primary_scores, primary_weights, primary_raw),
        build(control_scores, control_weights, control_raw),
    )


def weighted_mean_and_se(
        values: tuple[float, ...],
        normalized_weight_ppb: tuple[int, ...]) -> tuple[float, float]:
    """Return the weighted mean and paired-fold standard error.

    The sandwich variance reduces exactly to the ordinary sample-mean variance
    for equal weights.  A caller compares action deltas on common worlds, not
    two independently weighted marginal means.
    """
    if type(values) is not tuple or not values \
            or type(normalized_weight_ppb) is not tuple \
            or len(values) != len(normalized_weight_ppb) \
            or any(type(value) not in (int, float) or not math.isfinite(value)
                   for value in values) \
            or any(not _is_int(weight) or weight <= 0
                   for weight in normalized_weight_ppb) \
            or sum(normalized_weight_ppb) != PPB:
        raise BeliefPolicyWeightingError(
            "weighted moment population drift")
    weights = tuple(weight / PPB for weight in normalized_weight_ppb)
    mean = math.fsum(weight * value
                     for weight, value in zip(weights, values, strict=True))
    squared_weight = math.fsum(weight * weight for weight in weights)
    if len(values) == 1 or squared_weight >= 1.0:
        return mean, float("inf")
    variance_of_mean = math.fsum(
        weight * weight * (value - mean) ** 2
        for weight, value in zip(weights, values, strict=True)
    ) / (1.0 - squared_weight)
    return mean, math.sqrt(max(0.0, variance_of_mean))
