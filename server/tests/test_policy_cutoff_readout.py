import copy
import hashlib
import json

import pytest

from shengji.train import policy_cutoff_readout as reader


@pytest.fixture
def screen(tmp_path, monkeypatch):
    qualification = tmp_path / 'qualification'
    recipe = dict(schema='policy-world-duel-v1', seed0=626190000, deals=1,
        checkpoint_sha256='fixed', checkpoint='/model', worlds=16, cap=4000,
        control='mc-levels-terminal', control_effective={'utility': 'levels'},
        policy={'mode': 'mc-heuristic-cutoff'}, decision_timeout_seconds=300,
        source_git_sha='fixed', harness_sha256='fixed', policy_module_sha256='fixed',
        runtime={'engine': 'pure'}, workers=1)
    hashes = {}
    for name in reader.QUALIFICATION_HASHES:
        ref = copy.deepcopy(recipe)
        if name == 'LEARNED_CUTOFF_T1':
            ref['control'] = 'mc-heuristic-cutoff'
            ref['control_effective'] = {'utility': 'cutoff'}
            ref['policy']['mode'] = 'mc-pv-cutoff'
        raw = json.dumps(ref).encode()
        directory = qualification / name
        directory.mkdir(parents=True)
        (directory / 'recipe.json').write_bytes(raw)
        hashes[name] = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(reader, 'QUALIFICATION_HASHES', hashes)
    root = tmp_path / 'screen'
    for i, (name, expected) in enumerate(zip(reader.ARMS, reader.expected_recipes(qualification))):
        directory = root / name
        directory.mkdir(parents=True)
        (directory / 'recipe.json').write_text(json.dumps(expected))
        (directory / 'summary.json').write_text(json.dumps(dict(
            complete=48, expected=48, errors=[], mean_utility=i)))
        (directory / 'pairs.jsonl').write_text('\n'.join(json.dumps(dict(
            seed=reader.SEED0+j, mirrors=[i, i], utility=i)) for j in range(48)))
    return root, qualification


def test_complete_readout(screen):
    result = reader.readout(*screen)
    assert result['primaries'][reader.ARMS[1]]['ci97_5'] == [1, 1]
    assert result['exploratory_model_minus_value'] == {'mean': 1, 'ci95': [1, 1]}


@pytest.mark.parametrize('field,value', [('worlds', 4), ('workers', 1),
    ('control', 'mc-lcb'), ('checkpoint_sha256', 'wrong'), ('seed0', 1)])
def test_recipe_drift(screen, field, value):
    root, qualification = screen
    path = root / reader.ARMS[1] / 'recipe.json'
    recipe = json.loads(path.read_text())
    recipe[field] = value
    path.write_text(json.dumps(recipe))
    with pytest.raises(ValueError):
        reader.readout(root, qualification)


@pytest.mark.parametrize('fault', ['timeout', 'missing', 'duplicate', 'mirror'])
def test_bad_pairs(screen, fault):
    root, qualification = screen
    path = root / reader.ARMS[1] / 'pairs.jsonl'
    rows = [json.loads(x) for x in path.read_text().splitlines()]
    if fault == 'timeout':
        rows[0]['timeout'] = True
    elif fault == 'missing':
        rows.pop()
    elif fault == 'duplicate':
        rows.append(rows[0])
    else:
        rows[0]['mirrors'] = [0]
    path.write_text('\n'.join(map(json.dumps, rows)))
    with pytest.raises(ValueError):
        reader.readout(root, qualification)


def test_qualification_tamper(screen):
    root, qualification = screen
    path = qualification / 'VALUE_CUTOFF_T1' / 'recipe.json'
    path.write_text(path.read_text() + ' ')
    with pytest.raises(ValueError, match='identity'):
        reader.readout(root, qualification)
