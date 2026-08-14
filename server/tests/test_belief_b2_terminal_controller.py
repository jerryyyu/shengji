"""One-shot publication and read-only terminal reconstruction tests."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

import shengji.rl.belief_b2_terminal_controller as terminal
from shengji.rl.belief_b2_protocol import CAPTURE_WALL_SECOND_CAP
from shengji.rl.belief_b2_result import NS_PER_SECOND
from shengji.rl.belief_b2_execution import (
    REQUIRED_ENVIRONMENT, REQUIRED_EXACT_PATHS, REVIEW_PREFIX,
    B2ExecutionDesignV1, RuntimeProfileV1, SourceBindingV1,
    build_pipeline_admission, expected_review_claim)
from shengji.rl.belief_b2_terminal_controller import (
    BeliefB2TerminalControllerError, run_open_test, verify_terminal)
from shengji.rl.belief_contract import canonical_json_bytes


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _design(root) -> B2ExecutionDesignV1:
    paths = (*REQUIRED_EXACT_PATHS,
             "server/shengji/rl/belief_b2_terminal_controller.py")
    bindings = tuple(SourceBindingV1(
        path=path, byte_count=index, sha256=_sha(path))
                     for index, path in enumerate(sorted(paths)))
    runtime = RuntimeProfileV1(
        hostname="test", operating_system="test", machine="x86_64",
        cpu_count=16, memory_bytes=32 << 30,
        boot_identity=_sha("boot"),
        python_executable="/runtime/python",
        python_resolved_executable="/runtime/python",
        python_executable_sha256=_sha("python"), python_version="3.14",
        torch_version="2.9", torch_config_sha256=_sha("torch"),
        numpy_version="2.3", native_path="/runtime/_fast.so",
        native_sha256=_sha("fast"),
        required_environment=REQUIRED_ENVIRONMENT)
    return B2ExecutionDesignV1(
        execution_git="a" * 40, source_bindings=bindings,
        runtime=runtime, evidence_root=str(root))


class _Bytes:
    def __init__(self, label):
        self.label = label

    def canonical_bytes(self):
        return canonical_json_bytes({"label": self.label})


def _authorized(root):
    design = _design(root)
    marker = REVIEW_PREFIX.encode() + canonical_json_bytes(
        expected_review_claim(design))
    admission = build_pipeline_admission(
        design, review_commit="b" * 40, review_marker=marker)
    return design, admission, marker


def _stub_derivation(monkeypatch):
    evidence = SimpleNamespace(inventory=_Bytes("inventory"))
    result = _Bytes("terminal")
    report = {"terminal": {"decision": "SELECT_NONE_NO_CALIBRATION_LIFT"}}
    monkeypatch.setattr(
        terminal, "derive_terminal_evidence",
        lambda _root, _design, _admission: evidence)
    monkeypatch.setattr(
        terminal, "evaluate_b2_terminal", lambda _evidence: result)
    monkeypatch.setattr(
        terminal, "_report_payload",
        lambda _design, _admission, _evidence: report)
    return report


def test_test_open_consumes_slot_before_derivation_failure(
        tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    design, admission, marker = _authorized(root)

    def fail(*_args):
        raise RuntimeError("injected terminal failure")

    monkeypatch.setattr(terminal, "derive_terminal_evidence", fail)
    with pytest.raises(RuntimeError, match="injected"):
        run_open_test(root, design, admission, review_marker=marker)
    partial = root / "terminal.partial"
    assert partial.is_dir()
    assert {path.name for path in partial.iterdir()} == {"attempt.json"}
    with pytest.raises(BeliefB2TerminalControllerError, match="occupied"):
        run_open_test(root, design, admission, review_marker=marker)


def test_terminal_publication_and_reconstruction_are_closed(
        tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    design, admission, marker = _authorized(root)
    expected = _stub_derivation(monkeypatch)
    assert run_open_test(
        root, design, admission, review_marker=marker) == expected
    directory = root / "terminal"
    assert {path.name for path in directory.iterdir()} == {
        "attempt.json", "result.json", "manifest.json"}
    assert verify_terminal(root, design, admission) == expected
    foreign = directory / "foreign.json"
    foreign.write_bytes(b"{}")
    with pytest.raises(
            BeliefB2TerminalControllerError, match="population"):
        verify_terminal(root, design, admission)
    foreign.unlink()
    result = directory / "result.json"
    result.chmod(0o600)
    result.write_bytes(b"{}")
    result.chmod(0o400)
    with pytest.raises(
            BeliefB2TerminalControllerError, match="reconstruction"):
        verify_terminal(root, design, admission)


def test_coordinated_result_and_manifest_rehash_hits_result_guard_exactly(
        tmp_path, monkeypatch):
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    design, admission, marker = _authorized(root)
    _stub_derivation(monkeypatch)
    run_open_test(root, design, admission, review_marker=marker)
    directory = root / "terminal"
    result = directory / "result.json"
    manifest = directory / "manifest.json"
    altered = canonical_json_bytes({
        "terminal": {"decision": "COORDINATED-REHASH-WITNESS"}})
    result.chmod(0o600)
    result.write_bytes(altered)
    result.chmod(0o400)
    manifest_row = json.loads(manifest.read_bytes())
    manifest_row["files"]["result.json"] = hashlib.sha256(
        altered).hexdigest()
    manifest.chmod(0o600)
    manifest.write_bytes(canonical_json_bytes(manifest_row))
    manifest.chmod(0o400)
    with pytest.raises(BeliefB2TerminalControllerError) as refusal:
        verify_terminal(root, design, admission)
    assert refusal.value.args == ("terminal result reconstruction drift",)


def test_parallel_resource_windows_use_wall_span_and_enforce_cap(tmp_path):
    design = _design((tmp_path / "evidence").resolve())

    def row(start, finish, *, cpu=0, device=0, size=0):
        return {"resources": {
            "started_monotonic_nanoseconds": start,
            "finished_monotonic_nanoseconds": finish,
            "cpu_nanoseconds": cpu,
            "device_nanoseconds": device,
            "artifact_bytes": size,
            "retry_count": 0,
        }}

    capture = (row(0, 10, cpu=7, size=3),
               row(5, 20, cpu=11, size=5))
    reference = (row(100, 110, cpu=13, size=7),
                 row(102, 118, cpu=17, size=9))
    training = (row(200, 230, device=19, size=11),
                row(205, 240, device=23, size=13))
    receipt = terminal._resources(
        design, capture, reference, training)
    assert receipt.capture_wall_nanoseconds == 20
    assert receipt.capture_cpu_nanoseconds == 18
    assert receipt.capture_artifact_bytes == 8
    assert receipt.reference_wall_nanoseconds == 18
    assert receipt.reference_cpu_nanoseconds == 30
    assert receipt.training_wall_nanoseconds == 40
    assert receipt.training_device_nanoseconds == 42
    assert receipt.within_caps is True

    over_cap = (row(
        0, CAPTURE_WALL_SECOND_CAP * NS_PER_SECOND + 1,
        cpu=1, size=1),)
    refused = terminal._resources(
        design, over_cap, reference, training)
    assert refused.capture_wall_nanoseconds \
        == CAPTURE_WALL_SECOND_CAP * NS_PER_SECOND + 1
    assert refused.within_caps is False
