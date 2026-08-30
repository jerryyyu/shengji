from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v2_audit_attempt import (
    build_audit_attempt_bytes,
)
from shengji.rl.world_afterstate_v2_terminal_controller import (
    AUDIT_COHORTS,
    COHORT_LABELS,
    DOSE_LABELS,
    EarlyTerminalInputPathsV2,
    TerminalInputPathsV2,
    WorldAfterstateV2TerminalControllerError,
    build_early_route_evidence_bytes,
    run_terminal_v2,
    verify_terminal_artifact_v2,
)
from shengji.rl import world_afterstate_v2_terminal_controller as terminal
from test_world_afterstate_v2_result import _p0


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def _inputs(tmp_path: Path) -> TerminalInputPathsV2:
    path = tmp_path / "input.json"
    freeze = _digest("freeze")
    admission = _digest("admission")
    audit_attempt = tmp_path / "audit-attempt.json"
    audit_attempt.write_bytes(build_audit_attempt_bytes(
        freeze_sha256=freeze, admission_sha256=admission,
        preflight={"preflight_relative_path": "audit-preflight.json",
                   "preflight_sha256": _digest("preflight")}))
    audit_attempt.chmod(0o400)
    return TerminalInputPathsV2(
        freeze_sha256=freeze, admission_sha256=admission,
        audit_population_root=tmp_path / "population",
        audit_population_namespace_sha256=_digest("namespace"),
        audit_population_tier="D256", audit_attempt_path=audit_attempt,
        continuation_root=tmp_path / "continuation",
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


def test_preflight_requires_the_shared_pipeline_audit_attempt(
        tmp_path, monkeypatch):
    inputs = _inputs(tmp_path)
    inputs.audit_attempt_path.chmod(0o600)
    inputs.audit_attempt_path.write_bytes(build_audit_attempt_bytes(
        freeze_sha256=inputs.freeze_sha256,
        admission_sha256=_digest("different-admission"),
        preflight={"preflight_relative_path": "audit-preflight.json"}))
    inputs.audit_attempt_path.chmod(0o400)
    monkeypatch.setattr(
        terminal, "_preflight_population",
        lambda *_: (_ for _ in ()).throw(
            AssertionError("population must not open before marker validation")))
    with pytest.raises(WorldAfterstateV2TerminalControllerError,
                       match="audit attempt"):
        terminal._preflight(inputs)


def test_attempt_is_published_before_derivation_and_failure_consumes_slot(
        monkeypatch, tmp_path):
    inputs = _inputs(tmp_path)
    digest = _digest("sealed")
    preflight = {
        "audit_attempt": {
            "attempt_sha256": _digest("pipeline-audit-attempt")},
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
    assert "published_before_audit_labels" not in attempt
    assert attempt["audit_opened_count"] == 1
    assert attempt["audit_attempt_sha256"] == _digest(
        "pipeline-audit-attempt")
    with pytest.raises(WorldAfterstateV2TerminalControllerError,
                       match="slot occupied"):
        run_terminal_v2(tmp_path / "run", inputs)


def test_early_p0_stop_seals_and_immediately_reconstructs_without_audit(
        tmp_path):
    freeze = _digest("early-freeze")
    admission = _digest("early-admission")
    route = "STOP_NO_REPRODUCIBLE_VALUE_LABEL"
    route_path = tmp_path / "early-route.json"
    route_path.write_bytes(build_early_route_evidence_bytes(
        freeze_sha256=freeze, admission_sha256=admission,
        source_stage="p0"))
    route_path.chmod(0o400)
    p0_path = tmp_path / "p0.json"
    p0_path.write_bytes(canonical_json_bytes(_p0(
        sibling_advantage_correlation_bootstrap_lower_ppm=0,
        statistical_gates_passed=False, decision=route)))
    p0_path.chmod(0o400)
    inputs = EarlyTerminalInputPathsV2(
        freeze_sha256=freeze, admission_sha256=admission,
        expected_route=route, route_evidence_path=route_path,
        p0_report_path=p0_path)
    receipt = run_terminal_v2(tmp_path / "run", inputs)
    assert receipt["matched"] is True
    terminal_root = tmp_path / "run" / "terminal"
    attempt = json.loads((terminal_root / "attempt.json").read_bytes())
    assert attempt["audit_opened_count"] == 0
    assert "published_before_audit_labels" not in attempt
    result = json.loads((terminal_root / "terminal.json").read_bytes())
    assert result["decision"] == route
    assert verify_terminal_artifact_v2(terminal_root, inputs)["matched"] is True
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
