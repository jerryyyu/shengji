"""Common-surface inference and exact V2 round-score witnesses."""

from __future__ import annotations

import hashlib
import random

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.engine.round import actual_play_after
from shengji.rl.belief_cohort import COHORT_SEEDS
from shengji.rl.belief_contract import (
    PublicTranscriptV1,
    build_information_partition,
)
from shengji.rl.belief_model import new_from_scratch_model
from shengji.rl.belief_refc_capture import capture_ref_c_worlds
from shengji.rl.belief_v2_accelerator import portable_model_state_sha256
from shengji.rl.belief_v2_common_surface import (
    build_common_surface_tensors,
    common_surface_actor,
)
from shengji.rl.belief_v2_human_corpus import UNIVERSAL_POLICY_IDS
from shengji.rl.belief_v2_scoring import (
    V2CohortModelsV1,
    V2ScoringDecisionV1,
    score_v2_round,
    v2_scoring_actor,
)


def _state(seed: int = 15001, plays: int = 5):
    rnd = Game(random.Random(seed)).start_round()
    bot = HeuristicBot()
    transcript = PublicTranscriptV1()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = bot.decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
            declaration = rnd.declaration
            transcript = transcript.with_declaration(
                declaration["seat"], declaration["cards"],
                declaration["strength"])
    for seat in range(4):
        cards = bot.decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
            declaration = rnd.declaration
            transcript = transcript.with_declaration(
                declaration["seat"], declaration["cards"],
                declaration["strength"])
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
    for _ in range(plays):
        seat = rnd.turn
        attempted = bot.decide_play(rnd, seat)
        previous = rnd.last_trick
        rnd.play(seat, attempted)
        transcript = transcript.with_play(
            seat, attempted, actual_play_after(rnd, seat, previous))
    partition = build_information_partition(rnd, rnd.turn, transcript)
    return rnd, transcript, partition


def _cohort() -> V2CohortModelsV1:
    models = tuple(new_from_scratch_model(seed) for seed in COHORT_SEEDS)
    return V2CohortModelsV1(
        cohort_id="synthetic-primary-v2",
        models=models,
        model_sha256s=tuple(portable_model_state_sha256(model)
                            for model in models))


def test_v2_round_scoring_uses_common_surface_and_corrected_ref_c(
        monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    rnd, transcript, partition = _state()
    reference = capture_ref_c_worlds(
        rnd, rnd.turn, transcript, sampler_seed=17001)
    common = build_common_surface_tensors(
        partition.actor, behavior_policy_ids=UNIVERSAL_POLICY_IDS)
    decision = V2ScoringDecisionV1(
        decision_key="a" * 64, source_actor=partition.actor,
        target=partition.targets, common=common, reference=reference)
    row = score_v2_round(
        round_key=hashlib.sha256(b"synthetic-round").hexdigest(),
        source_kind="synthetic", split="calibration",
        trump_rank=rnd.trump_rank, decisions=(decision,),
        cohorts=(_cohort(),))
    scoring_actor = v2_scoring_actor(partition.actor)
    assert scoring_actor.sha256() != partition.actor.sha256()
    assert all(not play.attempted_cards
               for trick in (*scoring_actor.completed_tricks,
                              scoring_actor.current_trick)
               for play in trick.plays)
    assert row.decision_count == 1
    assert row.reference_brier_ppb >= 0
    assert row.cohort_brier_ppb[0][0] == "synthetic-primary-v2"
    assert len(row.cohort_member_brier_ppb[0][1]) == len(COHORT_SEEDS)


def test_incomplete_human_style_actor_reuses_identical_common_scoring_surface(
        monkeypatch):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    rnd, transcript, partition = _state(15003)
    reference = capture_ref_c_worlds(
        rnd, rnd.turn, transcript, sampler_seed=17003)
    incomplete = common_surface_actor(partition.actor)
    assert incomplete.declaration_history_complete is False
    assert incomplete.attempted_play_history_complete is False
    common = build_common_surface_tensors(
        incomplete, behavior_policy_ids=UNIVERSAL_POLICY_IDS)
    row = score_v2_round(
        round_key=hashlib.sha256(b"human-round").hexdigest(),
        source_kind="human", split="calibration",
        trump_rank=rnd.trump_rank,
        decisions=(V2ScoringDecisionV1(
            decision_key="b" * 64, source_actor=incomplete,
            target=partition.targets, common=common,
            reference=reference),),
        cohorts=(_cohort(),))
    assert row.source_kind == "human"
    assert v2_scoring_actor(incomplete).canonical_bytes() \
        == v2_scoring_actor(partition.actor).canonical_bytes()
