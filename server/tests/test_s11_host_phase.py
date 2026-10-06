import os
from pathlib import Path
import sys

import pytest

from scripts import s11_host_phase as host
from shengji.eval.s11_phases import COST
from test_s11_collection_phase import packet, slots, trajectory, frozen, package


def invoke(packet, root):
    return host.run_host_phase(packet[0], packet[1], COST, host_root=root,
        cwd=Path(__file__).resolve().parents[1], env=os.environ, python=sys.executable)


def test_actual_guarded_cost_owns_and_releases_shared_lock(packet, tmp_path, monkeypatch):
    real = host.run_collection_phase
    def run(*args, **kwargs):
        owner = tmp_path / '.claude-host.lock/owner'
        assert owner.read_text().startswith(f'{os.getpid()} codex-s11 ')
        with pytest.raises(FileExistsError):
            (tmp_path / '.claude-host.lock').mkdir()
        return real(*args, **kwargs)
    monkeypatch.setattr(host, 'run_collection_phase', run)
    assert invoke(packet, tmp_path)['schema'] == 's11-cost-parent-accepted-v1'
    assert not (tmp_path / '.claude-host.lock').exists()


@pytest.mark.parametrize('kind', ['live', 'ownerless', 'symlink'])
def test_existing_peer_lease_untouched(packet, tmp_path, monkeypatch, kind):
    lock = tmp_path / '.claude-host.lock'
    if kind == 'symlink':
        lock.symlink_to(tmp_path, target_is_directory=True)
    else:
        lock.mkdir()
        if kind == 'live':
            (lock / 'owner').write_text('123 peer\n')
    before = lock.lstat()
    monkeypatch.setattr(host, 'run_collection_phase', lambda *a, **k: pytest.fail('dispatch'))
    with pytest.raises(FileExistsError):
        invoke(packet, tmp_path)
    assert lock.lstat() == before
    if kind == 'live':
        assert (lock / 'owner').read_text() == '123 peer\n'


def test_failed_collection_retains_lease_and_no_retry(packet, tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError('collection incomplete')
    monkeypatch.setattr(host, 'run_collection_phase', fail)
    with pytest.raises(ValueError, match='incomplete'):
        invoke(packet, tmp_path)
    assert (tmp_path / '.claude-host.lock/owner').exists()
    with pytest.raises(FileExistsError):
        invoke(packet, tmp_path)


@pytest.mark.parametrize('damage', ['owner', 'extra'])
def test_ownership_drift_never_deletes_peer_state(packet, tmp_path, monkeypatch, damage):
    real = host.run_collection_phase
    def run(*args, **kwargs):
        result = real(*args, **kwargs)
        lock = tmp_path / '.claude-host.lock'
        if damage == 'owner':
            owner = lock / 'owner'
            owner.chmod(0o600)
            owner.write_text('123 peer\n')
        else:
            (lock / 'foreign').touch()
        return result
    monkeypatch.setattr(host, 'run_collection_phase', run)
    with pytest.raises(ValueError, match='ownership changed'):
        invoke(packet, tmp_path)
    assert (tmp_path / '.claude-host.lock/owner').exists()


def test_hold_prevents_lock_acquisition(packet, tmp_path):
    Path(packet[2]['phases'][COST]['release']).with_name('HOLD').touch()
    with pytest.raises(ValueError, match='held'):
        invoke(packet, tmp_path)
    assert not (tmp_path / '.claude-host.lock').exists()


def test_legacy_marker_retains_owned_lease_without_dispatch(packet, tmp_path, monkeypatch):
    legacy = tmp_path / '.claude-screen.lock'
    legacy.mkdir()
    monkeypatch.setattr(host, 'run_collection_phase', lambda *a, **k: pytest.fail('dispatch'))
    with pytest.raises(ValueError, match='legacy'):
        invoke(packet, tmp_path)
    assert legacy.exists() and (tmp_path / '.claude-host.lock/owner').exists()


def test_missing_parent_acceptance_never_releases_host(packet, tmp_path, monkeypatch):
    monkeypatch.setattr(host, 'run_collection_phase', lambda *a, **k: {})
    with pytest.raises(FileNotFoundError):
        invoke(packet, tmp_path)
    assert (tmp_path / '.claude-host.lock/owner').exists()
