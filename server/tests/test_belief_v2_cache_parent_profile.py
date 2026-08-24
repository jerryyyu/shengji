"""Wiring and tamper witnesses for the bounded R5 parent profiler."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from tests.test_belief_v2_parallel_cache import _fixture


SCRIPT = (Path(__file__).parents[1] / "scripts"
          / "belief_v2_cache_parent_profile.py")
SPEC = importlib.util.spec_from_file_location("cache_parent_profile", SCRIPT)
PROFILE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(PROFILE)


def test_quantile_sample_is_exact_distinct_and_endpoint_bound():
    assert PROFILE._sample_indices(10, 4) == (0, 3, 6, 9)
    assert PROFILE._sample_indices(65, 64)[0] == 0
    assert PROFILE._sample_indices(65, 64)[-1] == 64
    assert len(set(PROFILE._sample_indices(65, 64))) == 64
    with pytest.raises(PROFILE.BeliefV2CacheParentProfileError,
                       match="sample inputs"):
        PROFILE._sample_indices(10, 11)


def test_preimport_gate_refuses_environment_and_bytecode_shadow(
        tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/tmp/poison")
    with pytest.raises(RuntimeError, match="PYTHONPATH"):
        PROFILE._refuse_preimport_drift()
    monkeypatch.delenv("PYTHONPATH")

    repo = tmp_path / "repo"
    server = repo / "server"
    (server / "shengji").mkdir(parents=True)
    (server / "scripts").mkdir()
    (server / "shengji" / "poison.pyc").write_bytes(b"poison")
    monkeypatch.setattr(PROFILE, "REPO", repo)
    monkeypatch.setattr(PROFILE, "SERVER", server)

    def fake_run(command, **_kwargs):
        if "status" in command:
            return SimpleNamespace(stdout="")
        if "ls-files" in command:
            return SimpleNamespace(stdout=b"")
        raise AssertionError(command)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="bytecode shadows"):
        PROFILE._refuse_preimport_drift()


def test_cli_invokes_preimport_gate_before_project_import(tmp_path):
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(tmp_path / "poison")
    result = subprocess.run(
        (sys.executable, "-P", "-B", str(SCRIPT), "--help"),
        cwd=tmp_path, env=environment, capture_output=True, text=True)
    assert result.returncode != 0
    assert "V2 parent profile refuses PYTHONPATH" in result.stderr


def test_context_refuses_live_runtime_drift(tmp_path, monkeypatch):
    (_index, _realization, _batches, freeze, _admission,
     _binding) = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(PROFILE, "build_runtime_profile", object)
    with pytest.raises(PROFILE.BeliefV2CacheParentProfileError,
                       match="live runtime identity drift"):
        PROFILE._require_live_runtime(freeze)

    monkeypatch.setattr(
        PROFILE, "build_runtime_profile", lambda: freeze.runtime)
    assert PROFILE._require_live_runtime(freeze) is None


def test_profile_run_reopens_and_summary_tamper_refuses(
        tmp_path, monkeypatch, capsys):
    (index, realization, _batches, freeze, admission,
     binding) = _fixture(tmp_path, monkeypatch)
    root = (tmp_path / "profile-evidence").resolve()
    root.mkdir()
    inputs = SimpleNamespace(index=index)
    context = (
        freeze, admission, {"index_sha256": "a" * 64}, inputs,
        realization, realization, realization, (0,), binding)
    monkeypatch.setattr(PROFILE, "_clean_git_head", lambda _expected: None)
    monkeypatch.setattr(
        PROFILE, "_context_and_sample",
        lambda _root, _count: context)
    monkeypatch.setattr(
        PROFILE, "parallel_cache_worker_count", lambda *_args: 2)

    args = SimpleNamespace(
        root=str(root), scratch=str(tmp_path / "profile-scratch"),
        out=str(tmp_path / "profile-receipt.json"),
        expected_source_git="f" * 40,
        expected_failed_freeze_sha256=freeze.sha256(),
        expected_failed_admission_sha256=admission.sha256(),
        expected_index_sha256="a" * 64,
        expected_worker_count=2, sample_batch_count=1)
    result = PROFILE.run(args)
    journal = [
        json.loads(line.removeprefix(PROFILE.JOURNAL_PREFIX))
        for line in capsys.readouterr().err.splitlines()
        if line.startswith(PROFILE.JOURNAL_PREFIX)]
    assert journal[0]["schema"] == PROFILE.JOURNAL_SCHEMA
    assert journal[0]["kind"] == "start"
    assert journal[0]["sample_batch_schedule_sha256"] \
        == realization.batch_schedule_sha256
    assert any(row["kind"] == "phase" for row in journal[1:])
    assert all(row["schema"] == PROFILE.JOURNAL_SCHEMA for row in journal)
    receipt = result["receipt"]
    assert receipt["sample_batch_count"] == 1
    assert receipt["sample_cache_reopened"] is True
    assert receipt["sample_control_overlay_reopened"] is True
    assert receipt["sample_control_changed_cell_count"] > 0
    assert receipt["caller_thread_cpu_nanoseconds"] >= 0
    assert receipt["caller_thread_cpu_nanoseconds"] \
        <= receipt["parent_process_cpu_nanoseconds"] + 1_000_000
    assert receipt["process_tree_cpu_nanoseconds"] >= 0
    assert receipt["parent_process_cpu_nanoseconds"] \
        <= receipt["process_tree_cpu_nanoseconds"] + 1_000_000
    assert receipt["quantile_sample_is_not_full_capacity_evidence"] is True
    assert receipt["synthetic_test_targets_opened"] is False
    assert receipt["human_test_targets_opened"] is False
    assert receipt["outcome_fields_opened"] is False
    assert all(value is False for value in receipt["authority"].values())

    verify_args = SimpleNamespace(
        root=str(root), scratch=str(tmp_path / "profile-scratch"),
        receipt=str(tmp_path / "profile-receipt.json"),
        expected_source_git="f" * 40)
    assert PROFILE.verify(verify_args)["status"] \
        == "VERIFIED_SCORE_FREE_PARENT_PROFILE"

    path = tmp_path / "profile-receipt.json"
    path.chmod(0o600)
    tampered = json.loads(path.read_bytes())
    tampered["phase_summary"][0]["wall_nanoseconds"] += 1
    path.write_bytes(canonical_json_bytes(tampered))
    path.chmod(0o400)
    with pytest.raises(PROFILE.BeliefV2CacheParentProfileError,
                       match="summary reconstruction"):
        PROFILE.verify(verify_args)

    path.chmod(0o600)
    path.write_bytes(canonical_json_bytes(receipt))
    timing_tamper = dict(receipt)
    timing_tamper["caller_thread_cpu_nanoseconds"] = \
        timing_tamper["parent_process_cpu_nanoseconds"] + 1_000_001
    path.write_bytes(canonical_json_bytes(timing_tamper))
    path.chmod(0o400)
    with pytest.raises(PROFILE.BeliefV2CacheParentProfileError,
                       match="aggregate timing"):
        PROFILE.verify(verify_args)
