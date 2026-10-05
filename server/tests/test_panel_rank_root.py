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
