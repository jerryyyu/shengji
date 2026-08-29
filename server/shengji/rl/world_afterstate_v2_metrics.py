"""Pure, integer-stable metrics for the Value-Afterstate V2 audit.

No function in this module opens an audit, performs inference, reads a file,
or grants authority.  Predictions use the PPB simplex emitted by
``world_afterstate_v2_inference`` and truths use the canonical 204-category
mapping from ``world_afterstate``.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .belief_contract import canonical_json_bytes
from .world_afterstate import OUTCOME_CLASSES, category_signed_level
from .world_afterstate_v2_inference import PROBABILITY_SCALE
from .world_afterstate_v2_protocol import PRIOR_POINTS_BUCKETS
from .world_afterstate_v2_training import WorldAfterstateV2TrainingExample


METRICS_SCHEMA = "world-afterstate-v2-pure-metrics-v1"
PRIOR_SCHEMA = "world-afterstate-v2-jeffreys-prior-v1"
BOOTSTRAP_SCHEMA = "world-afterstate-v2-deal-bootstrap-v1"
RECEIPT_SCHEMA = "world-afterstate-v2-metric-receipt-v1"
BOOTSTRAP_REPLICATES = 10_000
RPS_DENOMINATOR = OUTCOME_CLASSES - 1
MICROLEVELS = 1_000_000
AUTHORITY = {
    "audit_opening_authorized": False,
    "training_authorized": False,
    "prediction_authorized": False,
    "consumer_authorized": False,
    "strength_claim_authorized": False,
    "gameplay_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "retry_authorized": False,
}


class WorldAfterstateV2MetricsError(ValueError):
    """A V2 metric input, prior, bootstrap, or receipt drifted."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(
            char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV2MetricsError(f"{label} drift")
    return value


