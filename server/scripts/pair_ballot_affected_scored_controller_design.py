#!/usr/bin/env python3
"""Design the Pair V3 scored controller without implementing or running it.

The merged scored-packet design permits only this next design review.  This
module authenticates that exact source and its design-only review, reconstructs
the reviewed packet design, and prints a closed controller specification.  It
has no packet writer, admission writer, evaluator/gameplay import, process
launcher, scored-artifact reader, aggregate path, or deployment surface.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import ModuleType


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent

SCHEMA = "pair-ballot-affected-scored-controller-design-v1"
SOURCE_DESIGN_SCHEMA = "pair-ballot-affected-scored-packet-design-v1"
SOURCE_DESIGN_GIT = "289fdf0495da6ad691d8ac760409378f63955545"
SOURCE_DESIGN_MERGE_GIT = "05fb245487cafe0f80878217bb9a013c9f03ee38"
SOURCE_DESIGN_REVIEW_GIT = "6c5c0000b2c61335d66d74916c5b43c454b0093e"
SOURCE_DESIGN_PATH = (
    "server/scripts/pair_ballot_affected_scored_packet_design.py")
SOURCE_DESIGN_SOURCE_SHA256 = (
    "c25820e33053eefab7f5bacd4572391f47fa9897eb6820170b881515c3862f6e")
SOURCE_DESIGN_FILE_SHA256 = (
    "6fb5b5eb3938856234ef362b5f4017e10782e834c94c45ee645ec6f9b4634e41")
SOURCE_DESIGN_INTERNAL_SHA256 = (
    "0e909f6c3e399aaabd9b5bb357a540b64fbbf1df13dc48bfa268876f1d3b8417")
SOURCE_REVIEW_PARENT = "b7a52c3904daab1fcb7c29bfbd5b36b4be47c762"
SOURCE_MERGE_FIRST_PARENT = "6b5ed7e56d3360779e527522d4413ea837d8b77f"
CANONICAL_REF = "origin/main"
REVIEW_LEDGER = "HANDOFF_REVIEW.md"
REVIEWER = "Claude <noreply@anthropic.com>"
SESSION_TRAILER = "Claude-Session: https://claude.ai/code/session_"

RUN_ID = "pair-ballot-affected-scored-dev-calib-v1"
PACKET_SCHEMA = "pair-ballot-affected-scored-packet-v1"
CONTROLLER_SCHEMA = "pair-ballot-affected-scored-controller-v1"
SHARD_SCHEMA = "pair-ballot-affected-scored-shard-v1"
PROGRESS_SCHEMA = "pair-ballot-affected-scored-progress-v1"
FINAL_SCHEMA = "pair-ballot-affected-scored-supervisor-final-v1"
PACKET_REQUEST_PREFIX = "PAIR_BALLOT_AFFECTED_SCORED_PACKET_V1_REQUEST "
PACKET_ATTESTATION_PREFIX = (
    "PAIR_BALLOT_AFFECTED_SCORED_PACKET_V1_REVIEWER_ATTESTATION ")
FINAL_REQUEST_PREFIX = (
    "PAIR_BALLOT_AFFECTED_SCORED_SUPERVISOR_FINAL_V1_REQUEST ")
FINAL_ATTESTATION_PREFIX = (
    "PAIR_BALLOT_AFFECTED_SCORED_SUPERVISOR_FINAL_V1_REVIEWER_ATTESTATION ")
AGGREGATE_ATTESTATION_PREFIX = (
    "PAIR_BALLOT_AFFECTED_SCORED_AGGREGATE_V1_REVIEWER_ATTESTATION ")

LOGICAL_LANES = 16
SPLITS = ("dev", "calib")
SHARD_OUTPUTS = 32
STATES = 1_024
WORK_PER_STATE = 2_940
MAX_WORK_TOTAL = 3_010_560
MAX_FLEET_HOURS = 64.0
MAX_LANE_WALL_HOURS = 4.0

_sha256 = hashlib.sha256


class ControllerDesignRefused(ValueError):
    """Raised when controller-design provenance or structure drifts."""


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode()


def _digest(raw: bytes) -> str:
    return _sha256(raw).hexdigest()


def _strict_json(raw: bytes, *, label: str) -> object:
    def pairs(items: list[tuple[str, object]]) -> dict:
        out: dict[str, object] = {}
        for key, value in items:
            if key in out:
                raise ControllerDesignRefused(
                    f"{label} contains duplicate key {key!r}")
            out[key] = value
        return out

    def bad_constant(value: str) -> None:
        raise ControllerDesignRefused(
            f"{label} contains non-finite value {value}")

    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=bad_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ControllerDesignRefused(f"{label} is not strict JSON") from exc


def _stable_bytes(path: Path, *, label: str, frozen: bool = False) -> bytes:
    try:
        lexical = path.absolute()
        before = os.lstat(lexical)
        if (stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or (frozen and before.st_mode & 0o222)):
            raise ControllerDesignRefused(
                f"{label} must be regular, unlinked"
                + (" and non-writable" if frozen else ""))
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(lexical, flags)
        try:
            opened = os.fstat(fd)
            chunks: list[bytes] = []
            while True:
                chunk = os.read(fd, 1 << 20)
                if not chunk:
                    break
                chunks.append(chunk)
            after = os.fstat(fd)
        finally:
            os.close(fd)
        current = os.lstat(lexical)
    except OSError as exc:
        raise ControllerDesignRefused(f"cannot read stable {label}") from exc
    identity = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
    if (identity(before) != identity(opened)
            or identity(opened) != identity(after)
            or identity(after) != identity(current)):
        raise ControllerDesignRefused(f"{label} changed while read")
    return b"".join(chunks)


def _git(*args: str, text: bool = True) -> str | bytes:
    try:
        result = subprocess.run(
            ["git", *args], cwd=REPO, check=True, capture_output=True,
            text=text)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ControllerDesignRefused(
            f"git provenance command failed: {' '.join(args)}") from exc
    return result.stdout


def _git_bytes(ref: str, path: str) -> bytes:
    value = _git("show", f"{ref}:{path}", text=False)
    if not isinstance(value, bytes):
        raise ControllerDesignRefused("git returned text for byte request")
    return value


def _require_provenance() -> dict:
    if _git("rev-parse", SOURCE_DESIGN_GIT).strip() != SOURCE_DESIGN_GIT:
        raise ControllerDesignRefused("source-design git identity drift")
    if _git("rev-parse", SOURCE_DESIGN_REVIEW_GIT).strip() \
            != SOURCE_DESIGN_REVIEW_GIT:
        raise ControllerDesignRefused("source review git identity drift")
    if _git("rev-parse", f"{SOURCE_DESIGN_REVIEW_GIT}^").strip() \
            != SOURCE_REVIEW_PARENT:
        raise ControllerDesignRefused("source review parent drift")
    merge_parents = _git(
        "show", "-s", "--format=%P", SOURCE_DESIGN_MERGE_GIT).strip().split()
    if merge_parents != [SOURCE_MERGE_FIRST_PARENT, SOURCE_DESIGN_GIT]:
        raise ControllerDesignRefused("source merge topology drift")
    names = _git("diff-tree", "--no-commit-id", "--name-only", "-r",
                 SOURCE_DESIGN_REVIEW_GIT).splitlines()
    if names != [REVIEW_LEDGER]:
        raise ControllerDesignRefused("source review changed another file")
    actor = _git("show", "-s", "--format=%an <%ae>%n%cn <%ce>",
                 SOURCE_DESIGN_REVIEW_GIT).splitlines()
    if actor != [REVIEWER, REVIEWER]:
        raise ControllerDesignRefused("source reviewer identity drift")
    message = _git("show", "-s", "--format=%B", SOURCE_DESIGN_REVIEW_GIT)
    if (SESSION_TRAILER not in message
            or "design-only PASS" not in message
            or "289fdf0" not in message):
        raise ControllerDesignRefused("source review message drift")
    reviewed_ledger = _git_bytes(SOURCE_DESIGN_REVIEW_GIT, REVIEW_LEDGER)
    parent_ledger = _git_bytes(SOURCE_REVIEW_PARENT, REVIEW_LEDGER)
    delta = reviewed_ledger[len(parent_ledger):] \
        if reviewed_ledger.startswith(parent_ledger) else b""
    required = (
        b"PASS (design only, superseding): Pair V3 scored packet design",
        b"No execution marker is emitted",
        b"grants no runtime, execution, scoring, strength, retry",
    )
    if not delta or any(item not in delta for item in required):
        raise ControllerDesignRefused("source review ledger statement drift")
    source_bytes = _git_bytes(SOURCE_DESIGN_GIT, SOURCE_DESIGN_PATH)
    merged_bytes = _git_bytes(SOURCE_DESIGN_MERGE_GIT, SOURCE_DESIGN_PATH)
    live_bytes = _stable_bytes(REPO / SOURCE_DESIGN_PATH,
                               label="source packet design")
    if not (source_bytes == merged_bytes == live_bytes):
        raise ControllerDesignRefused("source packet-design bytes drift")
    if _digest(source_bytes) != SOURCE_DESIGN_SOURCE_SHA256:
        raise ControllerDesignRefused("source packet-design SHA drift")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", SOURCE_DESIGN_REVIEW_GIT,
         CANONICAL_REF], cwd=REPO, capture_output=True)
    if ancestor.returncode != 0:
        raise ControllerDesignRefused("source review not on canonical main")
    return {
        "source_design_git": SOURCE_DESIGN_GIT,
        "source_design_merge_git": SOURCE_DESIGN_MERGE_GIT,
        "source_design_review_git": SOURCE_DESIGN_REVIEW_GIT,
        "source_design_path": SOURCE_DESIGN_PATH,
        "source_design_source_sha256": SOURCE_DESIGN_SOURCE_SHA256,
        "review_is_design_only": True,
        "execution_authority_from_review": False,
    }


def _source_design() -> dict:
    raw = _stable_bytes(REPO / SOURCE_DESIGN_PATH,
                        label="source packet design")
    if _digest(raw) != SOURCE_DESIGN_SOURCE_SHA256:
        raise ControllerDesignRefused("source packet-design SHA drift")
    module = ModuleType("_reviewed_pair_scored_packet_design")
    module.__file__ = str(REPO / SOURCE_DESIGN_PATH)
    exec(compile(raw, module.__file__, "exec"), module.__dict__)
    payload = module.build_design()
    module.validate_design(payload)
    if (payload.get("schema") != SOURCE_DESIGN_SCHEMA
            or payload.get("design_sha256")
            != SOURCE_DESIGN_INTERNAL_SHA256
            or _digest(_canonical(payload)) != SOURCE_DESIGN_FILE_SHA256):
        raise ControllerDesignRefused("source packet-design artifact drift")
    return payload


def build_design() -> dict:
    """Reconstruct the complete non-executable controller specification."""
    provenance = _require_provenance()
    source = _source_design()
    selection = source["selection"]
    schedule = source["schedule"]
    work = source["scored_work"]
    capacity = source["capacity_and_economics"]
    if (selection["states"] != STATES
            or schedule["logical_lanes"] != LOGICAL_LANES
            or schedule["scored_shard_outputs"] != SHARD_OUTPUTS
            or work["max_candidate_world_rollouts_per_state"]
            != WORK_PER_STATE
            or work["max_candidate_world_rollouts_total"] != MAX_WORK_TOTAL
            or capacity["max_fleet_hours"] != MAX_FLEET_HOURS
            or capacity["max_lane_wall_hours"] != MAX_LANE_WALL_HOURS):
        raise ControllerDesignRefused("source controller contract drift")
    lane_manifest = schedule["lanes"]
    lane_work = [lane["max_candidate_world_rollouts"]
                 for lane in lane_manifest]
    if (len(lane_manifest) != LOGICAL_LANES
            or sum(lane_work) != MAX_WORK_TOTAL
            or any(value != lane_manifest[index]["state_count"]
                   * WORK_PER_STATE for index, value in enumerate(lane_work))):
        raise ControllerDesignRefused("lane work reconstruction drift")

    payload = {
        "schema": SCHEMA,
        "status": "controller design only; no controller implemented",
        "provenance": provenance,
        "source_packet_design": {
            "schema": source["schema"],
            "git": SOURCE_DESIGN_GIT,
            "source_sha256": SOURCE_DESIGN_SOURCE_SHA256,
            "file_sha256": SOURCE_DESIGN_FILE_SHA256,
            "internal_sha256": SOURCE_DESIGN_INTERNAL_SHA256,
            "run_id": source["future_controller_freeze"]["run_id"],
            "packet_schema": source["future_controller_freeze"][
                "packet_schema"],
            "selection_sha256": selection["selection_sha256"],
            "lane_manifest_sha256": schedule["lane_manifest_sha256"],
        },
        "packet_freeze_contract": {
            "run_id": RUN_ID,
            "packet_schema": PACKET_SCHEMA,
            "controller_schema": CONTROLLER_SCHEMA,
            "packet_binds_exact_controller_source_git_and_sha256": True,
            "packet_binds_exact_controller_design_file_and_internal_sha256":
                True,
            "packet_binds_source_packet_design_file_and_internal_sha256": True,
            "packet_reconstructs_source_design_before_publication": True,
            "packet_binds_all_reviewed_population_capacity_and_source_inputs":
                True,
            "packet_binds_exact_host_python_native_runtime_and_systemd_fragment":
                True,
            "packet_binds_exact_loaded_fragment_and_need_daemon_reload_false":
                True,
            "packet_requires_zero_dropins_and_exact_environment_nice_timeout":
                True,
            "packet_write_is_atomic_exclusive_and_preexisting_refuses": True,
            "packet_contains_no_scored_values_actions_or_outcomes": True,
            "packet_request_prefix": PACKET_REQUEST_PREFIX,
            "packet_reviewer_attestation_prefix": PACKET_ATTESTATION_PREFIX,
            "request_and_attestation_namespaces_are_distinct": True,
            "request_text_is_never_parsed_as_authority": True,
            "independent_packet_review_commit_required": True,
            "packet_cannot_self_authorize": True,
        },
        "execution_topology": {
            "logical_lanes": LOGICAL_LANES,
            "worker_processes": LOGICAL_LANES,
            "splits_in_each_lane": list(SPLITS),
            "split_order_in_each_lane": list(SPLITS),
            "sealed_shard_outputs": SHARD_OUTPUTS,
            "one_supervisor_owns_all_workers": True,
            "workers_run_concurrently": True,
            "lane_assignment": schedule["assignment"],
            "lane_manifest": lane_manifest,
            "lane_manifest_sha256": schedule["lane_manifest_sha256"],
            "systemd_service_required": True,
            "kill_mode_control_group": True,
            "restart": "no",
            "runtime_max_hours": MAX_LANE_WALL_HOURS,
            "interruption_kills_all_workers": True,
            "resume_supported": False,
            "retry_supported": False,
        },
        "population_and_work": {
            "splits": list(SPLITS),
            "report_split_permitted": False,
            "states": STATES,
            "states_by_split": selection["states_by_split"],
            "states_by_band": selection["states_by_band"],
            "states_by_role": selection["states_by_role"],
            "unique_deal_clusters": selection["unique_deal_clusters"],
            "complete_fixed_population_required": True,
            "work_per_state": WORK_PER_STATE,
            "max_work_total": MAX_WORK_TOTAL,
            "lane_work": lane_work,
            "current_policy": work["current_policy"],
            "retained_policy": work["retained_policy"],
            "external_actions": work["external_actions"],
            "selection_worlds_per_candidate": work[
                "selection_worlds_per_candidate"],
            "policy_report_lcb_worlds": work["policy_report_lcb_worlds"],
            "external_common_worlds": work["external_common_worlds"],
            "same_policy_root_seed_for_current_and_retained": True,
            "one_fresh_common_external_world_draw_for_distinct_actions": True,
            "short_zero_or_incomplete_work": "refuse entire execution",
        },
        "evidence_contract": {
            "shard_schema": SHARD_SCHEMA,
            "progress_schema": PROGRESS_SCHEMA,
            "supervisor_final_schema": FINAL_SCHEMA,
            "score_bearing_shards_are_regular_unlinked_and_sealed": True,
            "shard_payloads_are_never_printed_or_read_by_supervisor": True,
            "progress_allowlist": [
                "schema", "run_id", "lane_index", "split",
                "states_complete", "states_total", "work", "sampler",
                "dose", "elapsed_ns",
            ],
            "progress_forbids_actions_scores_utilities_winners_and_labels": True,
            "supervisor_final_contains_only_identity_hash_completion_work_and_telemetry":
                True,
            "supervisor_final_binds_all_32_ordered_shard_file_hashes": True,
            "supervisor_final_binds_exact_work_sampler_and_dose_reconciliation":
                True,
            "supervisor_final_contains_no_diagnostic_estimand": True,
            "partial_or_extra_output": "refuse",
            "outcome_access_before_terminal_review": "refuse",
        },
        "admission_and_review": {
            "fresh_consumed_admission_required": True,
            "admission_created_after_packet_attestation_and_before_workers":
                True,
            "admission_binds_packet_review_design_runtime_and_unit": True,
            "one_admission_per_run_id": True,
            "failed_or_interrupted_admission_is_spent": True,
            "final_request_prefix": FINAL_REQUEST_PREFIX,
            "final_reviewer_attestation_prefix": FINAL_ATTESTATION_PREFIX,
            "aggregate_reviewer_attestation_prefix":
                AGGREGATE_ATTESTATION_PREFIX,
            "all_request_and_attestation_prefixes_are_distinct": True,
            "review_records_are_canonical_main_claude_ledger_only_commits": True,
            "git_provenance_is_operational_not_cryptographic_identity": True,
        },
        "terminal_sequence": {
            "step_1": "controller implementation exact-head review",
            "step_2": "freeze one host-specific score-free packet",
            "step_3": "independent packet attestation",
            "step_4": "consume one admission and execute all 32 shards",
            "step_5": "independent score-free supervisor-final review",
            "step_6": "separate aggregation attestation",
            "step_7": "aggregate once and independently review result",
            "scored_shards_remain_sealed_through_step_5": True,
            "aggregation_never_uses_incomplete_or_subset_shards": True,
            "positive_diagnostic_opens_only_a_fresh_next_design_review": True,
            "no_automatic_retry_extension_confirmation_or_whole_game_run": True,
        },
        "capacity_boundary": {
            "projected_fleet_hours": capacity["projected_fleet_hours"],
            "projected_worst_lane_hours":
                capacity["projected_worst_lane_hours"],
            "max_fleet_hours": MAX_FLEET_HOURS,
            "max_lane_wall_hours": MAX_LANE_WALL_HOURS,
            "average_lane_projection_permitted": False,
            "capacity_is_runtime_specific_not_utility_or_strength": True,
            "champion_natural_dose_required_before_whole_game_economics": True,
        },
        "authority": {
            "controller_design_review_only": True,
            "controller_implementation_authorized": False,
            "packet_implementation_authorized": False,
            "packet_freeze_authorized": False,
            "packet_run_authorized": False,
            "population_open_authorized": False,
            "capacity_result_open_authorized": False,
            "scored_output_access_authorized": False,
            "aggregation_authorized": False,
            "report_access_authorized": False,
            "champion_dose_census_authorized": False,
            "whole_game_execution_authorized": False,
            "retry_authorized": False,
            "extension_authorized": False,
            "strength_claim": False,
            "training_authorized": False,
            "production_promotion": False,
            "production_deployment": False,
        },
    }
    if (payload["packet_freeze_contract"]["run_id"]
            != source["future_controller_freeze"]["run_id"]
            or payload["packet_freeze_contract"]["packet_schema"]
            != source["future_controller_freeze"]["packet_schema"]
            or len({PACKET_REQUEST_PREFIX, PACKET_ATTESTATION_PREFIX,
                    FINAL_REQUEST_PREFIX, FINAL_ATTESTATION_PREFIX,
                    AGGREGATE_ATTESTATION_PREFIX}) != 5
            or not math.isclose(sum(source["estimands"]["band_weights"].values()),
                                1.0, rel_tol=0.0, abs_tol=1e-15)):
        raise ControllerDesignRefused("controller design consistency drift")
    payload["design_sha256"] = _digest(_canonical(payload))
    return payload


def validate_design(payload: object) -> None:
    if not isinstance(payload, dict):
        raise ControllerDesignRefused("controller design is not an object")
    body = dict(payload)
    observed = body.pop("design_sha256", None)
    if observed != _digest(_canonical(body)):
        raise ControllerDesignRefused("controller design digest drift")
    if _canonical(payload) != _canonical(build_design()):
        raise ControllerDesignRefused(
            "controller design differs from reconstruction")


def verify_design_file(path: Path) -> dict:
    raw = _stable_bytes(path, label="controller design", frozen=True)
    payload = _strict_json(raw, label="controller design")
    if raw != _canonical(payload):
        raise ControllerDesignRefused("controller design is not canonical JSON")
    validate_design(payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--design", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "build":
            if args.design is not None:
                raise ControllerDesignRefused(
                    "build prints to stdout and accepts no design path")
            print(_canonical(build_design()).decode(), end="")
        else:
            if args.design is None:
                raise ControllerDesignRefused("verify requires --design")
            design = verify_design_file(args.design)
            print(json.dumps({
                "schema": design["schema"],
                "design_sha256": design["design_sha256"],
                "logical_lanes": design["execution_topology"][
                    "logical_lanes"],
                "sealed_shard_outputs": design["execution_topology"][
                    "sealed_shard_outputs"],
                "controller_implementation_authorized": False,
                "packet_run_authorized": False,
            }, sort_keys=True))
    except (ControllerDesignRefused, OSError, ValueError) as exc:
        print(f"REFUSING: {exc}")
        raise SystemExit(3) from exc


if __name__ == "__main__":
    main()
