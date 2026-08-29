"""Target-free prediction and paired action gates for Value V1.

Predictions are produced from outcome-blind successor tensors before audit
labels are opened.  The evaluator then joins those immutable forecasts to the
two calibration continuations per action.  Every statistic is deal-clustered
and each root contributes equal weight regardless of ballot width.

This module grants no data opening, execution, gameplay, strength, merge,
promotion, deployment, retry, world-twin, or R5 authority.
"""

from __future__ import annotations

import hashlib
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Sequence

import torch

from .belief_contract import canonical_json_bytes
from .world_afterstate import WorldAfterstateTensorsV0
from .world_afterstate_v1_dataset import JoinedAdvantageV1
from .world_afterstate_v1_model import (
    SuccessorBatchV1, WorldAfterstateAdvantageV1,
    collate_successor_tensors, successor_tensor_sha256)
from .world_afterstate_v1_training import COHORT_SIZE, model_state_sha256


INFERENCE_BATCH_SCHEMA = "world-afterstate-advantage-inference-batch-v1"
PREDICTION_SCHEMA = "world-afterstate-advantage-prediction-v1"
RESULT_SCHEMA = "world-afterstate-advantage-audit-result-v1"
WORLD_SHUFFLE_RESULT_SCHEMA = (
    "world-afterstate-advantage-world-shuffle-result-v1")
MICRO_LEVEL = 1_000_000
BOOTSTRAP_REPLICATES = 10_000
MINIMUM_SELECTION_DOSE_PPM = 50_000
AUTHORITY = {
    "dataset_opening_authorized": False,
    "training_execution_authorized": False,
    "audit_opening_authorized": False,
    "report_opening_authorized": False,
    "world_twin_generation_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "retry_authorized": False,
    "r5_authorized": False,
}


