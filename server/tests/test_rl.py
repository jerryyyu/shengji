import random

from shengji.ai.smart import SmartBot
from shengji.engine.game import Game
from shengji.engine.legal import validate_follow
from shengji.rl.actions import enumerate_actions
from shengji.rl.encode import ACT_DIM, OBS_DIM, encode_action, encode_obs


def _midround(seed=3):
    game = Game(random.Random(seed))
    rnd = game.start_round()
    while rnd.phase == "deal":
        rnd.deal_next()
    bot = SmartBot()
    for s in range(4):
        c = bot.decide_declare(rnd, s, final=True)
        if c:
            rnd.declare(s, c)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
    for _ in range(6):  # play a trick and a half
        rnd.play(rnd.turn, bot.decide_play(rnd, rnd.turn))
    return rnd


def test_obs_encoding_shape_and_determinism():
    rnd = _midround()
    a = encode_obs(rnd, rnd.turn)
    b = encode_obs(rnd, rnd.turn)
    assert len(a) == OBS_DIM and a == b
    assert all(0.0 <= x <= 1.0 for x in a)


def test_action_enumeration_legal_and_encoded():
    rnd = _midround()
    seat = rnd.turn
    actions = enumerate_actions(rnd, seat)
    assert actions
    lead = rnd.trick.plays[0].cards if rnd.trick.plays else None
    for a in actions:
        assert len(encode_action(a, rnd)) == ACT_DIM
        if lead is not None:
            validate_follow(a, rnd.hands[seat], lead, rnd.ordering)


def test_lead_enumeration_covers_hand():
    rnd = _midround(seed=5)
    # walk to a state where someone is leading
    bot = SmartBot()
    while rnd.phase == "play" and rnd.trick.plays:
        rnd.play(rnd.turn, bot.decide_play(rnd, rnd.turn))
    if rnd.phase != "play":
        return
    seat = rnd.turn
    actions = enumerate_actions(rnd, seat)
    singles = {a[0] for a in actions if len(a) == 1}
    assert singles == set(rnd.hands[seat])  # every single is on the ballot
