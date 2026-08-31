"""Literal production-world batch and proposal-marginal witnesses."""

from __future__ import annotations

import random

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.registry import make_bot
from shengji.engine.game import Game
from shengji.engine.round import actual_play_after
from shengji.rl.belief_capture import CHAMPION_POLICY
from shengji.rl.belief_contract import PublicTranscriptV1, build_actor_observation
from shengji.rl.belief_policy_worlds import (
    PRODUCTION_PROPOSAL_MODEL_SCHEMA,
    production_proposal_ownership,
    production_relative_world,
    sample_production_worlds,
    validate_production_world_batch,
)


def _state(seed: int = 19201):
    rnd = Game(random.Random(seed)).start_round()
    bot = HeuristicBot()
    while rnd.phase == "deal":
        rnd.deal_next()
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
    transcript = PublicTranscriptV1()
    seat = rnd.turn
    attempted = bot.decide_play(rnd, seat)
    previous = rnd.last_trick
    rnd.play(seat, attempted)
    transcript = transcript.with_play(
        seat, attempted, actual_play_after(rnd, seat, previous))
    return rnd, transcript


def test_batch_replays_the_world_stream_seen_by_production_decision(
        monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    rnd, transcript = _state()
    seat = rnd.turn
    actor = build_actor_observation(rnd, seat, transcript)
    policy = make_bot(CHAMPION_POLICY, seed=8123)
    policy.N_DETERMINIZATIONS = 3
    policy.REPORT_FOLD_WORLDS = 0
    policy.REPORT_RULE = "none"
    recorded = []
    original = policy._sample_hands

    def capture(round_state, acting_seat, memory):
        sampled = original(round_state, acting_seat, memory)
        if sampled is not None:
            recorded.append(production_relative_world(
                actor, acting_seat, sampled[0], sampled[1]))
        return sampled

    policy._sample_hands = capture
    policy.decide_play(rnd, seat)
    assert policy.last_n_worlds == 3
    batch = sample_production_worlds(
        rnd, seat, transcript, sampler_seed=8123, world_count=3)
    assert tuple(world.canonical_bytes() for world in batch.worlds) \
        == tuple(world.canonical_bytes() for world in recorded[:3])


def test_256_world_batch_builds_strict_production_proposal_marginals(
        monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    rnd, transcript = _state(19203)
    batch = sample_production_worlds(
        rnd, rnd.turn, transcript, sampler_seed=8125, world_count=256)
    validate_production_world_batch(batch)
    belief = production_proposal_ownership(batch)
    assert belief.model_schema == PRODUCTION_PROPOSAL_MODEL_SCHEMA
    assert belief.actor_observation_sha256 == batch.actor.sha256()
    assert batch.manifest_dict()["accepted_world_count"] == 256
    assert batch.manifest_dict()["contains_round_outcome"] is False
