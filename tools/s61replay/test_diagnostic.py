from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'server/tests'))
from diagnostic import diagnose_pair
from test_locator import fixture
from test_capture import make_bot
from shengji.ai.heuristic import HeuristicBot
from replay import branch_action
from served import replay_served_prefix
from capture import capture_lead


def factory(*, seed):
    bot = make_bot()
    heuristic = HeuristicBot()
    bot.decide_declare = heuristic.decide_declare
    bot.decide_bury = heuristic.decide_bury
    return bot


def bound_fixture():
    locator, rows, root = fixture()
    bot, restored, _ = replay_served_prefix(rows[1], factory, seat=root.turn)
    played = capture_lead(bot, restored)['played']
    alternative = next([card] for card in root.hands[root.turn]
                       if [card] != played)
    locator['release46_action'] = played
    locator['exploiter_action'] = alternative
    for mirror, action in ((1, played), (0, alternative)):
        rows[mirror]['dtrace'][locator['index']][5] = action
        _, witness = branch_action(root, action)
        rows[mirror]['history'][0][1] = witness['accepted']
    return locator, rows


def test_extracted_pair_to_served_paired_continuation():
    locator, rows = bound_fixture()
    before = deepcopy(rows)
    result = diagnose_pair(rows, factory, policy_identity='synthetic-flat-pv',
                           seed=51, locator=locator)
    assert rows == before
    contrast = result['continuation']
    assert contrast['weights'] == [.5, .5]
    assert contrast['perspective_seat'] == locator['seat']
    assert [a['attempted'] for a in contrast['actions']] == [
        locator['release46_action'], locator['exploiter_action']]
    assert all(w['completed_tricks'] == 2 for a in contrast['actions'] for w in a['worlds'])
    assert json.loads(json.dumps(result))['schema'] == 's61-served-lead-diagnostic-v1'


def test_saved_choice_drift_refused_before_replies():
    locator, rows = bound_fixture()
    locator['release46_action'], locator['exploiter_action'] = (
        locator['exploiter_action'], locator['release46_action'])
    rows[0]['dtrace'], rows[1]['dtrace'] = rows[1]['dtrace'], rows[0]['dtrace']
    rows[0]['history'], rows[1]['history'] = rows[1]['history'], rows[0]['history']
    calls = []
    def counted_factory(*, seed):
        calls.append(seed)
        return factory(seed=seed)
    with pytest.raises(ValueError, match='differs from saved locator'):
        diagnose_pair(rows, counted_factory, policy_identity='synthetic-flat-pv',
                      seed=51, locator=locator)
    assert len(calls) == 1
