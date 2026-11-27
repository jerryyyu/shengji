import hashlib
import json
from pathlib import Path
import sys

import pytest
import launch


def test_spec_sha_is_exact(tmp_path):
    path = tmp_path / 'spec.json'
    path.write_text('{"x": 1}\n')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert launch._spec(path, digest)['x'] == 1
    with pytest.raises(launch.Refused, match='SHA256'):
        launch._spec(path, '0' * 64)


def test_release_requires_both_pins(tmp_path):
    release = tmp_path / 'RELEASE'
    release.write_text(json.dumps({'launcher_sha256': 'abc', 'spec_sha256': 'def'}))
    launch._release(release, 'abc', 'def')
    with pytest.raises(launch.Refused, match='RELEASE'):
        launch._release(release, 'abc', 'bad')


@pytest.mark.parametrize('mode', ['success', 'failure', 'hold', 'timeout', 'exit-race', 'archive-floor'])
def test_terminal_and_owned_lock_cleanup(tmp_path, monkeypatch, mode):
    source = tmp_path / 'src'
    source.mkdir()
    out = tmp_path / 'out'
    hold = tmp_path / 'HOLD'
    lock = tmp_path / 'lock'
    release = tmp_path / 'RELEASE'
    launcher = Path(launch.__file__)
    release.write_text(json.dumps({'launcher_sha256': launch.sha256(launcher), 'spec_sha256': 'abc'}))
    spec = dict(release=str(release), lock=str(lock), source_dir=str(source), output=str(out),
                rounds=2, workers=1, holds=[str(hold)], max_seconds=0 if mode in ('timeout', 'exit-race') else 10, stop_disk_gib=0)
    code = ('from pathlib import Path; import time,sys; '
            f'p=Path({str(out)!r}); p.mkdir(); (p/"partial").write_text("kept"); ')
    if mode == 'success':
        code += '(p/"manifest.json").write_text("{}");'
    elif mode == 'failure':
        code += 'sys.exit(3)'
    elif mode == 'hold':
        code += f'Path({str(hold)!r}).touch(); time.sleep(20)'
    else:
        code += 'time.sleep(20)'
    monkeypatch.setattr(launch, '_admit', lambda spec: None)
    monkeypatch.setattr(launch, 'command', lambda spec: [sys.executable, '-c', code])
    if mode == 'archive-floor':
        monkeypatch.setattr(launch, '_archive_headroom', lambda volumes: False)
    if mode == 'exit-race':
        real_killpg = launch.os.killpg
        def raced_kill(pid, sig):
            if sig == launch.signal.SIGTERM:
                real_killpg(pid, sig)
                raise ProcessLookupError
            return real_killpg(pid, sig)
        monkeypatch.setattr(launch.os, 'killpg', raced_kill)
        monkeypatch.setattr(launch, 'group_alive', lambda pid: False)
    rc = launch.execute(spec, 'abc', launcher)
    assert rc == (0 if mode == 'success' else 1)
    assert not lock.exists()
    terminal = json.loads(Path(str(out)+'.terminal.0.json').read_text())
    assert terminal['status'] == {'success':'completed','failure':'failed','hold':'held','timeout':'time-cap','exit-race':'time-cap','archive-floor':'disk'}[mode]
    if mode not in ('timeout', 'exit-race', 'archive-floor'):
        assert (out/'partial').read_text() == 'kept'


def test_missing_release_and_existing_lock_do_not_launch(tmp_path, monkeypatch):
    release = tmp_path / 'RELEASE'
    lock = tmp_path / 'lock'
    launcher = Path(launch.__file__)
    spec = dict(release=str(release), lock=str(lock))
    monkeypatch.setattr(launch, '_admit', lambda spec: None)
    with pytest.raises(FileNotFoundError):
        launch.execute(spec, 'abc', launcher)
    assert not lock.exists()
    release.write_text(json.dumps({'launcher_sha256': launch.sha256(launcher), 'spec_sha256': 'abc'}))
    lock.mkdir()
    (lock/'owner').write_text('foreign')
    with pytest.raises(FileExistsError):
        launch.execute(spec, 'abc', launcher)
    assert (lock/'owner').read_text() == 'foreign'


def test_progress_counts_only_published_pairs_and_reports_eta(tmp_path, monkeypatch):
    shards = tmp_path / 'shards'
    shards.mkdir()
    (shards / 'cluster-000000.jsonl').touch()
    (shards / 'cluster-000000.json').touch()
    (shards / 'cluster-000001.jsonl').touch()
    monkeypatch.setattr(launch.subprocess, 'check_output',
                        lambda *a, **k: ' 123 python spawn_main()\n 123 python resource_tracker\n 456 python spawn_main()\n')
    spec = dict(output=str(tmp_path), rounds=10, workers=4, max_seconds=600)
    got = launch.progress(spec, 123, 20)
    assert got['completed_rounds'] == 2
    assert got['percent'] == 20
    assert got['eta_seconds'] == 80
    assert got['live_worker_processes'] == 1
    assert got['deadline_headroom_seconds'] == 580


