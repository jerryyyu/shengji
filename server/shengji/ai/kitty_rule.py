"""The bury-rule kitty (board rows S30/S31, `ai.uniform_worlds` on its own
line): a world proposal that deals the banker's unplayed cards and the hidden
kitty as one multiset ``U`` chooses the kitty with the served bury's incumbent
rule instead of dealing it eight random cards.

The real kitty is the banker's discard, not eight random cards.  The rule
rebuilds the banker's 33-card bury hand as ``U`` plus every card the banker
has played, applies `HeuristicBot.decide_bury`'s keep values restricted to
``U`` (a played card was not buried), and the banker's hand is ``U`` minus
that kitty.  A world is rejected when that hand breaks the banker's public
constraints (voids, draw-constraint codes, pair and run caps) or when the
kitty would need a trump: the rule keeps every trump while the 33-card hand
holds eight other cards, so such a kitty means the rule's own choice held a
card the banker has played since.  Requiring the rule's whole choice to be
unplayed instead rejects nearly every world once the banker has played one
low card, and the real banker is not exactly this rule.

These functions are the same text as `uniform_worlds.heuristic_bury_kitty`,
`kitty_rule_split` and `_caps_hold` on the S30 line; the first of the two
lines to merge keeps one copy and the other imports it."""
from __future__ import annotations

from collections import Counter

from ..engine.cards import TRUMP, points
from ..engine.combos import decompose
from .heuristic import HeuristicBot

#: the kitty rule's world model, named in a recipe digest
KITTY_RULE_MODEL = "heuristic-incumbent-bury-on-rebuilt-hand-unplayed-only-v1"

_INCUMBENT = HeuristicBot()


def heuristic_bury_kitty(hand33, available, ordering, slots):
    """The served bury's incumbent rule (`HeuristicBot.decide_bury`) on the
    rebuilt bury hand ``hand33``, choosing ``slots`` cards from ``available``
    only (a multiset inside ``hand33``).  Its keep value is the incumbent's,
    computed on the whole 33-card hand; ties go to the lower code, which is the
    incumbent's stable order on a hand sorted by code."""
    o = ordering
    cnt = Counter(hand33)
    suit_len = Counter(o.eff_suit(c) for c in hand33)
    mult = _INCUMBENT._bury_points_mult(suit_len[TRUMP], cnt["BJ"] > 0)
    top = len(o.plain_ranks) - 1
    keep = {}
    for code in cnt:
        suit = o.eff_suit(code)
        if suit == TRUMP:
            keep[code] = 100 + o.level(code)
            continue
        v = float(o.level(code))
        if o.level(code) >= top:
            v += 40
        if cnt[code] >= 2:
            v += 25
        v += points(code) * mult
        v -= _INCUMBENT._bury_short_bonus(suit_len[suit])
        keep[code] = v
    return sorted(available, key=lambda c: (keep[c], c))[:slots]


def kitty_rule_split(rnd, mem, union, played, forbidden=(), slots=None):
    """Split the banker's unplayed cards ``union`` (its hand now plus the
    kitty) by the served bury's incumbent rule: ``(hand, kitty)``, or None when
    the world contradicts the rule (the kitty would need a trump) or the
    banker's hand breaks its public constraints (voids, ``forbidden`` codes,
    pair and run caps).  ``played`` is every card the banker has played."""
    o = rnd.ordering
    banker = rnd.banker
    slots = len(rnd.buried) if slots is None else slots
    kitty = heuristic_bury_kitty(list(union) + list(played), union, o, slots)
    # the rule buries a trump only from a hand short of eight other cards; a
    # kitty that needs one here means the rule's own choice included a card
    # the banker has played since, so the world contradicts the rule
    if any(o.eff_suit(c) == TRUMP for c in kitty):
        return None
    hand = list((Counter(union) - Counter(kitty)).elements())
    voids = mem.voids[banker]
    if any(o.eff_suit(c) in voids or c in forbidden for c in hand):
        return None
    if not _caps_hold(banker, hand, mem, o):
        return None
    return hand, kitty


def _caps_hold(seat, hand, mem, o):
    """Does ``hand`` keep ``seat``'s pair and run caps (`Memory`)?"""
    caps = mem.pair_cap[seat]
    runs = mem.run_cap[seat]
    if not caps and not runs:
        return True
    for suit in set(caps) | set(runs):
        cards = [c for c in hand if o.eff_suit(c) == suit]
        if len(cards) < 2:
            continue
        cap = caps.get(suit)
        if cap is not None and sum(v // 2 for v in Counter(cards).values()) > cap:
            return False
        run = runs.get(suit)
        if run is not None and decompose(cards, o).max_pair_run() > run:
            return False
    return True
