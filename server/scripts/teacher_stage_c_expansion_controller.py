#!/usr/bin/env python3
"""Freeze the first larger, split-safe Stage-C Teacher label packet.

The original Stage-C capture retained far more score-free states than its
2,048-row first tranche.  This controller deterministically spends that
already-captured supply without opening an outcome:

* retain every original DESIGN/CALIB row so 1,536 reviewed labels can be
  reused;
* add 5,504 new DESIGN/CALIB rows for one finite label execution; and
* seal a third 512-row REPORT tranche after excluding both earlier REPORT
  populations.

Only the 7,040 DESIGN/CALIB states are written to the training state-set.
The third REPORT remains represented by hashes and counts until model
selection has completed.  Freezing or verifying this packet samples no world,
computes no label or prediction, and grants no execution authority.  One
external review may authorize the finite 16-shard label run.
"""
from __future__ import annotations

import argparse
import copy
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
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import teacher_stage_c_capture_runtime as CAPTURE  # noqa: E402
import teacher_stage_c_fresh_report_controller as FRESH  # noqa: E402
import teacher_stage_c_label_controller as BASE  # noqa: E402
import teacher_stage_c_label_runtime as LABEL  # noqa: E402
from shengji.rl import stage_c_expansion as EXP  # noqa: E402


SCHEMA = "teacher-stage-c-expanded-label-controller-v1"
PACKET_ID = "teacher-v3-hard-tail-stage-c-expanded-label-controller-v1"
RUN_ID = "teacher-v3-hard-tail-stage-c-expanded-labels-v1"
CONTROLLER_RUN_ID = \
    "teacher-v3-hard-tail-stage-c-expanded-label-controller-v1"
CONTROLLER_PACKET_PATH = (
    f"server/runs/logs/{CONTROLLER_RUN_ID}/controller_packet.json"
)
STATE_SET_RUN_ID = "teacher-v3-hard-tail-stage-c-expanded-selection-v1"
STATE_SET_PATH = f"server/runs/logs/{STATE_SET_RUN_ID}/training-state-set.json"

REVIEW_SCHEMA = "teacher-stage-c-expanded-label-controller-review-v1"
REVIEW_MARKER = "TEACHER_STAGE_C_EXPANDED_LABEL_CONTROLLER_V1_REVIEW "
RECEIPT_SCHEMA = "teacher-stage-c-expanded-label-receipt-v1"
ADMISSION_SCHEMA = "teacher-stage-c-expanded-label-admission-v1"
SHARD_ADMISSION_SCHEMA = "teacher-stage-c-expanded-label-shard-admission-v1"
SHARD_SCHEMA = "teacher-stage-c-expanded-label-shard-v1"
AGGREGATE_SCHEMA = "teacher-stage-c-expanded-label-aggregate-v1"

CAPTURE_CTRL = BASE.CAPTURE_CTRL
CAPTURE_CONTROLLER_SHA256 = BASE.CAPTURE_CONTROLLER_SHA256
CAPTURE_STATE_SET_SHA256 = FRESH.CAPTURE_STATE_SET_SHA256
CAPTURE_VERIFICATION_SHA256 = FRESH.CAPTURE_VERIFICATION_SHA256
FRESH_REPORT_PACKET_SHA256 = (
    "7dd0caacff9e61e4f963ba0afa56c3eca81c05abd9da2eaaba4ece8284870e69"
)
EVIDENCE_GIT = BASE.CAPTURE_SOURCE_GIT

LABEL_SHARDS = 16
SPLIT_SHARDS = {"DESIGN": 12, "CALIB": 4}
EXPECTED_STATES = EXP.NEW_LABEL_STATES
TRAINING_LABEL_STATES = EXP.NEW_LABEL_STATES
REUSED_LABEL_STATES = EXP.REUSED_TRAINING_STATES
SEALED_REPORT_STATES = EXP.SEALED_REPORT_STATES
COMPUTE_FIDELITY_GATE = False
MAX_CONCURRENT_SHARDS = 8

SOURCE_PATHS = (
    "server/scripts/teacher_stage_c_expansion_controller.py",
    "server/scripts/teacher_stage_c_expanded_label_runtime.py",
    "server/scripts/teacher_stage_c_expanded_label_supervisor.py",
    "server/scripts/teacher_stage_c_label_runtime.py",
    "server/scripts/teacher_stage_c_label_controller.py",
    "server/scripts/teacher_stage_c_label_capacity.py",
    "server/scripts/teacher_stage_c_capture_controller.py",
    "server/scripts/teacher_stage_c_capture_runtime.py",
    "server/scripts/teacher_stage_c_fresh_report_controller.py",
    "server/shengji/rl/stage_c_expansion.py",
)


class ExpansionControllerRefused(RuntimeError):
    """An expansion parent, selection, work budget or authority drifted."""