def admission_spec(tmp_path, monkeypatch):
    monkeypatch.setattr(launch, '_census', lambda: None)
    real = launch.subprocess.check_output
    def git_state(args, **kw):
        if args[:1] == ['git']:
            return 'head\n' if 'rev-parse' in args else ''
        return real(args, **kw)
    monkeypatch.setattr(launch.subprocess, 'check_output', git_state)
    return dict(host=launch.socket.gethostname(), source_dir=str(tmp_path), source_git_head='head',
                rounds=4, workers=1, max_seconds=90, holds=[], foreign_locks=[],
                output=str(tmp_path/'store'), admit_disk_gib=0, stop_disk_gib=0, files={})


@pytest.mark.parametrize('fault', ['missing', 'wrong_id', 'complete', 'hold', 'foreign_lock', 'not_bool'])
def test_resume_admission_refuses_wrong_or_unsafe_store(tmp_path, monkeypatch, fault):
    spec = admission_spec(tmp_path, monkeypatch)
    out = Path(spec['output'])
    out.mkdir()
    spec.update(resume=True, run_id='expected')
    if fault != 'missing':
        (out/'run.json').write_text(json.dumps({'run_id': 'wrong' if fault == 'wrong_id' else 'expected'}))
    if fault == 'complete':
        (out/'manifest.json').touch()
    if fault in ('hold', 'foreign_lock'):
        stop = tmp_path/'stop'
        stop.touch()
        spec['holds' if fault == 'hold' else 'foreign_locks'] = [str(stop)]
    if fault == 'not_bool':
        spec['resume'] = 'true'
    with pytest.raises(launch.Refused):
        launch._admit(spec)


def test_resume_preserves_attempts_and_passes_runner_flag(tmp_path, monkeypatch):
    spec = admission_spec(tmp_path, monkeypatch)
    out = Path(spec['output'])
    out.mkdir()
    (out/'run.json').write_text(json.dumps({'run_id': 'expected'}))
    spec.update(resume=True, run_id='expected', python=sys.executable,
                fly_path='fly', models_path='models', seed_registry='registry', seed=100)
    launch._admit(spec)
    assert launch.command(spec)[-1] == '--resume'
    Path(str(out)+'.log').write_text('legacy')
    Path(str(out)+'.terminal.3.json').write_text('old terminal')
    attempt, log, terminal = launch.attempt_paths(out)
    assert attempt == 4
    assert log.name == 'store.log.4' and terminal.name == 'store.terminal.4.json'
    spec['resume'] = False
    with pytest.raises(launch.Refused, match='existing output'):
        launch._admit(spec)


def test_split_tail_requires_an_explicit_boolean(tmp_path, monkeypatch):
    spec = admission_spec(tmp_path, monkeypatch)
    spec.update(python=sys.executable, fly_path='fly', models_path='models', seed_registry='registry', seed=100)
    assert '--split-tail-mirrors' not in launch.command(spec)
    for value in (False, True):
        spec['split_tail_mirrors'] = value
        launch._admit(spec)
        assert ('--split-tail-mirrors' in launch.command(spec)) == value
    spec['split_tail_mirrors'] = 'false'
    with pytest.raises(launch.Refused, match='split_tail_mirrors'):
        launch._admit(spec)


def test_tranche_requires_internal_output_and_archive_reserve(tmp_path, monkeypatch):
    from types import SimpleNamespace

    spec = admission_spec(tmp_path, monkeypatch)
    spec.update(tranche_volumes=dict(internal_uuid='internal', archive_uuid='archive'),
                stop_disk_gib=150, admit_disk_gib=157)
    archive = tmp_path/'archive'
    archive.mkdir()
    device = tmp_path.stat().st_dev
    real_stat = Path.stat
    monkeypatch.setattr(Path, 'stat', lambda path, **kw: SimpleNamespace(st_dev=device + 1)
                        if path == archive else real_stat(path, **kw))
    monkeypatch.setattr(launch, '_volume', lambda uuid, *, internal: tmp_path if internal else archive)
    free = {tmp_path: 157, archive: 175}
    monkeypatch.setattr(launch.shutil, 'disk_usage', lambda path: SimpleNamespace(free=free[path]*2**30))
    volumes = launch._admit(spec)
    free[archive] -= 1
    assert not launch._archive_headroom(volumes)
    with pytest.raises(launch.Refused, match='175 GiB'):
        launch._admit(spec)
    free[archive] += 1
    spec['admit_disk_gib'] -= 1
    with pytest.raises(launch.Refused, match='full leg'):
        launch._admit(spec)


