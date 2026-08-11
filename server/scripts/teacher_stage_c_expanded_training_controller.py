#!/usr/bin/env python3
"""Freeze the expanded Stage-C model dataset and A/B training packet.

This controller merges two immutable, split-safe inputs:

* the 1,536 DESIGN/CALIB examples already reviewed in the first Stage-C
  training packet; and
* exactly 5,504 newly completed labels from the expanded controller.

The resulting 7,040-example dataset trains two matched eight-seed cohorts.
``all_pairs_v1`` is the unchanged loss at larger data scale; the
``candidate0_relative_v2`` treatment directly predicts each challenger's
signed utility advantage over the incumbent.  Both cohorts share states,
seeds, initialization, epochs and auxiliary outcome loss.  CALIB selects a
whole cohort; no seed is selected individually.  The third 512-state REPORT
population remains digest-sealed and unopened.

Freezing and verifying this packet perform no training, REPORT evaluation,
composition, strength run, promotion or deployment.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import math
import os
import platform
import stat
import subprocess
import sys
from pathlib import Path
from typing import Iterator, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SCRIPT.parents[2]
sys.path.insert(0, str(SCRIPT.parent))

import teacher_stage_c_capture_runtime as CAPTURE  # noqa: E402
import teacher_stage_c_expansion_controller as EXP  # noqa: E402
import teacher_stage_c_label_runtime as LABEL  # noqa: E402
import teacher_stage_c_training_controller as BASE  # noqa: E402
from shengji.rl import stage_c_model as MODEL  # noqa: E402
from shengji.rl import stage_c_training as TRAIN  # noqa: E402


SCHEMA = "teacher-stage-c-expanded-training-controller-v1"
PACKET_ID = "teacher-v3-hard-tail-stage-c-expanded-training-controller-v1"
RUN_ID = "teacher-v3-hard-tail-stage-c-expanded-training-v1"
CONTROLLER_RUN_ID = \
    "teacher-v3-hard-tail-stage-c-expanded-training-controller-v1"
DATASET_SCHEMA = "teacher-stage-c-expanded-model-dataset-v1"
DATASET_PATH = f"server/runs/logs/{CONTROLLER_RUN_ID}/model-dataset.json"
PACKET_PATH = f"server/runs/logs/{CONTROLLER_RUN_ID}/controller_packet.json"
RUNTIME_PATH = "server/scripts/teacher_stage_c_expanded_training_runtime.py"
SUPERVISOR_PATH = \
    "server/scripts/teacher_stage_c_expanded_training_supervisor.py"

REVIEW_SCHEMA = "teacher-stage-c-expanded-training-controller-review-v1"
REVIEW_MARKER = "TEACHER_STAGE_C_EXPANDED_TRAINING_CONTROLLER_V1_REVIEW "
LABEL_RESULT_REVIEW_SCHEMA = \
    "teacher-stage-c-expanded-label-result-review-v1"
LABEL_RESULT_REVIEW_MARKER = \
    "TEACHER_STAGE_C_EXPANDED_LABEL_RESULT_V1_REVIEW "

EXPANDED_SOURCE_GIT = "32d94a426addd5b39024e8260c15bade4452492a"
EXPANDED_STATE_SET_SHA256 = \
    "1ca28dbc9e9f4f2428ce65a3fa1211d8f9488423b7250eea22c60e4575cd3c95"
EXPANDED_STATE_SET_INTERNAL_SHA256 = \
    "a39d68070a094f925b386a714c45b27c753418e26485f0667a01eb59476575fb"
EXPANDED_LABEL_CONTROLLER_SHA256 = \
    "82447501ca517d936fa5f453a793f0afae2dc05939d2088212746e75bc0e2084"
EXPANDED_LABEL_CONTROLLER_INTERNAL_SHA256 = \
    "16391d9b5526d2df626a63abeb43fce6b51b0c27033eace2d6d3da52353580b9"

PRIOR_DATASET_SHA256 = \
    "8cd782d39d80af2919961d098c3f1a3acc2c6cbf1e4d47a79637a1193d66722b"
PRIOR_DATASET_INTERNAL_SHA256 = \
    "db7a212231cfeaaea5a5a950fefe9cc297f62f471406b7caa4579ee8ba278124"
PRIOR_TRAINING_PACKET_SHA256 = \
    "fbc72afac862bb0335a151e88021f27b28fc1554aea4e8d1130498dce775ac81"
PRIOR_TRAINING_PACKET_INTERNAL_SHA256 = \
    "eb07dee9c1d9156186aea07114d0dbc4cbfa4ea6ab400d3876efa1502e73d37d"
PRIOR_TRAINING_REVIEW_RECORD_SHA256 = \
    "d5aae938a86c5ce461bb3a8b3a5bffe745f635bca5b3aa4ed2b6b2a30d300d52"
PRIOR_TRAINING_REVIEW_LINE_SHA256 = \
    "5c58c0fd27df2e2f8a00f0054f49377199fb2b4fa8e417c026e43f6b9ffc69a0"

EXPECTED_SPLITS = {"DESIGN": 5_632, "CALIB": 1_408}
EXPECTED_SURFACES = {
    "DESIGN": {"play": 5_120, "bury": 512},
    "CALIB": {"play": 1_280, "bury": 128},
}
EXPECTED_TOTAL_STATES = 7_040
REUSED_STATES = 1_536
NEW_STATES = 5_504
SEALED_REPORT_STATES = 512
LOSS_RECIPES = MODEL.LOSS_RECIPES
TRAINING_CELLS = (len(LOSS_RECIPES) * len(MODEL.SURFACES)
                  * len(MODEL.TRAINING_SEEDS)
                  * len(MODEL.CURVE_FRACTIONS))
SUPERVISOR_MAX_WORKERS = len(MODEL.TRAINING_SEEDS)
SUPERVISOR_HEARTBEAT_SECONDS = 30
SUPERVISOR_HANDLED_SIGNALS = ("SIGHUP", "SIGINT", "SIGTERM")

SOURCE_PATHS = (
    "server/scripts/teacher_stage_c_expanded_training_controller.py",
    RUNTIME_PATH,
    SUPERVISOR_PATH,
    "server/scripts/teacher_stage_c_training_runtime.py",
    "server/scripts/teacher_stage_c_training_supervisor.py",
    "server/scripts/teacher_stage_c_expansion_controller.py",
    "server/scripts/teacher_stage_c_expanded_label_runtime.py",
    "server/scripts/teacher_stage_c_label_runtime.py",
    "server/scripts/teacher_stage_c_capture_runtime.py",
    "server/shengji/rl/stage_c_expansion.py",
    "server/shengji/rl/stage_c_model.py",
    "server/shengji/rl/stage_c_training.py",
    "server/shengji/rl/encode.py",
)


class TrainingControllerRefused(RuntimeError):
    """An expanded label, merge, training or split boundary drifted."""


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


def _manifest_hash(value: object) -> str:
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


def _git(*args: str, cwd: Path = REPO) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


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


def _source_sha256s() -> dict[str, str]:
    values = {}
    for logical in SOURCE_PATHS:
        path = REPO / logical
        if not is_regular_unlinked(path):
            raise TrainingControllerRefused(
                f"expanded training source unavailable: {logical}")
        values[logical] = sha256_file(path)
    return dict(sorted(values.items()))


def runtime_contract() -> dict:
    if MODEL.torch is None:
        raise TrainingControllerRefused("expanded training runtime lacks torch")
    try:
        import numpy
    except ImportError as exc:
        raise TrainingControllerRefused(
            "expanded training runtime lacks numpy") from exc
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
            "each cell logs after every epoch; the one-shot supervisor "
            "publishes progress at least every 30 seconds"
        ),
    }


def candidate_provenance_contract() -> dict:
    value = dict(BASE.candidate_provenance_contract())
    value.update({
        "prior_examples_reused_without_candidate_source_tags": True,
        "expanded_examples_materialized_source_agnostically": True,
        "v11_checkpoint_use_during_training": "none",
    })
    return value


def _upgrade_target(target: Mapping[str, object]) -> dict:
    if (target.get("schema") != "teacher-stage-c-model-target-v1"
            or target.get("target_sha256")
            != self_hash(target, "target_sha256")):
        raise TrainingControllerRefused("prior Stage-C target identity drift")
    value = copy.deepcopy(dict(target))
    count = value.get("candidate_count")
    ranking = value.get("ranking_mean_signed_level_utility")
    outcome = value.get("outcome_mean_signed_level_utility")
    deeper = value.get("deeper_report_pair")
    if (isinstance(count, bool) or not isinstance(count, int) or count <= 0
            or not isinstance(ranking, list) or len(ranking) != count
            or not isinstance(outcome, list) or len(outcome) != count
            or any(isinstance(item, bool)
                   or not isinstance(item, (int, float))
                   or not math.isfinite(float(item))
                   for item in [*ranking, *outcome])):
        raise TrainingControllerRefused("prior Stage-C target geometry drift")
    advantages = [float(item) - float(ranking[0]) for item in ranking]
    weights = [0.0] + [1.0] * (count - 1)
    if isinstance(deeper, dict) and deeper.get(
            "replaced_all_candidate_pair") is True:
        indices = deeper.get("candidate_indices")
        if (not isinstance(indices, list) or len(indices) != 2
                or indices[0] != 0 or isinstance(indices[1], bool)
                or not isinstance(indices[1], int)
                or not 0 < indices[1] < count
                or deeper.get("worlds") != MODEL.HARD_REPORT_WORLDS):
            raise TrainingControllerRefused(
                "prior Stage-C deeper-pair geometry drift")
        challenger = indices[1]
        advantages[challenger] = (
            float(outcome[challenger]) - float(outcome[0]))
        weights[challenger] = (
            MODEL.HARD_REPORT_WORLDS / MODEL.HARD_SELECTION_WORLDS)
    value["schema"] = MODEL.TARGET_SCHEMA
    value["candidate0_relative_advantage"] = advantages
    value["candidate0_relative_weight"] = weights
    value["target_sha256"] = self_hash(value, "target_sha256")
    return value


def _upgrade_example(example: Mapping[str, object]) -> dict:
    if (example.get("schema") != "teacher-stage-c-model-example-v1"
            or example.get("example_sha256")
            != self_hash(example, "example_sha256")
            or "sources" in example):
        raise TrainingControllerRefused("prior Stage-C example identity drift")
    value = copy.deepcopy(dict(example))
    value["schema"] = MODEL.SCHEMA
    value["target"] = _upgrade_target(value["target"])
    value["example_sha256"] = self_hash(value, "example_sha256")
    return value


def validate_prior_dataset(
    *, dataset_path: Path, packet_path: Path, review_record: Path,
) -> tuple[dict, dict]:
    if (sha256_file(dataset_path) != PRIOR_DATASET_SHA256
            or sha256_file(packet_path) != PRIOR_TRAINING_PACKET_SHA256
            or sha256_file(review_record)
            != PRIOR_TRAINING_REVIEW_RECORD_SHA256):
        raise TrainingControllerRefused("prior Teacher artifact SHA drift")
    dataset = load_json(dataset_path)
    packet = load_json(packet_path)
    review_lines = [line for line in review_record.read_text().splitlines()
                    if line.startswith(BASE.REVIEW_MARKER)]
    if (len(review_lines) != 1
            or sha256_bytes((review_lines[0] + "\n").encode())
            != PRIOR_TRAINING_REVIEW_LINE_SHA256
            or dataset.get("dataset_sha256")
            != PRIOR_DATASET_INTERNAL_SHA256
            or dataset.get("dataset_sha256")
            != self_hash(dataset, "dataset_sha256")
            or packet.get("packet_sha256")
            != PRIOR_TRAINING_PACKET_INTERNAL_SHA256
            or packet.get("packet_sha256")
            != self_hash(packet, "packet_sha256")
            or packet.get("parents", {}).get("model_dataset", {}).get(
                "external_sha256") != PRIOR_DATASET_SHA256
            or packet["parents"]["model_dataset"].get("internal_sha256")
            != PRIOR_DATASET_INTERNAL_SHA256
            or packet.get("authority", {}).get("report_rows_opened") != 0
            or packet.get("authority", {}).get(
                "report_open_authorized") is not False
            or dataset.get("schema")
            != "teacher-stage-c-v11-free-model-dataset-v1"
            or dataset.get("split_counts")
            != {"DESIGN": 1_024, "CALIB": 512}
            or dataset.get("surface_counts") != {
                "DESIGN": {"play": 960, "bury": 64},
                "CALIB": {"play": 480, "bury": 32},
            }
            or dataset.get("report_rows_included") is not False
            or dataset.get("report_label_shard_files_opened") != 0):
        raise TrainingControllerRefused(
            "prior Teacher dataset/packet/review drift")
    upgraded = {"DESIGN": {"play": [], "bury": []},
                "CALIB": {"play": [], "bury": []}}
    for split, surfaces in upgraded.items():
        raw_surfaces = dataset.get("examples", {}).get(split)
        if not isinstance(raw_surfaces, dict):
            raise TrainingControllerRefused(
                "prior Teacher example split drift")
        for surface in surfaces:
            values = [_upgrade_example(value)
                      for value in raw_surfaces.get(surface, [])]
            TRAIN.validate_population(values, split=split, surface=surface)
            upgraded[split][surface] = values
    if ({split: {surface: len(values)
                 for surface, values in surfaces.items()}
         for split, surfaces in upgraded.items()}
            != dataset["surface_counts"]):
        raise TrainingControllerRefused(
            "prior Teacher upgraded population drift")
    return upgraded, {
        "dataset_external_sha256": PRIOR_DATASET_SHA256,
        "dataset_internal_sha256": PRIOR_DATASET_INTERNAL_SHA256,
        "training_packet_external_sha256": PRIOR_TRAINING_PACKET_SHA256,
        "training_packet_internal_sha256":
            PRIOR_TRAINING_PACKET_INTERNAL_SHA256,
        "training_review_record_sha256":
            PRIOR_TRAINING_REVIEW_RECORD_SHA256,
        "training_review_line_sha256": PRIOR_TRAINING_REVIEW_LINE_SHA256,
        "states": REUSED_STATES,
        "report_rows_opened": 0,
    }


@contextlib.contextmanager
def _expanded_runtime_context(evidence_repo: Path) -> Iterator[None]:
    old_label_repo = LABEL.REPO
    old_capture_repo = CAPTURE.REPO
    old_exp_repo = EXP.REPO
    old_ctrl = LABEL._ctrl
    LABEL.REPO = evidence_repo
    CAPTURE.REPO = evidence_repo
    EXP.REPO = evidence_repo
    LABEL._ctrl = lambda: EXP
    try:
        yield
    finally:
        LABEL._ctrl = old_ctrl
        EXP.REPO = old_exp_repo
        CAPTURE.REPO = old_capture_repo
        LABEL.REPO = old_label_repo


def expected_expanded_label_result_claim(
    *, aggregate: Mapping[str, object], aggregate_external_sha256: str,
    packet: Mapping[str, object], receipt_external_sha256: str,
) -> dict:
    work = aggregate["work"]
    return {
        "schema": LABEL_RESULT_REVIEW_SCHEMA,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": EXPANDED_LABEL_CONTROLLER_SHA256,
        "controller_packet_internal_sha256":
            EXPANDED_LABEL_CONTROLLER_INTERNAL_SHA256,
        "state_set_sha256": EXPANDED_STATE_SET_SHA256,
        "label_receipt_sha256": receipt_external_sha256,
        "aggregate_sha256": aggregate_external_sha256,
        "aggregate_internal_sha256": aggregate["aggregate_sha256"],
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "states": NEW_STATES,
        "complete_rows": NEW_STATES,
        "refused_rows": 0,
        "reused_labels_not_recomputed": REUSED_STATES,
        "sealed_report_states": SEALED_REPORT_STATES,
        "candidate_worlds_attempted": work[
            "candidate_worlds_attempted"],
        "candidate_worlds_completed": work[
            "candidate_worlds_completed"],
        "sampler_attempts": work["sampler_attempts"],
        "max_candidate_worlds": packet["result_contract"][
            "max_candidate_worlds"],
        "max_sampler_attempts": packet["result_contract"][
            "max_sampler_attempts"],
        "aggregate_fully_recomputed": True,
        "independent_review": True,
        "one_expanded_training_controller_freeze_authorized": True,
        "training_authorized": False,
        "report_open_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }


def _expanded_paths(evidence_repo: Path) -> dict[str, Path]:
    return {
        "state_set": evidence_repo / EXP.STATE_SET_PATH,
        "controller": evidence_repo / EXP.CONTROLLER_PACKET_PATH,
        "receipt": evidence_repo /
            f"server/runs/logs/{EXP.RUN_ID}/label-receipt.json",
        "aggregate": evidence_repo /
            f"server/runs/logs/{EXP.RUN_ID}/label-aggregate.json",
    }


def validate_expanded_labels(
    *, evidence_repo: Path, capture_evidence_repo: Path,
    state_set_review_record: Path, fresh_report_review_record: Path,
    controller_review_record: Path, receipt_sha256: str,
    aggregate_sha256: str, result_review_record: Path,
) -> tuple[dict, dict, dict, list[dict]]:
    if (_git("rev-parse", "HEAD", cwd=evidence_repo)
            != EXPANDED_SOURCE_GIT
            or _git("status", "--porcelain", "--untracked-files=no",
                    cwd=evidence_repo)):
        raise TrainingControllerRefused(
            "expanded label evidence Git drift")
    paths = _expanded_paths(evidence_repo)
    if (sha256_file(paths["state_set"]) != EXPANDED_STATE_SET_SHA256
            or sha256_file(paths["controller"])
            != EXPANDED_LABEL_CONTROLLER_SHA256
            or sha256_file(paths["receipt"]) != receipt_sha256
            or sha256_file(paths["aggregate"]) != aggregate_sha256):
        raise TrainingControllerRefused(
            "expanded label evidence external identity drift")
    with _expanded_runtime_context(evidence_repo):
        try:
            rebuilt_state, _capture, _verification, _state_review = \
                EXP._rebuild_state_set(
                    evidence_repo=capture_evidence_repo,
                    state_set_review_record=state_set_review_record,
                    fresh_report_review_record=fresh_report_review_record)
        except EXP.ExpansionControllerRefused as exc:
            raise TrainingControllerRefused(
                f"expanded state-set recomputation refused: {exc}") from exc
        rebuilt_state["producer_git"] = EXPANDED_SOURCE_GIT
        rebuilt_state["dataset_sha256"] = EXP.self_hash(
            rebuilt_state, "dataset_sha256")
        state_set = load_json(paths["state_set"])
        if (state_set != rebuilt_state
                or state_set.get("dataset_sha256")
                != EXPANDED_STATE_SET_INTERNAL_SHA256):
            raise TrainingControllerRefused(
                "expanded state-set full recomputation drift")
        packet = load_json(paths["controller"])
        controller_claim = marker_claim(
            controller_review_record, EXP.REVIEW_MARKER)
        if (packet.get("schema") != EXP.SCHEMA
                or packet.get("packet_id") != EXP.PACKET_ID
                or packet.get("producer", {}).get("git")
                != EXPANDED_SOURCE_GIT
                or packet.get("packet_sha256")
                != EXPANDED_LABEL_CONTROLLER_INTERNAL_SHA256
                or packet.get("packet_sha256") != EXP.self_hash(packet)
                or packet.get("runtime_sources") != EXP.runtime_sources()
                or packet.get("schedule") != EXP.build_schedule(state_set)
                or packet.get("parents", {}).get("state_set", {}).get(
                    "external_sha256") != EXPANDED_STATE_SET_SHA256
                or controller_claim != EXP.expected_review_claim(
                    packet, EXPANDED_LABEL_CONTROLLER_SHA256)):
            raise TrainingControllerRefused(
                "expanded label controller/review drift")
        packet = dict(packet)
        packet["external_sha256"] = EXPANDED_LABEL_CONTROLLER_SHA256
        try:
            LABEL._receipt(
                paths["receipt"], receipt_sha256, packet,
                EXPANDED_LABEL_CONTROLLER_SHA256,
                controller_review_record, controller_review_record)
            shard_paths = [evidence_repo / logical for logical in
                           packet["result_contract"]["shards"]]
            rebuilt_aggregate, shards = LABEL.recompute_aggregate_payload(
                packet=packet,
                expected_packet_sha256=EXPANDED_LABEL_CONTROLLER_SHA256,
                expected_receipt_sha256=receipt_sha256,
                state_set=state_set, shard_paths=shard_paths)
        except LABEL.LabelRefused as exc:
            raise TrainingControllerRefused(
                f"expanded label terminal replay refused: {exc}") from exc
    aggregate = load_json(paths["aggregate"])
    if (aggregate != rebuilt_aggregate
            or aggregate.get("status") != "COMPLETE"
            or aggregate.get("states") != NEW_STATES
            or aggregate.get("complete_rows") != NEW_STATES
            or aggregate.get("refused_rows") != 0
            or aggregate.get("model_packet_review_authorized") is not True
            or aggregate.get("report_open_authorized") is not False):
        raise TrainingControllerRefused(
            "expanded label aggregate completion drift")
    result_claim = marker_claim(
        result_review_record, LABEL_RESULT_REVIEW_MARKER)
    expected_claim = expected_expanded_label_result_claim(
        aggregate=aggregate, aggregate_external_sha256=aggregate_sha256,
        packet=packet, receipt_external_sha256=receipt_sha256)
    if result_claim != expected_claim:
        raise TrainingControllerRefused(
            "expanded label terminal-result review drift")
    aggregate = dict(aggregate)
    aggregate["external_sha256"] = aggregate_sha256
    return state_set, packet, aggregate, shards


def materialize_dataset(
    *, prior_examples: Mapping[str, Mapping[str, Sequence[Mapping[str, object]]]],
    prior_contract: Mapping[str, object], expanded_state_set: Mapping[str, object],
    expanded_packet: Mapping[str, object], expanded_aggregate: Mapping[str, object],
    expanded_shards: Sequence[Mapping[str, object]],
) -> dict:
    states = {str(value["state_id"]): value
              for value in expanded_state_set["states"]}
    reused_ids = set(str(value) for value in
                     expanded_state_set["reused_training_state_ids"])
    new_ids = set(str(value) for value in
                  expanded_state_set["new_label_state_ids"])
    prior_ids = {str(value["state_id"])
                 for surfaces in prior_examples.values()
                 for values in surfaces.values() for value in values}
    if (len(states) != EXPECTED_TOTAL_STATES
            or len(reused_ids) != REUSED_STATES
            or len(new_ids) != NEW_STATES
            or reused_ids & new_ids or set(states) != reused_ids | new_ids
            or prior_ids != reused_ids):
        raise TrainingControllerRefused(
            "expanded/prior dataset identity merge drift")
    examples = {
        split: {surface: [copy.deepcopy(value) for value in
                         prior_examples[split][surface]]
                for surface in MODEL.SURFACES}
        for split in ("DESIGN", "CALIB")
    }
    consumed = []
    observed_new = set()
    for shard in expanded_shards:
        split = str(shard["split"])
        if split not in {"DESIGN", "CALIB"}:
            raise TrainingControllerRefused(
                "expanded model materializer received REPORT shard")
        for state_id, row in zip(
                shard["state_ids"], shard["rows"], strict=True):
            state_id = str(state_id)
            if state_id not in new_ids or state_id in observed_new:
                raise TrainingControllerRefused(
                    "expanded new-label identity collision")
            state = states[state_id]
            rnd = CAPTURE.replay_state(state)
            example = MODEL.materialize_example(state, row, rnd)
            examples[split][str(example["surface_type"])].append(example)
            observed_new.add(state_id)
        consumed.append({
            "index": shard["shard_index"],
            "split": split,
            "sha256": shard["external_sha256"],
            "row_sha256s_sha256": _manifest_hash(shard["row_sha256s"]),
        })
    if observed_new != new_ids:
        raise TrainingControllerRefused(
            "expanded model materializer missed new labels")
    for split, surfaces in examples.items():
        if {surface: len(values) for surface, values in surfaces.items()} \
                != EXPECTED_SURFACES[split]:
            raise TrainingControllerRefused(
                f"expanded {split} model surface count drift")
        for surface, values in surfaces.items():
            TRAIN.validate_population(values, split=split, surface=surface)
    design_ids = {value["state_id"] for values in examples["DESIGN"].values()
                  for value in values}
    calib_ids = {value["state_id"] for values in examples["CALIB"].values()
                 for value in values}
    if (len(design_ids) != EXPECTED_SPLITS["DESIGN"]
            or len(calib_ids) != EXPECTED_SPLITS["CALIB"]
            or design_ids & calib_ids):
        raise TrainingControllerRefused(
            "expanded model dataset split collision")
    report = expanded_state_set["sealed_report_manifest"]
    payload = {
        "schema": DATASET_SCHEMA,
        "run_id": RUN_ID,
        "split_counts": dict(EXPECTED_SPLITS),
        "surface_counts": EXPECTED_SURFACES,
        "examples": examples,
        "design_state_ids_sha256": _manifest_hash(sorted(design_ids)),
        "calib_state_ids_sha256": _manifest_hash(sorted(calib_ids)),
        "reused_state_ids_sha256": _manifest_hash(sorted(reused_ids)),
        "new_state_ids_sha256": _manifest_hash(sorted(new_ids)),
        "prior_dataset": dict(prior_contract),
        "expanded_labels": {
            "controller_packet_sha256": EXPANDED_LABEL_CONTROLLER_SHA256,
            "controller_packet_internal_sha256": expanded_packet[
                "packet_sha256"],
            "aggregate_sha256": expanded_aggregate["external_sha256"],
            "aggregate_internal_sha256": expanded_aggregate[
                "aggregate_sha256"],
            "label_shards": consumed,
            "new_states": NEW_STATES,
        },
        "sealed_report_selection": {
            "states": report["states"],
            "state_ids_sha256": report["state_ids_sha256"],
            "state_material_sha256": report["state_material_sha256"],
            "surface_counts": report["surface_counts"],
            "state_material_published": False,
            "labels_or_predictions_computed": False,
        },
        "candidate_provenance_contract": candidate_provenance_contract(),
        "original_report_quarantined": True,
        "spent_fresh_report_quarantined": True,
        "report_rows_included": False,
        "report_state_material_published": False,
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
    names = {"all_pairs_v1": "allpairs",
             "candidate0_relative_v2": "anchor"}
    for loss_recipe in LOSS_RECIPES:
        for surface in MODEL.SURFACES:
            for seed in MODEL.TRAINING_SEEDS:
                for fraction in MODEL.CURVE_FRACTIONS:
                    cell_id = (
                        f"{names[loss_recipe]}-{surface}-seed{seed}-"
                        f"curve{int(fraction * 100):03d}"
                    )
                    cells.append({
                        "index": len(cells),
                        "cell_id": cell_id,
                        "loss_recipe": loss_recipe,
                        "surface": surface,
                        "seed": seed,
                        "curve_fraction": fraction,
                        "design_states": EXPECTED_SURFACES[
                            "DESIGN"][surface],
                        "calib_states": EXPECTED_SURFACES[
                            "CALIB"][surface],
                        "epoch_grid": list(MODEL.EPOCH_GRID),
                        "result":
                            f"server/runs/logs/{RUN_ID}/cells/{cell_id}.json",
                        "snapshot_dir":
                            f"server/runs/logs/{RUN_ID}/checkpoints/{cell_id}",
                    })
    if (len(cells) != TRAINING_CELLS
            or [value["index"] for value in cells]
            != list(range(TRAINING_CELLS))
            or len({value["cell_id"] for value in cells})
            != TRAINING_CELLS):
        raise TrainingControllerRefused(
            "expanded training cell schedule drift")
    value = {
        "cells": cells,
        "cell_count": TRAINING_CELLS,
        "loss_recipes": list(LOSS_RECIPES),
        "surfaces": list(MODEL.SURFACES),
        "seeds": list(MODEL.TRAINING_SEEDS),
        "curve_fractions": list(MODEL.CURVE_FRACTIONS),
        "epoch_grid": list(MODEL.EPOCH_GRID),
        "full_curve_cells_for_calib_selection": (
            len(LOSS_RECIPES) * len(MODEL.SURFACES)
            * len(MODEL.TRAINING_SEEDS)),
        "matched_ab_states_seeds_initialization_epochs": True,
        "single_seed_selection": False,
        "report_rows_included": False,
    }
    value["schedule_sha256"] = self_hash(value, "schedule_sha256")
    return value


def model_contract() -> dict:
    return {
        "architecture": f"StageCRankingOutcomeNet(hidden={TRAIN.HIDDEN})",
        "separate_play_bury_weights": True,
        "loss_recipes": {
            "all_pairs_v1": (
                "unchanged state-balanced all-pairs BCE scale control"),
            "candidate0_relative_v2": (
                "state-balanced smooth-L1 signed utility advantage versus "
                "candidate zero; deeper hard-tail report pair preferred"),
        },
        "matched_ab_states_seeds_initialization_epochs": True,
        "outcome_target": "eight-bin-acting-team-signed-level-utility",
        "utility_bins": list(MODEL.UTILITY_BINS),
        "loss_weights": {
            "all_pairs_bce": MODEL.PAIRWISE_WEIGHT,
            "candidate0_advantage_huber": MODEL.ANCHOR_ADVANTAGE_WEIGHT,
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
            "one loss-recipe/surface/head/epoch eight-seed capability; "
            "no seed cherry-pick and no REPORT access"),
    }


def cell_hyperparameters(loss_recipe: str = MODEL.LOSS_RECIPES[0]) -> dict:
    if loss_recipe not in LOSS_RECIPES:
        raise TrainingControllerRefused(
            "expanded cell loss recipe drift")
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
        "loss_recipe": loss_recipe,
    }


def result_contract(schedule: Mapping[str, object]) -> dict:
    return {
        "cells": [value["result"] for value in schedule["cells"]],
        "aggregate": f"server/runs/logs/{RUN_ID}/training-aggregate.json",
        "supervisor_progress":
            f"server/runs/logs/{RUN_ID}/training-supervisor.jsonl",
        "supervisor_final":
            f"server/runs/logs/{RUN_ID}/training-supervisor-final.json",
        "selection_rule": MODEL.RECIPE_SELECTION_SCHEMA,
        "curve_diagnostics": {
            "loss_recipes": list(LOSS_RECIPES),
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
    receipt = f"server/runs/logs/{RUN_ID}/training-receipt.json"
    common = [
        "--expected-git", "{git}",
        "--controller-packet", PACKET_PATH,
        "--expected-controller-packet-sha256", "{packet_sha256}",
        "--controller-review-record", "{controller_review_record}",
    ]
    values = {
        "admit": ["{python}", RUNTIME_PATH, "admit", *common,
                  "--out", receipt],
        "run_cells": [{
            "index": cell["index"],
            "command": [
                "{python}", RUNTIME_PATH, "run-cell", *common,
                "--training-receipt", receipt,
                "--expected-training-receipt-sha256", "{receipt_sha256}",
                "--cell-index", str(cell["index"]),
                "--out", cell["result"],
            ],
        } for cell in schedule["cells"]],
        "aggregate": [
            "{python}", RUNTIME_PATH, "aggregate", *common,
            "--training-receipt", receipt,
            "--expected-training-receipt-sha256", "{receipt_sha256}",
            "--cells", *[value["result"] for value in schedule["cells"]],
            "--out", f"server/runs/logs/{RUN_ID}/training-aggregate.json",
        ],
    }
    values["supervise"] = [
        "{python}", SUPERVISOR_PATH, "launch", *common,
        "--training-receipt", receipt,
        "--expected-training-receipt-sha256", "{receipt_sha256}",
        "--heartbeat-seconds", str(SUPERVISOR_HEARTBEAT_SECONDS),
    ]
    values["verify_supervisor"] = [
        "{python}", SUPERVISOR_PATH, "verify", *common,
        "--training-receipt", receipt,
        "--expected-training-receipt-sha256", "{receipt_sha256}",
        "--heartbeat-seconds", str(SUPERVISOR_HEARTBEAT_SECONDS),
    ]
    return values


def select_global_capability(
    records: Sequence[Mapping[str, object]],
) -> dict:
    try:
        return MODEL.select_global_recipe_epoch(records)
    except MODEL.StageCModelError as exc:
        raise TrainingControllerRefused(
            f"expanded CALIB selector refused: {exc}") from exc


def validate_runtime_dataset(dataset: Mapping[str, object]) -> None:
    examples = dataset.get("examples")
    report = dataset.get("sealed_report_selection")
    if (dataset.get("schema") != DATASET_SCHEMA
            or dataset.get("run_id") != RUN_ID
            or dataset.get("dataset_sha256")
            != self_hash(dataset, "dataset_sha256")
            or dataset.get("split_counts") != EXPECTED_SPLITS
            or dataset.get("surface_counts") != EXPECTED_SURFACES
            or dataset.get("report_rows_included") is not False
            or dataset.get("report_state_material_published") is not False
            or dataset.get("training_authorized") is not False
            or dataset.get("report_open_authorized") is not False
            or dataset.get("original_report_quarantined") is not True
            or dataset.get("spent_fresh_report_quarantined") is not True
            or not isinstance(report, dict)
            or report.get("states") != SEALED_REPORT_STATES
            or report.get("state_material_published") is not False
            or not isinstance(examples, dict)
            or set(examples) != {"DESIGN", "CALIB"}):
        raise TrainingControllerRefused(
            "expanded runtime dataset identity drift")
    all_ids = set()
    for split in ("DESIGN", "CALIB"):
        surfaces = examples.get(split)
        if (not isinstance(surfaces, dict)
                or set(surfaces) != set(MODEL.SURFACES)):
            raise TrainingControllerRefused(
                "expanded runtime dataset surface drift")
        for surface in MODEL.SURFACES:
            values = surfaces[surface]
            if len(values) != EXPECTED_SURFACES[split][surface]:
                raise TrainingControllerRefused(
                    "expanded runtime dataset surface count drift")
            TRAIN.validate_population(values, split=split, surface=surface)
            ids = {str(value["state_id"]) for value in values}
            if all_ids & ids:
                raise TrainingControllerRefused(
                    "expanded runtime dataset identity overlap")
            all_ids.update(ids)
    if len(all_ids) != EXPECTED_TOTAL_STATES:
        raise TrainingControllerRefused(
            "expanded runtime dataset total count drift")


def validate_runtime_packet_parents(
    packet: Mapping[str, object], dataset: Mapping[str, object],
) -> None:
    parent = packet.get("parents", {}).get("model_dataset", {})
    expanded = packet.get("parents", {}).get("expanded_labels", {})
    if (parent.get("internal_sha256") != dataset.get("dataset_sha256")
            or parent.get("design_states") != EXPECTED_SPLITS["DESIGN"]
            or parent.get("calib_states") != EXPECTED_SPLITS["CALIB"]
            or parent.get("report_rows_included") is not False
            or parent.get("sealed_report_selection_sha256")
            != _manifest_hash(dataset.get("sealed_report_selection"))
            or expanded.get("controller_packet_sha256")
            != EXPANDED_LABEL_CONTROLLER_SHA256
            or expanded.get("aggregate_sha256")
            != dataset["expanded_labels"]["aggregate_sha256"]
            or expanded.get("new_states") != NEW_STATES):
        raise TrainingControllerRefused(
            "expanded runtime packet/dataset parent drift")


def build_packet(
    *, git: str, dataset: Mapping[str, object], dataset_external_sha256: str,
    expanded_packet: Mapping[str, object],
    expanded_aggregate: Mapping[str, object],
    expanded_result_review: Mapping[str, object],
) -> dict:
    if dataset.get("dataset_sha256") != self_hash(dataset, "dataset_sha256"):
        raise TrainingControllerRefused(
            "expanded model dataset internal SHA drift")
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
            "prior_training_asset": dict(dataset["prior_dataset"]),
            "expanded_labels": {
                "controller_packet_sha256":
                    EXPANDED_LABEL_CONTROLLER_SHA256,
                "controller_packet_internal_sha256": expanded_packet[
                    "packet_sha256"],
                "state_set_sha256": EXPANDED_STATE_SET_SHA256,
                "aggregate_sha256": expanded_aggregate["external_sha256"],
                "aggregate_internal_sha256": expanded_aggregate[
                    "aggregate_sha256"],
                "result_review_claim_sha256": _manifest_hash(
                    expanded_result_review),
                "new_states": NEW_STATES,
                "reused_states": REUSED_STATES,
            },
            "model_dataset": {
                "logical_path": DATASET_PATH,
                "external_sha256": dataset_external_sha256,
                "internal_sha256": dataset["dataset_sha256"],
                "design_states": EXPECTED_SPLITS["DESIGN"],
                "calib_states": EXPECTED_SPLITS["CALIB"],
                "report_rows_included": False,
                "sealed_report_selection_sha256": _manifest_hash(
                    dataset["sealed_report_selection"]),
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


def expected_review_claim(
    packet: Mapping[str, object], packet_external_sha256: str,
) -> dict:
    dataset = packet["parents"]["model_dataset"]
    sources = packet["producer"]["sources"]
    schedule = packet["schedule"]
    return {
        "schema": REVIEW_SCHEMA,
        "git": packet["producer"]["git"],
        "packet_sha256": packet_external_sha256,
        "packet_internal_sha256": packet["packet_sha256"],
        "controller_script_sha256": sources[
            "server/scripts/teacher_stage_c_expanded_training_controller.py"],
        "model_script_sha256": sources[
            "server/shengji/rl/stage_c_model.py"],
        "training_runtime_sha256": sources[
            "server/shengji/rl/stage_c_training.py"],
        "training_runtime_cli_sha256": sources[
            "server/scripts/teacher_stage_c_training_runtime.py"],
        "expanded_runtime_cli_sha256": sources[RUNTIME_PATH],
        "training_supervisor_sha256": sources[
            "server/scripts/teacher_stage_c_training_supervisor.py"],
        "expanded_supervisor_sha256": sources[SUPERVISOR_PATH],
        "model_contract_sha256": _manifest_hash(packet["model_contract"]),
        "runtime_contract_sha256": _manifest_hash(packet["runtime_contract"]),
        "execution_host": packet["runtime_contract"]["host"],
        "python": packet["runtime_contract"]["python"],
        "torch": packet["runtime_contract"]["torch"],
        "prior_dataset_sha256": PRIOR_DATASET_SHA256,
        "expanded_label_controller_sha256":
            EXPANDED_LABEL_CONTROLLER_SHA256,
        "expanded_label_aggregate_sha256": packet["parents"][
            "expanded_labels"]["aggregate_sha256"],
        "expanded_label_result_review_claim_sha256": packet["parents"][
            "expanded_labels"]["result_review_claim_sha256"],
        "model_dataset_sha256": dataset["external_sha256"],
        "design_states": dataset["design_states"],
        "calib_states": dataset["calib_states"],
        "reused_states": REUSED_STATES,
        "new_states": NEW_STATES,
        "sealed_report_states": SEALED_REPORT_STATES,
        "report_rows_included": False,
        "report_state_material_published": False,
        "loss_recipes": schedule["loss_recipes"],
        "matched_ab_states_seeds_initialization_epochs": True,
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
    if (dataset_out != (REPO / DATASET_PATH).resolve()
            or packet_out != (REPO / PACKET_PATH).resolve()):
        raise TrainingControllerRefused(
            "expanded training dataset/packet output path drift")
    _require_output_available(dataset_out)
    _require_output_available(packet_out)


def publish_exclusive(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = Path(str(path) + ".partial")
    _require_output_available(path)
    with partial.open("xb") as handle:
        handle.write(canonical_json(payload))
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.link(partial, path, follow_symlinks=False)
    except FileExistsError as exc:
        raise TrainingControllerRefused(
            f"refusing raced expanded output: {path}") from exc
    partial.unlink()


def _validated_inputs(args) -> tuple[dict, dict, dict, dict, dict, str]:
    if _git("status", "--porcelain", "--untracked-files=all"):
        raise TrainingControllerRefused(
            "real expanded training freeze refuses dirty tree")
    prior_examples, prior_contract = validate_prior_dataset(
        dataset_path=Path(args.prior_dataset).resolve(),
        packet_path=Path(args.prior_training_packet).resolve(),
        review_record=Path(args.prior_training_review_record).resolve())
    expanded_state, expanded_packet, expanded_aggregate, shards = \
        validate_expanded_labels(
            evidence_repo=Path(args.expanded_evidence_repo).resolve(),
            capture_evidence_repo=Path(
                args.capture_evidence_repo).resolve(),
            state_set_review_record=Path(
                args.state_set_review_record).resolve(),
            fresh_report_review_record=Path(
                args.fresh_report_review_record).resolve(),
            controller_review_record=Path(
                args.expanded_controller_review_record).resolve(),
            receipt_sha256=args.expected_expanded_label_receipt_sha256,
            aggregate_sha256=args.expected_expanded_label_aggregate_sha256,
            result_review_record=Path(
                args.expanded_label_result_review_record).resolve())
    result_review = marker_claim(
        Path(args.expanded_label_result_review_record).resolve(),
        LABEL_RESULT_REVIEW_MARKER)
    dataset = materialize_dataset(
        prior_examples=prior_examples, prior_contract=prior_contract,
        expanded_state_set=expanded_state,
        expanded_packet=expanded_packet,
        expanded_aggregate=expanded_aggregate,
        expanded_shards=shards)
    return (dataset, expanded_packet, expanded_aggregate, result_review,
            expanded_state, _git("rev-parse", "HEAD"))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands_parser = root.add_subparsers(dest="command", required=True)
    for name in ("freeze", "verify"):
        child = commands_parser.add_parser(name)
        child.add_argument("--prior-dataset", required=True)
        child.add_argument("--prior-training-packet", required=True)
        child.add_argument("--prior-training-review-record", required=True)
        child.add_argument("--expanded-evidence-repo", required=True)
        child.add_argument("--capture-evidence-repo", required=True)
        child.add_argument("--state-set-review-record", required=True)
        child.add_argument("--fresh-report-review-record", required=True)
        child.add_argument("--expanded-controller-review-record", required=True)
        child.add_argument(
            "--expected-expanded-label-receipt-sha256", required=True)
        child.add_argument(
            "--expected-expanded-label-aggregate-sha256", required=True)
        child.add_argument(
            "--expanded-label-result-review-record", required=True)
        child.add_argument("--dataset-out", default=DATASET_PATH)
        child.add_argument("--packet-out", default=PACKET_PATH)
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
    (dataset, expanded_packet, expanded_aggregate, result_review,
     _expanded_state, git) = _validated_inputs(args)
    dataset_external_sha256 = sha256_bytes(canonical_json(dataset))
    packet = build_packet(
        git=git, dataset=dataset,
        dataset_external_sha256=dataset_external_sha256,
        expanded_packet=expanded_packet,
        expanded_aggregate=expanded_aggregate,
        expanded_result_review=result_review)
    if args.command == "freeze":
        require_freeze_outputs_available(dataset_out, packet_out)
        publish_exclusive(dataset_out, dataset)
        publish_exclusive(packet_out, packet)
        status = "FROZEN_NO_TRAINING"
    else:
        if (sha256_file(dataset_out) != args.expected_dataset_sha256
                or load_json(dataset_out) != dataset
                or sha256_file(packet_out) != args.expected_packet_sha256
                or load_json(packet_out) != packet):
            raise TrainingControllerRefused(
                "expanded training frozen-artifact verification drift")
        status = "VERIFIED_NO_TRAINING"
    print(json.dumps({
        "status": status,
        "git": git,
        "dataset_sha256": sha256_file(dataset_out),
        "dataset_internal_sha256": dataset["dataset_sha256"],
        "packet_sha256": sha256_file(packet_out),
        "packet_internal_sha256": packet["packet_sha256"],
        "training_cells": packet["schedule"]["cell_count"],
        "loss_recipes": packet["schedule"]["loss_recipes"],
        "training_authorized": False,
        "report_open_authorized": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TrainingControllerRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
