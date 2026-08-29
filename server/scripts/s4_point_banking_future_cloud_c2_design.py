#!/usr/bin/env python3
"""Machine-checkable 16-shard successor to the S4 Cloud capacity HOLD.

The first Cloud preflight measured the unchanged S4 mechanism and correctly
HOLDed the eight-shard execution envelope.  This design keeps the evidence
target, alpha spending and automatic stopping rule intact.  It changes only
fresh seeds, physical sharding and the explicitly accepted capacity envelope
so all 16 Cloud cores can work.

This module launches nothing and grants no execution authority.  A later
controller must bind this exact design and receive separate review.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import s4_point_banking_future_design as C1


SCHEMA = "s4-point-banking-future-cloud-c2-design-v1"
RUN_ID = "s4-point-banking-future-c2-300b-v1"
SHARD_COUNT = 16
CLOUD_CORES = 16
SCREEN_SEED0 = 300_000_000_000
STREAM_STRIDE = C1.STREAM_STRIDE
LOOK_CLUSTERS = (8_192, 16_384)
LOOK_ALPHAS = (0.025, 0.025)
NULL_SENTINEL_MODULUS = C1.NULL_SENTINEL_MODULUS
MAX_PROJECTED_FLEET_HOURS = 1_024.0
MAX_PROJECTED_SHARD_HOURS = 64.0

CAPACITY_EXECUTED_GIT = "6ba6b81353f2239e56d56df34b209c306364a6d9"
CAPACITY_RESULT_SHA256 = (
    "70a15405c7edb94ecfdd89fb8c86d158ba64d8161eeba82c57851b67d513413e"
)
CAPACITY_ADMISSION_SHA256 = (
    "8332404e8ff4f97c4cdbaea232f9cdf695a83a2ceb121151923f2c99610fb9ca"
)
CAPACITY_RESULT = (
    Path(__file__).parents[1]
    / "tests/data/s4_point_banking_future_cloud_preflight.v1.json")


@dataclass(frozen=True)
class Population:
    name: str
    seed0: int
    clusters: int
    stride: int = STREAM_STRIDE
    max_role_offset: int = max(C1.ROLE_OFFSETS)

    @property
    def low(self) -> int:
        return self.seed0

    @property
    def high(self) -> int:
        return (self.seed0 + self.stride * (self.clusters - 1)
                + self.max_role_offset)


@dataclass(frozen=True)
class Design:
    look_clusters: tuple[int, int] = LOOK_CLUSTERS
    look_alphas: tuple[float, float] = LOOK_ALPHAS
    seed0: int = SCREEN_SEED0
    stream_stride: int = STREAM_STRIDE
    shard_count: int = SHARD_COUNT
    cloud_cores: int = CLOUD_CORES
    sentinel_modulus: int = NULL_SENTINEL_MODULUS
    max_projected_fleet_hours: float = MAX_PROJECTED_FLEET_HOURS
    max_projected_shard_hours: float = MAX_PROJECTED_SHARD_HOURS
    historical_outcomes_enter_estimator: bool = False
    automatic_continue_after_clean_efficacy_nonpass: bool = True
    futility_stop: bool = False


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capacity_result() -> dict:
    if (CAPACITY_RESULT.is_symlink() or not CAPACITY_RESULT.is_file()
            or sha256(CAPACITY_RESULT) != CAPACITY_RESULT_SHA256):
        raise ValueError("S4 Cloud capacity result identity drift")
    try:
        value = json.loads(CAPACITY_RESULT.read_bytes())
    except (OSError, ValueError) as exc:
        raise ValueError("S4 Cloud capacity result is unreadable") from exc
    if not isinstance(value, dict):
        raise ValueError("S4 Cloud capacity result is not an object")
    return value


def capacity_problems(value: dict | None = None) -> list[str]:
    try:
        value = capacity_result() if value is None else value
    except ValueError as exc:
        return [str(exc)]
    problems = []
    criteria = value.get("criteria")
    projection = value.get("projection")
    if (value.get("schema") != "s4-point-banking-future-preflight-v1"
            or value.get("run_id") !=
            "s4-point-banking-future-cloud-preflight-239b-v1"
            or value.get("complete") is not True
            or value.get("score_free") is not True
            or value.get("outcomes_published") is not False
            or value.get("outcomes_discarded") is not True
            or value.get("status") != "HOLD"):
        problems.append("capacity result identity/status")
    if (value.get("preflight_admission", {}).get("sha256") !=
            CAPACITY_ADMISSION_SHA256):
        problems.append("capacity admission identity")
    for field in (
            "sequential_launch_authorized", "tranche_2_pre_authorized",
            "strength_claim", "training_authorized",
            "production_promotion", "retry_or_extension_authorized"):
        if value.get(field) is not False:
            problems.append(f"capacity authority: {field}")
    expected_criteria = {
        "records_valid": True,
        "stream_populations_disjoint": True,
        "treatment_triggered_both_roles": True,
        "matched_null_triggered_both_roles": True,
        "treatment_dose_exact": True,
        "matched_null_dose_exact": True,
        "champion_feature_off": True,
        "fleet_hours_le_cap": False,
        "max_shard_hours_le_cap": False,
        "all": False,
    }
    if criteria != expected_criteria:
        problems.append("capacity criteria population")
    expected_projection_fields = {
        "fleet_hours", "max_shard_hours", "target_arm_clusters",
        "preflight_arm_clusters", "look_1_fleet_hours",
        "look_1_max_shard_hours",
    }
    if (not isinstance(projection, dict)
            or set(projection) != expected_projection_fields
            or any(not isinstance(item, (int, float))
                   or isinstance(item, bool) or not math.isfinite(item)
                   or item <= 0 for item in projection.values())):
        problems.append("capacity projection population")
    return sorted(set(problems))


def primary_population(design: Design = Design()) -> Population:
    return Population(
        "s4-future-cloud-c2-primary", design.seed0,
        design.look_clusters[-1], design.stream_stride)


def c1_reserved_populations() -> tuple[Population, ...]:
    return tuple(Population(
        value.name, value.seed0, value.clusters, value.stride,
        value.max_role_offset)
        for value in (*C1.EXCLUDED_POPULATIONS,
                      *C1.future_populations(C1.Design())))


def overlap(left: Population, right: Population) -> bool:
    return not (left.high < right.low or right.high < left.low)


def adjusted_projection(design: Design = Design(),
                        value: dict | None = None) -> dict[str, float]:
    value = capacity_result() if value is None else value
    projection = value["projection"]
    fleet_hours = float(projection["fleet_hours"])
    look_1_fleet_hours = float(projection["look_1_fleet_hours"])
    return {
        "fleet_hours": fleet_hours,
        "max_shard_hours": fleet_hours / design.shard_count,
        "look_1_fleet_hours": look_1_fleet_hours,
        "look_1_max_shard_hours": (
            look_1_fleet_hours / design.shard_count),
    }


def design_problems(design: Design = Design()) -> list[str]:
    problems = capacity_problems()
    if (design.look_clusters != LOOK_CLUSTERS
            or design.look_alphas != LOOK_ALPHAS):
        problems.append("evidence target or alpha spending changed")
    if sum(design.look_alphas) > C1.FAMILY_ALPHA + 1e-15:
        problems.append("alpha spending exceeds family budget")
    if (design.shard_count != SHARD_COUNT
            or design.cloud_cores != CLOUD_CORES
            or design.shard_count != design.cloud_cores
            or any(count % design.shard_count
                   for count in design.look_clusters)):
        problems.append("16-core shard geometry drift")
    if (design.max_projected_fleet_hours != MAX_PROJECTED_FLEET_HOURS
            or design.max_projected_shard_hours !=
            MAX_PROJECTED_SHARD_HOURS):
        problems.append("capacity envelope drift")
    if design.historical_outcomes_enter_estimator:
        problems.append("historical outcomes enter estimator")
    if (not design.automatic_continue_after_clean_efficacy_nonpass
            or design.futility_stop):
        problems.append("post-look continuation is discretionary")
    if (isinstance(design.seed0, bool) or not isinstance(design.seed0, int)
            or design.seed0 != SCREEN_SEED0):
        problems.append("fresh population seed drift")
    candidate = primary_population(design)
    if any(overlap(candidate, old) for old in c1_reserved_populations()):
        problems.append("fresh population overlaps prior reservation")
    projection = adjusted_projection(design)
    if projection["fleet_hours"] > design.max_projected_fleet_hours:
        problems.append("measured fleet projection exceeds C2 cap")
    if projection["max_shard_hours"] > design.max_projected_shard_hours:
        problems.append("measured shard projection exceeds C2 cap")
    final = C1.Look(design.look_clusters[-1], design.look_alphas[-1])
    if C1.marginal_power(final, C1.SMALL_EFFECT) < C1.MIN_POWER_SMALL:
        problems.append("maximum is underpowered for +0.03 effect")
    return sorted(set(problems))


def _stable_decimal(value: float) -> str:
    """Keep review display stable across ARM and x86 libm implementations."""
    return format(value, ".12g")


def design_record(design: Design = Design()) -> dict[str, object]:
    problems = design_problems(design)
    if problems:
        raise ValueError("invalid S4 Cloud C2 design: " + "; ".join(problems))
    looks = []
    for clusters, alpha in zip(
            design.look_clusters, design.look_alphas, strict=True):
        look = C1.Look(clusters, alpha)
        looks.append({
            "clusters": clusters,
            "alpha": alpha,
            "critical_decimal": _stable_decimal(look.critical),
            "projected_half_width_decimal":
                _stable_decimal(C1.half_width(look)),
            "power_at_replicated_effect_decimal":
                _stable_decimal(C1.marginal_power(
                    look, C1.REPLICATED_EFFECT)),
            "power_at_plus_0_03_decimal":
                _stable_decimal(C1.marginal_power(look, C1.SMALL_EFFECT)),
            "null_sentinel_clusters":
                clusters // design.sentinel_modulus,
        })
    population = primary_population(design)
    design_payload = asdict(design)
    design_payload["look_clusters"] = list(design.look_clusters)
    design_payload["look_alphas"] = list(design.look_alphas)
    return {
        "schema": SCHEMA,
        "run_id": RUN_ID,
        "design": design_payload,
        "looks": looks,
        "primary_efficacy": C1.PRIMARY_EFFICACY,
        "integrity_gates": list(C1.INTEGRITY_GATES),
        "look_1_transition": {
            "efficacy_pass_and_integrity_pass": "STOP_PASS",
            "efficacy_nonpass_and_integrity_pass":
                "CONTINUE_AUTOMATICALLY",
            "any_integrity_nonpass": "STOP_HOLD",
        },
        "final_transition": {
            "efficacy_pass_and_integrity_pass": "PASS",
            "efficacy_nonpass_and_integrity_pass": "SELECT_NONE",
            "any_integrity_nonpass": "HOLD",
        },
        "capacity_evidence": {
            "executed_git": CAPACITY_EXECUTED_GIT,
            "result_sha256": CAPACITY_RESULT_SHA256,
            "admission_sha256": CAPACITY_ADMISSION_SHA256,
            "old_profile_status": "HOLD",
            "old_shards": C1.SHARD_COUNT,
            "new_shards": design.shard_count,
            "measured_projection": adjusted_projection(design),
            "fleet_hour_cap": design.max_projected_fleet_hours,
            "max_shard_hour_cap": design.max_projected_shard_hours,
            "new_preflight_requested": False,
        },
        "primary_population": asdict(population) | {
            "low": population.low, "high": population.high},
        "excluded_populations": [asdict(value) | {
            "low": value.low, "high": value.high}
            for value in c1_reserved_populations()],
        "historical_outcomes_used_for_claim": False,
        "score_free_capacity_only": True,
        "packet_implementation_authorized": False,
        "sequential_execution_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }


if __name__ == "__main__":
    print(json.dumps(design_record(), sort_keys=True, indent=2))
