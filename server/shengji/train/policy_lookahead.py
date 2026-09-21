"""DEV bounded continuation before root-team value evaluation.

Not a branching tree or minimax search. Complete the candidate's current trick
as in PolicyValueBot, then simulate up to four additional card plays. Every
policy continuation actor resamples from its own information through PolicyWorldBot;
it never encodes the surrounding simulated world's hidden hands directly. The
opt-in heuristic control makes the same number of additional plays without
policy inference or additional world sampling. Four plies from this boundary
complete one additional trick (or end the round early), not four extra tricks.
"""
from .policy_value_search import PolicyValueBot
from .policy_world_search import PolicyWorldBot
from ..ai.heuristic import HeuristicBot


class PolicyLookaheadBot(PolicyValueBot):
    def __init__(self, predict, *, extra_plies=4, continuation_worlds=1,
                 continuation_policy='policy', **kwargs):
        if continuation_policy not in ('policy', 'heuristic'):
            raise ValueError('continuation_policy must be policy or heuristic')
        for name, value, maximum in (('extra_plies', extra_plies, 4),
                                     ('continuation_worlds', continuation_worlds, 4)):
            if name == 'continuation_worlds' and continuation_policy == 'heuristic':
                if type(value) is not int or value != 0:
                    raise ValueError('heuristic continuation requires continuation_worlds=0')
                continue
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError(f'{name} must be an integer in [1,{maximum}]')
        self.continuation_seed = int(kwargs.get('seed', 0))
        super().__init__(predict, **kwargs)
        self.extra_plies = extra_plies
        self.continuation_worlds = continuation_worlds
        self.continuation_policy = continuation_policy
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
            bot = (PolicyWorldBot(self.predict, worlds=self.continuation_worlds,
                                  cap=self.cap, seed=seed)
                   if self.continuation_policy == 'policy' else HeuristicBot())
            cards = bot.decide_play(leaf, actor)
            record = (bot.last_decision_record if self.continuation_policy == 'policy'
                      else dict(worlds=0, sample_attempts=0, legal_complete=True))
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
        if self.continuation_policy != 'policy':
            # Keep the historical default record unchanged; identify the new arm.
            self.last_decision_record['schema'] = 'policy-admit-heuristic-lookahead-value-v1'
            self.last_decision_record['continuation_policy'] = 'heuristic'
        return action
