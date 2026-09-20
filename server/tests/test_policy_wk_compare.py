import json

import pytest

from test_policy_strength_compare import runs
from shengji.train import policy_wk_compare as wk


@pytest.fixture
def wk_runs(runs):
    for path, (_, worlds, candidates) in zip(runs, wk.ARMS):
        recipe = json.loads((path/'recipe.json').read_text())
        recipe.update(seed0=wk.SEED0, worlds=worlds,
                      policy=wk.base.policy_recipe('policy-value'))
        recipe['policy'].update(worlds=worlds, candidates=candidates)
        (path/'recipe.json').write_text(json.dumps(recipe))
        rows = [json.loads(line) for line in (path/'pairs.jsonl').read_text().splitlines()]
        for i, row in enumerate(rows):
            row['seed'] = wk.SEED0+i
        (path/'pairs.jsonl').write_text('\n'.join(map(json.dumps, rows)))
    return runs


def test_paired_scaling_contrasts(wk_runs):
    result = wk.compare_wk(wk_runs)
    assert result['seed0'] == wk.SEED0
    for item, delta in zip(result['components'].values(), (.5, 1.)):
        assert item['ci_familywise95_bonferroni'] == pytest.approx([delta, delta])
        assert item['family_size'] == 2
    assert all(v['family_size'] == 3 for v in result['primary'].values())


@pytest.mark.parametrize('mutation', ['qualification', 'worlds', 'candidates', 'source', 'cap', 'module', 'partial'])
def test_drift_and_partial_refused(wk_runs, mutation):
    path = wk_runs[1]/'recipe.json'
    recipe = json.loads(path.read_text())
    if mutation == 'qualification': recipe['seed0'] = 625490000
    if mutation == 'worlds': recipe['worlds'] = 4
    if mutation == 'candidates': recipe['policy']['candidates'] = 16
    if mutation == 'source': recipe['source_git_sha'] = 'b'*40
    if mutation == 'cap': recipe['decision_timeout_seconds'] = 0
    if mutation == 'module': recipe['harness_sha256'] = 'b'*64
    path.write_text(json.dumps(recipe))
    if mutation == 'partial':
        path = wk_runs[1]/'pairs.jsonl'
        path.write_text('\n'.join(path.read_text().splitlines()[:-1]))
    with pytest.raises(ValueError): wk.compare_wk(wk_runs)


def test_arm_order_refused(wk_runs):
    with pytest.raises(ValueError): wk.compare_wk(wk_runs[::-1])
