#!/usr/bin/env python3
"""Build labels and public histories, then reopen every row through the trainer.

This prepares all-row belief supervision without sampler draws or model fitting.
Memory during validation is bounded by one task chunk, not the whole dataset.
Resume requires the identical extraction recipe; a changed limit is not an append.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shengji.train import belief_history, belief_labels, belief_seq, unified_seq  # noqa: E402


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


def sealed_leg(store, terminal, pin):
    raw = Path(terminal).read_bytes()
    if hashlib.sha256(raw).hexdigest() != pin:
        raise ValueError('terminal digest differs')
    result = json.loads(raw)
    if result['status'] != 'completed' or result['returncode'] != 0 or result['lock_retained']:
        raise ValueError('leg has not completed')
    seal = result['leg_seal']
    raw = (store / 'manifest.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != seal['manifest_sha256']:
        raise ValueError('store manifest differs from sealed leg')
    manifest = json.loads(raw)
    expected = [store / sh['path'] for sh in manifest['shards']]
    if (store / 'shards').is_symlink() or expected != belief_labels.cluster_paths(store):
        raise ValueError('raw shard inventory differs from sealed leg')
    for shard in manifest['shards']:
        sidecar = store / shard['sidecar']
        if (store / shard['path']).is_symlink() or sidecar.is_symlink():
            raise ValueError('linked member in sealed leg')
    return manifest, seal['manifest_sha256']


def validate_unified(directory, store, manifest_sha, decisions):
    index = unified_seq.OutcomeIndex()
    verified = belief_seq._Verified()
    splits = {}
    for split in ('train', 'calib', 'test'):
        entries = unified_seq.entries_for([str(directory)], split)
        rows = 0
        for entry in entries:
            part = unified_seq.load_unified_part(entry, verified, index)
            for round_ids, selected in belief_seq.round_batches(part, 8, None):
                batch = unified_seq.make_unified_batch(part, round_ids, selected)
                rows += len(batch['pol_target'])
                del batch
            del part
        if rows != sum(e['rows'] for e in entries):
            raise RuntimeError(f'{split}: unified consumer/index row mismatch')
        splits[split] = {'rows': rows, 'chunks': len(entries)}
    if index.manifests.get(str(store), {}).get('manifest_sha256') != manifest_sha:
        raise RuntimeError('unified outcome source differs from the sealed manifest')
    if not splits['train']['rows'] or sum(s['rows'] for s in splits.values()) != decisions:
        raise RuntimeError('unified training rows differ from sealed play decisions')
    return splits


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--workers', type=positive, default=2)
    parser.add_argument('--task-clusters', type=positive, default=10)
    parser.add_argument('--limit-clusters', type=positive)
    parser.add_argument('--cluster-stride', type=positive, default=1)
    parser.add_argument('--cluster-offset', type=int, default=0)
    parser.add_argument('--sealed-rt4-leg', nargs=2, metavar=('TERMINAL', 'SHA256'),
                        help='prepare a complete leg with the RT4 split and verify its unified outcome targets')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args(argv)
    if not 0 <= args.cluster_offset < args.cluster_stride:
        parser.error('--cluster-offset must be in [0, cluster-stride)')
    store, out = args.store.resolve(), args.out.resolve()
    manifest = None
    verify_inventory = None
    quality = None
    if args.sealed_rt4_leg:
        if args.limit_clusters is not None or args.cluster_stride != 1:
            parser.error('sealed RT4 extraction requires the whole leg')
        manifest, manifest_sha = sealed_leg(store, *args.sealed_rt4_leg)

        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools' / 'y_datagen'))
        from check_leg import check_leg

        def verify_inventory(inventory):
            nonlocal quality
            if len(inventory) != len(manifest['shards']):
                raise ValueError('incomplete extraction inventory')
            for item, shard in zip(inventory, manifest['shards']):
                identity = item['source']
                if (identity.get('manifest_sha256') != manifest_sha
                        or identity['path'] != str(store / shard['path'])
                        or identity['sha256'] != shard['sha256']):
                    raise ValueError('extraction inventory differs from sealed leg')
            terminal, pin = args.sealed_rt4_leg
            quality = check_leg(store, Path(terminal), pin)

    def log(*messages, **kwargs):
        print(*messages, file=sys.stderr, flush=True)
    labels = belief_labels.extract(
        [str(store)], str(out), cluster_stride=args.cluster_stride, cluster_offset=args.cluster_offset,
        max_clusters_per_store=args.limit_clusters, calib=0.06, test=0.04 if manifest is not None else 0.12,
        sampler_worlds=0, sampler_splits=('calib', 'test'), sampler_stride=1,
        workers=args.workers, task_clusters=args.task_clusters, log=log, resume=args.resume,
        verify_inventory=verify_inventory)
    if labels['status'] != 'complete' or labels['failed_clusters']:
        raise RuntimeError('incomplete label extraction')
    if manifest is not None:
        deals = sum(labels['stats'].get(f'deals_{s}', 0) for s in ('train', 'calib', 'test'))
        if labels['excluded_clusters'] or deals != manifest['clusters']:
            raise RuntimeError('incomplete sealed deal coverage')
    history = belief_history.extract([str(out)], str(store.parent), workers=args.workers, log=log)
    if manifest is None:
        scope = 'labels/history/trainer loading; no training'
        splits = validate(out)
        binding = {}
    else:
        if history[str(out)]['rounds'] != manifest['rounds']:
            raise RuntimeError('incomplete sealed round coverage')
        splits = validate_unified(out, store, manifest_sha, manifest['counts']['decisions'])
        scope = 'sealed RT4 labels/history/unified policy and outcome batches'
        binding = {'terminal_sha256': args.sealed_rt4_leg[1], 'trajectory_quality': quality}
    rows = sum(s['rows'] for s in splits.values())
    if history[str(out)]['rows'] != rows:
        raise RuntimeError('history/consumer row mismatch')
    print(json.dumps({'status': 'PASS', 'scope': scope, **binding,
                      'store': str(store), 'out': str(out), 'consumer_rows': rows,
                      'split_rows': splits, 'required_eval_rows': 'all',
                      'workers': args.workers, 'task_clusters': args.task_clusters,
                      'cluster_stride': args.cluster_stride, 'cluster_offset': args.cluster_offset,
                      'excluded_clusters': len(labels['excluded_clusters'])}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
