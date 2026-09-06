"""Decision-parity witnesses for prepared lead validation."""
from __future__ import annotations

import copy
import random

import pytest

from shengji.ai import cwv_policy
from shengji.ai.cwv_successor_reuse import WorldSuccessorCache
from shengji.engine.cards import LJ, Ordering, RANKS
from shengji.engine.legal import (IllegalPlay, PreparedLeadValidation,
                                  validate_lead)
from shengji.engine.round import Round, Trick


def _same_result(fn, *args):
    try:
        return "ok", fn(*args)
    except Exception as exc:  # parity includes refusal type and text
        return type(exc), str(exc)


@pytest.mark.parametrize("trump_suit,trump_rank", [("H", "7"), (None, "A")])
def test_prepared_lead_matches_oracle_and_reuses_component_facts(
        trump_suit, trump_rank):
    ordering = Ordering(trump_suit, trump_rank)
    hand = ["S2", "S3", "S4", "S5", "S5", "S6", "S7", "S7", "H2"]
    others = [["S8", "S8", "S9", "S10"], ["S2", "S2"], ["S3"]]
    prepared = PreparedLeadValidation(hand, others, ordering)
    plays = [
        ["S2"],
        ["S5", "S5"],
        ["S2", "S3", "S4", "S5", "S5", "S6"],
        ["S5", "S5", "S7", "S7"],
        ["S2", "S3", "S4", "S5", "S5", "S6", "S7", "S7"],
        ["S2", "H2"],
        ["S9"],
    ]
    for play in plays:
        expected = _same_result(validate_lead, play, hand, others, ordering)
        actual = _same_result(prepared.validate, play, hand, others, ordering)
        assert actual == expected
    # The multi-component calls above share suit/pair-length facts.
    assert prepared.calls == len(plays)
    assert prepared.hits > 0
    assert prepared.misses > 0
    assert len(prepared._max_top) <= prepared._MAX_FACTS


@pytest.mark.parametrize("play,others", [
    # A tractor is beaten only by a higher tractor, not by a higher pair.
    (["S2", "S2", "S3", "S3", "S5", "S5"],
     [["S4", "S4", "S5", "S5"], [], []]),
    # Equal-level trump-rank pairs exercise stable component order when both
    # components are beatable by the same higher trump pair.
    (["S7", "S7", "C7", "C7"], [[LJ, LJ], [], []]),
])
def test_prepared_tractor_and_lowest_tied_penalty_match(play, others):
    ordering = Ordering("H", "7")
    hand = list(play)
    prepared = PreparedLeadValidation(hand, others, ordering)
    expected = _same_result(validate_lead, play, hand, others, ordering)
    assert expected[0] == "ok" and expected[1][1].startswith("Throw failed")
    assert expected == _same_result(prepared.validate, play, hand, others, ordering)
    # Repeating the same multi-component action must consume prepared facts,
    # while preserving the decomposition's stable component tie order.
    prepared.validate(play, hand, others, ordering)
    assert prepared.hits > 0


@pytest.mark.parametrize("suit,rank,hand,others,play,accepted", [
    # NT rank pairs tie: a different suit at the same level does not beat.
    (None, "7", ["S7", "S7", "C7", "C7"],
     [["D7", "D7"], [], []], ["S7", "S7", "C7", "C7"],
     ["S7", "S7", "C7", "C7"]),
    # Do not choose an unbeatable single merely because singles sort first.
    ("H", "7", ["S2", "S2", "SA"],
     [["S4", "S4"], [], []], ["S2", "S2", "SA"], ["S2", "S2"]),
    # A single tractor always stands even against a stronger tractor.
    ("H", "7", ["S2", "S2", "S3", "S3"],
     [["S4", "S4", "S5", "S5"], [], []],
     ["S2", "S2", "S3", "S3"], ["S2", "S2", "S3", "S3"]),
])
def test_explicit_accepted_components(suit, rank, hand, others, play, accepted):
    ordering = Ordering(suit, rank)
    context = PreparedLeadValidation(hand, others, ordering)
    expected = validate_lead(play, hand, others, ordering)
    assert expected[0] == accepted
    assert context.validate(play, hand, others, ordering) == expected


@pytest.mark.parametrize("play", [[], ["S2", "S2"], ["SA"]])
def test_invalid_multiset_refusals_are_exact(play):
    ordering = Ordering("H", "7")
    hand, others = ["S2", "S3"], [[], [], []]
    context = PreparedLeadValidation(hand, others, ordering)
    expected = (IllegalPlay, "You don't hold those cards.")
    assert _same_result(validate_lead, play, hand, others, ordering) == expected
    assert _same_result(context.validate, play, hand, others, ordering) == expected


