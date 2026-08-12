"""Falsification tests for the future-only, powered S4 successor design."""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import s4_point_banking_future_design as D  # noqa: E402


def test_default_design_is_fresh_alpha_bounded_and_powered():
    design = D.Design()
    assert D.design_problems(design) == []
    record = D.design_record(design)
    assert [look["clusters"] for look in record["looks"]] == [8_192, 16_384]
    assert sum(look["alpha"] for look in record["looks"]) == 0.05
    assert record["looks"][0]["power_at_replicated_effect"] > 0.92
    assert record["looks"][1]["power_at_replicated_effect"] > 0.998
    assert record["looks"][1]["power_at_plus_0_03"] > 0.84
    assert record["looks"][1]["projected_half_width"] < 0.02
    assert record["historical_outcomes_used_for_claim"] is False
    assert "treatment-minus-live-champion" in record["primary_efficacy"]
    assert record["look_1_transition"] == {
        "efficacy_pass_and_integrity_pass": "STOP_PASS",
        "efficacy_nonpass_and_integrity_pass": "CONTINUE_AUTOMATICALLY",
        "any_integrity_nonpass": "STOP_HOLD",
    }


def test_reducing_maximum_to_first_look_fails_small_effect_power_floor():
    design = replace(D.Design(), looks=(D.Design().looks[0],))
    assert "maximum is underpowered for +0.03 effect" in \
        D.design_problems(design)


def test_alpha_overspend_is_rejected():
    design = replace(D.Design(), looks=(
        D.Look(8_192, 0.03), D.Look(16_384, 0.03)))
    assert "alpha spending exceeds family budget" in D.design_problems(design)


def test_spent_replication_seed_interval_is_rejected():
    design = replace(D.Design(), seed0=180_000_000_000)
    assert any(problem.startswith("seed interval overlap")
               for problem in D.design_problems(design))


def test_preflight_and_primary_intervals_are_disjoint():
    preflight, primary = D.future_populations(D.Design())
    assert preflight.high < primary.low
    assert not D.overlap(preflight, primary)
    assert all(not D.overlap(primary, old) for old in D.EXCLUDED_POPULATIONS)


def test_historical_pooling_or_discretionary_continuation_is_rejected():
    pooled = replace(D.Design(), historical_outcomes_enter_estimator=True)
    discretionary = replace(
        D.Design(), automatic_continue_after_clean_efficacy_nonpass=False)
    assert "historical S4 outcomes enter the future estimator" in \
        D.design_problems(pooled)
    assert "post-look continuation is discretionary" in \
        D.design_problems(discretionary)


def test_nonintegral_sentinel_geometry_is_rejected():
    design = replace(D.Design(), sentinel_modulus=7)
    assert "null-sentinel geometry drift" in D.design_problems(design)


def test_invalid_design_cannot_publish_a_record():
    design = replace(D.Design(), futility_stop=True)
    with pytest.raises(ValueError, match="post-look continuation"):
        D.design_record(design)
