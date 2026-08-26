"""Wiring witnesses for the one-shot PT1 terminal recovery boundary."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from shengji.rl import privileged_teacher_pt1_recovery as recovery
from shengji.rl.privileged_teacher_pt0 import canonical_json_bytes
from shengji.rl.privileged_teacher_pt1_natural import (
    NaturalPT1Design, _capture_id_sha256, _cluster_sha256,
)
from shengji.rl.privileged_teacher_pt1_statistics import (
    PT1PopulationStateIdentity,
)


SOURCE = {"git_head": "a" * 40, "source_tree_dirty": False,
          "files": [], "files_sha256": "b" * 64}
RUNTIME = {"hostname": "mini", "boot_identity_sha256": "c" * 64,
           "python_version": "3.14.0", "python_executable_sha256": "d" * 64,
           "native_extension_sha256": "e" * 64, "compiled_engine": True,
           "strict_voids": True, "worker_count": 1}
HASHES = tuple(hashlib.sha256(f"group-{index}".encode()).hexdigest()
               for index in range(416))


def _freeze(tmp_path: Path) -> recovery.PT1TerminalRecoveryFreeze:
    root = tmp_path / "failed"
    target = tmp_path / "recovery"
    claim = {
        "schema": recovery.RECOVERY_REVIEW_SCHEMA,
        "source_git": SOURCE["git_head"],
        "source_execution_freeze_sha256": "1" * 64,
        "source_failure_sha256": "2" * 64,
        "source_group_tree_sha256": recovery._group_tree_sha256(HASHES),
        "recovery_evidence_root": str(target),
        "authority": dict(recovery.AUTHORITIES),
    }
    return recovery.PT1TerminalRecoveryFreeze(
        "1" * 64, "2" * 64, "3" * 64, "4" * 64, HASHES,
        recovery._group_tree_sha256(HASHES), str(root), str(target),
        "5" * 40, SOURCE, RUNTIME,
        hashlib.sha256(canonical_json_bytes(claim)).hexdigest(), claim,
        dict(recovery.AUTHORITIES))


def test_freeze_binds_all_416_hashes_without_opening_group_records(
        monkeypatch, tmp_path):
    source_root = tmp_path / "failed"
    result = {
        "source_freeze": object(), "freeze_sha256": "1" * 64,
        "failure_sha256": "2" * 64, "progress_sha256": "3" * 64,
        "deadline_sha256": "4" * 64, "group_hashes": HASHES,
        "group_tree_sha256": recovery._group_tree_sha256(HASHES),
    }
    monkeypatch.setattr(recovery, "_validate_failed_source_root",
                        lambda root: result)
    typed = recovery.freeze_terminal_recovery(
        source_evidence_root=source_root,
        recovery_evidence_root=tmp_path / "recovery",
        source_review_commit="5" * 40, source=SOURCE, runtime=RUNTIME)
    assert typed.source_group_hashes == HASHES
    assert typed.source_group_tree_sha256 == recovery._group_tree_sha256(HASHES)
    assert typed.review_marker["source_group_tree_sha256"] \
        == typed.source_group_tree_sha256
    altered = typed.payload()
    altered["source_group_hashes"][9] = "f" * 64
    with pytest.raises(recovery.PT1RecoveryError,
                       match="source group tree drift"):
        recovery.verify_recovery_freeze(altered)


def test_packet_derivation_uses_reopened_identities_and_all_records(
        monkeypatch, tmp_path):
    typed = _freeze(tmp_path)
    design = NaturalPT1Design("6" * 64)
    groups = []
    for index, key in enumerate(design.state_keys):
        public = hashlib.sha256(f"public-{index}".encode()).hexdigest()
        groups.append({
            "index": index, "state_key": list(key), "state_schema":
                "privileged-teacher-pt1-natural-state-v1",
            "round_seed": index,
            "capture_round_cluster_sha256": _cluster_sha256(index),
            "capture_id_sha256": _capture_id_sha256(*key, public),
            "public_state_sha256": public,
            "true_world_sha256": hashlib.sha256(
                f"world-{index}".encode()).hexdigest(),
            "records": [object(), object(), object(), object()],
            "parallel_wave_wall_nanoseconds": 1,
            "parallel_wave_cpu_nanoseconds": 1,
            "parallel_wave_peak_rss_bytes": 1,
            "artifact_projection_bytes": 1,
            "exact_nodes": 1,
        })
    source_freeze = SimpleNamespace(
        scientific_capture_secret_sha256="6" * 64,
        population_manifest=None, worker_count=10,
        capacity_caps={name: 10_000 for name in recovery.SCIENTIFIC_CAP_KEYS})
    monkeypatch.setattr(recovery, "_reopen_inputs",
                        lambda freeze: (source_freeze, groups))
    observed = {}

    class Report:
        def payload(self):
            return {"report": "exact"}

    def reduce(design_value, states, records):
        observed["state_count"] = len(states)
        observed["record_count"] = len(records)
        observed["identity_types"] = {type(value) for value in states.values()}
        return Report()

    monkeypatch.setattr(recovery, "reduce_reopened_pt1_statistics", reduce)
    monkeypatch.setattr(recovery, "verify_statistics_report",
                        lambda report, design: report)
    packet = recovery._derive_packet(typed)
    assert observed == {"state_count": 416, "record_count": 1664,
                        "identity_types": {PT1PopulationStateIdentity}}
    assert packet["status"] == recovery.RECOVERY_STATUS
    assert packet["completed_units"] == packet["total_units"] == 416


def test_recovery_namespace_is_one_shot_and_attempt_precedes_derivation(
        monkeypatch, tmp_path):
    typed = _freeze(tmp_path)
    monkeypatch.setattr(recovery, "_require_live_recovery_bindings",
                        lambda *args, **kwargs: None)
    monkeypatch.setattr(recovery, "authenticate_recovery_marker",
                        lambda *args, **kwargs: None)
    packet = {"schema": recovery.RECOVERY_PACKET_SCHEMA,
              "packet_sha256": "7" * 64, "status": recovery.RECOVERY_STATUS}
    monkeypatch.setattr(recovery, "_derive_packet", lambda freeze: packet)
    marker = canonical_json_bytes(dict(typed.review_marker))
    assert recovery.run_terminal_recovery(
        typed, review_marker=marker,
        review_commit="8" * 40)["status"] == recovery.RECOVERY_STATUS
    assert (Path(typed.recovery_evidence_root)
            / recovery.RECOVERY_ATTEMPT_NAME).is_file()
    with pytest.raises(recovery.PT1RecoveryError,
                       match="already consumed"):
        recovery.run_terminal_recovery(
            typed, review_marker=marker, review_commit="8" * 40)


def test_packet_is_published_last_and_failed_recovery_cannot_retry(
        monkeypatch, tmp_path):
    typed = _freeze(tmp_path)
    monkeypatch.setattr(recovery, "_require_live_recovery_bindings",
                        lambda *args, **kwargs: None)
    monkeypatch.setattr(recovery, "authenticate_recovery_marker",
                        lambda *args, **kwargs: None)
    packet = {"schema": recovery.RECOVERY_PACKET_SCHEMA,
              "packet_sha256": "7" * 64, "status": recovery.RECOVERY_STATUS}
    monkeypatch.setattr(recovery, "_derive_packet", lambda freeze: packet)
    real_write = recovery._write_once

    def refuse_packet(path, data, **kwargs):
        if path.name == recovery.PACKET_NAME:
            raise recovery.PT1RecoveryError("injected packet publication failure")
        return real_write(path, data, **kwargs)

    monkeypatch.setattr(recovery, "_write_once", refuse_packet)
    marker = canonical_json_bytes(dict(typed.review_marker))
    with pytest.raises(recovery.PT1RecoveryError,
                       match="packet publication"):
        recovery.run_terminal_recovery(
            typed, review_marker=marker, review_commit="8" * 40)
    root = Path(typed.recovery_evidence_root)
    assert not (root / recovery.PACKET_NAME).exists()
    assert (root / recovery.MANIFEST_NAME).is_file()
    assert (root / recovery.RECOVERY_FAILURE_NAME).is_file()
    with pytest.raises(recovery.PT1RecoveryError,
                       match="already consumed"):
        recovery.run_terminal_recovery(
            typed, review_marker=marker, review_commit="8" * 40)
