from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v2_prediction_artifacts import (
    prediction_population_manifest_path,
)
from shengji.rl.world_afterstate_v2_rehearsal import (
    AUTHORITY, SOURCE_IDENTITY, STOP_PATHS, RehearsalError, RehearsalStage,
    build_non_scientific_rehearsal_v2, dispatch_stage,
    reopen_non_scientific_rehearsal, run_non_scientific_rehearsal_v2,
)


def _run(tmp_path: Path):
    output = tmp_path / "artifacts"
    receipt = tmp_path / "receipt.json"
    value = run_non_scientific_rehearsal_v2(output, receipt)
    return output, receipt, value


def test_happy_path_reopens_score_free_artifacts_and_receipt(tmp_path: Path):
    output, receipt, value = _run(tmp_path)
    reopened = reopen_non_scientific_rehearsal(output, receipt=receipt)
    assert reopened.payload == value.payload
    assert value.body["non_scientific"] is True
    assert value.body["score_free"] is True
    assert value.body["scientific"] is False
    assert value.body["stop_before"] == "audit-attempt"
    assert value.body["progress_event_count"] >= 5
    assert all(item is False for item in AUTHORITY.values())
    assert all(not (output / path).exists() for path in STOP_PATHS)
    population = (output / "population" / "score-free-material.json").read_bytes()
    assert b"outcome" not in population
    assert b"target" not in population


def test_target_audit_outcome_and_terminal_producers_are_never_called(
        monkeypatch: pytest.MonkeyPatch):
    # These are deliberately broad sentinels: the rehearsal must not cross
    # any scientific label, continuation, audit-attempt, or terminal seam.
    import shengji.rl.world_afterstate_v2_audit_attempt as attempt
    import shengji.rl.world_afterstate_v2_label as label
    import shengji.rl.world_afterstate_v2_terminal_controller as terminal

    def fail(*_args, **_kwargs):
        raise AssertionError("scientific constructor invoked")

    monkeypatch.setattr(attempt, "build_audit_attempt_bytes", fail)
    monkeypatch.setattr(label, "evaluate_precision_label", fail)
    monkeypatch.setattr(label, "ContinuationOutcomeV2", fail)
    monkeypatch.setattr(terminal, "run_terminal_v2", fail)
    build = build_non_scientific_rehearsal_v2()
    assert len(build.prediction_manifest["predictions"]) == 16


def test_typed_dispatch_and_tampered_or_symlink_artifacts_refuse(tmp_path: Path):
    with pytest.raises(RehearsalError):
        dispatch_stage("population", lambda: None)  # type: ignore[arg-type]
    output, receipt, _value = _run(tmp_path)
    population_path = output / "population" / "score-free-material.json"
    original = population_path.read_bytes()
    population_path.chmod(0o600)
    population_path.write_bytes(original[:-1] + b" ")
    population_path.chmod(0o400)
    with pytest.raises(RehearsalError):
        reopen_non_scientific_rehearsal(output, receipt=receipt)

    # Restore the exact shard, then replace the prediction artifact by a link.
    population_path.chmod(0o600)
    population_path.write_bytes(original)
    population_path.chmod(0o400)
    prediction_path = prediction_population_manifest_path(
        output, "natural", 1, "fit")
    prediction_raw = prediction_path.read_bytes()
    prediction_path.unlink()
    prediction_path.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(Exception):
        reopen_non_scientific_rehearsal(output, receipt=receipt)
    prediction_path.unlink()
    prediction_path.write_bytes(prediction_raw)
    prediction_path.chmod(0o400)


def test_exact_rerun_reuses_immutable_shards_and_mismatch_refuses(tmp_path: Path):
    output, receipt, first = _run(tmp_path)
    second = run_non_scientific_rehearsal_v2(output, receipt)
    assert second.payload == first.payload
    # A missing receipt simulates an interrupted final publication.  Existing
    # shards must be reopened and reused, never regenerated or replaced.
    receipt.unlink()
    third = run_non_scientific_rehearsal_v2(output, receipt)
    assert third.body["population_sha256"] == first.body["population_sha256"]
    receipt.unlink()
    path = output / "population" / "score-free-material.json"
    path.chmod(0o600)
    value = json.loads(path.read_bytes())
    value["source_identity_sha256"] = "0" * 64
    path.write_bytes(canonical_json_bytes(value))
    path.chmod(0o400)
    with pytest.raises(RehearsalError):
        run_non_scientific_rehearsal_v2(output, receipt)


def test_source_identity_mismatch_refuses_before_any_artifact(tmp_path: Path):
    with pytest.raises(RehearsalError):
        run_non_scientific_rehearsal_v2(
            tmp_path / "artifacts", tmp_path / "receipt.json",
            source_identity="0" * 64)
    assert not (tmp_path / "artifacts").exists()
    assert SOURCE_IDENTITY != "0" * 64
