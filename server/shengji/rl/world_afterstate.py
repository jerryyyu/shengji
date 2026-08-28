"""Strict mechanics and tensors for the first complete-world value learner.

``V_world_after`` evaluates a state *after* the Shengji engine applies one
legal root action in one complete hidden world.  The action is retained only
in the audit record: the model consumes the reached state, never an action
feature.  This keeps transition mechanics owned by :class:`Round` and makes a
later ``Q_world(w, o, a)`` a derived engine quantity rather than a second
learned contract.

This module deliberately contains no corpus reader, continuation policy,
checkpoint writer, run launcher, promotion rule, belief model, or gameplay
authority.  Those surfaces require a separately frozen experiment packet.
"""

from __future__ import annotations

import copy
import hashlib
import random
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from ..engine.cards import RANKS, make_deck
from ..engine.round import Round, Trick
from ..teacher_v1 import attacker_level_utility
from .belief_contract import canonical_json_bytes
from .douzero_micro import (HISTORY_EVENT_DIM, encode_public_history)
from .encode import CARD_INDEX, N_CARDS, OBS_DIM, encode_obs


AUDIT_SCHEMA = "world-afterstate-audit-v0"
ROOT_REPLAY_SCHEMA = "world-afterstate-root-replay-v0"
SUCCESSOR_SCHEMA = "world-afterstate-successor-v0"
OUTCOME_SCHEMA = "world-afterstate-outcome-v0"
TENSOR_SCHEMA = "world-afterstate-tensors-v0"
PUBLIC_DIM = OBS_DIM + 1  # actor-visible observation plus terminal flag
WORLD_RECEIVERS = 5      # root-relative hands 0..3, then hidden burial
PERSPECTIVE_DIM = 2      # attacker-root, defender-root
OUTCOME_CLASSES = 204
MIN_SIGNED_LEVEL_UTILITY = -101.5
MAX_SIGNED_LEVEL_UTILITY = 101.5


class WorldAfterstateError(ValueError):
    """An afterstate, transition, tensor, perspective, or label drifted."""


def _sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _seat(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) \
            or not 0 <= value < 4:
        raise WorldAfterstateError(f"{label} must be an integer seat")
    return value


def _relative(seat: int | None, root_seat: int) -> int | None:
    return None if seat is None else (seat - root_seat) % 4


def _cards(value: object, label: str) -> list[str]:
    if type(value) not in (list, tuple):
        raise WorldAfterstateError(f"{label} must be a card sequence")
    result = list(value)
    if any(type(card) is not str or card not in CARD_INDEX for card in result):
        raise WorldAfterstateError(f"{label} contains an unknown card")
    return result


def _play_dict(play, root_seat: int) -> dict[str, Any]:
    return {
        "seat": _relative(play.seat, root_seat),
        "cards": sorted(_cards(play.cards, "trick play")),
    }


def _trick_dict(trick: Trick | None, root_seat: int) -> dict[str, Any] | None:
    if trick is None:
        return None
    return {
        "leader": _relative(trick.leader, root_seat),
        "plays": [_play_dict(play, root_seat) for play in trick.plays],
        "winner": _relative(trick.winner, root_seat),
        "points": int(trick.points),
    }


def _played_cards(rnd: Round) -> list[str]:
    played: list[str] = []
    for trick in rnd.history:
        for play in trick.plays:
            played.extend(play.cards)
    if rnd.trick is not None:
        for play in rnd.trick.plays:
            played.extend(play.cards)
    return played


def _validate_complete_world(
        rnd: Round, root_seat: int, hands: Mapping[int, Sequence[str]],
        buried: Sequence[str]) -> tuple[list[list[str]], list[str]]:
    if type(hands) is not dict or set(hands) != {0, 1, 2, 3}:
        raise WorldAfterstateError("complete world must contain exactly four hands")
    normalized_hands = [sorted(_cards(hands[seat], f"hand {seat}"))
                        for seat in range(4)]
    normalized_buried = sorted(_cards(buried, "burial"))
    if normalized_hands[root_seat] != sorted(rnd.hands[root_seat]):
        raise WorldAfterstateError("complete world changed the root actor hand")
    if any(len(normalized_hands[seat]) != len(rnd.hands[seat])
           for seat in range(4)):
        raise WorldAfterstateError("complete world hand-size drift")
    if len(normalized_buried) != len(rnd.buried):
        raise WorldAfterstateError("complete world burial-size drift")
    physical = Counter(_played_cards(rnd))
    for hand in normalized_hands:
        physical.update(hand)
    physical.update(normalized_buried)
    if physical != Counter(make_deck()):
        raise WorldAfterstateError("complete world violates physical deck conservation")
    return normalized_hands, normalized_buried


