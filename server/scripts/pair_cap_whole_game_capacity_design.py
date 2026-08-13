"""Design the attacker-gated pair-cap whole-game capacity experiment.

This module is deliberately declarative.  It freezes a fresh score-free
capacity population and a disjoint future evaluation population, reconstructs
the three policy contracts, and exposes validators for the future score-free
telemetry.  It does not import the game runner, launch gameplay, score a round,
bind a machine, or grant execution authority.

The scientific question is incremental: does the attacker-gated pair-cap
extension improve on reviewed pair-aware v1?  The literal ``mc-s0-report-lcb``
champion remains a third arm so an incremental win cannot be mistaken for an
absolute-strength win.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import sys
from pathlib import Path
from statistics import NormalDist


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
sys.path.insert(0, str(SERVER))

from shengji.ai.heuristic import HeuristicBot  # noqa: E402
from shengji.ai.pair_aware_rollout import (  # noqa: E402
    PAIR_AWARE_COUNTER_FIELDS,
)
from shengji.ai.pair_cap_incremental_rollout import (  # noqa: E402
    PAIR_CAP_INCREMENTAL_COUNTER_FIELDS,
    PAIR_CAP_INCREMENTAL_POLICIES,
    PairCapAttackerIncrementalRolloutPolicy,
    make_pair_cap_incremental_bot,
)
from shengji.ai.pair_cap_rollout import (  # noqa: E402
    PAIR_CAP_COUNTER_FIELDS,
)
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.engine.ballot import mc_ballot  # noqa: E402


SCHEMA = "pair-cap-attacker-whole-game-capacity-design-v1"
CAPACITY_RECORD_SCHEMA = "pair-cap-attacker-capacity-record-v1"
REVIEWED_GIT = "ca1913f0380c24061d9f395c760e3daa4c69de60"
REVIEWED_PARENT_GIT = "8b83cec46e59f8d53ca9f8c6b95fffac862fdffc"
REVIEW_SCHEMA = "pair-cap-attacker-incremental-design-review-v1"
REVIEW_POLICY_SHA256 = (
    "716692c90398d0f2e08133698e3a2942cb5bf10ce1023dfee9691cb7cd0763da")
REVIEW_TEST_SHA256 = (
    "42ee8d942ca1ac09d6c00da1f513cec9d4da9a5bddf69510075e55444f193a21")

SOURCE_SHA256S = {
    "incremental_policy": REVIEW_POLICY_SHA256,
    "incremental_test": REVIEW_TEST_SHA256,
    "attacker_gate_policy": (
        "85ec3ae75367045e651a89ee7bc775f5e70f56d9d16e229860c87256639aab93"),
    "pair_cap_policy": (
        "d591bd2fad91aaf03ac74b4a00fae7e447fd8654e0e5834bf4312682cd4f8e63"),
    "pair_aware_policy": (
        "55f94a58b914301bfb456d91a98b13efb8e40de66750b1ccb07b316fef0b6391"),
    "registry": (
        "dbb2848535eda766df737cda8decffe56e00d514b12ba5fa5c9386ff9d86fd1a"),
    "ballot": (
        "63e2e94ca12f9ebf8dce30c1a1bdbe3fe9cf6223603677173d4eb75e334845d5"),
}
SOURCE_PATHS = {
    "incremental_policy": SERVER / "shengji/ai/pair_cap_incremental_rollout.py",
    "incremental_test": SERVER / "tests/test_pair_cap_incremental_rollout.py",
    "attacker_gate_policy": SERVER / "shengji/ai/pair_cap_attacker_rollout.py",
    "pair_cap_policy": SERVER / "shengji/ai/pair_cap_rollout.py",
    "pair_aware_policy": SERVER / "shengji/ai/pair_aware_rollout.py",
    "registry": SERVER / "shengji/ai/registry.py",
    "ballot": SERVER / "shengji/engine/ballot.py",
}

LABEL_ORDER = ("treatment", "matched_parent", "literal_champion")
POLICY_SEED_OFFSETS = (0, 500_000)
OPPONENT_SEED_OFFSETS = (1_000_000, 1_500_000)
FLIPS = (0, 1)
STREAM_STRIDE = 3_000_017

# The capacity stream is the only population opened by this design.  The
# evaluation stream is frozen now so a later packet cannot select it after
# observing capacity dose, timing, or the broad pair-aware result.
CAPACITY_SEED0 = 620_000_000_000
CAPACITY_CLUSTERS = 8
EVALUATION_SEED0 = 621_000_000_000
EVALUATION_CLUSTERS = 4_608
LOGICAL_LANES = 16
CLUSTERS_PER_LANE = EVALUATION_CLUSTERS // LOGICAL_LANES

ROOT_SELECTION_WORLDS = 30
ROOT_REPORT_WORLDS = 300
LEAD_CANDIDATE_CAP = 14
FOLLOW_CANDIDATE_CAP = 12
MAX_ROOT_ACTIONS_PER_ROUND = 100
MAX_CANDIDATE_WORLD_ROLLOUTS_PER_SEARCH = (
    ROOT_SELECTION_WORLDS * LEAD_CANDIDATE_CAP + 2 * ROOT_REPORT_WORLDS)
ACCEPTED_WORLDS_PER_SEARCH = ROOT_SELECTION_WORLDS + ROOT_REPORT_WORLDS
MIN_CANDIDATE_WORLD_ROLLOUTS_PER_SEARCH = (
    ROOT_SELECTION_WORLDS * 2 + 2 * ROOT_REPORT_WORLDS)

# Algorithmic and operational ceilings.  The hour limits are budget caps, not
# throughput claims; a separately reviewed capacity result must measure every
# arm and project with the safety factor.  No machine is selected here.
CAPACITY_MAX_TOTAL_ELAPSED_SECONDS = 7_200.0
CAPACITY_SAFETY_FACTOR = 2.0
MAX_PROJECTED_COMPUTE_HOURS = 768.0
MAX_PROJECTED_LANE_HOURS = 48.0

# Two positive one-sided contrasts form an intersection-union gate.  This is
# an economical first-look screen, not a confirmation: 4,608 clusters give
# each contrast above 90% marginal power, and an above-80% union-bound joint
# floor, only for effects of at least +0.07.  A smaller effect is disclosed as
# underpowered here rather than used to justify an automatic larger look.  The
# SD anchor is the conservative reviewed whole-game value used by the parent
# pair-aware screen; it is not read from any sealed result.
ONE_SIDED_ALPHA = 0.05
TARGET_POWER_EACH = 0.90
TARGET_JOINT_POWER_FLOOR = 0.80
PLANNING_CLUSTER_SD = 1.6
TARGET_EFFECT = 0.07

ROOT_WORK_FIELDS = (
    "rollouts",
    "searches",
    "search_secs",
    "void_fallbacks",
    "rejected_worlds",
    "sample_attempts",
    "accepted_worlds",
    "failed_worlds",
    "short_searches",
    "zero_world",
    "exact_endgames",
    "exact_endgame_attempts",
    "exact_endgame_refusals",
    "exact_endgame_budget_exceeded",
    "exact_endgame_sessions",
    "exact_endgame_nodes",
    "exact_endgame_cache_hits",
)
FORBIDDEN_TELEMETRY_FIELDS = frozenset({
    "action",
    "actions",
    "attacker_points",
    "banker",
    "cards",
    "history",
    "level_change",
    "level_utility",
    "outcome",
    "outcomes",
    "points",
    "score",
    "scores",
    "utility",
    "winner",
    "winner_team",
    "won",
})


class CapacityDesignRefused(RuntimeError):
    """The reviewed source, closed design, or score-free record drifted."""


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"))
            + "\n").encode()


def _stable_digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _normal_cdf(value: float) -> float:
    """Return the standard-normal CDF with cross-Python-stable arithmetic.

    ``statistics.NormalDist.cdf`` changed its last bit between CPython 3.12
    and 3.14 for the values in this design.  Those floats are persisted inside
    the byte-pinned design, so the mathematically immaterial drift changed the
    complete artifact identity.  ``math.erf`` is identical on every supported
    fleet interpreter for this fixed expression.
    """
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _reviewed_sources() -> dict[str, str]:
    observed = {name: _sha256_path(path)
                for name, path in sorted(SOURCE_PATHS.items())}
    if observed != dict(sorted(SOURCE_SHA256S.items())):
        raise CapacityDesignRefused("reviewed pair-cap source digest drift")
    return observed


def _uppercase_contract(bot) -> dict[str, bool | int | float | str | None]:
    values = {}
    for name in dir(bot):
        if not name.isupper():
            continue
        value = getattr(bot, name)
        if not isinstance(value, (bool, int, float, str, type(None))):
            raise CapacityDesignRefused(
                f"non-serializable champion policy knob {name}")
        values[name] = value
    return values


def _policy_contracts() -> dict[str, dict[str, object]]:
    seed = 7
    treatment = make_pair_cap_incremental_bot(treatment=True, seed=seed)
    parent = make_pair_cap_incremental_bot(treatment=False, seed=seed)
    champion = make_bot(
        PAIR_CAP_INCREMENTAL_POLICIES["literal_champion"], seed=seed)
    bots = (treatment, parent, champion)

    if type(treatment) is not type(parent):
        raise CapacityDesignRefused("treatment/parent root policy class drift")
    if not issubclass(type(treatment), type(champion)):
        raise CapacityDesignRefused("incremental root is not champion-derived")
    if (type(treatment.rollout_policy)
            is not PairCapAttackerIncrementalRolloutPolicy
            or type(parent.rollout_policy)
            is not PairCapAttackerIncrementalRolloutPolicy):
        raise CapacityDesignRefused("incremental rollout seam identity drift")
    if type(champion.rollout_policy) is not HeuristicBot:
        raise CapacityDesignRefused("literal champion rollout seam drift")
    if hasattr(champion, "pair_cap_incremental_telemetry"):
        raise CapacityDesignRefused("literal champion gained an experiment hook")

    uppercase = [_uppercase_contract(bot) for bot in bots]
    ballots = [mc_ballot(bot).digest for bot in bots]
    rng_states = [bot.rng.getstate() for bot in bots]
    if not uppercase[0] == uppercase[1] == uppercase[2]:
        raise CapacityDesignRefused("three-arm champion contract drift")
    if len(set(ballots)) != 1:
        raise CapacityDesignRefused("three-arm root ballot drift")
    if not rng_states[0] == rng_states[1] == rng_states[2]:
        raise CapacityDesignRefused("three-arm initial RNG drift")
    if (treatment.rollout_policy.mode != "treatment"
            or parent.rollout_policy.mode != "matched_parent"):
        raise CapacityDesignRefused("incremental outer mode drift")

    common = {
        "root_base_class": type(champion).__name__,
        "root_ballot_digest": ballots[0],
        "uppercase_contract_sha256": _stable_digest(uppercase[0]),
        "rng_probe_seed": seed,
        "rng_state_sha256": _stable_digest(rng_states[0]),
        "root_selection_worlds": ROOT_SELECTION_WORLDS,
        "root_report_worlds": ROOT_REPORT_WORLDS,
        "lead_candidate_cap": LEAD_CANDIDATE_CAP,
        "follow_candidate_cap": FOLLOW_CANDIDATE_CAP,
        "require_exact_root_work": True,
    }
    return {
        "treatment": {
            **common,
            "class": type(treatment).__name__,
            "policy": PAIR_CAP_INCREMENTAL_POLICIES["treatment"],
            "rollout_class": type(treatment.rollout_policy).__name__,
            "outer_mode": "treatment",
            "component_recipe": ["v1_pair_aware", "v3_attacker_gate"],
            "components_run_once_per_visited_rollout_lead": True,
            "returned_component": "v3 only when incremental action differs",
        },
        "matched_parent": {
            **common,
            "class": type(parent).__name__,
            "policy": PAIR_CAP_INCREMENTAL_POLICIES["matched_parent"],
            "rollout_class": type(parent.rollout_policy).__name__,
            "outer_mode": "matched_parent",
            "component_recipe": ["v1_pair_aware", "v3_attacker_gate"],
            "components_run_once_per_visited_rollout_lead": True,
            "returned_component": "v1",
        },
        "literal_champion": {
            **common,
            "class": type(champion).__name__,
            "policy": PAIR_CAP_INCREMENTAL_POLICIES["literal_champion"],
            "rollout_class": type(champion.rollout_policy).__name__,
            "outer_mode": "off",
            "component_recipe": [],
            "components_run_once_per_visited_rollout_lead": False,
            "returned_component": "literal champion",
        },
    }


def _seed_manifest(*, seed0: int, clusters: int) -> list[dict[str, object]]:
    return [
        {
            "cluster_index": index,
            "deal_seed": seed0 + STREAM_STRIDE * index,
            "flips": list(FLIPS),
            "labels": list(LABEL_ORDER),
            "policy_seed_offsets": list(POLICY_SEED_OFFSETS),
            "opponent_seed_offsets": list(OPPONENT_SEED_OFFSETS),
        }
        for index in range(clusters)
    ]


def _population_block(*, seed0: int, clusters: int) -> dict[str, object]:
    manifest = _seed_manifest(seed0=seed0, clusters=clusters)
    return {
        "seed0": seed0,
        "clusters": clusters,
        "seed_hi": seed0 + STREAM_STRIDE * (clusters - 1),
        "stream_stride": STREAM_STRIDE,
        "flips": list(FLIPS),
        "labels": list(LABEL_ORDER),
        "policy_seed_offsets": list(POLICY_SEED_OFFSETS),
        "opponent_seed_offsets": list(OPPONENT_SEED_OFFSETS),
        "manifest_sha256": _stable_digest(manifest),
    }


def _planning() -> dict[str, object]:
    standard_error = PLANNING_CLUSTER_SD / math.sqrt(EVALUATION_CLUSTERS)
    z_alpha = NormalDist().inv_cdf(1.0 - ONE_SIDED_ALPHA)
    z_power80 = NormalDist().inv_cdf(TARGET_JOINT_POWER_FLOOR)
    z_power_each = NormalDist().inv_cdf(TARGET_POWER_EACH)
    marginal_power = _normal_cdf(
        TARGET_EFFECT / standard_error - z_alpha)
    sensitivity = {}
    for effect in (0.05, 0.06, TARGET_EFFECT):
        power = _normal_cdf(effect / standard_error - z_alpha)
        sensitivity[f"{effect:.2f}"] = {
            "marginal_power_each": power,
            "joint_power_union_bound_floor": max(0.0, 2.0 * power - 1.0),
        }
    return {
        "cluster_unit": "deal seed with both policy-team flips",
        "planning_cluster_sd": PLANNING_CLUSTER_SD,
        "dispersion_provenance": (
            "conservative reviewed whole-game planning anchor; no sealed "
            "pair outcome read"),
        "one_sided_alpha_per_contrast": ONE_SIDED_ALPHA,
        "intersection_union_gate": True,
        "multiplicity_adjustment_for_type_i_error": (
            "none; the claim requires both null hypotheses to be rejected"),
        "clusters": EVALUATION_CLUSTERS,
        "standard_error": standard_error,
        "mde_at_80pct_marginal_power": (
            (z_alpha + z_power80) * standard_error),
        "target_effect": TARGET_EFFECT,
        "target_effect_interpretation": (
            "minimum worthwhile effect for this economical screen"),
        "marginal_power_at_target_effect": marginal_power,
        "target_marginal_power_each": TARGET_POWER_EACH,
        "clusters_required_for_target_marginal_power_each": math.ceil(
            ((z_alpha + z_power_each) * PLANNING_CLUSTER_SD
             / TARGET_EFFECT) ** 2),
        "joint_power_union_bound_floor_at_target_effect": max(
            0.0, 2.0 * marginal_power - 1.0),
        "target_joint_power_floor": TARGET_JOINT_POWER_FLOOR,
        "sensitivity_by_effect": sensitivity,
        "adequately_powered": (
            marginal_power >= TARGET_POWER_EACH
            and 2.0 * marginal_power - 1.0
            >= TARGET_JOINT_POWER_FLOOR),
    }


def _work_block(clusters: int) -> dict[str, object]:
    arm_rounds = clusters * len(LABEL_ORDER) * len(FLIPS)
    max_root_searches = arm_rounds * MAX_ROOT_ACTIONS_PER_ROUND
    return {
        "clusters": clusters,
        "arms": len(LABEL_ORDER),
        "flips": len(FLIPS),
        "arm_rounds": arm_rounds,
        "max_root_actions_per_round": MAX_ROOT_ACTIONS_PER_ROUND,
        "root_search_scope": "arm team plus literal champion opponent",
        "max_all_bot_root_searches": max_root_searches,
        "accepted_worlds_per_contested_search": ACCEPTED_WORLDS_PER_SEARCH,
        "max_accepted_worlds": (
            max_root_searches * ACCEPTED_WORLDS_PER_SEARCH),
        "max_candidate_world_rollouts_per_search": (
            MAX_CANDIDATE_WORLD_ROLLOUTS_PER_SEARCH),
        "max_candidate_world_rollouts": (
            max_root_searches
            * MAX_CANDIDATE_WORLD_ROLLOUTS_PER_SEARCH),
    }


def build_design() -> dict[str, object]:
    """Reconstruct the complete design from reviewed source and constants."""
    sources = _reviewed_sources()
    arms = _policy_contracts()
    capacity = _population_block(
        seed0=CAPACITY_SEED0, clusters=CAPACITY_CLUSTERS)
    evaluation = _population_block(
        seed0=EVALUATION_SEED0, clusters=EVALUATION_CLUSTERS)
    if ({row["deal_seed"] for row in _seed_manifest(
            seed0=CAPACITY_SEED0, clusters=CAPACITY_CLUSTERS)}
            & {row["deal_seed"] for row in _seed_manifest(
                seed0=EVALUATION_SEED0, clusters=EVALUATION_CLUSTERS)}):
        raise CapacityDesignRefused("capacity/evaluation seed overlap")
    planning = _planning()
    if planning["adequately_powered"] is not True:
        raise CapacityDesignRefused("whole-game design is underpowered")

    payload = {
        "schema": SCHEMA,
        "reviewed_source": {
            "pr_number": 69,
            "git": REVIEWED_GIT,
            "parent_pr_number": 62,
            "parent_git": REVIEWED_PARENT_GIT,
            "review_schema": REVIEW_SCHEMA,
            "review_verdict": "PASS",
            "review_authority": "capacity/packet design only",
            "review_claim": {
                "component_work_identical": True,
                "parent_v1_preserved": True,
                "attacker_only_incremental_dose": True,
                "root_ballot_unchanged": True,
                "literal_champion_separate_arm_required": True,
                "public_information_only": True,
                "capacity_packet_design_authorized": True,
                "whole_game_execution_authorized": False,
                "strength_claim": False,
                "production_promotion": False,
                "production_deployment": False,
            },
            "source_sha256s": sources,
            "sealed_outcomes_opened": False,
        },
        "population": {
            "source": (
                "fresh deterministic Game(random.Random(deal_seed)) streams; "
                "no capture, filtering, replacement, retry, or extension"),
            "capacity": capacity,
            "evaluation": evaluation,
            "capacity_evaluation_disjoint": True,
            "same_deal_for_all_arms": True,
            "same_two_flips_for_all_arms": True,
            "same_policy_and_opponent_rng_offsets_for_all_arms": True,
            "freshness_must_be_rechecked_against_live_ledger_before_admission":
                True,
        },
        "arms": {
            "order": list(LABEL_ORDER),
            "contracts": arms,
            "opponent_for_every_arm": (
                PAIR_CAP_INCREMENTAL_POLICIES["literal_champion"]),
            "treatment_parent_component_work_identical": True,
            "component_work_identity_unit": "each visited rollout lead",
            "post_divergence_total_lead_counts_may_differ": True,
            "literal_champion_is_unmodified": True,
            "champion_internal_component_work_identical": False,
            "champion_budget_comparability_unit": (
                "root Monte Carlo budget on a shared public state; internal "
                "continuation CPU is intentionally not equal"),
            "champion_budget_comparison": (
                "same exact root N=30 selection, paired N=300 report, root "
                "ballot, deal, flip, and seed offsets; no shadow component hook"),
        },
        "estimands": {
            "stage": "economical first-look screen; not confirmation",
            "primary": (
                "mirrored mean signed level utility: treatment minus "
                "matched_parent"),
            "absolute_guardrail": (
                "mirrored mean signed level utility: treatment minus "
                "literal_champion"),
            "diagnostic": (
                "mirrored mean signed level utility: matched_parent minus "
                "literal_champion"),
            "secondary": (
                "mirrored whole-round win-rate differences for all three "
                "pairwise contrasts"),
            "cluster_unit": "deal seed; average both flips before inference",
            "decision_rule": (
                "PASS_SCREEN only if one-sided 95% LCBs for both treatment "
                "minus matched_parent and treatment minus literal_champion "
                "are positive and every integrity/dose gate passes"),
            "diagnostic_can_select_treatment": False,
            "secondary_can_select_treatment": False,
            "capacity_telemetry_can_select_treatment": False,
            "pass_opens": (
                "fresh disjoint confirmation design review only; no execution"),
            "nonpass_route": "SELECT_NONE; no automatic continuation",
        },
        "power": planning,
        "work_ceiling": {
            "capacity": _work_block(CAPACITY_CLUSTERS),
            "evaluation": _work_block(EVALUATION_CLUSTERS),
            "logical_lanes": LOGICAL_LANES,
            "evaluation_clusters_per_lane": CLUSTERS_PER_LANE,
            "capacity_max_total_elapsed_seconds": (
                CAPACITY_MAX_TOTAL_ELAPSED_SECONDS),
            "projection_safety_factor": CAPACITY_SAFETY_FACTOR,
            "max_projected_compute_hours": MAX_PROJECTED_COMPUTE_HOURS,
            "max_projected_lane_hours": MAX_PROJECTED_LANE_HOURS,
            "projection_uses_measured_sum_of_three_arm_times": True,
            "projection_formula": (
                "2.0 * (sum elapsed seconds for all 48 fixed capacity "
                "records / 8 clusters) * 4608 clusters / 3600"),
            "lane_projection_formula": (
                "projected compute hours / 16 fixed equal-count lanes"),
            "champion_time_reported_separately": True,
            "resource_or_machine_binding": False,
        },
        "telemetry": {
            "capacity_record_schema": CAPACITY_RECORD_SCHEMA,
            "record_fields": [
                "schema", "design_sha256", "cluster_index", "deal_seed",
                "flip", "label", "policy", "opponent", "elapsed_seconds",
                "arm_root_work", "opponent_root_work", "root_roles",
                "incremental", "natural_dose",
            ],
            "root_work_fields": list(ROOT_WORK_FIELDS),
            "incremental_sections": [
                "outer", "v1_pair_aware", "v3_pair_aware", "v3_pair_cap"],
            "treatment_parent_components_are_counterfactual_analyses": True,
            "outer_counters_alone_bind_returned_action_dose": True,
            "literal_champion_incremental_telemetry": None,
            "root_work_exact_for_every_contested_decision": True,
            "per_arm_elapsed_seconds_required": True,
            "forbidden_recursive_fields": sorted(FORBIDDEN_TELEMETRY_FIELDS),
            "raw_actions_or_histories_retained": False,
            "design_build_scores_or_outcomes_computed": False,
            "future_capacity_scores_or_outcomes_retained_or_published": False,
            "complete_collection_required_before_projection": True,
            "capacity_collection_rows": (
                CAPACITY_CLUSTERS * len(FLIPS) * len(LABEL_ORDER)),
        },
        "role_dose_scope": {
            "mirrored_policy_team_roles": ["attacker", "defender"],
            "both_roles_required_in_fixed_capacity_population": True,
            "incremental_continuation_gate": "attacker leads only",
            "v1_parent_remains_active_for_both_roles": True,
            "v3_pair_cap_defender_triggers_required": 0,
            "natural_treatment_parent_root_changes_required_for_capacity_pass":
                1,
            "root_changes_reported_by_role_and_phase": True,
            "no_claim_of_role_specific_power": True,
            "no_role_specific_strength_claim": True,
        },
        "refusal": {
            "unknown_or_extra_design_fields": "refuse",
            "source_or_review_identity_drift": "refuse",
            "population_seed_flip_label_or_rng_drift": "refuse",
            "treatment_parent_component_recipe_drift": "refuse",
            "literal_champion_substitution_or_hook": "refuse",
            "capacity_total_elapsed_above_7200_seconds": "HOLD; no extension",
            "short_or_zero_world_root_search": "refuse",
            "score_outcome_action_or_history_telemetry": "refuse",
            "nonzero_incremental_defender_trigger": "refuse",
            "zero_natural_incremental_root_change": "HOLD; no extension",
            "capacity_or_power_ceiling_failure": "HOLD; no smaller claim",
            "outcome_dependent_retry_or_population_extension": "refuse",
            "larger_or_second_look": (
                "requires a new design, fresh disjoint population, and "
                "independent review; never automatic"),
            "broad_pair_screen_dependency": (
                "route economics only after its terminal result is "
                "independently reviewed"),
        },
        "authority": {
            "design_only": True,
            "score_free": True,
            "design_review_authorized": True,
            "capacity_implementation_authorized": False,
            "capacity_execution_authorized": False,
            "scored_controller_implementation_authorized": False,
            "scored_packet_review_authorized": False,
            "whole_game_execution_authorized": False,
            "sealed_outcome_access_authorized": False,
            "launcher_present": False,
            "resource_binding_authorized": False,
            "retry_or_extension_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
            "production_deployment": False,
        },
    }
    payload["design_sha256"] = _stable_digest(payload)
    return payload


def validate_design(payload: object) -> None:
    """Fail closed unless ``payload`` exactly reconstructs from reviewed bytes."""
    if not isinstance(payload, dict):
        raise CapacityDesignRefused("capacity design is not an object")
    body = dict(payload)
    observed = body.pop("design_sha256", None)
    if observed != _stable_digest(body):
        raise CapacityDesignRefused("capacity design digest drift")
    expected = build_design()
    if payload != expected:
        raise CapacityDesignRefused("capacity design differs from reconstruction")


def verify_design_file(path: os.PathLike | str) -> dict[str, object]:
    source = Path(path)
    partial = Path(str(source) + ".partial")
    try:
        info = source.lstat()
    except FileNotFoundError as exc:
        raise CapacityDesignRefused("capacity design file is missing") from exc
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or os.path.lexists(partial)):
        raise CapacityDesignRefused(
            "capacity design file is linked, nonregular, or partial")
    try:
        payload = json.loads(source.read_bytes())
    except (OSError, ValueError) as exc:
        raise CapacityDesignRefused("capacity design file is unreadable") from exc
    validate_design(payload)
    return payload


def _forbidden_telemetry_paths(value: object, path: str = "$") -> list[str]:
    problems = []
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}"
            if str(key).lower() in FORBIDDEN_TELEMETRY_FIELDS:
                problems.append(child)
            problems.extend(_forbidden_telemetry_paths(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            problems.extend(_forbidden_telemetry_paths(
                item, f"{path}[{index}]"))
    return problems


def _counter_dict_problems(value: object, fields: tuple[str, ...],
                           *, label: str) -> list[str]:
    if not isinstance(value, dict) or set(value) != set(fields):
        return [f"{label} field population"]
    if any(isinstance(item, bool) or not isinstance(item, int) or item < 0
           for item in value.values()):
        return [f"{label} counters"]
    return []


def _root_work_problems(value: object, *, label: str) -> list[str]:
    if not isinstance(value, dict) or set(value) != set(ROOT_WORK_FIELDS):
        return [f"{label} field population"]
    problems = []
    for field in ROOT_WORK_FIELDS:
        item = value[field]
        if field == "search_secs":
            if (isinstance(item, bool) or not isinstance(item, (int, float))
                    or not math.isfinite(item) or item < 0):
                problems.append(f"{label} search_secs")
        elif isinstance(item, bool) or not isinstance(item, int) or item < 0:
            problems.append(f"{label} {field}")
    if problems:
        return problems
    searches = value["searches"]
    if searches <= 0:
        problems.append(f"{label} has no contested root search")
    if value["accepted_worlds"] != ACCEPTED_WORLDS_PER_SEARCH * searches:
        problems.append(f"{label} accepted-world dose")
    if value["sample_attempts"] != (
            value["accepted_worlds"] + value["failed_worlds"]):
        problems.append(f"{label} sampler accounting")
    if value["rejected_worlds"] > value["failed_worlds"]:
        problems.append(f"{label} rejected-world accounting")
    if not (MIN_CANDIDATE_WORLD_ROLLOUTS_PER_SEARCH * searches
            <= value["rollouts"]
            <= MAX_CANDIDATE_WORLD_ROLLOUTS_PER_SEARCH * searches):
        problems.append(f"{label} candidate-world budget")
    for field in (
            "void_fallbacks", "short_searches", "zero_world",
            "exact_endgames", "exact_endgame_attempts",
            "exact_endgame_refusals", "exact_endgame_budget_exceeded",
            "exact_endgame_sessions", "exact_endgame_nodes",
            "exact_endgame_cache_hits"):
        if value[field] != 0:
            problems.append(f"{label} forbidden {field}")
    return problems


def _pair_aware_problems(value: object, *, label: str) -> list[str]:
    problems = _counter_dict_problems(
        value, PAIR_AWARE_COUNTER_FIELDS, label=label)
    if problems:
        return problems
    assert isinstance(value, dict)
    if value["single_baseline_leads"] > value["lead_calls"]:
        problems.append(f"{label} lead accounting")
    if value["promoted_boss_pairs"] > value["pair_candidates_checked"]:
        problems.append(f"{label} candidate accounting")
    if value["ruff_safe_promoted_pairs"] > value["promoted_boss_pairs"]:
        problems.append(f"{label} ruff accounting")
    if value["triggers"] != value["opportunities"]:
        problems.append(f"{label} opportunity accounting")
    if value["triggers"] != (
            value["attacker_triggers"] + value["defender_triggers"]):
        problems.append(f"{label} role accounting")
    if value["point_pair_triggers"] > value["triggers"]:
        problems.append(f"{label} point-trigger accounting")
    if (value["changes"] != value["triggers"]
            or value["matched_noops"] != 0):
        problems.append(f"{label} always-treatment component dose")
    return problems


def _pair_cap_problems(value: object) -> list[str]:
    problems = _counter_dict_problems(
        value, PAIR_CAP_COUNTER_FIELDS, label="v3 pair-cap")
    if problems:
        return problems
    assert isinstance(value, dict)
    if not (value["ruff_safe_proofs"]
            <= value["opponent_pair_cap_proofs"]
            <= value["candidates_checked"]):
        problems.append("v3 pair-cap proof accounting")
    if value["triggers"] != value["opportunities"]:
        problems.append("v3 pair-cap opportunity accounting")
    if value["triggers"] != (
            value["attacker_triggers"] + value["defender_triggers"]):
        problems.append("v3 pair-cap role accounting")
    if value["point_pair_triggers"] > value["triggers"]:
        problems.append("v3 pair-cap point-trigger accounting")
    if value["defender_triggers"] != 0:
        problems.append("v3 pair-cap defender trigger")
    if (value["changes"] != value["triggers"]
            or value["matched_noops"] != 0):
        problems.append("v3 pair-cap always-treatment component dose")
    return problems


def _incremental_problems(value: object, *, mode: str) -> list[str]:
    expected_fields = {
        "schema", "mode", "deterministic", "public_information_only",
        "exact_component_work", "components_are_counterfactual_analyses",
        "counters",
    }
    if not isinstance(value, dict) or set(value) != expected_fields:
        return ["incremental telemetry field population"]
    problems = []
    if (value["schema"] != "pair-cap-attacker-incremental-telemetry-v1"
            or value["mode"] != mode
            or value["deterministic"] is not True
            or value["public_information_only"] is not True
            or value["exact_component_work"] is not True
            or value["components_are_counterfactual_analyses"] is not True):
        problems.append("incremental telemetry identity")
    counters = value["counters"]
    if not isinstance(counters, dict) or set(counters) != {
            "outer", "v1_pair_aware", "v3_pair_aware", "v3_pair_cap"}:
        return problems + ["incremental component population"]
    outer = counters["outer"]
    v1 = counters["v1_pair_aware"]
    v3 = counters["v3_pair_aware"]
    cap = counters["v3_pair_cap"]
    problems.extend(_counter_dict_problems(
        outer, PAIR_CAP_INCREMENTAL_COUNTER_FIELDS, label="incremental outer"))
    problems.extend(_pair_aware_problems(v1, label="v1 pair-aware"))
    problems.extend(_pair_aware_problems(v3, label="v3 pair-aware"))
    problems.extend(_pair_cap_problems(cap))
    if problems:
        return problems
    assert all(isinstance(item, dict) for item in (outer, v1, v3, cap))
    if not outer["lead_calls"] == v1["lead_calls"] == v3["lead_calls"]:
        problems.append("incremental component lead work")
    if not (outer["triggers"] == outer["opportunities"]
            == outer["v1_v3_action_differences"] == cap["triggers"]):
        problems.append("incremental trigger accounting")
    if (outer["defender_triggers"] != 0
            or outer["attacker_triggers"] != cap["attacker_triggers"]
            or outer["point_pair_triggers"] != cap["point_pair_triggers"]):
        problems.append("incremental attribution")
    if v3["triggers"] != v1["triggers"] + cap["triggers"]:
        problems.append("incremental v3 composition")
    expected_changes = outer["triggers"] if mode == "treatment" else 0
    expected_noops = 0 if mode == "treatment" else outer["triggers"]
    if (outer["changes"] != expected_changes
            or outer["matched_parent_noops"] != expected_noops):
        problems.append("incremental returned-action dose")
    return problems


def capacity_record_problems(record: object, design: object) -> list[str]:
    """Validate one future score-free arm/flip capacity record.

    This validates telemetry only.  It cannot authorize producing a record.
    """
    try:
        validate_design(design)
    except CapacityDesignRefused as exc:
        return [f"design: {exc}"]
    forbidden = _forbidden_telemetry_paths(record)
    if forbidden:
        return ["forbidden telemetry field: " + path for path in forbidden]
    fields = set(design["telemetry"]["record_fields"])
    if not isinstance(record, dict) or set(record) != fields:
        return ["capacity record field population"]

    problems = []
    label = record["label"]
    index = record["cluster_index"]
    flip = record["flip"]
    if (record["schema"] != CAPACITY_RECORD_SCHEMA
            or record["design_sha256"] != design["design_sha256"]
            or isinstance(index, bool) or not isinstance(index, int)
            or not 0 <= index < CAPACITY_CLUSTERS
            or record["deal_seed"]
            != CAPACITY_SEED0 + STREAM_STRIDE * index
            or isinstance(flip, bool) or not isinstance(flip, int)
            or flip not in FLIPS
            or label not in LABEL_ORDER):
        problems.append("capacity record identity")
        return problems
    contract = design["arms"]["contracts"][label]
    if (record["policy"] != contract["policy"]
            or record["opponent"]
            != PAIR_CAP_INCREMENTAL_POLICIES["literal_champion"]):
        problems.append("capacity record policy identity")
    elapsed = record["elapsed_seconds"]
    if (isinstance(elapsed, bool) or not isinstance(elapsed, (int, float))
            or not math.isfinite(elapsed) or elapsed <= 0
            or elapsed > CAPACITY_MAX_TOTAL_ELAPSED_SECONDS):
        problems.append("capacity record elapsed time")
    problems.extend(_root_work_problems(
        record["arm_root_work"], label="arm root work"))
    problems.extend(_root_work_problems(
        record["opponent_root_work"], label="opponent root work"))

    roles = record["root_roles"]
    if (not isinstance(roles, dict)
            or set(roles) != {"attacker_searches", "defender_searches"}
            or any(isinstance(item, bool) or not isinstance(item, int)
                   or item < 0 for item in roles.values())
            or sum(roles.values()) != record["arm_root_work"]["searches"]):
        problems.append("capacity record root-role accounting")

    if label == "literal_champion":
        if record["incremental"] is not None:
            problems.append("literal champion gained incremental telemetry")
    else:
        problems.extend(_incremental_problems(
            record["incremental"], mode=label))

    dose = record["natural_dose"]
    if label != "treatment":
        if dose is not None:
            problems.append("non-treatment arm gained natural-dose contrast")
    elif (not isinstance(dose, dict)
          or set(dose) != {
              "shared_prefix_root_decisions", "root_action_changed",
              "change_phase", "change_role"}
          or isinstance(dose.get("shared_prefix_root_decisions"), bool)
          or not isinstance(dose.get("shared_prefix_root_decisions"), int)
          or dose["shared_prefix_root_decisions"] < 0
          or not isinstance(dose.get("root_action_changed"), bool)):
        problems.append("treatment natural-dose population")
    elif dose["root_action_changed"]:
        if (dose["change_phase"] not in {"early", "mid", "late"}
                or dose["change_role"] not in {"attacker", "defender"}):
            problems.append("treatment natural-dose attribution")
    elif dose["change_phase"] is not None or dose["change_role"] is not None:
        problems.append("treatment zero-dose attribution")
    return sorted(set(problems))


def capacity_collection_problems(records: object,
                                 design: object) -> list[str]:
    """Validate the complete future score-free capacity preflight.

    Per-record validity is insufficient for a preflight claim: duplicates can
    hide missing arms, individually legal elapsed times can exceed the whole
    budget, and a claimed natural root change is impossible without any
    incremental continuation trigger on the shared prefix.  This collection
    validator closes those seams without launching or scoring gameplay.
    """
    try:
        validate_design(design)
    except CapacityDesignRefused as exc:
        return [f"design: {exc}"]
    if not isinstance(records, list):
        return ["capacity collection is not a list"]

    expected_rows = CAPACITY_CLUSTERS * len(FLIPS) * len(LABEL_ORDER)
    problems = []
    if len(records) != expected_rows:
        problems.append("capacity collection row count")

    identities = []
    valid_rows = []
    for position, record in enumerate(records):
        row_problems = capacity_record_problems(record, design)
        problems.extend(
            f"record {position}: {problem}" for problem in row_problems)
        if not row_problems:
            assert isinstance(record, dict)
            valid_rows.append(record)
            identities.append((
                record["cluster_index"], record["flip"], record["label"]))

    expected_identities = {
        (index, flip, label)
        for index in range(CAPACITY_CLUSTERS)
        for flip in FLIPS
        for label in LABEL_ORDER
    }
    if len(valid_rows) == len(records) and (
            len(set(identities)) != len(identities)
            or set(identities) != expected_identities):
        problems.append("capacity collection identity population")
    if problems:
        return sorted(set(problems))

    elapsed_seconds = math.fsum(
        float(record["elapsed_seconds"]) for record in valid_rows)
    if elapsed_seconds > CAPACITY_MAX_TOTAL_ELAPSED_SECONDS:
        problems.append("capacity collection total elapsed cap")

    projected_compute_hours = (
        CAPACITY_SAFETY_FACTOR
        * elapsed_seconds / CAPACITY_CLUSTERS
        * EVALUATION_CLUSTERS / 3_600.0)
    projected_lane_hours = projected_compute_hours / LOGICAL_LANES
    if projected_compute_hours > MAX_PROJECTED_COMPUTE_HOURS:
        problems.append("capacity projected compute-hour cap")
    if projected_lane_hours > MAX_PROJECTED_LANE_HOURS:
        problems.append("capacity projected lane-hour cap")

    total_searches = 0
    total_accepted_worlds = 0
    total_rollouts = 0
    for record in valid_rows:
        arm = record["arm_root_work"]
        opponent = record["opponent_root_work"]
        round_searches = arm["searches"] + opponent["searches"]
        if round_searches > MAX_ROOT_ACTIONS_PER_ROUND:
            problems.append("capacity per-round root-search cap")
        total_searches += round_searches
        total_accepted_worlds += (
            arm["accepted_worlds"] + opponent["accepted_worlds"])
        total_rollouts += arm["rollouts"] + opponent["rollouts"]
        if math.fsum((float(arm["search_secs"]),
                      float(opponent["search_secs"]))) > (
                          float(record["elapsed_seconds"]) + 0.01):
            problems.append("capacity root-search time exceeds round time")

    ceiling = design["work_ceiling"]["capacity"]
    if total_searches > ceiling["max_all_bot_root_searches"]:
        problems.append("capacity aggregate root-search cap")
    if total_accepted_worlds > ceiling["max_accepted_worlds"]:
        problems.append("capacity aggregate accepted-world cap")
    if total_rollouts > ceiling["max_candidate_world_rollouts"]:
        problems.append("capacity aggregate candidate-world cap")

    role_totals = {
        label: {"attacker_searches": 0, "defender_searches": 0}
        for label in LABEL_ORDER
    }
    changed_roots = 0
    for record in valid_rows:
        label = record["label"]
        for role in role_totals[label]:
            role_totals[label][role] += record["root_roles"][role]
        if label != "treatment":
            continue
        dose = record["natural_dose"]
        assert isinstance(dose, dict)
        changed = dose["root_action_changed"]
        changed_roots += int(changed)
        outer = record["incremental"]["counters"]["outer"]
        if changed and outer["triggers"] <= 0:
            problems.append(
                "capacity root change without incremental trigger dose")
        if dose["shared_prefix_root_decisions"] > \
                MAX_ROOT_ACTIONS_PER_ROUND:
            problems.append("capacity shared-prefix root-decision cap")

    for label, totals in role_totals.items():
        if any(totals[role] <= 0 for role in totals):
            problems.append(f"capacity {label} missing root role")
    if changed_roots < design["role_dose_scope"][
            "natural_treatment_parent_root_changes_required_for_capacity_pass"]:
        problems.append("capacity has zero natural incremental root changes")
    return sorted(set(problems))
