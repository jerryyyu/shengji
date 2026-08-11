#!/usr/bin/env python3
"""Freeze one reviewed broad normal-play Stage-C REPORT examination.

This controller consumes only an independently reviewed expanded-play
capability packet.  It rebuilds the fifth 480-state play population, schedules
exact finite Teacher work, and publishes a score-free execution packet.  It
does not label, score, compose, launch games, claim strength, promote, or
deploy; those authorities remain behind separate review and terminal gates.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SCRIPT.parents[2]
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import teacher_stage_c_expanded_play_capability as CAP  # noqa: E402
import teacher_stage_c_expanded_report_controller as BASE  # noqa: E402
from shengji.rl import stage_c_report as REPORT  # noqa: E402
from shengji.rl import stage_c_training as TRAIN  # noqa: E402


SCHEMA = "teacher-stage-c-expanded-play-fresh-report-controller-v1"
PACKET_ID = "teacher-v3-hard-tail-stage-c-expanded-play-report-controller-v1"
RUN_ID = "teacher-v3-hard-tail-stage-c-expanded-play-fresh-report-v1"
CONTROLLER_RUN_ID = \
    "teacher-v3-hard-tail-stage-c-expanded-play-report-controller-v1"
PACKET_PATH = f"server/runs/logs/{CONTROLLER_RUN_ID}/controller_packet.json"
REVIEW_SCHEMA = \
    "teacher-stage-c-expanded-play-fresh-report-controller-review-v1"
REVIEW_MARKER = \
    "TEACHER_STAGE_C_EXPANDED_PLAY_FRESH_REPORT_CONTROLLER_V1_REVIEW "

RUNTIME_RECEIPT_SCHEMA = \
    "teacher-stage-c-expanded-play-fresh-report-receipt-v1"
RUNTIME_ADMISSION_SCHEMA = \
    "teacher-stage-c-expanded-play-fresh-report-admission-v1"
RUNTIME_REPORT_OPEN_ADMISSION_SCHEMA = \
    "teacher-stage-c-expanded-play-fresh-report-open-admission-v1"
RUNTIME_SHARD_ADMISSION_SCHEMA = \
    "teacher-stage-c-expanded-play-fresh-report-shard-admission-v1"
RUNTIME_SHARD_SCHEMA = \
    "teacher-stage-c-expanded-play-fresh-report-label-shard-v1"
RUNTIME_RESULT_SCHEMA = \
    "teacher-stage-c-expanded-play-fresh-report-result-v1"
SUPERVISOR_SCHEMA = \
    "teacher-stage-c-expanded-play-fresh-report-supervisor-v1"
SUPERVISOR_EXIT_SCHEMA = \
    "teacher-stage-c-expanded-play-fresh-report-supervisor-exit-v1"
SUPERVISOR_FINAL_SCHEMA = \
    "teacher-stage-c-expanded-play-fresh-report-supervisor-final-v1"
SUPERVISOR_REVIEW_SCHEMA = \
    "teacher-stage-c-expanded-play-fresh-report-result-review-v1"
SUPERVISOR_REVIEW_MARKER = \
    "TEACHER_STAGE_C_EXPANDED_PLAY_FRESH_REPORT_RESULT_V1_REVIEW "

REPORT_SURFACE_COUNTS = {"play": 480}
REPORT_SHARDS = 8
SUPERVISOR_MAX_WORKERS = 8
SUPERVISOR_HEARTBEAT_SECONDS = 30
SUPERVISOR_HANDLED_SIGNALS = ("SIGHUP", "SIGINT", "SIGTERM")
RUNTIME_SCRIPT_PATH = \
    "server/scripts/teacher_stage_c_expanded_play_report_runtime.py"
SUPERVISOR_SCRIPT_PATH = \
    "server/scripts/teacher_stage_c_expanded_play_report_supervisor.py"

SOURCE_PATHS = tuple(dict.fromkeys((
    "server/scripts/teacher_stage_c_expanded_play_report_controller.py",
    RUNTIME_SCRIPT_PATH,
    SUPERVISOR_SCRIPT_PATH,
    "server/scripts/teacher_stage_c_report_runtime.py",
    "server/scripts/teacher_stage_c_report_supervisor.py",
    *CAP.SOURCE_PATHS,
)))


class ReportControllerRefused(RuntimeError):
    """A capability, population, packet, command, or authority drifted."""


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
                f"expanded play REPORT source unavailable: {logical}")
        result[logical] = sha256_file(path)
    return dict(sorted(result.items()))


def runtime_contract() -> dict:
    value = BASE.runtime_contract()
    value["max_concurrent_label_shards"] = SUPERVISOR_MAX_WORKERS
    value["supervisor_heartbeat_seconds"] = SUPERVISOR_HEARTBEAT_SECONDS
    return value


def build_report_schedule(
    states: Sequence[Mapping[str, object]], *, surface: str,
) -> dict:
    if surface != "play":
        raise ReportControllerRefused(
            "expanded play REPORT surface drift")
    selected = sorted(
        (state for state in states if state.get("surface_type") == surface),
        key=lambda state: str(state["state_id"]))
    if (len(selected) != REPORT_SURFACE_COUNTS[surface]
            or len({str(state["state_id"]) for state in selected})
            != len(selected)):
        raise ReportControllerRefused(
            "expanded play REPORT selected population drift")
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
        "schema": "teacher-stage-c-expanded-play-report-schedule-v1",
        "surface": "play",
        "states": len(selected),
        "selected_surface_state_ids_sha256": _manifest_hash([
            str(state["state_id"]) for state in selected]),
        "partition_rule": (
            "sort play states by state_id, then assign position modulo eight"),
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
    value = {
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
    return value


def _validate_capability_review(
    path: Path, packet: Mapping[str, object], packet_external_sha256: str,
) -> dict:
    claim = marker_claim(path, CAP.REVIEW_MARKER)
    if claim != CAP.expected_review_claim(packet, packet_external_sha256):
        raise ReportControllerRefused(
            "expanded play capability review marker drift")
    return claim


def _build_inputs(
    *, capability_packet_path: Path,
    expected_capability_packet_sha256: str,
    capability_review_record: Path,
    evidence_repo: Path, training_result_review_record: Path,
    capture_evidence_repo: Path, state_set_review_record: Path,
    fresh_report_review_record: Path, bury_result_review_record: Path,
    recompute_capability: bool = True,
) -> tuple[dict, dict, dict, dict, list[dict]]:
    if (capability_packet_path.resolve() != (REPO / CAP.PACKET_PATH).resolve()
            or not is_regular_unlinked(capability_packet_path)
            or sha256_file(capability_packet_path)
            != expected_capability_packet_sha256):
        raise ReportControllerRefused(
            "expanded play capability packet path/SHA drift")
    capability_packet = load_json(capability_packet_path)
    if (capability_packet.get("schema") != CAP.SCHEMA
            or capability_packet.get("packet_sha256")
            != self_hash(capability_packet, "packet_sha256")):
        raise ReportControllerRefused(
            "expanded play capability packet identity drift")
    for logical, expected in capability_packet["producer"]["sources"].items():
        path = REPO / logical
        if not is_regular_unlinked(path) or sha256_file(path) != expected:
            raise ReportControllerRefused(
                f"expanded play capability source drift: {logical}")
    _validate_capability_review(
        capability_review_record, capability_packet,
        expected_capability_packet_sha256)
    if recompute_capability:
        rebuilt = CAP._build_packet(
            evidence_repo=evidence_repo,
            training_result_review_record=training_result_review_record,
            capture_evidence_repo=capture_evidence_repo,
            state_set_review_record=state_set_review_record,
            fresh_report_review_record=fresh_report_review_record,
            bury_result_review_record=bury_result_review_record,
            expected_git=str(capability_packet["producer"]["git"]))
        if capability_packet != rebuilt:
            raise ReportControllerRefused(
                "expanded play capability full recomputation drift")
    try:
        training_packet, dataset, _receipt, _aggregate, _final, _bury = \
            BASE.validate_training_evidence(
                evidence_repo=evidence_repo,
                training_result_review_record=training_result_review_record,
                reopen_checkpoints=False)
        selection = CAP._fresh_play_selection(
            capture_evidence_repo=capture_evidence_repo,
            state_set_review_record=state_set_review_record,
            fresh_report_review_record=fresh_report_review_record)
    except (BASE.ReportControllerRefused,
            CAP.ExpandedPlayCapabilityRefused) as exc:
        raise ReportControllerRefused(str(exc)) from exc
    if CAP._selection_summary(selection) \
            != capability_packet["fresh_play_selection"]:
        raise ReportControllerRefused(
            "expanded play fresh selection binding drift")
    return (capability_packet, training_packet, dataset, selection,
            list(selection["states"]))


def build_packet(
    *, git: str, capability_packet_path: Path,
    expected_capability_packet_sha256: str,
    capability_review_record: Path,
    evidence_repo: Path, training_result_review_record: Path,
    capture_evidence_repo: Path, state_set_review_record: Path,
    fresh_report_review_record: Path, bury_result_review_record: Path,
    _validated_inputs: tuple[dict, dict, dict, dict, list[dict]] | None = None,
) -> dict:
    values = _validated_inputs
    if values is None:
        values = _build_inputs(
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
    schedule = build_report_schedule(states, surface="play")
    selected = capability["capability"]
    scope = CAP._play_scope_contract(states)
    if scope != capability["play_scope_contract"]:
        raise ReportControllerRefused(
            "expanded play scope contract drift")
    prior = TRAIN.state_balanced_prior(
        dataset["examples"]["DESIGN"]["play"])
    if prior != capability["design_prior_distribution"]:
        raise ReportControllerRefused(
            "expanded play design prior drift")
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
                "review_record_sha256":
                    sha256_file(capability_review_record),
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
                "logical_path": BASE.TRAIN_CTRL.PACKET_PATH,
                "external_sha256": BASE.TRAINING_PACKET_SHA256,
                "internal_sha256": training_packet["packet_sha256"],
            },
            "model_dataset": {
                "logical_path": BASE.TRAIN_CTRL.DATASET_PATH,
                "external_sha256": BASE.MODEL_DATASET_SHA256,
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
                "sealed_selection_sha256": selection["selection_sha256"],
                "fresh_report_state_ids_sha256":
                    selection["state_ids_sha256"],
                "fresh_report_state_material_sha256":
                    selection["states_sha256"],
                "fresh_report_states": selection["state_count"],
                "spent_report_populations":
                    selection["spent_report_populations"],
                "spent_report_state_ids_sha256":
                    selection["spent_report_state_ids_sha256"],
                "spent_report_deal_seeds_sha256":
                    selection["spent_report_deal_seeds_sha256"],
                "spent_state_overlap": selection["spent_state_overlap"],
                "spent_deal_seed_overlap":
                    selection["spent_deal_seed_overlap"],
                "remaining_report_supply_after_selection":
                    selection["remaining_report_supply_after_selection"],
                "state_material_published": False,
            },
        },
        "selected_capability": selected,
        "play_scope_contract": scope,
        "protected_policy": None,
        "checkpoint_manifest": capability["checkpoint_manifest"],
        "design_prior_distribution": prior,
        "runtime_contract": runtime_contract(),
        "report_schedule": schedule,
        "report_contract": {
            "surface": "play",
            "head": "ranking",
            "states": 480,
            "bury_states": 0,
            "scope": scope["scope"],
            "candidate_world_ceiling": schedule["candidate_world_ceiling"],
            "v11_checkpoint_loaded": False,
            "v11_candidates_reconstructed": False,
            "captured_candidate_tensor_authenticated": True,
            "single_report_look": True,
            "report_population_ordinal": 5,
            "prior_report_populations_spent": 4,
            "prior_report_state_overlap": 0,
            "prior_report_deal_seed_overlap": 0,
            "protected_policy": None,
            "model_score_tie_epsilon": REPORT.MODEL_SCORE_TIE_EPSILON,
            "rank_ensemble": (
                "mean within-ballot softmax probability across seeds"),
            "tie_break": "lowest candidate index within epsilon",
            "durable_report_open_admission_slot": (
                f"server/runs/locks/{RUN_ID}.report-open.consumed.json"),
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
    return {
        "schema": REVIEW_SCHEMA,
        "git": packet["producer"]["git"],
        "packet_sha256": packet_external_sha256,
        "packet_internal_sha256": packet["packet_sha256"],
        "controller_script_sha256": sources[
            "server/scripts/teacher_stage_c_expanded_play_report_controller.py"],
        "runtime_wrapper_sha256": sources[RUNTIME_SCRIPT_PATH],
        "supervisor_wrapper_sha256": sources[SUPERVISOR_SCRIPT_PATH],
        "shared_runtime_sha256": sources[
            "server/scripts/teacher_stage_c_report_runtime.py"],
        "shared_supervisor_sha256": sources[
            "server/scripts/teacher_stage_c_report_supervisor.py"],
        "capability_packet_sha256": packet["parents"][
            "capability_packet"]["external_sha256"],
        "capability_review_record_sha256": packet["parents"][
            "capability_packet"]["review_record_sha256"],
        "capability_review_claim_sha256": packet["parents"][
            "capability_packet"]["review_claim_sha256"],
        "selected_capability": packet["selected_capability"],
        "play_scope_contract": packet["play_scope_contract"],
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
        "execution_host": packet["runtime_contract"]["host"],
        "python": packet["runtime_contract"]["python"],
        "torch": packet["runtime_contract"]["torch"],
        "numpy": packet["runtime_contract"]["numpy"],
        "teacher_labels_computed_before_review": 0,
        "model_predictions_computed_before_review": 0,
        "report_utility_opened_before_review": False,
        "fresh_report_state_material_published": False,
        "report_population_ordinal": 5,
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
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise ReportControllerRefused(f"refusing existing output: {path}")
    with partial.open("xb") as handle:
        handle.write(canonical_json(payload))
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.link(partial, path, follow_symlinks=False)
    except FileExistsError as exc:
        raise ReportControllerRefused(
            f"refusing raced output publication: {path}") from exc
    partial.unlink()


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
            "expanded play runtime packet path/SHA drift")
    frozen = load_json(path)
    common = _common_from_packet(frozen)
    if (fresh_report_review_record.resolve()
            != common["fresh_report_review_record"]
            or state_set_review_record.resolve()
            != common["state_set_review_record"]):
        raise ReportControllerRefused(
            "expanded play runtime review-record path drift")
    values = _build_inputs(**common, recompute_capability=False)
    rebuilt = build_packet(
        git=_git("rev-parse", "HEAD"), **common,
        _validated_inputs=values)
    if (frozen != rebuilt
            or frozen.get("packet_sha256")
            != self_hash(frozen, "packet_sha256")):
        raise ReportControllerRefused(
            "expanded play runtime packet recomputation drift")
    return frozen, values[2], values[1], values[3], values[4]


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("command", choices=("freeze", "verify"))
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
    root.add_argument("--out", default=PACKET_PATH)
    root.add_argument("--expected-packet-sha256")
    return root


def main() -> int:
    args = parser().parse_args()
    if (_git("rev-parse", "HEAD") != args.expected_git
            or _git("status", "--porcelain", "--untracked-files=all")):
        raise ReportControllerRefused(
            "expanded play REPORT producer Git/cleanliness drift")
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
        "capture_evidence_repo": Path(args.capture_evidence_repo).resolve(),
        "state_set_review_record": Path(
            args.state_set_review_record).resolve(),
        "fresh_report_review_record": Path(
            args.fresh_report_review_record).resolve(),
        "bury_result_review_record": Path(
            args.bury_result_review_record).resolve(),
    }
    packet = build_packet(**common)
    out = Path(args.out).resolve()
    if out != (REPO / PACKET_PATH).resolve():
        raise ReportControllerRefused(
            "expanded play REPORT output path drift")
    if args.command == "freeze":
        publish_exclusive(out, packet)
        external = sha256_file(out)
    else:
        if (not args.expected_packet_sha256
                or not is_regular_unlinked(out)
                or sha256_file(out) != args.expected_packet_sha256
                or load_json(out) != packet):
            raise ReportControllerRefused(
                "expanded play frozen packet recomputation drift")
        external = args.expected_packet_sha256
    print(json.dumps({
        "status": "VERIFIED_NO_REPORT_OPEN" if args.command == "verify"
                  else "FROZEN_NO_REPORT_OPEN",
        "packet_sha256": external,
        "packet_internal_sha256": packet["packet_sha256"],
        "expected_review_claim": expected_review_claim(packet, external),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ReportControllerRefused,
            CAP.ExpandedPlayCapabilityRefused,
            BASE.ReportControllerRefused) as exc:
        print(f"REFUSING: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
