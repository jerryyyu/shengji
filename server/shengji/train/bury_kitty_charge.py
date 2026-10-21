"""The OPTIONAL kitty charge of the wide value-only bury (``SHENGJI_PV_BURY_KITTY_CHARGE``,
bury-name token ``bkc`` after ``bwv``/``bwv2``).  OFF BY DEFAULT.

When the attackers (the non-banker team) win the last trick they add the kitty's
points times ``2 x`` the last lead's card count (`engine.round`, the house rule)
to their score.  The served value head (encoder v2) encodes the banker's burial
as unseen cards (``Memory(own_kitty=False)``): a buried point card looks to it
like a point card an opponent may hold, so the value cannot tell a candidate
kitty's multiplied exposure from points still in play.

With the flag on, the wide chooser (`bury_wide_value.decide_wide_value_bury`)
subtracts from every candidate's value mean that kitty's expected bonus in the
value head's units (signed levels for the banker's team):

    charge = total_points(kitty) x P_ATTACKERS_LAST x MULTIPLIER x LEVELS_PER_POINT

and picks the argmax of the charged means (lowest index on a tie).  The three
factors are constants measured on release-46 self-play (S53 census:
``P_ATTACKERS_LAST`` is the attackers' last-trick rate over 600 replayed rounds,
``MULTIPLIER`` the mean multiplier when they took it, ``LEVELS_PER_POINT`` the
level-utility bracket width of `teacher_v1.attacker_level_utility`).  Their
product, ``PER_POINT`` (0.0285 levels per kitty point), agrees with the census's
direct realized cost, 0.0296 levels per buried point.  The bury runs no rollout,
so the last-trick probability cannot come from the bury's own evaluations; a
per-hand estimate is a later refinement, not this rule.

Record: the ``cwv-bury-policy-v1`` record keeps ``model_means`` (uncharged) and
gains ``kitty_charge``: ``per_point``, ``charges`` and ``charged_means``
(aligned with ``candidates``), ``uncharged_index`` (the argmax without the
charge) and ``changed``.  ``picked_index`` and ``wide_value.chosen_index`` are
the charged argmax.

Off (the default) nothing here is called: the chooser checks the bot's
``bury_kitty_charge`` (class default False) and its record, name and decisions
are release 46's.
"""

from __future__ import annotations

import numpy as np

from ..engine.cards import total_points

#: the bury-name token (``...-bury-<arm>-bwv-bkc-<12 hex>``)
TOKEN = "bkc"
#: the key the decision record carries the charge's telemetry under
RECORD_KEY = "kitty_charge"
#: the attackers' last-trick rate, release-46 self-play (S53, 230 of 600 rounds)
P_ATTACKERS_LAST = 0.38
#: the mean kitty multiplier (2 x last lead size) when the attackers took the last trick (S53)
MULTIPLIER = 3.0
#: levels per attacker point: the 40-point bracket of `teacher_v1.attacker_level_utility`
LEVELS_PER_POINT = 1.0 / 40.0
#: the charge per kitty point, in signed levels
PER_POINT = P_ATTACKERS_LAST * MULTIPLIER * LEVELS_PER_POINT


def identity() -> dict:
    """The rule inside the ``cwv-bury-recipe-v1`` digest: its factors."""
    return {"p_attackers_last": P_ATTACKERS_LAST, "multiplier": MULTIPLIER,
            "levels_per_point": LEVELS_PER_POINT}


def kitty_charges(candidates) -> np.ndarray:
    """Each candidate kitty's expected bonus cost in signed levels."""
    return np.array([total_points(candidate) * PER_POINT for candidate in candidates],
                    dtype=np.float64)


def charged_choice(candidates, means) -> tuple[int, dict]:
    """The argmax of ``means`` less each kitty's charge (lowest index on a tie)
    and the record's ``kitty_charge``."""
    means = np.asarray(means, dtype=np.float64)
    charges = kitty_charges(candidates)
    if charges.shape != means.shape:
        raise ValueError("kitty charges and value means are misaligned")
    charged = means - charges
    picked = min(range(len(candidates)), key=lambda i: (-float(charged[i]), i))
    uncharged = min(range(len(candidates)), key=lambda i: (-float(means[i]), i))
    return picked, {"per_point": PER_POINT, "charges": charges.tolist(),
                    "charged_means": charged.tolist(), "uncharged_index": int(uncharged),
                    "changed": picked != uncharged}


__all__ = ["TOKEN", "RECORD_KEY", "P_ATTACKERS_LAST", "MULTIPLIER", "LEVELS_PER_POINT",
           "PER_POINT", "identity", "kitty_charges", "charged_choice"]
