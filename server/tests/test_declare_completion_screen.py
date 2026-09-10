from copy import deepcopy
from dataclasses import asdict
import json

import pytest

from shengji.train import declare_completion_screen as screen


def row(config, cluster, values):
    role, seed = screen.world_identity(config, cluster)
    return {'cluster': cluster, 'role': role, 'seed': seed,
            'config_sha256': config['config_sha256'], 'result': {'actions': [
                {'action': action, 'mean_signed_levels': value,
                 'rows': [{'seed': seed, 'metrics': {'focal_signed_levels': value}}]}
                for action, value in zip((None, ['S2']), values)]}}


def test_report_outcomes_cannot_select_the_declaration():
    config = {'selection_worlds': 2, 'report_worlds': 2, 'observation_index': 0, 'config_sha256': 'source'}
    shards = [row(config, 0, [0, 2]), row(config, 1, [1, 2]),
              row(config, 2, [3, -2]), row(config, 3, [3, -1])]
    result = screen.summarize(shards, config)
    assert result['selected_action'] == ['S2']
    assert result['independent_report_deltas'] == [-5, -4]
    assert result['mean_report_delta'] == -4.5
    changed = shards[:2]+[row(config, 2, [-3, 3]), row(config, 3, [-3, 3])]
    assert screen.summarize(changed, config)['selected_action'] == ['S2']
    assert {s['seed'] for s in shards[:2]}.isdisjoint(s['seed'] for s in shards[2:])


def test_actual_cli_reuses_completed_worlds_without_replaying(tmp_path, monkeypatch):
    observations = [screen.capture_first_opportunity(i) for i in range(12)]
    obs = next(o for o in observations if o is not None)
    assert screen.reopen_observation(asdict(obs)) == obs
    monkeypatch.setattr(screen, 'capture_first_opportunity', lambda *args, **kwargs: obs)
    monkeypatch.setattr(screen, 'execution_source_identity', lambda *args: {'source': 'same'})
    monkeypatch.setenv('SHENGJI_REQUIRE_VOIDS', '1')
    checkpoint = tmp_path/'model.bin'
    checkpoint.write_bytes(b'fixture')
    out = tmp_path/'pilot'
    calls = []
    def finish(config, pending, shards, *, output, **kwargs):
        calls.append(list(pending))
        for cluster in pending:
            record = row(config, cluster, [0, 1])
            screen._publish(output/f'cluster-{cluster:05d}.json', record)
            shards.append(record)
    monkeypatch.setattr(screen, '_run_pending', finish)
    args = ['--out', str(out), '--checkpoint', str(checkpoint), '--index', '0']
    screen.main(args)
    screen.main(args)
    assert calls == [[0, 1, 2, 3], []]
    record = json.loads((out/'cluster-00002.json').read_text())
    record['role'] = 'selection'
    screen._publish(out/'cluster-00002.json', record)
    with pytest.raises(ValueError, match='selection/report role differs'):
        screen.main(args)
    assert calls == [[0, 1, 2, 3], []]


def test_completed_action_seed_cannot_be_silently_reused(tmp_path):
    config = {'selection_worlds': 1, 'report_worlds': 1, 'observation_index': 0, 'config_sha256': 'source'}
    record = row(config, 0, [0, 1])
    path = tmp_path/'world.json'
    screen._publish(path, record)
    assert screen.reopen_world(path, config, 0) == record
    forged = deepcopy(record)
    forged['result']['actions'][0]['rows'][0]['seed'] += 1
    screen._publish(path, forged)
    with pytest.raises(ValueError, match='action rows differ'):
        screen.reopen_world(path, config, 0)
