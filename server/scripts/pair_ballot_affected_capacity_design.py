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


def _planning_sensitivity(*, band_weights: dict[str, float],
                          counts: dict[str, int]) -> dict:
    variance_factor = sum(
        band_weights[band] ** 2 / counts[band] for band in BANDS)
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
        "effective_clusters_under_band_weights": effective_clusters,
        "planning_se": planning_se,
        "mde_at_target_power": mde,
        "power_at_worthwhile_effect": power,
        "adequately_powered_at_worthwhile_effect": power >= TARGET_POWER,
        "confirmatory_claim": False,
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
    for row in selected:
        if (row["search_eligible"] is not True
                or len(row["current_ballot"]) != BALLOT_WIDTH
                or len(row["retained_ballot"]) != BALLOT_WIDTH
                or EVAL.action_key(row["current_ballot"][0])
                != EVAL.action_key(row["retained_ballot"][0])):
            raise CapacityDesignRefused(
                "search eligibility/equal-width work geometry drift")

    manifest = [_manifest_row(row) for row in selected]
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
    combined_band_counts = {band: band_counts[band] for band in BANDS}
    natural_events = int(payload["search_eligible_denominator"])
    max_deals = int(payload["max_deals"])
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
            "selection_sha256": _sha256(_canonical(manifest)),
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
            "primary": "retained_policy_minus_current",
            "secondary": "best_inserted_pair_minus_current",
            "cluster_unit": "deal_seed",
            "band_weights": band_weights,
            "band_weight_unit": "all_search_reachable_omission_events",
            "within_band_sampling_unit": (
                "first_affected_state_per_deal_band_in_frozen_population"),
            "split_results_reported_separately": True,
            "combined_dev_calib_summary": "predeclared exploration only",
            "exact_natural_decision_estimand": False,
            "exact_whole_round_estimand": False,
            "terminal_selection": False,
        },
        "dose": {
            "search_eligible_omission_events": natural_events,
            "capture_deals": max_deals,
            "events_per_captured_deal": natural_events / max_deals,
            "translation_to_whole_round_is_approximate": True,
        },
        "scope": {
            "defender_states": role_counts["defender"],
            "attacker_states": role_counts["attacker"],
            "primary_role_inference": "defender",
            "attacker_effect_estimable": False,
            "attacker_row_use": "descriptive case study only",
            "all_role_generalization_authorized": False,
            "role_stratified_reporting_required": True,
            "late_band_use": "diagnostic slice; natural weight is below 0.001",
        },
        "power": _planning_sensitivity(
            band_weights=band_weights, counts=combined_band_counts),
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
            "always_publish_both_metrics_and_all_split_band_slices": True,
            "policy_and_source_positive": "design natural-dose whole-game test",
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
    validate_design(design)
    return design


def validate_design(design: object) -> None:
    if not isinstance(design, dict) or design.get("schema") != SCHEMA:
        raise CapacityDesignRefused("capacity design schema drift")
    body = dict(design)
    observed = body.pop("design_sha256", None)
    if observed != _sha256(_canonical(body)):
        raise CapacityDesignRefused("capacity design digest drift")
    authority = design.get("authority")
    if (not isinstance(authority, dict)
            or authority.get("capacity_design_only") is not True
            or any(authority.get(name) is not False for name in (
                "runtime_qualification_authorized",
                "capacity_preflight_authorized",
                "scored_evaluation_authorized",
                "report_access_authorized",
                "training_authorized",
                "strength_claim",
                "production_promotion",
                "production_deployment",
            ))):
        raise CapacityDesignRefused("capacity design authority escalation")
    if (design.get("selection", {}).get("report_permitted") is not False
            or design.get("selection", {}).get("splits") != list(SPLITS)
            or design.get("power", {}).get(
                "adequately_powered_at_worthwhile_effect") is not True
            or design.get("capacity", {}).get(
                "preflight_required_before_scored_execution") is not True):
        raise CapacityDesignRefused("capacity design boundary drift")


def verify_design(population: Path, design_path: Path) -> dict:
    if design_path.is_symlink() or not design_path.is_file():
        raise CapacityDesignRefused("capacity design missing/nonregular")
    try:
        observed = json.loads(design_path.read_bytes())
    except (OSError, ValueError) as exc:
        raise CapacityDesignRefused("capacity design unreadable") from exc
    validate_design(observed)
    expected = build_design(population)
    if observed != expected:
        raise CapacityDesignRefused("capacity design differs from reconstruction")
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
