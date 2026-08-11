from __future__ import annotations

import copy
import math
from pathlib import Path

import pytest

import teacher_stage_c_training_runtime as RUNTIME
from shengji.rl import stage_c_model as MODEL


def _packet() -> dict:
    return {
        "producer": {"git": "a" * 40},
        "schedule": RUNTIME.CTRL.build_schedule(),
        "parents": {"model_dataset": {"external_sha256": "b" * 64}},
        "packet_sha256": "c" * 64,
    }


def _dataset() -> dict:
    return {"examples": {
        "DESIGN": {"play": [], "bury": []},
        "CALIB": {"play": [], "bury": []},
    }}


def _metrics(*, good: bool) -> dict:
    return {
        "ranking_improvement_vs_candidate0": 0.2 if good else -0.1,
        "outcome_head_ranking_improvement_vs_candidate0":
            0.1 if good else -0.1,
        "outcome_head_mean_teacher_regret": 0.2 if good else 0.3,
        "outcome_nll_improvement_vs_prior": 0.1 if good else -0.1,
        "mean_teacher_regret": 0.1 if good else 0.3,
        "outcome_nll": 1.0 if good else 2.0,
    }


def test_cell_and_global_admission_slots_are_distinct() -> None:
    packet = _packet()
    values = [RUNTIME._cell_slot_payload(
        packet, index=index, packet_sha256="d" * 64,
        receipt_sha256="e" * 64)
        for index in range(RUNTIME.CTRL.TRAINING_CELLS)]
    assert len({value["slot_sha256"] for value in values}) == 48
    assert [value["index"] for value in values] == list(range(48))
    assert all(value["consumed_even_if_training_or_publication_fails"] is True
               for value in values)


@pytest.mark.parametrize(
    "occupied",
    ("slot", "slot.partial", "receipt", "receipt.partial"),
)
def test_admission_preflights_slot_and_receipt_before_opening_packet(
        monkeypatch, tmp_path: Path, occupied: str) -> None:
    monkeypatch.setattr(RUNTIME, "REPO", tmp_path)
    slot = (tmp_path / RUNTIME.ADMISSION_PATH).resolve()
    receipt = (tmp_path / RUNTIME.RECEIPT_PATH).resolve()
    paths = {
        "slot": slot,
        "slot.partial": Path(str(slot) + ".partial"),
        "receipt": receipt,
        "receipt.partial": Path(str(receipt) + ".partial"),
    }
    paths[occupied].parent.mkdir(parents=True, exist_ok=True)
    paths[occupied].write_text("occupied\n")
    monkeypatch.setattr(
        RUNTIME, "_packet",
        lambda *args, **kwargs: pytest.fail(
            "reviewed packet opened before admission-pair preflight"))

    with pytest.raises(RUNTIME.TrainingRuntimeRefused, match="existing output"):
        RUNTIME.admit(
            packet_path=tmp_path / "packet.json",
            expected_packet_sha256="d" * 64,
            review_record=tmp_path / "review.md",
            out=receipt)
    if occupied not in {"slot", "slot.partial"}:
        assert not slot.exists()
        assert not Path(str(slot) + ".partial").exists()


def test_admission_publishes_a_reopenable_slot_receipt_pair(
        monkeypatch, tmp_path: Path) -> None:
    packet = _packet()
    monkeypatch.setattr(RUNTIME, "REPO", tmp_path)
    monkeypatch.setattr(
        RUNTIME, "_packet", lambda *args, **kwargs: (packet, _dataset()))
    claim = {"verdict": "PASS"}
    monkeypatch.setattr(
        RUNTIME, "_review_claim", lambda *args, **kwargs: claim)
    review = tmp_path / "review.md"
    review.write_text("reviewed\n")
    receipt_path = (tmp_path / RUNTIME.RECEIPT_PATH).resolve()

    receipt = RUNTIME.admit(
        packet_path=tmp_path / "packet.json",
        expected_packet_sha256="d" * 64,
        review_record=review, out=receipt_path)
    slot_path = (tmp_path / RUNTIME.ADMISSION_PATH).resolve()

    assert RUNTIME.is_regular_unlinked(slot_path)
    assert RUNTIME.is_regular_unlinked(receipt_path)
    assert receipt["admission_slot_sha256"] == RUNTIME.sha256_file(slot_path)
    assert receipt["receipt_sha256"] \
        == RUNTIME.self_hash(receipt, "receipt_sha256")
    assert RUNTIME._receipt(
        receipt_path, RUNTIME.sha256_file(receipt_path), packet,
        "d" * 64, review) == receipt


