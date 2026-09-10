"""DEV data-only scaling: fixed old dev/check, nested additional fit deals.

Streams one trajectory shard per worker, reuses the original cache, and never
copies the full trajectory corpus. No changes to inference or training recipe.
"""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import json
import os
from pathlib import Path
import time

from .simple_belief_data import (SCHEMA, canonical, digest, deal_split,
    record_deal_key, reconstruction_record, select_records, _cache_deal)


def write_once(path, value):
    path = Path(path)
    raw = canonical(value)
    if path.exists():
        if path.read_bytes().rstrip(b'\n') != raw:
            raise ValueError('existing scaling artifact differs')
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.partial.json')
    tmp.write_bytes(raw)
    tmp.replace(path)


def first_key(task):
    root, shard = task
    with (Path(root)/shard['path']).open() as handle:
        return record_deal_key(json.loads(handle.readline())), root, shard


def choose_keys(index, fit, old, forbidden, size):
    old_train = {d['deal_key'] for d in old['deals'] if d['split'] == 'train'}
    protected = {d['deal_key'] for d in old['deals'] if d['split'] != 'train'} | set(forbidden)
    if old_train & protected or not old_train <= fit:
        raise ValueError('old train/exclusion mismatch')
    candidates = set(index) & fit - protected - old_train
    candidates = {k for k in candidates if deal_split(k) == 'train'}
    ordered = sorted(candidates, key=lambda k: digest(('belief-scale-v1|'+k).encode()))
    if size < len(old_train) or size > len(old_train)+len(ordered):
        raise ValueError('requested training size unavailable')
    return sorted(old_train) + ordered[:size-len(old_train)]


def encode_extra(task):
    key, shards, output, code = task
    path = Path(output)/(key.removeprefix('deck:')+'.npz')
    identity = digest(canonical(['belief-scale-shard-v1', code, key, shards, 16]))
    if path.exists():
        import numpy as np
        with np.load(path, allow_pickle=False) as saved:
            if str(saved['identity']) != identity or str(saved['deal_key']) != key:
                raise ValueError('reused scaling cache identity differs')
            count = len(saved['x'])
    else:
        rows = []
        for root, shard in shards:
            source = Path(root)/shard['path']
            if not source.resolve().is_relative_to(Path(root).resolve()):
                raise ValueError('source path escapes corpus')
            raw = source.read_bytes()
            if len(raw) != shard['bytes'] or digest(raw) != shard['sha256']:
                raise ValueError('source shard byte binding differs')
            records = [json.loads(line) for line in raw.splitlines()]
            if len(records) != shard['records'] or any(record_deal_key(r) != key for r in records):
                raise ValueError('source shard mixed deals or row count differs')
            rows.extend(reconstruction_record(r) for r in records if r['decision_kind'] == 'play')
        selected = select_records(rows, 16)
        _, count, _ = _cache_deal((key, selected, str(path), identity))
    return {'deal_key': key, 'split': 'train', 'path': path.name,
            'identity': identity, 'rows': count, 'sources': shards}


