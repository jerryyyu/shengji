import copy
from dataclasses import asdict

import pytest

from shengji.eval import panel_rank_root as module, tactical
from shengji.eval.public_refusal_history import public_root_with_ledger
from shengji.harvest.legal import enumerate_legal
from test_policy_world_search import state
from test_refusal_constraints import served


def inputs(mode='fresh-root'):
    original = state()
    original.play(0, ['S2'])
    fixture = tactical.Fixture(
        id='synthetic-rank-root', category=tactical.OBSERVATION_CATEGORY,
        source={'kind': 'synthetic'}, seat=1,
        setup={'trump_rank': original.trump_rank, 'trump_suit': original.trump_suit,
               'trump_is_nt': original.trump_is_nt, 'banker': original.banker,
               'declarations': [{'seat': 0, 'cards': ['S2']}], 'buried': None},
        plays=[{'seat': 0, 'cards': ['S2']}], hand=list(original.hands[1]),
        observed={}, predicate='observe_follow', args={}, why='synthetic binding')
    root, _, receipt = public_root_with_ledger(fixture, mode=mode)
    bot = served(seed=0, worlds=64, refusal_constraints=True)
    legal = enumerate_legal(root, 1, cap=bot.cap)
    assert legal.complete
    panel = {'schema': 'public-fixture-panel-v1', 'fixture_id': fixture.id,
             'mode': mode, 'seed': 0, 'fill_seed': 0,
             'config': asdict(bot.config), 'checkpoint_sha256': bot.checkpoint_sha256,
             'effective': {key: getattr(bot, key) for key in
                           ('worlds', 'cap', 'batch_size', 'candidates')},
             'legal_count': legal.count, 'actions': copy.deepcopy(legal.actions),
             'worlds': [[copy.deepcopy(original.hands), list(original.buried)] for _ in range(64)],
             'tape_receipt': {'ledger_receipt': receipt, 'last_sampling':
                              {'refusal_fallback_worlds': 64}}}
    def forbidden(*a, **kw):
        pytest.fail('sampling/prediction/value forbidden in root binding')
    bot.predict = bot._worlds = bot._score_leaves = bot.evaluator.score = forbidden
    return panel, fixture, bot


@pytest.mark.parametrize('mode', ['fresh-root', 'history-primed'])
def test_real_public_rebuild_binds_without_mutation_or_model_work(mode):
    panel, fixture, bot = inputs(mode)
    before = copy.deepcopy((panel, fixture.to_json(), bot.sampler.rng.getstate()))
    root = module.bind_panel_rank_root(panel, fixture, bot)
    assert root.turn == fixture.seat
    assert sorted(root.hands[root.turn]) == sorted(fixture.hand)
    assert (panel, fixture.to_json(), bot.sampler.rng.getstate()) == before
    assert panel['tape_receipt']['last_sampling']['refusal_fallback_worlds'] == 64


@pytest.mark.parametrize('mode', ['fresh-root', 'history-primed'])
def test_pre_doomed_throw_config_projects_once_without_rewriting_panel(mode):
    import numpy as np
    selected, fixture, bot = selected_inputs(mode)
    del selected['panel']['config']['doomed_throw_swap']
    before = copy.deepcopy(selected)
    calls = []
    def predict(x):
        calls.append(len(x))
        return np.tile(np.arange(54), (len(x), 1))
    bot.predict = predict
    result = module.project_panel_rank_repairs(selected, fixture, bot)
    assert calls == [64]
    assert set(result['projections']) == {'control', 'treatment'}
    assert selected == before


@pytest.mark.parametrize('damage', ['config_true', 'config_zero', 'bot_true',
                                  'bot_zero', 'missing_other', 'extra', 'changed'])
def test_old_config_compatibility_is_narrow_and_strict(damage):
    from dataclasses import replace
    panel, fixture, bot = inputs()
    del panel['config']['doomed_throw_swap']
    if damage.startswith('config_'):
        bot.config = replace(bot.config, doomed_throw_swap=True if damage == 'config_true' else 0)
    elif damage.startswith('bot_'):
        bot.doomed_throw_swap = True if damage == 'bot_true' else 0
    elif damage == 'missing_other':
        del panel['config']['lead_anchor']
    elif damage == 'extra':
        panel['config']['unknown_future_rule'] = False
    else:
        panel['config']['candidates'] += 1
    before = copy.deepcopy(panel)
    with pytest.raises(ValueError, match='config mismatch'):
        module.bind_panel_rank_root(panel, fixture, bot)
    assert panel == before


