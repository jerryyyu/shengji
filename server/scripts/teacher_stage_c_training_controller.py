#!/usr/bin/env python3
"""Freeze the Stage-C DESIGN/CALIB model dataset and training packet.

This controller is downstream of a terminal Stage-C label aggregate and its
independent review.  It reopens and semantically validates only the eight
DESIGN and four CALIB label shards.  The four REPORT shard paths and hashes are
carried forward from the reviewed aggregate as a sealed manifest; this process
never opens those files.

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
import teacher_stage_c_label_controller as LABEL_CTRL  # noqa: E402
import teacher_stage_c_label_runtime as LABEL  # noqa: E402
from shengji.rl import stage_c_model as MODEL  # noqa: E402
from shengji.rl import stage_c_training as TRAIN  # noqa: E402


SCHEMA = "teacher-stage-c-training-controller-v1"
PACKET_ID = "teacher-v3-hard-tail-stage-c-training-controller-v1"
RUN_ID = "teacher-v3-hard-tail-stage-c-training-v1"
CONTROLLER_RUN_ID = "teacher-v3-hard-tail-stage-c-training-controller-v1"
DATASET_SCHEMA = "teacher-stage-c-model-dataset-v1"
DATASET_PATH = f"server/runs/logs/{CONTROLLER_RUN_ID}/model-dataset.json"
PACKET_PATH = f"server/runs/logs/{CONTROLLER_RUN_ID}/controller_packet.json"
SUPERVISOR_PATH = "server/scripts/teacher_stage_c_training_supervisor.py"
LABEL_AGGREGATE_REVIEW_SCHEMA = "teacher-stage-c-label-aggregate-review-v2"
LABEL_AGGREGATE_REVIEW_MARKER = "TEACHER_STAGE_C_LABEL_AGGREGATE_V2_REVIEW "
REVIEW_SCHEMA = "teacher-stage-c-training-controller-review-v1"
REVIEW_MARKER = "TEACHER_STAGE_C_TRAINING_CONTROLLER_V1_REVIEW "

EXPECTED_SPLITS = {"DESIGN": 1024, "CALIB": 512}
EXPECTED_SURFACES = {
    "DESIGN": {"play": 960, "bury": 64},
    "CALIB": {"play": 480, "bury": 32},
}
TRAINING_CELLS = len(MODEL.SURFACES) * len(MODEL.TRAINING_SEEDS) \
    * len(MODEL.CURVE_FRACTIONS)
SUPERVISOR_MAX_WORKERS = len(MODEL.TRAINING_SEEDS)
SUPERVISOR_HEARTBEAT_SECONDS = 30

SOURCE_PATHS = (
    "server/scripts/teacher_stage_c_training_controller.py",
    "server/scripts/teacher_stage_c_training_runtime.py",
    SUPERVISOR_PATH,
    "server/shengji/rl/stage_c_model.py",
    "server/shengji/rl/stage_c_training.py",
    "server/shengji/rl/encode.py",
    "server/scripts/teacher_stage_c_label_controller.py",
    "server/scripts/teacher_stage_c_label_runtime.py",
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


def expected_label_aggregate_review_claim(
        aggregate: Mapping[str, object], aggregate_sha256: str) -> dict:
    gate = aggregate.get("fidelity_gate")
    design = aggregate.get("design_calib_manifest")
    report = aggregate.get("sealed_report_manifest")
    if not isinstance(gate, dict) or not isinstance(design, dict) \
            or not isinstance(report, dict):
        raise TrainingControllerRefused(
            "label aggregate gate/manifests are missing")
    ordinary = gate.get("ordinary_anchor_regret")
    hard = gate.get("hard_tail_regret")
    recall = gate.get("v11_recall_treatment_minus_matched_random")
    if not all(isinstance(value, dict)
               for value in (ordinary, hard, recall)):
        raise TrainingControllerRefused("label aggregate gate metrics missing")
    return {
        "schema": LABEL_AGGREGATE_REVIEW_SCHEMA,
        "label_git": aggregate.get("git"),
        "aggregate_sha256": aggregate_sha256,
        "aggregate_internal_sha256": aggregate.get("aggregate_sha256"),
        "state_set_sha256": aggregate.get("state_set_sha256"),
        "states": aggregate.get("states"),
        "complete_rows": aggregate.get("complete_rows"),
        "refused_rows": aggregate.get("refused_rows"),
        "fidelity_decision": gate.get("decision"),
        "ordinary_anchor_regret_ucb": ordinary.get("one_sided_95_ucb"),
        "hard_tail_regret_ucb": hard.get("one_sided_95_ucb"),
        "v11_recall_lcb": recall.get("one_sided_95_lcb"),
        "design_calib_manifest_sha256": _manifest_hash(design),
        "sealed_report_manifest_sha256": _manifest_hash(report),
        "report_shards_opened_by_training_review": 0,
        "independent_review": True,
        "one_training_controller_freeze_authorized": True,
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
    if sha256_file(path) != expected_sha256:
        raise TrainingControllerRefused("label aggregate external SHA-256 drift")
    aggregate = load_json(path)
    gate = aggregate.get("fidelity_gate")
    design = aggregate.get("design_calib_manifest")
    report = aggregate.get("sealed_report_manifest")
    shards = aggregate.get("shards")
    ordinary = gate.get("ordinary_anchor_regret") if isinstance(gate, dict) \
        else None
    hard = gate.get("hard_tail_regret") if isinstance(gate, dict) else None
    recall = gate.get("v11_recall_treatment_minus_matched_random") \
        if isinstance(gate, dict) else None
    metric_values = (
        ordinary.get("one_sided_95_ucb") if isinstance(ordinary, dict) else None,
        hard.get("one_sided_95_ucb") if isinstance(hard, dict) else None,
        recall.get("one_sided_95_lcb") if isinstance(recall, dict) else None,
    )
    if (aggregate.get("schema") != LABEL_CTRL.AGGREGATE_SCHEMA
            or aggregate.get("run_id") != LABEL_CTRL.RUN_ID
            or aggregate.get("aggregate_sha256")
            != self_hash(aggregate, "aggregate_sha256")
            or aggregate.get("status") != "COMPLETE"
            or aggregate.get("states") != 2048
            or aggregate.get("complete_rows") != 2048
            or aggregate.get("refused_rows") != 0
            or aggregate.get("utility_published") is not True
            or aggregate.get("model_packet_review_authorized") is not True
            or aggregate.get("training_authorized") is not False
            or aggregate.get("report_open_authorized") is not False
            or not isinstance(gate, dict)
            or gate.get("decision") != "AUTHORIZE_MODEL_PACKET_REVIEW"
            or gate.get("fidelity_pass") is not True
            or gate.get("v11_recall_pass") is not True
            or any(isinstance(value, bool)
                   or not isinstance(value, (int, float))
                   or not math.isfinite(float(value)) for value in metric_values)
            or float(metric_values[0]) > 0.10
            or float(metric_values[1]) > 0.10
            or float(metric_values[2]) <= 0
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
    claim = marker_claim(review_record, LABEL_AGGREGATE_REVIEW_MARKER)
    expected = expected_label_aggregate_review_claim(aggregate, expected_sha256)
    if claim != expected:
        raise TrainingControllerRefused("label aggregate PASS marker drift")
    return aggregate, claim


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


def materialize_dataset(
    *, label_packet: Mapping[str, object], label_receipt_sha256: str,
    state_set: Mapping[str, object], aggregate: Mapping[str, object],
) -> dict:
    """Open only DESIGN/CALIB shards and encode their public examples."""
    states = {str(value["state_id"]): value for value in state_set["states"]}
    if len(states) != 2048:
        raise TrainingControllerRefused("Stage-C state map identity drift")
    manifest = _design_calib_manifest(aggregate)
    net = LABEL._load_v11()
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
        LABEL.validate_shard(
            shard, packet=label_packet,
            receipt_sha256=label_receipt_sha256,
            state_set=state_set, index=index, net=net)
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
    report_manifest = aggregate["sealed_report_manifest"]
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
        "sealed_report_manifest_sha256": _manifest_hash(report_manifest),
        "sealed_report_shards": list(report_manifest["shards"]),
        "report_rows_included": False,
        "report_shard_files_opened": 0,
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
) -> dict:
    if dataset.get("dataset_sha256") != self_hash(dataset, "dataset_sha256"):
        raise TrainingControllerRefused("model dataset internal SHA drift")
    schedule = build_schedule()
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
                "review_schema": LABEL_AGGREGATE_REVIEW_SCHEMA,
                "review_claim_sha256": _manifest_hash(aggregate_review),
                "fidelity_decision": aggregate["fidelity_gate"]["decision"],
            },
            "model_dataset": {
                "logical_path": DATASET_PATH,
                "external_sha256": dataset_external_sha256,
                "internal_sha256": dataset["dataset_sha256"],
                "design_states": 1024,
                "calib_states": 512,
                "report_rows_included": False,
                "sealed_report_manifest_sha256": dataset[
                    "sealed_report_manifest_sha256"],
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
        "model_dataset_sha256": dataset["external_sha256"],
        "design_states": dataset["design_states"],
        "calib_states": dataset["calib_states"],
        "report_rows_included": False,
        "report_shard_files_opened": 0,
        "sealed_report_manifest_sha256": dataset[
            "sealed_report_manifest_sha256"],
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


def publish_exclusive(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise TrainingControllerRefused(f"refusing existing output: {path}")
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


def _validated_inputs(args) -> tuple[dict, dict, dict, dict, str]:
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
    if (aggregate.get("controller_packet_sha256")
            != args.expected_label_controller_sha256
            or aggregate.get("label_receipt_sha256")
            != args.expected_label_receipt_sha256
            or aggregate.get("state_set_sha256")
            != label_packet["parents"]["state_set"]["external_sha256"]):
        raise TrainingControllerRefused(
            "label aggregate/controller/receipt parent drift")
    aggregate = dict(aggregate)
    aggregate["external_sha256"] = args.expected_label_aggregate_sha256
    return label_packet, state_set, aggregate, aggregate_review, git


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
        child.add_argument("--dataset-out", required=True)
        child.add_argument("--packet-out", required=True)
        if name == "verify":
            child.add_argument("--expected-dataset-sha256", required=True)
            child.add_argument("--expected-packet-sha256", required=True)
    return root


def main() -> int:
    args = parser().parse_args()
    label_packet, state_set, aggregate, aggregate_review, git = \
        _validated_inputs(args)
    dataset = materialize_dataset(
        label_packet=label_packet,
        label_receipt_sha256=args.expected_label_receipt_sha256,
        state_set=state_set, aggregate=aggregate)
    dataset_out = Path(args.dataset_out).resolve()
    packet_out = Path(args.packet_out).resolve()
    if args.command == "freeze":
        if (dataset_out != (REPO / DATASET_PATH).resolve()
                or packet_out != (REPO / PACKET_PATH).resolve()):
            raise TrainingControllerRefused(
                "real Stage-C model dataset/packet output path drift")
        publish_exclusive(dataset_out, dataset)
        dataset_external_sha256 = sha256_file(dataset_out)
        packet = build_packet(
            git=git, dataset=dataset,
            dataset_external_sha256=dataset_external_sha256,
            aggregate=aggregate, aggregate_review=aggregate_review)
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
            aggregate=aggregate, aggregate_review=aggregate_review)
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
