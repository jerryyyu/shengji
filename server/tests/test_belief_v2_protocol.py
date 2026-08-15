"""Exact population and authority witnesses for the BELIEF-V1 V2 proposal."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace

import pytest

from shengji.engine.cards import RANKS
from shengji.rl.belief_corpus import split_for_round_seed
from shengji.rl.belief_v2_protocol import (
    HUMAN_V8_ACCEPTED_BURIES,
    HUMAN_V8_ACCEPTED_PLAYS,
    HUMAN_V8_INCOMPLETE_ROUNDS,
    HUMAN_V8_ROUNDS_REPLAYED,
    HUMAN_V8_ROUNDS_SEEN,
    V1_B2_SEED_END,
    V1_B2_SEED_START,
    V2_CAPTURE_LANES,
    V2_ROUND_COUNT,
    V2_ROUNDS_PER_LANE_RANK,
    V2_ROUNDS_PER_RANK,
    V2_RANKS,
    V2_SPLIT_COUNTS,
    V2_SPLIT_COUNTS_PER_RANK,
    BeliefV2ProtocolError,
    protocol_dict,
    protocol_sha256,
    schedule_sha256,
    v2_policy_seeds,
    v2_research_round,
    v2_round_coordinate,
    v2_round_coordinates,
)


EXPECTED_SCHEDULE_SHA256 = (
    "eea7d9581ce32cbce2c138977c4d1acd21f987c2076820f32ab9ca5d470ee4b6")
EXPECTED_PROTOCOL_SHA256 = (
    "a45903a79a9302c61201b428b01a97b7e9bf34d2c5b5478618331e1ce1a13b03")


def test_population_is_exactly_balanced_before_any_deal_is_opened():
    rows = v2_round_coordinates()
    assert v2_round_coordinates() is rows
    assert len(rows) == V2_ROUND_COUNT == 13_312
    assert V2_RANKS == tuple(RANKS)
    assert len({row.round_seed for row in rows}) == len(rows)
    assert all(not V1_B2_SEED_START <= row.round_seed <= V1_B2_SEED_END
               for row in rows)
    assert Counter(row.trump_rank for row in rows) \
        == Counter({rank: V2_ROUNDS_PER_RANK for rank in V2_RANKS})
    assert Counter(row.split for row in rows) == Counter(dict(V2_SPLIT_COUNTS))
    for rank in V2_RANKS:
        rank_rows = [row for row in rows if row.trump_rank == rank]
        assert Counter(row.split for row in rank_rows) \
            == Counter(dict(V2_SPLIT_COUNTS_PER_RANK))
        assert Counter(row.lane for row in rank_rows) == Counter({
            lane: V2_ROUNDS_PER_LANE_RANK
            for lane in range(V2_CAPTURE_LANES)})
    assert all(row.split == split_for_round_seed(row.round_seed)
               for row in rows)


def test_ranked_round_factory_preserves_first_round_semantics_and_seed():
    for rank in V2_RANKS:
        coordinate = next(row for row in v2_round_coordinates()
                          if row.trump_rank == rank)
        first = v2_research_round(coordinate)
        second = v2_research_round(coordinate)
        assert first.trump_rank == rank
        assert first.banker is None and first.first_round is True
        assert first.phase == "deal" and first.turn is None
        assert first.deck == second.deck
        assert first.deck is not second.deck


def test_coordinate_and_policy_seed_derivations_refuse_forgery():
    coordinate = v2_round_coordinates()[0]
    policy_seeds = v2_policy_seeds(coordinate)
    assert len(policy_seeds) == len(set(policy_seeds)) == 4
    assert coordinate.round_seed not in policy_seeds
    assert v2_round_coordinate(
        coordinate.trump_rank, coordinate.rank_ordinal) == coordinate
    for bad_rank, bad_ordinal in (
            (True, 0), ("1", 0), (coordinate.trump_rank, True),
            (coordinate.trump_rank, -1),
            (coordinate.trump_rank, V2_ROUNDS_PER_RANK)):
        with pytest.raises(BeliefV2ProtocolError, match="coordinate"):
            v2_round_coordinate(bad_rank, bad_ordinal)
    forged = replace(coordinate, split=(
        "test" if coordinate.split != "test" else "train"))
    with pytest.raises(BeliefV2ProtocolError, match="derivation drift"):
        v2_research_round(forged)
    with pytest.raises(BeliefV2ProtocolError, match="derivation drift"):
        v2_policy_seeds(forged)


def test_human_asset_is_descriptive_and_carries_no_training_authority():
    payload = protocol_dict()
    human = payload["human_input"]
    assert (HUMAN_V8_ROUNDS_SEEN, HUMAN_V8_ROUNDS_REPLAYED,
            HUMAN_V8_INCOMPLETE_ROUNDS) == (129, 122, 7)
    assert (HUMAN_V8_ACCEPTED_PLAYS, HUMAN_V8_ACCEPTED_BURIES) == (2_830, 45)
    assert human["starting_asset_training_authorized"] is False
    assert human["v2_belief_training_authorized"] is False


def test_protocol_is_pinned_parallelizes_only_after_capture_and_authorizes_nothing():
    payload = protocol_dict()
    assert schedule_sha256() == EXPECTED_SCHEDULE_SHA256
    assert protocol_sha256() == EXPECTED_PROTOCOL_SHA256
    assert payload["status"] == "source-design-proposal-not-execution-freeze"
    assert payload["reference"]["training_dependency"] is False
    assert payload["parallel_after_capture"] == [
        "synthetic-only-training",
        "bounded-human-mixture-training",
        "ref-c-transcript-replay",
    ]
    assert payload["freeze_inputs_missing"]
    assert set(payload["authority"].values()) == {False}
