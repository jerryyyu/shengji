"""Ordered evaluation-only packing; no training shuffle or split changes."""
import numpy as np

from .cwv_data import collate


def merged_bytes(parts):
    """Include Unicode dtype promotion when estimating concatenated bytes."""
    rows = sum(len(p['target']) for p in parts)
    return sum(rows * int(np.prod(parts[0][k].shape[1:])) *
               np.result_type(*(p[k].dtype for p in parts)).itemsize
               for k in parts[0])


def eval_batches(store, mask_fn, batch_size, *, pack=False, staging_bytes=32 * 1024**2):
    """Preserve shard/row order and pre-decode split skipping.

    Packing supports history-free blocks only. Retained staging and merged
    output each fit staging_bytes; a freshly collated incoming piece may add
    one more staging_bytes transiently. This is NOT a bound on the store's
    resident shards, tensor/device memory, or retained prediction arrays.
    """
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError('batch_size must be positive integer')
    if type(staging_bytes) is not int or staging_bytes < 1:
        raise ValueError('staging_bytes must be positive integer')
    selects_any = getattr(mask_fn, 'selects_any', None)
    skip = (lambda keys: not selects_any(keys)) if selects_any else None
    parts, rows = [], 0

    def merge():
        return {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}

    for block in store.iter_blocks(skip=skip):
        selected = np.flatnonzero(mask_fn(block))
        if not len(selected):
            continue
        if pack and block.history:
            raise ValueError('packed evaluation requires history-free blocks')
        offset = 0
        while offset < len(selected):
            take = min(batch_size - rows if pack else batch_size, len(selected) - offset)
            idx = selected[offset:offset + take]
            raw = collate(block, idx)
            raw['has_search_means'] = block.has_search_means[idx]
            offset += take
            if not pack:
                yield raw
                continue
            if merged_bytes([raw]) > staging_bytes:
                raise ValueError('evaluation piece exceeds staging_bytes')
            # Flush incompatible optional schemas rather than silently drop
            # metadata. A store normally has one fixed schema.
            if parts and (raw.keys() != parts[0].keys() or
                          merged_bytes(parts + [raw]) > staging_bytes):
                ready = merge()
                parts, rows = [], 0
                yield ready
                del ready
            parts.append(raw)
            rows += take
            if rows == batch_size:
                ready = merge()
                parts, rows = [], 0
                yield ready
                del ready
    if parts:
        yield merge()
