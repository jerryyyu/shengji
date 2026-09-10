"""DEV-only finite-pool belief sampler used by every W32 play fold.

This is NOT an exact joint posterior. A corrected legal proposal supplies a
fixed pool per decision; bounded marginal matching reweights that pool. Ranking,
selection and reporting draw with replacement from it using their existing RNG
streams. Draws are conditionally independent given the pool, but share finite-
pool approximation error. A uniform-pool control isolates this support change.
No registry/default, declaration, bury or rollout-policy changes occur here.
"""
from collections import Counter
import time

import numpy as np

from ..ai.mcbot import MCBot, _child_seed
from ..engine.cards import make_deck
from .banker_kitty_sampler import banker_kitty_bounds, supported_bot_class
from .simple_belief_features import _counts, actor_features
from .world_mixture_fit import fit_world_mixture


def checked_world(rnd, seat, mem, sampled, allowed):
    """Validate sampled objects against actor-visible facts, never true hands."""
    others, kitty = sampled
    expected = {s for s in range(4) if s != seat}
    if set(others) != expected or len(kitty) != 8:
        raise ValueError('belief sampled receiver population differs')
    hands = [list(rnd.hands[seat]) if s == seat else list(others[s]) for s in range(4)]
    if any(len(hands[s]) != 25-sum(mem.played_by[s].values()) for s in range(4)):
        raise ValueError('belief sampled public hand size differs')
    if Counter(c for hand in hands for c in hand) + Counter(kitty) + mem.played != Counter(make_deck()):
        raise ValueError('belief sampled physical conservation differs')
    if seat == rnd.banker and Counter(kitty) != Counter(rnd.buried):
        raise ValueError('belief sampled banker private kitty differs')
    if any(rnd.ordering.eff_suit(c) in mem.voids[s] for s in range(4) for c in hands[s]):
        raise ValueError('belief sampled proven void differs')
    counts = np.stack([_counts(hands[(seat+r) % 4]) for r in range(1, 4)] + [_counts(kitty)])
    if (counts > 2).any() or not np.take_along_axis(allowed, counts[..., None], -1).all():
        raise ValueError('belief sampled hard count constraint differs')
    union = Counter(hands[rnd.banker]) + Counter(kitty)
    if any(union[c] < n for c, n in banker_kitty_bounds(rnd, seat, mem).items()):
        raise ValueError('belief sampled banker declaration union differs')
    return hands, list(kitty), counts


