"""Inference-only fixed-input adapter for MLP complete-world values.

The training encoder remains :func:`value_afterstate.tensors_from_round`.
This adapter skips its unused history sequence and the Memory deductions not
consumed by the fixed public features. Valid engine states retain the reference
model inputs; unsupported public shapes use the original encoder.
"""

from __future__ import annotations

import hashlib
import operator
from pathlib import Path

import numpy as np

from ..engine.cards import Ordering
from ..engine.round import Round, Trick, TrickPlay
from ..rl.encode import (
    CARD_INDEX, N_CARDS, OBS_DIM, RANKS, SUITS, TRUMP, _counts, encode_obs,
)
from ..rl.douzero_micro import HISTORY_EVENT_DIM, HISTORY_MAX_EVENTS
from ..rl.value_afterstate import (
    WORLD_RECEIVERS,
    ValueAfterstateTensors,
    _seat,
    _validate_complete_round,
    tensors_from_round as _reference_tensors_from_round,
)


STATIC_ENCODING_SCHEMA = "shengji-cwv-mlp-static-adapter-v2"


def _source_sha256() -> str:
    digest = hashlib.sha256()
    with Path(__file__).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


STATIC_ENCODING_SOURCE_SHA256 = _source_sha256()


def static_encoding_identity() -> dict[str, str]:
    """Identify this inference adapter, never the training encoder."""
    return {
        "schema": STATIC_ENCODING_SCHEMA,
        "source_sha256": STATIC_ENCODING_SOURCE_SHA256,
    }


def _standard_play(play) -> bool:
    return (type(play) is TrickPlay and type(play.cards) is list
            and bool(play.cards)
            and all(type(card) is str and card in CARD_INDEX
                    for card in play.cards)
            and type(play.seat) is int and 0 <= play.seat < 4)


def _static_obs_eligible(rnd, seat: int) -> bool:
    """Be conservative when the reference ``Memory`` may raise or differ."""
    try:
        if type(rnd) is not Round or type(seat) is not int or not 0 <= seat < 4:
            return False
        if type(rnd.ordering) is not Ordering or rnd.phase not in ("play", "round_end"):
            return False
        if type(rnd.history) is not list or type(rnd.hands) is not list \
                or len(rnd.hands) != 4 or type(rnd.buried) is not list:
            return False
        if any(type(hand) is not list or any(
                type(card) is not str or card not in CARD_INDEX for card in hand)
               for hand in rnd.hands):
            return False
        if any(type(card) is not str or card not in CARD_INDEX
               for card in rnd.buried):
            return False
        if type(rnd.banker) is not int or not 0 <= rnd.banker < 4 \
                or type(rnd.attacker_points) is not int:
            return False
        if type(rnd.trump_is_nt) is not bool or rnd.trump_rank not in RANKS:
            return False
        for trick in rnd.history:
            if type(trick) is not Trick or type(trick.plays) is not list \
                    or len(trick.plays) != 4 \
                    or not all(_standard_play(play) for play in trick.plays):
                return False
        if rnd.trick is None:
            return False
        if type(rnd.trick) is not Trick or type(rnd.trick.plays) is not list \
                or len(rnd.trick.plays) > 3:
            return False
        if not all(_standard_play(play) for play in rnd.trick.plays):
            return False
        declaration = rnd.declaration
        if declaration is not None:
            if type(declaration) is not dict \
                    or not {"seat", "cards"}.issubset(declaration):
                return False
            decl_seat = declaration["seat"]
            cards = declaration["cards"]
            if type(decl_seat) is not int or not 0 <= decl_seat < 4 \
                    or type(cards) is not list or not cards \
                    or any(type(card) is not str or card not in CARD_INDEX
                           for card in cards):
                return False
        return True
    except Exception:
        return False


