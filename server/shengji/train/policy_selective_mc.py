"""DEV close-gap verification: fresh-world heuristic MC on the top two values.

The gap is an uncalibrated selection heuristic, not a confidence interval.
No blending: either retain the value choice or select by mean MC terminal
utility on the SAME half-level support as CompleteWorldEvaluator.
"""
import math
import numpy as np

from ..rl.value_afterstate import signed_level_category, category_signed_level
from .policy_value_search import PolicyValueBot
from .policy_world_search import PolicyWorldBot


class PolicySelectiveMCBot(PolicyValueBot):
    def __init__(self, predict, *, verify_gap=.1, verify_worlds=8, **kwargs):
        if isinstance(verify_gap, bool) or not math.isfinite(verify_gap) or not 0 <= verify_gap <= 5:
            raise ValueError('verify_gap must be finite in [0,5]')
        super().__init__(predict, **kwargs)
        self.verify_gap = float(verify_gap)
        # Independent sampling stream from root admission/value evaluation.
        self.verifier = PolicyWorldBot(None, worlds=verify_worlds,
                                      seed=int(kwargs.get('seed', 0)) + 1000000007)
        self._verification = {}

    def _select(self, rnd, seat, admitted, means):
        ranked = sorted(range(len(admitted)), key=lambda i: (-means[i], i))
        winner = ranked[0]
        gap = float(means[winner] - means[ranked[1]]) if len(ranked) > 1 else None
        self._verification = dict(triggered=False, value_gap=gap, worlds=0,
                                  sample_attempts=0, rollouts=0)
        if gap is None or gap > self.verify_gap:
            return winner
        selected = ranked[:2]
        worlds, attempts = self.verifier._worlds(rnd, seat)
        bot = self.verifier.sampler
        if bot.EXACT_ENDGAME:
            raise ValueError('verification requires actual terminal rollout points')
        values = np.zeros(2, dtype=np.float64)
        for hands, buried in worlds:
            sampled = {s: hands[s] for s in range(4) if s != seat}
            for j, index in enumerate(selected):
                points = bot._rollout(rnd, seat, sampled, buried, list(admitted[index]))
                if not math.isfinite(points) or points != int(points):
                    raise ValueError('verification requires finite integer terminal points')
                values[j] += category_signed_level(
                    signed_level_category(int(points), rnd.is_attacker(seat)))
        values /= len(worlds)
        self._verification.update(triggered=True, worlds=len(worlds), sample_attempts=attempts,
                                  rollouts=2*len(worlds), admitted_indices=selected,
                                  mean_levels=values.tolist())
        # The value winner is first, so MC ties keep it.
        return selected[int(np.argmax(values))]

    def decide_play(self, rnd, seat):
        self._verification = {}
        action = super().decide_play(rnd, seat)
        self.last_decision_record.update(schema='policy-value-selective-mc-v1',
            verify_gap=self.verify_gap, verify_worlds=self.verifier.worlds,
            verification=dict(self._verification))
        return action
