import hashlib
import json

import pytest

from shengji.train import policy_joint_production_readout as reader


@pytest.fixture
def screen(tmp_path, monkeypatch):
    qualification, output = tmp_path / 'qualification', tmp_path / 'screen'
    hashes = {}
    for index, name in enumerate(reader.QUALIFICATION_HASHES):
        ref, arm = qualification / name, output / name
        ref.mkdir(parents=True)
        arm.mkdir(parents=True)
        recipe = dict(schema='policy-world-duel-v1', seed0=626290000, deals=12,
            checkpoint='old', checkpoint_sha256=name, worlds=64, cap=4000,
            control='production-play', control_effective={'checkpoint': 'old', 'hash': 'prod'},
            policy={'mode': 'policy-value', 'worlds': 64, 'top_k': 8}, workers=12,
            decision_timeout_seconds=300, source_git_sha='source', harness_sha256='harness',
            policy_module_sha256='policy', runtime={'threads': 1})
        raw = json.dumps(recipe).encode()
        (ref / 'recipe.json').write_bytes(raw)
        hashes[name] = hashlib.sha256(raw).hexdigest()
        recipe.update(seed0=reader.SEED0, deals=reader.DEALS, checkpoint='new')
        recipe['control_effective']['checkpoint'] = 'new'
        (arm / 'recipe.json').write_text(json.dumps(recipe))
        value = index + 1
        (arm / 'summary.json').write_text(json.dumps(dict(expected=800, complete=800,
            errors=[], mean_utility=value)))
        (arm / 'pairs.jsonl').write_text('\n'.join(json.dumps(dict(seed=reader.SEED0+i,
            utility=value, mirrors=[value, value])) for i in range(800)))
    monkeypatch.setattr(reader, 'QUALIFICATION_HASHES', hashes)
    return output, qualification


def test_primary_family_and_paired_contrast(screen):
    result = reader.readout(*screen)
    assert [r['ci97_5'] for r in result['primaries'].values()] == [[1, 1], [2, 2]]
    assert result['exploratory_g1_minus_m1'] == dict(mean=1, ci95=[1, 1])
    assert result['bootstrap_seed'] == 20260921
    assert result['deals'] == 800


@pytest.mark.parametrize('field,value', [('seed0', 626290000), ('deals', 12),
    ('worlds', 16), ('checkpoint_sha256', 'other'), ('workers', 4),
    ('decision_timeout_seconds', 0), ('source_git_sha', 'other')])
def test_recipe_drift(screen, field, value):
    path = screen[0] / 'JS_G1_W64_K8' / 'recipe.json'
    recipe = json.loads(path.read_text())
    recipe[field] = value
    path.write_text(json.dumps(recipe))
    with pytest.raises(ValueError):
        reader.readout(*screen)


def test_qualification_identity(screen):
    (screen[1] / 'JS_M1_W64_K8' / 'recipe.json').write_text('{}')
    with pytest.raises(ValueError, match='identity mismatch'):
        reader.readout(*screen)


@pytest.mark.parametrize('failure', ['timeout', 'error', 'mirror', 'missing', 'duplicate'])
def test_bad_pairs_refused(screen, failure):
    path = screen[0] / 'JS_M1_W64_K8' / 'pairs.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if failure in ('timeout', 'error'):
        rows[0][failure] = True
    elif failure == 'mirror':
        rows[0]['mirrors'] = [1]
    elif failure == 'missing':
        rows.pop()
    else:
        rows.append(rows[0])
    path.write_text('\n'.join(json.dumps(row) for row in rows))
    with pytest.raises(ValueError):
        reader.readout(*screen)


def test_unsealed_summary_refused(screen):
    path = screen[0] / 'JS_G1_W64_K8' / 'summary.json'
    summary = json.loads(path.read_text())
    summary['errors'] = ['timeout']
    path.write_text(json.dumps(summary))
    with pytest.raises(ValueError, match='unsealed'):
        reader.readout(*screen)
