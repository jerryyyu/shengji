"""Encoder v7: who acts next, seat-relative to the observer.

At a trick boundary the v1 and v2 columns cannot say who leads the next trick.
The trick that just finished is in the played-by planes, but nothing marks its
winner: the v2 trick columns describe the trick IN PROGRESS, and at a boundary
that trick is empty, so ``encode_versions.trick_state`` returns ``(None, None,
0)`` and those columns are all zero.  Two boundary states that differ only in
the next leader therefore encode to identical bytes.  The served search scores
exactly such states (every leaf is a finished trick), and who leads next moves
the value of the rest of the round.

Layout (4 columns, appended to the v2 vector; every earlier byte untouched):

* ``next_actor:<rel>``  one-hot of ``(rnd.turn - seat) % 4`` while the round is
                        in the play phase: rel 0 is the observer, 2 its
                        partner, 1 and 3 the opponents.  All zero once the
                        round has ended (nobody acts).

The current trick's winner so far is not repeated here: mid-trick it is v2's
``winner_rel`` block, and at a boundary the finished trick's winner IS the next
actor.  Mid-trick the next actor is also implied by the v2 trick position, so
the block adds information only at boundaries, which is where it is missing.

Every input is public: the turn is shown to every player at the table.
"""
from __future__ import annotations

from ..engine.round import Round

NEXT_ACTOR_COLUMNS: tuple[str, ...] = tuple(f"next_actor:{rel}" for rel in range(4))
N_NEXT_ACTOR_COLUMNS = len(NEXT_ACTOR_COLUMNS)   # = 4


def next_actor_rel(rnd: Round, seat: int) -> int | None:
    """``(turn - seat) % 4`` for a round in the play phase, else None."""
    turn = rnd.turn
    if rnd.phase != "play" or isinstance(turn, bool) or not isinstance(turn, int) \
            or not 0 <= turn < 4:
        return None
    return (turn - seat) % 4


def next_actor_columns(rnd: Round, seat: int) -> list[float]:
    """The 4 columns encoder v7 appends to the v2 vector."""
    columns = [0.0] * N_NEXT_ACTOR_COLUMNS
    rel = next_actor_rel(rnd, seat)
    if rel is not None:
        columns[rel] = 1.0
    return columns


__all__ = ["NEXT_ACTOR_COLUMNS", "N_NEXT_ACTOR_COLUMNS", "next_actor_columns", "next_actor_rel"]
