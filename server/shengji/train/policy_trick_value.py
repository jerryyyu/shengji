"""DEV policy-guided current-trick continuation, then root-team value.

Same evaluation horizon as PolicyValueBot; only the response policy changes.
Not registered for production or added to the frozen strength screen.
"""
from ..ai.cwv_policy import afterstate
from .policy_value_search import PolicyValueBot
from .policy_world_search import PolicyWorldBot


class PolicyTrickValueBot(PolicyValueBot):
    def __init__(self, predict, *, continuation_worlds=1, **kwargs):
        if type(continuation_worlds) is not int or not 1 <= continuation_worlds <= 4:
            raise ValueError('continuation_worlds must be an integer in [1,4]')
        self.continuation_seed = int(kwargs.get('seed', 0))
        super().__init__(predict, **kwargs)
        self.continuation_worlds = continuation_worlds
        self._continuation_work = {}

    def _leaf(self, rnd, seat, hands, buried, action, world_index):
        leaf = afterstate(rnd, seat, hands, buried, action, finish_trick=False)
        ply = 0
        while leaf.phase == 'play' and leaf.trick is not None and leaf.trick.plays:
            if ply >= 3:
                raise RuntimeError('current trick did not resolve within three responses')
            actor = leaf.turn
            # Candidate-independent random streams; fresh actor-local sampling.
            # Do not hand the policy the outer root's sampled hidden holdings.
            bot = PolicyWorldBot(self.predict, worlds=self.continuation_worlds,
                cap=self.cap, seed=self.continuation_seed + 1000000007 + world_index*16 + ply*4 + actor)
            cards = bot.decide_play(leaf, actor)
            record = bot.last_decision_record
            for key, value in (('plies', 1), ('worlds', record['worlds']),
                               ('sample_attempts', record['sample_attempts']),
                               ('capped_decisions', int(not record['legal_complete']))):
                self._continuation_work[key] = self._continuation_work.get(key, 0) + value
            leaf.play(actor, cards)
            ply += 1
        return leaf

    def decide_play(self, rnd, seat):
        self._continuation_work = dict(plies=0, worlds=0, sample_attempts=0, capped_decisions=0)
        action = super().decide_play(rnd, seat)
        self.last_decision_record.update(schema='policy-trick-value-v1',
            continuation_worlds=self.continuation_worlds,
            continuation_work=dict(self._continuation_work))
        return action
