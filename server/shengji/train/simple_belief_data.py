"""Small, resumable ownership cache from fit-only trajectory clusters.

Only supports the curated single-round trajectory source. A cluster must have
one original deal; mirrors and duplicate sources never become independent data.
Internal dev/check splits are held out from this belief fit, NOT from the value
model that previously fitted this corpus. Fresh gameplay is a separate test.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import importlib
import json
from pathlib import Path
import time

import numpy as np

from .harvest_labels import record_deal_key, replay_checked, state_key
from .simple_belief_features import FEATURE_SCHEMA, actor_features, ownership_targets

SCHEMA = 'simple-belief-fit-cache-v1'
REPLAY_FIELDS = ('deck', 'setup', 'plays_prefix', 'seat', 'decision_kind')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def deal_split(key):
    bucket = int(digest(('simple-belief-split-v1|' + key).encode())[:8], 16) % 10
    return 'dev' if bucket == 0 else 'check' if bucket == 1 else 'train'


def reconstruction_record(record):
    if record.get('decision_kind') != 'play' or not isinstance(record.get('deck'), list):
        raise ValueError('belief cache requires play records with explicit original deck')
    if type(record.get('seat')) is not int or record['seat'] not in range(4):
        raise ValueError('belief cache requires integer actor seat')
    return {k: record[k] for k in REPLAY_FIELDS}


def encode_record(record):
    # Exclude action/outcome/value labels and cached hidden_hands altogether.
    stripped = reconstruction_record(record)
    rnd, diffs = replay_checked(stripped)
    if diffs:
        raise ValueError('recorded prefix differs from accepted engine plays')
    if rnd.phase != 'play' or rnd.turn != stripped['seat']:
        raise ValueError('reconstructed actor turn differs')
    x, allowed = actor_features(rnd, stripped['seat'])
    targets = ownership_targets(rnd, stripped['seat'])
    if not np.take_along_axis(allowed, targets[..., None], axis=-1).all():
        raise ValueError('true ownership outside actor-visible mask')
    return x, allowed, targets


def select_records(records, limit):
    """Deduplicate states before outcome-blind, phase-spread selection."""
    if type(limit) is not int or limit < 1:
        raise ValueError('positions per deal must be positive')
    unique = {}
    for record in records:
        stripped = reconstruction_record(record)
        unique.setdefault(state_key(stripped), stripped)
    ordered = sorted(unique.items(), key=lambda item: (len(item[1]['plays_prefix']), item[0]))
    indices = np.linspace(0, len(ordered)-1, min(limit, len(ordered)), dtype=int)
    return [ordered[int(i)] for i in indices]


def load_fit_records(root):
    """One byte-binding at input consumption; globally group by actual deck."""
    root = Path(root)
    curation = json.loads((root / 'curation.json').read_bytes())
    if curation.get('schema') != 'cwv-fit-subset-v1' or curation.get('baseline_val_test_included') != 0:
        raise ValueError('requires explicit baseline-fit-only curation')
    grouped, provenance = {}, {}
    for source, eligibility in sorted(curation['sources'].items()):
        directory = root / source
        raw = (directory / 'manifest.json').read_bytes()
        if digest(raw) != eligibility['manifest_sha256']:
            raise ValueError('curated manifest byte binding differs')
        manifest = json.loads(raw)
        if manifest.get('source') != 'trajectory':
            raise ValueError('only single-round trajectory clusters are admitted')
        fit = set(eligibility['fit_deal_keys'])
        for shard in manifest['shards']:
            path = (directory / shard['path']).resolve()
            if not path.is_relative_to(directory.resolve()):
                raise ValueError('shard outside curated source')
            data = path.read_bytes()
            if digest(data) != shard['sha256'] or len(data) != shard['bytes']:
                raise ValueError('trajectory shard byte binding differs')
            records = [json.loads(line) for line in data.splitlines()]
            if len(records) != shard['records'] or not records:
                raise ValueError('trajectory shard population differs')
            keys = {record_deal_key(r) for r in records}
            if len(keys) != 1 or None in keys:
                raise ValueError('trajectory cluster must contain exactly one original deal')
            key = next(iter(keys))
            if key not in fit:
                raise ValueError('deal not in curated fit eligibility')
            grouped.setdefault(key, []).extend(reconstruction_record(r) for r in records
                                                if r.get('decision_kind') == 'play')
            provenance.setdefault(key, []).append({'source': source, 'shard': shard['path'],
                                                   'sha256': shard['sha256']})
    if len(grouped) != curation['distinct_deals'] or any(not rows for rows in grouped.values()):
        raise ValueError('curated distinct play-deal population differs')
    return grouped, provenance, curation


def _cache_deal(task):
    key, selected, destination, identity = task
    path = Path(destination)
    if path.exists():
        with np.load(path, allow_pickle=False) as saved:
            if str(saved['identity']) != identity:
                raise ValueError('existing cache has different producing inputs or source')
            if saved['x'].shape[0] != len(selected):
                raise ValueError('existing cache row count differs')
        return key, len(selected), True
    rows = [encode_record(record) for _, record in selected]
    x, allowed, targets = (np.stack([row[i] for row in rows]) for i in range(3))
    temporary = path.with_suffix('.partial.npz')
    np.savez_compressed(temporary, x=x, allowed=allowed, targets=targets,
                        state_keys=np.asarray([k for k, _ in selected]),
                        identity=np.asarray(identity), deal_key=np.asarray(key))
    temporary.replace(path)
    return key, len(selected), False


def build_cache(root, output, *, positions=16, max_deals=None, workers=4):
    if workers < 1 or (max_deals is not None and max_deals < 1):
        raise ValueError('workers and optional deal cap must be positive')
    started = time.monotonic()
    grouped, provenance, curation = load_fit_records(root)
    # Code identity is cheap and local, not a repeated corpus verification pass.
    modules = ('shengji.train.simple_belief_data', 'shengji.train.simple_belief_features',
               'shengji.train.harvest_labels', 'shengji.train.data',
               'shengji.harvest.rebuild', 'shengji.engine.round', 'shengji.engine.cards',
               'shengji.engine.combos', 'shengji.engine.legal',
               'shengji.ai.memory', 'shengji.rl.encode', 'shengji.rl.public_history')
    code = digest(b''.join(Path(importlib.import_module(name).__file__).read_bytes()
                           for name in modules))
    keys = sorted(grouped, key=lambda key: digest(('simple-belief-order-v1|' + key).encode()))
    if max_deals is not None:
        keys = keys[:max_deals]
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    tasks, descriptors = [], []
    for key in keys:
        selected = select_records(grouped[key], positions)
        identity = digest(canonical([SCHEMA, FEATURE_SCHEMA, code, key, selected]))
        filename = key.removeprefix('deck:') + '.npz'
        tasks.append((key, selected, str(output / filename), identity))
        descriptors.append({'deal_key': key, 'split': deal_split(key), 'path': filename,
                            'identity': identity, 'rows': len(selected), 'sources': provenance[key]})
    recipe = {'schema': SCHEMA, 'feature_schema': FEATURE_SCHEMA, 'source_digest': code,
              'positions_per_deal': positions, 'deals': descriptors,
              'baseline_checkpoint_sha256': curation['baseline_checkpoint_sha256'],
              'scope': 'internal belief holdout on baseline value-fit deals; not fresh W32 holdout'}
    recipe_path = output / 'recipe.json'
    recipe_bytes = canonical(recipe)
    if recipe_path.exists() and recipe_path.read_bytes() != recipe_bytes:
        raise ValueError('cache recipe differs; use a separate output for a new population')
    if not recipe_path.exists():
        recipe_path.write_bytes(recipe_bytes)
    completed = []
    preparation_seconds = time.monotonic()-started
    work_started = time.monotonic()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for key, n, reused in pool.map(_cache_deal, tasks):
            completed.append(key)
            done = len(completed)
            elapsed = time.monotonic()-started
            print(json.dumps({'stage': 'ownership_cache', 'done': done, 'total': len(tasks),
                              'percent': 100*done/len(tasks), 'rows': n, 'reused': reused,
                              'wall_seconds': elapsed, 'preparation_seconds': preparation_seconds,
                              'eta_seconds': (time.monotonic()-work_started)/done*(len(tasks)-done)}),
                  flush=True)
    result = {'schema': SCHEMA, 'completed_deals': len(completed),
              'rows': sum(d['rows'] for d in descriptors), 'wall_seconds': time.monotonic()-started}
    temporary = output / 'complete.partial.json'
    temporary.write_bytes(canonical(result))
    temporary.replace(output / 'complete.json')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--positions', type=int, default=16)
    parser.add_argument('--max-deals', type=int)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    print(json.dumps(build_cache(args.root, args.output, positions=args.positions,
                                max_deals=args.max_deals, workers=args.workers)))


if __name__ == '__main__':
    main()
