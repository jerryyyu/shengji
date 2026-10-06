"""Compose all 64 authenticated public slots with durable collect-once work.

The caller must obtain slots from the reviewed input reader after admission.
This module does not open raw shards, authenticate models or authorize runs.
"""
import copy
import fcntl
import os
from pathlib import Path
import re
import stat

from .s11_once import collect_s11_once
from .s11_persistence import _encode
from .s11_report import summarize_s11
from ..luna.atomic_io import publish_exclusive_bytes


def collect_s11_schedule(slots, directory, bot_factory, *, manifest_sha256,
                         packet_sha256, seed, max_public_refusals,
                         fill_seed=0, check_budget=None):
    """Bind the whole schedule before any inference; never replace a root.

    The refusal ceiling is mandatory and must be predeclared in the external
    packet. Any shard/terminal refusal stops before collection regardless of
    ceiling. Failed/started roots stop in collect_s11_once; no implicit retry.
    """
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
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('owned existing run directory required')
    lock = os.open(directory / 'schedule.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise ValueError('schedule lock identity mismatch')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        binding = dict(schema='s11-public-schedule-v1', manifest_sha256=manifest_sha256,
            packet_sha256=packet_sha256, seed=seed, fill_seed=fill_seed,
            max_public_refusals=max_public_refusals, slots=inventory)
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
                    check_budget=check_budget)
                reports.append(result['report'])
        summary = summarize_s11(reports, [slot['root_id'] for slot in slots])
        publish_exclusive_bytes(directory / 'summary.json', _encode(summary), existing_equal_ok=True)
        return summary
    finally:
        os.close(lock)
