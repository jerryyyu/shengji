#!/usr/bin/env python3
"""Freeze the Pair V3 DEV/CALIB capacity *design*, never evaluation.

The reviewed affected-state evaluator is intentionally expensive: each state
runs two complete production report-LCB decisions plus a fresh common-world
comparison.  This module opens the reviewed population only to bind the fixed
state schedule, deterministic work ceiling, exploration estimands and later
runtime gate.  It has no subprocess launcher and grants no gameplay authority.

REPORT rows are present in the source asset but are never admitted here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from statistics import NormalDist

import pair_ballot_affected_aggregate as AGG
import pair_ballot_affected_eval as EVAL
import pair_ballot_affected_states as STATES


SCHEMA = "pair-ballot-affected-capacity-design-v1"
SUMMARY_SCHEMA = "pair-ballot-affected-capacity-defender-summary-v1"
PARENT_REVIEW_GIT = "22ddfa3728f1d66cac22e98d64725184dd71efd6"
PARENT_REVIEW_RECORD_SHA256 = (
    "82c36d3604de0c3b8c59bef82e1bf7e16edbcefafddb13a87dad0b005bc79341"
)
POPULATION_FILE_SHA256 = (
    "6a3f8d9d5317db642b6fae75a042c26a3b1085f6275e48d233b7b851ac2339ae"
)
POPULATION_ARTIFACT_SHA256 = (
    "6e62bf4bd43558da6233118fea13d49cd6f90ed4d2632b628b56ccd0f470d4d7"
)
REVIEWED_IDENTITY_MEMBERSHIP_SHA256 = (
    "57c835c8785db8c84fff78d19e84dcc7ea1b2ee74ea120065fdf7c75bc276e24"
)
REVIEWED_DEFENDER_MEMBERSHIP_SHA256 = (
    "8225e5f88b5b3a7d368d9715f9c3e9c5fc1a14df61486204168583e5511de9a4"
)
REVIEWED_SELECTION_SHA256 = (
    "3c9993bc8432d2fc419cfb75c2f766119de3aa4eacdf87dc3c238e1a484b29ab"
)
CAPTURE_SHA256 = (
    "e54102482c2f1652186bfa5458f4f229fa01bd8bf74cdcb2d29c7fe133e6f4ce"
)
EVALUATOR_SHA256 = (
    "2d4adfd06d0de7517bb190ebf5d190bd95f848d9ab25fb5eb9a29f27b3cd7488"
)
AGGREGATE_SHA256 = (
    "a1908a32853ea62e0c775dd1975b7b7ad7316f662dc19b8fe108b25282099ba0"
)

SPLITS = ("dev", "calib")
BANDS = ("early", "mid", "late")
ROWS_PER_SPLIT = 512
BAND_ROWS_PER_SPLIT = {"early": 448, "mid": 48, "late": 16}
DEFENDER_ROWS = 1_023
ATTACKER_ROWS = 1
DEFENDER_DEAL_CLUSTERS = 990
DEFENDER_ROWS_BY_SPLIT = {"dev": 512, "calib": 511}
DEFENDER_ROWS_BY_BAND = {"early": 895, "mid": 96, "late": 32}
SOURCE_TRAJECTORY_POLICY = "smart"
REVIEWED_BAND_WEIGHTS = {
    "early": 0.9686815593517302,
    "mid": 0.03081197985107315,
    "late": 0.000506460797196671,
}
CAPACITY_ROUTES = {
    "POLICY_AND_SOURCE_PROMISING_TEST_NATURAL_DOSE":
        "POLICY_AND_SOURCE_PROMISING_MEASURE_LIVE_CHAMPION_DOSE",
    "SOURCE_PROMISING_SELECTOR_NOT_EXPLOITING":
        "SOURCE_PROMISING_SELECTOR_NOT_EXPLOITING",
    "POLICY_POSITIVE_WITHOUT_INSERTED_PAIR_HEADROOM_AUDIT_EVICTIONS":
        "POLICY_POSITIVE_WITHOUT_INSERTED_PAIR_HEADROOM_AUDIT_EVICTIONS",
    "FIXED_WIDTH_RETENTION_NOT_PROMISING_TRY_CONTEXTUAL_PAIR_SOURCE":
        "FIXED_WIDTH_RETENTION_NOT_PROMISING_TRY_CONTEXTUAL_PAIR_SOURCE",
}
SHARD_COUNT = 16
BALLOT_WIDTH = 14
SELECTION_WORLDS = 30
POLICY_REPORT_WORLDS = 300
EXTERNAL_REPORT_WORLDS = 300
POLICY_WORK_PER_STATE = BALLOT_WIDTH * SELECTION_WORLDS + (
    2 * POLICY_REPORT_WORLDS
)
MAX_EXTERNAL_ACTIONS = 3
MAX_EXTERNAL_WORK_PER_STATE = MAX_EXTERNAL_ACTIONS * EXTERNAL_REPORT_WORLDS
MAX_WORK_PER_STATE = 2 * POLICY_WORK_PER_STATE + MAX_EXTERNAL_WORK_PER_STATE

# This is a fail-closed operational envelope, not a throughput claim.  A later
# reviewed host qualification/preflight must project within both bounds before
# any scored state is admitted.
MAX_FLEET_HOURS = 64.0
MAX_LANE_WALL_HOURS = 4.0
MAX_CONCURRENT_LANES = 16

# State-level effects are means over 300 common worlds.  0.50 is deliberately
# more conservative than the ~0.15 per-state dispersion seen in the recent
# Teacher action exams.  The design reports sensitivity rather than pretending
# this reusable exploration population is a terminal strength gate.
PLANNING_CLUSTER_SD = 0.50
ONE_SIDED_ALPHA = 0.05
TARGET_POWER = 0.80
Z_ALPHA = 1.645
Z_POWER = 0.842
WORTHWHILE_CONDITIONAL_EFFECT = 0.05


class CapacityDesignRefused(RuntimeError):
    """The reviewed population or fixed capacity design drifted."""


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"))
            + "\n").encode()


def _manifest_row(row: dict) -> dict:
    return {
        "state_id": row["state_id"],
        "state_sha256": row["state_sha256"],
        "deal_seed": row["deal_seed"],
        "split": row["split"],
        "band": row["band"],
        "role": row["role"],
        "ballot_width": len(row["current_ballot"]),
    }


def _identity_row(row: dict) -> dict:
    return {
        "state_id": row["state_id"],
        "state_sha256": row["state_sha256"],
        "deal_seed": row["deal_seed"],
        "split": row["split"],
        "band": row["band"],
        "role": row["role"],
    }


def _membership_sha256(rows: list[dict]) -> str:
    """Hash identity + role membership independent of shard/result order."""
    manifest = sorted((_identity_row(row) for row in rows), key=_canonical)
    return _sha256(_canonical(manifest))


def _defender_rows(rows: list[dict]) -> list[dict]:
    """Return the exact combined DEV/CALIB defender population or refuse.

    The frozen source has one attacker case study.  It is retained for a
    descriptive report but cannot enter the primary estimator or its power
    calculation.  Thirty-three defender deals contribute both an early and a
    mid row, so state rows are not independent clusters.
    """
    if (not isinstance(rows, list)
            or len(rows) != len(SPLITS) * ROWS_PER_SPLIT
            or any(row.get("split") not in SPLITS for row in rows)
            or len({row.get("state_id") for row in rows}) != len(rows)):
        raise CapacityDesignRefused("combined DEV/CALIB population drift")
    role_counts = Counter(row.get("role") for row in rows)
    split_counts = Counter(row.get("split") for row in rows)
    defenders = [row for row in rows if row.get("role") == "defender"]
    if (_membership_sha256(rows) != REVIEWED_IDENTITY_MEMBERSHIP_SHA256
            or _membership_sha256(defenders)
            != REVIEWED_DEFENDER_MEMBERSHIP_SHA256):
        raise CapacityDesignRefused("reviewed role membership drift")
    if (role_counts != Counter({
            "defender": DEFENDER_ROWS, "attacker": ATTACKER_ROWS})
            or split_counts != Counter({split: ROWS_PER_SPLIT
                                        for split in SPLITS})
            or Counter(row["split"] for row in defenders)
            != Counter(DEFENDER_ROWS_BY_SPLIT)
            or Counter(row.get("band") for row in defenders)
            != Counter(DEFENDER_ROWS_BY_BAND)
            or len({row.get("deal_seed") for row in defenders})
            != DEFENDER_DEAL_CLUSTERS):
        raise CapacityDesignRefused("defender role/cluster population drift")
    return defenders


def _planning_sensitivity(*, band_weights: dict[str, float],
                          defender_rows: list[dict]) -> dict:
    """Plan against unique defender deal clusters under the fixed weights."""
    counts = Counter(row["band"] for row in defender_rows)
    cluster_weights: dict[int, float] = {}
    for row in defender_rows:
        deal_seed = int(row["deal_seed"])
        cluster_weights[deal_seed] = cluster_weights.get(deal_seed, 0.0) + (
            band_weights[row["band"]] / counts[row["band"]])
    if (len(cluster_weights) != DEFENDER_DEAL_CLUSTERS
            or not math.isclose(sum(cluster_weights.values()), 1.0,
                                abs_tol=1e-12)):
        raise CapacityDesignRefused("defender planning cluster drift")
    variance_factor = sum(weight * weight
                          for weight in cluster_weights.values())
    effective_clusters = 1.0 / variance_factor
    planning_se = PLANNING_CLUSTER_SD * math.sqrt(variance_factor)
    mde = (Z_ALPHA + Z_POWER) * planning_se
    power = NormalDist().cdf(
        WORTHWHILE_CONDITIONAL_EFFECT / planning_se - Z_ALPHA)
    return {
        "family": "predeclared one-sided normal planning approximation",
        "alpha": ONE_SIDED_ALPHA,
        "target_power": TARGET_POWER,
        "planning_cluster_sd": PLANNING_CLUSTER_SD,
        "worthwhile_conditional_effect": WORTHWHILE_CONDITIONAL_EFFECT,
        "primary_role": "defender",
        "state_rows": len(defender_rows),
        "independent_deal_clusters": len(cluster_weights),
        "rows_by_band": dict(sorted(counts.items())),
        "effective_clusters_under_band_weights": effective_clusters,
        "planning_se": planning_se,
        "mde_at_target_power": mde,
        "power_at_worthwhile_effect": power,
        "adequately_powered_at_worthwhile_effect": power >= TARGET_POWER,
        "confirmatory_claim": False,
    }


def defender_combined_summary(rows: list[dict], design: dict) -> dict:
    """Route one combined DEV+CALIB exploration result on defenders only.

    ``rows`` must already have passed the reviewed per-shard result validator.
    This capacity-specific layer then proves the complete two-split population,
    removes the lone attacker case study from inference, and computes both the
    primary combined estimate and split diagnostics with deal clustering.
    It is deliberately not a terminal strength or natural-dose estimator.
    """
    _validate_design_structure(design)
    selection = design["selection"]
    if (selection["identity_membership_sha256"]
            != REVIEWED_IDENTITY_MEMBERSHIP_SHA256
            or selection["defender_membership_sha256"]
            != REVIEWED_DEFENDER_MEMBERSHIP_SHA256):
        raise CapacityDesignRefused("summary/design membership drift")
    band_weights = design["estimands"]["band_weights"]
    defenders = _defender_rows(rows)
    for row in defenders:
        estimands = row.get("estimands")
        if (not isinstance(estimands, dict)
                or set(estimands) != set(AGG.METRICS)
                or any(not isinstance(estimands[name], (int, float))
                       or isinstance(estimands[name], bool)
                       or not math.isfinite(float(estimands[name]))
                       for name in AGG.METRICS)):
            raise CapacityDesignRefused("defender estimand population drift")

    combined = {
        metric: AGG.weighted_cluster_stats(defenders, metric, band_weights)
        for metric in AGG.METRICS
    }
    if any(stats["deal_clusters"] != DEFENDER_DEAL_CLUSTERS
           for stats in combined.values()):
        raise CapacityDesignRefused("defender summary cluster drift")
    by_split = {
        split: {
            metric: AGG.weighted_cluster_stats(
                [row for row in defenders if row["split"] == split],
                metric, band_weights)
            for metric in AGG.METRICS
        }
        for split in SPLITS
    }
    policy_mean = combined["retained_policy_minus_current"][
        "capture_event_band_weighted_mean"]
    source_mean = combined["best_inserted_pair_minus_current"][
        "capture_event_band_weighted_mean"]
    reviewed_route = AGG.diagnostic_route(policy_mean, source_mean)
    return {
        "schema": SUMMARY_SCHEMA,
        "primary_population": "combined DEV+CALIB defender rows",
        "primary_role": "defender",
        "rows": len(defenders),
        "deal_clusters": DEFENDER_DEAL_CLUSTERS,
        "attacker_case_study_rows_excluded": ATTACKER_ROWS,
        "identity_membership_sha256": REVIEWED_IDENTITY_MEMBERSHIP_SHA256,
        "defender_membership_sha256": REVIEWED_DEFENDER_MEMBERSHIP_SHA256,
        "metrics": combined,
        "split_diagnostics": by_split,
        "routing_basis": "combined_defender_dev_calib",
        "diagnostic_route": CAPACITY_ROUTES[reviewed_route],
        "weight_provenance": (
            "SmartBot-trajectory search-reachable omission events; "
            "not live-champion dose"),
        "selected_role_mix_is_natural_dose": False,
        "exact_natural_decision_estimand": False,
        "exact_whole_round_estimand": False,
        "terminal_selection": False,
        "strength_claim": False,
    }


def build_design(population: Path) -> dict:
    """Reconstruct a fixed, all-row DEV/CALIB design from reviewed bytes."""
    if STATES.sha256_file(population) != POPULATION_FILE_SHA256:
        raise CapacityDesignRefused("formal population file digest drift")
    if STATES.sha256_file(EVAL.__file__) != EVALUATOR_SHA256:
        raise CapacityDesignRefused("reviewed evaluator source drift")
    if STATES.sha256_file(AGG.__file__) != AGGREGATE_SHA256:
        raise CapacityDesignRefused("reviewed aggregate source drift")
    payload = EVAL.load_population(population)
    if (payload.get("artifact_sha256") != POPULATION_ARTIFACT_SHA256
            or payload.get("source_sha256s", {}).get("producer")
            != CAPTURE_SHA256):
        raise CapacityDesignRefused("formal population ancestry drift")

    selected = sorted(
        (row for row in payload["states"] if row["split"] in SPLITS),
        key=lambda row: (SPLITS.index(row["split"]), row["deal_seed"],
                         row["trick"], row["seat"]),
    )
    if len(selected) != len(SPLITS) * ROWS_PER_SPLIT:
        raise CapacityDesignRefused("DEV/CALIB state population drift")
    if any(row["split"] == "report" for row in selected):
        raise CapacityDesignRefused("REPORT row entered capacity design")

    split_counts = Counter(row["split"] for row in selected)
    band_counts = Counter(row["band"] for row in selected)
    role_counts = Counter(row["role"] for row in selected)
    expected_bands = {
        band: len(SPLITS) * BAND_ROWS_PER_SPLIT[band] for band in BANDS
    }
    if (split_counts != Counter({split: ROWS_PER_SPLIT for split in SPLITS})
            or band_counts != Counter(expected_bands)):
        raise CapacityDesignRefused("fixed split/band schedule drift")
    defender_rows = _defender_rows(selected)
    for row in selected:
        if (row["search_eligible"] is not True
                or len(row["current_ballot"]) != BALLOT_WIDTH
                or len(row["retained_ballot"]) != BALLOT_WIDTH
                or EVAL.action_key(row["current_ballot"][0])
                != EVAL.action_key(row["retained_ballot"][0])):
            raise CapacityDesignRefused(
                "search eligibility/equal-width work geometry drift")

    manifest = [_manifest_row(row) for row in selected]
    selection_sha256 = _sha256(_canonical(manifest))
    if selection_sha256 != REVIEWED_SELECTION_SHA256:
        raise CapacityDesignRefused("reviewed selection membership drift")
    lanes = []
    for index in range(SHARD_COUNT):
        lane_rows = [row for row in selected
                     if row["deal_seed"] % SHARD_COUNT == index]
        if not lane_rows or {row["split"] for row in lane_rows} != set(SPLITS):
            raise CapacityDesignRefused("empty/incomplete logical lane")
        lane_manifest = [_manifest_row(row) for row in lane_rows]
        lanes.append({
            "lane_index": index,
            "state_count": len(lane_rows),
            "states_by_split": dict(sorted(Counter(
                row["split"] for row in lane_rows).items())),
            "states_by_band": dict(sorted(Counter(
                row["band"] for row in lane_rows).items())),
            "max_candidate_world_rollouts": (
                len(lane_rows) * MAX_WORK_PER_STATE),
            "selection_sha256": _sha256(_canonical(lane_manifest)),
        })

    band_weights = {
        band: float(payload["search_eligible_weights"][band])
        for band in BANDS
    }
    if band_weights != REVIEWED_BAND_WEIGHTS:
        raise CapacityDesignRefused("reviewed SmartBot band weights drift")
    natural_events = int(payload["search_eligible_denominator"])
    max_deals = int(payload["max_deals"])
    if payload.get("source_policy") != SOURCE_TRAJECTORY_POLICY:
        raise CapacityDesignRefused("source trajectory policy drift")
    # The capture does not publish role-specific natural denominators.  The
    # selected population's 1,023/1 role split is therefore a scope warning,
    # not a valid estimate that 99.9% of natural omission events are defender
    # events.  Keep whole-round dose role-agnostic until a fresh census counts
    # every eligible event by role.
    role_dose_available = False
    design = {
        "schema": SCHEMA,
        "ancestry": {
            "parent_review_git": PARENT_REVIEW_GIT,
            "parent_review_record_sha256": PARENT_REVIEW_RECORD_SHA256,
            "population_file_sha256": POPULATION_FILE_SHA256,
            "population_artifact_sha256": POPULATION_ARTIFACT_SHA256,
            "capture_sha256": CAPTURE_SHA256,
            "evaluator_sha256": EVALUATOR_SHA256,
            "aggregate_sha256": AGGREGATE_SHA256,
        },
        "selection": {
            "splits": list(SPLITS),
            "report_permitted": False,
            "rule": "all frozen DEV and CALIB rows; no outcome filtering",
            "states": len(selected),
            "unique_deal_clusters": len({row["deal_seed"] for row in selected}),
            "states_by_split": dict(sorted(split_counts.items())),
            "states_by_band": dict(sorted(band_counts.items())),
            "states_by_role": dict(sorted(role_counts.items())),
            "identity_membership_sha256":
                REVIEWED_IDENTITY_MEMBERSHIP_SHA256,
            "defender_membership_sha256":
                REVIEWED_DEFENDER_MEMBERSHIP_SHA256,
            "selection_sha256": selection_sha256,
        },
        "schedule": {
            "logical_lanes": SHARD_COUNT,
            "max_concurrent_lanes": MAX_CONCURRENT_LANES,
            "assignment": "deal_seed modulo 16; DEV then CALIB in each lane",
            "outputs": len(SPLITS) * SHARD_COUNT,
            "no_outcome_dependent_extension": True,
            "lanes": lanes,
        },
        "work": {
            "ballot_width": BALLOT_WIDTH,
            "selection_worlds_per_candidate": SELECTION_WORLDS,
            "policy_report_worlds": POLICY_REPORT_WORLDS,
            "external_report_worlds": EXTERNAL_REPORT_WORLDS,
            "complete_policy_rollouts_per_arm": POLICY_WORK_PER_STATE,
            "policy_arms": 2,
            "max_external_actions": MAX_EXTERNAL_ACTIONS,
            "max_external_rollouts_per_state": MAX_EXTERNAL_WORK_PER_STATE,
            "max_candidate_world_rollouts_per_state": MAX_WORK_PER_STATE,
            "max_candidate_world_rollouts_total": (
                len(selected) * MAX_WORK_PER_STATE),
        },
        "estimands": {
            "primary": "defender_retained_policy_minus_current",
            "secondary": "defender_best_inserted_pair_minus_current",
            "primary_row_filter": "role == defender",
            "primary_splits": list(SPLITS),
            "cluster_unit": "deal_seed",
            "band_weights": band_weights,
            "band_weight_unit": (
                "SmartBot-trajectory search-reachable omission events"),
            "within_band_sampling_unit": (
                "first_affected_state_per_deal_band_in_frozen_population"),
            "implementation": (
                "pair_ballot_affected_capacity_design."
                "defender_combined_summary"),
            "combined_dev_calib_primary": True,
            "split_results_are_diagnostics": True,
            "attacker_case_study_is_descriptive_only": True,
            "combined_dev_calib_summary": "predeclared exploration only",
            "exact_natural_decision_estimand": False,
            "exact_whole_round_estimand": False,
            "terminal_selection": False,
        },
        "dose": {
            "source_trajectory_policy": SOURCE_TRAJECTORY_POLICY,
            "search_eligible_omission_events": natural_events,
            "capture_deals": max_deals,
            "events_per_captured_smartbot_deal": natural_events / max_deals,
            "is_live_champion_dose": False,
            "live_champion_role_specific_dose_available": False,
            "translation_to_whole_round_is_approximate": True,
        },
        "scope": {
            "defender_states": role_counts["defender"],
            "attacker_states": role_counts["attacker"],
            "primary_role_inference": "defender-selected-state population",
            "attacker_effect_estimable": False,
            "attacker_row_use": "descriptive case study only",
            "all_role_generalization_authorized": False,
            "role_stratified_reporting_required": True,
            "selected_role_mix_is_natural_dose": False,
            "role_specific_natural_dose_available": role_dose_available,
            "role_conditional_band_weights_available": False,
            "all_role_smartbot_band_weights_used_for_exploration": True,
            "role_specific_capture_census_required_before_whole_round_claim":
                True,
            "late_band_use": "diagnostic slice; natural weight is below 0.001",
        },
        "power": _planning_sensitivity(
            band_weights=band_weights, defender_rows=defender_rows),
        "capacity": {
            "preferred_future_host_class": "cpx62-x86-16-vcpu-32gb",
            "preferred_host_is_runtime_qualified": False,
            "fallback_host_alias": "shengji-cloud",
            "fallback_currently_available": False,
            "public_address_recorded": False,
            "host_qualification_required": True,
            "measured_projection_available": False,
            "preflight_required_before_scored_execution": True,
            "max_fleet_hours": MAX_FLEET_HOURS,
            "max_lane_wall_hours": MAX_LANE_WALL_HOURS,
            "cap_is_fail_closed_not_a_throughput_claim": True,
        },
        "routing": {
            "decision_statistic": "combined DEV+CALIB defender summary",
            "always_publish_both_metrics_and_all_split_band_slices": True,
            "policy_and_source_positive": (
                "measure live-champion natural dose, then design whole-game test"),
            "source_only_positive": "improve selector before whole-game test",
            "no_source_headroom": "stop forced retention; try contextual source",
        },
        "authority": {
            "capacity_design_only": True,
            "population_opened_for_design_only": True,
            "runtime_qualification_authorized": False,
            "capacity_preflight_authorized": False,
            "scored_evaluation_authorized": False,
            "report_access_authorized": False,
            "training_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
            "production_deployment": False,
        },
    }
    design["design_sha256"] = _sha256(_canonical(design))
    _validate_design_structure(design)
    return design


def _require_fields(value: object, fields: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        raise CapacityDesignRefused(f"capacity design {label} field drift")
    return value


def _validate_design_structure(design: object) -> None:
    """Validate the closed schema and every load-bearing semantic value.

    This does not replace source reconstruction: public ``validate_design``
    additionally rebuilds the complete object from the reviewed population.
    Keeping the local schema closed makes the object safe to consume inside
    ``defender_combined_summary`` without silently accepting new authority or
    a relabelled estimator.
    """
    design = _require_fields(design, {
        "schema", "ancestry", "selection", "schedule", "work",
        "estimands", "dose", "scope", "power", "capacity", "routing",
        "authority", "design_sha256",
    }, "top-level")
    if design["schema"] != SCHEMA:
        raise CapacityDesignRefused("capacity design schema drift")
    body = dict(design)
    observed = body.pop("design_sha256", None)
    if observed != _sha256(_canonical(body)):
        raise CapacityDesignRefused("capacity design digest drift")

    ancestry = _require_fields(design["ancestry"], {
        "parent_review_git", "parent_review_record_sha256",
        "population_file_sha256", "population_artifact_sha256",
        "capture_sha256", "evaluator_sha256", "aggregate_sha256",
    }, "ancestry")
    if ancestry != {
            "parent_review_git": PARENT_REVIEW_GIT,
            "parent_review_record_sha256": PARENT_REVIEW_RECORD_SHA256,
            "population_file_sha256": POPULATION_FILE_SHA256,
            "population_artifact_sha256": POPULATION_ARTIFACT_SHA256,
            "capture_sha256": CAPTURE_SHA256,
            "evaluator_sha256": EVALUATOR_SHA256,
            "aggregate_sha256": AGGREGATE_SHA256,
    }:
        raise CapacityDesignRefused("capacity design ancestry drift")

    selection = _require_fields(design["selection"], {
        "splits", "report_permitted", "rule", "states",
        "unique_deal_clusters", "states_by_split", "states_by_band",
        "states_by_role", "identity_membership_sha256",
        "defender_membership_sha256", "selection_sha256",
    }, "selection")
    if selection != {
            "splits": list(SPLITS),
            "report_permitted": False,
            "rule": "all frozen DEV and CALIB rows; no outcome filtering",
            "states": 1_024,
            "unique_deal_clusters": 991,
            "states_by_split": {"calib": 512, "dev": 512},
            "states_by_band": {"early": 896, "late": 32, "mid": 96},
            "states_by_role": {"attacker": 1, "defender": 1_023},
            "identity_membership_sha256":
                REVIEWED_IDENTITY_MEMBERSHIP_SHA256,
            "defender_membership_sha256":
                REVIEWED_DEFENDER_MEMBERSHIP_SHA256,
            "selection_sha256": REVIEWED_SELECTION_SHA256,
    }:
        raise CapacityDesignRefused("capacity design selection drift")

    schedule = _require_fields(design["schedule"], {
        "logical_lanes", "max_concurrent_lanes", "assignment", "outputs",
        "no_outcome_dependent_extension", "lanes",
    }, "schedule")
    lanes = schedule["lanes"]
    if (schedule["logical_lanes"] != SHARD_COUNT
            or schedule["max_concurrent_lanes"] != MAX_CONCURRENT_LANES
            or schedule["assignment"]
            != "deal_seed modulo 16; DEV then CALIB in each lane"
            or schedule["outputs"] != len(SPLITS) * SHARD_COUNT
            or schedule["no_outcome_dependent_extension"] is not True
            or not isinstance(lanes, list) or len(lanes) != SHARD_COUNT):
        raise CapacityDesignRefused("capacity design schedule drift")
    for index, lane in enumerate(lanes):
        lane = _require_fields(lane, {
            "lane_index", "state_count", "states_by_split",
            "states_by_band", "max_candidate_world_rollouts",
            "selection_sha256",
        }, "lane")
        if lane["lane_index"] != index:
            raise CapacityDesignRefused("capacity design lane identity drift")

    work = _require_fields(design["work"], {
        "ballot_width", "selection_worlds_per_candidate",
        "policy_report_worlds", "external_report_worlds",
        "complete_policy_rollouts_per_arm", "policy_arms",
        "max_external_actions", "max_external_rollouts_per_state",
        "max_candidate_world_rollouts_per_state",
        "max_candidate_world_rollouts_total",
    }, "work")
    if work != {
            "ballot_width": BALLOT_WIDTH,
            "selection_worlds_per_candidate": SELECTION_WORLDS,
            "policy_report_worlds": POLICY_REPORT_WORLDS,
            "external_report_worlds": EXTERNAL_REPORT_WORLDS,
            "complete_policy_rollouts_per_arm": POLICY_WORK_PER_STATE,
            "policy_arms": 2,
            "max_external_actions": MAX_EXTERNAL_ACTIONS,
            "max_external_rollouts_per_state": MAX_EXTERNAL_WORK_PER_STATE,
            "max_candidate_world_rollouts_per_state": MAX_WORK_PER_STATE,
            "max_candidate_world_rollouts_total": 1_024 * MAX_WORK_PER_STATE,
    }:
        raise CapacityDesignRefused("capacity design work drift")

    estimands = _require_fields(design["estimands"], {
        "primary", "secondary", "primary_row_filter", "primary_splits",
        "cluster_unit", "band_weights", "band_weight_unit",
        "within_band_sampling_unit", "implementation",
        "combined_dev_calib_primary", "split_results_are_diagnostics",
        "attacker_case_study_is_descriptive_only",
        "combined_dev_calib_summary", "exact_natural_decision_estimand",
        "exact_whole_round_estimand", "terminal_selection",
    }, "estimands")
    if estimands != {
            "primary": "defender_retained_policy_minus_current",
            "secondary": "defender_best_inserted_pair_minus_current",
            "primary_row_filter": "role == defender",
            "primary_splits": list(SPLITS),
            "cluster_unit": "deal_seed",
            "band_weights": REVIEWED_BAND_WEIGHTS,
            "band_weight_unit":
                "SmartBot-trajectory search-reachable omission events",
            "within_band_sampling_unit":
                "first_affected_state_per_deal_band_in_frozen_population",
            "implementation": (
                "pair_ballot_affected_capacity_design."
                "defender_combined_summary"),
            "combined_dev_calib_primary": True,
            "split_results_are_diagnostics": True,
            "attacker_case_study_is_descriptive_only": True,
            "combined_dev_calib_summary": "predeclared exploration only",
            "exact_natural_decision_estimand": False,
            "exact_whole_round_estimand": False,
            "terminal_selection": False,
    }:
        raise CapacityDesignRefused("capacity design estimand drift")

    dose = _require_fields(design["dose"], {
        "source_trajectory_policy", "search_eligible_omission_events",
        "capture_deals", "events_per_captured_smartbot_deal",
        "is_live_champion_dose",
        "live_champion_role_specific_dose_available",
        "translation_to_whole_round_is_approximate",
    }, "dose")
    if dose != {
            "source_trajectory_policy": SOURCE_TRAJECTORY_POLICY,
            "search_eligible_omission_events": 146_112,
            "capture_deals": 12_000_000,
            "events_per_captured_smartbot_deal": 146_112 / 12_000_000,
            "is_live_champion_dose": False,
            "live_champion_role_specific_dose_available": False,
            "translation_to_whole_round_is_approximate": True,
    }:
        raise CapacityDesignRefused("capacity design dose drift")

    scope = _require_fields(design["scope"], {
        "defender_states", "attacker_states", "primary_role_inference",
        "attacker_effect_estimable", "attacker_row_use",
        "all_role_generalization_authorized",
        "role_stratified_reporting_required",
        "selected_role_mix_is_natural_dose",
        "role_specific_natural_dose_available",
        "role_conditional_band_weights_available",
        "all_role_smartbot_band_weights_used_for_exploration",
        "role_specific_capture_census_required_before_whole_round_claim",
        "late_band_use",
    }, "scope")
    if scope != {
            "defender_states": DEFENDER_ROWS,
            "attacker_states": ATTACKER_ROWS,
            "primary_role_inference": "defender-selected-state population",
            "attacker_effect_estimable": False,
            "attacker_row_use": "descriptive case study only",
            "all_role_generalization_authorized": False,
            "role_stratified_reporting_required": True,
            "selected_role_mix_is_natural_dose": False,
            "role_specific_natural_dose_available": False,
            "role_conditional_band_weights_available": False,
            "all_role_smartbot_band_weights_used_for_exploration": True,
            "role_specific_capture_census_required_before_whole_round_claim":
                True,
            "late_band_use": "diagnostic slice; natural weight is below 0.001",
    }:
        raise CapacityDesignRefused("capacity design scope drift")

    power = _require_fields(design["power"], {
        "family", "alpha", "target_power", "planning_cluster_sd",
        "worthwhile_conditional_effect", "primary_role", "state_rows",
        "independent_deal_clusters", "rows_by_band",
        "effective_clusters_under_band_weights", "planning_se",
        "mde_at_target_power", "power_at_worthwhile_effect",
        "adequately_powered_at_worthwhile_effect", "confirmatory_claim",
    }, "power")
    if (power["family"]
            != "predeclared one-sided normal planning approximation"
            or power["alpha"] != ONE_SIDED_ALPHA
            or power["target_power"] != TARGET_POWER
            or power["planning_cluster_sd"] != PLANNING_CLUSTER_SD
            or power["worthwhile_conditional_effect"]
            != WORTHWHILE_CONDITIONAL_EFFECT
            or power["primary_role"] != "defender"
            or power["state_rows"] != DEFENDER_ROWS
            or power["independent_deal_clusters"]
            != DEFENDER_DEAL_CLUSTERS
            or power["rows_by_band"] != DEFENDER_ROWS_BY_BAND
            or power["adequately_powered_at_worthwhile_effect"] is not True
            or power["confirmatory_claim"] is not False):
        raise CapacityDesignRefused("capacity design power drift")

    capacity = _require_fields(design["capacity"], {
        "preferred_future_host_class", "preferred_host_is_runtime_qualified",
        "fallback_host_alias", "fallback_currently_available",
        "public_address_recorded", "host_qualification_required",
        "measured_projection_available",
        "preflight_required_before_scored_execution", "max_fleet_hours",
        "max_lane_wall_hours", "cap_is_fail_closed_not_a_throughput_claim",
    }, "capacity")
    if capacity != {
            "preferred_future_host_class": "cpx62-x86-16-vcpu-32gb",
            "preferred_host_is_runtime_qualified": False,
            "fallback_host_alias": "shengji-cloud",
            "fallback_currently_available": False,
            "public_address_recorded": False,
            "host_qualification_required": True,
            "measured_projection_available": False,
            "preflight_required_before_scored_execution": True,
            "max_fleet_hours": MAX_FLEET_HOURS,
            "max_lane_wall_hours": MAX_LANE_WALL_HOURS,
            "cap_is_fail_closed_not_a_throughput_claim": True,
    }:
        raise CapacityDesignRefused("capacity design capacity drift")

    routing = _require_fields(design["routing"], {
        "decision_statistic",
        "always_publish_both_metrics_and_all_split_band_slices",
        "policy_and_source_positive", "source_only_positive",
        "no_source_headroom",
    }, "routing")
    if routing != {
            "decision_statistic": "combined DEV+CALIB defender summary",
            "always_publish_both_metrics_and_all_split_band_slices": True,
            "policy_and_source_positive": (
                "measure live-champion natural dose, then design whole-game test"),
            "source_only_positive": "improve selector before whole-game test",
            "no_source_headroom":
                "stop forced retention; try contextual source",
    }:
        raise CapacityDesignRefused("capacity design routing drift")

    authority = _require_fields(design["authority"], {
        "capacity_design_only", "population_opened_for_design_only",
        "runtime_qualification_authorized", "capacity_preflight_authorized",
        "scored_evaluation_authorized", "report_access_authorized",
        "training_authorized", "strength_claim", "production_promotion",
        "production_deployment",
    }, "authority")
    if authority != {
            "capacity_design_only": True,
            "population_opened_for_design_only": True,
            "runtime_qualification_authorized": False,
            "capacity_preflight_authorized": False,
            "scored_evaluation_authorized": False,
            "report_access_authorized": False,
            "training_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
            "production_deployment": False,
    }:
        raise CapacityDesignRefused("capacity design authority escalation")


def validate_design(design: object, *, population: Path | None = None) -> None:
    """Validate only by rebuilding from the reviewed population bytes."""
    if population is None:
        raise CapacityDesignRefused(
            "capacity design validation requires source reconstruction")
    _validate_design_structure(design)
    expected = build_design(population)
    if design != expected:
        raise CapacityDesignRefused("capacity design differs from reconstruction")


def verify_design(population: Path, design_path: Path) -> dict:
    if design_path.is_symlink() or not design_path.is_file():
        raise CapacityDesignRefused("capacity design missing/nonregular")
    try:
        observed = json.loads(design_path.read_bytes())
    except (OSError, ValueError) as exc:
        raise CapacityDesignRefused("capacity design unreadable") from exc
    validate_design(observed, population=population)
    return observed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--population", type=Path, required=True)
    parser.add_argument("--design", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "build":
            design = build_design(args.population)
            STATES._write_exclusive(args.design, design)
        else:
            design = verify_design(args.population, args.design)
        print(json.dumps({
            "schema": design["schema"],
            "design_sha256": design["design_sha256"],
            "states": design["selection"]["states"],
            "max_candidate_world_rollouts": design["work"][
                "max_candidate_world_rollouts_total"],
            "scored_evaluation_authorized": False,
        }, sort_keys=True))
    except (CapacityDesignRefused, EVAL.EvalRefused,
            STATES.CaptureRefused, OSError, ValueError) as exc:
        print(f"REFUSING: {exc}")
        raise SystemExit(3) from exc


if __name__ == "__main__":
    main()
