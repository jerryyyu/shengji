import copy

import numpy as np
import pytest

from shengji.eval.s11_collection import collect_s11_fixture
from shengji.eval.s11_public_view import public_s11_fixture
from shengji.eval.s11_report import summarize_s11
from shengji.train.pv_search_policy import PVSearchBot, PVSearchConfig
from test_s11_public_view import trajectory


def factory(calls, *, seed=17, **changes):
    options = dict(checkpoint_sha256='f' * 64, worlds=64, cap=4000,
                   candidates=8, batch_size=128, refusal_constraints=True,
                   admission_diversity=True, lead_anchor=True,
                   tiebreak_points=True)
    options.update(changes)

    class Evaluator:
        def score(self, leaves, seat):
            calls['leaves'] += len(leaves)
            return np.zeros(len(leaves))

    def predict(x):
        calls['policy'].append(len(x))
        return np.zeros((len(x), 54))

    def build():
        bot = PVSearchBot(predict, evaluator=Evaluator(), version=2,
                          config=PVSearchConfig(**options),
                          checkpoint='/synthetic-no-model', seed=seed)
        calls['bots'].append(bot)
        return bot
    return build


@pytest.mark.parametrize('ply', [21, 97, 98])
def test_real_synthetic_path_samples_scores_and_projects_once(trajectory, ply):
    fixture = public_s11_fixture(trajectory, ply, root_id=f'synthetic-{ply}')
    before = copy.deepcopy(fixture.to_json())
    calls = dict(leaves=0, policy=[], bots=[])
    result = collect_s11_fixture(factory(calls), fixture, seed=17)
    assert len(calls['bots']) == 2
    assert calls['policy'] == [64]
    actions = result['policy_capture']['actions']
    assert calls['leaves'] == 64 * len(actions)
    assert result['value_capture']['actions'] == actions
    assert result['report']['baseline']['actions'] == actions
    assert result['report']['status'] == 'valid'
    assert result['tape_receipt']['mode'] == 'history-primed'
    assert len(result['worlds']) == 64
    assert not result['model_verified'] and not result['provenance_verified']
    assert fixture.to_json() == before
    # Use the real summary consumer, not merely a serialization assertion.
    summary = summarize_s11([result['report']], [fixture.id])
    assert summary['valid_count'] == 1 and summary['coverage_complete']
    assert summary['primary']['mean'] == 0  # synthetic zero evaluator only


@pytest.mark.parametrize('changes', [dict(worlds=32), dict(cap=100),
    dict(candidates=4), dict(refusal_constraints=False),
    dict(refusal_event_complete=True), dict(doomed_throw_swap=True)])
def test_wrong_recipe_refused_before_predicting(trajectory, changes):
    fixture = public_s11_fixture(trajectory, 98, root_id='synthetic')
    calls = dict(leaves=0, policy=[], bots=[])
    with pytest.raises(ValueError, match='release38'):
        collect_s11_fixture(factory(calls, **changes), fixture, seed=17)
    assert calls['policy'] == [] and calls['leaves'] == 0


def test_factory_reuse_refused_before_sampling(trajectory):
    fixture = public_s11_fixture(trajectory, 98, root_id='synthetic')
    calls = dict(leaves=0, policy=[], bots=[])
    bot = factory(calls)()
    with pytest.raises(ValueError, match='independently owned'):
        collect_s11_fixture(lambda: bot, fixture, seed=17)
    assert not hasattr(bot, '_public_refusal_tape_consumed')


def test_budget_failure_propagates_before_factory(trajectory):
    fixture = public_s11_fixture(trajectory, 98, root_id='synthetic')
    def expired():
        raise TimeoutError('expired')
    with pytest.raises(TimeoutError, match='expired'):
        collect_s11_fixture(lambda: pytest.fail('factory ran'), fixture,
                            seed=17, check_budget=expired)


def test_incomplete_pool_is_reported_not_filtered(trajectory, monkeypatch):
    from dataclasses import replace
    original = PVSearchBot._legal
    def capped(bot, root, seat, extras):
        legal = original(bot, root, seat, extras)
        return replace(legal, complete=False, count=9000)
    monkeypatch.setattr(PVSearchBot, '_legal', capped)
    fixture = public_s11_fixture(trajectory, 98, root_id='synthetic')
    result = collect_s11_fixture(factory(dict(leaves=0, policy=[], bots=[])),
                                  fixture, seed=17)
    assert result['legal_complete'] is False
    assert result['legal_count'] == 9000
    assert result['report']['baseline']['legal_complete'] is False


@pytest.mark.parametrize('damage', ['checkpoint', 'encoder', 'leaf', 'rng', 'value'])
def test_scorer_drift_and_failures_never_publish_partial_report(
        trajectory, damage):
    fixture = public_s11_fixture(trajectory, 98, root_id='synthetic')
    calls = dict(leaves=0, policy=[], bots=[])
    build = factory(calls)
    def altered():
        bot = build()
        if len(calls['bots']) == 2:
            if damage == 'checkpoint':
                bot.checkpoint_sha256 = 'e' * 64
            elif damage == 'encoder':
                bot.version = 3
            elif damage == 'leaf':
                bot._leaf = lambda *a: None
            else:
                original = bot.evaluator.score
                def score(leaves, seat):
                    if damage == 'value':
                        raise RuntimeError('value failure')
                    bot.sampler.rng.random()
                    return original(leaves, seat)
                bot.evaluator.score = score
        return bot
    with pytest.raises((ValueError, RuntimeError)):
        collect_s11_fixture(altered, fixture, seed=17)
    if damage in ('checkpoint', 'encoder', 'leaf'):
        assert calls['policy'] == [] and calls['leaves'] == 0
