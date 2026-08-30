"""Pure held-out evaluation kernels for Value-Afterstate V2.

The evaluator joins already-sealed prediction and continuation rows.  It has
no engine, file, audit-opening, controller, or downstream authority surface.
All score aggregation is root/action/replica balanced first and deal balanced
second, as preregistered by the V2 design.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .belief_contract import canonical_json_bytes
from .world_afterstate import category_signed_level
from .world_afterstate_v2_continuation import ContinuationOutcomeV2
from .world_afterstate_v2_inference import (
    CONTROL_NAMES, CandidatePredictionV2,
    reopen_prediction_population_manifest_v2,
    validate_prediction_population_manifest_v2,
)
from .world_afterstate_v2_metrics import (
    AUTHORITY as METRIC_AUTHORITY, BootstrapIntervalV2, JeffreysPriorV2,
    WorldAfterstateV2MetricsError, deal_cluster_bootstrap_interval,
    expected_signed_microlevels, ranked_probability_score_ppb,
    expected_signed_level_absolute_error_microlevels,
    paired_advantage_absolute_error_improvement_microlevels,
)


SCHEMA = "world-afterstate-v2-evaluation-v1"
RECEIPT_SCHEMA = "world-afterstate-v2-evaluation-metric-receipt-v1"
BOOTSTRAP_REPLICATES = 10_000
MEMBERS = (0, 1, 2, 3)
REPLICATES = tuple(range(8))
MICROLEVELS = 1_000_000
AUTHORITY = dict(METRIC_AUTHORITY)


class WorldAfterstateV2EvaluationError(ValueError):
    """A sealed V2 prediction/outcome population or score drifted."""


@dataclass(frozen=True)
class AbsoluteCurveScoreReceiptV2:
    """Absolute (not improvement) scores for one sealed population."""

    population_sha256: str
    source_binding_sha256: str
    deal_count: int
    rps_nano: int
    paired_target_error_nano: int
    deal_rps_nano: tuple[tuple[str, int], ...]
    deal_paired_target_error_nano: tuple[tuple[str, int], ...]
    schema: str = "world-afterstate-v2-absolute-curve-score-v2"

    def validate(self) -> None:
        _digest(self.population_sha256, "absolute score population SHA-256")
        _digest(self.source_binding_sha256,
                "absolute score source binding SHA-256")
        if self.schema != "world-afterstate-v2-absolute-curve-score-v2" \
                or isinstance(self.deal_count, bool) or not isinstance(self.deal_count, int) \
                or self.deal_count < 2 or len(self.deal_rps_nano) != self.deal_count \
                or len(self.deal_paired_target_error_nano) != self.deal_count \
                or self.rps_nano < 0 or self.paired_target_error_nano < 0:
            raise WorldAfterstateV2EvaluationError("absolute curve score drift")
        for values in (self.deal_rps_nano, self.deal_paired_target_error_nano):
            if type(values) is not tuple or any(
                    type(row) is not tuple or len(row) != 2 or type(row[0]) is not str
                    or isinstance(row[1], bool) or not isinstance(row[1], int)
                    or row[1] < 0 for row in values):
                raise WorldAfterstateV2EvaluationError("absolute score deal population drift")
            if len({row[0] for row in values}) != self.deal_count:
                raise WorldAfterstateV2EvaluationError("absolute score deal identity drift")
        if _mean(tuple(value for _, value in self.deal_rps_nano)) != self.rps_nano \
                or _mean(tuple(value for _, value in self.deal_paired_target_error_nano)) != self.paired_target_error_nano:
            raise WorldAfterstateV2EvaluationError("absolute score aggregate drift")

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": self.schema,
            "population_sha256": self.population_sha256,
            "source_binding_sha256": self.source_binding_sha256,
            "deal_count": self.deal_count,
            "rps_nano": self.rps_nano,
            "paired_target_error_nano": self.paired_target_error_nano,
            "deal_rps_nano": [list(row) for row in self.deal_rps_nano],
            "deal_paired_target_error_nano": [
                list(row) for row in self.deal_paired_target_error_nano],
        }

    def sha256(self) -> str:
        return _sha(self.payload())


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(
            char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV2EvaluationError(f"{label} drift")
    return value


def _mean(values: Sequence[int]) -> int:
    if not values:
        raise WorldAfterstateV2EvaluationError("empty metric group")
    numerator = sum(values)
    sign = -1 if numerator < 0 else 1
    return sign * ((abs(numerator) + len(values) // 2) // len(values))


def _identity(row: ContinuationOutcomeV2) -> tuple[str, str, str, str]:
    return (row.deal_sha256, row.slot_sha256, row.state_sha256,
            row.candidate_set_sha256)


@dataclass(frozen=True)
class EvaluationMetricReceiptV2:
    metric_name: str
    mean: int
    bootstrap: BootstrapIntervalV2
    schema: str = RECEIPT_SCHEMA
    authority: Mapping[str, bool] = field(default_factory=lambda: dict(AUTHORITY))

    def validate(self) -> None:
        if type(self.bootstrap) is not BootstrapIntervalV2:
            raise WorldAfterstateV2EvaluationError(
                "evaluation bootstrap type drift")
        if self.schema != RECEIPT_SCHEMA or self.authority != AUTHORITY \
                or type(self.metric_name) is not str or not self.metric_name \
                or self.mean != self.bootstrap.mean \
                or self.bootstrap.metric_name != self.metric_name:
            raise WorldAfterstateV2EvaluationError("evaluation receipt drift")
        try:
            self.bootstrap.validate()
        except Exception as exc:
            raise WorldAfterstateV2EvaluationError(
                "evaluation bootstrap receipt drift") from exc

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {"schema": self.schema, "metric_name": self.metric_name,
                "mean": self.mean, "bootstrap": self.bootstrap.payload(),
                "authority": dict(self.authority)}

    def sha256(self) -> str:
        return _sha(self.payload())

    @property
    def population_sha256(self) -> str:
        return self.bootstrap.population_sha256

    @property
    def lower_5th(self) -> int:
        return self.bootstrap.lower_5th

    @property
    def upper_95th(self) -> int:
        return self.bootstrap.upper_95th


@dataclass(frozen=True)
class ControlComparisonV2:
    control_name: str
    seed_block: int
    rps_improvement: EvaluationMetricReceiptV2
    absolute_error_improvement: EvaluationMetricReceiptV2
    paired_error_improvement: EvaluationMetricReceiptV2
    action_utility: EvaluationMetricReceiptV2
    positive_rps_member_count: int
    positive_paired_member_count: int
    positive_action_member_count: int
    authority: Mapping[str, bool] = field(default_factory=lambda: dict(AUTHORITY))
    schema: str = "world-afterstate-v2-control-comparison-v1"

    def validate(self) -> None:
        counts = (self.positive_rps_member_count,
                  self.positive_paired_member_count,
                  self.positive_action_member_count)
        if self.schema != "world-afterstate-v2-control-comparison-v1" \
                or self.control_name not in CONTROL_NAMES \
                or self.control_name == "natural" \
                or isinstance(self.seed_block, bool) \
                or self.seed_block not in (1, 2) \
                or any(isinstance(value, bool) or not isinstance(value, int)
                       or not 0 <= value <= 4 for value in counts) \
                or self.authority != AUTHORITY:
            raise WorldAfterstateV2EvaluationError("control comparison drift")
        for value in (self.rps_improvement, self.absolute_error_improvement,
                      self.paired_error_improvement,
                      self.action_utility):
            if type(value) is not EvaluationMetricReceiptV2:
                raise WorldAfterstateV2EvaluationError(
                    "control comparison metric type drift")
            value.validate()
        if tuple(value.metric_name for value in (
                self.rps_improvement, self.absolute_error_improvement,
                self.paired_error_improvement, self.action_utility)) != (
                    "natural-minus-control|rps",
                    "natural-minus-control|absolute",
                    "natural-minus-control|paired",
                    "natural-minus-control|action"):
            raise WorldAfterstateV2EvaluationError(
                "control comparison metric identity drift")
        population = self.rps_improvement.bootstrap.population_sha256
        if any(value.bootstrap.population_sha256 != population
               for value in (self.absolute_error_improvement,
                             self.paired_error_improvement,
                             self.action_utility)):
            raise WorldAfterstateV2EvaluationError(
                "control comparison population drift")

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {"schema": self.schema, "control_name": self.control_name,
                "seed_block": self.seed_block,
                "rps_improvement": self.rps_improvement.payload(),
                "absolute_error_improvement": self.absolute_error_improvement.payload(),
                "paired_error_improvement": self.paired_error_improvement.payload(),
                "action_utility": self.action_utility.payload(),
                "positive_rps_member_count": self.positive_rps_member_count,
                "positive_paired_member_count": self.positive_paired_member_count,
                "positive_action_member_count": self.positive_action_member_count,
                "authority": dict(self.authority),
                "learning_gates_1_to_4": list(self.learning_gates_1_to_4)}

    @property
    def learning_gates_1_to_4(self) -> tuple[bool, bool, bool, bool]:
        return (self.rps_improvement.bootstrap.lower_5th > 0,
                self.absolute_error_improvement.bootstrap.lower_5th > 0,
                self.paired_error_improvement.bootstrap.lower_5th > 0,
                self.positive_rps_member_count >= 3)

    def sha256(self) -> str:
        return _sha(self.payload())


@dataclass(frozen=True)
class EvaluationResultV2:
    population_sha256: str
    seed_block: int
    control_name: str
    rps_improvement: EvaluationMetricReceiptV2
    absolute_error_improvement: EvaluationMetricReceiptV2
    paired_error_improvement: EvaluationMetricReceiptV2
    selected_action_utility: EvaluationMetricReceiptV2
    cvar10_selected_utility: EvaluationMetricReceiptV2
    member_rps_improvement: tuple[int, ...]
    member_absolute_error_improvement: tuple[int, ...]
    member_paired_error_improvement: tuple[int, ...]
    member_action_utility: tuple[int, ...]
    positive_rps_member_count: int
    positive_absolute_error_member_count: int
    positive_paired_error_member_count: int
    positive_action_utility_member_count: int
    nonincumbent_dose_ppm: int
    learning_gates_1_to_4: tuple[bool, bool, bool, bool]
    deal_rps_improvement: tuple[tuple[str, int], ...] = ()
    deal_absolute_error_improvement: tuple[tuple[str, int], ...] = ()
    deal_paired_error_improvement: tuple[tuple[str, int], ...] = ()
    deal_action_utility: tuple[tuple[str, int], ...] = ()
    schema: str = SCHEMA
    authority: Mapping[str, bool] = field(default_factory=lambda: dict(AUTHORITY))

    def validate(self) -> None:
        if self.schema != SCHEMA or self.authority != AUTHORITY \
                or isinstance(self.seed_block, bool) \
                or self.seed_block not in (1, 2) \
                or self.control_name not in CONTROL_NAMES \
                or type(self.learning_gates_1_to_4) is not tuple \
                or len(self.learning_gates_1_to_4) != 4 \
                or any(type(value) is not bool for value in self.learning_gates_1_to_4):
            raise WorldAfterstateV2EvaluationError("evaluation result drift")
        _digest(self.population_sha256, "evaluation population SHA-256")
        for value in (self.rps_improvement, self.absolute_error_improvement,
                      self.paired_error_improvement, self.selected_action_utility,
                      self.cvar10_selected_utility):
            if type(value) is not EvaluationMetricReceiptV2:
                raise WorldAfterstateV2EvaluationError(
                    "evaluation metric type drift")
            value.validate()
        expected_metric_names = (
            f"{self.control_name}|block-{self.seed_block}|rps-improvement",
            f"{self.control_name}|block-{self.seed_block}|absolute-error-improvement",
            f"{self.control_name}|block-{self.seed_block}|paired-error-improvement",
            f"{self.control_name}|block-{self.seed_block}|action-utility",
            f"{self.control_name}|block-{self.seed_block}|cvar10-selected-utility",
        )
        if tuple(value.metric_name for value in (
                self.rps_improvement, self.absolute_error_improvement,
                self.paired_error_improvement, self.selected_action_utility,
                self.cvar10_selected_utility)) != expected_metric_names:
            raise WorldAfterstateV2EvaluationError(
                "evaluation metric identity drift")
        if any(value.bootstrap.population_sha256 != self.population_sha256
               for value in (self.rps_improvement, self.absolute_error_improvement,
                             self.paired_error_improvement,
                             self.selected_action_utility,
                             self.cvar10_selected_utility)):
            raise WorldAfterstateV2EvaluationError("evaluation metric population drift")
        counts = (self.positive_rps_member_count,
                  self.positive_absolute_error_member_count,
                  self.positive_paired_error_member_count,
                  self.positive_action_utility_member_count)
        if any(isinstance(value, bool) or not isinstance(value, int)
               or not 0 <= value <= 4 for value in counts):
            raise WorldAfterstateV2EvaluationError("evaluation sign counts drift")
        members = (self.member_rps_improvement,
                   self.member_absolute_error_improvement,
                   self.member_paired_error_improvement,
                   self.member_action_utility)
        if any(type(row) is not tuple or len(row) != 4
               or any(isinstance(item, bool) or not isinstance(item, int)
                      for item in row) for row in members):
            raise WorldAfterstateV2EvaluationError("evaluation member metrics drift")
        if isinstance(self.nonincumbent_dose_ppm, bool) \
                or not isinstance(self.nonincumbent_dose_ppm, int) \
                or not 0 <= self.nonincumbent_dose_ppm <= 1_000_000:
            raise WorldAfterstateV2EvaluationError("selection dose drift")
        for values in (self.deal_rps_improvement,
                       self.deal_absolute_error_improvement,
                       self.deal_paired_error_improvement,
                       self.deal_action_utility):
            if type(values) is not tuple or any(
                    type(item) is not tuple or len(item) != 2
                    or type(item[0]) is not str or not item[0]
                    or isinstance(item[1], bool) or not isinstance(item[1], int)
                    for item in values):
                raise WorldAfterstateV2EvaluationError("evaluation deal metrics drift")
            if not values or len({item[0] for item in values}) != len(values):
                raise WorldAfterstateV2EvaluationError(
                    "evaluation deal population drift")
        expected_counts = (
            sum(value > 0 for value in self.member_rps_improvement),
            sum(value > 0 for value in self.member_absolute_error_improvement),
            sum(value > 0 for value in self.member_paired_error_improvement),
            sum(value > 0 for value in self.member_action_utility),
        )
        if counts != expected_counts:
            raise WorldAfterstateV2EvaluationError("evaluation sign count drift")
        expected_gates = (
            self.rps_improvement.bootstrap.lower_5th > 0,
            self.absolute_error_improvement.bootstrap.lower_5th > 0,
            self.paired_error_improvement.bootstrap.lower_5th > 0,
            self.positive_rps_member_count >= 3,
        )
        if self.learning_gates_1_to_4 != expected_gates:
            raise WorldAfterstateV2EvaluationError(
                "evaluation learning-gate derivation drift")
        deal_populations = tuple(
            tuple(item[0] for item in values)
            for values in (
                self.deal_rps_improvement,
                self.deal_absolute_error_improvement,
                self.deal_paired_error_improvement,
                self.deal_action_utility,
            ))
        if any(population != deal_populations[0]
               for population in deal_populations[1:]):
            raise WorldAfterstateV2EvaluationError(
                "evaluation deal population cross-binding drift")
        for receipt, values in zip(
                (self.rps_improvement, self.absolute_error_improvement,
                 self.paired_error_improvement, self.selected_action_utility),
                (self.deal_rps_improvement,
                 self.deal_absolute_error_improvement,
                 self.deal_paired_error_improvement,
                 self.deal_action_utility), strict=True):
            if receipt.mean != _mean(tuple(value for _, value in values)):
                raise WorldAfterstateV2EvaluationError(
                    "evaluation deal/receipt mean binding drift")

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {"schema": self.schema, "population_sha256": self.population_sha256,
                "seed_block": self.seed_block, "control_name": self.control_name,
                "rps_improvement": self.rps_improvement.payload(),
                "absolute_error_improvement": self.absolute_error_improvement.payload(),
                "paired_error_improvement": self.paired_error_improvement.payload(),
                "selected_action_utility": self.selected_action_utility.payload(),
                "cvar10_selected_utility": self.cvar10_selected_utility.payload(),
                "member_rps_improvement": list(self.member_rps_improvement),
                "member_absolute_error_improvement": list(self.member_absolute_error_improvement),
                "member_paired_error_improvement": list(self.member_paired_error_improvement),
                "member_action_utility": list(self.member_action_utility),
                "positive_rps_member_count": self.positive_rps_member_count,
                "positive_absolute_error_member_count": self.positive_absolute_error_member_count,
                "positive_paired_error_member_count": self.positive_paired_error_count,
                "positive_action_utility_member_count": self.positive_action_utility_member_count,
                "nonincumbent_dose_ppm": self.nonincumbent_dose_ppm,
                "learning_gates_1_to_4": list(self.learning_gates_1_to_4),
                "deal_rps_improvement": [list(item) for item in self.deal_rps_improvement],
                "deal_absolute_error_improvement": [list(item) for item in self.deal_absolute_error_improvement],
                "deal_paired_error_improvement": [list(item) for item in self.deal_paired_error_improvement],
                "deal_action_utility": [list(item) for item in self.deal_action_utility],
                "authority": dict(self.authority)}

    @property
    def positive_paired_error_count(self) -> int:
        return self.positive_paired_error_member_count

    def sha256(self) -> str:
        return _sha(self.payload())


def _bind(predictions: Sequence[CandidatePredictionV2],
          outcomes: Sequence[ContinuationOutcomeV2], *, control_name: str,
          seed_block: int) -> tuple[dict[tuple[str, int, int], CandidatePredictionV2],
                                     dict[tuple[tuple[str, str, str, str], int, int], ContinuationOutcomeV2],
                                     dict[str, tuple[ContinuationOutcomeV2, ...]]]:
    if type(predictions) not in (tuple, list) or not predictions \
            or type(outcomes) not in (tuple, list) or not outcomes \
            or control_name == "natural" and seed_block not in (1, 2):
        raise WorldAfterstateV2EvaluationError("evaluation population drift")
    pmap: dict[tuple[str, int, int], CandidatePredictionV2] = {}
    omap: dict[tuple[tuple[str, str, str, str], int, int], ContinuationOutcomeV2] = {}
    roots: dict[str, list[ContinuationOutcomeV2]] = {}
    for row in predictions:
        if type(row) is not CandidatePredictionV2:
            raise WorldAfterstateV2EvaluationError("prediction type drift")
        try:
            row.validate()
        except Exception as exc:
            raise WorldAfterstateV2EvaluationError("prediction validation drift") from exc
        if row.control_name != control_name or row.seed_block != seed_block:
            raise WorldAfterstateV2EvaluationError("prediction control/block mixing")
        key = (row.root_sha256, row.candidate_index, row.member_index)
        if key in pmap:
            raise WorldAfterstateV2EvaluationError("duplicate prediction")
        pmap[key] = row
    for row in outcomes:
        if type(row) is not ContinuationOutcomeV2:
            raise WorldAfterstateV2EvaluationError("outcome type drift")
        try:
            row.validate()
        except Exception as exc:
            raise WorldAfterstateV2EvaluationError("outcome validation drift") from exc
        identity = _identity(row)
        if row.protected_incumbent != (row.candidate_index == 0):
            raise WorldAfterstateV2EvaluationError("outcome incumbent binding drift")
        key = (identity, row.candidate_index, row.replica)
        if key in omap:
            raise WorldAfterstateV2EvaluationError("duplicate outcome")
        omap[key] = row
        roots.setdefault(row.state_sha256, []).append(row)
    if not roots:
        raise WorldAfterstateV2EvaluationError("empty evaluation roots")
    # Reconstruct complete candidate×8 root populations and bind each
    # prediction's public digest identity to the corresponding outcome rows.
    by_root_identity: dict[str, tuple[str, str, str, str]] = {}
    root_by_deal: dict[str, str] = {}
    model_states: dict[int, set[str]] = {member: set() for member in MEMBERS}
    for state, rows in roots.items():
        identities = {_identity(row) for row in rows}
        if len(identities) != 1:
            raise WorldAfterstateV2EvaluationError("root identity mismatch")
        identity = next(iter(identities)); by_root_identity[state] = identity
        metadata = {(row.source, row.split, row.role, row.phase,
                     row.position, row.trump_rank, row.trump_mode,
                     row.points_bucket) for row in rows}
        if len(metadata) != 1:
            raise WorldAfterstateV2EvaluationError("root stratum mismatch")
        if identity[0] in root_by_deal:
            raise WorldAfterstateV2EvaluationError("deal has multiple roots")
        root_by_deal[identity[0]] = state
        candidates = sorted({row.candidate_index for row in rows})
        if candidates != list(range(len(candidates))) or len(candidates) < 2 \
                or len(rows) != len(candidates) * 8:
            raise WorldAfterstateV2EvaluationError("outcome candidate/replica drop")
        for candidate in candidates:
            if {row.replica for row in rows if row.candidate_index == candidate} \
                    != set(REPLICATES):
                raise WorldAfterstateV2EvaluationError("outcome replica drop")
        successors = [next(row.successor_sha256 for row in rows
                           if row.candidate_index == candidate)
                      for candidate in candidates]
        if any({row.successor_sha256 for row in rows
                if row.candidate_index == candidate} != {successors[candidate]}
               for candidate in candidates):
            raise WorldAfterstateV2EvaluationError("outcome successor drift")
        continuation_by_replica = {
            row.replica: row.continuation_sha256 for row in rows
            if row.candidate_index == 0}
        if set(continuation_by_replica) != set(REPLICATES) \
                or any(row.continuation_sha256 != continuation_by_replica[row.replica]
                       for row in rows):
            raise WorldAfterstateV2EvaluationError("outcome CRN binding drift")
        if _sha({"schema": "world-afterstate-v2-candidate-set-v1",
                 "state_sha256": identity[2],
                 "successor_sha256s": successors}) != identity[3]:
            raise WorldAfterstateV2EvaluationError("outcome candidate-set drift")
        root_predictions = [row for row in predictions
                            if row.state_sha256 == state]
        if not root_predictions:
            raise WorldAfterstateV2EvaluationError("prediction root drop")
        root_sha = root_predictions[0].root_sha256
        if any(row.root_sha256 != root_sha for row in root_predictions):
            raise WorldAfterstateV2EvaluationError("prediction root mismatch")
        if {(row.candidate_index, row.member_index) for row in root_predictions} \
                != {(candidate, member) for candidate in candidates for member in MEMBERS}:
            raise WorldAfterstateV2EvaluationError("prediction member drop")
        successor = {row.candidate_index: row.successor_sha256 for row in rows}
        for row in root_predictions:
            model_states[row.member_index].add(row.model_state_sha256)
            if (row.deal_sha256, row.slot_sha256, row.state_sha256,
                    row.candidate_set_sha256, row.successor_sha256) != (
                        *identity, successor[row.candidate_index]):
                raise WorldAfterstateV2EvaluationError("prediction/outcome misbinding")
    if set(by_root_identity) != set(roots):
        raise WorldAfterstateV2EvaluationError("evaluation root population drift")
    if any(len(values) != 1 for values in model_states.values()):
        raise WorldAfterstateV2EvaluationError("member model population drift")
    if {row.state_sha256 for row in predictions} != set(roots):
        raise WorldAfterstateV2EvaluationError("prediction root population drift")
    return pmap, omap, roots


def evaluate_absolute_curve_v2(
        prediction_manifest: Mapping[str, Any],
        outcomes: Sequence[ContinuationOutcomeV2],
        prior: JeffreysPriorV2) -> AbsoluteCurveScoreReceiptV2:
    """Derive absolute model RPS and paired-target error from sealed rows."""
    if type(prior) is not JeffreysPriorV2:
        raise WorldAfterstateV2EvaluationError("absolute score prior type drift")
    prior.validate()
    try:
        validate_prediction_population_manifest_v2(prediction_manifest)
        predictions = reopen_prediction_population_manifest_v2(prediction_manifest)
    except Exception as exc:
        raise WorldAfterstateV2EvaluationError("absolute prediction manifest refused") from exc
    control_name = prediction_manifest["control_name"]
    seed_block = prediction_manifest["seed_block"]
    pmap, _omap, roots = _bind(predictions, outcomes,
                                control_name=control_name, seed_block=seed_block)
    deal_rps: dict[str, list[int]] = {}
    deal_pair: dict[str, list[int]] = {}
    for state, rows in roots.items():
        identity = _identity(rows[0])
        root_sha = next(row.root_sha256 for row in predictions
                        if row.state_sha256 == state)
        by_candidate = {candidate: [row for row in rows
                                    if row.candidate_index == candidate]
                        for candidate in sorted({row.candidate_index for row in rows})}
        rps_values: list[int] = []
        pair_values: list[int] = []
        for member in MEMBERS:
            for candidate, truths in by_candidate.items():
                prediction = pmap[(root_sha, candidate, member)]
                rps_values.extend(ranked_probability_score_ppb(
                    prediction.probability_ppb, row.signed_level_category)
                    for row in truths)
            by_pair = {(row.candidate_index, row.replica): row for row in rows}
            for candidate in sorted(by_candidate):
                if candidate == 0:
                    continue
                for replica in REPLICATES:
                    candidate_row = by_pair[(candidate, replica)]
                    incumbent_row = by_pair[(0, replica)]
                    predicted = expected_signed_microlevels(
                        pmap[(root_sha, candidate, member)].probability_ppb) \
                        - expected_signed_microlevels(
                            pmap[(root_sha, 0, member)].probability_ppb)
                    target = int(round((
                        category_signed_level(candidate_row.signed_level_category)
                        - category_signed_level(incumbent_row.signed_level_category))
                        * MICROLEVELS))
                    pair_values.append((predicted - target) ** 2)
        deal_rps[identity[0]] = [_mean(tuple(rps_values))]
        deal_pair[identity[0]] = [_mean(tuple(pair_values))]
    rps = tuple(sorted((deal, _mean(values)) for deal, values in deal_rps.items()))
    pair = tuple(sorted((deal, _mean(values)) for deal, values in deal_pair.items()))
    result = AbsoluteCurveScoreReceiptV2(
        population_sha256=prediction_manifest["root_population_sha256"],
        source_binding_sha256=_sha({
            "schema": "world-afterstate-v2-absolute-curve-source-v2",
            "prediction_manifest": _sha(prediction_manifest),
            "outcomes": [dict(row.__dict__) for row in sorted(
                outcomes, key=lambda value: (value.deal_sha256,
                                             value.state_sha256,
                                             value.candidate_index,
                                             value.replica))],
            "prior": prior.payload(),
        }),
        deal_count=len(rps), rps_nano=_mean(tuple(value for _, value in rps)),
        paired_target_error_nano=_mean(tuple(value for _, value in pair)),
        deal_rps_nano=rps, deal_paired_target_error_nano=pair)
    result.validate()
    return result


def _receipt(name: str, deal_values: Mapping[str, int], population_sha256: str) \
        -> EvaluationMetricReceiptV2:
    try:
        interval = deal_cluster_bootstrap_interval(
            deal_values, population_sha256=population_sha256,
            metric_name=name)
    except WorldAfterstateV2MetricsError as exc:
        raise WorldAfterstateV2EvaluationError("metric bootstrap drift") from exc
    result = EvaluationMetricReceiptV2(name, interval.mean, interval)
    result.validate()
    return result


def _cvar_receipt(name: str, deal_values: Mapping[str, int],
                  population_sha256: str) -> EvaluationMetricReceiptV2:
    if not deal_values:
        raise WorldAfterstateV2EvaluationError("empty CVaR population")
    values = tuple(sorted(deal_values.items()))
    ordered = tuple(value for _, value in values)
    worst_count = max(1, math.ceil(len(ordered) * 0.10))
    seed = int.from_bytes(hashlib.sha256(
        f"{population_sha256}|{name}".encode("ascii")).digest()[:8], "big")
    rng = random.Random(seed)
    samples = []
    for _ in range(BOOTSTRAP_REPLICATES):
        draw = sorted(ordered[rng.randrange(len(ordered))]
                      for _ in range(len(ordered)))
        samples.append(_mean(tuple(draw[:worst_count])))
    samples.sort()
    interval = BootstrapIntervalV2(
        population_sha256=population_sha256, metric_name=name, seed=seed,
        replicates=BOOTSTRAP_REPLICATES, mean=_mean(tuple(sorted(ordered)[:worst_count])),
        lower_5th=samples[499], upper_95th=samples[9499])
    result = EvaluationMetricReceiptV2(name, interval.mean, interval)
    result.validate()
    return result


def _evaluate_bound(
        prediction_manifest: Mapping[str, Any],
        outcomes: Sequence[ContinuationOutcomeV2], prior: JeffreysPriorV2, *,
        control_name: str, seed_block: int) -> EvaluationResultV2:
    if type(prior) is not JeffreysPriorV2:
        raise WorldAfterstateV2EvaluationError("prior type drift")
    prior.validate()
    try:
        validate_prediction_population_manifest_v2(prediction_manifest)
        predictions = reopen_prediction_population_manifest_v2(
            prediction_manifest)
    except Exception as exc:
        raise WorldAfterstateV2EvaluationError(
            "prediction manifest refused") from exc
    if prediction_manifest["split"] not in ("select", "audit") \
            or prediction_manifest["control_name"] != control_name \
            or prediction_manifest["seed_block"] != seed_block:
        raise WorldAfterstateV2EvaluationError(
            "prediction manifest evaluation identity drift")
    population_sha256 = prediction_manifest["root_population_sha256"]
    pmap, omap, roots = _bind(predictions, outcomes,
                               control_name=control_name, seed_block=seed_block)
    # State is indexed by root SHA, while outcomes are indexed by immutable
    # deal identity.  Every root has one deal in the reviewed population.
    root_data: dict[str, dict[str, Any]] = {}
    for state, rows in roots.items():
        identity = _identity(rows[0]); root_sha = next(
            row.root_sha256 for row in predictions if row.state_sha256 == state)
        candidates = sorted({row.candidate_index for row in rows})
        by_candidate = {candidate: [row for row in rows
                                     if row.candidate_index == candidate]
                        for candidate in candidates}
        member_rps: dict[int, list[int]] = {m: [] for m in MEMBERS}
        member_abs: dict[int, list[int]] = {m: [] for m in MEMBERS}
        member_pair: dict[int, list[int]] = {m: [] for m in MEMBERS}
        for member in MEMBERS:
            for candidate in candidates:
                pred = pmap[(root_sha, candidate, member)]
                truths = by_candidate[candidate]
                member_rps[member].append(_mean(tuple(
                    ranked_probability_score_ppb(
                        prior.probability_ppb(row.phase, row.role, row.points_bucket),
                        row.signed_level_category)
                    - ranked_probability_score_ppb(
                        pred.probability_ppb, row.signed_level_category)
                    for row in truths)))
                member_abs[member].append(_mean(tuple(
                    expected_signed_level_absolute_error_microlevels(
                        prior.probability_ppb(row.phase, row.role, row.points_bucket),
                        row.signed_level_category)
                    - expected_signed_level_absolute_error_microlevels(
                        pred.probability_ppb, row.signed_level_category)
                    for row in truths)))
            incumbent = by_candidate[0]
            for candidate in candidates[1:]:
                pred_c = pmap[(root_sha, candidate, member)]
                pred_i = pmap[(root_sha, 0, member)]
                member_pair[member].append(_mean(tuple(
                    paired_advantage_absolute_error_improvement_microlevels(
                        pred_c.probability_ppb, pred_i.probability_ppb,
                        row.signed_level_category,
                        incumbent[index].signed_level_category)
                    for index, row in enumerate(by_candidate[candidate]))))
        deal = identity[0]
        root_data[root_sha] = {"deal": deal, "candidates": candidates,
                               "rps": member_rps, "abs": member_abs,
                               "pair": member_pair, "rows": by_candidate,
                               "identity": identity, "root_sha": root_sha}
    deals = sorted({data["deal"] for data in root_data.values()})
    member_deal_rps: dict[int, dict[str, int]] = {m: {} for m in MEMBERS}
    member_deal_abs: dict[int, dict[str, int]] = {m: {} for m in MEMBERS}
    member_deal_pair: dict[int, dict[str, int]] = {m: {} for m in MEMBERS}
    member_deal_action: dict[int, dict[str, int]] = {m: {} for m in MEMBERS}
    ensemble_action: dict[str, int] = {}; selected_utility: dict[str, int] = {}
    selected_count = 0
    for data in root_data.values():
        deal = data["deal"]
        for m in MEMBERS:
            member_deal_rps[m][deal] = _mean(data["rps"][m])
            member_deal_abs[m][deal] = _mean(data["abs"][m])
            member_deal_pair[m][deal] = _mean(data["pair"][m])
        root_sha = data["root_sha"]
        sums = {candidate: sum(expected_signed_microlevels(
                    pmap[(root_sha, candidate, m)].probability_ppb)
                    for m in MEMBERS) for candidate in data["candidates"]}
        best = max(sums.values()); choice = 0 if sums.get(0) == best else min(
            candidate for candidate, value in sums.items() if value == best)
        ensemble_action[data["deal"]] = choice
        if choice != 0: selected_count += 1
        utilities = [category_signed_level(data["rows"][choice][replica].signed_level_category)
                     - category_signed_level(data["rows"][0][replica].signed_level_category)
                     for replica in REPLICATES]
        selected_utility[data["deal"]] = _mean(tuple(int(round(value * MICROLEVELS))
                                                     for value in utilities))
        for m in MEMBERS:
            member_choice = max(data["candidates"], key=lambda candidate: (
                expected_signed_microlevels(pmap[(root_sha, candidate, m)].probability_ppb),
                -candidate))
            member_deal_action[m][deal] = _mean(tuple(
                int(round((category_signed_level(data["rows"][member_choice][r].signed_level_category)
                           - category_signed_level(data["rows"][0][r].signed_level_category)) * MICROLEVELS))
                for r in REPLICATES))
    def metric_members(values: dict[int, dict[str, int]], name: str) -> tuple[EvaluationMetricReceiptV2, tuple[int, ...]]:
        member_means = tuple(_mean(tuple(values[m].values())) for m in MEMBERS)
        return _receipt(name, {deal: _mean(tuple(values[m][deal] for m in MEMBERS))
                               for deal in deals}, population_sha256), member_means
    rps_receipt, member_rps = metric_members(member_deal_rps, f"{control_name}|block-{seed_block}|rps-improvement")
    abs_receipt, member_abs = metric_members(member_deal_abs, f"{control_name}|block-{seed_block}|absolute-error-improvement")
    pair_receipt, member_pair = metric_members(member_deal_pair, f"{control_name}|block-{seed_block}|paired-error-improvement")
    member_action = tuple(
        _mean(tuple(member_deal_action[m].values())) for m in MEMBERS)
    action_receipt = _receipt(
        f"{control_name}|block-{seed_block}|action-utility",
        selected_utility, population_sha256)
    cvar = _cvar_receipt(
        f"{control_name}|block-{seed_block}|cvar10-selected-utility",
        {deal: selected_utility[deal] for deal in deals}, population_sha256)
    result = EvaluationResultV2(
        population_sha256=population_sha256, seed_block=seed_block,
        control_name=control_name, rps_improvement=rps_receipt,
        absolute_error_improvement=abs_receipt,
        paired_error_improvement=pair_receipt,
        selected_action_utility=action_receipt, cvar10_selected_utility=cvar,
        member_rps_improvement=member_rps,
        member_absolute_error_improvement=member_abs,
        member_paired_error_improvement=member_pair,
        member_action_utility=member_action,
        positive_rps_member_count=sum(value > 0 for value in member_rps),
        positive_absolute_error_member_count=sum(value > 0 for value in member_abs),
        positive_paired_error_member_count=sum(value > 0 for value in member_pair),
        positive_action_utility_member_count=sum(value > 0 for value in member_action),
        nonincumbent_dose_ppm=selected_count * 1_000_000 // len(deals),
        learning_gates_1_to_4=(rps_receipt.bootstrap.lower_5th > 0,
                               abs_receipt.bootstrap.lower_5th > 0,
                               pair_receipt.bootstrap.lower_5th > 0,
                               sum(value > 0 for value in member_rps) >= 3),
        deal_rps_improvement=tuple(sorted((deal, _mean(tuple(
            member_deal_rps[m][deal] for m in MEMBERS))) for deal in deals)),
        deal_absolute_error_improvement=tuple(sorted((deal, _mean(tuple(
            member_deal_abs[m][deal] for m in MEMBERS))) for deal in deals)),
        deal_paired_error_improvement=tuple(sorted((deal, _mean(tuple(
            member_deal_pair[m][deal] for m in MEMBERS))) for deal in deals)),
        deal_action_utility=tuple(sorted(selected_utility.items())))
    result.validate()
    return result


def evaluate_v2(
        prediction_manifest: Mapping[str, Any],
        outcomes: Sequence[ContinuationOutcomeV2], prior: JeffreysPriorV2, *,
        control_name: str | None = None,
        seed_block: int | None = None) -> EvaluationResultV2:
    """Evaluate one sealed control/block population; no terminal routing."""
    if type(prediction_manifest) is not dict:
        raise WorldAfterstateV2EvaluationError(
            "prediction manifest required")
    manifest_control = prediction_manifest.get("control_name")
    manifest_block = prediction_manifest.get("seed_block")
    if control_name is not None and control_name != manifest_control \
            or seed_block is not None and seed_block != manifest_block:
        raise WorldAfterstateV2EvaluationError(
            "evaluation caller/manifest identity drift")
    return _evaluate_bound(
        prediction_manifest, outcomes, prior,
        control_name=manifest_control, seed_block=manifest_block)


def evaluate_control_difference(
        natural: EvaluationResultV2, control: EvaluationResultV2) -> ControlComparisonV2:
    """Return natural-minus-control receipts for one block."""
    if type(natural) is not EvaluationResultV2 or type(control) is not EvaluationResultV2 \
            or natural.seed_block != control.seed_block \
            or natural.population_sha256 != control.population_sha256 \
            or natural.control_name != "natural" \
            or control.control_name == "natural":
        raise WorldAfterstateV2EvaluationError("control comparison binding drift")
    natural.validate(); control.validate()
    def diff(name: str, left: Sequence[tuple[str, int]],
             right: Sequence[tuple[str, int]]) -> EvaluationMetricReceiptV2:
        left_map, right_map = dict(left), dict(right)
        if set(left_map) != set(right_map):
            raise WorldAfterstateV2EvaluationError("control deal population drift")
        return _receipt(name,
                        {deal: left_map[deal] - right_map[deal]
                         for deal in left_map}, natural.population_sha256)
    result = ControlComparisonV2(
        control_name=control.control_name, seed_block=natural.seed_block,
        rps_improvement=diff("natural-minus-control|rps", natural.deal_rps_improvement,
                             control.deal_rps_improvement),
        absolute_error_improvement=diff("natural-minus-control|absolute", natural.deal_absolute_error_improvement,
                                        control.deal_absolute_error_improvement),
        paired_error_improvement=diff("natural-minus-control|paired", natural.deal_paired_error_improvement,
                                      control.deal_paired_error_improvement),
        action_utility=diff("natural-minus-control|action", natural.deal_action_utility,
                             control.deal_action_utility),
        positive_rps_member_count=sum(a > b for a, b in zip(
            natural.member_rps_improvement, control.member_rps_improvement)),
        positive_paired_member_count=sum(a > b for a, b in zip(
            natural.member_paired_error_improvement, control.member_paired_error_improvement)),
        positive_action_member_count=sum(a > b for a, b in zip(
            natural.member_action_utility, control.member_action_utility)))
    result.validate()
    return result


def validate_control_comparison(value: ControlComparisonV2) -> None:
    if type(value) is not ControlComparisonV2:
        raise WorldAfterstateV2EvaluationError("control comparison type drift")
    value.validate()


def validate_evaluation_result(value: EvaluationResultV2) -> None:
    if type(value) is not EvaluationResultV2:
        raise WorldAfterstateV2EvaluationError("evaluation result type drift")
    value.validate()


validate_evaluation_receipt = lambda value: value.validate()
evaluate_population_v2 = evaluate_v2
evaluate_audit_v2 = evaluate_v2
evaluate_block_v2 = evaluate_v2


__all__ = [
    "AUTHORITY", "AbsoluteCurveScoreReceiptV2", "ControlComparisonV2", "EvaluationMetricReceiptV2",
    "EvaluationResultV2", "WorldAfterstateV2EvaluationError", "evaluate_absolute_curve_v2", "evaluate_v2",
    "evaluate_population_v2", "evaluate_audit_v2", "evaluate_block_v2",
    "evaluate_control_difference",
    "validate_control_comparison", "validate_evaluation_receipt",
    "validate_evaluation_result",
]