def materialize_complete_world(
        rnd: Round, root_seat: int, hands: Mapping[int, Sequence[str]],
        buried: Sequence[str]) -> Round:
    """Return an isolated engine state containing one validated hidden world."""
    root_seat = _seat(root_seat, "root seat")
    if type(rnd) is not Round or rnd.phase != "play" or rnd.trick is None \
            or rnd.turn != root_seat:
        raise WorldAfterstateError("root state must be an exact play decision")
    normalized_hands, normalized_buried = _validate_complete_world(
        rnd, root_seat, hands, buried)
    clone: Round = copy.deepcopy(rnd)
    clone.hands = [list(hand) for hand in normalized_hands]
    clone.buried = list(normalized_buried)
    clone._trusted_rollout = False
    return clone


def root_replay(
        *, deal_seed: int, initial_banker: int | None, trump_rank: str,
        declarations: Sequence[Mapping[str, Any]], buried: Sequence[str],
        plays: Sequence[Mapping[str, Any]], root_seat: int) \
        -> dict[str, Any]:
    """Canonical engine-event recipe for any rank and prior banker identity."""
    if isinstance(deal_seed, bool) or not isinstance(deal_seed, int) \
            or not 0 <= deal_seed < 2**63:
        raise WorldAfterstateError("root replay deal seed drift")
    if initial_banker is not None:
        initial_banker = _seat(initial_banker, "initial banker")
    if type(trump_rank) is not str or trump_rank not in RANKS:
        raise WorldAfterstateError("root replay trump rank drift")
    root_seat = _seat(root_seat, "root seat")
    if type(declarations) not in (list, tuple) \
            or type(plays) not in (list, tuple):
        raise WorldAfterstateError("root replay event sequence drift")
    declaration_rows = []
    for value in declarations:
        if type(value) is not dict or set(value) != {
                "stage", "deal_pos", "seat", "cards"} \
                or value["stage"] not in ("deal", "final") \
                or isinstance(value["deal_pos"], bool) \
                or not isinstance(value["deal_pos"], int) \
                or not 0 <= value["deal_pos"] <= 100:
            raise WorldAfterstateError("root replay declaration event drift")
        declaration_rows.append({
            "stage": value["stage"], "deal_pos": value["deal_pos"],
            "seat": _seat(value["seat"], "declaration seat"),
            "cards": _cards(value["cards"], "declaration cards"),
        })
    play_rows = []
    for value in plays:
        if type(value) is not dict or set(value) != {"seat", "cards"}:
            raise WorldAfterstateError("root replay play event drift")
        play_rows.append({
            "seat": _seat(value["seat"], "play seat"),
            "cards": _cards(value["cards"], "play cards"),
        })
    return {
        "schema": ROOT_REPLAY_SCHEMA,
        "deal_seed": deal_seed,
        "initial_banker": initial_banker,
        "trump_rank": trump_rank,
        "declarations": declaration_rows,
        "buried": _cards(buried, "root replay burial"),
        "plays": play_rows,
        "root_seat": root_seat,
    }


