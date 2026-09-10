"""Disk-backed training arrays; same rows/order, bounded load-time memory."""
import json
from pathlib import Path
import time

import numpy as np


def load_split_disk(cache, split):
    from .simple_belief_train import _validate_recipe, _load_file, _atomic_bytes, _canonical
    from .simple_belief_features import FEATURE_DIM
    if split not in ('train', 'dev'):
        raise ValueError('training disk loader refuses check split')
    cache = Path(cache)
    recipe, identity = _validate_recipe(cache)
    descriptors = [d for d in recipe['deals'] if d['split'] == split]
    if not descriptors:
        raise ValueError('empty training split')
    count = sum(d['rows'] for d in descriptors)
    root = cache/f'dense-{split}'
    root.mkdir(exist_ok=True)
    spec = {'recipe': identity, 'split': split, 'rows': count,
            'schema': 'simple-belief-disk-arrays-v1'}
    plan = root/'plan.json'
    if plan.exists() and json.loads(plan.read_bytes()) != spec:
        raise ValueError('disk arrays belong to another recipe')
    _atomic_bytes(plan, _canonical(spec))
    shapes = ((count, FEATURE_DIM), (count, 4, 54, 3), (count, 4, 54))
    dtypes = (np.float32, np.bool_, np.uint8)
    paths = [root/f'{name}.npy' for name in ('x', 'allowed', 'targets')]
    progress = root/'progress.json'
    done = json.loads(progress.read_bytes())['completed_deals'] if progress.exists() else 0
    if not 0 <= done <= len(descriptors):
        raise ValueError('disk progress outside population')
    if done and not all(path.exists() for path in paths):
        raise ValueError('committed disk array is missing')
    arrays = []
    for path, shape, dtype in zip(paths, shapes, dtypes):
        a = (np.load(path, mmap_mode='r+') if path.exists() else
             np.lib.format.open_memmap(path, mode='w+', dtype=dtype, shape=shape))
        if a.shape != shape or a.dtype != np.dtype(dtype):
            raise ValueError('disk array shape/dtype differs')
        arrays.append(a)
    cursor = sum(d['rows'] for d in descriptors[:done])
    started = time.monotonic()
    for i, desc in enumerate(descriptors[done:], done+1):
        values = _load_file(cache, desc)
        for array, value in zip(arrays, values):
            array[cursor:cursor+desc['rows']] = value
        cursor += desc['rows']
        if i % 1000 == 0 or i == len(descriptors):
            for a in arrays:
                a.flush()
            _atomic_bytes(progress, _canonical({'completed_deals': i}))
            print(json.dumps({'stage': 'disk_arrays', 'split': split, 'done': i,
                              'total': len(descriptors), 'percent': 100*i/len(descriptors),
                              'wall_seconds': time.monotonic()-started}), flush=True)
    # Copy-on-write mappings prevent training from modifying retained arrays.
    return tuple(np.load(path, mmap_mode='c') for path in paths)
