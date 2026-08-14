"""Canonical B2 population/protocol derivation tests."""

from __future__ import annotations

import hashlib

import pytest

from shengji.rl.belief_b2_protocol import (
    B2_CAPTURE_LANES,
    B2_REFERENCE_REPLICATES,
    B2_ROUND_COUNT,
    B2_ROUNDS_PER_LANE,
    B2_SEED_START,
    B2_SPLIT_COUNTS,
    BeliefB2ProtocolError,
    b2_round_seeds,
    capture_lane,
    champion_policy_seeds,
    protocol_bytes,
    protocol_dict,
    protocol_sha256,
    reference_sampler_seed,
)
from shengji.rl.belief_corpus import decision_key, split_for_round_seed


EXPECTED_PROTOCOL_SHA256 = (
    "223ecb7f67aec4e254ee5fddea5b248530061c32b3a61beed4373d483f212de3")


def test_population_splits_lanes_and_policy_seeds_are_exact():
    seeds = b2_round_seeds()
    assert len(seeds) == B2_ROUND_COUNT
    assert seeds[0] == B2_SEED_START
    assert seeds[-1] == B2_SEED_START + B2_ROUND_COUNT - 1
    assert tuple((split, sum(split_for_round_seed(seed) == split
                             for seed in seeds))
                 for split, _ in B2_SPLIT_COUNTS) == B2_SPLIT_COUNTS
    assert tuple(sum(capture_lane(seed) == lane for seed in seeds)
                 for lane in range(B2_CAPTURE_LANES)) \
        == (B2_ROUNDS_PER_LANE,) * B2_CAPTURE_LANES
    for seed in seeds:
        policy_seeds = champion_policy_seeds(seed)
        assert len(policy_seeds) == len(set(policy_seeds)) == 4
        assert all(type(value) is int and 0 <= value < 2**63
                   for value in policy_seeds)


def test_reference_seeds_are_deterministic_domain_separated_and_strict():
    keys = tuple(decision_key(B2_SEED_START + offset, offset, offset % 4)
                 for offset in range(64))
    values = tuple(reference_sampler_seed(key, replicate)
                   for key in keys for replicate in B2_REFERENCE_REPLICATES)
    assert len(values) == len(set(values))
    assert values == tuple(reference_sampler_seed(key, replicate)
                           for key in keys
                           for replicate in B2_REFERENCE_REPLICATES)
    for bad_key in ("", "A" * 64, "0" * 63, True):
        with pytest.raises(BeliefB2ProtocolError, match="seed input"):
            reference_sampler_seed(bad_key, B2_REFERENCE_REPLICATES[0])
    with pytest.raises(BeliefB2ProtocolError, match="seed input"):
        reference_sampler_seed(keys[0], "unknown")


def test_canonical_protocol_is_pinned_and_authorizes_nothing():
    payload = protocol_dict()
    assert protocol_sha256() == hashlib.sha256(protocol_bytes()).hexdigest()
    assert protocol_sha256() == EXPECTED_PROTOCOL_SHA256
    assert set(payload["authority"].values()) == {False}
    assert payload["capture"]["retry_count"] == 0
    assert payload["capture"]["drop_count"] == 0
    assert payload["training"]["retry_count"] == 0
    assert payload["training"]["candidate_member_count"] == 8
    assert payload["training"][
        "hard_geometry_permuted_label_member_count"] == 8
    assert payload["training"][
        "history_chronology_ablation_is_inference_only"] is True
    assert payload["primary_gate"] == {
        "metric": "paired-per-round-hidden-ownership-count-brier",
        "reference_minus_candidate_mean_relative_floor_ppb": 5_000_000,
        "one_sided_95_percent_lower_bound_strictly_positive": True,
        "round_bootstrap_replicates": 20_000,
        "round_bootstrap_seed": 4_654_505_738_542_866_658,
        "positive_member_mean_minimum": 6,
        "member_count": 8,
        "mean_smoothed_log_loss_improvement_nonnegative": True,
    }


def test_population_refuses_bool_float_and_outside_seed():
    for bad in (True, float(B2_SEED_START), B2_SEED_START - 1,
                B2_SEED_START + B2_ROUND_COUNT):
        with pytest.raises(BeliefB2ProtocolError, match="outside"):
            capture_lane(bad)