def replay_root_state(value: Mapping[str, Any]) -> Round:
    """Rebuild the exact play decision without assuming rank 2/first game."""
    if type(value) is not dict or set(value) != {
        "schema", "deal_seed", "initial_banker", "trump_rank",
        "declarations", "buried", "plays", "root_seat",
    } or value.get("schema") != ROOT_REPLAY_SCHEMA:
        raise WorldAfterstateError("root replay schema drift")
    recipe = root_replay(
        deal_seed=value["deal_seed"],
        initial_banker=value["initial_banker"],
        trump_rank=value["trump_rank"], declarations=value["declarations"],
        buried=value["buried"], plays=value["plays"],
        root_seat=value["root_seat"])
    if canonical_json_bytes(recipe) != canonical_json_bytes(value):
        raise WorldAfterstateError("root replay canonical derivation drift")
    rnd = Round(
        recipe["trump_rank"], recipe["initial_banker"],
        random.Random(recipe["deal_seed"]))
    events = recipe["declarations"]
    event_index = 0
    try:
        while rnd.phase == "deal":
            rnd.deal_next()
            while event_index < len(events) \
                    and events[event_index]["stage"] == "deal":
                event = events[event_index]
                if event["deal_pos"] < rnd._deal_pos:
                    raise WorldAfterstateError(
                        "root replay declaration order drift")
                if event["deal_pos"] != rnd._deal_pos:
                    break
                rnd.declare(event["seat"], list(event["cards"]))
                event_index += 1
        if event_index < len(events) \
                and events[event_index]["stage"] == "deal":
            raise WorldAfterstateError(
                "root replay declaration lies beyond deal")
        while event_index < len(events):
            event = events[event_index]
            if event["stage"] != "final" \
                    or event["deal_pos"] != rnd._deal_pos:
                raise WorldAfterstateError(
                    "root replay final declaration drift")
            rnd.declare(event["seat"], list(event["cards"]))
            event_index += 1
        rnd.finalize_declare()
        if rnd.banker is None:
            raise WorldAfterstateError("root replay did not determine banker")
        rnd.bury(rnd.banker, list(recipe["buried"]))
        for play in recipe["plays"]:
            rnd.play(play["seat"], list(play["cards"]))
    except WorldAfterstateError:
        raise
    except Exception as exc:
        raise WorldAfterstateError("root replay engine event failed") from exc
    if rnd.phase != "play" or rnd.trick is None \
            or rnd.turn != recipe["root_seat"]:
        raise WorldAfterstateError("root replay did not land at root decision")
    return rnd


def canonical_successor(rnd: Round, root_seat: int) -> dict[str, Any]:
    """Canonical model-relevant complete state in root-actor perspective."""
    root_seat = _seat(root_seat, "root seat")
    if type(rnd) is not Round or rnd.phase not in ("play", "round_end"):
        raise WorldAfterstateError("successor must be an exact play/terminal Round")
    if rnd.banker is None or rnd.ordering is None:
        raise WorldAfterstateError("successor is missing banker or ordering")
    declaration = None if rnd.declaration is None else {
        "seat": _relative(rnd.declaration["seat"], root_seat),
        "cards": sorted(_cards(rnd.declaration["cards"], "declaration")),
        "strength": int(rnd.declaration["strength"]),
    }
    payload: dict[str, Any] = {
        "schema": SUCCESSOR_SCHEMA,
        "root_role": "attacker" if rnd.is_attacker(root_seat) else "defender",
        "public": {
            "phase": rnd.phase,
            "terminal": rnd.phase == "round_end",
            "turn": _relative(rnd.turn, root_seat),
            "banker": _relative(rnd.banker, root_seat),
            "first_round": bool(rnd.first_round),
            "trump_rank": rnd.trump_rank,
            "trump_suit": rnd.trump_suit,
            "trump_is_nt": bool(rnd.trump_is_nt),
            "declaration": declaration,
            "attacker_points": int(rnd.attacker_points),
            "kitty_bonus": int(rnd.kitty_bonus),
            "last_trick_winner": _relative(
                rnd.last_trick_winner, root_seat),
            "completed_tricks": [_trick_dict(trick, root_seat)
                                  for trick in rnd.history],
            "current_trick": _trick_dict(rnd.trick, root_seat),
            "message": rnd.message,
            "hand_sizes": [len(rnd.hands[(root_seat + rel) % 4])
                           for rel in range(4)],
        },
        "complete_world": {
            "hands": [sorted(_cards(rnd.hands[(root_seat + rel) % 4],
                                           f"relative hand {rel}"))
                      for rel in range(4)],
            "buried": sorted(_cards(rnd.buried, "successor burial")),
        },
    }
    physical = Counter(_played_cards(rnd))
    for hand in rnd.hands:
        physical.update(hand)
    physical.update(rnd.buried)
    if physical != Counter(make_deck()):
        raise WorldAfterstateError("successor violates physical deck conservation")
    return payload


