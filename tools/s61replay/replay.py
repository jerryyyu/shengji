"""Reconstruct a recorded decision prefix without running a policy or reading files."""
from collections import Counter
from copy import deepcopy
import random

from shengji.engine.game import Game
from shengji.engine.round import actual_play_after
from shengji.train.cwv_shortlist_screen import _game_factory_for


def branch_action(root, cards):
    """Apply an attempted action on an independent engine state, retaining refusal."""
    branch = deepcopy(root)
    seat = branch.turn
    before = branch.last_trick
    branch.play(seat, list(cards))
    accepted = actual_play_after(branch, seat, before)
    return branch, dict(seat=seat, attempted=list(cards), accepted=accepted,
                        failed_throw=Counter(cards) != Counter(accepted))


def replay_root(row, play_index, *, on_decision=None):
    """Return the pre-decision state and checked attempted/accepted action witness."""
    if type(play_index) is not int or play_index < 0:
        raise ValueError('invalid play index')
    if type(row.get('seed')) is not int:
        raise ValueError('missing integer seed')
    kind, rank, fixed = row['round_kind'], row['trump_rank'], row['planned_banker']
    if kind == 'first':
        if rank != '2' or fixed is not None:
            raise ValueError('first-round schedule drift')
        game = Game(random.Random(row['seed']))
    elif kind == 'fixed_banker' and type(fixed) is int and 0 <= fixed < 4:
        game = _game_factory_for(rank, fixed)(random.Random(row['seed']))
    else:
        raise ValueError('invalid round schedule')
    rnd = game.start_round()
    trace = iter(row['dtrace'])

    def take(phase, seat, trick=None, lead=None):
        try:
            entry = next(trace)
        except StopIteration as exc:
            raise ValueError('incomplete decision trace') from exc
        if (not isinstance(entry, list) or len(entry) != 6
                or entry[:5] != [phase, seat, trick, lead, len(rnd.hands[seat])]
                or not isinstance(entry[5], list)
                or any(type(card) is not str for card in entry[5])):
            raise ValueError('decision trace disagrees with replay context')
        if on_decision is not None:
            on_decision(phase, deepcopy(rnd), seat, list(entry[5]))
        return entry[5]

    while rnd.phase == 'deal':
        seat, _, _ = rnd.deal_next()
        cards = take('D', seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = take('F', seat)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    if rnd.banker != row['banker'] or (rnd.trump_suit or 'NT') != row['trump']:
        raise ValueError('declaration outcome drift')
    buried = take('B', rnd.banker)
    if Counter(buried) != Counter(row['buried']):
        raise ValueError('burial drift')
    rnd.bury(rnd.banker, buried)
    history = row['history']
    if play_index >= len(history):
        raise ValueError('target outside committed history')
    failed = []
    for index in range(play_index + 1):
        if rnd.phase != 'play':
            raise ValueError('target after terminal round')
        seat = rnd.turn
        lead = rnd.trick is not None and not rnd.trick.plays
        attempted = take('P', seat, len(rnd.history), lead)
        branch, witness = branch_action(rnd, attempted)
        committed = history[index]
        if (not isinstance(committed, list) or len(committed) != 2
                or committed[0] != seat or not isinstance(committed[1], list)
                or Counter(committed[1]) != Counter(witness['accepted'])):
            raise ValueError('committed play drift')
        if index == play_index:
            return rnd, dict(witness, play_index=index, prior_failed_throws=failed)
        if witness['failed_throw']:
            failed.append(dict(witness, play_index=index))
        rnd = branch
    raise AssertionError('unreachable target')
