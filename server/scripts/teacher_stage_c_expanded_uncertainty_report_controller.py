#!/usr/bin/env python3
"""Freeze one powered champion-uncertainty Stage-C REPORT examination.

The already-reviewed broad play ensemble is positive on DESIGN and CALIB, but
its frozen 480-state broad REPORT exam was held before evidence because it was
underpowered.  This replacement spends every still-untouched REPORT state in
the one pre-REPORT stratum that has a positive lower bound in both cohorts and
adequate projected power: ``champion_uncertainty`` (219 play states).

Selection uses only capture-time public-information diagnostics and frozen
DESIGN/CALIB model outputs.  The controller never opens a REPORT label, model
prediction, or utility.  A later composition must reproduce the uncertainty
predicate online from public information; this state-level packet does not
authorize that implementation, a game screen, strength, promotion, or deploy.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SCRIPT.parents[2]
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import teacher_stage_c_expanded_play_report_controller as BASE  # noqa: E402
from shengji.rl import stage_c_expansion as EXP  # noqa: E402
from shengji.rl import stage_c_report as REPORT  # noqa: E402


CAP = BASE.CAP
TRAIN = BASE.TRAIN
MODEL = CAP.MODEL

SCHEMA = "teacher-stage-c-expanded-uncertainty-report-controller-v3"
PACKET_ID = \
    "teacher-v3-hard-tail-stage-c-expanded-uncertainty-report-controller-v3"
RUN_ID = "teacher-v3-hard-tail-stage-c-expanded-uncertainty-report-v3"
CONTROLLER_RUN_ID = \
    "teacher-v3-hard-tail-stage-c-expanded-uncertainty-report-controller-v3"
PACKET_PATH = f"server/runs/logs/{CONTROLLER_RUN_ID}/controller_packet.json"
REVIEW_SCHEMA = \
    "teacher-stage-c-expanded-uncertainty-report-controller-review-v3"
REVIEW_MARKER = \
    "TEACHER_STAGE_C_EXPANDED_UNCERTAINTY_REPORT_CONTROLLER_V3_REVIEW "

RUNTIME_RECEIPT_SCHEMA = \
    "teacher-stage-c-expanded-uncertainty-report-receipt-v3"
RUNTIME_ADMISSION_SCHEMA = \
    "teacher-stage-c-expanded-uncertainty-report-admission-v3"
RUNTIME_REPORT_OPEN_ADMISSION_SCHEMA = \
    "teacher-stage-c-expanded-uncertainty-report-open-admission-v3"
RUNTIME_SHARD_ADMISSION_SCHEMA = \
    "teacher-stage-c-expanded-uncertainty-report-shard-admission-v3"
RUNTIME_SHARD_SCHEMA = \
    "teacher-stage-c-expanded-uncertainty-report-label-shard-v3"
RUNTIME_RESULT_SCHEMA = \
    "teacher-stage-c-expanded-uncertainty-report-result-v3"
SUPERVISOR_SCHEMA = \
    "teacher-stage-c-expanded-uncertainty-report-supervisor-v3"
SUPERVISOR_EXIT_SCHEMA = \
    "teacher-stage-c-expanded-uncertainty-report-supervisor-exit-v3"
SUPERVISOR_FINAL_SCHEMA = \
    "teacher-stage-c-expanded-uncertainty-report-supervisor-final-v3"
SUPERVISOR_REVIEW_SCHEMA = \
    "teacher-stage-c-expanded-uncertainty-report-result-review-v3"
SUPERVISOR_REVIEW_MARKER = \
    "TEACHER_STAGE_C_EXPANDED_UNCERTAINTY_REPORT_RESULT_V3_REVIEW "

TARGET_STRATUM = "champion_uncertainty"
TARGET_STATES = 219
UNTOUCHED_PLAY_STATES = 1_615
EXPECTED_REMAINING_PLAY_STATES = UNTOUCHED_PLAY_STATES - TARGET_STATES
REPORT_SURFACE_COUNTS = {"play": TARGET_STATES}
REPORT_SHARDS = 8
SUPERVISOR_MAX_WORKERS = 8
SUPERVISOR_HEARTBEAT_SECONDS = 30
SUPERVISOR_HANDLED_SIGNALS = ("SIGHUP", "SIGINT", "SIGTERM")
MIN_PROJECTED_POWER = 0.80
RUNTIME_SCRIPT_PATH = \
    "server/scripts/teacher_stage_c_expanded_uncertainty_report_runtime.py"
SUPERVISOR_SCRIPT_PATH = \
    "server/scripts/teacher_stage_c_expanded_uncertainty_report_supervisor.py"
SUPERSEDED_PACKET_SHA256 = \
    "aa1a94a21abf0351cea13cfcb568c20344ad18a66e6a0d8be6ad5404193008c8"
SUPERSEDED_HOLD_HEADING = (
    "## Claude — 2026-08-11 12:12 EDT — HOLD: "
    "TEACHER_STAGE_C_EXPANDED_PLAY_FRESH_REPORT_CONTROLLER_V1 — "
    "power precondition unmet; environment pin drift. No marker appended.")
SUPERSEDED_RETIREMENT_SCHEMA = \
    "teacher-stage-c-broad-report-admission-retirement-v1"

SOURCE_PATHS = tuple(dict.fromkeys((
    "server/scripts/teacher_stage_c_expanded_uncertainty_report_controller.py",
    RUNTIME_SCRIPT_PATH,
    SUPERVISOR_SCRIPT_PATH,
    "server/scripts/teacher_stage_c_report_runtime.py",
    "server/scripts/teacher_stage_c_report_supervisor.py",
    "server/scripts/teacher_stage_c_expanded_play_report_controller.py",
    *CAP.SOURCE_PATHS,
)))


class ReportControllerRefused(RuntimeError):
    """A parent, scope, power calculation, packet, or authority drifted."""


canonical_json = BASE.canonical_json
sha256_bytes = BASE.sha256_bytes
sha256_file = BASE.sha256_file
self_hash = BASE.self_hash
marker_claim = BASE.marker_claim
is_regular_unlinked = BASE.is_regular_unlinked
load_json = BASE.load_json
_manifest_hash = BASE._manifest_hash
_candidate_world_ceiling = BASE._candidate_world_ceiling


def _git(*args: str, cwd: Path = REPO) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _source_sha256s() -> dict[str, str]:
    result = {}
    for logical in SOURCE_PATHS:
        path = REPO / logical
        if not is_regular_unlinked(path):
            raise ReportControllerRefused(
                f"uncertainty REPORT source unavailable: {logical}")
        result[logical] = sha256_file(path)
    return dict(sorted(result.items()))


def runtime_contract() -> dict:
    value = BASE.runtime_contract()
    value["max_concurrent_label_shards"] = SUPERVISOR_MAX_WORKERS
    value["supervisor_heartbeat_seconds"] = SUPERVISOR_HEARTBEAT_SECONDS
    if value.get("python") != "3.14.6":
        raise ReportControllerRefused(
            "uncertainty REPORT requires reviewed Python 3.14.6")
    return value


def _forbidden_label_material(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            key in {"label_action", "raw_attacker_points",
                    "signed_level_utility", "row_sha256"}
            or _forbidden_label_material(child)
            for key, child in value.items())
    if isinstance(value, list):
        return any(_forbidden_label_material(child) for child in value)
    return False


def _validate_uncertainty_state(state: Mapping[str, object]) -> None:
    candidates = state.get("candidates")
    diagnostic = state.get("selection_diagnostic")
    allowed_sources = {
        "live_production_ballot",
        "v11pair_top_proposal",
        "named_structured_lead_or_follow_mechanism",
        "same_budget_random_diversifier",
    }
    if (state.get("split") != "REPORT"
            or state.get("surface_type") != "play"
            or state.get("stratum") != TARGET_STRATUM
            or not isinstance(candidates, list) or len(candidates) < 2
            or _forbidden_label_material(state)
            or not isinstance(diagnostic, dict)):
        raise ReportControllerRefused(
            "champion-uncertainty state identity drift")
    if any(not isinstance(candidate, dict)
           or not isinstance(candidate.get("cards"), list)
           or not candidate["cards"]
           or not isinstance(candidate.get("sources"), list)
           or not candidate["sources"]
           or any(source not in allowed_sources
                  for source in candidate["sources"])
           for candidate in candidates):
        raise ReportControllerRefused(
            "champion-uncertainty candidate source drift")
    means = diagnostic.get("means")
    best = diagnostic.get("raw_best_index")
    gap = diagnostic.get("paired_gap_vs_candidate0")
    paired_se = diagnostic.get("paired_se_vs_candidate0")
    if (diagnostic.get("schema")
            != "teacher-stage-c-uncertainty-selection-v1"
            or diagnostic.get("selection_only") is not True
            or diagnostic.get("may_train_or_label") is not False
            or diagnostic.get("evaluation_complete") is not True
            or diagnostic.get("eligible") is not True
            or diagnostic.get("worlds") != 30
            or diagnostic.get("attempts") != 30
            or diagnostic.get("production_margin") != 5.0
            or diagnostic.get("margin_window") != 2.5
            or not isinstance(means, list) or len(means) != len(candidates)
            or any(isinstance(value, bool)
                   or not isinstance(value, (int, float))
                   or not math.isfinite(float(value)) for value in means)
            or isinstance(best, bool) or not isinstance(best, int)
            or best <= 0 or best >= len(candidates)
            or not isinstance(gap, (int, float))
            or isinstance(paired_se, bool)
            or not isinstance(paired_se, (int, float))
            or not math.isfinite(float(paired_se)) or float(paired_se) < 0
            or abs(float(gap) - (float(means[best]) - float(means[0]))) > 1e-9
            or abs(float(gap) - 5.0) > 2.5):
        raise ReportControllerRefused(
            "champion-uncertainty capture predicate drift")
    counters = diagnostic.get("sampler_counters")
    expected_counters = {
        "accepted_worlds": 30,
        "failed_worlds": 0,
        "impossible_worlds": 0,
        "rejected_worlds": 0,
        "sample_attempts": 30,
    }
    if (counters != expected_counters
            or diagnostic.get("candidate_worlds")
            != 30 * len(candidates)
            or candidates[0].get("sources")
            != ["live_production_ballot"]):
        raise ReportControllerRefused(
            "champion-uncertainty sampler/candidate contract drift")


def _target_selection(
    *, capture_evidence_repo: Path, state_set_review_record: Path,
    fresh_report_review_record: Path,
) -> dict:
    try:
        capture, original, _verification, _state_review, shards, current = \
            CAP.EXPANSION.validate_evidence(
                evidence_repo=capture_evidence_repo,
                state_set_review_record=state_set_review_record,
                fresh_report_review_record=fresh_report_review_record)
        retained = [state for shard in shards
                    for state in shard["retained_states"]]
        expanded = EXP.select_expanded_states(
            capture_packet=capture, retained_states=retained,
            original_states=original["states"],
            current_fresh_report_states=current)
        fourth = EXP.select_successor_report_states(
            capture_packet=capture, retained_states=retained,
            original_states=original["states"],
            current_fresh_report_states=current)
    except (CAP.EXPANSION.ExpansionControllerRefused,
            EXP.ExpansionError) as exc:
        raise ReportControllerRefused(
            f"uncertainty REPORT selection refused: {exc}") from exc

    populations = [
        [state for state in original["states"]
         if state.get("split") == "REPORT"],
        list(current),
        [state for state in expanded["states"]
         if state.get("split") == "REPORT"],
        list(fourth["states"]),
    ]
    if any(len(population) != EXP.SEALED_REPORT_STATES
           for population in populations):
        raise ReportControllerRefused(
            "uncertainty REPORT spent population drift")
    spent = [state for population in populations for state in population]
    spent_ids = {str(state["state_id"]) for state in spent}
    spent_seeds = {int(state["seed"]) for state in spent}
    if (len(spent_ids) != 4 * EXP.SEALED_REPORT_STATES
            or len(spent_seeds) != 4 * EXP.SEALED_REPORT_STATES):
        raise ReportControllerRefused(
            "uncertainty REPORT spent identity collision")

    untouched = [
        state for state in retained
        if state.get("split") == "REPORT"
        and str(state["state_id"]) not in spent_ids
        and int(state["seed"]) not in spent_seeds
    ]
    untouched_play = [state for state in untouched
                      if state.get("surface_type") == "play"]
    untouched_bury = [state for state in untouched
                      if state.get("surface_type") == "bury"]
    states = [state for state in untouched_play
              if state.get("stratum") == TARGET_STRATUM]
    states.sort(key=lambda state: (
        str(state["cell_id"]), state["selection_priority"],
        state["state_id"]))
    for state in states:
        _validate_uncertainty_state(state)
    state_ids = [str(state["state_id"]) for state in states]
    deal_seeds = [int(state["seed"]) for state in states]
    if (len(untouched_play) != UNTOUCHED_PLAY_STATES
            or len(untouched_bury) != 128
            or len(states) != TARGET_STATES
            or len(set(state_ids)) != TARGET_STATES
            or len(set(deal_seeds)) != TARGET_STATES
            or set(state_ids) & spent_ids
            or set(deal_seeds) & spent_seeds):
        raise ReportControllerRefused(
            "uncertainty REPORT complete-target supply drift")

    raw_cells = [
        cell for cell in capture["schedule"]["quota_cells"]["REPORT"]
        if cell.get("surface_type") == "play"
        and cell.get("stratum") == TARGET_STRATUM
    ]
    cell_manifest = []
    for cell in sorted(raw_cells, key=lambda value: str(value["cell_id"])):
        cell_id = str(cell["cell_id"])
        chosen = [state for state in states if state["cell_id"] == cell_id]
        supply = [state for state in untouched_play
                  if state["cell_id"] == cell_id]
        if len(chosen) != len(supply):
            raise ReportControllerRefused(
                "uncertainty REPORT did not select complete cell supply")
        cell_manifest.append({
            "cell_id": cell_id,
            "base_quota": int(cell["quota"]),
            "eligible_supply_after_four_report_exclusions": len(supply),
            "allocation": len(chosen),
            "spare_after_selection": 0,
            "selected_state_ids_sha256": _manifest_hash([
                str(state["state_id"]) for state in chosen]),
        })

    source_candidates = Counter()
    source_states = Counter()
    for state in states:
        seen = set()
        for candidate in state["candidates"]:
            for source in candidate.get("sources", []):
                source_candidates[str(source)] += 1
                seen.add(str(source))
        source_states.update(seen)
    stratum_supply = Counter(str(state.get("stratum"))
                             for state in untouched_play)
    selection = {
        "schema": "teacher-stage-c-champion-uncertainty-selection-v1",
        "selection_rule": (
            "after recomputing and excluding four complete REPORT "
            "populations, take every retained REPORT/play row whose "
            "capture-authenticated public-information N=30 mc-strong "
            "diagnostic selected a nonzero candidate within 2.5 points of "
            "the production 5-point margin; use no label or outcome"),
        "states": states,
        "states_sha256": _manifest_hash(states),
        "state_ids_sha256": _manifest_hash(sorted(state_ids)),
        "deal_seeds_sha256": _manifest_hash(sorted(deal_seeds)),
        "state_count": len(states),
        "surface_counts": {"play": len(states)},
        "stratum_counts": {TARGET_STRATUM: len(states)},
        "cell_manifest": cell_manifest,
        "cell_manifest_sha256": _manifest_hash(cell_manifest),
        "candidate_source_candidate_counts": dict(sorted(
            source_candidates.items())),
        "candidate_source_state_counts": dict(sorted(source_states.items())),
        "untouched_play_stratum_counts": dict(sorted(stratum_supply.items())),
        "spent_report_populations": 4,
        "spent_report_states": len(spent_ids),
        "spent_report_state_ids_sha256": _manifest_hash(sorted(spent_ids)),
        "spent_report_deal_seeds_sha256": _manifest_hash(sorted(spent_seeds)),
        "prior_fourth_report_selection_sha256": fourth["selection_sha256"],
        "spent_state_overlap": 0,
        "spent_deal_seed_overlap": 0,
        "remaining_report_supply_after_selection": {
            "play": len(untouched_play) - len(states),
            "bury": len(untouched_bury),
        },
        "complete_target_supply_selected": True,
        "selection_uses_labels_or_outcomes": False,
        "labels_or_outcomes_opened": False,
        "report_labels_opened": False,
    }
    selection["selection_sha256"] = _manifest_hash({
        key: value for key, value in selection.items()
        if key != "selection_sha256"
    })
    return selection


def _selection_summary(selection: Mapping[str, object]) -> dict:
    return {key: copy.deepcopy(value) for key, value in selection.items()
            if key != "states"}


def _load_nets(
    capability: Mapping[str, object], evidence_repo: Path,
) -> list[object]:
    nets = []
    manifest = capability.get("checkpoint_manifest")
    if not isinstance(manifest, list) or len(manifest) != 8:
        raise ReportControllerRefused(
            "uncertainty REPORT checkpoint population drift")
    for item in manifest:
        path = (evidence_repo / str(item["checkpoint_path"])).resolve()
        if (not is_regular_unlinked(path)
                or sha256_file(path) != item["checkpoint_sha256"]):
            raise ReportControllerRefused(
                "uncertainty REPORT checkpoint identity drift")
        snapshot = TRAIN.load_snapshot(
            path, expected_contract=item["checkpoint_contract"])
        net = MODEL.StageCRankingOutcomeNet(hidden=TRAIN.HIDDEN)
        net.load_state_dict(snapshot["state_dict"], strict=True)
        nets.append(net)
    return nets


def _normal_power(mean: float, sd: float, n: int) -> float:
    if n <= 0:
        return 0.0
    if sd == 0:
        return 1.0 if mean > 0 else 0.0
    z = mean * math.sqrt(n) / sd - REPORT.REPORT_T_CRITICAL
    return statistics.NormalDist().cdf(z)


def _value_summary(values: Sequence[float], *, report_supply: int) -> dict:
    if len(values) < 2:
        raise ReportControllerRefused(
            "uncertainty REPORT diagnostic stratum underfilled")
    mean = statistics.fmean(values)
    sd = statistics.stdev(values)
    se = sd / math.sqrt(len(values))
    lcb = mean - REPORT.REPORT_T_CRITICAL * se
    break_even = None
    if mean > 0:
        break_even = max(2, math.ceil(
            (REPORT.REPORT_T_CRITICAL * sd / mean) ** 2))
    projected_se = None if report_supply <= 0 else sd / math.sqrt(report_supply)
    projected_lcb = (None if projected_se is None else
                     mean - REPORT.REPORT_T_CRITICAL * projected_se)
    return {
        "n": len(values),
        "mean": mean,
        "sample_sd": sd,
        "standard_error": se,
        "critical": REPORT.REPORT_T_CRITICAL,
        "one_sided_95_lcb": lcb,
        "plugin_break_even_states": break_even,
        "untouched_report_supply": report_supply,
        "projected_report_standard_error": projected_se,
        "projected_report_lcb": projected_lcb,
        "projected_normal_power": _normal_power(mean, sd, report_supply),
    }


def _power_analysis(
    *, capability: Mapping[str, object], dataset: Mapping[str, object],
    evidence_repo: Path, selection: Mapping[str, object],
) -> dict:
    nets = _load_nets(capability, evidence_repo)
    strata = tuple(CAP.EXPECTED_PLAY_SCOPE["stratum"])
    supply = selection["untouched_play_stratum_counts"]
    diagnostics: dict[str, dict[str, dict]] = {}
    for split in ("DESIGN", "CALIB"):
        examples = sorted(
            dataset["examples"][split]["play"],
            key=lambda value: str(value["state_id"]))
        predictions = [TRAIN.predict_examples(net, examples) for net in nets]
        ranks, outcomes = REPORT.average_ensemble(examples, predictions)
        values: dict[str, list[float]] = defaultdict(list)
        triggers = Counter()
        alternatives = Counter()
        for example, rank_values, outcome_values in zip(
                examples, ranks, outcomes, strict=True):
            stratum = str(example["stratum"])
            selected = REPORT._selected_index(
                rank_values, outcome_values, "ranking")
            means = example["target"][
                "ranking_mean_signed_level_utility"]
            values[stratum].append(
                float(means[selected]) - float(means[0]))
            triggers[stratum] += selected != 0
            alternatives[stratum] += int(
                example["target"]["candidate_count"]) >= 2
        split_result = {}
        for stratum in strata:
            summary = _value_summary(
                values[stratum], report_supply=int(supply.get(stratum, 0)))
            summary.update({
                "proposal_triggers": triggers[stratum],
                "proposal_trigger_rate": triggers[stratum] / len(
                    values[stratum]),
                "states_with_candidate_alternative": alternatives[stratum],
            })
            split_result[stratum] = summary
        diagnostics[split] = split_result

    qualified = []
    qualification = {}
    for stratum in strata:
        design = diagnostics["DESIGN"][stratum]
        calib = diagnostics["CALIB"][stratum]
        reasons = {
            "design_lcb_positive": design["one_sided_95_lcb"] > 0,
            "calib_lcb_positive": calib["one_sided_95_lcb"] > 0,
            "design_projected_power_at_least_0_80":
                design["projected_normal_power"] >= MIN_PROJECTED_POWER,
            "calib_projected_power_at_least_0_80":
                calib["projected_normal_power"] >= MIN_PROJECTED_POWER,
            "report_supply_at_least_30":
                int(supply.get(stratum, 0)) >= REPORT.MIN_REPORT_STATES,
            "model_triggers_in_both_splits":
                design["proposal_triggers"] > 0
                and calib["proposal_triggers"] > 0,
        }
        passed = all(reasons.values())
        qualification[stratum] = {"passed": passed, **reasons}
        if passed:
            qualified.append(stratum)
    if qualified != [TARGET_STRATUM]:
        raise ReportControllerRefused(
            f"uncertainty REPORT unique powered scope drift: {qualified}")
    result = {
        "schema": "teacher-stage-c-report-scope-power-analysis-v1",
        "selection_inputs": "DESIGN_AND_CALIB_ONLY",
        "report_labels_or_predictions_opened": False,
        "critical": REPORT.REPORT_T_CRITICAL,
        "minimum_projected_normal_power": MIN_PROJECTED_POWER,
        "power_method": (
            "plug-in normal approximation using frozen split mean and "
            "sample standard deviation at complete untouched stratum supply"),
        "diagnostics": diagnostics,
        "qualification": qualification,
        "qualified_strata": qualified,
        "selected_stratum": TARGET_STRATUM,
        "selection_is_unique_under_predeclared_rule": True,
    }
    result["analysis_sha256"] = _manifest_hash(result)
    return result


def _validate_frozen_power_analysis(value: Mapping[str, object]) -> dict:
    if (value.get("schema")
            != "teacher-stage-c-report-scope-power-analysis-v1"
            or value.get("analysis_sha256")
            != _manifest_hash({key: item for key, item in value.items()
                               if key != "analysis_sha256"})
            or value.get("selection_inputs") != "DESIGN_AND_CALIB_ONLY"
            or value.get("report_labels_or_predictions_opened") is not False
            or value.get("qualified_strata") != [TARGET_STRATUM]
            or value.get("selected_stratum") != TARGET_STRATUM
            or value.get("selection_is_unique_under_predeclared_rule")
            is not True):
        raise ReportControllerRefused(
            "uncertainty REPORT frozen power analysis drift")
    for split in ("DESIGN", "CALIB"):
        summary = value["diagnostics"][split][TARGET_STRATUM]
        if (summary["one_sided_95_lcb"] <= 0
                or summary["projected_normal_power"] < MIN_PROJECTED_POWER
                or summary["untouched_report_supply"] != TARGET_STATES):
            raise ReportControllerRefused(
                "uncertainty REPORT target power qualification drift")
    return copy.deepcopy(dict(value))


def scope_policy_contract(
    states: Sequence[Mapping[str, object]],
) -> dict:
    if len(states) != TARGET_STATES:
        raise ReportControllerRefused(
            "uncertainty REPORT scope state count drift")
    phase = Counter(str(state["phase"]) for state in states)
    role = Counter(str(state["role"]) for state in states)
    position = Counter(str(state["surface"]) for state in states)
    return {
        "schema": "teacher-stage-c-champion-uncertainty-protected-scope-v3",
        "scope": "champion_uncertainty_only",
        "surface": "play",
        "report_states": TARGET_STATES,
        "candidate0_source": "live_production_ballot",
        "candidate_source_contract": {
            "incumbent": "live_production_ballot",
            "proposal_sources": [
                "v11pair_top_proposal",
                "named_structured_lead_or_follow_mechanism",
                "same_budget_random_diversifier",
            ],
            "stage_c_model_was_not_a_capture_candidate_source": True,
        },
        "report_evaluation_baseline_index": 0,
        "inside_scope_model_head": "ranking",
        "capture_predicate": {
            "information": "public_information_only",
            "evaluator": "mc-strong",
            "common_worlds_across_candidate_union": 30,
            "attempt_factor": 10,
            "raw_best_index_nonzero": True,
            "production_margin_points": 5.0,
            "absolute_gap_to_margin_at_most_points": 2.5,
        },
        "downstream_composition_requirements": {
            "recompute_predicate_online_from_public_information": True,
            "reproduce_reviewed_candidate_source_contract": True,
            "scope_trigger_precedes_stage_c_model_proposal": True,
            "stage_c_model_ranks_the_reviewed_candidate_union": True,
            "stored_capture_diagnostic_may_drive_live_action": False,
            "model_direct_play_authorized": False,
            "outside_scope_policy": "unchanged_mc_s0_report_lcb",
            "preserve_complete_live_report_lcb_candidate_ballot": True,
            "insert_at_most_one_model_proposal_into_live_report_lcb": True,
            "unchanged_live_policy_is_literal_fallback": True,
            "same_work_null_required": True,
            "fresh_whole_game_screen_required": True,
        },
        "phase_counts": dict(sorted(phase.items())),
        "role_counts": dict(sorted(role.items())),
        "position_counts": dict(sorted(position.items())),
        "selection_uses_report_labels_or_outcomes": False,
    }


def build_report_schedule(
    states: Sequence[Mapping[str, object]], *, surface: str,
) -> dict:
    if surface != "play":
        raise ReportControllerRefused(
            "uncertainty REPORT surface drift")
    selected = sorted(states, key=lambda state: str(state["state_id"]))
    if (len(selected) != TARGET_STATES
            or len({str(state["state_id"]) for state in selected})
            != TARGET_STATES
            or any(state.get("surface_type") != "play"
                   or state.get("stratum") != TARGET_STRATUM
                   for state in selected)):
        raise ReportControllerRefused(
            "uncertainty REPORT schedule population drift")
    shards = []
    for index in range(REPORT_SHARDS):
        population = selected[index::REPORT_SHARDS]
        shards.append({
            "index": index,
            "state_count": len(population),
            "state_ids_sha256": _manifest_hash([
                str(state["state_id"]) for state in population]),
            "candidate_world_ceiling": sum(
                _candidate_world_ceiling(state) for state in population),
            "result": (
                f"server/runs/logs/{RUN_ID}/labels/shard-{index:02d}.json"),
        })
    value = {
        "schema": "teacher-stage-c-expanded-uncertainty-report-schedule-v3",
        "surface": "play",
        "stratum": TARGET_STRATUM,
        "states": len(selected),
        "selected_surface_state_ids_sha256": _manifest_hash([
            str(state["state_id"]) for state in selected]),
        "partition_rule": (
            "sort target states by state_id, assign position modulo eight"),
        "shard_count": REPORT_SHARDS,
        "shards": shards,
        "candidate_world_ceiling": sum(
            int(shard["candidate_world_ceiling"]) for shard in shards),
    }
    value["schedule_sha256"] = _manifest_hash(value)
    return value


def _commands(schedule: Mapping[str, object]) -> dict:
    common = [
        "--expected-git", "{git}",
        "--controller-packet", PACKET_PATH,
        "--expected-controller-packet-sha256", "{packet_sha256}",
        "--controller-review-record", "{controller_review_record}",
        "--fresh-report-review-record", "{fresh_report_review_record}",
        "--state-set-review-record", "{state_set_review_record}",
        "--report-receipt", f"server/runs/logs/{RUN_ID}/report-receipt.json",
        "--expected-report-receipt-sha256", "{receipt_sha256}",
    ]
    return {
        "admit": [
            "{python}", RUNTIME_SCRIPT_PATH, "admit",
            "--expected-git", "{git}",
            "--controller-packet", PACKET_PATH,
            "--expected-controller-packet-sha256", "{packet_sha256}",
            "--controller-review-record", "{controller_review_record}",
            "--fresh-report-review-record", "{fresh_report_review_record}",
            "--state-set-review-record", "{state_set_review_record}",
            "--out", f"server/runs/logs/{RUN_ID}/report-receipt.json",
        ],
        "run_shards": [[
            "{python}", RUNTIME_SCRIPT_PATH, "run-shard", *common,
            "--shard-index", str(shard["index"]),
            "--progress-every", "1", "--out", shard["result"],
        ] for shard in schedule["shards"]],
        "evaluate": [
            "{python}", RUNTIME_SCRIPT_PATH, "evaluate", *common,
            "--label-shards", *[
                shard["result"] for shard in schedule["shards"]],
            "--out", f"server/runs/logs/{RUN_ID}/report-result.json",
        ],
        "supervise": [
            "{python}", SUPERVISOR_SCRIPT_PATH, "launch",
            "--expected-git", "{git}",
            "--controller-packet", PACKET_PATH,
            "--expected-controller-packet-sha256", "{packet_sha256}",
            "--controller-review-record", "{controller_review_record}",
            "--fresh-report-review-record", "{fresh_report_review_record}",
            "--state-set-review-record", "{state_set_review_record}",
            "--report-receipt", f"server/runs/logs/{RUN_ID}/report-receipt.json",
            "--expected-report-receipt-sha256", "{receipt_sha256}",
            "--heartbeat-seconds", str(SUPERVISOR_HEARTBEAT_SECONDS),
        ],
    }


def _inspect_superseded_controller(path: Path) -> tuple[dict, Path]:
    if (not is_regular_unlinked(path)
            or sha256_file(path) != SUPERSEDED_PACKET_SHA256):
        raise ReportControllerRefused(
            "superseded broad REPORT packet identity drift")
    packet = load_json(path)
    if (packet.get("schema") != BASE.SCHEMA
            or packet.get("run_id") != BASE.RUN_ID
            or packet.get("packet_sha256")
            != self_hash(packet, "packet_sha256")
            or packet.get("authority", {}).get(
                "one_report_execution_authorized") is not False
            or packet.get("authority", {}).get(
                "report_utility_opened") is not False):
        raise ReportControllerRefused(
            "superseded broad REPORT authority drift")
    root = path.parents[4]
    forbidden = [
        root / f"server/runs/logs/{BASE.RUN_ID}/report-receipt.json",
        root / f"server/runs/logs/{BASE.RUN_ID}/report-result.json",
        root / f"server/runs/locks/{BASE.RUN_ID}.report-open.consumed.json",
    ]
    if any(os.path.lexists(item) for item in forbidden):
        raise ReportControllerRefused(
            "superseded broad REPORT was admitted or opened")
    slot = root / f"server/runs/locks/{BASE.RUN_ID}.consumed.json"
    return packet, slot


def _hold_record_contract(path: Path) -> dict:
    if not is_regular_unlinked(path):
        raise ReportControllerRefused(
            "superseded broad REPORT HOLD record unavailable")
    try:
        text = path.read_text()
    except (OSError, UnicodeError) as exc:
        raise ReportControllerRefused(
            "superseded broad REPORT HOLD record unreadable") from exc
    if text.count(SUPERSEDED_HOLD_HEADING) != 1:
        raise ReportControllerRefused(
            "superseded broad REPORT HOLD section identity drift")
    start = text.index(SUPERSEDED_HOLD_HEADING)
    end_candidates = [
        value for value in (
            text.find("\n---\n", start),
            text.find("\n## ", start + len(SUPERSEDED_HOLD_HEADING)),
        ) if value >= 0
    ]
    end = min(end_candidates) if end_candidates else len(text)
    section = text[start:end].rstrip() + "\n"
    expected_marker = BASE.REVIEW_MARKER
    raw_occurrences = sum(
        line.startswith(expected_marker) for line in text.splitlines())
    if ("I am not appending the requested PASS marker." not in section
            or "no output or slot exists" not in section
            or raw_occurrences != 0):
        raise ReportControllerRefused(
            "superseded broad REPORT HOLD authority drift")
    return {
        "absolute_path": str(path.resolve()),
        "file_sha256_at_retirement": sha256_file(path),
        "hold_heading": SUPERSEDED_HOLD_HEADING,
        "hold_section_sha256": sha256_bytes(section.encode()),
        "expected_pass_marker": expected_marker.strip(),
        "raw_pass_marker_occurrences_at_retirement": 0,
    }


def _retirement_payload(
    packet: Mapping[str, object], hold: Mapping[str, object],
) -> dict:
    value = {
        "schema": SUPERSEDED_RETIREMENT_SCHEMA,
        "retired_run_id": BASE.RUN_ID,
        "retired_controller_packet_sha256": SUPERSEDED_PACKET_SHA256,
        "retired_controller_packet_internal_sha256": packet["packet_sha256"],
        "external_review_verdict": "HOLD_BEFORE_EVIDENCE",
        "hold_record": copy.deepcopy(dict(hold)),
        "population_overlap_with_replacement_states": 94,
        "blocks_old_admit_before_packet_or_review_open": True,
        "old_report_open_slot_consumed": False,
        "teacher_labels_computed": 0,
        "model_predictions_computed": 0,
        "report_utility_opened": False,
        "retry_or_reactivation_authorized": False,
        "replacement_report_execution_authorized": False,
        "composition_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    value["retirement_sha256"] = self_hash(value, "retirement_sha256")
    return value


def retire_superseded_controller(
    *, packet_path: Path, hold_record: Path,
) -> dict:
    packet, slot = _inspect_superseded_controller(packet_path)
    hold = _hold_record_contract(hold_record)
    if os.path.lexists(slot):
        raise ReportControllerRefused(
            "superseded broad REPORT admission slot already exists")
    payload = _retirement_payload(packet, hold)
    publish_exclusive(slot, payload)
    return {
        "status": "SUPERSEDED_ADMISSION_DURABLY_RETIRED_NO_REPORT_OPEN",
        "admission_slot": str(slot),
        "admission_slot_sha256": sha256_file(slot),
        "retirement_internal_sha256": payload["retirement_sha256"],
        "hold_section_sha256": hold["hold_section_sha256"],
    }


def _superseded_controller(path: Path, hold_record: Path) -> dict:
    packet, slot = _inspect_superseded_controller(path)
    current_hold = _hold_record_contract(hold_record)
    if not is_regular_unlinked(slot):
        raise ReportControllerRefused(
            "superseded broad REPORT admission is not durably retired")
    retirement = load_json(slot)
    frozen_hold = retirement.get("hold_record")
    if (retirement.get("schema") != SUPERSEDED_RETIREMENT_SCHEMA
            or retirement.get("retired_run_id") != BASE.RUN_ID
            or retirement.get("retired_controller_packet_sha256")
            != SUPERSEDED_PACKET_SHA256
            or retirement.get("retired_controller_packet_internal_sha256")
            != packet["packet_sha256"]
            or not isinstance(frozen_hold, dict)
            or frozen_hold.get("absolute_path")
            != str(hold_record.resolve())
            or frozen_hold.get("hold_section_sha256")
            != current_hold["hold_section_sha256"]
            or frozen_hold.get("raw_pass_marker_occurrences_at_retirement")
            != 0
            or retirement.get("blocks_old_admit_before_packet_or_review_open")
            is not True
            or retirement.get("retry_or_reactivation_authorized") is not False
            or retirement.get("report_utility_opened") is not False
            or retirement.get("retirement_sha256")
            != self_hash(retirement, "retirement_sha256")):
        raise ReportControllerRefused(
            "superseded broad REPORT retirement tombstone drift")
    return {
        "schema": "teacher-stage-c-broad-report-supersession-v1",
        "absolute_path": str(path.resolve()),
        "external_sha256": SUPERSEDED_PACKET_SHA256,
        "internal_sha256": packet["packet_sha256"],
        "run_id": packet["run_id"],
        "frozen_python": packet["runtime_contract"]["python"],
        "external_review_verdict": "HOLD_BEFORE_EVIDENCE",
        "hold_record": frozen_hold,
        "admission_retirement_slot": str(slot),
        "admission_retirement_slot_sha256": sha256_file(slot),
        "admission_retirement_internal_sha256":
            retirement["retirement_sha256"],
        "admission_slot_durably_consumed_as_retirement": True,
        "report_open_slot_absent_at_supersession": True,
        "report_receipt_absent_at_supersession": True,
        "report_result_absent_at_supersession": True,
        "report_rows_opened": 0,
        "report_reuse_authorized": False,
    }


def _build_inputs(
    *, capability_packet_path: Path,
    expected_capability_packet_sha256: str,
    capability_review_record: Path, evidence_repo: Path,
    training_result_review_record: Path, capture_evidence_repo: Path,
    state_set_review_record: Path, fresh_report_review_record: Path,
    bury_result_review_record: Path, recompute_capability: bool = True,
) -> tuple[dict, dict, dict, dict, list[dict]]:
    try:
        capability, training_packet, dataset, _broad, _broad_states = \
            BASE._build_inputs(
                capability_packet_path=capability_packet_path,
                expected_capability_packet_sha256=
                    expected_capability_packet_sha256,
                capability_review_record=capability_review_record,
                evidence_repo=evidence_repo,
                training_result_review_record=training_result_review_record,
                capture_evidence_repo=capture_evidence_repo,
                state_set_review_record=state_set_review_record,
                fresh_report_review_record=fresh_report_review_record,
                bury_result_review_record=bury_result_review_record,
                recompute_capability=recompute_capability)
        selection = _target_selection(
            capture_evidence_repo=capture_evidence_repo,
            state_set_review_record=state_set_review_record,
            fresh_report_review_record=fresh_report_review_record)
    except (BASE.ReportControllerRefused,
            CAP.ExpandedPlayCapabilityRefused) as exc:
        raise ReportControllerRefused(str(exc)) from exc
    return (capability, training_packet, dataset, selection,
            list(selection["states"]))


def build_packet(
    *, git: str, capability_packet_path: Path,
    expected_capability_packet_sha256: str,
    capability_review_record: Path, evidence_repo: Path,
    training_result_review_record: Path, capture_evidence_repo: Path,
    state_set_review_record: Path, fresh_report_review_record: Path,
    bury_result_review_record: Path,
    superseded_controller_packet: Path | None = None,
    superseded_hold_record: Path | None = None,
    frozen_supersession: Mapping[str, object] | None = None,
    frozen_power_analysis: Mapping[str, object] | None = None,
    _validated_inputs: tuple[dict, dict, dict, dict, list[dict]] | None = None,
) -> dict:
    values = _validated_inputs or _build_inputs(
        capability_packet_path=capability_packet_path,
        expected_capability_packet_sha256=
            expected_capability_packet_sha256,
        capability_review_record=capability_review_record,
        evidence_repo=evidence_repo,
        training_result_review_record=training_result_review_record,
        capture_evidence_repo=capture_evidence_repo,
        state_set_review_record=state_set_review_record,
        fresh_report_review_record=fresh_report_review_record,
        bury_result_review_record=bury_result_review_record)
    capability, training_packet, dataset, selection, states = values
    if frozen_supersession is None:
        if (superseded_controller_packet is None
                or superseded_hold_record is None):
            raise ReportControllerRefused(
                "superseded broad controller packet/HOLD are required")
        supersession = _superseded_controller(
            superseded_controller_packet, superseded_hold_record)
    else:
        supersession = copy.deepcopy(dict(frozen_supersession))
        try:
            rebuilt_supersession = _superseded_controller(
                Path(str(supersession["absolute_path"])).resolve(),
                Path(str(supersession["hold_record"][
                    "absolute_path"])).resolve())
        except (KeyError, TypeError, ValueError) as exc:
            raise ReportControllerRefused(
                "frozen broad REPORT supersession identity drift") from exc
        if rebuilt_supersession != supersession:
            raise ReportControllerRefused(
                "frozen broad REPORT supersession recomputation drift")
    if (supersession.get("schema")
            != "teacher-stage-c-broad-report-supersession-v1"
            or supersession.get("external_sha256")
            != SUPERSEDED_PACKET_SHA256
            or supersession.get("external_review_verdict")
            != "HOLD_BEFORE_EVIDENCE"
            or supersession.get(
                "admission_slot_durably_consumed_as_retirement") is not True
            or supersession.get("report_rows_opened") != 0):
        raise ReportControllerRefused(
            "broad REPORT supersession contract drift")

    if frozen_power_analysis is None:
        power = _power_analysis(
            capability=capability, dataset=dataset,
            evidence_repo=evidence_repo, selection=selection)
    else:
        power = _validate_frozen_power_analysis(frozen_power_analysis)
    schedule = build_report_schedule(states, surface="play")
    scope = scope_policy_contract(states)
    selected = capability["capability"]
    prior = TRAIN.state_balanced_prior(
        dataset["examples"]["DESIGN"]["play"])
    summary = _selection_summary(selection)
    if (summary["remaining_report_supply_after_selection"]
            != {"play": EXPECTED_REMAINING_PLAY_STATES, "bury": 128}):
        raise ReportControllerRefused(
            "uncertainty REPORT remaining supply drift")
    value = {
        "schema": SCHEMA,
        "packet_id": PACKET_ID,
        "run_id": RUN_ID,
        "producer": {
            "git": git,
            "tree_dirty": False,
            "sources": _source_sha256s(),
        },
        "parents": {
            "capability_packet": {
                "absolute_path": str(capability_packet_path.resolve()),
                "external_sha256": expected_capability_packet_sha256,
                "internal_sha256": capability["packet_sha256"],
                "review_record_absolute_path":
                    str(capability_review_record.resolve()),
                "review_record_sha256": sha256_file(
                    capability_review_record),
                "review_claim_sha256": _manifest_hash(marker_claim(
                    capability_review_record, CAP.REVIEW_MARKER)),
            },
            "training_evidence": {
                "absolute_path": str(evidence_repo.resolve()),
                "training_result_review_record_absolute_path":
                    str(training_result_review_record.resolve()),
                "training_result_review_record_sha256":
                    sha256_file(training_result_review_record),
            },
            "training_packet": {
                "logical_path": BASE.BASE.TRAIN_CTRL.PACKET_PATH,
                "external_sha256": BASE.BASE.TRAINING_PACKET_SHA256,
                "internal_sha256": training_packet["packet_sha256"],
            },
            "model_dataset": {
                "logical_path": BASE.BASE.TRAIN_CTRL.DATASET_PATH,
                "external_sha256": BASE.BASE.MODEL_DATASET_SHA256,
                "internal_sha256": dataset["dataset_sha256"],
            },
            "capture_evidence": {
                "absolute_path": str(capture_evidence_repo.resolve()),
                "state_set_review_record_absolute_path":
                    str(state_set_review_record.resolve()),
                "state_set_review_record_sha256":
                    sha256_file(state_set_review_record),
                "fresh_report_review_record_absolute_path":
                    str(fresh_report_review_record.resolve()),
                "fresh_report_review_record_sha256":
                    sha256_file(fresh_report_review_record),
                "bury_result_review_record_absolute_path":
                    str(bury_result_review_record.resolve()),
                "bury_result_review_record_sha256":
                    sha256_file(bury_result_review_record),
            },
            "fresh_report_selection": {
                "sealed_selection_sha256": summary["selection_sha256"],
                "fresh_report_state_ids_sha256":
                    summary["state_ids_sha256"],
                "fresh_report_state_material_sha256":
                    summary["states_sha256"],
                "fresh_report_states": summary["state_count"],
                "spent_report_populations":
                    summary["spent_report_populations"],
                "spent_report_state_ids_sha256":
                    summary["spent_report_state_ids_sha256"],
                "spent_report_deal_seeds_sha256":
                    summary["spent_report_deal_seeds_sha256"],
                "spent_state_overlap": summary["spent_state_overlap"],
                "spent_deal_seed_overlap":
                    summary["spent_deal_seed_overlap"],
                "remaining_report_supply_after_selection":
                    summary["remaining_report_supply_after_selection"],
                "state_material_published": False,
            },
            "superseded_broad_report_controller": supersession,
        },
        "target_selection": summary,
        "power_analysis": power,
        "selected_capability": selected,
        "play_scope_contract": {
            "scope": scope["scope"],
            "play_states": TARGET_STATES,
            "bury_states": 0,
            "phase_counts": scope["phase_counts"],
            "role_counts": scope["role_counts"],
            "position_counts": scope["position_counts"],
            "stratum_counts": {TARGET_STRATUM: TARGET_STATES},
            "selection_uses_labels_or_outcomes": False,
        },
        "scope_policy_contract": scope,
        "protected_policy": None,
        "checkpoint_manifest": capability["checkpoint_manifest"],
        "design_prior_distribution": prior,
        "runtime_contract": runtime_contract(),
        "report_schedule": schedule,
        "report_contract": {
            "surface": "play",
            "head": "ranking",
            "states": TARGET_STATES,
            "bury_states": 0,
            "stratum": TARGET_STRATUM,
            "candidate_world_ceiling": schedule["candidate_world_ceiling"],
            "v11_checkpoint_loaded": False,
            "v11_candidates_reconstructed": False,
            "captured_candidate_tensor_authenticated": True,
            "complete_untouched_target_supply": True,
            "single_report_look": True,
            "prior_report_populations_spent": 4,
            "prior_report_state_overlap": 0,
            "prior_report_deal_seed_overlap": 0,
            "protected_policy": None,
            "scope_policy_contract": scope,
            "model_score_tie_epsilon": REPORT.MODEL_SCORE_TIE_EPSILON,
            "rank_ensemble":
                "mean within-ballot softmax probability across eight seeds",
            "tie_break": "lowest candidate index within epsilon",
            "durable_report_open_admission_slot":
                f"server/runs/locks/{RUN_ID}.report-open.consumed.json",
            "retry_after_report_open_or_failure_authorized": False,
            "report_cannot_change_surface_head_epoch_or_seed_population":
                True,
        },
        "commands": _commands(schedule),
        "authority": {
            "fresh_report_capture_shards_revalidated": 8,
            "fresh_report_state_material_published": False,
            "teacher_labels_computed": 0,
            "model_predictions_computed": 0,
            "report_utility_opened": False,
            "one_report_execution_authorized": False,
            "composition_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
            "production_deployment": False,
        },
    }
    value["packet_sha256"] = self_hash(value, "packet_sha256")
    return value


def expected_review_claim(
    packet: Mapping[str, object], packet_external_sha256: str,
) -> dict:
    sources = packet["producer"]["sources"]
    contract = packet["report_contract"]
    design = packet["power_analysis"]["diagnostics"][
        "DESIGN"][TARGET_STRATUM]
    calib = packet["power_analysis"]["diagnostics"][
        "CALIB"][TARGET_STRATUM]
    return {
        "schema": REVIEW_SCHEMA,
        "git": packet["producer"]["git"],
        "packet_sha256": packet_external_sha256,
        "packet_internal_sha256": packet["packet_sha256"],
        "controller_script_sha256": sources[
            "server/scripts/teacher_stage_c_expanded_uncertainty_report_controller.py"],
        "runtime_wrapper_sha256": sources[RUNTIME_SCRIPT_PATH],
        "supervisor_wrapper_sha256": sources[SUPERVISOR_SCRIPT_PATH],
        "shared_runtime_sha256": sources[
            "server/scripts/teacher_stage_c_report_runtime.py"],
        "shared_supervisor_sha256": sources[
            "server/scripts/teacher_stage_c_report_supervisor.py"],
        "capability_packet_sha256": packet["parents"][
            "capability_packet"]["external_sha256"],
        "capability_review_claim_sha256": packet["parents"][
            "capability_packet"]["review_claim_sha256"],
        "superseded_broad_controller_sha256": packet["parents"][
            "superseded_broad_report_controller"]["external_sha256"],
        "superseded_broad_report_rows_opened": 0,
        "superseded_broad_hold_section_sha256": packet["parents"][
            "superseded_broad_report_controller"]["hold_record"][
                "hold_section_sha256"],
        "superseded_broad_admission_retirement_sha256": packet["parents"][
            "superseded_broad_report_controller"][
                "admission_retirement_slot_sha256"],
        "selected_capability": packet["selected_capability"],
        "scope_policy_contract": packet["scope_policy_contract"],
        "power_analysis_sha256": packet["power_analysis"]["analysis_sha256"],
        "design_target_n": design["n"],
        "design_target_mean": design["mean"],
        "design_target_lcb": design["one_sided_95_lcb"],
        "design_projected_report_power":
            design["projected_normal_power"],
        "calib_target_n": calib["n"],
        "calib_target_mean": calib["mean"],
        "calib_target_lcb": calib["one_sided_95_lcb"],
        "calib_projected_report_power": calib["projected_normal_power"],
        "unique_power_qualified_stratum": TARGET_STRATUM,
        "checkpoint_manifest_sha256": _manifest_hash(
            packet["checkpoint_manifest"]),
        "ensemble_models": len(packet["checkpoint_manifest"]),
        "fresh_report_selection_sha256": packet["parents"][
            "fresh_report_selection"]["sealed_selection_sha256"],
        "report_schedule_sha256": packet["report_schedule"][
            "schedule_sha256"],
        "report_label_shards": REPORT_SHARDS,
        "report_surface_states": contract["states"],
        "report_candidate_world_ceiling": packet["report_schedule"][
            "candidate_world_ceiling"],
        "complete_untouched_target_supply": True,
        "execution_host": packet["runtime_contract"]["host"],
        "python": packet["runtime_contract"]["python"],
        "torch": packet["runtime_contract"]["torch"],
        "numpy": packet["runtime_contract"]["numpy"],
        "teacher_labels_computed_before_review": 0,
        "model_predictions_computed_before_review": 0,
        "report_utility_opened_before_review": False,
        "fresh_report_state_material_published": False,
        "prior_report_populations_spent": 4,
        "prior_report_state_overlap": 0,
        "prior_report_deal_seed_overlap": 0,
        "single_report_look": True,
        "report_open_admission_slot": contract[
            "durable_report_open_admission_slot"],
        "retry_after_report_open_or_failure_authorized": False,
        "independent_review": True,
        "one_report_execution_authorized": True,
        "composition_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }


def publish_exclusive(path: Path, payload: Mapping[str, object]) -> None:
    BASE.publish_exclusive(path, payload)


def _common_from_packet(packet: Mapping[str, object]) -> dict:
    capability = packet["parents"]["capability_packet"]
    evidence = packet["parents"]["training_evidence"]
    capture = packet["parents"]["capture_evidence"]
    return {
        "capability_packet_path": Path(
            str(capability["absolute_path"])).resolve(),
        "expected_capability_packet_sha256":
            capability["external_sha256"],
        "capability_review_record": Path(
            str(capability["review_record_absolute_path"])).resolve(),
        "evidence_repo": Path(str(evidence["absolute_path"])).resolve(),
        "training_result_review_record": Path(str(
            evidence["training_result_review_record_absolute_path"])).resolve(),
        "capture_evidence_repo": Path(
            str(capture["absolute_path"])).resolve(),
        "state_set_review_record": Path(str(
            capture["state_set_review_record_absolute_path"])).resolve(),
        "fresh_report_review_record": Path(str(
            capture["fresh_report_review_record_absolute_path"])).resolve(),
        "bury_result_review_record": Path(str(
            capture["bury_result_review_record_absolute_path"])).resolve(),
    }


def validate_runtime_packet(
    *, path: Path, expected_sha256: str,
    fresh_report_review_record: Path, state_set_review_record: Path,
) -> tuple[dict, dict, dict, dict, list[dict]]:
    if (path.resolve() != (REPO / PACKET_PATH).resolve()
            or not is_regular_unlinked(path)
            or sha256_file(path) != expected_sha256):
        raise ReportControllerRefused(
            "uncertainty REPORT runtime packet path/SHA drift")
    frozen = load_json(path)
    common = _common_from_packet(frozen)
    if (fresh_report_review_record.resolve()
            != common["fresh_report_review_record"]
            or state_set_review_record.resolve()
            != common["state_set_review_record"]):
        raise ReportControllerRefused(
            "uncertainty REPORT runtime review-record path drift")
    values = _build_inputs(**common, recompute_capability=False)
    rebuilt = build_packet(
        git=_git("rev-parse", "HEAD"), **common,
        frozen_supersession=frozen["parents"][
            "superseded_broad_report_controller"],
        frozen_power_analysis=frozen["power_analysis"],
        _validated_inputs=values)
    if (frozen != rebuilt
            or frozen.get("packet_sha256")
            != self_hash(frozen, "packet_sha256")):
        raise ReportControllerRefused(
            "uncertainty REPORT runtime packet recomputation drift")
    return frozen, values[2], values[1], values[3], values[4]


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument(
        "command", choices=("retire-superseded", "freeze", "verify"))
    root.add_argument("--expected-git", required=True)
    root.add_argument("--capability-packet", required=True)
    root.add_argument("--expected-capability-packet-sha256", required=True)
    root.add_argument("--capability-review-record", required=True)
    root.add_argument("--evidence-repo", required=True)
    root.add_argument("--training-result-review-record", required=True)
    root.add_argument("--capture-evidence-repo", required=True)
    root.add_argument("--state-set-review-record", required=True)
    root.add_argument("--fresh-report-review-record", required=True)
    root.add_argument("--bury-result-review-record", required=True)
    root.add_argument("--superseded-controller-packet", required=True)
    root.add_argument("--superseded-hold-record", required=True)
    root.add_argument("--out", default=PACKET_PATH)
    root.add_argument("--expected-packet-sha256")
    return root


def main() -> int:
    args = parser().parse_args()
    if (_git("rev-parse", "HEAD") != args.expected_git
            or _git("status", "--porcelain", "--untracked-files=all")):
        raise ReportControllerRefused(
            "uncertainty REPORT producer Git/cleanliness drift")
    if args.command == "retire-superseded":
        result = retire_superseded_controller(
            packet_path=Path(args.superseded_controller_packet).resolve(),
            hold_record=Path(args.superseded_hold_record).resolve())
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    common = {
        "git": args.expected_git,
        "capability_packet_path": Path(args.capability_packet).resolve(),
        "expected_capability_packet_sha256":
            args.expected_capability_packet_sha256,
        "capability_review_record": Path(
            args.capability_review_record).resolve(),
        "evidence_repo": Path(args.evidence_repo).resolve(),
        "training_result_review_record": Path(
            args.training_result_review_record).resolve(),
        "capture_evidence_repo": Path(
            args.capture_evidence_repo).resolve(),
        "state_set_review_record": Path(
            args.state_set_review_record).resolve(),
        "fresh_report_review_record": Path(
            args.fresh_report_review_record).resolve(),
        "bury_result_review_record": Path(
            args.bury_result_review_record).resolve(),
        "superseded_controller_packet": Path(
            args.superseded_controller_packet).resolve(),
        "superseded_hold_record": Path(
            args.superseded_hold_record).resolve(),
    }
    packet = build_packet(**common)
    out = Path(args.out).resolve()
    if out != (REPO / PACKET_PATH).resolve():
        raise ReportControllerRefused(
            "uncertainty REPORT output path drift")
    if args.command == "freeze":
        publish_exclusive(out, packet)
        external = sha256_file(out)
    else:
        if (not args.expected_packet_sha256
                or not is_regular_unlinked(out)
                or sha256_file(out) != args.expected_packet_sha256
                or load_json(out) != packet):
            raise ReportControllerRefused(
                "uncertainty REPORT frozen packet recomputation drift")
        external = args.expected_packet_sha256
    print(json.dumps({
        "status": "VERIFIED_NO_REPORT_OPEN"
        if args.command == "verify" else "FROZEN_NO_REPORT_OPEN",
        "packet_sha256": external,
        "packet_internal_sha256": packet["packet_sha256"],
        "expected_review_claim": expected_review_claim(packet, external),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ReportControllerRefused, BASE.ReportControllerRefused,
            CAP.ExpandedPlayCapabilityRefused) as exc:
        print(f"REFUSING: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
