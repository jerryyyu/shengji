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
