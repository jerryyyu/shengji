from copy import deepcopy
import sys
from pathlib import Path

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent))
from continuation import compare_continuations
from replay import replay_root
from test_replay import recording
from shengji.ai.heuristic import HeuristicBot


def fixture():
    row, _ = recording('fixed_banker')
    root, _ = replay_root(row, 0)
    actions = [[card] for card in sorted(set(root.hands[root.turn]))[:2]]
    return root, actions


def factory(rng):
    bot = HeuristicBot()
    def reply(state, seat):
        return dict(cards=bot.decide_play(state, seat), fallback=False)
    return reply


def endpoint(state, team):
    return state.attacker_points * (1 if team != state.banker % 2 else -1)


def run(root, actions, **patch):
    args = dict(worlds=[root, deepcopy(root)], weights=[.25, .75], actions=actions,
                tricks=2, reply_factory=factory, evaluate=endpoint, seed=19,
                reply_identity='heuristic-test', evaluator_identity='points-test', served_ballot=actions[:1])
    args.update(patch)
    return compare_continuations(**args)


@pytest.mark.parametrize('tricks', [2, 3])
def test_replay_root_to_paired_completed_endpoints(tricks):
    root, actions = fixture()
    hands = deepcopy(root.hands)
    calls, starts = [], []
    def replies(rng):
        starts.append(rng.random())
        return factory(rng)
    def evaluate(state, team):
        calls.append((len(state.history), team))
        return endpoint(state, team)
    result = run(root, actions, tricks=tricks, reply_factory=replies, evaluate=evaluate)
    assert root.hands == hands and len(root.history) == 0
    assert len(calls) == 4 and {n for n, team in calls} == {tricks}
    assert starts[:2] == starts[2:]
    assert [a['in_served_ballot'] for a in result['actions']] == [True, False]
    for action in result['actions']:
        assert all(world['completed_tricks'] == tricks for world in action['worlds'])
        assert action['weighted_value'] == sum(w * row['endpoint_value']
            for w, row in zip(result['weights'], action['worlds']))
    assert run(root, actions, tricks=tricks) == run(root, actions, tricks=tricks)


@pytest.mark.parametrize('defect', ['weights', 'root', 'fallback', 'endpoint', 'horizon'])
def test_invalid_or_incomplete_evidence_refused(defect):
    root, actions = fixture()
    args = {}
    if defect == 'weights': args['weights'] = [.5, .6]
    elif defect == 'root':
        other = deepcopy(root); other.attacker_points += 5
        args['worlds'] = [root, other]
    elif defect == 'fallback':
        args['reply_factory'] = lambda rng: lambda state, seat: dict(cards=[], fallback=True)
    elif defect == 'endpoint': args['evaluate'] = lambda state, team: float('nan')
    else: args['tricks'] = 4
    with pytest.raises(ValueError): run(root, actions, **args)