class WorldAfterstateV1EvaluationError(ValueError):
    """A target-free input, prediction, audit population, or gate drifted."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV1EvaluationError(f"{label} drift")
    return value


def _round_divide(numerator: int, denominator: int) -> int:
    if isinstance(numerator, bool) or not isinstance(numerator, int) \
            or isinstance(denominator, bool) or not isinstance(denominator, int) \
            or denominator <= 0:
        raise WorldAfterstateV1EvaluationError("integer rounding request drift")
    sign = -1 if numerator < 0 else 1
    return sign * ((abs(numerator) + denominator // 2) // denominator)


@dataclass(frozen=True)
class AdvantageInferenceBatchV1:
    state_group_ids: tuple[str, ...]
    candidate_indexes: tuple[int, ...]
    incumbent_successor_sha256s: tuple[str, ...]
    candidate_successor_sha256s: tuple[str, ...]
    incumbent: SuccessorBatchV1
    candidate: SuccessorBatchV1
    schema: str = INFERENCE_BATCH_SCHEMA

    def validate(self) -> None:
        count = len(self.state_group_ids)
        if self.schema != INFERENCE_BATCH_SCHEMA or count <= 0 \
                or any(type(value) is not tuple or len(value) != count
                       for value in (
                           self.state_group_ids, self.candidate_indexes,
                           self.incumbent_successor_sha256s,
                           self.candidate_successor_sha256s)) \
                or type(self.incumbent) is not SuccessorBatchV1 \
                or type(self.candidate) is not SuccessorBatchV1:
            raise WorldAfterstateV1EvaluationError(
                "advantage inference batch identity drift")
        self.incumbent.validate()
        self.candidate.validate()
        if self.incumbent.size != count or self.candidate.size != count:
            raise WorldAfterstateV1EvaluationError(
                "advantage inference batch tensor drift")
        seen = set()
        for state, candidate, incumbent_sha, candidate_sha in zip(
                self.state_group_ids, self.candidate_indexes,
                self.incumbent_successor_sha256s,
                self.candidate_successor_sha256s, strict=True):
            _digest(state, "advantage inference state group")
            _digest(incumbent_sha, "advantage inference incumbent successor")
            _digest(candidate_sha, "advantage inference candidate successor")
            key = (state, candidate)
            if isinstance(candidate, bool) or not isinstance(candidate, int) \
                    or candidate < 1 or key in seen \
                    or incumbent_sha == candidate_sha:
                raise WorldAfterstateV1EvaluationError(
                    "advantage inference sibling identity drift")
            seen.add(key)


def collate_inference_pairs(
        *, state_group_ids: Sequence[str], candidate_indexes: Sequence[int],
        incumbent_successor_sha256s: Sequence[str],
        candidate_successor_sha256s: Sequence[str],
        incumbent_tensors: Sequence[WorldAfterstateTensorsV0],
        candidate_tensors: Sequence[WorldAfterstateTensorsV0]) \
        -> AdvantageInferenceBatchV1:
    fields = (
        state_group_ids, candidate_indexes, incumbent_successor_sha256s,
        candidate_successor_sha256s, incumbent_tensors, candidate_tensors,
    )
    if any(type(value) not in (list, tuple) for value in fields) \
            or not state_group_ids \
            or any(len(value) != len(state_group_ids) for value in fields):
        raise WorldAfterstateV1EvaluationError(
            "advantage inference population drift")
    result = AdvantageInferenceBatchV1(
        state_group_ids=tuple(state_group_ids),
        candidate_indexes=tuple(candidate_indexes),
        incumbent_successor_sha256s=tuple(incumbent_successor_sha256s),
        candidate_successor_sha256s=tuple(candidate_successor_sha256s),
        incumbent=collate_successor_tensors(incumbent_tensors),
        candidate=collate_successor_tensors(candidate_tensors))
    result.validate()
    return result


@dataclass(frozen=True)
class AdvantagePredictionV1:
    state_group_id: str
    candidate_index: int
    incumbent_successor_sha256: str
    candidate_successor_sha256: str
    member_index: int
    model_state_sha256: str
    advantage_microlevels: int
    schema: str = PREDICTION_SCHEMA

    def validate(self) -> None:
        for label, value in (
                ("prediction state group", self.state_group_id),
                ("prediction incumbent successor",
                 self.incumbent_successor_sha256),
                ("prediction candidate successor",
                 self.candidate_successor_sha256),
                ("prediction model state", self.model_state_sha256)):
            _digest(value, label)
        if self.schema != PREDICTION_SCHEMA \
                or isinstance(self.candidate_index, bool) \
                or not isinstance(self.candidate_index, int) \
                or self.candidate_index < 1 \
                or isinstance(self.member_index, bool) \
                or not isinstance(self.member_index, int) \
                or not 0 <= self.member_index < COHORT_SIZE \
                or isinstance(self.advantage_microlevels, bool) \
                or not isinstance(self.advantage_microlevels, int) \
                or not -203 * MICRO_LEVEL \
                <= self.advantage_microlevels <= 203 * MICRO_LEVEL \
                or self.incumbent_successor_sha256 \
                == self.candidate_successor_sha256:
            raise WorldAfterstateV1EvaluationError(
                "advantage prediction identity/value drift")

    def key(self) -> tuple[str, int, int]:
        self.validate()
        return (self.state_group_id, self.candidate_index,
                self.member_index)

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": self.schema,
            "state_group_id": self.state_group_id,
            "candidate_index": self.candidate_index,
            "incumbent_successor_sha256": self.incumbent_successor_sha256,
            "candidate_successor_sha256": self.candidate_successor_sha256,
            "member_index": self.member_index,
            "model_state_sha256": self.model_state_sha256,
            "advantage_microlevels": self.advantage_microlevels,
        }


def _batch_tensor(
        batch: SuccessorBatchV1, index: int) -> WorldAfterstateTensorsV0:
    length = int(batch.history_lengths[index])
    return WorldAfterstateTensorsV0(
        public=batch.public[index].detach().cpu().numpy().copy(),
        history=batch.history[index, :length].detach().cpu().numpy().copy(),
        world=batch.world[index].detach().cpu().numpy().copy(),
        perspective=batch.perspective[index].detach().cpu().numpy().copy())


def inference_population_sha256(value: AdvantageInferenceBatchV1) -> str:
    """Bind every identity and exact target-free tensor row."""
    if type(value) is not AdvantageInferenceBatchV1:
        raise WorldAfterstateV1EvaluationError(
            "advantage inference population type drift")
    value.validate()
    rows = []
    for index, (state, candidate, incumbent_sha, candidate_sha) in enumerate(
            zip(value.state_group_ids, value.candidate_indexes,
                value.incumbent_successor_sha256s,
                value.candidate_successor_sha256s, strict=True)):
        rows.append({
            "state_group_id": state, "candidate_index": candidate,
            "incumbent_successor_sha256": incumbent_sha,
            "candidate_successor_sha256": candidate_sha,
            "incumbent_tensor_sha256": successor_tensor_sha256(
                _batch_tensor(value.incumbent, index)),
            "candidate_tensor_sha256": successor_tensor_sha256(
                _batch_tensor(value.candidate, index)),
        })
    return _sha({
        "schema": "world-afterstate-advantage-inference-population-v1",
        "rows": rows,
    })


def prediction_population_sha256(
        values: Sequence[AdvantagePredictionV1]) -> str:
    if type(values) not in (list, tuple) or not values \
            or any(type(value) is not AdvantagePredictionV1
                   for value in values):
        raise WorldAfterstateV1EvaluationError(
            "advantage prediction population drift")
    rows = sorted((value.payload() for value in values), key=lambda row: (
        row["state_group_id"], row["candidate_index"], row["member_index"]))
    keys = [(row["state_group_id"], row["candidate_index"],
             row["member_index"]) for row in rows]
    if len(keys) != len(set(keys)):
        raise WorldAfterstateV1EvaluationError(
            "duplicate advantage prediction")
    return _sha({
        "schema": "world-afterstate-advantage-prediction-population-v1",
        "rows": rows,
    })


def predict_advantages(
        model: WorldAfterstateAdvantageV1,
        batch: AdvantageInferenceBatchV1, *,
        member_index: int) -> tuple[AdvantagePredictionV1, ...]:
    if type(model) is not WorldAfterstateAdvantageV1 \
            or type(batch) is not AdvantageInferenceBatchV1 \
            or isinstance(member_index, bool) \
            or not isinstance(member_index, int) \
            or not 0 <= member_index < COHORT_SIZE:
        raise WorldAfterstateV1EvaluationError(
            "advantage prediction request drift")
    batch.validate()
    before = model_state_sha256(model)
    was_training = model.training
    model.eval()
    try:
        with torch.no_grad():
            raw = model(batch.incumbent, batch.candidate).cpu()
    finally:
        model.train(was_training)
    if raw.shape != (len(batch.state_group_ids),) \
            or not bool(torch.all(torch.isfinite(raw))) \
            or model_state_sha256(model) != before:
        raise WorldAfterstateV1EvaluationError(
            "advantage prediction execution drift")
    rows = tuple(AdvantagePredictionV1(
        state_group_id=state, candidate_index=candidate,
        incumbent_successor_sha256=incumbent_sha,
        candidate_successor_sha256=candidate_sha,
        member_index=member_index, model_state_sha256=before,
        advantage_microlevels=int(round(float(raw[index]) * MICRO_LEVEL)))
        for index, (state, candidate, incumbent_sha, candidate_sha) in enumerate(
            zip(batch.state_group_ids, batch.candidate_indexes,
                batch.incumbent_successor_sha256s,
                batch.candidate_successor_sha256s, strict=True)))
    for row in rows:
        row.validate()
    return rows


def _bootstrap_interval(
        deal_values: dict[str, tuple[int, int]], *, namespace: str,
        replicates: int) -> tuple[int, int, int]:
    if not deal_values or type(namespace) is not str or not namespace \
            or isinstance(replicates, bool) or not isinstance(replicates, int) \
            or replicates < 100 \
            or any(type(value) is not tuple or len(value) != 2
                   or type(value[0]) is not int or type(value[1]) is not int
                   or value[1] <= 0 for value in deal_values.values()):
        raise WorldAfterstateV1EvaluationError(
            "advantage bootstrap request drift")
    deals = sorted(deal_values)
    rng = random.Random(int.from_bytes(hashlib.sha256(
        f"world-afterstate-v1|{namespace}".encode("ascii")).digest()[:16],
        "big"))
    samples = []
    for _ in range(replicates):
        numerator = 0
        denominator = 0
        for _ in deals:
            value, count = deal_values[deals[rng.randrange(len(deals))]]
            numerator += value
            denominator += count
        samples.append(_round_divide(numerator, denominator))
    samples.sort()
    mean = _round_divide(
        sum(value for value, _ in deal_values.values()),
        sum(count for _, count in deal_values.values()))
    return (mean, samples[(replicates * 5) // 100],
            samples[(replicates * 95) // 100])


def _metric(value: tuple[int, int, int]) -> dict[str, int]:
    return {"mean": value[0], "bootstrap_lower": value[1],
            "bootstrap_upper": value[2]}


def evaluate_advantage_audit(
        joined: Sequence[JoinedAdvantageV1],
        predictions: Sequence[AdvantagePredictionV1], *,
        bootstrap_replicates: int = BOOTSTRAP_REPLICATES) -> dict[str, Any]:
    if type(joined) not in (list, tuple) or not joined \
            or type(predictions) not in (list, tuple) or not predictions:
        raise WorldAfterstateV1EvaluationError(
            "advantage audit population drift")
    prediction_map = {}
    model_states: dict[int, set[str]] = defaultdict(set)
    for row in predictions:
        if type(row) is not AdvantagePredictionV1:
            raise WorldAfterstateV1EvaluationError(
                "advantage audit prediction type drift")
        key = row.key()
        if key in prediction_map:
            raise WorldAfterstateV1EvaluationError(
                "duplicate advantage prediction")
        prediction_map[key] = row
        model_states[row.member_index].add(row.model_state_sha256)
    if set(model_states) != set(range(COHORT_SIZE)) \
            or any(len(values) != 1 for values in model_states.values()) \
            or len({next(iter(values)) for values in model_states.values()}) \
            != COHORT_SIZE:
        raise WorldAfterstateV1EvaluationError(
            "advantage audit model cohort drift")
    states: dict[str, list[JoinedAdvantageV1]] = defaultdict(list)
    seen_pairs = set()
    for value in joined:
        if type(value) is not JoinedAdvantageV1:
            raise WorldAfterstateV1EvaluationError(
                "advantage audit joined-row type drift")
        value.validate()
        if value.pair.fold != "calibration" or value.key() in seen_pairs:
            raise WorldAfterstateV1EvaluationError(
                "advantage audit split/pair drift")
        seen_pairs.add(value.key())
        states[value.pair.state_group_id].append(value)

    error_deals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    utility_deals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    member_utility = [0] * COHORT_SIZE
    selected = 0
    selected_utility = 0
    nonpositive_selected = 0
    minimum_selected = None
    used_predictions = set()
    pair_count = 0
    for state_id in sorted(states):
        rows = sorted(states[state_id], key=lambda value: value.key())
        candidates = sorted({value.pair.candidate_index for value in rows})
        expected = [(candidate, replicate) for candidate in candidates
                    for replicate in (0, 1)]
        if candidates != list(range(1, len(candidates) + 1)) \
                or [(value.pair.candidate_index, value.pair.replicate)
                    for value in rows] != expected:
            raise WorldAfterstateV1EvaluationError(
                "advantage audit incomplete root")
        first = rows[0].pair
        if any(value.pair.deal_group_sha256 != first.deal_group_sha256
               or value.pair.state_identity() != first.state_identity()
               for value in rows):
            raise WorldAfterstateV1EvaluationError(
                "advantage audit cross-sibling binding drift")
        ensemble_sums = {}
        member_values = {member: {} for member in range(COHORT_SIZE)}
        truths: dict[int, list[int]] = defaultdict(list)
        root_error = 0
        for candidate in candidates:
            candidate_rows = [value for value in rows
                              if value.pair.candidate_index == candidate]
            member_rows = []
            for member in range(COHORT_SIZE):
                key = (state_id, candidate, member)
                prediction = prediction_map.get(key)
                if prediction is None \
                        or prediction.incumbent_successor_sha256 \
                        != candidate_rows[0].pair.incumbent_successor_sha256 \
                        or prediction.candidate_successor_sha256 \
                        != candidate_rows[0].pair.candidate_successor_sha256:
                    raise WorldAfterstateV1EvaluationError(
                        "advantage audit prediction binding drift")
                member_rows.append(prediction)
                member_values[member][candidate] = \
                    prediction.advantage_microlevels
                used_predictions.add(key)
            ensemble_sum = sum(
                prediction.advantage_microlevels for prediction in member_rows)
            ensemble_sums[candidate] = ensemble_sum
            for value in candidate_rows:
                truth = value.pair.advantage_levels * MICRO_LEVEL
                truths[candidate].append(truth)
                baseline_error = abs(truth)
                model_error = _round_divide(
                    abs(truth * COHORT_SIZE - ensemble_sum), COHORT_SIZE)
                root_error += baseline_error - model_error
                pair_count += 1
        root_error = _round_divide(root_error, len(rows))
        error_deals[first.deal_group_sha256][0] += root_error
        error_deals[first.deal_group_sha256][1] += 1

        choice = max([0, *candidates], key=lambda candidate: (
            0 if candidate == 0 else ensemble_sums[candidate], -candidate))
        utility = 0 if choice == 0 else _round_divide(
            sum(truths[choice]), len(truths[choice]))
        utility_deals[first.deal_group_sha256][0] += utility
        utility_deals[first.deal_group_sha256][1] += 1
        if choice != 0:
            selected += 1
            selected_utility += utility
            nonpositive_selected += int(utility <= 0)
            minimum_selected = utility if minimum_selected is None \
                else min(minimum_selected, utility)
        for member in range(COHORT_SIZE):
            member_choice = max([0, *candidates], key=lambda candidate: (
                0 if candidate == 0 else member_values[member][candidate],
                -candidate))
            if member_choice != 0:
                member_utility[member] += _round_divide(
                    sum(truths[member_choice]), len(truths[member_choice]))
    if used_predictions != set(prediction_map):
        raise WorldAfterstateV1EvaluationError(
            "unused advantage prediction")
    error = _bootstrap_interval(
        {key: tuple(value) for key, value in error_deals.items()},
        namespace="advantage-error", replicates=bootstrap_replicates)
    utility = _bootstrap_interval(
        {key: tuple(value) for key, value in utility_deals.items()},
        namespace="action-utility", replicates=bootstrap_replicates)
    state_count = len(states)
    dose = selected * 1_000_000 // state_count
    positive_members = sum(value > 0 for value in member_utility)
    passed = error[1] > 0 and utility[1] > 0 \
        and positive_members >= 6 and dose >= MINIMUM_SELECTION_DOSE_PPM
    body = {
        "schema": RESULT_SCHEMA,
        "state_count": state_count,
        "pair_count": pair_count,
        "deal_count": len(error_deals),
        "advantage_error_improvement_microlevels": _metric(error),
        "action_utility_microlevels": _metric(utility),
        # With the protected incumbent as comparator, this is the exact same
        # per-deal quantity. Publishing the identity prevents double-counting.
        "simple_regret_improvement_microlevels": _metric(utility),
        "regret_utility_identity_passed": True,
        "positive_member_count": positive_members,
        "member_count": COHORT_SIZE,
        "selected_nonincumbent_state_count": selected,
        "selection_dose_ppm": dose,
        "selected_conditional_utility_microlevels": (
            0 if selected == 0
            else _round_divide(selected_utility, selected)),
        "nonpositive_selected_state_count": nonpositive_selected,
        "minimum_selected_utility_microlevels": (
            0 if minimum_selected is None else minimum_selected),
        "bootstrap_replicates": bootstrap_replicates,
        "passed": passed,
        "authority": dict(AUTHORITY),
    }
    return {**body, "result_sha256": _sha(body)}


def validate_advantage_audit_result(value: object) -> None:
    required = {
        "schema", "state_count", "pair_count", "deal_count",
        "advantage_error_improvement_microlevels",
        "action_utility_microlevels",
        "simple_regret_improvement_microlevels",
        "regret_utility_identity_passed", "positive_member_count",
        "member_count", "selected_nonincumbent_state_count",
        "selection_dose_ppm", "selected_conditional_utility_microlevels",
        "nonpositive_selected_state_count",
        "minimum_selected_utility_microlevels", "bootstrap_replicates",
        "passed", "authority", "result_sha256",
    }
    if type(value) is not dict or set(value) != required \
            or value.get("schema") != RESULT_SCHEMA \
            or value.get("authority") != AUTHORITY \
            or value.get("regret_utility_identity_passed") is not True \
            or value.get("member_count") != COHORT_SIZE \
            or value.get("bootstrap_replicates") != BOOTSTRAP_REPLICATES \
            or type(value.get("passed")) is not bool:
        raise WorldAfterstateV1EvaluationError(
            "advantage audit result schema drift")
    integers = (
        "state_count", "pair_count", "deal_count", "positive_member_count",
        "selected_nonincumbent_state_count", "selection_dose_ppm",
        "selected_conditional_utility_microlevels",
        "nonpositive_selected_state_count",
        "minimum_selected_utility_microlevels", "bootstrap_replicates",
    )
    if any(isinstance(value.get(key), bool)
           or not isinstance(value.get(key), int) for key in integers) \
            or value["state_count"] <= 0 or value["pair_count"] <= 0 \
            or value["deal_count"] <= 0 \
            or not 0 <= value["positive_member_count"] <= COHORT_SIZE \
            or not 0 <= value["selected_nonincumbent_state_count"] \
            <= value["state_count"] \
            or value["selection_dose_ppm"] \
            != value["selected_nonincumbent_state_count"] * 1_000_000 \
            // value["state_count"] \
            or not 0 <= value["nonpositive_selected_state_count"] \
            <= value["selected_nonincumbent_state_count"]:
        raise WorldAfterstateV1EvaluationError(
            "advantage audit result population drift")
    for key in (
            "advantage_error_improvement_microlevels",
            "action_utility_microlevels",
            "simple_regret_improvement_microlevels"):
        metric = value.get(key)
        if type(metric) is not dict or set(metric) != {
                "mean", "bootstrap_lower", "bootstrap_upper"} \
                or any(isinstance(number, bool) or not isinstance(number, int)
                       for number in metric.values()):
            raise WorldAfterstateV1EvaluationError(
                "advantage audit result metric drift")
    if value["simple_regret_improvement_microlevels"] \
            != value["action_utility_microlevels"]:
        raise WorldAfterstateV1EvaluationError(
            "advantage audit regret/utility identity drift")
    expected_pass = (
        value["advantage_error_improvement_microlevels"][
            "bootstrap_lower"] > 0
        and value["action_utility_microlevels"]["bootstrap_lower"] > 0
        and value["positive_member_count"] >= 6
        and value["selection_dose_ppm"] >= MINIMUM_SELECTION_DOSE_PPM)
    body = {key: item for key, item in value.items()
            if key != "result_sha256"}
    if value["passed"] is not expected_pass \
            or _digest(value.get("result_sha256"),
                       "advantage audit result SHA-256") \
            != _sha(body):
        raise WorldAfterstateV1EvaluationError(
            "advantage audit result reconstruction drift")


def evaluate_world_shuffle_delta(
        joined: Sequence[JoinedAdvantageV1],
        natural_predictions: Sequence[AdvantagePredictionV1],
        shuffled_predictions: Sequence[AdvantagePredictionV1], *,
        bootstrap_replicates: int = BOOTSTRAP_REPLICATES) -> dict[str, Any]:
    """Compare natural and world-shuffled forecasts on the same deal roots."""
    if type(joined) not in (list, tuple) or not joined:
        raise WorldAfterstateV1EvaluationError(
            "world-shuffle audit population drift")

    def prediction_map(values, label):
        if type(values) not in (list, tuple) or not values:
            raise WorldAfterstateV1EvaluationError(
                f"world-shuffle {label} prediction population drift")
        result = {}
        model_states: dict[int, set[str]] = defaultdict(set)
        for row in values:
            if type(row) is not AdvantagePredictionV1:
                raise WorldAfterstateV1EvaluationError(
                    f"world-shuffle {label} prediction type drift")
            key = row.key()
            if key in result:
                raise WorldAfterstateV1EvaluationError(
                    f"duplicate world-shuffle {label} prediction")
            result[key] = row
            model_states[row.member_index].add(row.model_state_sha256)
        if set(model_states) != set(range(COHORT_SIZE)) \
                or any(len(value) != 1 for value in model_states.values()) \
                or len({next(iter(value)) for value in model_states.values()}) \
                != COHORT_SIZE:
            raise WorldAfterstateV1EvaluationError(
                f"world-shuffle {label} model cohort drift")
        return result, tuple(
            next(iter(model_states[member]))
            for member in range(COHORT_SIZE))

    natural_map, natural_models = prediction_map(
        natural_predictions, "natural")
    shuffled_map, shuffled_models = prediction_map(
        shuffled_predictions, "shuffled")
    if set(natural_map) != set(shuffled_map) \
            or natural_models != shuffled_models:
        raise WorldAfterstateV1EvaluationError(
            "world-shuffle paired prediction binding drift")
    states: dict[str, list[JoinedAdvantageV1]] = defaultdict(list)
    seen = set()
    for value in joined:
        if type(value) is not JoinedAdvantageV1:
            raise WorldAfterstateV1EvaluationError(
                "world-shuffle joined-row type drift")
        value.validate()
        if value.pair.fold != "calibration" or value.key() in seen:
            raise WorldAfterstateV1EvaluationError(
                "world-shuffle audit split/pair drift")
        seen.add(value.key())
        states[value.pair.state_group_id].append(value)
    error_deals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    utility_deals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    used = set()
    for state_id in sorted(states):
        rows = sorted(states[state_id], key=lambda value: value.key())
        candidates = sorted({value.pair.candidate_index for value in rows})
        if candidates != list(range(1, len(candidates) + 1)) \
                or [(value.pair.candidate_index, value.pair.replicate)
                    for value in rows] != [
                        (candidate, replicate) for candidate in candidates
                        for replicate in (0, 1)]:
            raise WorldAfterstateV1EvaluationError(
                "world-shuffle audit incomplete root")
        first = rows[0].pair
        if any(value.pair.deal_group_sha256 != first.deal_group_sha256
               or value.pair.state_identity() != first.state_identity()
               for value in rows):
            raise WorldAfterstateV1EvaluationError(
                "world-shuffle audit cross-sibling binding drift")
        truths: dict[int, list[int]] = defaultdict(list)
        natural_sums = {}
        shuffled_sums = {}
        root_error_delta = 0
        for candidate in candidates:
            candidate_rows = [value for value in rows
                              if value.pair.candidate_index == candidate]
            natural_member = []
            shuffled_member = []
            for member in range(COHORT_SIZE):
                key = (state_id, candidate, member)
                natural = natural_map.get(key)
                shuffled = shuffled_map.get(key)
                if natural is None or shuffled is None \
                        or natural.incumbent_successor_sha256 \
                        != candidate_rows[0].pair.incumbent_successor_sha256 \
                        or natural.candidate_successor_sha256 \
                        != candidate_rows[0].pair.candidate_successor_sha256 \
                        or shuffled.incumbent_successor_sha256 \
                        != natural.incumbent_successor_sha256 \
                        or shuffled.candidate_successor_sha256 \
                        != natural.candidate_successor_sha256:
                    raise WorldAfterstateV1EvaluationError(
                        "world-shuffle successor prediction binding drift")
                natural_member.append(natural.advantage_microlevels)
                shuffled_member.append(shuffled.advantage_microlevels)
                used.add(key)
            natural_sum = sum(natural_member)
            shuffled_sum = sum(shuffled_member)
            natural_sums[candidate] = natural_sum
            shuffled_sums[candidate] = shuffled_sum
            for value in candidate_rows:
                truth = value.pair.advantage_levels * MICRO_LEVEL
                truths[candidate].append(truth)
                natural_error = _round_divide(
                    abs(truth * COHORT_SIZE - natural_sum), COHORT_SIZE)
                shuffled_error = _round_divide(
                    abs(truth * COHORT_SIZE - shuffled_sum), COHORT_SIZE)
                root_error_delta += shuffled_error - natural_error
        root_error_delta = _round_divide(root_error_delta, len(rows))
        error_deals[first.deal_group_sha256][0] += root_error_delta
        error_deals[first.deal_group_sha256][1] += 1
        natural_choice = max([0, *candidates], key=lambda candidate: (
            0 if candidate == 0 else natural_sums[candidate], -candidate))
        shuffled_choice = max([0, *candidates], key=lambda candidate: (
            0 if candidate == 0 else shuffled_sums[candidate], -candidate))

        def utility(choice):
            return 0 if choice == 0 else _round_divide(
                sum(truths[choice]), len(truths[choice]))

        utility_deals[first.deal_group_sha256][0] += (
            utility(natural_choice) - utility(shuffled_choice))
        utility_deals[first.deal_group_sha256][1] += 1
    if used != set(natural_map):
        raise WorldAfterstateV1EvaluationError(
            "unused world-shuffle prediction")
    error = _bootstrap_interval(
        {key: tuple(value) for key, value in error_deals.items()},
        namespace="world-shuffle-advantage-error",
        replicates=bootstrap_replicates)
    utility = _bootstrap_interval(
        {key: tuple(value) for key, value in utility_deals.items()},
        namespace="world-shuffle-action-utility",
        replicates=bootstrap_replicates)
    body = {
        "schema": WORLD_SHUFFLE_RESULT_SCHEMA,
        "state_count": len(states), "deal_count": len(error_deals),
        "natural_minus_shuffled_advantage_error_microlevels":
            _metric(error),
        "natural_minus_shuffled_action_utility_microlevels":
            _metric(utility),
        "bootstrap_replicates": bootstrap_replicates,
        "passed": error[1] > 0 and utility[1] > 0,
        "authority": dict(AUTHORITY),
    }
    return {**body, "result_sha256": _sha(body)}


def validate_world_shuffle_delta(value: object) -> None:
    required = {
        "schema", "state_count", "deal_count",
        "natural_minus_shuffled_advantage_error_microlevels",
        "natural_minus_shuffled_action_utility_microlevels",
        "bootstrap_replicates", "passed", "authority", "result_sha256",
    }
    if type(value) is not dict or set(value) != required \
            or value.get("schema") != WORLD_SHUFFLE_RESULT_SCHEMA \
            or value.get("authority") != AUTHORITY \
            or value.get("bootstrap_replicates") != BOOTSTRAP_REPLICATES \
            or type(value.get("passed")) is not bool \
            or isinstance(value.get("state_count"), bool) \
            or not isinstance(value.get("state_count"), int) \
            or value["state_count"] <= 0 \
            or isinstance(value.get("deal_count"), bool) \
            or not isinstance(value.get("deal_count"), int) \
            or value["deal_count"] <= 0:
        raise WorldAfterstateV1EvaluationError(
            "world-shuffle result schema/population drift")
    metrics = (
        value.get("natural_minus_shuffled_advantage_error_microlevels"),
        value.get("natural_minus_shuffled_action_utility_microlevels"),
    )
    if any(type(metric) is not dict or set(metric) != {
            "mean", "bootstrap_lower", "bootstrap_upper"}
            or any(isinstance(number, bool) or not isinstance(number, int)
                   for number in metric.values()) for metric in metrics):
        raise WorldAfterstateV1EvaluationError(
            "world-shuffle result metric drift")
    expected = all(metric["bootstrap_lower"] > 0 for metric in metrics)
    body = {key: item for key, item in value.items()
            if key != "result_sha256"}
    if value["passed"] is not expected \
            or _digest(value.get("result_sha256"),
                       "world-shuffle result SHA-256") != _sha(body):
        raise WorldAfterstateV1EvaluationError(
            "world-shuffle result reconstruction drift")


__all__ = [
    "AUTHORITY", "BOOTSTRAP_REPLICATES", "AdvantageInferenceBatchV1",
    "AdvantagePredictionV1", "WorldAfterstateV1EvaluationError",
    "collate_inference_pairs", "evaluate_advantage_audit",
    "evaluate_world_shuffle_delta", "inference_population_sha256",
    "predict_advantages", "prediction_population_sha256",
    "validate_advantage_audit_result", "validate_world_shuffle_delta",
]
