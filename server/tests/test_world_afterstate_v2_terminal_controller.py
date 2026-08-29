from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v2_terminal_controller import (
    AUDIT_COHORTS,
    COHORT_LABELS,
    DOSE_LABELS,
    TerminalInputPathsV2,
    WorldAfterstateV2TerminalControllerError,
    run_terminal_v2,
)
from shengji.rl import world_afterstate_v2_terminal_controller as terminal


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def _inputs(tmp_path: Path) -> TerminalInputPathsV2:
    path = tmp_path / "input.json"
    return TerminalInputPathsV2(
        freeze_sha256=_digest("freeze"), admission_sha256=_digest("admission"),
        audit_population_root=tmp_path / "population",
        audit_population_namespace_sha256=_digest("namespace"),
        audit_population_tier="D256", continuation_root=tmp_path / "continuation",
        prediction_manifest_paths=tuple(
            (label, path) for label in COHORT_LABELS),
        cohort_manifest_paths=tuple((label, path) for label in COHORT_LABELS),
        checkpoint_roots=tuple(
            (label, tmp_path / "checkpoints") for label in COHORT_LABELS),
        p0_report_path=path, optimizer_canary_path=path,
        precision_select_result_path=path, model_selector_power_path=path,
        prior_path=path,
        control_dose_receipt_paths=tuple((label, path) for label in DOSE_LABELS),
    )


def test_input_contract_rejects_dropped_or_reordered_populations(tmp_path):
    inputs = _inputs(tmp_path)
    with pytest.raises(WorldAfterstateV2TerminalControllerError, match="order"):
        inputs.__class__(**{
            **inputs.__dict__,
            "prediction_manifest_paths": (
                inputs.prediction_manifest_paths[1],
                inputs.prediction_manifest_paths[0],
                *inputs.prediction_manifest_paths[2:],
            ),
        }).validate_shape()
    with pytest.raises(WorldAfterstateV2TerminalControllerError, match="population"):
        inputs.__class__(**{
            **inputs.__dict__,
            "control_dose_receipt_paths": inputs.control_dose_receipt_paths[:-1],
        }).validate_shape()
    with pytest.raises(WorldAfterstateV2TerminalControllerError, match="order"):
        inputs.__class__(**{
            **inputs.__dict__,
            "checkpoint_roots": (
                inputs.checkpoint_roots[1], inputs.checkpoint_roots[0],
                *inputs.checkpoint_roots[2:],
            ),
        }).validate_shape()


def test_attempt_is_published_before_derivation_and_failure_consumes_slot(
        monkeypatch, tmp_path):
    inputs = _inputs(tmp_path)
    digest = _digest("sealed")
    preflight = {
        "population": {"manifest_sha256": digest, "population_sha256": digest},
        "continuation_sha": digest,
        "predictions": tuple((label, {"manifest_sha256": _digest(label)})
                              for label in COHORT_LABELS),
        "cohorts": tuple((label, {"manifest_sha256": _digest("cohort:" + label)})
                          for label in COHORT_LABELS),
        "checkpoint_ids": tuple((label, _digest("checkpoint:" + label))
                                 for label in COHORT_LABELS),
    }
    observed = []
    monkeypatch.setattr(
        "shengji.rl.world_afterstate_v2_terminal_controller._preflight",
        lambda _inputs: preflight)

    def fail(_inputs, _preflight, _attempt_sha):
        attempt = tmp_path / "run" / "terminal.partial" / "attempt.json"
        observed.append((attempt.exists(), attempt.stat().st_mode & 0o777))
        raise RuntimeError("derivation sentinel")

    monkeypatch.setattr(
        "shengji.rl.world_afterstate_v2_terminal_controller._derive_from_inputs",
        fail)
    with pytest.raises(RuntimeError, match="derivation sentinel"):
        run_terminal_v2(tmp_path / "run", inputs)
    assert observed == [(True, 0o400)]
    partial = tmp_path / "run" / "terminal.partial"
    assert (partial / "attempt.json").is_file()
    attempt = json.loads((partial / "attempt.json").read_bytes())
    assert attempt["published_before_audit_labels"] is True
    with pytest.raises(WorldAfterstateV2TerminalControllerError,
                       match="slot occupied"):
        run_terminal_v2(tmp_path / "run", inputs)


