"""Lead/follow legality and trick resolution.

Follow rules implemented (standard digital-tractor rule set):
- You must play the same number of cards as the lead.
- If you hold enough cards of the led effective suit, all cards must come
  from it; you must use pairs from that suit up to the number of pairs led
  (as many as you have); if the lead is a single tractor and you hold a
  tractor of that length in suit, you must include one.
- If you hold some but not enough, you must play all of them and fill freely.
- If you are void, you may play anything; an all-trump, shape-matching play
  contends for the trick.
"""

from __future__ import annotations

from collections import Counter, OrderedDict

from .cards import Ordering, TRUMP
from .combos import Decomposition, decompose, decompose_matching, has_tractor, pair_count


class IllegalPlay(Exception):
    pass


def suit_cards(hand: list[str], eff: str, ordering: Ordering) -> list[str]:
    return [c for c in hand if ordering.eff_suit(c) == eff]


def _is_submultiset(small: list[str], big: list[str]) -> bool:
    cs, cb = Counter(small), Counter(big)
    return all(cb[c] >= n for c, n in cs.items())


def check_in_hand(hand: list[str], play: list[str]) -> None:
    if not play or not _is_submultiset(play, hand):
        raise IllegalPlay("You don't hold those cards.")


def uniform_suit(play: list[str], ordering: Ordering) -> str | None:
    suits = {ordering.eff_suit(c) for c in play}
    return suits.pop() if len(suits) == 1 else None


def validate_lead(play: list[str], hand: list[str], other_hands: list[list[str]],
                  ordering: Ordering) -> tuple[list[str], str | None]:
    """Validate a lead. Returns (actual_play, message).

    Singles/pairs/tractors always stand. A multi-component throw is checked
    against the other three hands: if any component can be beaten in-suit,
    the throw fails and the leader is forced to play its lowest component.
    """
    check_in_hand(hand, play)
    eff = uniform_suit(play, ordering)
    if eff is None:
        raise IllegalPlay("A lead must be a single suit (throws included).")
    dec = decompose(play, ordering)
    if len(dec.components) == 1:
        return play, None

    beatable = []

    for comp in dec.components:
        for other in other_hands:
            oc = suit_cards(other, eff, ordering)
            if comp.pair_len == 0:
                if any(ordering.level(c) > comp.top for c in oc):
                    beatable.append(comp)
            elif comp.pair_len == 1:
                cnt = Counter(oc)
                if any(n >= 2 and ordering.level(c) > comp.top for c, n in cnt.items()):
                    beatable.append(comp)
            else:
                from .combos import find_tractor_runs
                runs = find_tractor_runs(oc, ordering, comp.pair_len)
                if any(ordering.level(r[-1]) > comp.top for r in runs):
                    beatable.append(comp)
    if beatable:
        # Rule (Jerry, 2026-08-03): the thrower forfeits the LOWEST
        # beatable part — not whichever the scan met first (component
        # order put bigger/higher structures first, over-punishing).
        return _throw_penalty(min(beatable,
                                  key=lambda c: (c.pair_len, c.top)))
    return play, None


