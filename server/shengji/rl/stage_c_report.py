"""One-shot Stage-C ensemble evaluation mechanics for untouched REPORT.

The original evaluator supports an unconditional CALIB-frozen capability.  A
terminal follow-up can instead freeze a protected-anchor policy: average raw
rank logits from all eight seeds, keep candidate zero unless the best
alternative clears a strict fixed margin, and leave bury unchanged.  This
module implements both contracts explicitly so a REPORT controller cannot
silently evaluate one while claiming the other.

Both routes measure per-state improvement over candidate zero on the Teacher's
common-world target and apply a conservative one-sided bound.  This is pure
model/evaluation code: callers own REPORT admission, shard reopening, artifact
publication and downstream composition authority.
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Mapping, Sequence

from . import stage_c_model as MODEL


REPORT_SCHEMA = "teacher-stage-c-model-report-v1"
REPORT_T_CRITICAL = 1.70
MIN_REPORT_STATES = 30
MODEL_SCORE_TIE_EPSILON = 1e-7
PROTECTED_POLICY_SCHEMA = "teacher-stage-c-protected-anchor-report-policy-v1"


class StageCReportError(RuntimeError):
    """A selected capability, ensemble prediction or REPORT gate drifted."""


def _rank_probabilities(values: Sequence[object]) -> list[float]:
    if (not values
            or any(isinstance(value, bool)
                   or not isinstance(value, (int, float))
                   or not math.isfinite(float(value)) for value in values)):
        raise StageCReportError("Stage-C REPORT rank-logit drift")
    maximum = max(float(value) for value in values)
    shifted = [math.exp(float(value) - maximum) for value in values]
    denominator = sum(shifted)
    if not math.isfinite(denominator) or denominator <= 0:
        raise StageCReportError("Stage-C REPORT rank softmax drift")
    result = [value / denominator for value in shifted]
    result[-1] += 1.0 - sum(result)
    return result


def average_ensemble(
    examples: Sequence[Mapping[str, object]],
    member_predictions: Sequence[tuple[
        Sequence[Sequence[float]],
        Sequence[Sequence[Sequence[float]]],
    ]],
) -> tuple[list[list[float]], list[list[list[float]]]]:
    """Average eight normalized rank votes and outcome distributions."""
    if len(member_predictions) != len(MODEL.TRAINING_SEEDS):
        raise StageCReportError("Stage-C REPORT ensemble is not eight seeds")
    if not examples:
        raise StageCReportError("Stage-C REPORT population is empty")
    # The canonical metric validator checks every member's ragged geometry,
    # finiteness and outcome probability contract before any averaging.
    for ranks, outcomes in member_predictions:
        MODEL.evaluate_predictions(examples, ranks, outcomes)
    rank_rows = []
    outcome_rows = []
    for state_index, example in enumerate(examples):
        count = int(example["target"]["candidate_count"])
        state_rank = [0.0] * count
        state_outcome = [[0.0] * len(MODEL.UTILITY_BINS)
                         for _ in range(count)]
        for ranks, outcomes in member_predictions:
            votes = _rank_probabilities(ranks[state_index])
            for candidate in range(count):
                state_rank[candidate] += votes[candidate]
                for bucket, probability in enumerate(
                        outcomes[state_index][candidate]):
                    state_outcome[candidate][bucket] += float(probability)
        scale = 1.0 / len(member_predictions)
        state_rank = [value * scale for value in state_rank]
        state_rank[-1] += 1.0 - sum(state_rank)
        for distribution in state_outcome:
            for bucket in range(len(distribution)):
                distribution[bucket] *= scale
            distribution[-1] += 1.0 - sum(distribution)
            MODEL.distribution_mean(distribution)
        rank_rows.append(state_rank)
        outcome_rows.append(state_outcome)
    return rank_rows, outcome_rows


def average_raw_logit_ensemble(
    examples: Sequence[Mapping[str, object]],
    member_predictions: Sequence[tuple[
        Sequence[Sequence[float]],
        Sequence[Sequence[Sequence[float]]],
    ]],
) -> tuple[list[list[float]], list[list[list[float]]]]:
    """Average raw rank logits and outcome distributions across eight seeds."""
    if len(member_predictions) != len(MODEL.TRAINING_SEEDS):
        raise StageCReportError("Stage-C REPORT ensemble is not eight seeds")
    if not examples:
        raise StageCReportError("Stage-C REPORT population is empty")
    for ranks, outcomes in member_predictions:
        MODEL.evaluate_predictions(examples, ranks, outcomes)
    rank_rows = []
    outcome_rows = []
    scale = 1.0 / len(member_predictions)
    for state_index, example in enumerate(examples):
        count = int(example["target"]["candidate_count"])
        state_rank = [0.0] * count
        state_outcome = [[0.0] * len(MODEL.UTILITY_BINS)
                         for _ in range(count)]
        for ranks, outcomes in member_predictions:
            for candidate in range(count):
                state_rank[candidate] += float(ranks[state_index][candidate])
                for bucket, probability in enumerate(
                        outcomes[state_index][candidate]):
                    state_outcome[candidate][bucket] += float(probability)
        state_rank = [value * scale for value in state_rank]
        for distribution in state_outcome:
            for bucket in range(len(distribution)):
                distribution[bucket] *= scale
            distribution[-1] += 1.0 - sum(distribution)
            MODEL.distribution_mean(distribution)
        rank_rows.append(state_rank)
        outcome_rows.append(state_outcome)
    return rank_rows, outcome_rows


def one_sided_summary(values: Sequence[object]) -> dict:
    if (len(values) < MIN_REPORT_STATES
            or any(isinstance(value, bool)
                   or not isinstance(value, (int, float))
                   or not math.isfinite(float(value)) for value in values)):
        raise StageCReportError("Stage-C REPORT interval population drift")
    samples = [float(value) for value in values]
    mean = statistics.fmean(samples)
    standard_error = statistics.stdev(samples) / math.sqrt(len(samples))
    return {
        "n": len(samples),
        "mean": mean,
        "standard_error": standard_error,
        "critical": REPORT_T_CRITICAL,
        "one_sided_95_lcb": mean - REPORT_T_CRITICAL * standard_error,
        "bound": "paired-state Student-t one-sided 95%; t=1.70",
    }


def _selected_index(
    ranks: Sequence[float], outcomes: Sequence[Sequence[float]], head: str,
) -> int:
    if head == "ranking":
        scores = [float(value) for value in ranks]
    elif head == "outcome":
        scores = [MODEL.distribution_mean(value) for value in outcomes]
    else:
        raise StageCReportError("Stage-C REPORT capability head drift")
    maximum = max(scores)
    # Distinct candidates can share an encoding. Batched float32 matmuls may
    # then differ by a few ulps solely because of row position; treating that
    # noise as model preference would violate the frozen lowest-index tie rule.
    return next(index for index, score in enumerate(scores)
                if maximum - score <= MODEL_SCORE_TIE_EPSILON)


def _protected_policy_contract(value: Mapping[str, object]) -> dict:
    """Validate and normalize the exact protected-anchor REPORT policy."""
    expected = {
        "schema": PROTECTED_POLICY_SCHEMA,
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
    if dict(value) != expected:
        raise StageCReportError(
            "Stage-C REPORT protected-anchor policy contract drift")
    return expected


def _protected_selected_index(
    ranks: Sequence[float], policy_contract: Mapping[str, object],
) -> tuple[int, float]:
    """Apply the strict protected-anchor decision rule to mean raw logits."""
    contract = _protected_policy_contract(policy_contract)
    scores = [float(value) for value in ranks]
    if (not scores
            or any(not math.isfinite(value) for value in scores)):
        raise StageCReportError(
            "Stage-C REPORT protected-anchor rank-logit drift")
    incumbent = int(contract["incumbent_index"])
    start = int(contract["alternative_start_index"])
    if len(scores) <= start:
        return incumbent, 0.0
    alternative = max(
        range(start, len(scores)), key=lambda index: (scores[index], -index))
    margin = scores[alternative] - scores[incumbent]
    if margin > float(contract["threshold"]):
        return alternative, margin
    return incumbent, margin


def _nll_improvement(
    example: Mapping[str, object],
    outcomes: Sequence[Sequence[float]],
    prior_distribution: Sequence[float],
) -> float:
    MODEL.distribution_mean(prior_distribution)
    actual = example["target"]["outcome_distribution"]
    if len(actual) != len(outcomes):
        raise StageCReportError("Stage-C REPORT outcome geometry drift")
    model_nll = []
    prior_nll = []
    for target, predicted in zip(actual, outcomes, strict=True):
        MODEL.distribution_mean(target)
        MODEL.distribution_mean(predicted)
        model_nll.append(-sum(
            float(target_p) * math.log(max(float(model_p), 1e-12))
            for target_p, model_p in zip(target, predicted, strict=True)))
        prior_nll.append(-sum(
            float(target_p) * math.log(max(float(prior_p), 1e-12))
            for target_p, prior_p in zip(
                target, prior_distribution, strict=True)))
    return statistics.fmean(prior_nll) - statistics.fmean(model_nll)


def evaluate_capability(
    examples: Sequence[Mapping[str, object]],
    member_predictions: Sequence[tuple[
        Sequence[Sequence[float]],
        Sequence[Sequence[Sequence[float]]],
    ]],
    *, surface: str, head: str,
    prior_distribution: Sequence[float],
    protected_policy: Mapping[str, object] | None = None,
) -> dict:
    """Evaluate the one CALIB-frozen capability once on its REPORT surface."""
    if (surface not in MODEL.SURFACES or head not in MODEL.CAPABILITY_HEADS
            or len(examples) < MIN_REPORT_STATES
            or any(example.get("split") != "REPORT"
                   or example.get("surface_type") != surface
                   for example in examples)):
        raise StageCReportError("Stage-C REPORT capability/population drift")
    policy = (_protected_policy_contract(protected_policy)
              if protected_policy is not None else None)
    if policy is not None and (surface != policy["surface"]
                               or head != policy["head"]):
        raise StageCReportError(
            "Stage-C REPORT protected-anchor surface/head drift")
    if policy is None:
        ranks, outcomes = average_ensemble(examples, member_predictions)
    else:
        ranks, outcomes = average_raw_logit_ensemble(
            examples, member_predictions)
    canonical_metrics = MODEL.evaluate_predictions(
        examples, ranks, outcomes, prior_distribution=prior_distribution)
    rows = []
    nll_improvements = []
    by_stratum: dict[str, list[float]] = defaultdict(list)
    for example, rank_values, outcome_values in zip(
            examples, ranks, outcomes, strict=True):
        target = example["target"]
        means = target["ranking_mean_signed_level_utility"]
        if policy is None:
            selected = _selected_index(rank_values, outcome_values, head)
            activation_margin = None
        else:
            selected, activation_margin = _protected_selected_index(
                rank_values, policy)
        improvement = float(means[selected]) - float(means[0])
        nll_gain = _nll_improvement(
            example, outcome_values, prior_distribution)
        row = {
            "state_id": example["state_id"],
            "stratum": example["stratum"],
            "candidate_count": target["candidate_count"],
            "selected_index": selected,
            "candidate0_index": 0,
            "frozen_label_index": target["frozen_label_index"],
            "teacher_improvement_vs_candidate0": improvement,
            "outcome_nll_improvement_vs_prior": nll_gain,
            "proposal_triggered": selected != 0,
            "activation_margin": activation_margin,
        }
        rows.append(row)
        nll_improvements.append(nll_gain)
        by_stratum[str(example["stratum"])].append(improvement)
    primary = one_sided_summary([
        value["teacher_improvement_vs_candidate0"] for value in rows])
    calibration = one_sided_summary(nll_improvements)
    trigger_count = sum(bool(value["proposal_triggered"]) for value in rows)
    pass_gate = primary["one_sided_95_lcb"] > 0 and trigger_count > 0
    if head == "outcome" and policy is None:
        pass_gate &= calibration["one_sided_95_lcb"] > 0
    result = {
        "schema": REPORT_SCHEMA,
        "surface": surface,
        "head": head,
        "ensemble_seeds": list(MODEL.TRAINING_SEEDS),
        "ensemble_rule": {
            "ranking": (
                "arithmetic mean of raw rank logits across seeds"
                if policy is not None else
                "mean within-ballot softmax probability across seeds"),
            "outcome": "mean eight-bin probability across seeds",
            "tie_break": (
                "lowest alternative candidate index; strict threshold"
                if policy is not None else
                "lowest candidate index within model-score epsilon 1e-7"),
        },
        "protected_policy": policy,
        "states": len(examples),
        "proposal_triggers": trigger_count,
        "proposal_trigger_rate": trigger_count / len(examples),
        "teacher_improvement_vs_candidate0": primary,
        "outcome_nll_improvement_vs_design_prior": calibration,
        "outcome_calibration_is_gate": head == "outcome" and policy is None,
        "canonical_metrics": canonical_metrics,
        "stratum_diagnostics": {
            key: {"n": len(values), "mean_teacher_improvement_vs_candidate0":
                  statistics.fmean(values)}
            for key, values in sorted(by_stratum.items())
        },
        "rows": rows,
        "decision": ("AUTHORIZE_STAGE_C_COMPOSITION_PACKET_REVIEW"
                     if pass_gate else "SELECT_NONE"),
        "report_opened_once": True,
        "report_reuse_authorized": False,
        "composition_packet_review_authorized": pass_gate,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    result["result_sha256"] = MODEL.sha256_bytes(MODEL.canonical_json(result))
    return result
