"""Structural coverage summaries for candidate-action ballots.

This module deliberately describes only the action/card shape.  In particular,
variation in a card's multiplicity is not a claim that a training objective has
a non-zero gradient for that card.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any


_RANKS = ("2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A")
_SUITS = "SHDC"
_VALID_CARDS = frozenset(
    [suit + rank for suit in _SUITS for rank in _RANKS] + ["LJ", "BJ"]
)
_SEQUENCE_TYPES = (str, bytes, bytearray)


def _require_sequence(value: Any, description: str) -> Sequence[Any]:
    if isinstance(value, _SEQUENCE_TYPES) or not isinstance(value, Sequence):
        raise TypeError(f"{description} must be a sequence")
    return value


def _canonical_action(action: Any, slot: int) -> tuple[str, ...]:
    values = _require_sequence(action, f"ballot action {slot}")
    if not values:
        raise ValueError(f"ballot action {slot} must not be empty")

    counts: Counter[str] = Counter()
    for card in values:
        if type(card) is not str or card not in _VALID_CARDS:
            raise ValueError(f"ballot action {slot} contains invalid card {card!r}")
        counts[card] += 1
        if counts[card] > 2:
            raise ValueError(
                f"ballot action {slot} contains card {card!r} more than twice"
            )

    # An action is a multiset of cards: physical ordering within a play does
    # not make a distinct candidate action.
    return tuple(sorted(values))


def summarize_ballot_contrasts(ballot: Sequence[Sequence[str]]) -> dict[str, Any]:
    """Summarize card-level contrast available in ``ballot``.

    ``ballot`` is a sequence of candidate actions, and each action is a
    non-empty sequence of valid Sheng Ji card codes.  Repeated action slots
    count toward ``num_slots`` but not ``num_unique_actions``.  Card counts are
    measured for every observed card across *all* slots, including implicit
    zeroes in actions where that card is absent.

    Empty ballots are accepted and explicitly marked degenerate.  A ballot with
    only one unique candidate is also marked degenerate (with ``single`` for
    one slot and ``identical`` for repeated copies): it can describe a shape,
    but supplies no candidate contrast.  The returned booleans are coverage
    predicates only; they do not assert any non-zero model gradient.
    """
    rows = _require_sequence(ballot, "ballot")
    actions = [_canonical_action(action, slot) for slot, action in enumerate(rows)]
    num_slots = len(actions)
    unique_actions = sorted(set(actions))

    # Count every observed card once per slot, with absent cards contributing
    # zero.  Counter values are bounded by _canonical_action's two-deck guard.
    slot_counts = [Counter(action) for action in actions]
    cards = sorted({card for counts in slot_counts for card in counts})
    per_card: dict[str, dict[str, int | bool]] = {}
    common_positive_constant_cards: list[str] = []
    varying_cards: list[str] = []

    for card in cards:
        multiplicities = [counts.get(card, 0) for counts in slot_counts]
        minimum = min(multiplicities)
        maximum = max(multiplicities)
        varying = minimum != maximum
        preserve_spend = minimum == 0 and maximum > 0
        pair = minimum < 2 and maximum >= 2
        per_card[card] = {
            "min": minimum,
            "max": maximum,
            "preserve_spend": preserve_spend,
            "pair": pair,
        }
        if minimum == maximum and minimum > 0:
            common_positive_constant_cards.append(card)
        if varying:
            varying_cards.append(card)

    if num_slots == 0:
        degenerate_reason: str | None = "empty"
    elif len(unique_actions) == 1:
        degenerate_reason = "single" if num_slots == 1 else "identical"
    else:
        degenerate_reason = None

    return {
        "num_slots": num_slots,
        "num_unique_actions": len(unique_actions),
        "unique_actions": [list(action) for action in unique_actions],
        "per_card": per_card,
        "common_positive_constant_cards": common_positive_constant_cards,
        "varying_cards": varying_cards,
        "varying_card_count": len(varying_cards),
        "degenerate": degenerate_reason is not None,
        "degenerate_reason": degenerate_reason,
    }


__all__ = ["summarize_ballot_contrasts"]
