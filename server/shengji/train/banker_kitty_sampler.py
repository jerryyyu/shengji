"""Opt-in DEV correction for banker declarations; never registered by import.

A banker may bury publicly declared cards. Opponents know a lower bound in
banker-hand UNION hidden kitty, not in banker-hand alone. Remove only that
incorrect hand pin and condition the existing proposal on the union bound.
The resulting law is a rejection-conditioned heuristic proposal, not a claim
of uniform deals or an exact Bayesian posterior. Caller attempt limits remain
in force. Existing policies and the encoder/Memory source stay unchanged.
"""
from __future__ import annotations

from collections import Counter
from copy import copy


def banker_kitty_bounds(rnd, seat, mem):
    """Actor-visible remaining declaration evidence; no true kitty inspection."""
    declaration = rnd.declaration
    banker = rnd.banker
    if declaration is None or banker is None or seat == banker or declaration["seat"] != banker:
        return {}
    shown = Counter(declaration["cards"])
    played = mem.played_by[banker]
    return {code: count - played[code] for code, count in shown.items()
            if count > played[code]}


class BankerKittySupportMixin:
    """Place before MCBot/CWVShortlistBot in an explicitly named DEV class.

    All play sampler calls, including cheap W32 ranking and final MC folds,
    dispatch through this method. Bury helper bots are unchanged: their actor
    is already the banker, which knows its own hand and chosen burial.
    """

    def _sample_hands(self, rnd, seat, mem):
        bounds = banker_kitty_bounds(rnd, seat, mem) if self.DECLARER_PIN else {}
        if not bounds:
            return super()._sample_hands(rnd, seat, mem)
        relaxed = copy(mem)
        relaxed.known = {code: pin for code, pin in mem.known.items()
                         if pin[0] != rnd.banker}
        impossible_before = self.impossible_worlds
        sampled = super()._sample_hands(rnd, seat, relaxed)
        if sampled is None:
            return None
        hands, buried = sampled
        union = Counter(hands[rnd.banker]) + Counter(buried)
        if all(union[code] >= count for code, count in bounds.items()):
            return sampled
        # Super counts an accepted proposal. It was not an accepted world for
        # this policy: publish consistent counts at the actual consumer boundary.
        self.accepted_worlds -= 1
        self.failed_worlds += 1
        self.rejected_worlds += 1
        self.impossible_worlds = impossible_before
        self.reject_cause["banker_kitty_declaration"] += 1
        return None


def supported_bot_class(base):
    """Explicit local construction only; no mutation of a registry class."""
    return type(f"BankerKittySupported{base.__name__}",
                (BankerKittySupportMixin, base),
                {"SAMPLER_SUPPORT_RECIPE": "banker-kitty-union-rejection-v1"})
