"""Compose all 64 authenticated public slots with durable collect-once work.

The caller must obtain slots from the reviewed input reader after admission.
This module does not open raw shards, authenticate models or authorize runs.
"""
import copy
import fcntl
import hashlib
import os
from pathlib import Path
import re
import stat

from . import s11_once
from .s11_once import collect_s11_once
from .s11_persistence import _context, _encode, load_s11_root
from .s11_report import summarize_s11
from ..luna.atomic_io import publish_exclusive_bytes


_SCHEDULE_SCHEMA = 's11-public-schedule-v1'
_INVENTORY_SCHEMA = 's11-operational-inventory-v1'
_ROOT_FILES = frozenset({
    'owner.lock', 'started.json', 'completed.json', 'failed.json',
    '.started.json.partial', '.completed.json.partial', '.failed.json.partial',
})
_STATUS_NAMES = frozenset(('completed', 'refused', 'interrupted', 'unattempted'))


def _bind_s11_schedule(slots, manifest_sha256, packet_sha256, seed,
                        max_public_refusals, fill_seed):
    """Validate and normalize the public schedule without touching the run."""
    for pin in (manifest_sha256, packet_sha256):
        if type(pin) is not str or not re.fullmatch('[0-9a-f]{64}', pin):
            raise ValueError('manifest and packet SHA256 required')
    if any(type(n) is not int or n < 0 for n in (seed, fill_seed)):
        raise ValueError('nonnegative integer seeds required')
    if type(max_public_refusals) is not int or not 0 <= max_public_refusals < 64:
        raise ValueError('explicit public refusal ceiling in 0..63 required')
    if type(slots) is not list or len(slots) != 64:
        raise ValueError('exactly64 scheduled slots required')
    slots = copy.deepcopy(slots)
    inventory, refused = [], []
    for draw, slot in enumerate(slots):
        root_id = f's11-{manifest_sha256}-draw-{draw:02d}'
        if (not isinstance(slot, dict) or type(slot.get('draw_index')) is not int
                or slot['draw_index'] != draw or slot.get('root_id') != root_id):
            raise ValueError('fixed schedule coordinate mismatch')
        if slot.get('status') == 'valid':
            if set(slot) != {'root_id', 'draw_index', 'status', 'selected_ply', 'fixture'}:
                raise ValueError('valid slot shape mismatch')
            fixture = slot['fixture']
            if (fixture.id != root_id or type(slot['selected_ply']) is not int
                    or slot['selected_ply'] < 0 or len(fixture.plays) != slot['selected_ply']):
                raise ValueError('public fixture coordinate mismatch')
            inventory.append({**{k: v for k, v in slot.items() if k != 'fixture'},
                              'fixture': fixture.to_json()})
        elif slot.get('status') == 'refused':
            if (set(slot) != {'root_id', 'draw_index', 'status', 'stage', 'reason'}
                    or slot['stage'] not in ('shard', 'terminal', 'public-projection')
                    or type(slot['reason']) is not str or not slot['reason'].strip()):
                raise ValueError('refused slot shape mismatch')
            inventory.append(slot)
            refused.append(slot)
        else:
            raise ValueError('unknown slot status')
    return slots, inventory, refused


def _schedule_binding(manifest_sha256, packet_sha256, seed,
                      max_public_refusals, fill_seed, inventory):
    return dict(schema=_SCHEDULE_SCHEMA, manifest_sha256=manifest_sha256,
                packet_sha256=packet_sha256, seed=seed, fill_seed=fill_seed,
                max_public_refusals=max_public_refusals, slots=inventory)


def _owned_directory(directory):
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('owned existing run directory required')
    info = directory.stat(follow_symlinks=False)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError('run directory identity mismatch')
    return directory


def _locked_existing(path, label, *, mode=0o600):
    """Open and lock an existing owner file; never create one while reading."""
    try:
        descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError as exc:
        raise ValueError(f'{label} is missing') from exc
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != mode or info.st_nlink != 1):
            raise ValueError(f'{label} identity mismatch')
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def _root_entries(root):
    entries = {}
    try:
        iterator = os.scandir(root)
    except OSError as exc:
        raise ValueError('root directory cannot be inspected') from exc
    with iterator:
        for entry in iterator:
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise ValueError('root entry cannot be inspected') from exc
            if entry.is_symlink() or not (stat.S_ISREG(info.st_mode)):
                raise ValueError('unsafe root entry')
            entries[entry.name] = info
    return entries


