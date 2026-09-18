"""Encoder v6: the banker's own burial removed from the unseen pool ("the no-regrets fix").

Jerry 2026-09-17, deciding the v5 decomposition on #477: try the "exclude the kitty cards when
banker" correction SEPARATELY from v5's other columns.  This is that arm.

WHAT IT IS.  ``encode.encode_obs`` builds the unseen plane from ``Memory(..., own_kitty=False)``
-- a deliberate v1-compatibility choice -- so the banker's observation counts the eight cards it
buried itself as cards an opponent might hold.  Production's world sampler uses
``own_kitty=True``, so the search draws worlds that exclude the burial and then scores them with
a net whose input contradicts them.  v6 is the v2 vector with that plane CORRECTED, plus a single
``kitty_known`` flag so the correction is legible to the net rather than silent.

WHY IT IS A VERSION AND NOT A TRAINING FLAG.  Measured 2026-09-18
(``~/shengji-archive/2026-09-13/readouts/kitty-serve-mismatch-probe.txt``): checkpoint dispatch is
BY WIDTH.  A corrected net emitted at v2's 560 columns returns ``encoder_version_for -> 2``, the
same answer an ordinary v2 net gives, with no field distinguishing them -- so it would be SERVED
the uncorrected plane, differing in 8 of 54 unseen columns on every banker decision, with no width
mismatch and no version disagreement to catch it.  Hence 561: a width nothing else claims, so the
mismatch is impossible rather than merely unlikely.

WHY IT BREAKS THE APPEND-ONLY RULE, DELIBERATELY.  Every other version satisfies
``encode_obs(version=n)[:531] == encode_obs(version=1)``.  v6 CANNOT: the unseen plane lives at
columns 432:486, inside the v1 block, and correcting it is the entire point.  That rule is
load-bearing, not decorative -- ``value_afterstate_v2.widen_to`` reconstructs any version >= 2 as
"v1 tensor + appended columns", which would silently hand back an UNCORRECTED v6.  So v6 must be
refused by that path (see ``rl.value_afterstate_v2``), and this module never edits ``encode.py``:
v1/v2/v4/v5 bytes are untouched and no archived checkpoint is orphaned.

TRAINING READS IT FROM A v5 EXTRACT.  ``from_v5`` derives the v6 vector from a v5 one by
subtracting the kitty plane, so one extract feeds both this arm and the v5 arm and they differ
only by an input transform over identical rows.  ``test_v6_from_v5_equals_v6_encoded_directly``
pins that the derived vector and the directly encoded one agree -- which IS the train/serve
agreement the probe found missing.
"""
from __future__ import annotations

from ..ai.memory import Memory
from ..engine.round import Round
from .encode import N_CARDS, _counts
from .encode_banker_kitty import banker_kitty_known

#: the unseen plane inside the v1 block: hand, four seat-relative histories, three trick planes,
#: then unseen.  Correcting these 54 columns is what v6 exists to do.
UNSEEN = slice(N_CARDS * 8, N_CARDS * 9)

CORRECTED_COLUMNS: tuple[str, ...] = ("kitty_known",)
N_CORRECTED_COLUMNS = len(CORRECTED_COLUMNS)


def corrected_unseen_plane(rnd: Round, seat: int) -> list[float]:
    """The unseen plane ``seat`` SHOULD see: the pool the world sampler actually draws from."""
    return _counts(Memory(rnd, seat, own_kitty=True).unseen.elements())


def correct_in_place(obs: list[float], kitty_plane: list[float]) -> list[float]:
    """Subtract ``kitty_plane`` from ``obs``'s unseen plane, in place, and return ``obs``."""
    plane = obs[UNSEEN]
    if len(kitty_plane) != N_CARDS:
        raise ValueError(f"kitty plane must be {N_CARDS} columns, got {len(kitty_plane)}")
    corrected = [p - k for p, k in zip(plane, kitty_plane)]
    if min(corrected) < -1e-9:
        raise ValueError("a burial card was not in the unseen plane: the offsets are wrong")
    obs[UNSEEN] = corrected
    return obs


def banker_kitty_corrected_columns(rnd: Round, seat: int) -> list[float]:
    """The single column v6 appends after correcting the plane."""
    return [1.0 if banker_kitty_known(rnd, seat) else 0.0]
