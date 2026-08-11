#!/usr/bin/env python3
"""Freeze the one Stage-C whole-game composition screen packet.

This controller runs only after the single untouched REPORT result authorizes
composition-packet review.  It reopens that complete one-shot chain, exports
the exact eight selected Torch checkpoints to immutable NumPy artifacts, and
freezes one fresh three-arm screen population:

* selected Stage-C proposer protected by live report-LCB;
* the same trigger/work geometry with a deterministic random proposer; and
* the unmodified live report-LCB champion.

Freezing this packet authorizes external review only.  It does not launch a
game, confirm strength, promote a policy, or deploy anything.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
import platform
import stat
import subprocess
import sys
from pathlib import Path
from typing import Mapping


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SCRIPT.parents[2]
sys.path.insert(0, str(SCRIPT.parent))

_REPORT_CONTROLLER_MODULE = os.environ.get(
    "SHENGJI_STAGE_C_REPORT_CONTROLLER",
    "teacher_stage_c_report_controller")
if _REPORT_CONTROLLER_MODULE not in {
        "teacher_stage_c_report_controller",
        "teacher_stage_c_expanded_report_controller"}:
    raise RuntimeError("unrecognized Stage-C composition REPORT controller")
REPORT_CTRL = importlib.import_module(_REPORT_CONTROLLER_MODULE)  # noqa: E402
import teacher_stage_c_report_runtime as REPORT_RUNTIME  # noqa: E402
import teacher_stage_c_report_supervisor as REPORT_SUPERVISOR  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.engine import combos, fast, legal  # noqa: E402
from shengji.rl import stage_c_candidates as CANDIDATES  # noqa: E402
from shengji.rl import stage_c_composition as COMPOSITION  # noqa: E402
from shengji.rl import stage_c_model as MODEL  # noqa: E402
from shengji.rl import stage_c_npnet as NPNET  # noqa: E402
from shengji.rl import stage_c_report as REPORT  # noqa: E402
from shengji.rl import stage_c_screen as SCREEN  # noqa: E402
from shengji.rl import stage_c_training as TRAIN  # noqa: E402


_PROFILE = os.environ.get(
    "SHENGJI_STAGE_C_COMPOSITION_PROFILE", "protected-anchor")
if _PROFILE not in {"protected-anchor", "expanded-bury"}:
    raise RuntimeError("unrecognized Stage-C composition profile")

_EXPANDED = _PROFILE == "expanded-bury"
if _EXPANDED != (
        _REPORT_CONTROLLER_MODULE
        == "teacher_stage_c_expanded_report_controller"):
    raise RuntimeError(
        "Stage-C composition/report controller profiles disagree")
SCHEMA = ("teacher-stage-c-expanded-composition-screen-controller-v1"
          if _EXPANDED else
          "teacher-stage-c-composition-screen-controller-v3")
PACKET_ID = ("teacher-v3-hard-tail-stage-c-expanded-composition-screen-v1"
             if _EXPANDED else
             "teacher-stage-c-composition-screen-181m-v3")
RUN_ID = PACKET_ID
PACKET_PATH = f"server/runs/logs/{RUN_ID}/controller-packet.json"
REVIEW_SCHEMA = (
    "teacher-stage-c-expanded-composition-screen-controller-review-v1"
    if _EXPANDED else
    "teacher-stage-c-composition-screen-controller-review-v3")
REVIEW_MARKER = (
    "TEACHER_STAGE_C_EXPANDED_COMPOSITION_SCREEN_CONTROLLER_V1_REVIEW "
    if _EXPANDED else
    "TEACHER_STAGE_C_COMPOSITION_SCREEN_CONTROLLER_V3_REVIEW ")
CAPACITY_RESULT_SCHEMA = (
    "teacher-stage-c-expanded-composition-capacity-v1"
    if _EXPANDED else "teacher-stage-c-composition-capacity-v3")
CAPACITY_REVIEW_SCHEMA = (
    "teacher-stage-c-expanded-composition-capacity-review-v1"
    if _EXPANDED else "teacher-stage-c-composition-capacity-review-v3")
CAPACITY_REVIEW_MARKER = (
    "TEACHER_STAGE_C_EXPANDED_COMPOSITION_CAPACITY_V1_REVIEW "
    if _EXPANDED else "TEACHER_STAGE_C_COMPOSITION_CAPACITY_V3_REVIEW ")
SUPERVISOR_REVIEW_SCHEMA = (
    "teacher-stage-c-expanded-composition-supervisor-final-review-v1"
    if _EXPANDED else
    "teacher-stage-c-composition-supervisor-final-review-v3")
SUPERVISOR_REVIEW_MARKER = (
    "TEACHER_STAGE_C_EXPANDED_COMPOSITION_SUPERVISOR_FINAL_V1_REVIEW "
    if _EXPANDED else
    "TEACHER_STAGE_C_COMPOSITION_SUPERVISOR_FINAL_V3_REVIEW ")
RUNTIME_SCRIPT_PATH = (
    "server/scripts/teacher_stage_c_expanded_composition_runtime.py"
    if _EXPANDED else
    "server/scripts/teacher_stage_c_composition_runtime.py")
RUNTIME_ADMISSION_SCHEMA = (
    "teacher-stage-c-expanded-composition-screen-admission-v1"
    if _EXPANDED else "teacher-stage-c-composition-screen-admission-v1")
RUNTIME_CAPACITY_ADMISSION_SCHEMA = (
    "teacher-stage-c-expanded-composition-capacity-admission-v1"
    if _EXPANDED else "teacher-stage-c-composition-capacity-admission-v1")
RUNTIME_SUPERVISOR_ADMISSION_SCHEMA = (
    "teacher-stage-c-expanded-composition-supervisor-admission-v1"
    if _EXPANDED else "teacher-stage-c-composition-supervisor-admission-v1")
RUNTIME_SUPERVISOR_FINAL_SCHEMA = (
    "teacher-stage-c-expanded-composition-supervisor-final-v1"
    if _EXPANDED else "teacher-stage-c-composition-supervisor-final-v1")
RUNTIME_RECEIPT_SCHEMA = (
    "teacher-stage-c-expanded-composition-screen-receipt-v1"
    if _EXPANDED else "teacher-stage-c-composition-screen-receipt-v1")
RUNTIME_SHARD_SCHEMA = (
    "teacher-stage-c-expanded-composition-screen-shard-v1"
    if _EXPANDED else "teacher-stage-c-composition-screen-shard-v1")
RUNTIME_AGGREGATE_SCHEMA = (
    "teacher-stage-c-expanded-composition-screen-result-v1"
    if _EXPANDED else "teacher-stage-c-composition-screen-result-v1")
PREFLIGHT_SEED0 = 180_000_000
PREFLIGHT_CLUSTERS = 4
PREFLIGHT_MAX_SECONDS = 3_600.0
THROUGHPUT_SAFETY_FACTOR = 2.0
SCREEN_FLEET_HOUR_CAP = 384.0
SCREEN_MAX_SHARD_HOUR_CAP = 48.0
SCREEN_SEED0 = 181_000_000
SCREEN_CLUSTERS = 2_048
SHARD_COUNT = 8
CLUSTERS_PER_SHARD = SCREEN_CLUSTERS // SHARD_COUNT
SUPERVISOR_HEARTBEAT_SECONDS = 30
SUPERVISOR_HANDLED_SIGNALS = ("SIGHUP", "SIGINT", "SIGTERM")
MODEL_DIR = f"server/runs/logs/{RUN_ID}/models"
MODEL_PATHS = tuple(
    f"{MODEL_DIR}/seed-{seed}.npz" for seed in MODEL.TRAINING_SEEDS)
SHARD_PATHS = tuple(
    f"server/runs/logs/{RUN_ID}/shard-{index:02d}.json"
    for index in range(SHARD_COUNT))
SHARD_LOG_PATHS = tuple(
    f"server/runs/logs/{RUN_ID}/shard-{index:02d}.log"
    for index in range(SHARD_COUNT))
RESULT_PATH = f"server/runs/logs/{RUN_ID}/aggregate.json"
CAPACITY_RESULT_PATH = f"server/runs/logs/{RUN_ID}/capacity.json"
SUPERVISOR_FINAL_PATH = \
    f"server/runs/logs/{RUN_ID}/supervisor-final.json"
RECEIPT_PATH = f"server/runs/logs/{RUN_ID}/screen-receipt.json"
CAPACITY_ADMISSION_PATH = \
    f"server/runs/locks/{RUN_ID}.capacity.consumed.json"
ADMISSION_PATH = f"server/runs/locks/{RUN_ID}.consumed.json"
SUPERVISOR_ADMISSION_PATH = \
    f"server/runs/locks/{RUN_ID}.supervisor.consumed.json"
SHARD_ADMISSION_PATHS = tuple(
    f"server/runs/locks/{RUN_ID}.shard-{index:02d}.consumed.json"
    for index in range(SHARD_COUNT))
AGGREGATE_ADMISSION_PATH = \
    f"server/runs/locks/{RUN_ID}.aggregate.consumed.json"
SOURCE_PATHS = (
    "server/scripts/teacher_stage_c_composition_controller.py",
    "server/scripts/teacher_stage_c_composition_runtime.py",
    *(("server/scripts/teacher_stage_c_expanded_composition_controller.py",
       "server/scripts/teacher_stage_c_expanded_composition_runtime.py")
      if _EXPANDED else ()),
    "server/shengji/rl/stage_c_candidates.py",
    "server/shengji/rl/stage_c_composition.py",
    "server/shengji/rl/stage_c_npnet.py",
    "server/shengji/rl/stage_c_screen.py",
)


class CompositionControllerRefused(RuntimeError):
    """A REPORT parent, model export, packet, or authority drifted."""


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


def _positive_finite(value: object) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(float(value)) and float(value) > 0)


def is_regular_unlinked(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not path.is_symlink())


def require_publishable(path: Path, label: str) -> None:
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise CompositionControllerRefused(
            f"refusing existing {label}: {path}")


def load_json(path: Path) -> dict:
    if not is_regular_unlinked(path):
        raise CompositionControllerRefused(
            f"input is not regular/unlinked: {path}")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise CompositionControllerRefused(
            f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CompositionControllerRefused(
            f"JSON root is not an object: {path}")
    return value


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _source_sha256s() -> dict[str, str]:
    result = {}
    for logical in SOURCE_PATHS:
        path = REPO / logical
        if not is_regular_unlinked(path):
            raise CompositionControllerRefused(
                f"composition source unavailable: {logical}")
        result[logical] = sha256_file(path)
    return result


def runtime_contract() -> dict:
    routed = (bool(fast.HAVE_FAST)
              and combos.decompose is fast.decompose
              and legal.beats is fast.beats)
    if os.environ.get("SHENGJI_FAST") != "1" or not routed:
        raise CompositionControllerRefused(
            "composition packet requires compiled engine on live route")
    binary = getattr(fast, "_fast", None)
    binary_path = None if binary is None else Path(binary.__file__).resolve()
    if binary_path is None or not is_regular_unlinked(binary_path):
        raise CompositionControllerRefused(
            "composition packet lacks regular compiled binary")
    python_path = Path(sys.executable)
    python_resolved = python_path.resolve()
    if not is_regular_unlinked(python_resolved):
        raise CompositionControllerRefused(
            "composition packet lacks regular Python executable")
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
        "workers": SHARD_COUNT,
        "progress_every_clusters": 50,
        "supervisor_heartbeat_seconds": SUPERVISOR_HEARTBEAT_SECONDS,
        "supervisor_signal_contract": {
            "handled_signals": list(SUPERVISOR_HANDLED_SIGNALS),
            "signals_deferred_until_child_registered": True,
            "terminates_all_owned_children": True,
            "orphaned_shards_authorized": False,
        },
    }


def _logical_ref(path: Path, expected_sha256: str, label: str) -> dict:
    path = path.resolve()
    try:
        logical = str(path.relative_to(REPO.resolve()))
    except ValueError as exc:
        raise CompositionControllerRefused(
            f"{label} escapes repository") from exc
    if (not is_regular_unlinked(path)
            or not is_sha256(expected_sha256)
            or sha256_file(path) != expected_sha256):
        raise CompositionControllerRefused(f"{label} path/SHA drift")
    return {"logical_path": logical, "external_sha256": expected_sha256}


def _marker_claim(path: Path, marker: str, label: str) -> dict:
    if not is_regular_unlinked(path):
        raise CompositionControllerRefused(
            f"{label} is not regular/unlinked")
    matches = [line[len(marker):] for line in path.read_text().splitlines()
               if line.startswith(marker)]
    if len(matches) != 1:
        raise CompositionControllerRefused(
            f"{label} must contain exactly one raw marker")
    try:
        claim = json.loads(matches[0])
    except ValueError as exc:
        raise CompositionControllerRefused(
            f"{label} marker is invalid JSON") from exc
    if not isinstance(claim, dict):
        raise CompositionControllerRefused(
            f"{label} marker root is not an object")
    return claim


def validate_report_result(
    *, report_packet_path: Path, report_packet_sha256: str,
    report_review_record: Path, fresh_report_review_record: Path,
    state_set_review_record: Path, report_receipt_path: Path,
    report_receipt_sha256: str, report_result_path: Path,
    report_result_sha256: str, report_supervisor_final_path: Path,
    report_supervisor_final_sha256: str,
    report_result_review_record: Path,
) -> tuple[dict, dict]:
    """Reopen a separately replayed terminal REPORT without reselection."""
    try:
        packet, _dataset, _training, _fresh, _states = \
            REPORT_RUNTIME._packet(
                report_packet_path.resolve(), report_packet_sha256,
                fresh_report_review_record=
                fresh_report_review_record.resolve(),
                state_set_review_record=state_set_review_record.resolve())
        receipt = REPORT_RUNTIME._receipt(
            report_receipt_path.resolve(), report_receipt_sha256,
            packet, report_packet_sha256, report_review_record.resolve())
    except REPORT_RUNTIME.ReportRuntimeRefused as exc:
        raise CompositionControllerRefused(str(exc)) from exc
    result_path = report_result_path.resolve()
    if (result_path != (REPO / REPORT_RUNTIME.RESULT_PATH).resolve()
            or not is_regular_unlinked(result_path)
            or sha256_file(result_path) != report_result_sha256):
        raise CompositionControllerRefused(
            "Stage-C REPORT result path/SHA drift")
    result = load_json(result_path)
    evaluation = result.get("evaluation")
    capability = packet["selected_capability"]
    opened = result.get("opened_report_label_shards")
    schedule = packet["report_schedule"]
    opened_ok = (
        isinstance(opened, list) and len(opened) == REPORT_CTRL.REPORT_SHARDS
        and all(
            isinstance(item, dict)
            and item.get("index") == index
            and item.get("logical_path") == REPORT_RUNTIME.SHARD_PATHS[index]
            and is_sha256(item.get("external_sha256"))
            and is_sha256(item.get("internal_sha256"))
            and item.get("state_ids_sha256")
            == schedule["shards"][index]["state_ids_sha256"]
            and is_sha256(item.get("row_sha256s_sha256"))
            and item.get("status") == "COMPLETE"
            and item.get("refused_rows") == 0
            for index, item in enumerate(opened or [])))
    if (result.get("schema") != REPORT_RUNTIME.RESULT_SCHEMA
            or result.get("run_id") != REPORT_CTRL.RUN_ID
            or result.get("git") != packet["producer"]["git"]
            or result.get("controller_packet_sha256")
            != report_packet_sha256
            or result.get("report_receipt_sha256")
            != report_receipt_sha256
            or result.get("report_open_admission_slot")
            != REPORT_RUNTIME.REPORT_OPEN_ADMISSION_PATH
            or result.get("report_open_admission_slot_sha256")
            != receipt.get("report_open_admission_slot_sha256")
            or result.get("selected_capability")
            != packet["selected_capability"]
            or result.get("checkpoint_manifest_sha256")
            != REPORT_CTRL._manifest_hash(packet["checkpoint_manifest"])
            or result.get("fresh_report_selection_sha256")
            != packet["parents"]["fresh_report_selection"][
                "sealed_selection_sha256"]
            or result.get("report_schedule_sha256")
            != schedule["schedule_sha256"]
            or not opened_ok
            or result.get("report_label_shard_files_opened")
            != REPORT_CTRL.REPORT_SHARDS
            or result.get("fresh_report_states_reconstructed")
            != packet["parents"]["fresh_report_selection"][
                "fresh_report_states"]
            or result.get("selected_surface_rows_labeled")
            != packet["report_contract"]["states"]
            or result.get("report_label_refusals") != 0
            or result.get("candidate_world_ceiling")
            != schedule["candidate_world_ceiling"]
            or result.get("candidate_world_ceiling_respected") is not True
            or result.get("v11_checkpoint_loaded") is not False
            or not isinstance(evaluation, dict)
            or evaluation.get("schema") != REPORT.REPORT_SCHEMA
            or evaluation.get("surface") != capability["surface"]
            or evaluation.get("head") != capability["head"]
            or evaluation.get("ensemble_seeds")
            != list(MODEL.TRAINING_SEEDS)
            or evaluation.get("states")
            != packet["report_contract"]["states"]
            or isinstance(evaluation.get("proposal_triggers"), bool)
            or not isinstance(evaluation.get("proposal_triggers"), int)
            or evaluation.get("proposal_triggers") <= 0
            or not isinstance(evaluation.get(
                "teacher_improvement_vs_candidate0"), dict)
            or not _positive_finite(
                evaluation["teacher_improvement_vs_candidate0"].get(
                    "one_sided_95_lcb"))
            or (capability["head"] == "outcome" and (
                not isinstance(evaluation.get(
                    "outcome_nll_improvement_vs_design_prior"), dict)
                or not _positive_finite(evaluation[
                    "outcome_nll_improvement_vs_design_prior"].get(
                        "one_sided_95_lcb"))))
            or not isinstance(evaluation.get("rows"), list)
            or len(evaluation["rows"]) != evaluation.get("states")
            or any(not isinstance(row, dict)
                   or not isinstance(row.get("state_id"), str)
                   or not row.get("state_id") for row in evaluation["rows"])
            or len({row["state_id"] for row in evaluation["rows"]})
            != evaluation.get("states")
            or evaluation.get("result_sha256")
            != self_hash(evaluation, "result_sha256")
            or evaluation.get("decision")
            != "AUTHORIZE_STAGE_C_COMPOSITION_PACKET_REVIEW"
            or evaluation.get("composition_packet_review_authorized")
            is not True
            or evaluation.get("report_opened_once") is not True
            or evaluation.get("report_reuse_authorized") is not False
            or evaluation.get("strength_claim") is not False
            or evaluation.get("production_promotion") is not False
            or evaluation.get("production_deployment") is not False
            or result.get("decision") != evaluation.get("decision")
            or result.get("composition_packet_review_authorized") is not True
            or result.get("report_reuse_authorized") is not False
            or result.get("strength_claim") is not False
            or result.get("production_promotion") is not False
            or result.get("production_deployment") is not False
            or result.get("result_sha256")
            != self_hash(result, "result_sha256")):
        raise CompositionControllerRefused(
            "Stage-C REPORT result identity/authority drift")

    supervisor_path = report_supervisor_final_path.resolve()
    if (supervisor_path != (REPO / REPORT_SUPERVISOR.FINAL_PATH).resolve()
            or not is_regular_unlinked(supervisor_path)
            or not is_sha256(report_supervisor_final_sha256)
            or sha256_file(supervisor_path)
            != report_supervisor_final_sha256):
        raise CompositionControllerRefused(
            "Stage-C REPORT supervisor final path/SHA drift")
    supervisor = load_json(supervisor_path)
    if (supervisor.get("schema") != REPORT_SUPERVISOR.FINAL_SCHEMA
            or supervisor.get("run_id") != REPORT_CTRL.RUN_ID
            or supervisor.get("git") != packet["producer"]["git"]
            or supervisor.get("controller_packet_sha256")
            != report_packet_sha256
            or supervisor.get("report_receipt_sha256")
            != report_receipt_sha256
            or supervisor.get("report_schedule_sha256")
            != schedule["schedule_sha256"]
            or supervisor.get("label_shards_complete")
            != REPORT_CTRL.REPORT_SHARDS
            or supervisor.get("result_path") != REPORT_RUNTIME.RESULT_PATH
            or supervisor.get("result_external_sha256")
            != report_result_sha256
            or supervisor.get("result_internal_sha256")
            != result["result_sha256"]
            or supervisor.get("decision") != result["decision"]
            or supervisor.get("composition_packet_review_authorized")
            is not True
            or supervisor.get("report_reuse_authorized") is not False
            or supervisor.get("retry_authorized") is not False
            or supervisor.get("strength_claim") is not False
            or supervisor.get("production_promotion") is not False
            or supervisor.get("production_deployment") is not False
            or supervisor.get("final_sha256")
            != self_hash(supervisor, "final_sha256")):
        raise CompositionControllerRefused(
            "Stage-C REPORT supervisor final identity/authority drift")
    try:
        expected_review = REPORT_SUPERVISOR.expected_review_claim(
            packet=packet, packet_external_sha256=report_packet_sha256,
            receipt_external_sha256=report_receipt_sha256, result=result,
            result_external_sha256=report_result_sha256,
            supervisor_final=supervisor,
            supervisor_external_sha256=report_supervisor_final_sha256)
    except REPORT_SUPERVISOR.ReportSupervisorRefused as exc:
        raise CompositionControllerRefused(str(exc)) from exc
    review = _marker_claim(
        report_result_review_record.resolve(),
        REPORT_SUPERVISOR.REVIEW_MARKER, "Stage-C REPORT result review")
    if (review != expected_review
            or review.get("one_composition_controller_freeze_authorized")
            is not True):
        raise CompositionControllerRefused(
            "Stage-C REPORT result review claim/authority drift")
    return packet, result


def _checkpoint_root(packet: Mapping[str, object]) -> Path:
    """Return the already-authenticated training root for selected snapshots."""
    evidence = packet.get("parents", {}).get("training_evidence")
    if evidence is None:
        return REPO
    if not isinstance(evidence, Mapping):
        raise CompositionControllerRefused(
            "Stage-C training-evidence parent drift")
    root = Path(str(evidence.get("absolute_path", ""))).resolve()
    expected_git = evidence.get("git")
    try:
        actual_git = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True,
            capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=root, check=True, capture_output=True,
            text=True).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise CompositionControllerRefused(
            "Stage-C training-evidence Git unavailable") from exc
    if (not root.is_dir() or actual_git != expected_git or dirty):
        raise CompositionControllerRefused(
            "Stage-C training-evidence Git drift")
    return root


def _export_models(packet: Mapping[str, object], *, verify: bool) -> list[dict]:
    capability = packet["selected_capability"]
    checkpoint_root = _checkpoint_root(packet)
    # Check the complete population before the first no-replace publication.
    # A late known collision must not leave seven newly exported models and no
    # controller packet.
    for logical in MODEL_PATHS:
        path = (REPO / logical).resolve()
        if verify:
            if not is_regular_unlinked(path):
                raise CompositionControllerRefused(
                    "Stage-C NumPy export missing during verification")
        else:
            require_publishable(path, "Stage-C NumPy export")
    exports = []
    for item, logical in zip(
            packet["checkpoint_manifest"], MODEL_PATHS, strict=True):
        checkpoint_logical = Path(str(item["checkpoint_path"]))
        if checkpoint_logical.is_absolute() or ".." in checkpoint_logical.parts:
            raise CompositionControllerRefused(
                "Stage-C checkpoint logical path escapes evidence root")
        checkpoint = (checkpoint_root / checkpoint_logical).resolve()
        try:
            checkpoint.relative_to(checkpoint_root)
        except ValueError as exc:
            raise CompositionControllerRefused(
                "Stage-C checkpoint resolved outside evidence root") from exc
        reopened = TRAIN.load_snapshot(
            checkpoint, expected_contract=item["checkpoint_contract"])
        out = (REPO / logical).resolve()
        if verify:
            if not is_regular_unlinked(out):
                raise CompositionControllerRefused(
                    "Stage-C NumPy export missing during verification")
            loaded = NPNET.StageCNpNet(out)
            artifact = {
                "logical_path": logical,
                "sha256": sha256_file(out),
                "metadata": loaded.metadata,
            }
        else:
            artifact = NPNET.export_model(
                reopened["state_dict"], out,
                surface=str(capability["surface"]), seed=int(item["seed"]),
                epoch=int(capability["epoch"]),
                model_state_sha256=str(item["model_state_sha256"]),
                checkpoint_sha256=str(item["checkpoint_sha256"]))
            artifact["logical_path"] = logical
        metadata = artifact["metadata"]
        if (metadata.get("surface") != capability["surface"]
                or metadata.get("seed") != item["seed"]
                or metadata.get("epoch") != capability["epoch"]
                or metadata.get("model_state_sha256")
                != item["model_state_sha256"]
                or metadata.get("checkpoint_sha256")
                != item["checkpoint_sha256"]):
            raise CompositionControllerRefused(
                "Stage-C NumPy export/checkpoint binding drift")
        exports.append(artifact)
    if [item["metadata"]["seed"] for item in exports] \
            != list(MODEL.TRAINING_SEEDS):
        raise CompositionControllerRefused(
            "Stage-C NumPy export seed population drift")
    return exports


def _preflight_export_environment() -> None:
    # Refuse all cheap/environmental problems before publishing the first of
    # eight no-replace exports. A mid-export process failure intentionally
    # leaves evidence and cannot be silently resumed under the same paths.
    _source_sha256s()
    runtime_contract()
    try:
        COMPOSITION._require_live_report_lcb(
            make_bot("mc-s0-report-lcb", seed=0))
    except Exception as exc:
        raise CompositionControllerRefused(
            f"Stage-C composition inference preflight failed: {exc}") from exc


def _commands() -> dict:
    shared = [
        "--expected-git", "{git}",
        "--controller-packet", PACKET_PATH,
        "--expected-controller-packet-sha256", "{packet_sha256}",
        "--controller-review-record", "{controller_review_record}",
    ]
    capacity = [
        "--capacity-result", CAPACITY_RESULT_PATH,
        "--expected-capacity-result-sha256", "{capacity_result_sha256}",
        "--capacity-review-record", "{capacity_review_record}",
    ]
    receipt = [
        "--screen-receipt", RECEIPT_PATH,
        "--expected-screen-receipt-sha256", "{receipt_sha256}",
    ]
    supervisor = [
        "--supervisor-admission", SUPERVISOR_ADMISSION_PATH,
        "--expected-supervisor-admission-sha256",
        "{supervisor_admission_sha256}",
    ]
    return {
        "capacity_preflight": [
            "{python}",
            RUNTIME_SCRIPT_PATH,
            "capacity-preflight", *shared, "--out", CAPACITY_RESULT_PATH,
        ],
        "admit": [
            "{python}",
            RUNTIME_SCRIPT_PATH,
            "admit", *shared, *capacity, "--out", RECEIPT_PATH,
        ],
        "supervise": [
            "{python}",
            RUNTIME_SCRIPT_PATH,
            "supervise", *shared, *receipt, *capacity,
            "--out", SUPERVISOR_FINAL_PATH,
        ],
        "supervisor_child_shards": [[
            "{python}",
            RUNTIME_SCRIPT_PATH,
            "run-shard", *shared, *receipt, *capacity, *supervisor,
            "--shard-index", str(index), "--out", SHARD_PATHS[index],
        ] for index in range(SHARD_COUNT)],
        "aggregate": [
            "{python}",
            RUNTIME_SCRIPT_PATH,
            "aggregate", *shared,
            *receipt, *capacity,
            "--supervisor-final", SUPERVISOR_FINAL_PATH,
            "--expected-supervisor-final-sha256",
            "{supervisor_final_sha256}",
            "--supervisor-review-record", "{supervisor_review_record}",
            "--shards", *SHARD_PATHS, "--out", RESULT_PATH,
        ],
    }


def candidate_contract() -> dict:
    return {
        "experiment_id": CANDIDATES.INFERENCE_EXPERIMENT_ID,
        "split": CANDIDATES.INFERENCE_SPLIT,
        "play_candidate_cap": CANDIDATES.PLAY_CANDIDATE_CAP,
        "bury_candidate_cap": CANDIDATES.BURY_CANDIDATE_CAP,
        "live_parent": "mc-s0-report-lcb",
        "novel_model_proposer": "stage_c_mc_teacher_ensemble",
        "v11_proposer_admitted": False,
        "v11_artifact_loaded": False,
        "model_proposes_at_most_one_challenger": True,
        "fresh_report_lcb_required": True,
        "direct_model_override_authorized": False,
    }


def screen_contract() -> dict:
    return {
        "seed0": SCREEN_SEED0,
        "clusters": SCREEN_CLUSTERS,
        "shards": SHARD_COUNT,
        "clusters_per_shard": CLUSTERS_PER_SHARD,
        "rounds_per_cluster_per_arm": 2,
        "arms": list(SCREEN.LABELS),
        "paired_unit": "deal seed with both team flips",
        "primary_gates": [
            "treatment-minus-champion one-sided 95% LCB > 0",
            "treatment-minus-matched-null one-sided 95% LCB > 0",
            "matched-null-minus-champion interval contains zero",
        ],
        "nonzero_model_trigger_required": True,
        "zero_fallback_and_exact_work_required": True,
        "reviewed_capacity_result_required_before_screen_admission": True,
        "per_shard_timeout_from_reviewed_capacity_required": True,
        "supervisor_owns_all_shards_and_logs": True,
        "supervisor_heartbeat_seconds": SUPERVISOR_HEARTBEAT_SECONDS,
        "supervisor_signal_contract": {
            "handled_signals": list(SUPERVISOR_HANDLED_SIGNALS),
            "signals_deferred_until_child_registered": True,
            "terminates_all_owned_children": True,
            "orphaned_shards_authorized": False,
        },
        "external_supervisor_final_review_required_before_aggregate": True,
        "aggregate_slot_precedes_outcome_open": True,
        "pass_authority": "confirmation packet review only",
        "retry_or_extension_authorized": False,
    }


def capacity_contract() -> dict:
    return {
        "seed0": PREFLIGHT_SEED0,
        "clusters": PREFLIGHT_CLUSTERS,
        "arms": list(SCREEN.LABELS),
        "score_free_output": True,
        "preflight_max_seconds": PREFLIGHT_MAX_SECONDS,
        "throughput_safety_factor": THROUGHPUT_SAFETY_FACTOR,
        "screen_fleet_hour_cap": SCREEN_FLEET_HOUR_CAP,
        "screen_max_shard_hour_cap": SCREEN_MAX_SHARD_HOUR_CAP,
        "nonzero_treatment_and_null_trigger_required": True,
        "zero_fallback_and_exact_work_required": True,
        "pass_authority": "screen execution review only",
        "retry_or_extension_authorized": False,
    }


def result_contract() -> dict:
    return {
        "capacity_admission_slot": CAPACITY_ADMISSION_PATH,
        "capacity_result": CAPACITY_RESULT_PATH,
        "admission_slot": ADMISSION_PATH,
        "supervisor_admission_slot": SUPERVISOR_ADMISSION_PATH,
        "supervisor_final": SUPERVISOR_FINAL_PATH,
        "shard_logs": list(SHARD_LOG_PATHS),
        "shard_admission_slots": list(SHARD_ADMISSION_PATHS),
        "aggregate_admission_slot": AGGREGATE_ADMISSION_PATH,
        "receipt": RECEIPT_PATH,
        "shards": list(SHARD_PATHS),
        "aggregate": RESULT_PATH,
        "one_shot_no_overwrite": True,
    }


def build_packet(
    *, git: str, report_packet: Mapping[str, object],
    report_packet_ref: Mapping[str, object],
    report_review_ref: Mapping[str, object],
    fresh_report_review_ref: Mapping[str, object],
    state_set_review_ref: Mapping[str, object],
    report_receipt_ref: Mapping[str, object],
    report_result: Mapping[str, object],
    report_result_ref: Mapping[str, object],
    report_supervisor_final_ref: Mapping[str, object],
    report_result_review_ref: Mapping[str, object], exports: list[dict],
) -> dict:
    capability = dict(report_packet["selected_capability"])
    if report_result["selected_capability"] != capability:
        raise CompositionControllerRefused(
            "Stage-C composition capability drift")
    packet = {
        "schema": SCHEMA,
        "packet_id": PACKET_ID,
        "run_id": RUN_ID,
        "producer": {
            "git": git,
            "tree_dirty": False,
            "sources": _source_sha256s(),
        },
        "runtime_contract": runtime_contract(),
        "parents": {
            "report_packet": dict(report_packet_ref),
            "report_review_record": dict(report_review_ref),
            "fresh_report_review_record": dict(fresh_report_review_ref),
            "state_set_review_record": dict(state_set_review_ref),
            "report_receipt": dict(report_receipt_ref),
            "report_result": {
                **dict(report_result_ref),
                "internal_sha256": report_result["result_sha256"],
                "decision": report_result["decision"],
            },
            "report_supervisor_final": dict(report_supervisor_final_ref),
            "report_result_review_record": dict(report_result_review_ref),
            "report_open_admission_slot": {
                "logical_path": report_result[
                    "report_open_admission_slot"],
                "external_sha256": report_result[
                    "report_open_admission_slot_sha256"],
            },
        },
        "selected_capability": capability,
        "model_exports": exports,
        "model_exports_sha256": manifest_hash(exports),
        "candidate_contract": candidate_contract(),
        "capacity_contract": capacity_contract(),
        "screen_contract": screen_contract(),
        "commands": _commands(),
        "result_contract": result_contract(),
        "authority": {
            "capacity_preflight_review_authorized": True,
            "capacity_preflight_launch_authorized": False,
            "screen_packet_review_authorized": False,
            "screen_launch_authorized": False,
            "confirmation_launch_authorized": False,
            "v11_inference_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
            "production_deployment": False,
        },
    }
    packet["packet_sha256"] = self_hash(packet, "packet_sha256")
    return packet


def expected_review_claim(packet: Mapping[str, object],
                          external_sha256: str) -> dict:
    return {
        "schema": REVIEW_SCHEMA,
        "git": packet["producer"]["git"],
        "run_id": RUN_ID,
        "packet_sha256": external_sha256,
        "packet_internal_sha256": packet["packet_sha256"],
        "report_result_sha256": packet["parents"]["report_result"][
            "external_sha256"],
        "report_supervisor_final_sha256": packet["parents"][
            "report_supervisor_final"]["external_sha256"],
        "report_result_review_record_sha256": packet["parents"][
            "report_result_review_record"]["external_sha256"],
        "selected_capability": packet["selected_capability"],
        "model_exports_sha256": packet["model_exports_sha256"],
        "ensemble_models": len(packet["model_exports"]),
        "preflight_seed0": PREFLIGHT_SEED0,
        "preflight_clusters": PREFLIGHT_CLUSTERS,
        "screen_seed0": SCREEN_SEED0,
        "screen_clusters": SCREEN_CLUSTERS,
        "screen_shards": SHARD_COUNT,
        "execution_host": packet["runtime_contract"]["host"],
        "python": packet["runtime_contract"]["python"],
        "python_executable": packet["runtime_contract"][
            "python_executable"],
        "python_executable_resolved": packet["runtime_contract"][
            "python_executable_resolved"],
        "python_executable_sha256": packet["runtime_contract"][
            "python_executable_sha256"],
        "numpy": packet["runtime_contract"]["numpy"],
        "supervisor_heartbeat_seconds": packet["runtime_contract"][
            "supervisor_heartbeat_seconds"],
        "supervisor_signal_contract": packet["runtime_contract"][
            "supervisor_signal_contract"],
        "novel_model_proposer": "stage_c_mc_teacher_ensemble",
        "v11_inference_authorized": False,
        "independent_review": True,
        "one_capacity_preflight_authorized": True,
        "one_screen_execution_authorized": False,
        "confirmation_launch_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }


def expected_capacity_review_claim(
    packet: Mapping[str, object], packet_external_sha256: str,
    capacity_result: Mapping[str, object], capacity_external_sha256: str,
) -> dict:
    return {
        "schema": CAPACITY_REVIEW_SCHEMA,
        "git": packet["producer"]["git"],
        "run_id": RUN_ID,
        "packet_sha256": packet_external_sha256,
        "capacity_result_sha256": capacity_external_sha256,
        "capacity_result_internal_sha256": capacity_result[
            "result_sha256"],
        "preflight_seed0": PREFLIGHT_SEED0,
        "preflight_clusters": PREFLIGHT_CLUSTERS,
        "elapsed_seconds": capacity_result["elapsed_seconds"],
        "screen_fleet_hours": capacity_result["projection"][
            "screen_fleet_hours"],
        "screen_max_shard_hours": capacity_result["projection"][
            "screen_max_shard_hours"],
        "screen_max_shard_seconds": capacity_result[
            "screen_max_shard_seconds"],
        "capacity_pass": True,
        "score_free": True,
        "independent_review": True,
        "one_screen_execution_authorized": True,
        "confirmation_launch_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }


def expected_supervisor_review_claim(
    packet: Mapping[str, object], packet_external_sha256: str,
    supervisor_final: Mapping[str, object],
    supervisor_external_sha256: str,
) -> dict:
    return {
        "schema": SUPERVISOR_REVIEW_SCHEMA,
        "git": packet["producer"]["git"],
        "run_id": RUN_ID,
        "packet_sha256": packet_external_sha256,
        "screen_receipt_sha256": supervisor_final[
            "screen_receipt_sha256"],
        "supervisor_final_sha256": supervisor_external_sha256,
        "supervisor_final_internal_sha256": supervisor_final[
            "final_sha256"],
        "shard_manifest_sha256": supervisor_final[
            "shard_manifest_sha256"],
        "shards": len(supervisor_final["shards"]),
        "all_children_exit_zero": True,
        "outcomes_or_statistics_read_by_reviewer": False,
        "independent_review": True,
        "one_aggregate_execution_authorized": True,
        "confirmation_launch_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }


def publish_exclusive(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = Path(str(path) + ".partial")
    require_publishable(path, "output")
    with partial.open("xb") as handle:
        handle.write(canonical_json(payload))
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.link(partial, path, follow_symlinks=False)
    except FileExistsError as exc:
        raise CompositionControllerRefused(
            f"refusing raced output publication: {path}") from exc
    partial.unlink()


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("command", choices=("freeze", "verify"))
    root.add_argument("--report-packet", required=True)
    root.add_argument("--expected-report-packet-sha256", required=True)
    root.add_argument("--report-review-record", required=True)
    root.add_argument("--fresh-report-review-record", required=True)
    root.add_argument("--state-set-review-record", required=True)
    root.add_argument("--report-receipt", required=True)
    root.add_argument("--expected-report-receipt-sha256", required=True)
    root.add_argument("--report-result", required=True)
    root.add_argument("--expected-report-result-sha256", required=True)
    root.add_argument("--report-supervisor-final", required=True)
    root.add_argument(
        "--expected-report-supervisor-final-sha256", required=True)
    root.add_argument("--report-result-review-record", required=True)
    root.add_argument("--out", required=True)
    root.add_argument("--expected-out-sha256")
    return root


def main() -> int:
    args = parser().parse_args()
    if _git("status", "--porcelain", "--untracked-files=all"):
        raise CompositionControllerRefused(
            "composition packet freeze refuses dirty tree")
    out = Path(args.out).resolve()
    if out != (REPO / PACKET_PATH).resolve():
        raise CompositionControllerRefused(
            "composition packet output path drift")
    if args.command == "freeze":
        require_publishable(out, "composition packet output")
    elif (not is_sha256(args.expected_out_sha256)
          or not is_regular_unlinked(out)
          or sha256_file(out) != args.expected_out_sha256):
        raise CompositionControllerRefused(
            "composition packet verification input drift")
    report_packet_path = Path(args.report_packet).resolve()
    report_review_path = Path(args.report_review_record).resolve()
    fresh_report_review_path = Path(
        args.fresh_report_review_record).resolve()
    state_set_review_path = Path(args.state_set_review_record).resolve()
    report_receipt_path = Path(args.report_receipt).resolve()
    report_result_path = Path(args.report_result).resolve()
    report_supervisor_final_path = Path(
        args.report_supervisor_final).resolve()
    report_result_review_path = Path(
        args.report_result_review_record).resolve()
    packet, result = validate_report_result(
        report_packet_path=report_packet_path,
        report_packet_sha256=args.expected_report_packet_sha256,
        report_review_record=report_review_path,
        fresh_report_review_record=fresh_report_review_path,
        state_set_review_record=state_set_review_path,
        report_receipt_path=report_receipt_path,
        report_receipt_sha256=args.expected_report_receipt_sha256,
        report_result_path=report_result_path,
        report_result_sha256=args.expected_report_result_sha256,
        report_supervisor_final_path=report_supervisor_final_path,
        report_supervisor_final_sha256=
        args.expected_report_supervisor_final_sha256,
        report_result_review_record=report_result_review_path)
    _preflight_export_environment()
    exports = _export_models(packet, verify=args.command == "verify")
    output = build_packet(
        git=_git("rev-parse", "HEAD"), report_packet=packet,
        report_packet_ref=_logical_ref(
            report_packet_path, args.expected_report_packet_sha256,
            "REPORT packet"),
        report_review_ref=_logical_ref(
            report_review_path, sha256_file(report_review_path),
            "REPORT review record"),
        fresh_report_review_ref=_logical_ref(
            fresh_report_review_path, sha256_file(fresh_report_review_path),
            "fresh REPORT review record"),
        state_set_review_ref=_logical_ref(
            state_set_review_path, sha256_file(state_set_review_path),
            "state-set review record"),
        report_receipt_ref=_logical_ref(
            report_receipt_path, args.expected_report_receipt_sha256,
            "REPORT receipt"),
        report_result=result,
        report_result_ref=_logical_ref(
            report_result_path, args.expected_report_result_sha256,
            "REPORT result"),
        report_supervisor_final_ref=_logical_ref(
            report_supervisor_final_path,
            args.expected_report_supervisor_final_sha256,
            "REPORT supervisor final"),
        report_result_review_ref=_logical_ref(
            report_result_review_path, sha256_file(report_result_review_path),
            "REPORT result review record"),
        exports=exports)
    if args.command == "freeze":
        publish_exclusive(out, output)
    elif (not args.expected_out_sha256
          or sha256_file(out) != args.expected_out_sha256
          or load_json(out) != output):
        raise CompositionControllerRefused(
            "composition packet verification drift")
    print(json.dumps({
        "status": "FROZEN" if args.command == "freeze" else "VERIFIED",
        "packet_sha256": sha256_file(out),
        "packet_internal_sha256": output["packet_sha256"],
        "selected_capability": output["selected_capability"],
        "model_exports": len(output["model_exports"]),
        "screen_launch_authorized": False,
        "strength_claim": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (CompositionControllerRefused, NPNET.StageCNumpyError,
            TRAIN.StageCTrainingError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        raise SystemExit(2)
