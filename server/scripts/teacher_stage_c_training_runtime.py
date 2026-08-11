#!/usr/bin/env python3
"""Execute and aggregate one reviewed Stage-C model-training packet.

The runtime consumes only the materialized DESIGN/CALIB dataset frozen by the
training controller.  Forty-eight immutable cells cover separate play/bury
models, eight seeds and three nested DESIGN curves.  Every cell consumes its
own durable admission before training.  There is no retry path.

Aggregation reopens every checkpoint and recomputes every CALIB metric from
the frozen dataset.  Only full-data cells enter the single global epoch rule.
A passing aggregate can authorize review of a one-shot REPORT evaluator; this
runtime never opens REPORT, composes a policy, launches strength compute,
promotes, or deploys.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import stat
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SCRIPT.parents[2]
sys.path.insert(0, str(SCRIPT.parent))

import teacher_stage_c_training_controller as CTRL  # noqa: E402
from shengji.rl import stage_c_model as MODEL  # noqa: E402
from shengji.rl import stage_c_training as TRAIN  # noqa: E402


RECEIPT_SCHEMA = "teacher-stage-c-training-receipt-v1"
ADMISSION_SCHEMA = "teacher-stage-c-training-admission-v1"
CELL_ADMISSION_SCHEMA = "teacher-stage-c-training-cell-admission-v1"
CELL_SCHEMA = "teacher-stage-c-training-cell-result-v1"
AGGREGATE_SCHEMA = "teacher-stage-c-training-aggregate-v1"
RECEIPT_PATH = f"server/runs/logs/{CTRL.RUN_ID}/training-receipt.json"
AGGREGATE_PATH = f"server/runs/logs/{CTRL.RUN_ID}/training-aggregate.json"
ADMISSION_PATH = f"server/runs/locks/{CTRL.RUN_ID}.consumed.json"


class TrainingRuntimeRefused(RuntimeError):
    """A packet, admission, cell, checkpoint or CALIB result drifted."""


def canonical_json(value: object) -> bytes:
    return CTRL.canonical_json(value)


def sha256_bytes(value: bytes) -> str:
    return CTRL.sha256_bytes(value)


def sha256_file(path: str | os.PathLike[str]) -> str:
    return CTRL.sha256_file(path)


def self_hash(value: Mapping[str, object], field: str) -> str:
    return CTRL.self_hash(value, field)


def is_regular_unlinked(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not path.is_symlink())


def load_json(path: Path) -> dict:
    if not is_regular_unlinked(path):
        raise TrainingRuntimeRefused(f"input is not regular/unlinked: {path}")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise TrainingRuntimeRefused(f"cannot read JSON {path}: {exc}") \
            from exc
    if not isinstance(value, dict):
        raise TrainingRuntimeRefused(f"JSON root is not an object: {path}")
    return value


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _require_output_available(path: Path) -> None:
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise TrainingRuntimeRefused(f"refusing existing output: {path}")


def _require_admission_outputs_available(slot_path: Path, out: Path) -> None:
    if (slot_path != (REPO / ADMISSION_PATH).resolve()
            or out.resolve() != _expected_receipt_path()):
        raise TrainingRuntimeRefused("Stage-C training receipt path drift")
    _require_output_available(slot_path)
    _require_output_available(out)


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
            raise TrainingRuntimeRefused(
                f"refusing raced output publication: {path}") from exc
        partial.unlink()
    except BaseException:
        raise


def _expected_dataset_path() -> Path:
    return (REPO / CTRL.DATASET_PATH).resolve()


def _expected_packet_path() -> Path:
    return (REPO / CTRL.PACKET_PATH).resolve()


def _expected_receipt_path() -> Path:
    return (REPO / RECEIPT_PATH).resolve()


def _expected_aggregate_path() -> Path:
    return (REPO / AGGREGATE_PATH).resolve()


def _cell_slot_path(index: int) -> Path:
    return (REPO / "server/runs/locks"
            / f"{CTRL.RUN_ID}.cell-{index:02d}.consumed.json").resolve()


def _dataset(path: Path, expected_sha256: str) -> dict:
    if path.resolve() != _expected_dataset_path() \
            or sha256_file(path) != expected_sha256:
        raise TrainingRuntimeRefused("Stage-C model dataset path/SHA drift")
    dataset = load_json(path)
    examples = dataset.get("examples")
    fresh = dataset.get("fresh_report_selection")
    if (dataset.get("schema") != CTRL.DATASET_SCHEMA
            or dataset.get("run_id") != CTRL.RUN_ID
            or dataset.get("dataset_sha256")
            != self_hash(dataset, "dataset_sha256")
            or dataset.get("split_counts") != CTRL.EXPECTED_SPLITS
            or dataset.get("surface_counts") != CTRL.EXPECTED_SURFACES
            or dataset.get("report_rows_included") is not False
            or dataset.get("report_label_shard_files_opened") != 0
            or dataset.get("old_report_labels_quarantined") is not True
            or dataset.get("fresh_report_states_materialized") is not False
            or dataset.get("fresh_report_capture_shards_revalidated") != 8
            or dataset.get("training_authorized") is not False
            or dataset.get("report_open_authorized") is not False
            or not isinstance(fresh, dict)
            or fresh.get("packet_external_sha256")
            != CTRL.FRESH_REPORT_PACKET_SHA256
            or fresh.get("fresh_report_states") != 512
            or not isinstance(examples, dict)
            or set(examples) != {"DESIGN", "CALIB"}):
        raise TrainingRuntimeRefused("Stage-C model dataset identity drift")
    all_ids = set()
    for split in ("DESIGN", "CALIB"):
        surfaces = examples.get(split)
        if not isinstance(surfaces, dict) or set(surfaces) != set(MODEL.SURFACES):
            raise TrainingRuntimeRefused("Stage-C model dataset surface drift")
        for surface in MODEL.SURFACES:
            values = surfaces[surface]
            if len(values) != CTRL.EXPECTED_SURFACES[split][surface]:
                raise TrainingRuntimeRefused(
                    "Stage-C model dataset surface count drift")
            TRAIN.validate_population(values, split=split, surface=surface)
            ids = {str(value["state_id"]) for value in values}
            if all_ids & ids:
                raise TrainingRuntimeRefused(
                    "Stage-C model dataset cross-cell identity overlap")
            all_ids.update(ids)
    if len(all_ids) != 1536:
        raise TrainingRuntimeRefused("Stage-C model dataset state count drift")
    return dataset


def _packet(path: Path, expected_sha256: str) -> tuple[dict, dict]:
    if path.resolve() != _expected_packet_path() \
            or sha256_file(path) != expected_sha256:
        raise TrainingRuntimeRefused("Stage-C training packet path/SHA drift")
    packet = load_json(path)
    if (packet.get("schema") != CTRL.SCHEMA
            or packet.get("packet_id") != CTRL.PACKET_ID
            or packet.get("run_id") != CTRL.RUN_ID
            or packet.get("packet_sha256")
            != self_hash(packet, "packet_sha256")
            or packet.get("producer", {}).get("git") != _git("rev-parse", "HEAD")
            or packet.get("producer", {}).get("tree_dirty") is not False
            or packet.get("producer", {}).get("sources")
            != CTRL._source_sha256s()
            or packet.get("runtime_contract") != CTRL.runtime_contract()
            or packet.get("model_contract") != CTRL.model_contract()
            or packet.get("schedule") != CTRL.build_schedule()
            or packet.get("result_contract")
            != CTRL.result_contract(packet.get("schedule", {}))
            or packet.get("commands") != CTRL.commands(
                packet.get("schedule", {}))
            or packet.get("authority", {}).get(
                "one_training_execution_authorized") is not False
            or packet.get("authority", {}).get("report_rows_opened") != 0
            or packet.get("authority", {}).get(
                "report_open_authorized") is not False):
        raise TrainingRuntimeRefused("Stage-C training packet identity drift")
    parents = packet.get("parents", {})
    parent = parents.get("model_dataset", {})
    fresh_parent = parents.get("fresh_report_selection", {})
    dataset = _dataset(
        REPO / str(parent.get("logical_path")),
        str(parent.get("external_sha256")))
    if (parent.get("internal_sha256") != dataset.get("dataset_sha256")
            or parent.get("design_states") != 1024
            or parent.get("calib_states") != 512
            or parent.get("report_rows_included") is not False
            or parent.get("fresh_report_selection_sha256")
            != CTRL._manifest_hash(dataset.get("fresh_report_selection"))
            or fresh_parent.get("external_sha256")
            != CTRL.FRESH_REPORT_PACKET_SHA256
            or fresh_parent.get("internal_sha256")
            != dataset["fresh_report_selection"]["packet_internal_sha256"]
            or fresh_parent.get("sealed_selection_sha256")
            != dataset["fresh_report_selection"]["sealed_selection_sha256"]
            or fresh_parent.get("fresh_report_state_ids_sha256")
            != dataset["fresh_report_selection"][
                "fresh_report_state_ids_sha256"]
            or fresh_parent.get("state_material_published") is not False):
        raise TrainingRuntimeRefused("Stage-C packet/dataset parent drift")
    return packet, dataset


def _review_claim(path: Path, packet: Mapping[str, object],
                  packet_sha256: str) -> dict:
    claim = CTRL.marker_claim(path, CTRL.REVIEW_MARKER)
    expected = CTRL.expected_review_claim(packet, packet_sha256)
    if claim != expected:
        raise TrainingRuntimeRefused("Stage-C training packet PASS marker drift")
    return claim


def _slot_payload(packet: Mapping[str, object], packet_sha256: str,
                  review_record: Path) -> dict:
    value = {
        "schema": ADMISSION_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": packet_sha256,
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "model_dataset_sha256": packet["parents"]["model_dataset"][
            "external_sha256"],
        "controller_review_record_sha256": sha256_file(review_record),
        "receipt_path": str(_expected_receipt_path()),
        "consumed_even_if_receipt_publication_fails": True,
    }
    value["slot_sha256"] = self_hash(value, "slot_sha256")
    return value


def admit(*, packet_path: Path, expected_packet_sha256: str,
          review_record: Path, out: Path) -> dict:
    slot_path = (REPO / ADMISSION_PATH).resolve()
    _require_admission_outputs_available(slot_path, out)
    packet, _dataset_value = _packet(packet_path, expected_packet_sha256)
    claim = _review_claim(review_record, packet, expected_packet_sha256)
    slot = _slot_payload(packet, expected_packet_sha256, review_record)
    slot_sha256 = sha256_bytes(canonical_json(slot))
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": expected_packet_sha256,
        "controller_packet_internal_sha256": packet["packet_sha256"],
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "model_dataset_sha256": packet["parents"]["model_dataset"][
            "external_sha256"],
        "controller_review_record_sha256": sha256_file(review_record),
        "controller_review_claim": claim,
        "admission_slot": ADMISSION_PATH,
        "admission_slot_sha256": slot_sha256,
        "training_authorized": True,
        "report_rows_opened": 0,
        "report_open_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    receipt["receipt_sha256"] = self_hash(receipt, "receipt_sha256")
    # Build and preflight the complete logical pair before consuming the
    # durable no-retry admission. A genuine race or I/O failure after this
    # point still consumes admission, as the slot contract states.
    _require_admission_outputs_available(slot_path, out)
    publish_exclusive(slot_path, slot)
    publish_exclusive(out, receipt)
    return receipt


def _receipt(path: Path, expected_sha256: str,
             packet: Mapping[str, object], packet_sha256: str,
             review_record: Path) -> dict:
    if path.resolve() != _expected_receipt_path() \
            or sha256_file(path) != expected_sha256:
        raise TrainingRuntimeRefused("Stage-C training receipt path/SHA drift")
    receipt = load_json(path)
    claim = _review_claim(review_record, packet, packet_sha256)
    slot_path = (REPO / ADMISSION_PATH).resolve()
    expected_slot = _slot_payload(packet, packet_sha256, review_record)
    if not is_regular_unlinked(slot_path) or load_json(slot_path) != expected_slot:
        raise TrainingRuntimeRefused("Stage-C training admission slot drift")
    expected = {
        "schema": RECEIPT_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": packet_sha256,
        "controller_packet_internal_sha256": packet["packet_sha256"],
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "model_dataset_sha256": packet["parents"]["model_dataset"][
            "external_sha256"],
        "controller_review_record_sha256": sha256_file(review_record),
        "controller_review_claim": claim,
        "admission_slot": ADMISSION_PATH,
        "admission_slot_sha256": sha256_file(slot_path),
        "training_authorized": True,
        "report_rows_opened": 0,
        "report_open_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise TrainingRuntimeRefused(
                f"Stage-C training receipt field drift: {key}")
    if receipt.get("receipt_sha256") != self_hash(receipt, "receipt_sha256"):
        raise TrainingRuntimeRefused("Stage-C training receipt self-hash drift")
    return receipt


def _cell_slot_payload(packet: Mapping[str, object], *, index: int,
                       packet_sha256: str, receipt_sha256: str) -> dict:
    cell = packet["schedule"]["cells"][index]
    value = {
        "schema": CELL_ADMISSION_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "index": index,
        "cell_id": cell["cell_id"],
        "controller_packet_sha256": packet_sha256,
        "training_receipt_sha256": receipt_sha256,
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "consumed_even_if_training_or_publication_fails": True,
    }
    value["slot_sha256"] = self_hash(value, "slot_sha256")
    return value


def _snapshot_path(cell: Mapping[str, object], epoch: int) -> Path:
    return (REPO / str(cell["snapshot_dir"])
            / f"epoch-{epoch:02d}.pt").resolve()


def _snapshot_contract(packet: Mapping[str, object], cell: Mapping[str, object],
                       epoch: int, state_sha256: str) -> dict:
    value = MODEL.checkpoint_contract(
        surface=str(cell["surface"]), seed=int(cell["seed"]), epoch=epoch,
        curve_fraction=float(cell["curve_fraction"]),
        state_dict_sha256=state_sha256)
    value.update({
        "run_id": CTRL.RUN_ID,
        "cell_id": cell["cell_id"],
        "controller_packet_sha256": packet["external_sha256"],
        "model_dataset_sha256": packet["parents"]["model_dataset"][
            "external_sha256"],
        "report_rows_opened": 0,
    })
    return value


def run_cell(*, packet_path: Path, expected_packet_sha256: str,
             receipt_path: Path, expected_receipt_sha256: str,
             review_record: Path, index: int, out: Path) -> dict:
    packet, dataset = _packet(packet_path, expected_packet_sha256)
    packet["external_sha256"] = expected_packet_sha256
    _receipt(receipt_path, expected_receipt_sha256, packet,
             expected_packet_sha256, review_record)
    if not 0 <= index < CTRL.TRAINING_CELLS:
        raise TrainingRuntimeRefused("Stage-C training cell index drift")
    cell = packet["schedule"]["cells"][index]
    if out.resolve() != (REPO / str(cell["result"])).resolve():
        raise TrainingRuntimeRefused("Stage-C training cell output path drift")
    slot_path = _cell_slot_path(index)
    slot = _cell_slot_payload(
        packet, index=index, packet_sha256=expected_packet_sha256,
        receipt_sha256=expected_receipt_sha256)
    publish_exclusive(slot_path, slot)

    def heartbeat(value: Mapping[str, object]) -> None:
        print(json.dumps(value, sort_keys=True), file=sys.stderr, flush=True)

    surface = str(cell["surface"])
    result = TRAIN.train_curve(
        dataset["examples"]["DESIGN"][surface],
        dataset["examples"]["CALIB"][surface],
        surface=surface, seed=int(cell["seed"]),
        curve_fraction=float(cell["curve_fraction"]),
        max_epoch=max(MODEL.EPOCH_GRID), heartbeat=heartbeat)
    snapshots = []
    for snapshot in result["snapshots"]:
        contract = _snapshot_contract(
            packet, cell, int(snapshot["epoch"]),
            str(snapshot["model_state_sha256"]))
        published = TRAIN.publish_snapshot(
            _snapshot_path(cell, int(snapshot["epoch"])),
            state_dict=snapshot["state_dict"], contract=contract)
        snapshots.append({
            "epoch": snapshot["epoch"],
            "updates": snapshot["updates"],
            "mean_training_loss": snapshot["mean_training_loss"],
            "calib_metrics": snapshot["calib_metrics"],
            "model_state_sha256": snapshot["model_state_sha256"],
            "checkpoint_path": str(Path(published["path"]).relative_to(REPO)),
            "checkpoint_sha256": published["file_sha256"],
            "checkpoint_contract": contract,
        })
    payload = {
        "schema": CELL_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": expected_packet_sha256,
        "training_receipt_sha256": expected_receipt_sha256,
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "model_dataset_sha256": packet["parents"]["model_dataset"][
            "external_sha256"],
        "index": index,
        "cell_id": cell["cell_id"],
        "surface": surface,
        "seed": cell["seed"],
        "curve_fraction": cell["curve_fraction"],
        "design_states": result["design_states"],
        "full_design_states": result["full_design_states"],
        "calib_states": result["calib_states"],
        "prior_distribution": result["prior_distribution"],
        "hyperparameters": result["hyperparameters"],
        "snapshots": snapshots,
        "cell_admission_slot": str(slot_path.relative_to(REPO)),
        "cell_admission_slot_sha256": sha256_file(slot_path),
        "status": "COMPLETE",
        "report_rows_opened": 0,
        "report_open_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    payload["cell_sha256"] = self_hash(payload, "cell_sha256")
    # Reopen every mutable parent after expensive work and before publication.
    final_packet, final_dataset = _packet(
        packet_path, expected_packet_sha256)
    _receipt(receipt_path, expected_receipt_sha256, final_packet,
             expected_packet_sha256, review_record)
    if final_dataset != dataset:
        raise TrainingRuntimeRefused("Stage-C model dataset changed during cell")
    publish_exclusive(out, payload)
    return payload


def _validate_cell(
    value: Mapping[str, object], *, packet: Mapping[str, object],
    dataset: Mapping[str, object], index: int, packet_sha256: str,
    receipt_sha256: str,
) -> dict:
    cell = packet["schedule"]["cells"][index]
    expected_path = (REPO / str(cell["result"])).resolve()
    slot_path = _cell_slot_path(index)
    expected_slot = _cell_slot_payload(
        packet, index=index, packet_sha256=packet_sha256,
        receipt_sha256=receipt_sha256)
    if (value.get("schema") != CELL_SCHEMA
            or value.get("run_id") != CTRL.RUN_ID
            or value.get("git") != packet["producer"]["git"]
            or value.get("controller_packet_sha256") != packet_sha256
            or value.get("training_receipt_sha256") != receipt_sha256
            or value.get("schedule_sha256")
            != packet["schedule"]["schedule_sha256"]
            or value.get("model_dataset_sha256")
            != packet["parents"]["model_dataset"]["external_sha256"]
            or value.get("index") != index
            or value.get("cell_id") != cell["cell_id"]
            or value.get("surface") != cell["surface"]
            or value.get("seed") != cell["seed"]
            or value.get("curve_fraction") != cell["curve_fraction"]
            or value.get("full_design_states")
            != CTRL.EXPECTED_SURFACES["DESIGN"][cell["surface"]]
            or value.get("calib_states")
            != CTRL.EXPECTED_SURFACES["CALIB"][cell["surface"]]
            or value.get("status") != "COMPLETE"
            or value.get("report_rows_opened") != 0
            or value.get("report_open_authorized") is not False
            or value.get("strength_claim") is not False
            or value.get("production_promotion") is not False
            or value.get("production_deployment") is not False
            or value.get("cell_sha256") != self_hash(value, "cell_sha256")
            or not is_regular_unlinked(expected_path)
            or not is_regular_unlinked(slot_path)
            or load_json(slot_path) != expected_slot
            or value.get("cell_admission_slot")
            != str(slot_path.relative_to(REPO))
            or value.get("cell_admission_slot_sha256")
            != sha256_file(slot_path)):
        raise TrainingRuntimeRefused(
            f"Stage-C training cell {index} identity drift")
    expected_design = MODEL.curve_subset(
        dataset["examples"]["DESIGN"][cell["surface"]],
        float(cell["curve_fraction"]))
    if value.get("design_states") != len(expected_design):
        raise TrainingRuntimeRefused(
            f"Stage-C training cell {index} curve population drift")
    prior = TRAIN.state_balanced_prior(
        dataset["examples"]["DESIGN"][cell["surface"]])
    if value.get("prior_distribution") != prior:
        raise TrainingRuntimeRefused(
            f"Stage-C training cell {index} prior drift")
    if value.get("hyperparameters") != CTRL.cell_hyperparameters():
        raise TrainingRuntimeRefused(
            f"Stage-C training cell {index} hyperparameter drift")
    snapshots = value.get("snapshots")
    if (not isinstance(snapshots, list)
            or [row.get("epoch") for row in snapshots]
            != list(MODEL.EPOCH_GRID)):
        raise TrainingRuntimeRefused(
            f"Stage-C training cell {index} snapshot population drift")
    verified = []
    for snapshot in snapshots:
        epoch = int(snapshot["epoch"])
        expected_updates = math.ceil(
            len(expected_design) / TRAIN.BATCH_SIZE) * epoch
        losses = snapshot.get("mean_training_loss")
        if (set(snapshot) != {
                "epoch", "updates", "mean_training_loss", "calib_metrics",
                "model_state_sha256", "checkpoint_path",
                "checkpoint_sha256", "checkpoint_contract"}
                or snapshot.get("updates") != expected_updates
                or not isinstance(losses, dict)
                or set(losses) != {
                    "loss", "pairwise_bce", "label_ce", "outcome_ce"}
                or any(isinstance(value, bool)
                       or not isinstance(value, (int, float))
                       or not math.isfinite(float(value))
                       for value in losses.values())):
            raise TrainingRuntimeRefused(
                f"Stage-C training cell {index} diagnostic/work drift")
        path = _snapshot_path(cell, epoch)
        if (snapshot.get("checkpoint_path") != str(path.relative_to(REPO))
                or snapshot.get("checkpoint_sha256") != sha256_file(path)):
            raise TrainingRuntimeRefused(
                f"Stage-C training cell {index} checkpoint identity drift")
        contract = _snapshot_contract(
            packet, cell, epoch, str(snapshot.get("model_state_sha256")))
        if snapshot.get("checkpoint_contract") != contract:
            raise TrainingRuntimeRefused(
                f"Stage-C training cell {index} checkpoint contract drift")
        reopened = TRAIN.load_snapshot(path, expected_contract=contract)
        net = MODEL.StageCRankingOutcomeNet(hidden=TRAIN.HIDDEN)
        net.load_state_dict(reopened["state_dict"], strict=True)
        metrics = TRAIN.evaluate_model(
            net, dataset["examples"]["CALIB"][cell["surface"]],
            prior_distribution=prior)
        if snapshot.get("calib_metrics") != metrics:
            raise TrainingRuntimeRefused(
                f"Stage-C training cell {index} CALIB metric drift")
        verified.append({
            "epoch": epoch,
            "updates": expected_updates,
            "mean_training_loss": dict(losses),
            "checkpoint_path": snapshot["checkpoint_path"],
            "checkpoint_sha256": snapshot["checkpoint_sha256"],
            "model_state_sha256": snapshot["model_state_sha256"],
            "metrics": metrics,
        })
    return {
        "index": index,
        "cell_id": cell["cell_id"],
        "surface": cell["surface"],
        "seed": cell["seed"],
        "curve_fraction": cell["curve_fraction"],
        "design_states": value["design_states"],
        "full_design_states": value["full_design_states"],
        "calib_states": value["calib_states"],
        "cell_sha256": value["cell_sha256"],
        "snapshots": verified,
    }


def _curve_diagnostics(
        cells: Sequence[Mapping[str, object]]) -> list[dict]:
    rows = []
    for surface in MODEL.SURFACES:
        for fraction in MODEL.CURVE_FRACTIONS:
            population = [value for value in cells
                          if value["surface"] == surface
                          and value["curve_fraction"] == fraction]
            if ({value["seed"] for value in population}
                    != set(MODEL.TRAINING_SEEDS)
                    or len(population) != len(MODEL.TRAINING_SEEDS)
                    or len({value["design_states"] for value in population}) != 1
                    or len({value["calib_states"] for value in population}) != 1):
                raise TrainingRuntimeRefused(
                    "Stage-C curve diagnostic population drift")
            for epoch in MODEL.EPOCH_GRID:
                snapshots = [next(
                    item for item in value["snapshots"]
                    if item["epoch"] == epoch) for value in population]
                metrics = [value["metrics"] for value in snapshots]
                ranking = [float(value[
                    "ranking_improvement_vs_candidate0"]) for value in metrics]
                calibration = [float(value[
                    "outcome_nll_improvement_vs_prior"]) for value in metrics]
                outcome_action = [float(value[
                    "outcome_head_ranking_improvement_vs_candidate0"])
                    for value in metrics]
                rows.append({
                    "surface": surface,
                    "curve_fraction": fraction,
                    "design_states": population[0]["design_states"],
                    "calib_states": population[0]["calib_states"],
                    "epoch": epoch,
                    "seed_count": len(population),
                    "ranking_positive_seeds": sum(value > 0
                                                  for value in ranking),
                    "outcome_nll_positive_seeds": sum(
                        value > 0 for value in calibration),
                    "outcome_head_action_positive_seeds": sum(
                        value > 0 for value in outcome_action),
                    "median_ranking_improvement_vs_candidate0":
                        statistics.median(ranking),
                    "median_outcome_nll_improvement_vs_prior":
                        statistics.median(calibration),
                    "median_outcome_head_action_improvement_vs_candidate0":
                        statistics.median(outcome_action),
                    "mean_teacher_regret": statistics.fmean(float(value[
                        "mean_teacher_regret"]) for value in metrics),
                    "mean_outcome_nll": statistics.fmean(float(value[
                        "outcome_nll"]) for value in metrics),
                    "selection_eligible": fraction == 1.0,
                    "used_by_global_selector": fraction == 1.0,
                })
    expected = (len(MODEL.SURFACES) * len(MODEL.CURVE_FRACTIONS)
                * len(MODEL.EPOCH_GRID))
    if len(rows) != expected:
        raise TrainingRuntimeRefused(
            "Stage-C curve diagnostic row-count drift")
    return rows


def recompute_aggregate(*, packet_path: Path, expected_packet_sha256: str,
                        receipt_path: Path, expected_receipt_sha256: str,
                        review_record: Path,
                        cell_paths: Sequence[Path]) -> dict:
    """Reopen every cell/checkpoint and reconstruct the terminal aggregate."""
    packet, dataset = _packet(packet_path, expected_packet_sha256)
    packet["external_sha256"] = expected_packet_sha256
    _receipt(receipt_path, expected_receipt_sha256, packet,
             expected_packet_sha256, review_record)
    if len(cell_paths) != CTRL.TRAINING_CELLS:
        raise TrainingRuntimeRefused("Stage-C training aggregate cell-count drift")
    verified = []
    for index, path in enumerate(cell_paths):
        expected = (REPO / packet["schedule"]["cells"][index]["result"]).resolve()
        if path.resolve() != expected:
            raise TrainingRuntimeRefused(
                "Stage-C training aggregate cell path/order drift")
        value = load_json(path)
        checked = _validate_cell(
            value, packet=packet, dataset=dataset, index=index,
            packet_sha256=expected_packet_sha256,
            receipt_sha256=expected_receipt_sha256)
        checked["external_sha256"] = sha256_file(path)
        verified.append(checked)
    records = []
    for cell in verified:
        if cell["curve_fraction"] != 1.0:
            continue
        for snapshot in cell["snapshots"]:
            records.append({
                "split": "CALIB",
                "curve_fraction": 1.0,
                "epoch": snapshot["epoch"],
                "surface": cell["surface"],
                "seed": cell["seed"],
                "metrics": snapshot["metrics"],
            })
    selection = MODEL.select_global_epoch(records)
    curve_diagnostics = _curve_diagnostics(verified)
    selected = []
    capability = selection["selected_capability"]
    if capability is not None:
        for cell in verified:
            if (cell["curve_fraction"] != 1.0
                    or cell["surface"] != capability["surface"]):
                continue
            snapshot = next(value for value in cell["snapshots"]
                            if value["epoch"] == capability["epoch"])
            selected.append({
                "surface": cell["surface"], "seed": cell["seed"],
                "head": capability["head"],
                "epoch": snapshot["epoch"],
                "checkpoint_path": snapshot["checkpoint_path"],
                "checkpoint_sha256": snapshot["checkpoint_sha256"],
                "model_state_sha256": snapshot["model_state_sha256"],
            })
    payload = {
        "schema": AGGREGATE_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": expected_packet_sha256,
        "training_receipt_sha256": expected_receipt_sha256,
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "model_dataset_sha256": packet["parents"]["model_dataset"][
            "external_sha256"],
        "cells": [{key: value for key, value in cell.items()
                   if key != "snapshots"} for cell in verified],
        "cell_count": len(verified),
        "calib_metrics_recomputed_from_checkpoints": True,
        "selection": selection,
        "curve_diagnostics": curve_diagnostics,
        "curve_diagnostics_used_for_selection": False,
        "smaller_curves_are_diagnostic_only": True,
        "selected_ensemble": selected,
        "decision": selection["decision"],
        "report_packet_review_authorized":
            selection["decision"]
            == "FREEZE_SINGLE_CAPABILITY_FOR_REPORT_REVIEW",
        "report_rows_opened": 0,
        "report_open_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    if (payload["report_packet_review_authorized"]
            and len(selected) != len(MODEL.TRAINING_SEEDS)):
        raise TrainingRuntimeRefused("Stage-C selected ensemble geometry drift")
    payload["aggregate_sha256"] = self_hash(payload, "aggregate_sha256")
    final_packet, final_dataset = _packet(packet_path, expected_packet_sha256)
    _receipt(receipt_path, expected_receipt_sha256, final_packet,
             expected_packet_sha256, review_record)
    if final_dataset != dataset:
        raise TrainingRuntimeRefused(
            "Stage-C model dataset changed during aggregate")
    return payload


def aggregate(*, packet_path: Path, expected_packet_sha256: str,
              receipt_path: Path, expected_receipt_sha256: str,
              review_record: Path, cell_paths: Sequence[Path],
              out: Path) -> dict:
    if out.resolve() != _expected_aggregate_path():
        raise TrainingRuntimeRefused("Stage-C training aggregate path drift")
    payload = recompute_aggregate(
        packet_path=packet_path,
        expected_packet_sha256=expected_packet_sha256,
        receipt_path=receipt_path,
        expected_receipt_sha256=expected_receipt_sha256,
        review_record=review_record,
        cell_paths=cell_paths)
    publish_exclusive(out, payload)
    return payload


def _identity_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--expected-git", required=True)
    parser.add_argument("--controller-packet", required=True)
    parser.add_argument("--expected-controller-packet-sha256", required=True)
    parser.add_argument("--controller-review-record", required=True)


def _receipt_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--training-receipt", required=True)
    parser.add_argument("--expected-training-receipt-sha256", required=True)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    admit_parser = commands.add_parser("admit")
    _identity_args(admit_parser)
    admit_parser.add_argument("--out", required=True)
    cell_parser = commands.add_parser("run-cell")
    _identity_args(cell_parser)
    _receipt_args(cell_parser)
    cell_parser.add_argument("--cell-index", type=int, required=True)
    cell_parser.add_argument("--out", required=True)
    aggregate_parser = commands.add_parser("aggregate")
    _identity_args(aggregate_parser)
    _receipt_args(aggregate_parser)
    aggregate_parser.add_argument("--cells", nargs="+", required=True)
    aggregate_parser.add_argument("--out", required=True)
    return root


def main() -> int:
    args = parser().parse_args()
    if _git("rev-parse", "HEAD") != args.expected_git:
        raise TrainingRuntimeRefused("Stage-C training expected Git drift")
    common = {
        "packet_path": Path(args.controller_packet).resolve(),
        "expected_packet_sha256": args.expected_controller_packet_sha256,
        "review_record": Path(args.controller_review_record).resolve(),
    }
    if args.command == "admit":
        value = admit(**common, out=Path(args.out).resolve())
    elif args.command == "run-cell":
        value = run_cell(
            **common,
            receipt_path=Path(args.training_receipt).resolve(),
            expected_receipt_sha256=args.expected_training_receipt_sha256,
            index=args.cell_index, out=Path(args.out).resolve())
    else:
        value = aggregate(
            **common,
            receipt_path=Path(args.training_receipt).resolve(),
            expected_receipt_sha256=args.expected_training_receipt_sha256,
            cell_paths=[Path(value).resolve() for value in args.cells],
            out=Path(args.out).resolve())
    print(json.dumps({
        "status": value.get("status", value.get("decision", "ADMITTED")),
        "sha256": sha256_bytes(canonical_json(value)),
        "report_open_authorized": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TrainingRuntimeRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        raise SystemExit(2)
