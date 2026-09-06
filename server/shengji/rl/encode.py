"""Observation and action encoding for the RL policy (RL_PLAN.md Phase 1).

Pure Python (lists of floats) so the encoder has no torch/numpy dependency;
training code converts to tensors. Bump ENC_VERSION on ANY layout change —
checkpoints and datasets are only valid within one version.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path

from ..engine.cards import RANKS, SUITS, TRUMP, make_deck, total_points
from ..engine.combos import decompose
from ..engine.legal import beats
from ..engine.round import Round
from ..ai.memory import Memory

ENC_VERSION = 2
OBS_SCHEMA = "rl-observation-v2-trick-state"


def _source_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# Version integers catch deliberate layout changes; source digests also bind
# behavioural dependencies that can drift without changing vector length.  The
# Aug-3 Memory default change demonstrated why both are necessary.
ENCODER_SOURCE_SHA256S = {
    "encode": _source_sha256(Path(__file__).resolve()),
    "memory": _source_sha256(
        Path(__file__).resolve().parents[1] / "ai" / "memory.py"),
}
ENCODER_IMPLEMENTATION_SHA256 = hashlib.sha256(
    "|".join(f"{name}:{digest}" for name, digest in
             sorted(ENCODER_SOURCE_SHA256S.items())).encode("ascii")
).hexdigest()

# Canonical card index: S2..SA, H2..HA, D2..DA, C2..CA, LJ, BJ  (54)
CARD_INDEX: dict[str, int] = {}
for _s in SUITS:
    for _r in RANKS:
        CARD_INDEX[_s + _r] = len(CARD_INDEX)
CARD_INDEX["LJ"] = len(CARD_INDEX)
CARD_INDEX["BJ"] = len(CARD_INDEX)
N_CARDS = 54

#: v1 block, then the v2 additions: 16 trick-local, 5 points-regime, 8 hand shape
OBS_DIM = N_CARDS * 9 + 5 + 13 + 4 + 1 + 1 + 1 + 20 + 16 + 5 + 8  # = 560
ACT_DIM = N_CARDS + 6                                  # = 60


def _counts(cards) -> list[float]:
    v = [0.0] * N_CARDS
    for c in cards:
        v[CARD_INDEX[c]] += 0.5  # counts 0/1/2 -> 0/.5/1
    return v



def trick_state(rnd: Round, seat: int) -> tuple[int | None, str | None, int]:
    """``(winning seat, lead effective suit, points on the table)`` for the
    trick in progress, or ``(None, None, 0)`` when ``seat`` is on lead.

    ``Round`` keeps a running incumbent only inside a trusted rollout; on the
    ordinary path the winner is resolved when the trick completes. This
    recomputes it the same way ``Round`` does, so the observation can carry a
    fact the acting player plainly has and the v1 vector never stated.
    """
    trick = rnd.trick
    if trick is None or not trick.plays:
        return None, None, 0
    o = rnd.ordering
    assert o is not None
    lead = trick.plays[0].cards
    winner = trick.plays[0].seat
    inc_suit = o.eff_suit(lead[0])
    inc_top = decompose(lead, o).top_level()
    for tp in trick.plays[1:]:
        won, top = beats(tp.cards, lead, inc_suit, inc_top, o)
        if won:
            winner, inc_top = tp.seat, top
            inc_suit = o.eff_suit(tp.cards[0])
    points = total_points(c for tp in trick.plays for c in tp.cards)
    return winner, o.eff_suit(lead[0]), points


def encode_obs(rnd: Round, seat: int) -> list[float]:
    """Fixed-size observation for the acting seat. Public info + own hand."""
    assert rnd.ordering is not None
    o = rnd.ordering
    # Encoder v1 predates the banker's private-kitty Memory feature.  Its
    # checkpoints and stored shards therefore encode `unseen` without removing
    # the burial, even for the banker.  Memory's default changed on 2026-08-03;
    # relying on that default silently changed banker inputs while
    # ENC_VERSION stayed 1.  Keep the historical v1 bytes explicit here.  A
    # future encoder may expose the legal private kitty only behind a version
    # bump and freshly generated data/checkpoints.
    mem = Memory(rnd, seat, own_kitty=False)

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

    # --- v2: the trick in progress (16) -------------------------------
    winner, lead_suit, trick_pts = trick_state(rnd, seat)
    winner_rel = [0.0] * 4
    if winner is not None:
        winner_rel[(winner - seat) % 4] = 1.0
    obs += winner_rel
    obs.append(1.0 if (winner is not None and winner != seat
                       and (winner - seat) % 2 == 0) else 0.0)
    obs.append(min(trick_pts, 80) / 80.0)
    lead_onehot = [0.0] * 5
    if lead_suit is not None:
        lead_onehot[(list(SUITS) + [TRUMP]).index(lead_suit)] = 1.0
    obs += lead_onehot
    played_here = 0 if rnd.trick is None else len(rnd.trick.plays)
    position = [0.0] * 4
    position[min(played_here, 3)] = 1.0
    obs += position
    obs.append(len(rnd.trick.plays[0].cards) / 6.0
               if (rnd.trick is not None and rnd.trick.plays) else 0.0)

    # --- v2: the points regime (5) ------------------------------------
    # A point near the 80 threshold decides the level; a point at 20 does not.
    # v1 gave only a linear fraction of 200 and never stated the kink.
    pts_now = min(rnd.attacker_points, 200)
    obs.append(max(-1.0, min(1.0, (pts_now - 80) / 80.0)))
    band = [0.0] * 4
    band[0 if pts_now < 40 else 1 if pts_now < 80 else 2 if pts_now < 120 else 3] = 1.0
    obs += band

    # --- v2: what the hand is made of (8) -----------------------------
    hand = rnd.hands[seat]
    eff = [o.eff_suit(c) for c in hand]
    for name in list(SUITS) + [TRUMP]:
        obs.append(eff.count(name) / 27.0)
    obs.append(sum(1 for c in mem.unseen.elements()
                   if o.eff_suit(c) == TRUMP) / 27.0)
    counts = Counter(hand)
    obs.append(sum(1 for v in counts.values() if v >= 2) / 13.0)
    obs.append(len(hand) / 27.0)

    assert len(obs) == OBS_DIM, f"{len(obs)} != {OBS_DIM}"
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