@pytest.mark.parametrize('damage,match', [
    ('fixture', 'identity'), ('config', 'config mismatch'), ('effective', 'effective mismatch'),
    ('checkpoint', 'checkpoint_sha256 mismatch'), ('ledger', 'ledger receipt'),
    ('order', 'legal pool'), ('missing', 'legal pool'), ('count', 'legal pool'),
    ('fill', 'fill seed'), ('worlds', '64-world'), ('seed', 'strict panel seed'),
    ('seed_bool', 'strict panel seed'),
])
def test_join_damage_refuses(damage, match):
    panel, fixture, bot = inputs()
    if damage == 'fixture':
        panel['fixture_id'] = 'wrong'
    elif damage == 'config':
        panel['config']['candidates'] += 1
    elif damage == 'effective':
        panel['effective']['cap'] += 1
    elif damage == 'checkpoint':
        panel['checkpoint_sha256'] = 'a' * 64
    elif damage == 'ledger':
        panel['tape_receipt']['ledger_receipt']['actor_turn_observations'] += 1
    elif damage == 'order':
        assert len(panel['actions']) > 1
        panel['actions'].reverse()
    elif damage == 'missing':
        panel['actions'].pop()
    elif damage == 'count':
        panel['legal_count'] = True
    elif damage == 'fill':
        panel['fill_seed'] = True
    elif damage == 'worlds':
        panel['worlds'].pop()
    elif damage == 'seed_bool':
        panel['seed'] = False
    else:
        panel['seed'] = 99
    with pytest.raises(ValueError, match=match):
        module.bind_panel_rank_root(panel, fixture, bot)


def test_public_void_damage_refuses_without_filtering(monkeypatch):
    panel, fixture, bot = inputs()
    memory = module.Memory
    def with_void(root, seat, **kwargs):
        result = memory(root, seat, **kwargs)
        result.voids[2].add(root.ordering.eff_suit(panel['worlds'][-1][0][2][0]))
        return result
    monkeypatch.setattr(module, 'Memory', with_void)
    before = copy.deepcopy(panel)
    with pytest.raises(ValueError, match='public voids'):
        module.bind_panel_rank_root(panel, fixture, bot)
    assert panel == before


@pytest.mark.parametrize('mode', ['fresh-root', 'history-primed'])
def test_bound_root_scores_original_tape_once_with_stub_predictor(mode):
    import numpy as np
    from shengji.eval.fixed_tape_policy import capture_policy_ranks

    panel, fixture, bot = inputs(mode)
    calls = []
    def stub_predict(x):
        calls.append(len(x))
        return np.tile(np.arange(54), (len(x), 1))
    bot.predict = stub_predict
    root = module.bind_panel_rank_root(panel, fixture, bot)
    result = capture_policy_ranks(bot, root, fixture.seat, panel['actions'], panel['worlds'])
    assert calls == [64]
    assert result['actions'] == panel['actions']
    assert result['world_count'] == 64
    assert result['provenance_verified'] is False


def selected_inputs(mode):
    panel, fixture, bot = inputs(mode)
    actions = panel['actions']
    values = [float(i) for i in range(len(actions))]
    saved = {'schema': 'fixed-tape-same-leaf-capture-v1',
             'actions': copy.deepcopy(actions), 'world_count': 64,
             'value_matrix': [values[:] for _ in range(64)],
             'serving_value_means': values,
             'signed_trick_points': [[0] * len(actions) for _ in range(64)]}
    panel['collection'] = ({'captures': {'full_pool': saved}} if mode == 'fresh-root'
                           else {'full_pool_capture': saved})
    job = {key: panel[key] for key in ('fixture_id', 'mode', 'seed')}
    job.update(control_ballot=copy.deepcopy(actions[:1]),
               treatment_ballot=copy.deepcopy(actions[-1:]))
    return {'schema': 'selected-m9-panel-v1', 'panel': panel, 'job': job}, fixture, bot


