"""DEV bounded policy continuation before root-team value evaluation.

Not a branching tree or minimax search. Complete the candidate's current trick
as in PolicyValueBot, then simulate up to four additional card plays. Every
continuation actor resamples from its own information through PolicyWorldBot;
it never encodes the surrounding simulated world's hidden hands directly.
"""
from .policy_value_search import PolicyValueBot
from .policy_world_search import PolicyWorldBot


class PolicyLookaheadBot(PolicyValueBot):
    def __init__(self, predict, *, extra_plies=4, continuation_worlds=1, **kwargs):
        for name, value, maximum in (('extra_plies', extra_plies, 4),
                                     ('continuation_worlds', continuation_worlds, 4)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f'{name} must be an integer in [1,{maximum}]')
        self.continuation_seed = int(kwargs.get('seed', 0))
        super().__init__(predict, **kwargs)
        self.extra_plies = extra_plies
        self.continuation_worlds = continuation_worlds
        self._continuation_work = {}

    def _leaf(self, rnd, seat, hands, buried, action, world_index):
        leaf = super()._leaf(rnd, seat, hands, buried, action, world_index)
        for ply in range(self.extra_plies):
            if leaf.phase != 'play':
                break
            actor = leaf.turn
            # Same seed for a given world/ply/actor across candidates. Candidate
            # ordering therefore cannot consume different random streams.
            seed = self.continuation_seed + world_index * 16 + ply * 4 + actor
            bot = PolicyWorldBot(self.predict, worlds=self.continuation_worlds,
                                 cap=self.cap, seed=seed)
            cards = bot.decide_play(leaf, actor)
            record = bot.last_decision_record
            for key, value in (('plies', 1), ('worlds', record['worlds']),
                               ('sample_attempts', record['sample_attempts']),
                               ('capped_decisions', int(not record['legal_complete']))):
                self._continuation_work[key] = self._continuation_work.get(key, 0) + value
            leaf.play(actor, cards)
        return leaf

    def decide_play(self, rnd, seat):
        self._continuation_work = dict(plies=0, worlds=0, sample_attempts=0,
                                      capped_decisions=0)
        action = super().decide_play(rnd, seat)
        self.last_decision_record.update(
            schema='policy-admit-lookahead-value-v1', extra_plies=self.extra_plies,
            continuation_worlds=self.continuation_worlds,
            continuation_work=dict(self._continuation_work))
        return action
