"""Small fresh DEV ranking-only R4 mixture screen; no production registration.

Four treatment rounds + ONE common ordinary baseline per deal. Two focal-team
mirrors are averaged within each deal, never counted as independent samples.
All arms keep baseline declarations and unbudgeted hybrid bury/W32 MC.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import time

from ..engine.cards import RANKS
from ..engine.round import actual_play_after
from .declare_screen import prepare_round
from .r4_mixture_policy import R4MixtureRankBot
from .r4_runtime_client import R4RuntimeClient
from .search_screen import _publish, _run_pending, bind_output_config, execution_source_identity

NAMESPACE = 'r4-mixture-rank-gameplay-dev-20260910-v1'
ARMS = ('synthetic-primary', 'hard-geometry-label-permutation')


def seed_for(label, index):
    return int.from_bytes(hashlib.sha256(f'{NAMESPACE}:{label}:{index}'.encode()).digest()[:8], 'big')


def spec_for(cluster):
    if not 0 <= cluster < 14:
        raise ValueError('this small screen has exactly14 planned deals')
    return {'index': cluster, 'seed': seed_for('deal', cluster),
            'rank': RANKS[cluster] if cluster < 13 else '2',
            'initial_banker': cluster % 4 if cluster < 13 else None}


def schedule():
    return [('ordinary', None), *((name, team) for name in ARMS for team in (0, 1))]


def play_round(rnd, bots, cluster, arm, team):
    banker = rnd.banker
    rnd.bury(banker, bots[banker].decide_bury(rnd, banker))
    transcript, inference_wall = [], 0.
    started = time.monotonic()
    while rnd.phase == 'play':
        seat = rnd.turn
        bot = bots[seat]
        attempted = bot.decide_play(rnd, seat)
        previous = rnd.last_trick
        rnd.play(seat, attempted)
        detail = bot.last_mixture
        mixture = None if detail is None else {k: detail[k] for k in (
            'actor_sha256', 'model_arm', 'inference_wall_s', 'inference_and_fit_wall_s')}
        if mixture is not None:
            inference_wall += mixture['inference_wall_s']
            mixture['fit'] = {k: detail['fit'][k] for k in (
                'recipe', 'iterations', 'converged', 'ess_fraction', 'max_weight')}
        transcript.append({'seat': seat, 'attempted': attempted,
                           'cards': actual_play_after(rnd, seat, previous), 'mixture': mixture})
        if len(transcript) % 16 == 0:
            print(json.dumps({'cluster': cluster, 'arm': arm, 'team': team,
                              'plays': len(transcript), 'cards_remaining': sum(map(len, rnd.hands)),
                              'round_wall_s': round(time.monotonic()-started, 1)}), flush=True)
    points = rnd.attacker_points
    banker_value = (-max(1, (points-80)//40) if points >= 80 else
                    3 if points == 0 else 2 if points < 40 else 1)
    return {'team0_signed_levels': banker_value if banker % 2 == 0 else -banker_value,
            'banker': banker, 'attacker_points': points, 'kitty_bonus': rnd.kitty_bonus,
            'buried': list(rnd.buried), 'transcript': transcript,
            'model_inference_wall_sum': inference_wall}


def validate_arm(row, config, spec, arm, team):
    if row.get('config_sha256') != config['config_sha256'] or row.get('spec') != spec \
            or row.get('arm') != arm or row.get('focal_team') != team:
        raise ValueError('saved gameplay arm identity differs')
    outcome = row.get('outcome')
    if not isinstance(outcome, dict) or any(type(outcome.get(k)) is not int for k in (
            'team0_signed_levels', 'banker', 'attacker_points', 'kitty_bonus')) \
            or outcome['banker'] not in range(4) or outcome['team0_signed_levels'] == 0 \
            or min(outcome['attacker_points'], outcome['kitty_bonus']) < 0 \
            or not isinstance(outcome.get('transcript'), list) \
            or not isinstance(outcome.get('buried'), list) or len(outcome['buried']) != 8:
        raise ValueError('saved gameplay outcome shape differs')
    return row


def read_arm(path, config, spec, arm, team):
    return validate_arm(json.loads(path.read_bytes()), config, spec, arm, team)


def read_cluster(path, config, cluster):
    shard = json.loads(path.read_bytes())
    if shard.get('config_sha256') != config['config_sha256'] or shard.get('cluster') != cluster:
        raise ValueError('saved gameplay cluster identity differs')
    records = shard.get('records', [])
    if not isinstance(records, list) or len(records) != len(schedule()):
        raise ValueError('saved gameplay cluster arm population differs')
    for row, (arm, team) in zip(records, schedule(), strict=True):
        validate_arm(row, config, spec_for(cluster), arm, team)
    return shard


def run_cluster(config, cluster):
    from ..ai.cwv_policy import shared_evaluator
    from ..oracle.screen import work_counters
    spec = spec_for(cluster)
    evaluator = shared_evaluator(config['checkpoint'], threads=1, max_batch=128, encoding='mlp-static')
    if evaluator.checkpoint_sha256 != config['checkpoint_sha256']:
        raise ValueError('gameplay value checkpoint changed')
    rows = []
    with R4RuntimeClient(config['archive_server'], config['training_root']) as client:
        for arm, team in schedule():
            path = Path(config['output'])/f'arm-{cluster:03d}-{arm}-{team}.json'
            if path.exists():
                rows.append(read_arm(path, config, spec, arm, team))
                continue
            start, cpu = time.monotonic(), time.process_time()
            rnd, _ = prepare_round(spec, 'baseline', 0)
            bots = [R4MixtureRankBot(evaluator, client=client,
                    model_arm=arm if seat % 2 == team else 'ordinary',
                    seed=seed_for(f'play:{cluster}', seat)) for seat in range(4)]
            outcome = play_round(rnd, bots, cluster, arm, team)
            row = {'config_sha256': config['config_sha256'], 'spec': spec, 'arm': arm,
                   'focal_team': team, 'trump_suit': rnd.trump_suit,
                   'declaration': rnd.declaration, 'outcome': outcome,
                   'bury_config': asdict(bots[0].bury_config), 'model_identity': client.identity,
                   'work': work_counters(bots), 'wall_s': time.monotonic()-start,
                   'parent_cpu_s': time.process_time()-cpu,
                   'cpu_scope': 'parent only; inference child wall tracked separately'}
            _publish(path, row)
            rows.append(row)
            print(json.dumps({'cluster': cluster, 'completed_arms': len(rows), 'total_arms': 5,
                              'last_arm_wall_s': round(row['wall_s'], 2)}), flush=True)
    return {'cluster': cluster, 'config_sha256': config['config_sha256'], 'records': rows}


def summarize(shards):
    from .cwv_bury_readout import interval
    deltas = {n: {'signed_levels': [], 'wins': [], 'kitty_bonus': []} for n in ARMS}
    for shard in shards:
        rows = shard['records']
        if len(rows) != 5 or {(r['arm'], r['focal_team']) for r in rows} != set(schedule()):
            raise ValueError('five distinct paired gameplay arms required')
        baseline = next(r['outcome'] for r in rows if r['arm'] == 'ordinary')
        for name in ARMS:
            differences = {key: [] for key in deltas[name]}
            for team in (0, 1):
                result = next(r['outcome'] for r in rows if r['arm'] == name and r['focal_team'] == team)
                sign = 1 if team == 0 else -1
                base, changed = (sign*r['team0_signed_levels'] for r in (baseline, result))
                differences['signed_levels'].append(changed-base)
                differences['wins'].append(int(changed > 0)-int(base > 0))
                differences['kitty_bonus'].append(result['kitty_bonus']-baseline['kitty_bonus'])
            for key, values in differences.items():
                deltas[name][key].append(sum(values)/2)
    return {'independent_deals': len(shards), 'planned_deals': 14, 'complete': len(shards) == 14,
            'rounds': 5*len(shards), 'comparisons': {n: {k: interval(v) for k, v in metrics.items()}
                                                      for n, metrics in deltas.items()} if shards else {},
            'scope': 'fresh DEV ranking-only screen; not confirmation or production authority'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--archive-server', type=Path, required=True)
    parser.add_argument('--training-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--workers', type=int, choices=(1, 2), default=2)
    parser.add_argument('--limit', type=int, choices=range(1, 15), default=14)
    args = parser.parse_args(argv)
    if os.environ.get('SHENGJI_REQUIRE_VOIDS') != '1':
        parser.error('SHENGJI_REQUIRE_VOIDS=1 required')
    config = {'schema': NAMESPACE, 'output': str(args.out.resolve()),
              'checkpoint': str(args.checkpoint.resolve()),
              'checkpoint_sha256': hashlib.sha256(args.checkpoint.read_bytes()).hexdigest(),
              'archive_server': str(args.archive_server.resolve()),
              'training_root': str(args.training_root.resolve()),
              'training_manifests': {n: hashlib.sha256((args.training_root/n/'manifest.json').read_bytes()).hexdigest() for n in ARMS},
              'source': execution_source_identity(Path(__file__).parents[1]),
              'archive_source': execution_source_identity(args.archive_server/'shengji'),
              'planned_deals': [spec_for(i) for i in range(14)], 'arms': schedule()}
    # JSON-normalize tuples before binding/reopening the exact config.
    config = json.loads(json.dumps(config, sort_keys=True))
    config['config_sha256'] = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    bind_output_config(args.out, config)
    shards, pending = [], []
    for cluster in range(args.limit):
        path = args.out/f'cluster-{cluster:05d}.json'
        if path.exists():
            shards.append(read_cluster(path, config, cluster))
        else:
            pending.append(cluster)
    _run_pending(config, pending, shards, output=args.out, workers=args.workers, task_fn=run_cluster)
    result = summarize(shards)
    _publish(args.out/f'summary-{len(shards)}.json', result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