def test_preflight_wiring_reopens_all_six_checkpoint_aggregates(
        monkeypatch, tmp_path):
    (tmp_path / "checkpoints").mkdir()
    common = _inputs(tmp_path)
    predictions = tuple((label, tmp_path / f"prediction-{index}.json")
                        for index, label in enumerate(COHORT_LABELS))
    cohorts = tuple((label, tmp_path / f"cohort-{index}.json")
                    for index, label in enumerate(COHORT_LABELS))
    inputs = common.__class__(**{
        **common.__dict__, "prediction_manifest_paths": predictions,
        "cohort_manifest_paths": cohorts,
        "p0_report_path": tmp_path / "p0.json",
        "optimizer_canary_path": tmp_path / "canary.json",
        "precision_select_result_path": tmp_path / "precision.json",
        "model_selector_power_path": tmp_path / "power.json",
        "prior_path": tmp_path / "prior.json",
        "control_dose_receipt_paths": tuple(
            (label, tmp_path / f"dose-{label}.json") for label in DOSE_LABELS),
    })
    digest = _digest("preflight")
    monkeypatch.setattr(terminal, "_preflight_population", lambda *_: (
        {"rows": [{"deal_sha256": digest}], "population_sha256": digest,
         "manifest_sha256": digest}, b"population\n"))
    monkeypatch.setattr(terminal, "_preflight_continuation_manifest",
                        lambda *_: (digest, b"continuations\n"))
    monkeypatch.setattr(terminal, "validate_prediction_population_manifest_v2",
                        lambda _value: None)
    monkeypatch.setattr(terminal, "validate_cohort_manifest", lambda _value: None)
    monkeypatch.setattr(terminal, "validate_precision_label", lambda _value: None)
    monkeypatch.setattr(terminal, "validate_control_evidence", lambda _value: None)
    for name in ("reopen_optimizer_canary_v2", "reopen_evaluation_result_v2",
                 "reopen_model_selector_power_v2", "reopen_jeffreys_prior_v2"):
        monkeypatch.setattr(terminal, name, lambda value: value)

    prediction_values = {}
    cohort_values = {}
    for index, ((label, control, block), (_, prediction_path),
                (_, cohort_path)) in enumerate(zip(
                    AUDIT_COHORTS, predictions, cohorts, strict=True)):
        prediction_values[prediction_path] = {
            "split": "audit", "control_name": control, "seed_block": block,
            "manifest_sha256": _digest(f"prediction:{index}")}
        cohort_values[cohort_path] = {
            "cohort_name": control, "seed_block": block,
            "freeze_sha256": inputs.freeze_sha256,
            "config_sha256": _digest(f"config:{index}"),
            "training_population_sha256": _digest(f"population:{index}"),
            "common_epoch": {"selected_epoch": 1},
            "common_epoch_sha256": _digest(f"common:{index}"),
            "members": [{"epoch_receipts": [{
                "schedule_sha256": _digest(f"schedule:{index}:{member}")}]} 
                        for member in range(4)],
            "manifest_sha256": _digest(f"cohort:{index}"),
        }
    doses = {path: {"control_name": {
        "association": "action-association-permutation",
        "label": "label-permutation",
        "world": "complete-world-shuffle",
    }[label]} for label, path in inputs.control_dose_receipt_paths}

    checkpoint_raws = {}
    calls = []
    for index, (label, control, block) in enumerate(AUDIT_COHORTS):
        path = terminal.checkpoint_manifest_path(
            inputs.checkpoint_roots[index][1], control, block, 1)
        checkpoint_raws[path] = f"checkpoint-manifest-{index}\n".encode("ascii")

    def read_json(path, _label):
        if path in prediction_values:
            return prediction_values[path], f"prediction-{path.name}\n".encode()
        if path in cohort_values:
            return cohort_values[path], f"cohort-{path.name}\n".encode()
        if path in checkpoint_raws:
            return {}, checkpoint_raws[path]
        if path in doses:
            return doses[path], f"dose-{path.name}\n".encode()
        return {}, f"typed-{path.name}\n".encode()

    def reopen(root, **kwargs):
        calls.append((root, kwargs))
        return tuple((object(), {}) for _ in range(4))

    monkeypatch.setattr(terminal, "_read_json", read_json)
    monkeypatch.setattr(terminal, "reopen_checkpoint_manifest", reopen)
    preflight = terminal._preflight(inputs)
    assert len(calls) == len(COHORT_LABELS)
    assert tuple(label for label, _ in preflight["checkpoint_ids"]) == COHORT_LABELS
    assert tuple(digest for _, digest in preflight["checkpoint_ids"]) == tuple(
        hashlib.sha256(checkpoint_raws[
            terminal.checkpoint_manifest_path(
                inputs.checkpoint_roots[index][1], control, block, 1)]).hexdigest()
        for index, (_label, control, block) in enumerate(AUDIT_COHORTS))
