"""Soft level-head targets from the search's own mean (issue #340).

The realised outcome is one draw with ~14 points of per-world spread; the
search's refined mean for the played action averages 30 to 330 worlds.  Its
scale is exactly ``40 * U + 0.2 * p`` (``mcbot._score``: level utility ``U``
in half-integers times 40, plus a fifth of the attacker points), signed for the
acting team.  Given the realised attacker points ``p`` the level utility is
recovered as ``U = (sign * mean - 0.2 p) / 40``; the points term is worth at
most one bracket and carries a fifth of the old target's noise.  ``U`` is
generally fractional, so the target is a two-point distribution over the
neighbouring half-integer classes, with the fractional part as the weight.
Rows without a usable mean keep their one-hot realised target.
"""
from __future__ import annotations

import torch

from ..rl.value_afterstate import (MAX_SIGNED_LEVEL_UTILITY, MIN_SIGNED_LEVEL_UTILITY,
                                   OUTCOME_CLASSES)

TARGET_KINDS = ("realised", "search-mean")


def _category(signed: torch.Tensor) -> torch.Tensor:
    """``value_afterstate.signed_level_category`` for half-integer ``signed``, vectorised."""
    neg = (signed - MIN_SIGNED_LEVEL_UTILITY)
    pos = 102 + (signed - 0.5)
    return torch.where(signed < 0, neg, pos).round().to(torch.int64)


def soft_targets(mean: torch.Tensor, attacker_points: torch.Tensor,
                 role_attacker: torch.Tensor, realised: torch.Tensor
                 ) -> tuple[torch.Tensor, torch.Tensor]:
    """``(probs [b, 204], used [b])``: two-point targets where a mean exists and
    maps inside the support, the one-hot realised target elsewhere."""
    b = realised.shape[0]
    probs = torch.zeros((b, OUTCOME_CLASSES), dtype=torch.float32, device=realised.device)
    probs[torch.arange(b, device=realised.device), realised] = 1.0
    sign = torch.where(role_attacker, 1.0, -1.0).to(torch.float32)
    utility = (sign * mean.to(torch.float32) - 0.2 * attacker_points.to(torch.float32)) / 40.0
    signed = sign * utility
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
