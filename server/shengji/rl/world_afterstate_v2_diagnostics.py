"""Strict, score-free receipts for the Value-Afterstate V2 recipe ladder.

These types authenticate already-produced diagnostics; they do not run an
optimizer, read data, open labels, select a terminal route, or perform I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
import hashlib
import math
from typing import Any, Sequence

from .belief_contract import canonical_json_bytes


CANARY_SCHEMA = "world-afterstate-v2-optimizer-canary-receipt-v2"
CURVE_SCHEMA = "world-afterstate-v2-nested-curve-receipt-v1"
POINT_SCHEMA = "world-afterstate-v2-nested-curve-point-v1"
STABILITY_SCHEMA = "world-afterstate-v2-primary-stability-receipt-v1"
MEMBER_SCHEMA = "world-afterstate-v2-primary-member-epoch-v1"
POWER_SCHEMA = "world-afterstate-v2-model-selector-power-receipt-v1"
CANARY_ROOT_COUNT = 16
CANARY_STEPS = 500
CANARY_PROGRESS_PPM = 800_000
CURVE_FRACTIONS_PPM = (250_000, 500_000, 1_000_000)
PRIMARY_MEMBER_COUNT = 4
REPLICA_COUNT = 8
Z_ALPHA_PPM = 1_644_854
Z_POWER_PPM = 841_621
DELTA_MICROLEVELS = 100_000  # +0.10 signed levels
ESTIMAND_IDENTITY = (
    "equal-weight-eight-replica-chosen-action-minus-"
    "production-incumbent;tie-to-incumbent")
AUTHORITY = {
    "optimizer_authorized": False,
    "training_authorized": False,
    "data_opening_authorized": False,
    "label_opening_authorized": False,
    "audit_opening_authorized": False,
    "terminal_route_authorized": False,
    "consumer_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "retry_authorized": False,
}


class WorldAfterstateV2DiagnosticsError(ValueError):
    """A V2 pre-audit diagnostic receipt violated its contract."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(
            char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV2DiagnosticsError(f"{label} drift")
    return value


