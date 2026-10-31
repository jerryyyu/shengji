#!/usr/bin/env python3
"""Build labels and public histories, then reopen every row through the trainer.

This prepares all-row belief supervision without sampler draws or model fitting.
Memory during validation is bounded by one task chunk, not the whole dataset.
Resume requires the identical extraction recipe; a changed limit is not an append.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shengji.train import belief_history, belief_labels, belief_seq  # noqa: E402


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError('must be positive')
    return number


def validate(directory):
    """Use the training loader sequentially, retaining no completed chunk arrays."""
    verified = belief_seq._Verified()
    splits = {}
    for split in ('train', 'calib', 'test'):
        entries = belief_seq.extract_entries([str(directory)], split)
        rows = sampled = 0
        for entry in entries:
            part = belief_seq.load_part(entry, belief_seq.EVAL_KEYS, verified,
                                        sampler_rows_only=False)
            rows += len(part['X'])
            sampled += int((part['S_n'] > 0).sum())
            del part
        if rows != sum(e['rows'] for e in entries):
            raise RuntimeError(f'{split}: consumer/index row mismatch')
        if sampled:
            raise RuntimeError('unexpected sampler rows in labels-only cache')
        splits[split] = {'rows': rows, 'chunks': len(entries), 'sampler_rows': sampled}
    if splits['train']['rows'] == 0:
        raise RuntimeError('no training rows')
    return splits


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--workers', type=positive, default=2)
    parser.add_argument('--task-clusters', type=positive, default=10)
    parser.add_argument('--limit-clusters', type=positive)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args(argv)
    store, out = args.store.resolve(), args.out.resolve()
    def log(*messages, **kwargs):
        print(*messages, file=sys.stderr, flush=True)
    labels = belief_labels.extract(
        [str(store)], str(out), cluster_stride=1, cluster_offset=0,
        max_clusters_per_store=args.limit_clusters, calib=0.06, test=0.12,
        sampler_worlds=0, sampler_splits=('calib', 'test'), sampler_stride=1,
        workers=args.workers, task_clusters=args.task_clusters, log=log, resume=args.resume)
    if labels['status'] != 'complete' or labels['failed_clusters']:
        raise RuntimeError('incomplete label extraction')
    history = belief_history.extract([str(out)], str(store.parent), workers=args.workers, log=log)
    splits = validate(out)
    rows = sum(s['rows'] for s in splits.values())
    if history[str(out)]['rows'] != rows:
        raise RuntimeError('history/consumer row mismatch')
    print(json.dumps({'status': 'PASS', 'scope': 'labels/history/trainer loading; no training',
                      'store': str(store), 'out': str(out), 'consumer_rows': rows,
                      'split_rows': splits, 'required_eval_rows': 'all',
                      'workers': args.workers, 'task_clusters': args.task_clusters,
                      'excluded_clusters': len(labels['excluded_clusters'])}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
