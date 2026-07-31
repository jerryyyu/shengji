import random

from shengji.ai.env import play_round
from shengji.ai.heuristic import HeuristicBot
from shengji.ai.memory import Memory
from shengji.ai.smart import SmartBot
from shengji.engine.cards import Ordering
from shengji.engine.game import Game
from shengji.engine.round import Round, Trick, TrickPlay


def make_round_with_history():
    rnd = Round("2", 0, random.Random(1))
    while rnd.phase == "deal":
        rnd.deal_next()
    rnd.finalize_declare()  # nobody declared: trump flipped from kitty
    return rnd


def test_void_inference_and_counting():
    rnd = make_round_with_history()
    o = rnd.ordering
    # Fabricate a resolved trick: seat 1 follows with an off-suit card.
    lead_code = next(c for c in rnd.hands[0] if o.eff_suit(c) != "T")
    lead_suit = o.eff_suit(lead_code)
    off = next(c for c in rnd.hands[1] if o.eff_suit(c) != lead_suit)
    t = Trick(leader=0, plays=[
        TrickPlay(0, [lead_code]), TrickPlay(1, [off]),
    ])
    rnd.history.append(t)
    mem = Memory(rnd, 2)
    assert lead_suit in mem.voids[1]
    assert not mem.voids[0]
    assert mem.played[lead_code] >= 1
    # played + own copies are excluded from unseen
    own = rnd.hands[2][0]
    assert mem.unseen[own] <= 2 - rnd.hands[2].count(own)


def test_boss_detection():
    rnd = make_round_with_history()
    mem = Memory(rnd, 0)
    from shengji.engine.cards import BJ
    if BJ in rnd.hands[0]:
        assert mem.is_boss(BJ)
    # after both big jokers are publicly played, little joker becomes boss
    rnd.history.append(Trick(leader=1, plays=[TrickPlay(1, [BJ]), TrickPlay(2, [BJ])]))
    mem = Memory(rnd, 0)
    from shengji.engine.cards import LJ
    if rnd.hands[0].count(LJ) == 2 or (LJ in rnd.hands[0]):
        assert mem.higher_unseen("T", rnd.ordering.level(LJ)) == 0


def test_smartbot_full_games():
    bots = [SmartBot(), HeuristicBot(), SmartBot(), HeuristicBot()]
    for seed in range(3):
        game = Game(random.Random(seed))
        log = play_round(game, bots)
        assert log.attacker_points >= 0
