import json

import pytest

from shengji.train import policy_model_family_readout as reader
from test_policy_joint_production_readout import screen  # noqa: F401


def test_four_model_family_is_not_reduced_to_two_completed_arms(screen, monkeypatch):
    seen = []
    original = reader.np.quantile
    def quantile(a, q, *args, **kwargs):
        seen.append(q)
        return original(a, q, *args, **kwargs)
    monkeypatch.setattr(reader.np, 'quantile', quantile)
    result = reader.readout(*screen)
    assert result['family_size'] == 4
    assert result['family_complete'] is False
    assert result['pending_models'] == ['GEN4_W64_K8', 'GEN3_W64_K8']
    assert seen == [[.00625, .99375], [.00625, .99375]]
    assert [v['ci98_75'] for v in result['primaries'].values()] == [[1, 1], [2, 2]]
    assert result['deals'] == 800
    assert result['bootstrap_seed'] == 20260921


@pytest.mark.parametrize('bad', ['recipe', 'qualification', 'missing', 'timeout'])
def test_incomplete_or_drifted_inputs_refused(screen, bad):
    output, qualification = screen
    arm = output / 'JS_G1_W64_K8'
    if bad == 'qualification':
        (qualification / 'JS_G1_W64_K8' / 'recipe.json').write_text('{}')
    elif bad == 'recipe':
        path = arm / 'recipe.json'
        recipe = json.loads(path.read_text())
        recipe['worlds'] = 128
        path.write_text(json.dumps(recipe))
    else:
        path = arm / 'pairs.jsonl'
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        if bad == 'missing':
            rows.pop()
        else:
            rows[0]['timeout'] = True
        path.write_text('\n'.join(json.dumps(row) for row in rows))
    with pytest.raises(ValueError):
        reader.readout(*screen)
