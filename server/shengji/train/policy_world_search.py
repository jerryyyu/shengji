"""DEV public-information policy aggregation. No value calls or rollouts.

Every enumerated candidate is scored on the SAME sampled worlds. These are mean card
log-odds preferences, not expected returns or confidence bounds on returns.
Not registered as a production policy.
"""
from __future__ import annotations

import time
import numpy as np

from ..ai.heuristic import HeuristicBot
from ..ai.mcbot import MCBot
from ..ai.memory import Memory
from ..ai.cwv_policy import sample_worlds
from ..harvest.legal import enumerate_legal
from .cwv_prior_admission import CWVPriorAdmissionBot, load_prior_checked, root_clone


class PolicyWorldBot(HeuristicBot):
    """Heuristic declare/bury; batched mean policy scores for card play.

    ``predict`` is a batch log-odds callable, injectable for privacy/parity tests.
    Sampling is bounded and refuses incomplete work instead of silently changing
    W. The external screen must supply its total-play deadline.
    """

    def __init__(self, predict, *, worlds=4, cap=4000, seed=0):
        super().__init__()
        if type(worlds) is not int or not 1 <= worlds <= 256:
            raise ValueError('worlds must be an integer in [1,256]')
        if type(cap) is not int or cap < 1:
            raise ValueError('cap must be positive')
        self.predict = predict
        self.worlds, self.cap = worlds, cap
        self.sampler = MCBot(seed=seed)
        self.last_decision_record = None

    @classmethod
    def from_checkpoint(cls, path, sha256, **kwargs):
        # Reuse production's checked loading and all supported prior adapters.
        class Adapter:
            _prior_log_odds = CWVPriorAdmissionBot._prior_log_odds
        adapter = Adapter()
        adapter._prior_kind, adapter._prior_net, adapter._prior_payload = load_prior_checked(path, sha256)
        return cls(adapter._prior_log_odds, **kwargs)

    def _worlds(self, rnd, seat):
        mem = Memory(rnd, seat, own_kitty=getattr(self.sampler, 'BANKER_KITTY', True))
        # Production owns attempt bounds, conservation checks, and canonical
        # card ordering. Do not duplicate its private sampler pipeline here.
        worlds, attempts = sample_worlds(self.sampler, rnd, seat, self.worlds, mem=mem)
        if len(worlds) != self.worlds:
            raise RuntimeError(f'policy world sampling short: {len(worlds)}/{self.worlds}')
        # Legacy sampling may relax voids. Refuse the entire decision rather
        # than silently filter/replenish worlds with a different attempt budget.
        if any(rnd.ordering.eff_suit(c) in mem.voids[s]
               for hands, _ in worlds for s in range(4) if s != seat for c in hands[s]):
            raise RuntimeError('policy world sampling violates public voids')
        return worlds, attempts

    def scores(self, rnd, seat, actions, worlds):
        """Batch each sampled state once; never encode the live hidden world."""
        from .policy_prior import CARD_INDEX, N_CARDS, flat_input, root_tensors
        x = np.stack([flat_input(root_tensors(root_clone(rnd, hands, buried), seat))
                      for hands, buried in worlds]).astype(np.float32)
        logits = np.asarray(self.predict(x), dtype=np.float64)
        if logits.shape != (len(worlds), N_CARDS) or not np.isfinite(logits).all():
            raise ValueError('policy requires finite W x 54 log-odds')
        multiplicity = np.zeros((len(actions), N_CARDS), dtype=np.float64)
        for i, action in enumerate(actions):
            for card in action:
                multiplicity[i, CARD_INDEX[card]] += 1
        return logits @ multiplicity.T

    def decide_play(self, rnd, seat):
        self.last_decision_record = None
        start = time.perf_counter()
        fallback = super().decide_play(rnd, seat)
        legal = enumerate_legal(rnd, seat, cap=self.cap, must_include=[fallback])
        actions = list(legal.actions)
        sampled, attempts = self._worlds(rnd, seat)
        values = self.scores(rnd, seat, actions, sampled)
        means = values.mean(axis=0)
        index = int(np.argmax(means))  # deterministic enumeration-order ties
        self.last_decision_record = {
            'schema': 'policy-world-mean-v1', 'worlds':len(sampled),
            'sample_attempts':attempts, 'actions':len(actions), 'cap':self.cap,
            'legal_count':legal.count, 'legal_complete':legal.complete,
            'selected_index':index, 'selected_mean_score':float(means[index]),
            'seconds':time.perf_counter()-start,
        }
        return list(actions[index])
