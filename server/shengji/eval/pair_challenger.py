"""Exploratory fixed-width lead admission over omitted singles, pairs and
tractors; not a serving registry recipe.

The singleton challenger (`singleton_challenger`) prices the ballot plus the
omitted legal singletons on at most eight sampled worlds. This variant widens
the omitted pool to every one-component lead the engine's decomposition
classifies as a pair or a tractor. Throws (several components) stay out. The
one-slot rule is unchanged: the single best omitted candidate replaces the last
base slot only when it strictly beats the whole ballot on the proxy, so the
measured effect is the marginal value over the singleton pool. The full-world
scorer and reducer still choose the move.
"""
from collections import Counter

import numpy as np

from shengji.engine.combos import decompose
from shengji.eval.singleton_challenger import (_SingletonChallenger, challenger_from_env,
                                               load_challenger)
from shengji.train.pv_search_policy import PVSearchBot, PVSearchBuryBot

SUFFIX = '-sc8p'
#: the lead kinds the probe may admit; a throw never enters the pool
POOL_KINDS = ('single', 'pair', 'tractor')


def lead_kind(action, ordering):
    """``single`` / ``pair`` / ``tractor`` for a one-component lead, ``throw``
    for several components, by the engine's own decomposition. A pair or a
    tractor is a multiset of pairs, so an action with an unpaired card is a
    throw before any decomposition."""
    if len(action) == 1:
        return 'single'
    if len(action) % 2 or any(n != 2 for n in Counter(action).values()):
        return 'throw'
    components = decompose(list(action), ordering).components
    return components[0].kind if len(components) == 1 else 'throw'


class _PairChallenger(_SingletonChallenger):
    """The singleton challenger with pairs and tractors in its omitted pool."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.policy_name = 'research-pair-challenger-sc8p'
        self._pool_kind = {}

    def _omitted(self, rnd, actions, preferences, chosen):
        skip = set(chosen)
        self._pool_kind = {}
        for index, action in enumerate(actions):
            if index in skip or not np.isfinite(preferences[index]):
                continue
            kind = lead_kind(action, rnd.ordering)
            if kind in POOL_KINDS:
                self._pool_kind[index] = kind
        counts = Counter(self._pool_kind.values())
        self._singleton_probe['challenger_pool'] = {k: int(counts.get(k, 0)) for k in POOL_KINDS}
        return list(self._pool_kind)

    def _admit(self, rnd, seat, actions, preferences, anchor_index):
        chosen = super()._admit(rnd, seat, actions, preferences, anchor_index)
        if self._singleton_probe.get('singleton_challenger_applied'):
            self._singleton_probe['challenger_added_kind'] = self._pool_kind[chosen[-1]]
        return chosen


class PairChallengerBot(_PairChallenger, PVSearchBot):
    """Card-play candidate for a dedicated diagnostic."""


class PairChallengerBuryBot(_PairChallenger, PVSearchBuryBot):
    """The same lead candidate preserving the production bury consumer."""


def load_pair_challenger(*, name, **recipe):
    """Load a named baseline recipe through the production package loader
    under the distinct research name ``name + '-sc8p'``; no serving flag."""
    return load_challenger(name=name, suffix=SUFFIX, play_cls=PairChallengerBot,
                           bury_cls=PairChallengerBuryBot, **recipe)


def pair_candidate_from_env(environ, *, seed=0):
    """The pair challenger bound to the verified baseline serving recipe."""
    return challenger_from_env(environ, suffix=SUFFIX, play_cls=PairChallengerBot,
                               bury_cls=PairChallengerBuryBot, seed=seed)
