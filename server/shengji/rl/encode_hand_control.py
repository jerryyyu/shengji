"""Eight actor-visible hand-control columns for the encoder-v3 ablation.

Boss means no higher unseen card/pair in the SAME effective suit, not a sure
trick winner (ruffing, lead/follow structure and team coordination still matter).
Callers supply the historical public unseen set (kitty included). Only this
new feature block removes the actor's own known burial when it is the banker;
the v1/v2 prefix remains unchanged. Non-bankers never inspect burial contents.
"""
from collections import Counter

from ..engine.cards import SUITS, TRUMP
from ..engine.combos import decompose
from .encode import CARD_INDEX, N_CARDS

HAND_CONTROL_COLUMNS = (
    'boss_plain_copies', 'boss_trump_copies',
    'boss_plain_pairs', 'boss_trump_pairs',
    'longest_plain_tractor_pairs', 'longest_trump_tractor_pairs',
    'plain_tractor_components', 'trump_tractor_components',
)


def hand_control_from_observation(rnd, seat, observation):
    """Reuse the v1 unseen plane; no extra Memory/history walk for v3."""
    offset = 8 * N_CARDS
    unseen = Counter({card: int(2 * observation[offset + index])
                      for card, index in CARD_INDEX.items()
                      if observation[offset + index] > 0})
    return hand_control_columns(rnd, seat, unseen)


def hand_control_columns(rnd, seat, unseen):
    """Same inputs on training and serving; never inspect another hand.

    ``unseen`` must be the v1/v2 public counter, not Memory(own_kitty=True),
    otherwise the banker's burial would be subtracted twice.
    """
    if rnd.banker == seat and rnd.buried:
        unseen = Counter(unseen) - Counter(rnd.buried)
    ordering = rnd.ordering
    hand = Counter(rnd.hands[seat])
    suits = [*SUITS, TRUMP]
    highest = {s: -1 for s in suits}
    highest_pair = {s: -1 for s in suits}
    for card, count in unseen.items():
        if count <= 0:
            continue
        suit, level = ordering.eff_suit(card), ordering.level(card)
        highest[suit] = max(highest[suit], level)
        if count >= 2:
            highest_pair[suit] = max(highest_pair[suit], level)
    boss, pairs, longest, tractors = [0, 0], [0, 0], [0, 0], [0, 0]
    grouped = {s: [] for s in suits}
    for card, count in hand.items():
        suit, level = ordering.eff_suit(card), ordering.level(card)
        group = int(suit == TRUMP)
        if level >= highest[suit]:
            boss[group] += count
        if count >= 2 and level >= highest_pair[suit]:
            pairs[group] += 1
        grouped[suit].extend([card] * count)
    for suit, cards in grouped.items():
        if not cards:
            continue
        group = int(suit == TRUMP)
        for component in decompose(cards, ordering).components:
            if component.kind == 'tractor':
                longest[group] = max(longest[group], component.pair_len)
                tractors[group] += 1
    return [*(x / 25.0 for x in boss), *(x / 12.0 for x in pairs),
            *(x / 12.0 for x in longest), *(x / 6.0 for x in tractors)]
