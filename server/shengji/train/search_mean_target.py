"""Soft level-head targets from the search's own mean (issue #340).

What the sidecar mean IS
------------------------
``preference.means[played_index]`` is the search's refined value of the
played action, signed for the acting team, in the units of ``mcbot._score``
of the PRODUCER that generated the record.  Every corpus this project has
generated (run A through run L) ran with ``LEVEL_OBJECTIVE = False``, where
``_score(p) = p``: the mean is the search's expected ATTACKER POINTS over its
rollouts (30 to 330 worlds; the report fold refines the played action's
difference to the incumbent, not its absolute mean).  With
``LEVEL_OBJECTIVE = True`` the mean would be ``E[40 * clip(bracket) + 0.2 p]``
which has NO exact inverse to a level utility (the bracket is clipped at 3
and the expectation does not commute with the step function), so the sidecar
records the producer's flag and this module refuses such rows.

What the target IS (a named surrogate, not the expected level utility)
------------------------------------------------------------------
The realised target is ``attacker_level_utility(p_realised)``, a step function
of ONE draw of the attacker points.  This module trains instead on the
**ramp utility of the search's expected points**::

    ramp(p) = p / 40 - 1.5     if p >= 80
            = p / 40 - 2.5     if 0 < p < 80
            = -3.5             if p == 0

``ramp`` agrees with ``attacker_level_utility`` at every bracket's lower
edge (0 -> -3.5, 40 -> -1.5, 80 -> 0.5, 120 -> 1.5, 160 -> 2.5, ...), climbs
one bracket per 40 points inside a bracket, and keeps the takeover cliff at
80 (79 -> -0.525, 80 -> 0.5).  It is applied to the
search's EXPECTED points, so it is ``ramp(E[p])``, not ``E[utility(p)]``: an
action whose rollouts straddle 80 gets a target between the brackets rather
than the mixture.  That is the surrogate's known bias; what it buys is the
search's 30-330-world average instead of one realised draw.  Because ``ramp``
is generally fractional, the target is a two-point distribution over the
neighbouring half-integer classes of the head's support, with the fractional
part as the weight.  Rows without a usable mean keep their one-hot realised
target; both live in the same signed-level space.
"""
from __future__ import annotations

import torch

from ..rl.value_afterstate import (MAX_SIGNED_LEVEL_UTILITY, MIN_SIGNED_LEVEL_UTILITY,
                                   OUTCOME_CLASSES)

TARGET_KINDS = ("realised", "search-mean")
ESTIMAND = ("ramp utility of the search's expected attacker points, ramp(E[p]); "
            "a surrogate for, not an estimate of, the expected level utility")
#: the only producer objective whose search mean is an expected-points mean
PRODUCER_LEVEL_OBJECTIVE = False


def ramp_utility(points: torch.Tensor) -> torch.Tensor:
    """Continuous ramp agreeing with ``teacher_v1.attacker_level_utility`` at
    each bracket's lower edge (see the module docstring)."""
    p = points.to(torch.float32)
    above = p / 40.0 - 1.5
    below = p / 40.0 - 2.5
    out = torch.where(p >= 80.0, above, below)
    return torch.where(p <= 0.0, torch.full_like(out, -3.5), out)


def _category(signed: torch.Tensor) -> torch.Tensor:
    """``value_afterstate.signed_level_category`` for half-integer ``signed``, vectorised."""
    neg = (signed - MIN_SIGNED_LEVEL_UTILITY)
    pos = 102 + (signed - 0.5)
    return torch.where(signed < 0, neg, pos).round().to(torch.int64)


def soft_targets(mean: torch.Tensor, role_attacker: torch.Tensor, realised: torch.Tensor
                 ) -> tuple[torch.Tensor, torch.Tensor]:
    """``(probs [b, 204], used [b])``: two-point ramp targets where a mean
    exists and maps inside the support, the one-hot realised target elsewhere.

    ``mean`` is the acting team's signed expected attacker points (the
    producer's ``LEVEL_OBJECTIVE = False`` score); ``role_attacker`` restores
    the attacker perspective before the ramp and re-signs the utility."""
    b = realised.shape[0]
    probs = torch.zeros((b, OUTCOME_CLASSES), dtype=torch.float32, device=realised.device)
    probs[torch.arange(b, device=realised.device), realised] = 1.0
    sign = torch.where(role_attacker, 1.0, -1.0).to(torch.float32)
    expected_points = sign * mean.to(torch.float32)
    signed = sign * ramp_utility(expected_points)
    lo = torch.floor(signed - 0.5) + 0.5
    hi = lo + 1.0
    frac = (signed - lo).clamp(0.0, 1.0)
    used = (torch.isfinite(mean) & (lo >= MIN_SIGNED_LEVEL_UTILITY)
            & (hi <= MAX_SIGNED_LEVEL_UTILITY))
    if bool(used.any()):
        idx = torch.nonzero(used, as_tuple=False).squeeze(1)
        lo_c = _category(lo[idx]).clamp(0, OUTCOME_CLASSES - 1)
        hi_c = _category(hi[idx]).clamp(0, OUTCOME_CLASSES - 1)
        probs[idx] = 0.0
        probs[idx, lo_c] += 1.0 - frac[idx]
        probs[idx, hi_c] += frac[idx]
    return probs, used