def encode_obs_static(rnd: Round, seat: int) -> list[float]:
    """Encode the fixed observation without constructing ``Memory``.

    The direct path consumes only Memory's played-card, unseen-card, and void
    results.  Pair/run deductions and declaration pins are intentionally not
    reconstructed.  Unsupported shapes delegate to the original encoder so
    its historical refusal type and message remain authoritative.
    """
    if not _static_obs_eligible(rnd, seat):
        return encode_obs(rnd, seat)
    try:
        ordering = rnd.ordering
        played_by = [[] for _ in range(4)]
        voids = [set() for _ in range(4)]
        played_counts = [0] * N_CARDS

        tricks = list(rnd.history)
        if rnd.trick.plays:
            tricks.append(rnd.trick)
        for trick in tricks:
            lead_suit = ordering.eff_suit(trick.plays[0].cards[0])
            for index, play in enumerate(trick.plays):
                played_by[play.seat].extend(play.cards)
                for card in play.cards:
                    played_counts[CARD_INDEX[card]] += 1
                if index > 0 and any(
                        ordering.eff_suit(card) != lead_suit
                        for card in play.cards):
                    voids[play.seat].add(lead_suit)

        trick_planes = [[0.0] * N_CARDS for _ in range(3)]
        for index, play in enumerate(rnd.trick.plays[:3]):
            trick_planes[index] = _counts(play.cards)

        obs: list[float] = []
        obs += _counts(rnd.hands[seat])
        for relative in range(4):
            obs += _counts(played_by[(seat + relative) % 4])
        for plane in trick_planes:
            obs += plane

        own_counts = [0] * N_CARDS
        for card in rnd.hands[seat]:
            own_counts[CARD_INDEX[card]] += 1
        # _counts increments by exactly 0.5 per copy; these small integer
        # counts give the identical floats without materializing card strings.
        obs += [0.5 * max(0, 2 - played_counts[index] - own_counts[index])
                for index in range(N_CARDS)]

        suit_onehot = [0.0] * 5
        if rnd.trump_is_nt:
            suit_onehot[4] = 1.0
        elif rnd.trump_suit in SUITS:
            suit_onehot[SUITS.index(rnd.trump_suit)] = 1.0
        obs += suit_onehot
        rank_onehot = [0.0] * 13
        rank_onehot[RANKS.index(rnd.trump_rank)] = 1.0
        obs += rank_onehot
        banker_rel = [0.0] * 4
        banker_rel[(rnd.banker - seat) % 4] = 1.0
        obs += banker_rel
        obs.append(min(rnd.attacker_points, 200) / 200.0)
        obs.append(sum(len(hand) for hand in rnd.hands) / 100.0)
        obs.append(1.0 if rnd.is_attacker(seat) else 0.0)
        for relative in range(4):
            observed_seat = (seat + relative) % 4
            for eff in list(SUITS) + [TRUMP]:
                obs.append(float(eff in voids[observed_seat]))
        if len(obs) != OBS_DIM:
            return encode_obs(rnd, seat)
        return obs
    except Exception:
        return encode_obs(rnd, seat)


def _events(rnd):
    events = []
    for trick in rnd.history:
        events.extend((position, play) for position, play in enumerate(trick.plays))
    if rnd.trick is not None:
        events.extend(
            (position, play) for position, play in enumerate(rnd.trick.plays))
    return events


def _history_is_valid(rnd) -> bool:
    """Check every condition enforced by ``encode_public_history``.

    Invalid input is sent through the reference encoder by the caller, which
    preserves its exact exception type/message.  Valid input never allocates
    the sequence rows or calls the reference history encoder.
    """
    try:
        events = _events(rnd)
        if not 1 <= len(events) <= HISTORY_MAX_EVENTS:
            return False
        for position, play in events:
            if position not in range(4) or play.seat not in range(4):
                return False
            # Membership alone also accepts 1.0, but NumPy's reference row
            # indexing does not. Preserve that refusal instead of accepting a
            # malformed event merely because the MLP discards history.
            operator.index(play.seat % 4)
            for card in play.cards:
                if card not in CARD_INDEX:
                    return False
        return True
    except Exception:
        return False