def _round_divide(numerator: int, denominator: int) -> int:
    if isinstance(numerator, bool) or not isinstance(numerator, int) \
            or isinstance(denominator, bool) or not isinstance(denominator, int) \
            or denominator <= 0:
        raise WorldAfterstateV2MetricsError("integer rounding request drift")
    sign = -1 if numerator < 0 else 1
    return sign * ((abs(numerator) + denominator // 2) // denominator)


def _validate_probability(probability_ppb: Sequence[int]) -> tuple[int, ...]:
    if type(probability_ppb) not in (tuple, list) \
            or len(probability_ppb) != OUTCOME_CLASSES \
            or any(isinstance(value, bool) or not isinstance(value, int)
                   or value < 0 for value in probability_ppb) \
            or sum(probability_ppb) != PROBABILITY_SCALE:
        raise WorldAfterstateV2MetricsError("prediction probability simplex drift")
    return tuple(probability_ppb)


def _category(category: object) -> int:
    if isinstance(category, bool) or not isinstance(category, int) \
            or not 0 <= category < OUTCOME_CLASSES:
        raise WorldAfterstateV2MetricsError("terminal category drift")
    return category


def _probabilities_from_counts(counts: Sequence[int]) -> tuple[int, ...]:
    if len(counts) != OUTCOME_CLASSES or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in counts):
        raise WorldAfterstateV2MetricsError("prior count drift")
    denominator = 2 * sum(counts) + OUTCOME_CLASSES
    numerators = tuple(2 * count + 1 for count in counts)
    scaled = tuple(value * PROBABILITY_SCALE for value in numerators)
    floors = [value // denominator for value in scaled]
    residual = PROBABILITY_SCALE - sum(floors)
    order = sorted(range(OUTCOME_CLASSES), key=lambda index: (
        -(scaled[index] % denominator), index))
    for index in order[:residual]:
        floors[index] += 1
    result = tuple(floors)
    if sum(result) != PROBABILITY_SCALE:
        raise WorldAfterstateV2MetricsError("prior quantization drift")
    return result


def _stratum_key(row: WorldAfterstateV2TrainingExample) -> str:
    return f"{row.phase}|{row.role}|{row.points_bucket}"


@dataclass(frozen=True)
class JeffreysPriorV2:
    """Smoothed natural-fit prior in the exact inference PPB representation."""

    global_probability_ppb: tuple[int, ...]
    strata_probability_ppb: tuple[tuple[str, tuple[int, ...]], ...]
    natural_fit_row_count: int
    schema: str = PRIOR_SCHEMA
    authority: Mapping[str, bool] = field(default_factory=lambda: dict(AUTHORITY))

    def validate(self) -> None:
        if self.schema != PRIOR_SCHEMA or self.authority != AUTHORITY \
                or isinstance(self.natural_fit_row_count, bool) \
                or not isinstance(self.natural_fit_row_count, int) \
                or self.natural_fit_row_count <= 0 \
                or type(self.strata_probability_ppb) is not tuple:
            raise WorldAfterstateV2MetricsError("prior receipt drift")
        _validate_probability(self.global_probability_ppb)
        keys = []
        for key, probability in self.strata_probability_ppb:
            if key in keys or type(key) is not str \
                    or key.count("|") != 2:
                raise WorldAfterstateV2MetricsError("prior stratum drift")
            phase, role, points_bucket = key.split("|")
            if phase not in ("early", "middle", "late") \
                    or role not in ("attacker", "defender") \
                    or points_bucket not in PRIOR_POINTS_BUCKETS:
                raise WorldAfterstateV2MetricsError("prior stratum drift")
            _validate_probability(probability)
            keys.append(key)

    def probability_ppb(self, phase: str, role: str, points_bucket: str) \
            -> tuple[int, ...]:
        self.validate()
        key = f"{phase}|{role}|{points_bucket}"
        for candidate, probability in self.strata_probability_ppb:
            if candidate == key:
                return probability
        return self.global_probability_ppb

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {"schema": self.schema,
                "global_probability_ppb": list(self.global_probability_ppb),
                "strata_probability_ppb": [
                    [key, list(probability)]
                    for key, probability in self.strata_probability_ppb],
                "natural_fit_row_count": self.natural_fit_row_count,
                "authority": dict(self.authority)}

    def sha256(self) -> str:
        return _sha(self.payload())


def build_natural_fit_prior(
        rows: Sequence[WorldAfterstateV2TrainingExample]) -> JeffreysPriorV2:
    """Build a Jeffreys prior from natural/fit rows, ignoring other sources."""
    if type(rows) not in (tuple, list) or not rows \
            or any(type(row) is not WorldAfterstateV2TrainingExample
                   for row in rows):
        raise WorldAfterstateV2MetricsError("prior population drift")
    natural = [row for row in rows if row.source == "natural" and row.split == "fit"]
    if not natural:
        raise WorldAfterstateV2MetricsError("natural fit prior is empty")
    global_counts = [0] * OUTCOME_CLASSES
    strata: dict[str, list[int]] = {}
    for row in natural:
        try:
            row.validate()
        except Exception as exc:
            raise WorldAfterstateV2MetricsError("natural fit row drift") from exc
        global_counts[row.signed_level_category] += 1
        strata.setdefault(_stratum_key(row), [0] * OUTCOME_CLASSES)[
            row.signed_level_category] += 1
    result = JeffreysPriorV2(
        global_probability_ppb=_probabilities_from_counts(global_counts),
        strata_probability_ppb=tuple(
            (key, _probabilities_from_counts(strata[key]))
            for key in sorted(strata)),
        natural_fit_row_count=len(natural))
    result.validate()
    return result


def ranked_probability_score_ppb(
        probability_ppb: Sequence[int], target_category: int) -> int:
    """Return RPS in PPB, rounded once after the exact integer calculation."""
    probabilities = _validate_probability(probability_ppb)
    target = _category(target_category)
    cumulative = 0
    numerator = 0
    for index in range(RPS_DENOMINATOR):
        cumulative += probabilities[index]
        target_cumulative = 0 if target > index else PROBABILITY_SCALE
        difference = cumulative - target_cumulative
        numerator += difference * difference
    return _round_divide(numerator, RPS_DENOMINATOR * PROBABILITY_SCALE)


def ranked_probability_score(probability_ppb: Sequence[int],
                             target_category: int) -> float:
    """Floating spelling of RPS for descriptive callers; PPB is canonical."""
    return ranked_probability_score_ppb(probability_ppb, target_category) \
        / PROBABILITY_SCALE


def expected_signed_microlevels(probability_ppb: Sequence[int]) -> int:
    probabilities = _validate_probability(probability_ppb)
    # Every signed-level category is half-integral.  Keep the expectation in
    # integer half-level PPB until the final microlevel projection so a
    # 204-category sum never passes through a large float accumulator.
    half_level_numerator = sum(
        value * int(round(category_signed_level(index) * 2))
        for index, value in enumerate(probabilities))
    return _round_divide(
        half_level_numerator * (MICROLEVELS // 2), PROBABILITY_SCALE)


def expected_signed_level_absolute_error_microlevels(
        probability_ppb: Sequence[int], target_category: int) -> int:
    expected = expected_signed_microlevels(probability_ppb)
    target = _category(target_category)
    target_micro = int(round(category_signed_level(target) * MICROLEVELS))
    return abs(expected - target_micro)


def expected_signed_level_absolute_error(
        probability_ppb: Sequence[int], target_category: int) -> float:
    return expected_signed_level_absolute_error_microlevels(
        probability_ppb, target_category) / MICROLEVELS


def paired_advantage_absolute_error_improvement_microlevels(
        candidate_probability_ppb: Sequence[int],
        incumbent_probability_ppb: Sequence[int],
        candidate_category: int, incumbent_category: int) -> int:
    candidate = expected_signed_microlevels(candidate_probability_ppb)
    incumbent = expected_signed_microlevels(incumbent_probability_ppb)
    target = (int(round(category_signed_level(_category(candidate_category))
                       * MICROLEVELS)
              - round(category_signed_level(_category(incumbent_category))
                      * MICROLEVELS)))
    return abs(target) - abs((candidate - incumbent) - target)


def paired_advantage_absolute_error_improvement(*args: Any) -> float:
    return paired_advantage_absolute_error_improvement_microlevels(*args) \
        / MICROLEVELS


def _deal_values(values: Mapping[str, int] | Sequence[tuple[str, int]]) \
        -> tuple[tuple[str, int], ...]:
    if isinstance(values, Mapping):
        items = tuple(values.items())
    elif type(values) in (tuple, list):
        items = tuple(values)
    else:
        raise WorldAfterstateV2MetricsError("deal metric population drift")
    if not items or any(type(item) is not tuple or len(item) != 2
                        for item in items):
        raise WorldAfterstateV2MetricsError("deal metric population drift")
    result = []
    for deal, value in items:
        _digest(deal, "deal cluster SHA-256")
        if isinstance(value, bool) or not isinstance(value, int):
            raise WorldAfterstateV2MetricsError("deal metric value drift")
        result.append((deal, value))
    if len({deal for deal, _ in result}) != len(result):
        raise WorldAfterstateV2MetricsError("duplicate deal cluster")
    return tuple(sorted(result))


@dataclass(frozen=True)
class BootstrapIntervalV2:
    population_sha256: str
    metric_name: str
    seed: int
    replicates: int
    mean: int
    lower_5th: int
    upper_95th: int
    schema: str = BOOTSTRAP_SCHEMA

    def validate(self) -> None:
        _digest(self.population_sha256, "bootstrap population SHA-256")
        if self.schema != BOOTSTRAP_SCHEMA or type(self.metric_name) is not str \
                or not self.metric_name or isinstance(self.seed, bool) \
                or not isinstance(self.seed, int) or not 0 <= self.seed < 2**64 \
                or self.replicates != BOOTSTRAP_REPLICATES \
                or any(isinstance(value, bool) or not isinstance(value, int)
                       for value in (self.mean, self.lower_5th, self.upper_95th)) \
                or self.lower_5th > self.upper_95th:
            raise WorldAfterstateV2MetricsError("bootstrap interval drift")

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {"schema": self.schema, "population_sha256": self.population_sha256,
                "metric_name": self.metric_name, "seed": self.seed,
                "replicates": self.replicates, "mean": self.mean,
                "lower_5th": self.lower_5th, "upper_95th": self.upper_95th}

    def sha256(self) -> str:
        return _sha(self.payload())

    @property
    def lower(self) -> int:
        return self.lower_5th

    @property
    def upper(self) -> int:
        return self.upper_95th


def deal_cluster_bootstrap_interval(
        deal_values: Mapping[str, int] | Sequence[tuple[str, int]], *,
        population_sha256: str, metric_name: str,
        replicates: int = BOOTSTRAP_REPLICATES) -> BootstrapIntervalV2:
    _digest(population_sha256, "bootstrap population SHA-256")
    if type(metric_name) is not str or not metric_name \
            or replicates != BOOTSTRAP_REPLICATES:
        raise WorldAfterstateV2MetricsError("bootstrap configuration drift")
    values = _deal_values(deal_values)
    seed = int.from_bytes(hashlib.sha256(
        f"{population_sha256}|{metric_name}".encode("ascii")).digest()[:8], "big")
    rng = random.Random(seed)
    samples = []
    ordered = tuple(value for _, value in values)
    for _ in range(BOOTSTRAP_REPLICATES):
        total = sum(ordered[rng.randrange(len(ordered))]
                    for _ in range(len(ordered)))
        samples.append(_round_divide(total, len(ordered)))
    samples.sort()
    # Integer nearest-rank percentile: rank ceil(p*N), one-indexed.
    lower = samples[(5 * BOOTSTRAP_REPLICATES + 99) // 100 - 1]
    upper = samples[(95 * BOOTSTRAP_REPLICATES + 99) // 100 - 1]
    result = BootstrapIntervalV2(
        population_sha256=population_sha256, metric_name=metric_name,
        seed=seed, replicates=BOOTSTRAP_REPLICATES,
        mean=_round_divide(sum(ordered), len(ordered)),
        lower_5th=lower, upper_95th=upper)
    result.validate()
    return result


@dataclass(frozen=True)
class MetricReceiptV2:
    metric_name: str
    population_sha256: str
    mean: int
    bootstrap: BootstrapIntervalV2
    schema: str = RECEIPT_SCHEMA
    authority: Mapping[str, bool] = field(default_factory=lambda: dict(AUTHORITY))

    def validate(self) -> None:
        if self.schema != RECEIPT_SCHEMA or self.authority != AUTHORITY \
                or type(self.metric_name) is not str or not self.metric_name \
                or self.bootstrap.population_sha256 != self.population_sha256 \
                or self.bootstrap.metric_name != self.metric_name \
                or self.mean != self.bootstrap.mean:
            raise WorldAfterstateV2MetricsError("metric receipt drift")
        _digest(self.population_sha256, "metric population SHA-256")
        if isinstance(self.mean, bool) or not isinstance(self.mean, int):
            raise WorldAfterstateV2MetricsError("metric mean drift")
        self.bootstrap.validate()

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {"schema": self.schema, "metric_name": self.metric_name,
                "population_sha256": self.population_sha256,
                "mean": self.mean, "bootstrap": self.bootstrap.payload(),
                "authority": dict(self.authority)}

    def sha256(self) -> str:
        return _sha(self.payload())


def paired_advantage_error_improvement_microlevels(
        model_advantage_microlevels: int,
        target_advantage_microlevels: int) -> int:
    """Baseline-zero minus model absolute error for one paired root."""
    if any(isinstance(value, bool) or not isinstance(value, int)
           for value in (model_advantage_microlevels,
                         target_advantage_microlevels)):
        raise WorldAfterstateV2MetricsError("paired advantage value drift")
    return abs(target_advantage_microlevels) - abs(
        model_advantage_microlevels - target_advantage_microlevels)


def validate_metric_receipt(value: MetricReceiptV2) -> None:
    if type(value) is not MetricReceiptV2:
        raise WorldAfterstateV2MetricsError("metric receipt type drift")
    value.validate()


# Short spellings retained for metric consumers that do not need units in the
# function name; the PPB/microlevel variants remain the canonical kernels.
build_jeffreys_prior = build_natural_fit_prior
rps = ranked_probability_score_ppb
absolute_error = expected_signed_level_absolute_error_microlevels
paired_error_improvement = paired_advantage_absolute_error_improvement_microlevels
bootstrap_interval = deal_cluster_bootstrap_interval


__all__ = [
    "AUTHORITY", "BOOTSTRAP_REPLICATES", "BootstrapIntervalV2",
    "JeffreysPriorV2", "MetricReceiptV2", "WorldAfterstateV2MetricsError",
    "build_natural_fit_prior", "deal_cluster_bootstrap_interval",
    "build_jeffreys_prior", "bootstrap_interval",
    "expected_signed_level_absolute_error",
    "expected_signed_level_absolute_error_microlevels", "expected_signed_microlevels",
    "paired_advantage_absolute_error_improvement",
    "paired_advantage_absolute_error_improvement_microlevels",
    "paired_advantage_error_improvement_microlevels", "paired_error_improvement",
    "ranked_probability_score", "ranked_probability_score_ppb",
    "rps", "absolute_error", "validate_metric_receipt",
]
