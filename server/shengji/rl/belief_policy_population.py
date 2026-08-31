"""Outcome-blind natural-root selection for the R4 policy diagnostic."""

from __future__ import annotations

import copy
from dataclasses import dataclass

from ..ai.mcbot import MCBot
from ..ai.registry import make_bot
from ..engine.round import Round
from .belief_capture import (
    CHAMPION_POLICY,
    CapturedActorRoundV1,
    _capture_with_policies,
)
from .belief_contract import ActorObservationV1, PublicTranscriptV1
from .belief_corpus import reopen_actor_row
from .belief_policy_protocol import (
    PolicyRoundCoordinateV1,
    policy_capacity_coordinates,
    policy_root_order_key,
    policy_round_coordinates,
    policy_seat_seeds,
)


class BeliefPolicyPopulationError(ValueError):
    """A natural root, ballot, replay state, or selection identity drifted."""


@dataclass(frozen=True)
class SelectedPolicyRootV1:
    coordinate: PolicyRoundCoordinateV1
    decision_index: int
    actor_seat: int
    actor: ActorObservationV1
    candidates: tuple[tuple[str, ...], ...]
    selection_key: bytes
    round_state: Round
    transcript: PublicTranscriptV1
    proposal_true_world_compatible: bool


def _proposal_true_world_compatible(
        rnd: Round, seat: int, actor: ActorObservationV1) -> bool:
    for constraint in actor.deductions.declaration_eligibility:
        receiver = constraint.eligible_receivers[0]
        prefix = "seat-relative-"
        if not receiver.startswith(prefix):
            raise BeliefPolicyPopulationError(
                "proposal support receiver drift")
        relative = int(receiver.removeprefix(prefix))
        absolute = (seat + relative) % 4
        if rnd.hands[absolute].count(constraint.card) \
                < constraint.minimum_copies:
            return False
    return True


def validate_selected_policy_root(value: SelectedPolicyRootV1) -> None:
    if type(value) is not SelectedPolicyRootV1 \
            or (value.coordinate not in policy_round_coordinates()
                and value.coordinate not in policy_capacity_coordinates()) \
            or type(value.decision_index) is not int \
            or value.decision_index < 0 \
            or type(value.actor_seat) is not int \
            or value.actor_seat not in range(4) \
            or type(value.actor) is not ActorObservationV1 \
            or type(value.candidates) is not tuple \
            or len(value.candidates) < 2 \
            or any(type(candidate) is not tuple or not candidate
                   or any(type(card) is not str or not card
                          for card in candidate)
                   for candidate in value.candidates) \
            or len(set(value.candidates)) != len(value.candidates) \
            or type(value.selection_key) is not bytes \
            or len(value.selection_key) != 32 \
            or type(value.round_state) is not Round \
            or value.round_state.phase != "play" \
            or value.round_state.turn != value.actor_seat \
            or type(value.transcript) is not PublicTranscriptV1 \
            or type(value.proposal_true_world_compatible) is not bool:
        raise BeliefPolicyPopulationError(
            "selected policy root population drift")
    if value.selection_key != policy_root_order_key(
            value.coordinate,
            decision_index=value.decision_index,
            actor_sha256=value.actor.sha256()):
        raise BeliefPolicyPopulationError(
            "selected policy root order-key drift")
    try:
        from .belief_contract import build_actor_observation
        rebuilt = build_actor_observation(
            value.round_state, value.actor_seat, value.transcript)
    except ValueError as exc:
        raise BeliefPolicyPopulationError(
            "selected policy root actor replay refused") from exc
    if rebuilt.canonical_bytes() != value.actor.canonical_bytes() \
            or _proposal_true_world_compatible(
                value.round_state, value.actor_seat, value.actor) \
            is not value.proposal_true_world_compatible:
        raise BeliefPolicyPopulationError(
            "selected policy root replay drift")
    probe = make_bot(CHAMPION_POLICY, seed=0)
    if not isinstance(probe, MCBot):
        raise BeliefPolicyPopulationError(
            "selected policy root ballot policy drift")
    candidates, early = probe._search_entry(
        value.round_state, value.actor_seat)
    if early is not None or candidates is None \
            or tuple(tuple(candidate) for candidate in candidates) \
            != value.candidates:
        raise BeliefPolicyPopulationError(
            "selected policy root ballot replay drift")


def select_natural_policy_root(
        coordinate: PolicyRoundCoordinateV1) -> SelectedPolicyRootV1 | None:
    """Capture one natural round and retain its hash-min contested root."""
    if type(coordinate) is not PolicyRoundCoordinateV1 \
            or (coordinate not in policy_round_coordinates()
                and coordinate not in policy_capacity_coordinates()):
        raise BeliefPolicyPopulationError(
            "policy root coordinate derivation drift")
    seat_seeds = policy_seat_seeds(coordinate)
    policies = [make_bot(CHAMPION_POLICY, seed=seed)
                for seed in seat_seeds]
    if any(not isinstance(policy, MCBot) for policy in policies):
        raise BeliefPolicyPopulationError(
            "policy root capture policy drift")
    ballot_probe = make_bot(CHAMPION_POLICY, seed=0)
    if not isinstance(ballot_probe, MCBot):
        raise BeliefPolicyPopulationError(
            "policy root ballot policy drift")
    selected: SelectedPolicyRootV1 | None = None

    def observe(rnd: Round, seat: int, transcript: PublicTranscriptV1,
                actor_row: bytes) -> None:
        nonlocal selected
        try:
            actor, metadata = reopen_actor_row(actor_row)
        except ValueError as exc:
            raise BeliefPolicyPopulationError(
                "policy root actor row refused") from exc
        candidates, early = ballot_probe._search_entry(rnd, seat)
        if early is not None or candidates is None:
            return
        decision_index = metadata["decision_index"]
        key = policy_root_order_key(
            coordinate, decision_index=decision_index,
            actor_sha256=actor.sha256())
        if selected is not None and selected.selection_key <= key:
            return
        selected = SelectedPolicyRootV1(
            coordinate=coordinate,
            decision_index=decision_index,
            actor_seat=seat,
            actor=actor,
            candidates=tuple(tuple(candidate) for candidate in candidates),
            selection_key=key,
            round_state=copy.deepcopy(rnd),
            transcript=copy.deepcopy(transcript),
            proposal_true_world_compatible=(
                _proposal_true_world_compatible(rnd, seat, actor)),
        )

    captured = _capture_with_policies(
        coordinate.round_seed,
        CHAMPION_POLICY,
        seat_seeds,
        policies,
        decision_observer=observe,
        actor_only=True,
        trump_rank=coordinate.trump_rank,
    )
    if type(captured) is not CapturedActorRoundV1:
        raise BeliefPolicyPopulationError(
            "policy root actor capture type drift")
    if selected is not None:
        validate_selected_policy_root(selected)
    return selected
