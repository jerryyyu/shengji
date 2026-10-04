"""Exercise real worker control rejection before any shared lease access."""

import json
import os

import pytest

from scripts import observation_worker as worker
from shengji.eval import observation_queue as guards
from shengji.eval.observation_recipe import build_observation_command, MODEL_SHA256, FIXTURE_SHA256


@pytest.mark.parametrize("fault,match", [
    ("claim_digest", "strict spent owner claim"),
    ("claim_complete", "strict spent owner claim"),
    ("command", "owner inner command mismatch"),
    ("boolean_pid", "strict positive owner pid"),
    ("hold", "HOLD or peer lock"),
    ("peer", "HOLD or peer lock"),
    ("release_missing", "exact RELEASE"),
    ("release_digest", "exact RELEASE"),
])
def test_actual_worker_refuses_invalid_controls(tmp_path, monkeypatch, fault, match):
    digest = "a" * 64
    packet = {key: str(tmp_path / key) for key in
              ("release", "hold", "reservation", "status", "claim")}
    packet["host_lock"] = "/root/.claude-host.lock"
    packet["other_locks"] = [str(tmp_path / "peer")]
    packet["recipe"] = {
        "python": "/opt/venv/bin/python", "source_root": "/srv/shengji",
        "model": "/srv/models/smv3.npz",
        "fixtures": "/srv/shengji/server/tests/tactical/public_observations.jsonl",
        "output": str(tmp_path / "comparison.json"), "evidence": str(tmp_path / "evidence"),
        "seeds": [0, 1, 2], "fill_seed": 0, "timeout_seconds": 600,
        "model_sha256": MODEL_SHA256, "fixture_sha256": FIXTURE_SHA256,
    }
    claim = dict(schema="m9-owner-attempt-v1", packet_sha256=digest,
                 status="spent_no_retry", comparison_validated=False,
                 owner_pid=os.getpid(), inner_command=list(build_observation_command(packet["recipe"])))
    release = dict(schema="m9-release-v1", packet_sha256=digest)
    if fault == "claim_digest":
        claim["packet_sha256"] = "b" * 64
    elif fault == "claim_complete":
        claim["comparison_validated"] = True
    elif fault == "command":
        claim["inner_command"].append("--override")
    elif fault == "boolean_pid":
        claim["owner_pid"] = True
    elif fault in ("hold", "peer"):
        (tmp_path / fault).touch()
    elif fault == "release_digest":
        release["packet_sha256"] = "b" * 64
    (tmp_path / "claim").write_text(json.dumps(claim))
    if fault != "release_missing":
        (tmp_path / "release").write_text(json.dumps(release))
    # Fail the test if rejection reaches host-lease inspection. No /root writes.
    def forbidden(*args):
        raise AssertionError("invalid controls reached shared lease inspection")
    monkeypatch.setattr(worker.Path, "is_dir", forbidden)
    with pytest.raises(ValueError, match=match):
        worker._verify_claim_and_controls(packet, digest, guards)
