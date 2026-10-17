from copy import deepcopy
import json

import pytest

from shengji.train.policy_depth_readout import ARMS, MODES, WORK_KEYS, _costs, compare_records, readout


def records():
    return {name: [dict(seed=s, mirrors=[v, v], utility=v, error=None, timeout=False,
                       sides={'control': dict(fallback_decisions=0, budget_fallbacks=0,
                                              error_fallbacks=0)})
                   for s, v in zip(range(10, 14), [-1., 0., 1., 2.])]
            for name in ARMS}


def test_joint_resampling_preserves_covariance_and_primary_estimand():
    data = records()
    # Arm order on disk must not change pairing.
    data[ARMS[1]].reverse()
    for row in data[ARMS[2]]:
        row['utility'] += .5
        row['mirrors'] = [v + .5 for v in row['mirrors']]
    result = compare_records(data, range(10, 14), replicates=1000)
    assert result['primaries_vs_production'][ARMS[2]]['mean'] == 1.
    assert result['primaries_vs_production'][ARMS[2]]['confidence'] == .975
    contrast = result['exploratory_component_contrasts'][f'{ARMS[2]}_minus_{ARMS[1]}']
    assert contrast['mean'] == .5
    assert contrast['interval'] == [.5, .5]
    assert result == compare_records(data, range(10, 14), replicates=1000)


@pytest.mark.parametrize('defect', ['missing', 'duplicate', 'extra', 'timeout', 'error',
                                  'mirror', 'mean_mismatch', 'nonfinite', 'fallback', 'telemetry'])
def test_no_partial_or_unclean_family_inference(defect):
    data = deepcopy(records())
    rows = data[ARMS[1]]
    if defect == 'missing':
        rows.pop()
    elif defect == 'duplicate':
        rows.append(deepcopy(rows[0]))
    elif defect == 'extra':
        rows.append(dict(rows[0], seed=99))
    elif defect in ('timeout', 'error'):
        rows[0][defect] = True
    elif defect == 'mirror':
        rows[0]['mirrors'] = [0.]
    elif defect == 'mean_mismatch':
        rows[0]['utility'] += .5
    elif defect == 'nonfinite':
        rows[0]['utility'] = float('nan')
    elif defect == 'fallback':
        rows[0]['sides']['control']['budget_fallbacks'] = 1
    else:
        del rows[0]['sides']
    result = compare_records(data, range(10, 14), replicates=100)
    assert result['status'] == 'incomplete_or_unclean'
    assert not result['family_complete']
    assert 'primaries_vs_production' not in result


@pytest.mark.parametrize('seeds', [[], [10, 10], [626700000], [True]])
def test_refuse_invalid_or_qualification_seed_declaration(seeds):
    with pytest.raises(ValueError):
        compare_records(records(), seeds)


def saved_screen(tmp_path):
    frozen = {}
    data = records()
    for arm, mode in zip(ARMS, MODES):
        recipe = dict(seed0=10, deals=4, control='production-pv-r29', worlds=64,
                      policy=dict(mode=mode, candidates=8),
                      control_effective={'checkpoint_sha256': 'frozen-test-model'},
                      source_git_sha='frozen-test-source', decision_timeout_seconds=300)
        frozen[arm] = deepcopy(recipe)
        path = tmp_path / arm
        path.mkdir()
        for row in data[arm]:
            row['max_rss_kib'] = 1234
            row['sides'] = {role: dict.fromkeys(WORK_KEYS, 0) for role in ('policy', 'control')}
            for side in row['sides'].values():
                side.update(seconds=[.1, .3], decisions=2, sample_attempts=5, worlds=4)
        (path / 'recipe.json').write_text(json.dumps(recipe))
        (path / 'pairs.jsonl').write_text('\n'.join(map(json.dumps, data[arm])) + '\n')
        (path / 'summary.json').write_text(json.dumps(dict(expected=4, complete=4,
                                                          errors=[], wall_seconds=12.)))
    return frozen


def test_saved_screen_reconstructs_statistics_and_costs(tmp_path):
    frozen = saved_screen(tmp_path)
    result = readout(tmp_path, frozen, replicates=100)
    assert result['family_complete']
    cost = result['costs'][ARMS[2]]
    assert cost['policy']['timing']['mean_seconds'] == pytest.approx(.2)
    assert cost['policy']['sample_attempts'] == 20
    assert cost['policy']['worlds'] == 16
    assert cost['max_process_rss_kib'] == 1234
    assert cost['wall_seconds'] == 12.
    assert result['primaries_vs_production'][ARMS[2]]['mean'] == .5


def test_latency_tail_quantiles_pool_decisions_not_pair_quantiles():
    rows = []
    for times in ([0.], [1., 2., 3., 100.]):
        sides = {}
        for role in ('policy', 'control'):
            sides[role] = dict.fromkeys(WORK_KEYS, 0)
            sides[role].update(seconds=times, decisions=len(times))
        rows.append(dict(sides=sides, max_rss_kib=1234, error=None, timeout=False))
    costs = _costs(rows)
    for role in ('policy', 'control'):
        timing = costs[role]['timing']
        assert timing['mean_seconds'] == pytest.approx(21.2)
        assert timing['p95_seconds'] == pytest.approx(80.6)
        assert timing['p99_seconds'] == pytest.approx(96.12)
        assert timing['max_seconds'] == 100.
    for role in ('policy', 'control'):
        assert _costs([])[role]['timing']['p99_seconds'] is None


@pytest.mark.parametrize('defect', ['recipe', 'source', 'missing_summary', 'failed_summary',
                                  'partial_json', 'missing_rows', 'costs', 'counter'])
def test_artifact_boundary_withholds_estimates(tmp_path, defect):
    frozen = saved_screen(tmp_path)
    path = tmp_path / ARMS[2]
    if defect in ('recipe', 'source'):
        recipe = deepcopy(frozen[ARMS[2]])
        recipe['worlds' if defect == 'recipe' else 'source_git_sha'] = 'changed'
        (path / 'recipe.json').write_text(json.dumps(recipe))
    elif defect == 'missing_summary':
        (path / 'summary.json').unlink()
    elif defect == 'failed_summary':
        (path / 'summary.json').write_text(json.dumps(dict(expected=4, complete=4,
                                                          errors=['failure'], wall_seconds=12.)))
    elif defect == 'partial_json':
        (path / 'pairs.jsonl').write_text('{')
    else:
        rows = [json.loads(line) for line in (path / 'pairs.jsonl').read_text().splitlines()]
        if defect == 'missing_rows':
            rows.pop()
        elif defect == 'costs':
            rows[0]['sides']['policy']['seconds'][0] = float('nan')
        else:
            rows[0]['sides']['policy']['worlds'] = -1
        (path / 'pairs.jsonl').write_text('\n'.join(map(json.dumps, rows)))
    result = readout(tmp_path, frozen, replicates=100)
    assert not result['family_complete']
    assert 'primaries_vs_production' not in result


def test_frozen_family_cannot_mix_controls(tmp_path):
    frozen = saved_screen(tmp_path)
    frozen[ARMS[1]]['control_effective']['checkpoint_sha256'] = 'another-model'
    with pytest.raises(ValueError, match='inconsistent'):
        readout(tmp_path, frozen)
