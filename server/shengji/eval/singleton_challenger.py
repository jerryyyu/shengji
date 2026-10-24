"""Exploratory fixed-width lead admission; not a serving registry recipe.

Up to eight existing belief worlds price the ballot and omitted singletons
with heuristic-finished leaves. A singleton must beat the entire ballot on
that proxy to replace its last base slot. The normal full-world scorer and
reducer still choose the move; the proxy never selects the played action.
"""
import numpy as np

from shengji.train.policy_value_search import PolicyValueBot, leading
from shengji.train.pv_search_policy import PVSearchBot, PVSearchBuryBot, make_pv_search_bot


class _SingletonChallenger:
    """Dedicated research bot with unchanged construction and serving deadlines."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.admit_forced_single or self.finish_lead_admission or self.small_joker_guard:
            raise ValueError('singleton challenger requires no forced extras or singleton guard')
        self.policy_name = 'research-singleton-challenger-sc8'
        self._singleton_probe = {}

    def _admit(self, rnd, seat, actions, preferences, anchor_index):
        chosen = super()._admit(rnd, seat, actions, preferences, anchor_index)
        self._singleton_probe = {'singleton_challenger_applied': False}
        if not leading(rnd) or max(map(len, rnd.hands)) <= 7 or len(chosen) < 2:
            return chosen
        omitted = [i for i, action in enumerate(actions)
                   if len(action) == 1 and i not in chosen and np.isfinite(preferences[i])]
        if not omitted:
            return chosen
        worlds, check_budget = self._admission_context
        if not worlds:
            raise ValueError('singleton challenger requires sampled worlds')
        probe_worlds = worlds[:8]
        indices = [*chosen, *omitted]
        sums = np.zeros(len(indices), dtype=np.float64)
        pending, slots = [], []
        evaluations = 0

        def flush():
            nonlocal evaluations
            if not pending:
                return
            if check_budget:
                check_budget()
            values = np.asarray(self.evaluator.score(pending, seat), dtype=np.float64)
            if values.shape != (len(pending),) or not np.isfinite(values).all():
                raise ValueError('singleton probe requires finite root-team values')
            np.add.at(sums, slots, values)
            evaluations += len(pending)
            pending.clear()
            slots.clear()
            if check_budget:
                check_budget()

        for world_index, (hands, buried) in enumerate(probe_worlds):
            if check_budget:
                check_budget()
            for slot, index in enumerate(indices):
                pending.append(PolicyValueBot._leaf(
                    self, rnd, seat, hands, buried, actions[index], world_index))
                slots.append(slot)
                if len(pending) == self.batch_size:
                    flush()
        flush()
        means = sums / len(probe_worlds)
        challenger_slot = len(chosen) + int(np.argmax(means[len(chosen):]))
        margin = float(means[challenger_slot] - max(means[:len(chosen)]))
        self._singleton_probe.update(singleton_probe_worlds=len(probe_worlds),
                                     singleton_probe_evaluations=evaluations,
                                     singleton_probe_margin=margin)
        if margin <= 0:
            return chosen
        challenger = indices[challenger_slot]
        self._singleton_probe.update(singleton_challenger_applied=True,
                                     singleton_challenger_added=list(actions[challenger]),
                                     singleton_challenger_removed=list(actions[chosen[-1]]))
        return [*chosen[:-1], challenger]

    def _admission_record(self):
        return {**super()._admission_record(), **self._singleton_probe}


class SingletonChallengerBot(_SingletonChallenger, PVSearchBot):
    """Card-play candidate for a dedicated diagnostic."""


class SingletonChallengerBuryBot(_SingletonChallenger, PVSearchBuryBot):
    """The same lead candidate preserving the production bury consumer."""


def load_singleton_challenger(*, name, **recipe):
    """Load a named baseline recipe through the production package loader.

    The caller supplies the baseline identity and its full recipe, including
    belief and bury packages. This entry point adds a distinct research name;
    it does not register a serving flag or mutate an existing bot.
    """
    def factory(*args, **kwargs):
        cls = SingletonChallengerBuryBot if 'bury_arm' in kwargs else SingletonChallengerBot
        return cls(*args, **kwargs)
    return make_pv_search_bot(**recipe, name=name + '-sc8', bot_factory=factory)
