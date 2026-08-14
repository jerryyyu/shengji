"""PointContext + point-flow attribution: exactness, purity, determinism.

Covers the item-1+2 contract of docs/proposals/point-management-census.md:
(a) context fields match independently hand-computed values, (b)
``effective_boss`` agrees with Memory ground truth, (c) building a context
never mutates the round, (d) bracket distances at the 39/40/79/80
boundaries, (e) point-flow classification on constructed tricks with known
nonzero feed/contest/discard content, (f) byte-level determinism via
canonical JSON, (g) negative controls proving each guard can actually fail.
"""

import copy
import json
import random

import pytest

from shengji.ai.memory import Memory
from shengji.ai.point_context import (
    BRACKETS,
    EFF_SUITS,
    POINT_CONTEXT_SCHEMA,
    build_point_context,
)
from shengji.ai.point_flow import (
    POINT_FLOW_COUNTER_FIELDS,
    POINT_FLOW_SCHEMA,
    PointFlowAccumulator,
    classify_trick_point_flow,
    empty_point_flow_telemetry,
    round_flow,
)
from shengji.ai.registry import make_bot
from shengji.engine.cards import BJ, Ordering, make_deck, total_points
from shengji.engine.game import Game
from shengji.engine.round import Round, Trick, TrickPlay

# --------------------------------------------------------------------- rounds


def _engine_round(seed, plays=0):
    """Engine-generated round via smart self-play (the _played_round
    pattern), stopped after ``plays`` seat-actions into the play phase."""
    game = Game(random.Random(seed))
    actors = [make_bot("smart") for _ in range(4)]
    rnd = game.start_round()
    while rnd.phase == "deal":
        s, _, _ = rnd.deal_next()
        c = actors[s].decide_declare(rnd, s)
        if c:
            rnd.declare(s, c)
    for s in range(4):
        c = actors[s].decide_declare(rnd, s, final=True)
        if c:
            rnd.declare(s, c)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, list(actors[rnd.banker].decide_bury(rnd, rnd.banker)))
    for _ in range(plays):
        s = rnd.turn
        rnd.play(s, actors[s].decide_play(rnd, s))
    return rnd, actors


def _finished_round(seed):
    rnd, actors = _engine_round(seed)
    while rnd.phase == "play":
        s = rnd.turn
        rnd.play(s, actors[s].decide_play(rnd, s))
    assert rnd.phase == "round_end"
    return rnd


def _constructed_round(seat0_hand, *, trump_suit="S", trump_rank="2",
                       banker=0, history=(), attacker_points=0, buried=()):
    """Hand-built play-phase round (the test_memory pattern): only the
    fields Memory/PointContext read need to be truthful."""
    rnd = Round(trump_rank, banker, random.Random(0))
    rnd.phase = "play"
    rnd.ordering = Ordering(trump_suit, trump_rank)
    rnd.trump_suit = trump_suit
    rnd.hands = [list(seat0_hand), [], [], []]
    rnd.history = list(history)
    rnd.buried = list(buried)
    rnd.trick = Trick(leader=0)
    rnd.turn = 0
    rnd.attacker_points = attacker_points
    return rnd


def _flow_round(hands, leader, buried):
    """Single-trick round played through the REAL engine so winner/points
    are engine-computed, not hand-asserted. banker=0 -> attackers 1,3."""
    rnd = Round("2", 0, random.Random(1))
    rnd.phase = "play"
    rnd.ordering = Ordering("H", "2")
    rnd.trump_suit = "H"
    rnd.hands = [list(h) for h in hands]
    rnd.buried = list(buried)
    rnd.trick = Trick(leader=leader)
    rnd.turn = leader
    for _ in range(4):
        s = rnd.turn
        rnd.play(s, list(rnd.hands[s]))
    assert rnd.phase == "round_end" and len(rnd.history) == 1
    return rnd


# ------------------------------------------------------- full state snapshot


def _trick_state(t):
    if t is None:
        return None
    return (t.leader, [(p.seat, list(p.cards)) for p in t.plays],
            t.winner, t.points, copy.deepcopy(t.incumbent),
            copy.deepcopy(t.running_points))


