import hashlib
import json

import numpy as np
import pytest

from shengji.train import policy_model_readout as reader


@pytest.fixture
def data(tmp_path, monkeypatch):
    hashes, recipes = [], {}
    for arm, worlds in zip(reader.ARMS, (16, 16, 16)):
        path = tmp_path / arm
        path.mkdir()
        r = dict(seed0=626090000, deals=12, worlds=worlds, checkpoint='a', checkpoint_sha256='pinned')
        raw = json.dumps(r).encode()
        (path / 'recipe.json').write_bytes(raw)
        hashes.append(hashlib.sha256(raw).hexdigest())
        recipes[arm] = dict(r, seed0=reader.SEED0, deals=800)
    monkeypatch.setattr(reader, 'REFERENCE_HASHES', tuple(hashes))
    # Perfectly correlated arms must have exactly zero paired contrasts.
    monkeypatch.setattr(reader, '_read', lambda path:
        (recipes[path.name], np.tile([-1., 1.], 400)))
    return tmp_path, recipes


def test_joint_resampling_and_families(data):
    path, _ = data
    result = reader.compare(path, path)
    assert len(result['primary']) == 3
    assert all(r['family_size'] == 3 for r in result['primary'].values())
    assert all(r['family_size'] == 2 and r['ci95'] == [0., 0.]
               for r in result['components'].values())
    assert result['bootstrap_seed'] == 20260920


@pytest.mark.parametrize('key,value', [('deals', 12), ('seed0', 625890000),
    ('worlds', 4), ('checkpoint_sha256', 'wrong')])
def test_recipe_drift(data, key, value):
    path, recipes = data
    recipes['JS_M1_W16_K8'][key] = value
    with pytest.raises(ValueError, match='recipe drift'):
        reader.compare(path, path)


def test_reference_replacement_refused(data):
    path, _ = data
    (path / 'JS_G1_W16_K8' / 'recipe.json').write_text('{}')
    with pytest.raises(ValueError, match='identity mismatch'):
        reader.compare(path, path)


def test_model_contrast_direction(data, monkeypatch):
    path, recipes = data
    offsets = dict(zip(reader.ARMS, (3., 1., 0.)))
    monkeypatch.setattr(reader, '_read', lambda p:
        (recipes[p.name], np.full(800, offsets[p.name])))
    result = reader.compare(path, path)
    assert result['components']['SOFT_W16_K8 minus JS_M1_W16_K8']['mean'] == 2.
    assert result['components']['JS_G1_W16_K8 minus JS_M1_W16_K8']['mean'] == -1.


@pytest.fixture
def file_data(tmp_path, monkeypatch):
    """Exercise the real strict reader through complete on-disk arm artifacts."""
    root, qualification = tmp_path / 'full', tmp_path / 'qualification'
    hashes = []
    for index, arm in enumerate(reader.ARMS):
        full, qual = root / arm, qualification / arm
        full.mkdir(parents=True)
        qual.mkdir(parents=True)
        recipe = dict(schema='policy-world-duel-v1', seed0=626090000,
            deals=12, checkpoint='qualification-model', checkpoint_sha256=arm,
            worlds=16, cap=4000, control='mc-lcb', control_effective={'n': 30},
            policy={'mode': 'policy-value', 'worlds': 16, 'candidates': 8},
            decision_timeout_seconds=300, source_git_sha='frozen',
            harness_sha256='harness', policy_module_sha256='policy',
            runtime={'engine': 'pure'})
        raw = json.dumps(recipe).encode()
        (qual / 'recipe.json').write_bytes(raw)
        hashes.append(hashlib.sha256(raw).hexdigest())
        recipe.update(seed0=reader.SEED0, deals=800, checkpoint='full-model')
        (full / 'recipe.json').write_text(json.dumps(recipe))
        rows = [dict(seed=reader.SEED0+i, mirrors=[index-1, index+1],
                     utility=float(index)) for i in range(800)]
        # Completion order differs from seed order; pairing must sort by seed.
        (full / 'pairs.jsonl').write_text('\n'.join(map(json.dumps, reversed(rows))))
        (full / 'summary.json').write_text(json.dumps(dict(
            complete=800, expected=800, errors=[], mean_utility=float(index))))
    monkeypatch.setattr(reader, 'REFERENCE_HASHES', tuple(hashes))
    return root, qualification


def test_real_file_readout(file_data):
    result = reader.compare(*file_data)
    assert [r['mean'] for r in result['primary'].values()] == [0., 1., 2.]
    assert [r['mean'] for r in result['components'].values()] == [-1., 1.]


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'mirror', 'timeout',
                                  'summary', 'error', 'control'])
def test_real_file_fail_closed(file_data, fault):
    root, qualification = file_data
    arm = root / reader.ARMS[0]
    path = arm / 'pairs.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if fault == 'missing':
        rows.pop()
    elif fault == 'duplicate':
        rows[-1] = rows[0]
    elif fault == 'mirror':
        rows[0]['mirrors'] = [0.]
    elif fault == 'timeout':
        rows[0]['timeout'] = True
    elif fault in ('summary', 'error'):
        p = arm / 'summary.json'
        summary = json.loads(p.read_text())
        summary['mean_utility' if fault == 'summary' else 'errors'] = (
            99. if fault == 'summary' else ['worker failed'])
        p.write_text(json.dumps(summary))
    else:
        p = arm / 'recipe.json'
        recipe = json.loads(p.read_text())
        recipe['control_effective']['n'] = 31
        p.write_text(json.dumps(recipe))
    path.write_text('\n'.join(map(json.dumps, rows)))
    with pytest.raises(ValueError):
        reader.compare(root, qualification)
