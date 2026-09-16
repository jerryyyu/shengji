"""Exact input contract for history-free prior admission."""
import random

import numpy as np
import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.train import policy_prior as pp


@pytest.mark.parametrize("seed", [3, 19, 41])
def test_all_seats_opening_follow_lead_and_terminal(seed):
    rnd = Game(random.Random(seed)).start_round()
    bot = HeuristicBot()
    while rnd.phase != "play":
        if rnd.phase == "deal":
            rnd.deal_next()
        elif rnd.phase == "declare":
            rnd.finalize_declare()
        else:
            rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
    while True:
        for seat in range(4):
            expected = pp.flat_input(pp.root_tensors(rnd, seat))
            actual = pp.root_flat_input(rnd, seat)
            assert actual.dtype == expected.dtype
            assert actual.tobytes() == expected.tobytes()
        if rnd.phase == "round_end":
            break
        rnd.play(rnd.turn, bot.decide_play(rnd, rnd.turn))


def test_nonopening_does_not_call_reference_root_builder(monkeypatch):
    from tests.test_policy_prior import _round_in_play
    rnd = _round_in_play(3, plays=5)
    expected = pp.flat_input(pp.root_tensors(rnd, rnd.turn))
    def forbidden(*args, **kwargs):
        raise AssertionError("unused history builder called")
    monkeypatch.setattr(pp, "root_tensors", forbidden)
    np.testing.assert_array_equal(pp.root_flat_input(rnd, rnd.turn), expected)


def test_hidden_hands_and_kitty_swaps():
    from tests.test_policy_prior import _round_in_play
    from shengji.train.cwv_prior_admission import root_clone
    rnd = _round_in_play(41, plays=17)
    seat = rnd.turn
    hands = [list(hand) for hand in rnd.hands]
    buried = list(rnd.buried)
    other = (seat + 1) % 4
    hands[other][0], buried[0] = buried[0], hands[other][0]
    swapped = root_clone(rnd, hands, buried)
    for actor in range(4):
        expected = pp.flat_input(pp.root_tensors(swapped, actor))
        assert pp.root_flat_input(swapped, actor).tobytes() == expected.tobytes()