def _full_state(rnd):
    """Every attribute of the round, caches included (Trick.__eq__ excludes
    incumbent/running_points, so a naive == would miss cache mutation)."""
    out = {}
    for k, v in vars(rnd).items():
        if isinstance(v, Ordering):
            out[k] = ("Ordering", v.trump_suit, v.trump_rank)
        elif isinstance(v, Trick):
            out[k] = _trick_state(v)
        elif k == "history":
            out[k] = [_trick_state(t) for t in v]
        elif isinstance(v, set):
            out[k] = sorted(v)
        else:
            out[k] = copy.deepcopy(v)
    return out


# ------------------------------------------------------------- (a) exactness


def test_context_fields_match_hand_computed_engine_states():
    assert total_points(make_deck()) == 200  # premise of the hand count
    for seed, plays in ((11, 6), (12, 13), (13, 26)):
        rnd, _ = _engine_round(seed, plays=plays)
        for seat in (rnd.turn, (rnd.turn + 1) % 4):
            ctx = build_point_context(rnd, seat)
            open_cards = [c for tp in rnd.trick.plays for c in tp.cards]
            seen = [c for t in rnd.history for tp in t.plays
                    for c in tp.cards] + open_cards
            expected_left = (200 - total_points(seen)
                             - total_points(rnd.hands[seat]))
            if seat == rnd.banker:
                expected_left -= total_points(rnd.buried)
            assert ctx.schema == POINT_CONTEXT_SCHEMA
            assert ctx.seat == seat
            assert ctx.points_left_total == expected_left
            assert ctx.trick_points == total_points(open_cards)
            assert ctx.attacker_points == rnd.attacker_points
            assert set(ctx.points_left_by_suit) == set(EFF_SUITS)
            assert (sum(ctx.points_left_by_suit.values())
                    == ctx.points_left_total)
            if rnd.trump_suit is not None:
                # the trump suit's letter never occurs as an effective suit
                assert ctx.points_left_by_suit[rnd.trump_suit] == 0


def test_points_left_by_suit_constructed_exact():
    # Trump S/rank 2. Seat 0 holds HK+H10 (20 pts); one resolved trick
    # showed H5,H5,HK (20 pts). Hearts hold 50 deck points -> 10 left (the
    # other H10). Spades all live under "T"; other suits untouched.
    hist = Trick(leader=1, plays=[
        TrickPlay(1, ["H5"]), TrickPlay(2, ["H5"]),
        TrickPlay(3, ["HK"]), TrickPlay(0, ["H3"])], winner=3, points=20)
    rnd = _constructed_round(["HK", "H10"], history=[hist])
    ctx = build_point_context(rnd, 0)
    assert dict(ctx.points_left_by_suit) == {
        "C": 50, "D": 50, "H": 10, "S": 0, "T": 50}
    assert ctx.points_left_total == 160
    assert ctx.trick_points == 0  # open trick is empty


def test_build_requires_ordering_and_valid_seat():
    rnd = Round("2", 0, random.Random(2))
    with pytest.raises(ValueError):
        build_point_context(rnd, 0)  # still in deal: no ordering yet
    ready = _constructed_round(["HA"])
    with pytest.raises(ValueError):
        build_point_context(ready, 4)


# -------------------------------------------------------- (b) effective_boss


def test_effective_boss_agrees_with_memory_ground_truth():
    for seed in (21, 22, 23):
        rnd, _ = _engine_round(seed, plays=9)
        seat = rnd.turn
        ctx = build_point_context(rnd, seat)
        mem = Memory(rnd, seat)  # independent instance, same public info
        seats = [s for s in range(4) if s != seat]
        for code in sorted(set(rnd.hands[seat])):
            eff = rnd.ordering.eff_suit(code)
            single = mem.is_boss(code) and not mem.ruff_risk(eff, seats)
            assert ctx.effective_boss([code], seats) == single
            if rnd.hands[seat].count(code) == 2:
                pair = (mem.pair_is_boss(code)
                        and not mem.ruff_risk(eff, seats))
                assert ctx.effective_boss([code, code], seats) == pair


