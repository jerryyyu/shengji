import hashlib
import json

import pytest

from shengji.train import policy_four_model_readout as reader


def test_unfrozen_release_refuses_before_io():
    with pytest.raises(ValueError, match='readout held'):
        reader.readout('/missing', '/missing', '/missing', '/missing')


@pytest.fixture
def four(tmp_path, monkeypatch):
    output, qualification = tmp_path / 'full', tmp_path / 'qual'
    hashes = {}
    for index, name in enumerate(reader.QUALIFICATION_HASHES):
        ref, arm = qualification / name, output / name
        ref.mkdir(parents=True)
        arm.mkdir(parents=True)
        recipe = dict(schema='policy-world-duel-v1', seed0=626290000+index*100000,
            deals=12, checkpoint='old', checkpoint_sha256=name, worlds=64, cap=4000,
            control='production-play', control_effective={'checkpoint': 'old', 'hash': 'prod'},
            policy={'mode': 'policy-value', 'worlds': 64, 'top_k': 8}, workers=12,
            decision_timeout_seconds=300, source_git_sha='source', harness_sha256='harness',
            policy_module_sha256='policy', runtime={'threads': 1})
        raw = json.dumps(recipe).encode()
        (ref / 'recipe.json').write_bytes(raw)
        hashes[name] = hashlib.sha256(raw).hexdigest()
        recipe.update(seed0=reader.SEED0, deals=800, checkpoint='new')
        (arm / 'recipe.json').write_text(json.dumps(recipe))
        value = index - 1
        (arm / 'summary.json').write_text(json.dumps(dict(expected=800, complete=800,
            errors=[], mean_utility=value)))
        (arm / 'pairs.jsonl').write_text('\n'.join(json.dumps(dict(seed=reader.SEED0+i,
            utility=value, mirrors=[value, value])) for i in range(800)))
    monkeypatch.setattr(reader, 'QUALIFICATION_HASHES', hashes)
    return output, qualification, qualification, qualification


def test_complete_family_and_joint_contrasts(four, monkeypatch):
    seen = []
    quantile = reader.np.quantile
    def capture(a, q, *args, **kw):
        seen.append(q)
        return quantile(a, q, *args, **kw)
    monkeypatch.setattr(reader.np, 'quantile', capture)
    result = reader.readout(*four)
    assert result['family_complete'] and result['family_size'] == 4
    assert seen[:4] == [[.00625, .99375]] * 4
    assert seen[4:] == [[.025, .975]] * 6
    assert [v['ci98_75'] for v in result['primaries'].values()] == [[-1,-1],[0,0],[1,1],[2,2]]
    assert result['exploratory_model_contrasts']['GEN3_W64_K8_minus_GEN4_W64_K8'] == {
        'mean': 1, 'ci95': [1, 1]}
    assert result['bootstrap_replicates'] == 10000


def test_shared_deal_noise_cancels_in_paired_model_contrast(four):
    for name in reader.QUALIFICATION_HASHES:
        path = four[0] / name / 'pairs.jsonl'
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        for i, row in enumerate(rows):
            row['utility'] += 1 if i % 2 else -1
            row['mirrors'] = [row['utility']] * 2
        # Alternating perturbations have zero mean; summary stays exact.
        path.write_text('\n'.join(json.dumps(row) for row in rows))
    result = reader.readout(*four)
    assert result['primaries']['GEN4_W64_K8']['ci98_75'][0] < 1
    contrast = result['exploratory_model_contrasts']['GEN3_W64_K8_minus_GEN4_W64_K8']
    assert contrast['mean'] == 1
    assert contrast['ci95'] == pytest.approx([1, 1], abs=1e-12)


@pytest.mark.parametrize('bad', ['missing', 'duplicate', 'timeout', 'error',
                               'mirror', 'summary', 'recipe', 'qualification'])
def test_last_model_invalid_refuses_whole_family(four, bad):
    arm = four[0] / 'GEN3_W64_K8'
    path = arm / 'pairs.jsonl'
    if bad == 'qualification':
        (four[3] / 'GEN3_W64_K8' / 'recipe.json').write_text('{}')
    elif bad == 'recipe':
        p = arm / 'recipe.json'
        r = json.loads(p.read_text()); r['worlds'] = 128
        p.write_text(json.dumps(r))
    elif bad == 'summary':
        (arm / 'summary.json').write_text('{}')
    else:
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        if bad == 'missing':
            rows.pop()
        elif bad == 'duplicate':
            rows.append(rows[0])
        elif bad == 'mirror':
            rows[0]['mirrors'] = [1]
        else:
            rows[0][bad] = True
        path.write_text('\n'.join(json.dumps(row) for row in rows))
    with pytest.raises(ValueError):
        reader.readout(*four)
