"""Full-data belief checkpoint in unchanged W32; fixed 260-deal DEV screen.

Reuses the original legal-weighting consumer and resumable gameplay worker.
No R4 process, policy registration, training, or production setting changes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random

from ..engine.cards import RANKS
from ..engine.round import Round
from . import simple_belief_gameplay as game
from .search_screen import _publish, _run_pending, bind_output_config, execution_source_identity
from .simple_belief_train import _load_checkpoint

NAMESPACE = 'simple-belief-full-w32-dev-20260911-v1'
DEALS = 260


def planned_deals():
    return [{'index': i,
             'seed': int.from_bytes(hashlib.sha256(f'{NAMESPACE}:deal:{i}'.encode()).digest()[:8], 'big'),
             'rank': RANKS[i % len(RANKS)],
             'initial_banker': i % 5 if i % 5 < 4 else None}
            for i in range(DEALS)]


def build_config(checkpoint, small_checkpoint, cache_recipe, out):
    checkpoint, small_checkpoint, cache_recipe, out = map(
        lambda p: Path(p).resolve(), (checkpoint, small_checkpoint, cache_recipe, out))
    planned = planned_deals()
    recipe_sha, cache_keys = game._fresh_check(cache_recipe, planned)
    payload = _load_checkpoint(small_checkpoint, recipe_sha)
    # A different recipe must not be supplied to evade the actual fit boundary.
    embedded = {d['deal_key'] for d in payload['recipe']['deals']}
    if embedded != set(cache_keys):
        raise ValueError('checkpoint embedded deal population differs')
    old = {game.record_deal_key({'deck': Round(s['rank'], s['initial_banker'],
               random.Random(s['seed'])).deck}) for s in [game.spec_for(i) for i in range(game.PLANNED_DEALS)]}
    fresh = [game.record_deal_key({'deck': Round(s['rank'], s['initial_banker'],
                 random.Random(s['seed'])).deck}) for s in planned]
    if len(set(fresh)) != DEALS or set(fresh) & old:
        raise ValueError('new gameplay deals duplicate earlier screen')
    config = {
        'schema': NAMESPACE, 'policy_seed_namespace': NAMESPACE, 'output': str(out),
        'checkpoint': str(checkpoint),
        'checkpoint_sha256': hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        'small_checkpoint': str(small_checkpoint),
        'small_checkpoint_sha256': hashlib.sha256(small_checkpoint.read_bytes()).hexdigest(),
        'cache_recipe': str(cache_recipe), 'cache_recipe_sha256': recipe_sha,
        'selected_epoch': payload['completed_epochs'],
        'source': execution_source_identity(Path(__file__).parents[1]),
        'planned_deals': planned, 'fresh_deal_keys': fresh,
        'arms': [('ordinary', None), ('uniform-pool', 0), ('uniform-pool', 1),
                 ('new-small', 0), ('new-small', 1)],
        'play': {'worlds': 32, 'selection_worlds': game.SELECT_WORLDS,
                 'alternatives': 4, 'report_worlds': game.REPORT_WORLDS,
                 'reuse_successors': True, 'pool_worlds': game.POOL_SIZE,
                 'fit_iterations': game.FIT_ITERATIONS},
        'scope': 'Fixed fresh DEV screen; no optional outcome stopping or production authority',
    }
    config = json.loads(json.dumps(config, sort_keys=True))
    config['config_sha256'] = game._config_hash(config)
    return config


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('checkpoint', 'small-checkpoint', 'cache-recipe', 'out'):
        p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--workers', type=int, choices=range(1, 17), default=4)
    args = p.parse_args(argv)
    if os.environ.get('SHENGJI_REQUIRE_VOIDS') != '1':
        p.error('SHENGJI_REQUIRE_VOIDS=1 required')
    config = build_config(args.checkpoint, args.small_checkpoint, args.cache_recipe, args.out)
    bind_output_config(args.out, config)
    shards, pending = [], []
    for i in range(DEALS):
        path = args.out / f'cluster-{i:05d}.json'
        if path.exists():
            shards.append(game.read_cluster(path, config, i))
        else:
            pending.append(i)
    print(json.dumps({'stage': 'admitted', 'deals': DEALS, 'rounds': DEALS*5,
                      'workers': args.workers, 'checkpoint': config['small_checkpoint_sha256'],
                      'completed_deals': len(shards)}), flush=True)
    _run_pending(config, pending, shards, output=args.out, workers=args.workers,
                 task_fn=game.run_cluster)
    shards.sort(key=lambda s: s['cluster'])
    summary = game.summarize(shards, config)
    summary['config_sha256'] = config['config_sha256']
    summary['cost'] = {
        arm: {'rounds': len(rows), 'cpu_seconds': sum(r['work']['parent_cpu_seconds'] for r in rows),
              'summed_wall_seconds': sum(r['wall_s'] for r in rows)}
        for arm in ('ordinary', 'uniform-pool', 'new-small')
        for rows in [[r for s in shards for r in s['records'] if r['arm'] == arm]]}
    _publish(args.out / 'summary.json', summary)
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
