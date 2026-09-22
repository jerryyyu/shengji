"""DEV policy admission followed by sampled-world value choice, without MC.

This is a policy change, not a decision-preserving optimization. The value
contract matches CWV shortlist: apply the candidate, heuristically finish the
current trick, and evaluate from the root team's perspective.
"""
from __future__ import annotations

import time
import numpy as np

from ..ai.cwv_policy import afterstate
from ..ai.heuristic import HeuristicBot
from ..harvest.legal import enumerate_legal
from .policy_world_search import PolicyWorldBot


class PolicyValueBot(PolicyWorldBot):
    def __init__(self, predict, *, evaluator, candidates=8, batch_size=128, **kwargs):
        super().__init__(predict, **kwargs)
        if evaluator is None:
            raise ValueError('value evaluator required')
        for name, value in (('candidates', candidates), ('batch_size', batch_size)):
            if type(value) is not int or not 1 <= value <= 512:
                raise ValueError(f'{name} must be an integer in [1,512]')
        self.evaluator = evaluator
        self.candidates = candidates
        self.batch_size = batch_size

    def _leaf(self, rnd, seat, hands, buried, action, world_index):
        return afterstate(rnd, seat, hands, buried, action, finish_trick=True)

    def _value_means(self, rnd, seat, actions, worlds):
        sums = np.zeros(len(actions), dtype=np.float64)
        pending, indices = [], []
        batches = 0

        def flush():
            nonlocal batches
            if not pending:
                return
            scores = np.asarray(self.evaluator.score(pending, seat), dtype=np.float64)
            if scores.shape != (len(pending),) or not np.isfinite(scores).all():
                raise ValueError('value evaluator requires one finite root-team score per leaf')
            np.add.at(sums, indices, scores)
            batches += 1
            pending.clear()
            indices.clear()

        for world_index, (hands, buried) in enumerate(worlds):
            for index, action in enumerate(actions):
                pending.append(self._leaf(rnd, seat, hands, buried, action, world_index))
                indices.append(index)
                if len(pending) == self.batch_size:
                    flush()
        flush()
        return sums / len(worlds), batches

    def _select(self, rnd, seat, admitted, means):
        return int(np.argmax(means))  # anchor retained on an exact value tie

    def decide_play(self, rnd, seat):
        self.last_decision_record = None
        self.last_world_diversity = None
        started = time.perf_counter()
        anchor = HeuristicBot().decide_play(rnd, seat)
        legal = enumerate_legal(rnd, seat, cap=self.cap, must_include=[anchor])
        actions = list(legal.actions)
        worlds, attempts = self._worlds(rnd, seat)
        diversity = self.last_world_diversity
        preferences = self.scores(rnd, seat, actions, worlds).mean(axis=0)
        # The anchor occupies one slot. Ties follow enumeration order. Compare
        # card multisets because the heuristic need not return canonical order.
        anchor_key = tuple(sorted(anchor))
        anchor_index = next(i for i, a in enumerate(actions)
                            if tuple(sorted(a)) == anchor_key)
        ranked = sorted(range(len(actions)), key=lambda i: (-preferences[i], i))
        chosen = [anchor_index]
        chosen.extend(i for i in ranked if i != anchor_index)
        chosen = chosen[:self.candidates]
        admitted = [actions[i] for i in chosen]
        means, batches = self._value_means(rnd, seat, admitted, worlds)
        winner = self._select(rnd, seat, admitted, means)
        self.last_decision_record = {
            'schema': 'policy-admit-value-mean-v1', 'worlds': len(worlds),
            'sample_attempts': attempts, 'actions': len(actions), 'cap': self.cap,
            'world_diversity': diversity,
            'legal_count': legal.count, 'legal_complete': legal.complete,
            'admitted_indices': chosen, 'value_means': means.tolist(),
            'selected_index': chosen[winner], 'value_batches': batches,
            'value_evaluations': len(worlds) * len(admitted),
            'seconds': time.perf_counter() - started,
        }
        return list(admitted[winner])
