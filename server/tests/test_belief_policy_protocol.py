"""Opened-DEV R4 policy coordinate and RNG separation witnesses."""

from __future__ import annotations

from shengji.rl.belief_policy_protocol import (
    CAPACITY_ROUND_COUNT,
    CANDIDATE_ROUNDS_PER_RANK,
    FOLD_LABELS,
    POLICY_RANKS,
    TARGET_ROUND_COUNT,
    policy_capacity_coordinates,
    policy_fold_seed,
    policy_rank_coordinates,
    policy_root_order_key,
    policy_round_coordinates,
    policy_seat_seeds,
)
from shengji.rl.belief_v2_protocol import (
    V1_B2_SEED_END,
    V1_B2_SEED_START,
    v2_round_coordinates,
)


def test_candidate_population_is_balanced_unique_and_disjoint_from_r4():
    rows = policy_round_coordinates()
    assert len(rows) == len(POLICY_RANKS) * CANDIDATE_ROUNDS_PER_RANK
    assert len({row.round_seed for row in rows}) == len(rows)
    assert all(len(policy_rank_coordinates(rank))
               == CANDIDATE_ROUNDS_PER_RANK for rank in POLICY_RANKS)
    assert TARGET_ROUND_COUNT == 104
    r4_seeds = {row.round_seed for row in v2_round_coordinates()}
    assert not ({row.round_seed for row in rows} & r4_seeds)
    assert all(not V1_B2_SEED_START <= row.round_seed <= V1_B2_SEED_END
               for row in rows)


def test_policy_and_fold_streams_are_domain_separated():
    coordinate = policy_round_coordinates()[0]
    actor = "a" * 64
    seats = policy_seat_seeds(coordinate)
    folds = tuple(policy_fold_seed(
        coordinate, decision_index=7, actor_sha256=actor, fold=fold)
        for fold in FOLD_LABELS)
    assert len(set((*seats, *folds, coordinate.round_seed))) == 8
    assert policy_root_order_key(
        coordinate, decision_index=7, actor_sha256=actor) \
        != policy_root_order_key(
            coordinate, decision_index=8, actor_sha256=actor)


def test_capacity_namespace_is_fixed_and_disjoint():
    scientific = {row.round_seed for row in policy_round_coordinates()}
    capacity = policy_capacity_coordinates()
    assert len(capacity) == CAPACITY_ROUND_COUNT
    assert len({row.round_seed for row in capacity}) == len(capacity)
    assert not scientific.intersection(row.round_seed for row in capacity)
    assert all(len(set((*policy_seat_seeds(row), row.round_seed))) == 5
               for row in capacity)
