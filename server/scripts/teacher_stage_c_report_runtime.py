#!/usr/bin/env python3
"""Consume one reviewed Stage-C REPORT packet exactly once.

Admission validates the packet, selected checkpoints and all non-REPORT
parents without touching a REPORT shard.  Evaluation then opens the four
sealed label shards, replays their semantics, scores only the CALIB-frozen
surface/head/epoch ensemble, and publishes one terminal accept/reject result.
It cannot compose a bot, launch games, promote or deploy.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Mapping


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SCRIPT.parents[2]
sys.path.insert(0, str(SCRIPT.parent))

import teacher_stage_c_capture_runtime as CAPTURE  # noqa: E402
import teacher_stage_c_label_runtime as LABEL  # noqa: E402
import teacher_stage_c_report_controller as CTRL  # noqa: E402
import teacher_stage_c_training_controller as TRAIN_CTRL  # noqa: E402
import teacher_stage_c_training_runtime as TRAIN_RUNTIME  # noqa: E402
from shengji.rl import stage_c_model as MODEL  # noqa: E402
from shengji.rl import stage_c_report as REPORT  # noqa: E402
from shengji.rl import stage_c_training as TRAIN  # noqa: E402


RECEIPT_SCHEMA = "teacher-stage-c-report-receipt-v1"
ADMISSION_SCHEMA = "teacher-stage-c-report-admission-v1"
RESULT_SCHEMA = "teacher-stage-c-report-result-v1"
RECEIPT_PATH = f"server/runs/logs/{CTRL.RUN_ID}/report-receipt.json"
RESULT_PATH = f"server/runs/logs/{CTRL.RUN_ID}/report-result.json"
ADMISSION_PATH = f"server/runs/locks/{CTRL.RUN_ID}.consumed.json"
REPORT_OPEN_ADMISSION_PATH = \
    f"server/runs/locks/{CTRL.RUN_ID}.report-open.consumed.json"


class ReportRuntimeRefused(RuntimeError):
    """A packet, admission, REPORT shard, model or result identity drifted."""


canonical_json = CTRL.canonical_json
sha256_bytes = CTRL.sha256_bytes
sha256_file = CTRL.sha256_file
self_hash = CTRL.self_hash


def is_regular_unlinked(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not path.is_symlink())


def load_json(path: Path) -> dict:
    if not is_regular_unlinked(path):
        raise ReportRuntimeRefused(f"input is not regular/unlinked: {path}")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ReportRuntimeRefused(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReportRuntimeRefused(f"JSON root is not an object: {path}")
    return value


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _require_clean_tree() -> None:
    if _git("status", "--porcelain", "--untracked-files=all"):
        raise ReportRuntimeRefused("Stage-C REPORT runtime refuses a dirty tree")


def publish_exclusive(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise ReportRuntimeRefused(f"refusing existing output: {path}")
    with partial.open("xb") as handle:
        handle.write(canonical_json(payload))
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.link(partial, path, follow_symlinks=False)
    except FileExistsError as exc:
        raise ReportRuntimeRefused(
            f"refusing raced output publication: {path}") from exc
    partial.unlink()


def _expected_packet_path() -> Path:
    return (REPO / CTRL.PACKET_PATH).resolve()


def _expected_receipt_path() -> Path:
    return (REPO / RECEIPT_PATH).resolve()


def _expected_result_path() -> Path:
    return (REPO / RESULT_PATH).resolve()


def _parent_file(parent: Mapping[str, object], label: str) -> tuple[Path, dict]:
    path = (REPO / str(parent.get("logical_path"))).resolve()
    if (not is_regular_unlinked(path)
            or sha256_file(path) != parent.get("external_sha256")):
        raise ReportRuntimeRefused(f"Stage-C REPORT {label} path/SHA drift")
    return path, load_json(path)


def _validate_checkpoint_manifest(packet: Mapping[str, object],
                                  training_packet: Mapping[str, object]) -> None:
    capability = packet["selected_capability"]
    manifest = packet.get("checkpoint_manifest")
    if (not isinstance(manifest, list)
            or len(manifest) != len(MODEL.TRAINING_SEEDS)
            or [value.get("seed") for value in manifest]
            != list(MODEL.TRAINING_SEEDS)):
        raise ReportRuntimeRefused("Stage-C REPORT checkpoint manifest drift")
    training_packet = dict(training_packet)
    training_packet["external_sha256"] = packet["parents"][
        "training_packet"]["external_sha256"]
    for item in manifest:
        path = (REPO / str(item.get("checkpoint_path"))).resolve()
        if (not is_regular_unlinked(path)
                or sha256_file(path) != item.get("checkpoint_sha256")
                or item.get("surface") != capability["surface"]
                or item.get("head") != capability["head"]
                or item.get("epoch") != capability["epoch"]):
            raise ReportRuntimeRefused(
                "Stage-C REPORT checkpoint identity drift")
        cell = next(value for value in training_packet["schedule"]["cells"]
                    if value["surface"] == capability["surface"]
                    and value["seed"] == item["seed"]
                    and value["curve_fraction"] == 1.0)
        expected_contract = TRAIN_RUNTIME._snapshot_contract(
            training_packet, cell, int(capability["epoch"]),
            str(item["model_state_sha256"]))
        if item.get("checkpoint_contract") != expected_contract:
            raise ReportRuntimeRefused(
                "Stage-C REPORT checkpoint contract drift")
        TRAIN.load_snapshot(path, expected_contract=expected_contract)


def _packet(path: Path, expected_sha256: str) -> tuple[dict, dict, dict, dict]:
    _require_clean_tree()
    if (path.resolve() != _expected_packet_path()
            or not is_regular_unlinked(path)
            or sha256_file(path) != expected_sha256):
        raise ReportRuntimeRefused("Stage-C REPORT packet path/SHA drift")
    packet = load_json(path)
    authority = packet.get("authority", {})
    if (packet.get("schema") != CTRL.SCHEMA
            or packet.get("packet_id") != CTRL.PACKET_ID
            or packet.get("run_id") != CTRL.RUN_ID
            or packet.get("packet_sha256")
            != self_hash(packet, "packet_sha256")
            or packet.get("producer", {}).get("git")
            != _git("rev-parse", "HEAD")
            or packet.get("producer", {}).get("tree_dirty") is not False
            or packet.get("producer", {}).get("sources")
            != CTRL._source_sha256s()
            or packet.get("runtime_contract") != CTRL.runtime_contract()
            or authority.get("report_shard_files_opened") != 0
            or authority.get("report_rows_opened") != 0
            or authority.get("one_report_execution_authorized") is not False
            or authority.get("composition_authorized") is not False
            or authority.get("strength_claim") is not False
            or authority.get("production_promotion") is not False
            or authority.get("production_deployment") is not False):
        raise ReportRuntimeRefused("Stage-C REPORT packet identity/authority drift")
    parents = packet.get("parents", {})
    training_packet_path, training_packet = _parent_file(
        parents["training_packet"], "training packet")
    if training_packet_path != (REPO / TRAIN_CTRL.PACKET_PATH).resolve():
        raise ReportRuntimeRefused("Stage-C REPORT training packet path drift")
    try:
        verified_training_packet, verified_dataset = TRAIN_RUNTIME._packet(
            training_packet_path,
            str(parents["training_packet"]["external_sha256"]))
    except TRAIN_RUNTIME.TrainingRuntimeRefused as exc:
        raise ReportRuntimeRefused(str(exc)) from exc
    if verified_training_packet != training_packet:
        raise ReportRuntimeRefused(
            "Stage-C REPORT training packet replay drift")
    aggregate_path, aggregate = _parent_file(
        parents["training_aggregate"], "training aggregate")
    if (aggregate_path != (REPO / TRAIN_RUNTIME.AGGREGATE_PATH).resolve()
            or aggregate.get("aggregate_sha256")
            != parents["training_aggregate"]["internal_sha256"]
            or aggregate.get("selection", {}).get("selected_capability")
            != packet.get("selected_capability")
            or aggregate.get("selected_ensemble")
            != [{key: value for key, value in item.items()
                 if key != "checkpoint_contract"}
                for item in packet.get("checkpoint_manifest", [])]):
        raise ReportRuntimeRefused(
            "Stage-C REPORT training aggregate selection drift")
    dataset_path, dataset = _parent_file(
        parents["model_dataset"], "model dataset")
    if (dataset_path != (REPO / TRAIN_CTRL.DATASET_PATH).resolve()
            or dataset != verified_dataset
            or dataset.get("dataset_sha256")
            != TRAIN_CTRL.self_hash(dataset, "dataset_sha256")
            or dataset.get("report_rows_included") is not False
            or dataset.get("report_shard_files_opened") != 0):
        raise ReportRuntimeRefused("Stage-C REPORT model dataset drift")
    label_path, label_packet = _parent_file(
        parents["label_controller"], "label controller")
    if label_path != (REPO / LABEL._ctrl().CONTROLLER_PACKET_PATH).resolve():
        raise ReportRuntimeRefused("Stage-C REPORT label packet path drift")
    try:
        verified_label_packet = LABEL._controller_packet(
            label_path, str(parents["label_controller"]["external_sha256"]))
    except LABEL.LabelRefused as exc:
        raise ReportRuntimeRefused(str(exc)) from exc
    expected_label_packet = dict(label_packet)
    expected_label_packet["external_sha256"] = parents["label_controller"][
        "external_sha256"]
    if verified_label_packet != expected_label_packet:
        raise ReportRuntimeRefused("Stage-C REPORT label packet replay drift")
    label_packet = verified_label_packet
    state_path, state_set = _parent_file(
        parents["state_set"], "state set")
    if (state_path != (REPO / label_packet["parents"]["state_set"][
            "logical_path"]).resolve()
            or len(state_set.get("states", [])) != 2048):
        raise ReportRuntimeRefused("Stage-C REPORT state-set drift")
    _validate_checkpoint_manifest(packet, training_packet)
    surface = packet["selected_capability"]["surface"]
    prior = TRAIN.state_balanced_prior(dataset["examples"]["DESIGN"][surface])
    if (packet.get("design_prior_distribution") != prior
            or packet.get("report_contract", {}).get("surface") != surface
            or packet["report_contract"].get("head")
            != packet["selected_capability"]["head"]
            or packet["report_contract"].get("states")
            != CTRL.REPORT_SURFACE_COUNTS[surface]
            or packet["report_contract"].get("single_report_look") is not True
            or packet["report_contract"].get("model_score_tie_epsilon")
            != REPORT.MODEL_SCORE_TIE_EPSILON
            or packet["report_contract"].get("tie_break")
            != "lowest candidate index within epsilon"
            or packet["report_contract"].get(
                "durable_report_open_admission_slot")
            != REPORT_OPEN_ADMISSION_PATH
            or packet["report_contract"].get(
                "retry_after_report_open_or_failure_authorized") is not False
            or packet["report_contract"].get(
                "report_cannot_change_surface_head_epoch_or_seed_population")
            is not True):
        raise ReportRuntimeRefused("Stage-C REPORT contract/prior drift")
    manifest = packet.get("report_manifest")
    if (not isinstance(manifest, list) or len(manifest) != 4
            or [value.get("index") for value in manifest]
            != list(range(12, 16))
            or any(value.get("split") != "REPORT"
                   or value.get("states") != 128 for value in manifest)
            or sum(int(value["states"]) for value in manifest) != 512):
        raise ReportRuntimeRefused("Stage-C REPORT sealed manifest drift")
    # This deliberately validates logical identities only. No REPORT path is
    # statted, hashed or opened before the durable admission exists.
    for item in manifest:
        expected_path = TRAIN_CTRL._expected_label_shard_path(
            label_packet, int(item["index"]))
        if item.get("logical_path") != str(expected_path.relative_to(REPO)):
            raise ReportRuntimeRefused("Stage-C REPORT shard path drift")
    return packet, dataset, label_packet, state_set


def _review_claim(path: Path, packet: Mapping[str, object],
                  packet_sha256: str) -> dict:
    claim = CTRL.marker_claim(path, CTRL.REVIEW_MARKER)
    if claim != CTRL.expected_review_claim(packet, packet_sha256):
        raise ReportRuntimeRefused("Stage-C REPORT packet PASS marker drift")
    return claim


def _slot_payload(packet: Mapping[str, object], packet_sha256: str,
                  review_record: Path) -> dict:
    value = {
        "schema": ADMISSION_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": packet_sha256,
        "selected_capability": packet["selected_capability"],
        "checkpoint_manifest_sha256": CTRL._manifest_hash(
            packet["checkpoint_manifest"]),
        "report_manifest_sha256": CTRL._manifest_hash(
            packet["report_manifest"]),
        "controller_review_record_sha256": sha256_file(review_record),
        "receipt_path": RECEIPT_PATH,
        "consumed_even_if_receipt_or_report_publication_fails": True,
    }
    value["slot_sha256"] = self_hash(value, "slot_sha256")
    return value


def admit(*, packet_path: Path, expected_packet_sha256: str,
          review_record: Path, out: Path) -> dict:
    packet, _dataset, _label_packet, _state_set = _packet(
        packet_path, expected_packet_sha256)
    claim = _review_claim(review_record, packet, expected_packet_sha256)
    if out.resolve() != _expected_receipt_path():
        raise ReportRuntimeRefused("Stage-C REPORT receipt path drift")
    slot_path = (REPO / ADMISSION_PATH).resolve()
    slot = _slot_payload(packet, expected_packet_sha256, review_record)
    publish_exclusive(slot_path, slot)
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": expected_packet_sha256,
        "controller_packet_internal_sha256": packet["packet_sha256"],
        "selected_capability": packet["selected_capability"],
        "controller_review_record_sha256": sha256_file(review_record),
        "controller_review_claim": claim,
        "admission_slot": ADMISSION_PATH,
        "admission_slot_sha256": sha256_file(slot_path),
        "report_open_admission_slot": REPORT_OPEN_ADMISSION_PATH,
        "report_open_admission_consumed": False,
        "report_execution_authorized": True,
        "report_shard_files_opened": 0,
        "report_rows_opened": 0,
        "composition_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    receipt["receipt_sha256"] = self_hash(receipt, "receipt_sha256")
    publish_exclusive(out, receipt)
    return receipt


def _report_open_slot_payload(
    packet: Mapping[str, object], packet_sha256: str,
    receipt_sha256: str, review_record: Path,
) -> dict:
    value = {
        "schema": "teacher-stage-c-report-open-admission-v1",
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": packet_sha256,
        "report_receipt_sha256": receipt_sha256,
        "selected_capability": packet["selected_capability"],
        "report_manifest_sha256": CTRL._manifest_hash(
            packet["report_manifest"]),
        "controller_review_record_sha256": sha256_file(review_record),
        "result_path": RESULT_PATH,
        "consumed_before_any_report_path_access": True,
        "retry_after_report_open_or_failure_authorized": False,
    }
    value["slot_sha256"] = self_hash(value, "slot_sha256")
    return value


def _consume_report_open_slot(
    packet: Mapping[str, object], packet_sha256: str,
    receipt_sha256: str, review_record: Path,
) -> tuple[dict, str]:
    path = (REPO / REPORT_OPEN_ADMISSION_PATH).resolve()
    value = _report_open_slot_payload(
        packet, packet_sha256, receipt_sha256, review_record)
    publish_exclusive(path, value)
    return value, sha256_file(path)


def _validate_report_open_slot(
    packet: Mapping[str, object], packet_sha256: str,
    receipt_sha256: str, review_record: Path, expected_sha256: str,
) -> None:
    path = (REPO / REPORT_OPEN_ADMISSION_PATH).resolve()
    expected = _report_open_slot_payload(
        packet, packet_sha256, receipt_sha256, review_record)
    if (not is_regular_unlinked(path)
            or sha256_file(path) != expected_sha256
            or load_json(path) != expected):
        raise ReportRuntimeRefused("Stage-C REPORT-open admission drift")


def _receipt(path: Path, expected_sha256: str,
             packet: Mapping[str, object], packet_sha256: str,
             review_record: Path) -> dict:
    if (path.resolve() != _expected_receipt_path()
            or not is_regular_unlinked(path)
            or sha256_file(path) != expected_sha256):
        raise ReportRuntimeRefused("Stage-C REPORT receipt path/SHA drift")
    receipt = load_json(path)
    slot_path = (REPO / ADMISSION_PATH).resolve()
    expected_slot = _slot_payload(packet, packet_sha256, review_record)
    if (not is_regular_unlinked(slot_path)
            or load_json(slot_path) != expected_slot
            or receipt.get("schema") != RECEIPT_SCHEMA
            or receipt.get("run_id") != CTRL.RUN_ID
            or receipt.get("git") != packet["producer"]["git"]
            or receipt.get("controller_packet_sha256") != packet_sha256
            or receipt.get("controller_packet_internal_sha256")
            != packet["packet_sha256"]
            or receipt.get("selected_capability")
            != packet["selected_capability"]
            or receipt.get("controller_review_record_sha256")
            != sha256_file(review_record)
            or receipt.get("controller_review_claim")
            != _review_claim(review_record, packet, packet_sha256)
            or receipt.get("admission_slot") != ADMISSION_PATH
            or receipt.get("admission_slot_sha256") != sha256_file(slot_path)
            or receipt.get("report_open_admission_slot")
            != REPORT_OPEN_ADMISSION_PATH
            or receipt.get("report_open_admission_consumed") is not False
            or receipt.get("report_execution_authorized") is not True
            or receipt.get("report_shard_files_opened") != 0
            or receipt.get("report_rows_opened") != 0
            or receipt.get("composition_authorized") is not False
            or receipt.get("receipt_sha256")
            != self_hash(receipt, "receipt_sha256")):
        raise ReportRuntimeRefused("Stage-C REPORT receipt/slot drift")
    return receipt


def _report_examples(packet: Mapping[str, object],
                     label_packet: Mapping[str, object],
                     state_set: Mapping[str, object]) -> tuple[list[dict], list[dict]]:
    receipt_parent = packet["parents"]["label_receipt"]
    receipt_path, _label_receipt = _parent_file(
        receipt_parent, "label receipt")
    if receipt_path != (REPO / label_packet["result_contract"]["receipt"]).resolve():
        raise ReportRuntimeRefused("Stage-C REPORT label receipt path drift")
    net = LABEL._load_v11()
    state_map = {str(value["state_id"]): value
                 for value in state_set["states"]}
    examples = []
    opened = []
    surface = packet["selected_capability"]["surface"]
    for item in packet["report_manifest"]:
        index = int(item["index"])
        path = (REPO / str(item["logical_path"])).resolve()
        if (not is_regular_unlinked(path)
                or sha256_file(path) != item.get("sha256")):
            raise ReportRuntimeRefused(
                f"Stage-C REPORT shard {index} path/SHA drift")
        shard = load_json(path)
        LABEL.validate_shard(
            shard, packet=label_packet,
            receipt_sha256=receipt_parent["external_sha256"],
            state_set=state_set, index=index, net=net)
        if (shard.get("status") != "COMPLETE"
                or shard.get("refused_rows") != 0
                or sha256_bytes(canonical_json(shard.get("row_sha256s")))
                != item.get("row_sha256s_sha256")):
            raise ReportRuntimeRefused(
                f"Stage-C REPORT shard {index} incomplete")
        for state_id, row in zip(
                shard["state_ids"], shard["rows"], strict=True):
            state = state_map[str(state_id)]
            if state["surface_type"] != surface:
                continue
            rnd = CAPTURE.replay_state(state)
            example = MODEL.materialize_example(state, row, rnd)
            TRAIN._validate_example(example, split="REPORT", surface=surface)
            examples.append(example)
        opened.append({
            "index": index,
            "logical_path": item["logical_path"],
            "external_sha256": item["sha256"],
            "row_sha256s_sha256": item["row_sha256s_sha256"],
        })
    examples.sort(key=lambda value: str(value["state_id"]))
    if (len(examples) != packet["report_contract"]["states"]
            or len({value["state_id"] for value in examples}) != len(examples)):
        raise ReportRuntimeRefused("Stage-C REPORT example population drift")
    return examples, opened


def _member_predictions(packet: Mapping[str, object],
                        examples: list[dict]):
    TRAIN._configure_determinism(MODEL.TRAINING_SEEDS[0])
    values = []
    for item in packet["checkpoint_manifest"]:
        path = (REPO / str(item["checkpoint_path"])).resolve()
        reopened = TRAIN.load_snapshot(
            path, expected_contract=item["checkpoint_contract"])
        net = MODEL.StageCRankingOutcomeNet(hidden=TRAIN.HIDDEN)
        net.load_state_dict(reopened["state_dict"], strict=True)
        values.append(TRAIN.predict_examples(net, examples))
    return values


def evaluate(*, packet_path: Path, expected_packet_sha256: str,
             review_record: Path, receipt_path: Path,
             expected_receipt_sha256: str, out: Path) -> dict:
    if out.resolve() != _expected_result_path():
        raise ReportRuntimeRefused("Stage-C REPORT result path drift")
    packet, _dataset, label_packet, state_set = _packet(
        packet_path, expected_packet_sha256)
    _receipt(receipt_path, expected_receipt_sha256, packet,
             expected_packet_sha256, review_record)
    _report_slot, report_slot_sha256 = _consume_report_open_slot(
        packet, expected_packet_sha256, expected_receipt_sha256,
        review_record)
    examples, opened = _report_examples(packet, label_packet, state_set)
    predictions = _member_predictions(packet, examples)
    capability = packet["selected_capability"]
    evaluation = REPORT.evaluate_capability(
        examples, predictions, surface=capability["surface"],
        head=capability["head"],
        prior_distribution=packet["design_prior_distribution"])
    payload = {
        "schema": RESULT_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": expected_packet_sha256,
        "report_receipt_sha256": expected_receipt_sha256,
        "report_open_admission_slot": REPORT_OPEN_ADMISSION_PATH,
        "report_open_admission_slot_sha256": report_slot_sha256,
        "selected_capability": capability,
        "checkpoint_manifest_sha256": CTRL._manifest_hash(
            packet["checkpoint_manifest"]),
        "report_manifest_sha256": CTRL._manifest_hash(
            packet["report_manifest"]),
        "opened_report_shards": opened,
        "report_shard_files_opened": len(opened),
        "report_rows_opened": sum(
            int(item["states"]) for item in packet["report_manifest"]),
        "evaluation": evaluation,
        "decision": evaluation["decision"],
        "composition_packet_review_authorized": evaluation[
            "composition_packet_review_authorized"],
        "report_reuse_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    payload["result_sha256"] = self_hash(payload, "result_sha256")
    # Close every mutable input/output TOCTOU boundary after the expensive
    # prediction pass. `_packet` still does not open REPORT shard paths.
    final_packet, _dataset2, _label2, _state2 = _packet(
        packet_path, expected_packet_sha256)
    _receipt(receipt_path, expected_receipt_sha256, final_packet,
             expected_packet_sha256, review_record)
    _validate_report_open_slot(
        final_packet, expected_packet_sha256, expected_receipt_sha256,
        review_record, report_slot_sha256)
    for item in packet["report_manifest"]:
        if sha256_file(REPO / str(item["logical_path"])) != item["sha256"]:
            raise ReportRuntimeRefused("Stage-C REPORT shard changed during run")
    publish_exclusive(out, payload)
    return payload


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("admit", "evaluate"):
        child = commands.add_parser(name)
        child.add_argument("--expected-git", required=True)
        child.add_argument("--controller-packet", required=True)
        child.add_argument("--expected-controller-packet-sha256", required=True)
        child.add_argument("--controller-review-record", required=True)
        child.add_argument("--out", required=True)
        if name == "evaluate":
            child.add_argument("--report-receipt", required=True)
            child.add_argument("--expected-report-receipt-sha256", required=True)
    return root


def main() -> int:
    args = parser().parse_args()
    if _git("rev-parse", "HEAD") != args.expected_git:
        raise ReportRuntimeRefused("Stage-C REPORT expected Git drift")
    common = {
        "packet_path": Path(args.controller_packet).resolve(),
        "expected_packet_sha256": args.expected_controller_packet_sha256,
        "review_record": Path(args.controller_review_record).resolve(),
        "out": Path(args.out).resolve(),
    }
    if args.command == "admit":
        value = admit(**common)
    else:
        value = evaluate(
            **common, receipt_path=Path(args.report_receipt).resolve(),
            expected_receipt_sha256=args.expected_report_receipt_sha256)
    print(json.dumps({
        "status": value.get("decision", "ADMITTED"),
        "sha256": sha256_bytes(canonical_json(value)),
        "composition_authorized": False,
        "strength_claim": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReportRuntimeRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        raise SystemExit(2)
