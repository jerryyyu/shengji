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

from ..engine.cards import RANKS, Ordering, make_deck
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
ACTOR_DECISION_SCHEMA = "world-afterstate-actor-decision-v0"
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


def actor_visible_root_identity(
        rnd: Round, root_seat: int,
        ordered_candidates: Sequence[Sequence[str]]) -> dict[str, Any]:
    """Hash only information visible to the actor before any outcome.

    This identity is selection metadata, never a model feature. Other hands,
    a non-banker-visible burial, engine seeds, and continuation results cannot
    affect its bytes.
    """
    root_seat = _seat(root_seat, "root seat")
    if type(rnd) is not Round or rnd.phase != "play" or rnd.trick is None \
            or rnd.turn != root_seat \
            or type(ordered_candidates) not in (list, tuple) \
            or not ordered_candidates:
        raise WorldAfterstateError(
            "actor-visible root identity requires a play decision")
    candidates = [
        _cards(candidate, "actor-visible candidate")
        for candidate in ordered_candidates
    ]
    candidate_keys = [tuple(sorted(candidate)) for candidate in candidates]
    if len(candidate_keys) != len(set(candidate_keys)):
        raise WorldAfterstateError(
            "actor-visible candidate population contains duplicates")
    actor_cards = Counter(rnd.hands[root_seat])
    if any(not Counter(candidate) <= actor_cards for candidate in candidates):
        raise WorldAfterstateError(
            "actor-visible candidate is absent from the actor hand")
    public = np.asarray(encode_obs(rnd, root_seat), dtype="<f4")
    history = np.asarray(encode_public_history(rnd, root_seat), dtype="<f4")
    body = {
        "schema": ACTOR_DECISION_SCHEMA,
        "root_role": "attacker" if rnd.is_attacker(root_seat) else "defender",
        "public_shape": list(public.shape),
        "public_sha256": hashlib.sha256(public.tobytes(order="C")).hexdigest(),
        "history_shape": list(history.shape),
        "history_sha256":
            hashlib.sha256(history.tobytes(order="C")).hexdigest(),
        "ordered_candidates": [list(candidate) for candidate in candidates],
    }
    return {**body, "decision_sha256": _sha256(body)}


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


