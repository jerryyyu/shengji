"""Offline tests for the pair-resource admission hypothesis."""
import copy
import random
from collections import Counter
from types import SimpleNamespace

import pytest

from shengji.engine.cards import Ordering
from shengji.eval.pair_resource_admission import pair_resource_ballot, pair_resource_rank_repair
from shengji.harvest.legal import enumerate_legal
from shengji.train.policy_value_search import structure_key, _near_duplicate

from test_pv_admission_rules import _pair_preservation_follow, harness


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
        ["S6", "D8", "C2"],       # anchor: split S6
        ["S8", "D8", "C2"],       # rank-2 alternative: split S8
        ["S6", "D8", "C4"],       # same resource state, near duplicate
        ["S6", "D8", "C5"],       # same resource state, near duplicate
        ["S8", "D8", "C4"],       # same resource state as rank-2, near duplicate
        ["C2"],                   # backfill
        ["D2"],                   # backfill
        ["C4", "D2"],             # backfill
    ]


def test_real_legal_k8_witness_admits_rank2_pair_preserving_follow():
    rnd = _pair_preservation_follow()
    actions = list(enumerate_legal(rnd, 1, cap=4000).actions)
    keys = [tuple(sorted(action)) for action in actions]
    anchor = keys.index(("C2", "D8", "S6"))
    preserving = keys.index(("C2", "D8", "S8"))
    ranked = [anchor, preserving] + [
        index for index in range(len(actions)) if index not in (anchor, preserving)
    ]

    result = pair_resource_ballot(rnd, 1, actions, ranked, anchor, k=8)

    assert result["chosen"][0] == anchor
    assert result["chosen"][1] == preserving
    assert len(result["chosen"]) == 8
    assert len(set(result["chosen"])) == 8
    for index in result["chosen"]:
        played = copy.deepcopy(rnd)
        played.play(1, list(actions[index]))


def test_no_pair_hands_match_production_diversity_selection():
    rnd = _synthetic_round()
    rnd.hands[1] = ["S6", "S8", "D8", "C2", "C4", "C5", "D2", "C6"]
    actions = [
        ["S6", "D8", "C2"],
        ["S8", "D8", "C2"],
        ["S6", "D8", "C4"],
        ["C2"],
        ["D2"],
        ["C4", "D2"],
    ]
    ranked = [2, 0, 1, 5, 4, 3]
    bot = harness(admission_diversity=True)
    bot.max_per_structure = 2

    production = bot._admit_diverse(rnd, actions, ranked, anchor_index=0, k=5)
    result = pair_resource_ballot(
        rnd, 1, actions, ranked, anchor_index=0, k=5, max_per_structure=2
    )

    assert result["chosen"] == production
    assert result["skipped"] == bot._diversity_skipped


@pytest.mark.parametrize(
    ("ranked", "k", "cap"),
    [
        ([0, 1, 2, 3, 4, 5, 6, 7], 5, 2),
        ([7, 6, 5, 4, 3, 2, 1, 0], 8, 2),
        ([1, 0, 2, 3, 4, 5, 6, 7], 3, 2),
    ],
)
def test_resource_partition_is_deterministic_and_preserves_anchor(ranked, k, cap):
    rnd = _synthetic_round()
    actions = _resource_actions()
    hand_before = list(rnd.hands[1])
    ranked_before = list(ranked)

    first = pair_resource_ballot(rnd, 1, actions, ranked, 0, k=k,
                                 max_per_structure=cap)
    second = pair_resource_ballot(rnd, 1, actions, ranked, 0, k=k,
                                  max_per_structure=cap)

    assert first == second
    assert first["chosen"][0] == 0
    assert len(first["chosen"]) == k
    assert len(first["chosen"]) == len(set(first["chosen"]))
    assert rnd.hands[1] == hand_before
    assert ranked == ranked_before


def test_same_resource_near_duplicates_are_suppressed_and_backfilled():
    rnd = _synthetic_round()
    actions = _resource_actions()
    ranked = list(range(len(actions)))

    result = pair_resource_ballot(rnd, 1, actions, ranked, 0, k=5)

    assert result["chosen"] == [0, 1, 5, 6, 7]
    assert result["skipped"] == [2, 3, 4]
    assert 2 not in result["chosen"] and 3 not in result["chosen"]


