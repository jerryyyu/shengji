"""Observation and action encoding for the RL policy (RL_PLAN.md Phase 1).

Pure Python (lists of floats) so the encoder has no torch/numpy dependency;
training code converts to tensors. Bump ENC_VERSION on ANY layout change —
checkpoints and datasets are only valid within one version.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path

from ..engine.cards import RANKS, SUITS, TRUMP, make_deck
from ..engine.combos import decompose
from ..engine.round import Round
from ..ai.memory import Memory

ENC_VERSION = 1
OBS_SCHEMA = "rl-observation-v1-public-no-private-kitty"


def _source_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# Version integers catch deliberate layout changes; source digests also bind
# behavioural dependencies that can drift without changing vector length.  The
# Aug-3 Memory default change demonstrated why both are necessary.
#: Pre-change digests of the three files edited on 2026-09-19 for speed (one Memory per
#: encode) with output PROVEN byte-identical: tests/data/encoder_bytes_golden.json was
#: written by the pre-change tree and tests/test_encoder_bytes_golden.py regenerates it.
#: Every identity that hashes these files -- this two-file public-head identity, the
#: transitive contract (encoder_identity.py), and the CWV identities (train.cwv_data and
#: its replica in ai.cwv_policy) -- substitutes these digests, so archived public-head
#: and CWV checkpoints keep loading and no cache is orphaned.  The guard against a future
#: change that DOES move bytes is the golden test, on its sampled states, not the source
#: digest.  Decision: Jerry 2026-09-19.
PUBLISHED_SOURCE_SHA256 = {
    "memory": "905873b332fd54471070b25ce24f100b813c9a9f234c1b50254d00895140cf51",
    "encode": "819fe2b2fc3cb9f0dd18cfd1c916b2387e92d97345f6dda212b2f149c7e7408b",
    "encode_versions": "8e85d046c1d09a387fc51f1f3f40c4fa992469ba981d6ad3def5f61c60a11b55",
}
_LIVE_SOURCE_SHA256S = {
    "encode": _source_sha256(Path(__file__).resolve()),
    "memory": _source_sha256(
        Path(__file__).resolve().parents[1] / "ai" / "memory.py"),
}
ENCODER_SOURCE_SHA256S = {
    name: PUBLISHED_SOURCE_SHA256.get(name, digest) for name, digest in _LIVE_SOURCE_SHA256S.items()
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

OBS_DIM = N_CARDS * 9 + 5 + 13 + 4 + 1 + 1 + 1 + 20  # = 531
ACT_DIM = N_CARDS + 6                                  # = 60


def _counts(cards) -> list[float]:
    v = [0.0] * N_CARDS
    for c in cards:
        v[CARD_INDEX[c]] += 0.5  # counts 0/1/2 -> 0/.5/1
    return v


def encode_obs(rnd: Round, seat: int, *, mem: "Memory | None" = None) -> list[float]:
    """Fixed-size observation for the acting seat. Public info + own hand.

    ``mem`` may be the public ``Memory(rnd, seat, own_kitty=False)`` already built by a
    caller that also needs it (encode_versions builds one and hands it to every block);
    when omitted it is built here exactly as before.  The bytes do not depend on which.
    """
    assert rnd.ordering is not None
    o = rnd.ordering
    # Encoder v1 predates the banker's private-kitty Memory feature.  Its
    # checkpoints and stored shards therefore encode `unseen` without removing
    # the burial, even for the banker.  Memory's default changed on 2026-08-03;
    # relying on that default silently changed banker inputs while
    # ENC_VERSION stayed 1.  Keep the historical v1 bytes explicit here.  A
    # future encoder may expose the legal private kitty only behind a version
    # bump and freshly generated data/checkpoints.
    if mem is None:
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
