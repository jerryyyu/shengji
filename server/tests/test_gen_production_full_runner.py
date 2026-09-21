import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from test_policy_four_model_readout import four  # noqa: F401


@pytest.fixture
def runner(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / 'scripts'
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location('gen_runner', scripts / 'run_gen_production_full.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def args_for(root):
    return [item for key in ('source', 'python', 'gen4-checkpoint', 'gen3-checkpoint',
                            'production-checkpoint', 'out', 'joint-qualification',
                            'gen4-qualification', 'gen3-qualification')
            for item in ('--' + key, str(root / key))]


@pytest.mark.parametrize('run', [False, True])
def test_unfrozen_gate_precedes_io_and_host_probe(runner, tmp_path, monkeypatch, run):
    monkeypatch.setattr(runner.subprocess, 'check_output', lambda *a, **k: pytest.fail('host probe'))
    with pytest.raises(RuntimeError, match='launch held'):
        runner.main(args_for(tmp_path) + (['--run'] if run else []))
    assert list(tmp_path.iterdir()) == []


@pytest.fixture
def released(runner, tmp_path, monkeypatch):
    # Synthetic released gate only; real constants remain unset.
    monkeypatch.setattr(runner, 'qualification_gate', lambda *a: {'fixture': True})
    monkeypatch.setattr(runner.sys, 'platform', 'linux')
    sup = runner.supervisor
    for key, constant in [('gen4-checkpoint', 'GEN4_CHECKPOINT_SHA256'),
                          ('gen3-checkpoint', 'GEN3_CHECKPOINT_SHA256'),
                          ('production-checkpoint', 'PRODUCTION_SHA256')]:
        (tmp_path / key).write_bytes(key.encode())
        monkeypatch.setattr(sup, constant, hashlib.sha256(key.encode()).hexdigest())
    monkeypatch.setattr(runner.subprocess, 'check_output',
        lambda cmd, **kw: sup.REFERENCE_SOURCE if 'rev-parse' in cmd else '')
    monkeypatch.setattr(sup, 'LOCKS', (tmp_path / 'lock1', tmp_path / 'lock2'))
    monkeypatch.setattr(sup, 'resource_guard', lambda *a: None)
    return runner, tmp_path, args_for(tmp_path)


def test_dry_run_creates_no_outputs_or_locks(released, monkeypatch, capsys):
    runner, root, args = released
    monkeypatch.setattr(runner.supervisor, 'run_arm', lambda *a, **kw: pytest.fail('launch'))
    assert runner.main(args) == 0
    assert json.loads(capsys.readouterr().out)['qualification_evidence'] == {'fixture': True}
    assert not (root / 'out').exists()
    assert not any(lock.exists() for lock in runner.supervisor.LOCKS)


@pytest.mark.parametrize('failure', [None, 'first_arm', 'summary'])
def test_serial_lifecycle_and_failure_preserve_artifacts(released, monkeypatch, failure):
    runner, root, args = released
    calls = []
    def run(cmd, **kw):
        output = Path(cmd[cmd.index('--out') + 1])
        output.mkdir()
        calls.append(output.name)
        assert kw['seconds'] == 21600
        assert 'SHENGJI_FAST' not in kw['env']
        assert kw['env']['OMP_NUM_THREADS'] == '1'
        if failure == 'first_arm':
            raise RuntimeError('fixture child failure')
        (output / 'summary.json').write_text(json.dumps({
            'complete': 799 if failure == 'summary' else 800,
            'expected': 800, 'errors': []}))
    monkeypatch.setattr(runner.supervisor, 'run_arm', run)
    if failure:
        with pytest.raises(RuntimeError):
            runner.main(args + ['--run'])
        assert calls == ['GEN4_W64_K8']
    else:
        assert runner.main(args + ['--run']) == 0
        assert calls == ['GEN4_W64_K8', 'GEN3_W64_K8']
    assert (root / 'out' / 'launch-plan.json').exists()
    assert (root / 'out' / 'GEN4_W64_K8').exists()
    assert not any(lock.exists() for lock in runner.supervisor.LOCKS)


@pytest.mark.parametrize('bad', ['existing_output', 'reservation', 'checkpoint', 'source'])
def test_preflight_refusals(released, monkeypatch, bad):
    runner, root, args = released
    if bad == 'existing_output':
        (root / 'out').mkdir()
    elif bad == 'reservation':
        runner.supervisor.LOCKS[0].mkdir()
    elif bad == 'checkpoint':
        (root / 'gen3-checkpoint').write_text('changed')
    else:
        monkeypatch.setattr(runner.subprocess, 'check_output', lambda *a, **k: 'wrong')
    monkeypatch.setattr(runner.supervisor, 'run_arm', lambda *a, **kw: pytest.fail('launch'))
    with pytest.raises(RuntimeError):
        runner.main(args + ['--run'])


@pytest.mark.parametrize('bad', [None, 'wall', 'hash', 'timeout', 'incomplete'])
def test_qualification_gate_validates_sealed_pairs(runner, four, bad):
    from shengji.train import policy_four_model_readout as reader
    root = four[1]
    seeds = [626290000, 626290000, 626390000, 626490000]
    for (name, _), seed in zip(list(reader.QUALIFICATION_HASHES.items()), seeds, strict=True):
        arm = root / name
        recipe = json.loads((arm / 'recipe.json').read_text())
        recipe.update(seed0=seed, deals=12)
        raw = json.dumps(recipe).encode()
        (arm / 'recipe.json').write_bytes(raw)
        reader.QUALIFICATION_HASHES[name] = hashlib.sha256(raw).hexdigest()
        rows = [dict(seed=seed+i, utility=1, mirrors=[1, 1]) for i in range(12)]
        if name == 'GEN3_W64_K8' and bad == 'timeout':
            rows[0]['timeout'] = True
        if name == 'GEN3_W64_K8' and bad == 'incomplete':
            rows.pop()
        (arm / 'pairs.jsonl').write_text('\n'.join(json.dumps(row) for row in rows))
        (arm / 'summary.json').write_text(json.dumps(dict(complete=12, expected=12,
            errors=[], mean_utility=1, wall_seconds=-1 if bad == 'wall' else 150)))
    if bad == 'hash':
        (root / 'GEN3_W64_K8' / 'recipe.json').write_text('{}')
    if bad:
        with pytest.raises((RuntimeError, ValueError)):
            runner.qualification_gate(root, root, root)
    else:
        evidence = runner.qualification_gate(root, root, root)
        assert len(evidence) == 4
        assert all(item['wall_seconds'] == 150 for item in evidence.values())