def test_zero_one_two_remaining_pair_signatures_partition_overlap_checks():
    rnd = SimpleNamespace(
        hands=[[], ["D2", "D2", "S6", "S6", "C2", "C4", "C5", "C7"], [], []],
        ordering=Ordering("H", "7"),
    )
    actions = [
        ["D2", "C2"],       # D2 remaining 1: anchor signature
        ["D2", "C4"],       # same signature/structure: near duplicate
        ["D2", "D2"],       # D2 remaining 0: separate resource bucket
        ["S6", "C2"],       # S6 remaining 1: separate resource bucket
        ["S6", "C4"],       # same signature as index 3: near duplicate
        ["C5", "C7"],       # both pairs remain at 2: separate bucket
        ["D2", "S6"],       # both pairs split at 1: separate bucket
    ]

    result = pair_resource_ballot(rnd, 1, actions, list(range(len(actions))), 0, k=5)

    assert result == {"chosen": [0, 2, 3, 5, 6], "skipped": [1, 4]}


def test_different_seats_do_not_change_pair_resource_result():
    rnd = _synthetic_round()
    actions = _resource_actions()
    ranked = list(range(len(actions)))
    other_hands = copy.deepcopy(rnd)
    other_hands.hands[0] = ["BJ", "LJ"]
    other_hands.hands[2] = ["H2", "H3"]
    other_hands.hands[3] = ["C7", "C8"]

    original = pair_resource_ballot(rnd, 1, actions, ranked, 0, k=5)
    changed = pair_resource_ballot(other_hands, 1, actions, ranked, 0, k=5)

    assert changed == original


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ranked": [0, 1, 1, 3, 4, 5, 6, 7]},
        {"ranked": [0, 1, 2]},
        {"ranked": [0, 1, 2, 3, 4, 5, 6, 9]},
        {"actions": [["S6", "D8", "C2"], []], "ranked": [0, 1]},
        {"actions": [["S6", "D8", "C2"], ["BJ"]], "ranked": [0, 1]},
        {"k": True},
        {"max_per_structure": True},
        {"seat": True},
        {"anchor_index": True},
    ],
)
def test_invalid_rank_subset_and_bool_inputs_refuse(kwargs):
    rnd = _synthetic_round()
    actions = _resource_actions()
    params = dict(
        seat=1,
        actions=actions,
        ranked=list(range(len(actions))),
        anchor_index=0,
        k=5,
        max_per_structure=2,
    )
    params.update(kwargs)

    with pytest.raises(ValueError):
        pair_resource_ballot(rnd, **params)


def test_rejected_actions_backfill_in_rank_order_when_pool_is_exhausted():
    rnd = _synthetic_round()
    actions = _resource_actions()
    result = pair_resource_ballot(rnd, 1, actions, list(range(8)), 0, k=7)
    assert result == {"chosen": [0, 1, 5, 6, 7, 2, 3], "skipped": [4]}


def test_structure_keys_are_same_only_within_matching_resource_signatures():
    rnd = _synthetic_round()
    actions = _resource_actions()
    assert structure_key(rnd, actions[0]) == structure_key(rnd, actions[1])
    assert Counter(actions[0]) != Counter(actions[1])


def test_fixed_k_resource_partition_can_reduce_both_kinds_of_coverage():
    """Known limitation, not a desired strength invariant or learned ranking.

    Relaxing both filters lets earlier ranks crowd out later action shapes and
    even resource states. A successful rank-2 witness is not dominance proof.
    """
    rnd = _pair_preservation_follow()
    actions = list(enumerate_legal(rnd, 1, cap=4000).actions)
    anchor = [tuple(sorted(a)) for a in actions].index(("C2", "D8", "S6"))
    ranked = list(range(len(actions)))
    random.Random(22).shuffle(ranked)
    legacy = harness(admission_diversity=True)._admit_diverse(
        rnd, actions, ranked, anchor, k=8
    )
    prototype = pair_resource_ballot(rnd, 1, actions, ranked, anchor, k=8)["chosen"]
    pairs = sorted(c for c, n in Counter(rnd.hands[1]).items() if n == 2)

    def coverage(chosen):
        shapes = {structure_key(rnd, actions[i]) for i in chosen}
        resources = {tuple(2 - Counter(actions[i])[c] for c in pairs) for i in chosen}
        return len(shapes), len(resources)

    assert len(legacy) == len(prototype) == 8
    assert legacy[0] == prototype[0] == anchor
    assert coverage(legacy) == (5, 3)
    assert coverage(prototype) == (3, 2)


