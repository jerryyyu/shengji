"""Parity gate for the heuristic lead tractor-scan prefilter.

The optimized implementation skips tractor lengths that cannot fit in the
number of physical pairs held in a suit.  These tests compare it against the
literal pre-optimization scan (always ask for lengths 5 through 2), so the
performance shortcut cannot silently change rollout-policy actions.
"""

from __future__ import annotations

import random

import pytest

from shengji.ai import heuristic
from shengji.ai.heuristic import HeuristicBot
from shengji.engine.cards import Ordering, make_deck
from shengji.engine.round import Round


CONFIGS = (
    ("H", "7"),
    ("S", "2"),
    ("D", "A"),
    (None, "7"),
    (None, "A"),
    ("C", "10"),
)


def _round(hand: list[str], trump_suit: str | None, trump_rank: str) -> Round:
    rnd = Round(trump_rank, 0, random.Random(0))
    rnd.ordering = Ordering(trump_suit, trump_rank)
    rnd.hands[0] = list(hand)
    return rnd


def _lead_before_prefilter(
    monkeypatch: pytest.MonkeyPatch,
    hand: list[str],
    trump_suit: str | None,
    trump_rank: str,
) -> list[str]:
    """Run the old 5..2 scan through the current policy implementation.

    ``pair_count`` is used by ``_lead`` only for the new loop bounds.  Making
    it report five therefore reconstructs the old scan without copying the
    rest of the policy into the test (where the two copies could drift).
    """
    with monkeypatch.context() as patch:
        patch.setattr(heuristic, "pair_count", lambda _cards: 5)
        return HeuristicBot()._lead(
            _round(hand, trump_suit, trump_rank), 0)


def _assert_old_new_equal(
    monkeypatch: pytest.MonkeyPatch,
    hand: list[str],
    trump_suit: str | None,
    trump_rank: str,
) -> list[str]:
    old = _lead_before_prefilter(
        monkeypatch, hand, trump_suit, trump_rank)
    new = HeuristicBot()._lead(
        _round(hand, trump_suit, trump_rank), 0)
    assert new == old, (hand, trump_suit, trump_rank, old, new)
    return new


@pytest.mark.parametrize(
    ("trump_suit", "trump_rank", "hand", "expected"),
    (
        # Exact lower boundary: a two-pair tractor must not be skipped.
        ("H", "7",
         ["S3", "S3", "S4", "S4", "C2"],
         ["S3", "S3", "S4", "S4"]),
        # Exact upper boundary: five pairs still ask for and retain k=5.
        ("H", "7",
         [card for rank in ("3", "4", "5", "6", "8")
          for card in (f"S{rank}", f"S{rank}")] + ["C2"],
         [card for rank in ("3", "4", "5", "6", "8")
          for card in (f"S{rank}", f"S{rank}")]),
        # No-trump puts every level card in the trump group at one tied level;
        # those pairs are not a run and must not displace the plain tractor.
        (None, "7",
         ["S3", "S3", "S4", "S4",
          "S7", "S7", "H7", "H7", "LJ", "C2"],
         ["S3", "S3", "S4", "S4"]),
        # Suited trump also has multiple physical codes tied at the off-suit
        # level.  Pair-count bounds may reduce calls, never the alternatives.
        ("H", "7",
         ["C7", "C7", "D7", "D7", "H7", "H7", "LJ", "LJ", "C2"],
         ["D7", "D7", "H7", "H7", "LJ", "LJ"]),
    ),
)
def test_lead_prefilter_exact_boundary_and_tied_level_parity(
    monkeypatch: pytest.MonkeyPatch,
    trump_suit: str | None,
    trump_rank: str,
    hand: list[str],
    expected: list[str],
) -> None:
    assert _assert_old_new_equal(
        monkeypatch, hand, trump_suit, trump_rank) == expected


def test_lead_prefilter_random_old_new_parity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rng = random.Random(20260812)
    deck = make_deck()
    tractors = 0
    no_trump = 0
    for index in range(2_000):
        trump_suit, trump_rank = CONFIGS[index % len(CONFIGS)]
        hand = rng.sample(deck, rng.randint(1, 33))
        lead = _assert_old_new_equal(
            monkeypatch, hand, trump_suit, trump_rank)
        tractors += len(lead) >= 4
        no_trump += trump_suit is None

    # Prove that the random differential exercised more than ordinary
    # singleton fallbacks and included a substantial no-trump population.
    assert tractors >= 50
    assert no_trump >= 600


def test_lead_prefilter_never_asks_for_an_impossible_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], int]] = []
    real_find = heuristic.find_tractor_runs

    def recording_find(cards: list[str], ordering: Ordering, k: int):
        calls.append((list(cards), k))
        return real_find(cards, ordering, k)

    monkeypatch.setattr(heuristic, "find_tractor_runs", recording_find)
    hand = [
        "S3", "S3", "S4", "S4", "S5", "S5",
        "H3", "H3", "C4", "D5", "LJ",
    ]
    HeuristicBot()._lead(_round(hand, "D", "7"), 0)

    assert calls
    assert all(k <= heuristic.pair_count(cards) for cards, k in calls)
    assert all(heuristic.pair_count(cards) >= 2 for cards, _ in calls)