def test_run_cell_publishes_all_frozen_epochs_without_report(
        monkeypatch, tmp_path) -> None:
    packet = _packet()
    dataset = _dataset()
    monkeypatch.setattr(RUNTIME, "REPO", tmp_path)
    monkeypatch.setattr(
        RUNTIME, "_packet", lambda *args, **kwargs: (packet, dataset))
    monkeypatch.setattr(RUNTIME, "_receipt", lambda *args, **kwargs: {})
    state_sha = "f" * 64
    monkeypatch.setattr(
        RUNTIME.TRAIN, "train_curve",
        lambda *args, **kwargs: {
            "design_states": 10, "full_design_states": 20,
            "calib_states": 5, "prior_distribution": [0.125] * 8,
            "hyperparameters": {"device": "cpu"},
            "snapshots": [{
                "epoch": epoch, "updates": epoch,
                "mean_training_loss": {"loss": 1.0},
                "calib_metrics": _metrics(good=epoch == 8),
                "model_state_sha256": state_sha, "state_dict": {},
            } for epoch in MODEL.EPOCH_GRID],
        })
    monkeypatch.setattr(
        RUNTIME.TRAIN, "publish_snapshot",
        lambda path, **kwargs: {
            "path": str(path), "file_sha256": "1" * 64,
            "model_state_sha256": state_sha,
        })
    cell = packet["schedule"]["cells"][0]
    # The runtime cross-checks these exact counts against the frozen schedule.
    cell["design_states"] = 20
    cell["calib_states"] = 5
    out = tmp_path / cell["result"]
    value = RUNTIME.run_cell(
        packet_path=tmp_path / "packet.json",
        expected_packet_sha256="d" * 64,
        receipt_path=tmp_path / "receipt.json",
        expected_receipt_sha256="e" * 64,
        review_record=tmp_path / "review.md", index=0, out=out)
    assert [row["epoch"] for row in value["snapshots"]] \
        == list(MODEL.EPOCH_GRID)
    assert value["report_rows_opened"] == 0
    assert value["report_open_authorized"] is False
    assert out.is_file()


