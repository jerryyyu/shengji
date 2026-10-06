"""Phase-scoped S11 collection composition, not a launch controller.

Caller owns the accepted-input receipt, frozen source/model/runtime, host lock,
outer wall/RSS guard and separately reviewed phase invocation. Worker output is
PRIVATE until that guard accepts it. No CLI, transport, model loading or release
creation lives here. A cost completion is retained for exact full-phase reuse.
"""
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time

from .s11_admission_once import _manifest
from .s11_input_bundle import load_s11_input_bundle, _unique, _bad_constant
from .s11_once import collect_s11_once
from .s11_schedule import collect_s11_schedule, _owned_directory
from ..luna.benchmark_readout_receipt import run_once

COST = 'cost-first-valid-slot'
FULL = 'full-schedule'
_COST_FIELDS = {'schema', 'packet_sha256', 'bundle_sha256', 'root_id',
                'draw_index', 'capture_sha256', 'metrics'}


def _pin(value):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('SHA256 required')
    return value


def require_phase_release(path, packet_sha256, phase):
    """Exact packet+phase marker; a cost release cannot unlock a full phase."""
    _pin(packet_sha256)
    if phase not in (COST, FULL):
        raise ValueError('unknown S11 phase')
    path = Path(path)
    if os.path.lexists(path.parent / 'HOLD'):
        raise ValueError('S11 held')
    expected = (packet_sha256 + '\n' + phase + '\n').encode('ascii')
    if _manifest(path, 128) != expected:
        raise ValueError('S11 phase release mismatch')


def _capture_digest(path):
    """Seal new capture bytes once without parsing or exposing their values."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                or stat.S_IMODE(before.st_mode) != 0o400 or before.st_nlink != 1
                or not 0 < before.st_size <= 128 << 20):
            raise ValueError('cost capture identity/size refused')
        digest, total = hashlib.sha256(), 0
        while chunk := os.read(fd, 1 << 20):
            total += len(chunk)
            if total > 128 << 20:
                raise ValueError('cost capture grew past bound')
            digest.update(chunk)
        after = os.fstat(fd)
        if total != before.st_size or any(getattr(before, k) != getattr(after, k)
                for k in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')):
            raise ValueError('cost capture changed')
        return digest.hexdigest()
    finally:
        os.close(fd)


def _cost_seal(raw, digest, packet, bundle, first):
    if type(raw) is not bytes or len(raw) > 65536 or hashlib.sha256(raw).hexdigest() != _pin(digest):
        raise ValueError('cost receipt digest mismatch')
    value = json.loads(raw, object_pairs_hook=_unique, parse_constant=_bad_constant)
    if (type(value) is not dict or set(value) != _COST_FIELDS
            or value['schema'] != 's11-cost-worker-v1'
            or value['packet_sha256'] != packet or value['bundle_sha256'] != bundle
            or value['root_id'] != first['root_id']
            or type(value['draw_index']) is not int or value['draw_index'] != first['draw_index']):
        raise ValueError('cost receipt context mismatch')
    metrics = value['metrics']
    if (type(metrics) is not dict or set(metrics) != {'elapsed_seconds', 'batches', 'cells', 'status'}
            or metrics['status'] != 'completed'
            or type(metrics['elapsed_seconds']) not in (int, float)
            or not math.isfinite(metrics['elapsed_seconds']) or metrics['elapsed_seconds'] < 0
            or any(type(metrics[k]) is not int or metrics[k] <= 0 for k in ('batches', 'cells'))):
        raise ValueError('cost metrics refused')
    return _pin(value['capture_sha256'])


def run_s11_phase(*, phase, release_path, packet_sha256, bundle_raw,
                  bundle_sha256, directory, output_dir, bot_factory,
                  cost_receipt_raw=None, cost_receipt_sha256=None,
                  check_budget=None):
    """Run only the separately released phase under an external guarded worker.

    Cost returns identities and operational counts only. Sampled RSS and guard
    disposition belong to the external parent receipt, never fabricated here.
    Full input pins must come from that accepted parent, not private output.
    elapsed_seconds measures first-slot work and sealing, excluding input reload
    and process startup; it is not a full-schedule ETA or worst-case bound.
    """
    require_phase_release(release_path, packet_sha256, phase)
    identity = dict(packet_sha256=packet_sha256, bundle_sha256=_pin(bundle_sha256), phase=phase)
    if phase == FULL:
        identity['cost_receipt_sha256'] = _pin(cost_receipt_sha256)

    def execute():
        slots, admission = load_s11_input_bundle(bundle_raw, sha256=bundle_sha256)
        first = next(s for s in slots if s['status'] == 'valid')
        run = _owned_directory(directory)
        if phase == FULL:
            pin = _cost_seal(cost_receipt_raw, cost_receipt_sha256,
                             packet_sha256, bundle_sha256, first)
            result = collect_s11_schedule(slots, run, bot_factory,
                manifest_sha256=admission['manifest_sha256'], packet_sha256=packet_sha256,
                seed=0, fill_seed=0, max_public_refusals=4, check_budget=check_budget,
                pinned_completions={first['root_id']: pin})
        else:
            if cost_receipt_raw is not None or cost_receipt_sha256 is not None:
                raise ValueError('cost phase cannot reuse a cost receipt')
            fd = os.open(run / 'schedule.lock', os.O_RDWR | os.O_CREAT | os.O_EXCL |
                         os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if {p.name for p in run.iterdir()} != {'schedule.lock'}:
                    raise ValueError('cost phase requires a fresh collection directory')
                start = time.monotonic()
                capture = collect_s11_once(run, bot_factory, first['fixture'],
                    packet_sha256=packet_sha256, seed=0, fill_seed=0, check_budget=check_budget)
                if check_budget is not None:
                    check_budget()
                capture_path = run / hashlib.sha256(first['root_id'].encode()).hexdigest() / 'completed.json'
                result = dict(schema='s11-cost-worker-v1', packet_sha256=packet_sha256,
                    bundle_sha256=bundle_sha256, root_id=first['root_id'],
                    draw_index=first['draw_index'], capture_sha256=_capture_digest(capture_path),
                    metrics=dict(status='completed', elapsed_seconds=time.monotonic() - start,
                        batches=capture['value_capture']['batches'],
                        cells=64 * len(capture['value_capture']['actions'])))
            finally:
                os.close(fd)
        require_phase_release(release_path, packet_sha256, phase)
        return result

    def guarded_output():
        try:
            return execute()
        except Exception:
            if phase != COST:
                raise
        # Model exception text can contain values. Keep private root journals,
        # but never echo that payload into the operational phase refusal.
        raise ValueError('S11 cost incomplete; preserve artifacts for explicit disposition')

    return run_once(output_dir, identity, guarded_output)
