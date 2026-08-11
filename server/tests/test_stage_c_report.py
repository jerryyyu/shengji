from __future__ import annotations

import copy

import pytest

from shengji.rl import stage_c_model as MODEL
from shengji.rl import stage_c_report as REPORT


def _distribution(bucket: int, epsilon: float = 1e-5) -> list[float]:
    values = [epsilon] * len(MODEL.UTILITY_BINS)
    values[bucket] = 1.0 - epsilon * (len(values) - 1)
    return values


def _example(index: int, *, surface: str = "play") -> dict:
    target = {
        "candidate_count": 2,
        "ranking_mean_signed_level_utility": [-0.5, 1.5],
        "outcome_distribution": [
            MODEL.utility_distribution([-0.5] * 64),
            MODEL.utility_distribution([1.5] * 64),
        ],
        "frozen_label_index": 1,
    }
    return {
        "state_id": f"report:{surface}:{index}",
        "split": "REPORT",
        "surface_type": surface,
        "stratum": "proposal_disagreement",
        "target": target,
    }


def _members(examples, *, choose_one: bool = True,
             calibrated: bool = True):
    values = []
    for seed_index in range(8):
        ranks = []
        outcomes = []
        for _example_value in examples:
            ranks.append([0.0, 2.0] if choose_one else [2.0, 0.0])
            if calibrated:
                outcomes.append([_distribution(3), _distribution(5)])
            else:
                # Candidate one remains larger in expected utility but both
                # distributions are badly wrong relative to the targets.
                outcomes.append([_distribution(0), _distribution(1)])
        values.append((ranks, outcomes))
    return values


def _protected_policy() -> dict:
    return {
        "schema": REPORT.PROTECTED_POLICY_SCHEMA,
        "surface": "play",
        "head": "ranking",
        "ensemble": "arithmetic_mean_raw_rank_logits_across_eight_seeds",
        "incumbent_index": 0,
        "alternative_start_index": 1,
        "threshold": 0.2,
        "strict_greater_than_threshold": True,
        "alternative_tie_break": "lowest_candidate_index",
        "fallback_index": 0,
        "bury_behavior": "unchanged_incumbent",
    }


def test_report_ranking_capability_passes_with_positive_paired_lcb() -> None:
    examples = [_example(index) for index in range(40)]
    result = REPORT.evaluate_capability(
        examples, _members(examples), surface="play", head="ranking",
        prior_distribution=[1 / 8] * 8)
    assert result["decision"] \
        == "AUTHORIZE_STAGE_C_COMPOSITION_PACKET_REVIEW"
    assert result["teacher_improvement_vs_candidate0"][
        "one_sided_95_lcb"] == pytest.approx(2.0)
    assert result["proposal_triggers"] == 40
    assert result["ensemble_seeds"] == list(MODEL.TRAINING_SEEDS)
    assert result["strength_claim"] is False


def test_report_rejects_candidate_zero_or_short_ensemble() -> None:
    examples = [_example(index) for index in range(40)]
    rejected = REPORT.evaluate_capability(
        examples, _members(examples, choose_one=False),
        surface="play", head="ranking",
        prior_distribution=[1 / 8] * 8)
    assert rejected["decision"] == "SELECT_NONE"
    assert rejected["proposal_triggers"] == 0
    with pytest.raises(REPORT.StageCReportError, match="eight seeds"):
        REPORT.evaluate_capability(
            examples, _members(examples)[:7], surface="play", head="ranking",
            prior_distribution=[1 / 8] * 8)


def test_outcome_capability_requires_report_calibration() -> None:
    examples = [_example(index, surface="bury") for index in range(32)]
    passed = REPORT.evaluate_capability(
        examples, _members(examples), surface="bury", head="outcome",
        prior_distribution=[1 / 8] * 8)
    assert passed["decision"] \
        == "AUTHORIZE_STAGE_C_COMPOSITION_PACKET_REVIEW"
    failed = REPORT.evaluate_capability(
        examples, _members(examples, calibrated=False),
        surface="bury", head="outcome",
        prior_distribution=[1 / 8] * 8)
    assert failed["teacher_improvement_vs_candidate0"]["mean"] > 0
    assert failed["outcome_nll_improvement_vs_design_prior"][
        "one_sided_95_lcb"] < 0
    assert failed["decision"] == "SELECT_NONE"


def test_report_result_changes_under_prediction_mutation() -> None:
    examples = [_example(index) for index in range(40)]
    members = _members(examples)
    first = REPORT.evaluate_capability(
        examples, members, surface="play", head="ranking",
        prior_distribution=[1 / 8] * 8)
    changed = copy.deepcopy(members)
    for member in changed[:5]:
        member[0][0] = [3.0, 0.0]
    second = REPORT.evaluate_capability(
        examples, changed, surface="play", head="ranking",
        prior_distribution=[1 / 8] * 8)
    assert first["result_sha256"] != second["result_sha256"]


def test_numerically_tied_model_scores_choose_lowest_index() -> None:
    outcomes = [_distribution(3), _distribution(3)]
    assert REPORT._selected_index(
        [0.0, REPORT.MODEL_SCORE_TIE_EPSILON / 2], outcomes, "ranking") == 0
    assert REPORT._selected_index(
        [0.0, REPORT.MODEL_SCORE_TIE_EPSILON * 2], outcomes, "ranking") == 1


def test_protected_policy_averages_raw_logits_not_member_softmax_votes() -> None:
    examples = [_example(index) for index in range(40)]
    members = _members(examples)
    # One very confident seed outweighs seven mildly negative raw margins.
    # Averaging per-member softmax votes would choose candidate zero instead.
    for member_index, (ranks, _outcomes) in enumerate(members):
        for state_index in range(len(examples)):
            ranks[state_index] = ([0.0, 10.0] if member_index == 0
                                  else [0.0, -1.0])
    softmax_ranks, _ = REPORT.average_ensemble(examples, members)
    assert softmax_ranks[0][0] > softmax_ranks[0][1]
    raw_ranks, _ = REPORT.average_raw_logit_ensemble(examples, members)
    assert raw_ranks[0] == pytest.approx([0.0, 0.375])

    result = REPORT.evaluate_capability(
        examples, members, surface="play", head="ranking",
        prior_distribution=[1 / 8] * 8,
        protected_policy=_protected_policy())
    assert result["decision"] \
        == "AUTHORIZE_STAGE_C_COMPOSITION_PACKET_REVIEW"
    assert result["proposal_triggers"] == 40
    assert result["rows"][0]["activation_margin"] == pytest.approx(0.375)
    assert result["ensemble_rule"]["ranking"] \
        == "arithmetic mean of raw rank logits across seeds"


def test_protected_policy_uses_strict_margin_and_candidate_zero_fallback() \
        -> None:
    policy = _protected_policy()
    assert REPORT._protected_selected_index([0.0, 0.2], policy) \
        == (0, 0.2)
    selected, margin = REPORT._protected_selected_index(
        [0.0, 0.2000001, 0.2000002], policy)
    assert selected == 2
    assert margin == pytest.approx(0.2000002)
    assert REPORT._protected_selected_index([4.0], policy) == (0, 0.0)


def test_protected_policy_contract_mutation_refuses() -> None:
    examples = [_example(index) for index in range(40)]
    changed = _protected_policy()
    changed["threshold"] = 0.1
    with pytest.raises(REPORT.StageCReportError, match="policy contract drift"):
        REPORT.evaluate_capability(
            examples, _members(examples), surface="play", head="ranking",
            prior_distribution=[1 / 8] * 8, protected_policy=changed)
