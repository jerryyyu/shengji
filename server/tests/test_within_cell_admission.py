"""Offline synthetic tests for the S11a within-cell admission prototype."""

import copy
from collections import Counter
from types import SimpleNamespace

import pytest

from shengji.engine.cards import Ordering
from shengji.eval.pair_resource_admission import _pair_inputs, pair_resource_rank_repair
from shengji.eval.within_cell_admission import within_cell_rank_repair
from shengji.train.policy_value_search import structure_key


def _synthetic_round():
    hand = [
        "S6", "S6", "S8", "S8", "D8", "D8",
        "C2", "C4", "C5", "D2", "D2", "C6",
    ]
    return SimpleNamespace(
        hands=[[], hand, [], []],
        ordering=Ordering("H", "7"),
    )


def _resource_actions():
    return [
        ["S6", "D8", "C2"],       # anchor: cell shared with 2 and 3
        ["S8", "D8", "C2"],       # another pair remainder cell
        ["S6", "D8", "C4"],       # same cell as anchor
        ["S6", "D8", "C5"],       # same cell as anchor
        ["S8", "D8", "C4"],       # same cell as 1
        ["C2"],
        ["D2"],
        ["C4", "D2"],
    ]


def test_witness_replaces_worst_same_cell_slot_and_audits_the_swap():
    rnd = _synthetic_round()
    actions = _resource_actions()
    ranked = [0, 2, 1, 3, 4, 5, 6, 7]
    baseline = [0, 3]

    result = within_cell_rank_repair(rnd, 1, actions, ranked, baseline)

    assert result["chosen"] == [0, 2]
    assert result["audit"] == {
        "removed": {
            "index": 3,
            "action": ("S6", "D8", "C5"),
            "policy_rank": 4,
            "cell": (
                ("mixed", 3, (("C", 0), ("D", 0), ("S", 0))),
                (2, 1, 1, 2),
            ),
        },
        "added": {
            "index": 2,
            "action": ("S6", "D8", "C4"),
            "policy_rank": 2,
            "cell": (
                ("mixed", 3, (("C", 0), ("D", 0), ("S", 0))),
                (2, 1, 1, 2),
            ),
        },
    }


def test_worse_ranked_excluded_member_is_still_selected_without_rank_gate():
    rnd = _synthetic_round()
    actions = _resource_actions()
    # Action 2 is the only excluded member of the anchor cell, but its rank
    # is deliberately worse than removable baseline action 3.
    ranked = [0, 3, 1, 4, 5, 6, 7, 2]

    result = within_cell_rank_repair(rnd, 1, actions, ranked, [0, 3])

    assert result["chosen"] == [0, 2]
    assert result["audit"]["removed"]["policy_rank"] == 2
    assert result["audit"]["added"]["policy_rank"] == 8


def test_s11a_witness_differs_from_pair_resource_repair():
    rnd = _synthetic_round()
    actions = _resource_actions()
    ranked = [0, 2, 1, 3, 4, 5, 6, 7]
    baseline = [0, 3]

    old = pair_resource_rank_repair(rnd, 1, actions, ranked, baseline)
    new = within_cell_rank_repair(rnd, 1, actions, ranked, baseline)

    assert old["chosen"] == [0, 1]
    assert new["chosen"] == [0, 2]


def test_no_eligible_cell_is_a_noop_and_preserves_anchor_size_and_cells():
    rnd = _synthetic_round()
    actions = _resource_actions()
    ranked = [0, 2, 1, 3, 4, 5, 6, 7]

    result = within_cell_rank_repair(rnd, 1, actions, ranked, [0, 1])

    assert result == {"chosen": [0, 1], "audit": None}


def test_anchor_is_never_replaced_even_when_it_is_worst_ranked():
    rnd = _synthetic_round()
    actions = _resource_actions()
    # Anchor 0 is eligible by cell count but is ranked below removable 3.
    result = within_cell_rank_repair(rnd, 1, actions, [3, 2, 1, 0, 4, 5, 6, 7], [0, 3])
    assert result["chosen"] == [0, 2]
    assert result["audit"]["removed"]["index"] == 3


