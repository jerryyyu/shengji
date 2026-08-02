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

from collections import Counter

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

    for comp in dec.components:
        for other in other_hands:
            oc = suit_cards(other, eff, ordering)
            if comp.pair_len == 0:
                if any(ordering.level(c) > comp.top for c in oc):
                    return _throw_penalty(comp)
            elif comp.pair_len == 1:
                cnt = Counter(oc)
                if any(n >= 2 and ordering.level(c) > comp.top for c, n in cnt.items()):
                    return _throw_penalty(comp)
            else:
                from .combos import find_tractor_runs
                runs = find_tractor_runs(oc, ordering, comp.pair_len)
                if any(ordering.level(r[-1]) > comp.top for r in runs):
                    return _throw_penalty(comp)
    return play, None


def _throw_penalty(comp) -> tuple[list[str], str]:
    """Force the BEATEN component (standard rule): a failed low-pair+ace
    throw plays the low pair into the higher pair that exposed it — not
    the boss ace (the old globally-lowest rule barely punished)."""
    return comp.cards, "Throw failed — forced to play " + "+".join(comp.cards)


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
