"""Minimal complete-world afterstate contract for trajectory value learning.

The engine owns the transition: callers provide a complete :class:`Round`
and a legal root action, and this module encodes only the reached state from a
fixed root-team perspective.  The action, trajectory policy, search ballot,
source, split, seed, and terminal outcome are never model inputs.

This is a reusable library surface.  It contains no population selector,
experiment controller, launcher, consumer registration, or gameplay authority.
"""

from __future__ import annotations

import copy
import hashlib
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from ..engine.cards import make_deck
from ..engine.round import Round, actual_play_after
from ..teacher_v1 import attacker_level_utility
from ..harvest.common import action_key
from ..harvest.rebuild import state_for_record
from ..harvest.schema import validate_record
from .douzero_micro import HISTORY_EVENT_DIM, encode_public_history
from .encode import CARD_INDEX, N_CARDS, OBS_DIM, encode_obs


AFTERSTATE_SCHEMA = "shengji-value-afterstate-v1"
DEAL_KEY_SCHEMA = "shengji-value-deal-key-v1"
PUBLIC_DIM = OBS_DIM + 1
WORLD_RECEIVERS = 5
PERSPECTIVE_DIM = 2
OUTCOME_CLASSES = 204
MIN_SIGNED_LEVEL_UTILITY = -101.5
MAX_SIGNED_LEVEL_UTILITY = 101.5


class ValueAfterstateError(ValueError):
    """A complete world, transition, tensor, perspective, or label drifted."""


