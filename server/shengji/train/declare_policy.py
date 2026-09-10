"""Pure, actor-only declaration views and bounded declaration arms.

This module is deliberately not registered as a production bot.  A view owns
the exact legal options exposed at capture time, which lets research callers
compare declaration choices without handing a policy the deck, kitty, or
other players' private hands.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..engine.cards import Ordering, TRUMP, card_rank, card_suit, is_joker
from ..engine.combos import find_tractor_runs, pair_count

DECLARATION_ARMS = ("baseline", "pair-eager", "partner-wait", "structure-tie")

@dataclass(frozen=True)
class DeclareView:
    """Immutable actor-local declaration observation."""

    seat: int
    trump_rank: str
    own_hand: tuple[str, ...]
    options: tuple[tuple[str, ...], ...]
    phase: str
    final: bool
    banker: int | None
    declaration_seat: int | None


def capture_declare_view(rnd, seat: int, final: bool = False) -> DeclareView:
    """Capture only the actor's hand, legal options, and public metadata.

    In particular, this function intentionally does not inspect ``deck``,
    ``kitty``, or any hand other than ``seat``'s.  ``declare_options`` is the
    engine's actor-scoped legal-option API and is called exactly once.  The
    explicit ``final`` flag is operative: ``phase='declare', final=False``
    (the last-dealt-card path) intentionally uses the during-deal threshold.
    """
    own_hand = tuple(rnd.hands[seat])
    options = tuple(tuple(option) for option in rnd.declare_options(seat))
    declaration = rnd.declaration
    declaration_seat = None if declaration is None else declaration["seat"]
    return DeclareView(
        seat=seat,
        trump_rank=rnd.trump_rank,
        own_hand=own_hand,
        options=options,
        phase=rnd.phase,
        final=final,
        banker=rnd.banker,
        declaration_seat=declaration_seat,
    )


def _score(view: DeclareView, option: tuple[str, ...]) -> int:
    """Return the unchanged HeuristicBot/SmartBot declaration score."""
    code = option[0]
    hand = view.own_hand
    if is_joker(code):
        n_rank = sum(1 for card in hand if card_rank(card) == view.trump_rank)
        return 14 + n_rank if n_rank >= 3 else 0
    suit = code[0]
    n_trump = sum(
        1 for card in hand
        if is_joker(card) or card_rank(card) == view.trump_rank or card[0] == suit
    )
    return n_trump + (2 if len(option) == 2 else 0)


def _baseline(view: DeclareView) -> tuple[str, ...] | None:
    """Reproduce SmartBot with ``DECLARE_TUNE=False`` byte-for-action."""
    best: tuple[str, ...] | None = None
    best_score = 0
    for option in view.options:
        score = _score(view, option)
        # Strictly greater preserves the engine's stable option ordering on
        # ties, just as HeuristicBot.decide_declare does.
        if score > best_score:
            best, best_score = option, score
    threshold = 6 if view.final else 8
    return best if best_score >= threshold else None


def _structure(view: DeclareView, option: tuple[str, ...]) -> tuple[int, int]:
    """Return (longest tractor in pairs, physical trump pair count)."""
    ordering = Ordering(card_suit(option[0]), view.trump_rank)
    trumps = [card for card in view.own_hand
              if ordering.eff_suit(card) == TRUMP]
    pairs = pair_count(trumps)
    longest = next((k for k in range(pairs, 1, -1)
                    if find_tractor_runs(trumps, ordering, k)), 0)
    return longest, pairs


def choose_declaration(view: DeclareView, arm: str = "baseline") -> list[str] | None:
    """Choose one captured legal declaration under a named research arm.

    ``pair-eager`` only relaxes the during-deal threshold for suited pairs of
    the current rank.  It never changes an accepted baseline action, final
    decisions, or no-trump decisions.

    ``partner-wait`` suppresses an otherwise accepted baseline overcall of
    the partner during dealing. Final calls, self/opponent overcalls and
    choices without an existing declaration retain the baseline. This is a
    separate timing/context hypothesis, never combined with pair-eager.

    ``structure-tie`` only reorders same-strength, same-score suited choices
    using actor-visible trump structure. It preserves baseline passes, NT,
    and the engine's option order when structure ties.
    """
    if arm not in DECLARATION_ARMS:
        raise ValueError(f"unknown declaration arm {arm!r}")

    baseline = _baseline(view)
    if arm == "partner-wait":
        if not view.final and view.declaration_seat == (view.seat + 2) % 4:
            return None
        return None if baseline is None else list(baseline)
    if arm == "structure-tie":
        if baseline is None or is_joker(baseline[0]):
            return None if baseline is None else list(baseline)
        baseline_score = _score(view, baseline)
        best = baseline
        best_structure = _structure(view, baseline)
        for option in view.options:
            if (not option or is_joker(option[0])
                    or card_rank(option[0]) != view.trump_rank
                    or len(option) != len(baseline)
                    or _score(view, option) != baseline_score
                    or any(is_joker(card)
                           or card_rank(card) != view.trump_rank
                           or card_suit(card) != card_suit(option[0])
                           for card in option)):
                continue
            structure = _structure(view, option)
            if structure > best_structure:
                best, best_structure = option, structure
        return list(best)
    if baseline is not None or arm == "baseline" or view.final:
        return None if baseline is None else list(baseline)

    # A pair-eager candidate must itself be a legal captured option.  Restrict
    # the relaxation to a pair of suited trump-rank cards; jokers are NT and
    # singleton rank cards retain the baseline threshold.
    best: tuple[str, ...] | None = None
    best_score = 0
    for option in view.options:
        if (len(option) != 2 or option[0] != option[1]
                or is_joker(option[0])
                or card_rank(option[0]) != view.trump_rank):
            continue
        score = _score(view, option)
        if score >= 6 and score > best_score:
            best, best_score = option, score
    return None if best is None else list(best)
