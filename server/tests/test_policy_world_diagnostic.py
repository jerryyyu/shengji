import copy
import numpy as np
import pytest

from shengji.train.policy_world_diagnostic import diagnose_position
from test_policy_world_search import state


def test_crossed_design_separates_admission_from_value_noise(monkeypatch):
    from types import SimpleNamespace
    from shengji.train import policy_world_diagnostic as diag
    monkeypatch.setattr(diag.HeuristicBot, 'decide_play', lambda *a: [0])
    monkeypatch.setattr(diag, 'enumerate_legal', lambda *a, **kw:
                        SimpleNamespace(actions=[[0], [1], [2]], count=3, complete=True))
    monkeypatch.setattr(diag, 'world_diversity', lambda worlds:
                        dict(unique_worlds=len(worlds), duplicate_worlds=0))
    calls = []
    def worlds(bot, *args):
        calls.append(bot)
        return ([0, 1] if len(calls) == 1 else [2, 3]), 2
    monkeypatch.setattr(diag.PolicyValueBot, '_worlds', worlds)
    monkeypatch.setattr(diag.PolicyValueBot, 'scores', lambda *args:
                        np.asarray([[0, 4, 1], [0, 0, 9]]))
    matrix = np.asarray([[0, 5, 1], [0, -5, 9], [0, -1, 3], [0, -1, 3]])
    def values(bot, rnd, seat, actions, sampled):
        return matrix[sampled[0], [a[0] for a in actions]], 1
    monkeypatch.setattr(diag.PolicyValueBot, '_value_means', values)
    result = diagnose_position(None, object(), None, 0, counts=(1, 2), candidates=2)
    cells = {(c['admission_worlds'], c['value_worlds']): c for c in result['cells']}
    assert cells[1, 1]['selected_index'] == 1
    assert cells[1, 2]['selected_index'] == 0  # fixed admission, changed value estimate
    assert cells[2, 1]['selected_index'] == 2  # fixed value worlds, changed admission
    assert cells[2, 2]['selected_index'] == 2
    assert cells[1, 1]['fresh_union_gap'] == 4
    assert cells[2, 2]['fresh_union_gap'] == 0
    assert cells[2, 2]['paired_world_difference_variance'] == 32
    assert [row['overlap_with_largest'] for row in result['admissions']] == [1, 2]


@pytest.mark.parametrize('kw', [dict(counts=()), dict(counts=(2, 1)),
    dict(counts=(2, 2)), dict(counts=(True,)), dict(counts=(257,)),
    dict(seed=1, audit_seed=1)])
def test_refuses_invalid_design(kw):
    with pytest.raises(ValueError):
        diagnose_position(None, None, None, 0, **kw)


def test_real_position_privacy_common_prefixes_and_ties():
    rnd = state()
    before = copy.deepcopy(rnd)
    seat = rnd.turn
    class Evaluator:
        rows = 0
        def score(self, leaves, root):
            assert root == seat
            self.rows += len(leaves)
            assert all(len(leaf.history) == len(rnd.history) + 1 for leaf in leaves)
            return np.zeros(len(leaves))
    def predict(x):
        return np.zeros((len(x), 54))
    ev = Evaluator()
    result = diagnose_position(predict, ev, rnd, seat, counts=(1, 2, 4), candidates=2)
    assert len(result['cells']) == 9
    assert ev.rows == result['value_evaluations'] == 16
    assert all(row['selected_gap'] == row['fresh_union_gap'] == 0 for row in result['cells'])
    anchor = result['admissions'][0]['indices'][0]
    assert all(row['selected_index'] == anchor for row in result['cells'])
    assert all(row['overlap_with_largest'] == 2 for row in result['admissions'])
    assert rnd.hands == before.hands and rnd.history == before.history
    others = [s for s in range(4) if s != seat]
    changed = copy.deepcopy(rnd)
    changed.hands[others[0]], changed.hands[others[1]] = changed.hands[others[1]], changed.hands[others[0]]
    assert diagnose_position(predict, Evaluator(), changed, seat,
                             counts=(1, 2, 4), candidates=2) == result
