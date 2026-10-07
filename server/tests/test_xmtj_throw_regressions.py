"""XMTJ release38 replay; mechanism tests, NOT a release42 strength readout.

Fixture is the deck/setup and all 64 committed plays (plus attempted actions)
from logs/XMTJ.jsonl, SHA256
b0040f3eea422714afc91ab8ebbdfa0c4ec1def73466bd213b5bd03ab18e19ae.
Names, timestamps, policy scores and model dependencies are deliberately absent.
Controlled worlds below test the swap condition, not historical sampled worlds.
"""
import copy
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from shengji.eval.tactical import (not_a_throw_refuted_by_public_refusal,
                                   refusal_args)
from shengji.harvest.legal import forced_lead
from shengji.rl.replay_log import rebuild_round
from test_pv_doomed_throw_swap import served

EVENTS = json.loads((Path(__file__).parent / 'fixtures/xmtj_round1.json').read_text())
PLAYS = [e for e in EVENTS if e['e'] == 'play']


def position(index):
    rnd = rebuild_round(EVENTS)
    for e in PLAYS[:index]:
        before = Counter(rnd.hands[e['seat']])
        rnd.play(e['seat'], e['attempted'])
        assert before - Counter(rnd.hands[e['seat']]) == Counter(e['cards'])
    return rnd


def test_complete_replay_matches_every_committed_play():
    assert len(PLAYS) == 64
    assert position(len(PLAYS)).phase == 'round_end'


@pytest.mark.parametrize('index,forced', [(40, 'DA'), (44, 'S2'), (48, 'D2')])
def test_later_throws_do_not_repeat_a_publicly_refuted_component(index, forced):
    rnd = position(index)
    action = PLAYS[index]['attempted']
    assert rnd.turn == 3 and not rnd.trick.plays
    assert forced_lead(rnd, 3, action) == [forced]
    ctx = SimpleNamespace(rnd=rnd, seat=3, action=action,
                          fixture=SimpleNamespace(plays=PLAYS[:index]))
    checked = 0
    for prior, e in enumerate(PLAYS[:index]):
        if e['seat'] == 3 and Counter(e['attempted']) != Counter(e['cards']):
            args = refusal_args(PLAYS[:prior+1], 3, rnd.ordering)
            ok, reason = not_a_throw_refuted_by_public_refusal(ctx, **args)
            assert ok, reason
            checked += 1
    assert checked == {40: 1, 44: 2, 48: 3}[index]


@pytest.mark.parametrize('index', [40, 44, 48])
def test_uniform_refusal_swaps_but_one_standing_world_prevents_swap(index):
    rnd = position(index)
    action, forced = PLAYS[index]['attempted'], PLAYS[index]['cards']
    real = (copy.deepcopy(rnd.hands), [])
    # Deliberately synthetic engine witness, NOT a sampled feasible deal:
    # removing other hands makes the selected throw stand. This isolates the
    # universal quantifier; it makes no claim about the historical sampler.
    standing = ([[] if seat != 3 else list(hand)
                 for seat, hand in enumerate(rnd.hands)], [])
    assert forced_lead(rnd, 3, action, real[0]) == forced
    assert forced_lead(rnd, 3, action, standing[0]) is None
    bot = served(doomed_throw_swap=True)
    assert bot._swap_doomed_throw(rnd, 3, action, [real, real]) == forced
    assert bot._doomed_throw_record()['doomed_throw_swap_applied'] is True
    assert bot._swap_doomed_throw(rnd, 3, action, [real, standing]) == action
    record = bot._doomed_throw_record()
    assert record['doomed_throw_swap_applied'] is False
    assert record['doomed_throw_swap_refused_worlds'] == 1
    assert record['doomed_throw_swap_forced_variants'] == 1


@pytest.mark.parametrize('index', [40, 44, 48])
def test_swap_preserves_committed_state_without_new_refusal_notice(index):
    thrown, swapped = position(index), position(index)
    thrown.play(3, PLAYS[index]['attempted'])
    swapped.play(3, PLAYS[index]['cards'])
    assert thrown.hands == swapped.hands
    assert thrown.trick.plays == swapped.trick.plays
    assert thrown.turn == swapped.turn
    assert thrown.history == swapped.history
    assert thrown.notice['attempted'] == PLAYS[index]['attempted']
    # A previous notice can still be aging; require only no NEW refusal.
    assert swapped.notice is None or swapped.notice != thrown.notice
