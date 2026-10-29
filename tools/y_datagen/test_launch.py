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


@pytest.mark.parametrize('mode', ['success', 'failure', 'hold', 'timeout', 'exit-race'])
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
                holds=[str(hold)], max_seconds=0 if mode in ('timeout', 'exit-race') else 10, stop_disk_gib=0)
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
    if mode == 'exit-race':
        real_killpg = launch.os.killpg
        def raced_kill(pid, sig):
            real_killpg(pid, sig)
            if sig == launch.signal.SIGTERM:
                raise ProcessLookupError
        monkeypatch.setattr(launch.os, 'killpg', raced_kill)
    rc = launch.execute(spec, 'abc', launcher)
    assert rc == (0 if mode == 'success' else 1)
    assert not lock.exists()
    terminal = json.loads(Path(str(out)+'.terminal.json').read_text())
    assert terminal['status'] == {'success':'completed','failure':'failed','hold':'held','timeout':'time-cap','exit-race':'time-cap'}[mode]
    if mode not in ('timeout', 'exit-race'):
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
