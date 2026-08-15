"""All-rank capture/replay witnesses for the BELIEF-V1 V2 adapters."""

from __future__ import annotations

import os
from dataclasses import replace

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.rl.belief_capture import (
    CHAMPION_POLICY,
    CapturedActorRoundV1,
    _capture_with_policies,
)
from shengji.rl.belief_refc_replay import replay_actor_round
from shengji.rl.belief_v2_capture import (
    BeliefV2CaptureError,
    capture_v2_champion_actor_round,
    replay_v2_champion_actor_round,
)
from shengji.rl.belief_v2_protocol import (
    V2_RANKS,
    v2_policy_seeds,
    v2_round_coordinates,
)


class _NoPlaySearch(HeuristicBot):
    def decide_play(self, rnd, seat):
        raise AssertionError("V2 replay must not invoke play search")


def test_every_rank_capture_replays_byte_identically_without_play_search():
    for rank in V2_RANKS:
        coordinate = next(row for row in v2_round_coordinates()
                          if row.trump_rank == rank)
        seeds = v2_policy_seeds(coordinate)
        captured = _capture_with_policies(
            coordinate.round_seed, CHAMPION_POLICY, seeds,
            [HeuristicBot() for _ in range(4)], actor_only=True,
            trump_rank=rank)
        assert type(captured) is CapturedActorRoundV1
        replayed = replay_actor_round(
            round_seed=coordinate.round_seed,
            policy_name=CHAMPION_POLICY,
            policy_seeds=seeds,
            policies=[_NoPlaySearch() for _ in range(4)],
            sealed=captured,
            trump_rank=rank)
        assert replayed == captured
        assert replayed.actor_rows == captured.actor_rows
        assert replayed.public_transcript == captured.public_transcript


def test_v2_adapter_refuses_forged_coordinate_before_capture():
    coordinate = v2_round_coordinates()[0]
    forged = replace(coordinate, trump_rank=V2_RANKS[1])
    with pytest.raises(BeliefV2CaptureError, match="coordinate derivation"):
        capture_v2_champion_actor_round(forged)


@pytest.mark.skipif(
    os.environ.get("SHENGJI_FAST") != "1",
    reason="exact V2 champion replay witness is pinned to compiled mode",
)
def test_one_non_two_exact_v2_champion_round_replays_without_search():
    coordinate = next(row for row in v2_round_coordinates()
                      if row.trump_rank == "9")
    sealed = capture_v2_champion_actor_round(coordinate)
    replayed = replay_v2_champion_actor_round(coordinate, sealed)
    assert replayed == sealed
    assert replayed.policy_name == CHAMPION_POLICY
