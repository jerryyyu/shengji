"""Inference-only fixed-input adapter for MLP complete-world values.

The training encoder remains :func:`value_afterstate.tensors_from_round`.
This adapter only omits constructing its public-history sequence after running
the sequence encoder's refusal checks; MLP models never consume that input.
"""

from __future__ import annotations

import hashlib
import operator
from pathlib import Path

import numpy as np

from ..rl.encode import CARD_INDEX, N_CARDS, encode_obs
from ..rl.douzero_micro import HISTORY_EVENT_DIM, HISTORY_MAX_EVENTS
from ..rl.value_afterstate import (
    WORLD_RECEIVERS,
    ValueAfterstateTensors,
    _seat,
    _validate_complete_round,
    tensors_from_round as _reference_tensors_from_round,
)


STATIC_ENCODING_SCHEMA = "shengji-cwv-mlp-static-adapter-v1"


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


def tensors_from_round_static(rnd, root_seat: int) -> ValueAfterstateTensors:
    """Return MLP model inputs without constructing public-play history.

    Public/world/perspective construction deliberately follows the operation
    order and float32 casts in ``tensors_from_round``.  The one-row zero
    history is the same input produced by ``cwv_policy._stack(history_free)``.
    """
    root_seat = _seat(root_seat, "root seat")
    _validate_complete_round(rnd)
    try:
        public = np.asarray(
            [*encode_obs(rnd, root_seat), float(rnd.phase == "round_end")],
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
    "static_encoding_identity", "tensors_from_round_static",
]
