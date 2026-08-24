"""Mechanics witnesses for the score-free privileged-teacher PT0 boundary."""

from __future__ import annotations

from fractions import Fraction
import json
import random

import pytest

from shengji.rl.privileged_teacher_pt0 import (
    PT0_BASELINE_POLICIES,
    PT0_TARGET_SCHEMA,
    PrivilegedTeacherPT0Error,
    WorldActionValues,
    baseline_regret,
    canonical_json_bytes,
    exact_world_action_values,
    evaluate_named_baseline,
    information_set_target,
    rotate_round_seats,
    run_pt0_miniature,
    signed_level_utility,
)
from shengji.engine.cards import Ordering, RANKS
from shengji.engine.round import Round, Trick


def _sha(char: str) -> str:
    return char * 64


def _two_card_round(trump_rank: str = "7") -> Round:
    rnd = Round(trump_rank, banker=0, rng=random.Random(0))
    rnd.phase = "play"
    rnd.ordering = Ordering("H", trump_rank)
    rnd.trump_suit = "H"
    rnd.trump_is_nt = False
    rnd.hands = [
        ["C3", "D3"], ["C4", "D4"],
        ["C5", "D5"], ["C6", "D6"],
    ]
    rnd.buried = ["H5"]
    rnd.attacker_points = 70
    rnd.trick = Trick(leader=1)
    rnd.turn = 1
    rnd.deck = [card for hand in rnd.hands for card in hand] + rnd.buried
    return rnd


def _three_card_round(trump_rank: str = "7") -> Round:
    rnd = Round(trump_rank, banker=0, rng=random.Random(1))
    rnd.phase = "play"
    rnd.ordering = Ordering("H", trump_rank)
    rnd.trump_suit = "H"
    rnd.trump_is_nt = False
    rnd.hands = [
        ["C3", "D3", "S3"], ["C4", "D4", "S4"],
        ["C5", "D5", "S5"], ["C6", "D6", "S6"],
    ]
    rnd.buried = ["H5"]
    rnd.attacker_points = 70
    rnd.trick = Trick(leader=1)
    rnd.turn = 1
    rnd.deck = [card for hand in rnd.hands for card in hand] + rnd.buried
    return rnd


def _two_card_hidden_world_with_different_value() -> Round:
    rnd = _two_card_round()
    rnd.hands[0] = ["CK", "DK"]
    rnd.deck = [card for hand in rnd.hands for card in hand] + rnd.buried
    return rnd


def test_signed_level_utility_matches_round_scoring_for_both_roles():
    # Defender shutout, sub-40, 40-79, takeover, and multi-level attacker win.
    expected = {0: -3, 35: -2, 40: -1, 79: -1,
                80: 1, 119: 1, 120: 1, 160: 2}
    for points, attacker_value in expected.items():
        assert signed_level_utility(
            points, banker_seat=0, perspective_seat=1) == attacker_value
        assert signed_level_utility(
            points, banker_seat=0, perspective_seat=0) == -attacker_value


def test_exact_world_evaluator_forces_every_root_action_and_keeps_input():
    rnd = _two_card_round()
    before = [list(hand) for hand in rnd.hands]
    got = exact_world_action_values(
        rnd, world_sha256=_sha("4"), perspective_seat=1,
        max_hand_cards=2)
    assert [cards for cards, _ in got.values.action_utilities] == [
        ("C4",), ("D4",)]
    assert [cards for cards, _ in got.final_attacker_points] == [
        ("C4",), ("D4",)]
    assert got.nodes > 0 and got.cache_hits >= 0
    assert rnd.hands == before and rnd.turn == 1 and rnd.phase == "play"


def test_exact_world_evaluator_runs_genuine_three_card_endgame():
    got = exact_world_action_values(
        _three_card_round(), world_sha256=_sha("6"), perspective_seat=1,
        max_hand_cards=3)
    assert len(got.values.action_utilities) == 3
    assert len(got.final_attacker_points) == 3
    assert got.nodes > 0


def test_miniature_run_resumes_exact_prefix_byte_identically():
    worlds = [(_sha("5"), _two_card_round()), (_sha("4"), _two_card_round())]
    full = run_pt0_miniature(
        _sha("e"), worlds, perspective_seat=1,
        monotonic=iter((0.0, 0.0, 1.0, 1.0, 1.0, 1.0)).__next__)
    partial = run_pt0_miniature(
        _sha("e"), worlds, perspective_seat=1, deadline=0.5,
        monotonic=iter((0.0, 0.0, 1.0, 1.0)).__next__)
    assert partial.status == "DEADLINE"
    assert partial.completed_units == 1
    assert partial.receipt["progress"]["percent_basis_points"] == 5_000
    resumed = run_pt0_miniature(
        _sha("e"), worlds, perspective_seat=1,
        monotonic=lambda: 1.0, checkpoint=partial.checkpoint)
    assert resumed.status == "COMPLETE"
    assert canonical_json_bytes(resumed.target) == \
        canonical_json_bytes(full.target)
    assert canonical_json_bytes(resumed.receipt) == \
        canonical_json_bytes(full.receipt)
    assert resumed.receipt["authority"] == {
        "gameplay_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
        "training_authorized": False,
    }
    assert resumed.receipt["contract"]["terminal_horizon"] == "round_end"