def test_rank_repair_admits_legal_witness_without_losing_coverage():
    rnd = _pair_preservation_follow()
    actions = list(enumerate_legal(rnd, 1, cap=4000).actions)
    keys = [tuple(sorted(a)) for a in actions]
    anchor = keys.index(("C2", "D8", "S6"))
    target = keys.index(("C2", "D8", "S8"))
    ranked = [anchor, target] + [i for i in range(len(actions)) if i not in (anchor, target)]
    baseline = harness(admission_diversity=True)._admit_diverse(rnd, actions, ranked, anchor, k=8)
    original = list(baseline)
    result = pair_resource_rank_repair(rnd, 1, actions, ranked, baseline)
    assert result["swap"]["added"] == target
    assert target in result["chosen"] and target not in baseline
    assert result["chosen"][0] == anchor
    assert len(result["chosen"]) == len(set(result["chosen"])) == 8
    assert baseline == original
    for i in result["chosen"]:
        copy.deepcopy(rnd).play(1, list(actions[i]))


@pytest.mark.parametrize("seed", range(32))
def test_rank_repair_preserves_exact_coverage_sets_and_improves_rank(seed):
    rnd = _pair_preservation_follow()
    actions = list(enumerate_legal(rnd, 1, cap=4000).actions)
    anchor = [tuple(sorted(a)) for a in actions].index(("C2", "D8", "S6"))
    ranked = list(range(len(actions)))
    random.Random(seed).shuffle(ranked)
    baseline = harness(admission_diversity=True)._admit_diverse(rnd, actions, ranked, anchor, k=8)
    result = pair_resource_rank_repair(rnd, 1, actions, ranked, baseline)
    chosen = result["chosen"]
    pairs = sorted(c for c, n in Counter(rnd.hands[1]).items() if n == 2)
    signature = lambda i: tuple(2 - Counter(actions[i])[c] for c in pairs)
    assert {structure_key(rnd, actions[i]) for i in baseline} <= {
        structure_key(rnd, actions[i]) for i in chosen
    }
    assert {signature(i) for i in baseline} <= {signature(i) for i in chosen}
    assert len(chosen) == len(set(chosen)) == len(baseline)
    assert chosen[0] == baseline[0]
    if result["swap"]:
        removed, added = result["swap"]["removed"], result["swap"]["added"]
        assert ranked.index(added) < ranked.index(removed)
        assert set(chosen) - set(baseline) == {added}
        assert set(baseline) - set(chosen) == {removed}
        retained = [i for i in chosen if i != added]
        overlaps = [i for i in retained if _near_duplicate(
            Counter(actions[added]), len(actions[added]),
            [(len(actions[i]), Counter(actions[i]))]
        )]
        assert overlaps
        assert all(signature(i) != signature(added) for i in overlaps)
    else:
        assert chosen == baseline


def test_rank_repair_no_pair_parity_and_singleton_anchor():
    rnd = _synthetic_round()
    rnd.hands[1] = list(dict.fromkeys(rnd.hands[1]))
    actions = _resource_actions()
    ranked = list(range(len(actions)))
    baseline = [0, 5, 6, 7]
    assert pair_resource_rank_repair(rnd, 1, actions, ranked, baseline) == {
        "chosen": baseline, "swap": None
    }
    assert pair_resource_rank_repair(rnd, 1, actions, ranked, [0]) == {
        "chosen": [0], "swap": None
    }


@pytest.mark.parametrize("baseline", [[], [True], [0, 0], [99], [-1]])
def test_rank_repair_refuses_invalid_baseline(baseline):
    with pytest.raises(ValueError):
        pair_resource_rank_repair(_synthetic_round(), 1, _resource_actions(), list(range(8)), baseline)


def test_rank_repair_protects_unique_resource_and_does_not_mutate_inputs():
    rnd = _synthetic_round()
    actions = _resource_actions()
    ranked, baseline = list(range(8)), [0, 5]
    before = copy.deepcopy((rnd.hands, actions, ranked, baseline))
    # Candidate 1 cannot evict the only both-pairs-retained representative 5.
    result = pair_resource_rank_repair(rnd, 1, actions, ranked, baseline)
    assert result == {"chosen": baseline, "swap": None}
    assert (rnd.hands, actions, ranked, baseline) == before
    rnd.hands[0] = ["BJ", "BJ"]
    assert pair_resource_rank_repair(rnd, 1, actions, ranked, baseline) == result
