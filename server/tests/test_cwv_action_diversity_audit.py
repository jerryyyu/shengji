"""Pure contracts for the research-only effective-action diversity ablation."""

import copy

import pytest

from shengji.ai.registry import REGISTRY
from shengji.train.cwv_action_diversity_audit import (
    accepted_action_signatures,
    diverse_topk_with_incumbent,
)
from tests.test_invariants import _find_failing_throw, _room_at_play
from tests.test_world_shortlist import fixed_world, play_state


def test_full_world_vector_beats_first_world_only_cutoff_mutant():
    actions = [["A"], ["B"], ["C"]]
    signatures = [(("x",), ("left",)), (("x",), ("right",)),
                  (("y",), ("other",))]
    # A and B coincide only on the first sampled world.  The baseline and the
    # full-vector diversity rule retain B; a first-world-only mutant picks C.
    assert diverse_topk_with_incumbent(
        actions, [3.0, 2.0, 1.0], actions[0], signatures, alternatives=1) == [0, 1]


def test_equal_value_distinct_signature_beats_scalar_value_dedup_mutant():
    actions = [["A"], ["B"], ["C"], ["D"]]
    signatures = [(("a",),), (("b",),), (("c",),), (("d",),)]
    # B/C tie at the cutoff: score-based dedup would backfill D, while
    # effective-action diversity must retain both distinct vectors.
    assert diverse_topk_with_incumbent(
        actions, [10.0, 9.0, 9.0, 8.0], actions[0], signatures,
        alternatives=2) == [0, 1, 2]


def test_backfill_same_set_keeps_exact_baseline_nonincumbent_order():
    actions = [["A"], ["B"], ["C"], ["D"]]
    signatures = [(("a",),), (("b",),), (("a",),), (("d",),)]
    # D supplies the final distinct class and C then backfills the requested
    # cardinality; output remains in the baseline order A, B, C, D.
    assert diverse_topk_with_incumbent(
        actions, [4.0, 3.0, 2.0, 1.0], actions[0], signatures,
        alternatives=3) == [0, 1, 2, 3]


def test_incumbent_alias_is_skipped_when_distinct_classes_are_available():
    actions = [["A"], ["B"], ["C"], ["D"]]
    signatures = [(("same",),), (("same",),), (("new",),), (("other",),)]
    assert diverse_topk_with_incumbent(
        actions, [4.0, 3.0, 2.0, 1.0], actions[0], signatures, alternatives=2) == [0, 2, 3]


def test_signature_vectors_must_share_the_same_world_count():
    with pytest.raises(ValueError, match="sampled-world population"):
        diverse_topk_with_incumbent(
            [["A"], ["B"]], [1.0, 0.0], ["A"],
            [(("a",),), (("b",), ("b",))], alternatives=1)


def test_actual_failed_throw_signature_uses_engine_accepted_action_and_preserves_state():
    _room, rnd = _room_at_play(5)
    seat = rnd.turn
    candidate, expected = _find_failing_throw(rnd, seat)
    assert candidate is not None, "seed 5 must provide the failed-throw witness"
    world = fixed_world(rnd, seat)
    before = copy.deepcopy(rnd)
    signatures = accepted_action_signatures(rnd, seat, [candidate], [world, world])
    assert signatures == ((tuple(sorted(expected)), tuple(sorted(expected))),)
    assert signatures[0][0] != tuple(sorted(candidate))
    assert rnd.hands == before.hands
    assert rnd.trick.plays == before.trick.plays


def test_signatures_retain_repeated_worlds_and_actions_are_real_ballot_inputs():
    rnd = play_state()
    seat = rnd.turn
    actions = REGISTRY["mc-s0-report-lcb"](seed=3)._candidates(rnd, seat)[:2]
    world = fixed_world(rnd, seat)
    signatures = accepted_action_signatures(rnd, seat, actions, [world, world])
    assert len(signatures) == len(actions)
    assert all(len(signature) == 2 for signature in signatures)
    assert all(signature[0] == signature[1] for signature in signatures)
