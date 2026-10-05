"""Offline tests for the pair-resource admission hypothesis."""
import copy
import json
import random
from collections import Counter
from types import SimpleNamespace

import pytest

from shengji.engine.cards import Ordering
from shengji.eval.pair_resource_admission import (
    pair_resource_ballot, pair_resource_rank_repair, project_rank_repair,
    _pair_inputs,
)
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


def _projection_inputs():
    actions = _resource_actions()
    capture = {'schema': 'fixed-tape-policy-ranks-v1', 'actions': actions,
               'preferences': list(range(8, 0, -1)), 'ranked_indices': list(range(8))}
    return _synthetic_round(), capture, [actions[i] for i in [0, 2, 5, 6, 7]], actions


def test_projection_joins_by_multiset_not_position_and_can_show_value_loss():
    rnd, capture, baseline, actions = _projection_inputs()
    values = [0., -10., 10., 0., 0., 0., 0., 0.]
    original = copy.deepcopy((capture, baseline, actions, values))
    result = project_rank_repair(rnd, 1, capture, baseline, actions, values)
    shuffled = project_rank_repair(rnd, 1, capture, baseline,
                                  [list(reversed(a)) for a in reversed(actions)],
                                  list(reversed(values)))
    assert result == shuffled
    assert result['swap'] == {'removed': 2, 'added': 1}
    assert result['raw_value_max_delta'] == -10.
    assert result['repaired']['gap_to_full_pool'] == 10.
    assert not result['strategic_quality_assessed']
    assert not result['serving_choice_assessed']
    assert (capture, baseline, actions, values) == original


def test_projection_values_cannot_change_the_rank_repair():
    rnd, capture, baseline, actions = _projection_inputs()
    a = project_rank_repair(rnd, 1, capture, baseline, actions, [0.] * 8)
    b = project_rank_repair(rnd, 1, capture, baseline, actions, [100., -100.] * 4)
    assert a['swap'] == b['swap']
    assert a['repaired']['actions'] == b['repaired']['actions']


@pytest.mark.parametrize('failure', ['rank', 'tie', 'missing', 'duplicate', 'nan', 'bool', 'length'])
def test_projection_refuses_incompatible_or_invalid_inputs(failure):
    rnd, capture, baseline, actions = _projection_inputs()
    actions = copy.deepcopy(actions)
    values = [0.] * 8
    if failure == 'rank':
        capture['ranked_indices'] = list(reversed(range(8)))
    elif failure == 'tie':
        capture['preferences'] = [0.] * 8
        capture['ranked_indices'] = [1, 0] + list(range(2, 8))
    elif failure == 'missing':
        actions[1] = ['C6']
    elif failure == 'duplicate':
        actions[1] = actions[0]
    elif failure == 'nan':
        values[0] = float('nan')
    elif failure == 'bool':
        capture['preferences'][0] = True
    else:
        values.pop()
    with pytest.raises(ValueError):
        project_rank_repair(rnd, 1, capture, baseline, actions, values)


# Frozen S10 function from f7b5ed04, retained as an independent default oracle.
# Do not update alongside the implementation: this defines pre-ablation behavior.
def _frozen_s10_rank_repair(rnd, seat, actions, ranked, baseline):
    """Offline single-swap hypothesis; caller supplies the legacy ballot.

    Keep its anchor and size, and every covered played shape AND exact pair
    state. Consider excluded actions in supplied policy order; replace the
    worst-ranked removable non-anchor only with a better-ranked action that
    overlaps a retained action using different pair resources. Do not introduce
    same-resource overlap. Stop after one swap, returning its explicit indices.

    This does NOT preserve shape multiplicities, every action, tractor/control
    value, or utility. It cannot assert why the original selector omitted an
    action; it only tests a bounded alternative to global filter relaxation.
    """
    if (not baseline or any(type(i) is not int for i in baseline)
            or len(set(baseline)) != len(baseline)
            or any(not 0 <= i < len(actions) for i in baseline)):
        raise ValueError('invalid baseline ballot')
    counts, signatures = _pair_inputs(
        rnd, seat, actions, ranked, baseline[0], len(baseline), 1
    )
    shapes = {}

    def shape(i):
        if i not in shapes:
            shapes[i] = structure_key(rnd, actions[i])
        return shapes[i]

    chosen = list(baseline)
    covered_shapes = {shape(i) for i in chosen}
    covered_resources = {signatures[i] for i in chosen}
    rank = {i: position for position, i in enumerate(ranked)}
    for candidate in ranked:
        if candidate in chosen:
            continue
        for removed in sorted(chosen[1:], key=rank.get, reverse=True):
            if rank[candidate] >= rank[removed]:
                continue
            retained = [i for i in chosen if i != removed]
            overlaps = [i for i in retained if _near_duplicate(
                counts[candidate], len(actions[candidate]),
                [(len(actions[i]), counts[i])]
            )]
            if not overlaps or any(signatures[i] == signatures[candidate] for i in overlaps):
                continue
            if not covered_shapes <= {shape(i) for i in retained} | {shape(candidate)}:
                continue
            if not covered_resources <= {signatures[i] for i in retained} | {signatures[candidate]}:
                continue
            chosen[chosen.index(removed)] = candidate
            return {'chosen': chosen, 'swap': {'removed': removed, 'added': candidate}}
    return {'chosen': chosen, 'swap': None}


