#!/usr/bin/env python3
"""Machine-checkable design for the future-only S4 successor.

The two completed 2,048-cluster S4 populations are planning inputs only.  No
historical outcome may enter the new estimator.  The successor gets at most two
cumulative looks over one fresh population, with Bonferroni alpha spending
fixed before gameplay and a maximum sample sized to resolve effects smaller
than either historical point estimate.

This module launches nothing.  A later controller must import and bind this
exact design, pass a score-free capacity gate, and receive separate execution
authority.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from statistics import NormalDist


SCHEMA = "s4-point-banking-future-design-v1"
RUN_ID = "s4-point-banking-future-c1-240b-v1"
SHARD_COUNT = 8
STREAM_STRIDE = 3_000_017
ROLE_OFFSETS = (0, 500_000, 1_000_000, 1_500_000)
PREFLIGHT_SEED0 = 239_000_000_000
PREFLIGHT_CLUSTERS = 4
SCREEN_SEED0 = 240_000_000_000
NULL_SENTINEL_MODULUS = 8
FAMILY_ALPHA = 0.05

# The replication is the more conservative of the two terminal variance
# estimates.  Its outcomes choose neither seeds nor a decision threshold.
PLANNING_CLUSTERS = 2_048
PLANNING_HALF_WIDTH95 = 0.055711812163936635
PLANNING_Z = 1.96
PLANNING_CLUSTER_SD = (
    PLANNING_HALF_WIDTH95 / PLANNING_Z * math.sqrt(PLANNING_CLUSTERS))
REPLICATED_EFFECT = 0.048828125
SMALL_EFFECT = 0.03
MIN_POWER_REPLICATED = 0.99
MIN_POWER_SMALL = 0.80
PRIMARY_EFFICACY = (
    "clustered paired treatment-minus-live-champion lower bound > 0")
INTEGRITY_GATES = (
    "matched-null sentinel outcome identity",
    "treatment and null trigger both attacker and defender roles",
    "treatment changes exactly its triggers and null changes none",
    "exact registered search/sampler work with zero bad counters",
    "frozen mechanism, champion, runtime, seed and population identity",
)


@dataclass(frozen=True)
class Look:
    clusters: int
    alpha: float

    @property
    def critical(self) -> float:
        return NormalDist().inv_cdf(1.0 - self.alpha)


@dataclass(frozen=True)
class Population:
    name: str
    seed0: int
    clusters: int
    stride: int
    max_role_offset: int = max(ROLE_OFFSETS)

    @property
    def low(self) -> int:
        return self.seed0

    @property
    def high(self) -> int:
        return (self.seed0 + self.stride * (self.clusters - 1)
                + self.max_role_offset)


@dataclass(frozen=True)
class Design:
    looks: tuple[Look, ...] = (
        Look(clusters=8_192, alpha=0.025),
        Look(clusters=16_384, alpha=0.025),
    )
    seed0: int = SCREEN_SEED0
    stream_stride: int = STREAM_STRIDE
    shard_count: int = SHARD_COUNT
    sentinel_modulus: int = NULL_SENTINEL_MODULUS
    historical_outcomes_enter_estimator: bool = False
    automatic_continue_after_clean_efficacy_nonpass: bool = True
    futility_stop: bool = False


# Include unspent-but-predeclared old confirmation seeds conservatively.  The
# new population is far outside all intervals, so this costs nothing and makes
# accidental revival impossible.
EXCLUDED_POPULATIONS = (
    Population("s4-v2-preflight", 96_000_000_000, 4, STREAM_STRIDE),
    Population("s4-v2-screen", 100_000_000_000, 2_048, STREAM_STRIDE),
    Population("s4-v2-old-confirm-reserved", 120_000_000_000, 8_192,
               STREAM_STRIDE),
    Population("s4-replication-preflight", 179_000_000_000, 4,
               STREAM_STRIDE),
    Population("s4-replication", 180_000_000_000, 2_048, STREAM_STRIDE),
    # T4 uses consecutive deal seeds around 193M.  A deliberately broad 10M
    # interval covers all policy-role offsets without importing that lane.
    Population("t4-midlate-preflight-and-screen", 192_000_000, 10_000_000, 1,
               2_000_000),
)


def standard_error(clusters: int) -> float:
    return PLANNING_CLUSTER_SD / math.sqrt(clusters)


def half_width(look: Look) -> float:
    return look.critical * standard_error(look.clusters)


def marginal_power(look: Look, effect: float) -> float:
    """Power of this look alone; sequential pass probability is no smaller."""
    return NormalDist().cdf(
        effect / standard_error(look.clusters) - look.critical)


def future_populations(design: Design) -> tuple[Population, Population]:
    return (
        Population("s4-future-preflight", PREFLIGHT_SEED0,
                   PREFLIGHT_CLUSTERS, design.stream_stride),
        Population("s4-future-primary", design.seed0,
                   design.looks[-1].clusters, design.stream_stride),
    )


def overlap(a: Population, b: Population) -> bool:
    """Conservative interval overlap; false proves no RNG integer can repeat."""
    return not (a.high < b.low or b.high < a.low)


def design_problems(design: Design) -> list[str]:
    problems = []
    if not design.looks:
        return ["design has no looks"]
    clusters = [look.clusters for look in design.looks]
    if (clusters != sorted(set(clusters))
            or any(isinstance(n, bool) or not isinstance(n, int) or n <= 0
                   for n in clusters)):
        problems.append("look clusters are not strictly increasing positive ints")
    if any(not 0 < look.alpha < FAMILY_ALPHA for look in design.looks):
        problems.append("look alpha is outside its admissible range")
    if sum(look.alpha for look in design.looks) > FAMILY_ALPHA + 1e-15:
        problems.append("alpha spending exceeds family budget")
    if (design.shard_count != SHARD_COUNT
            or any(n % design.shard_count for n in clusters)):
        problems.append("look/shard geometry drift")
    if (isinstance(design.sentinel_modulus, bool)
            or not isinstance(design.sentinel_modulus, int)
            or design.sentinel_modulus <= 0
            or any(n % design.sentinel_modulus for n in clusters)):
        problems.append("null-sentinel geometry drift")
    if design.historical_outcomes_enter_estimator:
        problems.append("historical S4 outcomes enter the future estimator")
    if (not design.automatic_continue_after_clean_efficacy_nonpass
            or design.futility_stop):
        problems.append("post-look continuation is discretionary")

    future = future_populations(design)
    for index, left in enumerate(future):
        for right in (*EXCLUDED_POPULATIONS, *future[index + 1:]):
            if overlap(left, right):
                problems.append(f"seed interval overlap: {left.name}/{right.name}")

    final = design.looks[-1]
    if marginal_power(final, REPLICATED_EFFECT) < MIN_POWER_REPLICATED:
        problems.append("maximum is underpowered for replicated effect")
    if marginal_power(final, SMALL_EFFECT) < MIN_POWER_SMALL:
        problems.append("maximum is underpowered for +0.03 effect")
    if half_width(final) > 0.02:
        problems.append("maximum projected half-width exceeds 0.02")
    if marginal_power(design.looks[0], REPLICATED_EFFECT) < 0.90:
        problems.append("first look is too small for likely early resolution")
    return sorted(set(problems))


def design_record(design: Design = Design()) -> dict[str, object]:
    problems = design_problems(design)
    if problems:
        raise ValueError("invalid S4 future design: " + "; ".join(problems))
    looks = [{
        **asdict(look),
        "critical": look.critical,
        "projected_half_width": half_width(look),
        "power_at_replicated_effect": marginal_power(
            look, REPLICATED_EFFECT),
        "power_at_plus_0_03": marginal_power(look, SMALL_EFFECT),
        "null_sentinel_clusters": look.clusters // design.sentinel_modulus,
    } for look in design.looks]
    return {
        "schema": SCHEMA,
        "run_id": RUN_ID,
        "design": asdict(design),
        "looks": looks,
        "family_alpha": FAMILY_ALPHA,
        "primary_efficacy": PRIMARY_EFFICACY,
        "integrity_gates": list(INTEGRITY_GATES),
        "look_1_transition": {
            "efficacy_pass_and_integrity_pass": "STOP_PASS",
            "efficacy_nonpass_and_integrity_pass": "CONTINUE_AUTOMATICALLY",
            "any_integrity_nonpass": "STOP_HOLD",
        },
        "final_transition": {
            "efficacy_pass_and_integrity_pass": "PASS",
            "efficacy_nonpass_and_integrity_pass": "SELECT_NONE",
            "any_integrity_nonpass": "HOLD",
        },
        "planning": {
            "source": "terminal independent S4 replication; planning only",
            "clusters": PLANNING_CLUSTERS,
            "half_width95": PLANNING_HALF_WIDTH95,
            "cluster_sd": PLANNING_CLUSTER_SD,
            "replicated_effect": REPLICATED_EFFECT,
        },
        "future_populations": [asdict(value) | {
            "low": value.low, "high": value.high,
        } for value in future_populations(design)],
        "excluded_populations": [asdict(value) | {
            "low": value.low, "high": value.high,
        } for value in EXCLUDED_POPULATIONS],
        "historical_outcomes_used_for_claim": False,
        "automatic_promotion": False,
        "production_deployment": False,
    }


if __name__ == "__main__":
    print(json.dumps(design_record(), sort_keys=True, indent=2))
