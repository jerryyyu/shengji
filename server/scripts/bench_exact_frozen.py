"""Freeze synthetic exact inputs once, replay across builds without deadlines.

Run with the target server on PYTHONPATH and its native extension built:
  python scripts/bench_exact_frozen.py capture roots.json --seeds 53000 53004
  python scripts/bench_exact_frozen.py run roots.json base.json --repeats 5
  python scripts/bench_exact_frozen.py compare base.json candidate.json

Set EXACT_BENCH_SERVER to replay the same CLI against another server tree.
Fresh sessions measure cold root latency including native binding/conversion.
This is a kernel diagnostic, not a served-policy or strength measurement.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import subprocess
from pathlib import Path
import random
import statistics
import sys
import time

SERVER = Path(os.environ.get("EXACT_BENCH_SERVER", Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(SERVER))

from shengji.ai.endgame import ExactEndgameBudgetExceeded
from shengji.ai.endgame_compact import CompactWorldSession
from shengji.ai.env import prepare_round
from shengji.ai.heuristic import HeuristicBot
from shengji.engine.cards import Ordering
from shengji.engine.game import Game
from shengji.engine.round import Round, Trick, TrickPlay


def packed(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def freeze(rnd):
    """Persist the complete input consumed by the compact exact solver."""
    return dict(hands=rnd.hands, buried=rnd.buried, banker=rnd.banker,
                rank=rnd.ordering.trump_rank, suit=rnd.ordering.trump_suit,
                turn=rnd.turn, points=rnd.attacker_points, leader=rnd.trick.leader,
                plays=[[p.seat, p.cards] for p in rnd.trick.plays])


def thaw(row):
    rnd = Round(row['rank'], row['banker'], random.Random(0))
    rnd.phase = 'play'
    rnd.hands = [list(h) for h in row['hands']]
    rnd.buried = list(row['buried'])
    rnd.ordering = Ordering(row['suit'], row['rank'])
    rnd.trump_suit = row['suit']
    rnd.turn = row['turn']
    rnd.attacker_points = row['points']
    rnd.trick = Trick(row['leader'], [TrickPlay(s, list(c)) for s, c in row['plays']])
    return rnd


def capture(seeds, cards):
    roots = []
    for seed in seeds:
        bots = [HeuristicBot() for _ in range(4)]
        rnd = prepare_round(Game(random.Random(seed)), bots)
        while rnd.phase == 'play':
            if max(map(len, rnd.hands)) <= cards and not rnd.trick.plays:
                for _ in range(4):
                    if rnd.phase != 'play':
                        break
                    roots.append(json.loads(packed(freeze(rnd))))
                    rnd.play(rnd.turn, bots[rnd.turn].decide_play(rnd, rnd.turn))
                break
            rnd.play(rnd.turn, bots[rnd.turn].decide_play(rnd, rnd.turn))
    if not roots:
        raise ValueError('no eligible roots')
    return dict(schema='exact-frozen-v1', roots=roots)


def run(fixture, repeats, cap, opts, backend='compiled'):
    if fixture['schema'] != 'exact-frozen-v1' or not fixture['roots']:
        raise ValueError('expected nonempty exact-frozen-v1 fixture')
    if repeats < 1 or cap < 1:
        raise ValueError('repeats and node cap must be positive')
    native = None
    if backend == 'compiled':
        binary = Path(importlib.import_module('shengji.ai._endgame_fast').__file__).resolve()
        if not binary.is_relative_to(SERVER):
            raise ValueError('native extension is outside target server')
        native = dict(path=str(binary), sha256=hashlib.sha256(binary.read_bytes()).hexdigest())
    rows = []
    for root in fixture['roots']:
        samples, witness = [], None
        for repeat in range(repeats + 1):
            rnd = thaw(root)
            start = time.perf_counter()
            session = CompactWorldSession(rnd, max_hand_cards=8, max_nodes=cap,
                                          backend=backend, level=True, level_opts=opts)
            setup = time.perf_counter() - start
            start = time.perf_counter()
            try:
                outcome = ['value', session.solve_level(rnd)]
            except ExactEndgameBudgetExceeded:
                outcome = ['node_cap']
            elapsed = time.perf_counter() - start
            if session.backend != backend:
                raise ValueError('backend fallback invalidates timing')
            observed = dict(outcome=outcome, nodes=session.nodes, hits=session.cache_hits)
            if witness is not None and witness != observed:
                raise ValueError('repeated root changed outcome or work')
            witness = observed
            if repeat:
                samples.append(dict(setup_s=setup, solve_s=elapsed))
        rows.append(dict(witness=witness, samples=samples))
    return dict(schema='exact-timing-v1', fixture_sha256=hashlib.sha256(packed(fixture)).hexdigest(),
                cap=cap, opts=opts, backend=backend, rows=rows, server=str(SERVER), native=native,
                head=subprocess.check_output(['git', '-C', str(SERVER), 'rev-parse', 'HEAD'], text=True).strip())


def compare(base, candidate):
    for key in ('schema', 'fixture_sha256', 'cap', 'opts', 'backend'):
        if base[key] != candidate[key]:
            raise ValueError(f'incompatible {key}')
    if not base['rows'] or len(base['rows']) != len(candidate['rows']):
        raise ValueError('root count mismatch or empty result')
    ratios = []
    for left, right in zip(base['rows'], candidate['rows']):
        if left['witness'] != right['witness']:
            raise ValueError('outcome or work differs; fixed-work comparison refused')
        def median(row):
            return statistics.median(s['setup_s'] + s['solve_s'] for s in row['samples'])
        ratios.append(median(right) / median(left))
    return dict(candidate_over_base_by_root=ratios, median_ratio=statistics.median(ratios),
                claim='fixed-work cold exact roots only; not gameplay strength')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('capture')
    p.add_argument('out', type=Path)
    p.add_argument('--seeds', type=int, nargs='+', default=[53000, 53004])
    p.add_argument('--cards', type=int, choices=range(1, 9), default=7)
    p = sub.add_parser('run')
    p.add_argument('fixture', type=Path)
    p.add_argument('out', type=Path)
    p.add_argument('--repeats', type=int, default=5)
    p.add_argument('--cap', type=int, default=200000)
    p.add_argument('--opts', type=int, default=511)
    p = sub.add_parser('compare')
    p.add_argument('base', type=Path)
    p.add_argument('candidate', type=Path)
    args = parser.parse_args()
    if args.command == 'compare':
        print(json.dumps(compare(json.loads(args.base.read_text()), json.loads(args.candidate.read_text())), indent=2))
        return
    result = (capture(args.seeds, args.cards) if args.command == 'capture' else
              run(json.loads(args.fixture.read_text()), args.repeats, args.cap, args.opts))
    with args.out.open('x') as out:
        json.dump(result, out, indent=2, allow_nan=False)
        out.write('\n')


if __name__ == '__main__':
    main()
