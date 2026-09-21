import hashlib
import json

import pytest

from shengji.train import policy_wide_world_readout as reader
from test_policy_abc_launcher import isolated_main, launcher  # noqa: F401


@pytest.fixture
def screen(tmp_path, monkeypatch):
    qualification, output = tmp_path / 'qualification', tmp_path / 'screen'
    hashes = {}
    for index, (name, worlds) in enumerate(zip(reader.QUALIFICATION_HASHES, (64, 128, 256))):
        ref, arm = qualification / name, output / name
        ref.mkdir(parents=True)
        arm.mkdir(parents=True)
        recipe = dict(schema='policy-world-duel-v1', seed0=626590000, deals=12,
            checkpoint='old', checkpoint_sha256='soft', worlds=worlds, cap=4000,
            control='production-play', control_effective={'checkpoint': 'old', 'hash': 'prod'},
            policy={'mode': 'policy-value', 'worlds': worlds, 'candidates': 8}, workers=12,
            decision_timeout_seconds=300, source_git_sha='source', harness_sha256='harness',
            policy_module_sha256='policy', runtime={'threads': 1})
        raw = json.dumps(recipe).encode()
        (ref / 'recipe.json').write_bytes(raw)
        hashes[name] = hashlib.sha256(raw).hexdigest()
        (ref / 'summary.json').write_text(json.dumps(dict(expected=12, complete=12,
            errors=[], mean_utility=0)))
        (ref / 'pairs.jsonl').write_text('\n'.join(json.dumps(dict(
            seed=626590000+i, utility=0, mirrors=[0, 0])) for i in range(12)))
        recipe.update(seed0=reader.SEED0, deals=reader.DEALS, checkpoint='relocated')
        recipe['control_effective']['checkpoint'] = 'relocated'
        (arm / 'recipe.json').write_text(json.dumps(recipe))
        # Identical deal noise across arms must cancel in paired contrasts.
        rows = [dict(seed=reader.SEED0+i, utility=(i % 2)*2-1+index,
                     mirrors=[(i % 2)*2-1+index]*2) for i in range(reader.DEALS)]
        (arm / 'pairs.jsonl').write_text('\n'.join(map(json.dumps, rows)))
        (arm / 'summary.json').write_text(json.dumps(dict(expected=800, complete=800,
            errors=[], mean_utility=index)))
    monkeypatch.setattr(reader, 'QUALIFICATION_HASHES', hashes)
    return output, qualification


def test_paired_family_cancels_shared_deal_noise(screen):
    result = reader.readout(*screen)
    for expected, contrast in enumerate(result['primaries'].values(), start=1):
        assert contrast['ci97_5'] == pytest.approx([expected, expected])
    assert result['exploratory_w256_minus_w128']['mean'] == 1
    assert result['exploratory_w256_minus_w128']['ci95'] == pytest.approx([1, 1])
    assert len(result['exploratory_vs_shortlist']) == 3
    assert result['family_size'] == 2 and result['deals'] == 800


@pytest.mark.parametrize('field,value', [('seed0', 626590000), ('deals', 12),
    ('worlds', 128), ('checkpoint_sha256', 'other'), ('workers', 4),
    ('decision_timeout_seconds', 0), ('source_git_sha', 'other')])
def test_recipe_drift(screen, field, value):
    path = screen[0] / 'SOFT_W256_K8' / 'recipe.json'
    recipe = json.loads(path.read_text())
    recipe[field] = value
    path.write_text(json.dumps(recipe))
    with pytest.raises(ValueError):
        reader.readout(*screen)


@pytest.mark.parametrize('failure', ['timeout', 'error', 'mirror', 'missing', 'duplicate', 'nan'])
def test_bad_pairs(screen, failure):
    path = screen[0] / 'SOFT_W128_K8' / 'pairs.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if failure in ('timeout', 'error'):
        rows[0][failure] = True
    elif failure == 'mirror':
        rows[0]['mirrors'] = [1]
    elif failure == 'nan':
        rows[0]['utility'] = float('nan')
    elif failure == 'missing':
        rows.pop()
    else:
        rows.append(rows[0])
    path.write_text('\n'.join(map(json.dumps, rows)))
    with pytest.raises(ValueError):
        reader.readout(*screen)


def test_qualification_identity(screen):
    (screen[1] / 'SOFT_W64_K8' / 'recipe.json').write_text('{}')
    with pytest.raises(ValueError, match='identity mismatch'):
        reader.readout(*screen)


def test_missing_arm_refused(screen):
    (screen[0] / 'SOFT_W256_K8' / 'summary.json').unlink()
    with pytest.raises(FileNotFoundError):
        reader.readout(*screen)


def test_incomplete_summary_refused(screen):
    (screen[0] / 'SOFT_W64_K8' / 'summary.json').write_text(json.dumps(
        dict(expected=800, complete=799, errors=[])))
    with pytest.raises(ValueError, match='incomplete summary'):
        reader.readout(*screen)


def test_failed_qualification_refused(screen):
    (screen[1] / 'SOFT_W64_K8' / 'summary.json').write_text(json.dumps(
        dict(expected=12, complete=12, errors=['timeout'])))
    with pytest.raises(ValueError, match='unsealed'):
        reader.readout(*screen)


@pytest.mark.parametrize('failure', [False, True])
def test_supervisor_to_final_reader(screen, isolated_main, monkeypatch, tmp_path, failure):
    """Fake expensive arm execution, but use real locks, gate and terminal reader."""
    import shutil
    args, output = isolated_main
    monkeypatch.setattr(launcher, 'LOCKS', (tmp_path / 'lane-lock', tmp_path / 'screen-lock'))
    prod = tmp_path / 'prod'
    prod.write_bytes(b'prod')
    monkeypatch.setattr(launcher, 'PRODUCTION_SHA256', hashlib.sha256(b'prod').hexdigest())
    monkeypatch.setattr(launcher, 'WIDE_SCREEN_HOLD', False)  # test only; source stays held
    monkeypatch.setattr(launcher.subprocess, 'check_output',
        lambda cmd, **kw: launcher.PRODUCTION_WORLD_SCALING_SOURCE if 'rev-parse' in cmd else '')
    seen = []
    def arm(cmd, **kw):
        assert kw['seconds'] == 21600
        assert all(lock.is_dir() for lock in launcher.LOCKS)
        dest = Path(cmd[cmd.index('--out')+1])
        seen.append(dest.name)
        shutil.copytree(screen[0] / dest.name, dest)
        if failure and len(seen) == 2:
            (dest / 'summary.json').write_text(json.dumps(dict(
                expected=800, complete=799, errors=['timeout'])))
    from pathlib import Path
    monkeypatch.setattr(launcher, 'run_arm', arm)
    call = args + ['--suite', launcher.WIDE_SCREEN, '--qualification', str(screen[1]),
                   '--production-checkpoint', str(prod), '--run']
    if failure:
        with pytest.raises((RuntimeError, ValueError)):
            launcher.main(call)
        assert len(seen) == 2 and not (output / 'readout.json').exists()
        assert (output / seen[0] / 'pairs.jsonl').exists()  # retain completed work
    else:
        assert launcher.main(call) == 0
        assert seen == list(reader.QUALIFICATION_HASHES)
        result = json.loads((output / 'readout.json').read_text())
        assert result['family_complete'] and len(result['primaries']) == 2
    assert not any(lock.exists() for lock in launcher.LOCKS)
