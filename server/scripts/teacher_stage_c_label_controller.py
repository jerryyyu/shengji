#!/usr/bin/env python3
"""Freeze the one-shot Teacher Stage-C label controller.

This controller is intentionally downstream of three independent boundaries:
the replay-authenticated Stage-C capture must have published exactly 2,048
states, an independent reviewer must have passed that immutable state set, and
an outcome-discarding capacity preflight over that exact set must have passed
and been independently reviewed.  Only then may this script freeze a finite
label schedule.  Freezing or verifying the packet samples no belief world and
computes no outcome.

The immutable Stage-C design budgeted each REPORT audit state for two actions
on 600 report worlds.  That geometry cannot both certify a selection winner
against candidate zero and measure regret against a third, frozen label choice.
This successor preserves the exact 1,200 candidate-world budget as three
logical action slots on 400 common worlds.  Duplicate identities still consume
their logical slots.  The amendment changes no state, candidate, label fold,
utility, continuation, or total-work ceiling and requires its own review before
one label execution can be admitted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SCRIPT.parents[2]
sys.path.insert(0, str(SCRIPT.parent))

import teacher_stage_c_capture_controller as CAPTURE_CTRL  # noqa: E402
import teacher_stage_c_design as DESIGN  # noqa: E402
import teacher_stage_c_label_runtime as LABEL  # noqa: E402


SCHEMA = "teacher-stage-c-label-controller-v1"
PACKET_ID = "teacher-v3-hard-tail-stage-c-label-controller-v1"
RUN_ID = "teacher-v3-hard-tail-stage-c-labels-v1"
CONTROLLER_RUN_ID = "teacher-v3-hard-tail-stage-c-label-controller-v1"
CONTROLLER_PACKET_PATH = (
    f"server/runs/logs/{CONTROLLER_RUN_ID}/controller_packet.json"
)
REVIEW_SCHEMA = "teacher-stage-c-label-controller-review-v1"
REVIEW_MARKER = "TEACHER_STAGE_C_LABEL_CONTROLLER_V1_REVIEW "
STATE_SET_REVIEW_SCHEMA = "teacher-stage-c-state-set-review-v1"
STATE_SET_REVIEW_MARKER = "TEACHER_STAGE_C_STATE_SET_V3_REVIEW "
RECEIPT_SCHEMA = "teacher-stage-c-label-receipt-v1"
ADMISSION_SCHEMA = "teacher-stage-c-label-admission-v1"
SHARD_ADMISSION_SCHEMA = "teacher-stage-c-label-shard-admission-v1"
SHARD_SCHEMA = "teacher-stage-c-label-shard-v1"
AGGREGATE_SCHEMA = "teacher-stage-c-label-aggregate-v1"
CAPACITY_PACKET_SCHEMA = "teacher-stage-c-label-capacity-controller-v1"
CAPACITY_PACKET_ID = "teacher-v3-hard-tail-stage-c-label-capacity-controller-v1"
CAPACITY_RUN_ID = "teacher-v3-hard-tail-stage-c-label-capacity-v1"
CAPACITY_RESULT_SCHEMA = "teacher-stage-c-label-capacity-result-v1"
CAPACITY_RESULT_REVIEW_SCHEMA = (
    "teacher-stage-c-label-capacity-result-review-v1"
)
CAPACITY_RESULT_REVIEW_MARKER = (
    "TEACHER_STAGE_C_LABEL_CAPACITY_RESULT_V1_REVIEW "
)

CAPTURE_CONTROLLER_SHA256 = (
    "d58a9308907b53e9f61c80a4067d383c596cf39ebe303c246e7086535dad1c91"
)
CAPTURE_SOURCE_GIT = "0b697b6e5eee1891ca73737cb689591f8f2879df"
CAPTURE_RUN_ID = "teacher-v3-hard-tail-stage-c-capture-v3"
LABEL_SHARDS = 16
STATES_PER_SHARD = 128
SPLIT_SHARDS = {"DESIGN": 8, "CALIB": 4, "REPORT": 4}
EXPECTED_SPLITS = {"DESIGN": 1024, "CALIB": 512, "REPORT": 512}
EXPECTED_STATES = 2048
EXPECTED_PLAY = 1920
EXPECTED_BURY = 128
EXPECTED_AUDIT = 256
BASE_MAX_CANDIDATE_WORLDS = 10_494_720

SOURCE_PATHS = tuple(dict.fromkeys((
    "server/scripts/teacher_stage_c_label_controller.py",
    "server/scripts/teacher_stage_c_label_runtime.py",
    "server/scripts/teacher_stage_c_label_capacity.py",
    "server/scripts/teacher_stage_c_capture_controller.py",
    "server/scripts/teacher_stage_c_capture_runtime.py",
    "server/scripts/teacher_stage_c_design.py",
    *CAPTURE_CTRL.SOURCE_PATHS,
)))

REVIEW_FIELDS = (
    "schema", "git", "controller_script_sha256", "runtime_script_sha256",
    "packet_sha256", "capture_controller_sha256", "state_set_sha256",
    "capture_verification_sha256", "state_set_review_schema",
    "states", "design_states", "calib_states", "report_states",
    "play_states", "bury_states", "audit_states", "label_shards",
    "states_per_shard", "schedule_sha256", "exact_candidate_worlds",
    "max_candidate_worlds", "max_sampler_attempts",
    "audit_report_actions", "audit_report_worlds",
    "audit_report_candidate_worlds", "report_labels_sealed_from_training",
    "shard_admission_slots",
    "capacity_packet_sha256", "capacity_result_sha256",
    "capacity_result_review_schema", "capacity_pass",
    "worlds_sampled_before_review", "outcomes_computed_before_review",
    "independent_review", "one_label_execution_authorized",
    "training_authorized", "strength_claim", "production_promotion",
    "production_deployment", "verdict",
)


class ControllerRefused(RuntimeError):
    """A label input, identity, schedule, or authority boundary drifted."""


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"))
            + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def self_hash(payload: Mapping[str, object], field: str = "packet_sha256") -> str:
    return sha256_bytes(canonical_json({
        key: value for key, value in payload.items() if key != field
    }))


def is_regular_unlinked(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not path.is_symlink())


def load_json(path: Path) -> dict:
    if not is_regular_unlinked(path):
        raise ControllerRefused(f"input is not regular/unlinked: {path}")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ControllerRefused(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ControllerRefused(f"JSON root is not an object: {path}")
    return value


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def marker_claim(path: Path, marker: str) -> dict:
    if not is_regular_unlinked(path):
        raise ControllerRefused("review record is not regular/unlinked")
    matches = [line[len(marker):] for line in path.read_text().splitlines()
               if line.startswith(marker)]
    if len(matches) != 1:
        raise ControllerRefused(
            f"review record must contain exactly one {marker.strip()} marker")
    try:
        claim = json.loads(matches[0])
    except ValueError as exc:
        raise ControllerRefused("review marker is not valid JSON") from exc
    if not isinstance(claim, dict):
        raise ControllerRefused("review marker claim is not an object")
    return claim


def admission_slot_logical_path() -> str:
    return f"server/runs/locks/{RUN_ID}.consumed.json"


def require_admission_slot_ignored() -> dict:
    logical = admission_slot_logical_path()
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", logical], cwd=REPO,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ControllerRefused(f"admission slot is not Git-ignored: {logical}")
    return {"logical_path": logical, "gitignored": True}


def shard_admission_logical_path(index: int) -> str:
    if not 0 <= index < LABEL_SHARDS:
        raise ControllerRefused("label shard admission index outside schedule")
    return f"server/runs/locks/{RUN_ID}.shard-{index:02d}.consumed.json"


def require_shard_admission_slots_ignored() -> list[str]:
    values = []
    for index in range(LABEL_SHARDS):
        logical = shard_admission_logical_path(index)
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", logical], cwd=REPO,
            capture_output=True,
        )
        if result.returncode != 0:
            raise ControllerRefused(
                f"label shard admission slot is not Git-ignored: {logical}")
        values.append(logical)
    return values


def producer_identity(*, smoke: bool) -> dict:
    require_admission_slot_ignored()
    dirty = bool(_git("status", "--porcelain", "--untracked-files=all"))
    if dirty and not smoke:
        raise ControllerRefused("real label-controller freeze refuses dirty tree")
    return {
        "git": _git("rev-parse", "HEAD"),
        "tree_dirty": dirty,
        "promotable": not smoke,
        "controller_script_sha256": sha256_file(SCRIPT),
    }


def runtime_sources() -> dict[str, str]:
    values = {}
    for logical in SOURCE_PATHS:
        path = REPO / logical
        if not is_regular_unlinked(path):
            raise ControllerRefused(f"label runtime source unavailable: {logical}")
        values[logical] = sha256_file(path)
    return dict(sorted(values.items()))


def _capacity_module():
    # Imported lazily because the capacity controller itself imports this
    # module to reuse the exact state-set and label-schedule validators.
    import teacher_stage_c_label_capacity as capacity
    return capacity


def validate_capture_controller(path: Path) -> dict:
    if sha256_file(path) != CAPTURE_CONTROLLER_SHA256:
        raise ControllerRefused("capture-controller external SHA-256 drift")
    packet = load_json(path)
    authority = packet.get("authority", {})
    if (packet.get("schema") != CAPTURE_CTRL.SCHEMA
            or packet.get("packet_id") != CAPTURE_CTRL.PACKET_ID
            or packet.get("run_id") != CAPTURE_RUN_ID
            or packet.get("producer", {}).get("git") != CAPTURE_SOURCE_GIT
            or packet.get("packet_sha256") != CAPTURE_CTRL.self_hash(packet)
            or packet.get("result_contract", {}).get("required_states")
            != EXPECTED_STATES
            or packet.get("result_contract", {}).get(
                "terminal_disposition_replay_deals") != 750_000
            or authority.get("state_capture_authorized") is not False
            or authority.get("labels_authorized") is not False
            or authority.get("training_authorized") is not False):
        raise ControllerRefused("capture-controller identity/authority drift")
    for logical, expected in packet.get("runtime_sources", {}).items():
        path = REPO / logical
        if not is_regular_unlinked(path) or sha256_file(path) != expected:
            raise ControllerRefused(f"capture runtime source drift: {logical}")
    packet = dict(packet)
    packet["external_sha256"] = CAPTURE_CONTROLLER_SHA256
    return packet


def _forbidden_label_key(value: object) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"label_action", "raw_attacker_points",
                       "signed_level_utility", "row_sha256"}:
                return True
            if _forbidden_label_key(child):
                return True
    elif isinstance(value, list):
        return any(_forbidden_label_key(child) for child in value)
    return False


def expected_state_set_review_claim(
    state_set: Mapping[str, object], state_set_sha256: str,
    verification: Mapping[str, object], verification_sha256: str,
) -> dict:
    return {
        "schema": STATE_SET_REVIEW_SCHEMA,
        "capture_git": CAPTURE_SOURCE_GIT,
        "capture_controller_sha256": CAPTURE_CONTROLLER_SHA256,
        "capture_receipt_sha256": state_set["capture_receipt_sha256"],
        "state_set_sha256": state_set_sha256,
        "state_set_internal_sha256": state_set["dataset_sha256"],
        "states_sha256": state_set["states_sha256"],
        "report_audit_state_ids_sha256": state_set[
            "report_audit_state_ids_sha256"],
        "capture_verification_sha256": verification_sha256,
        "capture_verification_internal_sha256": verification[
            "verification_sha256"],
        "states": EXPECTED_STATES,
        "design_states": EXPECTED_SPLITS["DESIGN"],
        "calib_states": EXPECTED_SPLITS["CALIB"],
        "report_states": EXPECTED_SPLITS["REPORT"],
        "play_states": EXPECTED_PLAY,
        "bury_states": EXPECTED_BURY,
        "audit_states": EXPECTED_AUDIT,
        "all_scan_dispositions_replay_authenticated": True,
        "terminal_disposition_replay_deals": 750_000,
        "candidate_replay_verified": True,
        "split_safe": True,
        "labels_computed_before_review": False,
        "independent_review": True,
        "one_label_controller_freeze_authorized": True,
        "labels_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }


def validate_state_set(
    state_set_path: Path, expected_state_set_sha256: str,
    verification_path: Path, expected_verification_sha256: str,
    review_record: Path,
) -> tuple[dict, dict, dict]:
    if sha256_file(state_set_path) != expected_state_set_sha256:
        raise ControllerRefused("Stage-C state-set external SHA-256 drift")
    state_set = load_json(state_set_path)
    states = state_set.get("states")
    audit_ids = state_set.get("report_audit_state_ids")
    if (state_set.get("schema") != CAPTURE_CTRL.DATASET_SCHEMA
            or state_set.get("run_id") != CAPTURE_RUN_ID
            or state_set.get("git") != CAPTURE_SOURCE_GIT
            or state_set.get("controller_packet_sha256")
            != CAPTURE_CONTROLLER_SHA256
            or state_set.get("dataset_sha256")
            != self_hash(state_set, "dataset_sha256")
            or state_set.get("complete") is not True
            or state_set.get("state_count") != EXPECTED_STATES
            or state_set.get("split_counts") != EXPECTED_SPLITS
            or state_set.get("surface_counts")
            != {"play": EXPECTED_PLAY, "bury": EXPECTED_BURY}
            or not isinstance(states, list) or len(states) != EXPECTED_STATES
            or not isinstance(audit_ids, list) or len(audit_ids) != EXPECTED_AUDIT
            or len(set(audit_ids)) != EXPECTED_AUDIT
            or state_set.get("states_sha256")
            != sha256_bytes(canonical_json(states))
            or state_set.get("report_audit_state_ids_sha256")
            != sha256_bytes(canonical_json(audit_ids))
            or state_set.get("terminal_disposition_replay_required") is not True
            or state_set.get("labels_authorized") is not False
            or state_set.get("training_authorized") is not False
            or _forbidden_label_key(state_set)):
        raise ControllerRefused("Stage-C state-set identity/authority drift")
    ids = [state.get("state_id") for state in states]
    state_by_id = {str(state["state_id"]): state for state in states}
    if (len(set(ids)) != EXPECTED_STATES
            or Counter(state.get("split") for state in states) != EXPECTED_SPLITS
            or any(state_id not in set(ids) for state_id in audit_ids)
            or any(state_by_id[str(state_id)]["split"] != "REPORT"
                   for state_id in audit_ids)
            or any(state.get("selection_metadata", {}).get(
                "selection_features_may_train_or_label") is not False
                   for state in states)):
        raise ControllerRefused("Stage-C state-set split/identity population drift")
    audit_states = [state_by_id[str(state_id)] for state_id in audit_ids]
    audit_quota = Counter(
        "bury:*" if state["surface_type"] == "bury" else
        f"play:{state['stratum']}" for state in audit_states)
    if audit_quota != {
            "play:ordinary_anchor": 48,
            "play:champion_uncertainty": 48,
            "play:proposal_disagreement": 48,
            "play:exact_late_eligible": 48,
            "play:point_banking_opportunity": 32,
            "bury:*": 32,
    }:
        raise ControllerRefused("Stage-C REPORT audit quota drift")
    for state in audit_states:
        if state["stratum"] != "proposal_disagreement":
            continue
        sources = {source for candidate in state["candidates"]
                   for source in candidate.get("sources", [])}
        if not {"v11pair_top_proposal",
                "same_budget_random_diversifier"}.issubset(sources):
            raise ControllerRefused(
                "Stage-C V11 audit row lacks matched one-action control")
    if sha256_file(verification_path) != expected_verification_sha256:
        raise ControllerRefused("capture-verification external SHA-256 drift")
    verification = load_json(verification_path)
    if (verification.get("schema") != CAPTURE_CTRL.VERIFICATION_SCHEMA
            or verification.get("run_id") != CAPTURE_RUN_ID
            or verification.get("git") != CAPTURE_SOURCE_GIT
            or verification.get("controller_packet_sha256")
            != CAPTURE_CONTROLLER_SHA256
            or verification.get("status") != "VERIFIED_STAGE_C_CAPTURE"
            or verification.get("dataset_sha256") != expected_state_set_sha256
            or verification.get("states") != EXPECTED_STATES
            or verification.get("split_counts") != EXPECTED_SPLITS
            or verification.get("surface_counts")
            != {"play": EXPECTED_PLAY, "bury": EXPECTED_BURY}
            or verification.get("terminal_disposition_replay_deals") != 750_000
            or verification.get(
                "all_scan_dispositions_replay_authenticated") is not True
            or verification.get("state_set_review_authorized") is not True
            or verification.get("labels_authorized") is not False
            or verification.get("training_authorized") is not False
            or verification.get("verification_sha256")
            != self_hash(verification, "verification_sha256")):
        raise ControllerRefused("capture-verification identity/authority drift")
    claim = marker_claim(review_record, STATE_SET_REVIEW_MARKER)
    expected_claim = expected_state_set_review_claim(
        state_set, expected_state_set_sha256,
        verification, expected_verification_sha256)
    if claim != expected_claim:
        raise ControllerRefused("Stage-C state-set PASS marker drift")
    return state_set, verification, claim


def _label_candidate_worlds(state: Mapping[str, object], audit: bool) -> int:
    candidates = state.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ControllerRefused("label state candidate tensor is empty")
    count = len(candidates)
    cap = LABEL.PLAY_CANDIDATE_CAP if state.get("surface_type") == "play" \
        else LABEL.BURY_CANDIDATE_CAP
    if count > cap:
        raise ControllerRefused("label state candidate cap exceeded")
    if LABEL.recipe_for_state(state) == "ordinary_anchor":
        work = count * (
            LABEL.ORDINARY_SELECTION_WORLDS + LABEL.ORDINARY_REPORT_WORLDS)
    else:
        work = count * LABEL.HARD_SELECTION_WORLDS \
            + 2 * LABEL.HARD_REPORT_WORLDS
    if audit:
        work += count * LABEL.AUDIT_SELECTION_WORLDS \
            + LABEL.AUDIT_REPORT_CANDIDATE_WORLDS
    return work


def _sampler_attempt_cap(state: Mapping[str, object], audit: bool) -> int:
    worlds = (LABEL.ORDINARY_SELECTION_WORLDS
              + LABEL.ORDINARY_REPORT_WORLDS
              if LABEL.recipe_for_state(state) == "ordinary_anchor" else
              LABEL.HARD_SELECTION_WORLDS + LABEL.HARD_REPORT_WORLDS)
    if audit:
        worlds += LABEL.AUDIT_SELECTION_WORLDS + LABEL.AUDIT_REPORT_WORLDS
    return worlds * LABEL.SAMPLE_ATTEMPT_FACTOR


def build_schedule(state_set: Mapping[str, object]) -> dict:
    states = state_set["states"]
    audit_ids = set(state_set["report_audit_state_ids"])
    by_split = {split: [state for state in states if state["split"] == split]
                for split in SPLIT_SHARDS}
    shards = []
    global_index = 0
    for split in ("DESIGN", "CALIB", "REPORT"):
        rows = by_split[split]
        if len(rows) != EXPECTED_SPLITS[split]:
            raise ControllerRefused(f"Stage-C {split} state count drift")
        for local in range(SPLIT_SHARDS[split]):
            selected = rows[local * STATES_PER_SHARD:(local + 1)
                            * STATES_PER_SHARD]
            if len(selected) != STATES_PER_SHARD:
                raise ControllerRefused("Stage-C label shard size drift")
            state_ids = [state["state_id"] for state in selected]
            shard = {
                "index": global_index,
                "split": split,
                "local_shard": local,
                "state_start": local * STATES_PER_SHARD,
                "state_count": len(selected),
                "state_ids": state_ids,
                "state_ids_sha256": sha256_bytes(canonical_json(state_ids)),
                "audit_state_ids": [value for value in state_ids
                                    if value in audit_ids],
                "candidate_worlds": sum(_label_candidate_worlds(
                    state, state["state_id"] in audit_ids) for state in selected),
                "sampler_attempt_cap": sum(_sampler_attempt_cap(
                    state, state["state_id"] in audit_ids) for state in selected),
            }
            shards.append(shard)
            global_index += 1
    candidate_worlds = sum(shard["candidate_worlds"] for shard in shards)
    if (len(shards) != LABEL_SHARDS
            or sum(shard["state_count"] for shard in shards) != EXPECTED_STATES
            or sum(len(shard["audit_state_ids"]) for shard in shards)
            != EXPECTED_AUDIT
            or candidate_worlds > BASE_MAX_CANDIDATE_WORLDS):
        raise ControllerRefused("Stage-C label schedule/work ceiling drift")
    payload = {
        "shards": shards,
        "shard_count": len(shards),
        "states_per_shard": STATES_PER_SHARD,
        "split_shards": SPLIT_SHARDS,
        "state_count": EXPECTED_STATES,
        "audit_state_count": EXPECTED_AUDIT,
        "candidate_worlds": candidate_worlds,
        "base_all_optional_candidate_world_ceiling":
            BASE_MAX_CANDIDATE_WORLDS,
        "sampler_attempt_cap": sum(
            shard["sampler_attempt_cap"] for shard in shards),
        "underfill_action": "TERMINAL_HOLD_NO_EXTENSION",
        "report_labels_sealed_from_training": True,
    }
    payload["schedule_sha256"] = sha256_bytes(canonical_json(payload))
    return payload


def validate_capacity_evidence(
    capacity_packet_path: Path, expected_capacity_packet_sha256: str,
    capacity_result_path: Path, expected_capacity_result_sha256: str,
    capacity_result_review_record: Path, *,
    state_set: Mapping[str, object], state_set_sha256: str,
    verification_sha256: str, schedule: Mapping[str, object], smoke: bool,
) -> tuple[dict, dict, dict]:
    """Recompute the outcome-free capacity gate before packet construction."""
    capacity = _capacity_module()
    try:
        expected_preflight_schedule = capacity.build_capacity_schedule(state_set)
        expected_runtime_sources = capacity.runtime_sources()
    except capacity.CapacityRefused as exc:
        raise ControllerRefused(f"capacity-controller validation failed: {exc}") \
            from exc
    if sha256_file(capacity_packet_path) != expected_capacity_packet_sha256:
        raise ControllerRefused("capacity-controller external SHA-256 drift")
    packet = load_json(capacity_packet_path)
    producer = packet.get("producer", {})
    parents = packet.get("parents", {})
    authority = packet.get("authority", {})
    if (packet.get("schema") != CAPACITY_PACKET_SCHEMA
            or packet.get("packet_id") != CAPACITY_PACKET_ID
            or packet.get("run_id") != CAPACITY_RUN_ID
            or packet.get("packet_sha256")
            != capacity.self_hash(packet, "packet_sha256")
            or producer.get("git") != _git("rev-parse", "HEAD")
            or (not smoke and (producer.get("tree_dirty") is not False
                               or producer.get("promotable") is not True))
            or parents.get("state_set", {}).get("external_sha256")
            != state_set_sha256
            or parents.get("capture_verification", {}).get("external_sha256")
            != verification_sha256
            or packet.get("label_schedule", {}).get("schedule_sha256")
            != schedule["schedule_sha256"]
            or packet.get("label_schedule", {}).get("candidate_worlds")
            != schedule["candidate_worlds"]
            or packet.get("preflight_schedule")
            != expected_preflight_schedule
            or packet.get("runtime_sources") != expected_runtime_sources
            or capacity.forbidden_outcome_paths(packet)
            or authority.get("outcomes_computed") is not False
            or authority.get("outcomes_retained") is not False
            or authority.get("label_controller_freeze_authorized") is not False
            or authority.get("labels_authorized") is not False
            or authority.get("training_authorized") is not False):
        raise ControllerRefused("capacity-controller identity/authority drift")
    try:
        result = capacity.validate_result(
            capacity_result_path, expected_capacity_result_sha256,
            packet, expected_capacity_packet_sha256, state_set)
    except capacity.CapacityRefused as exc:
        raise ControllerRefused(f"capacity-result validation failed: {exc}") \
            from exc
    if (result.get("schema") != CAPACITY_RESULT_SCHEMA
            or result.get("capacity_pass") is not True
            or result.get("label_controller_freeze_authorized") is not True
            or result.get("labels_authorized") is not False
            or result.get("training_authorized") is not False):
        raise ControllerRefused("capacity-result does not authorize packet review")
    try:
        review = capacity.validate_result_review(
            capacity_result_review_record, result,
            expected_capacity_result_sha256)
    except capacity.CapacityRefused as exc:
        raise ControllerRefused(f"capacity-result review failed: {exc}") from exc
    if review.get("schema") != CAPACITY_RESULT_REVIEW_SCHEMA:
        raise ControllerRefused("capacity-result review schema drift")
    return packet, result, review


def build_packet(
    capture_controller_path: Path,
    state_set_path: Path, state_set_sha256: str,
    verification_path: Path, verification_sha256: str,
    state_set_review_record: Path,
    capacity_packet_path: Path, capacity_packet_sha256: str,
    capacity_result_path: Path, capacity_result_sha256: str,
    capacity_result_review_record: Path, *, smoke: bool,
) -> dict:
    capture = validate_capture_controller(capture_controller_path)
    state_set, verification, state_review = validate_state_set(
        state_set_path, state_set_sha256,
        verification_path, verification_sha256,
        state_set_review_record)
    schedule = build_schedule(state_set)
    capacity_packet, capacity_result, capacity_review = \
        validate_capacity_evidence(
            capacity_packet_path, capacity_packet_sha256,
            capacity_result_path, capacity_result_sha256,
            capacity_result_review_record,
            state_set=state_set, state_set_sha256=state_set_sha256,
            verification_sha256=verification_sha256,
            schedule=schedule, smoke=smoke)
    packet = {
        "schema": SCHEMA,
        "packet_id": PACKET_ID,
        "run_id": RUN_ID,
        "producer": producer_identity(smoke=smoke),
        "parents": {
            "base_stage_c_sha256": CAPTURE_CTRL.BASE_PACKET_SHA256,
            "rebind_sha256": CAPTURE_CTRL.REBIND_PACKET_SHA256,
            "capture_controller": {
                "external_sha256": CAPTURE_CONTROLLER_SHA256,
                "internal_sha256": capture["packet_sha256"],
                "source_git": CAPTURE_SOURCE_GIT,
            },
            "state_set": {
                "logical_path": str(state_set_path.relative_to(REPO)),
                "external_sha256": state_set_sha256,
                "internal_sha256": state_set["dataset_sha256"],
                "states_sha256": state_set["states_sha256"],
                "audit_state_ids_sha256": state_set[
                    "report_audit_state_ids_sha256"],
                "review_claim": state_review,
            },
            "capture_verification": {
                "logical_path": str(verification_path.relative_to(REPO)),
                "external_sha256": verification_sha256,
                "internal_sha256": verification["verification_sha256"],
            },
            "capacity_preflight": {
                "controller_logical_path": str(
                    capacity_packet_path.relative_to(REPO)),
                "controller_external_sha256": capacity_packet_sha256,
                "controller_internal_sha256": capacity_packet[
                    "packet_sha256"],
                "result_logical_path": str(
                    capacity_result_path.relative_to(REPO)),
                "result_external_sha256": capacity_result_sha256,
                "result_internal_sha256": capacity_result["result_sha256"],
                "review_claim": capacity_review,
                "capacity_pass": True,
                "outcomes_retained": False,
            },
        },
        "runtime_mode": CAPTURE_CTRL.require_runtime_mode(),
        "runtime_sources": runtime_sources(),
        "schedule": schedule,
        "label_contract": {
            "utility": "acting-team-signed-level-utility",
            "continuation": "non-recursive HeuristicBot",
            "ordinary_worlds": [LABEL.ORDINARY_SELECTION_WORLDS,
                                LABEL.ORDINARY_REPORT_WORLDS],
            "hard_tail_selection_worlds": LABEL.HARD_SELECTION_WORLDS,
            "hard_tail_report_worlds": LABEL.HARD_REPORT_WORLDS,
            "selection_and_report_disjoint": True,
            "report_never_selects": True,
            "strict_sampler_attempt_factor": LABEL.SAMPLE_ATTEMPT_FACTOR,
            "partial_state_publishes_no_label": True,
            "raw_attacker_points_and_signed_utilities_preserved": True,
            "recursive_mc_continuation_rollouts": 0,
        },
        "audit_contract_amendment": {
            "reason": (
                "candidate0, audit-selection winner and frozen label choice "
                "may be three distinct identities"
            ),
            "selection_worlds_all_candidates": LABEL.AUDIT_SELECTION_WORLDS,
            "base_report_geometry": {
                "logical_actions": 2, "worlds": 600,
                "candidate_worlds": 1200,
                "identified_both_estimands": False,
            },
            "successor_report_geometry": {
                "slot_roles": ["candidate0", "audit_selection_winner",
                               "frozen_label_choice"],
                "logical_actions": LABEL.AUDIT_REPORT_ACTIONS,
                "worlds": LABEL.AUDIT_REPORT_WORLDS,
                "candidate_worlds": LABEL.AUDIT_REPORT_CANDIDATE_WORLDS,
                "duplicate_identities_consume_work": True,
                "identified_both_estimands": True,
            },
            "total_candidate_world_ceiling_changed": False,
            "v11_recall_primary": (
                "live ballot plus one V11 proposal versus live ballot plus "
                "one frozen random diversifier on trigger-matched REPORT rows"
            ),
            "structured_recall_diagnostic_only": True,
            "multiple_proposal_sources_never_compared_to_one_control_as_if_"
            "equal_budget": True,
        },
        "split_boundary": {
            "design_and_calib_labels_publish_to_training_manifest": True,
            "report_labels_publish_to_separate_sealed_manifest": True,
            "training_or_seed_selection_may_read_report": False,
            "report_open_authorized": False,
        },
        "result_contract": {
            "receipt": f"server/runs/logs/{RUN_ID}/label-receipt.json",
            "shards": [f"server/runs/logs/{RUN_ID}/{shard['split'].lower()}/"
                       f"shard-{shard['local_shard']:02d}.json"
                       for shard in schedule["shards"]],
            "aggregate": f"server/runs/logs/{RUN_ID}/label-aggregate.json",
            "required_complete_states": EXPECTED_STATES,
            "required_audit_states": EXPECTED_AUDIT,
            "exact_candidate_worlds": schedule["candidate_worlds"],
            "max_candidate_worlds": BASE_MAX_CANDIDATE_WORLDS,
            "max_sampler_attempts": schedule["sampler_attempt_cap"],
            "one_shot_admission": require_admission_slot_ignored(),
            "shard_admission_slots": require_shard_admission_slots_ignored(),
            "shard_retry_after_any_sampling": "TERMINAL_HOLD_NO_RETRY",
            "any_refusal_status": "TERMINAL_HOLD_NO_EXTENSION",
        },
        "commands": {
            "admit_once": [
                "{python}",
                "server/scripts/teacher_stage_c_label_runtime.py", "admit",
                "--expected-git", "{git}",
                "--controller-packet", CONTROLLER_PACKET_PATH,
                "--expected-controller-packet-sha256", "{packet_sha256}",
                "--controller-review-record", "{controller_review_record}",
                "--state-set-review-record", "{state_set_review_record}",
                "--out", f"server/runs/logs/{RUN_ID}/label-receipt.json",
            ],
            "run_shards": [{
                "index": shard["index"],
                "split": shard["split"],
                "command": [
                    "{python}",
                    "server/scripts/teacher_stage_c_label_runtime.py",
                    "run-shard",
                    "--expected-git", "{git}",
                    "--controller-packet", CONTROLLER_PACKET_PATH,
                    "--expected-controller-packet-sha256", "{packet_sha256}",
                    "--label-receipt",
                    f"server/runs/logs/{RUN_ID}/label-receipt.json",
                    "--expected-label-receipt-sha256", "{receipt_sha256}",
                    "--controller-review-record", "{controller_review_record}",
                    "--state-set-review-record", "{state_set_review_record}",
                    "--shard-index", str(shard["index"]),
                    "--progress-every", "1",
                    "--out", f"server/runs/logs/{RUN_ID}/"
                    f"{shard['split'].lower()}/"
                    f"shard-{shard['local_shard']:02d}.json",
                ],
            } for shard in schedule["shards"]],
            "aggregate": [
                "{python}",
                "server/scripts/teacher_stage_c_label_runtime.py",
                "aggregate",
                "--expected-git", "{git}",
                "--controller-packet", CONTROLLER_PACKET_PATH,
                "--expected-controller-packet-sha256", "{packet_sha256}",
                "--label-receipt",
                f"server/runs/logs/{RUN_ID}/label-receipt.json",
                "--expected-label-receipt-sha256", "{receipt_sha256}",
                "--controller-review-record", "{controller_review_record}",
                "--state-set-review-record", "{state_set_review_record}",
                "--shards", *[
                    f"server/runs/logs/{RUN_ID}/{shard['split'].lower()}/"
                    f"shard-{shard['local_shard']:02d}.json"
                    for shard in schedule["shards"]
                ],
                "--out", f"server/runs/logs/{RUN_ID}/label-aggregate.json",
            ],
        },
        "authority": {
            "score_free": True,
            "worlds_sampled": False,
            "outcomes_computed": False,
            "labels_computed": False,
            "one_label_execution_authorized": False,
            "training_authorized": False,
            "report_open_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
            "production_deployment": False,
        },
    }
    packet["packet_sha256"] = self_hash(packet)
    return packet


def expected_review_claim(packet: Mapping[str, object], packet_sha256: str) -> dict:
    schedule = packet["schedule"]
    source = packet["runtime_sources"]
    parents = packet["parents"]
    capacity = parents["capacity_preflight"]
    return {
        "schema": REVIEW_SCHEMA,
        "git": packet["producer"]["git"],
        "controller_script_sha256": packet["producer"][
            "controller_script_sha256"],
        "runtime_script_sha256": source[
            "server/scripts/teacher_stage_c_label_runtime.py"],
        "packet_sha256": packet_sha256,
        "capture_controller_sha256": CAPTURE_CONTROLLER_SHA256,
        "state_set_sha256": parents["state_set"]["external_sha256"],
        "capture_verification_sha256": parents[
            "capture_verification"]["external_sha256"],
        "state_set_review_schema": STATE_SET_REVIEW_SCHEMA,
        "states": EXPECTED_STATES,
        "design_states": EXPECTED_SPLITS["DESIGN"],
        "calib_states": EXPECTED_SPLITS["CALIB"],
        "report_states": EXPECTED_SPLITS["REPORT"],
        "play_states": EXPECTED_PLAY,
        "bury_states": EXPECTED_BURY,
        "audit_states": EXPECTED_AUDIT,
        "label_shards": LABEL_SHARDS,
        "states_per_shard": STATES_PER_SHARD,
        "schedule_sha256": schedule["schedule_sha256"],
        "exact_candidate_worlds": schedule["candidate_worlds"],
        "max_candidate_worlds": BASE_MAX_CANDIDATE_WORLDS,
        "max_sampler_attempts": schedule["sampler_attempt_cap"],
        "audit_report_actions": LABEL.AUDIT_REPORT_ACTIONS,
        "audit_report_worlds": LABEL.AUDIT_REPORT_WORLDS,
        "audit_report_candidate_worlds": LABEL.AUDIT_REPORT_CANDIDATE_WORLDS,
        "report_labels_sealed_from_training": True,
        "shard_admission_slots": LABEL_SHARDS,
        "capacity_packet_sha256": capacity["controller_external_sha256"],
        "capacity_result_sha256": capacity["result_external_sha256"],
        "capacity_result_review_schema": CAPACITY_RESULT_REVIEW_SCHEMA,
        "capacity_pass": True,
        "worlds_sampled_before_review": 0,
        "outcomes_computed_before_review": False,
        "independent_review": True,
        "one_label_execution_authorized": True,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }


def publish_exclusive(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise ControllerRefused(f"refusing existing output: {path}")
    data = canonical_json(payload)
    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(partial, path)
    except BaseException:
        try:
            partial.unlink()
        except OSError:
            pass
        raise


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("freeze", "verify"):
        child = commands.add_parser(name)
        child.add_argument("--capture-controller", required=True)
        child.add_argument("--state-set", required=True)
        child.add_argument("--expected-state-set-sha256", required=True)
        child.add_argument("--capture-verification", required=True)
        child.add_argument("--expected-capture-verification-sha256", required=True)
        child.add_argument("--state-set-review-record", required=True)
        child.add_argument("--capacity-controller", required=True)
        child.add_argument("--expected-capacity-controller-sha256", required=True)
        child.add_argument("--capacity-result", required=True)
        child.add_argument("--expected-capacity-result-sha256", required=True)
        child.add_argument("--capacity-result-review-record", required=True)
        child.add_argument("--out", required=True)
        if name == "freeze":
            child.add_argument("--smoke", action="store_true")
        else:
            child.add_argument("--expected-packet-sha256", required=True)
    return root


def main() -> int:
    args = parser().parse_args()
    out = Path(args.out).resolve()
    packet = build_packet(
        Path(args.capture_controller).resolve(),
        Path(args.state_set).resolve(), args.expected_state_set_sha256,
        Path(args.capture_verification).resolve(),
        args.expected_capture_verification_sha256,
        Path(args.state_set_review_record).resolve(),
        Path(args.capacity_controller).resolve(),
        args.expected_capacity_controller_sha256,
        Path(args.capacity_result).resolve(),
        args.expected_capacity_result_sha256,
        Path(args.capacity_result_review_record).resolve(),
        smoke=bool(getattr(args, "smoke", False)),
    )
    if args.command == "freeze":
        if out != (REPO / CONTROLLER_PACKET_PATH).resolve() and not args.smoke:
            raise ControllerRefused("real label-controller packet path drift")
        publish_exclusive(out, packet)
    else:
        if (not is_regular_unlinked(out)
                or sha256_file(out) != args.expected_packet_sha256
                or load_json(out) != packet):
            raise ControllerRefused("label-controller packet verification drift")
    print(json.dumps({
        "status": "VERIFIED" if args.command == "verify" else "FROZEN",
        "path": str(out),
        "sha256": sha256_file(out),
        "internal_sha256": packet["packet_sha256"],
        "states": packet["schedule"]["state_count"],
        "candidate_worlds": packet["schedule"]["candidate_worlds"],
        "labels_authorized": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ControllerRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        raise SystemExit(2)