def _seat(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 4:
        raise ValueAfterstateError(f"{label} must be an integer seat")
    return value


def _played_cards(rnd: Round) -> list[str]:
    cards: list[str] = []
    for trick in rnd.history:
        for play in trick.plays:
            cards.extend(play.cards)
    if rnd.trick is not None:
        for play in rnd.trick.plays:
            cards.extend(play.cards)
    return cards


def _deal_key(rnd: Round) -> str:
    """Cluster every row rebuilt from the same dealt deck together.

    The key deliberately ignores source labels and run-local identifiers, so
    the same deal cannot cross train/evaluation merely because it was imported
    through two harvest adapters or replayed by two policies.
    """
    if type(rnd.deck) is not list or len(rnd.deck) != len(make_deck()) \
            or any(type(card) is not str or card not in CARD_INDEX
                   for card in rnd.deck):
        raise ValueAfterstateError("afterstate deal deck drift")
    digest = hashlib.sha256(DEAL_KEY_SCHEMA.encode("ascii"))
    for card in rnd.deck:
        encoded = card.encode("ascii")
        digest.update(len(encoded).to_bytes(2, "big"))
        digest.update(encoded)
    return f"deck:{digest.hexdigest()}"


def _validate_complete_round(rnd: Round) -> None:
    if type(rnd) is not Round or rnd.phase not in ("play", "round_end"):
        raise ValueAfterstateError("afterstate must be an exact play/terminal Round")
    if rnd.banker is None or rnd.ordering is None:
        raise ValueAfterstateError("afterstate is missing banker or ordering")
    physical = Counter(_played_cards(rnd))
    for hand in rnd.hands:
        physical.update(hand)
    physical.update(rnd.buried)
    if physical != Counter(make_deck()):
        raise ValueAfterstateError("afterstate violates physical deck conservation")


def signed_level_category(attacker_points: int, root_is_attacker: bool) -> int:
    """Map the engine score to the historical closed 204-category support."""
    if isinstance(attacker_points, bool) or not isinstance(attacker_points, int) \
            or not 0 <= attacker_points <= 4_120:
        raise ValueAfterstateError("attacker points lie outside the engine bound")
    if type(root_is_attacker) is not bool:
        raise ValueAfterstateError("root perspective must be boolean")
    utility = attacker_level_utility(attacker_points)
    signed = utility if root_is_attacker else -utility
    if signed < MIN_SIGNED_LEVEL_UTILITY or signed > MAX_SIGNED_LEVEL_UTILITY \
            or signed == 0 or float(signed).is_integer():
        raise ValueAfterstateError("signed-level utility is outside support")
    return (int(signed - MIN_SIGNED_LEVEL_UTILITY) if signed < 0
            else 102 + int(signed - 0.5))


def category_signed_level(category: int) -> float:
    if isinstance(category, bool) or not isinstance(category, int) \
            or not 0 <= category < OUTCOME_CLASSES:
        raise ValueAfterstateError("outcome category is outside support")
    return (MIN_SIGNED_LEVEL_UTILITY + category if category < 102
            else 0.5 + category - 102)


@dataclass(frozen=True)
class ValueAfterstateTensors:
    """Target-free state tensors.  There is deliberately no action tensor."""

    public: np.ndarray
    history: np.ndarray
    world: np.ndarray
    perspective: np.ndarray

    def validate(self) -> None:
        expected = (
            (self.public, (PUBLIC_DIM,), "public"),
            (self.history, (None, HISTORY_EVENT_DIM), "history"),
            (self.world, (WORLD_RECEIVERS, N_CARDS), "world"),
            (self.perspective, (PERSPECTIVE_DIM,), "perspective"),
        )
        for value, shape, label in expected:
            if not isinstance(value, np.ndarray) or value.dtype != np.float32 \
                    or value.ndim != len(shape) \
                    or any(bound is not None and value.shape[index] != bound
                           for index, bound in enumerate(shape)) \
                    or not bool(np.all(np.isfinite(value))):
                raise ValueAfterstateError(f"{label} tensor shape/dtype drift")
        if not 1 <= self.history.shape[0] <= 100:
            raise ValueAfterstateError("history tensor length drift")
        if not bool(np.all((self.world == 0.0) | (self.world == 0.5)
                           | (self.world == 1.0))):
            raise ValueAfterstateError("world tensor count encoding drift")
        if float(self.perspective.sum()) != 1.0 \
                or not bool(np.all((self.perspective == 0.0)
                                   | (self.perspective == 1.0))):
            raise ValueAfterstateError("perspective tensor is not one-hot")

    def sha256(self) -> str:
        self.validate()
        digest = hashlib.sha256(AFTERSTATE_SCHEMA.encode("ascii"))
        for name, value in (
                ("public", self.public), ("history", self.history),
                ("world", self.world), ("perspective", self.perspective)):
            payload = np.asarray(value, dtype="<f4", order="C")
            label = name.encode("ascii")
            shape = ",".join(str(size) for size in payload.shape).encode("ascii")
            digest.update(len(label).to_bytes(2, "big"))
            digest.update(label)
            digest.update(len(shape).to_bytes(2, "big"))
            digest.update(shape)
            digest.update(payload.tobytes(order="C"))
        return digest.hexdigest()


@dataclass(frozen=True)
class ValueAfterstateExample:
    """One offline state/terminal-outcome binding from a trajectory record."""

    source_ref: str
    deal_key: str
    stratum: str
    tensors: ValueAfterstateTensors
    target_category: int
    input_sha256: str

    def validate(self) -> None:
        if not self.source_ref or not self.deal_key:
            raise ValueAfterstateError("example identity is empty")
        if self.stratum not in {
                f"{phase}|{role}" for phase in ("early", "middle", "late")
                for role in ("attacker", "defender")}:
            raise ValueAfterstateError("example stratum drift")
        self.tensors.validate()
        category_signed_level(self.target_category)
        if self.input_sha256 != self.tensors.sha256():
            raise ValueAfterstateError("example input hash drift")


def phase_for_ply(ply_after_action: int) -> str:
    if isinstance(ply_after_action, bool) or not isinstance(ply_after_action, int) \
            or ply_after_action < 1:
        raise ValueAfterstateError("afterstate ply must be a positive integer")
    if ply_after_action <= 32:
        return "early"
    if ply_after_action <= 64:
        return "middle"
    return "late"


def tensors_from_round(rnd: Round, root_seat: int) -> ValueAfterstateTensors:
    """Encode one complete state from a fixed root-team perspective."""
    root_seat = _seat(root_seat, "root seat")
    _validate_complete_round(rnd)
    public = np.asarray(
        [*encode_obs(rnd, root_seat), float(rnd.phase == "round_end")],
        dtype=np.float32)
    history = encode_public_history(rnd, root_seat).astype(np.float32, copy=False)
    world = np.zeros((WORLD_RECEIVERS, N_CARDS), dtype=np.float32)
    for relative in range(4):
        for card in rnd.hands[(root_seat + relative) % 4]:
            world[relative, CARD_INDEX[card]] += 0.5
    for card in rnd.buried:
        world[4, CARD_INDEX[card]] += 0.5
    root_is_attacker = rnd.is_attacker(root_seat)
    perspective = np.asarray(
        [float(root_is_attacker), float(not root_is_attacker)], dtype=np.float32)
    result = ValueAfterstateTensors(public, history, world, perspective)
    result.validate()
    return result


def apply_action(rnd: Round, root_seat: int,
                 action: Sequence[str]) -> tuple[Round, tuple[str, ...]]:
    """Apply ``action`` through the real engine without mutating ``rnd``."""
    root_seat = _seat(root_seat, "root seat")
    _validate_complete_round(rnd)
    if rnd.phase != "play" or rnd.turn != root_seat:
        raise ValueAfterstateError("root action requires the actor's play decision")
    if type(action) not in (list, tuple) or not action \
            or any(type(card) is not str or card not in CARD_INDEX for card in action):
        raise ValueAfterstateError("root action contains an unknown card")
    successor: Round = copy.deepcopy(rnd)
    previous_last = successor.last_trick
    try:
        successor.play(root_seat, list(action))
    except Exception as exc:
        raise ValueAfterstateError("root action failed engine validation") from exc
    accepted = tuple(actual_play_after(successor, root_seat, previous_last))
    _validate_complete_round(successor)
    return successor, accepted


def tensors_after_action(rnd: Round, root_seat: int,
                         action: Sequence[str]) -> ValueAfterstateTensors:
    successor, _accepted = apply_action(rnd, root_seat, action)
    return tensors_from_round(successor, root_seat)


def terminal_distribution(rnd: Round, root_seat: int) -> np.ndarray:
    """Exact one-hot terminal value; terminal leaves never call a model."""
    root_seat = _seat(root_seat, "root seat")
    _validate_complete_round(rnd)
    if rnd.phase != "round_end":
        raise ValueAfterstateError("exact terminal value requires round_end")
    category = signed_level_category(rnd.attacker_points,
                                     rnd.is_attacker(root_seat))
    result = np.zeros(OUTCOME_CLASSES, dtype=np.float64)
    result[category] = 1.0
    return result


def example_from_trajectory_record(
        record: Mapping[str, Any]) -> ValueAfterstateExample:
    """Rebuild a full trajectory state, apply its action, and bind its outcome.

    Only ``outcome.attacker_points`` supplies the label.  The trajectory's
    recorded policy, ballot, preference, search evidence, action identity, and
    outcome never enter :func:`tensors_from_round`.
    """
    try:
        validate_record(record)
    except Exception as exc:
        raise ValueAfterstateError("trajectory record validation failed") from exc
    if record["decision_kind"] != "play" or record["outcome"] is None:
        raise ValueAfterstateError("value examples require labeled play records")
    try:
        root = state_for_record(record)
    except Exception as exc:
        raise ValueAfterstateError("trajectory state reconstruction failed") from exc
    root_seat = _seat(record["seat"], "record seat")
    if root.turn != root_seat:
        raise ValueAfterstateError("trajectory record is not the actor's decision")
    root_is_attacker = root.is_attacker(root_seat)
    role = "attacker" if root_is_attacker else "defender"
    record_role = "attacker-team" if root_is_attacker else "banker-team"
    if record["role"] != record_role:
        raise ValueAfterstateError("trajectory role disagrees with the engine")
    successor, accepted = apply_action(root, root_seat, record["action"])
    recorded_accepted = record.get("engine_play", record["action"])
    if action_key(accepted) != action_key(recorded_accepted):
        raise ValueAfterstateError("trajectory engine-accepted action drift")
    if action_key(accepted) != action_key(record["action"]) \
            and "engine_play" not in record:
        raise ValueAfterstateError("failed throw omitted engine_play")
    tensors = tensors_from_round(successor, root_seat)
    outcome = record["outcome"]
    points = outcome.get("attacker_points") if isinstance(outcome, dict) else None
    if isinstance(points, bool) or not isinstance(points, int):
        raise ValueAfterstateError("trajectory outcome attacker_points drift")
    target = signed_level_category(points, root_is_attacker)
    example = ValueAfterstateExample(
        source_ref=record["source_ref"], deal_key=_deal_key(root),
        stratum=f"{phase_for_ply(int(record['ply']) + 1)}|{role}",
        tensors=tensors, target_category=target,
        input_sha256=tensors.sha256())
    example.validate()
    return example
