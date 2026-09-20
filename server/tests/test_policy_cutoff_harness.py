import pytest

from shengji.train import policy_world_duel as duel


@pytest.mark.parametrize('extra', [
    ['--cutoff-tricks', '1'],
    ['--mode', 'mc-pv-cutoff', '--cutoff-tricks', '0'],
    ['--mode', 'mc-pv-cutoff', '--cutoff-tricks', '65'],
    ['--mode', 'policy', '--control', 'mc-heuristic-cutoff'],
    ['--mode', 'mc-pv-cutoff', '--control', 'policy-value'],
])
def test_cutoff_recipe_refusals(extra):
    args = duel.build_parser().parse_args([
        '--checkpoint', 'missing', '--checkpoint-sha256', 'a'*64,
        '--out', 'missing', '--seed0', '7'] + extra)
    with pytest.raises(ValueError):
        duel._validate_args(args)


def test_worker_transmits_cutoff_without_progress(monkeypatch):
    calls = []
    monkeypatch.setattr(duel, 'play_pair', lambda *a, **kw: calls.append(kw))
    duel._worker_pair((7, 'ck', 'sha', 16, 'mc-heuristic-cutoff', 'mc-pv-cutoff', 8, None, None, 2))
    assert calls[0]['cutoff_tricks'] == 2
    assert 'progress' not in calls[0]


@pytest.mark.parametrize('mode,learned,horizon', [
    ('mc-pv-cutoff', True, 2), ('mc-heuristic-cutoff', False, 2),
    ('mc-levels-terminal', False, None)])
def test_factory_modes_and_work_receipt(monkeypatch, mode, learned, horizon):
    from test_mc_policy_value_rollout import continuation
    from shengji.train.policy_value_search import PolicyValueBot
    inner = continuation()
    monkeypatch.setattr(duel, '_value_evaluator', lambda *a: inner.evaluator)
    monkeypatch.setattr(PolicyValueBot, 'from_checkpoint', lambda *a, **kw: inner)
    bot = duel.make_policy('ck', 'sha', 16, 7, mode, 8, cutoff_tricks=2)
    assert bot.cutoff_tricks == horizon
    assert bot.learned_continuation is learned
    bot.leaf_rollouts['predicted'] = 3
    telemetry = duel._decision_telemetry(bot, 'control')
    assert telemetry['leaf_predicted'] == 3
    assert telemetry['value_evaluations'] == telemetry['value_batches'] == 3
