"""DEV-only two-trick lookahead policy for bounded paired duels.

This module is deliberately not registered as a production bot.  It composes
the existing PV tree bot and changes only the root selection in positions that
are outside the exact endgame.  The baseline PV decision is complete before
the optional stage starts; any budget expiry, malformed matrix, or exception
returns that baseline decision unchanged.
"""

from __future__ import annotations

import math
import time

import numpy as np

from shengji.train.policy_value_search import PolicyValueBot
from shengji.train.pv_search_policy import PVSearchBuryBot, PVSearchBot
from shengji.train.pv_tree_search import (PVTreeMixin, PVTreeSearchBuryBot,
                                           PVTreeSearchBot)
from shengji.train.pv_tree_config import PVTreeConfig


class HybridMultiTrickError(RuntimeError):
    """Raised internally when the optional matrix cannot be published."""


class HybridMultiTrickMixin:
    """Add a bounded, all-world two-trick correction to the PV selection.

    The flag is explicit and instance-local.  It is not part of the production
    registry or recipe format.  The exact-endgame path (all hands <= 7 cards)
    is intentionally untouched so a DEV duel can isolate earlier-trick value.
    """

    def __init__(self, *args, hybrid_multi_trick=False, **kwargs):
        if type(hybrid_multi_trick) is not bool:
            raise TypeError("hybrid_multi_trick must be a bool")
        self.hybrid_multi_trick = hybrid_multi_trick
        self.hybrid_decision_started = None
        self.hybrid_last_fields = None
        self._hybrid_tree_config = PVTreeConfig(sims=0)
        super().__init__(*args, **kwargs)

    @property
    def tree_config(self):
        """Private DEV tree mechanics; leave the serving recipe untouched."""
        return self._hybrid_tree_config

    def decide_play(self, rnd, seat):
        self.hybrid_decision_started = time.perf_counter()
        original_budget = self.serving_budget_seconds
        try:
            return super().decide_play(rnd, seat)
        finally:
            self.serving_budget_seconds = original_budget

    @staticmethod
    def _hybrid_fields():
        return {
            "hybrid_attempted": False,
            "hybrid_applied": False,
            "hybrid_changed": False,
            "hybrid_fallback": "",
            "hybrid_completed_tricks": 0,
            "hybrid_worlds": 0,
            "hybrid_actions": 0,
        }

    def _hybrid_tree_decide(self, rnd, seat, admitted, means, worlds, pv_winner,
                            fields, select_kwargs):
        hybrid = self._hybrid_fields()
        fields.update(hybrid)
        if not self.hybrid_multi_trick:
            fields["hybrid_fallback"] = "disabled"
            self.hybrid_last_fields = fields
            return pv_winner
        if max((len(hand) for hand in rnd.hands), default=0) <= 7:
            fields["hybrid_fallback"] = "exact_endgame"
            self.hybrid_last_fields = fields
            return pv_winner
        if worlds is None or not admitted:
            fields["hybrid_fallback"] = "empty_input"
            self.hybrid_last_fields = fields
            return pv_winner
        baseline = np.asarray(means, dtype=np.float64)
        if baseline.shape != (len(admitted),) or not np.isfinite(baseline).all():
            fields["hybrid_fallback"] = "invalid_baseline"
            self.hybrid_last_fields = fields
            return pv_winner
        v0 = getattr(self, "_tree_v0", None)
        if v0 is None or np.asarray(v0).shape != (len(worlds), len(admitted)):
            fields["hybrid_fallback"] = "missing_pv_matrix"
            self.hybrid_last_fields = fields
            return pv_winner
        v0 = np.asarray(v0, dtype=np.float64)
        if not np.isfinite(v0).all():
            fields["hybrid_fallback"] = "invalid_pv_matrix"
            self.hybrid_last_fields = fields
            return pv_winner

        fields["hybrid_attempted"] = True
        fields["hybrid_completed_tricks"] = 2
        fields["hybrid_worlds"] = len(worlds)
        fields["hybrid_actions"] = len(admitted)
        started = self.hybrid_decision_started or self._tree_started or time.perf_counter()
        budget = self.serving_budget_seconds
        total_budget = getattr(self, "hybrid_total_seconds", None)
        cutoff = None if budget is None else budget * 0.8
        if total_budget is not None:
            # The baseline selection is complete before the extra allowance
            # becomes visible to the outer PV finalization guard.
            self.serving_budget_seconds = total_budget
            cutoff = total_budget

        def gate():
            # Only the default mode reserves serving finalization headroom.
            if cutoff is not None and time.perf_counter() - started >= cutoff:
                raise HybridMultiTrickError("serving budget expired")

        try:
            gate()
            deep, stats = self._tree_lookahead(
                rnd, seat, admitted, worlds, gate,
                completed_tricks=2, exact_max_cards=0)
            gate()
            deep = np.asarray(deep, dtype=np.float64)
            if deep.shape != v0.shape or not np.isfinite(deep).all():
                raise HybridMultiTrickError("incomplete or non-finite lookahead")
            correction = deep - v0
            q = baseline + correction.mean(axis=0)
            if not np.isfinite(q).all():
                raise HybridMultiTrickError("non-finite hybrid means")
            # Invoke the serving selector directly, preserving points/prior/
            # doomed-throw selection rules without re-entering this mixin.
            selected = int(PolicyValueBot._select(
                self, rnd, seat, admitted, q, worlds=worlds, check_budget=gate,
                **select_kwargs))
            gate()
        except HybridMultiTrickError as exc:
            fields["hybrid_fallback"] = (
                "budget" if "budget expired" in str(exc) else "invalid")
            fields["hybrid_completed_tricks"] = 0
            fields["hybrid_worlds"] = 0
            fields["hybrid_actions"] = 0
            self.hybrid_last_fields = fields
            return pv_winner
        except Exception as exc:
            fields["hybrid_fallback"] = type(exc).__name__
            fields["hybrid_completed_tricks"] = 0
            fields["hybrid_worlds"] = 0
            fields["hybrid_actions"] = 0
            self.hybrid_last_fields = fields
            return pv_winner
        fields.update(hybrid_applied=True, hybrid_changed=selected != pv_winner)
        if isinstance(stats, dict):
            fields["hybrid_completed_tricks_min"] = stats.get("tree_completed_tricks_min")
            fields["hybrid_completed_tricks_max"] = stats.get("tree_completed_tricks_max")
        self.hybrid_last_fields = fields
        return selected

    def _tree_decide(self, rnd, seat, admitted, means, worlds, pv_winner, fields,
                     select_kwargs):
        return self._hybrid_tree_decide(
            rnd, seat, admitted, means, worlds, pv_winner, fields, select_kwargs)