class BeliefPoolMixin:
    """Place before CWVBuryBot; predictor(rnd, seat) returns 4x54x3 marginals.

    ``ordinary`` uses the corrected sampler directly with strict fact checks;
    ``uniform-pool`` and ``learned-pool`` use identical pool construction. Pool
    proposal work is recorded separately from delivered MC world counters.
    """

    def __init__(self, *args, belief_mode='ordinary', belief_predictor=None,
                 belief_pool_size=128, belief_fit_iterations=500, **kwargs):
        if belief_mode not in ('ordinary', 'uniform-pool', 'learned-pool'):
            raise ValueError('unknown belief sampler mode')
        if type(belief_pool_size) is not int or belief_pool_size < 2:
            raise ValueError('belief pool needs at least two worlds')
        if type(belief_fit_iterations) is not int or not 1 <= belief_fit_iterations <= 2000:
            raise ValueError('belief fit iteration bound invalid')
        if (belief_mode == 'learned-pool') != callable(belief_predictor):
            raise ValueError('only learned-pool requires a predictor')
        self.belief_mode = belief_mode
        self.belief_predictor = belief_predictor
        self.belief_pool_size = belief_pool_size
        self.belief_fit_iterations = belief_fit_iterations
        self._belief_pool = None
        self._belief_allowed = None
        self.last_belief = None
        super().__init__(*args, **kwargs)

    def decide_play(self, rnd, seat):
        self._belief_pool = None
        self._belief_allowed = None
        self.last_belief = {'mode': self.belief_mode, 'delivered': 0,
                            'strict_rejections': 0, 'drawn_pool_indices': set()}
        action = super().decide_play(rnd, seat)
        self.last_belief['unique_pool_indices_drawn'] = len(self.last_belief.pop('drawn_pool_indices'))
        if self.last_decision_record is not None:
            self.last_decision_record['belief_sampler'] = dict(self.last_belief)
        return action

    def _prepare_belief_pool(self, rnd, seat, mem):
        started = time.monotonic()
        # Independent proposal stream: never advance ranking/selection/report
        # RNG to build the support, and never use true deal/target metadata.
        helper = supported_bot_class(MCBot)(seed=_child_seed(self.rng.getstate(), 'belief-legal-pool-v1'))
        pool, counts, rejected = [], [], 0
        for _ in range(self.belief_pool_size * helper.SAMPLE_ATTEMPT_FACTOR):
            sampled = helper._sample_hands(rnd, seat, mem)
            if sampled is None:
                continue
            try:
                hands, kitty, row = checked_world(rnd, seat, mem, sampled, self._belief_allowed)
            except ValueError:
                rejected += 1
                continue
            pool.append((tuple(tuple(sorted(h)) for h in hands), tuple(sorted(kitty))))
            counts.append(row)
            if len(pool) == self.belief_pool_size:
                break
        if len(pool) != self.belief_pool_size:
            raise ValueError(f'belief legal pool underfilled: {len(pool)}/{self.belief_pool_size}')
        self.last_belief.update(proposal_attempts=helper.sample_attempts,
                               invalid_proposals=rejected, pool_worlds=len(pool),
                               unique_pool_worlds=len(set(pool)))
        weights = np.full(len(pool), 1/len(pool))
        if self.belief_mode == 'learned-pool':
            inference = time.monotonic()
            p = np.asarray(self.belief_predictor(rnd, seat), dtype=np.float64)
            if p.shape != (4, 54, 3) or not np.isfinite(p).all() or (p < 0).any() \
                    or not np.allclose(p.sum(axis=-1), 1, atol=1e-7, rtol=0):
                raise ValueError('belief predictor count probabilities invalid')
            p = p / p.sum(axis=-1, keepdims=True)
            self.last_belief['inference_seconds'] = time.monotonic()-inference
            uncertain = self._belief_allowed.sum(axis=-1) > 1
            if uncertain.any():
                fit = fit_world_mixture(np.asarray(counts)[:, uncertain], p[uncertain],
                                        iterations=self.belief_fit_iterations)
                weights = np.asarray(fit.pop('weights'))
                self.last_belief['fit'] = fit
        self._belief_pool = pool, np.cumsum(weights).tolist()
        self._belief_pool[1][-1] = 1.0
        self.last_belief['pool_seconds'] = time.monotonic()-started

    def _sample_hands(self, rnd, seat, mem):
        if self._belief_allowed is None:
            _, self._belief_allowed = actor_features(rnd, seat)
        if self.last_belief is None:
            self.last_belief = {'mode': self.belief_mode, 'delivered': 0,
                                'strict_rejections': 0, 'drawn_pool_indices': set()}
        if self.belief_mode == 'ordinary':
            impossible_before = self.impossible_worlds
            sampled = super()._sample_hands(rnd, seat, mem)
            if sampled is None:
                return None
            try:
                checked_world(rnd, seat, mem, sampled, self._belief_allowed)
            except ValueError:
                self.accepted_worlds -= 1
                self.failed_worlds += 1
                self.rejected_worlds += 1
                self.impossible_worlds = impossible_before
                self.reject_cause['belief_strict_facts'] += 1
                self.last_belief['strict_rejections'] += 1
                return None
        else:
            if self._belief_pool is None:
                self._prepare_belief_pool(rnd, seat, mem)
            pool, cumulative = self._belief_pool
            index = self.rng.choices(range(len(pool)), cum_weights=cumulative, k=1)[0]
            hands, kitty = pool[index]
            # Fresh mutable containers: a rollout cannot poison future draws.
            sampled = {s: list(hands[s]) for s in range(4) if s != seat}, list(kitty)
            self.sample_attempts += 1
            self.accepted_worlds += 1
            self.last_belief['drawn_pool_indices'].add(index)
        self.last_belief['delivered'] += 1
        return sampled


def belief_bot_class(base):
    return type(f'BeliefPool{base.__name__}', (BeliefPoolMixin, supported_bot_class(base)), {})


class SmallBeliefPredictor:
    """Load once, then expose only the actor-feature path to the small model."""

    def __init__(self, checkpoint, cache_recipe_sha256):
        from pathlib import Path
        from .simple_belief_features import FEATURE_DIM
        from .simple_belief_model import SimpleBeliefMLP
        from .simple_belief_train import _load_checkpoint
        payload = _load_checkpoint(Path(checkpoint), cache_recipe_sha256)
        self.model = SimpleBeliefMLP(FEATURE_DIM, payload['config']['width'], payload['config']['hidden'])
        self.model.load_state_dict(payload['model'])
        self.model.eval()

    def __call__(self, rnd, seat):
        import torch
        from .simple_belief_model import masked_count_probabilities
        features, allowed = actor_features(rnd, seat)
        with torch.inference_mode():
            return masked_count_probabilities(self.model(torch.from_numpy(features[None])),
                                              torch.from_numpy(allowed[None]))[0].numpy()
