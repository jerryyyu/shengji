"""Real-process integration using synthetic policies, never model inference."""
import json
import os
from pathlib import Path
import sys

import pytest

from shengji.eval.observation_process import run_observation_process


@pytest.mark.parametrize("mode,status,partials", [
    ("complete", "exited", 24), ("failure", "failed", 2),
    ("malformed", "failed", 1), ("timeout", "timeout", 1),
])
def test_process_and_cli_keep_complete_and_partial_states_distinct(tmp_path, mode, status, partials):
    server = Path(__file__).resolve().parents[1]
    output = tmp_path / "comparison.json"
    evidence = tmp_path / "process"
    receipt = run_observation_process(
        (sys.executable, "-I", "-B", str(server / "tests/fixtures/m9_fake_worker.py"),
         str(server), str(output), mode),
        workspace=tmp_path, env={"PATH": os.environ.get("PATH", "")},
        watchdog_script=server / "shengji/luna/watchdog.py",
        timeout_seconds=5, evidence=evidence)
    assert receipt["status"] == status
    assert receipt["comparison_validated"] is False
    stdout = (evidence / "stdout.bin").read_text()
    stderr = (evidence / "stderr.bin").read_text()
    assert "synthetic-decision-1" in stdout
    attempt = Path(f"{output}.attempt")
    records = [p for p in attempt.glob("*.json") if p.name != "claim.json"]
    assert len(records) == partials
    for path in records:
        raw = path.read_text()
        assert json.loads(raw)["comparison_complete"] is False
        assert "private-synthetic-marker" not in raw
        assert "worlds" not in json.loads(raw)["decision"]
    if mode == "complete":
        report = json.loads(output.read_text())
        assert report["comparison_complete"] is True
        assert len(report["results"]) == 12
        assert "synthetic-decision-24" in stdout
        assert "wrote " in stderr
        assert receipt["returncode"] == 0
    else:
        assert not output.exists()
        assert receipt["returncode"] != 0
        assert "wrote " not in stderr
        if mode != "timeout":
            assert "TacticalError" in stderr


def test_second_process_cannot_reuse_a_spent_partial_attempt(tmp_path):
    server = Path(__file__).resolve().parents[1]
    output = tmp_path / "comparison.json"

    def invoke(mode, evidence):
        return run_observation_process(
            (sys.executable, "-I", "-B",
             str(server / "tests/fixtures/m9_fake_worker.py"),
             str(server), str(output), mode),
            workspace=tmp_path, env={"PATH": os.environ.get("PATH", "")},
            watchdog_script=server / "shengji/luna/watchdog.py",
            timeout_seconds=30, evidence=evidence)

    first_evidence = tmp_path / "first-process"
    first = invoke("failure", first_evidence)
    assert first["status"] == "failed"
    attempt = Path(f"{output}.attempt")
    assert len(list(attempt.glob("*.json"))) == 3  # claim plus two partials
    before = {p.relative_to(tmp_path): p.read_bytes()
              for root in (attempt, first_evidence)
              for p in root.rglob("*") if p.is_file()}

    second_evidence = tmp_path / "second-process"
    second = invoke("complete", second_evidence)
    assert second["status"] == "failed"
    assert second["returncode"] != 0
    assert second["comparison_validated"] is False
    assert "synthetic-decision-" not in (second_evidence / "stdout.bin").read_text()
    assert "comparison output or attempt already exists" in (
        second_evidence / "stderr.bin").read_text()
    assert not output.exists()
    after = {p.relative_to(tmp_path): p.read_bytes()
             for root in (attempt, first_evidence)
             for p in root.rglob("*") if p.is_file()}
    assert after == before
