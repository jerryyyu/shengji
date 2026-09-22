from types import SimpleNamespace
import copy
import numpy as np
import pytest

from shengji.train.policy_selective_mc import PolicySelectiveMCBot


@pytest.mark.parametrize('gap', [-1, float('nan'), float('inf'), True, 6])
def test_gap_bound(gap):
    with pytest.raises(ValueError):
        PolicySelectiveMCBot(None, evaluator=object(), verify_gap=gap)


@pytest.mark.parametrize('means', [[1.], [1., 0.]])
def test_single_or_large_gap_never_samples(monkeypatch, means):
    b=PolicySelectiveMCBot(None, evaluator=object())
    def forbidden(*a): raise AssertionError('untriggered MC')
    monkeypatch.setattr(b.verifier, '_worlds', forbidden)
    assert b._select(None, 0, [['S2']]*len(means), np.array(means)) == 0
    assert not b._verification['triggered']


def test_shared_fresh_worlds_and_root_team_utility(monkeypatch):
    b=PolicySelectiveMCBot(None, evaluator=object(), verify_worlds=2)
    worlds=[([['S2'],['S3'],['S4'],['S5']], ['S6'])]*2
    monkeypatch.setattr(b.verifier, '_worlds', lambda *a: (worlds,3))
    seen=[]
    def rollout(rnd,seat,sampled,buried,candidate):
        seen.append((sampled,buried))
        return 80 if candidate==['S2'] else 160
    monkeypatch.setattr(b.verifier.sampler, '_rollout', rollout)
    actions=[['S2'],['S3']]
    assert b._select(SimpleNamespace(is_attacker=lambda s: True),0,actions,np.array([.01,0.])) == 1
    assert seen[0] == seen[1] == seen[2] == seen[3]
    assert b._verification['rollouts'] == 4 and b._verification['sample_attempts'] == 3
    assert b._select(SimpleNamespace(is_attacker=lambda s: False),0,actions,np.array([.01,0.])) == 0


def test_mc_ties_keep_value_winner(monkeypatch):
    b=PolicySelectiveMCBot(None,evaluator=object(),verify_worlds=1)
    monkeypatch.setattr(b.verifier,'_worlds',lambda *a: ([([[],[],[],[]],[])],1))
    monkeypatch.setattr(b.verifier.sampler,'_rollout',lambda *a: 80)
    assert b._select(SimpleNamespace(is_attacker=lambda s: True),0,[[],[]],np.array([0.,.01])) == 1


@pytest.mark.parametrize('points', [float('nan'), float('inf'), 80.5])
def test_invalid_terminal_points_refuse(monkeypatch, points):
    b = PolicySelectiveMCBot(None, evaluator=object(), verify_worlds=1)
    monkeypatch.setattr(b.verifier, '_worlds', lambda *a: ([([[], [], [], []], [])], 1))
    monkeypatch.setattr(b.verifier.sampler, '_rollout', lambda *a: points)
    with pytest.raises(ValueError, match='finite integer terminal points'):
        b._select(SimpleNamespace(is_attacker=lambda s: True), 0, [[], []], np.zeros(2))


def test_verification_sampling_failure_does_not_fall_back(monkeypatch):
    from test_policy_world_search import state
    b = PolicySelectiveMCBot(lambda x: np.zeros((len(x), 54)),
        evaluator=SimpleNamespace(score=lambda leaves, root: np.zeros(len(leaves))),
        worlds=1, candidates=2)
    def refused(*args):
        raise RuntimeError('policy world sampling short: 0/8')
    monkeypatch.setattr(b.verifier, '_worlds', refused)
    rnd = state()
    with pytest.raises(RuntimeError, match='sampling short'):
        b.decide_play(rnd, rnd.turn)
    assert b.last_decision_record is None


def test_exact_endgame_scores_are_not_misread_as_points(monkeypatch):
    b = PolicySelectiveMCBot(None, evaluator=object(), verify_worlds=1)
    monkeypatch.setattr(b.verifier, '_worlds', lambda *a: ([([[], [], [], []], [])], 1))
    monkeypatch.setattr(b.verifier.sampler, 'EXACT_ENDGAME', True)
    with pytest.raises(ValueError, match='actual terminal rollout points'):
        b._select(None, 0, [[], []], np.zeros(2))


def test_real_verification_is_independent_of_hidden_hands():
    from test_policy_world_search import state
    rnd=state(); seat=rnd.turn
    changed=copy.deepcopy(rnd)
    others=[s for s in range(4) if s!=seat]
    changed.hands[others[0]],changed.hands[others[1]]=changed.hands[others[1]],changed.hands[others[0]]
    evaluator=SimpleNamespace(score=lambda leaves, root: np.zeros(len(leaves)))
    predict=lambda x: np.tile(np.arange(54),(len(x),1))
    kwargs=dict(evaluator=evaluator,worlds=1,candidates=2,verify_worlds=2,seed=23)
    a=PolicySelectiveMCBot(predict,**kwargs); b=PolicySelectiveMCBot(predict,**kwargs)
    before=copy.deepcopy(rnd.hands)
    assert a.decide_play(rnd,seat)==b.decide_play(changed,seat)
    assert a.last_decision_record['verification']==b.last_decision_record['verification']
    assert a.last_decision_record['verification']['triggered']
    assert rnd.hands==before
