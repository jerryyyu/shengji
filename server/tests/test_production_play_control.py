from types import SimpleNamespace

import pytest

from shengji.train import production_play_control as control
from shengji.train.cwv_shortlist import shortlist_policy_name


def test_recipe_reconstructs_live_fly_card_play_name():
    recipe = control.recipe()
    worlds = recipe.pop('worlds')
    recipe.pop('threads')
    assert shortlist_policy_name(control.SHA256[:8], worlds, recipe=recipe) == control.PLAY_NAME


def test_factory_pins_full_recipe_without_overriding_name(monkeypatch):
    seen = {}
    bot = SimpleNamespace(cwv_checkpoint_sha256=control.SHA256,
                          cwv_prior_sha256=control.SHA256,
                          policy_name=control.PLAY_NAME)
    def make(path, **kw):
        seen.update(path=path, **kw)
        return bot
    monkeypatch.setattr(control, 'make_shortlist_bot', make)
    assert control.ProductionPlayControl('/model.npz').make(7) is bot
    assert seen == dict(path='/model.npz', seed=7,
                       prior_checkpoint='/model.npz', **control.recipe())
    assert 'name' not in seen
    assert seen['worlds'] == 32
    assert seen['prior_threshold'] == 1000
    assert seen['selection_worlds'] == 30
    assert seen['report_worlds'] == 300


@pytest.mark.parametrize('field', ['cwv_checkpoint_sha256', 'cwv_prior_sha256', 'policy_name'])
def test_factory_refuses_model_or_recipe_drift(monkeypatch, field):
    fields = dict(cwv_checkpoint_sha256=control.SHA256,
                  cwv_prior_sha256=control.SHA256, policy_name=control.PLAY_NAME)
    fields[field] = 'wrong'
    monkeypatch.setattr(control, 'make_shortlist_bot', lambda *a, **kw: SimpleNamespace(**fields))
    with pytest.raises(RuntimeError, match='identity drift'):
        control.ProductionPlayControl('/model.npz').make(1)


def test_identity_is_explicit_about_nonproduction_bury_and_hardware():
    ident = control.ProductionPlayControl('/model.npz').identity()
    assert ident['declare_bury'] == 'shared HeuristicBot supplied by duel'
    assert 'not full production package' in ident['scope']
    assert ident['served_package_reference'] != ident['play_policy']
    ident['recipe']['worlds'] = 999
    assert control.recipe()['worlds'] == 32


@pytest.mark.parametrize('name,path', [('production-play', None), ('mc-smart4', '/unused')])
def test_cli_requires_production_path_exactly_for_named_control(name, path):
    from shengji.train import policy_world_duel as duel
    args = duel.build_parser().parse_args(['--checkpoint', '/arm', '--checkpoint-sha256',
        '0'*64, '--out', '/out', '--seed0', '1', '--control', name]
        + (['--production-checkpoint', path] if path else []))
    with pytest.raises(ValueError, match='required exactly'):
        duel._validate_args(args)


def test_worker_rechecks_production_hash_before_loading(monkeypatch):
    from shengji.train import policy_world_duel as duel
    monkeypatch.setattr(duel, '_sha256', lambda path: 'arm-sha' if str(path) == '/arm' else 'bad')
    monkeypatch.setattr(duel, 'make_policy', lambda *a: None)
    monkeypatch.setattr(control.ProductionPlayControl, 'make',
                        lambda *a: pytest.fail('must refuse before loading swapped artifact'))
    with pytest.raises(ValueError, match='production checkpoint SHA256 mismatch in worker'):
        duel._worker_init('/arm', 'arm-sha', 4, 'production-play',
                          production=control.ProductionPlayControl('/production'))


def test_production_configuration_survives_worker_dispatch(monkeypatch):
    from shengji.train import policy_world_duel as duel
    production = control.ProductionPlayControl('/production')
    seen = {}
    def fake(*args, **kwargs):
        seen.update(kwargs)
    monkeypatch.setattr(duel, 'play_pair', fake)
    duel._worker_pair((1, '/arm', 'sha', 4, 'production-play', 'policy-value', 8, production))
    assert seen['production'] is production
    assert seen['control'] == 'production-play'


def test_shortlist_ranking_work_survives_mirrors_without_becoming_mc_work(monkeypatch):
    from shengji.train import policy_world_duel as duel
    bot = SimpleNamespace(last_shortlist={
        'counts': {'decisions': 1, 'cheap_worlds': 32, 'cheap_evaluations': 160,
                   'cheap_batches': 2, 'legal_actions': 1001},
        'cheap_sampler_delta': {'sample_attempts': 33, 'accepted_worlds': 32,
                                'failed_worlds': 1},
        'prior_admission': {'triggered': True, 'worlds': 32, 'pool_evaluations': 160}})
    def fake(*args):
        sides = {k: duel._empty_side() for k in ('policy', 'control')}
        duel._record_decision(sides['control'], .1,
                             duel._decision_telemetry(bot, 'control'), 'control')
        return {'sides': sides, 'utility': 0}
    monkeypatch.setattr(duel, '_play_one', fake)
    row = duel.play_pair(7, 'ck', 'sha', control='production-play')
    summary = duel.aggregate_records([row], [7])['control']
    work = summary['shortlist_work']
    assert work['cheap_worlds'] == work['cheap_accepted_worlds'] == 64
    assert work['cheap_sample_attempts'] == 66
    assert work['cheap_failed_worlds'] == 2
    assert work['cheap_evaluations'] == work['prior_pool_evaluations'] == 320
    assert work['prior_decisions'] == 2
    assert summary['worlds'] == summary['report_worlds'] == 0
    bot.last_shortlist = None
    assert not any(duel._decision_telemetry(bot, 'control')['shortlist_work'].values())
