"""Target-blind common public-history surface for BELIEF-V1 V2.

Historical human logs do not contain attempted-card sets for plays, while the
synthetic capture does.  V2 must not copy engine-accepted cards into an
"attempted" field or let channel availability become a policy/source feature.
This adapter therefore derives the same conservative surface for every row:

* only the final winning declaration is retained;
* engine-accepted play cards are retained;
* attempted-card vectors and failed-throw indicators are masked; and
* original completeness flags remain receipt metadata, never model tensors.

The adapter consumes only an already-built ``ActorObservationV1`` and named
public policy identities.  It accepts no target, hidden world, file, sampler,
model, RNG, or gameplay action surface.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from .belief_contract import (
    ACTOR_OBSERVATION_SCHEMA,
    ActorObservationV1,
    PlayView,
    TrickView,
    canonical_json_bytes,
)
from .belief_input import _build_history_ownership_input
from .belief_tensor import HistoryOwnershipTensorsV1, _tensorize


COMMON_SURFACE_SCHEMA = "belief-v1-v2-common-history-surface-v1"
DECLARATION_SURFACE = "final-winning-declaration-only-v1"
PLAY_SURFACE = "engine-accepted-cards-only-v1"
ARRAY_FIELDS = (
    "events",
    "global_features",
    "card_features",
    "receiver_features",
    "receiver_mask",
    "unseen_mask",
    "count_minimums",
    "count_maximums",
)


class BeliefV2CommonSurfaceError(ValueError):
    """A V2 common-surface actor or tensor derivation drifted."""


def _array_population_sha256(tensors: HistoryOwnershipTensorsV1) -> str:
    digest = hashlib.sha256()
    digest.update(canonical_json_bytes({
        "schema": "belief-v1-v2-common-tensor-population-v1",
        "fields": list(ARRAY_FIELDS),
    }))
    for field in ARRAY_FIELDS:
        value = getattr(tensors, field)
        if type(value) is not np.ndarray or not value.flags.c_contiguous:
            raise BeliefV2CommonSurfaceError(
                "V2 common tensor layout drift")
        header = canonical_json_bytes({
            "field": field,
            "dtype": value.dtype.str,
            "shape": list(value.shape),
            "byte_count": value.nbytes,
        })
        raw = value.tobytes(order="C")
        digest.update(len(header).to_bytes(8, "big"))
        digest.update(header)
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def _common_play(play: PlayView) -> PlayView:
    if type(play) is not PlayView:
        raise BeliefV2CommonSurfaceError(
            "V2 common play population drift")
    return replace(
        play,
        failed_throw=False,
        attempted_cards=(),
    )


def _common_trick(trick: TrickView) -> TrickView:
    if type(trick) is not TrickView or type(trick.plays) is not tuple:
        raise BeliefV2CommonSurfaceError(
            "V2 common trick population drift")
    return replace(
        trick,
        plays=tuple(_common_play(play) for play in trick.plays),
    )


def common_surface_actor(actor: ActorObservationV1) -> ActorObservationV1:
    """Return the truthful, target-blind common replay view of one actor."""
    if type(actor) is not ActorObservationV1 \
            or actor.schema != ACTOR_OBSERVATION_SCHEMA \
            or type(actor.declaration_history_complete) is not bool \
            or type(actor.attempted_play_history_complete) is not bool \
            or type(actor.completed_tricks) is not tuple \
            or type(actor.current_trick) is not TrickView:
        raise BeliefV2CommonSurfaceError(
            "V2 common actor identity drift")
    declaration_history = () if actor.declaration is None \
        else (actor.declaration,)
    return replace(
        actor,
        declaration_history=declaration_history,
        declaration_history_complete=False,
        attempted_play_history_complete=False,
        completed_tricks=tuple(
            _common_trick(trick) for trick in actor.completed_tricks),
        current_trick=_common_trick(actor.current_trick),
    )


@dataclass(frozen=True)
class V2CommonSurfaceTensorsV1:
    source_actor_sha256: str
    common_surface_actor_sha256: str
    source_declaration_history_complete: bool
    source_attempted_play_history_complete: bool
    behavior_policy_ids: tuple[str, ...]
    tensors: HistoryOwnershipTensorsV1
    schema: str = COMMON_SURFACE_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "source_actor_sha256": self.source_actor_sha256,
            "common_surface_actor_sha256": (
                self.common_surface_actor_sha256),
            "source_channels": {
                "declaration_history_complete": (
                    self.source_declaration_history_complete),
                "attempted_play_history_complete": (
                    self.source_attempted_play_history_complete),
                "model_input": False,
            },
            "model_surface": {
                "declarations": DECLARATION_SURFACE,
                "plays": PLAY_SURFACE,
                "attempted_cards_masked": True,
                "failed_throw_masked": True,
                "source_channel_availability_model_input": False,
            },
            "behavior_policy_ids": list(self.behavior_policy_ids),
            "history_input_sha256": self.tensors.history_input_sha256,
            "tensor_population_sha256": _array_population_sha256(
                self.tensors),
            "privileged_targets_consumed": False,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def _build_common_surface_tensors(
        actor: ActorObservationV1, *,
        behavior_policy_ids: tuple[str, ...]) -> V2CommonSurfaceTensorsV1:
    common = common_surface_actor(actor)
    # The V1 feature builder requires complete channels.  This private adapter
    # flag is never serialized or hashed as an observation: the events already
    # contain the reviewed common surface (empty attempts, final declaration),
    # and the returned input is rebound to the truthful incomplete actor hash.
    builder_actor = replace(
        common,
        declaration_history_complete=True,
        attempted_play_history_complete=True,
    )
    model_input = _build_history_ownership_input(
        builder_actor, behavior_policy_ids=behavior_policy_ids)
    model_input = replace(
        model_input,
        actor_observation_sha256=common.sha256(),
    )
    tensors = _tensorize(model_input)
    return V2CommonSurfaceTensorsV1(
        source_actor_sha256=actor.sha256(),
        common_surface_actor_sha256=common.sha256(),
        source_declaration_history_complete=(
            actor.declaration_history_complete),
        source_attempted_play_history_complete=(
            actor.attempted_play_history_complete),
        behavior_policy_ids=behavior_policy_ids,
        tensors=tensors,
    )


def build_common_surface_tensors(
        actor: ActorObservationV1, *,
        behavior_policy_ids: tuple[str, ...]) -> V2CommonSurfaceTensorsV1:
    """Build and independently rederive the exact V2 common tensors."""
    result = _build_common_surface_tensors(
        actor, behavior_policy_ids=behavior_policy_ids)
    validate_common_surface_tensors(actor, result)
    return result


def validate_common_surface_tensors(
        actor: ActorObservationV1,
        candidate: V2CommonSurfaceTensorsV1) -> None:
    if type(candidate) is not V2CommonSurfaceTensorsV1 \
            or candidate.schema != COMMON_SURFACE_SCHEMA \
            or candidate.to_dict()["privileged_targets_consumed"] is not False:
        raise BeliefV2CommonSurfaceError(
            "V2 common tensor schema/authority drift")
    expected = _build_common_surface_tensors(
        actor, behavior_policy_ids=candidate.behavior_policy_ids)
    scalar_fields = (
        "schema",
        "source_actor_sha256",
        "common_surface_actor_sha256",
        "source_declaration_history_complete",
        "source_attempted_play_history_complete",
        "behavior_policy_ids",
    )
    if any(getattr(candidate, field) != getattr(expected, field)
           for field in scalar_fields) \
            or candidate.tensors.schema != expected.tensors.schema \
            or candidate.tensors.actor_observation_sha256 \
            != expected.tensors.actor_observation_sha256 \
            or candidate.tensors.history_input_sha256 \
            != expected.tensors.history_input_sha256 \
            or candidate.tensors.behavior_policy_ids \
            != expected.tensors.behavior_policy_ids \
            or any(type(getattr(candidate.tensors, field)) is not np.ndarray
                   or not np.array_equal(
                       getattr(candidate.tensors, field),
                       getattr(expected.tensors, field))
                   for field in ARRAY_FIELDS):
        raise BeliefV2CommonSurfaceError(
            "V2 common tensor derivation drift")
