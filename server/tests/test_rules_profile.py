"""The ``shengjiorg`` rules profile: kitty bonus by the lead's largest component,
an undeclared round played as NT, and the unchanged declare legality, on the
pure and the compiled engine.  Off (the default) installs nothing."""
import random

import pytest

from shengji.ai import endgame_compact
from shengji.engine import rules_profile as rp
from shengji.engine.cards import Ordering, make_deck, total_points
from shengji.engine.legal import IllegalPlay
from shengji.engine.round import Round, Trick
from shengji.train import value_declare

BURIED = ["D10", "DK", "C5", "C3", "C4", "C6", "C7", "C8"]  # 25 points


@pytest.fixture
def sjorg():
    rp.install(rp.SHENGJIORG)
    try:
        yield
    finally:
        rp.uninstall()


def last_trick_round(leader_hand, leader=1, banker=0):
    """A round at its last trick: ``leader`` (an attacker by default) holds
    ``leader_hand``; the others hold low clubs and diamonds, void in spades."""
    n = len(leader_hand)
    filler = [["C9", "CJ", "CQ", "CA"], ["D3", "D4", "D6", "D7"], ["D8", "D9", "DJ", "DQ"]]
    rnd = Round("2", banker, random.Random(0))
    rnd.hands = [[] for _ in range(4)]
    others = [s for s in range(4) if s != leader]
    rnd.hands[leader] = list(leader_hand)
    for seat, cards in zip(others, filler):
        rnd.hands[seat] = cards[:n]
    rnd.trump_suit, rnd.trump_is_nt = "H", False
    rnd.ordering = Ordering("H", "2")
    rnd.buried = list(BURIED)
    rnd.phase = "play"
    rnd.trick = Trick(leader=leader)
    rnd.turn = leader
    return rnd


def play_out(rnd, lead):
    rnd.play(rnd.turn, list(lead))
    while rnd.phase == "play" and rnd.trick is not None and rnd.trick.plays:
        seat = rnd.turn
        need = len(rnd.trick.plays[0].cards)
        rnd.play(seat, rnd.hands[seat][:need])
    return rnd


def test_off_is_the_default_and_installs_nothing():
    play, finalize = Round.play, Round.finalize_declare
    assert rp.requested({}) == rp.DEFAULT and rp.active() == rp.DEFAULT
    rp.install(rp.DEFAULT)
    assert Round.play is play and Round.finalize_declare is finalize
    rp.install(rp.SHENGJIORG)
    assert Round.play is not play
    rp.uninstall()
    assert Round.play is play and Round.finalize_declare is finalize
    assert rp.active() == rp.DEFAULT


def test_an_unknown_profile_is_refused():
    with pytest.raises(ValueError):
        rp.requested({rp.ENV: "rbtying"})
    with pytest.raises(ValueError):
        rp.install("rbtying")


@pytest.mark.parametrize("lead,ours,theirs", [
    (["SA"], 2, 2), (["SA", "SA"], 4, 4), (["S7", "S9"], 4, 2),
    (["SK", "SJ", "S9", "S8"], 8, 2), (["CQ", "C10", "C5", "C5"], 8, 4),
    (["S7", "S7", "S8", "S8"], 8, 8)])
def test_kitty_multiplier_by_largest_component(lead, ours, theirs):
    ordering = Ordering("H", "2")
    assert rp.kitty_multiplier(lead, ordering, rp.DEFAULT) == ours
    assert rp.kitty_multiplier(lead, ordering, rp.SHENGJIORG) == theirs


@pytest.mark.parametrize("profile,bonus", [(rp.DEFAULT, 25 * 4), (rp.SHENGJIORG, 25 * 2)])
def test_a_singles_throw_on_the_last_trick_scores_the_profile_bonus(profile, bonus):
    rp.install(profile)
    try:
        rnd = play_out(last_trick_round(["S7", "S9"]), ["S7", "S9"])
    finally:
        rp.uninstall()
    assert rnd.phase == "round_end" and rnd.last_trick_winner == 1
    assert rnd.kitty_bonus == bonus
    assert rnd.attacker_points == bonus + total_points(
        c for tp in rnd.last_trick.plays for c in tp.cards)


def test_a_pair_on_the_last_trick_scores_alike(sjorg):
    rnd = play_out(last_trick_round(["SA", "SA"]), ["SA", "SA"])
    assert rnd.kitty_bonus == 25 * 4


def test_no_bonus_when_the_banker_takes_the_last_trick(sjorg):
    rnd = play_out(last_trick_round(["S7", "S9"], leader=0), ["S7", "S9"])
    assert rnd.kitty_bonus == 0 and rnd.attacker_points == 0


def test_rescoring_is_idempotent(sjorg):
    rnd = play_out(last_trick_round(["S7", "S9"]), ["S7", "S9"])
    before = (rnd.kitty_bonus, rnd.attacker_points)
    rp._rescore_kitty(rnd)
    assert (rnd.kitty_bonus, rnd.attacker_points) == before == (50, 50)


