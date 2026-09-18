"""Encoder v5: the banker's OWN buried kitty (Jerry, 2026-09-16).

Every encoder version so far reshuffled information the net already had: v2
restated the trick in progress, the points regime and the hand's shape; v4 fed
the memory's opponent-pair inferences (and moved nothing in play).  This block
is different in kind -- it adds a fact the observation has never carried.

``encode.encode_obs`` builds its ``unseen`` plane from ``Memory(rnd, seat,
own_kitty=False)``.  That is a deliberate v1-compatibility choice, documented
in ``encode.py``: v1 predates Memory's private-kitty feature and its stored
bytes must not move.  The consequence is that the BANKER's observation still
lists the eight cards it buried itself as cards an opponent might hold -- on a
fresh burial that is eight of about eighty unseen cards, a tenth of the pool,
wrong on every banker decision for the rest of the round.  Production's world
sampler does not make that mistake (it builds ``Memory(..., own_kitty=True)``),
so the search draws worlds that exclude the burial and then scores them with a
net whose own input contradicts them.

Layout (56 columns, appended; v1/v2 bytes untouched):

* ``kitty_known``      1.0 when the acting seat is the banker AND the burial
                       exists; 0.0 otherwise.
* ``kitty:<card>``     the burial as a 54-wide count plane in ``encode``'s
                       canonical card order, on the same 0/.5/1 scale the other
                       card planes use.  All zero when not known.
* ``kitty_points``     the burial's card points scaled by 100 (the kitty's
                       points decide the round when the attackers take the last
                       trick, multiplied by the winning play's width).  0.0 when
                       not known.

Two properties this block is written to keep, and the tests pin both:

* **Secrecy.** The columns are zero for every seat that is not the banker, and
  zero for the banker before the burial exists.  No other seat's hand is read,
  and nothing here depends on a determinized world.
* **Append-only.** A consumer that wants the corrected unseen pool subtracts
  this plane from the v1 unseen plane, a linear operation on two inputs.  The
  net is never asked to infer the burial, and no earlier byte changes, so a v2
  checkpoint's archived bytes and identity digests stand.
"""
from __future__ import annotations

from ..engine.cards import total_points
from ..engine.round import Round
from .encode import CARD_INDEX, N_CARDS, _counts

#: the burial's points are at most the 100 in one deck's worth of 5/10/K, and in
#: practice far less; the scale only has to keep the column O(1).
KITTY_POINTS_SCALE = 100.0

BANKER_KITTY_COLUMNS: tuple[str, ...] = (
    "kitty_known",
    *[f"kitty:{code}" for code in CARD_INDEX],
    "kitty_points",
)
N_BANKER_KITTY_COLUMNS = len(BANKER_KITTY_COLUMNS)   # 1 + 54 + 1 = 56


def banker_kitty_known(rnd: Round, seat: int) -> bool:
    """Is ``seat`` the banker of a round whose burial has happened?

    The same condition ``ai.memory.Memory`` uses for ``own_kitty_known``, so the
    encoder and the world sampler agree about when the burial is knowable.
    """
    return bool(rnd.banker == seat and rnd.buried)


def banker_kitty_columns(rnd: Round, seat: int) -> list[float]:
    """The 56 columns encoder v5 appends to the v2 vector."""
    if not banker_kitty_known(rnd, seat):
        columns = [0.0] * N_BANKER_KITTY_COLUMNS
        assert len(columns) == N_BANKER_KITTY_COLUMNS
        return columns
    buried = list(rnd.buried)
    columns = [1.0, *_counts(buried),
               min(total_points(buried), KITTY_POINTS_SCALE) / KITTY_POINTS_SCALE]
    assert len(columns) == N_BANKER_KITTY_COLUMNS == 1 + N_CARDS + 1
    return columns


__all__ = ["BANKER_KITTY_COLUMNS", "KITTY_POINTS_SCALE", "N_BANKER_KITTY_COLUMNS",
           "banker_kitty_columns", "banker_kitty_known"]
