"""Tests for the bounded high-N audit of pair-cap-changed roots."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import pair_cap_rollout_root_audit as AUDIT  # noqa: E402


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
