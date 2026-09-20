import copy

import numpy as np
import pytest

from shengji.ai.mcbot import MCBot
from shengji.ai.registry import make_bot
from shengji.train.mc_policy_value_rollout import MCPolicyValueRollout
from shengji.train.policy_value_search import PolicyValueBot
from test_policy_world_search import state


def continuation(traces=None):
    class Value:
        def score(self, leaves, seat):
            return np.zeros(len(leaves))
    def predict(x):
        if traces is not None:
            traces.append(x.copy())
        return np.zeros((len(x), 54))
    return PolicyValueBot(predict, evaluator=Value(), worlds=1, candidates=2)


def test_root_settings_unchanged():
    candidate = MCPolicyValueRollout(continuation(), seed=7)
    control = make_bot('mc-s0-report-lcb', seed=7)
    for key in dir(control):
        if key.isupper() and not key.startswith('_'):
            assert getattr(candidate, key) == getattr(control, key), key
    assert candidate.rng.getstate() == control.rng.getstate()
    assert candidate.rollout_policy.bot.sampler.rng.getstate() != candidate.rng.getstate()
    candidate.rollout_policy.begin_rollout()
    assert candidate.rollout_policy.bot.sampler.rng.getstate() != candidate.rng.getstate()


def test_each_rollout_restarts_inner_stream_without_touching_root(monkeypatch):
    bot = MCPolicyValueRollout(continuation(), seed=7)
    before = bot.rng.getstate()
    monkeypatch.setattr(MCBot, '_rollout', lambda self, *a, **k:
                        [self.rollout_policy.bot.sampler.rng.random() for _ in range(4)])
    first = bot._rollout()
    bot.rollout_policy.bot.sampler.rng.random()
    assert bot._rollout() == first
    assert bot.rng.getstate() == before


def test_actor_public_inputs_and_action_ignore_outer_hidden_hands():
    rnd = state()
    seat = rnd.turn
    changed = copy.deepcopy(rnd)
    others = [s for s in range(4) if s != seat]
    changed.hands[others[0]], changed.hands[others[1]] = (
        changed.hands[others[1]], changed.hands[others[0]])
    traces = []
    bot = MCPolicyValueRollout(continuation(traces), seed=17)
    policy = bot.rollout_policy
    policy.begin_rollout()
    first = policy.decide_play(rnd, seat)
    policy.begin_rollout()
    second = policy.decide_play(changed, seat)
    assert first == second
    assert np.array_equal(traces[0], traces[1])
    assert not rnd._trusted_rollout
    assert policy.decisions == 2 and policy.worlds == 2
    assert policy.value_evaluations >= 2


def test_real_rollout_reaches_terminal_and_preserves_live_round(monkeypatch):
    from shengji.ai.heuristic import HeuristicBot
    rnd = state()
    # Ordering memoizes card comparisons; its caches are not game state.
    before = copy.deepcopy({k: v for k, v in rnd.__dict__.items() if k != 'ordering'})
    seat = rnd.turn
    bot = MCPolicyValueRollout(continuation(), seed=19)
    action = HeuristicBot().decide_play(rnd, seat)
    terminal_scores = []
    original_play = type(rnd).play
    def tracked_play(self, actor, cards):
        result = original_play(self, actor, cards)
        if self.phase != 'play':
            terminal_scores.append(float(self.attacker_points))
        return result
    monkeypatch.setattr(type(rnd), 'play', tracked_play)
    # Outer world may know all hands; inner continuation still re-samples from
    # each actor's observation. No model is consulted for outer final scoring.
    value = bot._rollout(rnd, seat,
                        {s: list(rnd.hands[s]) for s in range(4) if s != seat},
                        list(rnd.buried), action)
    assert terminal_scores and value == terminal_scores[-1]
    assert bot.rollout_policy.decisions > 0
    assert {k: v for k, v in rnd.__dict__.items() if k != 'ordering'} == before


def test_harness_factory_and_work_accounting(monkeypatch):
    from shengji.train import policy_world_duel as duel
    inner = continuation()
    monkeypatch.setattr(duel, '_value_evaluator', lambda *a: inner.evaluator)
    monkeypatch.setattr(PolicyValueBot, 'from_checkpoint', lambda *a, **k: inner)
    bot = duel.make_policy('unused', 'a' * 64, 4, 7, 'mc-policy-value-rollout', 8)
    assert isinstance(bot, MCPolicyValueRollout)
    bot.last_alloc = {'worlds': 30, 'rollouts': 90, 'attempts': 31}
    bot.rollout_policy.decisions = 100
    bot.rollout_policy.worlds = 400
    bot.rollout_policy.value_evaluations = 3200
    side = duel._empty_side()
    duel._record_decision(side, 1., duel._decision_telemetry(bot, 'control'), 'control')
    assert side['continuation_plies'] == 100
    assert side['continuation_worlds'] == 400
    assert side['value_evaluations'] == 3200
    assert side['mc_last_alloc']['worlds'] == 30
    row = {'seed': 7, 'utility': 0., 'error': None,
           'sides': {'policy': side, 'control': duel._empty_side()}}
    summary = duel.aggregate_records([row], [7])
    assert summary['policy']['mc_last_alloc']['rollouts'] == 90
    assert summary['policy']['continuation_worlds'] == 400


def test_harness_rejects_unmatched_control():
    from shengji.train import policy_world_duel as duel
    args = duel.build_parser().parse_args([
        '--checkpoint', 'unused', '--checkpoint-sha256', 'a' * 64,
        '--out', 'unused', '--seed0', '7', '--mode', 'mc-policy-value-rollout',
        '--control', 'mc-smart4'])
    with pytest.raises(ValueError, match='matched mc-lcb'):
        duel._validate_args(args)


def test_nonbanker_hidden_kitty_and_prior_rng_consumption_are_invisible():
    from shengji.ai.heuristic import HeuristicBot
    rnd = state()
    rnd.play(rnd.turn, HeuristicBot().decide_play(rnd, rnd.turn))
    seat = rnd.turn
    assert seat != rnd.banker
    changed = copy.deepcopy(rnd)
    other = next(s for s in range(4) if s != seat)
    changed.buried[0], changed.hands[other][-1] = (
        changed.hands[other][-1], changed.buried[0])
    traces = []
    bot = MCPolicyValueRollout(continuation(traces), seed=29)
    first = bot.rollout_policy.decide_play(rnd, seat)
    # Mimic a previous actor needing a different number of private sampling
    # attempts. This must not influence the next actor at the same observation.
    for _ in range(103):
        bot.rollout_policy.bot.sampler.rng.random()
    second = bot.rollout_policy.decide_play(changed, seat)
    assert first == second
    assert np.array_equal(traces[0], traces[1])