class PreparedLeadValidation:
    """Prepared facts for validating leads in one determinized world.

    The context is deliberately bound to the exact ``Ordering`` instance and
    snapshots of the participating hands.  A caller that presents any other
    state is sent through :func:`validate_lead`, which keeps this optimization
    decision-preserving even when a rollout is copied or mutated incorrectly.
    Facts are keyed by effective suit and component pair length; that is the
    only information about a component used by the opponent scan in the
    ordinary validator.
    """

    _MAX_FACTS = 64

    def __init__(self, hand: list[str], other_hands: list[list[str]],
                 ordering: Ordering):
        self._hand_snapshot = list(hand)
        self._other_hands_snapshot = [list(other) for other in other_hands]
        self._ordering = ordering
        self._ordering_binding = (ordering.trump_suit, ordering.trump_rank)
        self._suit_cards: dict[str, list[list[str]]] = {}
        self._max_top: OrderedDict[tuple[str, int], float] = OrderedDict()
        self.calls = 0
        self.hits = 0
        self.misses = 0
        self.fallbacks = 0

    @property
    def counters(self) -> dict[str, int]:
        """Counters for this context only (never the world-cache counters)."""
        return {
            "calls": self.calls,
            "hits": self.hits,
            "misses": self.misses,
            "fallbacks": self.fallbacks,
        }

    def _bound(self, hand: list[str], other_hands: list[list[str]],
               ordering: Ordering) -> bool:
        return (ordering is self._ordering
                and (ordering.trump_suit, ordering.trump_rank)
                == self._ordering_binding
                and hand == self._hand_snapshot
                and other_hands == self._other_hands_snapshot)

    def _opponent_suits(self, eff: str) -> list[list[str]]:
        suited = self._suit_cards.get(eff)
        if suited is None:
            suited = [suit_cards(other, eff, self._ordering)
                      for other in self._other_hands_snapshot]
            self._suit_cards[eff] = suited
        return suited

    def _highest_beatable(self, eff: str, pair_len: int) -> float:
        key = (eff, pair_len)
        cached = self._max_top.get(key)
        if cached is not None:
            self.hits += 1
            self._max_top.move_to_end(key)
            return cached

        self.misses += 1
        suited = self._opponent_suits(eff)
        if pair_len == 0:
            tops = [self._ordering.level(card)
                    for cards in suited for card in cards]
        elif pair_len == 1:
            tops = [self._ordering.level(card)
                    for cards in suited
                    for card, count in Counter(cards).items()
                    if count >= 2]
        else:
            from .combos import find_tractor_runs
            tops = [self._ordering.level(run[-1])
                    for cards in suited
                    for run in find_tractor_runs(cards, self._ordering,
                                                 pair_len)]
        top = max(tops, default=float("-inf"))
        self._max_top[key] = top
        self._max_top.move_to_end(key)
        if len(self._max_top) > self._MAX_FACTS:
            self._max_top.popitem(last=False)
        return top

    def validate(self, play: list[str], hand: list[str],
                 other_hands: list[list[str]], ordering: Ordering
                 ) -> tuple[list[str], str | None]:
        """Validate using prepared opponent facts when the binding matches."""
        if not self._bound(hand, other_hands, ordering):
            self.fallbacks += 1
            return validate_lead(play, hand, other_hands, ordering)

        self.calls += 1
        check_in_hand(hand, play)
        eff = uniform_suit(play, ordering)
        if eff is None:
            raise IllegalPlay("A lead must be a single suit (throws included).")
        dec = decompose(play, ordering)
        if len(dec.components) == 1:
            return play, None
        beatable = [component for component in dec.components
                    if self._highest_beatable(eff, component.pair_len)
                    > component.top]
        if beatable:
            return _throw_penalty(min(beatable,
                                      key=lambda c: (c.pair_len, c.top)))
        return play, None


def _throw_penalty(comp) -> tuple[list[str], str]:
    """Force the BEATEN component (standard rule): a failed low-pair+ace
    throw plays the low pair into the higher pair that exposed it — not
    the boss ace (the old globally-lowest rule barely punished).

    Returns a COPY: comp.cards aliases the Decomposition held in the
    per-Ordering decompose cache, and handing the caller the live list
    lets any in-place mutation poison the cache (the find_tractor_runs
    bug class, caught 2026-08-02)."""
    return list(comp.cards), "Throw failed — forced to play " + "+".join(comp.cards)


def validate_follow(play: list[str], hand: list[str], lead: list[str],
                    ordering: Ordering) -> None:
    """Raise IllegalPlay if ``play`` is not a legal response to ``lead``."""
    check_in_hand(hand, play)
    if len(play) != len(lead):
        raise IllegalPlay(f"Must play exactly {len(lead)} card(s).")
    eff = uniform_suit(lead, ordering)
    assert eff is not None
    h_suit = suit_cards(hand, eff, ordering)
    p_suit = suit_cards(play, eff, ordering)

    if len(h_suit) >= len(lead):
        if len(p_suit) != len(play):
            raise IllegalPlay("You must follow suit.")
        lead_dec = decompose(lead, ordering)
        need_pairs = min(lead_dec.n_pairs, pair_count(h_suit))
        if pair_count(play) < need_pairs:
            raise IllegalPlay("You must play pairs from the led suit.")
        # Tractor obligation for a pure tractor lead.
        if (len(lead_dec.components) == 1
                and lead_dec.components[0].kind == "tractor"):
            k = lead_dec.components[0].pair_len
            if has_tractor(h_suit, ordering, k):
                if decompose(play, ordering).max_pair_run() < k:
                    raise IllegalPlay(f"You must follow with a tractor of {k} pairs.")
    else:
        if not _is_submultiset(h_suit, play):
            raise IllegalPlay("You must play all your cards of the led suit.")


def beats(challenger: list[str], lead: list[str], incumbent_suit: str,
          incumbent_top: int, ordering: Ordering) -> tuple[bool, int]:
    """Does ``challenger`` beat the current best play? Returns (wins, top).

    Challenger must be one suit and match the lead's shape; then it wins by
    higher top in the same suit, or by being trump over non-trump.
    """
    eff = uniform_suit(challenger, ordering)
    if eff is None:
        return False, 0
    lead_dec = decompose(lead, ordering)
    ch_dec = decompose_matching(challenger, ordering, lead_dec.shape())
    if ch_dec is None:
        return False, 0
    top = ch_dec.top_level()
    if eff == incumbent_suit:
        return top > incumbent_top, top
    if eff == TRUMP:
        return True, top
    return False, 0