def test_changed_opponent_world_falls_back_before_using_stale_facts():
    ordering = Ordering("H", "7")
    hand = ["S2", "S3", "S5", "S5"]
    original_others = [[], [], []]
    changed_others = [["SA"], [], []]
    play = list(hand)
    prepared = PreparedLeadValidation(hand, original_others, ordering)
    assert prepared.validate(play, hand, original_others, ordering) == \
        validate_lead(play, hand, original_others, ordering)
    expected = _same_result(validate_lead, play, hand, changed_others, ordering)
    actual = _same_result(prepared.validate, play, hand, changed_others, ordering)
    assert actual == expected
    assert prepared.fallbacks == 1


def test_seeded_rank_and_trump_modes_preserve_all_small_lead_results():
    rng = random.Random(20260906)
    for no_trump in (False, True):
        for trump_rank in RANKS:
            ranks = [rank for rank in RANKS if rank != trump_rank]
            rng.shuffle(ranks)
            chosen = ranks[:4]
            code = lambda rank: "S" + rank
            hand = [code(chosen[0]), code(chosen[1]),
                    code(chosen[2]), code(chosen[2])]
            others = [[code(chosen[3]), code(chosen[3])], [], []]
            ordering = Ordering(None if no_trump else "H", trump_rank)
            prepared = PreparedLeadValidation(hand, others, ordering)
            expected = _same_result(validate_lead, hand, hand, others, ordering)
            actual = _same_result(prepared.validate, hand, hand, others, ordering)
            assert actual == expected, (no_trump, trump_rank, hand)


def test_prepared_context_falls_back_on_world_or_ordering_drift():
    ordering = Ordering("H", "7")
    hand = ["S2", "S3", "S4", "S5", "S5"]
    others = [["S8", "S8"], ["S9"], []]
    prepared = PreparedLeadValidation(hand, others, ordering)
    changed_hand = hand + ["S6"]
    assert prepared.validate(["S6"], changed_hand, others, ordering) == \
        validate_lead(["S6"], changed_hand, others, ordering)
    other_ordering = Ordering("H", "7")
    assert prepared.validate(["S2"], hand, others, other_ordering) == \
        validate_lead(["S2"], hand, others, other_ordering)
    assert prepared.fallbacks == 2


def _lead_round():
    rnd = Round("7", 0)
    rnd.phase = "play"
    rnd.turn = 0
    rnd.ordering = Ordering("H", "7")
    rnd.hands = [["S2", "S3", "S4", "S5", "S5"],
                 ["S8", "S8"], ["S9"], ["S10"]]
    rnd.trick = Trick(leader=0)
    return rnd


def _state_signature(rnd):
    def trick_signature(trick):
        if trick is None:
            return None
        return (trick.leader,
                tuple((p.seat, tuple(p.cards)) for p in trick.plays),
                trick.winner, trick.points, trick.incumbent,
                trick.running_points)
    return (rnd.phase, rnd.turn,
            tuple(tuple(hand) for hand in rnd.hands), tuple(rnd.buried),
            rnd.message, rnd.attacker_points, rnd.kitty_bonus,
            tuple(trick_signature(trick) for trick in rnd.history),
            trick_signature(rnd.trick), trick_signature(rnd.last_trick))


@pytest.mark.parametrize("play", [["S2"], ["S5", "S5"],
                                  ["S2", "S3", "S4", "S5", "S5"]])
def test_afterstate_prepared_lead_matches_default_without_mutating_root(play):
    root = _lead_round()
    before = _state_signature(root)
    context = PreparedLeadValidation(
        root.hands[0], root.hands[1:], root.ordering)
    ordinary = cwv_policy.afterstate(root, 0, root.hands, [], play)
    prepared = cwv_policy.afterstate(
        root, 0, root.hands, [], play, _lead_validation=context)
    assert _state_signature(prepared) == _state_signature(ordinary)
    assert _state_signature(root) == before
    assert not getattr(root, "_trusted_rollout", False)
    assert context.calls == 1


def test_engine_play_has_no_prepared_context_override():
    refused = _lead_round()
    before = _state_signature(refused)
    context = PreparedLeadValidation(
        refused.hands[0], refused.hands[1:], refused.ordering)
    with pytest.raises(TypeError, match="_lead_validation"):
        refused.play(0, ["S2"], _lead_validation=context)
    assert _state_signature(refused) == before


def test_afterstate_refuses_an_untyped_prepared_context():
    root = _lead_round()
    before = _state_signature(root)
    with pytest.raises(cwv_policy.CWVError, match=(
            "^afterstate requires an exact prepared lead context$")):
        cwv_policy.afterstate(root, 0, root.hands, [], ["S2"],
                              _lead_validation=object())
    assert _state_signature(root) == before


