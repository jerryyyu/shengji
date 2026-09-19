import copy
import random

import numpy as np
import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.train.policy_prior import CARD_INDEX
from shengji.train.policy_world_search import PolicyWorldBot


def state():
    rnd = Game(random.Random(625091990)).start_round()
    h = HeuristicBot()
    while rnd.phase == 'deal':
        seat, _, _ = rnd.deal_next()
        c = h.decide_declare(rnd, seat)
        if c: rnd.declare(seat, c)
    for seat in range(4):
        c = h.decide_declare(rnd, seat, final=True)
        if c: rnd.declare(seat, c)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, h.decide_bury(rnd, rnd.banker))
    return rnd


def test_batched_scores_average_and_card_multiplicity():
    rnd = state(); seat = rnd.turn
    lo = np.arange(4*54,dtype=float).reshape(4,54)
    calls=[]
    bot=PolicyWorldBot(lambda x: calls.append(x.copy()) or lo, worlds=4)
    worlds,_=bot._worlds(rnd,seat)
    c=rnd.hands[seat][0]
    got=bot.scores(rnd,seat,[(c,), (c,c)],worlds)
    assert len(calls)==1 and calls[0].shape[0]==4
    assert np.array_equal(got[:,0],lo[:,CARD_INDEX[c]])
    assert np.array_equal(got[:,1],2*got[:,0])


def test_hidden_hands_do_not_change_sampled_policy_inputs_or_action():
    rnd=state(); seat=rnd.turn
    other=[s for s in range(4) if s!=seat]
    changed=copy.deepcopy(rnd)
    changed.hands[other[0]],changed.hands[other[1]]=changed.hands[other[1]],changed.hands[other[0]]
    seen=[]
    def predict(x):
        seen.append(x.copy())
        return np.tile(np.arange(54),(len(x),1))
    a=PolicyWorldBot(predict,worlds=4,seed=7)
    b=PolicyWorldBot(predict,worlds=4,seed=7)
    before=copy.deepcopy(rnd.hands)
    assert a.decide_play(rnd,seat)==b.decide_play(changed,seat)
    assert np.array_equal(seen[0],seen[1])
    assert rnd.hands==before
    assert a.last_decision_record['worlds']==4


def test_world_count_uses_same_rng_prefix():
    rnd=state(); seat=rnd.turn
    a=PolicyWorldBot(None,worlds=1,seed=9)
    b=PolicyWorldBot(None,worlds=4,seed=9)
    wa,_=a._worlds(rnd,seat); wb,_=b._worlds(rnd,seat)
    assert wa[0]==wb[0]


def test_nonbanker_hidden_kitty_does_not_change_policy_inputs():
    rnd = state()
    rnd.play(rnd.turn, HeuristicBot().decide_play(rnd, rnd.turn))
    seat = rnd.turn
    assert seat != rnd.banker
    changed = copy.deepcopy(rnd)
    other = next(s for s in range(4) if s != seat)
    changed.buried[0], changed.hands[other][-1] = (
        changed.hands[other][-1], changed.buried[0])
    seen = []
    def predict(x):
        seen.append(x.copy())
        return np.tile(np.arange(54), (len(x), 1))
    a = PolicyWorldBot(predict, worlds=4, seed=11)
    b = PolicyWorldBot(predict, worlds=4, seed=11)
    assert a.decide_play(rnd, seat) == b.decide_play(changed, seat)
    assert np.array_equal(seen[0], seen[1])


def test_failed_sampling_refuses_instead_of_silent_fallback(monkeypatch):
    rnd=state(); bot=PolicyWorldBot(None,worlds=1)
    monkeypatch.setattr(bot.sampler,'_sample_hands',lambda *a: None)
    with pytest.raises(RuntimeError,match='sampling short'):
        bot.decide_play(rnd,rnd.turn)
    assert bot.last_decision_record is None


def test_decision_uses_mean_scores_not_majority_vote(monkeypatch):
    from types import SimpleNamespace
    from shengji.train import policy_world_search as module
    rnd = state()
    first, second = rnd.hands[rnd.turn][:2]
    assert first != second
    bot = PolicyWorldBot(None, worlds=3)
    monkeypatch.setattr(module, 'enumerate_legal', lambda *a, **k:
                        SimpleNamespace(actions=[(first,), (second,)], count=2, complete=True))
    monkeypatch.setattr(bot, '_worlds', lambda *a: ([None] * 3, 3))
    # Two worlds prefer first, but the average preference favors second.
    monkeypatch.setattr(bot, 'scores', lambda *a: np.array([[1., 0.], [1., 0.], [0., 9.]]))
    assert bot.decide_play(rnd, rnd.turn) == [second]
    assert bot.last_decision_record['selected_mean_score'] == 3.


def test_legacy_sampler_void_relaxations_are_rejected(monkeypatch):
    from types import SimpleNamespace
    from shengji.train import policy_world_search as module
    rnd = state(); seat = rnd.turn
    other = (seat + 1) % 4
    voids = {s: set() for s in range(4)}
    voids[other].add(rnd.ordering.eff_suit(rnd.hands[other][0]))
    monkeypatch.setattr(module, 'Memory', lambda *a: SimpleNamespace(voids=voids))
    bot = PolicyWorldBot(None, worlds=1)
    calls = []
    def invalid(*args):
        calls.append(1)
        return {s: list(rnd.hands[s]) for s in range(4) if s != seat}, list(rnd.buried)
    monkeypatch.setattr(bot.sampler, '_sample_hands', invalid)
    with pytest.raises(RuntimeError, match='sampling short'):
        bot._worlds(rnd, seat)
    assert len(calls) == 40


@pytest.mark.parametrize('output',[np.zeros((2,54)), np.full((1,54),np.nan)])
def test_invalid_predictions_refuse(output):
    rnd=state(); bot=PolicyWorldBot(lambda x:output,worlds=1)
    worlds,_=bot._worlds(rnd,rnd.turn)
    with pytest.raises(ValueError,match='finite'):
        bot.scores(rnd,rnd.turn,[(rnd.hands[rnd.turn][0],)],worlds)


@pytest.mark.parametrize('worlds',[0,True,129,1.5])
def test_world_budget_is_bounded(worlds):
    with pytest.raises(ValueError): PolicyWorldBot(None,worlds=worlds)
