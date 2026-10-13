"""Declare worlds consistent with the other seats' silence (#707 S15(4); OFF BY DEFAULT).

``SHENGJI_PV_VALUE_DECLARE_PASS_WORLDS=1`` (token ``vdpw``; wiring, refusals
and record: `pv_search_policy`).  The value declaration (``vd``) scores its
outcomes on deals drawn by `value_declare.sample_declare_world`: the uniform
posterior given the seat's own hand and the public declaration.  That posterior
ignores that the other seats have NOT declared.  A seat that has held a
declarable combination which beats the current declaration, for several of its
own cards, and still has not declared is (weak) evidence that it does not hold
one.  This module reweights the declare worlds by that evidence, softly.

The likelihood.  Seat ``s`` (not the deciding seat and not the current
declarer) has been dealt ``n_s`` cards (public: the deal is round-robin).  In a
sampled world its dealt cards are the first ``n_s`` of its sampled hand, in the
sampled order (the unseen cards are exchangeable, so that order is a draw from
the true deal order's posterior).  Let ``a_s`` be the first count at which those
cards contain a combination STRONGER than the current declaration (a single of
the trump rank when nothing is declared; a pair of it, or a pair of either
joker, above a weaker declaration).  Declarations only ever strengthen, so that
combination has beaten every declaration standing since it was completed: the
seat had a legal over-declaration for each of the ``n_s - a_s`` cards dealt to
it since, and stayed silent.  With a constant per-card declare hazard ``h``::

    P(silent | world) = prod_s (1 - h) ** (n_s - a_s)

(a seat with no such combination contributes 1).  A world is accepted with that
probability (rejection sampling: an accepted world is an exact draw from the
uniform posterior times the silence likelihood; the capped fallback below is
not).  Each draw takes one shuffle
and one ``random()`` from the decision's own stream, so no bot RNG moves.

``HAZARD`` (0.02 per own card) is an EXPLORATORY FIXED CONSTANT, not a
calibrated rate.  It is chosen at or below what the production room logs (the
human corpus, 262 rounds; `scripts/declare_pass_evidence.py`, deal positions
reconstructed from event times) show for HUMAN seats once a seat has passed
its first chance: deal-time declarations per own card held silently were
0.031 (a trump-rank single with nothing declared) and 0.019 (an over-declaring
pair) at the server's deal rate, 0.032 / 0.027 assuming a slower deal.  The
weight leaves out the zero-wait factor (a seat declaring on the very card that
made it eligible: 0 of 330 human episodes at the server rate, 4-12% at the
slower one; 2-43% for bots), which could only strengthen the conditioning.
Humans holding an over-declaring pair PASSED it to the end of the window in
39 of the 64 episodes that were not pre-empted, so a hard exclusion of such
worlds would reject the true world most of the time; the bots in the same
rooms passed 40 of 135.  One value serves both kinds.  A seat that has held a
combination for its whole 25-card hand keeps weight 0.98 ** 25 = 0.60; three
such seats, 0.22, so the acceptance rate is bounded below.  The cap
``MAX_ATTEMPTS`` bounds the draws regardless: after that many rejections the
last draw is kept and counted as a fallback.  That world is NOT a uniform draw
(it is rejection-conditioned, distributed as ``q(w) (1 - weight(w)) / (1 - Z)``
with ``Z`` the mean acceptance), so the sampler is exact only up to the
counted fallbacks; with acceptance at least 0.22 a fallback has probability
below 0.78 ** 32 < 0.001 per world.

Not modelled (each would need its own data and flag): the grace-window passes
(``rnd.passed``) and the seats' silence against a declaration that has since
been overcalled (the engine keeps only the current one); whether a seat is a
bot (a bot's declare policy is deterministic, not a hazard); and the
"wait" option, a bot that deliberately passes now to declare later.
"""
from __future__ import annotations

import random
from collections import Counter

from ..engine.cards import BJ, LJ, card_rank
from . import value_declare as value_declare_model

#: the name token (after ``vdef`` and ``vdsb``) and the recipe keys (`pv_search_policy`)
TOKEN = "vdpw"
#: the declare world model's unseen-card part with the rule on: it replaces
#: ``uniform-unseen`` in `value_declare.MODEL`
MODEL_UNSEEN = "pass-conditioned-unseen"
#: per own card dealt while holding a combination that beats the current
#: declaration (module docstring); fixed, not env-tunable
HAZARD = 0.02
#: draws per accepted world before the last draw is taken as is
MAX_ATTEMPTS = 32


def dealt_counts(rnd) -> list[int]:
    """Cards dealt so far to each seat: public (round-robin from seat 0)."""
    dealt = sum(len(hand) for hand in rnd.hands)
    return [dealt // 4 + (1 if s < dealt % 4 else 0) for s in range(4)]


def _strength(counts: Counter, trump_rank: str, code: str) -> int:
    """The strongest declaration ``code``'s copies in ``counts`` allow
    (`Round._declaration_strength`'s scale: single 1, pair 2, small-joker
    pair 3, big-joker pair 4; 0 none)."""
    n = counts[code]
    if code == BJ:
        return 4 if n >= 2 else 0
    if code == LJ:
        return 3 if n >= 2 else 0
    if card_rank(code) == trump_rank:
        return 2 if n >= 2 else 1
    return 0


def silent_cards(dealt, trump_rank: str, current: int) -> int:
    """Cards dealt after ``dealt`` (in deal order) first held a combination
    stronger than ``current``: the seat's silent declare chances."""
    counts: Counter = Counter()
    for index, code in enumerate(dealt):
        counts[code] += 1
        if _strength(counts, trump_rank, code) > current:
            return len(dealt) - (index + 1)
    return 0


def silence_weight(rnd, seat: int, hands, hazard: float | None = None) -> float:
    """``P(every other seat's silence | hands)`` (module docstring); the
    deciding seat and the current declarer contribute 1.  ``hazard`` None is
    `HAZARD`."""
    hazard = HAZARD if hazard is None else hazard
    declaration = rnd.declaration
    current = 0 if declaration is None else int(declaration["strength"])
    declarer = None if declaration is None else declaration["seat"]
    counts = dealt_counts(rnd)
    silent = 0
    for s in range(4):
        if s == seat or s == declarer:
            continue
        silent += silent_cards(hands[s][:counts[s]], rnd.trump_rank, current)
    return (1.0 - hazard) ** silent


def sample_pass_world(rnd, seat: int, rng: random.Random, stats=None):
    """``(hands, kitty)``: one world drawn from the uniform declare posterior
    (`value_declare.sample_declare_world`) and accepted with its silence
    weight; after ``MAX_ATTEMPTS`` rejections the last draw is returned.
    ``stats`` (a dict, optional) accumulates ``worlds``, ``attempts`` and
    ``fallbacks``."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        hands, kitty = value_declare_model.sample_declare_world(rnd, seat, rng)
        if rng.random() < silence_weight(rnd, seat, hands):
            break
    else:
        attempt = None
    if stats is not None:
        stats["worlds"] = stats.get("worlds", 0) + 1
        stats["attempts"] = stats.get("attempts", 0) + (MAX_ATTEMPTS if attempt is None else attempt)
        stats["fallbacks"] = stats.get("fallbacks", 0) + (attempt is None)
    return hands, kitty


__all__ = ["TOKEN", "MODEL_UNSEEN", "HAZARD", "MAX_ATTEMPTS", "dealt_counts",
           "silent_cards", "silence_weight", "sample_pass_world"]
