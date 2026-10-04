"""Hand-conditioned ballot coverage; no value, gradient, or strength claims."""
from collections import Counter

from .ballot_contrast import _canonical_action, _require_sequence


def summarize_opportunities(hand, legal_actions, ballot, *, legal_complete):
    """Compare offered card-use levels against a caller-verified legal pool.

    Legality is supplied by the public engine, not established by this helper.
    Incomplete legal enumeration refuses rather than producing a denominator.
    Duplicate/reordered actions count once. Card counts alone do not describe
    all strategic contrasts or imply that a missing contrast should be added.
    Covered means both count levels occur somewhere, not that two actions
    differ only in this card or constitute a controlled strategic comparison.
    """
    if legal_complete is not True:
        raise ValueError("complete legal enumeration required")
    held = Counter(_canonical_action(hand, -1))
    def actions(rows):
        result = set()
        for i, row in enumerate(_require_sequence(rows, "actions")):
            action = _canonical_action(row, i)
            if Counter(action) - held:
                raise ValueError("action exceeds actor hand")
            result.add(action)
        return result
    legal, offered = actions(legal_actions), actions(ballot)
    if not legal:
        raise ValueError("nonempty legal pool required")
    if not offered <= legal:
        raise ValueError("ballot action absent from legal pool")
    legal_counts = [Counter(a) for a in legal]
    offered_counts = [Counter(a) for a in offered]
    cards = {}
    for card, copies in sorted(held.items()):
        available = sorted({c[card] for c in legal_counts})
        admitted = sorted({c[card] for c in offered_counts})
        contrasts = []
        for low in available:
            for high in available:
                if low >= high:
                    continue
                contrasts.append({"spent": [low, high],
                                  "covered": low in admitted and high in admitted})
        cards[card] = {"held": copies, "legal_spent": available,
                       "ballot_spent": admitted, "contrasts": contrasts}
    pairs = [v for v in cards.values() if v["held"] == 2]
    def pair_count(low, high, covered=False):
        return sum(any(c["spent"] == [low, high] and
                       (not covered or c["covered"]) for c in p["contrasts"])
                   for p in pairs)
    return {"schema": "hand-conditioned-ballot-opportunity-v1",
            "legal_unique_actions": len(legal), "ballot_unique_actions": len(offered),
            "cards": cards,
            "pair_opportunities": {
                f"{lo}_vs_{hi}": {"available_cards": pair_count(lo, hi),
                                   "covered_cards": pair_count(lo, hi, True)}
                for lo, hi in ((0, 1), (0, 2), (1, 2))},
            "strategic_quality_assessed": False}
