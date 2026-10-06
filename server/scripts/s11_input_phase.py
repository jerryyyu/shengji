"""Guarded, single-attempt Mini input phase; no transport or launch authority.

The full reviewed controller still owns host/runtime/source freeze and RELEASE.
Only accepted.json publishes a usable reference to the private worker bundle.
A worker receipt or bundle alone is never acceptance. Preserve all partials;
there is no implicit recovery, retry, deletion or promotion after interruption.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

from scripts.s11_input_guard import supervise_s11_input
from scripts.s11_input_worker import validate_packet
from shengji.eval.s11_admission_once import _manifest
from shengji.eval.s11_input_bundle import _unique, _bad_constant
from shengji.eval.s11_persistence import _encode
from shengji.eval.s11_schedule import _owned_directory
from shengji.luna.atomic_io import publish_exclusive_bytes


def _private_empty(path):
    path = _owned_directory(path)
    if stat.S_IMODE(path.stat().st_mode) != 0o700 or any(path.iterdir()):
        raise ValueError('fresh private directory required')
    return path


def _released(packet_path, pin):
    if os.path.lexists(packet_path.parent / 'HOLD'):
        raise ValueError('input phase held')
    if _manifest(packet_path.parent / 'RELEASE', 65) != (pin + '\n').encode('ascii'):
        raise ValueError('input phase not released')


def _bundle_digest(path):
    """One bounded streaming hash of new public bundle, not raw source shards."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or
                stat.S_IMODE(before.st_mode) != 0o400 or before.st_nlink != 1 or
                not 0 < before.st_size <= 64 << 20):
            raise ValueError('private bundle metadata refused')
        digest, total = hashlib.sha256(), 0
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            while True:
                chunk = stream.read(1 << 20)
                if not chunk:
                    break
                total += len(chunk)
                if total > 64 << 20:
                    raise ValueError('private bundle grew past ceiling')
                digest.update(chunk)
        after = os.fstat(fd)
        if total != before.st_size or any(getattr(before, k) != getattr(after, k)
                for k in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')):
            raise ValueError('private bundle changed')
        return digest.hexdigest()
    finally:
        os.close(fd)


def run_input_phase(packet_path, pin, control, *, cwd, env, python=sys.executable):
    """Execute a released input worker once and publish acceptance last.

    Caller must supply frozen reviewed cwd/env/python. This is deliberately not
    a generic command runner. The final next-phase packet must pin accepted.json
    and its bundle digest; its reader still validates the bundle before use.
    """
    packet_path = Path(packet_path)
    config = validate_packet(_manifest(packet_path, 65536), pin)
    _released(packet_path, pin)
    control = _private_empty(control)
    output = _private_empty(config['output'])
    if control.resolve() == output.resolve():
        raise ValueError('control and worker directories must differ')
    # Non-recoverable O_EXCL marker: an empty/crashed marker also blocks retry.
    fd = os.open(control / 'started.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 os.O_NOFOLLOW, 0o400)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(_encode(dict(schema='s11-input-phase-start-v1', packet_sha256=pin)))
        stream.flush()
        os.fsync(stream.fileno())
    parent = os.open(control, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    try:
        with (control / 'worker.log').open('xb') as log:
            guard = supervise_s11_input([python, '-m', 'scripts.s11_input_worker',
                '--packet', str(packet_path), '--sha256', pin, '--run'],
                cwd=cwd, env=dict(env, OMP_NUM_THREADS='1'), log=log, python=python)
        publish_exclusive_bytes(control / 'guard.json', _encode(guard))
        if guard['exit_cause'] != 'process-exited' or guard['returncode'] != 0:
            raise ValueError('guard did not accept worker')
        if {p.name for p in output.iterdir()} != {'started.json', 'receipt.json', 'bundle.json'}:
            raise ValueError('private admission inventory incomplete')
        expected_start = _encode(dict(schema='s11-input-attempt-v1',
            packet_sha256=pin, manifest_sha256=config['manifest_sha256']))
        if _manifest(output / 'started.json', 4096) != expected_start:
            raise ValueError('private admission context mismatch')
        receipt_raw = _manifest(output / 'receipt.json', 128 << 10)
        receipt = json.loads(receipt_raw, object_pairs_hook=_unique, parse_constant=_bad_constant)
        if (receipt['schema'] != 's11-input-receipt-v1' or
                receipt['packet_sha256'] != pin or
                receipt['manifest_sha256'] != config['manifest_sha256'] or
                receipt['bundle_sha256'] != _bundle_digest(output / 'bundle.json')):
            raise ValueError('private admission pins mismatch')
        accepted = dict(schema='s11-input-phase-accepted-v1', packet_sha256=pin,
            manifest_sha256=config['manifest_sha256'], bundle_path=str(output / 'bundle.json'),
            bundle_sha256=receipt['bundle_sha256'],
            receipt_sha256=hashlib.sha256(receipt_raw).hexdigest(),
            guard_sha256=hashlib.sha256(_encode(guard)).hexdigest())
        _released(packet_path, pin)
        publish_exclusive_bytes(control / 'accepted.json', _encode(accepted))
        return accepted
    except Exception:
        # No private paths, records or exception chains in public diagnostics.
        pass
    raise ValueError('input phase incomplete; preserve staging for explicit disposition')
