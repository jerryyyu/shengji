import json

import pytest

from test_policy_strength_compare import runs
from shengji.train import policy_grid_compare as grid


@pytest.fixture
def grid_runs(runs):
    paths = runs[:2]
    for path, (_, checksum) in zip(paths, grid.ARMS):
        recipe = json.loads((path/'recipe.json').read_text())
        recipe.update(seed0=grid.SEED0, checkpoint_sha256=checksum,
                      policy=grid.base.policy_recipe('policy-value'))
        (path/'recipe.json').write_text(json.dumps(recipe))
        rows = [json.loads(line) for line in (path/'pairs.jsonl').read_text().splitlines()]
        for i, row in enumerate(rows): row['seed'] = grid.SEED0+i
        (path/'pairs.jsonl').write_text('\n'.join(map(json.dumps, rows)))
    return paths


def test_matched_contrast(grid_runs):
    result = grid.compare_grid(grid_runs)
    assert result['matched_grid_minus_mlp']['ci95'] == pytest.approx([.5, .5])
    assert all(item['family_size'] == 2 for item in result['primary'].values())
    assert result['checkpoints'] == dict(grid.ARMS)


@pytest.mark.parametrize('mutation', ['checkpoint', 'qualification', 'module', 'policy', 'partial', 'order'])
def test_drift_refused(grid_runs, mutation):
    path = grid_runs[1]/'recipe.json'
    recipe = json.loads(path.read_text())
    if mutation == 'checkpoint': recipe['checkpoint_sha256'] = grid.ARMS[0][1]
    if mutation == 'qualification': recipe['seed0'] = 625590000
    if mutation == 'module': recipe['harness_sha256'] = 'b'*64
    if mutation == 'policy': recipe['policy']['candidates'] = 16
    path.write_text(json.dumps(recipe))
    if mutation == 'partial':
        path = grid_runs[1]/'pairs.jsonl'
        path.write_text('\n'.join(path.read_text().splitlines()[:-1]))
    if mutation == 'order': grid_runs.reverse()
    with pytest.raises(ValueError): grid.compare_grid(grid_runs)
