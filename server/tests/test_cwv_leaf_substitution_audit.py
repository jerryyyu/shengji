import json

import pytest

from shengji.ai.registry import REGISTRY
from shengji.train.cwv_horizon_audit import run_fixed_ballot
from shengji.train.cwv_leaf_substitution_audit import run_fixed_leaf_ballot, verify_sampling
from tests.test_world_shortlist import play_state, round_signature


class RecordingLeaf:
    kind = 'audit-stub'

    def __init__(self):
        self.positions = []

    def final_attacker_points(self, clone, seat):
        plays = clone.trick.plays or clone.history[-1].plays
        self.positions.append((len(clone.history), len(clone.trick.plays), seat, clone.turn, plays[-1].seat))
        return 50.


def fixture():
    rnd = play_state()
    candidates = REGISTRY['mc-s0-report-lcb'](seed=7)._candidates(rnd, rnd.turn)
    assert len(candidates) >= 2
    return rnd, list(reversed(candidates[:2]))


def test_wiring_keeps_ballot_and_uses_leaf_in_both_stages_at_requested_horizon():
    rnd, ballot = fixture()
    before = round_signature(rnd)
    leaf = RecordingLeaf()
    got = run_fixed_leaf_ballot(rnd, rnd.turn, ballot, leaf,
                                selection_worlds=2, report_worlds=30)
    assert got['record']['candidates'] == ballot
    assert got['leaf_counts']['leaf_calls'] == got['record']['work']['total_rollouts'] == 64
    assert got['stage_counts'] == dict(selection_net_calls=4, report_net_calls=60)
    assert len(leaf.positions) == 64
    assert all(h == len(rnd.history)+1 and p == 0 and seat == turn
               for h,p,seat,turn,_last in leaf.positions)
    assert round_signature(rnd) == before


def test_no_truncation_reproduces_the_real_fixed_ballot_consumer():
    rnd, ballot = fixture()
    leaf = RecordingLeaf()
    got = run_fixed_leaf_ballot(rnd, rnd.turn, ballot, leaf, seed=31,
                                selection_worlds=2, report_worlds=30, leaf_tricks=100)
    baseline = run_fixed_ballot(rnd, rnd.turn, ballot, seed=31,
                                selection_worlds=2, report_worlds=30)
    saved = json.loads(json.dumps(baseline['record']))
    verify_sampling(saved, got['record'])
    # A real sample identity change must still refuse after normalization.
    saved['rng_state'][1][0] += 1
    with pytest.raises(ValueError, match='^leaf changed sampling identity: rng_state$'):
        verify_sampling(saved, got['record'])
    assert got['played'] == baseline['played']
    for field in ('candidates','means','n_by_candidate','paired_se','raw_winner_index',
                  'report_candidate_index','worlds','eligible_indices','rng_state',
                  'report_fold','reason'):
        assert got['record'][field] == baseline['record'][field], field
    assert not leaf.positions and got['leaf_counts']['predicted_leaves'] == 0
    assert got['stage_counts'] == dict(selection_net_calls=0, report_net_calls=0)


@pytest.mark.parametrize('tricks',[0,1])
def test_training_view_reaches_actual_last_actor_inside_and_after_trick(tricks):
    rnd,ballot=fixture()
    leaf=RecordingLeaf()
    got=run_fixed_leaf_ballot(rnd,rnd.turn,ballot,leaf,selection_worlds=2,
                              report_worlds=30,leaf_tricks=tricks,leaf_view='last_actor')
    assert len(leaf.positions)==64
    assert all(seat==last for _h,_p,seat,_turn,last in leaf.positions)
    assert any(seat!=turn for _h,_p,seat,turn,_last in leaf.positions)
    assert got['leaf_view']=='last_actor' and got['stage_counts']==dict(selection_net_calls=4,report_net_calls=60)


@pytest.mark.parametrize('kwargs,message', [
    ({'leaf_tricks':True}, 'leaf_tricks must be an integer'),
    ({'selection_worlds':0}, 'selection_worlds must be positive'),
    ({'seed':True}, 'seed must be an integer or None'),
])
def test_bad_inputs_refuse(kwargs,message):
    rnd, ballot = fixture()
    with pytest.raises(ValueError,match=f'^{message}$'):
        run_fixed_leaf_ballot(rnd,rnd.turn,ballot,RecordingLeaf(),**kwargs)
