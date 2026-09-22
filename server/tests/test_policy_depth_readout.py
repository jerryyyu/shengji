from copy import deepcopy

import pytest

from shengji.train.policy_depth_readout import ARMS, compare_records


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
