import copy

import numpy as np
import pytest

from shengji.ai.cwv_policy import sample_worlds
from shengji.ai.mcbot import MCBot
from shengji.ai.memory import Memory
from shengji.train.simple_belief_features import actor_features
from shengji.train.simple_belief_sampler import belief_bot_class, checked_world
from test_banker_kitty_sampler import declared_round


def test_pool_hidden_twins_and_draws_are_valid_and_independent_containers():
    rnd, code = declared_round()
    twin = copy.deepcopy(rnd)
    i = twin.buried.index(code)
    twin.buried[i], twin.hands[0][0] = twin.hands[0][0], twin.buried[i]
    cls = belief_bot_class(MCBot)
    first = cls(seed=19, belief_mode='uniform-pool', belief_pool_size=32)
    second = cls(seed=19, belief_mode='uniform-pool', belief_pool_size=32)
    a, _ = sample_worlds(first, rnd, 1, 80)
    b, _ = sample_worlds(second, twin, 1, 80)
    assert a == b
    assert first._belief_pool == second._belief_pool
    assert first.last_belief['delivered'] == first.accepted_worlds == 80
    assert first.last_belief['unique_pool_worlds'] > 1
    assert any(not hands[0].count(code) and kitty.count(code) for hands, kitty in a)
    mem = Memory(rnd, 1)
    _, mask = actor_features(rnd, 1)
    for hands, kitty in a:
        checked_world(rnd, 1, mem, ({s: hands[s] for s in (0, 2, 3)}, kitty), mask)
    pool_before = copy.deepcopy(first._belief_pool)
    a[0][0][0].clear()
    assert first._belief_pool == pool_before


def test_learned_weights_change_draw_law_not_legal_support():
    rnd, _ = declared_round()
    def predicts(r, seat):
        _, mask = actor_features(r, seat)
        p = mask.astype(float) * np.array([1., 4., .1])
        return p/p.sum(axis=-1, keepdims=True)
    cls = belief_bot_class(MCBot)
    uniform = cls(seed=13, belief_mode='uniform-pool', belief_pool_size=32)
    learned = cls(seed=13, belief_mode='learned-pool', belief_pool_size=32, belief_predictor=predicts)
    a, _ = sample_worlds(uniform, rnd, 1, 80)
    b, _ = sample_worlds(learned, rnd, 1, 80)
    assert uniform._belief_pool[0] == learned._belief_pool[0]
    assert a != b
    fit = learned.last_belief['fit']
    assert fit['ess_fraction'] >= .5-1e-9
    assert fit['max_weight'] <= 4/32+1e-9
    assert fit['guarded_fit_model_squared_error'] < fit['uniform_model_squared_error']


def test_float32_probability_rounding_reaches_consumer_but_bad_mass_refuses():
    rnd, _ = declared_round()
    # Actual first bad baseline-state prediction from the retained model.
    row = np.asarray([0.42222699522972107, 0.3814769983291626,
                      0.19629590213298798], dtype=np.float32)
    assert abs(row.astype(float).sum()-1) > 1e-7
    cls = belief_bot_class(MCBot)
    def make(offset):
        p = np.broadcast_to(row, (4, 54, 3)).copy()
        p[..., 0] += offset
        return cls(seed=17, belief_mode='learned-pool', belief_pool_size=4,
                   belief_fit_iterations=1, belief_predictor=lambda *a: p)
    bot = make(0)
    worlds, _ = sample_worlds(bot, rnd, 1, 2)
    assert len(worlds) == bot.last_belief['delivered'] == 2
    assert bot.last_belief['fit']['iterations'] == 1
    with pytest.raises(ValueError, match='^belief predictor count probabilities invalid$'):
        sample_worlds(make(.001), rnd, 1, 2)