@pytest.mark.parametrize('mode', ['fresh-root', 'history-primed'])
@pytest.mark.parametrize('arm', ['control', 'treatment'])
def test_projection_composes_one_prediction_with_saved_values(mode, arm):
    import numpy as np
    selected, fixture, bot = selected_inputs(mode)
    before = copy.deepcopy((selected, fixture.to_json(), bot.sampler.rng.getstate()))
    calls = []
    def predict(x):
        calls.append(len(x))
        return np.tile(np.arange(54), (len(x), 1))
    bot.predict = predict
    result = module.project_panel_rank_repair(selected, fixture, bot, arm=arm)
    assert calls == [64]
    assert result['projection']['baseline']['actions'] == selected['job'][f'{arm}_ballot']
    index = 0 if arm == 'control' else len(selected['panel']['actions']) - 1
    assert result['projection']['baseline']['raw_value_max'] == float(index)
    assert result['capture']['world_count'] == 64
    assert result['provenance_verified'] is False
    assert result['serving_choice_assessed'] is False
    assert (selected, fixture.to_json(), bot.sampler.rng.getstate()) == before


@pytest.mark.parametrize('damage', ['job', 'baseline', 'means', 'cards'])
@pytest.mark.parametrize('mode', ['fresh-root', 'history-primed'])
def test_projection_refuses_damage_before_prediction(damage, mode):
    selected, fixture, bot = selected_inputs(mode)
    if damage == 'job':
        selected['job']['seed'] = 1
    elif damage == 'baseline':
        selected['job']['treatment_ballot'] = [['not-a-card']]
    elif damage == 'means':
        collection = selected['panel']['collection']
        saved = (collection['captures']['full_pool'] if mode == 'fresh-root'
                 else collection['full_pool_capture'])
        saved['serving_value_means'][0] += 1
    else:
        selected['panel']['worlds'][-1][0][2].pop()
    # inputs() has forbidden sampler, predictor and value callbacks installed.
    with pytest.raises(ValueError):
        module.project_panel_rank_repair(selected, fixture, bot, arm='treatment')


@pytest.mark.parametrize('expire_at', [1, 2, 3, 4])
@pytest.mark.parametrize('both_arms', [False, True])
def test_projection_budget_refusal_returns_no_result(expire_at, both_arms):
    import numpy as np
    selected, fixture, bot = selected_inputs('fresh-root')
    calls = []
    def predict(x):
        calls.append(len(x))
        return np.zeros((len(x), 54))
    bot.predict = predict
    checks = 0
    def budget():
        nonlocal checks
        checks += 1
        if checks == expire_at:
            raise TimeoutError('synthetic deadline')
    with pytest.raises(TimeoutError, match='synthetic deadline'):
        if both_arms:
            module.project_panel_rank_repairs(selected, fixture, bot, check_budget=budget)
        else:
            module.project_panel_rank_repair(selected, fixture, bot,
                                             arm='treatment', check_budget=budget)
    assert calls == ([] if expire_at <= 2 else [64])


@pytest.mark.parametrize('mode', ['fresh-root', 'history-primed'])
def test_both_arms_share_one_capture_and_match_independent_projections(mode):
    import numpy as np
    from shengji.eval.pair_resource_admission import project_rank_repair
    selected, fixture, bot = selected_inputs(mode)
    before = copy.deepcopy((selected, fixture.to_json(), bot.sampler.rng.getstate()))
    calls = []
    def predict(x):
        calls.append(len(x))
        assert len(calls) == 1, 'both arms must share the same rank capture'
        return np.tile(np.arange(54), (len(x), 1))
    bot.predict = predict
    result = module.project_panel_rank_repairs(selected, fixture, bot)
    assert calls == [64]
    assert list(result['projections']) == ['control', 'treatment']
    panel = selected['panel']
    root = module.bind_panel_rank_root(panel, fixture, bot)
    for arm in ('control', 'treatment'):
        expected = project_rank_repair(root, fixture.seat, result['capture'],
                                      selected['job'][f'{arm}_ballot'], panel['actions'],
                                      [float(i) for i in range(len(panel['actions']))])
        assert result['projections'][arm] == expected
    assert (selected, fixture.to_json(), bot.sampler.rng.getstate()) == before


@pytest.mark.parametrize('arms', [[], ['control', 'control'], ['bogus'], 'control', [True], [{}]])
def test_multi_arm_request_rejected_before_prediction(arms):
    selected, fixture, bot = selected_inputs('fresh-root')
    with pytest.raises(ValueError, match='arms'):
        module.project_panel_rank_repairs(selected, fixture, bot, arms=arms)


@pytest.mark.parametrize('mode', ['fresh-root', 'history-primed'])
def test_invalid_second_arm_refuses_before_shared_prediction(mode):
    selected, fixture, bot = selected_inputs(mode)
    selected['job']['treatment_ballot'] = []
    with pytest.raises(ValueError, match='baseline'):
        module.project_panel_rank_repairs(selected, fixture, bot)