def test_tranche_admission_uses_published_window_and_runtime_registry(tmp_path, monkeypatch):
    import runpy

    source = Path(__file__).resolve().parents[2]
    api = runpy.run_path(str(source/'server/shengji/seeds.py'))
    spec = admission_spec(tmp_path, monkeypatch)
    runtime = tmp_path/'runtime.json'
    runtime.write_text(json.dumps(dict(schema=api['SCHEMA'], windows=[])))
    registry = source/'server/runs/seed_windows.json'
    name = 'r55-loop-tranche1-2675000000'
    spec.update(source_dir=str(source), rounds=10_000, seed_registry=str(runtime),
                tranche_reservation=dict(registry=str(registry), name=name, seed0=2675000000))
    with pytest.raises(launch.Refused, match='must pin'):
        launch._admit(spec)
    quality = Path(launch.__file__).with_name('shard_quality.py').resolve()
    spec['files'][str(quality)] = launch.sha256(quality)
    for seed in range(2675000000, 2675050000, 5000):
        spec['seed'] = seed
        launch._admit(spec)
        api['check_and_register'](name=f'fixture-{seed}', purpose='trajectory', seed0=seed,
                                  clusters=5000, refuse=None, path=runtime)
    with pytest.raises(launch.Refused, match='already covers'):
        launch._admit(spec)
    spec.update(seed=2675000001)
    with pytest.raises(launch.Refused, match='reserved'):
        launch._admit(spec)
    spec.update(seed=2675050000)
    with pytest.raises(launch.Refused, match='reserved'):
        launch._admit(spec)
    spec.update(seed=seed, resume=True, run_id=f'fixture-{seed}')
    out = Path(spec['output'])
    out.mkdir()
    (out/'run.json').write_text(json.dumps({'run_id': spec['run_id']}))
    launch._admit(spec)
    shadow = tmp_path/'shadow.json'
    own = api['find'](api['load'](registry), name)
    conflict = dict(own, name='another-run', seed0=seed, clusters=1, span=[seed, seed+1])
    shadow.write_text(json.dumps(dict(schema=api['SCHEMA'], windows=[own, conflict])))
    spec['tranche_reservation']['registry'] = str(shadow)
    with pytest.raises(launch.Refused, match='another reservation'):
        launch._admit(spec)


@pytest.mark.parametrize('exit_after_publish', [False, True])
def test_tranche_stops_on_late_stage_fallback(tmp_path, monkeypatch, exit_after_publish):
    out = tmp_path / 'store'
    release = tmp_path / 'RELEASE'
    lock = tmp_path / 'lock'
    launcher = Path(launch.__file__)
    release.write_text(json.dumps({'launcher_sha256': launch.sha256(launcher), 'spec_sha256': 'test'}))
    spec = dict(release=str(release), lock=str(lock), source_dir=str(tmp_path), output=str(out),
                rounds=4, workers=1, holds=[], max_seconds=30, stop_disk_gib=0, tranche_reservation={})
    row = {'decision_kind': 'play', 'allocation': {'serving_decision': {
        'schema': 'pv-search-decision-v1', 'belief_fallback': 0, 'belief_fallback_any': 0,
        'belief_fallback_all_draws': 0, 'belief_fallback_by_stage': {
            'base': 0, 'adaptive_worlds': 1, 'lead_confirm': 0}}}}
    payload = json.dumps(row) + '\n'
    side = json.dumps({'sha256': hashlib.sha256(payload.encode()).hexdigest(), 'counts': {}})
    code = f"""
from pathlib import Path
import time
out = Path({str(out)!r})
shards = out / 'shards'
shards.mkdir(parents=True)
(shards / 'cluster-000000.jsonl').touch()
(shards / 'cluster-000001.jsonl').write_text({payload!r})
(shards / 'cluster-000001.json').write_text({side!r})
if {exit_after_publish!r}:
    (out / 'manifest.json').write_text('{{}}')
else:
    time.sleep(30)
"""
    monkeypatch.setattr(launch, '_admit', lambda spec: None)
    monkeypatch.setattr(launch, 'command', lambda spec: [sys.executable, '-c', code])
    assert launch.execute(spec, 'test', launcher) == 1
    result = json.loads(Path(str(out) + '.terminal.0.json').read_bytes())
    assert result['status'] == 'invalid-store' and 'leg_seal' not in result
    assert result['shard_fault'] == {'shard': 'cluster-000001.json', 'reason': 'play belief fallback'}
    assert (result['returncode'] == 0) == exit_after_publish
    assert (out/'shards/cluster-000001.jsonl').read_text() == payload
    assert not lock.exists()
    spec['resume'] = True
    with pytest.raises(launch.Refused, match='existing shard cluster-000001.json'):
        launch.execute(spec, 'test', launcher)
    assert not Path(str(out) + '.log.1').exists()
