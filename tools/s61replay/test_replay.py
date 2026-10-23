from copy import deepcopy
import random
import sys
from pathlib import Path

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent))
from replay import replay_root, branch_action
from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.engine.round import actual_play_after
from shengji.train.cwv_shortlist_screen import _game_factory_for


def recording(kind):
    fixed = 2 if kind == 'fixed_banker' else None
    rank = '5' if fixed is not None else '2'
    game = (Game(random.Random(19)) if fixed is None
            else _game_factory_for(rank, fixed)(random.Random(19)))
    rnd = game.start_round()
    bot = HeuristicBot()
    trace, history, snapshots = [], [], []
    def note(phase, seat, cards, trick=None, lead=None):
        trace.append([phase, seat, trick, lead, len(rnd.hands[seat]), sorted(cards or [])])
    while rnd.phase == 'deal':
        seat, _, _ = rnd.deal_next()
        cards = bot.decide_declare(rnd, seat)
        note('D', seat, cards)
        if cards: rnd.declare(seat, cards)
    for seat in range(4):
        cards = bot.decide_declare(rnd, seat, final=True)
        note('F', seat, cards)
        if cards: rnd.declare(seat, cards)
    rnd.finalize_declare()
    buried = bot.decide_bury(rnd, rnd.banker)
    note('B', rnd.banker, buried)
    rnd.bury(rnd.banker, buried)
    for _ in range(12):
        seat = rnd.turn
        snapshots.append(deepcopy(rnd))
        cards = bot.decide_play(rnd, seat)
        note('P', seat, cards, len(rnd.history), not rnd.trick.plays)
        before = rnd.last_trick
        rnd.play(seat, cards)
        history.append([seat, actual_play_after(rnd, seat, before)])
    return dict(seed=19, round_kind=kind, planned_banker=fixed, trump_rank=rank,
                banker=rnd.banker, trump=rnd.trump_suit or 'NT', buried=buried,
                dtrace=trace, history=history), snapshots


@pytest.mark.parametrize('kind', ['first', 'fixed_banker'])
def test_recorded_engine_prefix_reconstructs_same_root(kind):
    row, states = recording(kind)
    for index in (0, 1, 4, 11):
        root, witness = replay_root(row, index)
        assert root.hands == states[index].hands
        assert root.turn == states[index].turn
        assert root.attacker_points == states[index].attacker_points
        assert len(root.history) == len(states[index].history)
        assert sorted(witness['accepted']) == sorted(row['history'][index][1])
        assert max(map(len, root.hands)) > 7
    root, witness = replay_root(row, 0)
    original_hands = deepcopy(root.hands)
    branch, alternative = branch_action(root, [root.hands[root.turn][0]])
    assert root.hands == original_hands
    assert branch.hands != root.hands
    assert alternative['accepted'] == alternative['attempted']


@pytest.mark.parametrize('defect', ['hand', 'seat', 'trick', 'accepted', 'buried', 'banker', 'missing'])
def test_drift_refused(defect):
    row, _ = recording('fixed_banker')
    play = next(x for x in row['dtrace'] if x[0] == 'P')
    if defect == 'hand': play[4] += 1
    elif defect == 'seat': play[1] = (play[1] + 1) % 4
    elif defect == 'trick': play[2] += 1
    elif defect == 'accepted': row['history'][0][1] = ['SJ']
    elif defect == 'buried': row['buried'] = []
    elif defect == 'banker': row['banker'] = (row['banker'] + 1) % 4
    else: row['dtrace'] = []
    with pytest.raises(ValueError): replay_root(row, 0)


def test_failed_throw_keeps_attempted_and_accepted_actions_separate():
    from itertools import combinations
    from shengji.engine.legal import uniform_suit, validate_lead
    row, _ = recording('first')
    root, _ = replay_root(row, 0)
    seat = root.turn
    opponents = [root.hands[s] for s in range(4) if s % 2 != seat % 2]
    for cards in combinations(sorted(set(root.hands[seat])), 2):
        if uniform_suit(list(cards), root.ordering) is None:
            continue
        accepted, message = validate_lead(list(cards), root.hands[seat], opponents, root.ordering)
        if message is not None and accepted:
            _, witness = branch_action(root, cards)
            assert witness['failed_throw']
            assert sorted(witness['accepted']) == sorted(accepted)
            assert witness['attempted'] == list(cards)
            return
    pytest.fail('fixed fixture lost its refused throw')
