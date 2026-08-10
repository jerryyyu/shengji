#!/usr/bin/env python3
"""Freeze a one-shot evaluator packet for the CALIB-selected Stage-C model.

This controller replays the terminal DESIGN/CALIB training aggregate and binds
the exact eight-model capability selected without REPORT.  It carries the
four sealed REPORT shard identities forward without opening them.  A separate
independent packet review is required before the runtime may consume its
one-shot admission and inspect REPORT once.
"""
from __future__ import annotations

import argparse
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
sys.path.insert(0, str(SCRIPT.parent))

import teacher_stage_c_label_runtime as LABEL  # noqa: E402
import teacher_stage_c_training_controller as TRAIN_CTRL  # noqa: E402
import teacher_stage_c_training_runtime as TRAIN_RUNTIME  # noqa: E402
from shengji.rl import stage_c_model as MODEL  # noqa: E402
from shengji.rl import stage_c_report as REPORT  # noqa: E402
from shengji.rl import stage_c_training as TRAIN  # noqa: E402


SCHEMA = "teacher-stage-c-report-controller-v1"
PACKET_ID = "teacher-v3-hard-tail-stage-c-report-controller-v1"
RUN_ID = "teacher-v3-hard-tail-stage-c-report-v1"
CONTROLLER_RUN_ID = "teacher-v3-hard-tail-stage-c-report-controller-v1"
PACKET_PATH = f"server/runs/logs/{CONTROLLER_RUN_ID}/controller_packet.json"
TRAINING_AGGREGATE_REVIEW_SCHEMA = \
    "teacher-stage-c-training-aggregate-review-v1"
TRAINING_AGGREGATE_REVIEW_MARKER = \
    "TEACHER_STAGE_C_TRAINING_AGGREGATE_V1_REVIEW "
REVIEW_SCHEMA = "teacher-stage-c-report-controller-review-v1"
REVIEW_MARKER = "TEACHER_STAGE_C_REPORT_CONTROLLER_V1_REVIEW "

REPORT_SURFACE_COUNTS = {"play": 480, "bury": 32}
SOURCE_PATHS = (
    "server/scripts/teacher_stage_c_report_controller.py",
    "server/scripts/teacher_stage_c_report_runtime.py",
    "server/shengji/rl/stage_c_report.py",
    "server/shengji/rl/stage_c_model.py",
    "server/shengji/rl/stage_c_training.py",
    "server/shengji/rl/encode.py",
    "server/shengji/rl/exact_resume.py",
    "server/scripts/teacher_stage_c_training_controller.py",
    "server/scripts/teacher_stage_c_training_runtime.py",
    "server/scripts/teacher_stage_c_label_controller.py",
    "server/scripts/teacher_stage_c_label_runtime.py",
    "server/scripts/teacher_stage_c_capture_runtime.py",
)


class ReportControllerRefused(RuntimeError):
    """A training, checkpoint, sealed-REPORT or authority identity drifted."""


canonical_json = TRAIN_CTRL.canonical_json
sha256_bytes = TRAIN_CTRL.sha256_bytes
sha256_file = TRAIN_CTRL.sha256_file
self_hash = TRAIN_CTRL.self_hash


def is_regular_unlinked(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not path.is_symlink())


def load_json(path: Path) -> dict:
    if not is_regular_unlinked(path):
        raise ReportControllerRefused(f"input is not regular/unlinked: {path}")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ReportControllerRefused(f"cannot read JSON {path}: {exc}") \
            from exc
    if not isinstance(value, dict):
        raise ReportControllerRefused(f"JSON root is not an object: {path}")
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
            raise ReportControllerRefused(
                f"Stage-C REPORT source unavailable: {logical}")
        result[logical] = sha256_file(path)
    return result


def marker_claim(path: Path, marker: str) -> dict:
    if not is_regular_unlinked(path):
        raise ReportControllerRefused("review record is not regular/unlinked")
    matches = [line[len(marker):] for line in path.read_text().splitlines()
               if line.startswith(marker)]
    if len(matches) != 1:
        raise ReportControllerRefused(
            f"review record must contain exactly one {marker.strip()} marker")
    try:
        value = json.loads(matches[0])
    except ValueError as exc:
        raise ReportControllerRefused("review marker is not JSON") from exc
    if not isinstance(value, dict):
        raise ReportControllerRefused("review marker root is not an object")
    return value


def _manifest_hash(value: object) -> str:
    return sha256_bytes(canonical_json(value))