def prepare(checkpoint, old_cache, fresh, output, sizes=(8000, 32000), workers=4):
    import torch
    started = time.monotonic()
    output, old_cache = Path(output), Path(old_cache)
    output.mkdir(parents=True, exist_ok=True)
    old = json.loads((old_cache/'recipe.json').read_bytes())
    raw = Path(checkpoint).read_bytes()
    if digest(raw) != old['baseline_checkpoint_sha256']:
        raise ValueError('baseline checkpoint changed')
    meta = torch.load(checkpoint, weights_only=False, map_location='cpu')['metadata']
    fit = set(meta['population']['train'])
    heldout = set(meta['population']['val']) | set(meta['population']['test'])
    if fit & heldout:
        raise ValueError('baseline split overlap')
    forbidden = {d['deal_key'] for d in json.loads(Path(fresh).read_bytes())['deals']}
    roots = meta['config']['data']
    manifests = [(str(Path(r)), json.loads((Path(r)/'manifest.json').read_bytes())) for r in roots]
    if any(m['source'] != 'trajectory' for _, m in manifests):
        raise ValueError('only single-round trajectory sources supported')
    signatures = {r: digest((Path(r)/'manifest.json').read_bytes()) for r in roots}
    plan = {'schema': 'belief-scale-plan-v1', 'baseline': digest(raw),
            'old_recipe': digest((old_cache/'recipe.json').read_bytes()),
            'sources': signatures, 'sizes': list(sizes), 'forbidden_fresh': sorted(forbidden),
            'selection': 'retain old train; hash-order additional baseline-fit belief-train deals',
            'fixed_dev': 68, 'fixed_check': 97, 'positions': 16}
    write_once(output/'plan.json', plan)
    indexpath = output/'index.json'
    if indexpath.exists():
        index = json.loads(indexpath.read_bytes())
    else:
        index = {}
        tasks = [(r, s) for r, m in manifests for s in m['shards']]
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for i, (key, root, shard) in enumerate(pool.map(first_key, tasks, chunksize=64), 1):
                if key in fit and key not in forbidden:
                    index.setdefault(key, []).append((root, shard))
                if i % 5000 == 0:
                    print(json.dumps({'stage': 'index', 'done': i, 'total': len(tasks),
                                      'seconds': time.monotonic()-started}), flush=True)
        write_once(indexpath, index)
    selected = {n: choose_keys(index, fit, old, forbidden, n) for n in sizes}
    oldkeys = {d['deal_key'] for d in old['deals']}
    extra = [k for k in selected[max(sizes)] if k not in oldkeys]
    poolpath = output/'pool'
    poolpath.mkdir(exist_ok=True)
    descriptors = {d['deal_key']: d for d in old['deals']}
    tasks = [(k, index[k], str(poolpath), old['source_digest']) for k in extra]
    workstart = time.monotonic()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i, desc in enumerate(pool.map(encode_extra, tasks, chunksize=8), 1):
            descriptors[desc['deal_key']] = desc
            if i % 250 == 0 or i == len(tasks):
                elapsed = time.monotonic()-workstart
                print(json.dumps({'stage': 'cache', 'done': i, 'total': len(tasks),
                                  'percent': 100*i/len(tasks), 'seconds': elapsed,
                                  'eta_seconds': elapsed/i*(len(tasks)-i)}), flush=True)
    for n, train in selected.items():
        destination = output/f'cache-{n}'
        destination.mkdir(exist_ok=True)
        keys = train + [d['deal_key'] for d in old['deals'] if d['split'] != 'train']
        rows = [descriptors[k] for k in keys]
        for d in rows:
            source = (old_cache if d['deal_key'] in oldkeys else poolpath)/d['path']
            target = destination/d['path']
            if not target.exists():
                os.link(source, target)
            elif not os.path.samefile(source, target):
                raise ValueError('cache alias differs')
        write_once(destination/'recipe.json', {**old, 'deals': rows,
                   'scope': f'data-only scale {n} train; fixed original dev/check'})
        write_once(destination/'complete.json', {'schema': SCHEMA,
                   'completed_deals': len(rows), 'rows': sum(d['rows'] for d in rows)})
    result = {'schema': 'belief-scale-prepared-v1', 'sizes': list(sizes),
              'eligible_fit': len(fit), 'indexed_fit': len(index),
              'source_train_counts': {str(n): dict(Counter(Path(index[k][0][0]).name
                    for k in selected[n] if k in index)) for n in sizes},
              'wall_seconds': time.monotonic()-started}
    write_once(output/'prepared.json', result)
    print(json.dumps(result), flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('checkpoint', 'old-cache', 'fresh', 'output'):
        p.add_argument('--'+name, required=True)
    p.add_argument('--sizes', type=int, nargs='+', default=[8000, 32000])
    p.add_argument('--workers', type=int, default=4)
    prepare(**vars(p.parse_args()))


if __name__ == '__main__':
    main()
