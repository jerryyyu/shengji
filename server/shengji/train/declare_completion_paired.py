"""Before-deal paired DEV screen of one sampled declaration intervention.

The tested team may replace its first legal >=20-card declaration callback.
Every subsequent callback uses SmartBot; every actual continuation uses the
same hybrid bury/W32 policy. Unexposed deals remain in the result. This is not
an all-callback policy, a mirrored match, or a deployment gate.
"""
from dataclasses import asdict
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import time

from ..engine.cards import RANKS
from ..engine.round import Round
from .declare_completion import PublicDeclaration, capture_observation, baseline_action
from .declare_completion_evaluation import evaluate_actions
from .declare_completion_screen import FullW32Evaluator, digest, derived_seed
from .search_screen import _publish, _run_pending, bind_output_config, execution_source_identity

RECIPE = 'one-eligible-team-callback-min20-completions2-v1'


def context(index):
    # Two deals per rank, testing both focal teams; the extra cell is a true
    # first round with no preassigned banker. No outcome-based population filter.
    cell = index % 27
    if cell == 26:
        return '2', None, 0
    return RANKS[cell % 13], (cell + cell // 13) % 4, cell // 13


def complete_actual_deal(rnd, *, focal_team, choose=None):
    """Only the immutable actor observation crosses into the selector."""
    shown, exposure = [], None

    def callback(seat, final=False):
        nonlocal exposure
        observation = capture_observation(rnd, seat, shown, final=final)
        incumbent = baseline_action(observation)
        action = incumbent
        if choose is not None and exposure is None and seat % 2 == focal_team \
                and len(observation.own_hand) >= 20 and observation.options:
            chosen = choose(observation)
            action = None if chosen is None else tuple(chosen)
            if action is not None and action not in observation.options:
                raise ValueError('selected declaration is not legal')
            exposure = {'observation': json.loads(json.dumps(asdict(observation))),
                        'baseline_action': None if incumbent is None else list(incumbent),
                        'selected_action': None if action is None else list(action),
                        'changed': action != incumbent}
        if action is not None:
            rnd.declare(seat, list(action))
            shown.append(PublicDeclaration(seat, tuple(action), rnd._deal_pos))

    while rnd.phase == 'deal':
        seat, _, _ = rnd.deal_next()
        callback(seat)
    for seat in range(4):
        callback(seat, final=True)
    for seat in range(4):
        rnd.pass_declare(seat)
    rnd.finalize_declare()
    return exposure


def select_declaration(observation, config, index, evaluator):
    seeds = tuple(derived_seed(f'paired-inner:{index}', w) for w in range(2))
    identity = {'config_sha256': config['config_sha256'], 'index': index,
                'observation': json.loads(json.dumps(asdict(observation))),
                'seeds': list(seeds)}
    path = Path(config['output'])/f'selection-{index:05d}.json'
    if path.exists():
        saved = json.loads(path.read_text())
        if saved['identity'] != identity:
            raise ValueError('retained declaration selection input differs')
        return saved['result']['selected_action']
    result = evaluate_actions(observation, seeds=seeds, evaluator=evaluator)
    _publish(path, {'identity': identity, 'result': result})
    return result['selected_action']


def run_pair(config, cluster):
    started = time.perf_counter()
    index = config['start_index'] + cluster
    rank, banker, focal_team = context(index)
    deal_seed = derived_seed('paired-fresh-deal', index)
    evaluation_seed = derived_seed('paired-actual-play', index)
    evaluator = FullW32Evaluator(config)
    arms, setups, exposure = {}, {}, None
    # Choose using sampled worlds before looking at either actual-game result.
    for arm in ('sampled', 'baseline'):
        rnd = Round(rank, banker, random.Random(deal_seed))
        choose = (lambda obs: select_declaration(obs, config, index, evaluator)) if arm == 'sampled' else None
        seen = complete_actual_deal(rnd, focal_team=focal_team, choose=choose)
        if arm == 'sampled':
            exposure = seen
        setups[arm] = {'declaration': rnd.declaration, 'banker': rnd.banker,
                       'trump_suit': rnd.trump_suit, 'first_round': rnd.first_round}
        arms[arm] = evaluator(rnd, focal_team=focal_team, seed=evaluation_seed)
    return {'cluster': cluster, 'index': index, 'config_sha256': config['config_sha256'],
            'rank': rank, 'initial_banker': banker, 'focal_team': focal_team,
            'deal_seed': deal_seed, 'evaluation_seed': evaluation_seed,
            'exposure': exposure, 'setups': setups, 'arms': arms,
            'wall_s': time.perf_counter()-started}


def reopen_pair(path, config, cluster):
    row = json.loads(path.read_text())
    index = config['start_index'] + cluster
    if row['cluster'] != cluster or row['index'] != index \
            or row['config_sha256'] != config['config_sha256'] \
            or (row['rank'], row['initial_banker'], row['focal_team']) != context(index) \
            or row['deal_seed'] != derived_seed('paired-fresh-deal', index) \
            or row['evaluation_seed'] != derived_seed('paired-actual-play', index):
        raise ValueError('retained paired deal identity differs')
    return row


def summarize(shards, config):
    import numpy as np
    if not shards:
        return {'complete': False, 'completed_deals': 0}
    rows = sorted(shards, key=lambda r: r['cluster'])
    rng = np.random.default_rng(382071)
    # Independent units are original deals, never inner-world/candidate rows.
    draws = rng.integers(0, len(rows), size=(4000, len(rows)))
    deltas = {}
    for metric in ('focal_signed_levels', 'focal_won', 'kitty_bonus', 'kitty_ge80'):
        x = np.asarray([r['arms']['sampled'][metric]-r['arms']['baseline'][metric] for r in rows])
        deltas[metric] = {'mean': float(x.mean()),
                         'ci95': np.quantile(x[draws].mean(axis=1), [.025, .975]).tolist()}
    return {'scope': 'paired rounds from before dealing; one eligible team callback; DEV only',
            'complete': len(rows) == config['deals'], 'completed_deals': len(rows),
            'requested_deals': config['deals'], 'recipe': RECIPE,
            'exposed_deals': sum(r['exposure'] is not None for r in rows),
            'changed_deals': sum(bool(r['exposure'] and r['exposure']['changed']) for r in rows),
            'paired_deltas': deltas, 'pair_worker_wall_s': sum(r['wall_s'] for r in rows),
            'uncertainty': 'descriptive paired deal bootstrap; sparse fixed rank/context mix, not confirmation',
            'kitty_note': 'raw kitty bonus belongs to attackers; lower is not always better for focal team'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--checkpoint', required=True, type=Path)
    parser.add_argument('--start-index', type=int, default=0)
    parser.add_argument('--deals', type=int, default=27)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--max-new', type=int, default=27, help='operational chunk limit, not a recipe change')
    args = parser.parse_args(argv)
    if args.start_index < 0 or not 1 <= args.deals <= 108 or not 1 <= args.workers <= 8 \
            or args.max_new < 1 or os.environ.get('SHENGJI_REQUIRE_VOIDS') != '1':
        parser.error('invalid bounded size or missing SHENGJI_REQUIRE_VOIDS=1')
    config = {'schema': 'declare-completion-paired-v1', 'recipe': RECIPE,
              'start_index': args.start_index, 'deals': args.deals,
              'output': str(args.out.resolve()), 'checkpoint': str(args.checkpoint.resolve()),
              'checkpoint_sha256': hashlib.sha256(args.checkpoint.read_bytes()).hexdigest(),
              'source': execution_source_identity(Path(__file__).resolve().parents[1])}
    config['config_sha256'] = digest(config)
    bind_output_config(args.out, config)
    shards, pending = [], []
    for cluster in range(args.deals):
        path = args.out/f'cluster-{cluster:05d}.json'
        if path.exists():
            shards.append(reopen_pair(path, config, cluster))
        else:
            pending.append(cluster)
    try:
        _run_pending(config, pending[:args.max_new], shards, output=args.out,
                     workers=args.workers, task_fn=run_pair)
    finally:
        # Publish usable scientific readout even when another shard fails.
        result = summarize(shards, config)
        _publish(args.out/'summary.json', result)
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