def runtime_contract() -> dict:
    """Bind REPORT inference to the exact reviewed training environment."""
    value = TRAIN_CTRL.runtime_contract()
    return {
        "host": value["host"],
        "python": value["python"],
        "torch": value["torch"],
        "numpy": value["numpy"],
        "device": value["device"],
        "cpu_threads": TRAIN.CPU_THREADS,
    }


def expected_training_aggregate_review_claim(
    aggregate: Mapping[str, object], aggregate_external_sha256: str,
) -> dict:
    selection = aggregate.get("selection")
    ensemble = aggregate.get("selected_ensemble")
    if not isinstance(selection, dict) or not isinstance(ensemble, list):
        raise ReportControllerRefused(
            "Stage-C training selection/ensemble is missing")
    return {
        "schema": TRAINING_AGGREGATE_REVIEW_SCHEMA,
        "git": aggregate.get("git"),
        "aggregate_sha256": aggregate_external_sha256,
        "aggregate_internal_sha256": aggregate.get("aggregate_sha256"),
        "controller_packet_sha256": aggregate.get(
            "controller_packet_sha256"),
        "training_receipt_sha256": aggregate.get("training_receipt_sha256"),
        "model_dataset_sha256": aggregate.get("model_dataset_sha256"),
        "cell_count": aggregate.get("cell_count"),
        "decision": aggregate.get("decision"),
        "selection_sha256": selection.get("selection_sha256"),
        "selected_capability": selection.get("selected_capability"),
        "selected_ensemble_sha256": _manifest_hash(ensemble),
        "selected_ensemble_models": len(ensemble),
        "report_rows_opened_by_training_review": 0,
        "independent_review": True,
        "one_report_controller_freeze_authorized": True,
        "report_open_authorized": False,
        "composition_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }


def _cell_paths(training_packet: Mapping[str, object]) -> list[Path]:
    return [(REPO / str(cell["result"])).resolve()
            for cell in training_packet["schedule"]["cells"]]


def validate_training_aggregate(
    *, training_packet_path: Path, training_packet_sha256: str,
    training_review_record: Path, training_receipt_path: Path,
    training_receipt_sha256: str, aggregate_path: Path,
    aggregate_sha256: str, aggregate_review_record: Path,
) -> tuple[dict, dict, dict, dict]:
    packet, dataset = TRAIN_RUNTIME._packet(
        training_packet_path, training_packet_sha256)
    packet["external_sha256"] = training_packet_sha256
    TRAIN_RUNTIME._receipt(
        training_receipt_path, training_receipt_sha256, packet,
        training_packet_sha256, training_review_record)
    expected = TRAIN_RUNTIME.recompute_aggregate(
        packet_path=training_packet_path,
        expected_packet_sha256=training_packet_sha256,
        receipt_path=training_receipt_path,
        expected_receipt_sha256=training_receipt_sha256,
        review_record=training_review_record,
        cell_paths=_cell_paths(packet))
    if (aggregate_path.resolve()
            != (REPO / TRAIN_RUNTIME.AGGREGATE_PATH).resolve()
            or sha256_file(aggregate_path) != aggregate_sha256
            or load_json(aggregate_path) != expected):
        raise ReportControllerRefused(
            "Stage-C training aggregate replay/path/SHA drift")
    selection = expected.get("selection", {})
    ensemble = expected.get("selected_ensemble")
    capability = selection.get("selected_capability")
    if (expected.get("decision")
            != "FREEZE_SINGLE_CAPABILITY_FOR_REPORT_REVIEW"
            or expected.get("report_packet_review_authorized") is not True
            or expected.get("report_rows_opened") != 0
            or expected.get("report_open_authorized") is not False
            or not isinstance(capability, dict)
            or capability.get("surface") not in MODEL.SURFACES
            or capability.get("head") not in MODEL.CAPABILITY_HEADS
            or capability.get("epoch") not in MODEL.EPOCH_GRID
            or not isinstance(ensemble, list)
            or len(ensemble) != len(MODEL.TRAINING_SEEDS)
            or [value.get("seed") for value in ensemble]
            != list(MODEL.TRAINING_SEEDS)
            or any(value.get("surface") != capability["surface"]
                   or value.get("head") != capability["head"]
                   or value.get("epoch") != capability["epoch"]
                   for value in ensemble)):
        raise ReportControllerRefused(
            "Stage-C training aggregate selection/authority drift")
    claim = marker_claim(
        aggregate_review_record, TRAINING_AGGREGATE_REVIEW_MARKER)
    expected_claim = expected_training_aggregate_review_claim(
        expected, aggregate_sha256)
    if claim != expected_claim:
        raise ReportControllerRefused(
            "Stage-C training aggregate PASS marker drift")
    return packet, dataset, expected, claim


def _checkpoint_manifest(
    training_packet: Mapping[str, object],
    aggregate: Mapping[str, object],
) -> list[dict]:
    values = []
    capability = aggregate["selection"]["selected_capability"]
    for item in aggregate["selected_ensemble"]:
        path = (REPO / str(item["checkpoint_path"])).resolve()
        if (not is_regular_unlinked(path)
                or sha256_file(path) != item["checkpoint_sha256"]):
            raise ReportControllerRefused(
                "Stage-C selected checkpoint path/SHA drift")
        cell = next(value for value in training_packet["schedule"]["cells"]
                    if value["surface"] == capability["surface"]
                    and value["seed"] == item["seed"]
                    and value["curve_fraction"] == 1.0)
        contract = TRAIN_RUNTIME._snapshot_contract(
            training_packet, cell, int(capability["epoch"]),
            str(item["model_state_sha256"]))
        reopened = TRAIN.load_snapshot(path, expected_contract=contract)
        if reopened["model_state_sha256"] != item["model_state_sha256"]:
            raise ReportControllerRefused(
                "Stage-C selected checkpoint model-state drift")
        values.append({
            **dict(item),
            "checkpoint_contract": contract,
        })
    return values


def _report_manifest(
    label_packet: Mapping[str, object], dataset: Mapping[str, object],
) -> list[dict]:
    values = dataset.get("sealed_report_shards")
    if (not isinstance(values, list) or len(values) != 4
            or [value.get("index") for value in values]
            != list(range(12, 16))
            or any(value.get("split") != "REPORT" for value in values)):
        raise ReportControllerRefused("sealed REPORT manifest geometry drift")
    result = []
    for item in values:
        index = int(item["index"])
        schedule = label_packet["schedule"]["shards"][index]
        if (schedule.get("split") != "REPORT"
                or schedule.get("local_shard") != index - 12
                or schedule.get("state_count") != 128):
            raise ReportControllerRefused(
                "sealed REPORT label-schedule geometry drift")
        path = TRAIN_CTRL._expected_label_shard_path(label_packet, index)
        # Deliberately do not stat, hash or open `path` here. The reviewed
        # label aggregate supplied these identities; the one-shot runtime is
        # the first model consumer permitted to inspect the REPORT files.
        result.append({
            **dict(item),
            "states": int(schedule["state_count"]),
            "logical_path": str(path.relative_to(REPO)),
        })
    return result


def build_packet(
    *, git: str, training_packet: Mapping[str, object],
    training_aggregate: Mapping[str, object],
    training_aggregate_sha256: str,
    training_aggregate_review: Mapping[str, object],
    dataset: Mapping[str, object], label_packet: Mapping[str, object],
    label_controller_sha256: str, label_receipt_sha256: str,
) -> dict:
    capability = training_aggregate["selection"]["selected_capability"]
    surface = str(capability["surface"])
    checkpoints = _checkpoint_manifest(
        training_packet, training_aggregate)
    report_manifest = _report_manifest(label_packet, dataset)
    prior = TRAIN.state_balanced_prior(
        dataset["examples"]["DESIGN"][surface])
    current_runtime = runtime_contract()
    training_runtime = training_packet.get("runtime_contract", {})
    if any(training_runtime.get(key) != current_runtime[key]
           for key in ("host", "python", "torch", "numpy", "device")):
        raise ReportControllerRefused(
            "Stage-C REPORT/training runtime contract drift")
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
            "training_packet": {
                "logical_path": TRAIN_CTRL.PACKET_PATH,
                "external_sha256": training_aggregate[
                    "controller_packet_sha256"],
            },
            "training_aggregate": {
                "logical_path": TRAIN_RUNTIME.AGGREGATE_PATH,
                "external_sha256": training_aggregate_sha256,
                "internal_sha256": training_aggregate["aggregate_sha256"],
            },
            "training_aggregate_review_claim_sha256": _manifest_hash(
                training_aggregate_review),
            "model_dataset": {
                "logical_path": TRAIN_CTRL.DATASET_PATH,
                "external_sha256": training_aggregate[
                    "model_dataset_sha256"],
            },
            "label_controller": {
                "logical_path": LABEL._ctrl().CONTROLLER_PACKET_PATH,
                "external_sha256": label_controller_sha256,
            },
            "label_receipt": {
                "logical_path": label_packet["result_contract"]["receipt"],
                "external_sha256": label_receipt_sha256,
            },
            "state_set": dict(label_packet["parents"]["state_set"]),
        },
        "selected_capability": dict(capability),
        "runtime_contract": current_runtime,
        "checkpoint_manifest": checkpoints,
        "design_prior_distribution": prior,
        "report_manifest": report_manifest,
        "report_contract": {
            "surface": surface,
            "head": capability["head"],
            "states": REPORT_SURFACE_COUNTS[surface],
            "ensemble_models": len(MODEL.TRAINING_SEEDS),
            "ensemble_seeds": list(MODEL.TRAINING_SEEDS),
            "rank_ensemble":
                "mean within-ballot softmax probability across seeds",
            "outcome_ensemble": "mean eight-bin probability across seeds",
            "model_score_tie_epsilon": REPORT.MODEL_SCORE_TIE_EPSILON,
            "tie_break": "lowest candidate index within epsilon",
            "primary_gate":
                "paired-state Teacher improvement vs candidate0 LCB > 0",
            "outcome_head_additional_gate":
                "REPORT outcome NLL improvement vs DESIGN prior LCB > 0",
            "critical": REPORT.REPORT_T_CRITICAL,
            "single_report_look": True,
            "durable_report_open_admission_slot":
                f"server/runs/locks/{RUN_ID}.report-open.consumed.json",
            "retry_after_report_open_or_failure_authorized": False,
            "report_cannot_change_surface_head_epoch_or_seed_population": True,
            "pass_authority": "composition packet review only",
        },
        "commands": {
            "admit": [
                "{python}",
                "server/scripts/teacher_stage_c_report_runtime.py", "admit",
                "--expected-git", "{git}",
                "--controller-packet", PACKET_PATH,
                "--expected-controller-packet-sha256", "{packet_sha256}",
                "--controller-review-record", "{controller_review_record}",
                "--out", f"server/runs/logs/{RUN_ID}/report-receipt.json",
            ],
            "evaluate": [
                "{python}",
                "server/scripts/teacher_stage_c_report_runtime.py", "evaluate",
                "--expected-git", "{git}",
                "--controller-packet", PACKET_PATH,
                "--expected-controller-packet-sha256", "{packet_sha256}",
                "--controller-review-record", "{controller_review_record}",
                "--report-receipt",
                f"server/runs/logs/{RUN_ID}/report-receipt.json",
                "--expected-report-receipt-sha256", "{receipt_sha256}",
                "--out", f"server/runs/logs/{RUN_ID}/report-result.json",
            ],
        },
        "authority": {
            "report_shard_files_opened": 0,
            "report_rows_opened": 0,
            "one_report_execution_authorized": False,
            "composition_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
            "production_deployment": False,
        },
    }
    packet["packet_sha256"] = self_hash(packet, "packet_sha256")
    return packet