def test_effective_boss_constructed_truths():
    # The A+KK shape: holding HA,HK,HK makes the K-pair counted boss (only
    # one HA remains unseen, so no HA pair can exist) while the single K is
    # not. No voids and 20 unseen hearts -> no ruff risk.
    rnd = _constructed_round(["HA", "HK", "HK", "H3"])
    ctx = build_point_context(rnd, 0)
    others = [1, 2, 3]
    assert ctx.effective_boss(["HA"], others) is True
    assert ctx.effective_boss(["HK"], others) is False
    assert ctx.effective_boss(["HK", "HK"], others) is True
    assert ctx.effective_boss([BJ], others) is True  # ties lose to us
    # complex shapes: conservative False even when provably unbeatable
    assert ctx.effective_boss(["HA", "HK"], others) is False
    assert ctx.effective_boss(["HA", "HA", "HK", "HK"], others) is False
    with pytest.raises(ValueError):
        ctx.effective_boss([], others)
    with pytest.raises(ValueError):
        ctx.effective_boss(["HA"], [4])


def test_effective_boss_ruff_risk_veto_respects_seats_to_act():
    # Seat 1 proved void in hearts (off-suit follow on a heart lead) while
    # trumps are unseen: HA is effectively boss only when seat 1 no longer
    # acts. The explicit seats_to_act list is the veto's scope.
    hist = Trick(leader=0, plays=[
        TrickPlay(0, ["H4"]), TrickPlay(1, ["C4"]),
        TrickPlay(2, ["H6"]), TrickPlay(3, ["H7"])], winner=0, points=0)
    rnd = _constructed_round(["HA", "HA"], history=[hist])
    ctx = build_point_context(rnd, 0)
    assert ctx.effective_boss(["HA"], [1]) is False
    assert ctx.effective_boss(["HA", "HA"], [1]) is False
    assert ctx.effective_boss(["HA"], [2, 3]) is True
    assert ctx.effective_boss(["HA"], []) is True  # nobody left to ruff


# ------------------------------------------------------------ (c) no writes


def test_build_point_context_never_mutates_round():
    for seed, plays in ((31, 0), (32, 7), (33, 14)):
        rnd, _ = _engine_round(seed, plays=plays)
        before = _full_state(rnd)
        for seat in range(4):
            ctx = build_point_context(rnd, seat)
            ctx.effective_boss(list(rnd.hands[seat][:1]) or ["C3"],
                               [s for s in range(4) if s != seat])
            ctx.canonical_json()
        assert _full_state(rnd) == before
    rnd = _finished_round(34)  # round_end: trick is None, kitty resolved
    before = _full_state(rnd)
    build_point_context(rnd, 0).canonical_json()
    assert _full_state(rnd) == before


def test_context_boundary_is_immutable():
    rnd, _ = _engine_round(35, plays=5)
    ctx = build_point_context(rnd, rnd.turn)
    with pytest.raises(AttributeError):  # FrozenInstanceError
        ctx.trick_points = 99
    with pytest.raises(TypeError):  # mappingproxy rejects writes
        ctx.points_left_by_suit["H"] = 0


# ------------------------------------------------------------- (d) brackets


def test_bracket_distance_boundaries():
    assert BRACKETS == (40, 80, 120)
    cases = {
        0: (40, 80, 120),
        39: (1, 41, 81),
        40: (0, 40, 80),
        79: (0, 1, 41),
        80: (0, 0, 40),
        119: (0, 0, 1),
        120: (0, 0, 0),
        195: (0, 0, 0),
    }
    for pts, expected in cases.items():
        rnd = _constructed_round(["HA"], attacker_points=pts)
        assert build_point_context(rnd, 0).bracket_distance == expected, pts


# ----------------------------------------------------------- (e) point flow


def test_point_flow_feed_and_discard_with_kitty_transfer():
    # banker 0 -> attackers 1,3. Seat 1 wins its own SA lead; partner 3
    # feeds 5, defender 2 discards 10, defender 0 adds nothing. Attackers
    # take the last (only) trick -> buried SK transfers x2.
    rnd = _flow_round(hands=[["S3"], ["SA"], ["S10"], ["S5"]],
                      leader=1, buried=["SK"])
    flow = classify_trick_point_flow(rnd.history[0], rnd.ordering, 0)
    assert flow.winner == 1 and flow.winner_is_attacker is True
    assert flow.trick_points == 15
    assert flow.winner_teammate_points == 5
    assert flow.losing_team_points == 10
    assert flow.winner_own_points == 0
    tele = round_flow(rnd)
    assert rnd.kitty_bonus == 20 and rnd.attacker_points == 35
    assert tele["kitty_points"] == 20
    assert tele["attacker_captured"] == 15 and tele["defender_captured"] == 0
    assert tele["attacker_teammate_points"] == 5 and tele["defender_teammate_points"] == 0


