"""Bounded, seed-bound natural/mechanics source driver for Value V2.

The population bridge accepts a complete snapshot by design.  This module is
the small producer-side boundary: it owns the one attempted deal, constructs
the only :class:`Round` used for that attempt, and gives the bridge only
canonical snapshots produced by that round.
"""

from __future__ import annotations

import copy
import hashlib
import random
from dataclasses import dataclass
from typing import Any, Mapping

from ..ai.registry import make_bot
from ..engine.round import Round
from .belief_contract import canonical_json_bytes
from .world_afterstate import canonical_successor
from .world_afterstate_capacity import PRODUCTION_BALLOT_POLICY
from .world_afterstate_v2_population import (
    PopulationMaterialV2, WorldAfterstateV2PopulationError,
    _validate_attempt, build_population_material_v2,
)
from .world_afterstate_v2_protocol import (
    ATTEMPT_SCHEMA, PopulationSlotV2,
)


SCHEMA = "world-afterstate-v2-source-attempt-v1"
MAX_DECISIONS = 100  # Four players, twenty-five cards each.
REJECTION_MODE_MISMATCH = "actual-trump-mode-mismatch"
REJECTION_REQUESTED_MODE_UNAVAILABLE = "requested-trump-mode-unavailable"
REJECTION_NO_ELIGIBLE_STATE = "no-eligible-state"
REJECTION_ENGINE_ERROR = "engine-error"
REJECTION_MATERIALIZATION_ERROR = "materialization-error"
FORBIDDEN_TOKENS = (
    "outcome", "utility", "label", "raw_seed", "terminal_outcome",
)


