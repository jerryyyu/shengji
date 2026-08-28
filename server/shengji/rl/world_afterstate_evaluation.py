"""Held-out gates for the first complete-world successor-value learner.

The evaluator consumes raw engine outcomes and per-member categorical
forecasts.  Report labels are never converted into an empirical reference
forecast: every model and train-only-prior probability is scored directly
against each raw outcome.  Deal-grouped bootstrap units preserve the frozen
population split.
"""

from __future__ import annotations

import hashlib
import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import torch

from .belief_contract import canonical_json_bytes
from .world_afterstate import (
    OUTCOME_CLASSES, category_signed_level, validate_outcome)
from .world_afterstate_population import validate_population_group
from .world_afterstate_model import WorldAfterstateValueV0
from .world_afterstate_training import (
    COHORT_SIZE, WorldAfterstateTrainingBatchV0, model_state_sha256)


EVALUATION_OUTCOME_SCHEMA = "world-afterstate-evaluation-outcome-v0"
PREDICTION_SCHEMA = "world-afterstate-prediction-v0"
PRIOR_SCHEMA = "world-afterstate-train-prior-v0"
PRIMARY_SCHEMA = "world-afterstate-primary-gate-v0"
ACTION_SCHEMA = "world-afterstate-action-gate-v0"
PROBABILITY_SCALE = 1_000_000_000
NANONAT_SCALE = 1_000_000_000
BOOTSTRAP_REPLICATES = 10_000
PROVIDER_ESTIMATOR_REPLICATES = (0, 1, 2, 3)
PROVIDER_TRUTH_REPLICATES = (4, 5, 6, 7)
EVALUATION_AUTHORITY = {
    "report_opening_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
}


