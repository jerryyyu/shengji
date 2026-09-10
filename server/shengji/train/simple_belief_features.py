"""Small actor-only belief input and separate privileged ownership labels.

Four relative receivers are next/opposite/previous player and kitty. Per-card
class masks encode necessary facts, NOT a valid joint-world distribution.
The legal sampler remains responsible for complete hand/kitty constraints.
"""
from collections import Counter
import numpy as np

from ..ai.memory import Memory
from ..engine.cards import make_deck
from ..rl.encode import CARD_INDEX, N_CARDS, OBS_DIM, encode_obs
from ..rl.public_history import HISTORY_EVENT_DIM, encode_public_history

FEATURE_SCHEMA = 'simple-belief-public-own-kitty-final-declaration-v1'
FEATURE_DIM = OBS_DIM + N_CARDS + 4 + 4 + N_CARDS + 1 + 2 * HISTORY_EVENT_DIM
CARDS = tuple(sorted(CARD_INDEX, key=CARD_INDEX.get))


def _counts(cards):
    counts = Counter(cards)
    return np.asarray([counts[c] for c in CARDS], dtype=np.int64)


def actor_features(rnd, seat):
    """Reads own cards/private burial and public state only; never true deal."""
    if type(seat) is not int or seat not in range(4) or rnd.phase != 'play':
        raise ValueError('belief features require a play-phase actor')
    mem = Memory(rnd, seat, own_kitty=False)
    # Hand lengths are public, but derive them from accepted public plays so
    # this new path need not inspect opponents' hand objects even for lengths.
    sizes = np.asarray([25-sum(mem.played_by[(seat+r) % 4].values()) for r in range(4)])
    declaration = rnd.declaration
    shown = np.zeros(N_CARDS)
    declarer = np.zeros(4)
    if declaration is not None:
        shown = _counts(declaration['cards']) / 2
        declarer[(declaration['seat']-seat) % 4] = 1
    knows_kitty = seat == rnd.banker
    kitty = _counts(rnd.buried) if knows_kitty else np.zeros(N_CARDS, dtype=np.int64)
    if knows_kitty and int(kitty.sum()) != 8:
        raise ValueError('banker private kitty must have eight cards')
    events = encode_public_history(rnd, seat)
    history = events.mean(axis=0) if len(events) else np.zeros(HISTORY_EVENT_DIM)
    recent = events[-8:].mean(axis=0) if len(events) else np.zeros(HISTORY_EVENT_DIM)
    features = np.concatenate([encode_obs(rnd, seat), shown, declarer, sizes/25,
                               kitty/2, [float(knows_kitty)], history, recent]).astype(np.float32)
    if features.shape != (FEATURE_DIM,) or not np.isfinite(features).all():
        raise ValueError('invalid belief feature shape or values')

    unseen = _counts(mem.unseen.elements())  # Includes kitty even for banker.
    capacities = np.concatenate([sizes[1:], [8]])
    lower = np.zeros((4, N_CARDS), dtype=np.int64)
    upper = np.minimum(capacities[:, None], unseen[None, :])
    for rel in range(1, 4):
        other = (seat + rel) % 4
        for j, code in enumerate(CARDS):
            suit = rnd.ordering.eff_suit(code)
            if suit in mem.voids[other]:
                upper[rel-1, j] = 0
            elif mem.pair_cap[other].get(suit) == 0:
                upper[rel-1, j] = min(upper[rel-1, j], 1)
    if knows_kitty:
        lower[3] = upper[3] = kitty

    if declaration is not None and declaration['seat'] != seat:
        owner = declaration['seat']
        receiver = (owner-seat) % 4 - 1
        remaining = Counter(declaration['cards']) - mem.played_by[owner]
        for code, count in remaining.items():
            j = CARD_INDEX[code]
            if owner != rnd.banker:
                lower[receiver, j] = max(lower[receiver, j], count)
            else:
                # Banker may bury a shown card. Never convert this union fact
                # into the old unsound probability-one ownership of its hand.
                for other in range(3):
                    if other != receiver:
                        upper[other, j] = min(upper[other, j], unseen[j]-count)
                lower[receiver, j] = max(lower[receiver, j], count-upper[3, j])
                lower[3, j] = max(lower[3, j], count-upper[receiver, j])

    # Necessary per-card conservation implications; full row/suit/run checks
    # are still enforced by the existing legal world sampler, not these masks.
    for _ in range(8):
        lo = np.maximum(lower, unseen[None, :] - (upper.sum(axis=0)-upper))
        hi = np.minimum(upper, unseen[None, :] - (lo.sum(axis=0)-lo))
        if np.array_equal(lo, lower) and np.array_equal(hi, upper):
            break
        lower, upper = lo, hi
    if (lower < 0).any() or (upper > 2).any() or (lower > upper).any() \
            or (lower.sum(axis=0) > unseen).any() or (upper.sum(axis=0) < unseen).any():
        raise ValueError('inconsistent actor-visible count constraints')
    classes = np.arange(3)[None, None, :]
    allowed = (classes >= lower[:, :, None]) & (classes <= upper[:, :, None])
    return features, allowed


def ownership_targets(rnd, seat):
    """Privileged training/evaluation ONLY; never call from feature assembly."""
    if rnd.phase != 'play' or type(seat) is not int or seat not in range(4):
        raise ValueError('ownership labels require a play-phase actor')
    labels = np.stack([_counts(rnd.hands[(seat+r) % 4]) for r in range(1, 4)] + [_counts(rnd.buried)])
    mem = Memory(rnd, seat, own_kitty=False)
    if (labels < 0).any() or (labels > 2).any() or not np.array_equal(labels.sum(axis=0), _counts(mem.unseen.elements())):
        raise ValueError('ownership label conservation differs')
    if Counter(c for hand in rnd.hands for c in hand) + Counter(rnd.buried) + mem.played != Counter(make_deck()):
        raise ValueError('ownership physical deck differs')
    return labels