# The shared label runtime expects ControllerRefused from its selected
# controller.  Keep one identity so its narrow exception translations work.
ControllerRefused = ExpansionControllerRefused


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


def self_hash(value: Mapping[str, object], field: str = "packet_sha256") \
        -> str:
    return sha256_bytes(canonical_json({
        key: item for key, item in value.items() if key != field
    }))


def manifest_hash(value: object) -> str:
    return sha256_bytes(canonical_json(value))


def is_regular_unlinked(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not path.is_symlink())


def load_json(path: Path) -> dict:
    if not is_regular_unlinked(path):
        raise ExpansionControllerRefused(
            f"JSON parent is not regular/unlinked: {path}")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ExpansionControllerRefused(
            f"cannot read JSON parent {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ExpansionControllerRefused("JSON parent root is not an object")
    return value


def _git(*args: str, cwd: Path = REPO) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def marker_claim(path: Path, marker: str) -> dict:
    if not is_regular_unlinked(path):
        raise ExpansionControllerRefused(
            "review record is not regular/unlinked")
    matches = [line[len(marker):] for line in path.read_text().splitlines()
               if line.startswith(marker)]
    if len(matches) != 1:
        raise ExpansionControllerRefused(
            f"review record must contain exactly one {marker.strip()} marker")
    try:
        claim = json.loads(matches[0])
    except ValueError as exc:
        raise ExpansionControllerRefused("review marker is invalid JSON") \
            from exc
    if not isinstance(claim, dict):
        raise ExpansionControllerRefused("review marker is not an object")
    return claim


def admission_slot_logical_path() -> str:
    return f"server/runs/locks/{RUN_ID}.consumed.json"


def shard_admission_logical_path(index: int) -> str:
    if not 0 <= index < LABEL_SHARDS:
        raise ExpansionControllerRefused("expanded shard index drift")
    return f"server/runs/locks/{RUN_ID}.shard-{index:02d}.consumed.json"


def _require_ignored(logical: str) -> str:
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", logical], cwd=REPO,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ExpansionControllerRefused(
            f"expanded one-shot path is not Git-ignored: {logical}")
    return logical


def require_admission_slot_ignored() -> dict:
    logical = _require_ignored(admission_slot_logical_path())
    return {"logical_path": logical, "gitignored": True}


def require_shard_admission_slots_ignored() -> list[str]:
    return [_require_ignored(shard_admission_logical_path(index))
            for index in range(LABEL_SHARDS)]


def runtime_sources() -> dict[str, str]:
    values = {}
    for logical in SOURCE_PATHS:
        path = REPO / logical
        if not is_regular_unlinked(path):
            raise ExpansionControllerRefused(
                f"expanded runtime source unavailable: {logical}")
        values[logical] = sha256_file(path)
    return dict(sorted(values.items()))


def producer_identity(*, smoke: bool) -> dict:
    require_admission_slot_ignored()
    require_shard_admission_slots_ignored()
    dirty = bool(_git("status", "--porcelain", "--untracked-files=all"))
    if dirty and not smoke:
        raise ExpansionControllerRefused(
            "real expanded-controller freeze refuses dirty tree")
    return {
        "git": _git("rev-parse", "HEAD"),
        "tree_dirty": dirty,
        "promotable": not smoke,
        "controller_script_sha256": sha256_file(SCRIPT),
    }


def _evidence_paths(evidence_repo: Path) -> dict[str, Path]:
    return {
        "capture_controller": evidence_repo / FRESH.CAPTURE_PACKET_PATH,
        "capture_state_set": evidence_repo / FRESH.CAPTURE_STATE_SET_PATH,
        "capture_verification": evidence_repo /
            FRESH.CAPTURE_VERIFICATION_PATH,
        "capture_shards": evidence_repo / FRESH.CAPTURE_SHARD_DIRECTORY,
        # The capture worktree owns the 24 immutable reservoir shards.  The
        # already-reviewed fresh packet is staged in this downstream clean
        # worktree and is independently byte-pinned below.
        "fresh_report_packet": REPO / FRESH.PACKET_PATH,
    }


def _capture_shards(
    *, evidence_repo: Path, capture_packet: Mapping[str, object],
    state_set: Mapping[str, object],
) -> list[dict]:
    inputs = state_set.get("shard_inputs")
    if not isinstance(inputs, list) or len(inputs) != 24:
        raise ExpansionControllerRefused("capture shard manifest drift")
    receipt_sha256 = str(state_set.get("capture_receipt_sha256"))
    directory = _evidence_paths(evidence_repo)["capture_shards"]
    result = []
    for index, expected in enumerate(inputs):
        path = directory / f"shard-{index:02d}.json"
        if (not isinstance(expected, dict)
                or expected.get("index") != index
                or not is_regular_unlinked(path)
                or sha256_file(path) != expected.get("sha256")):
            raise ExpansionControllerRefused(
                f"capture shard {index} external identity drift")
        shard = load_json(path)
        try:
            CAPTURE.validate_shard(
                shard, dict(capture_packet), receipt_sha256, index)
        except CAPTURE.RuntimeRefused as exc:
            raise ExpansionControllerRefused(
                f"capture shard {index} semantic drift: {exc}") from exc
        material = copy.deepcopy(shard)
        material["external_sha256"] = expected["sha256"]
        result.append(material)
    return result