def replay_canonical_successor(value: Mapping[str, Any]) -> Round:
    """Rebuild a complete canonical snapshot through legal engine plays.

    This is the seed-free ingestion path for reviewed teacher transcripts.
    Remaining hands plus the public play history reconstruct each player's
    25-card post-burial hand.  Every recorded play is then applied through
    :meth:`Round.play`; the final canonical bytes must match the input.  The
    snapshot therefore cannot assert its own winner, points, turn, hand sizes,
    or terminal result.

    Seats in ``value`` are already root-relative, so the rebuilt actor is
    always seat 0.  Declaration metadata and the last engine message do not
    affect play mechanics or V0 tensors; they remain byte-bound public
    metadata and are restored only after the mechanical replay succeeds.
    """
    if type(value) is not dict or set(value) != {
            "schema", "root_role", "public", "complete_world"} \
            or value.get("schema") != SUCCESSOR_SCHEMA:
        raise WorldAfterstateError("canonical snapshot schema drift")
    if value["root_role"] not in ("attacker", "defender"):
        raise WorldAfterstateError("canonical snapshot root role drift")
    public = value["public"]
    complete = value["complete_world"]
    public_keys = {
        "phase", "terminal", "turn", "banker", "first_round",
        "trump_rank", "trump_suit", "trump_is_nt", "declaration",
        "attacker_points", "kitty_bonus", "last_trick_winner",
        "completed_tricks", "current_trick", "message", "hand_sizes",
    }
    if type(public) is not dict or set(public) != public_keys \
            or type(complete) is not dict \
            or set(complete) != {"hands", "buried"}:
        raise WorldAfterstateError("canonical snapshot field population drift")
    phase = public["phase"]
    if phase not in ("play", "round_end") \
            or type(public["terminal"]) is not bool \
            or public["terminal"] is not (phase == "round_end"):
        raise WorldAfterstateError("canonical snapshot phase drift")
    banker = _seat(public["banker"], "snapshot banker")
    turn = public["turn"]
    if turn is not None:
        turn = _seat(turn, "snapshot turn")
    if (phase == "play" and turn is None) \
            or (phase == "round_end" and turn is not None):
        raise WorldAfterstateError("canonical snapshot turn drift")
    rank = public["trump_rank"]
    suit = public["trump_suit"]
    if type(rank) is not str or rank not in RANKS \
            or suit not in ("S", "H", "D", "C", None) \
            or type(public["trump_is_nt"]) is not bool \
            or public["trump_is_nt"] is not (suit is None) \
            or type(public["first_round"]) is not bool:
        raise WorldAfterstateError("canonical snapshot trump metadata drift")
    for key in ("attacker_points", "kitty_bonus"):
        if isinstance(public[key], bool) or not isinstance(public[key], int) \
                or public[key] < 0:
            raise WorldAfterstateError(
                "canonical snapshot score metadata drift")
    last_winner = public["last_trick_winner"]
    if last_winner is not None:
        _seat(last_winner, "snapshot last-trick winner")
    if public["message"] is not None and type(public["message"]) is not str:
        raise WorldAfterstateError("canonical snapshot message drift")

    declaration = public["declaration"]
    normalized_declaration = None
    if declaration is not None:
        if type(declaration) is not dict \
                or set(declaration) != {"seat", "cards", "strength"} \
                or isinstance(declaration["strength"], bool) \
                or not isinstance(declaration["strength"], int):
            raise WorldAfterstateError(
                "canonical snapshot declaration drift")
        normalized_declaration = {
            "seat": _seat(declaration["seat"], "snapshot declaration seat"),
            "cards": _cards(
                declaration["cards"], "snapshot declaration cards"),
            "strength": declaration["strength"],
        }

    hands_value = complete["hands"]
    if type(hands_value) not in (list, tuple) or len(hands_value) != 4:
        raise WorldAfterstateError("canonical snapshot hand population drift")
    remaining_hands = [
        _cards(hands_value[seat], f"snapshot hand {seat}")
        for seat in range(4)
    ]
    buried = _cards(complete["buried"], "snapshot burial")
    hand_sizes = public["hand_sizes"]
    if type(hand_sizes) not in (list, tuple) or len(hand_sizes) != 4 \
            or any(isinstance(size, bool) or not isinstance(size, int)
                   or size < 0 for size in hand_sizes) \
            or list(hand_sizes) != [len(hand) for hand in remaining_hands]:
        raise WorldAfterstateError("canonical snapshot hand-size drift")
    if len(buried) != 8:
        raise WorldAfterstateError("canonical snapshot burial-size drift")

    def trick_row(raw: object, label: str, *, completed: bool) \
            -> tuple[int, list[tuple[int, list[str]]]]:
        if type(raw) is not dict or set(raw) != {
                "leader", "plays", "winner", "points"}:
            raise WorldAfterstateError(f"{label} schema drift")
        leader = _seat(raw["leader"], f"{label} leader")
        plays = raw["plays"]
        if type(plays) not in (list, tuple) \
                or (completed and len(plays) != 4) \
                or (not completed and not 0 <= len(plays) < 4):
            raise WorldAfterstateError(f"{label} play population drift")
        normalized_plays: list[tuple[int, list[str]]] = []
        for index, play in enumerate(plays):
            if type(play) is not dict or set(play) != {"seat", "cards"}:
                raise WorldAfterstateError(f"{label} play schema drift")
            normalized_plays.append((
                _seat(play["seat"], f"{label} play seat"),
                _cards(play["cards"], f"{label} play cards")))
        if completed:
            _seat(raw["winner"], f"{label} winner")
            if isinstance(raw["points"], bool) \
                    or not isinstance(raw["points"], int) \
                    or raw["points"] < 0:
                raise WorldAfterstateError(f"{label} score drift")
        elif raw["winner"] is not None or raw["points"] != 0:
            raise WorldAfterstateError(f"{label} unresolved state drift")
        return leader, normalized_plays

    completed_value = public["completed_tricks"]
    if type(completed_value) not in (list, tuple):
        raise WorldAfterstateError(
            "canonical snapshot completed-trick population drift")
    completed = [
        trick_row(raw, f"completed trick {index}", completed=True)
        for index, raw in enumerate(completed_value)
    ]
    current_value = public["current_trick"]
    if phase == "play":
        if current_value is None:
            raise WorldAfterstateError("canonical snapshot current trick drift")
        current = trick_row(current_value, "current trick", completed=False)
    else:
        if current_value is not None:
            raise WorldAfterstateError("terminal snapshot retained current trick")
        current = None

    initial_hands = [list(hand) for hand in remaining_hands]
    for _leader, plays in [*completed, *(() if current is None else (current,))]:
        for seat, cards in plays:
            initial_hands[seat].extend(cards)
    if any(len(hand) != 25 for hand in initial_hands):
        raise WorldAfterstateError(
            "canonical snapshot cannot reconstruct 25-card hands")
    physical = Counter(buried)
    for hand in initial_hands:
        physical.update(hand)
    if physical != Counter(make_deck()):
        raise WorldAfterstateError(
            "canonical snapshot violates physical deck conservation")

    rnd = Round(rank, banker, random.Random(0))
    rnd.deck = make_deck()
    rnd.kitty = list(buried)
    rnd._deal_pos = 100
    rnd.hands = [list(hand) for hand in initial_hands]
    rnd.banker = banker
    rnd.first_round = public["first_round"]
    rnd.phase = "play"
    rnd.turn = banker
    rnd.declaration = normalized_declaration
    if normalized_declaration is not None \
            and rnd._declaration_strength(normalized_declaration["cards"]) \
            != normalized_declaration["strength"]:
        raise WorldAfterstateError(
            "canonical snapshot declaration strength drift")
    rnd.passed = set()
    rnd.ordering = Ordering(suit, rank)
    rnd.trump_suit = suit
    rnd.trump_is_nt = public["trump_is_nt"]
    rnd.buried = list(buried)
    rnd.trick = Trick(leader=banker)
    rnd.last_trick = None
    rnd.history = []
    rnd.attacker_points = 0
    rnd.kitty_bonus = 0
    rnd.last_trick_winner = None
    rnd.message = None
    rnd._trusted_rollout = False

    try:
        for leader, plays in completed:
            if rnd.phase != "play" or rnd.trick is None \
                    or rnd.trick.leader != leader:
                raise WorldAfterstateError(
                    "canonical snapshot completed-trick leader drift")
            for seat, cards in plays:
                rnd.play(seat, list(cards))
        if current is not None:
            leader, plays = current
            if rnd.phase != "play" or rnd.trick is None \
                    or rnd.trick.leader != leader:
                raise WorldAfterstateError(
                    "canonical snapshot current-trick leader drift")
            for seat, cards in plays:
                rnd.play(seat, list(cards))
    except WorldAfterstateError:
        raise
    except Exception as exc:
        raise WorldAfterstateError(
            "canonical snapshot engine replay failed") from exc

    # A failed-throw message is not recoverable from accepted play cards.
    # It is actor-visible metadata but not a V0 tensor, so retain it only after
    # all mechanics have been independently reconstructed.
    rnd.message = public["message"]
    reconstructed = canonical_successor(rnd, 0)
    if canonical_json_bytes(reconstructed) != canonical_json_bytes(value):
        raise WorldAfterstateError("canonical snapshot reconstruction drift")
    return rnd


