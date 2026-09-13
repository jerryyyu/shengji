import copy
import random

import pytest

from shengji.engine.cards import Ordering
from shengji.engine.round import Round, Trick
from shengji.luna.benchmark_observation import observation
from shengji.luna.canonical import canonical_json_bytes


def state():
    rnd = Round("7", 0, random.Random(1))
    rnd.phase = "play"
    rnd.turn = 1
    rnd.trick = Trick(leader=1)
    rnd.ordering = Ordering("H", "7")
    rnd.trump_suit = "H"
    rnd.hands = [["S3", "S4"], ["C9", "C3"], ["D5", "D6"], ["H8", "H9"]]
    rnd.buried = ["S5", "S6"]
    return rnd


@pytest.mark.parametrize("component", ["partner", "opponents", "burial", "deck"])
def test_hidden_twins_have_identical_public_bytes_and_digest(component):
    a = state()
    b = copy.deepcopy(a)
    if component == "partner":
        b.hands[3][0], b.buried[0] = b.buried[0], b.hands[3][0]
    elif component == "opponents":
        b.hands[0][0], b.hands[2][0] = b.hands[2][0], b.hands[0][0]
    elif component == "burial":
        b.buried[0], b.hands[2][0] = b.hands[2][0], b.buried[0]
    else:
        b.deck.reverse()
    assert canonical_json_bytes(observation(a, 1, information="actor-only")) == canonical_json_bytes(observation(b, 1, information="actor-only"))
    if component != "deck":
        assert observation(a, 1, information="perfect") != observation(b, 1, information="perfect")


def test_own_hand_public_points_and_bankers_burial_are_visible():
    a = state()
    base = observation(a, 1, information="actor-only")
    b = copy.deepcopy(a)
    b.hands[1][0], b.hands[2][0] = b.hands[2][0], b.hands[1][0]
    assert observation(b, 1, information="actor-only") != base
    a.attacker_points += 5
    assert observation(a, 1, information="actor-only") != base
    a.turn = 0
    bank = observation(a, 0, information="actor-only")
    assert bank["own_burial"] == sorted(a.buried)
    a.buried[0], a.hands[2][0] = a.hands[2][0], a.buried[0]
    assert observation(a, 0, information="actor-only") != bank


def test_wrong_seat_and_information_mode_refuse():
    with pytest.raises(ValueError, match="acting play seat"):
        observation(state(), 0, information="actor-only")
    with pytest.raises(ValueError, match="information mode"):
        observation(state(), 1, information="public-ish")
