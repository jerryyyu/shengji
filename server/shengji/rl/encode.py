"""Observation and action encoding for the RL policy (RL_PLAN.md Phase 1).

Pure Python (lists of floats) so the encoder has no torch/numpy dependency;
training code converts to tensors. Bump ENC_VERSION on ANY layout change —
checkpoints and datasets are only valid within one version.
"""

from __future__ import annotations

from collections import Counter

from ..engine.cards import RANKS, SUITS, TRUMP, make_deck
from ..engine.combos import decompose
from ..engine.round import Round
from ..ai.memory import Memory

ENC_VERSION = 1

# Canonical card index: S2..SA, H2..HA, D2..DA, C2..CA, LJ, BJ  (54)
CARD_INDEX: dict[str, int] = {}
for _s in SUITS:
    for _r in RANKS:
        CARD_INDEX[_s + _r] = len(CARD_INDEX)
CARD_INDEX["LJ"] = len(CARD_INDEX)
CARD_INDEX["BJ"] = len(CARD_INDEX)
N_CARDS = 54

OBS_DIM = N_CARDS * 9 + 5 + 13 + 4 + 1 + 1 + 1 + 20  # = 531
ACT_DIM = N_CARDS + 6                                  # = 60


def _counts(cards) -> list[float]:
    v = [0.0] * N_CARDS
    for c in cards:
        v[CARD_INDEX[c]] += 0.5  # counts 0/1/2 -> 0/.5/1
    return v


def encode_obs(rnd: Round, seat: int) -> list[float]:
    """Fixed-size observation for the acting seat. Public info + own hand."""
    assert rnd.ordering is not None
    o = rnd.ordering
    mem = Memory(rnd, seat)

    played_by = [[] for _ in range(4)]
    for t in rnd.history:
        for tp in t.plays:
            played_by[tp.seat].extend(tp.cards)
    trick_planes = [[0.0] * N_CARDS for _ in range(3)]
    if rnd.trick is not None:
        for i, tp in enumerate(rnd.trick.plays[:3]):
            trick_planes[i] = _counts(tp.cards)
            played_by[tp.seat].extend(tp.cards)

    obs: list[float] = []
    obs += _counts(rnd.hands[seat])
    for rel in range(4):  # seat-relative play history
        obs += _counts(played_by[(seat + rel) % 4])
    for plane in trick_planes:
        obs += plane
    obs += _counts(mem.unseen.elements())

    suit_onehot = [0.0] * 5  # S H D C NT
    if rnd.trump_is_nt:
        suit_onehot[4] = 1.0
    elif rnd.trump_suit in SUITS:
        suit_onehot[SUITS.index(rnd.trump_suit)] = 1.0
    obs += suit_onehot
    rank_onehot = [0.0] * 13
    rank_onehot[RANKS.index(rnd.trump_rank)] = 1.0
    obs += rank_onehot
    banker_rel = [0.0] * 4
    if rnd.banker is not None:
        banker_rel[(rnd.banker - seat) % 4] = 1.0
    obs += banker_rel
    obs.append(min(rnd.attacker_points, 200) / 200.0)
    obs.append(sum(len(h) for h in rnd.hands) / 100.0)  # cards remaining
    obs.append(1.0 if rnd.is_attacker(seat) else 0.0)
    for rel in range(4):  # seat-relative observed voids per eff suit
        s = (seat + rel) % 4
        for eff in list(SUITS) + [TRUMP]:
            obs.append(1.0 if eff in mem.voids[s] else 0.0)
    assert len(obs) == OBS_DIM
    return obs


def encode_action(cards: list[str], rnd: Round) -> list[float]:
    """Candidate-play encoding for the (obs, action) -> Q model."""
    assert rnd.ordering is not None
    o = rnd.ordering
    from ..engine.cards import points
    v = _counts(cards)
    dec = decompose(cards, o)
    v.append(len(cards) / 8.0)
    v.append(dec.n_pairs / 4.0)
    v.append(dec.max_pair_run() / 4.0)
    v.append(1.0 if all(o.eff_suit(c) == TRUMP for c in cards) else 0.0)
    v.append(sum(points(c) for c in cards) / 25.0)
    v.append(len(dec.components) / 4.0)
    assert len(v) == ACT_DIM
    return v