@pytest.mark.parametrize('mode', ['ordinary', 'uniform-pool', 'learned-pool'])
def test_actual_w32_ranking_selection_and_report_receive_sampler(mode, monkeypatch):
    from shengji.train.cwv_bury_policy import CWVBuryBot
    from shengji.train.cwv_shortlist import CWVShortlistConfig
    import shengji.train.cwv_shortlist as shortlist
    import shengji.train.simple_belief_features as features
    monkeypatch.setattr(features, 'ownership_targets', lambda *a: pytest.fail('privileged target entered inference'))
    rnd, _ = declared_round()
    class Values:
        def score(self, positions, seat, **kwargs):
            return [float(r.attacker_points) for r in positions]
    def predicts(r, seat):
        _, mask = actor_features(r, seat)
        return mask/mask.sum(axis=-1, keepdims=True)
    bot = belief_bot_class(CWVBuryBot)(Values(), seed=17, arm='hybrid',
        config=CWVShortlistConfig(worlds=4, selection_worlds=4, alternatives=4),
        reuse_successors=True, belief_mode=mode, belief_pool_size=16,
        belief_predictor=predicts if mode == 'learned-pool' else None)
    bot.REPORT_FOLD_WORLDS = 30
    ranking, rollouts = [], []
    original = shortlist.sample_worlds
    def capture(*args, **kwargs):
        result = original(*args, **kwargs)
        ranking.extend(result[0])
        return result
    monkeypatch.setattr(shortlist, 'sample_worlds', capture)
    def rollout(r, s, hands, buried, action, **kwargs):
        rollouts.append((hands, buried))
        return float(sum(ord(c) for card in action for c in card))
    monkeypatch.setattr(bot, '_rollout', rollout)
    assert bot.decide_play(rnd, 1)
    assert len(ranking) == 4 and len(rollouts) >= 30
    assert bot.last_decision_record['belief_sampler']['delivered'] == bot.accepted_worlds > 4
    assert bot.sample_attempts == bot.accepted_worlds + bot.failed_worlds
    assert bot.last_decision_record['report_fold']
    mem = Memory(rnd, 1)
    _, mask = actor_features(rnd, 1)
    for hands, kitty in ranking+rollouts:
        sampled = hands if isinstance(hands, dict) else {s: hands[s] for s in (0, 2, 3)}
        checked_world(rnd, 1, mem, (sampled, kitty), mask)
    if mode != 'ordinary':
        assert bot.last_belief['pool_worlds'] == 16
        assert bot.last_belief['unique_pool_indices_drawn'] <= 16


def test_invalid_pool_proposals_refuse_not_silent_fallback(monkeypatch):
    rnd, _ = declared_round()
    monkeypatch.setattr(MCBot, '_sample_hands', lambda *a: ({0: [], 2: [], 3: []}, []))
    bot = belief_bot_class(MCBot)(seed=1, belief_mode='uniform-pool', belief_pool_size=2)
    with pytest.raises(ValueError, match='^belief legal pool underfilled: 0/2$'):
        sample_worlds(bot, rnd, 1, 1)
    assert bot.accepted_worlds == 0


def test_strict_void_rejection_reaches_ordinary_consumer_counters(monkeypatch):
    rnd, _ = declared_round()
    mem = Memory(rnd, 1)
    source = belief_bot_class(MCBot)(seed=55)
    (hands, kitty), = sample_worlds(source, rnd, 1, 1)[0]
    other = 2
    mem.voids[other].add(rnd.ordering.eff_suit(hands[other][0]))
    def impossible(self, *args):
        self.sample_attempts += 1
        self.accepted_worlds += 1
        return {s: hands[s] for s in (0, 2, 3)}, kitty
    monkeypatch.setattr(MCBot, '_sample_hands', impossible)
    bot = belief_bot_class(MCBot)(seed=55)
    bot.SAMPLE_ATTEMPT_FACTOR = 2
    assert sample_worlds(bot, rnd, 1, 1, mem=mem) == ([], 2)
    assert bot.accepted_worlds == 0
    assert bot.failed_worlds == bot.rejected_worlds == 2
    assert bot.last_belief['strict_rejections'] == 2


def test_small_predictor_never_reads_hidden_inputs(monkeypatch):
    import torch
    import shengji.train.simple_belief_train as train
    import shengji.train.simple_belief_features as features
    from shengji.train.simple_belief_model import SimpleBeliefMLP
    from shengji.train.simple_belief_sampler import SmallBeliefPredictor
    model = SimpleBeliefMLP(features.FEATURE_DIM, 8, 4)
    monkeypatch.setattr(train, '_load_checkpoint', lambda *a: {
        'config': {'width': 8, 'hidden': 4}, 'model': model.state_dict()})
    monkeypatch.setattr(features, 'ownership_targets', lambda *a: pytest.fail('hidden target constructed'))
    predictor = SmallBeliefPredictor('/unused', 'unused')
    rnd, _ = declared_round()
    class SizeOnly:
        def __init__(self, n): self.n = n
        def __len__(self): return self.n
        def __iter__(self): raise AssertionError('hidden cards iterated')
    class Hands:
        def __getitem__(self, s):
            assert s == 1, 'hidden hand indexed'
            return rnd.hands[1]
        def __iter__(self):
            return iter([SizeOnly(len(h)) for h in rnd.hands])
    class View:
        hands = Hands()
        def __getattr__(self, name):
            assert name not in ('deck', 'buried', 'kitty', 'rng'), 'hidden input read'
            return getattr(rnd, name)
    torch.set_num_threads(1)
    np.testing.assert_array_equal(predictor(rnd, 1), predictor(View(), 1))
