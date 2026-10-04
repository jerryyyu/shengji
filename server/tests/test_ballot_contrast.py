import random

import pytest

from shengji.train.ballot_contrast import summarize_ballot_contrasts


def test_common_s6_pair_is_constant_and_has_no_card_contrast():
    summary = summarize_ballot_contrasts(
        [["S6", "S6", "H2"], ["H2", "S6", "S6"], ["S6", "S6", "C3"]]
    )

    assert summary["num_slots"] == 3
    assert summary["num_unique_actions"] == 2
    assert summary["common_positive_constant_cards"] == ["S6"]
    assert summary["per_card"]["S6"] == {
        "min": 2,
        "max": 2,
        "preserve_spend": False,
        "pair": False,
    }
    assert "S6" not in summary["varying_cards"]


def test_retaining_one_and_two_are_distinct_from_full_preservation():
    summary = summarize_ballot_contrasts(
        [["S6", "H2"], ["S6", "S6"], ["S6", "C3"]]
    )

    assert summary["per_card"]["S6"] == {
        "min": 1,
        "max": 2,
        "preserve_spend": False,
        "pair": True,
    }
    assert summary["per_card"]["H2"]["preserve_spend"] is True
    assert summary["per_card"]["H2"]["pair"] is False
    assert summary["varying_card_count"] == 3


def test_duplicate_slots_count_but_unique_actions_do_not():
    summary = summarize_ballot_contrasts(
        [["S2", "S2"], ["S2", "S2"], ["H2"]]
    )

    assert summary["num_slots"] == 3
    assert summary["num_unique_actions"] == 2
    assert summary["unique_actions"] == [["H2"], ["S2", "S2"]]
    assert summary["per_card"]["S2"]["min"] == 0
    assert summary["per_card"]["S2"]["max"] == 2


def test_action_card_order_and_slot_order_do_not_change_summary():
    ballot = [["C10", "S2"], ["S2", "S2"], ["H3"]]
    reordered = [["H3"], ["S2", "S2"], ["S2", "C10"]]

    assert summarize_ballot_contrasts(ballot) == summarize_ballot_contrasts(reordered)


@pytest.mark.parametrize(
    "ballot, reason",
    [([], "empty"), ([["S2"]], "single"), ([["S2"], ["S2"]], "identical")],
)
def test_empty_and_one_slot_ballots_are_explicitly_degenerate(ballot, reason):
    summary = summarize_ballot_contrasts(ballot)

    assert summary["degenerate"] is True
    assert summary["degenerate_reason"] == reason


@pytest.mark.parametrize(
    "ballot",
    [
        "S2",
        ["S2"],
        [[]],
        [["S2", "S2", "S2"]],
        [["S1"]],
        [[1]],
        [[None]],
        {"S2": 1},
    ],
)
def test_malformed_actions_and_cards_are_rejected(ballot):
    with pytest.raises((TypeError, ValueError)):
        summarize_ballot_contrasts(ballot)


def test_randomized_slot_permutations_are_invariant():
    ballot = [
        ["S2", "S2"],
        ["H5"],
        ["C10", "D10"],
        ["S2", "H5"],
        ["C10", "D10"],
    ]
    expected = summarize_ballot_contrasts(ballot)
    rng = random.Random(20261003)

    for _ in range(30):
        candidate = [list(action) for action in ballot]
        rng.shuffle(candidate)
        for action in candidate:
            rng.shuffle(action)
        assert summarize_ballot_contrasts(candidate) == expected
