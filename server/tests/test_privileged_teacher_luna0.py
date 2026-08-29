"""Boundary witnesses for the PT-Luna0 runner."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import stat

import pytest

from shengji.rl.privileged_teacher_pt0 import canonical_json_bytes


SCRIPT = Path(__file__).parents[1] / "scripts" / "run_privileged_teacher_luna0.py"
SPEC = importlib.util.spec_from_file_location("pt_luna0_runner", SCRIPT)
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
    assert runner._read_single_link(parent, mode=0o400, label="parent") == b"parent"
    assert runner._read_single_link(secret, mode=0o600, label="secret") == b"s" * 32
    secret.chmod(0o400)
    with pytest.raises(ValueError, match="secret identity drift"):
        runner._read_single_link(secret, mode=0o600, label="secret")


def test_strict_report_and_exclusive_output(tmp_path: Path):
    payload = {"schema": "parent", "report_sha256": "a" * 64}
    raw = canonical_json_bytes(payload)
    assert runner._strict_report(raw, "parent") == payload
    with pytest.raises(ValueError, match="canonical JSON"):
        runner._strict_report(json.dumps(payload, indent=2).encode(), "parent")
    output = tmp_path / "result.json"
    runner._publish_exclusive(output, b"result")
    assert stat.S_IMODE(output.stat().st_mode) == 0o400
    with pytest.raises(ValueError, match="already exists"):
        runner._publish_exclusive(output, b"replacement")


def test_frozen_design_rejects_model_or_design_substitution():
    class Design:
        @staticmethod
        def payload():
            return {"schema": "reviewed-design", "model": "gpt-5.6-luna"}

    expected = __import__("hashlib").sha256(
        canonical_json_bytes(Design.payload())).hexdigest()
    calls = []
    assert runner._run_with_frozen_design(
        Design(), expected, lambda: calls.append("run") or "done") == "done"
    assert calls == ["run"]
    calls.clear()
    with pytest.raises(ValueError, match="frozen runtime design"):
        runner._run_with_frozen_design(
            Design(), "f" * 64, lambda: calls.append("run"))
    assert calls == []
