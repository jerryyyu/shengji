"""Torch-free public-play history encoding shared by value consumers."""

from __future__ import annotations

from typing import Any

import numpy as np

from ..engine.cards import points
from .encode import CARD_INDEX, N_CARDS

HISTORY_MAX_EVENTS = 100
HISTORY_EVENT_DIM = N_CARDS + 4 + 4 + 2


class PublicHistoryError(ValueError):
    """A public engine history cannot be encoded."""


def encode_public_history(rnd: Any, seat: int) -> np.ndarray:
    """Encode chronological engine-recorded plays before ``seat``'s turn."""
    events = []
    for trick in rnd.history:
        events.extend((position, play) for position, play in enumerate(trick.plays))
    if rnd.trick is not None:
        events.extend((position, play) for position, play in enumerate(rnd.trick.plays))
    if len(events) > HISTORY_MAX_EVENTS:
        raise PublicHistoryError(
            f"public history has {len(events)} events; cap is {HISTORY_MAX_EVENTS}")
    rows = np.zeros((len(events), HISTORY_EVENT_DIM), dtype=np.float32)
    for row_index, (position, play) in enumerate(events):
        if position not in range(4) or play.seat not in range(4):
            raise PublicHistoryError("invalid public trick event")
        for card in play.cards:
            try:
                card_index = CARD_INDEX[card]
            except KeyError as exc:
                raise PublicHistoryError(
                    f"unknown public card code {card!r}") from exc
            rows[row_index, card_index] += 0.5
        offset = N_CARDS
        rows[row_index, offset + (play.seat - seat) % 4] = 1.0
        offset += 4
        rows[row_index, offset + position] = 1.0
        offset += 4
        rows[row_index, offset] = len(play.cards) / 25.0
        rows[row_index, offset + 1] = sum(points(c) for c in play.cards) / 40.0
    return rows


__all__ = ["HISTORY_EVENT_DIM", "HISTORY_MAX_EVENTS", "PublicHistoryError",
           "encode_public_history"]
