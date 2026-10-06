"""Shared mkdir-host-lock wrapper for an already admitted S11 invocation.

The external frozen bootstrap verifies runtime/source/env first. Claude owns
RELEASE and the cloud preemption request; this wrapper neither requests nor
signals preemption and never waits or reclaims a stale lock. Invoke only after
the named predecessor is terminal and its reservation handover is admitted.
"""
import os
from pathlib import Path
import sys

from scripts.s11_collection_phase import run_collection_phase
from scripts.s11_collection_worker import validate_packet
from shengji.eval.s11_admission_once import _manifest
from shengji.eval.s11_phases import require_phase_release


def _stamp(path):
    info = path.lstat()
    return info.st_dev, info.st_ino


def run_host_phase(packet_path, pin, phase, *, host_root, cwd, env,
                   cost_path=None, cost_sha=None, python=sys.executable):
    """Take the shared host lock once; release only after accepted completion.

    On any failure after acquisition retain the lock, owner and private state
    for explicit disposition. A successful guardless/corrupt callback return
    cannot silently free the host: exact parent acceptance is checked first.
    This deliberate fail-closed policy is not an automatic stale-lock repair.
    """
    config = validate_packet(_manifest(packet_path, 65536), pin)
    selected = config['phases'][phase]
    require_phase_release(selected['release'], pin, phase)
    root = Path(host_root)
    if (not root.is_absolute() or root.resolve() != root or not root.is_dir()
            or root.stat().st_uid != os.getuid()):
        raise ValueError('canonical owned host root required')
    lock = root / '.claude-host.lock'
    # Same atomic mkdir as the live cloud screen/store launchers. Never use
    # absence of a different lock as mutual exclusion or delete a peer lease.
    lock.mkdir(mode=0o700)
    owned = _stamp(lock)
    owner = lock / 'owner'
    payload = f'{os.getpid()} codex-s11 {pin} {phase}\n'.encode('ascii')
    fd = os.open(owner, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    owner_stamp = _stamp(owner)
    fd = os.open(lock, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    # Preserve the acquired lease if any legacy job might still occupy host.
    for name in ('.claude-screen.lock', '.claude-datagen.lock'):
        if os.path.lexists(root / name):
            raise ValueError('legacy host marker present; acquired lease retained')
    require_phase_release(selected['release'], pin, phase)
    result = run_collection_phase(packet_path, pin, phase, cwd=cwd, env=env,
                                  cost_path=cost_path, cost_sha=cost_sha, python=python)
    from shengji.eval.s11_persistence import _encode
    if _manifest(Path(selected['control']) / 'accepted.json', 65536) != _encode(result):
        raise ValueError('parent acceptance changed; host lease retained')
    # Validate both inode identity and exact owner bytes, with no broad cleanup.
    if (lock.is_symlink() or _stamp(lock) != owned or owner.is_symlink()
            or _stamp(owner) != owner_stamp or _manifest(owner, 512) != payload
            or {p.name for p in lock.iterdir()} != {'owner'}):
        raise ValueError('host ownership changed; lease retained')
    owner.unlink()
    lock.rmdir()
    return result
