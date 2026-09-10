"""Corrected ordinary sampler baseline for ownership diagnostics, not gameplay.

Empirical Brier is upward biased by finite draws. Report its unbiased additive
correction separately; never compare a deterministic forecast to an uncorrected
256-world estimate and call the estimator noise learned improvement.
"""
from collections import Counter
import time

import numpy as np

from ..ai.cwv_policy import sample_worlds
from ..ai.mcbot import MCBot
from ..ai.memory import Memory
from ..engine.cards import make_deck
from .banker_kitty_sampler import supported_bot_class
from .simple_belief_features import _counts, actor_features


def empirical_count_probabilities(counts):
    counts = np.asarray(counts)
    if counts.ndim != 3 or counts.shape[1:] != (4, 54) or len(counts) < 2 \
            or not np.issubdtype(counts.dtype, np.integer) \
            or (counts < 0).any() or (counts > 2).any():
        raise ValueError('need at least two complete 0/1/2 count worlds')
    p = np.eye(3, dtype=np.float64)[counts].mean(axis=0)
    correction = (p*(1-p)).sum(axis=-1)/(len(counts)-1)
    return p, correction


def corrected_reference(rnd, seat, *, seed, n=256):
    if type(n) is not int or n < 2:
        raise ValueError('reference requires at least two worlds')
    started = time.monotonic()
    bot = supported_bot_class(MCBot)(seed=seed)
    memory = Memory(rnd, seat)
    worlds, attempts = sample_worlds(bot, rnd, seat, n, mem=memory)
    if len(worlds) != n:
        raise ValueError(f'reference sampler underfilled: {len(worlds)}/{n}')
    _, mask = actor_features(rnd, seat)
    rows, unique = [], set()
    for hands, kitty in worlds:
        # Reject the legacy sampler's possible void-relaxation fallback rather
        # than silently benchmarking against physically impossible hands.
        if any(rnd.ordering.eff_suit(c) in memory.voids[s]
               for s in range(4) for c in hands[s]):
            raise ValueError('reference world violates a proven void')
        counts = np.stack([_counts(hands[(seat+r) % 4]) for r in range(1, 4)] + [_counts(kitty)])
        if not np.take_along_axis(mask, counts[..., None], -1).all():
            raise ValueError('reference world violates count mask')
        if Counter(c for hand in hands for c in hand) + Counter(kitty) + memory.played != Counter(make_deck()):
            raise ValueError('reference physical conservation differs')
        rows.append(counts)
        unique.add(counts.tobytes())
    counts = np.stack(rows)
    p, correction = empirical_count_probabilities(counts)
    return {'probabilities': p, 'brier_correction': correction, 'counts': counts,
            'worlds': n, 'attempts': attempts, 'unique_worlds': len(unique),
            'wall_seconds': time.monotonic()-started}
