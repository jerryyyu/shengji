from copy import deepcopy
import sys
from pathlib import Path

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent))
from locator import bind_locator
from replay import replay_root, branch_action
from test_replay import recording


def fixture():
    row, _ = recording('fixed_banker')
    root, _ = replay_root(row, 0)
    index = next(i for i, entry in enumerate(row['dtrace']) if entry[0] == 'P')
    rows = [deepcopy(row), deepcopy(row)]
    choices = sorted(set(root.hands[root.turn]))[:2]
    for mirror, entry in enumerate(rows):
        entry['mirror'] = mirror
        entry['dtrace'][index][5] = [choices[mirror]]
        _, witness = branch_action(root, [choices[mirror]])
        entry['history'][0] = [root.turn, witness['accepted']]
    phase, seat, trick, lead, hand = row['dtrace'][index][:5]
    locator = dict(seed=row['seed'], kind=row['round_kind'], rank=row['trump_rank'],
        index=index, phase=phase, seat=seat, trick=trick, lead=lead, hand=hand,
        exploiter_action=[choices[seat % 2]], release46_action=[choices[1-seat % 2]])
    return locator, rows, root


def test_saved_locator_index_and_role_labels_bind_to_replay():
    locator, rows, original = fixture()
    root, result = bind_locator(locator, list(reversed(rows)))
    assert locator['index'] == 105 and result['play_index'] == 0
    assert root.hands == original.hands
    assert result['exploiter']['attempted'] == locator['exploiter_action']
    assert result['release46']['attempted'] == locator['release46_action']


@pytest.mark.parametrize('defect', ['seed', 'index', 'context', 'label', 'prefix', 'mirror'])
def test_binding_drift_refused(defect):
    locator, rows, _ = fixture()
    if defect == 'seed': locator['seed'] += 1
    elif defect == 'index': locator['index'] = 0
    elif defect == 'context': locator['hand'] -= 1
    elif defect == 'label': locator['exploiter_action'] = ['SJ']
    elif defect == 'prefix': rows[1]['dtrace'][0][4] += 1
    else: rows[1]['mirror'] = 0
    with pytest.raises(ValueError): bind_locator(locator, rows)
