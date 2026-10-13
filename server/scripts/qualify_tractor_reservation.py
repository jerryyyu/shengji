"""Bounded OFF/ON tractor-reservation qualification on one deterministic root.

This is evidence collection, not a strength comparison: a no-displacement result
is valid.  The caller must provide an explicitly pinned NumPy package and output
path; each completed decision is flushed so a later failure preserves prior rows.
"""
import argparse
import asyncio
import copy
import json
import random
import time
from pathlib import Path

from shengji.ai.heuristic import HeuristicBot
from shengji.api import server as srv
from shengji.engine.combos import decompose
from shengji.engine.game import Game
from shengji.train import pv_search_policy as pv


SEED = 625091990


def build_root(seed=SEED):
    rnd = Game(random.Random(seed)).start_round()
    heuristic = HeuristicBot()
    while rnd.phase == 'deal':
        seat, _, _ = rnd.deal_next()
        declaration = heuristic.decide_declare(rnd, seat)
        if declaration:
            rnd.declare(seat, declaration)
    for seat in range(4):
        declaration = heuristic.decide_declare(rnd, seat, final=True)
        if declaration:
            rnd.declare(seat, declaration)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, heuristic.decide_bury(rnd, rnd.banker))
    if rnd.phase != 'play' or rnd.trick.plays:
        raise RuntimeError('seed did not produce a first-trick root')
    return rnd


def _pure_tractor(rnd, action):
    if len(action) < 4 or len({rnd.ordering.eff_suit(c) for c in action}) != 1:
        return False
    components = decompose(list(action), rnd.ordering).components
    return len(components) == 1 and components[0].pair_len >= 2


def _recipe(package, sha256, enabled):
    return pv.pv_registry_entries(
        package, sha256=sha256, worlds=64, candidates=8, cap=4000,
        batch_size=128, serving_budget_seconds=3,
        admission_diversity=True, refusal_constraints=True,
        tiebreak_points=True, lead_anchor=True,
        doomed_throw_reselect=True, value_declare=True,
        bury_arm='hybrid', bury_serving_budget_seconds=2,
        tractor_reservation=enabled)


async def qualify(package, sha256, dest, *, seed=SEED):
    rows = []
    baseline_admitted = None
    for enabled in (False, True):
        rnd = build_root(seed)
        seat = rnd.turn
        entries = _recipe(package, sha256, enabled)
        name, factory = next(iter(entries.items()))
        bot = factory(seed=seed)
        before_hands = copy.deepcopy(rnd.hands)
        before_plays = copy.deepcopy(rnd.trick.plays)
        game = Game(random.Random(7))
        game.round = rnd
        room = srv.Room(code=f'TRACTOR-{int(enabled)}', game=game, bot=bot,
                        seats=[srv.Seat(str(s), is_bot=True) for s in range(4)])
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        room.log_event = lambda *args, **kwargs: None
        started = time.perf_counter()
        prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
        seconds = time.perf_counter() - started
        if prepared is None or rnd.hands != before_hands or rnd.trick.plays != before_plays:
            raise RuntimeError('snapshot mutated live root before commit')
        copied = prepared.decision.snapshot.bot_copy
        record = copied.last_decision_record or {}
        admitted = [list(a) for a in record.get('admitted', [])]
        admitted_indices = record.get('admitted_indices') or []
        selected_index = record.get('selected_index')
        selected_action = None
        ballot_bound = (bool(admitted) and len(admitted) == len(admitted_indices)
                        and len(set(admitted_indices)) == len(admitted_indices)
                        and selected_index in admitted_indices)
        if ballot_bound:
            selected_action = admitted[admitted_indices.index(selected_index)]
        final_cards = list(prepared.decision.cards)
        committed = srv._commit_bot_turn(room, prepared)
        if not committed or srv._commit_bot_turn(room, prepared):
            raise RuntimeError('decision did not commit exactly once')
        keys = {tuple(sorted(a)) for a in admitted}
        baseline_keys = {tuple(sorted(a)) for a in baseline_admitted or []}
        displacement = baseline_admitted is not None and keys != baseline_keys
        rows.append({
            'enabled': enabled, 'policy': name, 'seed': seed,
            'seat': seat, 'seconds': seconds, 'worlds': record.get('worlds'),
            'work_complete': record.get('work_complete'),
            'fallback_reason': record.get('reason'),
            'legal_count': record.get('legal_count'),
            'legal_complete': record.get('legal_complete'), 'admitted': admitted,
            'admitted_tractor_cards': [a for a in admitted if _pure_tractor(rnd, a)],
            'displacement_from_off': displacement,
            'selected_index': selected_index,
            'selected_action': selected_action,
            'final_cards': final_cards,
            'ballot_bound': ballot_bound,
            'value_means': record.get('value_means'),
            'admitted_count': len(admitted),
            'candidate_bound_ok': len(admitted) <= 8,
            'committed': committed, 'snapshot_unchanged': True,
        })
        if baseline_admitted is not None:
            rows[-1]['ballot_added'] = [list(a) for a in sorted(keys - baseline_keys)]
            rows[-1]['ballot_removed'] = [list(a) for a in sorted(baseline_keys - keys)]
        passed = (record.get('work_complete') is True and record.get('worlds') == 64
                  and seconds < 3 and committed and ballot_bound
                  and rows[-1]['candidate_bound_ok'])
        rows[-1]['passed'] = passed
        dest.write(json.dumps(rows[-1]) + '\n')
        dest.flush()
        if baseline_admitted is None:
            baseline_admitted = admitted
        if not passed:
            raise RuntimeError(f'qualification failed for enabled={enabled}')
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=SEED)
    args = parser.parse_args(argv)
    if len(args.sha256) != 64 or any(c not in '0123456789abcdef' for c in args.sha256.lower()):
        raise SystemExit('--sha256 must be a 64-hex package digest')
    with args.out.open('x') as dest:
        rows = asyncio.run(qualify(str(args.package), args.sha256, dest, seed=args.seed))
    print(json.dumps({'rows': len(rows), 'out': str(args.out)}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
