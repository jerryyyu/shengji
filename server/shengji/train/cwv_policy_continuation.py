"""DEV policy-head continuation on private sampled worlds; no registry entry.

The prior sees the simulated mover's determinized features. This is not a
public-only information-set policy and must not be used on a live hidden hand.
Root admission and the selection/report objectives are inherited unchanged.
"""
import numpy as np

from ..harvest.legal import enumerate_legal
from .cwv_truncated_search import CWVPriorTruncatedSearchBot


class PriorRolloutPolicy:
    def __init__(self, scores, *, fallback, stop_trick=None):
        self.scores, self.fallback, self.stop_trick = scores, fallback, stop_trick
        self.counts = dict(guided_plies=0, fallback_plies=0, prior_calls=0,
                           legal_actions=0)

    def decide_play(self, rnd, seat):
        if not getattr(rnd, '_determinized_world', False):
            raise ValueError('policy continuation requires a private sampled world')
        if rnd.phase != 'play' or seat != rnd.turn:
            raise ValueError('policy continuation requires the acting seat')
        if self.stop_trick is not None and len(rnd.history) >= self.stop_trick:
            self.counts['fallback_plies'] += 1
            return self.fallback.decide_play(rnd, seat)
        legal = enumerate_legal(rnd, seat, cap=None)
        if not legal.complete or not legal.actions:
            raise ValueError('policy continuation requires exhaustive legal actions')
        actions = legal.actions
        self.counts['guided_plies'] += 1
        self.counts['legal_actions'] += len(actions)
        if len(actions) == 1:
            return list(actions[0])
        logits = np.asarray(self.scores(rnd, seat, actions), dtype=float)
        if logits.shape != (len(actions),) or not np.isfinite(logits).all():
            raise ValueError('one finite prior score required per legal action')
        self.counts['prior_calls'] += 1
        # Stable enumerator-order ties, no stochastic policy/RNG confound.
        return list(actions[int(np.argmax(logits))])


class CWVPolicyContinuationBot(CWVPriorTruncatedSearchBot):
    def __init__(self, *args, guided_tricks=1, **kwargs):
        if guided_tricks is not None and (type(guided_tricks) is not int or guided_tricks < 0):
            raise ValueError('guided_tricks must be None or a nonnegative integer')
        super().__init__(*args, **kwargs)
        self.guided_tricks = guided_tricks
        self.policy_continuation_totals = dict(guided_plies=0, fallback_plies=0,
                                               prior_calls=0, legal_actions=0)

    def _continuation_prior(self, rnd, seat, actions):
        return self._prior_scores(rnd, seat, actions, [(rnd.hands, rnd.buried)])[0]

    def _continuation_matrix(self, rnd, seat, candidates, mem, n):
        original = self.rollout_policy
        stop = None if self.guided_tricks is None else len(rnd.history) + self.guided_tricks
        guide = PriorRolloutPolicy(self._continuation_prior, fallback=original, stop_trick=stop)
        # The guide is transient: immutable model assets remain factory-owned
        # and no self-referential callback crosses deadline checkpoint IPC.
        self.rollout_policy = guide
        try:
            return super()._continuation_matrix(rnd, seat, candidates, mem, n)
        finally:
            self.rollout_policy = original
            for key, count in guide.counts.items():
                self.policy_continuation_totals[key] += count