def test_point_flow_winner_own_points_ride_the_winning_play():
    # Winner seat 3 takes the trick WITH its own SK: 10 contested points.
    rnd = _flow_round(hands=[["S10"], ["S5"], ["S4"], ["SK"]],
                      leader=2, buried=["C3"])
    flow = classify_trick_point_flow(rnd.history[0], rnd.ordering, 0)
    assert flow.winner == 3 and flow.winner_is_attacker is True
    assert flow.trick_points == 25
    assert flow.winner_own_points == 10  # the SK itself
    assert flow.winner_teammate_points == 5         # partner seat 1's S5
    assert flow.losing_team_points == 10  # defender seat 0's S10


def test_point_flow_defended_kitty_never_transfers():
    # Banker's own SA holds the last trick: attacker points stay 0 and the
    # buried SK does NOT transfer.
    rnd = _flow_round(hands=[["SA"], ["S5"], ["S10"], ["S3"]],
                      leader=0, buried=["SK"])
    assert rnd.kitty_bonus == 0 and rnd.attacker_points == 0
    tele = round_flow(rnd)
    assert tele["kitty_points"] == 0
    assert tele["defender_captured"] == 15 and tele["defender_teammate_points"] == 10
    assert tele["losing_team_points"] == 5  # attacker seat 1's S5


def test_point_flow_full_rounds_reconcile_with_engine():
    for seed in (41, 42, 43):
        rnd = _finished_round(seed)
        tele = round_flow(rnd)
        assert tele["schema"] == POINT_FLOW_SCHEMA
        assert tele["deterministic"] is True
        assert tele["tricks"] == len(rnd.history)
        # every non-buried point lands in exactly one trick
        assert tele["trick_points"] == 200 - total_points(rnd.buried)
        assert (tele["winner_teammate_points"] + tele["winner_own_points"]
                + tele["losing_team_points"] == tele["trick_points"])
        assert (tele["attacker_captured"] + tele["kitty_points"]
                == rnd.attacker_points)
    # partial rounds reconcile too (open trick excluded, no kitty yet)
    rnd, _ = _engine_round(44, plays=10)
    tele = round_flow(rnd)
    assert tele["attacker_captured"] == rnd.attacker_points
    assert tele["kitty_points"] == 0


def test_empty_telemetry_schema_population():
    zero = empty_point_flow_telemetry()
    assert zero["schema"] == POINT_FLOW_SCHEMA
    assert zero["deterministic"] is True
    assert {k for k in zero if k not in ("schema", "deterministic")} \
        == set(POINT_FLOW_COUNTER_FIELDS)
    assert all(zero[name] == 0 for name in POINT_FLOW_COUNTER_FIELDS)


# ---------------------------------------------------------- (f) determinism


def test_context_determinism_byte_equal_canonical_json():
    rnd, _ = _engine_round(51, plays=9)
    seat = rnd.turn
    a = build_point_context(rnd, seat).canonical_json()
    b = build_point_context(rnd, seat).canonical_json()
    assert a.encode() == b.encode()
    # an independent deepcopy of the round builds the same bytes
    c = build_point_context(copy.deepcopy(rnd), seat).canonical_json()
    assert a.encode() == c.encode()
    assert json.loads(a)["schema"] == POINT_CONTEXT_SCHEMA


def test_point_flow_determinism_byte_equal():
    # same seed, two fully independent engine replays -> identical bytes
    j1 = json.dumps(round_flow(_finished_round(52)), sort_keys=True)
    j2 = json.dumps(round_flow(_finished_round(52)), sort_keys=True)
    assert j1.encode() == j2.encode()


# ----------------------------------------------- (g) the guards can fail


def test_point_flow_validation_can_fail():
    acc = PointFlowAccumulator()
    acc.accumulate_round(_finished_round(61))
    acc._totals["winner_teammate_points"] += 1  # break the partition on purpose
    with pytest.raises(AssertionError):
        acc.telemetry()