def build_afterstate_audit_from_snapshot(
        prestate: Mapping[str, Any], action: Sequence[str]) -> dict[str, Any]:
    """Apply one root action to a seed-free complete-world snapshot."""
    if type(prestate) is not dict:
        raise WorldAfterstateError("snapshot prestate must be an exact object")
    source_copy = copy.deepcopy(prestate)
    world = replay_canonical_successor(source_copy)
    root_seat = 0
    if world.phase != "play" or world.trick is None or world.turn != root_seat:
        raise WorldAfterstateError(
            "snapshot prestate must be a root play decision")
    canonical_prestate = canonical_successor(world, root_seat)
    attempted_action = _cards(action, "root action")
    if not attempted_action:
        raise WorldAfterstateError("root action must not be empty")
    complete_world = {
        "hands": {str(seat): sorted(world.hands[seat]) for seat in range(4)},
        "buried": sorted(world.buried),
    }
    try:
        world.play(root_seat, list(attempted_action))
    except Exception as exc:
        raise WorldAfterstateError("root action is not engine legal") from exc
    successor = canonical_successor(world, root_seat)
    return {
        "schema": AUDIT_SCHEMA,
        "source_state": source_copy,
        "complete_world_pre_action": complete_world,
        "root_seat": root_seat,
        "attempted_action": list(attempted_action),
        "prestate": canonical_prestate,
        "prestate_sha256": _sha256(canonical_prestate),
        "successor": successor,
        "successor_sha256": _sha256(successor),
    }


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
    source_state = copy.deepcopy(record["source_state"])
    if type(source_state) is not dict:
        raise WorldAfterstateError("source state must be an exact object")
    source_schema = source_state.get("schema")
    if source_schema == ROOT_REPLAY_SCHEMA:
        rnd = replay_root_state(source_state)
    elif source_schema == SUCCESSOR_SCHEMA:
        if root_seat != 0:
            raise WorldAfterstateError(
                "canonical snapshot root-seat binding drift")
        rnd = replay_canonical_successor(source_state)
    else:
        raise WorldAfterstateError("source state schema drift")
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