def build_afterstate_audit(
        source_state: Mapping[str, Any], hands: Mapping[int, Sequence[str]],
        buried: Sequence[str], action: Sequence[str]) -> dict[str, Any]:
    """Build an audit row by applying ``action`` through the real engine."""
    if type(source_state) is not dict:
        raise WorldAfterstateError("source state must be an exact object")
    source_copy = copy.deepcopy(source_state)
    rnd = replay_root_state(source_copy)
    root_seat = _seat(source_copy.get("root_seat"), "root seat")
    world = materialize_complete_world(rnd, root_seat, hands, buried)
    prestate = canonical_successor(world, root_seat)
    attempted_action = _cards(action, "root action")
    if not attempted_action:
        raise WorldAfterstateError("root action must not be empty")
    try:
        world.play(root_seat, list(attempted_action))
    except Exception as exc:
        raise WorldAfterstateError("root action is not engine legal") from exc
    successor = canonical_successor(world, root_seat)
    complete_world = {
        "hands": {str(seat): sorted(_cards(hands[seat], f"hand {seat}"))
                  for seat in range(4)},
        "buried": sorted(_cards(buried, "burial")),
    }
    return {
        "schema": AUDIT_SCHEMA,
        "source_state": source_copy,
        "complete_world_pre_action": complete_world,
        "root_seat": root_seat,
        "attempted_action": list(attempted_action),
        "prestate": prestate,
        "prestate_sha256": _sha256(prestate),
        "successor": successor,
        "successor_sha256": _sha256(successor),
    }


def reopen_afterstate_audit(record: Mapping[str, Any]) -> Round:
    """Reapply the action and require exact stored pre/successor bytes."""
    if type(record) is not dict or record.get("schema") != AUDIT_SCHEMA:
        raise WorldAfterstateError("afterstate audit schema drift")
    required = {
        "schema", "source_state", "complete_world_pre_action", "root_seat",
        "attempted_action", "prestate", "prestate_sha256", "successor",
        "successor_sha256",
    }
    if set(record) != required:
        raise WorldAfterstateError("afterstate audit field population drift")
    root_seat = _seat(record["root_seat"], "root seat")
    world_payload = record["complete_world_pre_action"]
    if type(world_payload) is not dict \
            or set(world_payload) != {"hands", "buried"} \
            or type(world_payload["hands"]) is not dict \
            or set(world_payload["hands"]) != {"0", "1", "2", "3"}:
        raise WorldAfterstateError("complete pre-action world schema drift")
    rnd = replay_root_state(copy.deepcopy(record["source_state"]))
    if rnd.turn != root_seat:
        raise WorldAfterstateError("source state root-seat binding drift")
    hands = {seat: world_payload["hands"][str(seat)] for seat in range(4)}
    world = materialize_complete_world(
        rnd, root_seat, hands, world_payload["buried"])
    prestate = canonical_successor(world, root_seat)
    if _sha256(prestate) != record["prestate_sha256"] \
            or canonical_json_bytes(prestate) \
            != canonical_json_bytes(record["prestate"]):
        raise WorldAfterstateError("prestate reconstruction drift")
    attempted_action = _cards(record["attempted_action"], "root action")
    try:
        world.play(root_seat, attempted_action)
    except Exception as exc:
        raise WorldAfterstateError("root action replay failed") from exc
    successor = canonical_successor(world, root_seat)
    if _sha256(successor) != record["successor_sha256"] \
            or canonical_json_bytes(successor) \
            != canonical_json_bytes(record["successor"]):
        raise WorldAfterstateError("successor reconstruction drift")
    return world


def signed_level_category(attacker_points: int, root_is_attacker: bool) -> int:
    """Mechanically map raw engine points to the closed 204-class support."""
    if isinstance(attacker_points, bool) or not isinstance(attacker_points, int) \
            or not 0 <= attacker_points <= 4_120:
        raise WorldAfterstateError("attacker points lie outside engine bound")
    if type(root_is_attacker) is not bool:
        raise WorldAfterstateError("root perspective must be boolean")
    utility = attacker_level_utility(attacker_points)
    signed = utility if root_is_attacker else -utility
    if signed < MIN_SIGNED_LEVEL_UTILITY or signed > MAX_SIGNED_LEVEL_UTILITY \
            or signed == 0 or float(signed).is_integer():
        raise WorldAfterstateError("signed-level utility is outside support")
    if signed < 0:
        return int(signed - MIN_SIGNED_LEVEL_UTILITY)
    return 102 + int(signed - 0.5)


def category_signed_level(category: int) -> float:
    if isinstance(category, bool) or not isinstance(category, int) \
            or not 0 <= category < OUTCOME_CLASSES:
        raise WorldAfterstateError("outcome category is outside support")
    if category < 102:
        return MIN_SIGNED_LEVEL_UTILITY + category
    return 0.5 + category - 102


