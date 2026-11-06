"""Rules profiles: another table's scoring and declare rules (OFF BY DEFAULT).

``SHENGJI_RULES_PROFILE`` names the profile; package import
(``shengji/__init__.py``) installs it after the compiled engine, if any, is
active.  Unset or empty is this server's own rules: nothing is installed,
``Round`` keeps its own methods and every caller computes exactly what it
computes without this module.

Profiles:

* ``shengjiorg`` (the shengji.org tables the research adapter plays):

  - kitty bonus: the attackers' last-trick bonus is the buried points times
    ``KITTY_MULTIPLIER x`` the card count of the lead's LARGEST component
    (single x2, pair x4, a singles throw x2, a throw holding a pair x4).
    Ours multiplies by the lead's whole card count, so the two differ only
    when the last lead is a multi-component throw;
  - no declaration: the round is played without trump (NT) and the banker
    keeps the deal; ours flips trump from the kitty's first non-joker.

  Both apply to every ``Round`` in the process through ``Round.play`` and
  ``Round.finalize_declare`` wrappers, so rollouts, exact searches over the
  engine and the declare evaluation's worlds score these rules.  The compact
  exact solver reads :func:`kitty_multiplier` (``ai/endgame_compact.py``).
  What a network learned under our rules is unchanged by any profile.

The engine source files are not edited: their bytes are part of the
production encoder identity.
"""
from __future__ import annotations

import os

from .cards import Ordering, total_points
from .combos import decompose
from .round import KITTY_MULTIPLIER, Round

ENV = "SHENGJI_RULES_PROFILE"
DEFAULT = ""
SHENGJIORG = "shengjiorg"
PROFILES = (DEFAULT, SHENGJIORG)

_active = DEFAULT
_saved: dict = {}


def requested(environ=None) -> str:
    """The profile ``environ`` (default ``os.environ``) names; unknown raises."""
    value = (os.environ if environ is None else environ).get(ENV, DEFAULT)
    if value not in PROFILES:
        raise ValueError(f"unknown {ENV} {value!r}; known: {PROFILES}")
    return value


def active() -> str:
    """The installed profile (``DEFAULT`` when none)."""
    return _active


def kitty_multiplier(lead, ordering: Ordering, profile: str | None = None) -> int:
    """The last-trick kitty multiplier for the lead ``lead`` under ``profile``
    (default: the installed one)."""
    profile = _active if profile is None else profile
    if profile == SHENGJIORG:
        components = decompose(list(lead), ordering).components
        return KITTY_MULTIPLIER * max(component.size for component in components)
    return KITTY_MULTIPLIER * len(lead)


def _rescore_kitty(rnd: Round) -> None:
    """Replace a round-end kitty bonus computed by our rule with the profile's.

    Idempotent: a bonus that no longer equals our rule's value is left alone,
    so a play that passes through the wrapper twice is rescored once."""
    if rnd.phase != "round_end" or not rnd.kitty_bonus or rnd.last_trick is None:
        return
    lead = rnd.last_trick.plays[0].cards
    buried = total_points(rnd.buried)
    ours = buried * KITTY_MULTIPLIER * len(lead)
    if rnd.kitty_bonus != ours:
        return
    theirs = buried * kitty_multiplier(lead, rnd.ordering)
    rnd.attacker_points += theirs - ours
    rnd.kitty_bonus = theirs


def _finalize_without_trump(rnd: Round) -> None:
    """``Round.finalize_declare`` with no declaration, played as NT."""
    rnd.trump_is_nt = True
    rnd.trump_suit = None
    if rnd.banker is None:
        rnd.banker = 0
    rnd.message = "No declaration — played without trump: NT"
    rnd.ordering = Ordering(None, rnd.trump_rank)
    rnd.hands[rnd.banker].extend(rnd.kitty)
    rnd.phase = "bury"
    rnd.turn = rnd.banker


def no_declaration_trump(profile: str | None = None) -> str:
    """What an undeclared round's trump is under ``profile``: ``"NT"`` or
    ``"flip"`` (the kitty decides)."""
    profile = _active if profile is None else profile
    return "NT" if profile == SHENGJIORG else "flip"


def install(profile: str) -> None:
    """Install ``profile`` process-wide; ``DEFAULT`` uninstalls.  Install after
    ``engine.fast.activate``: activation replaces ``Round.play``."""
    global _active
    if profile not in PROFILES:
        raise ValueError(f"unknown rules profile {profile!r}")
    if profile == _active:
        return
    uninstall()
    if profile == DEFAULT:
        return
    play = Round.play
    finalize = Round.finalize_declare

    def profiled_play(self, seat, cards):
        play(self, seat, cards)
        if self.phase == "round_end":
            _rescore_kitty(self)

    def profiled_finalize_declare(self):
        if self.declaration is None and self.phase == "declare":
            _finalize_without_trump(self)
        else:
            finalize(self)

    _saved["play"] = play
    _saved["finalize_declare"] = finalize
    Round.play = profiled_play
    Round.finalize_declare = profiled_finalize_declare
    _active = profile


def uninstall() -> None:
    """Restore ``Round``'s methods as they were before :func:`install`."""
    global _active
    if _saved:
        Round.play = _saved.pop("play")
        Round.finalize_declare = _saved.pop("finalize_declare")
    _active = DEFAULT


def install_from_env(environ=None) -> str:
    """Install the profile ``environ`` names; returns it."""
    profile = requested(environ)
    install(profile)
    return profile


__all__ = ["ENV", "DEFAULT", "SHENGJIORG", "PROFILES", "requested", "active",
           "kitty_multiplier", "no_declaration_trump", "install", "uninstall",
           "install_from_env"]
