"""One-root end-to-end R4 policy mechanism witness."""

from __future__ import annotations

import copy

import pytest

from shengji.ai.mcbot import MCBot
from shengji.rl import belief_policy_population as population
from shengji.rl.belief_capture import CHAMPION_POLICY
from shengji.rl.belief_cohort import COHORT_SEEDS
from shengji.rl.belief_model import new_from_scratch_model
from shengji.rl.belief_policy_artifacts import (
    BeliefPolicyArtifactError,
    build_policy_root_result,
    publish_policy_root_result,
    reopen_policy_root_result,
    validate_policy_root_result,
)
from shengji.rl.belief_policy_evaluation import evaluate_policy_root
from shengji.rl.belief_policy_protocol import policy_round_coordinates
from shengji.rl.belief_v2_accelerator import portable_model_state_sha256
from shengji.rl.belief_v2_freeze import CONTROL_COHORT_ID, PRIMARY_COHORT_ID
from shengji.rl.belief_v2_scoring import V2CohortModelsV1


class _FastCapturePolicy(MCBot):
    N_DETERMINIZATIONS = 1
    REQUIRE_EXACT_WORK = False
    REPORT_FOLD_WORLDS = 0
    REPORT_RULE = "none"


def _fast_make_bot(name: str, **kwargs):
    assert name == CHAMPION_POLICY
    bot = _FastCapturePolicy(seed=kwargs.get("seed"))
    bot.policy_name = name
    return bot


def _cohort(cohort_id: str, offset: int) -> V2CohortModelsV1:
    models = tuple(new_from_scratch_model(seed + offset)
                   for seed in COHORT_SEEDS)
    return V2CohortModelsV1(
        cohort_id=cohort_id,
        models=models,
        model_sha256s=tuple(portable_model_state_sha256(model)
                            for model in models),
    )


def test_one_root_shares_exact_worlds_work_and_legal_ballot(
        monkeypatch, tmp_path):
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    monkeypatch.setattr(population, "make_bot", _fast_make_bot)
    root = population.select_natural_policy_root(
        policy_round_coordinates()[0])
    assert root is not None
    primary = _cohort(PRIMARY_COHORT_ID, 0)
    control = _cohort(CONTROL_COHORT_ID, 10_000)
    result = evaluate_policy_root(root, primary=primary, control=control)
    assert len(result.reference_batch.worlds) == 256
    assert len(result.selection_batch.worlds) == 30
    assert len(result.report_batch.worlds) == 300
    assert result.primary_selection_weights.alpha_ppb \
        == result.control_selection_weights.alpha_ppb
    assert result.primary_report_weights.alpha_ppb \
        == result.control_report_weights.alpha_ppb
    assert all(0 <= row.played_index < len(root.candidates)
               for row in result.decisions)
    assert result.work.selection_physical_rollouts \
        == 30 * len(root.candidates)
    assert result.work.report_logical_rollouts_per_arm == 600
    assert set(index for index, _ in result.report_values_by_candidate) \
        == {0, *(row.nomination.challenger_index
                 for row in result.decisions)}
    assert 0 <= result.true_world_oracle_index < len(root.candidates)
    path = tmp_path / "root-result.json"
    digest = publish_policy_root_result(
        path, result, primary=primary, control=control)
    reopened = reopen_policy_root_result(path)
    assert len(digest) == 64
    assert reopened["actor_sha256"] == root.actor.sha256()
    assert reopened["r4_test_opened"] is False

    forged = copy.deepcopy(build_policy_root_result(
        result, primary=primary, control=control))
    forged["decisions"][0]["played_index"] = (
        1 - forged["decisions"][0]["played_index"])
    with pytest.raises(BeliefPolicyArtifactError,
                       match="decision reconstruction"):
        validate_policy_root_result(forged)

    forged = copy.deepcopy(build_policy_root_result(
        result, primary=primary, control=control))
    forged["weights"]["selection_primary"]["untempered_ess_ppb"] += 1
    with pytest.raises(BeliefPolicyArtifactError,
                       match="common temperature reconstruction drift"):
        validate_policy_root_result(forged)

    capacity = evaluate_policy_root(
        root, primary=primary, control=control, privileged_truth=False)
    assert capacity.true_world_is_privileged is False
    with pytest.raises(BeliefPolicyArtifactError,
                       match="requires privileged scientific truth"):
        build_policy_root_result(
            capacity, primary=primary, control=control)