class WorldAfterstateV2SourceDriverError(ValueError):
    """An attempted deal or its source-driver contract was malformed."""


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(
            char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV2SourceDriverError(f"{label} drift")
    return value


def _derived_initial_banker(deal_sha256: str) -> int | None:
    """Derive a stable banker anchor without adding a caller-owned field."""
    digest = hashlib.sha256(canonical_json_bytes({
        "namespace": "world-afterstate-v2-source-driver-banker-v1",
        "deal_sha256": deal_sha256,
    })).digest()[0]
    # Keeping None in the stream exercises first-round engine behavior while
    # still making the choice a property of this exact attempted deal.
    return None if digest % 5 == 0 else digest % 4


def trajectory_policy_seed(deal_sha256: str, seat: int) -> int:
    """Return the domain-separated production trajectory seed for one seat."""
    _digest(deal_sha256, "trajectory deal SHA-256")
    if isinstance(seat, bool) or not isinstance(seat, int) or not 0 <= seat < 4:
        raise WorldAfterstateV2SourceDriverError("trajectory seat drift")
    return int.from_bytes(hashlib.sha256(canonical_json_bytes({
        "namespace": "world-afterstate-v2-source-driver-trajectory-v1",
        "deal_sha256": deal_sha256,
        "seat": seat,
    })).digest()[:8], "big") & ((1 << 63) - 1)


def _safe_attempt_identity(attempt: Mapping[str, Any], deal: str) -> dict[str, Any]:
    """Return attempt identity suitable for a score-free result.

    The engine seed is intentionally absent.  It is an input to the one
    in-memory Round, never a result or publication field.
    """
    return {
        "schema": ATTEMPT_SCHEMA,
        "population_namespace_sha256": attempt[
            "population_namespace_sha256"],
        "slot_sha256": attempt["slot_sha256"],
        "attempt_index": attempt["attempt_index"],
        "deal_sha256": deal,
    }


def _trump_mode(rnd: Round) -> str:
    return "NT" if rnd.trump_is_nt else str(rnd.trump_suit)


def _declare_requested_mechanics_mode(
        rnd: Round, slot: PopulationSlotV2) -> bool:
    """Declare the requested mode from the dealt hands, if it is legal.

    This is intentionally a read of the canonical hands followed by the
    engine's own ``declare`` transition.  In particular, it never edits the
    deck, hands, or any of Round's derived trump fields.  Seat order is the
    deterministic tie-break; for a no-trump seat holding both legal pairs,
    BJ is preferred to LJ.
    """
    if slot.trump_mode == "NT":
        for seat in range(4):
            hand = rnd.hands[seat]
            for code in ("BJ", "LJ"):
                if hand.count(code) >= 2:
                    rnd.declare(seat, [code, code])
                    return True
        return False

    code = f"{slot.trump_mode}{slot.trump_rank}"
    for seat in range(4):
        hand = rnd.hands[seat]
        count = hand.count(code)
        if count:
            rnd.declare(seat, [code, code] if count >= 2 else [code])
            return True
    return False


@dataclass(frozen=True)
class PopulationAttemptResultV2:
    """Score-free result of one exact D256 natural/mechanics attempt."""

    attempted_deal_identity: dict[str, Any]
    deal_sha256: str
    slot_sha256: str
    attempted: bool
    accepted: bool
    rejection_reason: str | None
    material: PopulationMaterialV2 | None
    decision_count: int
    schema: str = SCHEMA

    def validate(self) -> None:
        if self.schema != SCHEMA or type(self.attempted) is not bool \
                or type(self.accepted) is not bool or not self.attempted:
            raise WorldAfterstateV2SourceDriverError("attempt result schema drift")
        if type(self.attempted_deal_identity) is not dict \
                or set(self.attempted_deal_identity) != {
                    "schema", "population_namespace_sha256", "slot_sha256",
                    "attempt_index", "deal_sha256"} \
                or self.attempted_deal_identity.get("schema") != ATTEMPT_SCHEMA:
            raise WorldAfterstateV2SourceDriverError("attempt result identity drift")
        identity_deal = self.attempted_deal_identity["deal_sha256"]
        _digest(identity_deal, "result deal SHA-256")
        _digest(self.deal_sha256, "result deal SHA-256")
        _digest(self.slot_sha256, "result slot SHA-256")
        if identity_deal != self.deal_sha256 \
                or self.attempted_deal_identity["slot_sha256"] != self.slot_sha256:
            raise WorldAfterstateV2SourceDriverError("attempt result binding drift")
        _digest(self.attempted_deal_identity[
            "population_namespace_sha256"], "result namespace SHA-256")
        index = self.attempted_deal_identity["attempt_index"]
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise WorldAfterstateV2SourceDriverError("result attempt index drift")
        expected_deal = hashlib.sha256(canonical_json_bytes({
            "schema": ATTEMPT_SCHEMA,
            "population_namespace_sha256": self.attempted_deal_identity[
                "population_namespace_sha256"],
            "slot_sha256": self.slot_sha256,
            "attempt_index": index,
        })).hexdigest()
        if expected_deal != self.deal_sha256:
            raise WorldAfterstateV2SourceDriverError(
                "result deal derivation drift")
        if isinstance(self.decision_count, bool) \
                or not isinstance(self.decision_count, int) \
                or not 0 <= self.decision_count <= MAX_DECISIONS:
            raise WorldAfterstateV2SourceDriverError("result decision count drift")
        if self.accepted:
            if self.rejection_reason is not None \
                    or type(self.material) is not PopulationMaterialV2:
                raise WorldAfterstateV2SourceDriverError("accepted result drift")
            self.material.validate()
            if self.material.deal_sha256 != self.deal_sha256 \
                    or self.material.slot_sha256 != self.slot_sha256:
                raise WorldAfterstateV2SourceDriverError("accepted material binding drift")
        elif self.material is not None \
                or self.rejection_reason not in {
                    REJECTION_MODE_MISMATCH,
                    REJECTION_REQUESTED_MODE_UNAVAILABLE,
                    REJECTION_NO_ELIGIBLE_STATE, REJECTION_ENGINE_ERROR,
                    REJECTION_MATERIALIZATION_ERROR}:
            raise WorldAfterstateV2SourceDriverError("rejected result drift")

    def payload(self) -> dict[str, Any]:
        """Serialize only score-free, seed-free result identity."""
        self.validate()
        return {
            "schema": self.schema,
            "attempted_deal_identity": copy.deepcopy(
                self.attempted_deal_identity),
            "deal_sha256": self.deal_sha256,
            "slot_sha256": self.slot_sha256,
            "attempted": self.attempted,
            "accepted": self.accepted,
            "rejection_reason": self.rejection_reason,
            "selected_material": None if self.material is None else
            dict(self.material.state.__dict__),
            "decision_count": self.decision_count,
        }

    to_dict = payload


def _result(attempt: Mapping[str, Any], deal: str, slot: PopulationSlotV2,
            *, accepted: bool, reason: str | None,
            material: PopulationMaterialV2 | None,
            decision_count: int) -> PopulationAttemptResultV2:
    value = PopulationAttemptResultV2(
        attempted_deal_identity=_safe_attempt_identity(attempt, deal),
        deal_sha256=deal, slot_sha256=slot.slot_sha256, attempted=True,
        accepted=accepted, rejection_reason=reason, material=material,
        decision_count=decision_count)
    value.validate()
    return value


def drive_population_attempt_v2(
        attempted_deal_identity: Mapping[str, Any],
        slot: PopulationSlotV2) -> PopulationAttemptResultV2:
    """Drive one exact D256 deal and select its smallest eligible state hash.

    There is deliberately no snapshot argument.  Every snapshot passed to the
    population bridge is emitted from this invocation's single Round.
    """
    if type(slot) is not PopulationSlotV2:
        raise WorldAfterstateV2SourceDriverError("population slot type drift")
    try:
        slot.validate()
    except Exception as exc:
        raise WorldAfterstateV2SourceDriverError(
            "population slot identity drift") from exc
    if slot.tier != "D256" or slot.source not in ("natural", "mechanics"):
        raise WorldAfterstateV2SourceDriverError(
            "D256 source driver forbids external slot")
    # Validate the exact attempt before touching Round.  In particular this
    # refuses a forged engine seed before the engine can be constructed.
    try:
        deal = _validate_attempt(attempted_deal_identity, slot)
    except Exception as exc:
        if isinstance(exc, WorldAfterstateV2SourceDriverError):
            raise
        raise WorldAfterstateV2SourceDriverError(str(exc)) from exc
    assert type(attempted_deal_identity) is dict
    engine_seed = attempted_deal_identity["engine_seed"]
    banker = _derived_initial_banker(deal)
    policies: list[Any]
    rnd: Round
    try:
        policies = [make_bot(
            PRODUCTION_BALLOT_POLICY,
            seed=trajectory_policy_seed(deal, seat)) for seat in range(4)]
        rnd = Round(slot.trump_rank, banker, random.Random(engine_seed))
        if slot.source == "mechanics":
            # Mechanics targets are selected only after the complete deal, so
            # the forced declaration is a function of all four hands.
            while rnd.phase == "deal":
                rnd.deal_next()
            if not _declare_requested_mechanics_mode(rnd, slot):
                return _result(
                    attempted_deal_identity, deal, slot, accepted=False,
                    reason=REJECTION_REQUESTED_MODE_UNAVAILABLE, material=None,
                    decision_count=0)
        else:
            # Keep the natural production declaration stream byte-identical.
            while rnd.phase == "deal":
                seat, _, _ = rnd.deal_next()
                cards = policies[seat].decide_declare(rnd, seat)
                if cards:
                    rnd.declare(seat, cards)
            for seat in range(4):
                cards = policies[seat].decide_declare(rnd, seat, final=True)
                if cards:
                    rnd.declare(seat, cards)
        rnd.finalize_declare()
        if rnd.banker is None:
            raise RuntimeError("banker missing")
        rnd.bury(rnd.banker, policies[rnd.banker].decide_bury(
            rnd, rnd.banker))
    except Exception as exc:
        return _result(attempted_deal_identity, deal, slot, accepted=False,
                       reason=REJECTION_ENGINE_ERROR, material=None,
                       decision_count=0)

    if _trump_mode(rnd) != slot.trump_mode:
        return _result(attempted_deal_identity, deal, slot, accepted=False,
                       reason=REJECTION_MODE_MISMATCH, material=None,
                       decision_count=0)

    materials: list[PopulationMaterialV2] = []
    decision_count = 0
    try:
        while rnd.phase == "play":
            if decision_count >= MAX_DECISIONS:
                return _result(attempted_deal_identity, deal, slot,
                               accepted=False, reason=REJECTION_ENGINE_ERROR,
                               material=None, decision_count=decision_count)
            actor = rnd.turn
            if actor is None:
                raise RuntimeError("play actor missing")
            snapshot = canonical_successor(rnd, actor)
            decision_count += 1
            public = snapshot["public"]
            if slot.source == "natural":
                completed = public["completed_tricks"]
                phase = "early" if len(completed) < 6 else (
                    "middle" if len(completed) < 14 else "late")
                position = "lead" if not public["current_trick"]["plays"] \
                    else "follow"
                role = snapshot["root_role"]
                if (phase, position, role) != slot.cell:
                    rnd.play(actor, policies[actor].decide_play(rnd, actor))
                    continue
            try:
                material = build_population_material_v2(
                    attempted_deal_identity, slot, snapshot)
            except WorldAfterstateV2PopulationError as exc:
                # Mechanics surfaces are derived by the bridge and may miss
                # this state.  A one-action late state also cannot form the
                # required comparison ballot.  These are eligibility misses;
                # all other bridge/engine errors fail closed.
                if str(exc) == "candidate ballot lacks comparison actions" \
                        or (slot.source == "mechanics" \
                            and str(exc) == "mechanics surface mismatch"):
                    material = None
                else:
                    return _result(
                        attempted_deal_identity, deal, slot, accepted=False,
                        reason=REJECTION_MATERIALIZATION_ERROR, material=None,
                        decision_count=decision_count)
            if material is not None:
                materials.append(material)
            rnd.play(actor, policies[actor].decide_play(rnd, actor))
    except Exception:
        return _result(attempted_deal_identity, deal, slot, accepted=False,
                       reason=REJECTION_ENGINE_ERROR, material=None,
                       decision_count=decision_count)
    if not materials:
        return _result(attempted_deal_identity, deal, slot, accepted=False,
                       reason=REJECTION_NO_ELIGIBLE_STATE, material=None,
                       decision_count=decision_count)
    selected = min(materials, key=lambda value: value.state_sha256)
    return _result(attempted_deal_identity, deal, slot, accepted=True,
                   reason=None, material=selected, decision_count=decision_count)


# Descriptive aliases for callers that use "attempt" or "source" vocabulary.
run_population_attempt_v2 = drive_population_attempt_v2
attempt_population_slot_v2 = drive_population_attempt_v2
materialize_population_attempt_v2 = drive_population_attempt_v2
drive_source_attempt_v2 = drive_population_attempt_v2
run_source_attempt_v2 = drive_population_attempt_v2
attempt_source_v2 = drive_population_attempt_v2
drive_attempt_v2 = drive_population_attempt_v2
run_attempt_v2 = drive_population_attempt_v2
SourceDriverResultV2 = PopulationAttemptResultV2
SourceAttemptResultV2 = PopulationAttemptResultV2
V2SourceAttemptResult = PopulationAttemptResultV2


__all__ = [
    "FORBIDDEN_TOKENS", "MAX_DECISIONS", "PopulationAttemptResultV2",
    "REJECTION_ENGINE_ERROR", "REJECTION_MATERIALIZATION_ERROR",
    "REJECTION_MODE_MISMATCH", "REJECTION_NO_ELIGIBLE_STATE",
    "REJECTION_REQUESTED_MODE_UNAVAILABLE", "SCHEMA",
    "WorldAfterstateV2SourceDriverError", "SourceDriverResultV2",
    "attempt_population_slot_v2",
    "SourceAttemptResultV2", "V2SourceAttemptResult",
    "attempt_source_v2", "drive_attempt_v2", "drive_population_attempt_v2",
    "drive_source_attempt_v2", "materialize_population_attempt_v2",
    "run_attempt_v2", "run_population_attempt_v2", "run_source_attempt_v2",
    "trajectory_policy_seed",
]
