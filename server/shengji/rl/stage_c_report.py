"""One-shot Stage-C ensemble evaluation mechanics for untouched REPORT.

CALIB freezes exactly one surface/head/epoch capability and all eight seeds.
This module averages that complete cohort, measures per-state improvement over
candidate zero on the Teacher's common-world target, and applies a conservative
one-sided bound.  It is pure model/evaluation code: callers own REPORT
admission, shard reopening, artifact publication and downstream composition
authority.
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
    return max(range(len(scores)), key=lambda index: (scores[index], -index))


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
) -> dict:
    """Evaluate the one CALIB-frozen capability once on its REPORT surface."""
    if (surface not in MODEL.SURFACES or head not in MODEL.CAPABILITY_HEADS
            or len(examples) < MIN_REPORT_STATES
            or any(example.get("split") != "REPORT"
                   or example.get("surface_type") != surface
                   for example in examples)):
        raise StageCReportError("Stage-C REPORT capability/population drift")
    ranks, outcomes = average_ensemble(examples, member_predictions)
    canonical_metrics = MODEL.evaluate_predictions(
        examples, ranks, outcomes, prior_distribution=prior_distribution)
    rows = []
    nll_improvements = []
    by_stratum: dict[str, list[float]] = defaultdict(list)
    for example, rank_values, outcome_values in zip(
            examples, ranks, outcomes, strict=True):
        target = example["target"]
        means = target["ranking_mean_signed_level_utility"]
        selected = _selected_index(rank_values, outcome_values, head)
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
        }
        rows.append(row)
        nll_improvements.append(nll_gain)
        by_stratum[str(example["stratum"])].append(improvement)
    primary = one_sided_summary([
        value["teacher_improvement_vs_candidate0"] for value in rows])
    calibration = one_sided_summary(nll_improvements)
    trigger_count = sum(bool(value["proposal_triggered"]) for value in rows)
    pass_gate = primary["one_sided_95_lcb"] > 0 and trigger_count > 0
    if head == "outcome":
        pass_gate &= calibration["one_sided_95_lcb"] > 0
    result = {
        "schema": REPORT_SCHEMA,
        "surface": surface,
        "head": head,
        "ensemble_seeds": list(MODEL.TRAINING_SEEDS),
        "ensemble_rule": {
            "ranking": "mean within-ballot softmax probability across seeds",
            "outcome": "mean eight-bin probability across seeds",
            "tie_break": "lowest candidate index",
        },
        "states": len(examples),
        "proposal_triggers": trigger_count,
        "proposal_trigger_rate": trigger_count / len(examples),
        "teacher_improvement_vs_candidate0": primary,
        "outcome_nll_improvement_vs_design_prior": calibration,
        "outcome_calibration_is_gate": head == "outcome",
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
