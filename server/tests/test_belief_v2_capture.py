"""All-rank capture/replay witnesses for the BELIEF-V1 V2 adapters."""

from __future__ import annotations

import os
from pathlib import Path
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
from shengji.rl.belief_v2_reference import (
    BeliefV2ReferenceError,
    capture_v2_ref_c_from_replay,
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


def test_v2_ref_c_uses_sealed_replay_without_play_search(monkeypatch):
    coordinate = next(row for row in v2_round_coordinates()
                      if row.trump_rank == "9"
                      and row.split == "calibration")
    seeds = v2_policy_seeds(coordinate)
    sealed = _capture_with_policies(
        coordinate.round_seed, CHAMPION_POLICY, seeds,
        [HeuristicBot() for _ in range(4)], actor_only=True,
        trump_rank=coordinate.trump_rank)
    assert type(sealed) is CapturedActorRoundV1
    monkeypatch.setattr(
        "shengji.rl.belief_v2_reference.make_bot",
        lambda *args, **kwargs: _NoPlaySearch())
    def target_tripwire(*args, **kwargs):
        raise AssertionError("V2 REF-C must not construct a target row")
    monkeypatch.setattr(
        "shengji.rl.belief_corpus.capture_corpus_pair", target_tripwire)
    monkeypatch.setattr(
        "shengji.rl.belief_contract.build_belief_targets", target_tripwire)
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    result = capture_v2_ref_c_from_replay(
        coordinate, sealed, replicate="calibration-replicate-0")
    assert result.captured == sealed
    assert len(result.batches) == len(sealed.actor_rows)
    assert all(len(batch.worlds) == 256 for batch in result.batches)


def test_v2_reference_source_has_no_target_or_full_capture_surface():
    import shengji.rl.belief_v2_reference as reference
    source = Path(reference.__file__).read_text(encoding="utf-8")
    for forbidden in (
            "capture_corpus_pair", "build_belief_targets", "target_rows",
            "CapturedBeliefRoundV1", "reopen_capture_bundle"):
        assert forbidden not in source


def test_v2_ref_c_refuses_train_or_wrong_replicate_before_replay():
    coordinate = next(row for row in v2_round_coordinates()
                      if row.split == "train")
    forged = CapturedActorRoundV1(
        round_seed=coordinate.round_seed, policy_name=CHAMPION_POLICY,
        policy_seeds=v2_policy_seeds(coordinate), actor_rows=(b"x",),
        public_transcript=None)  # type: ignore[arg-type]
    with pytest.raises(BeliefV2ReferenceError, match="replicate/split"):
        capture_v2_ref_c_from_replay(
            coordinate, forged, replicate="test-primary")
