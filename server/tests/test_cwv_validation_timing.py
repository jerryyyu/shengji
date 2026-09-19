"""Validation timing must not alter call order or selection values."""
from types import SimpleNamespace

import pytest

from shengji.train import train_cwv as module


@pytest.mark.parametrize('search,policy', [(False, False), (True, False),
                                         (False, True), (True, True)])
@pytest.mark.parametrize('pack', [False, True])
def test_stage_timings_preserve_validation_contract(monkeypatch, search, policy, pack):
    calls = []
    clock = iter(range(10))
    monkeypatch.setattr(module.time, 'perf_counter', lambda: next(clock))
    model, store, mask, device, aux, candidates = [object() for _ in range(6)]
    ev = object()
    def run(m, s, f, d, **kwargs):
        assert (m, s, f, d) == (model, store, mask, device)
        assert kwargs == {'batch_size': 32, 'aux_head': aux, **({'pack_shards': True} if pack else {})}
        calls.append('eval')
        return ev
    def quick(e):
        assert e is ev
        calls.append('metrics')
        return {'loss': .75, 'n': 4}
    def ranking(m, e, c, d, **kwargs):
        assert (m, e, c, d) == (model, ev, candidates, device)
        assert kwargs == {'batch_size': 32}
        calls.append('ranking')
        return {'rank_regret': .125}
    def search_ranking(*args, **kwargs):
        result = ranking(*args, **kwargs)
        calls[-1] = 'search'
        return result
    def policy_run(m, d):
        assert (m, d) == (model, device)
        calls.append('policy')
        return {'top64': {'test': .5}, 'miss_at_64': .5}
    monkeypatch.setattr(module, 'run_eval', run)
    monkeypatch.setattr(module, 'quick_metrics', quick)
    monkeypatch.setattr(module, 'search_facing', ranking)
    monkeypatch.setattr(module, 'search_head_rank', search_ranking)
    got = module.validation_pass(model, store, mask, device, batch_size=32,
        aux_head=aux, candidates=candidates, search_head=search,
        policy_evalset=SimpleNamespace(run=policy_run) if policy else None, pack_shards=pack)
    assert calls == ['eval', 'metrics', 'ranking'] + (['search'] if search else []) + (['policy'] if policy else [])
    expected = {'loss': .75, 'n': 4, 'rank_regret': .125}
    if search:
        expected['search_head'] = {'rank_regret': .125}
    if policy:
        expected['policy'] = {'top64': {'test': .5}, 'miss_at_64': .5}
        expected['policy_miss_at_64'] = .5
    timing = got.pop('stage_wall_seconds')
    assert got == expected
    assert timing.pop('total') == 3 + int(search) + int(policy)
    assert all(t == 1 for t in timing.values())
