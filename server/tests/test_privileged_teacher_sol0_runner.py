"""Boundary witnesses for the isolated PT-Sol0 Mini runner."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import stat

import pytest

from shengji.rl.privileged_teacher_pt0 import canonical_json_bytes


SCRIPT = Path(__file__).parents[1] / "scripts" / \
    "run_privileged_teacher_sol0.py"
SPEC = importlib.util.spec_from_file_location("pt_sol0_runner", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_parent_and_secret_reads_require_exact_modes(tmp_path: Path):
    parent = tmp_path / "parent.json"
    parent.write_bytes(b"parent")
    parent.chmod(0o400)
    secret = tmp_path / "secret.bin"
    secret.write_bytes(b"s" * 32)
    secret.chmod(0o600)
    assert runner._read_single_link(
        parent, mode=0o400, label="parent") == b"parent"
    assert runner._read_single_link(
        secret, mode=0o600, label="secret") == b"s" * 32
    secret.chmod(0o400)
    with pytest.raises(ValueError, match="secret identity drift"):
        runner._read_single_link(secret, mode=0o600, label="secret")


def test_each_parent_report_must_be_one_canonical_object():
    payload = {"schema": "parent", "report_sha256": "a" * 64}
    raw = canonical_json_bytes(payload)
    assert runner._strict_report(raw, "parent") == payload
    with pytest.raises(ValueError, match="canonical JSON"):
        runner._strict_report(json.dumps(payload, indent=2).encode(), "parent")
    with pytest.raises(ValueError, match="canonical JSON"):
        runner._strict_report(b"[]\n", "parent")


def test_public_output_is_exclusive_and_read_only(tmp_path: Path):
    output = tmp_path / "result.json"
    runner._publish_exclusive(output, b"result\n")
    assert output.read_bytes() == b"result\n"
    assert stat.S_IMODE(output.stat().st_mode) == 0o400
    with pytest.raises(ValueError, match="already exists"):
        runner._publish_exclusive(output, b"replacement\n")


def test_frozen_design_drift_refuses_before_external_execution():
    class Design:
        @staticmethod
        def payload():
            return {"schema": "reviewed-design", "value": 1}

    expected = __import__("hashlib").sha256(
        canonical_json_bytes(Design.payload())).hexdigest()
    calls = []

    assert runner._run_with_frozen_design(
        Design(), expected, lambda: calls.append("external") or "done"
    ) == "done"
    assert calls == ["external"]

    calls.clear()
    with pytest.raises(ValueError, match="frozen runtime design drift"):
        runner._run_with_frozen_design(
            Design(), "f" * 64,
            lambda: calls.append("external") or "should-not-run")
    assert calls == []

    with pytest.raises(ValueError, match="expected design SHA-256 is invalid"):
        runner._run_with_frozen_design(
            Design(), "not-a-sha", lambda: calls.append("external"))
    assert calls == []
