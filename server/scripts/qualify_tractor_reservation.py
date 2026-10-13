"""Bounded OFF/ON tractor-reservation qualification on one deterministic root.

This is evidence collection, not a strength comparison: a no-displacement result
is valid.  The caller must provide an explicitly pinned NumPy package and output
path; each completed decision is flushed so a later failure preserves prior rows.
"""
import argparse
import asyncio
import copy
import json
import math
import random
import time
from collections import Counter
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


def _same_cards(left, right):
    """Compare card lists as plays, retaining duplicate-card multiplicity."""
    return (isinstance(left, list) and isinstance(right, list)
            and Counter(left) == Counter(right))


def _play_evidence(events, seat, record, submitted_cards):
    """Return the engine-backed play fields or raise on malformed evidence."""
    if not isinstance(record, dict):
        raise ValueError('decision record is not an object')
    played = record.get('played')
    if not _same_cards(played, submitted_cards):
        raise ValueError('decision record played does not match submitted_cards')

    play_events = [event for event in events
                   if event.get('e') == 'play' and event.get('seat') == seat]
    if len(play_events) != 1:
        raise ValueError(f'expected exactly one play event for seat {seat}')
    event = play_events[0]
    if event.get('decision') != record:
        raise ValueError('play event decision is not bound to decision record')
    final_cards = event.get('cards')
    if not isinstance(final_cards, list):
        raise ValueError('play event cards are not a list')

    attempted_cards = event.get('attempted_cards')
    engine_resolution = event.get('engine_resolution')
    if not _same_cards(final_cards, submitted_cards):
        if (not _same_cards(attempted_cards, submitted_cards)
                or engine_resolution != 'failed_throw_forced'):
            raise ValueError('unequal final/submitted cards lack failed-throw resolution')

    admitted = record.get('admitted')
    value_means = record.get('value_means')
    if not isinstance(admitted, list) or not isinstance(value_means, list):
        raise ValueError('admitted and value_means must be lists')
    if len(value_means) != len(admitted):
        raise ValueError('value_means length does not match admitted')
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) for value in value_means):
        raise ValueError('value_means contains a non-finite value')
    return final_cards, attempted_cards, engine_resolution


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
        events = []

        def capture_event(kind, **data):
            events.append({'e': kind, **copy.deepcopy(data)})

        room.log_event = capture_event
        started = time.perf_counter()
        prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
        seconds = time.perf_counter() - started
        if prepared is None or rnd.hands != before_hands or rnd.trick.plays != before_plays:
            raise RuntimeError('snapshot mutated live root before commit')
        copied = prepared.decision.snapshot.bot_copy
        raw_record = copied.last_decision_record
        record = raw_record if isinstance(raw_record, dict) else {}
        admitted = [list(a) for a in record.get('admitted', [])
                    if isinstance(a, (list, tuple))]
        admitted_indices = record.get('admitted_indices') or []
        selected_index = record.get('selected_index')
        selected_action = None
        ballot_bound = (bool(admitted) and len(admitted) == len(admitted_indices)
                        and len(set(admitted_indices)) == len(admitted_indices)
                        and selected_index in admitted_indices)
        if ballot_bound:
            selected_action = admitted[admitted_indices.index(selected_index)]
        submitted_cards = list(prepared.decision.cards)
        commit_error = None
        committed = False
        second_commit = False
        try:
            committed = srv._commit_bot_turn(room, prepared)
            second_commit = srv._commit_bot_turn(room, prepared) if committed else False
        except Exception as exc:
            # `_log_play` deliberately fails closed when the policy's submitted
            # record disagrees with the server boundary.  Preserve that partial
            # row before surfacing the malformed evidence to the caller.
            commit_error = f'commit failed: {type(exc).__name__}: {exc}'
        if not committed or second_commit:
            commit_error = commit_error or 'decision did not commit exactly once'
        keys = {tuple(sorted(a)) for a in admitted}
        baseline_keys = {tuple(sorted(a)) for a in baseline_admitted or []}
        displacement = baseline_admitted is not None and keys != baseline_keys
        final_cards = None
        attempted_cards = None
        engine_resolution = None
        evidence_error = commit_error
        if evidence_error is None:
            try:
                final_cards, attempted_cards, engine_resolution = _play_evidence(
                    events, seat, raw_record, submitted_cards)
            except (TypeError, ValueError) as exc:
                evidence_error = str(exc)
        row = {
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
            'submitted_cards': submitted_cards,
            'final_cards': final_cards,
            'attempted_cards': attempted_cards,
            'engine_resolution': engine_resolution,
            'ballot_bound': ballot_bound,
            'value_means': record.get('value_means'),
            'admitted_count': len(admitted),
            'candidate_bound_ok': len(admitted) <= 8,
            'committed': committed, 'snapshot_unchanged': True,
            'evidence_valid': evidence_error is None,
        }
        if baseline_admitted is not None:
            row['ballot_added'] = [list(a) for a in sorted(keys - baseline_keys)]
            row['ballot_removed'] = [list(a) for a in sorted(baseline_keys - keys)]
        passed = (record.get('work_complete') is True and record.get('worlds') == 64
                  and seconds < 3 and committed and ballot_bound
                  and row['candidate_bound_ok'] and row['evidence_valid'])
        row['passed'] = passed
        if evidence_error is not None:
            row['evidence_error'] = evidence_error
        rows.append(row)
        dest.write(json.dumps(row) + '\n')
        dest.flush()
        if baseline_admitted is None:
            baseline_admitted = admitted
        if not passed:
            reason = evidence_error or f'qualification failed for enabled={enabled}'
            raise RuntimeError(reason)
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
