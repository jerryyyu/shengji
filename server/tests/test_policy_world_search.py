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
    monkeypatch.setattr(module, 'Memory', lambda *a, **k: SimpleNamespace(voids=voids))
    bot = PolicyWorldBot(None, worlds=1)
    calls = []
    def invalid(*args):
        calls.append(1)
        return {s: list(rnd.hands[s]) for s in range(4) if s != seat}, list(rnd.buried)
    monkeypatch.setattr(bot.sampler, '_sample_hands', invalid)
    with pytest.raises(RuntimeError, match='violates public voids'):
        bot._worlds(rnd, seat)
    assert len(calls) == 1


def test_production_attempt_factor_is_used(monkeypatch):
    rnd = state()
    bot = PolicyWorldBot(None, worlds=2)
    bot.sampler.SAMPLE_ATTEMPT_FACTOR = 3
    calls = []
    monkeypatch.setattr(bot.sampler, '_sample_hands', lambda *a: calls.append(1))
    with pytest.raises(RuntimeError, match='sampling short: 0/2'):
        bot._worlds(rnd, rnd.turn)
    assert len(calls) == 6


def test_worlds_match_production_canonical_pipeline():
    from shengji.ai.cwv_policy import sample_worlds
    from shengji.ai.mcbot import MCBot
    rnd = state()
    expected = sample_worlds(MCBot(seed=31), rnd, rnd.turn, 4)
    actual = PolicyWorldBot(None, worlds=4, seed=31)._worlds(rnd, rnd.turn)
    assert actual == expected


def test_completion_validation_cannot_be_bypassed(monkeypatch):
    rnd = state()
    bot = PolicyWorldBot(None, worlds=1)
    def reject(*a, **k):
        raise ValueError('conservation witness')
    monkeypatch.setattr(bot.sampler, '_complete_determinized_hands', reject)
    with pytest.raises(ValueError, match='conservation witness'):
        bot._worlds(rnd, rnd.turn)


def test_malformed_sample_fails_real_card_conservation(monkeypatch):
    from shengji.ai.mcbot import DeterminizationContractError
    rnd = state(); seat = rnd.turn
    sampled = {s: list(rnd.hands[s]) for s in range(4) if s != seat}
    hand = sampled[(seat + 1) % 4]
    i = next(i for i, card in enumerate(hand) if card != hand[0])
    hand[i] = hand[0]  # right seat lengths, wrong deck multiset
    bot = PolicyWorldBot(None, worlds=1)
    monkeypatch.setattr(bot.sampler, '_sample_hands',
                        lambda *a: (sampled, list(rnd.buried)))
    with pytest.raises(DeterminizationContractError, match='card conservation'):
        bot._worlds(rnd, seat)


@pytest.mark.parametrize('output',[np.zeros((2,54)), np.full((1,54),np.nan)])
def test_invalid_predictions_refuse(output):
    rnd=state(); bot=PolicyWorldBot(lambda x:output,worlds=1)
    worlds,_=bot._worlds(rnd,rnd.turn)
    with pytest.raises(ValueError,match='finite'):
        bot.scores(rnd,rnd.turn,[(rnd.hands[rnd.turn][0],)],worlds)


def test_world_budget_allows_256():
    assert PolicyWorldBot(None, worlds=256).worlds == 256


def test_batched_scores_accepts_256_world_rows():
    rnd = state(); seat = rnd.turn
    seed_bot = PolicyWorldBot(None, worlds=1, seed=31)
    one_world, _ = seed_bot._worlds(rnd, seat)
    bot = PolicyWorldBot(lambda x: np.ones((len(x), 54)), worlds=256)
    scores = bot.scores(rnd, seat, [(rnd.hands[seat][0],)], one_world * 256)
    assert scores.shape == (256, 1)
    assert np.all(scores == 1)


@pytest.mark.parametrize('worlds',[0,True,257,1.5])
def test_world_budget_is_bounded(worlds):
    with pytest.raises(ValueError): PolicyWorldBot(None,worlds=worlds)
