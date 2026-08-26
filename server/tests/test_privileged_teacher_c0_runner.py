"""Boundary tests for the isolated PT C0 Mini runner."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import stat

import pytest

from shengji.rl.privileged_teacher_pt0 import canonical_json_bytes


SCRIPT = Path(__file__).parents[1] / "scripts" / "run_privileged_teacher_c0.py"
SPEC = importlib.util.spec_from_file_location("pt_c0_runner", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_parent_and_secret_reads_require_exact_private_modes(tmp_path):
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
    parent.chmod(0o600)
    with pytest.raises(ValueError, match="parent identity drift"):
        runner._read_single_link(parent, mode=0o400, label="parent")


def test_parent_report_must_be_canonical_object():
    payload = {"schema": "parent", "report_sha256": "a" * 64}
    assert runner._strict_report(canonical_json_bytes(payload)) == payload
    with pytest.raises(ValueError, match="canonical JSON"):
        runner._strict_report(json.dumps(payload, indent=2).encode())
    with pytest.raises(ValueError, match="canonical JSON"):
        runner._strict_report(b"[]\n")


def test_output_is_exclusive_read_only_and_exact(tmp_path):
    output = tmp_path / "result.json"
    runner._publish_exclusive(output, b"result\n")
    assert output.read_bytes() == b"result\n"
    assert stat.S_IMODE(output.stat().st_mode) == 0o400
    with pytest.raises(ValueError, match="already exists"):
        runner._publish_exclusive(output, b"replacement\n")