def _root_path(directory, root_id):
    return directory / hashlib.sha256(root_id.encode()).hexdigest()


def _diagnostic_state(root_id, draw, diagnostic):
    return {'root_id': root_id, 'draw_index': draw, 'status': 'interrupted',
            'diagnostic': diagnostic}


def _inspect_valid_root(directory, slot, *, packet_sha256, seed, fill_seed):
    draw, root_id = slot['draw_index'], slot['root_id']
    fixture = slot['fixture']
    root = _root_path(directory, fixture.id)
    if root.is_symlink():
        raise ValueError('root directory symlink')
    if not root.exists():
        return {'root_id': root_id, 'draw_index': draw, 'status': 'unattempted'}
    if not root.is_dir():
        raise ValueError('root directory identity mismatch')
    lock = _locked_existing(root / 'owner.lock', 'root owner lock')
    try:
        entries = _root_entries(root)
        if any(name not in _ROOT_FILES for name in entries):
            raise ValueError('unknown root artifact')
        context = _context(packet_sha256, fixture, seed, fill_seed)
        start_bytes = _encode(dict(schema='s11-root-attempt-v1', status='started',
                                   context=context))
        completed = root / 'completed.json'
        started = root / 'started.json'
        failed = root / 'failed.json'
        partials = [root / name for name in
                    ('.started.json.partial', '.completed.json.partial', '.failed.json.partial')]
        try:
            saved = load_s11_root(completed, packet_sha256=packet_sha256,
                                  fixture=fixture, seed=seed, fill_seed=fill_seed)
        except (OSError, ValueError) as exc:
            return _diagnostic_state(root_id, draw, f'completion unreadable: {type(exc).__name__}')
        if saved is not None:
            try:
                s11_once._require_start(started, start_bytes)
            except (OSError, ValueError) as exc:
                return _diagnostic_state(root_id, draw, f'start unreadable: {type(exc).__name__}')
            if failed.exists() or (root / '.failed.json.partial').exists():
                return _diagnostic_state(root_id, draw, 'completed root has failed artifact')
            if any(path.exists() or path.is_symlink() for path in partials):
                return _diagnostic_state(root_id, draw, 'completed root has partial artifact')
            return {'root_id': root_id, 'draw_index': draw, 'status': 'completed'}
        if any(path.exists() or path.is_symlink() for path in (started, failed, *partials)):
            return _diagnostic_state(root_id, draw, 'attempt has no completion')
        return {'root_id': root_id, 'draw_index': draw, 'status': 'unattempted'}
    finally:
        os.close(lock)