def _int(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise WorldAfterstateV2DiagnosticsError(f"{label} drift")
    return value


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(float(value)):
        raise WorldAfterstateV2DiagnosticsError(f"{label} drift")
    return float(value)


def _authority(value: object) -> None:
    if value != AUTHORITY:
        raise WorldAfterstateV2DiagnosticsError("diagnostic authority drift")


@dataclass(frozen=True)
class OptimizerCanaryReceiptV2:
    source_p0_population_sha256: str
    root_population_sha256: str
    model_seed: int
    root_count: int
    optimizer_steps: int
    early_stopping_used: bool
    gradients_finite: bool
    weights_finite: bool
    initial_loss_nano: int
    empirical_loss_nano: int
    final_loss_nano: int
    normalized_progress_ppm: int
    passed: bool
    empirical_entropy_nano: int
    empirical_paired_residual_nano: int
    schema: str = CANARY_SCHEMA
    authority: dict[str, bool] = field(default_factory=lambda: dict(AUTHORITY))

    def validate(self) -> None:
        if self.schema != CANARY_SCHEMA or self.root_count != CANARY_ROOT_COUNT \
                or self.optimizer_steps != CANARY_STEPS \
                or type(self.early_stopping_used) is not bool \
                or type(self.gradients_finite) is not bool \
                or type(self.weights_finite) is not bool \
                or type(self.passed) is not bool:
            raise WorldAfterstateV2DiagnosticsError("optimizer canary identity drift")
        _digest(self.source_p0_population_sha256,
                "canary source P0 population SHA-256")
        _digest(self.root_population_sha256, "canary root population SHA-256")
        _int(self.model_seed, "canary model seed")
        if self.model_seed >= 2**63:
            raise WorldAfterstateV2DiagnosticsError(
                "optimizer canary model seed drift")
        for value, label in (
                (self.initial_loss_nano, "canary initial loss"),
                (self.empirical_loss_nano, "canary empirical loss"),
                (self.final_loss_nano, "canary final loss"),
                (self.normalized_progress_ppm, "canary normalized progress")):
            _int(value, label)
        _int(self.empirical_entropy_nano, "canary empirical entropy")
        _int(self.empirical_paired_residual_nano,
             "canary empirical paired residual")
        if self.empirical_loss_nano != self.empirical_entropy_nano:
            raise WorldAfterstateV2DiagnosticsError(
                "optimizer canary empirical loss/entropy drift")
        if self.empirical_paired_residual_nano != 0:
            raise WorldAfterstateV2DiagnosticsError(
                "optimizer canary empirical paired residual drift")
        denominator = self.initial_loss_nano - self.empirical_loss_nano
        numerator = self.initial_loss_nano - self.final_loss_nano
        expected = (numerator * 1_000_000 // denominator
                    if denominator > 0 else 0)
        if self.normalized_progress_ppm != max(0, expected):
            raise WorldAfterstateV2DiagnosticsError("optimizer canary progress drift")
        expected_passed = (
            not self.early_stopping_used and self.gradients_finite
            and self.weights_finite and denominator > 0
            and expected >= CANARY_PROGRESS_PPM)
        if self.passed is not expected_passed:
            raise WorldAfterstateV2DiagnosticsError(
                "optimizer canary gate reconstruction drift")
        _authority(self.authority)

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {"schema": self.schema,
                "source_p0_population_sha256": self.source_p0_population_sha256,
                "root_population_sha256": self.root_population_sha256,
                "model_seed": self.model_seed, "root_count": self.root_count,
                "optimizer_steps": self.optimizer_steps,
                "early_stopping_used": self.early_stopping_used,
                "gradients_finite": self.gradients_finite,
                "weights_finite": self.weights_finite,
                "initial_loss_nano": self.initial_loss_nano,
                "empirical_loss_nano": self.empirical_loss_nano,
                "final_loss_nano": self.final_loss_nano,
                "normalized_progress_ppm": self.normalized_progress_ppm,
                "passed": self.passed,
                "empirical_entropy_nano": self.empirical_entropy_nano,
                "empirical_paired_residual_nano": self.empirical_paired_residual_nano,
                "authority": dict(AUTHORITY)}

    def sha256(self) -> str:
        return _sha(self.payload())


@dataclass(frozen=True)
class NestedCurvePointV2:
    fraction_ppm: int
    independent_deal_count: int
    population_sha256: str
    fit_rps_nano: int
    select_rps_nano: int
    fit_paired_error_nano: int
    select_paired_error_nano: int
    checkpoint_sha256: str
    ensemble_member_eligible: bool = False
    schema: str = POINT_SCHEMA

    def validate(self) -> None:
        if self.schema != POINT_SCHEMA or self.fraction_ppm not in CURVE_FRACTIONS_PPM:
            raise WorldAfterstateV2DiagnosticsError("nested curve fraction drift")
        if type(self.ensemble_member_eligible) is not bool:
            raise WorldAfterstateV2DiagnosticsError("curve ensemble eligibility drift")
        _int(self.independent_deal_count, "curve independent deals", minimum=1)
        _digest(self.population_sha256, "curve population SHA-256")
        _digest(self.checkpoint_sha256, "curve checkpoint SHA-256")
        for value, label in ((self.fit_rps_nano, "fit RPS"),
                             (self.select_rps_nano, "select RPS"),
                             (self.fit_paired_error_nano, "fit paired error"),
                             (self.select_paired_error_nano, "select paired error")):
            _int(value, label)


def _slope(xs: Sequence[float], ys: Sequence[float]) -> float:
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    denominator = sum((x - mean_x) ** 2 for x in xs)
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator


@dataclass(frozen=True)
class NestedCurveReceiptV2:
    points: tuple[NestedCurvePointV2, ...]
    full_fit_population_sha256: str
    primary_member0_checkpoint_sha256: str
    fit_select_rps_gaps_nano: tuple[int, ...]
    fit_select_paired_error_gaps_nano: tuple[int, ...]
    fit_rps_slope: float
    select_rps_slope: float
    fit_paired_error_slope: float
    select_paired_error_slope: float
    prefix_order: str = "canonical-deal-hash"
    source_stratum_preserving: bool = True
    schema: str = CURVE_SCHEMA
    authority: dict[str, bool] = field(default_factory=lambda: dict(AUTHORITY))

    def validate(self) -> None:
        if self.schema != CURVE_SCHEMA or type(self.points) is not tuple \
                or len(self.points) != 3 or type(self.fit_select_rps_gaps_nano) is not tuple \
                or type(self.fit_select_paired_error_gaps_nano) is not tuple \
                or len(self.fit_select_rps_gaps_nano) != 3 \
                or len(self.fit_select_paired_error_gaps_nano) != 3:
            raise WorldAfterstateV2DiagnosticsError("nested curve receipt schema drift")
        if self.prefix_order != "canonical-deal-hash" \
                or self.source_stratum_preserving is not True:
            raise WorldAfterstateV2DiagnosticsError("curve prefix identity drift")
        points = sorted(self.points, key=lambda point: point.fraction_ppm)
        for point in points:
            point.validate()
        if tuple(point.fraction_ppm for point in points) != CURVE_FRACTIONS_PPM \
                or len({point.population_sha256 for point in points}) != 3 \
                or len({point.checkpoint_sha256 for point in points}) != 3:
            raise WorldAfterstateV2DiagnosticsError("nested curve point population drift")
        if any(point.ensemble_member_eligible for point in points[:2]) \
                or not points[2].ensemble_member_eligible:
            raise WorldAfterstateV2DiagnosticsError("curve ensemble eligibility drift")
        _digest(self.full_fit_population_sha256, "full curve population SHA-256")
        _digest(self.primary_member0_checkpoint_sha256,
                "primary member-0 checkpoint SHA-256")
        if points[-1].population_sha256 != self.full_fit_population_sha256 \
                or points[-1].checkpoint_sha256 != self.primary_member0_checkpoint_sha256:
            raise WorldAfterstateV2DiagnosticsError("100% curve binding drift")
        counts = tuple(point.independent_deal_count for point in points)
        if counts[2] % 4 or counts != (counts[2] // 4, counts[2] // 2, counts[2]):
            raise WorldAfterstateV2DiagnosticsError("curve prefix count drift")
        gaps_rps = tuple(point.fit_rps_nano - point.select_rps_nano for point in points)
        gaps_pair = tuple(point.fit_paired_error_nano - point.select_paired_error_nano
                          for point in points)
        if gaps_rps != self.fit_select_rps_gaps_nano \
                or gaps_pair != self.fit_select_paired_error_gaps_nano:
            raise WorldAfterstateV2DiagnosticsError("curve fit/select gap drift")
        xs = [math.log(point.independent_deal_count) for point in points]
        expected_slopes = (
            _slope(xs, [point.fit_rps_nano for point in points]),
            _slope(xs, [point.select_rps_nano for point in points]),
            _slope(xs, [point.fit_paired_error_nano for point in points]),
            _slope(xs, [point.select_paired_error_nano for point in points]))
        actual_slopes = (self.fit_rps_slope, self.select_rps_slope,
                         self.fit_paired_error_slope, self.select_paired_error_slope)
        if any(not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-9)
               for actual, expected in zip(actual_slopes, expected_slopes)):
            raise WorldAfterstateV2DiagnosticsError("curve slope drift")
        _authority(self.authority)

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {"schema": self.schema,
                "points": [point.__dict__ for point in sorted(
                    self.points, key=lambda point: point.fraction_ppm)],
                "full_fit_population_sha256": self.full_fit_population_sha256,
                "primary_member0_checkpoint_sha256": self.primary_member0_checkpoint_sha256,
                "fit_select_rps_gaps_nano": list(self.fit_select_rps_gaps_nano),
                "fit_select_paired_error_gaps_nano": list(
                    self.fit_select_paired_error_gaps_nano),
                "fit_rps_slope": self.fit_rps_slope,
                "select_rps_slope": self.select_rps_slope,
                "fit_paired_error_slope": self.fit_paired_error_slope,
                "select_paired_error_slope": self.select_paired_error_slope,
                "prefix_order": self.prefix_order,
                "source_stratum_preserving": self.source_stratum_preserving,
                "authority": dict(AUTHORITY)}

    def sha256(self) -> str:
        return _sha(self.payload())


@dataclass(frozen=True)
class PrimaryMemberEpochV2:
    member_index: int
    epoch: int
    fit_loss_nano: int
    select_loss_nano: int
    gradient_norm_nano: int
    update_norm_nano: int
    prediction_entropy_nano: int
    paired_target_error_nano: int
    schema: str = MEMBER_SCHEMA

    def validate(self) -> None:
        if self.schema != MEMBER_SCHEMA:
            raise WorldAfterstateV2DiagnosticsError("stability member schema drift")
        _int(self.member_index, "stability member index")
        _int(self.epoch, "stability epoch", minimum=1)
        for value, label in ((self.fit_loss_nano, "fit loss"),
                             (self.select_loss_nano, "select loss"),
                             (self.gradient_norm_nano, "gradient norm"),
                             (self.update_norm_nano, "update norm"),
                             (self.prediction_entropy_nano, "prediction entropy"),
                             (self.paired_target_error_nano, "paired target error")):
            _int(value, label)


@dataclass(frozen=True)
class PrimaryStabilityReceiptV2:
    members: tuple[tuple[PrimaryMemberEpochV2, ...], ...]
    selected_epochs: tuple[int, ...]
    common_epoch: int
    common_epoch_dispersion: int
    schema: str = STABILITY_SCHEMA
    authority: dict[str, bool] = field(default_factory=lambda: dict(AUTHORITY))

    def validate(self) -> None:
        if self.schema != STABILITY_SCHEMA or type(self.members) is not tuple \
                or len(self.members) != PRIMARY_MEMBER_COUNT \
                or type(self.selected_epochs) is not tuple \
                or len(self.selected_epochs) != PRIMARY_MEMBER_COUNT:
            raise WorldAfterstateV2DiagnosticsError("stability member population drift")
        _int(self.common_epoch, "common epoch", minimum=1)
        _int(self.common_epoch_dispersion, "common epoch dispersion")
        epoch_sets = []
        for index, member in enumerate(self.members):
            if type(member) is not tuple or not member:
                raise WorldAfterstateV2DiagnosticsError("stability epoch curve missing")
            for row in member:
                row.validate()
                if row.member_index != index:
                    raise WorldAfterstateV2DiagnosticsError("stability member binding drift")
            epochs = tuple(row.epoch for row in member)
            if epochs != tuple(sorted(epochs)) or len(set(epochs)) != len(epochs):
                raise WorldAfterstateV2DiagnosticsError("stability epoch order drift")
            epoch_sets.append(set(epochs))
            _int(self.selected_epochs[index], "selected member epoch", minimum=1)
        expected_epochs = set(range(1, max(epoch_sets[0]) + 1))
        if any(epochs != epoch_sets[0] for epochs in epoch_sets[1:]) \
                or epoch_sets[0] != expected_epochs:
            raise WorldAfterstateV2DiagnosticsError(
                "stability common epoch drift")
        expected_selected = tuple(min(
            member, key=lambda row: (row.select_loss_nano, row.epoch)).epoch
            for member in self.members)
        expected_common = min(
            sorted(expected_epochs),
            key=lambda epoch: (
                sum(member[epoch - 1].select_loss_nano
                    for member in self.members), epoch))
        if self.selected_epochs != expected_selected \
                or self.common_epoch != expected_common \
                or self.common_epoch_dispersion != max(self.selected_epochs) - min(self.selected_epochs):
            raise WorldAfterstateV2DiagnosticsError("stability common epoch drift")
        _authority(self.authority)

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {"schema": self.schema,
                "members": [[row.__dict__ for row in member] for member in self.members],
                "selected_epochs": list(self.selected_epochs),
                "common_epoch": self.common_epoch,
                "common_epoch_dispersion": self.common_epoch_dispersion,
                "authority": dict(AUTHORITY)}

    def sha256(self) -> str:
        return _sha(self.payload())


@dataclass(frozen=True)
class ModelSelectorPowerReceiptV2:
    precision_select_population_sha256: str
    deal_utilities_microlevels: tuple[int, ...]
    precision_select_deal_count: int
    frozen_audit_deal_count: int
    s_model_microlevels: float
    n_required: int
    stop_underpowered: bool
    z_alpha_ppm: int = Z_ALPHA_PPM
    z_power_ppm: int = Z_POWER_PPM
    delta_microlevels: int = DELTA_MICROLEVELS
    replica_count: int = REPLICA_COUNT
    estimand_identity: str = ESTIMAND_IDENTITY
    schema: str = POWER_SCHEMA
    authority: dict[str, bool] = field(default_factory=lambda: dict(AUTHORITY))

    def validate(self) -> None:
        if self.schema != POWER_SCHEMA or type(self.deal_utilities_microlevels) is not tuple \
                or self.z_alpha_ppm != Z_ALPHA_PPM or self.z_power_ppm != Z_POWER_PPM \
                or self.delta_microlevels != DELTA_MICROLEVELS \
                or self.replica_count != REPLICA_COUNT \
                or self.estimand_identity != ESTIMAND_IDENTITY \
                or type(self.stop_underpowered) is not bool:
            raise WorldAfterstateV2DiagnosticsError("power identity drift")
        _digest(self.precision_select_population_sha256,
                "precision-select population SHA-256")
        _int(self.precision_select_deal_count, "precision-select deal count", minimum=2)
        _int(self.frozen_audit_deal_count, "frozen audit deal count", minimum=2)
        if len(self.deal_utilities_microlevels) != self.precision_select_deal_count:
            raise WorldAfterstateV2DiagnosticsError("power deal population drift")
        if any(isinstance(value, bool) or not isinstance(value, int)
               for value in self.deal_utilities_microlevels):
            raise WorldAfterstateV2DiagnosticsError("power utility row drift")
        if any(value < -101_500_000 or value > 101_500_000
               for value in self.deal_utilities_microlevels):
            raise WorldAfterstateV2DiagnosticsError("power utility range drift")
        mean = Fraction(sum(self.deal_utilities_microlevels),
                        self.precision_select_deal_count)
        variance = sum((Fraction(value) - mean) ** 2
                       for value in self.deal_utilities_microlevels) \
            / (self.precision_select_deal_count - 1)
        expected_s = math.sqrt(float(variance))
        actual_s = _finite(self.s_model_microlevels, "model Bessel standard deviation")
        if not math.isclose(actual_s, expected_s, rel_tol=1e-12, abs_tol=1e-9):
            raise WorldAfterstateV2DiagnosticsError("power Bessel deviation drift")
        # Square the reviewed formula before converting to a count.  This
        # keeps the z constants, Bessel variance, and worthwhile delta in
        # exact rational arithmetic; sqrt is only a descriptive projection.
        z_sum = Z_ALPHA_PPM + Z_POWER_PPM
        required_fraction = Fraction(z_sum * z_sum, 1_000_000**2) \
            * variance / (DELTA_MICROLEVELS**2)
        expected_n = (required_fraction.numerator
                      + required_fraction.denominator - 1) \
            // required_fraction.denominator
        _int(self.n_required, "required audit deal count", minimum=1)
        if self.n_required != expected_n \
                or self.stop_underpowered != (expected_n > self.frozen_audit_deal_count):
            raise WorldAfterstateV2DiagnosticsError("power boundary drift")
        _authority(self.authority)

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {"schema": self.schema,
                "precision_select_population_sha256": self.precision_select_population_sha256,
                "deal_utilities_microlevels": list(self.deal_utilities_microlevels),
                "precision_select_deal_count": self.precision_select_deal_count,
                "frozen_audit_deal_count": self.frozen_audit_deal_count,
                "s_model_microlevels": self.s_model_microlevels,
                "n_required": self.n_required,
                "stop_underpowered": self.stop_underpowered,
                "z_alpha_ppm": self.z_alpha_ppm, "z_power_ppm": self.z_power_ppm,
                "delta_microlevels": self.delta_microlevels,
                "replica_count": self.replica_count,
                "estimand_identity": self.estimand_identity,
                "authority": dict(AUTHORITY)}

    def sha256(self) -> str:
        return _sha(self.payload())


def validate_optimizer_canary_v2(value: OptimizerCanaryReceiptV2) -> None:
    if type(value) is not OptimizerCanaryReceiptV2:
        raise WorldAfterstateV2DiagnosticsError("optimizer canary receipt type drift")
    value.validate()


def validate_nested_curve_v2(value: NestedCurveReceiptV2) -> None:
    if type(value) is not NestedCurveReceiptV2:
        raise WorldAfterstateV2DiagnosticsError("nested curve receipt type drift")
    value.validate()


def validate_primary_stability_v2(value: PrimaryStabilityReceiptV2) -> None:
    if type(value) is not PrimaryStabilityReceiptV2:
        raise WorldAfterstateV2DiagnosticsError("stability receipt type drift")
    value.validate()


def validate_model_selector_power_v2(value: ModelSelectorPowerReceiptV2) -> None:
    if type(value) is not ModelSelectorPowerReceiptV2:
        raise WorldAfterstateV2DiagnosticsError("power receipt type drift")
    value.validate()


__all__ = [
    "AUTHORITY", "CANARY_PROGRESS_PPM", "CANARY_ROOT_COUNT", "CANARY_STEPS",
    "CURVE_FRACTIONS_PPM", "DELTA_MICROLEVELS", "ESTIMAND_IDENTITY",
    "ModelSelectorPowerReceiptV2", "NestedCurvePointV2", "NestedCurveReceiptV2",
    "OptimizerCanaryReceiptV2", "PrimaryMemberEpochV2", "PrimaryStabilityReceiptV2",
    "WorldAfterstateV2DiagnosticsError", "Z_ALPHA_PPM", "Z_POWER_PPM",
    "validate_model_selector_power_v2", "validate_nested_curve_v2",
    "validate_optimizer_canary_v2", "validate_primary_stability_v2",
]
