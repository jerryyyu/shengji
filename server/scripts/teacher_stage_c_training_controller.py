#!/usr/bin/env python3
"""Freeze the Stage-C DESIGN/CALIB model dataset and training packet.

This controller is downstream of a terminal Stage-C label aggregate and a
separately reviewed fresh REPORT selection.  Teacher-label fidelity and V11
proposal recall are separate estimands: the controller consumes the good MC
counterfactual labels without admitting or loading V11.  Candidate source tags
are historical capture metadata only and are never model features.  The
controller reopens and semantically validates only the eight DESIGN and four
CALIB label shards.  It binds only the digest-sealed fresh REPORT replacement;
it never materializes those states or opens either old or fresh REPORT labels.

Freezing the dataset and packet performs no training.  A later independent
packet review is required before the one-shot training runtime can be admitted.
No result here authorizes REPORT access, composition, strength, promotion or
deployment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
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

import teacher_stage_c_capture_runtime as CAPTURE  # noqa: E402
import teacher_stage_c_fresh_report_controller as FRESH  # noqa: E402
import teacher_stage_c_label_controller as LABEL_CTRL  # noqa: E402
import teacher_stage_c_label_runtime as LABEL  # noqa: E402
from shengji.rl import stage_c_model as MODEL  # noqa: E402
from shengji.rl import stage_c_training as TRAIN  # noqa: E402


SCHEMA = "teacher-stage-c-v11-free-training-controller-v1"
PACKET_ID = "teacher-v3-hard-tail-stage-c-v11-free-training-controller-v1"
RUN_ID = "teacher-v3-hard-tail-stage-c-v11-free-training-v1"
CONTROLLER_RUN_ID = \
    "teacher-v3-hard-tail-stage-c-v11-free-training-controller-v1"
DATASET_SCHEMA = "teacher-stage-c-v11-free-model-dataset-v1"
DATASET_PATH = f"server/runs/logs/{CONTROLLER_RUN_ID}/model-dataset.json"
PACKET_PATH = f"server/runs/logs/{CONTROLLER_RUN_ID}/controller_packet.json"
SUPERVISOR_PATH = "server/scripts/teacher_stage_c_training_supervisor.py"
FRESH_REPORT_PACKET_SHA256 = \
    "7dd0caacff9e61e4f963ba0afa56c3eca81c05abd9da2eaaba4ece8284870e69"
LABEL_AGGREGATE_SHA256 = \
    "d0b4397ce0135b5ae665a76f9188ae3c974e2e440e0d6dc047d5080b27e6cdb9"
LABEL_AGGREGATE_INTERNAL_SHA256 = \
    "882baad7a5a8adf5044d8d6249e47b1a44f2dd838d1cb67c304fcbde1f02aac0"
LABEL_FIDELITY_REVIEW_SCHEMA = \
    "teacher-stage-c-label-fidelity-consumption-review-v3"
LABEL_FIDELITY_REVIEW_MARKER = \
    "TEACHER_STAGE_C_LABEL_FIDELITY_CONSUMPTION_V3_REVIEW "
REVIEW_SCHEMA = "teacher-stage-c-v11-free-training-controller-review-v1"
REVIEW_MARKER = "TEACHER_STAGE_C_V11_FREE_TRAINING_CONTROLLER_V1_REVIEW "

EXPECTED_SPLITS = {"DESIGN": 1024, "CALIB": 512}
EXPECTED_SURFACES = {
    "DESIGN": {"play": 960, "bury": 64},
    "CALIB": {"play": 480, "bury": 32},
}
TRAINING_CELLS = len(MODEL.SURFACES) * len(MODEL.TRAINING_SEEDS) \
    * len(MODEL.CURVE_FRACTIONS)
SUPERVISOR_MAX_WORKERS = len(MODEL.TRAINING_SEEDS)
SUPERVISOR_HEARTBEAT_SECONDS = 30
SUPERVISOR_HANDLED_SIGNALS = ("SIGHUP", "SIGINT", "SIGTERM")

SOURCE_PATHS = (
    "server/scripts/teacher_stage_c_training_controller.py",
    "server/scripts/teacher_stage_c_training_runtime.py",
    SUPERVISOR_PATH,
    "server/shengji/rl/stage_c_model.py",
    "server/shengji/rl/stage_c_training.py",
    "server/shengji/rl/encode.py",
    "server/scripts/teacher_stage_c_label_controller.py",
    "server/scripts/teacher_stage_c_label_runtime.py",
    "server/scripts/teacher_stage_c_fresh_report_controller.py",
    "server/scripts/teacher_stage_c_capture_controller.py",
    "server/scripts/teacher_stage_c_capture_runtime.py",
)


class TrainingControllerRefused(RuntimeError):
    """A label, split, dataset, model schedule, or authority boundary drifted."""


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


def self_hash(value: Mapping[str, object], field: str) -> str:
    return sha256_bytes(canonical_json({
        key: item for key, item in value.items() if key != field
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
        raise TrainingControllerRefused(
            f"input is not regular/unlinked: {path}")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise TrainingControllerRefused(f"cannot read JSON {path}: {exc}") \
            from exc
    if not isinstance(value, dict):
        raise TrainingControllerRefused(f"JSON root is not an object: {path}")
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
            raise TrainingControllerRefused(
                f"training-controller source unavailable: {logical}")
        result[logical] = sha256_file(path)
    return result


def runtime_contract() -> dict:
    if MODEL.torch is None:
        raise TrainingControllerRefused("Stage-C training runtime lacks torch")
    try:
        import numpy
    except ImportError as exc:
        raise TrainingControllerRefused(
            "Stage-C training runtime lacks numpy") from exc
    return {
        "host": platform.node(),
        "python": platform.python_version(),
        "torch": str(MODEL.torch.__version__),
        "numpy": str(numpy.__version__),
        "device": "cpu",
        "cpu_threads_per_cell": TRAIN.CPU_THREADS,
        "max_concurrent_cells": SUPERVISOR_MAX_WORKERS,
        "supervisor_signal_contract": {
            "handled_signals": list(SUPERVISOR_HANDLED_SIGNALS),
            "signals_deferred_until_child_registered": True,
            "terminates_all_owned_children": True,
            "orphaned_cells_authorized": False,
        },
        "heartbeat": (
            "each cell logs one JSON record after every epoch; the one-shot "
            "supervisor publishes fleet progress at least every 30 seconds"
        ),
    }


def marker_claim(path: Path, marker: str) -> dict:
    if not is_regular_unlinked(path):
        raise TrainingControllerRefused("review record is not regular/unlinked")
    matches = [line[len(marker):] for line in path.read_text().splitlines()
               if line.startswith(marker)]
    if len(matches) != 1:
        raise TrainingControllerRefused(
            f"review record must contain exactly one {marker.strip()} marker")
    try:
        value = json.loads(matches[0])
    except ValueError as exc:
        raise TrainingControllerRefused("review marker is not JSON") from exc
    if not isinstance(value, dict):
        raise TrainingControllerRefused("review marker root is not an object")
    return value


def _manifest_hash(value: object) -> str:
    return sha256_bytes(canonical_json(value))


def candidate_provenance_contract() -> dict:
    """State exactly how frozen proposal provenance may reach the learner."""
    return {
        "teacher_targets": "mc_counterfactual_signed_level_utility",
        "all_reviewed_candidate_actions_retained": True,
        "candidate_actions_authenticated_by_reviewed_capture": True,
        "candidate_source_tags_in_examples": False,
        "candidate_source_tags_in_model_inputs": False,
        "v11_origin_actions_are_source_agnostic_examples": True,
        "v11_checkpoint_use_after_label_generation": "none",
        "training_controller_loads_v11": False,
        "training_runtime_loads_v11": False,
        "v11_proposer_admitted_for_inference": False,
        "inference_must_not_load_v11": True,
    }


def _label_fidelity_values(aggregate: Mapping[str, object]) -> tuple[float, ...]:
    gate = aggregate.get("fidelity_gate")
    if not isinstance(gate, dict):
        raise TrainingControllerRefused("label aggregate gate is missing")
    ordinary = gate.get("ordinary_anchor_regret")
    hard = gate.get("hard_tail_regret")
    recall = gate.get("v11_recall_treatment_minus_matched_random")
    if not all(isinstance(value, dict)
               for value in (ordinary, hard, recall)):
        raise TrainingControllerRefused("label aggregate gate metrics missing")
    metric_values = (
        ordinary.get("mean"), ordinary.get("one_sided_95_ucb"),
        hard.get("mean"), hard.get("one_sided_95_ucb"),
        recall.get("mean"), recall.get("one_sided_95_lcb"),
        recall.get("one_sided_95_ucb"),
    )
    if any(isinstance(value, bool)
           or not isinstance(value, (int, float))
           or not math.isfinite(float(value)) for value in metric_values):
        raise TrainingControllerRefused(
            "label aggregate fidelity metric is missing/non-finite")
    return tuple(float(value) for value in metric_values)


def label_fidelity_summary(
        aggregate: Mapping[str, object], aggregate_sha256: str) -> dict:
    values = _label_fidelity_values(aggregate)
    gate = aggregate["fidelity_gate"]
    if (gate.get("schema") != "teacher-stage-c-label-fidelity-gate-v2"
            or gate.get("fidelity_pass") is not True
            or gate.get("v11_recall_pass") is not False
            or values[1] > 0.10
            or values[3] > 0.10
            or gate.get("decision") != "DIAGNOSE_FROZEN_STAGE_C_ONLY"
            or aggregate.get("model_packet_review_authorized") is not False):
        raise TrainingControllerRefused(
            "label aggregate does not admit the V11-free route")
    return {
        "schema": "teacher-stage-c-v11-free-label-fidelity-summary-v1",
        "label_git": aggregate.get("git"),
        "aggregate_sha256": aggregate_sha256,
        "aggregate_internal_sha256": aggregate.get("aggregate_sha256"),
        "state_set_sha256": aggregate.get("state_set_sha256"),
        "original_combined_decision": gate.get("decision"),
        "label_fidelity_pass": True,
        "ordinary_anchor_regret_mean": values[0],
        "ordinary_anchor_regret_ucb": values[1],
        "hard_tail_regret_mean": values[2],
        "hard_tail_regret_ucb": values[3],
        "v11_recall_mean": values[4],
        "v11_recall_lcb": values[5],
        "v11_recall_ucb": values[6],
        "v11_recall_pass": False,
        "v11_proposer_admitted": False,
        "old_report_quarantined": True,
    }


def expected_label_fidelity_review_claim(
        aggregate: Mapping[str, object], aggregate_sha256: str) -> dict:
    """Bind V11-free consumption to the independently replayed label result."""
    if (aggregate_sha256 != LABEL_AGGREGATE_SHA256
            or aggregate.get("aggregate_sha256")
            != LABEL_AGGREGATE_INTERNAL_SHA256):
        raise TrainingControllerRefused(
            "label fidelity review does not name the terminal aggregate")
    summary = label_fidelity_summary(aggregate, aggregate_sha256)
    design = aggregate.get("design_calib_manifest")
    report = aggregate.get("sealed_report_manifest")
    if not isinstance(design, dict) or not isinstance(report, dict):
        raise TrainingControllerRefused(
            "label aggregate manifests are missing")
    return {
        "schema": LABEL_FIDELITY_REVIEW_SCHEMA,
        "label_git": aggregate.get("git"),
        "aggregate_sha256": aggregate_sha256,
        "aggregate_internal_sha256": aggregate.get("aggregate_sha256"),
        "state_set_sha256": aggregate.get("state_set_sha256"),
        "states": aggregate.get("states"),
        "complete_rows": aggregate.get("complete_rows"),
        "refused_rows": aggregate.get("refused_rows"),
        "original_combined_decision": summary[
            "original_combined_decision"],
        "label_fidelity_pass": True,
        "ordinary_anchor_regret_mean": summary[
            "ordinary_anchor_regret_mean"],
        "ordinary_anchor_regret_ucb": summary[
            "ordinary_anchor_regret_ucb"],
        "hard_tail_regret_mean": summary["hard_tail_regret_mean"],
        "hard_tail_regret_ucb": summary["hard_tail_regret_ucb"],
        "v11_recall_mean": summary["v11_recall_mean"],
        "v11_recall_lcb": summary["v11_recall_lcb"],
        "v11_recall_ucb": summary["v11_recall_ucb"],
        "v11_recall_pass": False,
        "v11_proposer_admitted": False,
        "candidate_provenance_contract_sha256": _manifest_hash(
            candidate_provenance_contract()),
        "training_controller_script_sha256": sha256_file(SCRIPT),
        "stage_c_model_script_sha256": sha256_file(
            SERVER / "shengji/rl/stage_c_model.py"),
        "design_calib_manifest_sha256": _manifest_hash(design),
        "sealed_report_manifest_sha256": _manifest_hash(report),
        "report_shards_opened_by_training_review": 0,
        "independent_review": True,
        "one_v11_free_training_controller_freeze_authorized": True,
        "training_authorized": False,
        "report_open_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }


def validate_label_aggregate(
    path: Path, expected_sha256: str, review_record: Path,
) -> tuple[dict, dict]:
    if (expected_sha256 != LABEL_AGGREGATE_SHA256
            or sha256_file(path) != expected_sha256):
        raise TrainingControllerRefused("label aggregate external SHA-256 drift")
    aggregate = load_json(path)
    gate = aggregate.get("fidelity_gate")
    design = aggregate.get("design_calib_manifest")
    report = aggregate.get("sealed_report_manifest")
    shards = aggregate.get("shards")
    metric_values = _label_fidelity_values(aggregate)
    if (aggregate.get("schema") != LABEL_CTRL.AGGREGATE_SCHEMA
            or aggregate.get("run_id") != LABEL_CTRL.RUN_ID
            or aggregate.get("aggregate_sha256")
            != LABEL_AGGREGATE_INTERNAL_SHA256
            or aggregate.get("aggregate_sha256")
            != self_hash(aggregate, "aggregate_sha256")
            or aggregate.get("status") != "COMPLETE"
            or aggregate.get("states") != 2048
            or aggregate.get("complete_rows") != 2048
            or aggregate.get("refused_rows") != 0
            or aggregate.get("utility_published") is not True
            or aggregate.get("training_authorized") is not False
            or aggregate.get("report_open_authorized") is not False
            or not isinstance(gate, dict)
            or gate.get("schema")
            != "teacher-stage-c-label-fidelity-gate-v2"
            or gate.get("fidelity_pass") is not True
            or gate.get("v11_recall_pass") is not False
            or float(metric_values[1]) > 0.10
            or float(metric_values[3]) > 0.10
            or gate.get("decision") != "DIAGNOSE_FROZEN_STAGE_C_ONLY"
            or aggregate.get("model_packet_review_authorized") is not False
            or not isinstance(shards, list) or len(shards) != 16
            or [value.get("index") for value in shards] != list(range(16))
            or [value.get("split") for value in shards]
            != ["DESIGN"] * 8 + ["CALIB"] * 4 + ["REPORT"] * 4
            or not isinstance(design, dict)
            or design.get("splits") != ["DESIGN", "CALIB"]
            or design.get("states") != 1536
            or design.get("report_rows_included") is not False
            or not isinstance(design.get("shards"), list)
            or len(design["shards"]) != 12
            or any(value.get("split") not in {"DESIGN", "CALIB"}
                   for value in design["shards"])
            or not isinstance(report, dict)
            or report.get("split") != "REPORT"
            or report.get("states") != 512
            or report.get("sealed_from_training_and_seed_selection") is not True
            or report.get("report_open_authorized") is not False
            or not isinstance(report.get("shards"), list)
            or len(report["shards"]) != 4
            or any(value.get("split") != "REPORT"
                   for value in report["shards"])
            or design["shards"] != shards[:12]
            or report["shards"] != shards[12:]):
        raise TrainingControllerRefused(
            "label aggregate status/split/authority drift")
    claim = marker_claim(review_record, LABEL_FIDELITY_REVIEW_MARKER)
    expected = expected_label_fidelity_review_claim(
        aggregate, expected_sha256)
    if claim != expected:
        raise TrainingControllerRefused(
            "label fidelity-consumption PASS marker drift")
    return aggregate, claim


def validate_fresh_report(
    path: Path, expected_sha256: str, review_record: Path,
    state_set_review_record: Path,
) -> tuple[dict, dict]:
    expected_path = (REPO / FRESH.PACKET_PATH).resolve()
    if (path.resolve() != expected_path
            or expected_sha256 != FRESH_REPORT_PACKET_SHA256):
        raise TrainingControllerRefused(
            "fresh REPORT packet path/SHA-256 drift")
    try:
        packet = FRESH.validate_packet(
            packet_path=path,
            expected_external_sha256=expected_sha256,
            state_set_review_record=state_set_review_record)
    except FRESH.FreshReportRefused as exc:
        raise TrainingControllerRefused(
            f"fresh REPORT packet validation failed: {exc}") from exc
    claim = marker_claim(review_record, FRESH.REVIEW_MARKER)
    expected = FRESH.expected_review_claim(packet, expected_sha256)
    if (claim != expected
            or claim.get(
                "one_v11_free_training_controller_freeze_authorized")
            is not True
            or claim.get("training_authorized") is not False
            or claim.get("report_open_authorized") is not False):
        raise TrainingControllerRefused("fresh REPORT PASS marker drift")
    return packet, claim


def fresh_report_dataset_contract(
    fresh_report: Mapping[str, object],
    fresh_report_review: Mapping[str, object],
) -> dict:
    sealed = fresh_report["sealed_selection"]
    return {
        "packet_external_sha256": FRESH_REPORT_PACKET_SHA256,
        "packet_internal_sha256": fresh_report["packet_sha256"],
        "review_claim_sha256": _manifest_hash(fresh_report_review),
        "sealed_selection_sha256": sealed["sealed_selection_sha256"],
        "fresh_report_state_ids_sha256": sealed[
            "fresh_report_state_ids_sha256"],
        "fresh_report_state_material_sha256": sealed[
            "fresh_report_state_material_sha256"],
        "fresh_report_per_state_hashes_sha256": sealed[
            "fresh_report_per_state_hashes_sha256"],
        "effective_state_ids_sha256": sealed[
            "effective_state_ids_sha256"],
        "fresh_report_states": 512,
    }


def _expected_label_shard_path(packet: Mapping[str, object], index: int) -> Path:
    schedule = packet["schedule"]["shards"][index]
    return (REPO / "server/runs/logs" / LABEL_CTRL.RUN_ID
            / str(schedule["split"]).lower()
            / f"shard-{int(schedule['local_shard']):02d}.json").resolve()


def _design_calib_manifest(
        aggregate: Mapping[str, object]) -> list[Mapping[str, object]]:
    values = aggregate["design_calib_manifest"]["shards"]
    expected_indices = list(range(12))
    if ([value.get("index") for value in values] != expected_indices
            or [value.get("split") for value in values]
            != ["DESIGN"] * 8 + ["CALIB"] * 4):
        raise TrainingControllerRefused(
            "DESIGN/CALIB label manifest order drift")
    return values


def _validate_label_shard_without_v11(
    shard: Mapping[str, object], *, packet: Mapping[str, object],
    receipt_sha256: str, state_set: Mapping[str, object], index: int,
) -> None:
    """Recheck a frozen label shard without reconstructing proposal sources.

    The externally reviewed capture authenticates the candidate tensor.  This
    consumer therefore validates each row against that tensor and replays every
    game/label/work semantic, but deliberately does not rerun the historical
    V11 proposer that helped create some capture ballots.
    """
    schedule = packet["schedule"]["shards"][index]
    rows = shard.get("rows")
    if (shard.get("schema") != LABEL_CTRL.SHARD_SCHEMA
            or shard.get("run_id") != LABEL_CTRL.RUN_ID
            or shard.get("git") != packet["producer"]["git"]
            or shard.get("controller_packet_sha256")
            != packet["external_sha256"]
            or shard.get("label_receipt_sha256") != receipt_sha256
            or shard.get("state_set_sha256")
            != packet["parents"]["state_set"]["external_sha256"]
            or shard.get("schedule_sha256")
            != packet["schedule"]["schedule_sha256"]
            or shard.get("shard_index") != index
            or shard.get("split") != schedule["split"]
            or shard.get("local_shard") != schedule["local_shard"]
            or shard.get("state_ids") != schedule["state_ids"]
            or shard.get("state_ids_sha256") != schedule["state_ids_sha256"]
            or shard.get("audit_state_ids") != schedule["audit_state_ids"]
            or shard.get("shard_admission_slot")
            != LABEL_CTRL.shard_admission_logical_path(index)
            or not isinstance(shard.get("shard_admission_file_sha256"), str)
            or not isinstance(rows, list)
            or len(rows) != schedule["state_count"]
            or shard.get("shard_sha256")
            != LABEL._self_hash(shard, "shard_sha256")
            or shard.get("training_authorized") is not False
            or shard.get("report_open_authorized") is not False):
        raise TrainingControllerRefused(
            f"DESIGN/CALIB label shard {index} identity drift")
    try:
        LABEL._validate_shard_slot(
            packet, index=index,
            packet_sha256=packet["external_sha256"],
            receipt_sha256=receipt_sha256,
            expected_file_sha256=shard["shard_admission_file_sha256"])
        states = LABEL._state_map(state_set)
        audit_ids = set(schedule["audit_state_ids"])
        complete = 0
        refused = 0
        for state_id, row in zip(schedule["state_ids"], rows, strict=True):
            state = states[state_id]
            if row.get("state_id") != state_id:
                raise LABEL.LabelRefused(
                    f"Stage-C label shard {index} row order drift")
            if row.get("status") == "COMPLETE":
                rnd = CAPTURE.replay_state(state)
                LABEL.validate_label_row(
                    state, rnd, row,
                    audit_expected=state_id in audit_ids)
                complete += 1
            else:
                LABEL.validate_refusal_record(
                    state, row, audit_expected=state_id in audit_ids)
                refused += 1
        expected_status = ("COMPLETE" if refused == 0
                           else "REFUSED_INCOMPLETE_NO_AGGREGATE_UTILITY")
        work = LABEL._work_from_rows(rows)
        if (shard.get("status") != expected_status
                or shard.get("complete_rows") != complete
                or shard.get("refused_rows") != refused
                or shard.get("row_sha256s")
                != [row["row_sha256"] for row in rows]
                or shard.get("work") != work
                or shard.get("expected_candidate_worlds")
                != schedule["candidate_worlds"]
                or shard.get("candidate_world_ceiling_respected")
                is not (work["candidate_worlds_attempted"]
                        <= schedule["candidate_worlds"])):
            raise LABEL.LabelRefused(
                f"Stage-C label shard {index} work/status drift")
    except LABEL.LabelRefused as exc:
        raise TrainingControllerRefused(
            f"DESIGN/CALIB label shard {index} semantic drift: {exc}") from exc


def materialize_dataset(
    *, label_packet: Mapping[str, object], label_receipt_sha256: str,
    state_set: Mapping[str, object], aggregate: Mapping[str, object],
    fresh_report: Mapping[str, object],
    fresh_report_review: Mapping[str, object],
) -> dict:
    """Open only DESIGN/CALIB shards and encode their public examples."""
    states = {str(value["state_id"]): value for value in state_set["states"]}
    if len(states) != 2048:
        raise TrainingControllerRefused("Stage-C state map identity drift")
    manifest = _design_calib_manifest(aggregate)
    examples = {
        "DESIGN": {"play": [], "bury": []},
        "CALIB": {"play": [], "bury": []},
    }
    consumed = []
    for index, expected in enumerate(manifest):
        path = _expected_label_shard_path(label_packet, index)
        if sha256_file(path) != expected.get("sha256"):
            raise TrainingControllerRefused(
                f"DESIGN/CALIB label shard {index} external SHA drift")
        shard = load_json(path)
        _validate_label_shard_without_v11(
            shard, packet=label_packet,
            receipt_sha256=label_receipt_sha256,
            state_set=state_set, index=index)
        if (shard.get("status") != "COMPLETE"
                or shard.get("refused_rows") != 0
                or shard.get("split") not in examples
                or sha256_bytes(canonical_json(shard.get("row_sha256s")))
                != expected.get("row_sha256s_sha256")):
            raise TrainingControllerRefused(
                f"DESIGN/CALIB label shard {index} incomplete")
        split = str(shard["split"])
        for state_id, row in zip(
                shard["state_ids"], shard["rows"], strict=True):
            state = states[str(state_id)]
            if state.get("split") != split or row.get("split") != split:
                raise TrainingControllerRefused(
                    "DESIGN/CALIB state/label split drift")
            rnd = CAPTURE.replay_state(state)
            example = MODEL.materialize_example(state, row, rnd)
            surface = str(example["surface_type"])
            if surface not in MODEL.SURFACES:
                raise TrainingControllerRefused(
                    "DESIGN/CALIB model surface drift")
            examples[split][surface].append(example)
        consumed.append({
            "index": index,
            "split": split,
            "sha256": expected["sha256"],
            "row_sha256s_sha256": expected["row_sha256s_sha256"],
        })
    for split, surfaces in examples.items():
        if {surface: len(values) for surface, values in surfaces.items()} \
                != EXPECTED_SURFACES[split]:
            raise TrainingControllerRefused(
                f"Stage-C {split} model surface count drift")
        for surface, values in surfaces.items():
            TRAIN.validate_population(values, split=split, surface=surface)
    design_ids = {value["state_id"]
                  for values in examples["DESIGN"].values() for value in values}
    calib_ids = {value["state_id"]
                 for values in examples["CALIB"].values() for value in values}
    if len(design_ids) != 1024 or len(calib_ids) != 512 \
            or design_ids & calib_ids:
        raise TrainingControllerRefused(
            "Stage-C model dataset split identity drift")
    payload = {
        "schema": DATASET_SCHEMA,
        "run_id": RUN_ID,
        "label_git": aggregate["git"],
        "label_aggregate_sha256": aggregate["external_sha256"],
        "state_set_sha256": aggregate["state_set_sha256"],
        "split_counts": dict(EXPECTED_SPLITS),
        "surface_counts": EXPECTED_SURFACES,
        "design_calib_label_shards": consumed,
        "examples": examples,
        "design_state_ids_sha256": sha256_bytes(canonical_json(
            sorted(design_ids))),
        "calib_state_ids_sha256": sha256_bytes(canonical_json(
            sorted(calib_ids))),
        "fresh_report_selection": fresh_report_dataset_contract(
            fresh_report, fresh_report_review),
        "candidate_provenance_contract": candidate_provenance_contract(),
        "old_report_labels_quarantined": True,
        "report_rows_included": False,
        "report_label_shard_files_opened": 0,
        "fresh_report_states_materialized": False,
        "fresh_report_capture_shards_revalidated": 8,
        "training_authorized": False,
        "report_open_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    payload["dataset_sha256"] = self_hash(payload, "dataset_sha256")
    return payload


def build_schedule() -> dict:
    cells = []
    index = 0
    for surface in MODEL.SURFACES:
        for seed in MODEL.TRAINING_SEEDS:
            for curve_fraction in MODEL.CURVE_FRACTIONS:
                cell_id = f"{surface}-seed{seed}-curve{int(curve_fraction * 100):03d}"
                cells.append({
                    "index": index,
                    "cell_id": cell_id,
                    "surface": surface,
                    "seed": seed,
                    "curve_fraction": curve_fraction,
                    "design_states": EXPECTED_SURFACES["DESIGN"][surface],
                    "calib_states": EXPECTED_SURFACES["CALIB"][surface],
                    "epoch_grid": list(MODEL.EPOCH_GRID),
                    "result": f"server/runs/logs/{RUN_ID}/cells/{cell_id}.json",
                    "snapshot_dir":
                        f"server/runs/logs/{RUN_ID}/checkpoints/{cell_id}",
                })
                index += 1
    if (len(cells) != TRAINING_CELLS
            or [value["index"] for value in cells]
            != list(range(TRAINING_CELLS))
            or len({value["cell_id"] for value in cells}) != TRAINING_CELLS):
        raise TrainingControllerRefused("Stage-C training cell schedule drift")
    payload = {
        "cells": cells,
        "cell_count": TRAINING_CELLS,
        "surfaces": list(MODEL.SURFACES),
        "seeds": list(MODEL.TRAINING_SEEDS),
        "curve_fractions": list(MODEL.CURVE_FRACTIONS),
        "epoch_grid": list(MODEL.EPOCH_GRID),
        "full_curve_cells_for_calib_selection": 16,
        "single_seed_selection": False,
        "report_rows_included": False,
    }
    payload["schedule_sha256"] = self_hash(payload, "schedule_sha256")
    return payload


def model_contract() -> dict:
    return {
        "architecture": f"StageCRankingOutcomeNet(hidden={TRAIN.HIDDEN})",
        "separate_play_bury_weights": True,
        "ranking_target": "paired-common-world-within-ballot",
        "outcome_target": "eight-bin-acting-team-signed-level-utility",
        "utility_bins": list(MODEL.UTILITY_BINS),
        "loss_weights": {
            "pairwise_bce": MODEL.PAIRWISE_WEIGHT,
            "frozen_label_ce": MODEL.LABEL_CE_WEIGHT,
            "outcome_distribution_ce": MODEL.OUTCOME_CE_WEIGHT,
        },
        "batch_size_states": TRAIN.BATCH_SIZE,
        "learning_rate": TRAIN.LEARNING_RATE,
        "weight_decay": TRAIN.WEIGHT_DECAY,
        "gradient_clip_norm": 5.0,
        "max_epoch": TRAIN.MAX_EPOCH,
        "device": "cpu",
        "cpu_threads": TRAIN.CPU_THREADS,
        "deterministic_algorithms": True,
        "candidate_provenance": candidate_provenance_contract(),
        "calib_selection": (
            "exactly one surface/head/epoch eight-seed capability; "
            "no unrelated-surface conjunction and no seed cherry-pick"),
    }


def cell_hyperparameters() -> dict:
    return {
        "architecture": f"StageCRankingOutcomeNet(hidden={TRAIN.HIDDEN})",
        "batch_size_states": TRAIN.BATCH_SIZE,
        "learning_rate": TRAIN.LEARNING_RATE,
        "weight_decay": TRAIN.WEIGHT_DECAY,
        "gradient_clip_norm": 5.0,
        "max_epoch": TRAIN.MAX_EPOCH,
        "cpu_threads": TRAIN.CPU_THREADS,
        "device": "cpu",
        "deterministic_algorithms": True,
    }


def result_contract(schedule: Mapping[str, object]) -> dict:
    return {
        "cells": [value["result"] for value in schedule["cells"]],
        "aggregate": f"server/runs/logs/{RUN_ID}/training-aggregate.json",
        "supervisor_progress":
            f"server/runs/logs/{RUN_ID}/training-supervisor.jsonl",
        "supervisor_final":
            f"server/runs/logs/{RUN_ID}/training-supervisor-final.json",
        "selection_rule": MODEL.SELECTION_SCHEMA,
        "curve_diagnostics": {
            "surfaces": list(MODEL.SURFACES),
            "curve_fractions": list(MODEL.CURVE_FRACTIONS),
            "epoch_grid": list(MODEL.EPOCH_GRID),
            "seeds_per_row": len(MODEL.TRAINING_SEEDS),
            "selection_eligible_curve_fraction": 1.0,
            "smaller_curves_are_diagnostic_only": True,
        },
        "selected_ensemble_models": len(MODEL.TRAINING_SEEDS),
        "single_capability_selection": True,
        "report_packet_review_only_on_pass": True,
        "supervision": {
            "max_concurrent_cells": SUPERVISOR_MAX_WORKERS,
            "heartbeat_seconds": SUPERVISOR_HEARTBEAT_SECONDS,
            "handled_signals": list(SUPERVISOR_HANDLED_SIGNALS),
            "signals_deferred_until_child_registered": True,
            "terminates_all_owned_children": True,
            "orphaned_cells_authorized": False,
            "starts_all_frozen_cells": True,
            "resume_authorized": False,
            "retry_authorized": False,
            "aggregate_only_after_all_cells_exit_zero": True,
        },
    }


def commands(schedule: Mapping[str, object]) -> dict:
    values = {
        "admit": [
            "{python}", "server/scripts/teacher_stage_c_training_runtime.py",
            "admit", "--expected-git", "{git}",
            "--controller-packet", PACKET_PATH,
            "--expected-controller-packet-sha256", "{packet_sha256}",
            "--controller-review-record", "{controller_review_record}",
            "--out", f"server/runs/logs/{RUN_ID}/training-receipt.json",
        ],
        "run_cells": [{
            "index": cell["index"],
            "command": [
                "{python}", "server/scripts/teacher_stage_c_training_runtime.py",
                "run-cell", "--expected-git", "{git}",
                "--controller-packet", PACKET_PATH,
                "--expected-controller-packet-sha256", "{packet_sha256}",
                "--controller-review-record", "{controller_review_record}",
                "--training-receipt",
                f"server/runs/logs/{RUN_ID}/training-receipt.json",
                "--expected-training-receipt-sha256", "{receipt_sha256}",
                "--cell-index", str(cell["index"]),
                "--out", cell["result"],
            ],
        } for cell in schedule["cells"]],
        "aggregate": [
            "{python}", "server/scripts/teacher_stage_c_training_runtime.py",
            "aggregate", "--expected-git", "{git}",
            "--controller-packet", PACKET_PATH,
            "--expected-controller-packet-sha256", "{packet_sha256}",
            "--controller-review-record", "{controller_review_record}",
            "--training-receipt",
            f"server/runs/logs/{RUN_ID}/training-receipt.json",
            "--expected-training-receipt-sha256", "{receipt_sha256}",
            "--cells", *[value["result"] for value in schedule["cells"]],
            "--out", f"server/runs/logs/{RUN_ID}/training-aggregate.json",
        ],
    }
    values["supervise"] = [
        "{python}", SUPERVISOR_PATH, "launch",
        "--expected-git", "{git}",
        "--controller-packet", PACKET_PATH,
        "--expected-controller-packet-sha256", "{packet_sha256}",
        "--controller-review-record", "{controller_review_record}",
        "--training-receipt",
        f"server/runs/logs/{RUN_ID}/training-receipt.json",
        "--expected-training-receipt-sha256", "{receipt_sha256}",
        "--heartbeat-seconds", str(SUPERVISOR_HEARTBEAT_SECONDS),
    ]
    values["verify_supervisor"] = [
        "{python}", SUPERVISOR_PATH, "verify",
        "--expected-git", "{git}",
        "--controller-packet", PACKET_PATH,
        "--expected-controller-packet-sha256", "{packet_sha256}",
        "--controller-review-record", "{controller_review_record}",
        "--training-receipt",
        f"server/runs/logs/{RUN_ID}/training-receipt.json",
        "--expected-training-receipt-sha256", "{receipt_sha256}",
        "--heartbeat-seconds", str(SUPERVISOR_HEARTBEAT_SECONDS),
    ]
    return values


def build_packet(
    *, git: str, dataset: Mapping[str, object], dataset_external_sha256: str,
    aggregate: Mapping[str, object], aggregate_review: Mapping[str, object],
    fresh_report: Mapping[str, object],
    fresh_report_review: Mapping[str, object],
) -> dict:
    if dataset.get("dataset_sha256") != self_hash(dataset, "dataset_sha256"):
        raise TrainingControllerRefused("model dataset internal SHA drift")
    if (aggregate_review.get("schema") != LABEL_FIDELITY_REVIEW_SCHEMA
            or aggregate_review.get("aggregate_sha256")
            != aggregate.get("external_sha256")
            or aggregate_review.get("aggregate_internal_sha256")
            != aggregate.get("aggregate_sha256")
            or aggregate_review.get(
                "one_v11_free_training_controller_freeze_authorized")
            is not True
            or aggregate_review.get("verdict") != "PASS"):
        raise TrainingControllerRefused(
            "label fidelity-consumption review binding drift")
    if (dataset.get("fresh_report_selection")
            != fresh_report_dataset_contract(
                fresh_report, fresh_report_review)
            or dataset.get("candidate_provenance_contract")
            != candidate_provenance_contract()
            or dataset.get("old_report_labels_quarantined") is not True
            or dataset.get("report_rows_included") is not False
            or dataset.get("report_label_shard_files_opened") != 0
            or dataset.get("fresh_report_states_materialized") is not False):
        raise TrainingControllerRefused(
            "model dataset fresh REPORT/V11-free contract drift")
    schedule = build_schedule()
    fidelity = label_fidelity_summary(
        aggregate, str(aggregate["external_sha256"]))
    sealed = fresh_report["sealed_selection"]
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
            "label_aggregate": {
                "external_sha256": aggregate["external_sha256"],
                "internal_sha256": aggregate["aggregate_sha256"],
                "review_schema": LABEL_FIDELITY_REVIEW_SCHEMA,
                "review_claim_sha256": _manifest_hash(aggregate_review),
                "fidelity_summary": fidelity,
                "fidelity_summary_sha256": _manifest_hash(fidelity),
                "original_combined_decision":
                    aggregate["fidelity_gate"]["decision"],
                "label_fidelity_pass": True,
                "v11_proposer_admitted": False,
                "old_report_labels_quarantined": True,
            },
            "fresh_report_selection": {
                "external_sha256": FRESH_REPORT_PACKET_SHA256,
                "internal_sha256": fresh_report["packet_sha256"],
                "review_schema": FRESH.REVIEW_SCHEMA,
                "review_claim_sha256": _manifest_hash(fresh_report_review),
                "sealed_selection_sha256": sealed[
                    "sealed_selection_sha256"],
                "fresh_report_state_ids_sha256": sealed[
                    "fresh_report_state_ids_sha256"],
                "fresh_report_state_material_sha256": sealed[
                    "fresh_report_state_material_sha256"],
                "effective_state_ids_sha256": sealed[
                    "effective_state_ids_sha256"],
                "fresh_report_states": sealed["fresh_report_states"],
                "state_material_published": False,
            },
            "model_dataset": {
                "logical_path": DATASET_PATH,
                "external_sha256": dataset_external_sha256,
                "internal_sha256": dataset["dataset_sha256"],
                "design_states": 1024,
                "calib_states": 512,
                "report_rows_included": False,
                "fresh_report_selection_sha256": _manifest_hash(
                    dataset["fresh_report_selection"]),
            },
        },
        "runtime_contract": runtime_contract(),
        "model_contract": model_contract(),
        "schedule": schedule,
        "result_contract": result_contract(schedule),
        "commands": commands(schedule),
        "authority": {
            "examples_materialized": True,
            "training_started": False,
            "one_training_execution_authorized": False,
            "v11_inference_authorized": False,
            "report_rows_opened": 0,
            "report_open_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
            "production_deployment": False,
        },
    }
    packet["packet_sha256"] = self_hash(packet, "packet_sha256")
    return packet


def expected_review_claim(packet: Mapping[str, object],
                          packet_external_sha256: str) -> dict:
    dataset = packet["parents"]["model_dataset"]
    schedule = packet["schedule"]
    sources = packet["producer"]["sources"]
    return {
        "schema": REVIEW_SCHEMA,
        "git": packet["producer"]["git"],
        "packet_sha256": packet_external_sha256,
        "packet_internal_sha256": packet["packet_sha256"],
        "controller_script_sha256": sources[
            "server/scripts/teacher_stage_c_training_controller.py"],
        "model_script_sha256": sources[
            "server/shengji/rl/stage_c_model.py"],
        "training_runtime_sha256": sources[
            "server/shengji/rl/stage_c_training.py"],
        "training_runtime_cli_sha256": sources[
            "server/scripts/teacher_stage_c_training_runtime.py"],
        "training_supervisor_sha256": sources[SUPERVISOR_PATH],
        "encoder_sha256": sources["server/shengji/rl/encode.py"],
        "model_contract_sha256": _manifest_hash(packet["model_contract"]),
        "runtime_contract_sha256": _manifest_hash(packet["runtime_contract"]),
        "execution_host": packet["runtime_contract"]["host"],
        "python": packet["runtime_contract"]["python"],
        "torch": packet["runtime_contract"]["torch"],
        "label_aggregate_sha256": packet["parents"]["label_aggregate"][
            "external_sha256"],
        "label_fidelity_summary_sha256": packet["parents"][
            "label_aggregate"]["fidelity_summary_sha256"],
        "label_fidelity_review_claim_sha256": packet["parents"][
            "label_aggregate"]["review_claim_sha256"],
        "fresh_report_packet_sha256": packet["parents"][
            "fresh_report_selection"]["external_sha256"],
        "fresh_report_selection_sha256": packet["parents"][
            "fresh_report_selection"]["sealed_selection_sha256"],
        "fresh_report_state_ids_sha256": packet["parents"][
            "fresh_report_selection"]["fresh_report_state_ids_sha256"],
        "fresh_report_states_materialized": False,
        "model_dataset_sha256": dataset["external_sha256"],
        "design_states": dataset["design_states"],
        "calib_states": dataset["calib_states"],
        "report_rows_included": False,
        "report_label_shard_files_opened": 0,
        "old_report_labels_quarantined": True,
        "candidate_provenance_contract_sha256": _manifest_hash(
            packet["model_contract"]["candidate_provenance"]),
        "v11_inference_authorized": False,
        "training_cells": schedule["cell_count"],
        "training_seeds": len(schedule["seeds"]),
        "surfaces": schedule["surfaces"],
        "curve_fractions": schedule["curve_fractions"],
        "epoch_grid": schedule["epoch_grid"],
        "schedule_sha256": schedule["schedule_sha256"],
        "cpu_only_deterministic": True,
        "single_seed_selection": False,
        "single_capability_selection": True,
        "max_concurrent_cells": packet["runtime_contract"][
            "max_concurrent_cells"],
        "supervisor_heartbeat_seconds": SUPERVISOR_HEARTBEAT_SECONDS,
        "supervisor_handled_signals": list(SUPERVISOR_HANDLED_SIGNALS),
        "supervisor_signals_deferred_until_child_registered": True,
        "supervisor_terminates_all_owned_children": True,
        "supervisor_orphaned_cells_authorized": False,
        "supervisor_resume_authorized": False,
        "supervisor_retry_authorized": False,
        "independent_review": True,
        "one_training_execution_authorized": True,
        "report_open_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }


def _require_output_available(path: Path) -> None:
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise TrainingControllerRefused(f"refusing existing output: {path}")


def require_freeze_outputs_available(
        dataset_out: Path, packet_out: Path) -> None:
    """Refuse either half of the immutable freeze before publishing one.

    The dataset and controller packet are one logical artifact pair.  Checking
    only the file currently being published can strand a dataset if the packet
    path was already occupied.  Check both final and partial names together,
    once before opening the reviewed inputs and again immediately before the
    first publication.
    """
    if (dataset_out != (REPO / DATASET_PATH).resolve()
            or packet_out != (REPO / PACKET_PATH).resolve()):
        raise TrainingControllerRefused(
            "real Stage-C model dataset/packet output path drift")
    _require_output_available(dataset_out)
    _require_output_available(packet_out)


def publish_exclusive(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = Path(str(path) + ".partial")
    _require_output_available(path)
    data = canonical_json(payload)
    try:
        with partial.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(partial, path, follow_symlinks=False)
        except FileExistsError as exc:
            raise TrainingControllerRefused(
                f"refusing raced output publication: {path}") from exc
        partial.unlink()
    except BaseException:
        raise


def _reviewed_upstream_label_packet(path: Path,
                                    expected_sha256: str) -> dict:
    """Authenticate a reviewed label packet across a downstream Git commit.

    Label execution deliberately pins its producer Git for the lifetime of the
    one-shot run.  Training is a later source commit, so requiring that old
    producer Git to equal the training controller's Git makes the reviewed
    label aggregate impossible to consume.  The safe cross-stage boundary is
    the immutable packet hash plus byte-identical label runtime sources, not an
    equality between two intentionally different producer commits.
    """
    expected_path = (REPO / LABEL_CTRL.CONTROLLER_PACKET_PATH).resolve()
    if (path.resolve() != expected_path or not is_regular_unlinked(path)
            or sha256_file(path) != expected_sha256):
        raise TrainingControllerRefused(
            "reviewed label-controller packet path/SHA drift")
    packet = load_json(path)
    producer = packet.get("producer", {})
    authority = packet.get("authority", {})
    producer_git = producer.get("git")
    try:
        runtime_mode = LABEL_CTRL.CAPTURE_CTRL.require_runtime_mode()
        runtime_sources = LABEL_CTRL.runtime_sources()
        shard_slots = LABEL_CTRL.require_shard_admission_slots_ignored()
    except LABEL_CTRL.ControllerRefused as exc:
        raise TrainingControllerRefused(
            f"label-controller source validation failed: {exc}") from exc
    if (not isinstance(producer_git, str) or len(producer_git) != 40
            or any(value not in "0123456789abcdef" for value in producer_git)
            or packet.get("schema") != LABEL_CTRL.SCHEMA
            or packet.get("packet_id") != LABEL_CTRL.PACKET_ID
            or packet.get("run_id") != LABEL_CTRL.RUN_ID
            or packet.get("packet_sha256") != LABEL_CTRL.self_hash(packet)
            or producer.get("tree_dirty") is not False
            or producer.get("promotable") is not True
            or packet.get("runtime_mode") != runtime_mode
            or packet.get("runtime_sources") != runtime_sources
            or packet.get("result_contract", {}).get(
                "shard_admission_slots") != shard_slots
            or authority.get("score_free") is not True
            or authority.get("worlds_sampled") is not False
            or authority.get("outcomes_computed") is not False
            or authority.get("labels_computed") is not False
            or authority.get("one_label_execution_authorized") is not False
            or authority.get("training_authorized") is not False
            or authority.get("report_open_authorized") is not False
            or authority.get("strength_claim") is not False
            or authority.get("production_promotion") is not False
            or authority.get("production_deployment") is not False):
        raise TrainingControllerRefused(
            "reviewed label-controller identity/source/authority drift")
    value = dict(packet)
    value["external_sha256"] = expected_sha256
    return value


def _validated_inputs(args) -> tuple[dict, dict, dict, dict, dict, dict, str]:
    if _git("status", "--porcelain"):
        raise TrainingControllerRefused(
            "real Stage-C training-controller freeze refuses dirty tree")
    git = _git("rev-parse", "HEAD")
    label_packet = _reviewed_upstream_label_packet(
        Path(args.label_controller).resolve(),
        args.expected_label_controller_sha256)
    state_set, _verification = LABEL._validated_parents(
        label_packet, Path(args.state_set_review_record).resolve())
    LABEL._receipt(
        Path(args.label_receipt).resolve(), args.expected_label_receipt_sha256,
        label_packet, args.expected_label_controller_sha256,
        Path(args.label_controller_review_record).resolve(),
        Path(args.state_set_review_record).resolve())
    aggregate, aggregate_review = validate_label_aggregate(
        Path(args.label_aggregate).resolve(),
        args.expected_label_aggregate_sha256,
        Path(args.label_aggregate_review_record).resolve())
    fresh_report, fresh_report_review = validate_fresh_report(
        Path(args.fresh_report_controller).resolve(),
        args.expected_fresh_report_controller_sha256,
        Path(args.fresh_report_review_record).resolve(),
        Path(args.state_set_review_record).resolve())
    if (aggregate.get("controller_packet_sha256")
            != args.expected_label_controller_sha256
            or aggregate.get("label_receipt_sha256")
            != args.expected_label_receipt_sha256
            or aggregate.get("state_set_sha256")
            != label_packet["parents"]["state_set"]["external_sha256"]
            or fresh_report["parents"]["original_state_set"][
                "external_sha256"] != aggregate.get("state_set_sha256")
            or fresh_report["sealed_selection"][
                "design_calib_state_ids_sha256"] != _manifest_hash([
                    str(state["state_id"]) for state in state_set["states"]
                    if state.get("split") in {"DESIGN", "CALIB"}
                ])):
        raise TrainingControllerRefused(
            "label aggregate/fresh REPORT parent drift")
    aggregate = dict(aggregate)
    aggregate["external_sha256"] = args.expected_label_aggregate_sha256
    return (label_packet, state_set, aggregate, aggregate_review,
            fresh_report, fresh_report_review, git)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("freeze", "verify"):
        child = commands.add_parser(name)
        child.add_argument("--label-controller", required=True)
        child.add_argument("--expected-label-controller-sha256", required=True)
        child.add_argument("--label-receipt", required=True)
        child.add_argument("--expected-label-receipt-sha256", required=True)
        child.add_argument("--label-controller-review-record", required=True)
        child.add_argument("--state-set-review-record", required=True)
        child.add_argument("--label-aggregate", required=True)
        child.add_argument("--expected-label-aggregate-sha256", required=True)
        child.add_argument("--label-aggregate-review-record", required=True)
        child.add_argument("--fresh-report-controller", required=True)
        child.add_argument(
            "--expected-fresh-report-controller-sha256", required=True)
        child.add_argument("--fresh-report-review-record", required=True)
        child.add_argument("--dataset-out", required=True)
        child.add_argument("--packet-out", required=True)
        if name == "verify":
            child.add_argument("--expected-dataset-sha256", required=True)
            child.add_argument("--expected-packet-sha256", required=True)
    return root


def main() -> int:
    args = parser().parse_args()
    dataset_out = Path(args.dataset_out).resolve()
    packet_out = Path(args.packet_out).resolve()
    if args.command == "freeze":
        require_freeze_outputs_available(dataset_out, packet_out)
    (label_packet, state_set, aggregate, aggregate_review, fresh_report,
     fresh_report_review, git) = _validated_inputs(args)
    dataset = materialize_dataset(
        label_packet=label_packet,
        label_receipt_sha256=args.expected_label_receipt_sha256,
        state_set=state_set, aggregate=aggregate,
        fresh_report=fresh_report,
        fresh_report_review=fresh_report_review)
    if args.command == "freeze":
        dataset_external_sha256 = sha256_bytes(canonical_json(dataset))
        packet = build_packet(
            git=git, dataset=dataset,
            dataset_external_sha256=dataset_external_sha256,
            aggregate=aggregate, aggregate_review=aggregate_review,
            fresh_report=fresh_report,
            fresh_report_review=fresh_report_review)
        require_freeze_outputs_available(dataset_out, packet_out)
        publish_exclusive(dataset_out, dataset)
        publish_exclusive(packet_out, packet)
    else:
        if (not is_regular_unlinked(dataset_out)
                or sha256_file(dataset_out) != args.expected_dataset_sha256
                or load_json(dataset_out) != dataset):
            raise TrainingControllerRefused(
                "Stage-C model dataset verification drift")
        packet = build_packet(
            git=git, dataset=dataset,
            dataset_external_sha256=args.expected_dataset_sha256,
            aggregate=aggregate, aggregate_review=aggregate_review,
            fresh_report=fresh_report,
            fresh_report_review=fresh_report_review)
        if (not is_regular_unlinked(packet_out)
                or sha256_file(packet_out) != args.expected_packet_sha256
                or load_json(packet_out) != packet):
            raise TrainingControllerRefused(
                "Stage-C training packet verification drift")
    print(json.dumps({
        "status": "FROZEN" if args.command == "freeze" else "VERIFIED",
        "git": git,
        "dataset_sha256": sha256_file(dataset_out),
        "dataset_internal_sha256": dataset["dataset_sha256"],
        "packet_sha256": sha256_file(packet_out),
        "packet_internal_sha256": packet["packet_sha256"],
        "training_cells": packet["schedule"]["cell_count"],
        "training_authorized": False,
        "report_open_authorized": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TrainingControllerRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        raise SystemExit(2)