def test_signature_veto_off_admits_blocked_witness_only():
    rnd, actions = _synthetic_round(), _resource_actions()
    ranked, baseline = [0, 2, 1, 3, 4, 5, 6, 7], [0, 3]
    assert pair_resource_rank_repair(rnd, 1, actions, ranked, baseline) == {
        "chosen": [0, 1], "swap": {"removed": 3, "added": 1}}
    assert pair_resource_rank_repair(
        rnd, 1, actions, ranked, baseline, signature_overlap_veto=False
    ) == {"chosen": [0, 2], "swap": {"removed": 3, "added": 2}}


def test_signature_veto_nonbinding_swap_identical():
    rnd, actions = _synthetic_round(), _resource_actions()
    args = (rnd, 1, actions, list(range(8)), [0, 3])
    expected = {"chosen": [0, 1], "swap": {"removed": 3, "added": 1}}
    for veto in (True, False):
        assert pair_resource_rank_repair(
            *args, signature_overlap_veto=veto) == expected


@pytest.mark.parametrize("bad", [0, 1, None, "false"])
def test_signature_veto_requires_boolean(bad):
    with pytest.raises(ValueError, match="must be a bool"):
        pair_resource_rank_repair(
            _synthetic_round(), 1, _resource_actions(), list(range(8)),
            [0, 3], signature_overlap_veto=bad)


def test_default_byte_parity_and_both_mode_invariants_randomized():
    rng = random.Random(1105)
    rnd = _synthetic_round()
    fixed = _resource_actions()
    changed = 0
    for case in range(500):
        # Existing fixture pool and random unique hand-subset pools; synthetic,
        # not a claim of engine-legal play or sampled gameplay evidence.
        if case < 100:
            actions = copy.deepcopy(fixed)
        else:
            identities = {tuple(sorted(action)) for action in fixed}
            for _ in range(16):
                identities.add(tuple(sorted(rng.sample(rnd.hands[1], rng.randint(1, 5)))))
            actions = [list(action) for action in sorted(identities)]
        ranked = list(range(len(actions)))
        rng.shuffle(ranked)
        baseline = rng.sample(ranked, rng.randint(1, min(8, len(actions))))
        before = copy.deepcopy((rnd.hands, actions, ranked, baseline))
        args = (rnd, 1, actions, ranked, baseline)
        old = _frozen_s10_rank_repair(*args)
        default = pair_resource_rank_repair(*args)
        explicit = pair_resource_rank_repair(*args, signature_overlap_veto=True)
        assert json.dumps(default).encode() == json.dumps(old).encode()
        assert json.dumps(explicit).encode() == json.dumps(old).encode()
        _, signatures = _pair_inputs(rnd, 1, actions, ranked, baseline[0], len(baseline), 1)
        shapes = [structure_key(rnd, action) for action in actions]
        rank = {index: pos for pos, index in enumerate(ranked)}
        off = pair_resource_rank_repair(*args, signature_overlap_veto=False)
        changed += off != default
        for result in (default, off):
            chosen = result["chosen"]
            assert chosen[0] == baseline[0]
            assert len(chosen) == len(set(chosen)) == len(baseline)
            assert {shapes[i] for i in baseline} <= {shapes[i] for i in chosen}
            assert {signatures[i] for i in baseline} <= {signatures[i] for i in chosen}
            if result["swap"]:
                removed, added = result["swap"]["removed"], result["swap"]["added"]
                assert removed in baseline[1:] and added not in baseline
                assert rank[added] < rank[removed]
                assert len(set(chosen) - set(baseline)) == 1
                assert any(_near_duplicate(
                    Counter(actions[added]), len(actions[added]),
                    [(len(actions[i]), Counter(actions[i]))])
                    for i in baseline if i != removed)
        assert (rnd.hands, actions, ranked, baseline) == before
    assert changed > 0