def test_miniature_aggregates_different_values_on_same_public_ballot():
    result = run_pt0_miniature(
        _sha("e"), [
            (_sha("4"), _two_card_round()),
            (_sha("5"), _two_card_hidden_world_with_different_value()),
        ], perspective_seat=1, monotonic=lambda: 0.0)
    assert result.status == "COMPLETE"
    assert result.target is not None
    by_cards = {tuple(row["cards"]): row for row in result.target["actions"]}
    assert by_cards[("C4",)]["mean_signed_level_utility"] == {
        "numerator": 0, "denominator": 1}
    assert by_cards[("D4",)]["mean_signed_level_utility"] == {
        "numerator": 0, "denominator": 1}


def test_miniature_run_emits_canonical_checkpoints_and_deadline_can_fail():
    emitted = []
    calls = iter((0.0, 0.0, 1.0, 1.0))
    worlds = [(_sha("4"), _two_card_round()), (_sha("5"), _two_card_round())]
    result = run_pt0_miniature(
        _sha("e"), worlds, perspective_seat=1, deadline=0.5,
        monotonic=lambda: next(calls), checkpoint_sink=emitted.append)
    assert result.status == "DEADLINE"
    assert result.target is None
    assert result.completed_units == 1
    assert result.receipt["progress"]["percent_basis_points"] == 5_000
    assert emitted == list(result.checkpoints)
    assert emitted and all(
        canonical_json_bytes(json.loads(item.decode("ascii")))
        == item for item in emitted)

    tampered = bytearray(result.checkpoint)
    tampered[-2] = ord(" ")
    with pytest.raises(PrivilegedTeacherPT0Error, match="checkpoint is not"):
        run_pt0_miniature(
            _sha("e"), worlds, perspective_seat=1,
            monotonic=lambda: 0.0, checkpoint=bytes(tampered))
    semantic_tamper = json.loads(result.checkpoint.decode("ascii"))
    semantic_tamper["work"]["nodes"] += 1
    with pytest.raises(PrivilegedTeacherPT0Error, match="work drift"):
        run_pt0_miniature(
            _sha("e"), worlds, perspective_seat=1,
            monotonic=lambda: 0.0,
            checkpoint=canonical_json_bytes(semantic_tamper))


def test_exact_world_evaluator_refuses_non_actor_perspective():
    with pytest.raises(PrivilegedTeacherPT0Error, match="acting seat"):
        exact_world_action_values(
            _two_card_round(), world_sha256=_sha("4"),
            perspective_seat=0, max_hand_cards=2)


def test_exact_world_evaluator_refuses_invalid_resource_bounds():
    with pytest.raises(PrivilegedTeacherPT0Error, match="max_hand_cards"):
        exact_world_action_values(
            _two_card_round(), world_sha256=_sha("4"), perspective_seat=1,
            max_hand_cards=0)
    with pytest.raises(PrivilegedTeacherPT0Error, match="max_nodes"):
        exact_world_action_values(
            _two_card_round(), world_sha256=_sha("4"), perspective_seat=1,
            max_hand_cards=2, max_nodes=True)


def test_all_rank_and_seat_rotations_preserve_exact_action_values():
    for trump_rank in RANKS:
        original = _two_card_round(trump_rank)
        expected = exact_world_action_values(
            original, world_sha256=_sha("4"), perspective_seat=1,
            max_hand_cards=2)
        for offset in range(4):
            rotated = rotate_round_seats(original, offset)
            got = exact_world_action_values(
                rotated, world_sha256=_sha("4"),
                perspective_seat=(1 + offset) % 4, max_hand_cards=2)
            assert got.values.action_utilities == \
                expected.values.action_utilities
            assert got.final_attacker_points == expected.final_attacker_points


def test_named_public_baseline_adapter_reports_exact_regret():
    rnd = _two_card_round()
    exact = exact_world_action_values(
        rnd, world_sha256=_sha("4"), perspective_seat=1,
        max_hand_cards=2)
    # Duplicate the known world only to build a minimal information-set target;
    # the two world identities are distinct while their exact values agree.
    twin = WorldActionValues.build(_sha("5"), exact.values.action_utilities)
    target = information_set_target(_sha("e"), [exact.values, twin])
    for policy in ("heuristic", "smart"):
        got = evaluate_named_baseline(rnd, target, policy=policy, seed=19)
        assert got.policy == policy and got.seed == 19
        assert got.selected_cards in {
            cards for cards, _ in exact.values.action_utilities}
        assert got.information_set_regret >= 0
    # The synthetic miniature omits the full unseen deck required by MC
    # determinization.  Named MC baselines fail closed rather than claiming a
    # fabricated action value on this fixture.
    for policy in ("mc-strong", "mc-s0-report-lcb"):
        with pytest.raises(PrivilegedTeacherPT0Error, match="could not evaluate"):
            evaluate_named_baseline(rnd, target, policy=policy, seed=19)
    assert PT0_BASELINE_POLICIES == (
        "heuristic", "smart", "mc-strong", "mc-s0-report-lcb")