class WorldAfterstateEvaluationError(ValueError):
    """A held-out identity, forecast, baseline, metric, or gate drifted."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateEvaluationError(f"{label} drift")
    return value


def _probabilities(values: Sequence[int]) -> tuple[int, ...]:
    if type(values) not in (list, tuple) or len(values) != OUTCOME_CLASSES \
            or any(isinstance(value, bool) or not isinstance(value, int)
                   or value < 0 for value in values) \
            or sum(values) != PROBABILITY_SCALE:
        raise WorldAfterstateEvaluationError("prediction probability drift")
    return tuple(values)


def _quantize_counts(counts: Sequence[int]) -> tuple[int, ...]:
    if type(counts) not in (list, tuple) or len(counts) != OUTCOME_CLASSES \
            or any(isinstance(value, bool) or not isinstance(value, int)
                   or value <= 0 for value in counts):
        raise WorldAfterstateEvaluationError("prior count drift")
    total = sum(counts)
    floors = [value * PROBABILITY_SCALE // total for value in counts]
    residual = PROBABILITY_SCALE - sum(floors)
    order = sorted(
        range(OUTCOME_CLASSES),
        key=lambda index: (-(counts[index] * PROBABILITY_SCALE % total),
                           index))
    for index in order[:residual]:
        floors[index] += 1
    return _probabilities(floors)


def _quantize_model_probabilities(values: torch.Tensor) -> tuple[int, ...]:
    """Publish one finite categorical forecast with a one-ppb floor.

    The floor prevents artifact serialization from turning a finite logit into
    an impossible event.  Remaining mass is allocated by largest remainder in
    canonical category order, so reopening is deterministic.
    """
    if values.device.type != "cpu" or values.dtype != torch.float64 \
            or values.shape != (OUTCOME_CLASSES,) \
            or not bool(torch.all(torch.isfinite(values))) \
            or bool(torch.any(values <= 0)):
        raise WorldAfterstateEvaluationError(
            "model probability tensor drift")
    available = PROBABILITY_SCALE - OUTCOME_CLASSES
    scaled = values * available
    floors = [1 + int(math.floor(float(value))) for value in scaled]
    residual = PROBABILITY_SCALE - sum(floors)
    order = sorted(
        range(OUTCOME_CLASSES),
        key=lambda index: (-(float(scaled[index])
                             - math.floor(float(scaled[index]))), index))
    for index in order[:residual]:
        floors[index] += 1
    return _probabilities(floors)


def _nll_nanonats(probability_ppb: int) -> int:
    if not 0 < probability_ppb <= PROBABILITY_SCALE:
        raise WorldAfterstateEvaluationError(
            "scored truth probability is zero")
    return int(round(-math.log(probability_ppb / PROBABILITY_SCALE)
                     * NANONAT_SCALE))


def _expected_utility_ppm(probabilities: Sequence[int]) -> int:
    values = _probabilities(probabilities)
    numerator = sum(
        value * int(round(category_signed_level(index) * 2))
        for index, value in enumerate(values))
    # Signed utilities are half-integers.  PPM retains exact half-level
    # arithmetic while keeping every published metric integral.
    return numerator * 1_000_000 // (2 * PROBABILITY_SCALE)


@dataclass(frozen=True)
class EvaluationOutcomeV0:
    deal_group_sha256: str
    state_group_id: str
    source: str
    fold: str
    root_role: str
    play_phase: str
    position: str
    trump_rank: str
    trump_mode: str
    points_bucket: str
    candidate_index: int
    protected_incumbent: bool
    successor_sha256: str
    replicate: int
    signed_level_category: int
    schema: str = EVALUATION_OUTCOME_SCHEMA

    def validate(self) -> None:
        for label, value in (
                ("deal group SHA-256", self.deal_group_sha256),
                ("state group id", self.state_group_id),
                ("successor SHA-256", self.successor_sha256)):
            _digest(value, label)
        if self.schema != EVALUATION_OUTCOME_SCHEMA \
                or self.fold not in ("train", "calibration", "report",
                                     "provider-audit") \
                or any(type(value) is not str or not value
                       for value in (self.source, self.root_role,
                                     self.play_phase, self.position,
                                     self.trump_rank, self.trump_mode,
                                     self.points_bucket)) \
                or isinstance(self.candidate_index, bool) \
                or not isinstance(self.candidate_index, int) \
                or self.candidate_index < 0 \
                or type(self.protected_incumbent) is not bool \
                or isinstance(self.replicate, bool) \
                or not isinstance(self.replicate, int) \
                or self.replicate < 0:
            raise WorldAfterstateEvaluationError(
                "evaluation outcome identity drift")
        category_signed_level(self.signed_level_category)

    def key(self) -> tuple[str, int, int]:
        self.validate()
        return (self.state_group_id, self.candidate_index, self.replicate)

    def stratum(self) -> tuple[str, ...]:
        self.validate()
        return (self.root_role, self.play_phase, self.position,
                self.trump_rank, self.trump_mode, self.points_bucket)


def build_evaluation_outcome(
        group: Mapping[str, Any], *, candidate_index: int, replicate: int,
        outcome: Mapping[str, Any]) -> EvaluationOutcomeV0:
    validate_population_group(group)
    validate_outcome(outcome)
    if isinstance(candidate_index, bool) or not isinstance(candidate_index, int) \
            or not 0 <= candidate_index < group["candidate_count"]:
        raise WorldAfterstateEvaluationError(
            "evaluation candidate index drift")
    candidate = group["candidates"][candidate_index]
    if outcome["successor_sha256"] != candidate["successor_sha256"]:
        raise WorldAfterstateEvaluationError(
            "evaluation outcome/successor binding drift")
    value = EvaluationOutcomeV0(
        deal_group_sha256=group["deal_group_sha256"],
        state_group_id=group["state_group_id"], source=group["source"],
        fold=group["fold"], root_role=group["root_role"],
        play_phase=group["play_phase"], position=group["position"],
        trump_rank=group["trump_rank"], trump_mode=group["trump_mode"],
        points_bucket=group["points_bucket"],
        candidate_index=candidate_index,
        protected_incumbent=candidate["protected_incumbent"],
        successor_sha256=candidate["successor_sha256"],
        replicate=replicate,
        signed_level_category=outcome["signed_level_category"])
    value.validate()
    return value


@dataclass(frozen=True)
class PredictionV0:
    state_group_id: str
    candidate_index: int
    successor_sha256: str
    member_index: int
    model_state_sha256: str
    probabilities_ppb: tuple[int, ...]
    schema: str = PREDICTION_SCHEMA

    def validate(self) -> None:
        for label, value in (
                ("state group id", self.state_group_id),
                ("successor SHA-256", self.successor_sha256),
                ("model state SHA-256", self.model_state_sha256)):
            _digest(value, label)
        if self.schema != PREDICTION_SCHEMA \
                or isinstance(self.candidate_index, bool) \
                or not isinstance(self.candidate_index, int) \
                or self.candidate_index < 0 \
                or isinstance(self.member_index, bool) \
                or not isinstance(self.member_index, int) \
                or not 0 <= self.member_index < COHORT_SIZE:
            raise WorldAfterstateEvaluationError(
                "prediction identity drift")
        _probabilities(self.probabilities_ppb)

    def key(self) -> tuple[str, int, int]:
        self.validate()
        return (self.state_group_id, self.candidate_index,
                self.member_index)


def predict_batch(
        model: WorldAfterstateValueV0,
        batch: WorldAfterstateTrainingBatchV0, *, member_index: int,
        state_group_ids: Sequence[str],
        candidate_indexes: Sequence[int]) -> tuple[PredictionV0, ...]:
    """Run one frozen member without mutating it and bind every forecast."""
    if type(model) is not WorldAfterstateValueV0 \
            or type(batch) is not WorldAfterstateTrainingBatchV0:
        raise WorldAfterstateEvaluationError("prediction request drift")
    batch.validate()
    count = len(batch.example_keys)
    if isinstance(member_index, bool) or not isinstance(member_index, int) \
            or not 0 <= member_index < COHORT_SIZE \
            or type(state_group_ids) not in (list, tuple) \
            or type(candidate_indexes) not in (list, tuple) \
            or len(state_group_ids) != count \
            or len(candidate_indexes) != count:
        raise WorldAfterstateEvaluationError(
            "prediction identity population drift")
    for state_group_id, candidate_index in zip(
            state_group_ids, candidate_indexes, strict=True):
        _digest(state_group_id, "prediction state group id")
        if isinstance(candidate_index, bool) \
                or not isinstance(candidate_index, int) \
                or candidate_index < 0:
            raise WorldAfterstateEvaluationError(
                "prediction candidate identity drift")
    before = model_state_sha256(model)
    was_training = model.training
    model.eval()
    try:
        with torch.no_grad():
            logits = model(
                batch.public, batch.history, batch.history_lengths,
                batch.world, batch.perspective)
            probabilities = torch.softmax(
                logits.to(torch.float64), dim=1).cpu()
    finally:
        model.train(was_training)
    if probabilities.shape != (count, OUTCOME_CLASSES) \
            or model_state_sha256(model) != before:
        raise WorldAfterstateEvaluationError(
            "prediction execution mutated model")
    rows = tuple(PredictionV0(
        state_group_id=state_group_id,
        candidate_index=candidate_index,
        successor_sha256=successor,
        member_index=member_index,
        model_state_sha256=before,
        probabilities_ppb=_quantize_model_probabilities(probabilities[index]))
        for index, (state_group_id, candidate_index, successor) in enumerate(
            zip(state_group_ids, candidate_indexes,
                batch.successor_sha256s, strict=True)))
    for row in rows:
        row.validate()
    return rows


@dataclass(frozen=True)
class TrainPriorV0:
    global_probabilities_ppb: tuple[int, ...]
    stratum_rows: tuple[tuple[tuple[str, ...], tuple[int, ...]], ...]
    train_population_sha256: str
    schema: str = PRIOR_SCHEMA

    def validate(self) -> None:
        _probabilities(self.global_probabilities_ppb)
        _digest(self.train_population_sha256, "prior train population SHA-256")
        if self.schema != PRIOR_SCHEMA or type(self.stratum_rows) is not tuple \
                or any(type(key) is not tuple or len(key) != 6
                       or any(type(item) is not str for item in key)
                       or type(values) is not tuple
                       for key, values in self.stratum_rows) \
                or tuple(sorted(self.stratum_rows)) != self.stratum_rows \
                or len({key for key, _ in self.stratum_rows}) \
                != len(self.stratum_rows):
            raise WorldAfterstateEvaluationError("train prior schema drift")
        for _, values in self.stratum_rows:
            _probabilities(values)

    def probabilities(self, outcome: EvaluationOutcomeV0) -> tuple[int, ...]:
        self.validate()
        rows = dict(self.stratum_rows)
        return rows.get(outcome.stratum(), self.global_probabilities_ppb)


def build_train_prior(outcomes: Sequence[EvaluationOutcomeV0]) -> TrainPriorV0:
    if type(outcomes) not in (list, tuple) or not outcomes:
        raise WorldAfterstateEvaluationError("train prior population drift")
    global_counts = [1] * OUTCOME_CLASSES
    strata: dict[tuple[str, ...], list[int]] = {}
    keys = []
    for outcome in outcomes:
        if type(outcome) is not EvaluationOutcomeV0:
            raise WorldAfterstateEvaluationError("train prior row type drift")
        outcome.validate()
        if outcome.fold != "train":
            raise WorldAfterstateEvaluationError("train prior split drift")
        key = outcome.key()
        keys.append(key)
        global_counts[outcome.signed_level_category] += 1
        counts = strata.setdefault(outcome.stratum(), [1] * OUTCOME_CLASSES)
        counts[outcome.signed_level_category] += 1
    if len(keys) != len(set(keys)):
        raise WorldAfterstateEvaluationError("train prior duplicate outcome")
    population_sha = _sha({
        "schema": PRIOR_SCHEMA,
        "rows": [list(key) for key in sorted(keys)],
    })
    result = TrainPriorV0(
        global_probabilities_ppb=_quantize_counts(global_counts),
        stratum_rows=tuple(sorted(
            (key, _quantize_counts(counts))
            for key, counts in strata.items())),
        train_population_sha256=population_sha)
    result.validate()
    return result


def _prediction_map(predictions: Sequence[PredictionV0]) \
        -> dict[tuple[str, int, int], PredictionV0]:
    if type(predictions) not in (list, tuple) or not predictions:
        raise WorldAfterstateEvaluationError("prediction population drift")
    result = {}
    for prediction in predictions:
        if type(prediction) is not PredictionV0:
            raise WorldAfterstateEvaluationError("prediction row type drift")
        key = prediction.key()
        if key in result:
            raise WorldAfterstateEvaluationError("duplicate prediction")
        result[key] = prediction
    return result


def _ensemble(predictions: Sequence[PredictionV0]) -> tuple[int, ...]:
    if len(predictions) != COHORT_SIZE \
            or {row.member_index for row in predictions} \
            != set(range(COHORT_SIZE)):
        raise WorldAfterstateEvaluationError("prediction member population drift")
    totals = [sum(row.probabilities_ppb[index] for row in predictions)
              for index in range(OUTCOME_CLASSES)]
    floors = [value // COHORT_SIZE for value in totals]
    residual = PROBABILITY_SCALE - sum(floors)
    order = sorted(range(OUTCOME_CLASSES),
                   key=lambda index: (-(totals[index] % COHORT_SIZE), index))
    for index in order[:residual]:
        floors[index] += 1
    return _probabilities(floors)


def _bootstrap_interval(
        deal_values: Mapping[str, tuple[int, int]], *, namespace: str,
        replicates: int = BOOTSTRAP_REPLICATES) -> tuple[int, int, int]:
    if not deal_values or isinstance(replicates, bool) \
            or not isinstance(replicates, int) or replicates < 100:
        raise WorldAfterstateEvaluationError("bootstrap population drift")
    deals = sorted(deal_values)
    seed = int.from_bytes(hashlib.sha256(
        f"world-afterstate-e4|{namespace}".encode("ascii")).digest()[:16],
        "big")
    rng = random.Random(seed)
    samples = []
    for _ in range(replicates):
        numerator = 0
        denominator = 0
        for _ in deals:
            deal = deals[rng.randrange(len(deals))]
            value, count = deal_values[deal]
            numerator += value
            denominator += count
        samples.append(numerator // denominator)
    samples.sort()
    lower = samples[(replicates * 5) // 100]
    upper = samples[(replicates * 95) // 100]
    mean = sum(value for value, _ in deal_values.values()) // sum(
        count for _, count in deal_values.values())
    return mean, lower, upper


def evaluate_primary_gate(
        outcomes: Sequence[EvaluationOutcomeV0],
        predictions: Sequence[PredictionV0], prior: TrainPriorV0, *,
        expected_fold: str = "report", namespace: str = "primary",
        bootstrap_replicates: int = BOOTSTRAP_REPLICATES) -> dict[str, Any]:
    prior.validate()
    if expected_fold not in ("report", "provider-audit") \
            or type(outcomes) not in (list, tuple) or not outcomes:
        raise WorldAfterstateEvaluationError("primary population drift")
    prediction_map = _prediction_map(predictions)
    deal_values: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    member_sums = [0] * COHORT_SIZE
    row_count = 0
    used_predictions = set()
    for outcome in outcomes:
        if type(outcome) is not EvaluationOutcomeV0:
            raise WorldAfterstateEvaluationError("primary row type drift")
        outcome.validate()
        if outcome.fold != expected_fold:
            raise WorldAfterstateEvaluationError("primary split drift")
        rows = []
        for member in range(COHORT_SIZE):
            key = (outcome.state_group_id, outcome.candidate_index, member)
            prediction = prediction_map.get(key)
            if prediction is None \
                    or prediction.successor_sha256 != outcome.successor_sha256:
                raise WorldAfterstateEvaluationError(
                    "primary prediction binding drift")
            rows.append(prediction)
            used_predictions.add(key)
        ensemble = _ensemble(rows)
        prior_values = prior.probabilities(outcome)
        truth = outcome.signed_level_category
        prior_nll = _nll_nanonats(prior_values[truth])
        model_nll = _nll_nanonats(ensemble[truth])
        improvement = prior_nll - model_nll
        deal_values[outcome.deal_group_sha256][0] += improvement
        deal_values[outcome.deal_group_sha256][1] += 1
        for member, prediction in enumerate(rows):
            member_sums[member] += prior_nll - _nll_nanonats(
                prediction.probabilities_ppb[truth])
        row_count += 1
    if used_predictions != set(prediction_map):
        raise WorldAfterstateEvaluationError("unused prediction row")
    mean, lower, upper = _bootstrap_interval(
        {key: (value[0], value[1]) for key, value in deal_values.items()},
        namespace=namespace, replicates=bootstrap_replicates)
    positive_members = sum(value > 0 for value in member_sums)
    body = {
        "schema": PRIMARY_SCHEMA,
        "fold": expected_fold,
        "row_count": row_count,
        "deal_count": len(deal_values),
        "mean_nll_improvement_nanonats": mean,
        "bootstrap_lower_nanonats": lower,
        "bootstrap_upper_nanonats": upper,
        "bootstrap_replicates": bootstrap_replicates,
        "positive_member_count": positive_members,
        "member_count": COHORT_SIZE,
        "passed": lower > 0 and positive_members >= 6,
        "authority": dict(EVALUATION_AUTHORITY),
    }
    return {**body, "result_sha256": _sha(body)}


def _group_outcomes(outcomes: Sequence[EvaluationOutcomeV0]) \
        -> dict[str, dict[int, dict[int, EvaluationOutcomeV0]]]:
    groups: dict[str, dict[int, dict[int, EvaluationOutcomeV0]]] = defaultdict(
        lambda: defaultdict(dict))
    for outcome in outcomes:
        if type(outcome) is not EvaluationOutcomeV0:
            raise WorldAfterstateEvaluationError("action row type drift")
        outcome.validate()
        if outcome.fold != "provider-audit" \
                or outcome.replicate in groups[outcome.state_group_id][
                    outcome.candidate_index]:
            raise WorldAfterstateEvaluationError(
                "action population identity drift")
        groups[outcome.state_group_id][outcome.candidate_index][
            outcome.replicate] = outcome
    return groups


def evaluate_action_gate(
        outcomes: Sequence[EvaluationOutcomeV0],
        predictions: Sequence[PredictionV0], *,
        bootstrap_replicates: int = BOOTSTRAP_REPLICATES) -> dict[str, Any]:
    prediction_map = _prediction_map(predictions)
    groups = _group_outcomes(outcomes)
    error_deals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    regret_deals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    incumbent_deals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    used_predictions = set()
    for state_group_id, candidates in groups.items():
        indexes = sorted(candidates)
        if indexes != list(range(len(indexes))):
            raise WorldAfterstateEvaluationError(
                "action candidate population drift")
        truth_utilities = []
        baseline_utilities = []
        model_utilities = []
        deal = None
        group_identity = None
        for candidate_index in indexes:
            rows = candidates[candidate_index]
            if set(rows) != set(PROVIDER_ESTIMATOR_REPLICATES \
                                 + PROVIDER_TRUTH_REPLICATES):
                raise WorldAfterstateEvaluationError(
                    "action replicate population drift")
            ordered = [rows[index] for index in sorted(rows)]
            candidate_identity = {
                (row.deal_group_sha256, row.source, row.stratum())
                for row in ordered
            }
            if len(candidate_identity) != 1 \
                    or len({row.successor_sha256 for row in ordered}) != 1 \
                    or any(row.protected_incumbent \
                           is not (candidate_index == 0)
                           for row in ordered):
                raise WorldAfterstateEvaluationError(
                    "action sibling binding drift")
            candidate_group_identity = next(iter(candidate_identity))
            if group_identity is None:
                group_identity = candidate_group_identity
            elif candidate_group_identity != group_identity:
                raise WorldAfterstateEvaluationError(
                    "action cross-candidate binding drift")
            deal = candidate_group_identity[0]
            baseline_utilities.append(sum(
                int(round(category_signed_level(
                    rows[index].signed_level_category) * 1_000_000))
                for index in PROVIDER_ESTIMATOR_REPLICATES)
                // len(PROVIDER_ESTIMATOR_REPLICATES))
            truth_utilities.append(sum(
                int(round(category_signed_level(
                    rows[index].signed_level_category) * 1_000_000))
                for index in PROVIDER_TRUTH_REPLICATES)
                // len(PROVIDER_TRUTH_REPLICATES))
            member_rows = []
            for member in range(COHORT_SIZE):
                key = (state_group_id, candidate_index, member)
                prediction = prediction_map.get(key)
                if prediction is None or prediction.successor_sha256 \
                        != ordered[0].successor_sha256:
                    raise WorldAfterstateEvaluationError(
                        "action prediction binding drift")
                member_rows.append(prediction)
                used_predictions.add(key)
            model_utilities.append(_expected_utility_ppm(
                _ensemble(member_rows)))
        if deal is None or group_identity is None:
            raise WorldAfterstateEvaluationError(
                "action state group is empty")
        baseline_error = sum(abs(left - right) for left, right in zip(
            baseline_utilities, truth_utilities, strict=True)) // len(indexes)
        model_error = sum(abs(left - right) for left, right in zip(
            model_utilities, truth_utilities, strict=True)) // len(indexes)
        truth_best = max(truth_utilities)
        baseline_choice = max(
            indexes, key=lambda index: (baseline_utilities[index], -index))
        model_choice = max(
            indexes, key=lambda index: (model_utilities[index], -index))
        baseline_regret = truth_best - truth_utilities[baseline_choice]
        model_regret = truth_best - truth_utilities[model_choice]
        incumbent_regret = max(
            0, truth_utilities[0] - truth_utilities[model_choice])
        for target, value in (
                (error_deals, baseline_error - model_error),
                (regret_deals, baseline_regret - model_regret),
                (incumbent_deals, -incumbent_regret)):
            target[deal][0] += value
            target[deal][1] += 1
    if used_predictions != set(prediction_map):
        raise WorldAfterstateEvaluationError("unused action prediction row")
    error = _bootstrap_interval(
        {key: tuple(value) for key, value in error_deals.items()},
        namespace="action-expected-utility-error",
        replicates=bootstrap_replicates)
    regret = _bootstrap_interval(
        {key: tuple(value) for key, value in regret_deals.items()},
        namespace="action-simple-regret", replicates=bootstrap_replicates)
    incumbent = _bootstrap_interval(
        {key: tuple(value) for key, value in incumbent_deals.items()},
        namespace="action-protected-incumbent",
        replicates=bootstrap_replicates)
    passed = error[1] > 0 and regret[1] > 0 and incumbent[1] >= 0
    body = {
        "schema": ACTION_SCHEMA,
        "state_group_count": len(groups),
        "deal_count": len(error_deals),
        "expected_utility_error_improvement_ppm": {
            "mean": error[0], "bootstrap_lower": error[1],
            "bootstrap_upper": error[2]},
        "simple_regret_improvement_ppm": {
            "mean": regret[0], "bootstrap_lower": regret[1],
            "bootstrap_upper": regret[2]},
        "protected_incumbent_nonregression_ppm": {
            "mean": incumbent[0], "bootstrap_lower": incumbent[1],
            "bootstrap_upper": incumbent[2]},
        "bootstrap_replicates": bootstrap_replicates,
        "passed": passed,
        "authority": dict(EVALUATION_AUTHORITY),
    }
    return {**body, "result_sha256": _sha(body)}


def validate_primary_result(value: Mapping[str, Any]) -> None:
    required = {
        "schema", "fold", "row_count", "deal_count",
        "mean_nll_improvement_nanonats", "bootstrap_lower_nanonats",
        "bootstrap_upper_nanonats", "bootstrap_replicates",
        "positive_member_count", "member_count", "passed", "authority",
        "result_sha256",
    }
    if type(value) is not dict or set(value) != required \
            or value.get("schema") != PRIMARY_SCHEMA \
            or value.get("authority") != EVALUATION_AUTHORITY \
            or value.get("fold") not in ("report", "provider-audit") \
            or type(value.get("passed")) is not bool \
            or any(type(value.get(key)) is not int for key in (
                "row_count", "deal_count", "mean_nll_improvement_nanonats",
                "bootstrap_lower_nanonats", "bootstrap_upper_nanonats",
                "bootstrap_replicates", "positive_member_count",
                "member_count")) \
            or value["row_count"] <= 0 or value["deal_count"] <= 0 \
            or value["bootstrap_replicates"] != BOOTSTRAP_REPLICATES \
            or value["member_count"] != COHORT_SIZE \
            or not 0 <= value["positive_member_count"] <= COHORT_SIZE \
            or value["passed"] is not (
                value["bootstrap_lower_nanonats"] > 0
                and value["positive_member_count"] >= 6):
        raise WorldAfterstateEvaluationError("primary result schema drift")
    body = {key: item for key, item in value.items()
            if key != "result_sha256"}
    if value["result_sha256"] != _sha(body):
        raise WorldAfterstateEvaluationError(
            "primary result reconstruction drift")


def validate_action_result(value: Mapping[str, Any]) -> None:
    required = {
        "schema", "state_group_count", "deal_count",
        "expected_utility_error_improvement_ppm",
        "simple_regret_improvement_ppm",
        "protected_incumbent_nonregression_ppm", "bootstrap_replicates",
        "passed", "authority", "result_sha256",
    }
    if type(value) is not dict or set(value) != required \
            or value.get("schema") != ACTION_SCHEMA \
            or value.get("authority") != EVALUATION_AUTHORITY \
            or type(value.get("passed")) is not bool \
            or type(value.get("state_group_count")) is not int \
            or value["state_group_count"] <= 0 \
            or type(value.get("deal_count")) is not int \
            or value["deal_count"] <= 0 \
            or value.get("bootstrap_replicates") != BOOTSTRAP_REPLICATES:
        raise WorldAfterstateEvaluationError("action result schema drift")
    for key in (
            "expected_utility_error_improvement_ppm",
            "simple_regret_improvement_ppm",
            "protected_incumbent_nonregression_ppm"):
        if type(value[key]) is not dict or set(value[key]) != {
                "mean", "bootstrap_lower", "bootstrap_upper"} \
                or any(type(number) is not int for number in value[key].values()):
            raise WorldAfterstateEvaluationError(
                "action result metric drift")
    expected_pass = (
        value["expected_utility_error_improvement_ppm"][
            "bootstrap_lower"] > 0
        and value["simple_regret_improvement_ppm"][
            "bootstrap_lower"] > 0
        and value["protected_incumbent_nonregression_ppm"][
            "bootstrap_lower"] >= 0)
    if value["passed"] is not expected_pass:
        raise WorldAfterstateEvaluationError("action result gate drift")
    body = {key: item for key, item in value.items()
            if key != "result_sha256"}
    if value["result_sha256"] != _sha(body):
        raise WorldAfterstateEvaluationError(
            "action result reconstruction drift")


__all__ = [
    "ACTION_SCHEMA", "BOOTSTRAP_REPLICATES", "EVALUATION_AUTHORITY",
    "EVALUATION_OUTCOME_SCHEMA", "EvaluationOutcomeV0", "NANONAT_SCALE",
    "PREDICTION_SCHEMA", "PRIMARY_SCHEMA", "PROBABILITY_SCALE",
    "PROVIDER_ESTIMATOR_REPLICATES", "PROVIDER_TRUTH_REPLICATES",
    "PredictionV0", "TrainPriorV0", "WorldAfterstateEvaluationError",
    "build_evaluation_outcome", "build_train_prior", "evaluate_action_gate",
    "evaluate_primary_gate", "predict_batch", "validate_action_result",
    "validate_primary_result",
]
