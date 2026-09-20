"""DEV MC-LCB with actor-public policy/value continuations to terminal score.

Not registered for production. Root candidate selection and terminal utility
remain the inherited MC-LCB algorithm. Inner sampling has an independent RNG;
each outer rollout restarts the same continuation stream (common random
numbers), so evaluating another candidate first cannot alter its simulation.
"""
from __future__ import annotations

from ..ai.registry import REGISTRY
from .policy_value_search import PolicyValueBot


class PublicPVContinuation:
    def __init__(self, bot: PolicyValueBot, seed: int):
        self.bot = bot
        self.seed = seed
        self.decisions = 0
        self.worlds = 0
        self.value_evaluations = 0
        self.legal_caps = 0
        self.sample_attempts = 0
        self.value_batches = 0

    def begin_rollout(self):
        # Never touch the enclosing MC sampler. Do not seed from sampled hidden
        # hands: those are not information available to the continuation actor.
        self.bot.sampler.rng.seed(self.seed)

    def decide_play(self, rnd, seat):
        # The inherited rollout marks clones trusted for the built-in heuristic.
        # Learned actions must pass normal follow validation in Round.play.
        rnd._trusted_rollout = False
        cards = self.bot.decide_play(rnd, seat)
        record = self.bot.last_decision_record
        self.decisions += 1
        self.worlds += record['worlds']
        self.value_evaluations += record['value_evaluations']
        self.legal_caps += not record['legal_complete']
        self.sample_attempts += record['sample_attempts']
        self.value_batches += record['value_batches']
        return cards


class MCPolicyValueRollout(REGISTRY['mc-s0-report-lcb']):
    """Identical MC root/report algorithm, replacing only continuation choices.

Use one instance per worker/seat, never concurrently. Declaration and burial
must be supplied by the duel's shared heuristic, as in the existing DEV suite.
    """

    def __init__(self, continuation: PolicyValueBot, *, seed=0):
        super().__init__(seed=seed)
        if self.EXACT_ENDGAME:
            raise ValueError('terminal-rollout experiment forbids exact endgame shortcut')
        self.rollout_policy = PublicPVContinuation(continuation, seed)

    def decide_play(self, rnd, seat):
        for key in ('decisions', 'worlds', 'value_evaluations', 'legal_caps',
                    'sample_attempts', 'value_batches'):
            setattr(self.rollout_policy, key, 0)
        return super().decide_play(rnd, seat)

    def _rollout(self, *args, **kwargs):
        self.rollout_policy.begin_rollout()
        return super()._rollout(*args, **kwargs)
