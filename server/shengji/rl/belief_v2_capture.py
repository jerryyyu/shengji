"""Rank-bound V2 capture and REF-C transcript replay adapters.

The reviewed V1 functions default to the production game's initial rank-2
round.  V2 binds their explicit research-rank option to an exact
``V2RoundCoordinate`` so callers cannot select rank or deal independently.
No writer, sampler, training loop, CLI, or execution authority lives here.
"""

from __future__ import annotations

from typing import Any

from ..ai.registry import make_bot
from .belief_capture import (
    CHAMPION_POLICY,
    CapturedActorRoundV1,
    CapturedBeliefRoundV1,
    _capture_with_policies,
)
from .belief_refc_replay import replay_actor_round
from .belief_v2_protocol import (
    V2RoundCoordinate,
    v2_policy_seeds,
    v2_round_coordinate,
)


class BeliefV2CaptureError(ValueError):
    """A V2 capture/replay identity or output type drifted."""


def _validate_coordinate(coordinate: V2RoundCoordinate) -> None:
    if type(coordinate) is not V2RoundCoordinate \
            or coordinate != v2_round_coordinate(
                coordinate.trump_rank, coordinate.rank_ordinal):
        raise BeliefV2CaptureError("V2 capture coordinate derivation drift")


def capture_v2_champion_round(
        coordinate: V2RoundCoordinate, *,
        decision_observer: Any = None) -> CapturedBeliefRoundV1:
    _validate_coordinate(coordinate)
    policy_seeds = v2_policy_seeds(coordinate)
    policies = [make_bot(CHAMPION_POLICY, seed=seed)
                for seed in policy_seeds]
    result = _capture_with_policies(
        coordinate.round_seed, CHAMPION_POLICY, policy_seeds, policies,
        decision_observer=decision_observer,
        trump_rank=coordinate.trump_rank)
    if type(result) is not CapturedBeliefRoundV1:
        raise BeliefV2CaptureError("V2 champion capture type drift")
    return result


def capture_v2_champion_actor_round(
        coordinate: V2RoundCoordinate, *,
        decision_observer: Any = None) -> CapturedActorRoundV1:
    _validate_coordinate(coordinate)
    policy_seeds = v2_policy_seeds(coordinate)
    policies = [make_bot(CHAMPION_POLICY, seed=seed)
                for seed in policy_seeds]
    result = _capture_with_policies(
        coordinate.round_seed, CHAMPION_POLICY, policy_seeds, policies,
        decision_observer=decision_observer, actor_only=True,
        trump_rank=coordinate.trump_rank)
    if type(result) is not CapturedActorRoundV1:
        raise BeliefV2CaptureError("V2 actor-only capture type drift")
    return result


def replay_v2_champion_actor_round(
        coordinate: V2RoundCoordinate, sealed: CapturedActorRoundV1, *,
        decision_observer: Any = None) -> CapturedActorRoundV1:
    _validate_coordinate(coordinate)
    policy_seeds = v2_policy_seeds(coordinate)
    policies = [make_bot(CHAMPION_POLICY, seed=seed)
                for seed in policy_seeds]
    result = replay_actor_round(
        round_seed=coordinate.round_seed,
        policy_name=CHAMPION_POLICY,
        policy_seeds=policy_seeds,
        policies=policies,
        sealed=sealed,
        decision_observer=decision_observer,
        trump_rank=coordinate.trump_rank)
    if type(result) is not CapturedActorRoundV1:
        raise BeliefV2CaptureError("V2 actor-only replay type drift")
    return result
