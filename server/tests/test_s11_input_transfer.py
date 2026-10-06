from pathlib import Path
import subprocess

import pytest

from scripts.s11_input_transfer import files_from_bytes, rsync_command


@pytest.mark.parametrize('mode', ['success', 'failure', 'oversized'])
def test_manifest_pull_is_bounded_exclusive_and_retains_partial(tmp_path, monkeypatch, mode):
    from scripts import s11_input_transfer as transfer
    path = tmp_path / 'manifest'
    calls = []
    def fake_run(command, *, check, stdout, stderr):
        calls.append(command)
        assert command[-2:] == ['shengji-perf',
            '/usr/bin/head -c 8388609 -- /root/traj-out/runPVC8/manifest.json']
        assert check
        stdout.write(b'fixture')
        if mode == 'oversized':
            stdout.truncate((8 << 20) + 1)
        if mode == 'failure':
            raise subprocess.CalledProcessError(1, command)
    monkeypatch.setattr(transfer.subprocess, 'run', fake_run)
    with (tmp_path / 'log').open('wb') as log:
        if mode == 'success':
            transfer.transfer_manifest(path, log=log)
            assert path.read_bytes() == b'fixture'
        else:
            with pytest.raises((ValueError, subprocess.CalledProcessError)):
                transfer.transfer_manifest(path, log=log)
        assert path.exists()
        with pytest.raises(FileExistsError):
            transfer.transfer_manifest(path, log=log)
    assert len(calls) == 1


@pytest.fixture
def plan():
    return {'files': [dict(path=f'shards/cluster-{i:06d}.jsonl', bytes=1,
                          sha256='a'*64, draw_index=i) for i in range(64)]}


@pytest.mark.parametrize('damage', ['newline', 'traversal', 'duplicate', 'extra', 'large', 'short'])
def test_transfer_list_rejects_unsafe_or_changed_selection(plan, damage):
    if damage == 'short':
        plan['files'].pop()
    elif damage == 'duplicate':
        plan['files'][1]['path'] = plan['files'][0]['path']
    elif damage == 'extra':
        plan['files'][0]['outcome'] = 'SECRET'
    elif damage == 'large':
        plan['files'][0]['bytes'] = (4 << 20) + 1
    else:
        plan['files'][0]['path'] = 'shards/cluster-000000.jsonl\nsecret' if damage == 'newline' else '../secret'
    with pytest.raises(ValueError):
        files_from_bytes(plan)


def test_command_disables_daemonizing_ssh_and_has_no_broad_copy_flags():
    command = rsync_command('host:/source/', '/list', '/destination')
    assert '--partial' in command
    assert '--recursive' not in command and '-a' not in command
    assert all('delete' not in arg for arg in command)
    transport = command[command.index('-e') + 1]
    for setting in ['BatchMode=yes', 'StrictHostKeyChecking=yes', 'ControlMaster=no',
                    'ControlPath=none', 'ControlPersist=no']:
        assert setting in transport


@pytest.mark.parametrize('bad_pin', [False, True])
def test_staging_authenticates_manifest_before_transfer_and_never_retries(tmp_path, monkeypatch, bad_pin):
    from scripts import s11_input_transfer as transfer
    from scripts.s11_input_worker import stage_inputs
    from test_s11_input_join import input_frame
    fixture = tmp_path / 'fixture'
    fixture.mkdir()
    manifest, pin, _ = input_frame(fixture)
    root = tmp_path / 'staging'
    root.mkdir(mode=0o700)
    config = dict(root=str(root), manifest_path=str(root / 'manifest.json'),
                  manifest_sha256='b'*64 if bad_pin else pin, max_manifest_bytes=8 << 20)
    calls = []
    def pull(path, *, log):
        calls.append('manifest')
        Path(path).write_bytes(manifest)
    def shards(plan, files_from, destination, *, log):
        calls.append('shards')
        assert len(plan['files']) == 64 and destination == root
    monkeypatch.setattr(transfer, 'transfer_manifest', pull)
    monkeypatch.setattr(transfer, 'transfer_shards', shards)
    if bad_pin:
        with pytest.raises(ValueError, match='SHA256'):
            stage_inputs(config)
        assert calls == ['manifest']
    else:
        stage_inputs(config)
        assert calls == ['manifest', 'shards']
    with pytest.raises(ValueError, match='no implicit retry'):
        stage_inputs(config)


def test_staging_claim_is_durable_before_first_transfer(tmp_path, monkeypatch):
    import os
    import stat
    from scripts import s11_input_transfer as transfer
    from scripts.s11_input_worker import stage_inputs
    root = tmp_path / 'staging'
    root.mkdir(mode=0o700)
    events = []
    sync = os.fsync
    def fsync(fd):
        events.append('directory' if stat.S_ISDIR(os.fstat(fd).st_mode) else 'file')
        sync(fd)
    monkeypatch.setattr(os, 'fsync', fsync)
    def pull(*args, **kwargs):
        assert events == ['file', 'directory']
        assert (root / 'transfer.log').exists()
        raise ValueError('synthetic stop before transfer')
    monkeypatch.setattr(transfer, 'transfer_manifest', pull)
    with pytest.raises(ValueError, match='synthetic stop'):
        stage_inputs(dict(root=str(root), manifest_path=str(root / 'manifest.json')))


@pytest.mark.skipif(not Path('/usr/bin/rsync').exists(), reason='installed rsync qualification')
def test_installed_rsync_selected_only_no_links_specials_or_oversized(tmp_path, plan):
    import os
    source, destination = tmp_path / 'source', tmp_path / 'destination'
    (source / 'shards').mkdir(parents=True)
    destination.mkdir(mode=0o700)
    for item in plan['files']:
        (source / item['path']).write_bytes(b'x')
    # Unselected bytes must never enter the destination.
    (source / 'private-sidecar').write_bytes(b'SECRET')
    (source / 'shards' / 'cluster-999999.jsonl').write_bytes(b'SECRET')
    listed = tmp_path / 'files'
    listed.write_bytes(files_from_bytes(plan))
    result = subprocess.run(rsync_command(str(source) + '/', listed, destination),
                            capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert sorted(str(p.relative_to(destination)) for p in destination.rglob('*') if p.is_file()) == sorted(i['path'] for i in plan['files'])
    # Separate fresh destination; symlink/FIFO/oversized selected files are not
    # usable output. A zero rsync exit must not be confused with admission.
    refused = tmp_path / 'refused'
    refused.mkdir(mode=0o700)
    link, fifo, large = [source / plan['files'][i]['path'] for i in range(3)]
    link.unlink()
    link.symlink_to(source / 'private-sidecar')
    fifo.unlink()
    os.mkfifo(fifo)
    with large.open('wb') as stream:
        stream.truncate((4 << 20) + 1)
    result = subprocess.run(rsync_command(str(source) + '/', listed, refused),
                            capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    for item in plan['files'][:3]:
        assert not os.path.lexists(refused / item['path'])
    assert not (refused / 'private-sidecar').exists()
