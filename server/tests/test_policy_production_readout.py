import hashlib
import json

import numpy as np
import pytest

from shengji.train import policy_production_readout as reader


@pytest.fixture
def fixture(monkeypatch, tmp_path):
    reference = dict(seed0=625790000, deals=12, checkpoint='old-path',
                     checkpoint_sha256='soft', control_effective={'checkpoint': 'old', 'recipe': 'pinned'})
    path = tmp_path / 'recipe.json'
    path.write_text(json.dumps(reference))
    monkeypatch.setattr(reader, 'REFERENCE_SHA256', hashlib.sha256(path.read_bytes()).hexdigest())
    actual = dict(reference, seed0=reader.SEED0, deals=800, checkpoint='new-path')
    monkeypatch.setattr(reader, '_read', lambda _: (actual, np.ones(800)))
    return path, actual


def test_readout_pinned_bootstrap(fixture):
    path, _ = fixture
    result = reader.readout('unused', path)
    assert result['ci95'] == [1, 1]
    assert result['positive']
    assert result['bootstrap_seed'] == 20260920


@pytest.mark.parametrize('key,value', [('seed0', 625790000), ('deals', 12),
    ('checkpoint_sha256', 'different'), ('workers', 99)])
def test_recipe_drift_refused(fixture, key, value):
    path, actual = fixture
    actual[key] = value
    with pytest.raises(ValueError, match='recipe drift'):
        reader.readout('unused', path)


def test_reference_hash_refused(fixture):
    path, _ = fixture
    path.write_text('{}')
    with pytest.raises(ValueError, match='identity mismatch'):
        reader.readout('unused', path)


def test_real_rows_missing_mirror_and_timeout_refused(monkeypatch, tmp_path):
    recipe = dict(schema='policy-world-duel-v1', seed0=reader.SEED0, deals=800,
        checkpoint_sha256='soft', worlds=16, cap=4000, control='production-play',
        control_effective={}, policy={}, decision_timeout_seconds=300,
        source_git_sha='source', harness_sha256='harness', policy_module_sha256='policy', runtime={})
    ref = tmp_path / 'qualification.json'
    ref.write_text(json.dumps(dict(recipe, seed0=625790000, deals=12)))
    monkeypatch.setattr(reader, 'REFERENCE_SHA256', hashlib.sha256(ref.read_bytes()).hexdigest())
    (tmp_path / 'recipe.json').write_text(json.dumps(recipe))
    (tmp_path / 'summary.json').write_text(json.dumps(dict(expected=800, complete=800,
        errors=[], mean_utility=1)))
    rows = [dict(seed=reader.SEED0+i, mirrors=[1, 1], utility=1) for i in range(800)]
    pairs = tmp_path / 'pairs.jsonl'
    def write():
        pairs.write_text('\n'.join(json.dumps(row) for row in rows))
    write()
    assert reader.readout(tmp_path, ref)['mean'] == 1
    rows[0]['mirrors'] = [1]
    write()
    with pytest.raises(ValueError, match='mirror utility'):
        reader.readout(tmp_path, ref)
    rows[0]['mirrors'] = [1, 1]
    rows[0]['timeout'] = True
    write()
    with pytest.raises(ValueError, match='refused pair'):
        reader.readout(tmp_path, ref)
