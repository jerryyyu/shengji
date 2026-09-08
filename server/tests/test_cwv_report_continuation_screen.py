"""CLI -> worker -> recorded report-guidance wiring, with fixed root controls."""
import copy
import json

import numpy as np
import pytest

from shengji.train import cwv_shortlist_screen as S
from shengji.train.cwv_report_continuation import CWVReportContinuationBot
from shengji.train.cwv_shortlist import CWVShortlistBot
from tests.test_world_shortlist import play_state


class Evaluator:
    checkpoint_sha256 = 'a' * 64

    def __init__(self):
        self.many_calls = 0

    def identity(self):
        return {'checkpoint_sha256': self.checkpoint_sha256}

    def score(self, states, seat, **kwargs):
        return np.array([r.attacker_points for r in states], dtype=float)

    def score_many(self, states, seats):
        self.many_calls += 1
        return np.array([r.attacker_points * (1 if r.is_attacker(s) else -1)
                         for r, s in zip(states, seats, strict=True)], dtype=float)


@pytest.mark.parametrize('mode', ['learned', 'prior', 'heuristic'])
def test_cli_worker_real_decision_and_work_record(tmp_path, monkeypatch, mode):
    monkeypatch.setenv('SHENGJI_REQUIRE_VOIDS', '1')
    root, prior = Evaluator(), Evaluator()
    monkeypatch.setattr(S, 'shared_evaluator', lambda *a, **kw: root)
    monkeypatch.setattr(S, 'prior_evaluator_for', lambda *a, **kw: prior)
    monkeypatch.setattr(S, '_run_pending', lambda *a, **kw: None)
    out = tmp_path/'run'
    assert S.main(['--arm', 'learned', '--checkpoint', 'unused.pt',
                   '--worlds', '1', '--selection-worlds', '2', '--report-worlds', '30',
                   '--report-continuation', mode, '--baseline', 'flat-shortlist',
                   '--clusters', '1', '--seed0', '17', '--out', str(out)]) == 0
    config = json.loads((out/'config.json').read_text())
    arm = S.make_side(config, 'arm', 13)
    baseline = S.make_side(config, 'baseline', 13)
    assert type(arm) is CWVReportContinuationBot
    assert type(baseline) is CWVShortlistBot
    assert arm.shortlist_config == baseline.shortlist_config
    assert arm.N_DETERMINIZATIONS == baseline.N_DETERMINIZATIONS == 2
    assert arm.REPORT_FOLD_WORLDS == baseline.REPORT_FOLD_WORLDS == 30
    assert S._recipe(config)['report_continuation'] == config['report_continuation']
    state = play_state()
    wrapped = S.CwvTimedPolicy(arm)
    wrapped.decide_play(state, state.turn)
    record = wrapped.decisions[-1]['cwv_report_continuation']
    assert record == arm.last_decision_record['cwv_report_continuation']
    work = S.work_counters([wrapped])
    assert work['report_guidance_report_rollouts'] > 0
    assert work['report_guidance_selection_net_plays'] == 0
    assert work['report_guidance_report_net_plays'] == arm.netroll_counts['report_net_plays']
    assert work['total_rollouts'] == arm.rollouts
    assert work['report_guidance_report_rollouts'] <= work['total_rollouts']
    if mode == 'heuristic':
        assert root.many_calls == prior.many_calls == 0
    else:
        used = prior if mode == 'prior' else root
        unused = root if mode == 'prior' else prior
        assert used.many_calls > 0 and unused.many_calls == 0
        assert work['report_guidance_report_net_plays'] > 0


def test_changed_guidance_cannot_reopen_completed_shard(tmp_path):
    from tests.test_cwv_shortlist_screen import cfg
    recipe = dict(schema='cwv-report-continuation-v1', guidance='learned',
                  tricks=1, stage='report', inner_ballot='production', terminal='heuristic')
    config = cfg('learned', report_continuation=recipe)
    shard = {'schema': 'cwv-shortlist-shard-v1', 'cluster': 0, 'seed': 17,
             'rank': '2', 'recipe': S._recipe(config),
             'records': [dict(cluster=0, seed=17, mirror=m, trump_rank='2', arm='learned')
                         for m in (0, 1)]}
    path = tmp_path/'cluster-00000.json'
    path.write_text(json.dumps(shard))
    assert S.reopen_shard(path, config, 0) == shard
    changed = copy.deepcopy(config)
    changed['report_continuation']['guidance'] = 'prior'
    with pytest.raises(ValueError, match='^completed shard does not match'):
        S.reopen_shard(path, changed, 0)


@pytest.mark.parametrize('extra', [
    ['--arm', 'uniform', '--report-continuation', 'learned'],
    ['--arm', 'learned', '--checkpoint', 'unused', '--report-continuation', 'learned'],
    ['--arm', 'learned', '--checkpoint', 'unused', '--report-continuation', 'learned',
     '--inner-mode', 'learned'],
])
def test_invalid_combinations_refuse_before_model_load(tmp_path, monkeypatch, extra):
    monkeypatch.setenv('SHENGJI_REQUIRE_VOIDS', '1')
    def forbidden(*a, **kw):
        raise AssertionError('invalid mode must not load checkpoint')
    monkeypatch.setattr(S, 'shared_evaluator', forbidden)
    with pytest.raises(SystemExit):
        S.main(['--seed0', '17', '--out', str(tmp_path/'out'), *extra])


def test_execution_slice_retains_population_and_skips_finished_pairs(tmp_path, monkeypatch):
    monkeypatch.setenv('SHENGJI_REQUIRE_VOIDS', '1')
    batches = []
    def complete(config, pending, shards, *, output, **kwargs):
        batches.append(list(pending))
        for cluster in pending:
            shard = dict(schema='cwv-shortlist-shard-v1', cluster=cluster,
                         seed=config['seed0']+cluster, rank='2', recipe=S._recipe(config),
                         records=[dict(cluster=cluster, seed=config['seed0']+cluster,
                                       mirror=m, trump_rank='2', arm='uniform') for m in (0,1)])
            S._publish(output/f'cluster-{cluster:05}.json', shard)
            shards.append(shard)
    monkeypatch.setattr(S, '_run_pending', complete)
    monkeypatch.setattr(S, 'summary_for', lambda shards, config: {'complete': len(shards) == 3})
    out = tmp_path/'sliced'
    argv = ['--arm', 'uniform', '--seed0', '17', '--clusters', '3', '--out', str(out)]
    assert S.main([*argv, '--max-new-clusters', '1']) == 0
    config_bytes = (out/'config.json').read_bytes()
    pair_bytes = (out/'cluster-00000.json').read_bytes()
    assert json.loads(config_bytes)['clusters'] == 3
    assert 'max_new_clusters' not in json.loads(config_bytes)
    assert S.main(argv) == 0
    assert batches == [[0], [1,2]]
    assert (out/'config.json').read_bytes() == config_bytes
    assert (out/'cluster-00000.json').read_bytes() == pair_bytes
