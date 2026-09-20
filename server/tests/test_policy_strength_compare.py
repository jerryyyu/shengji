import json

import numpy as np
import pytest

from shengji.train import policy_strength_compare as screen


@pytest.fixture
def runs(tmp_path):
    paths = []
    for index, mode in enumerate(screen.MODES):
        path = tmp_path / mode
        path.mkdir()
        values = np.tile([-1., 1.], 400) + index * .5
        control = dict(requested='mc-lcb', registry_policy='mc-s0-report-lcb',
            **{'class': 'MCS0ReportLCB'}, N_DETERMINIZATIONS=30,
            REPORT_FOLD_WORLDS=300, REPORT_RULE='lcb', REQUIRE_EXACT_WORK=True,
            rollout_policy='HeuristicBot', all_uppercase_attributes={'EXACT_ENDGAME': False})
        recipe = dict(schema='policy-world-duel-v1', seed0=screen.SEED0, deals=800,
            workers=12, worlds=4, cap=4000, checkpoint_sha256=screen.CHECKPOINT,
            source_git_sha=screen.SOURCE, decision_timeout_seconds=300,
            policy=screen.policy_recipe(mode), control='mc-lcb', control_effective=control,
            runtime={'environment': dict(MKL_NUM_THREADS='1', OMP_NUM_THREADS='1',
                OPENBLAS_NUM_THREADS='1', SHENGJI_REQUIRE_VOIDS='1')})
        for key in ('policy_value_module_sha256', 'policy_selective_mc_module_sha256',
                    'policy_lookahead_module_sha256', 'harness_sha256', 'policy_module_sha256'):
            recipe[key] = 'a'*64
        (path/'recipe.json').write_text(json.dumps(recipe))
        (path/'summary.json').write_text(json.dumps(dict(errors=[], complete=800,
            expected=800, mean_utility=float(values.mean()))))
        (path/'pairs.jsonl').write_text('\n'.join(json.dumps(dict(
            seed=screen.SEED0+i, mirrors=[v, v], utility=v)) for i, v in enumerate(values)))
        paths.append(path)
    return paths


def test_joint_bootstrap_keeps_pairing_and_adjusts_intervals(runs):
    result = screen.compare_strength(*runs)
    components = list(result['exploratory_components'].values())
    assert components[0]['ci95'] == pytest.approx([.5, .5])
    assert components[1]['ci95'] == pytest.approx([1., 1.])
    for item in result['primary'].values():
        low, high = item['ci_familywise95_bonferroni']
        assert low <= item['ci95'][0] <= item['ci95'][1] <= high


@pytest.mark.parametrize('field,value', [('deals',12), ('seed0',625300000),
    ('checkpoint_sha256','b'*64), ('source_git_sha','changed'), ('workers',16),
    ('control','mc-smart4'), ('policy_value_module_sha256',''),
    ('decision_timeout_seconds',0)])
def test_frozen_recipe_changes_refused(runs, field, value):
    path=runs[1]/'recipe.json'
    recipe=json.loads(path.read_text()); recipe[field]=value
    path.write_text(json.dumps(recipe))
    with pytest.raises(ValueError): screen.compare_strength(*runs)


@pytest.mark.parametrize('mutation', ['mode', 'worlds', 'control', 'runtime', 'module', 'missing', 'timeout'])
def test_policy_control_runtime_and_result_fail_closed(runs, mutation):
    path=runs[2]/'recipe.json'
    recipe=json.loads(path.read_text())
    if mutation=='mode': recipe['policy']['mode']='policy-value'
    if mutation=='worlds': recipe['policy']['continuation_worlds']=2
    if mutation=='control': recipe['control_effective']['REPORT_FOLD_WORLDS']=4
    if mutation=='runtime': recipe['runtime']['environment']['SHENGJI_FAST']='1'
    if mutation=='module': recipe['harness_sha256']='b'*64
    path.write_text(json.dumps(recipe))
    pairs=runs[2]/'pairs.jsonl'
    rows=pairs.read_text().splitlines()
    if mutation=='missing': rows.pop()
    if mutation=='timeout':
        row=json.loads(rows[0]); row['timeout']=True; rows[0]=json.dumps(row)
    pairs.write_text('\n'.join(rows))
    with pytest.raises(ValueError): screen.compare_strength(*runs)
