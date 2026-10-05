"""Metadata-only preflight for the existing paired-screen raw reader.

The caller must pin/review expected_configs before observing outcomes and
provide the pinned validator. No defaults are learned from run artifacts.
Unlike older lane adapters this does not require pins/admission files that
the v52 producer does not write. Reservation/terminal ownership is a separate
caller gate, not implied by this function succeeding.
"""
from __future__ import annotations

import json
from pathlib import Path


def _canonical(obj):
    # Strict JSON comparison avoids Python's True == 1 / 1 == 1.0 coercion.
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), allow_nan=False)


def preflight_paired_windows(root, expected_configs, *, seeds, prefixes,
                             clusters, validator):
    """Validate ALL metadata before the caller can enter its single raw pass.

    Returns ordered (seed, [candidate_entry, comparator_entry]) and metadata
    hashes for the existing end-of-read mutation check. validator._arm_metadata
    retains its complete/population/accounting/inventory gates unchanged.
    """
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('missing or symlinked root')
    if (type(clusters) is not int or clusters < 2 or not seeds
            or len(set(seeds)) != len(seeds)
            or any(type(s) is not int for s in seeds)
            or len(prefixes) != 2 or prefixes[0] == prefixes[1]
            or any(not isinstance(p, str) or not p or '/' in p for p in prefixes)):
        raise ValueError('invalid frozen population')
    names = {f'{prefix}-{seed}' for prefix in prefixes for seed in seeds}
    if len(names) != 2 * len(seeds):
        raise ValueError('colliding arm directory names')
    if set(expected_configs) != names:
        raise ValueError('incomplete or extra frozen configs')
    if {p.name for p in root.iterdir() if p.is_dir() or p.is_symlink()} != names:
        raise ValueError('wrong campaign inventory')
    entries, hashes = [], {}
    for seed in seeds:
        pair = []
        for prefix in prefixes:
            name = f'{prefix}-{seed}'
            folder = root / name
            if folder.is_symlink() or not folder.is_dir():
                raise ValueError('symlinked or missing arm')
            shadow = root / (name + '.summary.json')
            failure = folder / 'failure.json'
            if any(p.exists() or p.is_symlink() for p in (shadow, failure)):
                raise ValueError('shadow summary or failure marker')
            for filename in ('config.json', 'summary.json'):
                path = folder / filename
                if path.is_symlink() or not path.is_file():
                    raise ValueError('missing or symlinked metadata')
            expected = expected_configs[name]
            if (type(expected.get('seed0')) is not int or expected['seed0'] != seed
                    or type(expected.get('clusters')) is not int or expected['clusters'] != clusters):
                raise ValueError('frozen config population mismatch')
            config, first_sha = validator._load(folder / 'config.json')
            if _canonical(config) != _canonical(expected):
                raise ValueError('frozen complete config mismatch')
            entry = dict(directory=name, config=expected)
            _, checked_config, summary, config_sha, summary_sha = validator._arm_metadata(root, entry)
            if config_sha != first_sha or _canonical(checked_config) != _canonical(expected):
                raise ValueError('config changed during preflight')
            if _canonical(summary['config']) != _canonical(expected):
                raise ValueError('summary config type/value mismatch')
            if any(p.is_symlink() or not p.is_file() for p in folder.glob('cluster-*.json')):
                raise ValueError('nonregular or symlinked shard')
            hashes[folder / 'config.json'] = config_sha
            hashes[folder / 'summary.json'] = summary_sha
            pair.append(entry)
        entries.append((seed, pair))
    return entries, hashes
