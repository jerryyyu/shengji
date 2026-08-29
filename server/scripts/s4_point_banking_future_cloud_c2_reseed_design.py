#!/usr/bin/env python3
"""Fresh-seed replacement for the quarantined S4 C2 confirmation packet.

The 300B C2 packet was never formally admitted, but an independent reviewer
accidentally crossed its gameplay boundary in a disposable worktree.  No
completed outcome artifact was published or observed.  Rather than retrofit a
post-hoc restart argument into an immutable confirmation packet, this design
retires the entire 300B interval and moves the otherwise unchanged experiment
to a disjoint 360B interval.

This file is design authority only.  It launches nothing and authorizes no
packet, preflight, gameplay, strength claim, promotion, or deployment.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass

import s4_point_banking_future_cloud_c2_design as C2


SCHEMA = "s4-point-banking-future-cloud-c2-reseed-design-v1"
RUN_ID = "s4-point-banking-future-c2-360b-v1"
SCREEN_SEED0 = 360_000_000_000

LOOK_CLUSTERS = C2.LOOK_CLUSTERS
LOOK_ALPHAS = C2.LOOK_ALPHAS
SHARD_COUNT = C2.SHARD_COUNT
CLOUD_CORES = C2.CLOUD_CORES
STREAM_STRIDE = C2.STREAM_STRIDE
NULL_SENTINEL_MODULUS = C2.NULL_SENTINEL_MODULUS
MAX_PROJECTED_FLEET_HOURS = C2.MAX_PROJECTED_FLEET_HOURS
MAX_PROJECTED_SHARD_HOURS = C2.MAX_PROJECTED_SHARD_HOURS

RETIRED_RUN_ID = "s4-point-banking-future-c2-300b-recovery-v2"
RETIRED_GIT = "2649b514380e7a2e2ef40c96e8cf5b15f0da6e31"
RETIRED_PACKET_SHA256 = (
    "65c3cf8a3488cacc230a6f9cca2c1a2fd30bf8006f97833b67eda7d1e75916e8"
)
RETIRED_SEED0 = C2.SCREEN_SEED0
RETIRED_CLUSTERS = LOOK_CLUSTERS[-1]


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


def retired_population() -> C2.Population:
    return C2.Population(
        "s4-future-cloud-c2-300b-retired-after-reviewer-gameplay",
        RETIRED_SEED0,
        RETIRED_CLUSTERS,
        STREAM_STRIDE,
    )


def primary_population(design: Design = Design()) -> C2.Population:
    return C2.Population(
        "s4-future-cloud-c2-360b-primary",
        design.seed0,
        design.look_clusters[-1],
        design.stream_stride,
    )


def reserved_populations() -> tuple[C2.Population, ...]:
    return (*C2.c1_reserved_populations(), retired_population())


def adjusted_projection(
    design: Design = Design(), value: dict | None = None,
) -> dict[str, float]:
    value = C2.capacity_result() if value is None else value
    projection = value["projection"]
    fleet_hours = float(projection["fleet_hours"])
    look_1_fleet_hours = float(projection["look_1_fleet_hours"])
    return {
        "fleet_hours": fleet_hours,
        "max_shard_hours": fleet_hours / design.shard_count,
        "look_1_fleet_hours": look_1_fleet_hours,
        "look_1_max_shard_hours": look_1_fleet_hours / design.shard_count,
    }


def incident_record() -> dict[str, object]:
    """Declare the bounded reason the complete 300B interval is retired."""
    return {
        "schema": "s4-point-banking-future-c2-reviewer-gameplay-incident-v1",
        "retired_run_id": RETIRED_RUN_ID,
        "retired_git": RETIRED_GIT,
        "retired_packet_sha256": RETIRED_PACKET_SHA256,
        "retired_seed0": RETIRED_SEED0,
        "retired_clusters": RETIRED_CLUSTERS,
        "reviewer_workers_started": 16,
        "completed_shard_results": 0,
        "aggregates_published": 0,
        "finals_published": 0,
        "formal_admission_consumed": False,
        "outcomes_observed": False,
        "entire_population_retired": True,
        "old_packet_launch_authorized": False,
    }


def design_problems(design: Design = Design()) -> list[str]:
    problems = C2.capacity_problems()
    if (design.look_clusters != LOOK_CLUSTERS
            or design.look_alphas != LOOK_ALPHAS):
        problems.append("evidence target or alpha spending changed")
    if sum(design.look_alphas) > C2.C1.FAMILY_ALPHA + 1e-15:
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
    if any(C2.overlap(candidate, old) for old in reserved_populations()):
        problems.append("fresh population overlaps prior reservation")
    projection = adjusted_projection(design)
    if projection["fleet_hours"] > design.max_projected_fleet_hours:
        problems.append("measured fleet projection exceeds C2 cap")
    if projection["max_shard_hours"] > design.max_projected_shard_hours:
        problems.append("measured shard projection exceeds C2 cap")
    final = C2.C1.Look(design.look_clusters[-1], design.look_alphas[-1])
    if C2.C1.marginal_power(final, C2.C1.SMALL_EFFECT) < C2.C1.MIN_POWER_SMALL:
        problems.append("maximum is underpowered for +0.03 effect")
    incident = incident_record()
    if (incident["entire_population_retired"] is not True
            or incident["old_packet_launch_authorized"] is not False
            or incident["outcomes_observed"] is not False):
        problems.append("reviewer incident retirement drift")
    return sorted(set(problems))


def design_record(design: Design = Design()) -> dict[str, object]:
    problems = design_problems(design)
    if problems:
        raise ValueError(
            "invalid S4 Cloud C2 reseed design: " + "; ".join(problems))
    looks = []
    for clusters, alpha in zip(
            design.look_clusters, design.look_alphas, strict=True):
        look = C2.C1.Look(clusters, alpha)
        looks.append({
            "clusters": clusters,
            "alpha": alpha,
            "critical_decimal": C2._stable_decimal(look.critical),
            "projected_half_width_decimal":
                C2._stable_decimal(C2.C1.half_width(look)),
            "power_at_replicated_effect_decimal":
                C2._stable_decimal(C2.C1.marginal_power(
                    look, C2.C1.REPLICATED_EFFECT)),
            "power_at_plus_0_03_decimal":
                C2._stable_decimal(C2.C1.marginal_power(
                    look, C2.C1.SMALL_EFFECT)),
            "null_sentinel_clusters": clusters // design.sentinel_modulus,
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
        "primary_efficacy": C2.C1.PRIMARY_EFFICACY,
        "integrity_gates": list(C2.C1.INTEGRITY_GATES),
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
            "executed_git": C2.CAPACITY_EXECUTED_GIT,
            "result_sha256": C2.CAPACITY_RESULT_SHA256,
            "admission_sha256": C2.CAPACITY_ADMISSION_SHA256,
            "old_profile_status": "HOLD",
            "old_shards": C2.C1.SHARD_COUNT,
            "new_shards": design.shard_count,
            "measured_projection": adjusted_projection(design),
            "fleet_hour_cap": design.max_projected_fleet_hours,
            "max_shard_hour_cap": design.max_projected_shard_hours,
            "new_preflight_requested": False,
        },
        "reviewer_incident": incident_record(),
        "primary_population": asdict(population) | {
            "low": population.low, "high": population.high},
        "excluded_populations": [asdict(value) | {
            "low": value.low, "high": value.high}
            for value in reserved_populations()],
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