def test_baseline_and_rotation_refuse_unfrozen_inputs():
    exact = exact_world_action_values(
        _two_card_round(), world_sha256=_sha("4"), perspective_seat=1,
        max_hand_cards=2)
    twin = WorldActionValues.build(_sha("5"), exact.values.action_utilities)
    target = information_set_target(_sha("e"), [exact.values, twin])
    with pytest.raises(PrivilegedTeacherPT0Error, match="not frozen"):
        evaluate_named_baseline(
            _two_card_round(), target, policy="mc", seed=1)
    with pytest.raises(PrivilegedTeacherPT0Error, match="offset"):
        rotate_round_seats(_two_card_round(), 4)


def test_information_set_target_is_order_and_true_world_invariant():
    first = WorldActionValues.build(_sha("1"), [
        (("C2",), 1), (("D3",), -1), (("S4",), 1)])
    second = WorldActionValues.build(_sha("2"), [
        (("C2",), -1), (("D3",), 2), (("S4",), 1)])
    third = WorldActionValues.build(_sha("3"), [
        (("C2",), 2), (("D3",), -1), (("S4",), 1)])

    one = information_set_target(_sha("a"), [first, second, third])
    two = information_set_target(_sha("a"), [third, first, second])
    assert canonical_json_bytes(one) == canonical_json_bytes(two)
    assert one["schema"] == PT0_TARGET_SCHEMA
    assert one["information_set_argmax"] == [["S4"]]
    assert one["true_world_selects_target"] is False
    # A single true world would select C2, D3, or tie on S4 depending on which
    # hidden deal was exposed. None of those identities exists in target bytes.
    assert b"true_world_sha256" not in canonical_json_bytes(one)


def test_best_world_probability_reports_rank_instability_and_ties():
    worlds = [
        WorldActionValues.build(_sha("1"), [(('C2',), 1), (('D3',), 1)]),
        WorldActionValues.build(_sha("2"), [(('C2',), 2), (('D3',), -1)]),
    ]
    target = information_set_target(_sha("b"), worlds)
    by_cards = {tuple(row["cards"]): row for row in target["actions"]}
    assert by_cards[("C2",)]["best_world_probability"] == {
        "numerator": 1, "denominator": 1}
    assert by_cards[("D3",)]["best_world_probability"] == {
        "numerator": 1, "denominator": 2}


def test_baseline_regret_is_exact_and_refuses_off_ballot_actions():
    target = information_set_target(_sha("c"), [
        WorldActionValues.build(_sha("1"), [(('C2',), 1), (('D3',), 3)]),
        WorldActionValues.build(_sha("2"), [(('C2',), -1), (('D3',), 1)]),
    ])
    assert baseline_regret(target, ["D3"]) == Fraction(0)
    assert baseline_regret(target, ["C2"]) == Fraction(2)
    with pytest.raises(PrivilegedTeacherPT0Error, match="outside"):
        baseline_regret(target, ["S4"])


def test_aggregation_refuses_world_or_action_population_drift():
    one = WorldActionValues.build(_sha("1"), [(('C2',), 1), (('D3',), -1)])
    different = WorldActionValues.build(
        _sha("2"), [(('C2',), 1), (('S4',), -1)])
    with pytest.raises(PrivilegedTeacherPT0Error, match="legal-action"):
        information_set_target(_sha("d"), [one, different])
    with pytest.raises(PrivilegedTeacherPT0Error, match="duplicate"):
        information_set_target(_sha("d"), [one, one])


def test_aggregation_refuses_non_world_values_and_baseline_authority_drift():
    one = WorldActionValues.build(_sha("1"), [(('C2',), 1), (('D3',), -1)])
    with pytest.raises(PrivilegedTeacherPT0Error, match="exact WorldActionValues"):
        information_set_target(_sha("d"), [one, object()])

    target = information_set_target(_sha("d"), [
        one,
        WorldActionValues.build(_sha("2"), [(('C2',), 2), (('D3',), 1)]),
    ])
    target["gameplay_authorized"] = True
    with pytest.raises(PrivilegedTeacherPT0Error, match="authority"):
        baseline_regret(target, ["C2"])


def test_baseline_regret_refuses_duplicate_target_actions():
    target = information_set_target(_sha("d"), [
        WorldActionValues.build(_sha("1"), [(('C2',), 1), (('D3',), -1)]),
        WorldActionValues.build(_sha("2"), [(('C2',), 2), (('D3',), 1)]),
    ])
    target["actions"].append(target["actions"][0])
    with pytest.raises(PrivilegedTeacherPT0Error, match="duplicate action"):
        baseline_regret(target, ["C2"])


def test_world_values_refuse_duplicate_or_zero_utility_rows():
    with pytest.raises(PrivilegedTeacherPT0Error, match="nonempty and unique"):
        WorldActionValues.build(
            _sha("1"), [(('C2',), 1), (('C2',), -1)])
    with pytest.raises(PrivilegedTeacherPT0Error, match="nonzero"):
        WorldActionValues.build(_sha("1"), [(('C2',), 0)])
