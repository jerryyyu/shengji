import copy

import pytest

from shengji.train import production_pv_control as control
from shengji.train.pv_search_policy import PVSearchConfig, pv_policy_name
from test_pv_search_serving import package  # noqa: F401


def test_live_recipe_is_pinned_and_does_not_depend_on_environment(monkeypatch):
    monkeypatch.setenv('SHENGJI_PV_WORLDS', '1')
    config = PVSearchConfig(checkpoint_sha256=control.SHA256, **control.recipe())
    assert pv_policy_name(control.SHA256[:8], config) == control.PLAY_NAME
    identity = control.ProductionPVControl('/not-loaded').identity()
    assert identity['recipe'] == dict(worlds=64, candidates=8, cap=4000,
                                     batch_size=128, serving_budget_seconds=3.0)
    assert 'card play only' in identity['scope']
    assert 'HeuristicBot' in identity['declare_bury']


def test_real_numpy_factory_and_deepcopy(package, monkeypatch):
    path, sha = package
    # Fixture-only identity binding; production constants are checked separately.
    monkeypatch.setattr(control, 'SHA256', sha)
    monkeypatch.setattr(control, 'PLAY_NAME', pv_policy_name(
        sha[:8], PVSearchConfig(checkpoint_sha256=sha, **control.recipe())))
    bot = control.ProductionPVControl(path).make(17)
    twin = copy.deepcopy(bot)
    assert twin.serving_budget_seconds == 3.0
    assert twin.policy_name == control.PLAY_NAME
    assert twin.worlds == 64
    assert twin.candidates == 8


def test_wrong_artifact_refused(package):
    path, _ = package
    with pytest.raises(Exception, match='(?i)(sha|hash|digest)'):
        control.ProductionPVControl(path).make(17)


def test_recipe_drift_refused_before_model_load(monkeypatch):
    monkeypatch.setattr(control, 'recipe', lambda: dict(worlds=32, candidates=8,
                        cap=4000, batch_size=128, serving_budget_seconds=3.0))
    with pytest.raises(RuntimeError, match='identity drift'):
        control.ProductionPVControl('/missing').make(17)


def test_duel_control_factory_and_budget_fallback_aggregate(package, monkeypatch):
    from shengji.train import policy_world_duel as duel
    from shengji.train.policy_world_search import PolicyWorldBot
    from shengji.ai.heuristic import HeuristicBot
    from shengji.ai.env import prepare_round
    from shengji.engine.game import Game
    import random
    path, sha = package
    monkeypatch.setattr(control, 'SHA256', sha)
    monkeypatch.setattr(control, 'PLAY_NAME', pv_policy_name(
        sha[:8], PVSearchConfig(checkpoint_sha256=sha, **control.recipe())))
    spec = control.ProductionPVControl(path)
    bot = duel.make_control('production-pv-r29', 7, spec)
    assert isinstance(bot, PolicyWorldBot)  # real harness routes it to policy telemetry
    config = duel.full_control_config('production-pv-r29', spec)
    assert config['rollout_policy'] is None
    assert config['recipe']['serving_budget_seconds'] == 3.0
    game = Game(random.Random(7))
    prepare_round(game, [HeuristicBot() for _ in range(4)])
    from shengji.train.pv_search_policy import PVSearchBudgetExceeded
    def refuse(*args, **kwargs):
        raise PVSearchBudgetExceeded('injected')
    monkeypatch.setattr(bot, '_search', refuse)
    played, seconds = duel._timed_play(bot, game.round, game.round.turn)
    assert played
    sides = dict(policy=duel._empty_side(), control=duel._empty_side())
    duel._record_decision(sides['control'], seconds,
                         duel._decision_telemetry(bot, 'policy'), 'policy')
    summary = duel.aggregate_records([dict(seed=7, utility=0, sides=sides,
                                          error=None, timeout=False)], [7])
    assert summary['control']['decisions'] == 1
    assert summary['control']['mc_decisions'] == 0
    work = summary['control']['policy_work']
    assert work['fallback_decisions'] == work['budget_fallbacks'] == 1
    assert work['error_fallbacks'] == 0


def test_r29_cli_requires_checkpoint():
    from shengji.train import policy_world_duel as duel
    args = duel.build_parser().parse_args(['--checkpoint', '/soft',
        '--checkpoint-sha256', 'a'*64, '--out', '/fresh', '--seed0', '7',
        '--control', 'production-pv-r29'])
    with pytest.raises(ValueError, match='checkpoint'):
        duel._validate_args(args)
    args.production_checkpoint = '/prod'
    duel._validate_args(args)
