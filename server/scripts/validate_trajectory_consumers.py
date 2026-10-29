"""Validate a completed trajectory store through both training consumers."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shengji.harvest.trajectory import sha256_file, verify_shard
from shengji.train.belief_labels import extract_cluster
from shengji.train.cwv_data import bridge_record, search_means_points


def validate_store(store: Path, *, expected_rounds: int, expected_source: str) -> dict:
    store = Path(store)
    manifest = json.loads((store / 'manifest.json').read_text())
    if expected_rounds <= 0 or expected_rounds % 2:
        raise ValueError('expected rounds must be positive and even')
    if (manifest['rounds'] != expected_rounds
            or manifest['clusters'] != expected_rounds // 2
            or manifest['identity']['git_sha'] != expected_source
            or manifest['identity']['git_dirty']):
        raise ValueError('completed manifest differs from expected rounds/source')
    config = manifest['config']
    if config['run_id'] != manifest['run_id'] or config['seed0'] != manifest['seed0']:
        raise ValueError('manifest/config identity mismatch')
    shards = manifest['shards']
    if [s['cluster'] for s in shards] != list(range(expected_rounds // 2)):
        raise ValueError('missing, duplicate or unordered clusters')
    totals = Counter()
    for cluster, entry in enumerate(shards):
        relative = f'shards/cluster-{cluster:06d}'
        if entry['path'] != relative + '.jsonl' or entry['sidecar'] != relative + '.json':
            raise ValueError('noncanonical shard path')
        side, why = verify_shard(store, config, cluster, manifest['seed0'] + cluster)
        if side is None:
            raise ValueError(f'cluster {cluster}: {why}')
        if (any(entry[k] != side[k] for k in ('seed', 'bytes', 'sha256', 'records'))
                or sha256_file(store / entry['sidecar']) != entry['sidecar_sha256']):
            raise ValueError(f'cluster {cluster}: manifest/sidecar mismatch')
        shard = store / entry['path']
        plays = 0
        with shard.open() as stream:
            for line in stream:
                record = json.loads(line)
                totals['records'] += 1
                kind = record.get('decision_kind')
                if kind == 'bury':
                    totals['bury_records'] += 1
                elif kind == 'play':
                    bridge_record(record)
                    means = search_means_points(record)
                    totals['policy_mean_rows'] += means is not None
                    plays += 1
                else:
                    raise ValueError('unknown decision kind')
        belief = extract_cluster(shard, store_index=0, cluster_index=cluster,
                                 calib=.1, test=.1, windows=[], sampler_worlds=0,
                                 sampler_splits=[])
        if belief is None or belief['excluded'] or len(belief['X']) != plays:
            raise ValueError(f'cluster {cluster}: belief/PV row mismatch')
        totals['pv_rows'] += plays
        totals['belief_rows'] += len(belief['Y'])
        totals['clusters'] += 1
    for name, key in [('records', 'records'), ('pv_rows', 'plays'),
                      ('bury_records', 'bury_records')]:
        if totals[name] != manifest['counts'][key]:
            raise ValueError(f'consumer/manifest {key} count mismatch')
    if totals['bury_records'] != expected_rounds:
        raise ValueError('missing round burial records')
    return {'status': 'PASS', 'store': str(store), 'source': expected_source,
            'run_id': manifest['run_id'], 'rounds': expected_rounds,
            'counts': dict(totals),
            'claim': 'store integrity and PV/belief consumer compatibility; not playing strength'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('store', type=Path)
    parser.add_argument('--expected-rounds', required=True, type=int)
    parser.add_argument('--expected-source', required=True)
    args = parser.parse_args(argv)
    result = validate_store(args.store, expected_rounds=args.expected_rounds,
                            expected_source=args.expected_source)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
