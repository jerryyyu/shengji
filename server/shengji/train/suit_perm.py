"""The 24 suit relabelings of a belief-format batch (``belief_seq.make_batch``) as index gathers.

A relabeling ``perm`` maps suit ``a`` (``S H D C`` = 0..3) to suit ``perm[a]``; jokers and ranks are
unchanged, and the trump suit moves with the cards (an ``S``-trump round becomes a ``perm[S]``-trump
round; a no-trump round stays no-trump).  Applying a relabeling to a batch gives exactly the batch
the extractor would build from the relabeled deal (``tests/test_unified_seq.py`` re-extracts
relabeled synthetic games, suited and no-trump, and compares every array), so training on a
uniformly drawn relabeling per batch teaches the model that suit names carry no information.

Layouts (card code ``suit * 13 + rank``, ``LJ`` 52, ``BJ`` 53; effective suits ``S H D C T``):

* summary row ``X`` (``belief_labels.FEATURE_BLOCKS``): 54-wide card planes; effective-suit blocks of
  five (``S H D C`` + one fixed slot for trump / no-trump), some interleaved with a stride;
* card arrays ``Y``, ``M``, ``tok_cards``, ``tok_att``, ``card_feat`` on their 54-card axis, and
  ``card_feat``'s ``eff_S .. eff_C`` columns;
* the token's led effective suit (``tok_int[..., 3]``) of every real play (padding stays zero).
"""
from __future__ import annotations

import itertools
from typing import Mapping

import numpy as np

from .belief_history import CARD_FEATURES, TOKEN_INT
from .belief_labels import FEATURE_BLOCKS, FEATURE_DIM

N_CARDS = 54
#: perm[a] = the image of suit a; PERMS[0] is the identity
PERMS: tuple[tuple[int, ...], ...] = tuple(itertools.permutations(range(4)))


def _block(name: str) -> int:
    at = 0
    for block, width in FEATURE_BLOCKS:
        if block == name:
            return at
        at += width
    raise KeyError(name)


_OBS = _block("obs_v4")
#: the 54-wide card planes of X: v1's nine planes, then the belief-only card blocks
_CARD_PLANES = tuple(_OBS + 54 * i for i in range(9)) + tuple(
    _block(b) for b in ("own_kitty", "declared_cards", "pinned_rel1", "pinned_rel2", "pinned_rel3",
                        "throw_unplayed_rel1", "throw_unplayed_rel2", "throw_unplayed_rel3"))
_RUN_CAP = _block("run_cap")
#: (start, stride) of every five-slot effective-suit block of X: v1 trump suit and the four
#: per-seat void blocks, v2's two suit blocks, v4's opponent-pair columns (three per-suit
#: fractions, the per-seat pair caps with three states per suit, the per-seat pairs played),
#: and the per-seat run caps (flag and cap per suit)
_SUIT5 = ((_OBS + 486, 1),) + tuple((_OBS + 511 + 5 * s, 1) for s in range(4)) + (
    (_OBS + 537, 1), (_OBS + 552, 1),
    (_OBS + 560, 1), (_OBS + 565, 1), (_OBS + 570, 1)) + tuple(
    (_OBS + 575 + 15 * rel + state, 3) for rel in range(3) for state in range(3)) + tuple(
    (_OBS + 620 + 5 * rel, 1) for rel in range(3)) + tuple(
    (_RUN_CAP + 10 * rel + k, 2) for rel in range(3) for k in range(2))
_LEAD = TOKEN_INT.index("lead_eff")
_EFF_COL = CARD_FEATURES.index("eff_S")


def card_gather(perm) -> np.ndarray:
    """``g`` with ``v_perm = v[g]`` on a 54-card axis: ``g[index(perm[a], r)] = index(a, r)``."""
    g = np.arange(N_CARDS)
    for a in range(4):
        g[perm[a] * 13:perm[a] * 13 + 13] = np.arange(a * 13, a * 13 + 13)
    return g


def suit5_gather(perm) -> np.ndarray:
    g = np.arange(5)
    for a in range(4):
        g[perm[a]] = a
    return g


def feature_gather(perm) -> np.ndarray:
    """``g`` with ``x_perm = x[g]`` on a ``FEATURE_DIM`` summary row."""
    g = np.arange(FEATURE_DIM)
    cg, sg = card_gather(perm), suit5_gather(perm)
    for start in _CARD_PLANES:
        g[start:start + N_CARDS] = start + cg
    for start, stride in _SUIT5:
        g[start + stride * np.arange(5)] = start + stride * sg
    return g


def lead_map(perm) -> np.ndarray:
    """New led-suit index of each old one (``S H D C T``; trump stays trump)."""
    return np.asarray(list(perm) + [4], np.int64)


def apply(batch: Mapping[str, np.ndarray], perm) -> dict[str, np.ndarray]:
    """The batch relabeled by ``perm`` (a new dict; the input is not modified).

    ``X`` is the batch's ``FEATURE_DIM`` row followed by the four receiver sizes (``make_batch``);
    ``row_card`` is rebuilt from the relabeled row.  Keys this module does not know are copied."""
    from .belief_seq import row_card_planes
    perm = tuple(int(p) for p in perm)
    if sorted(perm) != [0, 1, 2, 3]:
        raise ValueError(f"not a suit permutation: {perm}")
    out = dict(batch)
    if perm == PERMS[0]:
        return out
    cg, fg, sg = card_gather(perm), feature_gather(perm), suit5_gather(perm)
    X = np.asarray(batch["X"])
    Xp = X.copy()
    Xp[:, :FEATURE_DIM] = X[:, fg]
    out["X"] = Xp
    out["row_card"] = row_card_planes(Xp[:, :FEATURE_DIM])
    for k in ("M", "Y"):
        out[k] = np.asarray(batch[k])[:, cg]
    for k in ("tok_cards", "tok_att"):
        out[k] = np.asarray(batch[k])[..., cg]
    cf = np.asarray(batch["card_feat"])[:, cg].copy()
    cf[..., _EFF_COL:_EFF_COL + 5] = cf[..., _EFF_COL + sg]
    out["card_feat"] = cf
    ti = np.asarray(batch["tok_int"]).copy()
    # padding past a round's last play is all zero and stays so (a real play has a card)
    real = np.asarray(batch["tok_cards"]).sum(-1) > 0
    ti[..., _LEAD] = np.where(real, lead_map(perm)[ti[..., _LEAD]], ti[..., _LEAD])
    out["tok_int"] = ti
    return out


def draw(rng: np.random.Generator) -> tuple[int, ...]:
    """One of the 24 relabelings, uniformly."""
    return PERMS[int(rng.integers(len(PERMS)))]