def dealt(banker, seed=3):
    rnd = Round("5", banker, random.Random(seed))
    while rnd.phase == "deal":
        rnd.deal_next()
    return rnd


@pytest.mark.parametrize("banker", [2, None])
def test_no_declaration_is_nt_under_the_profile(sjorg, banker):
    rnd = dealt(banker)
    kitty = list(rnd.kitty)
    rnd.finalize_declare()
    expected = 0 if banker is None else banker
    assert (rnd.trump_is_nt, rnd.trump_suit, rnd.banker) == (True, None, expected)
    assert rnd.ordering.trump_suit is None and rnd.ordering.trump_rank == "5"
    assert rnd.phase == "bury" and rnd.turn == expected
    assert len(rnd.hands[expected]) == 33 and rnd.hands[expected][-8:] == kitty


def test_no_declaration_flips_the_kitty_by_default():
    rnd = dealt(2)
    flipped = next(c for c in rnd.kitty if c not in ("LJ", "BJ"))
    rnd.finalize_declare()
    assert rnd.trump_suit == flipped[0] and not rnd.trump_is_nt


def test_a_declaration_sets_trump_as_ours_under_the_profile(sjorg):
    rnd = dealt(2)
    for seat in range(4):
        options = rnd.declare_options(seat)
        if options and options[0][0] not in ("LJ", "BJ"):
            rnd.declare(seat, options[0])
            break
    else:
        pytest.skip("no suit declaration in this deal")
    rnd.finalize_declare()
    assert rnd.trump_suit == options[0][0][0] and rnd.banker == 2


def test_an_equal_declaration_cannot_overcall(sjorg):
    rnd = Round("5", 1, random.Random(0))
    rnd.phase = "declare"
    rnd.hands = [["H5", "H5", "C3"], ["S5", "S5", "LJ"], ["D5", "LJ", "LJ"], ["C5", "BJ", "BJ"]]
    rnd.declare(0, ["H5"])
    assert ["S5"] not in rnd.declare_options(1)
    assert ["S5", "S5"] in rnd.declare_options(1)
    with pytest.raises(IllegalPlay):
        rnd.declare(2, ["D5"])
    rnd.declare(1, ["S5", "S5"])
    assert ["H5", "H5"] not in rnd.declare_options(0)
    with pytest.raises(IllegalPlay):
        rnd.declare(0, ["H5", "H5"])
    rnd.declare(2, ["LJ", "LJ"])
    assert rnd.declare_options(2) == []
    rnd.declare(3, ["BJ", "BJ"])
    assert rnd.declare_options(0) == []


def test_pass_without_a_declaration_is_the_nt_outcome(sjorg):
    rnd = dealt(2)
    rnd.hands[0] = [c for c in rnd.hands[0] if c not in ("LJ", "BJ")][:23] + ["BJ", "BJ"]
    assert value_declare.outcome_key(rnd, 0, None) == (2, "NT")
    assert value_declare.outcome_key(rnd, 0, ["BJ", "BJ"]) == (2, "NT")
    outcomes = value_declare.candidate_outcomes(rnd, 0, [["BJ", "BJ"]], None)
    assert [key for key, _ in outcomes] == [(2, "NT")]


def test_pass_without_a_declaration_flips_by_default():
    rnd = dealt(2)
    assert value_declare.outcome_key(rnd, 0, None) == (2, "flip")


def test_the_declare_world_is_played_as_nt(sjorg):
    rnd = dealt(2)
    hands, kitty = value_declare.sample_declare_world(rnd, 0, random.Random(5))
    world = value_declare.declare_outcome_position(rnd, 0, hands, kitty, None)
    assert world.trump_is_nt and world.trump_suit is None and world.banker == 2
    assert world.phase == "play" and len(world.history) == 1
    assert sorted(world.deck) == sorted(make_deck())


@pytest.mark.parametrize("profile,points", [(rp.DEFAULT, 25 * 4), (rp.SHENGJIORG, 25 * 2)])
def test_the_compact_exact_solver_scores_the_profile(profile, points):
    """The attacker's best is the throw (x4) under ours; under the profile the
    throw and two singles both end on a single-component lead (x2)."""
    rp.install(profile)
    try:
        rnd = last_trick_round(["S7", "S9"])
        session = endgame_compact.CompactWorldSession(rnd)
        assert session.solve(rnd).attacker_points == points
        if profile:
            assert session.backend == "python"
    finally:
        rp.uninstall()


def test_the_compact_solver_keeps_its_backend_without_kitty_points(sjorg):
    rnd = last_trick_round(["S7", "S9"])
    rnd.buried = ["C3", "C4", "C6", "C7", "C8", "D3", "D4", "D6"]
    session = endgame_compact.CompactWorldSession(rnd)
    session.solve(rnd)
    assert session.backend == endgame_compact.default_backend()