def _tensors_from_round(rnd: Round, root_seat: int) \
        -> WorldAfterstateTensorsV0:
    """Encode one already-reopened complete state from a named perspective."""
    root_seat = _seat(root_seat, "root seat")
    if type(rnd) is not Round or rnd.phase not in ("play", "round_end") \
            or rnd.banker is None or rnd.ordering is None:
        raise WorldAfterstateError("tensor source round identity drift")
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


def build_afterstate_tensors(record: Mapping[str, Any]) \
        -> WorldAfterstateTensorsV0:
    """Reopen the audit row, then build only successor-state model inputs."""
    rnd = reopen_afterstate_audit(record)
    root_seat = _seat(record["root_seat"], "root seat")
    return _tensors_from_round(rnd, root_seat)


def build_root_rotated_afterstate_tensors(
        record: Mapping[str, Any], offset: int) -> WorldAfterstateTensorsV0:
    """Cyclically relabel every absolute seat, then encode from the new root.

    This is the executable rotation witness for E4.  It starts from the
    engine-reopened successor, rotates the actual ``Round`` graph (hands,
    banker, turn, declaration, tricks, winners, and plays), and requires the
    resulting canonical successor to remain byte-identical in root-relative
    coordinates before tensors are returned.
    """
    if isinstance(offset, bool) or not isinstance(offset, int) \
            or not 1 <= offset <= 3:
        raise WorldAfterstateError("root rotation offset drift")
    base = reopen_afterstate_audit(record)
    root = _seat(record["root_seat"], "root seat")
    rotated: Round = copy.deepcopy(base)

    def seat(value: int | None) -> int | None:
        return None if value is None else (value + offset) % 4

    hands = [[] for _ in range(4)]
    for original, hand in enumerate(rotated.hands):
        hands[(original + offset) % 4] = hand
    rotated.hands = hands
    rotated.banker = seat(rotated.banker)
    rotated.turn = seat(rotated.turn)
    rotated.last_trick_winner = seat(rotated.last_trick_winner)
    rotated.passed = {seat(value) for value in rotated.passed}
    if rotated.declaration is not None:
        rotated.declaration["seat"] = seat(rotated.declaration["seat"])

    seen: set[int] = set()
    for trick in [*rotated.history, rotated.trick, rotated.last_trick]:
        if trick is None or id(trick) in seen:
            continue
        seen.add(id(trick))
        trick.leader = seat(trick.leader)
        trick.winner = seat(trick.winner)
        for play in trick.plays:
            play.seat = seat(play.seat)
        # These rollout-only caches are not public identity and cannot be
        # transported safely across an explicit relabeling.
        trick.incumbent = None
        trick.running_points = None
    rotated_root = (root + offset) % 4
    if canonical_json_bytes(canonical_successor(base, root)) \
            != canonical_json_bytes(
                canonical_successor(rotated, rotated_root)):
        raise WorldAfterstateError(
            "root rotation changed canonical successor bytes")
    return _tensors_from_round(rotated, rotated_root)


def build_preaction_tensors(record: Mapping[str, Any]) \
        -> WorldAfterstateTensorsV0:
    """Build the frozen action-ablation input from the exact pre-action state.

    Reopening the complete audit first proves that this is not a caller-supplied
    alternate state.  ``prestate`` is already canonicalized into the root
    actor's relative seat frame, so its acting seat is exactly zero.
    """
    _ = reopen_afterstate_audit(record)
    prestate = record.get("prestate")
    if type(prestate) is not dict:
        raise WorldAfterstateError("pre-action tensor source drift")
    rnd = replay_canonical_successor(prestate)
    if rnd.phase != "play" or rnd.turn != 0:
        raise WorldAfterstateError("pre-action tensor source drift")
    return _tensors_from_round(rnd, 0)


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


def bind_outcome_to_preaction(
        record: Mapping[str, Any], outcome: Mapping[str, Any]) \
        -> WorldAfterstateExampleV0:
    """Bind the true successor outcome to the reviewed pre-action ablation."""
    rnd = reopen_afterstate_audit(record)
    validate_outcome(outcome)
    if outcome["successor_sha256"] != record["successor_sha256"]:
        raise WorldAfterstateError("outcome successor binding drift")
    root_seat = _seat(record["root_seat"], "root seat")
    if outcome["root_is_attacker"] is not rnd.is_attacker(root_seat):
        raise WorldAfterstateError("outcome root perspective binding drift")
    example = WorldAfterstateExampleV0(
        tensors=build_preaction_tensors(record),
        signed_level_category=outcome["signed_level_category"],
        # Predictions remain bound to the candidate successor even though the
        # ablation deliberately withholds that successor from the model.
        successor_sha256=record["successor_sha256"],
    )
    example.validate()
    return example
