"""Tests for the selected S6 report-world reliability diagnostic."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import s6_throw_reliability_audit as AUDIT  # noqa: E402


FROZEN_AUDIT = (
    Path(__file__).resolve().parent
    / "data/s6_throw_report_reliability_audit.v1.json"
)


def test_wilson_interval_is_bounded_and_refuses_bad_inputs():
    low, high = AUDIT.wilson_interval(0, 300)
    assert low == 0.0
    assert 0 < high < 0.02
    low, high = AUDIT.wilson_interval(300, 300)
    assert 0.98 < low < 1
    assert high == pytest.approx(1.0)
    with pytest.raises(AUDIT.ReliabilityRefused):
        AUDIT.wilson_interval(2, 1)


def test_loss_witness_override_replays_before_scoring():
    rnd, _bot, seat, attempted, decision = AUDIT._capture_override(
        AUDIT.REPLAY.WITNESS_SEED, AUDIT.REPLAY.WITNESS_FLIP)
    assert len(rnd.history) == 6
    assert seat == 3
    assert attempted == ["S4", "S4", "S6", "S6"]
    assert decision["report_fold"]["worlds"] == AUDIT.REPORT_WORLDS
    assert decision["report_fold"]["complete"] is True


def test_frozen_reliability_audit_is_hash_pinned_and_non_authorizing():
    raw = FROZEN_AUDIT.read_bytes()
    assert AUDIT.sha256(FROZEN_AUDIT) == (
        "fd1435b9adc216cc67176b221d3701efbeceed2b834cb1a8b8c85b6d523ac966")
    payload = json.loads(raw)
    internal = payload.pop("internal_sha256")
    assert AUDIT.PILOT.stable_digest(payload) == internal == (
        "3baabda1f0692a54df30c6dd2b01b32553b7e10a163f31277fbc74b5094fccd3")
    assert payload["git"] == "c2beaea6d510aeeecdb289169d3e528ebaac71bc"
    assert payload["design"] == {
        "candidate_contrast": "S6 attempted throw minus champion action",
        "candidate_safety_statistic": "complete throw survival per world",
        "report_worlds": 300,
        "same_exact_report_seed_and_sampler": True,
    }
    assert payload["summary"] == {
        "loss_witness_rejected": True,
        "report_world_failures": 276,
        "witnesses": 12,
        "zero_failure_gate_negative_utility": 0,
        "zero_failure_gate_neutral_utility": 10,
        "zero_failure_gate_positive_utility": 0,
        "zero_failure_gate_retained": 10,
    }
    rows = {(row["seed"], row["flip"]): row for row in payload["rows"]}
    assert set(rows) == set(AUDIT.REPLAY.OVERRIDE_WITNESSES)
    assert rows[(449_000_000_024, 1)]["report_throw_failures"] == 174
    assert rows[(449_000_000_024, 1)][
        "zero_report_failures_gate_accepts"] is False
    assert rows[(449_000_000_024, 1)]["signed_level_utility_delta"] == -2
    assert rows[(449_000_000_025, 0)]["report_throw_failures"] == 102
    assert rows[(449_000_000_025, 0)]["signed_level_utility_delta"] == 0
    assert sum(row["public_all_boss_gate_accepts"] for row in rows.values()) \
        == sum(row["zero_report_failures_gate_accepts"]
               for row in rows.values()) == 10
    assert payload["exploration_only"] is True
    assert payload["confirmatory_claim"] is False
    assert payload["strength_claim"] is False
    assert payload["whole_game_execution_authorized"] is False
    assert payload["production_promotion"] is False
    assert payload["production_deployment"] is False