def build_outcome(
        successor_sha256: str, attacker_points: int,
        root_is_attacker: bool) -> dict[str, Any]:
    if type(successor_sha256) is not str or len(successor_sha256) != 64 \
            or any(char not in "0123456789abcdef" for char in successor_sha256):
        raise WorldAfterstateError("successor SHA-256 is invalid")
    category = signed_level_category(attacker_points, root_is_attacker)
    return {
        "schema": OUTCOME_SCHEMA,
        "successor_sha256": successor_sha256,
        "attacker_points": attacker_points,
        "root_is_attacker": root_is_attacker,
        "signed_level_category": category,
        "signed_level_utility": category_signed_level(category),
    }


def validate_outcome(value: Mapping[str, Any]) -> None:
    if type(value) is not dict or set(value) != {
        "schema", "successor_sha256", "attacker_points", "root_is_attacker",
        "signed_level_category", "signed_level_utility",
    } or value.get("schema") != OUTCOME_SCHEMA:
        raise WorldAfterstateError("afterstate outcome schema drift")
    expected = build_outcome(
        value["successor_sha256"], value["attacker_points"],
        value["root_is_attacker"])
    if canonical_json_bytes(expected) != canonical_json_bytes(value):
        raise WorldAfterstateError("afterstate outcome derivation drift")


@dataclass(frozen=True)
class WorldAfterstateTensorsV0:
    """Target-free model input; notably there is no action tensor."""

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
                raise WorldAfterstateError(f"{label} tensor shape/dtype drift")
        if not bool(np.all((self.world == 0.0) | (self.world == 0.5)
                           | (self.world == 1.0))):
            raise WorldAfterstateError("world tensor count encoding drift")
        if float(self.perspective.sum()) != 1.0 \
                or not bool(np.all((self.perspective == 0.0)
                                   | (self.perspective == 1.0))):
            raise WorldAfterstateError("perspective tensor is not one-hot")


@dataclass(frozen=True)
class WorldAfterstateExampleV0:
    """Offline-only binding of target-free input to one raw outcome."""

    tensors: WorldAfterstateTensorsV0
    signed_level_category: int
    successor_sha256: str

    def validate(self) -> None:
        self.tensors.validate()
        category_signed_level(self.signed_level_category)
        if type(self.successor_sha256) is not str \
                or len(self.successor_sha256) != 64 \
                or any(char not in "0123456789abcdef"
                       for char in self.successor_sha256):
            raise WorldAfterstateError("example successor SHA-256 is invalid")


def build_afterstate_tensors(record: Mapping[str, Any]) \
        -> WorldAfterstateTensorsV0:
    """Reopen the audit row, then build only successor-state model inputs."""
    rnd = reopen_afterstate_audit(record)
    root_seat = _seat(record["root_seat"], "root seat")
    public = np.asarray(
        [*encode_obs(rnd, root_seat), float(rnd.phase == "round_end")],
        dtype=np.float32)
    history = encode_public_history(rnd, root_seat).astype(
        np.float32, copy=False)
    world = np.zeros((WORLD_RECEIVERS, N_CARDS), dtype=np.float32)
    for relative in range(4):
        for card in rnd.hands[(root_seat + relative) % 4]:
            world[relative, CARD_INDEX[card]] += 0.5
    for card in rnd.buried:
        world[4, CARD_INDEX[card]] += 0.5
    root_is_attacker = rnd.is_attacker(root_seat)
    perspective = np.asarray(
        [float(root_is_attacker), float(not root_is_attacker)],
        dtype=np.float32)
    tensors = WorldAfterstateTensorsV0(
        public=public, history=history, world=world,
        perspective=perspective)
    tensors.validate()
    return tensors


def bind_outcome_to_afterstate(
        record: Mapping[str, Any], outcome: Mapping[str, Any]) \
        -> WorldAfterstateExampleV0:
    """Pair one raw outcome only after transition and perspective revalidation."""
    rnd = reopen_afterstate_audit(record)
    validate_outcome(outcome)
    if outcome["successor_sha256"] != record["successor_sha256"]:
        raise WorldAfterstateError("outcome successor binding drift")
    root_seat = _seat(record["root_seat"], "root seat")
    if outcome["root_is_attacker"] is not rnd.is_attacker(root_seat):
        raise WorldAfterstateError("outcome root perspective binding drift")
    example = WorldAfterstateExampleV0(
        tensors=build_afterstate_tensors(record),
        signed_level_category=outcome["signed_level_category"],
        successor_sha256=record["successor_sha256"],
    )
    example.validate()
    return example