def test_aggregate_uses_only_full_curves_and_freezes_one_eight_model_capability(
        monkeypatch, tmp_path) -> None:
    packet = _packet()
    dataset = _dataset()
    monkeypatch.setattr(RUNTIME, "REPO", tmp_path)
    monkeypatch.setattr(
        RUNTIME, "_packet", lambda *args, **kwargs: (packet, dataset))
    monkeypatch.setattr(RUNTIME, "_receipt", lambda *args, **kwargs: {})
    monkeypatch.setattr(RUNTIME, "load_json", lambda path: {})
    monkeypatch.setattr(RUNTIME, "sha256_file", lambda path: "9" * 64)

    def validate(value, *, index, **kwargs):
        cell = packet["schedule"]["cells"][index]
        return {
            "index": index, "cell_id": cell["cell_id"],
            "surface": cell["surface"], "seed": cell["seed"],
            "loss_recipe": MODEL.LOSS_RECIPES[0],
            "curve_fraction": cell["curve_fraction"],
            "design_states": int(cell["design_states"]
                                 * cell["curve_fraction"]),
            "full_design_states": cell["design_states"],
            "calib_states": cell["calib_states"],
            "cell_sha256": f"{index + 1:064x}",
            "snapshots": [{
                "epoch": epoch,
                "checkpoint_path": f"checkpoint-{index}-{epoch}.pt",
                "checkpoint_sha256": f"{index + epoch + 1:064x}",
                "model_state_sha256": f"{index + epoch + 101:064x}",
                "metrics": _metrics(good=epoch == 8),
            } for epoch in MODEL.EPOCH_GRID],
        }

    monkeypatch.setattr(RUNTIME, "_validate_cell", validate)
    paths = [tmp_path / cell["result"]
             for cell in packet["schedule"]["cells"]]
    out = tmp_path / RUNTIME.AGGREGATE_PATH
    value = RUNTIME.aggregate(
        packet_path=tmp_path / "packet.json",
        expected_packet_sha256="d" * 64,
        receipt_path=tmp_path / "receipt.json",
        expected_receipt_sha256="e" * 64,
        review_record=tmp_path / "review.md", cell_paths=paths, out=out)
    assert value["decision"] \
        == "FREEZE_SINGLE_CAPABILITY_FOR_REPORT_REVIEW"
    assert value["selection"]["selected_epoch"] == 8
    assert value["selection"]["selected_capability"]["surface"] == "play"
    assert value["selection"]["selected_capability"]["head"] == "ranking"
    assert len(value["selected_ensemble"]) == 8
    assert all(row["epoch"] == 8 for row in value["selected_ensemble"])
    assert all(row["surface"] == "play" and row["head"] == "ranking"
               for row in value["selected_ensemble"])
    assert len(value["curve_diagnostics"]) == 36
    assert sum(row["selection_eligible"]
               for row in value["curve_diagnostics"]) == 12
    assert all(row["used_by_global_selector"] == row["selection_eligible"]
               for row in value["curve_diagnostics"])
    assert value["curve_diagnostics_used_for_selection"] is False
    assert value["report_rows_opened"] == 0
    assert value["report_open_authorized"] is False


def test_snapshot_contract_binds_dataset_packet_and_cell() -> None:
    packet = _packet()
    packet["external_sha256"] = "d" * 64
    cell = packet["schedule"]["cells"][0]
    value = RUNTIME._snapshot_contract(packet, cell, 8, "f" * 64)
    assert value["controller_packet_sha256"] == "d" * 64
    assert value["model_dataset_sha256"] == "b" * 64
    assert value["cell_id"] == cell["cell_id"]
    assert value["play_and_bury_share_weights"] is False


