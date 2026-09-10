"""Small end-to-end declaration-completion pilot, not a gameplay strength test.

Shared completion worlds compare every legal declaration plus waiting. Selection
and independent report worlds have disjoint RNG domains. Retain each completed
bury/play rollout so an interrupted pilot does not discard its useful work.
"""
from __future__ import annotations

from dataclasses import asdict
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import time

from ..ai.smart import SmartBot
from ..engine.cards import RANKS
from ..engine.round import Round, actual_play_after
from .declare_completion import DeclareObservation, PublicDeclaration, capture_observation, baseline_action
from .declare_completion_evaluation import evaluate_actions
from .search_screen import _publish, _run_pending, bind_output_config, execution_source_identity

NAMESPACE = 'declare-completion-dev-20260910-v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def derived_seed(domain, index):
    return int(digest([NAMESPACE, domain, index])[:16], 16)


def reopen_observation(payload):
    return DeclareObservation(seat=payload['seat'], rank=payload['rank'], banker=payload['banker'],
        deal_pos=payload['deal_pos'], final=payload['final'], own_hand=tuple(payload['own_hand']),
        shown=tuple(PublicDeclaration(e['seat'], tuple(e['cards']), e['deal_pos']) for e in payload['shown']),
        options=tuple(tuple(a) for a in payload['options']), passed=tuple(payload['passed']))


