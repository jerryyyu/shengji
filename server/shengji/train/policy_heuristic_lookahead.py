"""DEV fixed-depth control: policy/value root, heuristic continuation.

Matches PolicyLookaheadBot's horizon without its policy-only W1 replies.
No extra sampling, branching, production registration, or launch defaults.
"""
from ..ai.heuristic import HeuristicBot
from .policy_value_search import PolicyValueBot


class PolicyHeuristicLookaheadBot(PolicyValueBot):
    def __init__(self, predict, *, extra_plies=4, **kwargs):
        if type(extra_plies) is not int or not 1 <= extra_plies <= 4:
            raise ValueError('extra_plies must be an integer in [1,4]')
        super().__init__(predict, **kwargs)
        self.extra_plies = extra_plies
        self._continuation_plies = 0

    def _leaf(self, rnd, seat, hands, buried, action, world_index):
        leaf = super()._leaf(rnd, seat, hands, buried, action, world_index)
        bot = HeuristicBot()
        for _ in range(self.extra_plies):
            if leaf.phase != 'play':
                break
            actor = leaf.turn
            leaf.play(actor, bot.decide_play(leaf, actor))
            self._continuation_plies += 1
        return leaf

    def decide_play(self, rnd, seat):
        self._continuation_plies = 0
        action = super().decide_play(rnd, seat)
        self.last_decision_record.update(
            schema='policy-admit-heuristic-lookahead-value-v1',
            extra_plies=self.extra_plies, continuation_worlds=0,
            continuation_work=dict(plies=self._continuation_plies, worlds=0,
                                   sample_attempts=0, capped_decisions=0))
        return action
