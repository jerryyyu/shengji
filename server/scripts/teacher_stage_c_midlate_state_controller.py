#!/usr/bin/env python3
"""Freeze one fresh mid/late protected-Teacher state-screen packet.

The packet deliberately separates two one-shot operations.  First, a reviewed
controller may scan natural games and freeze exactly 256 decision-only
triggers.  Only after that immutable population receives its own review may a
second one-shot admission open the independent 300-world evaluation fold.

Freezing exports the already-selected eight-seed play ensemble and authenticates
all previously captured Stage-C deal seeds.  It opens no fresh game state,
model prediction, rollout, outcome, or evaluation fold.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import stat
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SCRIPT.parents[2]
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import teacher_stage_c_expanded_play_capability as CAPABILITY  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.engine import combos, fast, legal  # noqa: E402
from shengji.rl import stage_c_composition as COMPOSITION  # noqa: E402
from shengji.rl import stage_c_model as MODEL  # noqa: E402
from shengji.rl import stage_c_npnet as NPNET  # noqa: E402
from shengji.rl import stage_c_state_screen as SCREEN  # noqa: E402
from shengji.rl import stage_c_training as TRAIN  # noqa: E402


SCHEMA = "teacher-stage-c-midlate-state-screen-controller-v1"
PACKET_ID = "teacher-v3-stage-c-midlate-state-screen-controller-v1"
RUN_ID = "teacher-v3-stage-c-midlate-state-screen-v1"
PACKET_PATH = f"server/runs/logs/{PACKET_ID}/controller-packet.json"
MODEL_DIR = f"server/runs/logs/{RUN_ID}/models"
MODEL_PATHS = tuple(
    f"{MODEL_DIR}/seed-{seed}.npz" for seed in MODEL.TRAINING_SEEDS)
POPULATION_PATH = f"server/runs/logs/{RUN_ID}/selection-population.json"
RESULT_PATH = f"server/runs/logs/{RUN_ID}/state-screen-result.json"
SELECTION_ADMISSION_PATH = \
    f"server/runs/locks/{RUN_ID}.selection.consumed.json"
EVALUATION_ADMISSION_PATH = \
    f"server/runs/locks/{RUN_ID}.evaluation.consumed.json"

SOURCE_REVIEW_SCHEMA = \
    "teacher-stage-c-midlate-state-screen-source-review-v1"
SOURCE_REVIEW_MARKER = \
    "TEACHER_STAGE_C_MIDLATE_STATE_SCREEN_SOURCE_V1_REVIEW "
SOURCE_REVIEW_GIT = \
    "c9fa22b1abeb595b7e5083f37cc5d7cb676f82e3"
REVIEW_SCHEMA = "teacher-stage-c-midlate-state-screen-controller-review-v1"
REVIEW_MARKER = \
    "TEACHER_STAGE_C_MIDLATE_STATE_SCREEN_CONTROLLER_V1_REVIEW "
SELECTION_REVIEW_SCHEMA = \
    "teacher-stage-c-midlate-state-screen-selection-review-v1"
SELECTION_REVIEW_MARKER = \
    "TEACHER_STAGE_C_MIDLATE_STATE_SCREEN_SELECTION_V1_REVIEW "
RESULT_REVIEW_SCHEMA = \
    "teacher-stage-c-midlate-state-screen-result-review-v1"
RESULT_REVIEW_MARKER = \
    "TEACHER_STAGE_C_MIDLATE_STATE_SCREEN_RESULT_V1_REVIEW "

SEED0 = 188_000_000
SCAN_DEALS = 16_384
PROGRESS_EVERY_SCANNED = 25
PROGRESS_EVERY_EVALUATED = 4
V11_PATH = "server/snapshots_v11pair/ep07.npz"
V11_SHA256 = (
    "cd89d6ed7e9d5f798d69ce546107c4dfbef682c5385de39af527026e39e1c003"
)
# These are prior Stage-C whole-game/preflight populations.  The complete
# captured-state reservoir is added independently by ``forbidden_deal_seeds``.
PRIOR_STAGE_C_RANGES = (
    (180_000_000, 4), (181_000_000, 2_048),
    (184_000_000, 4), (185_000_000, 2_048),
    (186_000_000, 4), (186_500_000, 4), (187_000_000, 2_048),
)

RUNTIME_SCRIPT_PATH = \
    "server/scripts/teacher_stage_c_midlate_state_runtime.py"
SOURCE_PATHS = (
    "server/scripts/teacher_stage_c_midlate_state_controller.py",
    RUNTIME_SCRIPT_PATH,
    "server/scripts/teacher_stage_c_midlate_state_capture_runtime.py",
    "server/scripts/teacher_stage_c_midlate_state_screen_runtime.py",
    "server/shengji/rl/stage_c_state_capture.py",
    "server/shengji/rl/stage_c_state_screen.py",
    "server/shengji/rl/stage_c_candidates.py",
    "server/shengji/rl/stage_c_composition.py",
    "server/shengji/rl/stage_c_npnet.py",
    "server/shengji/rl/npnet.py",
    "server/scripts/teacher_stage_c_capture_runtime.py",
    "server/scripts/teacher_stage_c_label_runtime.py",
)


class MidlateStateControllerRefused(RuntimeError):
    """A reviewed parent, source, export, packet, or authority drifted."""


canonical_json = NPNET.canonical_json
sha256_file = NPNET.sha256_file


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def self_hash(value: Mapping[str, object], field: str) -> str:
    return sha256_bytes(canonical_json({
        key: item for key, item in value.items() if key != field
    }))


def manifest_hash(value: object) -> str:
    return sha256_bytes(canonical_json(value))


def is_sha256(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value))


def is_regular_unlinked(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not path.is_symlink())


def load_json(path: Path) -> dict:
    if not is_regular_unlinked(path):
        raise MidlateStateControllerRefused(
            f"input is not regular/unlinked: {path}")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise MidlateStateControllerRefused(
            f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise MidlateStateControllerRefused(
            f"JSON root is not an object: {path}")
    return value


def publish_exclusive(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise MidlateStateControllerRefused(
            f"refusing existing output: {path}")
    with partial.open("xb") as handle:
        handle.write(canonical_json(payload))
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.link(partial, path, follow_symlinks=False)
    except FileExistsError as exc:
        raise MidlateStateControllerRefused(
            f"refusing raced output: {path}") from exc
    partial.unlink()


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
            raise MidlateStateControllerRefused(
                f"mid/late screen source unavailable: {logical}")
        result[logical] = sha256_file(path)
    return result


def runtime_contract() -> dict:
    routed = (bool(fast.HAVE_FAST)
              and combos.decompose is fast.decompose
              and legal.beats is fast.beats)
    binary = getattr(fast, "_fast", None)
    binary_path = None if binary is None else Path(binary.__file__).resolve()
    python_path = Path(sys.executable)
    python_resolved = python_path.resolve()
    if (os.environ.get("SHENGJI_FAST") != "1" or not routed
            or binary_path is None or not is_regular_unlinked(binary_path)
            or not is_regular_unlinked(python_resolved)):
        raise MidlateStateControllerRefused(
            "mid/late screen requires the compiled live route and regular Python")
    return {
        "host": platform.node(),
        "python": platform.python_version(),
        "python_executable": str(python_path),
        "python_executable_resolved": str(python_resolved),
        "python_executable_sha256": sha256_file(python_resolved),
        "numpy": str(NPNET.np.__version__),
        "fast_engine": True,
        "fast_routed": True,
        "fast_binary_sha256": sha256_file(binary_path),
        "workers": 1,
        "single_process_owns_each_one_shot": True,
        "progress_every_scanned": PROGRESS_EVERY_SCANNED,
        "progress_every_evaluated": PROGRESS_EVERY_EVALUATED,
    }


def marker_claim(path: Path, marker: str, label: str) -> dict:
    if not is_regular_unlinked(path):
        raise MidlateStateControllerRefused(
            f"{label} is not regular/unlinked")
    matches = [line[len(marker):] for line in path.read_text().splitlines()
               if line.startswith(marker)]
    if len(matches) != 1:
        raise MidlateStateControllerRefused(
            f"{label} must contain exactly one raw marker")
    try:
        claim = json.loads(matches[0])
    except ValueError as exc:
        raise MidlateStateControllerRefused(
            f"{label} marker is invalid JSON") from exc
    if not isinstance(claim, dict):
        raise MidlateStateControllerRefused(
            f"{label} marker root is not an object")
    return claim


def expected_source_review_claim() -> dict:
    return {
        "controller_freeze_implementation_authorized": True,
        "evidence_open_authorized": False,
        "git": SOURCE_REVIEW_GIT,
        "independent_review": True,
        "production_deployment": False,
        "production_promotion": False,
        "schema": SOURCE_REVIEW_SCHEMA,
        "strength_claim": False,
        "verdict": "PASS",
        "whole_game_launch_authorized": False,
    }


def validate_source_review(path: Path) -> dict:
    claim = marker_claim(path, SOURCE_REVIEW_MARKER, "mid/late source review")
    if claim != expected_source_review_claim():
        raise MidlateStateControllerRefused(
            "mid/late source-review authority drift")
    return claim


def _external_ref(path: Path, expected_sha256: str, label: str) -> dict:
    path = path.resolve()
    if (not is_regular_unlinked(path) or not is_sha256(expected_sha256)
            or sha256_file(path) != expected_sha256):
        raise MidlateStateControllerRefused(f"{label} path/SHA drift")
    return {"absolute_path": str(path), "external_sha256": expected_sha256}


def _rebuild_capability(
    *, capability_packet_path: Path, capability_review_record: Path,
    training_evidence_repo: Path, training_result_review_record: Path,
    capture_evidence_repo: Path, state_set_review_record: Path,
    fresh_report_review_record: Path, bury_result_review_record: Path,
) -> dict:
    capability_packet_path = capability_packet_path.resolve()
    packet = load_json(capability_packet_path)
    external = sha256_file(capability_packet_path)
    if (packet.get("schema") != CAPABILITY.SCHEMA
            or packet.get("packet_sha256")
            != self_hash(packet, "packet_sha256")):
        raise MidlateStateControllerRefused(
            "expanded play capability identity drift")
    claim = marker_claim(
        capability_review_record.resolve(), CAPABILITY.REVIEW_MARKER,
        "expanded play capability review")
    if claim != CAPABILITY.expected_review_claim(packet, external):
        raise MidlateStateControllerRefused(
            "expanded play capability review drift")
    try:
        rebuilt = CAPABILITY._build_packet(
            evidence_repo=training_evidence_repo.resolve(),
            training_result_review_record=
                training_result_review_record.resolve(),
            capture_evidence_repo=capture_evidence_repo.resolve(),
            state_set_review_record=state_set_review_record.resolve(),
            fresh_report_review_record=fresh_report_review_record.resolve(),
            bury_result_review_record=bury_result_review_record.resolve(),
            expected_git=str(packet["producer"]["git"]))
    except Exception as exc:
        raise MidlateStateControllerRefused(
            f"expanded play capability recomputation refused: {exc}") from exc
    if rebuilt != packet:
        raise MidlateStateControllerRefused(
            "expanded play capability full recomputation drift")
    capability = packet.get("capability")
    if (not isinstance(capability, dict)
            or capability.get("surface") != "play"
            or capability.get("head") != "ranking"
            or capability.get("epoch") != 32
            or len(packet.get("checkpoint_manifest", [])) != 8):
        raise MidlateStateControllerRefused(
            "mid/late screen play capability drift")
    return packet


def forbidden_deal_seeds(
    *, capture_evidence_repo: Path, state_set_review_record: Path,
    fresh_report_review_record: Path,
) -> list[int]:
    try:
        _capture, original, _verification, _review, shards, current = \
            CAPABILITY.EXPANSION.validate_evidence(
                evidence_repo=capture_evidence_repo.resolve(),
                state_set_review_record=state_set_review_record.resolve(),
                fresh_report_review_record=fresh_report_review_record.resolve())
    except Exception as exc:
        raise MidlateStateControllerRefused(
            f"Stage-C freshness evidence refused: {exc}") from exc
    retained = [state for shard in shards for state in shard["retained_states"]]
    captured = {int(state["seed"]) for state in retained}
    original_seeds = {int(state["seed"]) for state in original["states"]}
    current_seeds = {int(state["seed"]) for state in current}
    if (not original_seeds <= captured or not current_seeds <= captured
            or len(captured) != len(retained)):
        raise MidlateStateControllerRefused(
            "Stage-C captured-deal union drift")
    prior_screen = {
        seed for start, count in PRIOR_STAGE_C_RANGES
        for seed in range(start, start + count)
    }
    values = sorted(captured | prior_screen)
    if (not values or len(values) != len(set(values))
            or any(SEED0 <= seed < SEED0 + SCAN_DEALS for seed in values)):
        raise MidlateStateControllerRefused(
            "fresh mid/late seed range overlaps prior Stage-C evidence")
    return values


def _checkpoint_root(capability: Mapping[str, object]) -> Path:
    parent = capability.get("parents", {}).get("training_evidence")
    if not isinstance(parent, Mapping):
        raise MidlateStateControllerRefused(
            "capability training-evidence parent unavailable")
    root = Path(str(parent.get("absolute_path", ""))).resolve()
    expected_git = parent.get("git")
    if (not root.is_dir() or _git("rev-parse", "HEAD", cwd=root) != expected_git
            or _git("status", "--porcelain", "--untracked-files=no", cwd=root)):
        raise MidlateStateControllerRefused(
            "capability training-evidence repository drift")
    return root


def export_models(capability: Mapping[str, object], *, verify: bool) -> list[dict]:
    root = _checkpoint_root(capability)
    selected = capability["capability"]
    manifest = capability["checkpoint_manifest"]
    exports = []
    for item, logical in zip(manifest, MODEL_PATHS, strict=True):
        checkpoint = (root / str(item["checkpoint_path"])).resolve()
        try:
            checkpoint.relative_to(root)
        except ValueError as exc:
            raise MidlateStateControllerRefused(
                "Stage-C checkpoint escapes evidence root") from exc
        if (not is_regular_unlinked(checkpoint)
                or sha256_file(checkpoint) != item["checkpoint_sha256"]):
            raise MidlateStateControllerRefused(
                "Stage-C checkpoint path/SHA drift")
        reopened = TRAIN.load_snapshot(
            checkpoint, expected_contract=item["checkpoint_contract"])
        out = (REPO / logical).resolve()
        if verify:
            try:
                loaded = NPNET.StageCNpNet(out)
            except NPNET.StageCNumpyError as exc:
                raise MidlateStateControllerRefused(str(exc)) from exc
            artifact = {
                "logical_path": logical,
                "sha256": sha256_file(out),
                "metadata": loaded.metadata,
            }
        else:
            artifact = NPNET.export_model(
                reopened["state_dict"], out,
                surface=str(selected["surface"]), seed=int(item["seed"]),
                epoch=int(selected["epoch"]),
                model_state_sha256=str(item["model_state_sha256"]),
                checkpoint_sha256=str(item["checkpoint_sha256"]))
            artifact["logical_path"] = logical
        metadata = artifact["metadata"]
        if (metadata.get("surface") != "play"
                or metadata.get("seed") != item["seed"]
                or metadata.get("epoch") != selected["epoch"]
                or metadata.get("model_state_sha256")
                != item["model_state_sha256"]
                or metadata.get("checkpoint_sha256")
                != item["checkpoint_sha256"]):
            raise MidlateStateControllerRefused(
                "Stage-C model-export binding drift")
        exports.append(artifact)
    if [item["metadata"]["seed"] for item in exports] \
            != list(MODEL.TRAINING_SEEDS):
        raise MidlateStateControllerRefused(
            "Stage-C model-export seed population drift")
    return exports


def candidate_contract() -> dict:
    return {
        "surface": "play",
        "literal_live_policy": "mc-s0-report-lcb",
        "literal_live_decision_precedes_phase_gate": True,
        "min_completed_tricks": SCREEN.MIN_COMPLETED_TRICKS,
        "novel_model_proposer": "v11pair_ep07_value",
        "v11_artifact_path": V11_PATH,
        "v11_artifact_sha256": V11_SHA256,
        "stage_c_model_proposes_at_most_one_challenger": True,
        "scope_worlds": COMPOSITION.SCOPE_WORLDS,
        "protected_report_worlds_per_arm": SCREEN.DECISION_REPORT_WORLDS,
        "direct_model_override_authorized": False,
        "incumbent_fallback_required": True,
        "same_work_matched_null_required": True,
    }


def screen_contract(forbidden: Sequence[int]) -> dict:
    return {
        "seed0": SEED0,
        "scan_deals": SCAN_DEALS,
        "target_states": SCREEN.TARGET_STATES,
        "target_per_cell": SCREEN.TARGET_PER_CELL,
        "cells": list(SCREEN.CELL_KEYS),
        "one_state_per_deal": True,
        "forbidden_deal_count": len(forbidden),
        "forbidden_deal_seeds_sha256": manifest_hash(list(forbidden)),
        "selection_frozen_before_evaluation": True,
        "selection_review_required_before_evaluation": True,
        "evaluation_worlds_per_logical_action": SCREEN.EVALUATION_WORLDS,
        "evaluation_logical_actions": 3,
        "evaluation_candidate_worlds": (
            SCREEN.TARGET_STATES * 3 * SCREEN.EVALUATION_WORLDS),
        "primary_gates": [
            "treatment-minus-live one-sided 95% LCB > 0",
            "treatment-minus-matched-null one-sided 95% LCB > 0",
        ],
        "matched-null-minus-live_is_diagnostic_only": True,
        "retry_or_extension_authorized": False,
    }


def result_contract() -> dict:
    return {
        "selection_admission_slot": SELECTION_ADMISSION_PATH,
        "selection_population": POPULATION_PATH,
        "evaluation_admission_slot": EVALUATION_ADMISSION_PATH,
        "result": RESULT_PATH,
        "one_shot_no_overwrite": True,
    }


def commands() -> dict:
    common = [
        "--expected-git", "{git}",
        "--controller-packet", PACKET_PATH,
        "--expected-controller-packet-sha256", "{packet_sha256}",
        "--controller-review-record", "{controller_review_record}",
    ]
    return {
        "select": [
            "{python}", RUNTIME_SCRIPT_PATH, "select", *common,
            "--out", POPULATION_PATH,
        ],
        "evaluate": [
            "{python}", RUNTIME_SCRIPT_PATH, "evaluate", *common,
            "--selection-population", POPULATION_PATH,
            "--expected-selection-population-sha256",
            "{selection_population_sha256}",
            "--selection-review-record", "{selection_review_record}",
            "--out", RESULT_PATH,
        ],
    }


def build_packet(
    *, git: str, source_review_record: Path,
    capability_packet_path: Path, capability_review_record: Path,
    training_result_review_record: Path, capture_evidence_repo: Path,
    state_set_review_record: Path, fresh_report_review_record: Path,
    bury_result_review_record: Path, capability: Mapping[str, object],
    forbidden: Sequence[int], exports: Sequence[Mapping[str, object]],
) -> dict:
    capability_external = sha256_file(capability_packet_path)
    source_claim = validate_source_review(source_review_record)
    packet = {
        "schema": SCHEMA,
        "packet_id": PACKET_ID,
        "run_id": RUN_ID,
        "producer": {
            "git": git,
            "tree_dirty": False,
            "sources": _source_sha256s(),
        },
        "parents": {
            "source_review": {
                **_external_ref(source_review_record, sha256_file(
                    source_review_record), "mid/late source review"),
                "claim_sha256": manifest_hash(source_claim),
            },
            "capability_packet": {
                **_external_ref(capability_packet_path, capability_external,
                                "expanded play capability"),
                "internal_sha256": capability["packet_sha256"],
                "review_record": _external_ref(
                    capability_review_record,
                    sha256_file(capability_review_record),
                    "expanded play capability review"),
            },
            "training_evidence": {
                "absolute_path": str(_checkpoint_root(capability)),
                "git": capability["parents"]["training_evidence"]["git"],
                "training_result_review": _external_ref(
                    training_result_review_record,
                    sha256_file(training_result_review_record),
                    "training result review"),
            },
            "capture_evidence": {
                "absolute_path": str(capture_evidence_repo.resolve()),
                "git": _git("rev-parse", "HEAD", cwd=capture_evidence_repo),
                "state_set_review": _external_ref(
                    state_set_review_record, sha256_file(state_set_review_record),
                    "state-set review"),
                "fresh_report_review": _external_ref(
                    fresh_report_review_record,
                    sha256_file(fresh_report_review_record),
                    "fresh REPORT review"),
                "bury_result_review": _external_ref(
                    bury_result_review_record,
                    sha256_file(bury_result_review_record),
                    "bury result review"),
            },
        },
        "selected_capability": dict(capability["capability"]),
        "checkpoint_manifest_sha256": capability[
            "checkpoint_manifest_sha256"],
        "model_exports": [dict(item) for item in exports],
        "model_exports_sha256": manifest_hash(list(exports)),
        "runtime_contract": runtime_contract(),
        "candidate_contract": candidate_contract(),
        "screen_contract": screen_contract(forbidden),
        "commands": commands(),
        "result_contract": result_contract(),
        "authority": {
            "controller_review_authorized": True,
            "selection_execution_authorized": False,
            "evaluation_open_authorized": False,
            "whole_game_launch_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
            "production_deployment": False,
        },
    }
    packet["packet_sha256"] = self_hash(packet, "packet_sha256")
    return packet


def expected_review_claim(packet: Mapping[str, object], external: str) -> dict:
    return {
        "schema": REVIEW_SCHEMA,
        "git": packet["producer"]["git"],
        "run_id": RUN_ID,
        "packet_sha256": external,
        "packet_internal_sha256": packet["packet_sha256"],
        "source_review_record_sha256": packet["parents"]["source_review"][
            "external_sha256"],
        "capability_packet_sha256": packet["parents"]["capability_packet"][
            "external_sha256"],
        "selected_capability": packet["selected_capability"],
        "model_exports_sha256": packet["model_exports_sha256"],
        "ensemble_models": len(packet["model_exports"]),
        "seed0": SEED0,
        "scan_deals": SCAN_DEALS,
        "target_states": SCREEN.TARGET_STATES,
        "forbidden_deal_count": packet["screen_contract"][
            "forbidden_deal_count"],
        "forbidden_deal_seeds_sha256": packet["screen_contract"][
            "forbidden_deal_seeds_sha256"],
        "execution_host": packet["runtime_contract"]["host"],
        "python_executable": packet["runtime_contract"][
            "python_executable"],
        "one_selection_execution_authorized": True,
        "evaluation_open_authorized": False,
        "retry_or_extension_authorized": False,
        "whole_game_launch_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "independent_review": True,
        "verdict": "PASS",
    }


def expected_selection_review_claim(
    packet: Mapping[str, object], packet_external: str,
    population: Mapping[str, object], population_external: str,
) -> dict:
    value = population.get("population")
    if not isinstance(value, Mapping):
        raise MidlateStateControllerRefused(
            "selection result population unavailable")
    if (value.get("complete") is not True
            or value.get("decision") != "READY_FOR_EVALUATION_REVIEW"
            or value.get("selected_states") != SCREEN.TARGET_STATES
            or value.get("cell_counts") != {
                cell: SCREEN.TARGET_PER_CELL for cell in SCREEN.CELL_KEYS}
            or value.get("evaluation_folds_opened") != 0
            or value.get("forbidden_deal_overlap") != 0):
        raise MidlateStateControllerRefused(
            "selection result does not meet the evaluation-review gate")
    return {
        "schema": SELECTION_REVIEW_SCHEMA,
        "git": packet["producer"]["git"],
        "run_id": RUN_ID,
        "packet_sha256": packet_external,
        "selection_population_sha256": population_external,
        "selection_population_internal_sha256": value.get(
            "population_sha256"),
        "selected_states": value.get("selected_states"),
        "deals_scanned": value.get("deals_scanned"),
        "cell_counts": value.get("cell_counts"),
        "position_counts": value.get("position_counts"),
        "evaluation_folds_opened": value.get("evaluation_folds_opened"),
        "zero_forbidden_deal_overlap": (
            value.get("forbidden_deal_overlap") == 0),
        "one_evaluation_execution_authorized": True,
        "retry_or_extension_authorized": False,
        "whole_game_launch_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "independent_review": True,
        "verdict": "PASS",
    }


def expected_result_review_claim(
    packet: Mapping[str, object], packet_external: str,
    result: Mapping[str, object], result_external: str,
) -> dict:
    aggregate = result.get("aggregate")
    if (result.get("schema")
            != "teacher-stage-c-midlate-state-screen-result-v1"
            or result.get("complete") is not True
            or result.get("result_sha256")
            != self_hash(result, "result_sha256")
            or not isinstance(aggregate, Mapping)
            or aggregate.get("schema") != SCREEN.AGGREGATE_SCHEMA
            or aggregate.get("aggregate_sha256")
            != self_hash(aggregate, "aggregate_sha256")
            or aggregate.get("whole_game_launch_authorized") is not False
            or result.get("whole_game_launch_authorized") is not False
            or result.get("strength_claim") is not False
            or result.get("production_promotion") is not False
            or result.get("production_deployment") is not False):
        raise MidlateStateControllerRefused(
            "state-screen terminal result identity/authority drift")
    design = aggregate.get("whole_game_screen_design_authorized") is True
    return {
        "schema": RESULT_REVIEW_SCHEMA,
        "git": packet["producer"]["git"],
        "run_id": RUN_ID,
        "packet_sha256": packet_external,
        "selection_population_sha256": result[
            "selection_population_sha256"],
        "result_sha256": result_external,
        "result_internal_sha256": result["result_sha256"],
        "aggregate_sha256": aggregate["aggregate_sha256"],
        "states": aggregate["states"],
        "statistics": aggregate["statistics"],
        "gates": aggregate["gates"],
        "decision": aggregate["decision"],
        "whole_game_screen_design_authorized": design,
        "whole_game_launch_authorized": False,
        "confirmation_launch_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "retry_or_extension_authorized": False,
        "independent_review": True,
        "verdict": "PASS",
    }


def _build_inputs(args: argparse.Namespace) -> tuple[dict, list[int]]:
    capability = _rebuild_capability(
        capability_packet_path=args.capability_packet,
        capability_review_record=args.capability_review_record,
        training_evidence_repo=args.training_evidence_repo,
        training_result_review_record=args.training_result_review_record,
        capture_evidence_repo=args.capture_evidence_repo,
        state_set_review_record=args.state_set_review_record,
        fresh_report_review_record=args.fresh_report_review_record,
        bury_result_review_record=args.bury_result_review_record)
    forbidden = forbidden_deal_seeds(
        capture_evidence_repo=args.capture_evidence_repo,
        state_set_review_record=args.state_set_review_record,
        fresh_report_review_record=args.fresh_report_review_record)
    return capability, forbidden


def _require_clean_expected_git(expected_git: str) -> None:
    if (_git("rev-parse", "HEAD") != expected_git
            or _git("status", "--porcelain", "--untracked-files=all")):
        raise MidlateStateControllerRefused(
            "mid/late controller requires exact clean Git head")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    root.add_argument("command", choices=("freeze", "verify"))
    root.add_argument("--expected-git", required=True)
    root.add_argument("--source-review-record", type=Path, required=True)
    root.add_argument("--capability-packet", type=Path, required=True)
    root.add_argument("--capability-review-record", type=Path, required=True)
    root.add_argument("--training-evidence-repo", type=Path, required=True)
    root.add_argument("--training-result-review-record", type=Path,
                      required=True)
    root.add_argument("--capture-evidence-repo", type=Path, required=True)
    root.add_argument("--state-set-review-record", type=Path, required=True)
    root.add_argument("--fresh-report-review-record", type=Path,
                      required=True)
    root.add_argument("--bury-result-review-record", type=Path,
                      required=True)
    root.add_argument("--out", type=Path, required=True)
    root.add_argument("--expected-packet-sha256")
    return root


def main() -> int:
    args = parser().parse_args()
    _require_clean_expected_git(args.expected_git)
    if args.out.resolve() != (REPO / PACKET_PATH).resolve():
        raise MidlateStateControllerRefused(
            "mid/late controller packet output path drift")
    validate_source_review(args.source_review_record.resolve())
    capability, forbidden = _build_inputs(args)
    if args.command == "freeze":
        if args.expected_packet_sha256 is not None:
            raise MidlateStateControllerRefused(
                "freeze refuses an expected output hash")
        if os.path.lexists(args.out):
            raise MidlateStateControllerRefused(
                "refusing existing controller packet")
        for logical in MODEL_PATHS:
            if os.path.lexists(REPO / logical):
                raise MidlateStateControllerRefused(
                    "refusing existing model export")
        exports = export_models(capability, verify=False)
        packet = build_packet(
            git=args.expected_git,
            source_review_record=args.source_review_record.resolve(),
            capability_packet_path=args.capability_packet.resolve(),
            capability_review_record=args.capability_review_record.resolve(),
            training_result_review_record=
                args.training_result_review_record.resolve(),
            capture_evidence_repo=args.capture_evidence_repo.resolve(),
            state_set_review_record=args.state_set_review_record.resolve(),
            fresh_report_review_record=
                args.fresh_report_review_record.resolve(),
            bury_result_review_record=
                args.bury_result_review_record.resolve(),
            capability=capability, forbidden=forbidden, exports=exports)
        publish_exclusive(args.out.resolve(), packet)
    else:
        if (not is_sha256(args.expected_packet_sha256)
                or not is_regular_unlinked(args.out.resolve())
                or sha256_file(args.out.resolve())
                != args.expected_packet_sha256):
            raise MidlateStateControllerRefused(
                "verified packet path/SHA drift")
        packet = load_json(args.out.resolve())
        exports = export_models(capability, verify=True)
        rebuilt = build_packet(
            git=args.expected_git,
            source_review_record=args.source_review_record.resolve(),
            capability_packet_path=args.capability_packet.resolve(),
            capability_review_record=args.capability_review_record.resolve(),
            training_result_review_record=
                args.training_result_review_record.resolve(),
            capture_evidence_repo=args.capture_evidence_repo.resolve(),
            state_set_review_record=args.state_set_review_record.resolve(),
            fresh_report_review_record=
                args.fresh_report_review_record.resolve(),
            bury_result_review_record=
                args.bury_result_review_record.resolve(),
            capability=capability, forbidden=forbidden, exports=exports)
        if packet != rebuilt:
            raise MidlateStateControllerRefused(
                "mid/late controller packet recomputation drift")
    print(json.dumps({
        "status": "FROZEN" if args.command == "freeze" else "VERIFIED",
        "packet_sha256": sha256_file(args.out.resolve()),
        "packet_internal_sha256": packet["packet_sha256"],
        "review_claim": expected_review_claim(
            packet, sha256_file(args.out.resolve())),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
