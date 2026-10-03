"""World diversity is a diagnostic; repeated samples keep their vote weight."""
import copy
from types import SimpleNamespace

import numpy as np
import pytest

from shengji.train import policy_world_search as world
from shengji.train import policy_world_duel as duel
from shengji.train.policy_value_search import PolicyValueBot
from test_policy_world_search import state


def test_multisets_preserve_seats_kitty_and_duplicate_cards():
    first = ([['S2', 'S2', 'S3'], ['H2'], ['D2'], ['C2']], ['H3', 'H4'])
    reordered = copy.deepcopy(first)
    reordered[0][0].reverse()
    reordered[1].reverse()
    swapped = copy.deepcopy(first)
    swapped[0][1], swapped[0][2] = swapped[0][2], swapped[0][1]
    kitty = copy.deepcopy(first)
    kitty[1][0], kitty[0][1][0] = kitty[0][1][0], kitty[1][0]
    rows = [first, reordered, swapped, kitty]
    before = copy.deepcopy(rows)
    assert world.world_diversity(rows) == {'unique_worlds': 3, 'duplicate_worlds': 1}
    assert rows == before
    assert world.world_diversity([]) == {'unique_worlds': 0, 'duplicate_worlds': 0}


@pytest.mark.parametrize('value', [False, True])
def test_diagnostic_preserves_actions_inputs_rng_and_repeated_worlds(monkeypatch, value):
    rnd = state()
    traces = []
    def predict(x):
        traces.append(x.copy())
        return np.tile(np.arange(54), (len(x), 1))
    def bot():
        kwargs = dict(worlds=4, seed=17)
        if value:
            return PolicyValueBot(predict, evaluator=SimpleNamespace(
                score=lambda leaves, seat: np.zeros(len(leaves))), candidates=3, **kwargs)
        return world.PolicyWorldBot(predict, **kwargs)
    a, b = bot(), bot()
    before = copy.deepcopy(rnd.hands)
    action = a.decide_play(rnd, rnd.turn)
    counts = a.last_decision_record['world_diversity']
    assert counts['unique_worlds'] + counts['duplicate_worlds'] == 4
    # Returning no measurement models the old runtime without altering sampling.
    monkeypatch.setattr(world, 'world_diversity', lambda worlds: None)
    assert b.decide_play(rnd, rnd.turn) == action
    assert np.array_equal(traces[0], traces[1])
    assert a._worlds(rnd, rnd.turn) == b._worlds(rnd, rnd.turn)
    assert rnd.hands == before


def test_failed_sampling_clears_old_diversity(monkeypatch):
    rnd = state()
    bot = world.PolicyWorldBot(None, worlds=1)
    bot.last_world_diversity = {'unique_worlds': 100, 'duplicate_worlds': 0}
    monkeypatch.setattr(bot.sampler, '_sample_hands', lambda *a: None)
    with pytest.raises(RuntimeError, match='sampling short'):
        bot._worlds(rnd, rnd.turn)
    assert bot.last_world_diversity is None


def test_repeated_deals_are_counted_but_all_are_forwarded(monkeypatch):
    rnd = state()
    one, _ = world.PolicyWorldBot(None, worlds=1, seed=17)._worlds(rnd, rnd.turn)
    monkeypatch.setattr(world, 'sample_worlds', lambda *a, **k: (one * 4, 4))
    shapes = []
    def predict(x):
        shapes.append(x.shape[0])
        return np.zeros((len(x), 54))
    bot = world.PolicyWorldBot(predict, worlds=4)
    bot.decide_play(rnd, rnd.turn)
    assert shapes == [4]
    assert bot.last_decision_record['world_diversity'] == {
        'unique_worlds': 1, 'duplicate_worlds': 3}


def test_counts_and_measurement_coverage_survive_aggregation():
    side = duel._empty_side()
    record = {'worlds': 4, 'sample_attempts': 4, 'legal_complete': True,
              'world_diversity': {'unique_worlds': 1, 'duplicate_worlds': 3}}
    telemetry = duel._decision_telemetry(SimpleNamespace(last_decision_record=record), 'policy')
    for _ in range(2):
        duel._record_decision(side, .01, telemetry, 'policy')
    old = duel._decision_telemetry(SimpleNamespace(last_decision_record={}), 'policy')
    assert old['world_diversity_decisions'] == 0
    row = {'seed': 7, 'utility': 0., 'mirrors': [0., 0.], 'error': None,
           'sides': {'policy': side, 'control': duel._empty_side()}}
    result = duel.aggregate_records([row], [7])['policy']
    assert result['unique_worlds'] == 2  # per-decision sum, NOT globally distinct
    assert result['duplicate_worlds'] == 6
    assert result['world_diversity_decisions'] == 2
