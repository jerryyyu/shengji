from __future__ import annotations

import os
import runpy
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import shengji.rl.world_afterstate_v1_capacity as capacity
from shengji.rl.world_afterstate_v1_scientific import lock_root_for


def test_target_free_cli_refuses_label_bearing_path_surface(tmp_path):
    server = Path(__file__).resolve().parents[1]
    script = server / "scripts" / "world_afterstate_v1_run.py"
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment.update({
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0",
        "SHENGJI_FAST": "1", "SHENGJI_REQUIRE_VOIDS": "1",
    })
    result = subprocess.run((
        sys.executable, "-P", "-B", str(script), "seal-predictions",
        "--root", str(tmp_path / "missing-root"),
        "--expected-git", "a" * 40,
        "--population", str(tmp_path / "population.json"),
        "--audit-manifest", str(tmp_path / "audit.json"),
        "--audit-root", str(tmp_path / "audits"),
        "--dataset-manifest", str(tmp_path / "labels.json"),
        "--row-root", str(tmp_path / "label-rows"),
    ), cwd=server, env=environment, capture_output=True, text=True)
    assert result.returncode != 0
    assert "target-free prediction argument drift" in result.stderr


def test_initialize_checks_live_runtime_before_spending_admission(
        monkeypatch, tmp_path):
    server = Path(__file__).resolve().parents[1]
    script = server / "scripts" / "world_afterstate_v1_run.py"
    namespace = runpy.run_path(str(script))
    script_globals = namespace["_initialize"].__globals__
    freeze = {"source_git": "a" * 40}
    events = []
    script_globals["_canonical_read"] = \
        lambda _path, _label: (b"{}\n", freeze)
    monkeypatch.setattr(
        capacity, "reopen_capacity_directory", lambda _path: object())

    def refuse_live(_freeze, _expected_git):
        events.append("strict-live")
        raise RuntimeError("fixture live drift")

    script_globals["_strict_live"] = refuse_live
    script_globals["initialize_scientific_root"] = lambda *_args, **_kwargs: \
        events.append("initialize")
    args = SimpleNamespace(
        freeze=str(tmp_path / "freeze.json"),
        capacity=str(tmp_path / "capacity"),
        root=str(tmp_path / "scientific"), expected_git="a" * 40,
        review_commit="b" * 40)
    with pytest.raises(RuntimeError, match="^fixture live drift$"):
        namespace["_initialize"](args)
    assert events == ["strict-live"]
    assert not (tmp_path / "scientific").exists()


def _heldout_stage_fixture(namespace, tmp_path):
    root = tmp_path / "scientific"
    lock_root_for(root).mkdir(mode=0o700)
    freeze = {
        "freeze_sha256": "a" * 64,
        "population": {
            "calibration_label_row_count": 624,
            "calibration_label_pair_count": 520,
        },
        "resources": {
            "audit_wall_cap_nanoseconds": 10**9,
            "reconstruction_wall_cap_nanoseconds": 10**9,
        },
    }
    admission = {"admission_sha256": "b" * 64}
    script_globals = namespace["_calibration"].__globals__
    script_globals["_context"] = \
        lambda _args: (root, freeze, object(), admission)
    script_globals["_cohort_builds"] = lambda _root: {}
    script_globals["reopen_target_free_prediction_directory"] = \
        lambda _root: SimpleNamespace(
            manifest={"manifest_sha256": "c" * 64})
    return root, freeze, script_globals


def test_calibration_attempt_is_durable_before_first_label_read(
        tmp_path):
    server = Path(__file__).resolve().parents[1]
    namespace = runpy.run_path(
        str(server / "scripts" / "world_afterstate_v1_run.py"))
    root, _freeze, script_globals = _heldout_stage_fixture(
        namespace, tmp_path)
    attempt = lock_root_for(root) / "open-calibration-labels.json"

    def refuse_after_attempt(**_kwargs):
        assert attempt.is_file()
        raise RuntimeError("fixture calibration read stop")

    script_globals["reopen_calibration_labels"] = refuse_after_attempt
    args = SimpleNamespace(
        root=str(root), expected_git="d" * 40,
        population=str(tmp_path / "population.json"),
        dataset_manifest=str(tmp_path / "dataset.json"),
        row_root=str(tmp_path / "rows"))
    with pytest.raises(RuntimeError, match="^fixture calibration read stop$"):
        namespace["_calibration"](args)
    assert attempt.is_file()


def test_reconstruction_attempt_is_durable_before_label_reopen(
        tmp_path):
    server = Path(__file__).resolve().parents[1]
    namespace = runpy.run_path(
        str(server / "scripts" / "world_afterstate_v1_run.py"))
    root, _freeze, script_globals = _heldout_stage_fixture(
        namespace, tmp_path)
    attempt = lock_root_for(root) / "independent-reconstruction.json"
    script_globals["reopen_pipeline_directory"] = lambda _root: \
        SimpleNamespace(manifest={"manifest_sha256": "e" * 64})
    script_globals["_public_audits"] = lambda _args, _freeze: ({}, {})
    script_globals["reopen_population_audit_fold"] = \
        lambda *_args, **_kwargs: {}

    def refuse_after_attempt(**_kwargs):
        assert attempt.is_file()
        raise RuntimeError("fixture reconstruction read stop")

    script_globals["reopen_calibration_labels"] = refuse_after_attempt
    args = SimpleNamespace(
        root=str(root), expected_git="d" * 40,
        population=str(tmp_path / "population.json"),
        audit_manifest=str(tmp_path / "audit.json"),
        audit_root=str(tmp_path / "audits"),
        dataset_manifest=str(tmp_path / "dataset.json"),
        row_root=str(tmp_path / "rows"))
    with pytest.raises(
            RuntimeError, match="^fixture reconstruction read stop$"):
        namespace["_verify"](args)
    assert attempt.is_file()