class HybridMultiTrickPVTreeSearchBot(HybridMultiTrickMixin, PVTreeSearchBot):
    """DEV hybrid paired with the ordinary PV tree bot."""


class HybridMultiTrickPVTreeSearchBuryBot(HybridMultiTrickMixin, PVTreeSearchBuryBot):
    """DEV hybrid paired with PV search plus the existing bury policy."""


def attach_hybrid(bot, *, enabled=True, total_seconds=None):
    """Attach the DEV adapter to an already constructed PV serving bot.

    This is the intended duel hook: package, sampler, evaluator and checkpoint
    remain those of ``bot``.  The only config change is an instance-local
    ``PVTreeConfig(sims=0)`` marker needed by ``PVTreeMixin`` to expose the
    captured PV matrix and lookahead implementation.  No registry/default is
    changed, and the caller still chooses the ordinary bot as its baseline.

    ``total_seconds`` gives the optional stage a finite total play deadline
    instead of the serving headroom cutoff. It also extends outer finalization
    for that decision only; baseline search, bury and declaration keep their
    original budgets. The enclosing runner still needs a hard wall cap.
    """
    if type(enabled) is not bool:
        raise TypeError("enabled must be a bool")
    if total_seconds is not None:
        if (isinstance(total_seconds, bool) or not isinstance(total_seconds, (int, float))
                or not math.isfinite(total_seconds) or total_seconds <= 0):
            raise ValueError("total_seconds must be finite and positive")
        existing = getattr(bot, "serving_budget_seconds", None)
        if existing is None or total_seconds < existing:
            raise ValueError("total_seconds must cover the finite baseline budget")
    if not isinstance(bot, PVSearchBot):
        raise TypeError("attach_hybrid expects a PVSearchBot or PVSearchBuryBot")
    if getattr(bot.config, "tree", None) is not None:
        raise TypeError("attach_hybrid expects a bot without an existing tree config")
    if isinstance(bot, HybridMultiTrickMixin):
        bot.hybrid_multi_trick = enabled
        bot.hybrid_total_seconds = total_seconds
        return bot
    original = bot.__class__
    # Existing PV classes are pure Python and have no slots; this preserves the
    # live instance state while adding only the DEV MRO methods.
    attached = type(
        f"HybridAttached{original.__name__}",
        (HybridMultiTrickMixin, PVTreeMixin, original),
        {},
    )
    bot.__class__ = attached
    bot.hybrid_multi_trick = enabled
    bot.hybrid_total_seconds = total_seconds
    bot.hybrid_decision_started = None
    bot.hybrid_last_fields = None
    bot._hybrid_tree_config = PVTreeConfig(sims=0)
    return bot


__all__ = [
    "HybridMultiTrickPVTreeSearchBot",
    "HybridMultiTrickPVTreeSearchBuryBot",
    "attach_hybrid",
]