def _fused_static_tensors(rnd, seat: int) -> ValueAfterstateTensors | None:
    """Build and check ordinary engine inputs in one card traversal.

    No trust flag or cross-call cache is involved. The same traversal that
    constructs played/hand planes counts the entire physical population and
    validates every card/event. Unsupported or invalid states return to the
    established path, preserving its exception type, message and ordering.
    Half-copy increments are exactly representable, as in the training encoder.
    """
    try:
        if (type(rnd) is not Round or type(seat) is not int or not 0 <= seat < 4
                or rnd.phase != "play" or type(rnd.ordering) is not Ordering
                or type(rnd.history) is not list or type(rnd.hands) is not list
                or len(rnd.hands) != 4 or type(rnd.buried) is not list
                or type(rnd.banker) is not int or not 0 <= rnd.banker < 4
                or type(rnd.attacker_points) is not int
                or type(rnd.trump_is_nt) is not bool or rnd.trump_rank not in RANKS
                or type(rnd.trick) is not Trick or type(rnd.trick.plays) is not list
                or len(rnd.trick.plays) > 3):
            return None
        declaration = rnd.declaration
        if declaration is not None:
            if (type(declaration) is not dict
                    or type(declaration.get("seat")) is not int
                    or not 0 <= declaration["seat"] < 4
                    or type(declaration.get("cards")) is not list
                    or not declaration["cards"]
                    or any(type(card) is not str or card not in CARD_INDEX
                           for card in declaration["cards"])):
                return None

        physical = [0] * N_CARDS
        world = [[0.0] * N_CARDS for _ in range(WORLD_RECEIVERS)]
        for relative in range(WORLD_RECEIVERS):
            cards = (rnd.hands[(seat + relative) % 4] if relative < 4 else rnd.buried)
            if type(cards) is not list:
                return None
            plane = world[relative]
            for card in cards:
                if type(card) is not str:
                    return None
                index = CARD_INDEX[card]
                plane[index] += 0.5
                physical[index] += 1

        played = [[0.0] * N_CARDS for _ in range(4)]
        played_total = [0.0] * N_CARDS
        trick_planes = [[0.0] * N_CARDS for _ in range(3)]
        voids = [set() for _ in range(4)]
        event_count = 0
        for trick_index, trick in enumerate([*rnd.history, rnd.trick]):
            current = trick_index == len(rnd.history)
            if (type(trick) is not Trick or type(trick.plays) is not list
                    or (not current and len(trick.plays) != 4)):
                return None
            lead_suit = None
            for position, play in enumerate(trick.plays):
                if (type(play) is not TrickPlay or type(play.cards) is not list
                        or not play.cards or type(play.seat) is not int
                        or not 0 <= play.seat < 4):
                    return None
                event_count += 1
                plane = played[play.seat]
                off_suit = False
                for card in play.cards:
                    if type(card) is not str:
                        return None
                    index = CARD_INDEX[card]
                    suit = rnd.ordering.eff_suit(card)
                    if lead_suit is None:
                        lead_suit = suit
                    if position and suit != lead_suit:
                        off_suit = True
                    plane[index] += 0.5
                    played_total[index] += 0.5
                    physical[index] += 1
                    if current:
                        trick_planes[position][index] += 0.5
                if off_suit:
                    voids[play.seat].add(lead_suit)
        if (not 1 <= event_count <= HISTORY_MAX_EVENTS
                or any(count != 2 for count in physical)):
            return None

        obs = list(world[0])
        for relative in range(4):
            obs.extend(played[(seat + relative) % 4])
        for plane in trick_planes:
            obs.extend(plane)
        obs.extend(max(0.0, 1.0 - seen - own)
                   for seen, own in zip(played_total, world[0]))
        suit_onehot = [0.0] * 5
        if rnd.trump_is_nt:
            suit_onehot[4] = 1.0
        elif rnd.trump_suit in SUITS:
            suit_onehot[SUITS.index(rnd.trump_suit)] = 1.0
        obs.extend(suit_onehot)
        rank_onehot = [0.0] * 13
        rank_onehot[RANKS.index(rnd.trump_rank)] = 1.0
        obs.extend(rank_onehot)
        banker_rel = [0.0] * 4
        banker_rel[(rnd.banker - seat) % 4] = 1.0
        obs.extend(banker_rel)
        root_is_attacker = rnd.is_attacker(seat)
        obs.extend((min(rnd.attacker_points, 200) / 200.0,
                    sum(len(hand) for hand in rnd.hands) / 100.0,
                    float(root_is_attacker)))
        for relative in range(4):
            for suit in [*SUITS, TRUMP]:
                obs.append(float(suit in voids[(seat + relative) % 4]))
        if len(obs) != OBS_DIM:
            return None
        result = ValueAfterstateTensors(
            np.asarray([*obs, 0.0], dtype=np.float32),
            np.zeros((1, HISTORY_EVENT_DIM), dtype=np.float32),
            np.asarray(world, dtype=np.float32),
            np.asarray([float(root_is_attacker), float(not root_is_attacker)],
                       dtype=np.float32))
        result.validate()
        return result
    except Exception:
        return None


def tensors_from_round_static(rnd, root_seat: int) -> ValueAfterstateTensors:
    """Return MLP model inputs without unused Memory/history work.

    Public/world/perspective construction deliberately follows the operation
    order and float32 casts in ``tensors_from_round``.  The one-row zero
    history is the same input produced by ``cwv_policy._stack(history_free)``.
    """
    root_seat = _seat(root_seat, "root seat")
    fused = _fused_static_tensors(rnd, root_seat)
    if fused is not None:
        return fused
    _validate_complete_round(rnd)
    try:
        public = np.asarray(
            [*encode_obs_static(rnd, root_seat), float(rnd.phase == "round_end")],
            dtype=np.float32)
    except Exception:
        # Reference behavior remains authoritative for malformed public state.
        return _reference_tensors_from_round(rnd, root_seat)
    if not _history_is_valid(rnd):
        return _reference_tensors_from_round(rnd, root_seat)
    history = np.zeros((1, HISTORY_EVENT_DIM), dtype=np.float32)
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


__all__ = [
    "STATIC_ENCODING_SCHEMA", "STATIC_ENCODING_SOURCE_SHA256",
    "static_encoding_identity", "encode_obs_static",
    "tensors_from_round_static",
]