def test_world_cache_wires_root_prepared_context_and_can_disable_it(monkeypatch):
    root = _lead_round()
    root.hands = [["S2"], ["S3"], ["S4"], ["S5"]]
    world = [list(hand) for hand in root.hands]
    captured = []
    original = cwv_policy.afterstate

    def observe(*args, **kwargs):
        captured.append(kwargs.get("_lead_validation"))
        return original(*args, **kwargs)

    monkeypatch.setattr(cwv_policy, "afterstate", observe)
    enabled = WorldSuccessorCache(root, 0, world, [])
    enabled.leaf(["S2"])
    enabled.leaf(["S2"])
    disabled = WorldSuccessorCache(root, 0, world, [], prepare_leads=False)
    disabled_leaf = disabled.leaf(["S2"])
    assert type(enabled.lead_validation) is PreparedLeadValidation
    assert captured[0] is enabled.lead_validation
    assert captured[1] is enabled.lead_validation
    assert captured[2] is None
    assert enabled.lead_validation.calls == 2
    assert enabled.lead_validation.hits == 0  # singles need no opponent fact
    assert disabled.lead_validation is None
    assert _state_signature(enabled.leaf(["S2"])) == _state_signature(disabled_leaf)


def test_prepared_fact_cache_stays_bounded_under_eviction(monkeypatch):
    monkeypatch.setattr(PreparedLeadValidation, "_MAX_FACTS", 2)
    ordering = Ordering(None, "A")
    hand = []
    plays = []
    for suit in ("S", "C", "D"):
        play = [suit + "2", suit + "3", suit + "4", suit + "4"]
        hand.extend(play)
        plays.append(play)
    others = [[], [], []]
    prepared = PreparedLeadValidation(hand, others, ordering)
    prepared.validate(plays[0], hand, others, ordering)
    prepared.validate(plays[0], hand, others, ordering)
    assert prepared.hits >= 2
    for play in plays[1:]:
        prepared.validate(play, hand, others, ordering)
    misses_before = prepared.misses
    prepared.validate(plays[0], hand, others, ordering)
    assert len(prepared._max_top) == 2
    assert prepared.misses > misses_before


def test_world_cache_context_hits_on_repeated_multicomponent_root_action():
    root = _lead_round()
    world = [list(hand) for hand in root.hands]
    candidate = ["S2", "S3", "S4", "S5", "S5"]
    prepared_cache = WorldSuccessorCache(root, 0, world, [])
    legacy_cache = WorldSuccessorCache(root, 0, world, [], prepare_leads=False)
    prepared_first = prepared_cache.leaf(candidate)
    prepared_second = prepared_cache.leaf(candidate)
    legacy = legacy_cache.leaf(candidate)
    assert _state_signature(prepared_first) == _state_signature(legacy)
    assert _state_signature(prepared_second) == _state_signature(legacy)
    assert prepared_cache.lead_validation.calls == 2
    assert prepared_cache.lead_validation.misses > 0
    assert prepared_cache.lead_validation.hits > 0
    assert legacy_cache.lead_validation is None


def test_follow_and_terminal_cache_outputs_match_legacy_reference():
    # Follow roots never construct/use a lead context, and terminal leaves
    # still run the same exact resolution and cached trick accounting.
    follow_root = _lead_round()
    follow_root._trusted_rollout = True
    follow_root._determinized_world = True
    follow_root.play(0, ["S2"])
    world = [list(hand) for hand in follow_root.hands]
    seat = follow_root.turn
    assert seat == 1
    candidate = ["S8"]
    ordinary = cwv_policy.afterstate(
        follow_root, seat, world, [], candidate, finish_trick=False)
    cwv_policy.finish_current_trick(ordinary)
    cached = WorldSuccessorCache(
        follow_root, seat, world, [], prepare_leads=True).leaf(candidate)
    assert _state_signature(cached) == _state_signature(ordinary)
    assert WorldSuccessorCache(follow_root, seat, world, [],
                               prepare_leads=True).lead_validation is None

    terminal_root = _lead_round()
    terminal_root.hands = [["S2"], ["S3"], ["S4"], ["S5"]]
    terminal_world = [list(hand) for hand in terminal_root.hands]
    raw = cwv_policy.afterstate(terminal_root, 0, terminal_world, [],
                                ["S2"], finish_trick=False)
    cwv_policy.finish_current_trick(raw)
    terminal = WorldSuccessorCache(terminal_root, 0, terminal_world, []).leaf(
        ["S2"])
    assert _state_signature(terminal) == _state_signature(raw)
