"""Exact enumerable-posterior control tests for BELIEF-V1 B2."""

from __future__ import annotations

from dataclasses import replace

import pytest

from shengji.rl.belief_projection import (project_count_weights,
                                          uniform_raw_count_weights)
from shengji.rl.belief_evaluation import reopen_score_pair
from shengji.rl.belief_synthetic import (
    C4_BEHAVIOR_POLICY_IDS,
    C4_CONTEXT_IDS,
    C4_MAX_EVENT_ERROR_PPB,
    C4_MAX_ROW_TOTAL_VARIATION_PPB,
    BeliefSyntheticError,
    C4SyntheticEvidenceV1,
    build_c4_contexts,
    run_c4_synthetic_pipeline,
    validate_c4_synthetic_evidence,
)


@pytest.fixture(scope="module")
def evidence() -> C4SyntheticEvidenceV1:
    return run_c4_synthetic_pipeline(build_c4_contexts())


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