def test_classifier_refuses_corrupted_or_unresolved_tricks():
    rnd = _flow_round(hands=[["S3"], ["SA"], ["S10"], ["S5"]],
                      leader=1, buried=["SK"])
    trick = rnd.history[0]
    trick.points += 5  # corrupt the engine tally
    with pytest.raises(AssertionError):
        classify_trick_point_flow(trick, rnd.ordering, 0)
    trick.points -= 5
    with pytest.raises(ValueError):
        classify_trick_point_flow(Trick(leader=0), rnd.ordering, 0)
    with pytest.raises(ValueError):
        classify_trick_point_flow(trick, rnd.ordering, 7)


def test_round_reconciliation_can_fail():
    rnd = _finished_round(62)
    rnd.attacker_points += 5  # engine tally and attribution now disagree
    with pytest.raises(AssertionError):
        round_flow(rnd)


def test_wrong_banker_flips_attribution():
    # The classification demonstrably depends on the banker: flipping it
    # moves the same captured points to the other team's counters.
    rnd = _flow_round(hands=[["S3"], ["SA"], ["S10"], ["S5"]],
                      leader=1, buried=["SK"])
    f0 = classify_trick_point_flow(rnd.history[0], rnd.ordering, 0)
    f1 = classify_trick_point_flow(rnd.history[0], rnd.ordering, 1)
    assert f0.winner_is_attacker != f1.winner_is_attacker
    assert f0.trick_points == f1.trick_points == 15  # partition unchanged


# ------------------------------------------------- HOLD-repair regressions

def test_refused_round_leaves_accumulator_untouched():
    from shengji.ai.point_flow import PointFlowAccumulator
    rnd = _finished_round(31)
    acc = PointFlowAccumulator()
    acc.accumulate_round(rnd)
    before = dict(acc.telemetry())
    rnd.attacker_points += 5  # force the documented reconciliation refusal
    with pytest.raises(AssertionError):
        acc.accumulate_round(rnd)
    assert dict(acc.telemetry()) == before, "refusal mutated the accumulator"


def test_context_is_immune_to_source_mutation():
    from shengji.ai.memory import Memory
    rnd = _finished_round(32)
    probe_rnd = _finished_round(32)
    seat = 0
    ctx = build_point_context(rnd, seat)
    cards = sorted(set(probe_rnd.deck))
    answers_before = [ctx.effective_boss([c], [1, 3]) for c in cards[:20]]
    # mutate everything a shared consumer could reach on the SOURCE objects
    rnd.hands = [[], [], [], []]
    rnd.history.clear()
    rnd.attacker_points = 0
    answers_after = [ctx.effective_boss([c], [1, 3]) for c in cards[:20]]
    assert answers_before == answers_after
    with pytest.raises((AttributeError, TypeError)):
        ctx.boss_table["SA"] = True  # mappingproxy: no mutation surface


def test_malformed_tricks_are_rejected():
    from shengji.ai.point_flow import classify_trick_point_flow
    rnd = _finished_round(33)
    o, banker = rnd.ordering, rnd.banker
    good = rnd.history[0]
    # duplicate seats
    bad = Trick(leader=0, plays=[TrickPlay(0, ["S5"]), TrickPlay(0, ["S6"]),
                                 TrickPlay(2, ["S7"]), TrickPlay(3, ["S8"])])
    bad.winner, bad.points = 0, 5
    with pytest.raises(ValueError):
        classify_trick_point_flow(bad, o, banker)
    # out-of-range winner
    bad2 = Trick(leader=0, plays=[TrickPlay(s, [c]) for s, c in
                                  ((0, "S5"), (1, "S6"), (2, "S7"), (3, "S8"))])
    bad2.winner, bad2.points = 7, 5
    with pytest.raises(ValueError):
        classify_trick_point_flow(bad2, o, banker)
    # bool banker / bool winner
    with pytest.raises(ValueError):
        classify_trick_point_flow(good, o, True)
    bad3 = Trick(leader=good.leader,
                 plays=[TrickPlay(tp.seat, list(tp.cards))
                        for tp in good.plays])
    bad3.winner, bad3.points = True, good.points
    with pytest.raises(ValueError):
        classify_trick_point_flow(bad3, o, banker)


def test_bool_seat_is_rejected_by_build():
    rnd = _finished_round(34)
    with pytest.raises(ValueError):
        build_point_context(rnd, False)