def validate_evidence(
    *, evidence_repo: Path, state_set_review_record: Path,
    fresh_report_review_record: Path,
) -> tuple[dict, dict, dict, dict, list[dict], list[dict]]:
    evidence_repo = evidence_repo.resolve()
    if (_git("rev-parse", "HEAD", cwd=evidence_repo) != EVIDENCE_GIT
            or _git("status", "--porcelain", "--untracked-files=no",
                    cwd=evidence_repo)):
        raise ExpansionControllerRefused("expanded evidence Git drift")
    paths = _evidence_paths(evidence_repo)
    try:
        capture = BASE.validate_capture_controller(
            paths["capture_controller"])
        state_set, verification, state_review = BASE.validate_state_set(
            paths["capture_state_set"], CAPTURE_STATE_SET_SHA256,
            paths["capture_verification"], CAPTURE_VERIFICATION_SHA256,
            state_set_review_record)
    except BASE.ControllerRefused as exc:
        raise ExpansionControllerRefused(
            f"expanded capture parent refused: {exc}") from exc
    shards = _capture_shards(
        evidence_repo=evidence_repo, capture_packet=capture,
        state_set=state_set)

    fresh_path = paths["fresh_report_packet"]
    if sha256_file(fresh_path) != FRESH_REPORT_PACKET_SHA256:
        raise ExpansionControllerRefused("fresh REPORT packet SHA drift")
    fresh_packet = load_json(fresh_path)
    fresh_claim = marker_claim(
        fresh_report_review_record, FRESH.REVIEW_MARKER)
    if (fresh_packet.get("schema") != FRESH.SCHEMA
            or fresh_packet.get("packet_sha256")
            != FRESH.self_hash(fresh_packet, "packet_sha256")
            or fresh_claim != FRESH.expected_review_claim(
                fresh_packet, FRESH_REPORT_PACKET_SHA256)):
        raise ExpansionControllerRefused(
            "fresh REPORT packet/review identity drift")
    report_shards = [shard for shard in shards
                     if shard.get("split") == "REPORT"]
    try:
        sealed, current_fresh = FRESH.sealed_selection(
            capture_packet=capture, state_set=state_set,
            shards=report_shards)
    except FRESH.FreshReportRefused as exc:
        raise ExpansionControllerRefused(
            f"fresh REPORT recomputation refused: {exc}") from exc
    if sealed != fresh_packet.get("sealed_selection"):
        raise ExpansionControllerRefused(
            "fresh REPORT sealed selection recomputation drift")
    return (capture, state_set, verification, state_review,
            shards, current_fresh)