def test_cell_validator_refuses_work_loss_and_hyperparameter_forgery(
        monkeypatch, tmp_path) -> None:
    packet = _packet()
    packet["external_sha256"] = "d" * 64
    cell = packet["schedule"]["cells"][0]
    design_count = math.ceil(cell["design_states"] * cell["curve_fraction"])
    dataset = {"examples": {
        "DESIGN": {"play": [{}] * cell["design_states"], "bury": []},
        "CALIB": {"play": [{}] * cell["calib_states"], "bury": []},
    }}
    monkeypatch.setattr(RUNTIME, "REPO", tmp_path)
    monkeypatch.setattr(RUNTIME.MODEL, "curve_subset",
                        lambda values, fraction: list(values[:design_count]))
    monkeypatch.setattr(RUNTIME.TRAIN, "state_balanced_prior",
                        lambda values: [0.125] * 8)
    monkeypatch.setattr(RUNTIME, "is_regular_unlinked", lambda path: True)
    slot = RUNTIME._cell_slot_payload(
        packet, index=0, packet_sha256="d" * 64,
        receipt_sha256="e" * 64)
    monkeypatch.setattr(RUNTIME, "load_json", lambda path: slot)
    monkeypatch.setattr(RUNTIME, "sha256_file", lambda path: "9" * 64)
    monkeypatch.setattr(RUNTIME.TRAIN, "load_snapshot",
                        lambda *args, **kwargs: {"state_dict": {}})

    class _Net:
        def load_state_dict(self, *args, **kwargs):
            return None

    monkeypatch.setattr(RUNTIME.MODEL, "StageCRankingOutcomeNet",
                        lambda **kwargs: _Net())
    monkeypatch.setattr(RUNTIME.TRAIN, "evaluate_model",
                        lambda *args, **kwargs: _metrics(good=True))
    slot_path = RUNTIME._cell_slot_path(0)
    value = {
        "schema": RUNTIME.CELL_SCHEMA,
        "run_id": RUNTIME.CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": "d" * 64,
        "training_receipt_sha256": "e" * 64,
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "model_dataset_sha256": "b" * 64,
        "index": 0,
        "cell_id": cell["cell_id"],
        "surface": cell["surface"],
        "loss_recipe": MODEL.LOSS_RECIPES[0],
        "seed": cell["seed"],
        "curve_fraction": cell["curve_fraction"],
        "design_states": design_count,
        "full_design_states": cell["design_states"],
        "calib_states": cell["calib_states"],
        "prior_distribution": [0.125] * 8,
        "hyperparameters": RUNTIME.CTRL.cell_hyperparameters(),
        "snapshots": [],
        "cell_admission_slot": str(slot_path.relative_to(tmp_path)),
        "cell_admission_slot_sha256": "9" * 64,
        "status": "COMPLETE",
        "report_rows_opened": 0,
        "report_open_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    for epoch in MODEL.EPOCH_GRID:
        state_sha = f"{epoch:064x}"
        value["snapshots"].append({
            "epoch": epoch,
            "updates": math.ceil(design_count / RUNTIME.TRAIN.BATCH_SIZE)
            * epoch,
            "mean_training_loss": {
                "loss": 1.0, "pairwise_bce": 0.2,
                "candidate0_advantage_huber": 0.4,
                "label_ce": 0.3, "outcome_ce": 0.5,
            },
            "calib_metrics": _metrics(good=True),
            "model_state_sha256": state_sha,
            "checkpoint_path": str(
                RUNTIME._snapshot_path(cell, epoch).relative_to(tmp_path)),
            "checkpoint_sha256": "9" * 64,
            "checkpoint_contract": RUNTIME._snapshot_contract(
                packet, cell, epoch, state_sha),
        })
    value["cell_sha256"] = RUNTIME.self_hash(value, "cell_sha256")
    checked = RUNTIME._validate_cell(
        value, packet=packet, dataset=dataset, index=0,
        packet_sha256="d" * 64, receipt_sha256="e" * 64)
    assert checked["design_states"] == design_count

    for mutation in ("updates", "loss", "hyperparameters"):
        forged = copy.deepcopy(value)
        if mutation == "updates":
            forged["snapshots"][0]["updates"] += 1
        elif mutation == "loss":
            forged["snapshots"][0]["mean_training_loss"]["loss"] = math.nan
        else:
            forged["hyperparameters"]["learning_rate"] *= 2
        forged["cell_sha256"] = RUNTIME.self_hash(forged, "cell_sha256")
        with pytest.raises(RUNTIME.TrainingRuntimeRefused):
            RUNTIME._validate_cell(
                forged, packet=packet, dataset=dataset, index=0,
                packet_sha256="d" * 64, receipt_sha256="e" * 64)


def test_json_publication_cannot_overwrite_raced_destination(
        monkeypatch, tmp_path) -> None:
    path = tmp_path / "result.json"
    real_link = RUNTIME.os.link

    def _raced_link(source, destination, *, follow_symlinks):
        path.write_bytes(b"other publisher")
        return real_link(
            source, destination, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(RUNTIME.os, "link", _raced_link)
    with pytest.raises(RUNTIME.TrainingRuntimeRefused, match="raced"):
        RUNTIME.publish_exclusive(path, {"value": 1})
    assert path.read_bytes() == b"other publisher"
    assert (tmp_path / "result.json.partial").is_file()