def expected_review_claim(packet: Mapping[str, object],
                          packet_external_sha256: str) -> dict:
    sources = packet["producer"]["sources"]
    capability = packet["selected_capability"]
    return {
        "schema": REVIEW_SCHEMA,
        "git": packet["producer"]["git"],
        "packet_sha256": packet_external_sha256,
        "packet_internal_sha256": packet["packet_sha256"],
        "controller_script_sha256": sources[
            "server/scripts/teacher_stage_c_report_controller.py"],
        "runtime_script_sha256": sources[
            "server/scripts/teacher_stage_c_report_runtime.py"],
        "report_model_sha256": sources[
            "server/shengji/rl/stage_c_report.py"],
        "training_aggregate_sha256": packet["parents"][
            "training_aggregate"]["external_sha256"],
        "selected_capability": capability,
        "checkpoint_manifest_sha256": _manifest_hash(
            packet["checkpoint_manifest"]),
        "ensemble_models": len(packet["checkpoint_manifest"]),
        "report_manifest_sha256": _manifest_hash(packet["report_manifest"]),
        "report_surface_states": packet["report_contract"]["states"],
        "model_score_tie_epsilon": packet["report_contract"][
            "model_score_tie_epsilon"],
        "execution_host": packet["runtime_contract"]["host"],
        "python": packet["runtime_contract"]["python"],
        "torch": packet["runtime_contract"]["torch"],
        "numpy": packet["runtime_contract"]["numpy"],
        "report_shard_files_opened_before_review": 0,
        "report_rows_opened_before_review": 0,
        "single_report_look": True,
        "report_open_admission_slot": packet["report_contract"][
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


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("command", choices=("freeze", "verify"))
    root.add_argument("--training-packet", required=True)
    root.add_argument("--expected-training-packet-sha256", required=True)
    root.add_argument("--training-review-record", required=True)
    root.add_argument("--training-receipt", required=True)
    root.add_argument("--expected-training-receipt-sha256", required=True)
    root.add_argument("--training-aggregate", required=True)
    root.add_argument("--expected-training-aggregate-sha256", required=True)
    root.add_argument("--training-aggregate-review-record", required=True)
    root.add_argument("--label-controller", required=True)
    root.add_argument("--expected-label-controller-sha256", required=True)
    root.add_argument("--label-controller-review-record", required=True)
    root.add_argument("--label-receipt", required=True)
    root.add_argument("--expected-label-receipt-sha256", required=True)
    root.add_argument("--state-set-review-record", required=True)
    root.add_argument("--label-aggregate", required=True)
    root.add_argument("--expected-label-aggregate-sha256", required=True)
    root.add_argument("--label-aggregate-review-record", required=True)
    root.add_argument("--out", required=True)
    root.add_argument("--expected-out-sha256")
    return root


def _validated_inputs(args) -> tuple[dict, dict, dict, dict, dict]:
    if _git("status", "--porcelain"):
        raise ReportControllerRefused(
            "real Stage-C REPORT packet freeze refuses dirty tree")
    training_packet, dataset, training_aggregate, training_review = \
        validate_training_aggregate(
            training_packet_path=Path(args.training_packet).resolve(),
            training_packet_sha256=args.expected_training_packet_sha256,
            training_review_record=Path(args.training_review_record).resolve(),
            training_receipt_path=Path(args.training_receipt).resolve(),
            training_receipt_sha256=args.expected_training_receipt_sha256,
            aggregate_path=Path(args.training_aggregate).resolve(),
            aggregate_sha256=args.expected_training_aggregate_sha256,
            aggregate_review_record=Path(
                args.training_aggregate_review_record).resolve())
    label_packet = LABEL._controller_packet(
        Path(args.label_controller).resolve(),
        args.expected_label_controller_sha256)
    state_set, _verification = LABEL._validated_parents(
        label_packet, Path(args.state_set_review_record).resolve())
    LABEL._receipt(
        Path(args.label_receipt).resolve(),
        args.expected_label_receipt_sha256, label_packet,
        args.expected_label_controller_sha256,
        Path(args.label_controller_review_record).resolve(),
        Path(args.state_set_review_record).resolve())
    label_aggregate, _label_review = TRAIN_CTRL.validate_label_aggregate(
        Path(args.label_aggregate).resolve(),
        args.expected_label_aggregate_sha256,
        Path(args.label_aggregate_review_record).resolve())
    if (args.expected_label_aggregate_sha256
            != training_packet["parents"]["label_aggregate"][
                "external_sha256"]
            or label_aggregate["state_set_sha256"]
            != dataset["state_set_sha256"]
            or len(state_set["states"]) != 2048
            or _manifest_hash(label_aggregate["sealed_report_manifest"])
            != dataset["sealed_report_manifest_sha256"]):
        raise ReportControllerRefused(
            "Stage-C REPORT label/training/state parent drift")
    return (training_packet, dataset, training_aggregate, training_review,
            label_packet)


def main() -> int:
    args = parser().parse_args()
    inputs = _validated_inputs(args)
    packet = build_packet(
        git=_git("rev-parse", "HEAD"),
        training_packet=inputs[0], dataset=inputs[1],
        training_aggregate=inputs[2],
        training_aggregate_sha256=args.expected_training_aggregate_sha256,
        training_aggregate_review=inputs[3], label_packet=inputs[4],
        label_controller_sha256=args.expected_label_controller_sha256,
        label_receipt_sha256=args.expected_label_receipt_sha256)
    out = Path(args.out).resolve()
    if out != (REPO / PACKET_PATH).resolve():
        raise ReportControllerRefused("Stage-C REPORT packet output path drift")
    if args.command == "freeze":
        publish_exclusive(out, packet)
    elif (not args.expected_out_sha256
          or sha256_file(out) != args.expected_out_sha256
          or load_json(out) != packet):
        raise ReportControllerRefused("Stage-C REPORT packet verification drift")
    print(json.dumps({
        "status": "FROZEN" if args.command == "freeze" else "VERIFIED",
        "packet_sha256": sha256_file(out),
        "packet_internal_sha256": packet["packet_sha256"],
        "selected_capability": packet["selected_capability"],
        "report_shard_files_opened": 0,
        "report_rows_opened": 0,
        "report_execution_authorized": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReportControllerRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        raise SystemExit(2)