def build_training_state_set(
    *, selection: Mapping[str, object], evidence_repo: Path,
    capture_state_set: Mapping[str, object],
) -> dict:
    states = [copy.deepcopy(state) for state in selection["states"]
              if state.get("split") in {"DESIGN", "CALIB"}]
    split_counts = Counter(str(state["split"]) for state in states)
    surface_counts = Counter(str(state["surface_type"]) for state in states)
    if (len(states) != EXP.TARGET_SPLITS["DESIGN"]
            + EXP.TARGET_SPLITS["CALIB"]
            or split_counts != {
                "DESIGN": EXP.TARGET_SPLITS["DESIGN"],
                "CALIB": EXP.TARGET_SPLITS["CALIB"],
            }
            or surface_counts != {
                "play": EXP.TARGET_SURFACES["DESIGN"]["play"]
                        + EXP.TARGET_SURFACES["CALIB"]["play"],
                "bury": EXP.TARGET_SURFACES["DESIGN"]["bury"]
                        + EXP.TARGET_SURFACES["CALIB"]["bury"],
            }
            or BASE._forbidden_label_key(states)):
        raise ExpansionControllerRefused(
            "expanded training state-set population drift")
    value = {
        "schema": "teacher-stage-c-expanded-training-state-set-v1",
        "run_id": STATE_SET_RUN_ID,
        "producer_git": _git("rev-parse", "HEAD"),
        "evidence_repo": str(evidence_repo.resolve()),
        "capture_state_set_internal_sha256": capture_state_set[
            "dataset_sha256"],
        "selection_sha256": selection["selection_sha256"],
        "full_selected_states_sha256": selection["states_sha256"],
        "states": states,
        "states_sha256": manifest_hash(states),
        "state_count": len(states),
        "split_counts": dict(split_counts),
        "surface_counts": dict(surface_counts),
        "reused_training_state_ids": list(
            selection["reused_training_state_ids"]),
        "reused_training_state_ids_sha256": selection[
            "reused_training_state_ids_sha256"],
        "new_label_state_ids": list(selection["new_label_state_ids"]),
        "new_label_state_ids_sha256": selection[
            "new_label_state_ids_sha256"],
        "sealed_report_manifest": {
            "states": SEALED_REPORT_STATES,
            "state_ids_sha256": selection[
                "sealed_report_state_ids_sha256"],
            "state_material_sha256": manifest_hash([
                state for state in selection["states"]
                if state["split"] == "REPORT"]),
            "surface_counts": EXP.TARGET_SURFACES["REPORT"],
            "state_material_published": False,
            "labels_or_predictions_computed": False,
            "report_open_authorized": False,
        },
        "labels_computed": False,
        "training_authorized": False,
        "report_open_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    value["dataset_sha256"] = self_hash(value, "dataset_sha256")
    return value


def _state_set_claim(state_set: Mapping[str, object], external_sha256: str) \
        -> dict:
    return {
        "schema": "teacher-stage-c-expanded-state-set-contract-v1",
        "external_sha256": external_sha256,
        "internal_sha256": state_set["dataset_sha256"],
        "states_sha256": state_set["states_sha256"],
        "states": state_set["state_count"],
        "new_label_states": len(state_set["new_label_state_ids"]),
        "reused_label_states": len(state_set["reused_training_state_ids"]),
        "sealed_report_states": state_set["sealed_report_manifest"]["states"],
        "labels_computed": False,
        "report_open_authorized": False,
    }


def validate_state_set(
    state_set_path: Path, expected_state_set_sha256: str,
    verification_path: Path, expected_verification_sha256: str,
    _review_record: Path,
) -> tuple[dict, dict, dict]:
    expected_path = (REPO / STATE_SET_PATH).resolve()
    if (state_set_path.resolve() != expected_path
            or sha256_file(state_set_path) != expected_state_set_sha256):
        raise ExpansionControllerRefused(
            "expanded training state-set external identity drift")
    value = load_json(state_set_path)
    states = value.get("states")
    new_ids = value.get("new_label_state_ids")
    reused_ids = value.get("reused_training_state_ids")
    if (value.get("schema")
            != "teacher-stage-c-expanded-training-state-set-v1"
            or value.get("run_id") != STATE_SET_RUN_ID
            or value.get("producer_git") != _git("rev-parse", "HEAD")
            or value.get("dataset_sha256") != self_hash(
                value, "dataset_sha256")
            or not isinstance(states, list) or len(states) != 7_040
            or value.get("states_sha256") != manifest_hash(states)
            or value.get("state_count") != 7_040
            or value.get("split_counts") != {"DESIGN": 5_632,
                                               "CALIB": 1_408}
            or value.get("surface_counts") != {"play": 6_400,
                                                 "bury": 640}
            or not isinstance(new_ids, list) or len(new_ids) != EXPECTED_STATES
            or not isinstance(reused_ids, list)
            or len(reused_ids) != REUSED_LABEL_STATES
            or value.get("new_label_state_ids_sha256")
            != manifest_hash(new_ids)
            or value.get("reused_training_state_ids_sha256")
            != manifest_hash(reused_ids)
            or set(new_ids) & set(reused_ids)
            or set(new_ids) | set(reused_ids)
            != {str(state["state_id"]) for state in states}
            or value.get("sealed_report_manifest", {}).get("states")
            != SEALED_REPORT_STATES
            or value.get("sealed_report_manifest", {}).get(
                "state_material_published") is not False
            or value.get("labels_computed") is not False
            or value.get("training_authorized") is not False
            or value.get("report_open_authorized") is not False
            or BASE._forbidden_label_key(value)):
        raise ExpansionControllerRefused(
            "expanded training state-set semantic drift")
    if (sha256_file(verification_path) != expected_verification_sha256
            or expected_verification_sha256 != CAPTURE_VERIFICATION_SHA256):
        raise ExpansionControllerRefused(
            "expanded capture verification identity drift")
    verification = load_json(verification_path)
    if verification.get("status") != "VERIFIED_STAGE_C_CAPTURE":
        raise ExpansionControllerRefused(
            "expanded capture verification status drift")
    return value, verification, _state_set_claim(
        value, expected_state_set_sha256)


def build_schedule(state_set: Mapping[str, object]) -> dict:
    states = {str(state["state_id"]): state for state in state_set["states"]}
    new_ids = set(str(value) for value in state_set["new_label_state_ids"])
    shards = []
    global_index = 0
    for split in ("DESIGN", "CALIB"):
        rows = sorted(
            (state for state in states.values()
             if state["split"] == split and state["state_id"] in new_ids),
            key=lambda state: str(state["state_id"]),
        )
        expected = (EXP.TARGET_SPLITS[split]
                    - BASE.EXPECTED_SPLITS[split])
        count = SPLIT_SHARDS[split]
        if len(rows) != expected or expected % count:
            raise ExpansionControllerRefused(
                f"expanded {split} new-label population drift")
        for local in range(count):
            selected = rows[local::count]
            state_ids = [str(state["state_id"]) for state in selected]
            candidate_worlds = sum(
                BASE._label_candidate_worlds(state, False)
                for state in selected)
            sampler_attempt_cap = sum(
                BASE._sampler_attempt_cap(state, False)
                for state in selected)
            shards.append({
                "index": global_index,
                "split": split,
                "local_shard": local,
                "partition_rule": (
                    f"sort new {split} state IDs, position modulo {count}"
                ),
                "state_count": len(selected),
                "state_ids": state_ids,
                "state_ids_sha256": manifest_hash(state_ids),
                "audit_state_ids": [],
                "candidate_worlds": candidate_worlds,
                "sampler_attempt_cap": sampler_attempt_cap,
            })
            global_index += 1
    if (len(shards) != LABEL_SHARDS
            or sum(shard["state_count"] for shard in shards)
            != EXPECTED_STATES
            or len({value for shard in shards
                    for value in shard["state_ids"]}) != EXPECTED_STATES):
        raise ExpansionControllerRefused("expanded label schedule drift")
    value = {
        "schema": "teacher-stage-c-expanded-label-schedule-v1",
        "shards": shards,
        "shard_count": LABEL_SHARDS,
        "split_shards": SPLIT_SHARDS,
        "state_count": EXPECTED_STATES,
        "reused_label_states_not_recomputed": REUSED_LABEL_STATES,
        "audit_state_count": 0,
        "candidate_worlds": sum(
            shard["candidate_worlds"] for shard in shards),
        "sampler_attempt_cap": sum(
            shard["sampler_attempt_cap"] for shard in shards),
        "max_concurrent_shards": MAX_CONCURRENT_SHARDS,
        "underfill_action": "TERMINAL_HOLD_NO_EXTENSION",
        "report_states_scheduled": 0,
    }
    value["schedule_sha256"] = manifest_hash(value)
    return value


def build_packet(
    *, state_set: Mapping[str, object], state_set_path: Path,
    state_set_external_sha256: str, evidence_repo: Path,
    capture: Mapping[str, object], verification: Mapping[str, object],
    state_review: Mapping[str, object], fresh_review_record: Path,
    smoke: bool,
) -> dict:
    schedule = build_schedule(state_set)
    producer = producer_identity(smoke=smoke)
    fresh_packet_path = _evidence_paths(evidence_repo)["fresh_report_packet"]
    fresh_packet = load_json(fresh_packet_path)
    fresh_review = marker_claim(fresh_review_record, FRESH.REVIEW_MARKER)
    packet = {
        "schema": SCHEMA,
        "packet_id": PACKET_ID,
        "run_id": RUN_ID,
        "producer": producer,
        "parents": {
            "evidence_repo": {
                "absolute_path": str(evidence_repo.resolve()),
                "git": EVIDENCE_GIT,
            },
            "capture_controller": {
                "external_sha256": CAPTURE_CONTROLLER_SHA256,
                "internal_sha256": capture["packet_sha256"],
            },
            "capture_verification": {
                "logical_path": str(
                    _evidence_paths(evidence_repo)["capture_verification"]),
                "external_sha256": CAPTURE_VERIFICATION_SHA256,
                "internal_sha256": verification["verification_sha256"],
            },
            "original_state_set_review_claim": state_review,
            "spent_fresh_report": {
                "external_sha256": FRESH_REPORT_PACKET_SHA256,
                "internal_sha256": fresh_packet["packet_sha256"],
                "review_claim_sha256": manifest_hash(fresh_review),
                "status": "RESERVED_BY_CURRENT_PROTECTED_REPORT",
            },
            "state_set": {
                "logical_path": str(state_set_path.relative_to(REPO)),
                "external_sha256": state_set_external_sha256,
                "internal_sha256": state_set["dataset_sha256"],
                "states_sha256": state_set["states_sha256"],
                "review_claim": _state_set_claim(
                    state_set, state_set_external_sha256),
            },
        },
        "runtime_mode": CAPTURE_CTRL.require_runtime_mode(),
        "runtime_sources": runtime_sources(),
        "schedule": schedule,
        "data_contract": {
            "training_states": 7_040,
            "reused_labels": REUSED_LABEL_STATES,
            "new_labels": EXPECTED_STATES,
            "sealed_report_states": SEALED_REPORT_STATES,
            "report_state_material_published": False,
            "selection_uses_labels_predictions_or_outcomes": False,
            "original_and_current_report_excluded": True,
        },
        "label_contract": {
            "recipe": "unchanged finite-work Stage-C iid-v2",
            "utility": "acting-team-signed-level-utility",
            "continuation": "non-recursive HeuristicBot",
            "sampling_with_replacement": True,
            "domain_separated_selection_and_report_streams": True,
            "audit_folds": 0,
            "recursive_mc_continuation_rollouts": 0,
            "exact_candidate_worlds": schedule["candidate_worlds"],
            "max_sampler_attempts": schedule["sampler_attempt_cap"],
        },
        "supervisor_contract": {
            "max_concurrent_shards": MAX_CONCURRENT_SHARDS,
            "heartbeat_seconds": 30,
            "handled_signals": ["SIGHUP", "SIGINT", "SIGTERM"],
            "signals_deferred_until_child_registered": True,
            "terminates_all_owned_children": True,
            "two_wave_schedule": True,
            "orphaned_workers_authorized": False,
            "retry_after_failure_authorized": False,
        },
        "result_contract": {
            "receipt": f"server/runs/logs/{RUN_ID}/label-receipt.json",
            "shards": [
                f"server/runs/logs/{RUN_ID}/{shard['split'].lower()}/"
                f"shard-{shard['local_shard']:02d}.json"
                for shard in schedule["shards"]
            ],
            "aggregate": f"server/runs/logs/{RUN_ID}/label-aggregate.json",
            "required_complete_states": EXPECTED_STATES,
            "required_audit_states": 0,
            "exact_candidate_worlds": schedule["candidate_worlds"],
            "max_candidate_worlds": schedule["candidate_worlds"],
            "max_sampler_attempts": schedule["sampler_attempt_cap"],
            "one_shot_admission": require_admission_slot_ignored(),
            "shard_admission_slots":
                require_shard_admission_slots_ignored(),
            "any_refusal_status": "TERMINAL_HOLD_NO_EXTENSION",
            "retry_after_any_sampling": False,
        },
        "commands": {
            "admit_once": [
                "{python}",
                "server/scripts/teacher_stage_c_expanded_label_runtime.py",
                "admit", "--expected-git", "{git}",
                "--controller-packet", CONTROLLER_PACKET_PATH,
                "--expected-controller-packet-sha256", "{packet_sha256}",
                "--controller-review-record", "{controller_review_record}",
                "--state-set-review-record", "{controller_review_record}",
                "--out", f"server/runs/logs/{RUN_ID}/label-receipt.json",
            ],
            "run_shards": [{
                "index": shard["index"],
                "split": shard["split"],
                "command": [
                    "{python}",
                    "server/scripts/teacher_stage_c_expanded_label_runtime.py",
                    "run-shard", "--expected-git", "{git}",
                    "--controller-packet", CONTROLLER_PACKET_PATH,
                    "--expected-controller-packet-sha256",
                    "{packet_sha256}",
                    "--label-receipt",
                    f"server/runs/logs/{RUN_ID}/label-receipt.json",
                    "--expected-label-receipt-sha256", "{receipt_sha256}",
                    "--controller-review-record",
                    "{controller_review_record}",
                    "--state-set-review-record",
                    "{controller_review_record}",
                    "--shard-index", str(shard["index"]),
                    "--progress-every", "1",
                    "--out",
                    f"server/runs/logs/{RUN_ID}/{shard['split'].lower()}/"
                    f"shard-{shard['local_shard']:02d}.json",
                ],
            } for shard in schedule["shards"]],
            "aggregate": [
                "{python}",
                "server/scripts/teacher_stage_c_expanded_label_runtime.py",
                "aggregate", "--expected-git", "{git}",
                "--controller-packet", CONTROLLER_PACKET_PATH,
                "--expected-controller-packet-sha256", "{packet_sha256}",
                "--label-receipt",
                f"server/runs/logs/{RUN_ID}/label-receipt.json",
                "--expected-label-receipt-sha256", "{receipt_sha256}",
                "--controller-review-record", "{controller_review_record}",
                "--state-set-review-record", "{controller_review_record}",
                "--shards", *[
                    f"server/runs/logs/{RUN_ID}/{shard['split'].lower()}/"
                    f"shard-{shard['local_shard']:02d}.json"
                    for shard in schedule["shards"]
                ],
                "--out", f"server/runs/logs/{RUN_ID}/label-aggregate.json",
            ],
            "supervisor_launch": [
                "{python}",
                "server/scripts/teacher_stage_c_expanded_label_supervisor.py",
                "launch", "--expected-git", "{git}",
                "--controller-packet", CONTROLLER_PACKET_PATH,
                "--expected-controller-packet-sha256", "{packet_sha256}",
                "--controller-review-record", "{controller_review_record}",
                "--label-receipt",
                f"server/runs/logs/{RUN_ID}/label-receipt.json",
                "--expected-label-receipt-sha256", "{receipt_sha256}",
                "--heartbeat-seconds", "30",
            ],
            "supervisor_verify": [
                "{python}",
                "server/scripts/teacher_stage_c_expanded_label_supervisor.py",
                "verify", "--expected-git", "{git}",
                "--controller-packet", CONTROLLER_PACKET_PATH,
                "--expected-controller-packet-sha256", "{packet_sha256}",
                "--controller-review-record", "{controller_review_record}",
                "--label-receipt",
                f"server/runs/logs/{RUN_ID}/label-receipt.json",
                "--expected-label-receipt-sha256", "{receipt_sha256}",
                "--heartbeat-seconds", "30",
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


def expected_review_claim(packet: Mapping[str, object], packet_sha256: str) \
        -> dict:
    schedule = packet["schedule"]
    state = packet["parents"]["state_set"]
    return {
        "schema": REVIEW_SCHEMA,
        "git": packet["producer"]["git"],
        "controller_script_sha256": packet["producer"][
            "controller_script_sha256"],
        "packet_sha256": packet_sha256,
        "packet_internal_sha256": packet["packet_sha256"],
        "training_state_set_sha256": state["external_sha256"],
        "training_state_set_internal_sha256": state["internal_sha256"],
        "capture_controller_sha256": CAPTURE_CONTROLLER_SHA256,
        "capture_state_set_sha256": CAPTURE_STATE_SET_SHA256,
        "capture_verification_sha256": CAPTURE_VERIFICATION_SHA256,
        "spent_fresh_report_packet_sha256": FRESH_REPORT_PACKET_SHA256,
        "training_states": 7_040,
        "reused_labels": REUSED_LABEL_STATES,
        "new_label_states": EXPECTED_STATES,
        "sealed_report_states": SEALED_REPORT_STATES,
        "report_state_material_published": False,
        "label_shards": LABEL_SHARDS,
        "max_concurrent_shards": MAX_CONCURRENT_SHARDS,
        "supervisor_script_sha256": packet["runtime_sources"][
            "server/scripts/teacher_stage_c_expanded_label_supervisor.py"],
        "supervisor_heartbeat_seconds": 30,
        "supervisor_signal_contract": packet["supervisor_contract"],
        "schedule_sha256": schedule["schedule_sha256"],
        "exact_candidate_worlds": schedule["candidate_worlds"],
        "max_sampler_attempts": schedule["sampler_attempt_cap"],
        "sampling_with_replacement": True,
        "labels_or_outcomes_computed_before_review": False,
        "independent_review": True,
        "one_label_execution_authorized": True,
        "training_authorized": False,
        "report_open_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }


def publish_exclusive(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise ExpansionControllerRefused(
            f"refusing existing expanded output: {path}")
    with partial.open("xb") as handle:
        handle.write(canonical_json(value))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(partial, path)


def _rebuild_state_set(
    *, evidence_repo: Path, state_set_review_record: Path,
    fresh_report_review_record: Path,
) -> tuple[dict, dict, dict, dict]:
    """Recompute the score-free selection from its immutable parents."""
    parents = validate_evidence(
        evidence_repo=evidence_repo,
        state_set_review_record=state_set_review_record,
        fresh_report_review_record=fresh_report_review_record)
    capture, original, verification, state_review, shards, current = parents
    retained = [state for shard in shards
                for state in shard["retained_states"]]
    try:
        selection = EXP.select_expanded_states(
            capture_packet=capture, retained_states=retained,
            original_states=original["states"],
            current_fresh_report_states=current)
    except EXP.ExpansionError as exc:
        raise ExpansionControllerRefused(
            f"expanded selection refused: {exc}") from exc
    state_set = build_training_state_set(
        selection=selection, evidence_repo=evidence_repo,
        capture_state_set=original)
    return state_set, capture, verification, state_review


def freeze(
    *, evidence_repo: Path, state_set_review_record: Path,
    fresh_report_review_record: Path, state_set_out: Path, packet_out: Path,
    smoke: bool,
) -> tuple[dict, dict]:
    state_set, capture, verification, state_review = _rebuild_state_set(
        evidence_repo=evidence_repo,
        state_set_review_record=state_set_review_record,
        fresh_report_review_record=fresh_report_review_record)
    if state_set_out.resolve() != (REPO / STATE_SET_PATH).resolve():
        raise ExpansionControllerRefused("expanded state-set output drift")
    publish_exclusive(state_set_out, state_set)
    state_set_external = sha256_file(state_set_out)
    try:
        packet = build_packet(
            state_set=state_set, state_set_path=state_set_out,
            state_set_external_sha256=state_set_external,
            evidence_repo=evidence_repo, capture=capture,
            verification=verification, state_review=state_review,
            fresh_review_record=fresh_report_review_record, smoke=smoke)
        if packet_out.resolve() != (REPO / CONTROLLER_PACKET_PATH).resolve():
            raise ExpansionControllerRefused(
                "expanded controller output drift")
        publish_exclusive(packet_out, packet)
    except BaseException:
        # A packet-free state set carries no authority, but avoid leaving an
        # apparently complete two-artifact freeze after a construction error.
        try:
            state_set_out.unlink()
        except OSError:
            pass
        raise
    return state_set, packet


def verify_frozen(
    *, evidence_repo: Path, state_set_review_record: Path,
    fresh_report_review_record: Path, state_set_path: Path,
    expected_state_set_sha256: str, packet_path: Path,
    expected_packet_sha256: str, smoke: bool,
) -> tuple[dict, dict]:
    """Rebuild both frozen artifacts without writing or granting authority."""
    if (state_set_path.resolve() != (REPO / STATE_SET_PATH).resolve()
            or packet_path.resolve()
            != (REPO / CONTROLLER_PACKET_PATH).resolve()):
        raise ExpansionControllerRefused(
            "expanded frozen-artifact path drift")
    if (not is_regular_unlinked(state_set_path)
            or sha256_file(state_set_path) != expected_state_set_sha256):
        raise ExpansionControllerRefused(
            "expanded frozen state-set external identity drift")
    if (not is_regular_unlinked(packet_path)
            or sha256_file(packet_path) != expected_packet_sha256):
        raise ExpansionControllerRefused(
            "expanded frozen packet external identity drift")

    frozen_state_set = load_json(state_set_path)
    frozen_packet = load_json(packet_path)
    rebuilt_state_set, capture, verification, state_review = \
        _rebuild_state_set(
            evidence_repo=evidence_repo,
            state_set_review_record=state_set_review_record,
            fresh_report_review_record=fresh_report_review_record)
    if (frozen_state_set != rebuilt_state_set
            or state_set_path.read_bytes()
            != canonical_json(rebuilt_state_set)
            or sha256_bytes(canonical_json(rebuilt_state_set))
            != expected_state_set_sha256):
        raise ExpansionControllerRefused(
            "expanded frozen state-set recomputation drift")

    rebuilt_packet = build_packet(
        state_set=rebuilt_state_set, state_set_path=state_set_path,
        state_set_external_sha256=expected_state_set_sha256,
        evidence_repo=evidence_repo, capture=capture,
        verification=verification, state_review=state_review,
        fresh_review_record=fresh_report_review_record, smoke=smoke)
    if (frozen_packet != rebuilt_packet
            or packet_path.read_bytes() != canonical_json(rebuilt_packet)
            or sha256_bytes(canonical_json(rebuilt_packet))
            != expected_packet_sha256):
        raise ExpansionControllerRefused(
            "expanded frozen packet recomputation drift")
    return rebuilt_state_set, rebuilt_packet


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("command", choices=("freeze", "verify"))
    root.add_argument("--evidence-repo", required=True)
    root.add_argument("--state-set-review-record", required=True)
    root.add_argument("--fresh-report-review-record", required=True)
    root.add_argument("--state-set-out", default=STATE_SET_PATH)
    root.add_argument("--packet-out", default=CONTROLLER_PACKET_PATH)
    root.add_argument("--expected-state-set-sha256")
    root.add_argument("--expected-packet-sha256")
    root.add_argument("--smoke", action="store_true")
    return root


def main() -> int:
    args = parser().parse_args()
    common = {
        "evidence_repo": Path(args.evidence_repo).resolve(),
        "state_set_review_record": Path(
            args.state_set_review_record).resolve(),
        "fresh_report_review_record": Path(
            args.fresh_report_review_record).resolve(),
    }
    if args.command == "freeze":
        if (args.expected_state_set_sha256 is not None
                or args.expected_packet_sha256 is not None):
            raise ExpansionControllerRefused(
                "freeze refuses expected output hashes")
        state_set, packet = freeze(
            **common,
            state_set_out=Path(args.state_set_out).resolve(),
            packet_out=Path(args.packet_out).resolve(), smoke=args.smoke)
        status = "FROZEN_SCORE_FREE"
    else:
        if (args.expected_state_set_sha256 is None
                or args.expected_packet_sha256 is None):
            raise ExpansionControllerRefused(
                "verify requires both expected output hashes")
        state_set, packet = verify_frozen(
            **common,
            state_set_path=Path(args.state_set_out).resolve(),
            expected_state_set_sha256=args.expected_state_set_sha256,
            packet_path=Path(args.packet_out).resolve(),
            expected_packet_sha256=args.expected_packet_sha256,
            smoke=args.smoke)
        status = "VERIFIED_SCORE_FREE"
    print(json.dumps({
        "status": status,
        "state_set_sha256": sha256_file(Path(args.state_set_out)),
        "packet_sha256": sha256_file(Path(args.packet_out)),
        "states": state_set["state_count"],
        "new_labels": packet["schedule"]["state_count"],
        "sealed_report": SEALED_REPORT_STATES,
        "review_claim": expected_review_claim(
            packet, sha256_file(Path(args.packet_out))),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ExpansionControllerRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
