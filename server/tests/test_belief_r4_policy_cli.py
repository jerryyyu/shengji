"""Wiring witnesses for the R4 policy diagnostic command."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import belief_r4_policy as CLI
from shengji.rl.belief_contract import canonical_json_bytes


def _publish(path: Path, value: object) -> bytes:
    raw = canonical_json_bytes(value)
    path.write_bytes(raw)
    path.chmod(0o400)
    return raw


def test_run_start_uses_one_clock_sample_for_the_frozen_deadline(
        monkeypatch, tmp_path: Path, capsys) -> None:
    """The real run wiring must not derive start and deadline separately."""
    root = tmp_path / "evidence"
    root.mkdir()
    models = {
        "r4_freeze_sha256": "4" * 64,
        "r4_admission_sha256": "5" * 64,
    }
    freeze = {
        "evidence_root": str(root),
        "execution_git": "1" * 40,
        "source_manifest_sha256": "2" * 64,
        "runtime_compatibility_sha256": "3" * 64,
        "model_root": str(tmp_path / "models"),
        "models": models,
        "workers": 1,
        "scientific_wall_cap_nanoseconds": 10_000,
        "scientific_wall_estimate_nanoseconds": 1_000,
        "next_unit_reserve_nanoseconds": 100,
    }
    freeze_raw = _publish(root / "freeze.json", freeze)
    claim = {"schema": "test-freeze-review-v1"}
    marker = CLI.FREEZE_REVIEW_PREFIX.encode("ascii") \
        + canonical_json_bytes(claim)
    (root / "review.marker").write_bytes(marker)
    (root / "review.marker").chmod(0o400)
    authority = {
        "one_scientific_execution_authorized": True,
        "resume_missing_shards_before_deadline_authorized": True,
        "r4_test_opening_authorized": False,
        "retry_after_terminal_authorized": False,
        "r5_authorized": False,
        "gameplay_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }
    admission = {
        "schema": "belief-r4-policy-scientific-admission-v1",
        "freeze_sha256": hashlib.sha256(freeze_raw).hexdigest(),
        "review_commit": "6" * 40,
        "review_marker_sha256": hashlib.sha256(marker).hexdigest(),
        "created_unix_nanoseconds": 1,
        "authority": authority,
    }
    _publish(root / "admission.json", admission)

    monkeypatch.setattr(CLI, "validate_freeze", lambda _freeze: None)
    monkeypatch.setattr(CLI, "expected_freeze_review_claim", lambda _freeze: claim)
    monkeypatch.setattr(
        CLI, "authenticate_scientific_freeze_review", lambda **_kwargs: marker)
    monkeypatch.setattr(
        CLI, "build_source_identity",
        lambda _repo, expected_git: {
            "execution_git": expected_git,
            "source_manifest_sha256": freeze["source_manifest_sha256"],
        })
    monkeypatch.setattr(
        CLI, "build_runtime_identity",
        lambda: {"compatibility_sha256": freeze["runtime_compatibility_sha256"]})
    sentinel_models = object()
    monkeypatch.setattr(CLI, "load_r4_policy_models", lambda *_args, **_kwargs: sentinel_models)
    monkeypatch.setattr(CLI, "model_identity", lambda _models: models)
    calls: list[dict[str, object]] = []

    def run(root_arg: Path, **kwargs):
        calls.append({"root": root_arg, **kwargs})
        return {"terminal": {"route": "COMPLETE", "round_count": 104}}

    monkeypatch.setattr(CLI, "run_scientific_diagnostic", run)
    clock_values = iter((1_000, 2_000))
    monkeypatch.setattr(CLI.time, "time_ns", lambda: next(clock_values))
    monkeypatch.setattr(
        CLI.sys, "argv", ["belief_r4_policy.py", "run", str(root)])

    CLI.main()

    start = json.loads((root / "run-start.json").read_bytes())
    assert start == {
        "started_unix_nanoseconds": 1_000,
        "deadline_unix_nanoseconds": 11_000,
        "resume_count": 0,
    }
    assert calls[0]["deadline_unix_ns"] == 11_000
    assert json.loads(capsys.readouterr().out)["complete"] is True