def capture_first_opportunity(index, *, min_cards=20):
    """Score-free fixed-index capture; no hidden data is returned to selection."""
    cell = index % 53
    rank, banker = (RANKS[cell//4], cell%4) if cell < 52 else ('2', None)
    rnd = Round(rank, banker, random.Random(derived_seed('actual-deal', index)))
    history, bot = [], SmartBot()
    def callback(seat, final=False):
        obs = capture_observation(rnd, seat, history, final=final)
        if len(obs.own_hand) >= min_cards and obs.options:
            return obs
        action = bot.decide_declare(rnd, seat, final=final)
        if action:
            rnd.declare(seat, action)
            history.append(PublicDeclaration(seat, tuple(action), rnd._deal_pos))
        return None
    while rnd.phase == 'deal':
        seat, _, _ = rnd.deal_next()
        obs = callback(seat)
        if obs is not None:
            return obs
    for seat in range(4):
        obs = callback(seat, final=True)
        if obs is not None:
            return obs
    return None


class FullW32Evaluator:
    """Full fixed hybrid-bury/W32 continuation, with exact-state result reuse."""
    def __init__(self, config):
        self.config = config
        self.root = Path(config['output'])/'rollouts'
        self.root.mkdir(exist_ok=True)

    def __call__(self, rnd, *, focal_team, seed):
        if rnd.phase != 'bury' or rnd.turn != rnd.banker:
            raise ValueError('full evaluator requires a completed declaration state')
        state = {'deck': list(rnd.deck), 'hands': [list(h) for h in rnd.hands],
                 'kitty': list(rnd.kitty), 'rank': rnd.trump_rank, 'banker': rnd.banker,
                 'declaration': rnd.declaration, 'trump_suit': rnd.trump_suit,
                 'first_round': rnd.first_round, 'focal_team': focal_team, 'seed': seed}
        identity = {'config_sha256': self.config['config_sha256'], 'state': state}
        path = self.root/(digest(identity)+'.json')
        if path.exists():
            saved = json.loads(path.read_text())
            if saved['identity'] != identity:
                raise ValueError('completed rollout input binding differs')
            return {**saved['metrics'], 'reused': True}
        from ..ai.cwv_policy import shared_evaluator
        from ..oracle.screen import work_counters
        from .cwv_bury_policy import make_cwv_bury_bot
        from .cwv_bury_screen import banker_utility
        started, cpu = time.perf_counter(), time.process_time()
        net = shared_evaluator(self.config['checkpoint'], threads=1, max_batch=128, encoding='mlp-static')
        if net.checkpoint_sha256 != self.config['checkpoint_sha256']:
            raise ValueError('continuation model changed')
        bots = [make_cwv_bury_bot(net, arm='hybrid', seed=derived_seed(f'continuation:{seed}', s)) for s in range(4)]
        rnd.bury(rnd.banker, bots[rnd.banker].decide_bury(rnd, rnd.banker))
        buried = list(rnd.buried)
        transcript = []
        while rnd.phase == 'play':
            seat = rnd.turn
            attempted = bots[seat].decide_play(rnd, seat)
            before = rnd.last_trick
            rnd.play(seat, attempted)
            transcript.append({'seat': seat, 'cards': actual_play_after(rnd, seat, before)})
        value = banker_utility(rnd.attacker_points)*(1 if rnd.banker % 2 == focal_team else -1)
        metrics = {'focal_signed_levels': value, 'focal_won': int(value > 0),
                   'attacker_points': rnd.attacker_points, 'kitty_bonus': rnd.kitty_bonus,
                   'kitty_ge80': int(rnd.kitty_bonus >= 80), 'work': work_counters(bots),
                   'wall_s': time.perf_counter()-started, 'cpu_s': time.process_time()-cpu,
                   'reused': False}
        _publish(path, {'identity': identity, 'metrics': metrics, 'buried': buried, 'transcript': transcript})
        print(json.dumps({'completed_rollout': path.name, 'wall_s': metrics['wall_s']}, sort_keys=True), flush=True)
        return metrics


def run_world(config, cluster):
    role, seed = world_identity(config, cluster)
    result = evaluate_actions(reopen_observation(config['observation']), seeds=(seed,), evaluator=FullW32Evaluator(config))
    result.pop('selected_action')  # Selection is across all selection worlds only.
    return {'cluster': cluster, 'role': role, 'seed': seed,
            'config_sha256': config['config_sha256'], 'result': result}


def world_identity(config, cluster):
    if type(cluster) is not int or not 0 <= cluster < config['selection_worlds']+config['report_worlds']:
        raise ValueError('invalid completion world index')
    role, index = ('selection', cluster) if cluster < config['selection_worlds'] else ('report', cluster-config['selection_worlds'])
    return role, derived_seed(f"{role}:{config['observation_index']}", index)


def reopen_world(path, config, cluster):
    row = json.loads(path.read_text())
    role, seed = world_identity(config, cluster)
    if row['cluster'] != cluster or row['config_sha256'] != config['config_sha256'] \
            or row['role'] != role or row['seed'] != seed:
        raise ValueError('completed world identity or selection/report role differs')
    for action in row['result']['actions']:
        records = action['rows']
        if len(records) != 1 or records[0]['seed'] != seed \
                or action['mean_signed_levels'] != records[0]['metrics']['focal_signed_levels']:
            raise ValueError('completed world action rows differ')
    return row


def summarize(shards, config):
    ordered = sorted(shards, key=lambda s: s['cluster'])
    selection = [s for s in ordered if s['role'] == 'selection']
    report = [s for s in ordered if s['role'] == 'report']
    complete = len(selection) == config['selection_worlds'] and len(report) == config['report_worlds']
    if not complete:
        return {'complete': False, 'completed_worlds': len(shards)}
    actions = [row['action'] for row in selection[0]['result']['actions']]
    if any([row['action'] for row in s['result']['actions']] != actions for s in ordered):
        raise ValueError('world candidate populations differ')
    means = [sum(s['result']['actions'][a]['mean_signed_levels'] for s in selection)/len(selection)
             for a in range(len(actions))]
    chosen = max(range(len(actions)), key=lambda a: means[a])
    # Candidate zero is the actual baseline, so ties preserve the incumbent.
    deltas = [s['result']['actions'][chosen]['mean_signed_levels']-s['result']['actions'][0]['mean_signed_levels'] for s in report]
    return {'complete': True, 'actions': actions, 'selection_means': means,
            'baseline_action': actions[0], 'selected_action': actions[chosen],
            'independent_report_deltas': deltas, 'mean_report_delta': sum(deltas)/len(deltas),
            'scope': 'single-observation sampled-completion mechanics pilot; not fresh gameplay strength'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--checkpoint', required=True, type=Path)
    parser.add_argument('--index', type=int, required=True)
    parser.add_argument('--min-cards', type=int, default=20)
    parser.add_argument('--selection-worlds', type=int, default=2)
    parser.add_argument('--report-worlds', type=int, default=2)
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args(argv)
    if args.index < 0 or not 1 <= args.min_cards <= 25 or not 1 <= args.workers <= 8 \
            or not all(1 <= n <= 16 for n in (args.selection_worlds, args.report_worlds)):
        parser.error('invalid bounded pilot size')
    if os.environ.get('SHENGJI_REQUIRE_VOIDS') != '1':
        parser.error('pilot requires SHENGJI_REQUIRE_VOIDS=1')
    obs = capture_first_opportunity(args.index, min_cards=args.min_cards)
    if obs is None:
        parser.error('fixed deal has no eligible opportunity; inspect score-free census')
    config = {'schema': 'declare-completion-pilot-v1', 'namespace': NAMESPACE,
              'observation_index': args.index, 'observation': json.loads(json.dumps(asdict(obs))),
              'min_cards': args.min_cards, 'selection_worlds': args.selection_worlds,
              'report_worlds': args.report_worlds, 'output': str(args.out.resolve()),
              'checkpoint': str(args.checkpoint.resolve()),
              'checkpoint_sha256': hashlib.sha256(args.checkpoint.read_bytes()).hexdigest(),
              'source': execution_source_identity(Path(__file__).resolve().parents[1])}
    config['config_sha256'] = digest(config)
    bind_output_config(args.out, config)
    shards, pending = [], []
    for cluster in range(args.selection_worlds+args.report_worlds):
        path = args.out/f'cluster-{cluster:05d}.json'
        if path.exists():
            shards.append(reopen_world(path, config, cluster))
        else:
            pending.append(cluster)
    _run_pending(config, pending, shards, output=args.out, workers=args.workers, task_fn=run_world)
    result = summarize(shards, config)
    _publish(args.out/'summary.json', result)
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
