"""PointContext: one public-information point struct per decision.

Item 1 of docs/proposals/point-management-census.md (as repaired per the
Codex review of PR #95): a single immutable-at-boundary snapshot of every
point-relevant quantity a decision consumer (feed gate, endgame reserve
pricing, lead policy, encoder, telemetry) would otherwise recompute ad hoc:

- ``trick_points``: points already on the table in the OPEN trick;
- ``points_left_total`` / ``points_left_by_suit``: point cards still in
  circulation, total and per EFFECTIVE suit, via ``Memory.points_left``;
- ``attacker_points`` and ``bracket_distance``: points the attackers still
  need to reach each of the 40/80/120 scoring brackets (``Game.finish_round``
  semantics: <40, <80 and >=80(+40 per extra) decide the level change);
- ``effective_boss(cards, seats_to_act)``: is this holding provably unbeatable
  given public info, through the exact engine primitives ``Memory.is_boss``
  (singles), ``Memory.pair_is_boss`` (pairs) and ``Memory.ruff_risk`` over an
  explicit list of seats still to act.

Everything is derived from PUBLIC information plus ``seat``'s own private
information (its hand; its own burial when it is the banker) — exactly the
``Memory`` contract. No other hidden hand is read. Building a context NEVER
mutates the round; the boundary is a frozen dataclass, an immutable mapping
and a tuple, so a consumer cannot corrupt a shared context either.

This module deliberately changes no decision: nothing in production imports
it yet. Consumers arrive via the normal design -> review -> screen pipeline.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from ..engine.cards import TRUMP, total_points
from ..engine.round import Round
from .memory import Memory

POINT_CONTEXT_SCHEMA = "point-context-v1"

# Effective suits partition the whole deck under any Ordering: plain cards
# keep their own suit letter, every trump (trump suit, trump rank, jokers)
# lives under "T". With a suited trump the trump suit's letter therefore
# never occurs as an effective suit and its entry is always 0.
EFF_SUITS = ("C", "D", "H", "S", TRUMP)

# Attacker-point thresholds that change the round result (Game.finish_round):
# <40 banker +2, <80 banker +1, >=80 attackers take the deal, >=120 attackers
# +1 per extra 40. Distances are clamped at 0 once a bracket is reached.
BRACKETS = (40, 80, 120)


@dataclass(frozen=True)
class PointContext:
    """Immutable point snapshot for one (round, seat) decision.

    All fields are plain immutable data. ``effective_boss`` answers from
    boss/ruff tables PRECOMPUTED at build time through the exact engine
    ``Memory`` primitives; the Memory itself is discarded, so no caller can
    reach shared mutable state through a context (deep-immutability review
    requirement).
    """

    seat: int
    attacker_points: int
    trick_points: int
    points_left_total: int
    points_left_by_suit: Mapping[str, int]
    bracket_distance: tuple[int, int, int]
    boss_table: Mapping[str, bool] = field(compare=False, repr=False)
    pair_boss_table: Mapping[str, bool] = field(compare=False, repr=False)
    ruff_table: Mapping[tuple[str, frozenset], bool] = field(
        compare=False, repr=False)
    eff_suit_table: Mapping[str, str] = field(compare=False, repr=False)
    schema: str = POINT_CONTEXT_SCHEMA

    # ------------------------------------------------------------------ boss
    def effective_boss(self, cards: Sequence[str],
                       seats_to_act: Sequence[int]) -> bool:
        """True iff ``cards`` is provably unbeatable from public info.

        Exact semantics (the P1 census predicate):
        - a SINGLE card is counted boss via ``Memory.is_boss`` (no unseen
          card of its effective suit outranks it; ties lose to the earlier
          play);
        - a PAIR (exactly two identical codes) is counted boss via
          ``Memory.pair_is_boss`` (only a higher unseen PAIR beats a pair);
        - every other shape — tractors, throws, two different codes —
          conservatively returns False, even when provably unbeatable
          (documented limitation: the census "complex" class stays out of
          this predicate until a reviewed multi-component definition lands);
        - a counted boss is then vetoed by ``Memory.ruff_risk`` over the
          EXPLICIT ``seats_to_act`` list: any of those seats provably or
          plausibly void in the suit while trumps are unseen. Trump holdings
          have no ruff risk by definition. An empty ``seats_to_act`` means
          nobody can act after us, so counted boss stands.

        ``cards`` are evaluated as a public-info question; they need not be
        in ``seat``'s hand (the census asks about opponent shapes too).
        """
        cards = list(cards)
        seats = list(seats_to_act)
        if not cards:
            raise ValueError("effective_boss needs at least one card")
        if any(type(s) is not int or not 0 <= s < 4 for s in seats):
            raise ValueError(f"seats_to_act must be seats 0..3, got {seats!r}")
        for code in cards:
            if code not in self.eff_suit_table:
                raise ValueError(f"unknown card code {code!r}")
        if len(cards) == 1:
            counted = self.boss_table[cards[0]]
        elif len(cards) == 2 and cards[0] == cards[1]:
            counted = self.pair_boss_table[cards[0]]
        else:
            return False  # complex shapes: conservative False, documented
        if not counted:
            return False
        return not self.ruff_table[
            (self.eff_suit_table[cards[0]], frozenset(seats))]

    # ------------------------------------------------------------- serialize
    def to_dict(self) -> dict[str, object]:
        """Plain-data view of the public fields (no Memory), stable schema."""
        return {
            "schema": self.schema,
            "seat": self.seat,
            "attacker_points": self.attacker_points,
            "trick_points": self.trick_points,
            "points_left_total": self.points_left_total,
            "points_left_by_suit": dict(self.points_left_by_suit),
            "bracket_distance": {
                str(b): d for b, d in zip(BRACKETS, self.bracket_distance)
            },
        }

    def canonical_json(self) -> str:
        """Byte-stable serialization: sorted keys, no whitespace."""
        return json.dumps(self.to_dict(), sort_keys=True,
                          separators=(",", ":"))


def build_point_context(rnd: Round, seat: int) -> PointContext:
    """Build the context for ``seat`` from public info + seat's own hand.

    Valid whenever the round has an ``Ordering`` (post ``finalize_declare``:
    bury, play or round_end). Reads only ``rnd``'s public state plus
    ``rnd.hands[seat]`` (and ``rnd.buried`` when ``seat`` is the banker —
    that seat's own private information, per the Memory contract). Never
    mutates the round.
    """
    if rnd.ordering is None:
        raise ValueError("point context needs a finalized trump ordering")
    if type(seat) is not int or not 0 <= seat < 4:
        raise ValueError(f"seat must be an int 0..3, got {seat!r}")
    mem = Memory(rnd, seat)
    trick_points = 0
    if rnd.trick is not None and rnd.trick.plays:
        trick_points = total_points(
            c for tp in rnd.trick.plays for c in tp.cards)
    by_suit = {s: mem.points_left(s) for s in EFF_SUITS}
    total = mem.points_left()
    # Effective suits partition the deck, so the per-suit split must
    # reconcile exactly; a mismatch means the Ordering contract drifted.
    if sum(by_suit.values()) != total:
        raise AssertionError("points_left per-suit split does not reconcile")
    # Precompute every answer effective_boss can be asked, then drop the
    # Memory: the context carries only immutable derived tables.
    codes = sorted(set(rnd.deck))
    eff = {code: rnd.ordering.eff_suit(code) for code in codes}
    boss = {code: bool(mem.is_boss(code)) for code in codes}
    pair_boss = {code: bool(mem.pair_is_boss(code)) for code in codes}
    ruff = {}
    for suit_key in EFF_SUITS:
        for bits in range(16):
            seats_set = frozenset(i for i in range(4) if bits & (1 << i))
            ruff[(suit_key, seats_set)] = bool(
                mem.ruff_risk(suit_key, sorted(seats_set)))
    return PointContext(
        seat=seat,
        attacker_points=rnd.attacker_points,
        trick_points=trick_points,
        points_left_total=total,
        points_left_by_suit=MappingProxyType(by_suit),
        bracket_distance=tuple(
            max(0, b - rnd.attacker_points) for b in BRACKETS),
        boss_table=MappingProxyType(boss),
        pair_boss_table=MappingProxyType(pair_boss),
        ruff_table=MappingProxyType(ruff),
        eff_suit_table=MappingProxyType(eff),
    )
