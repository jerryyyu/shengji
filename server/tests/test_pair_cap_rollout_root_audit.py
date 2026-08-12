"""Tests for the bounded high-N audit of pair-cap-changed roots."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import pair_cap_rollout_root_audit as AUDIT  # noqa: E402


FROZEN_AUDIT = (
    Path(__file__).resolve().parent
    / "data/pair_cap_rollout_changed_root_audit.v1.json"
)


def test_changed_population_replays_exactly():
    payload, rows = AUDIT.changed_rows(AUDIT.DEFAULT_DOSE)
    assert payload["aggregate"]["v2_incremental_root_changes"] == 3
    assert [row["state_id"] for row in rows] == [
        "447000002:5:2", "447000005:2:1", "447000007:6:3",
    ]
    for row in rows:
        rnd = AUDIT.reconstruct_root(row)
        assert rnd.turn == row["seat"]
        assert len(rnd.history) == row["completed_tricks"]


def test_paired_moments_and_bounds():
    got = AUDIT.paired_moments([1.0, 3.0, 5.0, 7.0])
    assert got["n"] == 4
    assert got["mean"] == 4.0
    assert got["wins"] == 4
    assert got["losses"] == got["ties"] == 0
    assert got["ci_two_sided_95"][0] < 4.0 < got["ci_two_sided_95"][1]
    with pytest.raises(AUDIT.AuditRefused, match="at least two"):
        AUDIT.paired_moments([1.0])


def test_two_world_smoke_is_explicitly_non_promotable():
    payload = AUDIT.run_audit(n_worlds=2)
    assert len(payload["roots"]) == 3
    assert payload["exploration_only"] is True
    assert payload["strength_claim"] is False
    assert payload["whole_game_execution_authorized"] is False
    assert payload["production_promotion"] is False
    assert payload["production_deployment"] is False
    assert payload["direction_summary"].keys() == {
        "v1_pair_aware", "v2_opponent_pair_cap",
    }
    assert all(root["sampler_work"]["accepted_worlds"] == 2
               for root in payload["roots"])


def test_input_hash_and_exclusive_writer_refuse_drift(tmp_path):
    mutated = tmp_path / "dose.json"
    mutated.write_text(json.dumps({"rows": []}))
    with pytest.raises(AUDIT.AuditRefused, match="hash drift"):
        AUDIT.changed_rows(mutated)
    target = tmp_path / "audit.json"
    AUDIT.write_exclusive(target, {"schema": AUDIT.SCHEMA})
    with pytest.raises(AUDIT.AuditRefused, match="overwrite"):
        AUDIT.write_exclusive(target, {"schema": AUDIT.SCHEMA})


def test_frozen_changed_root_audit_is_hash_pinned_and_bounded():
    raw = FROZEN_AUDIT.read_bytes()
    assert AUDIT.sha256(FROZEN_AUDIT) == (
        "91a133e4eab14d25059c19e7c11cc4de8b7fb3614f3efa6882cf63345c9b0ad5")
    payload = json.loads(raw)
    internal = payload.pop("internal_sha256")
    assert AUDIT.stable_digest(payload) == internal == (
        "edfe1abe7b97764b26e8394e7f4620c2db6dbbc1796557318e966382a46358f8")
    assert payload["git"] == "dffe267c2c3fb69cd2ea34f227f75527c8704823"
    assert payload["tree_dirty"] is False
    assert payload["runtime"] == {
        "executable": (
            "/Users/jerryyu/.local/share/uv/python/"
            "cpython-3.14.6-macos-aarch64-none/bin/python3.14"),
        "hostname": "Jerrys-MacBook-Air.local",
        "python": "3.14.6",
    }
    assert payload["design"]["worlds_per_root"] == 4096
    assert payload["design"]["checkpoints"] == [512, 2048, 4096]
    assert "no population or whole-game inference" in payload["design"][
        "selection_warning"]
    assert payload["direction_summary"] == {
        policy: {
            "unresolved_roots": 0,
            "v1_action_positive_roots": 1,
            "v2_action_positive_roots": 2,
        }
        for policy in ("v1_pair_aware", "v2_opponent_pair_cap")
    }
    rows = {row["state_id"]: row for row in payload["roots"]}
    expected = {
        "447000002:5:2": (-3.233642578125, -3.233642578125),
        "447000005:2:1": (0.968017578125, 1.015625),
        "447000007:6:3": (4.700927734375, 4.7509765625),
    }
    assert set(rows) == set(expected)
    for state_id, means in expected.items():
        terminal = rows[state_id]["terminal"]
        assert terminal["worlds"] == 4096
        assert terminal["by_continuation"]["v1_pair_aware"][
            "signed_point_delta"]["mean"] == means[0]
        assert terminal["by_continuation"]["v2_opponent_pair_cap"][
            "signed_point_delta"]["mean"] == means[1]
    assert payload["exploration_only"] is True
    assert payload["strength_claim"] is False
    assert payload["whole_game_execution_authorized"] is False
    assert payload["production_promotion"] is False
    assert payload["production_deployment"] is False
