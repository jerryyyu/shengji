"""Exact enumerable-posterior control tests for BELIEF-V1 B2."""

from __future__ import annotations

import copy
import random
from dataclasses import replace

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.engine.round import actual_play_after
from shengji.rl.belief_contract import PublicTranscriptV1, build_actor_observation
from shengji.rl.belief_corpus import capture_corpus_pair
from shengji.rl.belief_projection import (project_count_weights,
                                          uniform_raw_count_weights)
from shengji.rl.belief_evaluation import reopen_score_pair
from shengji.rl.belief_synthetic import (
    C4_BEHAVIOR_POLICY_IDS,
    C4_CONTEXT_IDS,
    C4_MAX_EVENT_ERROR_PPB,
    C4_MAX_ROW_TOTAL_VARIATION_PPB,
    BeliefSyntheticError,
    C4PublicTwinContextV1,
    C4SyntheticEvidenceV1,
    run_c4_synthetic_pipeline,
    validate_c4_synthetic_evidence,
)


def _context(context_index: int) -> C4PublicTwinContextV1:
    seed = (10405, 10407, 10409, 10415)[context_index]
    plays = 5 + context_index
    rnd = Game(random.Random(seed)).start_round()
    bot = HeuristicBot()
    transcript = PublicTranscriptV1()
    while rnd.phase == "deal":
        rnd.deal_next()
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
    for _ in range(plays):
        seat = rnd.turn
        attempted = bot.decide_play(rnd, seat)
        previous_last = rnd.last_trick
        rnd.play(seat, attempted)
        transcript = transcript.with_play(
            seat, attempted, actual_play_after(
                rnd, seat, previous_last))
    actor = build_actor_observation(rnd, rnd.turn, transcript)
    changed = copy.deepcopy(rnd)
    hidden = [seat for seat in range(4) if seat != rnd.turn]
    left, right = next(
        (left, right) for index, left in enumerate(hidden)
        for right in hidden[index + 1:]
        if len(changed.hands[left]) == len(changed.hands[right]))
    changed.hands[left], changed.hands[right] = (
        changed.hands[right], changed.hands[left])
    assert build_actor_observation(
        changed, rnd.turn, transcript).canonical_bytes() \
        == actor.canonical_bytes()
    pairs = tuple(capture_corpus_pair(
        world, rnd.turn, round_seed=seed, decision_index=plays,
        transcript=transcript) for world in (rnd, changed))
    return C4PublicTwinContextV1(
        context_id=C4_CONTEXT_IDS[context_index],
        world_0=pairs[0], world_1=pairs[1])


@pytest.fixture(scope="module")
def evidence() -> C4SyntheticEvidenceV1:
    return run_c4_synthetic_pipeline(tuple(
        _context(index) for index in range(len(C4_CONTEXT_IDS))))


def test_exact_synthetic_pipeline_recovers_enumerated_posterior(evidence):
    validate_c4_synthetic_evidence(evidence)
    result = evidence.result
    assert result.passed is True
    assert result.max_event_probability_error_ppb \
        <= C4_MAX_EVENT_ERROR_PPB
    assert result.max_row_total_variation_ppb \
        <= C4_MAX_ROW_TOTAL_VARIATION_PPB
    assert result.posterior_world_weights == (3, 1)
    assert result.posterior_denominator == 4
    assert result.train_row_count == 4096
    assert result.batch_count == 256
    assert result.epoch_count == 30
    payload = result.to_dict()
    assert payload["training"] == {
        **payload["training"],
        "same_actor_encoder": True,
        "same_ownership_model": True,
        "same_adamw_step": True,
        "same_count_head": True,
        "same_exact_projection": True,
    }
    assert not any(payload[key] for key in (
        "sampler_implementation_authorized", "gameplay_authorized",
        "strength_claim_authorized", "promotion_authorized",
        "deployment_authorized"))


def test_uniform_no_learning_control_fails_exact_posterior(evidence):
    candidates = []
    for context in evidence.contexts:
        actor, _, _ = reopen_score_pair(context.world_0)
        candidates.append(project_count_weights(
            actor, behavior_policy_ids=C4_BEHAVIOR_POLICY_IDS,
            model_schema=evidence.candidates[0].model_schema,
            model_sha256=evidence.result.model_state_sha256,
            raw_weights=uniform_raw_count_weights(
                actor, behavior_policy_ids=C4_BEHAVIOR_POLICY_IDS)))
    forged = replace(evidence, candidates=tuple(candidates))
    with pytest.raises(BeliefSyntheticError, match="derivation drift"):
        validate_c4_synthetic_evidence(forged)


def test_context_and_result_mutations_refuse(evidence):
    with pytest.raises(BeliefSyntheticError, match="population/order"):
        run_c4_synthetic_pipeline(tuple(reversed(evidence.contexts)))
    same_target = replace(
        evidence.contexts[0], world_1=evidence.contexts[0].world_0)
    with pytest.raises(BeliefSyntheticError, match="distinct targets"):
        run_c4_synthetic_pipeline(
            (same_target, *evidence.contexts[1:]))
    changed_result = replace(
        evidence.result,
        max_event_probability_error_ppb=(
            evidence.result.max_event_probability_error_ppb + 1))
    with pytest.raises(BeliefSyntheticError, match="derivation drift"):
        validate_c4_synthetic_evidence(replace(
            evidence, result=changed_result))