def test_global_worst_slot_and_exact_cell_multiplicities_across_two_cells():
    rnd = _synthetic_round()
    actions = _resource_actions() + [["S8", "D8", "C5"]]
    ranked = [0, 2, 1, 3, 4, 5, 6, 7, 8]
    baseline = [0, 3, 1, 4]
    _, signatures = _pair_inputs(rnd, 1, actions, ranked, 0, len(actions), 1)
    cells = [
        (structure, signature)
        for structure, signature in zip(
            [structure_key(rnd, action) for action in actions],
            signatures,
        )
    ]

    result = within_cell_rank_repair(rnd, 1, actions, ranked, baseline)

    assert result["chosen"] == [0, 3, 1, 8]
    assert result["audit"]["removed"]["index"] == 4
    assert result["audit"]["added"]["index"] == 8
    assert Counter(cells[index] for index in result["chosen"]) == Counter(
        cells[index] for index in baseline
    )


def test_reordered_equivalent_pool_preserves_action_identities_and_ranks():
    rnd = _synthetic_round()
    actions = _resource_actions()
    ranked = [0, 2, 1, 3, 4, 5, 6, 7]
    baseline = [0, 3]
    first = within_cell_rank_repair(rnd, 1, actions, ranked, baseline)

    permutation = [4, 7, 0, 2, 6, 3, 1, 5]
    reordered = [list(reversed(actions[index])) for index in permutation]
    old_to_new = {old: new for new, old in enumerate(permutation)}
    reordered_ranked = [old_to_new[index] for index in ranked]
    reordered_baseline = [old_to_new[index] for index in baseline]
    second = within_cell_rank_repair(
        rnd, 1, reordered, reordered_ranked, reordered_baseline
    )

    assert [tuple(sorted(reordered[index])) for index in second["chosen"]] == [
        tuple(sorted(actions[index])) for index in first["chosen"]
    ]
    assert second["audit"]["removed"]["action"] == first["audit"]["removed"]["action"]
    assert second["audit"]["added"]["action"] == first["audit"]["added"]["action"]
    assert second["audit"]["removed"]["policy_rank"] == first["audit"]["removed"]["policy_rank"]
    assert second["audit"]["added"]["policy_rank"] == first["audit"]["added"]["policy_rank"]


@pytest.mark.parametrize("field", ["ranked", "baseline"])
def test_bool_and_missing_or_duplicate_indices_are_refused(field):
    rnd = _synthetic_round()
    actions = _resource_actions()
    ranked = list(range(8))
    baseline = [0, 3]
    if field == "ranked":
        ranked = [0, 1, 1, 3, 4, 5, 6, 7]
    else:
        baseline = [0, True]
    with pytest.raises(ValueError):
        within_cell_rank_repair(rnd, 1, actions, ranked, baseline)


@pytest.mark.parametrize(
    "damage",
    ["duplicate_action", "missing_rank", "out_of_range", "bool_seat", "unknown_card"],
)
def test_invalid_pool_or_indices_are_refused(damage):
    rnd = _synthetic_round()
    actions = _resource_actions()
    ranked = list(range(8))
    baseline = [0, 3]
    if damage == "duplicate_action":
        actions[2] = list(actions[0])
    elif damage == "missing_rank":
        ranked = list(range(7))
    elif damage == "out_of_range":
        ranked[-1] = 8
    elif damage == "bool_seat":
        with pytest.raises(ValueError):
            within_cell_rank_repair(rnd, True, actions, ranked, baseline)
        return
    else:
        actions[2] = ["ZZ"]
    with pytest.raises(ValueError):
        within_cell_rank_repair(rnd, 1, actions, ranked, baseline)


def test_inputs_are_not_mutated():
    rnd = _synthetic_round()
    actions = _resource_actions()
    ranked = [0, 2, 1, 3, 4, 5, 6, 7]
    baseline = [0, 3]
    before = copy.deepcopy((rnd.hands, actions, ranked, baseline))

    within_cell_rank_repair(rnd, 1, actions, ranked, baseline)

    assert (rnd.hands, actions, ranked, baseline) == before