def inspect_s11_schedule(slots, directory, *, manifest_sha256, packet_sha256,
                         seed, max_public_refusals, fill_seed=0):
    """Return owner-side operational root states; never authorize or resume.

    This is a bounded owner-side, post-admission inventory.  Reading validated
    completion payloads requires that owner-side permission; it reports
    durable file state only.  It does not read raw inputs, invoke collection or
    model code, establish terminality, or authorize a future resume.
    """
    slots, inventory, refused = _bind_s11_schedule(
        slots, manifest_sha256, packet_sha256, seed, max_public_refusals, fill_seed)
    directory = _owned_directory(directory)
    lock = _locked_existing(directory / 'schedule.lock', 'schedule lock')
    try:
        expected_refusals = {f'refused-{slot["draw_index"]:02d}.json'
                             for slot in refused}
        actual_refusals = {path.name for path in directory.iterdir()
                           if path.name.startswith(('refused-', '.refused-'))}
        if actual_refusals != expected_refusals:
            raise ValueError('refusal artifact inventory mismatch')
        expected_binding = _schedule_binding(
            manifest_sha256, packet_sha256, seed, max_public_refusals, fill_seed,
            inventory)
        expected_schedule = _encode(expected_binding)
        schedule_path = directory / 'schedule.json'
        if (schedule_path.with_name('.schedule.json.partial').exists()
                or schedule_path.with_name('.schedule.json.partial').is_symlink()):
            raise ValueError('schedule binding has an unfinished publication')
        try:
            s11_once._require_start(schedule_path, expected_schedule)
        except (OSError, ValueError) as exc:
            raise ValueError('schedule binding mismatch') from exc
        for slot in refused:
            draw = slot['draw_index']
            path = directory / f'refused-{draw:02d}.json'
            expected = _encode(slot)
            if (path.with_name(f'.refused-{draw:02d}.json.partial').exists()
                    or path.with_name(f'.refused-{draw:02d}.json.partial').is_symlink()):
                raise ValueError('refusal has an unfinished publication')
            try:
                s11_once._require_start(path, expected)
            except (OSError, ValueError) as exc:
                raise ValueError('refusal bytes mismatch') from exc
        states = []
        for slot in slots:
            draw, root_id = slot['draw_index'], slot['root_id']
            if slot['status'] == 'refused':
                root = _root_path(directory, root_id)
                if root.is_symlink():
                    raise ValueError('refused root directory symlink')
                if root.exists():
                    if not root.is_dir():
                        raise ValueError('refused root directory identity mismatch')
                    refusal_lock = _locked_existing(root / 'owner.lock',
                                                    'refused root owner lock')
                    try:
                        entries = _root_entries(root)
                        if set(entries) - {'owner.lock'}:
                            raise ValueError('refused root has attempted artifacts')
                    finally:
                        os.close(refusal_lock)
                states.append({'root_id': root_id, 'draw_index': draw, 'status': 'refused'})
            else:
                states.append(_inspect_valid_root(
                    directory, slot, packet_sha256=packet_sha256,
                    seed=seed, fill_seed=fill_seed))
        counts = {name: sum(state['status'] == name for state in states)
                  for name in ('completed', 'refused', 'interrupted', 'unattempted')}
        if len(states) != 64 or any(state['status'] not in _STATUS_NAMES for state in states):
            raise ValueError('operational inventory must contain exactly64 states')
        return {
            'schema': _INVENTORY_SCHEMA,
            'scope': 'operational-only; no model/provenance/terminality authority',
            'resume_authorized': False,
            'terminality_established': False,
            'roots': states,
            'counts': counts,
        }
    finally:
        os.close(lock)


def collect_s11_schedule(slots, directory, bot_factory, *, manifest_sha256,
                         packet_sha256, seed, max_public_refusals,
                         fill_seed=0, check_budget=None, pinned_completions=None):
    """Bind the whole schedule before any inference; never replace a root.

    The refusal ceiling is mandatory and must be predeclared in the external
    packet. Any shard/terminal refusal stops before collection regardless of
    ceiling. Failed/started roots stop in collect_s11_once; no implicit retry.
    """
    slots, inventory, refused = _bind_s11_schedule(
        slots, manifest_sha256, packet_sha256, seed, max_public_refusals, fill_seed)
    pins = {} if pinned_completions is None else dict(pinned_completions)
    valid_ids = {slot['root_id'] for slot in slots if slot['status'] == 'valid'}
    if not set(pins) <= valid_ids or any(type(pin) is not str or
            not re.fullmatch('[0-9a-f]{64}', pin) for pin in pins.values()):
        raise ValueError('invalid pinned completion map')
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('owned existing run directory required')
    lock = os.open(directory / 'schedule.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise ValueError('schedule lock identity mismatch')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        binding = _schedule_binding(manifest_sha256, packet_sha256, seed,
                                    max_public_refusals, fill_seed, inventory)
        publish_exclusive_bytes(directory / 'schedule.json', _encode(binding), existing_equal_ok=True)
        for slot in refused:
            publish_exclusive_bytes(directory / f'refused-{slot["draw_index"]:02d}.json',
                                    _encode(slot), existing_equal_ok=True)
        if any(slot['stage'] != 'public-projection' for slot in refused):
            raise ValueError('input integrity refusal; collection blocked')
        if len(refused) > max_public_refusals:
            raise ValueError('predeclared public refusal ceiling exceeded')
        reports = []
        for slot in slots:
            if slot['status'] == 'refused':
                reports.append({k: slot[k] for k in ('root_id', 'status', 'reason')})
            else:
                result = collect_s11_once(directory, bot_factory, slot['fixture'],
                    packet_sha256=packet_sha256, seed=seed, fill_seed=fill_seed,
                    check_budget=check_budget, expected_completion_sha256=pins.get(slot['root_id']))
                reports.append(result['report'])
        summary = summarize_s11(reports, [slot['root_id'] for slot in slots])
        publish_exclusive_bytes(directory / 'summary.json', _encode(summary), existing_equal_ok=True)
        return summary
    finally:
        os.close(lock)
